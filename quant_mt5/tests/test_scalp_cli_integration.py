"""Real offline CLI chain: pinned bars -> Fabio plan -> pinned quote replay.

Every input is a labelled synthetic fixture in pytest's temporary workspace.
No MT5 process, connector, monkeypatch, baseline candidate or live account is used.
"""
import copy
import json
import os
from pathlib import Path
import subprocess
import sys

import numpy as np
import pytest

from quantmt5.util import hash_obj, iso_utc, sha256_file
from synth import PROF, T0
from test_scalp_fabio import f1_with_target

ENGINE = Path(__file__).resolve().parents[1]


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")


@pytest.fixture(scope="module")
def cli_case(tmp_path_factory):
    root = tmp_path_factory.mktemp("fabio_cli_")
    bundle, store, tick_dir = root / "bundle", root / "store", root / "ticks"
    bundle.mkdir(); tick_dir.mkdir()
    rows = f1_with_target()
    ready = T0 + len(rows) * 300 + 1
    rate_dtype = [("time", "<i8"), ("open", "<f8"), ("high", "<f8"), ("low", "<f8"),
                  ("close", "<f8"), ("tick_volume", "<i8"), ("spread", "<i4"), ("real_volume", "<i8")]
    rates = np.array([(T0 + i * 300, *row[:4], row[4], 10, 0) for i, row in enumerate(rows)], dtype=rate_dtype)
    bars_path = root / "synthetic_bars.npz"
    np.savez(bars_path, m5=rates)
    tick_path = tick_dir / "synthetic_ticks.npz"
    tape = np.array([(ready * 1000, 104.2, 104.3), ((ready + 10) * 1000, 110., 110.1)],
                    dtype=[("time_msc", "<i8"), ("bid", "<f8"), ("ask", "<f8")])
    np.savez(tick_path, ticks=tape)
    write_json(tick_dir / "checkpoint.json", {
        "chunks": [{"file": tick_path.name, "sha256": sha256_file(tick_path),
                    "first_ms": ready * 1000, "last_ms": (ready + 10) * 1000}],
        "windows": {f"{ready}_{ready + 3600}": {"status": "OK"}}, "clock_profile": "RAW_IS_UTC"})
    registry = {
        "source_id": "SYNTHETIC_SCALP_CLI", "registry_version": "synthetic-cli-v1",
        "source_identity": {"provider_kind": "SYNTHETIC_FIXTURE", "account_currency": "USD"},
        "time_contracts": {"API_UTC_CONTRACT": {"clock_profile": "RAW_IS_UTC", "status": "SYNTHETIC"}},
        "symbols": {"TEST": {"dataset_id": "SYNTHETIC_SCALP_CLI_BARS", "provider_kind": "SYNTHETIC_FIXTURE",
            "exposure": "SYNTHETIC_FIXTURE_NOT_MARKET_EVIDENCE", "time_basis": {"contract": "API_UTC_CONTRACT"},
            "timeframes": {"M5": {"path": str(bars_path), "key": "m5", "sha256": sha256_file(bars_path)},
                           "H1": {"derive_from": "M5"}, "D1": {"derive_from": "M5"}},
            "ticks": {"format": "collector_ticks_v1", "chunk_dir": str(tick_dir)}}}}
    write_json(bundle / "datasets.json", registry)
    write_json(bundle / "symbol_profiles.json", {"symbols": {"TEST": {**PROF, "chart_basis": "BID"}}})
    for filename in ("strategy_v0_1.json", "cost_profiles.json"):
        (bundle / filename).write_bytes((ENGINE / "config" / filename).read_bytes())
    files = {p.name: sha256_file(p) for p in bundle.iterdir()}
    write_json(bundle / "BUNDLE_MANIFEST.json", {"bundle_id": "CFGB_" + hash_obj(files)[:20], "files": files,
        "source_id": registry["source_id"], "provider_kind": "SYNTHETIC_FIXTURE", "account_currency": "USD"})
    env = dict(os.environ, QUANTMT5_CONFIG_DIR=str(bundle), QUANTMT5_STORE=str(store),
               QUANTMT5_WORKSPACE=str(root), PYTHONUTF8="1")
    calls = []

    def cli(*args, expect=0):
        command = [sys.executable, "-X", "utf8", "-I", str(ENGINE / "run_quant.py"), *map(str, args)]
        process = subprocess.run(command, env=env, cwd=root, stdin=subprocess.DEVNULL,
                                 capture_output=True, text=True, encoding="utf-8", timeout=30)
        result = json.loads(process.stdout)
        calls.append({"command": command, "returncode": process.returncode, "output": result, "stderr": process.stderr})
        assert process.returncode == expect, process.stdout + process.stderr
        return result

    source = cli("snapshot", "--as-of", iso_utc(ready), "--universe", "TEST", "--no-scan")
    outcome = cli("snapshot", "--as-of", iso_utc(ready + 30), "--universe", "TEST", "--no-scan")
    sid, oid = source["snapshot_id"], outcome["snapshot_id"]
    analysis = cli("fabio", "--snapshot", sid, "--symbol", "TEST", "--policy", "scalp_mt5_v1")
    value = {"root": root, "store": store, "cli": cli, "sid": sid, "oid": oid, "analysis": analysis,
             "analysis_path": Path(analysis["data"]["artifact_path"]), "calls": calls,
             "tick_dir": tick_dir, "tick_path": tick_path, "ready": ready, "rows": rows}
    yield value
    # Optional persistent evidence when explicitly requested by the developer's finite test run.
    evidence = os.environ.get("SCALP_CLI_EVIDENCE_DIR")
    if evidence:
        write_json(Path(evidence) / "cli_integration_calls.json", calls)


