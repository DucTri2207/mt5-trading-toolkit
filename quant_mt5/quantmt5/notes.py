"""analysis_note (brainstorm output) and journal — append-only, validated against the snapshot/context.

Baseline eligibility comes from the engine, never from the agent. If the agent action differs from baseline,
deviation_reason is mandatory so the paired effect of discretionary advice can be measured later.
"""
from __future__ import annotations

from typing import Any

from .context import build_context, find_candidate
from .snapshot import load_snapshot
from .util import STORE_DIR, iso_utc, now_utc, parse_utc, read_jsonl, append_jsonl, file_lock, stable_id

NOTES_PATH = STORE_DIR / "journal" / "analysis_notes.jsonl"
JOURNAL_PATH = STORE_DIR / "journal" / "journal.jsonl"
ACTIONS = ("CONSIDER_ENTRY", "WAIT", "SKIP")
REQUIRED = ("author", "snapshot_id", "candidate_id", "branch", "as_of", "features_used", "observations", "preferred_scenario",
            "alternative_scenario", "change_mind_conditions", "missing_data", "agent_action", "next_check")


class NoteError(ValueError):
    pass


def _deadline_ts(cand: dict) -> float | None:
    if cand.get("entry_deadline_ts") is not None:
        return float(cand["entry_deadline_ts"])
    d = (cand.get("plan") or {}).get("deadline_at") or cand.get("entry_deadline_at")
    return parse_utc(d) if d else None


def _baseline(cand: dict, branch: str, as_of: float | None = None) -> str:
    """Engine baseline for `branch`. With `as_of` (the note's analysis time) only facts known at that time count:
    gate, readiness, the entry deadline (EXPIRED is not ELIGIBLE) and a plan block only once it was decided.
    Without `as_of`: the snapshot-time view (legacy)."""
    g = cand["branch_eligibility"].get(branch)
    if g is None:
        raise NoteError(f"BRANCH_NOT_APPLICABLE:{branch}")
    if g != "PASS":
        return f"NOT_ELIGIBLE_GATE_{g}"
    plan = cand.get("plan") or {}
    st = plan.get("state")
    if as_of is None:
        if st == "BLOCKED":
            return f"NOT_ELIGIBLE_BLOCKED_{plan.get('reason')}"
        if st == "EXPIRED":
            return "NOT_ELIGIBLE_EXPIRED"
        return "ELIGIBLE"
    if as_of < float(cand["ready_ts"]):
        return "NOT_YET_READY"
    deadline = _deadline_ts(cand)
    if deadline is None:
        return "UNKNOWN_DEADLINE"
    if st == "BLOCKED":
        dec = plan.get("decided_at")
        if dec is not None and parse_utc(dec) <= as_of:
            return f"NOT_ELIGIBLE_BLOCKED_{plan.get('reason')}"
        if dec is None and as_of < deadline:
            # Legacy snapshot: the block's decision time was not recorded, so it cannot be certified as known at
            # as_of inside the entry window (never substitute the snapshot time). After the deadline the window is
            # closed either way, which IS known.
            return "UNKNOWN_BLOCK_DECISION_TIME"
    if as_of >= deadline:
        return "NOT_ELIGIBLE_EXPIRED"
    return "ELIGIBLE"


