"""Explicit end-of-session retirement of owned operational tick data.

Ownership and receipts live outside ticks/. Historical stores without an owner
are readable but never adopted or purged by this module.
"""
from __future__ import annotations

import contextlib
import datetime as dt
import json
import os
import re
import stat
import threading
import uuid
from pathlib import Path

from .util import (append_jsonl, atomic_write_json, file_lock, hash_obj, iso_utc, now_utc, parse_utc,
                   read_jsonl, repair_jsonl_tail, sha256_file, stable_id)

_ICT = dt.timezone(dt.timedelta(hours=7))
_LOCAL = threading.local()
_THREAD_LOCKS: dict[str, threading.RLock] = {}
_LOCK_GUARD = threading.Lock()
_GENERATION = re.compile(r"^TG_[0-9a-f]{32}$")


class RetentionError(ValueError):
    pass


def _read(path: Path) -> dict | None:
    path = _plain(path)
    return json.loads(path.read_text(encoding="utf-8")) if path.is_file() else None


def _inside(path: Path, root: Path) -> bool:
    return path == root or root in path.parents


def _plain(path: Path) -> Path:
    """Reject links before resolve, including Windows junctions/reparse points."""
    p = Path(os.path.abspath(path))
    for part in (p, *p.parents):
        try:
            info = part.lstat()
        except FileNotFoundError:
            continue
        if stat.S_ISLNK(info.st_mode) or getattr(info, "st_file_attributes", 0) & 0x400:
            raise RetentionError(f"RETENTION_REPARSE_POINT:{part}")
    return p.resolve()


def _managed(path: str | Path) -> tuple[Path, dict] | None:
    p = Path(os.path.abspath(path))
    for candidate in (p, *p.parents):
        owner_file = candidate / "retention" / "owner.json"
        if owner_file.is_file():
            data = _plain(candidate)
            owner = _read(owner_file)
            if not owner or owner.get("schema") != "quantmt5.tick-owner.v1" or Path(owner.get("data_root", "")).resolve() != data:
                raise RetentionError("RETENTION_OWNER_INVALID")
            session = _plain(Path(owner["session_dir"]))
            if data != session / "data" or (_read(session / "session.json") or {}).get("session_id") != owner.get("session_id"):
                raise RetentionError("RETENTION_OWNER_SESSION_MISMATCH")
            return data, owner
    return None


@contextlib.contextmanager
def storage_lease(path: str | Path, timeout_s: float = 30.0):
    """Serialize managed readers/writers/purge; reentrant only in this thread.

    A parent must release this lease before launching a child that needs it.
    Legacy/unmanaged stores keep their existing locking behavior.
    """
    managed = _managed(path)
    if managed is None:
        yield
        return
    data, _ = managed
    key = os.path.normcase(str(data))
    depths = getattr(_LOCAL, "depths", None)
    if depths is None:
        depths = _LOCAL.depths = {}
    if depths.get(key, 0):
        depths[key] += 1
        try:
            yield
        finally:
            depths[key] -= 1
        return
    with _LOCK_GUARD:
        lock = _THREAD_LOCKS.setdefault(key, threading.RLock())
    if not lock.acquire(timeout=timeout_s):
        raise RetentionError("TICK_STORAGE_BUSY")
    try:
        try:
            with file_lock(data / "retention" / "storage", timeout_s=timeout_s):
                depths[key] = 1
                try:
                    yield
                finally:
                    depths.pop(key, None)
        except TimeoutError as exc:
            raise RetentionError("TICK_STORAGE_BUSY") from exc
    finally:
        lock.release()


def _new_state() -> dict:
    return {"schema": "quantmt5.tick-generation.v1", "generation_id": "TG_" + uuid.uuid4().hex,
            "status": "OPEN", "created_at": iso_utc(now_utc()), "mutation_revision": 0, "tick_dirs": {}}


