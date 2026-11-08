"""Public delivery contract and real offline CLI consumer, with no MT5 attach."""
import copy
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time

import pytest

from quantmt5.util import PROJECT_DIR, parse_utc, sha256_file
from test_evening_overlay import ASOF, _snapshot


@pytest.mark.parametrize("base_args", [
    ["session", "once", "--root", "r", "--name", "n"],
    ["session", "check", "--root", "r", "--name", "n", "--symbols", "XAUUSD"],
    ["paper-run", "--terminal-path", "fake", "--out-root", "r"], ["paper-scan"],
])
def test_t13_modes_default_full_and_explicit_baseline(base_args):
    from quantmt5.cli import build_parser
    parser = build_parser()
    assert parser.parse_args(base_args).analysis_mode == "full"
    for mode in ("baseline", "full"):
        assert parser.parse_args(base_args + ["--analysis-mode", mode]).analysis_mode == mode
    with pytest.raises(SystemExit):
        parser.parse_args(base_args + ["--analysis-mode", "invalid"])


def test_t13_t21_enrich_and_analysis_flags_parse_without_side_effect():
    from quantmt5.cli import build_parser
    parser = build_parser()
    args = parser.parse_args(["session", "enrich", "--root", "r", "--name", "n", "--expected-cycle", "C",
        "--expected-generation", "G", "--expected-snapshot", "S", "--context-timeout", "12.5"])
    assert (args.expected_cycle, args.expected_generation, args.expected_snapshot, args.context_timeout) == ("C", "G", "S", 12.5)
    assert parser.parse_args(["analysis", "--snapshot", "S", "--include-fabio"]).include_fabio is True
    assert parser.parse_args(["analysis", "--snapshot", "S"]).include_fabio is False


@pytest.mark.parametrize("action", ["once", "check"])
def test_t13_cli_forwards_mode_and_focus(monkeypatch, action):
    from quantmt5 import cli, session
    calls = []
    def fake(*args, **kwargs):
        calls.append((args, kwargs))
        return {"status": "OK"}
    monkeypatch.setattr(session, "on_demand", fake)
    args = ["session", action, "--root", "r", "--name", "n", "--analysis-mode", "baseline"]
    if action == "check":
        args += ["--symbols", "XAUUSD"]
    parsed = cli.build_parser().parse_args(args)
    parsed.fn(parsed)
    assert calls[0][1]["analysis_mode"] == "baseline"
    assert calls[0][1]["focused_symbols"] == (["XAUUSD"] if action == "check" else None)


def test_t31_mode_not_part_of_cycle_identity_and_child_receives_mode(tmp_path):
    from quantmt5.session import _child_argv, _cycle_id
    session = {"session_id": "S", "symbol_map": {"XAUUSD": "XAUUSD"}, "terminal_path": "fake",
               "collect": {"lookback_days": 35, "tick_minutes": 240}}
    full, baseline = dict(session, analysis_mode="full"), dict(session, analysis_mode="baseline")
    assert _cycle_id(full, 100) == _cycle_id(baseline, 100)
    for config in (full, baseline):
        argv = _child_argv(config, tmp_path, 100)
        assert argv[argv.index("--analysis-mode") + 1] == config["analysis_mode"]


def test_t15_t17_baseline_scan_returns_before_optional_consumer(monkeypatch, tmp_path):
    from quantmt5 import config, data, paper, reporting, snapshot
    snap = _snapshot(0)
    calls = []
    monkeypatch.setattr(config, "bundle_identity", lambda: {"kind": "SOURCE_BUNDLE", "bundle_id": "B", "provider_kind": "SYNTHETIC_FIXTURE"})
    monkeypatch.setattr(data, "load_registry", lambda: {"source_id": "SRC", "requested_symbols": ["XAUUSD"], "symbols": {"XAUUSD": {}}})
    monkeypatch.setattr(snapshot, "make_snapshot", lambda *a, **kw: copy.deepcopy(snap))
    monkeypatch.setattr(snapshot, "scan", lambda snap: {"status": "OK"})
    monkeypatch.setattr(paper, "paper_journal_path", lambda _: tmp_path / "journal.jsonl")
    def optional(*args, **kwargs):
        calls.append("optional_started")
        pytest.fail("optional work executed on baseline-return path")
    monkeypatch.setattr(paper, "_run_fabio_for_snapshot", optional)
    monkeypatch.setattr(reporting, "analyze_snapshot", optional)
    output = paper._paper_scan(parse_utc(ASOF), ["XAUUSD"], 0, analysis_mode="baseline")
    received = json.loads(json.dumps(output))
    calls.append("consumer_received_baseline")
    assert calls == ["consumer_received_baseline"]
    assert received["analysis"]["context_state"] == "PENDING"
    assert received["analysis"]["stage"] == "BASELINE" and received["fabio"] == {}


