"""Offline lifecycle witnesses; all mutations are pytest-owned temporary fixtures."""
import json
import os
import subprocess
import sys

import pytest

from quantmt5 import session as S
from quantmt5 import retention as R
from quantmt5.util import atomic_write_json, hash_obj, sha256_file
from tests.test_upgrade_retention import _session


def _pending(tmp_path, monkeypatch):
    import quantmt5.config as config
    import quantmt5.util as util
    monkeypatch.setattr(config, "config_hash", lambda: "CONFIG")
    monkeypatch.setattr(util, "engine_hash", lambda: "ENGINE")
    directory, ticks, pin, old_token = _session(tmp_path)
    root, name = directory.parent.parent, directory.name
    session = {"session_id": "S_TEST", "engine_hash": "ENGINE", "config_hash": "CONFIG"}
    atomic_write_json(directory / "session.json", session)
    contents = {"datasets.json": b"{}"}
    import hashlib
    files = {name: hashlib.sha256(data).hexdigest() for name, data in contents.items()}
    bid = "CFGB_" + hash_obj(files)[:20]
    bundle = directory / "data" / "bundles" / bid
    bundle.mkdir(parents=True)
    (bundle / "datasets.json").write_bytes(contents["datasets.json"])
    atomic_write_json(bundle / "BUNDLE_MANIFEST.json", {"bundle_id": bid, "files": files})
    pin = dict(pin, chunks=[{"file": "chunk.npz", "sha256": sha256_file(ticks / "chunk.npz")}])
    snap = {"snapshot_id": "SNAP_A", "config_bundle": {"bundle_id": bid}, "tick_versions": {"EURUSD": pin}}
    atomic_write_json(directory / "data" / "store" / "snapshots" / "SNAP_A.json", snap)
    rec = {"cycle_id": "CYCLE_A", "snapshot_id": "SNAP_A", "bundle_id": bid, "status": "OK",
           "planned_end_utc": "2026-11-08T13:00:00Z", "analysis": {"stage": "BASELINE"}}
    (directory / "cycles.jsonl").write_text(json.dumps(rec) + "\n", encoding="utf-8")
    report = {"report_md": str(directory / "reports" / "A.md"), "report_json": str(directory / "reports" / "A.json")}
    state = S._new_context(directory, session, rec, report)
    state_path = R.context_state_path(directory, "CYCLE_A", "SNAP_A")
    atomic_write_json(state_path, state)
    def render(root, name, rec, max_cards=8):
        md = directory / "reports" / "FINAL.md"
        js = directory / "reports" / "FINAL.json"
        md.write_text("Final synthetic report", encoding="utf-8")
        atomic_write_json(js, rec)
        return {"report_md": str(md), "report_json": str(js), "n_candidates": 0}
    monkeypatch.setattr(S, "build_report", render)
    return root, name, directory, ticks, state, state_path


def _enrich(root, name, state, **kw):
    c = state["continuation"]
    return S.enrich(root, name, c["cycle_id"], c["generation_id"], c["snapshot_id"], **kw)


def _child_ok(*args, **kwargs):
    return 0, {"data": {"snapshot_id": "SNAP_A", "errors": [], "market": {}, "cards": {}, "fabio": {}}}


def test_pending_direct_finish_refuses_even_guessed_ids(tmp_path, monkeypatch):
    root, name, directory, ticks, state, _ = _pending(tmp_path, monkeypatch)
    c = state["continuation"]
    assert R.finish_session(directory, c["cycle_id"], c["generation_id"], c["snapshot_id"])["reason"] == "CONTEXT_PENDING"
    assert (ticks / "chunk.npz").exists()


