"""B5 acceptance tests: opportunity card, freeze immutability, runbook validation,
and brainstorm note validation rules.
"""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

import pytest

from quantmt5.util import parse_utc

AS_OF = "2026-10-22T16:00:00Z"   # a Thursday inside the cached history


@pytest.fixture(scope="module", autouse=True)
def _isolated_notes_file():
    """Harness isolation (recheck 2026-11-04): notes added here used to land in the session-wide store file and
    made test_snapshot_notes::test_note_validation_rules see 5 extra notes for the same candidate."""
    import quantmt5.notes as notes
    from quantmt5.util import STORE_DIR
    mp = pytest.MonkeyPatch()
    mp.setattr(notes, "NOTES_PATH", STORE_DIR / "journal" / "analysis_notes_test_agy_003.jsonl")
    yield
    mp.undo()


@pytest.fixture(scope="module")
def snap():
    from quantmt5.snapshot import make_snapshot
    return make_snapshot(parse_utc(AS_OF), ["XAUUSD", "EURUSD", "USDJPY"])


def _pick(snap, setup=None):
    xs = [c for c in snap["candidates"] if c["symbol"] == "XAUUSD" and (setup is None or c["setup"] == setup)]
    assert xs, "fixture as_of must contain XAUUSD candidates in the 24h lookback"
    return xs[-1]


def _note(snap, c, **kw):
    from quantmt5.context import build_context
    from quantmt5.notes import _baseline
    ctx = build_context(snap["snapshot_id"], c["candidate_id"])
    atr = [f for f in ctx["features"] if f["name"] == "atr14_wilder" and f["tf"] == "M5"][0]
    rv = [f for f in ctx["features"] if f["name"] == "rvol20_tick"][0]
    branch = "M0" if c["setup"] == "A" else "P0"
    base = _baseline(c, branch, parse_utc(kw.get("as_of", c["ready_at"])))  # baseline at note.as_of (codex_033 H1)
    action = "CONSIDER_ENTRY" if base == "ELIGIBLE" else "SKIP"
    n = {
        "author": "test-agent",
        "snapshot_id": snap["snapshot_id"],
        "candidate_id": c["candidate_id"],
        "branch": branch,
        "as_of": c["ready_at"],
        "features_used": [
            {"name": "atr14_wilder", "tf": "M5", "value": atr["value"]},
            {"name": "rvol20_tick", "tf": "M5"},
        ],
        "observations": "obs",
        "preferred_scenario": "scen_a",
        "alternative_scenario": "scen_b",
        "change_mind_conditions": ["condition 1"],
        "missing_data": ["news calendar"],
        "agent_action": action,
        "deviation_reason": "",
        "next_check": "next M5 close",
        "created_at": "2026-11-03T08:00:00Z",
    }
    n.update(kw)
    return n


def test_card_has_all_sections_and_same_snapshot_is_identical(snap):
    from quantmt5.cli import cmd_card
    from quantmt5.context import opportunity_card
    from quantmt5.util import canonical_json

    c = _pick(snap)
    card1 = opportunity_card(snap["snapshot_id"], c["candidate_id"])
    card2 = opportunity_card(snap["snapshot_id"], c["candidate_id"])

    required_sections = {"identity", "why", "baseline", "context", "brainstorm_notes", "evidence", "status"}
    assert required_sections.issubset(card1.keys())
    assert card1["status"] == "OK"
    assert canonical_json(card1) == canonical_json(card2)

    env1 = cmd_card(argparse.Namespace(snapshot=snap["snapshot_id"], candidate=c["candidate_id"]))
    env2 = cmd_card(argparse.Namespace(snapshot=snap["snapshot_id"], candidate=c["candidate_id"]))
    assert env1["status"] == "OK"
    assert required_sections.issubset(set(env1["data"].keys()) | {"status"})
    assert env1["data"] == env2["data"]


def test_card_unknown_candidate_is_error(snap):
    from quantmt5.cli import cmd_card
    from quantmt5.context import opportunity_card

    with pytest.raises(KeyError, match="CANDIDATE_NOT_FOUND"):
        opportunity_card(snap["snapshot_id"], "CANDIDATE_NONEXISTENT_XYZ")

    env = cmd_card(argparse.Namespace(snapshot=snap["snapshot_id"], candidate="CANDIDATE_NONEXISTENT_XYZ"))
    assert env["status"] == "ERROR"
    reasons = [e.get("reason") for e in env.get("errors", [])]
    assert any("CANDIDATE_NOT_FOUND" in r for r in reasons)


def test_card_includes_notes_after_note_add(snap):
    from quantmt5.context import opportunity_card
    from quantmt5.notes import add_note

    c = _pick(snap)
    note_data = _note(snap, c, author="agent_test_3", created_at="2026-11-03T11:00:00Z")
    rec = add_note(note_data)

    card_after = opportunity_card(snap["snapshot_id"], c["candidate_id"])
    assert any(n.get("note_id") == rec["note_id"] for n in card_after["brainstorm_notes"])