def init_retention(session_dir: str | Path, session_id: str) -> dict:
    """Opt a newly initialized, empty session into end-day tick retirement."""
    session = _plain(Path(session_dir))
    if (_read(session / "session.json") or {}).get("session_id") != session_id:
        raise RetentionError("RETENTION_OWNER_SESSION_MISMATCH")
    data = _plain(session / "data")
    owner_file = data / "retention" / "owner.json"
    if owner_file.exists():
        managed = _managed(data)
        if managed and managed[1]["session_id"] == session_id:
            with storage_lease(data):
                state_path = data / "retention" / "state.json"
                if not state_path.exists():
                    if any(p.name != "retention" for p in data.iterdir()):
                        raise RetentionError("TICK_GENERATION_STATE_MISSING")
                    atomic_write_json(state_path, _new_state())
            return managed[1]
        raise RetentionError("RETENTION_OWNER_ALREADY_EXISTS")
    if data.exists() and any(data.iterdir()):
        raise RetentionError("LEGACY_TICK_OWNERSHIP_UNKNOWN")
    owner = {"schema": "quantmt5.tick-owner.v1", "session_id": session_id,
             "session_dir": str(session), "data_root": str(data), "created_at": iso_utc(now_utc()),
             "policy": "EXPLICIT_FINISH_DELETE_OPERATIONAL_TICKS"}
    atomic_write_json(owner_file, owner)
    atomic_write_json(data / "retention" / "state.json", _new_state())
    return owner


def _tick_dir(data: Path, path: Path) -> Path:
    p = _plain(path)
    if not _inside(p, data):
        raise RetentionError("TICK_PATH_OUTSIDE_SESSION")
    relative = p.relative_to(data)
    if len(relative.parts) != 4 or relative.parts[0] != "raw" or relative.parts[-1] != "ticks":
        raise RetentionError("TICK_PATH_NOT_ALLOWLISTED")
    return p


def _identity(identity: dict | None) -> str | None:
    if identity is None:
        return None
    keys = ("executable", "data_path", "server", "account_fingerprint", "account_currency", "provider_kind")
    return hash_obj({k: identity.get(k) for k in keys})


def ensure_tick_generation(tick_dir: str | Path, identity: dict | None = None) -> dict:
    """Mark a collection mutation and return metadata for its tick checkpoint."""
    managed = _managed(tick_dir)
    if managed is None:
        return {}
    data, owner = managed
    with storage_lease(data):
        path = _tick_dir(data, Path(tick_dir))
        state_path = data / "retention" / "state.json"
        state = _read(state_path)
        if not state:
            raise RetentionError("TICK_GENERATION_STATE_MISSING")
        retired = _read(data / "retention" / "generations" / f"{state['generation_id']}.json")
        if retired and state["status"] != "CLOSED":
            raise RetentionError("TICK_CLEANUP_IN_PROGRESS")
        if state["status"] == "CLOSED":
            state = _new_state()
        if state["status"] != "OPEN":
            raise RetentionError("TICK_CLEANUP_IN_PROGRESS")
        relative = path.relative_to(data).as_posix()
        previous = state["tick_dirs"].get(relative)
        observed_identity = _identity(identity)
        if previous and previous.get("identity_hash") != observed_identity:
            raise RetentionError("TICK_SOURCE_IDENTITY_CHANGED")
        checkpoint = _read(path / "checkpoint.json")
        if checkpoint and checkpoint.get("tick_generation_id") != state["generation_id"]:
            raise RetentionError("LEGACY_TICK_GENERATION_UNOWNED")
        if not previous and path.exists() and any(path.iterdir()):
            raise RetentionError("LEGACY_TICK_GENERATION_UNOWNED")
        state["tick_dirs"][relative] = {"identity_hash": observed_identity}
        state["mutation_revision"] += 1
        atomic_write_json(state_path, state)
        return {"tick_generation_id": state["generation_id"], "retention_root": str(data),
                "retention_session_id": owner["session_id"]}