def test_t16_t19_t20_t29_t31_t67_real_cli_two_phase_consumer(tmp_path):
    """A user-space consumer parses call1 before call2; every destructive action is temp-only."""
    engine = tmp_path / "engine"
    shutil.copytree(PROJECT_DIR / "quantmt5", engine / "quantmt5", ignore=shutil.ignore_patterns("__pycache__"))
    shutil.copytree(PROJECT_DIR / "config", engine / "config")
    shutil.copy2(PROJECT_DIR / "run_quant.py", engine / "run_quant.py")
    fixture = PROJECT_DIR / "tests" / "fixtures" / "b6c_fixture.py"
    root = tmp_path / "operations"
    root.mkdir()
    env = dict(os.environ, QUANTMT5_ALLOW_SYNTHETIC_FIXTURE="1", QUANTMT5_FIXTURE_VARIANT="default",
               QUANTMT5_FIXTURE_TICK_START="2025-01-15T14:00:00Z", QUANTMT5_STORE=str(tmp_path / "isolated_store"))
    for name in ("QUANTMT5_CONFIG_DIR", "QUANTMT5_WORKSPACE", "QUANTMT5_ALLOW_TEST_HOOKS", "QUANTMT5_TEST_CRASH_POINT"):
        env.pop(name, None)
    events = []
    def cli(action, *args):
        events.append({"event": action + "_started", "monotonic": time.monotonic()})
        process = subprocess.run([sys.executable, "-X", "utf8", "-I", str(engine / "run_quant.py"), "session", action,
            "--root", str(root), "--name", "evening", *map(str, args)], env=env, cwd=root, capture_output=True,
            stdin=subprocess.DEVNULL, timeout=180)
        try:
            result = json.loads(process.stdout.decode("utf-8"))
        except ValueError:
            pytest.fail((process.returncode, process.stdout.decode("utf-8", "replace"), process.stderr.decode("utf-8", "replace")))
        events.append({"event": action + "_consumer_received", "monotonic": time.monotonic()})
        return result
    initial = cli("init", "--terminal-path", "C:/SYNTH MT5", "--mode", "SYNTHETIC_FIXTURE", "--symbols", "XAUUSD",
                  "--synthetic-fixture", fixture, "--cycle-timeout", "120")
    assert initial["status"] == "OK", initial
    first = cli("once", "--end", "2025-01-15T15:30:00Z", "--analysis-mode", "baseline", "--max-cards", "0")
    baseline = first["data"]
    assert baseline["status"] in ("OK", "PARTIAL"), first
    assert baseline["context_state"] == "PENDING" and baseline["finish_token"] is None
    continuation = baseline["continuation"]
    for key in ("session_id", "cycle_id", "generation_id", "snapshot_id", "bundle_id", "mutation_revision", "engine_hash", "config_hash"):
        assert continuation[key] is not None
    session = root / "sessions" / "evening"
    snapshot_path = session / "data" / "store" / "snapshots" / f"{continuation['snapshot_id']}.json"
    snapshot_data = json.loads(snapshot_path.read_text(encoding="utf-8"))
    expected_ids = {c["candidate_id"] for c in snapshot_data["candidates"]}
    assert expected_ids, "synthetic fixture must actually exercise candidate delivery"
    baseline_report = json.loads(Path(baseline["report"]["report_json"]).read_text(encoding="utf-8"))
    assert {c["candidate_id"] for c in baseline_report["candidates"]} == expected_ids
    baseline_sha = sha256_file(Path(baseline["report"]["report_json"]))
    cycles_before = (session / "cycles.jsonl").read_bytes()
    journal_hashes = {p: sha256_file(p) for p in (session / "data" / "store" / "journal").glob("*.jsonl")}
    snapshot_inventory = {p: sha256_file(p) for p in (session / "data" / "store" / "snapshots").glob("*.json")}
    pin = snapshot_data["tick_versions"]["XAUUSD"]
    tick_dir = Path(pin["chunk_dir"])
    tick_hashes = {p: sha256_file(p) for p in tick_dir.rglob("*") if p.is_file()}
    identity_args = ["--expected-cycle", continuation["cycle_id"], "--expected-generation", continuation["generation_id"],
                     "--expected-snapshot", continuation["snapshot_id"]]
    refused = cli("finish", *identity_args)
    assert refused["data"]["status"] != "CLOSED", refused
    assert all(p.exists() and sha256_file(p) == digest for p, digest in tick_hashes.items())
    enriched = cli("enrich", *identity_args, "--context-timeout", "60", "--max-cards", "0")
    final = enriched["data"]
    assert final["context_state"] in ("COMPLETE", "PARTIAL_FAILED"), enriched
    assert final["finish_token"]["status"] == "REPORT_COMMITTED", enriched
    assert final["cycle_id"] == continuation["cycle_id"]
    assert (session / "cycles.jsonl").read_bytes() == cycles_before
    assert {p: sha256_file(p) for p in (session / "data" / "store" / "journal").glob("*.jsonl")} == journal_hashes
    assert {p: sha256_file(p) for p in (session / "data" / "store" / "snapshots").glob("*.json")} == snapshot_inventory
    assert sha256_file(Path(baseline["report"]["report_json"])) == baseline_sha
    assert all(p.exists() and sha256_file(p) == digest for p, digest in tick_hashes.items())
    final_report = json.loads(Path(final["report"]["report_json"]).read_text(encoding="utf-8"))
    assert {c["candidate_id"] for c in final_report["candidates"]} == expected_ids
    order = [event["event"] for event in events]
    assert order.index("once_consumer_received") < order.index("enrich_started")
    evidence = {"source_kind": "SYNTHETIC_FIXTURE", "consumer": "subprocess_json_loads",
                "events": events, "candidate_ids": sorted(expected_ids), "baseline_return_before_enrich": True,
                "late_or_missed_due_to_context": 0, "note": "Finite-call ordering only; not a live latency SLA."}
    (tmp_path / "delivery.json").write_text(json.dumps(evidence, indent=2), encoding="utf-8")
    closed = cli("finish", *identity_args)
    assert closed["data"]["status"] == "CLOSED", closed
    assert snapshot_path.exists() and Path(final["report"]["report_json"]).exists()
