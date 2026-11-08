"""Independent A-retention witnesses: real detector + renderer, never live MT5."""
import copy
import json
from pathlib import Path

import pytest

from quantmt5 import reporting
from quantmt5.detectors import detect_A
from quantmt5.util import canonical_json, iso_utc, parse_utc
from synth import symbol_data
from test_detectors import _setup_a_rows


ASOF = "2025-01-07T01:00:01Z"


def _snapshot(n=12, include_b=False):
    candidates = []
    for i in range(n):
        state = ("PASS", "FAIL", "UNKNOWN")[i % 3]
        candidates.append({"candidate_id": f"A_{i:02d}", "revision_id": f"REV_A_{i:02d}",
            "episode_id": f"EP_{i:02d}", "symbol": "XAUUSD", "setup": "A",
            "side": "LONG" if i % 2 == 0 else "SHORT", "ready_at": ASOF,
            "signal_bar": {"close_at": ASOF}, "entry_deadline_at": "2025-01-07T01:01:30Z",
            "branch_eligibility": {"M0": state, "M1": "UNKNOWN", "M2": "PASS"},
            "gates": {"M0": {"result": state, "reason": "FIXTURE"}},
            "plan_window": {"M0": "ENTRY_WINDOW" if state == "PASS" else state, "M2": "EXPIRED"},
            "plan": {"state": "READY", "entry": 100.0+i, "sl": 99.0+i, "tp": 101.5+i}})
    if include_b:
        candidates.append(dict(copy.deepcopy(candidates[0]), candidate_id="B_00", revision_id="REV_B_00", setup="B"))
    return {"snapshot_id": "SNAP_TEST", "as_of_utc": ASOF, "universe": ["XAUUSD"],
            "candidates": candidates, "episodes": [], "errors": [],
            "symbols": {"XAUUSD": {"status": "OK", "market_state": "FRESH", "economics": {"status": "ASSUMED"}}}}


def _by_id(candidates):
    return {c["candidate_id"]: c for c in candidates}


def test_t01_real_detector_catalog_not_mutated_by_annotation():
    sd = symbol_data(_setup_a_rows())
    episodes, candidates = detect_A(sd)
    snapshot = _snapshot(0)
    snapshot.update(episodes=episodes, candidates=candidates)
    before = canonical_json(snapshot)
    result = reporting.build_baseline_packet(snapshot, computed_at=parse_utc(ASOF))
    assert canonical_json(snapshot) == before
    assert _by_id(result["candidates"]) == _by_id(candidates)
    again_episodes, again_candidates = detect_A(sd)
    assert canonical_json([episodes, candidates]) == canonical_json([again_episodes, again_candidates])


def test_t02_real_r1_r2_h1_confirmation_and_warmup_preserved():
    _, candidates = detect_A(symbol_data(_setup_a_rows()))
    selected = [c for c in candidates if c["side"] == "LONG" and c["signal_bar"]["open_at"].endswith(("00:15:00Z", "01:00:00Z"))]
    assert len(selected) == 2
    snapshot = _snapshot(0)
    snapshot["candidates"] = selected
    result = _by_id(reporting.build_baseline_packet(snapshot)["candidates"])
    for index, source in enumerate(selected):
        candidate = result[source["candidate_id"]]
        assert candidate["gates"]["M0"]["result"] == "PASS"
        assert candidate["gates"]["M2"]["result"] == ("FAIL", "PASS")[index]
        assert candidate["gates"]["M1"]["result"] == "UNKNOWN"
        assert candidate["gates"]["M1"]["reason"] == "EMA50_WARMUP"
        assert candidate == source


def test_t01_baseline_packet_deepcopy_and_no_optional_calls(monkeypatch):
    from quantmt5 import context, paper
    def forbidden(*args, **kwargs):
        pytest.fail("baseline must return without optional context/Fabio/card")
    monkeypatch.setattr(context, "build_market_context", forbidden)
    monkeypatch.setattr(context, "opportunity_card", forbidden)
    monkeypatch.setattr(paper, "_run_fabio_for_snapshot", forbidden)
    snap = _snapshot(include_b=True)
    original = copy.deepcopy(snap)
    packet = reporting.build_baseline_packet(snap, computed_at=parse_utc(ASOF))
    assert packet["stage"] == "BASELINE" and packet["context_state"] == "PENDING"
    assert packet["news_handling"] == "USER_MANAGED" and packet["news_checked_by_system"] is False
    assert packet["market"] == {} and packet["cards"] == {}
    assert _by_id(packet["candidates"]) == _by_id(snap["candidates"])
    assert {c["candidate_id"] for c in packet["deferred_cards"]} == set(_by_id(snap["candidates"]))
    packet["candidates"][0]["plan"]["entry"] = -123
    assert snap == original