def _pin_owner(pin: dict) -> tuple[Path, dict, str] | None:
    declared = pin.get("retention_root")
    managed = _managed(declared or pin.get("chunk_dir", "."))
    generation = pin.get("tick_generation_id")
    if managed is None:
        if declared or generation:
            raise RetentionError("RETENTION_OWNER_MISSING")
        return None
    data, owner = managed
    if not generation or not _GENERATION.fullmatch(generation):
        raise RetentionError("TICK_GENERATION_MISSING_OR_INVALID")
    if declared and _plain(Path(declared)) != data:
        raise RetentionError("RETENTION_OWNER_INVALID")
    if pin.get("retention_session_id") != owner["session_id"]:
        raise RetentionError("RETENTION_OWNER_SESSION_MISMATCH")
    _tick_dir(data, Path(pin["chunk_dir"]))
    return data, owner, generation


def assert_tick_available(pin: dict) -> None:
    owner = _pin_owner(pin)
    if owner is None:
        return
    data, _, generation = owner
    with storage_lease(data):
        tombstone = _read(data / "retention" / "generations" / f"{generation}.json")
        if tombstone and tombstone.get("status") in ("PURGE_PLANNED", "PURGING", "CLEANUP_PARTIAL", "CLOSED"):
            raise RetentionError(f"TICK_DATA_PURGED_BY_RETENTION:{generation}")
        state = _read(data / "retention" / "state.json") or {}
        if state.get("generation_id") != generation:
            raise RetentionError("TICK_GENERATION_NOT_CURRENT")
        if state.get("status") != "OPEN":
            raise RetentionError(f"TICK_DATA_PURGED_BY_RETENTION:{generation}")


def register_consumer(pin: dict, consumer_path: str | Path, kind: str = "bundle") -> None:
    managed = _pin_owner(pin)
    if managed is None:
        return
    data, owner, generation = managed
    with storage_lease(data):
        assert_tick_available(pin)
        path = _plain(Path(consumer_path))
        journal = data / "retention" / "consumers.json"
        consumers = _read(journal) or {"schema": "quantmt5.tick-consumers.v1", "references": {}}
        key = hash_obj([generation, str(path), pin["chunk_dir"]])
        consumers["references"][key] = {"generation_id": generation, "consumer_path": str(path), "kind": kind,
                                         "tick_dir": str(_tick_dir(data, Path(pin["chunk_dir"]))),
                                         "outside_session": not _inside(path, Path(owner["session_dir"]))}
        atomic_write_json(journal, consumers)


def _inventory(data: Path, state: dict, with_hashes: bool = False) -> list[dict]:
    files = []
    for relative in sorted(state["tick_dirs"]):
        directory = _tick_dir(data, data / relative)
        if not directory.exists():
            continue
        for raw_path in sorted(directory.rglob("*")):
            path = _plain(raw_path)
            if not _inside(path, directory):
                raise RetentionError("TICK_PATH_OUTSIDE_SESSION")
            if path.is_dir():
                continue
            info = path.stat()
            if not stat.S_ISREG(info.st_mode):
                raise RetentionError("TICK_PATH_NOT_REGULAR_FILE")
            entry = {"path": path.relative_to(data).as_posix(), "bytes": info.st_size, "mtime_ns": info.st_mtime_ns}
            if with_hashes:
                entry["sha256"] = sha256_file(path)
            files.append(entry)
    return files


def _latest_cycle(session: Path) -> dict | None:
    records = read_jsonl(session / "cycles.jsonl")
    return records[-1] if records else None


def context_state_path(session: Path, cycle_id: str, snapshot_id: str) -> Path:
    """Opaque filenames prevent caller-supplied continuation IDs becoming paths."""
    return Path(session) / "reports" / ("context_" + hash_obj([cycle_id, snapshot_id]) + ".json")