def test_actual_cli_builds_new_policy_plan_and_keeps_legacy_distinct(cli_case):
    case = cli_case; analysis = case["analysis"]["data"]
    family = analysis["families"]["F1"]
    assert analysis["inputs"]["mode"] == "MT5_SNAPSHOT_AUTO"
    assert analysis["mt5_inputs"]["provider_kind"] == "SYNTHETIC_FIXTURE"
    assert family["setup_stage"] == "TRIGGER_OBSERVED"
    assert family["execution_readiness"] == "COST_UNKNOWN"
    assert family["research_plan"]["source_fingerprint"] == analysis["source_fingerprint"]
    assert family["research_plan"]["known_at"] == analysis["as_of"]
    assert family["gates"]["location"]["volume_basis"] == "MT5_BAR_TICK_VOLUME_UNIFORM_PROXY"
    again = case["cli"]("fabio", "--snapshot", case["sid"], "--symbol", "TEST", "--policy", "scalp_mt5_v1")
    assert again["data"] == analysis
    legacy = case["cli"]("fabio", "--snapshot", case["sid"], "--symbol", "TEST")["data"]
    assert legacy["spec_version"] == "1.1.0" and "policy" not in legacy
    assert legacy["analysis_id"] != analysis["analysis_id"]
    assert not any("candidate_id" in v for v in analysis["families"].values())


def test_real_cli_replays_same_frozen_plan_with_unknown_and_assumed_costs(cli_case):
    case = cli_case
    args = ("fabio-replay", "--analysis", case["analysis_path"], "--family", "F1", "--snapshot", case["oid"])
    gross = case["cli"](*args)["data"]
    net = case["cli"](*args, "--commission-price-rt", ".1", "--slippage-price", ".05")["data"]
    repeat = case["cli"](*args, "--commission-price-rt", ".1", "--slippage-price", ".05")["data"]
    plan = case["analysis"]["data"]["families"]["F1"]["research_plan"]
    assert gross["status"] == net["status"] == "EXITED" and gross["reason"] == net["reason"] == "TP"
    assert gross["scenario"]["cost_status"] == "UNKNOWN" and gross["net_R"] is None
    assert net["scenario"]["cost_status"] == "ASSUMED" and net["net_R"] > 0
    assert gross["target_chart"] == net["target_chart"] == plan["target_chart"]
    assert gross["sl_chart"] == net["sl_chart"] == plan["sl_chart"]
    assert net["entry"] == pytest.approx(104.35)
    assert net["net_price"] == pytest.approx(net["primary"]["exit_price"] - 104.35 - .1)
    assert net == repeat
    assert "fabio_replay" in net["artifact_path"] and "candidate_id" not in net


def test_real_cli_same_snapshot_does_not_read_pinned_future_ticks(cli_case):
    case = cli_case
    value = case["cli"]("fabio-replay", "--analysis", case["analysis_path"], "--family", "F1")["data"]
    assert value["status"] == "CENSORED"
    assert value["primary"]["gross_price"] is None and value["net_R"] is None


