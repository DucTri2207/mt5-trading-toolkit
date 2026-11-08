import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

from quantmt5.retention import (RetentionError, assert_tick_available, ensure_tick_generation, finish_session,
                               init_retention, record_report, register_consumer, storage_lease)
from quantmt5.util import append_jsonl, atomic_write_json, read_jsonl, sha256_file


def _session(tmp_path):
    session = tmp_path / "operations" / "sessions" / "evening"
    atomic_write_json(session / "session.json", {"session_id": "S_TEST"})
    init_retention(session, "S_TEST")
    tick_dir = session / "data" / "raw" / "mt5_fixture" / "EURUSD" / "ticks"
    meta = ensure_tick_generation(tick_dir, {"server": "fixture", "account_fingerprint": "demo"})
    tick_dir.mkdir(parents=True, exist_ok=True)
    (tick_dir / "chunk.npz").write_bytes(b"test tick payload")
    (tick_dir / "pending.npz").write_bytes(b"test pending payload")
    atomic_write_json(tick_dir / "checkpoint.json", {**meta, "chunks": [{"file": "chunk.npz", "sha256": sha256_file(tick_dir / "chunk.npz")}],
                                                    "windows": {"1_2": {"status": "OK"}}, "pending_file": "pending.npz"})
    pin = {**meta, "chunk_dir": str(tick_dir)}
    snapshot = {"snapshot_id": "SNAP_A", "tick_versions": {"EURUSD": pin}}
    atomic_write_json(session / "data" / "store" / "snapshots" / "SNAP_A.json", snapshot)
    append_jsonl(session / "cycles.jsonl", {"cycle_id": "CYCLE_A", "snapshot_id": "SNAP_A", "status": "OK"})
    atomic_write_json(session / "reports" / "A.json", {"cycle_id": "CYCLE_A"})
    (session / "reports" / "A.md").write_text("Report A", encoding="utf-8")
    report = record_report(session, "CYCLE_A", "SNAP_A", [session / "reports" / "A.json", session / "reports" / "A.md"], "2026-11-08T13:00:00Z")
    return session, tick_dir, pin, report


def _finish(session, report):
    return finish_session(session, report["cycle_id"], report["generation_id"], report["snapshot_id"])


def test_finish_deletes_only_owned_ticks_and_preserves_report_pins_and_bars(tmp_path):
    session, tick_dir, pin, report = _session(tmp_path)
    bars = session / "data" / "raw" / "mt5_fixture" / "EURUSD" / "bars" / "M5" / "history.npz"
    bars.parent.mkdir(parents=True)
    bars.write_bytes(b"retain bars")
    research = tmp_path / "research" / "ticks.npz"
    research.parent.mkdir()
    research.write_bytes(b"retain research")
    snapshot = session / "data" / "store" / "snapshots" / "SNAP_A.json"
    snapshot_before = snapshot.read_bytes()
    sizes = sum(p.stat().st_size for p in tick_dir.iterdir())
    result = _finish(session, report)
    assert result["status"] == "CLOSED"
    assert result["removed_files"] == 3
    assert result["removed_bytes"] == sizes
    assert not list(tick_dir.iterdir())
    assert bars.read_bytes() == b"retain bars"
    assert research.read_bytes() == b"retain research"
    assert snapshot.read_bytes() == snapshot_before
    assert (session / "reports" / "A.md").read_text() == "Report A"
    with pytest.raises(RetentionError, match="TICK_DATA_PURGED_BY_RETENTION"):
        assert_tick_available(pin)
    assert _finish(session, report)["already_closed"] is True


def test_newer_cycle_or_new_collection_invalidates_old_finish(tmp_path):
    session, tick_dir, pin, report = _session(tmp_path)
    append_jsonl(session / "cycles.jsonl", {"cycle_id": "CYCLE_B", "snapshot_id": "SNAP_B", "status": "ERROR"})
    assert _finish(session, report)["reason"] == "STALE_FINALIZATION_REQUEST"
    assert (tick_dir / "chunk.npz").exists()


def test_new_collection_revision_invalidates_old_finish_even_same_cycle(tmp_path):
    session, tick_dir, pin, report = _session(tmp_path)
    ensure_tick_generation(tick_dir, {"server": "fixture", "account_fingerprint": "demo"})
    assert _finish(session, report)["reason"] == "STALE_FINALIZATION_REQUEST"
    assert (tick_dir / "chunk.npz").exists()


def test_external_registered_consumer_prevents_purge(tmp_path):
    session, tick_dir, pin, report = _session(tmp_path)
    register_consumer(pin, tmp_path / "research" / "snapshot.json", "snapshot")
    result = _finish(session, report)
    assert result["reason"] == "SHARED_TICK_REFERENCE_OUTSIDE_SESSION"
    assert (tick_dir / "pending.npz").exists()