def record_report(session_dir: str | Path, cycle_id: str, snapshot_id: str,
                  report_paths: list[str | Path], as_of: float | str | None) -> dict:
    """Commit the finalizable generation/revision only after report files exist."""
    session = _plain(Path(session_dir))
    managed = _managed(session / "data")
    if managed is None:
        return {"status": "UNMANAGED", "reason": "LEGACY_TICK_OWNERSHIP_UNKNOWN"}
    data, owner = managed
    with storage_lease(data):
        state = _read(data / "retention" / "state.json") or {}
        if state.get("status") != "OPEN":
            raise RetentionError("TICK_GENERATION_NOT_OPEN")
        latest = _latest_cycle(session)
        if not latest or latest.get("cycle_id") != cycle_id or latest.get("snapshot_id") != snapshot_id or latest.get("status") not in ("OK", "PARTIAL"):
            raise RetentionError("REPORT_NOT_LATEST_SUCCESSFUL_CYCLE")
        snapshot_path = data / "store" / "snapshots" / f"{snapshot_id}.json"
        snapshot = _read(snapshot_path)
        if not snapshot or snapshot.get("snapshot_id") != snapshot_id:
            raise RetentionError("REPORT_SNAPSHOT_MISSING")
        for pin in (snapshot.get("tick_versions") or {}).values():
            assert_tick_available(pin)
            if pin.get("tick_generation_id") != state["generation_id"]:
                raise RetentionError("REPORT_GENERATION_MISMATCH")
            register_consumer(pin, snapshot_path, "snapshot")
        reports = []
        for supplied in report_paths:
            path = _plain(Path(supplied))
            if not _inside(path, session / "reports") or not path.is_file():
                raise RetentionError("REPORT_FILE_NOT_COMMITTED")
            reports.append({"path": str(path), "sha256": sha256_file(path)})
        if not reports:
            raise RetentionError("REPORT_FILE_NOT_COMMITTED")
        timestamp = parse_utc(as_of) if isinstance(as_of, str) else (as_of if as_of is not None else now_utc())
        result = {"status": "REPORT_COMMITTED", "session_id": owner["session_id"], "cycle_id": cycle_id,
                  "snapshot_id": snapshot_id, "generation_id": state["generation_id"],
                  "mutation_revision": state["mutation_revision"], "reports": reports,
                  "local_day": dt.datetime.fromtimestamp(timestamp, _ICT).date().isoformat(),
                  "recorded_at": iso_utc(now_utc()), "inventory": _inventory(data, state)}
        atomic_write_json(data / "retention" / "latest_report.json", result)
        return {k: result[k] for k in ("status", "cycle_id", "snapshot_id", "generation_id", "local_day")}


def _refuse(reason: str, **extra) -> dict:
    return {"status": "REFUSED", "reason": reason, **extra}


def _censor_outcomes(data: Path, generation_id: str, cycle_id: str) -> list[dict]:
    """Append terminal, non-win/loss outcomes before the raw evidence is retired."""
    snapshots = set()
    for raw_path in sorted((data / "store" / "snapshots").glob("*.json")):
        snapshot = _read(_plain(raw_path)) or {}
        if any(pin.get("tick_generation_id") == generation_id for pin in (snapshot.get("tick_versions") or {}).values()):
            snapshots.add(snapshot.get("snapshot_id"))
    censored = []
    for raw_path in sorted((data / "store" / "journal").glob("paper_*.jsonl")):
        path = _plain(raw_path)
        with file_lock(path):
            repair_jsonl_tail(path)
            latest, terminal = {}, set()
            for row in read_jsonl(path):
                if row.get("kind") not in ("paper_signal", "paper_outcome") or not row.get("revision_id"):
                    continue
                key = (row.get("source_id"), row["revision_id"])
                latest[key] = row
                if (row.get("replay") or {}).get("exit_at") or row.get("outcome_state") == "CENSORED_AT_SESSION_END":
                    terminal.add(key)
                if row.get("outcome_state") == "CENSORED_AT_SESSION_END" and row.get("generation_id") == generation_id:
                    censored.append({"journal_path": str(path), "revision_id": row["revision_id"], "dedup_key": row["dedup_key"]})
            for key, row in latest.items():
                if key in terminal or row.get("snapshot_id") not in snapshots:
                    continue
                record = dict(row, kind="paper_outcome", outcome_state="CENSORED_AT_SESSION_END",
                              dedup_key=stable_id("PCENSOR", *key, generation_id), generation_id=generation_id,
                              cycle_id=cycle_id, recorded_at=iso_utc(now_utc()), reason="TICK_RETENTION_SESSION_END",
                              replay={**(row.get("replay") or {}), "net_R": None},
                              note="Raw ticks retired at explicit session end; unresolved evidence is not a win, loss, or breakeven.")
                append_jsonl(path, record, lock=False)
                censored.append({"journal_path": str(path), "revision_id": row["revision_id"], "dedup_key": record["dedup_key"]})
    return censored