def validate_note(note: dict) -> dict:
    miss = [k for k in REQUIRED if k not in note or note[k] in (None, "", [])]
    if "missing_data" in miss and isinstance(note.get("missing_data"), list):
        miss.remove("missing_data")  # an empty list is a valid explicit statement
    if miss:
        raise NoteError(f"NOTE_FIELDS_MISSING:{','.join(miss)}")
    if note["agent_action"] not in ACTIONS:
        raise NoteError(f"AGENT_ACTION_INVALID:{note['agent_action']}")
    snap = load_snapshot(note["snapshot_id"])
    cand = find_candidate(snap, note["candidate_id"])
    as_of = parse_utc(note["as_of"])
    if as_of > parse_utc(snap["as_of_utc"]):
        raise NoteError("NOTE_AS_OF_AFTER_SNAPSHOT")
    if as_of < cand["ready_ts"]:
        raise NoteError("NOTE_AS_OF_BEFORE_CANDIDATE_READY")
    groups = sorted({g for f in note["features_used"] for g in [f.get("group")] if g})
    ctx = build_context(note["snapshot_id"], note["candidate_id"], groups=groups, at="decision")
    index = {(f["name"], f.get("tf")): f for f in ctx["features"]}
    checked = []
    for f in note["features_used"]:
        key = (f.get("name"), f.get("tf"))
        src = index.get(key)
        if src is None:
            raise NoteError(f"FEATURE_NOT_IN_CONTEXT:{key}")
        if src.get("available_at") and parse_utc(src["available_at"]) > as_of:
            raise NoteError(f"FEATURE_NOT_AVAILABLE_AT_AS_OF:{key}")
        if "value" in f and f["value"] != src.get("value"):
            raise NoteError(f"FEATURE_VALUE_MISMATCH:{key}: note={f['value']} engine={src.get('value')}")
        checked.append({"name": key[0], "tf": key[1], "value": src.get("value"), "quality": src.get("quality"),
                        "available_at": src.get("available_at")})
    baseline = _baseline(cand, note["branch"], as_of)
    if baseline.startswith("UNKNOWN"):
        differs = None                    # deviation not measurable against an unknown baseline (kept reason-coded)
    else:
        differs = (baseline == "ELIGIBLE") != (note["agent_action"] == "CONSIDER_ENTRY")
    if differs and not note.get("deviation_reason"):
        raise NoteError("DEVIATION_REASON_REQUIRED: agent_action differs from baseline eligibility")
    out = dict(note)
    out.update({"baseline_eligibility": baseline, "baseline_evaluated_at": iso_utc(as_of), "differs_from_baseline": differs,
                "features_verified": checked,
                "symbol": cand["symbol"], "setup": cand["setup"], "side": cand["side"],
                "evidence_limits": note.get("evidence_limits") or "machine-checked: detector/gates/plan; agent: qualitative scenarios (unvalidated)"})
    return out


CREATED_AT_FUTURE_TOLERANCE_S = 300


def add_note(note: dict, path=None) -> dict:
    path = path or NOTES_PATH
    rec = validate_note(note)
    now = now_utc()
    rec["created_at"] = rec.get("created_at") or iso_utc(now)
    created = parse_utc(rec["created_at"])
    if created < parse_utc(rec["as_of"]):
        raise NoteError("NOTE_CREATED_AT_BEFORE_AS_OF: a note cannot be written before the information it cites")
    if created > now + CREATED_AT_FUTURE_TOLERANCE_S:
        raise NoteError("NOTE_CREATED_AT_IN_FUTURE")
    rec["recorded_at"] = iso_utc(now)          # system time the note entered the store (card/replay cut-off uses this)
    rec["note_id"] = stable_id("NOTE", rec["author"], rec["snapshot_id"], rec["candidate_id"], rec["branch"], rec["created_at"])
    with file_lock(path):                      # check + append atomically across processes (idempotent restart)
        existing = {n["note_id"]: n for n in read_jsonl(path)}
        if rec["note_id"] in existing:
            raise NoteError("NOTE_ALREADY_RECORDED")
        if rec.get("supersedes"):
            old = existing.get(rec["supersedes"])
            if old is None:
                raise NoteError("SUPERSEDES_UNKNOWN_NOTE")
            if (old["snapshot_id"], old["candidate_id"], old["branch"]) != (rec["snapshot_id"], rec["candidate_id"], rec["branch"]):
                raise NoteError("SUPERSEDES_OTHER_CANDIDATE_OR_SNAPSHOT")
            if parse_utc(old["created_at"]) > created:
                raise NoteError("SUPERSEDES_LATER_NOTE")
        append_jsonl(path, rec, lock=False)
    return rec


def note_effective_at(n: dict) -> float:
    """When a note became visible: system recorded_at (legacy notes without it: created_at)."""
    return parse_utc(n.get("recorded_at") or n["created_at"])


def list_notes(candidate_id: str | None = None, path=None) -> list[dict]:
    notes = read_jsonl(path or NOTES_PATH)
    return [n for n in notes if candidate_id is None or n["candidate_id"] == candidate_id]


def add_journal(kind: str, text: str, *, candidate_id: str | None = None, snapshot_id: str | None = None,
                author: str = "unknown", event_at: str | None = None, path=None) -> dict:
    if kind not in ("observation", "decision", "outcome", "paper_signal", "user_action"):
        raise NoteError(f"JOURNAL_KIND_INVALID:{kind}")
    rec = {"kind": kind, "text": text, "candidate_id": candidate_id, "snapshot_id": snapshot_id, "author": author,
           "event_at": event_at, "recorded_at": iso_utc(now_utc()),
           "note": "journal entries are observations; they never send or imply broker orders"}
    rec["journal_id"] = stable_id("JRN", rec)
    append_jsonl(path or JOURNAL_PATH, rec)
    return rec