def test_report_must_exist_and_match_committed_bytes(tmp_path):
    session, tick_dir, pin, report = _session(tmp_path)
    (session / "reports" / "A.md").write_text("Changed after report commit", encoding="utf-8")
    assert _finish(session, report)["reason"] == "REPORT_FILE_NOT_COMMITTED"
    with pytest.raises(RetentionError, match="REPORT_FILE_NOT_COMMITTED"):
        record_report(session, "CYCLE_A", "SNAP_A", [session / "reports" / "missing.md"], None)
    assert (tick_dir / "chunk.npz").exists()


def test_tick_mutation_after_report_prevents_purge(tmp_path):
    session, tick_dir, pin, report = _session(tmp_path)
    (tick_dir / "new_file.npz").write_bytes(b"unreported tick file")
    assert _finish(session, report)["reason"] == "TICK_DATA_CHANGED_AFTER_REPORT"
    assert (tick_dir / "chunk.npz").exists()


def test_legacy_data_is_not_automatically_owned_or_deleted(tmp_path):
    session = tmp_path / "sessions" / "legacy"
    atomic_write_json(session / "session.json", {"session_id": "S_OLD"})
    old = session / "data" / "raw" / "old.npz"
    old.parent.mkdir(parents=True)
    old.write_bytes(b"protected history")
    with pytest.raises(RetentionError, match="LEGACY_TICK_OWNERSHIP_UNKNOWN"):
        init_retention(session, "S_OLD")
    result = finish_session(session, "C_OLD", "TG_" + "0" * 32)
    assert result["reason"] == "LEGACY_TICK_OWNERSHIP_UNKNOWN"
    assert old.read_bytes() == b"protected history"
    assert ensure_tick_generation(old.parent / "ticks") == {}


def test_purge_resumes_after_interrupted_unlink(tmp_path, monkeypatch):
    session, tick_dir, pin, report = _session(tmp_path)
    original = Path.unlink
    def fail_pending(path, *args, **kwargs):
        if path.name == "pending.npz":
            raise PermissionError("simulated busy file")
        return original(path, *args, **kwargs)
    monkeypatch.setattr(Path, "unlink", fail_pending)
    first = _finish(session, report)
    assert first["status"] == "CLEANUP_PARTIAL"
    assert not (tick_dir / "chunk.npz").exists()
    with pytest.raises(RetentionError, match="TICK_DATA_PURGED_BY_RETENTION"):
        assert_tick_available(pin)
    with pytest.raises(RetentionError, match="TICK_CLEANUP_IN_PROGRESS"):
        ensure_tick_generation(tick_dir)
    monkeypatch.setattr(Path, "unlink", original)
    second = _finish(session, report)
    assert second["status"] == "CLOSED"
    assert not list(tick_dir.iterdir())
    assert second["removed_files"] == 3


def test_retry_does_not_delete_new_or_changed_files(tmp_path, monkeypatch):
    session, tick_dir, pin, report = _session(tmp_path)
    original = Path.unlink
    def fail_pending(path, *args, **kwargs):
        if path.name == "pending.npz":
            raise PermissionError("simulated busy file")
        return original(path, *args, **kwargs)
    monkeypatch.setattr(Path, "unlink", fail_pending)
    assert _finish(session, report)["status"] == "CLEANUP_PARTIAL"
    monkeypatch.setattr(Path, "unlink", original)
    (tick_dir / "new.npz").write_bytes(b"must survive retry")
    assert _finish(session, report)["reason"] == "TICK_PURGE_PLAN_CHANGED"
    assert (tick_dir / "new.npz").exists()


def test_new_generation_same_directory_same_payload_keeps_old_pin_retired(tmp_path):
    session, tick_dir, old_pin, report = _session(tmp_path)
    payload = (tick_dir / "chunk.npz").read_bytes()
    assert _finish(session, report)["status"] == "CLOSED"
    meta = ensure_tick_generation(tick_dir, {"server": "fixture", "account_fingerprint": "demo"})
    assert meta["tick_generation_id"] != old_pin["tick_generation_id"]
    (tick_dir / "chunk.npz").write_bytes(payload)
    atomic_write_json(tick_dir / "checkpoint.json", {**meta, "chunks": [], "windows": {}})
    new_pin = {**meta, "chunk_dir": str(tick_dir)}
    assert_tick_available(new_pin)
    with pytest.raises(RetentionError, match="TICK_DATA_PURGED_BY_RETENTION"):
        assert_tick_available(old_pin)
    assert _finish(session, report)["reason"] == "STALE_FINALIZATION_REQUEST"
    assert (tick_dir / "chunk.npz").exists()