def test_enrich_releases_parent_lease_and_retry_does_not_spawn(tmp_path, monkeypatch):
    root, name, directory, ticks, state, _ = _pending(tmp_path, monkeypatch)
    calls = []
    def child(*args, **kwargs):
        calls.append(args)
        assert "--include-fabio" in args[2]
        assert kwargs["timeout_s"] == 30
        script = "from quantmt5.retention import storage_lease\nimport sys\nwith storage_lease(sys.argv[1],timeout_s=.05): print('LEASE_OK')"
        env = dict(os.environ, PYTHONPATH=str(S.PROJECT_DIR))
        check = subprocess.run([sys.executable, "-c", script, str(directory / "data")], env=env,
                               capture_output=True, text=True, timeout=10)
        assert check.returncode == 0 and "LEASE_OK" in check.stdout, check.stderr
        return _child_ok()
    monkeypatch.setattr(S, "exec_in_bundle", child)
    first = _enrich(root, name, state)
    second = _enrich(root, name, state)
    assert first["context_state"] == second["context_state"] == "COMPLETE"
    assert first["finish_token"] == second["finish_token"]
    assert len(calls) == 1
    assert len((directory / "cycles.jsonl").read_text().splitlines()) == 1


def test_optional_timeout_finishes_only_after_reaped_exception(tmp_path, monkeypatch):
    root, name, directory, ticks, state, _ = _pending(tmp_path, monkeypatch)
    def timeout(*args, **kwargs):
        raise subprocess.TimeoutExpired("analysis", 30)
    monkeypatch.setattr(S, "exec_in_bundle", timeout)
    import quantmt5.reporting as reporting
    monkeypatch.setattr(reporting, "build_baseline_packet", lambda snap: {"stage": "BASELINE", "errors": []})
    result = _enrich(root, name, state)
    assert result["context_state"] == "PARTIAL_FAILED"
    assert result["finish_token"]["status"] == "REPORT_COMMITTED"
    assert result["optional_errors"][0]["item_state"] == "TIMEOUT"


def test_concurrent_collection_revision_blocks_stale_commit(tmp_path, monkeypatch):
    root, name, directory, ticks, state, _ = _pending(tmp_path, monkeypatch)
    def child(*args, **kwargs):
        R.ensure_tick_generation(ticks, {"server": "fixture", "account_fingerprint": "demo"})
        return _child_ok()
    monkeypatch.setattr(S, "exec_in_bundle", child)
    result = _enrich(root, name, state)
    assert result["status"] == "REFUSED"
    assert "REVISION_MISMATCH" in result["reason"]
    assert result["finish_token"] is None
    assert (ticks / "chunk.npz").exists()


def test_raw_pin_tamper_refuses_before_child(tmp_path, monkeypatch):
    root, name, directory, ticks, state, _ = _pending(tmp_path, monkeypatch)
    monkeypatch.setattr(S, "exec_in_bundle", lambda *a, **kw: pytest.fail("must not spawn"))
    (ticks / "chunk.npz").write_bytes(b"tampered")
    result = _enrich(root, name, state)
    assert "PIN_HASH_MISMATCH" in result["reason"]
    assert result["finish_token"] is None


def test_crash_after_record_report_recovers_without_second_child(tmp_path, monkeypatch):
    root, name, directory, ticks, state, state_path = _pending(tmp_path, monkeypatch)
    calls = []
    monkeypatch.setattr(S, "exec_in_bundle", lambda *a, **kw: (calls.append(1) or _child_ok()))
    real_write = S.atomic_write_json
    def crash(path, value):
        if path == state_path and value.get("context_state") == "COMPLETE":
            raise OSError("simulated terminal state crash")
        return real_write(path, value)
    monkeypatch.setattr(S, "atomic_write_json", crash)
    first = _enrich(root, name, state)
    assert first["status"] == "REFUSED"
    c = state["continuation"]
    assert R.finish_session(directory, c["cycle_id"], c["generation_id"], c["snapshot_id"])["reason"] == "CONTEXT_PENDING"
    monkeypatch.setattr(S, "atomic_write_json", real_write)
    second = _enrich(root, name, state)
    assert second["context_state"] == "COMPLETE"
    assert len(calls) == 1


@pytest.mark.parametrize("timeout", [0, -1, float("inf"), float("nan"), True])
def test_invalid_timeout_rejected_without_session_mutation(tmp_path, timeout):
    with pytest.raises(ValueError, match="POSITIVE_FINITE"):
        S.enrich(tmp_path, "missing", "C", "G", "S", context_timeout=timeout)
    assert not list(tmp_path.iterdir())


