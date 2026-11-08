import json
from pathlib import Path


def test_session_defaults_and_explicit_tick_window_are_pinned(tmp_path):
    from quantmt5.session import init_session

    fresh = init_session(tmp_path, "fresh", "mt5.exe", {"XAUUSD": "XAUUSD"}, mode="SYNTHETIC_FIXTURE", synthetic_fixture="fixture.json")
    assert fresh["collect"]["tick_minutes"] == 240
    explicit = init_session(tmp_path, "explicit", "mt5.exe", {"XAUUSD": "XAUUSD"}, mode="SYNTHETIC_FIXTURE",
                            synthetic_fixture="fixture.json", tick_minutes=15)
    assert explicit["collect"]["tick_minutes"] == 15
    unchanged = init_session(tmp_path, "explicit", "mt5.exe", {"XAUUSD": "XAUUSD"}, mode="SYNTHETIC_FIXTURE",
                             synthetic_fixture="fixture.json", tick_minutes=240)
    assert unchanged["collect"]["tick_minutes"] == 15


def test_fabio_runs_once_for_available_symbols_and_writes_report(monkeypatch, tmp_path):
    import quantmt5.fabio as fabio
    import quantmt5.paper as paper

    calls = []

    def run_for_snapshot(snapshot_id, symbol, flow, exec_in, flow_sha, exec_sha, store=True):
        calls.append((snapshot_id, symbol, flow, exec_in, flow_sha, exec_sha, store))
        if symbol == "ERR":
            raise RuntimeError("DATA_INTEGRITY:tick pin changed")
        return {"analysis_id": "A1", "symbol": symbol, "decision": "WAIT", "reason": "NO_TRIGGER",
                "route": "FTMO_PRICE_PROXY", "flow": {"status": "NOT_PROVIDED"}, "families": {"F1": {"decision": "SKIP"}, "F2": {"decision": "WAIT"}},
                "artifact_path": str(tmp_path / f"{symbol}.json")}

    monkeypatch.setattr(fabio, "run_for_snapshot", run_for_snapshot)
    monkeypatch.setattr(fabio, "render_report", lambda result: f"# Fabio {result['symbol']}\n")
    monkeypatch.setattr(paper, "STORE_DIR", tmp_path / "store")
    snap = {"snapshot_id": "SNAP1", "symbols": {"XAUUSD": {"status": "OK"}, "ERR": {"status": "OK"},
                                                    "BAD": {"status": "ERROR", "reason": "MISSING_M5"}}}

    result = paper._run_fabio_for_snapshot(snap, ["XAUUSD", "ERR", "BAD"])

    assert [call[1] for call in calls] == ["ERR", "XAUUSD"]
    assert result["XAUUSD"]["decision"] == "WAIT"
    assert result["XAUUSD"]["report_path"].endswith("XAUUSD_A1.md")
    assert Path(result["XAUUSD"]["report_path"]).exists()
    assert result["BAD"]["status"] == "ERROR"
    assert result["BAD"]["reason"].startswith("FABIO_SYMBOL_ERROR:")
    assert result["ERR"]["status"] == "ERROR"
    assert "DATA_INTEGRITY" in result["ERR"]["reason"]


def test_report_includes_fabio_without_baseline_candidate(tmp_path):
    from quantmt5.session import build_report, sdir

    root, name = tmp_path, "demo"
    d = sdir(root, name)
    (d / "data" / "store" / "snapshots").mkdir(parents=True)
    session = {"session_name": name, "ftmo": {"program": "1-Step", "environment": "MT5_DEMO", "rule_regime": "UNKNOWN",
              "initial_capital": "UNCONFIGURED", "challenge_evaluation": "UNCONFIGURED"}, "risk": "UNCONFIGURED (paper)",
              "protocol": {}, "session_id": "S", "terminal_path": "mt5.exe"}
    (d / "session.json").write_text(json.dumps(session), encoding="utf-8")
    (d / "data" / "store" / "snapshots" / "SNAP.json").write_text(json.dumps({"symbols": {}, "candidates": []}), encoding="utf-8")
    rec = {"cycle_id": "C", "status": "OK", "planned_end_utc": "2026-01-01T00:00:00Z", "snapshot_id": "SNAP",
           "provider_kind": "MT5", "source_id": "SRC", "bundle_id": "B", "clock": {}, "symbols": {},
           "fabio": {"XAUUSD": {"families": {"F1": {"decision": "SKIP", "reason": "NO_BALANCE"},
                                                "F2": {"decision": "WAIT", "reason": "CVD_MISSING", "missing": ["ECONOMICS_UNKNOWN"]}},
                              "cvd": {"status": "NOT_PROVIDED", "coverage_window": 0.0}, "artifact_path": "fabio.json"}}}

    report = build_report(root, name, rec)
    text = Path(report["report_md"]).read_text(encoding="utf-8")
    assert "Fabio / CVD" in text
    assert "XAUUSD" in text and "NOT_PROVIDED" in text
    assert "Không có setup" in text