@pytest.mark.parametrize("max_cards", [0, 3, 8])
def test_t03_every_candidate_in_json_and_markdown_even_when_cards_capped(tmp_path, monkeypatch, max_cards):
    from quantmt5 import session
    snap = _snapshot(include_b=True)
    original = canonical_json(snap)
    d = session.sdir(tmp_path, "test")
    (d / "data" / "store" / "snapshots").mkdir(parents=True)
    state = {"session_name": "test", "ftmo": {"program": "1-Step", "environment": "MT5_DEMO",
        "rule_regime": "UNKNOWN", "initial_capital": "UNCONFIGURED", "challenge_evaluation": "UNCONFIGURED"}, "risk": "UNCONFIGURED"}
    (d / "session.json").write_text(json.dumps(state), encoding="utf-8")
    (d / "data" / "store" / "snapshots" / "SNAP_TEST.json").write_text(json.dumps(snap), encoding="utf-8")
    def forbidden(*args, **kwargs):
        pytest.fail("PENDING baseline report must not spawn fallback analysis")
    monkeypatch.setattr(session, "exec_in_bundle", forbidden)
    record = {"status": "OK", "cycle_id": "CYCLE_TEST", "snapshot_id": "SNAP_TEST",
              "planned_end_utc": ASOF, "symbols": snap["symbols"], "analysis_mode": "baseline",
              "context_state": "PENDING", "analysis": reporting.build_baseline_packet(snap)}
    paths = session.build_report(tmp_path, "test", record, max_cards=max_cards)
    report = json.loads(Path(paths["report_json"]).read_text(encoding="utf-8"))
    markdown = Path(paths["report_md"]).read_text(encoding="utf-8")
    assert {c["candidate_id"] for c in report["candidates"]} == set(_by_id(snap["candidates"]))
    assert all(c["candidate_id"] in markdown for c in snap["candidates"])
    assert "Không có setup" not in markdown
    assert "USER_MANAGED" in markdown
    assert canonical_json(snap) == original


@pytest.mark.parametrize("fabio_status", ["WAIT", "SKIP", "DATA_UNAVAILABLE"])
def test_t04_t05_optional_opposition_never_rewrites_a(monkeypatch, fabio_status):
    from quantmt5 import context
    snap = _snapshot()
    original = canonical_json(snap)
    monkeypatch.setattr(context, "check_snapshot_config", lambda snap: None)
    monkeypatch.setattr(context, "build_market_context", lambda *a, **kw: {"features": [], "quality_flags": ["MISSING"]})
    monkeypatch.setattr(context, "opportunity_card", lambda *a, **kw: {"status": "OK", "context": []})
    result = reporting.analyze_snapshot(snap, max_cards=0,
        fabio={"XAUUSD": {"status": "OK", "decision": fabio_status, "cvd": {"is_proxy": True, "status": "MISSING"}}})
    assert canonical_json(snap) == original
    represented = set(result["cards"]) | {c["candidate_id"] for c in result["deferred_cards"]}
    assert represented == set(_by_id(snap["candidates"]))
    assert _by_id(result["candidates"]) == _by_id(snap["candidates"])


def test_t06_context_cannot_make_expired_or_missing_costs_actionable():
    snap = _snapshot(1)
    candidate = snap["candidates"][0]
    assert not reporting.current_window(candidate, snap, parse_utc("2025-01-08T01:00:00Z"))["actionable_now"]
    snap["symbols"]["XAUUSD"]["economics"] = {"status": "UNKNOWN"}
    result = reporting.current_window(candidate, snap, parse_utc(ASOF) + 1)
    assert not result["actionable_now"] and not result["entry_window_at_computation"]


def test_t08_no_candidate_packet_does_not_invent_plan():
    snap = _snapshot(0)
    result = reporting.build_baseline_packet(snap)
    assert result["candidates"] == [] and result["cards"] == {} and result["watch_zones"] == []


def test_t10_annotation_preserves_hand_computable_execution():
    from quantmt5.execution import simulate
    from test_b3 import P, S, cand, tq
    candidate = cand(setup="A")
    quotes = tq([(S + 3, 100.0, 100.02, S + 20), (S + 7, 100.01, 100.03)])
    before = simulate(candidate, quotes, P())
    snap = _snapshot(0)
    snap["candidates"] = [candidate]
    annotated = reporting.build_baseline_packet(snap)["candidates"][0]
    after = simulate(annotated, quotes, P())
    assert canonical_json(before) == canonical_json(after)
    assert after["status"] == "FILLED" and after["entry"] == pytest.approx(100.03)
    assert after["fill_at"] == iso_utc(S + 7)