def finish_session(session_dir: str | Path, expected_cycle_id: str, expected_generation_id: str,
                   expected_snapshot_id: str | None = None) -> dict:
    """Purge only explicitly owned ticks after a current, committed final report.

    The caller also holds the session runner lock, preventing a newer session
    cycle from starting while this storage transaction is finalized.
    """
    try:
        session = _plain(Path(session_dir))
        managed = _managed(session / "data")
        if managed is None:
            return _refuse("LEGACY_TICK_OWNERSHIP_UNKNOWN")
        data, owner = managed
        with storage_lease(data, timeout_s=0.25):
            return _finish_locked(data, owner, expected_cycle_id, expected_generation_id, expected_snapshot_id)
    except (RetentionError, OSError, ValueError) as exc:
        return _refuse(str(exc))


def _finish_locked(data: Path, owner: dict, cycle_id: str, generation_id: str, snapshot_id: str | None) -> dict:
    session = Path(owner["session_dir"])
    state_path = data / "retention" / "state.json"
    state = _read(state_path) or {}
    report = _read(data / "retention" / "latest_report.json") or {}
    latest = _latest_cycle(session) or {}
    if (not _GENERATION.fullmatch(generation_id or "") or state.get("generation_id") != generation_id
            or report.get("generation_id") != generation_id or report.get("cycle_id") != cycle_id
            or latest.get("cycle_id") != cycle_id or latest.get("status") not in ("OK", "PARTIAL")
            or latest.get("snapshot_id") != report.get("snapshot_id")
            or snapshot_id is not None and report.get("snapshot_id") != snapshot_id
            or state.get("mutation_revision") != report.get("mutation_revision")):
        return _refuse("STALE_FINALIZATION_REQUEST")
    context = _read(context_state_path(session, cycle_id, report.get("snapshot_id")))
    needs_context = (latest.get("analysis") or {}).get("stage") == "BASELINE"
    if ((needs_context and not context) or
            context is not None and context.get("context_state") not in ("COMPLETE", "PARTIAL_FAILED")):
        return _refuse("CONTEXT_PENDING")
    if context is not None:
        continuation = context.get("continuation") or {}
        if any(continuation.get(k) != v for k, v in (
                ("cycle_id", cycle_id), ("snapshot_id", report.get("snapshot_id")),
                ("generation_id", generation_id), ("mutation_revision", state.get("mutation_revision")))):
            return _refuse("CONTEXT_IDENTITY_MISMATCH")
    receipt_path = data / "retention" / "generations" / f"{generation_id}.json"
    receipt = _read(receipt_path)
    if state.get("status") == "CLOSED":
        return dict(receipt or {}, status="CLOSED", already_closed=True)
    if state.get("status") not in ("OPEN", "PURGING", "CLEANUP_PARTIAL"):
        return _refuse("TICK_GENERATION_STATE_INVALID")
    for report_file in report.get("reports", []):
        path = _plain(Path(report_file["path"]))
        if not _inside(path, session / "reports") or not path.is_file() or sha256_file(path) != report_file["sha256"]:
            return _refuse("REPORT_FILE_NOT_COMMITTED")
    consumers = (_read(data / "retention" / "consumers.json") or {}).get("references", {})
    outside = [r["consumer_path"] for r in consumers.values() if r.get("generation_id") == generation_id
               and (r.get("outside_session") or not _inside(Path(r["consumer_path"]).resolve(), session))]
    if outside:
        return _refuse("SHARED_TICK_REFERENCE_OUTSIDE_SESSION", consumers=outside)
    if receipt is None:
        if _inventory(data, state) != report.get("inventory"):
            return _refuse("TICK_DATA_CHANGED_AFTER_REPORT")
        files = _inventory(data, state, with_hashes=True)
        receipt = {"schema": "quantmt5.tick-retirement.v1", "status": "PURGE_PLANNED", "session_id": owner["session_id"],
                   "cycle_id": cycle_id, "snapshot_id": report["snapshot_id"], "generation_id": generation_id,
                   "local_day": report["local_day"], "planned_at": iso_utc(now_utc()), "files": files,
                   "planned_bytes": sum(f["bytes"] for f in files), "planned_files": len(files),
                   "reports": report["reports"], "raw_tick_replay_available": False,
                   "outcome_note": "Only previously finalized outcomes remain known; unresolved paths are censored after purge."}
        atomic_write_json(receipt_path, receipt)
    planned = {f["path"]: f for f in receipt["files"]}
    actual = _inventory(data, state)
    for f in actual:
        expected = planned.get(f["path"])
        if not expected or f["bytes"] != expected["bytes"] or f["mtime_ns"] != expected["mtime_ns"]:
            return _refuse("TICK_PURGE_PLAN_CHANGED")
        if sha256_file(data / f["path"]) != expected["sha256"]:
            return _refuse("TICK_PURGE_PLAN_CHANGED")
    receipt["censored_outcomes"] = _censor_outcomes(data, generation_id, cycle_id)
    receipt["censored_count"] = len(receipt["censored_outcomes"])
    state["status"] = "PURGING"
    receipt["status"] = "PURGING"
    atomic_write_json(state_path, state)
    atomic_write_json(receipt_path, receipt)
    try:
        for item in receipt["files"]:
            path = _plain(data / item["path"])
            directory = next((_tick_dir(data, data / d) for d in state["tick_dirs"] if _inside(path, data / d)), None)
            if directory is None or path == directory or not _inside(path, directory):
                raise RetentionError("TICK_PATH_OUTSIDE_SESSION")
            if path.exists():
                if not path.is_file() or path.stat().st_size != item["bytes"] or sha256_file(path) != item["sha256"]:
                    raise RetentionError("TICK_PURGE_PLAN_CHANGED")
                path.unlink()
        if _inventory(data, state):
            raise RetentionError("TICK_FILES_REMAIN_AFTER_PURGE")
        for relative in state["tick_dirs"]:
            directory = _tick_dir(data, data / relative)
            for path in sorted(directory.rglob("*"), key=lambda p: len(p.parts), reverse=True):
                _plain(path).rmdir()
    except (OSError, RetentionError) as exc:
        receipt.update(status="CLEANUP_PARTIAL", reason=str(exc), updated_at=iso_utc(now_utc()))
        state["status"] = "CLEANUP_PARTIAL"
        atomic_write_json(receipt_path, receipt)
        atomic_write_json(state_path, state)
        return receipt
    receipt.update(status="CLOSED", completed_at=iso_utc(now_utc()),
                   removed_files=receipt["planned_files"], removed_bytes=receipt["planned_bytes"])
    state["status"] = "CLOSED"
    atomic_write_json(receipt_path, receipt)
    atomic_write_json(state_path, state)
    return receipt
