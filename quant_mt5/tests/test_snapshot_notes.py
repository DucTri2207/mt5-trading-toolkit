"""Acceptance: snapshot immutability/ID stability, scan statuses (OK/OK_EMPTY/PARTIAL/ERROR), stale vs closed,
historical exposure label, context provenance & causality, brainstorm note validation, journal append-only, CLI envelope."""
import json

import pytest

from quantmt5.util import parse_utc

AS_OF = "2026-10-22T16:00:00Z"   # a Thursday inside the cached history


@pytest.fixture(scope="module")
def snap():
    from quantmt5.snapshot import make_snapshot
    return make_snapshot(parse_utc(AS_OF), ["XAUUSD", "EURUSD", "USDJPY"])


def test_snapshot_immutable_and_same_id(snap):
    from quantmt5.snapshot import make_snapshot, snapshot_path
    again = make_snapshot(parse_utc(AS_OF), ["USDJPY", "EURUSD", "XAUUSD"])  # order-insensitive universe
    assert again["snapshot_id"] == snap["snapshot_id"]
    assert snapshot_path(snap["snapshot_id"]).exists()
    on_disk = json.loads(snapshot_path(snap["snapshot_id"]).read_text(encoding="utf-8"))
    assert on_disk["as_of_utc"] == "2026-10-22T16:00:00Z"


def test_snapshot_is_causal_and_labelled(snap):
    as_of = parse_utc(AS_OF)
    for c in snap["candidates"]:
        assert c["ready_ts"] <= as_of
        if c["plan"]["state"] == "FILLED_SIMULATED":
            assert parse_utc(c["plan"]["fill_at"]) <= as_of
    for s, v in snap["symbols"].items():
        assert "HISTORICAL_AS_OF" in v["quality_flags"] and v["exposure"].startswith("HISTORICAL_EXPOSED")
        assert v["watermark_m5_close_at"] <= AS_OF
    assert "HISTORY_INSUFFICIENT:M1_MISSING" in snap["symbols"]["EURUSD"]["quality_flags"]


def test_scan_statuses(snap):
    from quantmt5.snapshot import make_snapshot, scan
    assert scan(snap)["status"] in ("OK", "OK_EMPTY")
    bad = make_snapshot(parse_utc(AS_OF), ["XAUUSD", "NOPE"], write=False)
    assert scan(bad)["status"] == "PARTIAL"
    allbad = make_snapshot(parse_utc(AS_OF), ["NOPE"], write=False)
    assert scan(allbad)["status"] == "ERROR"
    # weekend: market closed is not "no setup" and not "stale"
    wk = make_snapshot(parse_utc("2026-10-18T12:00:00Z"), ["XAUUSD"], write=False)
    assert wk["symbols"]["XAUUSD"]["market_state"] == "MARKET_CLOSED_OR_BREAK"


def _pick(snap, setup=None):
    xs = [c for c in snap["candidates"] if c["symbol"] == "XAUUSD" and (setup is None or c["setup"] == setup)]
    assert xs, "fixture as_of must contain XAUUSD candidates in the 24h lookback"
    return xs[-1]


def test_context_provenance_and_causality(snap):
    from quantmt5.context import build_context
    c = _pick(snap)
    ctx = build_context(snap["snapshot_id"], c["candidate_id"], ["ema", "adx", "rsi", "er", "atr_pct"])
    assert ctx["causality_check"]["ok"]
    names = {f["name"] for f in ctx["features"]}
    assert {"atr14_wilder", "rvol20_tick", "rvol_same_slot_tick", "real_volume", "news_calendar", "h1_adx14_wilder"} <= names
    for f in ctx["features"]:
        assert "quality" in f
        if f["quality"] == "OK" and "available_at_ts" in f:
            assert f["available_at_ts"] <= c["ready_ts"] and f["unit"] and f["window"] and f["source"]["dataset_id"]
    rv = [f for f in ctx["features"] if f["name"] == "real_volume"][0]
    assert rv["value"] is None and rv["quality"] == "UNKNOWN"
    slot = [f for f in ctx["features"] if f["name"] == "rvol_same_slot_tick"][0]
    assert slot["volume_basis"] == "tick" and "sample_count" in slot


def test_two_agents_get_identical_context(snap):
    from quantmt5.context import build_context
    c = _pick(snap)
    a = build_context(snap["snapshot_id"], c["candidate_id"], ["ema"])
    b = build_context(snap["snapshot_id"], c["candidate_id"], ["ema"])
    from quantmt5.util import canonical_json
    assert canonical_json(a) == canonical_json(b)