def test_owned_paths_cannot_escape_or_purge_parent(tmp_path):
    session, tick_dir, pin, report = _session(tmp_path)
    for bad in (session / "data", session / "data" / "raw", tmp_path / "research" / "ticks"):
        altered = dict(pin, chunk_dir=str(bad))
        with pytest.raises(RetentionError, match="TICK_PATH_"):
            assert_tick_available(altered)
    with pytest.raises(RetentionError, match="TICK_GENERATION_MISSING_OR_INVALID"):
        assert_tick_available(dict(pin, tick_generation_id="../../escape"))


def test_symlink_is_refused_even_when_target_is_inside_session(tmp_path):
    session, tick_dir, pin, report = _session(tmp_path)
    link = tick_dir / "link.npz"
    try:
        link.symlink_to(tick_dir / "chunk.npz")
    except OSError:
        pytest.skip("This Windows account cannot create symbolic links")
    with pytest.raises(RetentionError, match="RETENTION_REPARSE_POINT"):
        record_report(session, "CYCLE_A", "SNAP_A", [session / "reports" / "A.md"], None)
    assert "RETENTION_REPARSE_POINT" in _finish(session, report)["reason"]
    assert (tick_dir / "chunk.npz").exists()


@pytest.mark.skipif(os.name != "nt", reason="Windows deployment: util.file_lock has Windows timeout support")
def test_storage_lease_reentrant_and_blocks_other_process(tmp_path):
    session, tick_dir, pin, report = _session(tmp_path)
    script = "from quantmt5.retention import storage_lease,RetentionError\nimport sys\ntry:\n with storage_lease(sys.argv[1],timeout_s=.05): pass\nexcept RetentionError as e:\n print(e)\n"
    env = dict(os.environ, PYTHONPATH=str(Path(__file__).resolve().parents[1]))
    with storage_lease(tick_dir):
        with storage_lease(session / "data" / "store"):
            assert_tick_available(pin)
        child = subprocess.run([sys.executable, "-c", script, str(tick_dir)], env=env, capture_output=True, text=True, timeout=10)
        assert child.returncode == 0, child.stderr
        assert "TICK_STORAGE_BUSY" in child.stdout


def test_source_identity_mismatch_cannot_reuse_generation(tmp_path):
    session, tick_dir, pin, report = _session(tmp_path)
    with pytest.raises(RetentionError, match="TICK_SOURCE_IDENTITY_CHANGED"):
        ensure_tick_generation(tick_dir, {"server": "other", "account_fingerprint": "real"})
    assert (tick_dir / "chunk.npz").exists()


def test_nested_pending_and_conflict_directories_are_removed_for_next_generation(tmp_path):
    session, tick_dir, pin, report = _session(tmp_path)
    nested = tick_dir / "conflict" / "window" / "payload.npz"
    nested.parent.mkdir(parents=True)
    nested.write_bytes(b"conflict tick payload")
    report = record_report(session, "CYCLE_A", "SNAP_A", [session / "reports" / "A.md"], None)
    result = _finish(session, report)
    assert result["status"] == "CLOSED"
    assert result["removed_files"] == 4
    assert not list(tick_dir.iterdir())
    assert ensure_tick_generation(tick_dir)["tick_generation_id"] != pin["tick_generation_id"]


def test_collection_cannot_reopen_after_purge_plan_before_state_commit(tmp_path, monkeypatch):
    import quantmt5.retention as retention
    session, tick_dir, pin, report = _session(tmp_path)
    original = retention.atomic_write_json
    def fail_state(path, value):
        if Path(path).name == "state.json" and value.get("status") == "PURGING":
            raise OSError("simulated crash after tombstone")
        return original(path, value)
    monkeypatch.setattr(retention, "atomic_write_json", fail_state)
    assert _finish(session, report)["status"] == "REFUSED"
    with pytest.raises(RetentionError, match="TICK_CLEANUP_IN_PROGRESS"):
        ensure_tick_generation(tick_dir)
    assert (tick_dir / "chunk.npz").exists()
    monkeypatch.setattr(retention, "atomic_write_json", original)
    assert _finish(session, report)["status"] == "CLOSED"