def test_real_cli_previous_chain_freezes_plan_after_tick_coverage_upgrade(cli_case):
    case = cli_case
    # Later collection supplies ticks for historical profile windows. Existing
    # source/outcome snapshots keep their original immutable chunk pins.
    historical = case["tick_dir"] / "historical_profile_ticks.npz"
    tape = np.array([((T0 + i * 300 + 150) * 1000, row[0], row[0] + .1)
                     for i, row in enumerate(case["rows"])],
                    dtype=[("time_msc", "<i8"), ("bid", "<f8"), ("ask", "<f8")])
    np.savez(historical, ticks=tape)
    write_json(case["tick_dir"] / "checkpoint.json", {
        "chunks": [{"file": historical.name, "sha256": sha256_file(historical),
                    "first_ms": int(tape["time_msc"][0]), "last_ms": int(tape["time_msc"][-1])},
                   {"file": case["tick_path"].name, "sha256": sha256_file(case["tick_path"]),
                    "first_ms": case["ready"] * 1000, "last_ms": (case["ready"] + 10) * 1000}],
        "windows": {f"{T0}_{case['ready'] + 3600}": {"status": "OK"}}, "clock_profile": "RAW_IS_UTC"})
    snapshot = case["cli"]("snapshot", "--as-of", iso_utc(case["ready"] + 30), "--universe", "TEST", "--no-scan")
    oid = snapshot["snapshot_id"]
    assert oid != case["oid"]
    prior = case["analysis"]["data"]
    chained = case["cli"]("fabio", "--snapshot", oid, "--symbol", "TEST", "--policy", "scalp_mt5_v1",
                           "--previous-analysis", case["analysis_path"])["data"]
    rebuilt = case["cli"]("fabio", "--snapshot", oid, "--symbol", "TEST", "--policy", "scalp_mt5_v1")["data"]
    assert chained["profile_lifecycle"]["mode"] == "FROZEN_PREVIOUS_ANALYSIS_CHAIN"
    assert chained["profile_lifecycle"]["previous_analysis_id"] == prior["analysis_id"]
    assert rebuilt["profile_lifecycle"]["mode"] == "RECONSTRUCTED_FROM_PINNED_INPUTS"
    assert chained["balance"] == prior["balance"]
    before, after = prior["families"]["F1"], chained["families"]["F1"]
    for key in ("opportunity_id", "trigger_id", "profile_revision_id", "frozen_profile", "research_plan"):
        assert after[key] == before[key], key
    assert rebuilt["families"]["F1"].get("profile_revision_id") != before["profile_revision_id"]


@pytest.mark.parametrize("kind,reason", [("source", "PREVIOUS_SOURCE_MISMATCH"),
                                        ("future", "PREVIOUS_IS_FUTURE"),
                                        ("prefix", "PREVIOUS_PRICE_HISTORY_CHANGED_OR_MISSING")])
def test_real_cli_rejects_wrong_previous_analysis_chain(cli_case, kind, reason):
    case = cli_case
    previous = copy.deepcopy(case["analysis"])
    data = previous["data"]
    if kind == "source":
        data["source_fingerprint"] = "WRONG_SOURCE"
    elif kind == "future":
        data["as_of"] = iso_utc(case["ready"] + 31)
    else:
        data["price_prefix"]["hash"] = "WRONG_PRICE_HISTORY"
    path = case["root"] / f"wrong_previous_{kind}.json"
    write_json(path, previous)
    result = case["cli"]("fabio", "--snapshot", case["oid"], "--symbol", "TEST", "--policy", "scalp_mt5_v1",
                         "--previous-analysis", path, expect=2)
    assert result["status"] == "ERROR"
    assert any(reason in error["reason"] for error in result["errors"])


@pytest.mark.parametrize("kind,reason", [("source", "SNAPSHOT_SOURCE_MISMATCH"),
                                        ("checksum", "TICK_CHUNK_MISSING_OR_CHANGED"),
                                        ("spec", "SPEC_MISMATCH")])
def test_real_cli_rejects_wrong_source_tampered_pin_and_wrong_spec(cli_case, kind, reason):
    case = cli_case
    analysis_path, oid = case["analysis_path"], case["oid"]
    if kind == "spec":
        wrong = copy.deepcopy(case["analysis"]["data"])
        wrong["spec_hash"] = "WRONG_SPEC"
        analysis_path = case["root"] / "wrong_spec.json"
        write_json(analysis_path, wrong)
    else:
        snapshot = json.loads((case["store"] / "snapshots" / f"{oid}.json").read_text(encoding="utf-8"))
        oid = "SNAP_TEST_BAD_" + kind.upper()
        snapshot["snapshot_id"] = oid
        if kind == "source":
            snapshot["config_bundle"]["source_id"] = "DIFFERENT_SYNTHETIC_SOURCE"
        else:
            snapshot["tick_versions"]["TEST"]["chunks"][0]["sha256"] = "0" * 64
        write_json(case["store"] / "snapshots" / f"{oid}.json", snapshot)
    result = case["cli"]("fabio-replay", "--analysis", analysis_path, "--family", "F1", "--snapshot", oid, expect=2)
    assert result["status"] == "ERROR"
    assert any(reason in error["reason"] for error in result["errors"])
