"""B4 evaluation pipeline tests: 6 configs x 9 scenarios, determinism, paired differences,
Holm adjustment, data versions recording, run report & manifest, registry idempotence & immutability.
"""
from __future__ import annotations

import argparse
import copy
import datetime as dt
import json
from pathlib import Path

import pytest

import quantmt5.cli as cli
import quantmt5.evaluate as evaluate
import quantmt5.report as report
from quantmt5.cli import cmd_evaluate, cmd_register, default_experiment
from quantmt5.data import aggregate
from quantmt5.detectors import SymbolData
from quantmt5.evaluate import daily_series, holm, run_experiment, trading_days
from quantmt5.report import write_run
from quantmt5.util import iso_utc, sha256_file
from synth import bars

T0 = 1736121600  # 2025-01-06 00:00:00 UTC (Monday)


def make_synth_symbol_data(symbol: str = "XAUUSD") -> SymbolData:
    m5_rows = [(100.0, 100.5, 99.5, 100.0, 100, 2)] * (5 * 288)
    m5 = bars(300, T0, m5_rows, symbol=symbol, tf="M5")
    h1 = aggregate(m5, "H1")
    d1 = aggregate(m5, "D1")

    # M1 bars for 5 days with specific movements triggering TP
    m1_rows = [(100.0, 100.5, 99.5, 100.0, 100, 2)] * (5 * 1440)
    for i in range(120, 150):
        m1_rows[i] = (101.5, 102.0, 101.4, 101.8, 100, 2)
    for i in range(1560, 1590):
        m1_rows[i] = (101.5, 102.0, 101.4, 101.8, 100, 2)

    m1 = bars(60, T0, m1_rows, symbol=symbol, tf="M1")
    prof = {
        "trade_tick_size": 0.01,
        "point": 0.01,
        "digits": 2,
        "contract_size": 100.0,
        "profit_currency": "USD",
        "stops_level_points": 0,
        "session": {},
    }
    return SymbolData(symbol, m5, h1, d1, m1, 0.01, prof, "synthetic_source")


def make_synth_catalog() -> dict:
    def _cand(cid, setup, day_offset, side="LONG", gates=None, ep=None):
        t_sig = T0 + day_offset * 86400 + 14 * 3600
        t_ready = t_sig + 1
        g = gates or {br: {"result": "PASS"} for br in ("M0", "M1", "M2", "P0", "P1", "P2")}
        return {
            "candidate_id": cid,
            "revision_id": "REV_" + cid,
            "setup": setup,
            "symbol": "XAUUSD",
            "side": side,
            "episode_id": ep or ("EP_" + cid),
            "signal_close_ts": t_sig,
            "ready_ts": t_ready,
            "ready_at": iso_utc(t_ready),
            "signal_bar": {
                "open_at": iso_utc(t_sig - 300),
                "close_at": iso_utc(t_sig),
                "o": 100.0,
                "h": 100.5,
                "l": 99.5,
                "c": 100.0,
            },
            "atr_frozen": 1.0,
            "buffer": 0.05,
            "episode_expires_ts": None,
            "gates": g,
        }

    cands = [
        # Setup A
        _cand("A1", "A", 0, "LONG", {"M0": {"result": "PASS"}, "M1": {"result": "PASS"}, "M2": {"result": "PASS"}}, "EP_A1"),
        _cand("A2", "A", 1, "LONG", {"M0": {"result": "PASS"}, "M1": {"result": "PASS"}, "M2": {"result": "FAIL"}}, "EP_A2"),
        _cand("A3", "A", 2, "SHORT", {"M0": {"result": "PASS"}, "M1": {"result": "FAIL"}, "M2": {"result": "PASS"}}, "EP_A3"),
        # Setup B
        _cand("B1", "B", 0, "LONG", {"P0": {"result": "PASS"}, "P1": {"result": "PASS"}, "P2": {"result": "PASS"}}),
        _cand("B2", "B", 1, "LONG", {"P0": {"result": "PASS"}, "P1": {"result": "PASS"}, "P2": {"result": "FAIL"}}),
        _cand("B3", "B", 2, "SHORT", {"P0": {"result": "PASS"}, "P1": {"result": "FAIL"}, "P2": {"result": "FAIL"}}),
    ]
    episodes = [
        {"episode_id": "EP_A1", "breakout_close_ts": T0 + 13 * 3600},
        {"episode_id": "EP_A2", "breakout_close_ts": T0 + 86400 + 13 * 3600},
        {"episode_id": "EP_A3", "breakout_close_ts": T0 + 2 * 86400 + 13 * 3600},
    ]
    return {"candidates": cands, "episodes": episodes}