def test_init_recovers_missing_state_only_for_empty_owned_data(tmp_path):
    session = tmp_path / "sessions" / "new"
    atomic_write_json(session / "session.json", {"session_id": "S_NEW"})
    owner = init_retention(session, "S_NEW")
    state = session / "data" / "retention" / "state.json"
    state.unlink()
    assert init_retention(session, "S_NEW") == owner
    assert state.exists()
    state.unlink()
    raw = session / "data" / "raw" / "existing.npz"
    raw.parent.mkdir()
    raw.write_bytes(b"cannot adopt")
    with pytest.raises(RetentionError, match="TICK_GENERATION_STATE_MISSING"):
        init_retention(session, "S_NEW")
    assert raw.read_bytes() == b"cannot adopt"


def test_finish_censors_unresolved_latest_outcomes_without_changing_known_results(tmp_path):
    session, tick_dir, pin, report = _session(tmp_path)
    journal = session / "data" / "store" / "journal" / "paper_mt5_fixture.jsonl"
    common = {"source_id": "mt5_fixture", "snapshot_id": "SNAP_A", "symbol": "EURUSD", "kind": "paper_signal"}
    rows = [
        dict(common, candidate_id="C_OPEN", revision_id="R_OPEN", replay={"status": "FILLED", "entry": 1.05, "exit_at": None, "net_R": .3}),
        dict(common, candidate_id="C_OPEN", revision_id="R_OPEN", kind="paper_outcome", outcome_state="UNRESOLVED",
             replay={"status": "FILLED", "entry": 1.05, "exit_at": None, "net_R": .7}),
        dict(common, candidate_id="C_CLOSED", revision_id="R_CLOSED", replay={"exit_at": "2026-11-08T12:59:00Z", "net_R": 1.4}),
        dict(common, candidate_id="C_FAKE_CLOSED", revision_id="R_FAKE_CLOSED", kind="paper_outcome", outcome_state="CLOSED",
             replay={"exit_at": None, "net_R": 1.2}),
        dict(common, candidate_id="C_WAIT", revision_id="R_WAIT", replay={"status": "WAITING", "net_R": None}),
        dict(common, candidate_id="C_OLD", revision_id="R_OLD", snapshot_id="SNAP_OTHER", replay={"exit_at": None, "net_R": None}),
    ]
    for row in rows:
        append_jsonl(journal, row)
    before = journal.read_bytes()
    result = _finish(session, report)
    assert result["status"] == "CLOSED"
    assert result["censored_count"] == 3
    assert journal.read_bytes().startswith(before)
    censored = read_jsonl(journal)[len(rows):]
    assert {r["revision_id"] for r in censored} == {"R_OPEN", "R_FAKE_CLOSED", "R_WAIT"}
    assert all(r["kind"] == "paper_outcome" and r["outcome_state"] == "CENSORED_AT_SESSION_END" for r in censored)
    assert all(r["replay"]["net_R"] is None and not r["replay"].get("exit_at") for r in censored)
    assert censored[0]["replay"]["entry"] == 1.05
    assert all(r["generation_id"] == report["generation_id"] for r in censored)
    assert _finish(session, report)["already_closed"] is True
    assert read_jsonl(journal) == rows + censored


def test_censor_is_idempotent_when_purge_is_interrupted(tmp_path, monkeypatch):
    session, tick_dir, pin, report = _session(tmp_path)
    journal = session / "data" / "store" / "journal" / "paper_mt5_fixture.jsonl"
    append_jsonl(journal, {"kind": "paper_signal", "source_id": "mt5_fixture", "snapshot_id": "SNAP_A",
                          "candidate_id": "C_OPEN", "revision_id": "R_OPEN", "replay": {"exit_at": None, "net_R": .2}})
    original = Path.unlink
    def fail_pending(path, *args, **kwargs):
        if path.name == "pending.npz":
            raise PermissionError("simulated busy file")
        return original(path, *args, **kwargs)
    monkeypatch.setattr(Path, "unlink", fail_pending)
    first = _finish(session, report)
    assert first["status"] == "CLEANUP_PARTIAL"
    assert first["censored_count"] == 1
    monkeypatch.setattr(Path, "unlink", original)
    second = _finish(session, report)
    assert second["status"] == "CLOSED"
    assert second["censored_count"] == 1
    assert len(read_jsonl(journal)) == 2


def test_journal_corruption_blocks_purge_before_any_deletion(tmp_path):
    session, tick_dir, pin, report = _session(tmp_path)
    journal = session / "data" / "store" / "journal" / "paper_mt5_fixture.jsonl"
    journal.parent.mkdir(parents=True)
    journal.write_text("bad complete json\n", encoding="utf-8")
    result = _finish(session, report)
    assert result["status"] == "REFUSED"
    assert "JOURNAL_CORRUPT" in result["reason"]
    assert (tick_dir / "chunk.npz").exists()