def test_freeze_is_immutable_and_idempotent(monkeypatch):
    import quantmt5.cli as cli
    import quantmt5.config as config
    from quantmt5.util import sha256_file

    f1 = cli.make_freeze(label="first_freeze")
    fid1 = f1["freeze_id"]
    p1 = Path(f1["path"])
    assert p1.exists()
    sha1 = sha256_file(p1)

    f2 = cli.make_freeze(label="second_freeze")
    assert f2["freeze_id"] == fid1
    assert f2.get("already_frozen") is True
    assert sha256_file(p1) == sha1

    monkeypatch.setattr(config, "config_hash", lambda: "config_hash_modified_99999")
    monkeypatch.setattr(cli, "config_hash", lambda: "config_hash_modified_99999")

    f3 = cli.make_freeze(label="third_freeze")
    fid3 = f3["freeze_id"]
    p3 = Path(f3["path"])
    assert fid3 != fid1
    assert p3.exists()
    assert sha256_file(p1) == sha1

    env_show = cli.cmd_freeze(argparse.Namespace(show=fid1, label=""))
    assert env_show["status"] == "OK"
    assert env_show["data"]["freeze_id"] == fid1


def test_note_as_of_after_snapshot_rejected(snap):
    from quantmt5.notes import NoteError, add_note

    c = _pick(snap)
    note = _note(snap, c, as_of="2026-10-22T17:00:00Z", created_at="2026-11-03T12:00:00Z")
    with pytest.raises(NoteError, match="NOTE_AS_OF_AFTER_SNAPSHOT"):
        add_note(note)


def test_note_feature_not_available_rejected(snap, monkeypatch):
    import quantmt5.notes as notes
    from quantmt5.notes import NoteError, add_note

    c = _pick(snap)
    note = _note(snap, c, created_at="2026-11-03T13:00:00Z")

    orig_build_context = notes.build_context

    def fake_build_context(snapshot_id, candidate_id, groups=None, at="decision"):
        ctx = orig_build_context(snapshot_id, candidate_id, groups=groups, at=at)
        for f in ctx["features"]:
            if f["name"] == "atr14_wilder":
                f["available_at"] = "2026-10-22T17:00:00Z"
        return ctx

    monkeypatch.setattr(notes, "build_context", fake_build_context)
    with pytest.raises(NoteError, match="FEATURE_NOT_AVAILABLE_AT_AS_OF"):
        add_note(note)


def test_note_empty_missing_data_list_is_valid(snap):
    from quantmt5.notes import add_note

    c = _pick(snap)
    note = _note(snap, c, missing_data=[], created_at="2026-11-03T14:00:00Z")
    rec = add_note(note)
    assert rec["missing_data"] == []


def test_note_supersedes_unknown_rejected_and_known_accepted(snap):
    from quantmt5.notes import NoteError, add_note, list_notes

    c = _pick(snap)
    bad = _note(snap, c, supersedes="NOTE_UNKNOWN_ID_9999", created_at="2026-11-03T15:00:00Z")
    with pytest.raises(NoteError, match="SUPERSEDES_UNKNOWN_NOTE"):
        add_note(bad)

    n1 = add_note(_note(snap, c, created_at="2026-11-03T15:05:00Z"))
    n2 = add_note(_note(snap, c, supersedes=n1["note_id"], observations="updated", created_at="2026-11-03T15:10:00Z"))

    notes = list_notes(c["candidate_id"])
    ids = [n["note_id"] for n in notes]
    assert n1["note_id"] in ids
    assert n2["note_id"] in ids


def test_journal_rejects_unknown_kind_and_never_implies_orders():
    from quantmt5.notes import NoteError, add_journal

    with pytest.raises(NoteError, match="JOURNAL_KIND_INVALID"):
        add_journal("order_send", "buy EURUSD")

    rec = add_journal("observation", "Ghi chu quan sat thi truong")
    assert "never send or imply broker orders" in rec["note"]


def test_runbook_commands_exist_in_parser():
    from quantmt5.cli import build_parser
    from quantmt5.util import PROJECT_DIR

    runbook_path = PROJECT_DIR / "RUNBOOK.md"
    assert runbook_path.exists(), "RUNBOOK.md must exist in quant_mt5"
    content = runbook_path.read_text(encoding="utf-8")

    parser = build_parser()
    sp = [a for a in parser._actions if isinstance(a, argparse._SubParsersAction)][0]
    valid_subcmds = set(sp.choices.keys())

    matches = re.findall(r"quant\.cmd\s+([a-zA-Z0-9_-]+)", content)
    assert len(matches) > 0, "RUNBOOK.md must contain quant.cmd commands"
    for cmd_name in matches:
        assert cmd_name in valid_subcmds, f"Command '{cmd_name}' from RUNBOOK not found in parser subparsers"