def _note(snap, c, **kw):
    from quantmt5.context import build_context
    ctx = build_context(snap["snapshot_id"], c["candidate_id"])
    atr = [f for f in ctx["features"] if f["name"] == "atr14_wilder" and f["tf"] == "M5"][0]
    rv = [f for f in ctx["features"] if f["name"] == "rvol20_tick"][0]
    n = {"author": "test-agent", "snapshot_id": snap["snapshot_id"], "candidate_id": c["candidate_id"],
         "branch": "M0" if c["setup"] == "A" else "P0", "as_of": c["ready_at"],
         "features_used": [{"name": "atr14_wilder", "tf": "M5", "value": atr["value"]}, {"name": "rvol20_tick", "tf": "M5"}],
         "observations": "x", "preferred_scenario": "y", "alternative_scenario": "z", "change_mind_conditions": ["close back through level"],
         "missing_data": ["news calendar"], "agent_action": "CONSIDER_ENTRY", "next_check": "next M5 close",
         "created_at": "2026-11-03T08:00:00Z"}
    n.update(kw)
    return n


def test_note_validation_rules(snap):
    from quantmt5.notes import NoteError, add_note, validate_note, _baseline
    c = _pick(snap)
    from quantmt5.util import parse_utc
    base = _baseline(c, "M0" if c["setup"] == "A" else "P0", parse_utc(c["ready_at"]))  # baseline at note.as_of (codex_033 H1)
    other = "SKIP" if base == "ELIGIBLE" else "CONSIDER_ENTRY"
    with pytest.raises(NoteError, match="DEVIATION_REASON_REQUIRED"):
        validate_note(_note(snap, c, agent_action=other))
    ok = validate_note(_note(snap, c, agent_action=other, deviation_reason="spread too wide vs R"))
    assert ok["differs_from_baseline"] is True and ok["baseline_eligibility"] == base
    with pytest.raises(NoteError, match="FEATURE_NOT_IN_CONTEXT"):
        validate_note(_note(snap, c, features_used=[{"name": "vwap_true", "tf": "M5"}]))
    with pytest.raises(NoteError, match="FEATURE_VALUE_MISMATCH"):
        validate_note(_note(snap, c, features_used=[{"name": "atr14_wilder", "tf": "M5", "value": 123.0}]))
    with pytest.raises(NoteError, match="NOTE_AS_OF_BEFORE_CANDIDATE_READY"):
        validate_note(_note(snap, c, as_of="2020-01-01T00:00:00Z"))
    with pytest.raises(NoteError, match="NOTE_FIELDS_MISSING"):
        validate_note(_note(snap, c, change_mind_conditions=[]))
    with pytest.raises(NoteError, match="AGENT_ACTION_INVALID"):
        validate_note(_note(snap, c, agent_action="BUY_NOW"))
    rec = add_note(_note(snap, c, agent_action=other, deviation_reason="test"))
    with pytest.raises(NoteError, match="NOTE_ALREADY_RECORDED"):
        add_note(_note(snap, c, agent_action=other, deviation_reason="test"))
    from quantmt5.notes import list_notes
    assert [n["note_id"] for n in list_notes(c["candidate_id"])] == [rec["note_id"]]


def test_cli_envelope_and_error_codes(snap, capsys):
    from quantmt5.cli import main
    rc = main(["scan", "--snapshot", snap["snapshot_id"]])
    env = json.loads(capsys.readouterr().out)
    assert rc == 0 and set(env) >= {"status", "schema_version", "request_id", "snapshot_id", "as_of", "data", "quality", "errors"}
    rc = main(["scan", "--snapshot", "SNAP_does_not_exist"])
    env = json.loads(capsys.readouterr().out)
    assert rc == 2 and env["status"] == "ERROR" and "SNAPSHOT_NOT_FOUND" in env["errors"][0]["reason"]
    rc = main(["evaluate", "--experiment", "EXP_missing"])
    env = json.loads(capsys.readouterr().out)
    assert env["status"] == "ERROR" and env["errors"][0]["reason"] == "EXPERIMENT_NOT_REGISTERED"


def test_journal_append_only(tmp_path):
    from quantmt5.notes import NoteError, add_journal
    from quantmt5.util import read_jsonl
    p = tmp_path / "j.jsonl"
    add_journal("observation", "a", path=p)
    add_journal("user_action", "moved SL manually", path=p)
    assert [r["kind"] for r in read_jsonl(p)] == ["observation", "user_action"]
    with pytest.raises(NoteError):
        add_journal("order", "x", path=p)
