import json
from pathlib import Path

import pytest

from quantmt5.reporting import candidate_priority, current_window, watch_zones
from quantmt5.util import parse_utc


def test_archive_window_is_never_present_actionable():
    c = {"symbol": "EURUSD", "ready_at": "2026-11-02T12:00:00Z", "entry_deadline_at": "2026-11-02T12:01:30Z",
         "plan_window": {"M0": "ENTRY_WINDOW"}}
    snap = {"as_of_utc": c["ready_at"], "symbols": {"EURUSD": {"market_state": "FRESH", "economics": {"status": "ASSUMED"}}}}
    old = current_window(c, snap, parse_utc("2026-11-08T12:00:00Z"))
    assert old["valid_at_as_of"] and not old["entry_window_at_computation"]
    assert old["current_status"] == "EXPIRED_OR_BLOCKED" and not old["actionable_now"]
    recent = current_window(c, snap, parse_utc(c["ready_at"]) + 20)
    assert recent["entry_window_at_computation"] and not recent["actionable_now"]
    del snap["symbols"]["EURUSD"]["economics"]
    assert not current_window(c, snap, parse_utc(c["ready_at"]) + 20)["entry_window_at_computation"]


def test_ready_candidate_before_newer_expired_candidate():
    live = {"ready_at": "2026-11-02T12:00:00Z", "plan_window": {"M0": "ENTRY_WINDOW"}}
    expired = {"ready_at": "2026-11-02T12:00:30Z", "plan_window": {"M0": "EXPIRED"}}
    assert sorted([expired, live], key=candidate_priority)[0] is live


def test_watch_uses_exact_frozen_anchor_and_no_fabricated_b():
    episode = {"state_at_as_of": "WATCHING_RETEST", "symbol": "EURUSD", "side": "LONG", "U": 1.2,
               "D": 1.1, "delta": .01, "atr_frozen": .02, "episode_id": "E", "expires_at": "2026-11-02T13:00:00Z"}
    zones = watch_zones({"episodes": [episode, dict(episode, state_at_as_of="EXPIRED")]})
    assert len(zones) == 1 and zones[0]["setup"] == "A"
    assert zones[0]["zone_low"] == pytest.approx(1.19)
    assert zones[0]["zone_high"] == pytest.approx(1.21)
    assert not zones[0]["actionable_now"]


def test_presets_explicit_maps_and_cli_finish_contract():
    from quantmt5.cli import _requested_map, _symbol_map, build_parser
    p = build_parser()
    assert len(_requested_map(p.parse_args(["session", "init", "--root", "r", "--name", "n"]))) == 8
    assert len(_requested_map(p.parse_args(["session", "init", "--root", "r", "--name", "n", "--universe-preset", "extended12"]))) == 12
    assert _symbol_map("EURUSD=EURUSD.r") == {"EURUSD": "EURUSD.r"}
    with pytest.raises(ValueError, match="DUPLICATE"):
        _symbol_map("EURUSD,EURUSD")
    with pytest.raises(ValueError, match="OIL"):
        _symbol_map("XTIUSD")


def test_focused_cycle_identity_is_distinct_and_subset_is_pinned(tmp_path):
    from quantmt5.session import _cycle_id, _child_argv, sdir
    s = {"session_id": "S", "symbol_map": {"EURUSD": "EURUSD.r"}, "focused_symbols": ["EURUSD"],
         "terminal_path": "mt5.exe", "collect": {"lookback_days": 35, "tick_minutes": 240}}
    assert _cycle_id(s, 100) != _cycle_id({"session_id": "S"}, 100)
    argv = _child_argv(s, tmp_path, 100)
    assert argv[argv.index("--symbols") + 1] == "EURUSD=EURUSD.r"
    with pytest.raises(ValueError, match="INVALID_SESSION"):
        sdir(tmp_path, "../other")


def test_embedded_analysis_report_never_spawns_card_context(monkeypatch, tmp_path):
    import quantmt5.session as session
    d = session.sdir(tmp_path, "test")
    (d / "data" / "store" / "snapshots").mkdir(parents=True)
    s = {"session_name": "test", "ftmo": {"program": "1-Step", "environment": "MT5_DEMO", "rule_regime": "UNKNOWN",
         "initial_capital": "UNCONFIGURED", "challenge_evaluation": "UNCONFIGURED"}, "risk": "UNCONFIGURED"}
    (d / "session.json").write_text(json.dumps(s), encoding="utf-8")
    (d / "data" / "store" / "snapshots" / "S.json").write_text(json.dumps({"symbols": {}, "candidates": []}), encoding="utf-8")
    monkeypatch.setattr(session, "exec_in_bundle", lambda *a, **k: pytest.fail("embedded batch must not spawn"))
    rec = {"status": "OK", "cycle_id": "C", "snapshot_id": "S", "analysis": {"cards": {}, "watch_zones": [], "market": {}}}
    report = session.build_report(tmp_path, "test", rec)
    data = json.loads(Path(report["report_json"]).read_text(encoding="utf-8"))
    assert "report_ready_at" in data and "analysis" in data


def test_batch_refreshes_deadline_at_completion_and_labels_deferred(monkeypatch):
    import quantmt5.context as context
    import quantmt5.reporting as reporting
    from quantmt5.util import iso_utc
    times = iter([100.0, 200.0])
    monkeypatch.setattr(reporting, "now_utc", lambda: next(times))
    monkeypatch.setattr(context, "check_snapshot_config", lambda snap: None)
    monkeypatch.setattr(context, "opportunity_card", lambda *args: {"status": "OK", "context": []})
    c = {"candidate_id": "C1", "symbol": "EURUSD", "ready_at": iso_utc(100),
         "entry_deadline_at": iso_utc(190), "plan_window": {"M0": "ENTRY_WINDOW"}}
    snap = {"snapshot_id": "S", "as_of_utc": iso_utc(100), "universe": [], "candidates": [c, dict(c, candidate_id="C2")],
            "symbols": {"EURUSD": {"market_state": "FRESH", "economics": {"status": "ASSUMED"}}}}
    result = reporting.analyze_snapshot(snap, max_cards=1)
    assert not result["cards"]["C1"]["current_window"]["entry_window_at_computation"]
    assert result["analysis_ready_at"] == iso_utc(200)
    assert result["deferred_cards"][0]["candidate_id"] == "C2"
    assert result["deferred_cards"][0]["status"] == "DEFERRED_DEEP_ANALYSIS"