def make_small_experiment() -> dict:
    exp = default_experiment()
    exp["name"] = "SMALL_B4_EXP"
    exp["universe"] = ["XAUUSD"]
    exp["evaluation"] = {"start": "2025-01-06", "end": "2025-01-10"}
    exp["experiment_id"] = "EXP_SMALL_B4"
    exp["registered_at"] = "2026-11-03T00:00:00Z"
    return exp


@pytest.fixture
def patch_synth_backend(monkeypatch):
    sd = make_synth_symbol_data("XAUUSD")
    cat = make_synth_catalog()
    monkeypatch.setattr(evaluate, "load_symbol", lambda s: sd)
    monkeypatch.setattr(evaluate, "detect_all", lambda s, cfg: cat)
    return sd, cat


def test_run_experiment_has_all_scenarios_and_branches(patch_synth_backend):
    exp = make_small_experiment()
    res = run_experiment(exp, progress=lambda _: None)

    expected_scenarios = [
        f"{lat}/{cost}"
        for cost in ("LOW", "BASE", "ADVERSE")
        for lat in ("BASE", "MANUAL", "SLOW")
    ]
    assert len(res["results"]) == 9
    assert set(res["results"].keys()) == set(expected_scenarios)

    required_pairs = ("M2-M0", "M2-M1", "P1-P0", "P2-P1")
    branches = ("M0", "M1", "M2", "P0", "P1", "P2")
    required_branch_keys = ("n_fills", "net_R_total", "n_fills_unresolved", "verdict")

    for scen, s_res in res["results"].items():
        assert "paired_daily_differences" in s_res, f"missing paired_daily_differences in {scen}"
        for pair in required_pairs:
            assert pair in s_res["paired_daily_differences"], f"missing pair {pair} in {scen}"

        assert "portfolio" in s_res, f"missing portfolio in {scen}"

        for br in branches:
            assert br in s_res, f"missing branch {br} in {scen}"
            for k in required_branch_keys:
                assert k in s_res[br], f"missing key {k} in branch {br} under {scen}"


def test_run_experiment_is_deterministic(patch_synth_backend):
    exp = make_small_experiment()
    res1 = run_experiment(exp, progress=lambda _: None)
    res2 = run_experiment(exp, progress=lambda _: None)

    s1 = json.dumps(res1["results"], sort_keys=True)
    s2 = json.dumps(res2["results"], sort_keys=True)
    assert s1 == s2


def test_paired_difference_equals_daily_series_difference(patch_synth_backend):
    exp = make_small_experiment()
    res = run_experiment(exp, progress=lambda _: None)

    days = trading_days(dt.date(2025, 1, 6), dt.date(2025, 1, 10))
    scen = "BASE/BASE"
    ledgers = res["_ledgers"][scen]

    pairs = [
        ("M2-M0", "M2", "M0"),
        ("M2-M1", "M2", "M1"),
        ("P1-P0", "P1", "P0"),
        ("P2-P1", "P2", "P1"),
    ]
    for pair_name, br_a, br_b in pairs:
        s_a = daily_series([r for r in ledgers[br_a] if r["status"] == "FILLED"], days)
        s_b = daily_series([r for r in ledgers[br_b] if r["status"] == "FILLED"], days)
        diff = s_a - s_b
        expected_mean = float(diff.mean())
        reported_mean = res["results"][scen]["paired_daily_differences"][pair_name]["mean"]
        assert abs(expected_mean - reported_mean) < 1e-12


def test_holm_is_applied_to_the_four_pairs(patch_synth_backend):
    exp = make_small_experiment()
    res = run_experiment(exp, progress=lambda _: None)

    scen = "BASE/BASE"
    comps = res["results"][scen]["paired_daily_differences"]
    raw_p = {k: v.get("p_two_sided_bootstrap") for k, v in comps.items()}
    expected_holm = holm(raw_p)

    for k in ("M2-M0", "M2-M1", "P1-P0", "P2-P1"):
        assert comps[k]["p_holm"] == pytest.approx(expected_holm[k])