def test_wrong_expected_identity_refuses_without_spawn(tmp_path, monkeypatch):
    root, name, directory, ticks, state, _ = _pending(tmp_path, monkeypatch)
    monkeypatch.setattr(S, "exec_in_bundle", lambda *a, **kw: pytest.fail("must not spawn"))
    result = S.enrich(root, name, "CYCLE_A", "WRONG", "SNAP_A")
    assert result["reason"] == "CONTEXT_EXPECTED_IDENTITY_MISMATCH"


def test_swallowed_integrity_error_never_optional_success(tmp_path, monkeypatch):
    root, name, directory, ticks, state, _ = _pending(tmp_path, monkeypatch)
    monkeypatch.setattr(S, "exec_in_bundle", lambda *a, **kw: (0, {"data": {
        "snapshot_id": "SNAP_A", "errors": [{"reason": "DATA_VERSION_MISMATCH"}]}}))
    result = _enrich(root, name, state)
    assert result["status"] == "REFUSED"
    assert "CORE_INTEGRITY" in result["reason"]
    assert result["finish_token"] is None


def test_unverified_process_teardown_remains_pending(tmp_path, monkeypatch):
    root, name, directory, ticks, state, state_path = _pending(tmp_path, monkeypatch)
    def child(*args, **kwargs):
        raise RuntimeError("CONTEXT_CHILD_TREE_TERMINATION_UNVERIFIED")
    monkeypatch.setattr(S, "exec_in_bundle", child)
    result = _enrich(root, name, state)
    assert result["status"] == "REFUSED"
    assert result["finish_token"] is None
    assert json.loads(state_path.read_text())["context_state"] == "PENDING"


def test_core_replay_integrity_error_cannot_finalize(tmp_path, monkeypatch):
    root, name, directory, ticks, state, state_path = _pending(tmp_path, monkeypatch)
    rec = json.loads((directory / "cycles.jsonl").read_text())
    rec["replay_errors"] = 1  # This existing counter contains only DataVersionMismatch failures.
    (directory / "cycles.jsonl").write_text(json.dumps(rec) + "\n", encoding="utf-8")
    monkeypatch.setattr(S, "exec_in_bundle", lambda *a, **kw: pytest.fail("must not spawn"))
    result = _enrich(root, name, state)
    assert result["reason"] == "CONTEXT_CORE_REPLAY_INTEGRITY_ERROR"
    assert result["finish_token"] is None
    assert (ticks / "chunk.npz").exists()


@pytest.mark.skipif(os.name != "nt", reason="Native Windows process identity/tree termination acceptance")
def test_real_context_timeout_reaps_parent_and_descendant(tmp_path, monkeypatch):
    # This fixture does not import engine/MT5 and never touches a real session.
    script = tmp_path / "sleep_child.py"
    pidfile = tmp_path / "pids.json"
    script.write_text(
        "import json,os,subprocess,sys,time\n"
        "from pathlib import Path\n"
        "child=subprocess.Popen([sys.executable,'-c','import time; time.sleep(60)'])\n"
        "Path(sys.argv[-1]).write_text(json.dumps([os.getpid(),child.pid]))\n"
        "time.sleep(60)\n", encoding="utf-8")
    monkeypatch.setattr(S, "ENTRY", script)
    monkeypatch.setattr(S, "bundle_env", lambda *a, **kw: dict(os.environ))
    try:
        with pytest.raises(subprocess.TimeoutExpired):
            S.exec_in_bundle(tmp_path, "synthetic", [str(pidfile)], "CFGB_TEST", timeout_s=2)
        pids = json.loads(pidfile.read_text())
        assert len(pids) == 2
        assert all(not (S.proc_identity(pid) or {}).get("alive") for pid in pids)
    finally:
        if pidfile.exists():
            for pid in json.loads(pidfile.read_text()):
                if (S.proc_identity(pid) or {}).get("alive"):
                    S._kill_tree(pid)