def test_data_versions_recorded(patch_synth_backend, monkeypatch):
    exp = make_small_experiment()

    # Normal case: data_versions recorded for symbol
    res = run_experiment(exp, progress=lambda _: None)
    assert "data_versions" in res
    assert "XAUUSD" in res["data_versions"]
    assert isinstance(res["data_versions"]["XAUUSD"], dict)
    assert len(res["data_versions"]["XAUUSD"]) > 0

    # Error case: dataset_version fails for symbol -> {"error": ...} without crash
    monkeypatch.setattr(evaluate, "dataset_version", lambda reg, sym, tf: (_ for _ in ()).throw(ValueError("MOCK_FAIL")))
    res_err = run_experiment(exp, progress=lambda _: None)
    assert "data_versions" in res_err
    assert "XAUUSD" in res_err["data_versions"]
    assert "error" in res_err["data_versions"]["XAUUSD"]
    assert res_err["data_versions"]["XAUUSD"]["error"] == "ValueError"
    assert "BASE/BASE" in res_err["results"]


def test_write_run_files_and_manifest(patch_synth_backend, monkeypatch, tmp_path):
    monkeypatch.setattr(report, "STORE_DIR", tmp_path)

    exp = make_small_experiment()
    res = run_experiment(exp, progress=lambda _: None)

    run_dir = write_run(exp, copy.deepcopy(res), ["test log line 1", "test log line 2"])

    assert (run_dir / "RESULTS.json").exists()
    assert (run_dir / "REPORT.md").exists()
    assert (run_dir / "run.log").exists()
    assert (run_dir / "MANIFEST.json").exists()

    man = json.loads((run_dir / "MANIFEST.json").read_text(encoding="utf-8"))
    assert set(man["files"].keys()) >= {"RESULTS.json", "REPORT.md", "run.log"}
    for filename, expected_hash in man["files"].items():
        actual_hash = sha256_file(run_dir / filename)
        assert actual_hash == expected_hash, f"Hash mismatch for {filename}"

    report_text = (run_dir / "REPORT.md").read_text(encoding="utf-8")
    for required_str in ("HISTORICAL_EXPOSED", "M1_OPEN_PROXY", "Paired daily differences", "Data versions"):
        assert required_str in report_text, f"Missing string '{required_str}' in REPORT.md"

    for cost in ("LOW", "BASE", "ADVERSE"):
        for lat in ("BASE", "MANUAL", "SLOW"):
            scen = f"{lat}/{cost}"
            assert f"## Scenario {scen}" in report_text, f"Missing scenario heading '## Scenario {scen}' in REPORT.md"


def test_register_is_idempotent_and_immutable(monkeypatch, tmp_path):
    monkeypatch.setattr(cli, "STORE_DIR", tmp_path)

    exp_data = default_experiment()
    exp_data["name"] = "EXP_REGISTER_TEST"
    exp_file = tmp_path / "exp_input.json"
    exp_file.write_text(json.dumps(exp_data), encoding="utf-8")

    ns = argparse.Namespace(file=str(exp_file), exploratory=False)

    # First registration
    env1 = cmd_register(ns)
    assert env1["status"] == "OK"
    eid1 = env1["data"]["experiment_id"]
    p1 = Path(env1["data"]["path"])
    assert p1.exists()
    assert "already_registered" not in env1["data"]
    sha_initial = sha256_file(p1)

    # Second registration with exact same content
    env2 = cmd_register(ns)
    assert env2["status"] == "OK"
    assert env2["data"]["already_registered"] is True
    assert env2["data"]["experiment_id"] == eid1
    assert sha256_file(p1) == sha_initial

    # Modify 1 field
    exp_data_mod = dict(exp_data, name="EXP_REGISTER_TEST_MODIFIED")
    exp_file_mod = tmp_path / "exp_input_mod.json"
    exp_file_mod.write_text(json.dumps(exp_data_mod), encoding="utf-8")
    ns_mod = argparse.Namespace(file=str(exp_file_mod), exploratory=False)

    env3 = cmd_register(ns_mod)
    assert env3["status"] == "OK"
    eid3 = env3["data"]["experiment_id"]
    assert eid3 != eid1
    # Old experiment file is strictly immutable
    assert sha256_file(p1) == sha_initial


def test_evaluate_refuses_unregistered(monkeypatch, tmp_path):
    monkeypatch.setattr(cli, "STORE_DIR", tmp_path)

    ns = argparse.Namespace(experiment="EXP_DOES_NOT_EXIST_999999")
    env = cmd_evaluate(ns)
    assert env["status"] == "ERROR"
    assert any(e.get("reason") == "EXPERIMENT_NOT_REGISTERED" for e in env.get("errors", []))
