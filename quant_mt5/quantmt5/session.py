"""B6C1 durable paper session (read-only; no orders, no LLM loop).

A session lives in <root>/sessions/<name>/:
  session.json      frozen at init (engine/config hashes, terminal, symbols, mode, FTMO selection, risk, cadence, protocol dates)
  identity_pin.json written once at the first successful cycle; every later cycle must match (else HALT)
  protocol.json     written once when the first successful NATIVE cycle happens (prospective_start); PENDING before
  runner.lock       single writer: {pid, process create time, exe}; stale lock recovered only after identity check
  health.json       heartbeat / last attempt / last success / counts / latest snapshot+bundle / current cycle / state
  cycles.jsonl      append-only cycle records (dedup by cycle_id; completed cycles are never re-run)
  events.jsonl      append-only runner events (start, stop, stale-lock recovery, halt)
  runner.log        bounded (rotated) text log
  data/             paper_run output root: raw/<source_id>, bundles/CFGB_*, store/ (snapshots, journal/paper_<source_id>.jsonl)
Each cycle runs `paper-run` in a CHILD process with a hard timeout (child tree killed on timeout). Cadence follows closed
M5 bars. Market closed → cycle recorded SKIPPED_MARKET_CLOSED without touching the source."""
from __future__ import annotations

import ctypes
import datetime as dt
import json
import math
import os
import subprocess
import sys
import time
from pathlib import Path

from .util import (PROJECT_DIR, append_jsonl, atomic_write_json, file_lock, iso_utc, now_utc, read_jsonl, repair_jsonl_tail,
                   stable_id, write_immutable_json)

ICT = dt.timezone(dt.timedelta(hours=7), "Asia/Ho_Chi_Minh")
HALT_REASONS = ("SOURCE_IDENTITY_NOT_SESSION_PINNED", "ACCOUNT_TRADE_MODE_NOT_ALLOWED", "JOURNAL_CORRUPT", "ENGINE_OR_CONFIG_CHANGED",
                "SOURCE_NAMESPACE_IDENTITY_CLASH", "SOURCE_CHANGED_DURING_BATCH", "CLOCK_CONFLICT", "CLOCK_PROFILE_CHANGED_FOR_STORE")
COMPLETED = ("OK", "PARTIAL", "SKIPPED_MARKET_CLOSED")
ENTRY = PROJECT_DIR / "run_quant.py"
DEMO_TRADE_MODE = 0              # MT5 ACCOUNT_TRADE_MODE_DEMO (CONTEST=1, REAL=2)
LOG_MAX_BYTES = 512 * 1024


def sdir(root, name) -> Path:
    if not name or Path(name).name != name or name in (".", "..") or any(x in name for x in ('/', '\\', ':')):
        raise ValueError("INVALID_SESSION_NAME")
    return Path(root) / "sessions" / name


def _read(p: Path):
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else None


# ------------------------------------------------------------------ process identity (Windows API, no psutil)
def proc_identity(pid: int) -> dict | None:
    """{'alive', 'create_time', 'exe'} for a pid, or None if it cannot be opened (gone)."""
    if os.name != "nt":
        try:
            os.kill(pid, 0)
            return {"alive": True, "create_time": None, "exe": None}
        except OSError:
            return None
    k = ctypes.windll.kernel32
    h = k.OpenProcess(0x1000, False, int(pid))           # PROCESS_QUERY_LIMITED_INFORMATION
    if not h:
        return None
    try:
        code = ctypes.c_ulong()
        k.GetExitCodeProcess(h, ctypes.byref(code))
        c, e, kt, ut = (ctypes.c_ulonglong() for _ in range(4))
        k.GetProcessTimes(h, ctypes.byref(c), ctypes.byref(e), ctypes.byref(kt), ctypes.byref(ut))
        buf = ctypes.create_unicode_buffer(1024)
        size = ctypes.c_ulong(1024)
        k.QueryFullProcessImageNameW(h, 0, buf, ctypes.byref(size))
        return {"alive": code.value == 259, "create_time": int(c.value), "exe": buf.value}
    finally:
        k.CloseHandle(h)


def _terminate(pid: int) -> bool:
    k = ctypes.windll.kernel32
    h = k.OpenProcess(0x0001, False, int(pid))           # PROCESS_TERMINATE
    if not h:
        return False
    try:
        return bool(k.TerminateProcess(h, 1))
    finally:
        k.CloseHandle(h)


def _kill_tree(pid: int) -> None:
    """Our own child process tree only (pid obtained from our Popen)."""
    subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"], capture_output=True)


# ------------------------------------------------------------------ init
def init_session(root, name: str, terminal_path: str, symbol_map: dict, *, mode: str = "DEMO_NATIVE", cadence_s: int = 300,
                 offset_s: int = 20, cycle_timeout_s: int = 600, ftmo_program: str = "1-Step", selection_ref: dict | None = None,
                synthetic_fixture: str | None = None, lookback_days: float = 35, tick_minutes: float = 240) -> dict:
    from .config import config_hash
    from .util import engine_hash
    from .universe import validate_map
    symbol_map = validate_map(symbol_map)
    if mode not in ("DEMO_NATIVE", "SYNTHETIC_FIXTURE"):
        raise ValueError("MODE_INVALID")
    if mode == "SYNTHETIC_FIXTURE" and not synthetic_fixture:
        raise ValueError("SYNTHETIC_FIXTURE_REQUIRED")
    now = dt.datetime.now(ICT)
    smoke = now.replace(hour=23, minute=0, second=0, microsecond=0)
    if smoke <= now:
        smoke += dt.timedelta(days=1)
    nxt = (now + dt.timedelta(days=1)).date()
    while nxt.weekday() >= 5:
        nxt += dt.timedelta(days=1)
    rec = {"schema": "quantmt5.session.v1", "session_name": name, "session_id": stable_id("SESS", name, iso_utc(now.timestamp())),
           "created_at": iso_utc(now.timestamp()), "mode": mode, "terminal_path": terminal_path, "symbol_map": symbol_map,
           "require_trade_mode": DEMO_TRADE_MODE if mode == "DEMO_NATIVE" else None,
           "synthetic_fixture": synthetic_fixture, "cadence": {"bar_s": cadence_s, "offset_after_close_s": offset_s},
           "cycle_timeout_s": cycle_timeout_s, "collect": {"lookback_days": lookback_days, "tick_minutes": tick_minutes},
           "engine_hash": engine_hash(), "config_hash": config_hash(),
           "ftmo": {"program": ftmo_program, "environment": "MT5_DEMO" if mode == "DEMO_NATIVE" else "SYNTHETIC",
                    "selection_ref": selection_ref, "rule_regime": "UNKNOWN (Best Day vs Consistency depends on the order date; no order)",
                    "initial_capital": "UNCONFIGURED", "challenge_evaluation": "UNCONFIGURED (B6C2)"},
           "risk": "UNCONFIGURED (no lot sizing / no money at risk; R-normalised paper only)",
           "outcome_tracking": "APPEND_ONLY_AS_OF_UPDATES; unresolved outcomes censored at explicit finish; no live fills or edge claimed",
           "protocol": {"smoke_checkpoint_local": smoke.isoformat(), "next_review_local_date": nxt.isoformat(),
                        "prospective_start": "PENDING until the first successful NATIVE demo cycle (see protocol.json)"},
           "orders": "NEVER: no order_send/order_check; the user places demo trades manually if desired"}
    d = sdir(root, name)
    d.mkdir(parents=True, exist_ok=True)
    p = d / "session.json"
    if p.exists():
        old = _read(p)
        if (d / "data" / "retention" / "owner.json").is_file():
            from .retention import init_retention
            init_retention(d, old["session_id"])
        return dict(old, already_initialised=True)
    write_immutable_json(p, rec)
    from .retention import init_retention
    init_retention(d, rec["session_id"])
    _event(d, "INIT", {"session_id": rec["session_id"], "mode": mode})
    return dict(rec, already_initialised=False)


# ------------------------------------------------------------------ lock
def _lock_path(d: Path) -> Path:
    return d / "runner.lock"


def acquire_lock(d: Path) -> dict:
    me = proc_identity(os.getpid()) or {}
    rec = {"pid": os.getpid(), "create_time": me.get("create_time"), "exe": me.get("exe"), "acquired_at": iso_utc(now_utc())}
    lp = _lock_path(d)
    for _ in range(2):
        try:
            fd = os.open(lp, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(rec, f)
            return {"acquired": True, "lock": rec}
        except FileExistsError:
            try:
                held = json.loads(lp.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                held = {}
            ident = proc_identity(int(held.get("pid", 0))) if held.get("pid") else None
            if ident and ident["alive"] and ident["create_time"] == held.get("create_time"):
                return {"acquired": False, "reason": "LOCK_HELD_BY_LIVE_RUNNER", "holder": held}
            stale = lp.with_name(f"runner.lock.stale_{int(now_utc() * 1000)}.json")
            os.replace(lp, stale)                         # audit copy; the holder process (if any) is NOT touched
            _event(d, "STALE_LOCK_RECOVERED", {"previous": held, "pid_identity_now": ident, "saved_as": stale.name})
    return {"acquired": False, "reason": "LOCK_RACE"}


def release_lock(d: Path) -> None:
    lp = _lock_path(d)
    try:
        held = json.loads(lp.read_text(encoding="utf-8"))
        if held.get("pid") == os.getpid():
            lp.unlink()
    except (OSError, ValueError):
        pass


# ------------------------------------------------------------------ logs / health / events
def _event(d: Path, kind: str, data: dict) -> None:
    append_jsonl(d / "events.jsonl", {"kind": kind, "at": iso_utc(now_utc()), "pid": os.getpid(), **data})


def _log(d: Path, msg: str) -> None:
    p = d / "runner.log"
    if p.exists() and p.stat().st_size > LOG_MAX_BYTES:
        for i in (2, 1):
            src = p.with_name(f"runner.log.{i}")
            if src.exists():
                os.replace(src, p.with_name(f"runner.log.{i + 1}"))
        os.replace(p, p.with_name("runner.log.1"))
    with open(p, "a", encoding="utf-8") as f:
        f.write(f"{iso_utc(now_utc())} pid={os.getpid()} {msg}\n")


def _health(d: Path, **kw) -> dict:
    p = d / "health.json"
    h = _read(p) or {}
    h.update(kw)
    h["heartbeat"] = iso_utc(now_utc())
    atomic_write_json(p, h)
    return h


# ------------------------------------------------------------------ cadence
def next_cycle_end(now: float, bar_s: int, offset_s: int) -> float:
    """Planned decision time = latest bar close + offset not in the past."""
    nxt = (now // bar_s) * bar_s + offset_s
    return nxt if nxt >= now else nxt + bar_s


def market_open(sess: dict | None, t: float) -> bool | None:
    if not sess:
        return None
    import numpy as np
    from .coverage import scheduled_open
    return bool(scheduled_open(np.array([int(t)]), sess)[0])


# ------------------------------------------------------------------ one cycle (child process)
def _child_argv(s: dict, d: Path, end_utc: float) -> list[str]:
    syms = ",".join(f"{c}={n}" for c, n in s["symbol_map"].items())
    a = [sys.executable, "-I", str(ENTRY), "paper-run", "--terminal-path", s["terminal_path"], "--symbols", syms,
         "--out-root", str(d / "data"), "--lookback-days", str(s["collect"]["lookback_days"]),
         "--tick-minutes", str(s["collect"]["tick_minutes"]), "--end", iso_utc(end_utc)]
    if s.get("require_trade_mode") is not None:
        a += ["--require-trade-mode", str(s["require_trade_mode"])]
    pin = _read(d / "identity_pin.json")
    if pin:
        a += ["--expect-identity", json.dumps(pin["identity"])]
        if pin.get("clock_profile"):
            a += ["--clock-profile", pin["clock_profile"]]
    if s.get("synthetic_fixture"):
        a += ["--synthetic-fixture", s["synthetic_fixture"]]
    a += ["--max-cards", str(s.get("max_cards", 8))]
    a += ["--analysis-mode", s.get("analysis_mode", "full")]
    return a


def _cycle_id(s: dict, end_utc: float) -> str:
    parts = [s["session_id"], iso_utc(end_utc)]
    if s.get("focused_symbols"):
        parts.append(sorted(s["focused_symbols"]))
    return stable_id("CYC", *parts)


def run_cycle(d: Path, s: dict, end_utc: float, stop_check=lambda: False) -> dict:
    cid = _cycle_id(s, end_utc)
    rec = {"cycle_id": cid, "planned_end_utc": iso_utc(end_utc), "started_at": iso_utc(now_utc())}
    scheduled = []
    try:
        from .config import symbol_profiles
        profiles = symbol_profiles()["symbols"]
        scheduled = [market_open((profiles.get(sym) or {}).get("session"), end_utc) for sym in s["symbol_map"]]
    except Exception:
        pass
    if scheduled and all(x is False for x in scheduled) and s["mode"] == "DEMO_NATIVE":
        rec.update({"status": "SKIPPED_MARKET_CLOSED", "reason": "schedule (legacy session, ASSUMED) says closed; source not touched",
                    "finished_at": iso_utc(now_utc())})
        return rec
    argv = _child_argv(s, d, end_utc)
    env = dict(os.environ)
    t0 = time.monotonic()
    cdir = d / "cycles"
    cdir.mkdir(exist_ok=True)
    tag = f"{cid}_{int(now_utc() * 1000)}"
    out_p, err_p = cdir / f"{tag}.stdout.json", cdir / f"{tag}.stderr.txt"
    fo, fe = open(out_p, "wb"), open(err_p, "wb")          # files, not pipes: a large envelope can never block the child
    p = subprocess.Popen(argv, stdout=fo, stderr=fe, stdin=subprocess.DEVNULL, env=env)
    ci = proc_identity(p.pid) or {}
    _health(d, current_cycle={"cycle_id": cid, "planned_end_utc": rec["planned_end_utc"], "child_pid": p.pid,
                              "child_create_time": ci.get("create_time"), "started_at": rec["started_at"]})
    timed_out = interrupted = False
    while p.poll() is None:
        if time.monotonic() - t0 > s["cycle_timeout_s"]:
            timed_out = True
            _kill_tree(p.pid)
            break
        if stop_check():
            interrupted = True
            _kill_tree(p.pid)
            break
        _health(d, phase="IN_CYCLE", in_cycle_s=round(time.monotonic() - t0, 1))
        time.sleep(0.5)
    p.wait()
    fo.close()
    fe.close()
    out, err = out_p.read_bytes(), err_p.read_bytes()
    rec.update({"child_pid": p.pid, "exit_code": p.returncode, "duration_s": round(time.monotonic() - t0, 2), "finished_at": iso_utc(now_utc()),
                "stderr_tail": err.decode("utf-8", "replace")[-800:], "child_stdout": out_p.name, "child_stderr": err_p.name})
    if timed_out:
        rec.update({"status": "TIMEOUT", "reason": f"CYCLE_TIMEOUT_AFTER_{s['cycle_timeout_s']}s (child tree killed)"})
        return rec
    if interrupted:
        rec.update({"status": "STOPPED_INTERRUPTED", "reason": "STOP_REQUESTED_DURING_CYCLE (child tree killed; cycle not completed, will be retried)"})
        return rec
    try:
        env_out = json.loads(out.decode("utf-8"))
        data = env_out.get("data") or {}
    except ValueError:
        rec.update({"status": "ERROR", "reason": f"CHILD_EXIT_{p.returncode}_NO_ENVELOPE"})
        return rec
    st = data.get("status") or env_out.get("status")
    errs = env_out.get("errors") or []
    reason = data.get("reason") or (errs[0].get("reason") if errs and isinstance(errs[0], dict) else None)
    scan = ((data.get("scan") or {}).get("data")) or {}
    rec.update({"paper_status": st, "reason": reason, "collect_status": data.get("collect_status"), "provider_kind": data.get("provider_kind"),
                "source_id": data.get("source_id"), "identity": data.get("identity"), "clock": data.get("clock"), "bundle_id": (data.get("bundle") or {}).get("bundle_id"),
                "snapshot_id": scan.get("snapshot_id"), "scan_status": scan.get("scan_status"), "signals_written": scan.get("signals_written"),
                "signals_duplicate": scan.get("signals_duplicate"), "observation_written": scan.get("observation_written"),
                "replay_errors": len(scan.get("replay_errors") or []), "symbols": scan.get("symbols"),
                "fabio": scan.get("fabio") or {},
                "analysis": scan.get("analysis") or {}, "timings_s": data.get("timings_s") or {},
                "cache_stats": scan.get("cache_stats") or {}, "requested_symbols": list(s["symbol_map"]),
                "scan_reason": (data.get("scan") or {}).get("errors")})
    if st == "PENDING_LIVE_SOURCE_NOT_RUNNING":
        rec["status"] = "PENDING_SOURCE"
    elif any(h in str(reason) or h in json.dumps(rec.get("scan_reason")) for h in HALT_REASONS):
        rec["status"] = "HALT"
    elif st in ("OK", "PARTIAL") and scan:
        rec["status"] = st
    else:
        rec["status"] = "ERROR"
    return rec


# ------------------------------------------------------------------ runner loop
def run(root, name: str, *, max_cycles: int | None = None, simulate_ends: list[float] | None = None, until_utc: float | None = None,
        max_attempts_per_cycle: int = 3, backoff_base_s: float = 5, backoff_max_s: float = 300, idle_sleep_s: float = 1.0) -> dict:
    from .config import config_hash
    from .util import engine_hash
    d = sdir(root, name)
    s = _read(d / "session.json")
    if not s:
        return {"status": "ERROR", "reason": "SESSION_NOT_INITIALISED"}
    lk = acquire_lock(d)
    if not lk["acquired"]:
        return {"status": "REFUSED", "reason": lk["reason"], "holder": lk.get("holder")}
    me = lk["lock"]
    stop_file = d / "stop.request"
    if stop_file.exists():
        os.replace(stop_file, d / f"stop.request.consumed_{int(now_utc() * 1000)}")
    _event(d, "START", {"lock": me})
    _log(d, f"START session={s['session_id']} mode={s['mode']}")
    h = _health(d, state="RUNNING", session_id=s["session_id"], pid=me["pid"], process_create_time=me["create_time"], exe=me["exe"],
                started_at=me["acquired_at"], mode=s["mode"], stop_requested=False, current_cycle=None, phase="STARTING")
    counts = dict(h.get("counts") or {})
    state, reason, n_run, consecutive_err = "RUNNING", None, 0, 0
    ends = list(simulate_ends) if simulate_ends is not None else None
    try:
        if engine_hash() != s["engine_hash"] or config_hash() != s["config_hash"]:
            state, reason = "HALTED", "ENGINE_OR_CONFIG_CHANGED"
            return {"status": state, "reason": reason}
        cyc_path = d / "cycles.jsonl"
        while True:
            if stop_file.exists():
                state, reason = "STOPPED", "STOP_REQUESTED"
                break
            if max_cycles is not None and n_run >= max_cycles:
                state, reason = "COMPLETED", "MAX_CYCLES"
                break
            if until_utc is not None and now_utc() >= until_utc:
                state, reason = "COMPLETED", "UNTIL_REACHED"
                break
            if ends is not None:
                if not ends:
                    state, reason = "COMPLETED", "SIMULATED_SCHEDULE_DONE"
                    break
                end = ends[0]
            else:
                end = next_cycle_end(now_utc(), s["cadence"]["bar_s"], s["cadence"]["offset_after_close_s"])
                while now_utc() < end:
                    if stop_file.exists():
                        break
                    _health(d, phase="WAITING_NEXT_BAR", next_cycle_at=iso_utc(end))
                    time.sleep(min(idle_sleep_s, max(0.05, end - now_utc())))
                if stop_file.exists():
                    continue
            cid = stable_id("CYC", s["session_id"], iso_utc(end))
            with file_lock(cyc_path):
                repair_jsonl_tail(cyc_path)
                prior = [c for c in read_jsonl(cyc_path) if c["cycle_id"] == cid]
            if any(c["status"] in COMPLETED for c in prior):
                if ends is not None:
                    ends.pop(0)
                _log(d, f"SKIP completed cycle {cid}")
                continue
            if ends is not None and len(prior) >= max_attempts_per_cycle:
                append_jsonl(cyc_path, {"cycle_id": cid, "planned_end_utc": iso_utc(end), "status": "GIVEN_UP",
                                        "reason": f"{len(prior)} attempts", "at": iso_utc(now_utc())})
                ends.pop(0)
                continue
            _health(d, phase="IN_CYCLE", last_attempt=iso_utc(now_utc()))
            rec = run_cycle(d, s, end, stop_check=stop_file.exists)
            rec["attempt"] = len(prior) + 1
            append_jsonl(cyc_path, rec)
            n_run += 1
            counts[rec["status"]] = counts.get(rec["status"], 0) + 1
            _log(d, f"CYCLE {cid} end={rec['planned_end_utc']} status={rec['status']} reason={rec.get('reason')}")
            upd = {"counts": counts, "current_cycle": None, "last_cycle": {k: rec.get(k) for k in ("cycle_id", "planned_end_utc", "status", "reason",
                                                                                                    "snapshot_id", "bundle_id", "duration_s")}}
            if rec["status"] == "STOPPED_INTERRUPTED":
                state, reason = "STOPPED", "STOP_REQUESTED_DURING_CYCLE"
                break
            if rec["status"] in COMPLETED:
                consecutive_err = 0
                upd.update({"last_success": rec["finished_at"], "latest_snapshot": rec.get("snapshot_id") or h.get("latest_snapshot"),
                            "latest_bundle": rec.get("bundle_id"), "source_id": rec.get("source_id"), "provider_kind": rec.get("provider_kind"),
                            "source_fingerprint": (rec.get("identity") or {}).get("account_fingerprint")})
                _after_success(d, rec, cid)
                if ends is not None:
                    ends.pop(0)
            elif rec["status"] == "HALT":
                state, reason = "HALTED", rec.get("reason")
                _health(d, **upd)
                break
            else:
                consecutive_err += 1
                wait = min(backoff_max_s, backoff_base_s * (2 ** (consecutive_err - 1)))
                upd.update({"backoff_s": wait, "last_error": rec.get("reason") or rec["status"]})
                _health(d, **upd)
                if ends is None:
                    t_end = now_utc() + wait
                    while now_utc() < t_end and not stop_file.exists():
                        _health(d, phase="BACKOFF", backoff_until=iso_utc(t_end))
                        time.sleep(min(idle_sleep_s, max(0.05, t_end - now_utc())))
                else:
                    time.sleep(min(wait, 0.2))
                continue
            _health(d, **upd)
        return {"status": state, "reason": reason, "cycles_run": n_run, "counts": counts}
    except Exception as e:          # never die silently: health + event
        state, reason = "CRASHED", f"{type(e).__name__}: {e}"
        raise
    finally:
        _health(d, state=state, stop_reason=reason, phase="EXITED", exited_at=iso_utc(now_utc()), current_cycle=None)
        _event(d, "EXIT", {"state": state, "reason": reason})
        _log(d, f"EXIT state={state} reason={reason}")
        release_lock(d)


# ------------------------------------------------------------------ ON_DEMAND (one bounded call, then exit)
def _after_success(d: Path, rec: dict, cid: str) -> None:
    if rec.get("identity") and not (d / "identity_pin.json").exists():
        ck = rec.get("clock") or {}
        # the clock is pinned only when a fresh probe resolved it (an UNRESOLVED default is never pinned)
        cp = ck.get("profile") if str(ck.get("clock_profile_status", "")).startswith("ASSUMED_FROM_CURRENT_PROBE") else None
        write_immutable_json(d / "identity_pin.json", {"identity": rec["identity"], "pinned_at": iso_utc(now_utc()),
                                                        "cycle_id": cid, "source_id": rec.get("source_id"),
                                                        "clock_profile": cp, "clock_at_pin": ck or None})
    if rec.get("provider_kind") == "NATIVE_TERMINAL" and rec["status"] in ("OK", "PARTIAL") and not (d / "protocol.json").exists():
        write_immutable_json(d / "protocol.json", {"prospective_start": rec["finished_at"], "first_native_cycle": cid,
                                                   "note": "forward observation starts here; earlier history is warmup, not forward"})


def bundle_env(d: Path, bundle_id: str | None = None) -> dict | None:
    """Env for running quant commands inside the session's (latest or given) source bundle."""
    cyc = [c for c in read_jsonl(d / "cycles.jsonl") if c.get("bundle_id")] if (d / "cycles.jsonl").exists() else []
    bid = bundle_id or (cyc[-1]["bundle_id"] if cyc else None)
    if not bid:
        return None
    return dict(os.environ, QUANTMT5_CONFIG_DIR=str(d / "data" / "bundles" / bid), QUANTMT5_STORE=str(d / "data" / "store"))


def exec_in_bundle(root, name: str, args: list[str], bundle_id: str | None = None, timeout_s: float = 300) -> tuple[int, dict | str]:
    d = sdir(root, name)
    if bundle_id is None and "--snapshot" in args:          # use the bundle the snapshot was taken with (pinned)
        snap = _read(d / "data" / "store" / "snapshots" / f"{args[args.index('--snapshot') + 1]}.json")
        bundle_id = ((snap or {}).get("config_bundle") or {}).get("bundle_id")
    env = bundle_env(d, bundle_id)
    if env is None:
        return 2, {"status": "ERROR", "errors": [{"reason": "NO_BUNDLE_YET: run `session once` first"}]}
    p = subprocess.Popen([sys.executable, "-I", str(ENTRY), *args], env=env, stdout=subprocess.PIPE,
                         stderr=subprocess.PIPE, stdin=subprocess.DEVNULL, start_new_session=os.name != "nt")
    try:
        stdout, _ = p.communicate(timeout=timeout_s)
    except subprocess.TimeoutExpired:
        try:
            if os.name == "nt":
                killed = subprocess.run(["taskkill", "/PID", str(p.pid), "/T", "/F"], capture_output=True, timeout=10)
                if killed.returncode:
                    if p.poll() is None:
                        p.kill()
                    p.communicate(timeout=10)
                    raise RuntimeError("CONTEXT_CHILD_TREE_TERMINATION_UNVERIFIED")
            else:
                import signal
                try:
                    os.killpg(p.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
            p.communicate(timeout=10)  # Reap before allowing any final report or retention.
        except Exception as exc:
            # A cleanup timeout is NOT the successfully-reaped optional timeout below.
            raise RuntimeError("CONTEXT_CHILD_TREE_TERMINATION_UNVERIFIED") from exc
        raise
    out = stdout.decode("utf-8", "replace")
    try:
        return p.returncode, json.loads(out)
    except ValueError:
        return p.returncode, out


def _pinned_file_refs(snap: dict, d: Path) -> list[dict]:
    """Use declared pins, not newly observed hashes, as the source integrity oracle."""
    from .util import WORKSPACE_DIR, sha256_file
    refs = {}
    def visit(node):
        if isinstance(node, dict):
            if node.get("chunk_dir"):
                directory = Path(node["chunk_dir"])
                if not directory.is_absolute():
                    directory = WORKSPACE_DIR / directory
                for chunk in node.get("chunks") or []:
                    path = (directory / chunk["file"]).resolve()
                    if not path.is_relative_to(directory.resolve()):
                        raise ValueError("PIN_PATH_OUTSIDE_CHUNK_DIRECTORY")
                    refs[str(path)] = chunk["sha256"]
            elif node.get("path") and node.get("sha256"):
                path = Path(node["path"])
                refs[str(path if path.is_absolute() else WORKSPACE_DIR / path)] = node["sha256"]
            for value in node.values():
                visit(value)
        elif isinstance(node, list):
            for value in node:
                visit(value)
    visit(snap.get("data_versions") or {})
    visit(snap.get("tick_versions") or {})
    bid = (snap.get("config_bundle") or {}).get("bundle_id")
    if not bid or Path(bid).name != bid or any(ch in bid for ch in "/\\:"):
        raise ValueError("CONTEXT_BUNDLE_ID_INVALID")
    bundle = d / "data" / "bundles" / bid
    manifest_path = bundle / "BUNDLE_MANIFEST.json"
    manifest = _read(manifest_path)
    from .util import hash_obj
    if not manifest or manifest.get("bundle_id") != bid or bid != "CFGB_" + hash_obj(manifest["files"])[:20]:
        raise ValueError("CONFIG_BUNDLE_ID_MISMATCH")
    refs[str(manifest_path)] = sha256_file(manifest_path)
    for filename, sha in manifest["files"].items():
        path = (bundle / filename).resolve()
        if not path.is_relative_to(bundle.resolve()):
            raise ValueError("CONFIG_BUNDLE_PATH_INVALID")
        refs[str(path)] = sha
    return [{"path": path, "sha256": sha} for path, sha in sorted(refs.items())]


def _report_hashes(rep: dict) -> list[dict]:
    from .util import sha256_file
    return [{"path": rep[k], "sha256": sha256_file(rep[k])} for k in ("report_md", "report_json")]


def _new_context(d: Path, s: dict, rec: dict, rep: dict) -> dict:
    from .util import sha256_file, hash_obj
    if rec.get("replay_errors"):
        raise ValueError("CONTEXT_CORE_REPLAY_INTEGRITY_ERROR")
    retention = _read(d / "data" / "retention" / "state.json") or {}
    if retention.get("status") != "OPEN":
        raise ValueError("TICK_GENERATION_NOT_OPEN")
    path = d / "data" / "store" / "snapshots" / f"{rec['snapshot_id']}.json"
    snap = _read(path)
    continuation = {"session_id": s["session_id"], "cycle_id": rec["cycle_id"], "snapshot_id": rec["snapshot_id"],
                    "bundle_id": rec["bundle_id"], "generation_id": retention["generation_id"],
                    "mutation_revision": retention["mutation_revision"], "engine_hash": s["engine_hash"],
                    "config_hash": s["config_hash"], "snapshot_sha256": sha256_file(path)}
    return {"schema_version": "A_MT5_CONTEXT_LIFECYCLE_V1", "context_state": "PENDING", "continuation": continuation,
            "continuation_hash": hash_obj(continuation), "baseline_report": rep, "baseline_hashes": _report_hashes(rep),
            "pinned_files": _pinned_file_refs(snap, d), "baseline_response_ready_at": iso_utc(now_utc()),
            "optional_errors": [], "finish_token": None}


def _verify_hash_refs(refs: list[dict]) -> None:
    from .util import sha256_file
    from .retention import _plain
    for ref in refs:
        path = _plain(Path(ref["path"]))
        if not path.is_file() or sha256_file(path) != ref["sha256"]:
            raise ValueError(f"CONTEXT_PIN_HASH_MISMATCH:{path}")


def _validate_context(d: Path, s: dict, rec: dict, state: dict) -> None:
    from .config import config_hash
    from .util import engine_hash, hash_obj, sha256_file
    from .retention import assert_tick_available
    if rec.get("replay_errors"):
        raise ValueError("CONTEXT_CORE_REPLAY_INTEGRITY_ERROR")
    continuation = state.get("continuation") or {}
    if state.get("continuation_hash") != hash_obj(continuation):
        raise ValueError("CONTEXT_CONTINUATION_TAMPERED")
    latest = (read_jsonl(d / "cycles.jsonl") or [{}])[-1]
    retention = _read(d / "data" / "retention" / "state.json") or {}
    expected = {"session_id": s["session_id"], "cycle_id": latest.get("cycle_id"), "snapshot_id": latest.get("snapshot_id"),
                "bundle_id": rec.get("bundle_id"), "generation_id": retention.get("generation_id"),
                "mutation_revision": retention.get("mutation_revision"), "engine_hash": engine_hash(), "config_hash": config_hash()}
    if (latest.get("status") not in ("OK", "PARTIAL") or retention.get("status") != "OPEN" or
            any(continuation.get(k) != v for k, v in expected.items()) or
            s["engine_hash"] != expected["engine_hash"] or s["config_hash"] != expected["config_hash"] or
            rec.get("cycle_id") != expected["cycle_id"] or rec.get("snapshot_id") != expected["snapshot_id"]):
        raise ValueError("CONTEXT_IDENTITY_OR_REVISION_MISMATCH")
    path = d / "data" / "store" / "snapshots" / f"{rec['snapshot_id']}.json"
    if sha256_file(path) != continuation.get("snapshot_sha256"):
        raise ValueError("CONTEXT_SNAPSHOT_HASH_MISMATCH")
    snap = _read(path)
    if snap.get("snapshot_id") != rec["snapshot_id"] or (snap.get("config_bundle") or {}).get("bundle_id") != rec["bundle_id"]:
        raise ValueError("CONTEXT_SNAPSHOT_IDENTITY_MISMATCH")
    for pin in (snap.get("tick_versions") or {}).values():
        assert_tick_available(pin)
        if pin.get("tick_generation_id") != continuation["generation_id"]:
            raise ValueError("CONTEXT_GENERATION_MISMATCH")
    if _pinned_file_refs(snap, d) != state.get("pinned_files"):
        raise ValueError("CONTEXT_PIN_SET_CHANGED")
    _verify_hash_refs(state["pinned_files"])
    _verify_hash_refs(state["baseline_hashes"])
    if state.get("final_hashes"):
        _verify_hash_refs(state["final_hashes"])


def _context_response(rec: dict, state: dict) -> dict:
    terminal = state["context_state"] in ("COMPLETE", "PARTIAL_FAILED")
    report = state["final_report"] if terminal else state["baseline_report"]
    if terminal:
        _verify_hash_refs(state["final_hashes"])
        payload = _read(Path(report["report_json"])) or {}
        rec = dict(rec, analysis=payload.get("analysis") or {}, fabio=payload.get("fabio") or {},
                   context_state=state["context_state"])
    return {"status": "PARTIAL" if state["context_state"] == "PARTIAL_FAILED" else rec["status"],
            "reason": rec.get("reason"), "cycle_id": rec["cycle_id"], "cycle": rec,
            "context_state": state["context_state"], "continuation": state["continuation"],
            "report": report, "analysis": rec.get("analysis") or {},
            "finish_token": state.get("finish_token") if terminal else None,
            "baseline_response_ready_at": state["baseline_response_ready_at"], "optional_errors": state.get("optional_errors", [])}


def enrich(root, name: str, expected_cycle_id: str, expected_generation_id: str, expected_snapshot_id: str,
           context_timeout: float = 30, max_cards: int = 8) -> dict:
    """Finite second call: exact pinned input only; never collect/replay or hold parent lease across child."""
    if isinstance(context_timeout, bool) or not math.isfinite(context_timeout) or context_timeout <= 0:
        raise ValueError("CONTEXT_TIMEOUT_MUST_BE_POSITIVE_FINITE")
    from .retention import context_state_path, storage_lease, record_report
    d = sdir(root, name)
    s = _read(d / "session.json")
    if not s:
        return {"status": "REFUSED", "reason": "SESSION_NOT_INITIALISED"}
    lock = acquire_lock(d)
    if not lock["acquired"]:
        return {"status": "REFUSED", "reason": lock["reason"]}
    try:
        state_path = context_state_path(d, expected_cycle_id, expected_snapshot_id)
        with storage_lease(d / "data"):
            state = _read(state_path)
            if not state or any((state.get("continuation") or {}).get(k) != v for k, v in (
                    ("cycle_id", expected_cycle_id), ("snapshot_id", expected_snapshot_id), ("generation_id", expected_generation_id))):
                return {"status": "REFUSED", "reason": "CONTEXT_EXPECTED_IDENTITY_MISMATCH"}
            rec = (read_jsonl(d / "cycles.jsonl") or [{}])[-1]
            _validate_context(d, s, rec, state)
            if state["context_state"] in ("COMPLETE", "PARTIAL_FAILED"):
                return _context_response(rec, state)
        # A crash after preparing files is recovered without recomputing context.
        if not state.get("final_report"):
            state["context_started_at"] = iso_utc(now_utc())
            atomic_write_json(state_path, state)
            try:
                rc, envelope = exec_in_bundle(root, name,
                    ["analysis", "--snapshot", expected_snapshot_id, "--include-fabio", "--max-cards", str(max_cards)],
                    state["continuation"]["bundle_id"], timeout_s=context_timeout)
                analysis = envelope.get("data") if isinstance(envelope, dict) else None
                if not isinstance(analysis, dict):
                    raise ValueError(f"OPTIONAL_CHILD_ERROR:{envelope}")
                if analysis.get("snapshot_id") != expected_snapshot_id:
                    raise RuntimeError("CONTEXT_CHILD_IDENTITY_MISMATCH")
                errors = analysis.get("errors") or []
                if rc and not errors:
                    errors = [{"reason": f"OPTIONAL_CHILD_EXIT_{rc}"}]
            except subprocess.TimeoutExpired:
                analysis, errors = {}, [{"item_state": "TIMEOUT", "reason": "CONTEXT_TIMEOUT_AFTER_REAP"}]
            except RuntimeError:
                raise  # Unknown process teardown/identity must remain pending, never finalizable.
            except Exception as exc:
                analysis, errors = {}, [{"item_state": "ERROR", "reason": f"{type(exc).__name__}:{exc}"}]
            integrity_words = ("DATA_VERSION", "CONFIG_BUNDLE", "SOURCE_HASH", "CHUNK_CORRUPT", "CHUNK_HASH", "DATA_INTEGRITY", "PIN_HASH")
            if any(word in str(errors).upper() for word in integrity_words):
                raise ValueError(f"CONTEXT_CORE_INTEGRITY:{errors}")
            with storage_lease(d / "data"):
                _validate_context(d, s, rec, state)
                if not analysis:
                    from .reporting import build_baseline_packet
                    snap = _read(d / "data" / "store" / "snapshots" / f"{expected_snapshot_id}.json")
                    analysis = build_baseline_packet(snap)
                target = "PARTIAL_FAILED" if errors else "COMPLETE"
                analysis = dict(analysis, context_state=target)
                final_rec = dict(rec, analysis=analysis, fabio=analysis.get("fabio") or {}, context_state=target,
                                 optional_errors=errors)
                report = build_report(root, name, final_rec, max_cards=max_cards)
                state.update(final_report=report, final_hashes=_report_hashes(report), target_context_state=target,
                             optional_errors=errors, context_finished_at=iso_utc(now_utc()))
                atomic_write_json(state_path, state)  # Still PENDING until retention registry commit below.
        with storage_lease(d / "data"):
            _validate_context(d, s, rec, state)
            report = state["final_report"]
            token = record_report(d, expected_cycle_id, expected_snapshot_id,
                                  [report["report_md"], report["report_json"]], rec["planned_end_utc"])
            state.update(context_state=state["target_context_state"], finish_token=token)
            atomic_write_json(state_path, state)
        return _context_response(rec, state)
    except Exception as exc:
        _event(d, "ENRICH_REFUSED", {"reason": str(exc), "cycle_id": expected_cycle_id})
        return {"status": "REFUSED", "reason": str(exc), "context_state": "PENDING", "finish_token": None}
    finally:
        release_lock(d)


def on_demand(root, name: str, end_utc: float | None = None, max_cards: int = 8,
              focused_symbols: list[str] | None = None, analysis_mode: str = "full") -> dict:
    """ON_DEMAND call: lock → verify engine/config → one bounded cycle (collect→bundle→snapshot/scan/replay/journal) →
    report with card/context per candidate → release. Re-calling with the same end is a no-op (dedup)."""
    from .config import config_hash
    from .util import engine_hash
    if analysis_mode not in ("full", "baseline"):
        raise ValueError("ANALYSIS_MODE_INVALID")
    d = sdir(root, name)
    s = _read(d / "session.json")
    if not s:
        return {"status": "ERROR", "reason": "SESSION_NOT_INITIALISED"}
    lk = acquire_lock(d)
    if not lk["acquired"]:
        return {"status": "REFUSED", "reason": lk["reason"], "holder": lk.get("holder")}
    try:
        if engine_hash() != s["engine_hash"] or config_hash() != s["config_hash"]:
            return {"status": "HALTED", "reason": "ENGINE_OR_CONFIG_CHANGED", "hint": "init a new session for the new engine/config"}
        if focused_symbols:
            if len(set(focused_symbols)) != len(focused_symbols) or any(sym not in s["symbol_map"] for sym in focused_symbols):
                return {"status": "REFUSED", "reason": "FOCUSED_SYMBOL_NOT_IN_PINNED_SESSION_OR_DUPLICATE"}
            s = dict(s, symbol_map={sym: s["symbol_map"][sym] for sym in focused_symbols}, focused_symbols=focused_symbols)
        s = dict(s, max_cards=max_cards, analysis_mode=analysis_mode)
        end = end_utc if end_utc is not None else now_utc()
        cid = _cycle_id(s, end)
        cyc_path = d / "cycles.jsonl"
        with file_lock(cyc_path):
            repair_jsonl_tail(cyc_path)
            prior = [c for c in read_jsonl(cyc_path) if c["cycle_id"] == cid]
        done = [c for c in prior if c["status"] in COMPLETED]
        if done:
            rec = dict(done[-1], reused_completed_cycle=True)
            from .retention import context_state_path, storage_lease
            existing_context = _read(context_state_path(d, cid, rec.get("snapshot_id")))
            if existing_context:
                with storage_lease(d / "data"):
                    _validate_context(d, s, rec, existing_context)
                    response = _context_response(rec, existing_context)
                    if analysis_mode == "full" and existing_context["context_state"] == "PENDING":
                        response.update(status="PARTIAL", reason="CONTEXT_PENDING: call session enrich")
                    return response
        else:
            _health(d, state="ON_DEMAND_RUNNING", phase="IN_CYCLE", last_attempt=iso_utc(now_utc()), session_id=s["session_id"])
            rec = run_cycle(d, s, end)
            rec["attempt"] = len(prior) + 1
            rec["trigger"] = "ON_DEMAND"
            append_jsonl(cyc_path, rec)
            if rec["status"] in COMPLETED:
                _after_success(d, rec, cid)
        from .retention import record_report, storage_lease, context_state_path
        if rec.get("snapshot_id") and rec["status"] in ("OK", "PARTIAL") and (
                analysis_mode == "baseline" or (rec.get("analysis") or {}).get("stage") == "BASELINE"):
            with storage_lease(d / "data"):
                from .reporting import build_baseline_packet
                snap = _read(d / "data" / "store" / "snapshots" / f"{rec['snapshot_id']}.json")
                baseline_rec = dict(rec, analysis=build_baseline_packet(snap), fabio={}, context_state="PENDING")
                rep = build_report(root, name, baseline_rec, max_cards=max_cards)
                context = _new_context(d, s, baseline_rec, rep)
                atomic_write_json(context_state_path(d, cid, rec["snapshot_id"]), context)
            _health(d, state="IDLE_ON_DEMAND", phase="BASELINE_DELIVERED", current_cycle=None)
            return _context_response(baseline_rec, context)
        rep = build_report(root, name, rec, max_cards=max_cards)
        finish_token = None
        if rec.get("snapshot_id") and rec["status"] in ("OK", "PARTIAL"):
            finish_token = record_report(d, cid, rec["snapshot_id"],
                                         [rep["report_md"], rep["report_json"]], rec["planned_end_utc"])
        _health(d, state="IDLE_ON_DEMAND", phase="DONE", current_cycle=None,
                last_cycle={k: rec.get(k) for k in ("cycle_id", "planned_end_utc", "status", "reason", "snapshot_id", "bundle_id")},
                **({"last_success": rec.get("finished_at"), "latest_snapshot": rec.get("snapshot_id"), "latest_bundle": rec.get("bundle_id")}
                   if rec["status"] in COMPLETED else {"last_error": rec.get("reason") or rec["status"]}))
        _event(d, "ON_DEMAND", {"cycle_id": cid, "status": rec["status"], "report": rep.get("report_md")})
        return {"status": rec["status"], "reason": rec.get("reason"), "cycle_id": cid, "report": rep,
                "finish_token": finish_token, "cycle": rec}
    finally:
        release_lock(d)


def finish(root, name: str, expected_cycle_id: str, expected_generation_id: str,
           expected_snapshot_id: str | None = None) -> dict:
    """Explicit final-scan acknowledgment, never inferred from inactivity or clock."""
    from .retention import finish_session
    d = sdir(root, name)
    if not (d / "session.json").exists():
        return {"status": "REFUSED", "reason": "SESSION_NOT_INITIALISED"}
    lk = acquire_lock(d)
    if not lk["acquired"]:
        return {"status": "REFUSED", "reason": lk["reason"]}
    try:
        return finish_session(d, expected_cycle_id, expected_generation_id, expected_snapshot_id)
    finally:
        release_lock(d)


def build_report(root, name: str, rec: dict, max_cards: int = 8) -> dict:
    """Human report for one call: source/identity, market state per symbol, candidates with card/context from the SAME
    snapshot (real CLI in the bundle process), journal path, next steps. Descriptive only; no orders, no FTMO verdict."""
    d = sdir(root, name)
    report_started = time.perf_counter()
    s = _read(d / "session.json")
    rdir = d / "reports"
    rdir.mkdir(exist_ok=True)
    L = [f"# Báo cáo quét theo yêu cầu — {s['session_name']}", "",
         f"- Thời điểm dữ liệu (as-of, UTC): {rec.get('planned_end_utc')} · cycle `{rec.get('cycle_id')}` · trạng thái **{rec.get('status')}**"
         + (f" ({rec.get('reason')})" if rec.get("reason") else ""),
         f"- Nguồn: provider `{rec.get('provider_kind')}` · source `{rec.get('source_id')}` · bundle `{rec.get('bundle_id')}` · snapshot `{rec.get('snapshot_id')}`",
         f"- Clock nguồn: `{(rec.get('clock') or {}).get('profile')}` · {(rec.get('clock') or {}).get('clock_profile_status')}"
         f" · ghim phiên: {bool((rec.get('clock') or {}).get('pinned_by_session'))} / kiểm lại: {(rec.get('clock') or {}).get('recheck') or 'probe lần đầu'}"
         f" · offset hiện tại {(rec.get('clock') or {}).get('offset_now_s')} s · phương án khác {(rec.get('clock') or {}).get('alternatives')}"
         " (giả định từ probe hiện tại; lịch sử/DST chưa xác minh)",
         f"- FTMO: program {s['ftmo']['program']} · môi trường {s['ftmo']['environment']} · luật/vốn/risk: {s['ftmo']['rule_regime']} / "
         f"{s['ftmo']['initial_capital']} / {s['risk'].split(' (')[0]} · đánh giá challenge: {s['ftmo']['challenge_evaluation']}",
         "- Công cụ KHÔNG đặt/kiểm tra lệnh. Mọi số liệu dưới đây là quan sát paper; không phải bằng chứng edge hay khả năng pass.", ""]
    out = {"cycle_id": rec.get("cycle_id"), "status": rec.get("status"), "symbols": rec.get("symbols"),
           "fabio": rec.get("fabio") or {}, "candidates": [],
           "context_state": rec.get("context_state") or (rec.get("analysis") or {}).get("context_state"),
           "optional_errors": rec.get("optional_errors") or [],
           "news_handling": "USER_MANAGED", "news_checked_by_system": False}
    L += ["- Tin tức: USER_MANAGED — người dùng tự kiểm; hệ thống không thu thập hoặc tránh tin.",
          f"- Xử lý bối cảnh: {out['context_state'] or 'legacy full'}; bối cảnh không có quyền loại A.", ""]
    if out["optional_errors"]:
        L += ["Hạn chế bối cảnh: " + json.dumps(out["optional_errors"], ensure_ascii=False), ""]
    if rec.get("planned_end_utc"):
        local_time = dt.datetime.fromisoformat(rec["planned_end_utc"].replace("Z", "+00:00")).astimezone(ICT)
        L += [f"- Giờ Việt Nam của snapshot: {local_time.isoformat()}", ""]
    if rec.get("status") not in COMPLETED or not rec.get("snapshot_id"):
        L += ["## Không có kết quả quét", "", f"Lý do: `{rec.get('reason') or rec.get('status')}`.", ""]
        if rec.get("status") == "PENDING_SOURCE":
            L += ["Mở MT5 demo đúng đường dẫn đã chọn, đăng nhập tài khoản DEMO (tự tay), rồi gọi lại."]
    else:
        snap = _read(d / "data" / "store" / "snapshots" / f"{rec['snapshot_id']}.json") or {}
        L += ["## Trạng thái từng mã", "",
              "| Mã | Trạng thái | Thị trường | Tuổi quote (tick) | Tuổi nến M5 đóng | Ứng viên 24h | Ghi chú |", "|---|---|---|---:|---:|---:|---|"]
        for sym, v in (rec.get("symbols") or {}).items():
            sv = (snap.get("symbols") or {}).get(sym) or {}
            qa = f"{sv['quote_age_s']:.1f}s" if sv.get("quote_age_s") is not None else str(sv.get("quote_age_status") or "UNKNOWN")
            ba = f"{sv['bar_watermark_age_s']:.0f}s" if sv.get("bar_watermark_age_s") is not None else "?"
            L.append(f"| {sym} | {v.get('status')} | {v.get('market_state')} | {qa} | {ba} | {v.get('relevant_candidates')} | "
                     f"{v.get('empty_meaning') or v.get('reason') or ''}; economics {(sv.get('economics') or v.get('economics') or {}).get('status', 'UNKNOWN')} |")
        L += ["", "## Fabio / CVD (cùng snapshot)", "",
              "| Mã | F1 | F2 | CVD basis/status | Coverage | Economics/missing | Artifact |", "|---|---|---|---|---:|---|---|"]
        for sym in sorted((rec.get("fabio") or {})):
            fr = rec["fabio"].get(sym) or {}
            fam = fr.get("families") or {}
            f1, f2 = fam.get("F1") or {}, fam.get("F2") or {}
            cvd = fr.get("cvd") or {}
            missing = "; ".join(str(x) for x in (f1.get("missing") or []) + (f2.get("missing") or [])) or fr.get("reason") or ""
            basis = cvd.get("volume_basis") or "UNKNOWN"
            cvd_status = cvd.get("status") or "UNKNOWN"
            coverage = cvd.get("coverage_window")
            cov_text = f"{coverage:.2%}" if isinstance(coverage, (int, float)) else "?"
            economics = []
            for family in (f1, f2):
                gate = (family.get("economics") or {}) if isinstance(family, dict) else {}
                if gate:
                    economics.append(": ".join(str(x) for x in (gate.get("status"), gate.get("reason")) if x) or "UNKNOWN")
            econ_text = ", ".join(economics) or missing or "UNKNOWN"
            artifact = fr.get("artifact_path") or "—"
            L.append(f"| {sym} | {f1.get('decision', '—')} | {f2.get('decision', '—')} | {basis} / {cvd_status} | {cov_text} | {econ_text} | `{artifact}` |")
        from .reporting import candidate_priority, current_window
        analysis = rec.get("analysis") or {}
        lightweight = analysis.get("stage") == "BASELINE"
        pending = out["context_state"] == "PENDING"
        if not analysis and not pending and not lightweight:
            _, batch = exec_in_bundle(root, name, ["analysis", "--snapshot", rec["snapshot_id"], "--max-cards", str(max_cards)], rec.get("bundle_id"))
            analysis = (batch.get("data") or {}) if isinstance(batch, dict) else {}
        out["analysis"] = analysis
        out["timings_s"] = rec.get("timings_s") or {}
        out["cache_stats"] = rec.get("cache_stats") or {}
        L += ["", "## Bối cảnh giá theo từng mã", "",
              "| Mã | Close M5 | ATR M5 | PDH / PDL | H1 8 nến (rolling, không phải anchor A) | Context |",
              "|---|---:|---:|---|---|---|"]
        for sym, market in analysis.get("market", {}).items():
            features = market.get("features") or []
            levels = {f["name"]: f.get("level") for f in features if "level" in f}
            atr = next((f.get("value") for f in features if f.get("name") == "atr14_wilder" and f.get("tf") == "M5"), None)
            px = (market.get("price_reference") or {}).get("close")
            L.append(f"| {sym} | {px} | {atr} | {levels.get('distance_close_to_prev_day_high_over_atr')} / "
                     f"{levels.get('distance_close_to_prev_day_low_over_atr')} | {levels.get('distance_close_to_h1_8bar_high_over_atr')} / "
                     f"{levels.get('distance_close_to_h1_8bar_low_over_atr')} | {market.get('reason') or 'Cùng snapshot; số liệu mô tả'} |")
        L += ["", "## Vùng cần kiểm tra lại trước tín hiệu cũ", "",
              "Vùng theo snapshot, không phải lệnh chờ. Setup B chưa có bộ phát hiện vùng trước trigger. Tin tức: USER_MANAGED.", ""]
        for zone in analysis.get("watch_zones", []):
            L.append(f"- {zone['symbol']} {zone['setup']} {zone.get('side')}: {zone.get('state')} · "
                     f"vùng {zone.get('zone_low', zone.get('location'))} → {zone.get('zone_high', '')} · "
                     f"vô hiệu {zone.get('invalidation')} · hết hạn {zone.get('expires_at')} · basis {zone.get('basis')}")
        if not analysis.get("watch_zones"):
            L.append("Không có vùng chờ retest đã được engine xác nhận ở snapshot này.")
        L += ["", "Các mã chung đồng tiền có thể cùng rủi ro; đây là nhóm phơi nhiễm, không phải phép đo tương quan: "
              + str({k: v for k, v in analysis.get("currency_groups", {}).items() if len(v) > 1})]
        cands = sorted(snap.get("candidates", []), key=lambda c: (candidate_priority(c), c["candidate_id"]))
        deep_ids = set() if lightweight or pending else {c["candidate_id"] for c in cands[:max(0, max_cards)]}
        L += ["", "## Toàn bộ tín hiệu A/B — không lọc theo bối cảnh", "",
              "| ID | Mã / hướng | Ready | Deadline | Nhánh / gate | Entry / SL / TP gốc | Tại as-of / khi xuất |",
              "|---|---|---|---|---|---|---|"]
        for c in cands:
            plan, cw = c.get("plan") or {}, current_window(c, snap, now_utc())
            L.append(f"| {c['candidate_id']} | {c['symbol']} {c.get('setup')} {c['side']} | {c['ready_at']} | {c.get('entry_deadline_at')} | "
                     f"{c.get('branch_eligibility')} | {plan.get('entry')} / {plan.get('sl')} / {plan.get('tp')} | "
                     f"{c.get('plan_window')} / {cw['current_status']} |")
        if not any(c.get("setup") == "A" for c in cands):
            L.append("Không có candidate A trong snapshot này; vùng chờ/context không phải lệnh mới.")
        if pending:
            L += ["", "Bối cảnh PENDING: chưa phân tích; không phải gate A thất bại."]
        elif lightweight:
            L += ["", "Bối cảnh đã kết thúc với lỗi/giới hạn; giữ nguyên mọi A, không phải gate A thất bại."]
        L += ["", f"## Thẻ chi tiết (tối đa {max_cards}; danh sách tín hiệu phía trên không bị cắt)", ""]
        if analysis.get("deferred_cards"):
            L.append(f"Còn {len(analysis['deferred_cards'])} thẻ DEFERRED_DEEP_ANALYSIS; chưa phân tích sâu, không ngầm đánh giá là kém hơn.")
        if not cands:
            L.append("Không có setup trong cửa sổ 24h trước as-of (đã quét, không lỗi).")
        jrows = {}
        for p in (d / "data" / "store" / "journal").glob("paper_*.jsonl"):
            for r in read_jsonl(p):
                if r.get("kind") in ("paper_signal", "paper_outcome"):
                    jrows[r["revision_id"]] = r
        for c in cands:
            cd = (analysis.get("cards") or {}).get(c["candidate_id"]) or {}
            feats = {f["name"] + ":" + str(f.get("tf")): f.get("value") for f in cd.get("context", [])}
            plan = c.get("plan") or {}
            j = jrows.get(c["revision_id"]) or {}
            rp = j.get("replay") or {}
            pw = c.get("plan_window") or {}
            open_now = [b for b, v in pw.items() if v == "ENTRY_WINDOW"]
            window_line = (f"**CÒN TRONG CỬA SỔ ENTRY** ({', '.join(open_now)}) tới {c.get('entry_deadline_at')}" if open_now else
                           ("**ĐÃ HẾT HẠN tại as-of — chỉ để quan sát, KHÔNG phải tín hiệu vào lệnh**" if "EXPIRED" in pw.values() else
                            "không có nhánh đủ điều kiện (gate) — chỉ quan sát"))
            cw = current_window(c, snap, now_utc())
            item = {"plan_window": pw, "actionable_at_as_of": bool(open_now), "current_window": cw,
                    "candidate_id": c["candidate_id"], "symbol": c["symbol"], "setup": c["setup"], "side": c["side"], "ready_at": c["ready_at"],
                    "deadline": c.get("entry_deadline_at"), "gates": c.get("branch_eligibility"), "plan_state": plan.get("state"),
                    "plan_reason": plan.get("reason"), "entry": plan.get("entry"), "sl": plan.get("sl"), "tp": plan.get("tp"),
                    "replay_quote_basis": rp.get("quote_basis"), "evidence_grade": rp.get("evidence_grade"),
                    "card_ok": cd.get("status") == "OK", "context_features": {k: feats[k] for k in list(feats)[:8]}}
            item.update(revision_id=c.get("revision_id"), episode_id=c.get("episode_id"),
                        baseline_candidate=c, context_state=out["context_state"],
                        deep_analysis_status=("PENDING" if pending else "ERROR" if lightweight else
                                              ("READY" if cd.get("status") == "OK" else cd.get("status") or "UNKNOWN")
                                              if c["candidate_id"] in deep_ids else "DEFERRED_DEEP_ANALYSIS"))
            out["candidates"].append(item)
            if c["candidate_id"] not in deep_ids:
                continue
            L += [f"### {c['symbol']} {c['setup']} {c['side']} — ready {c['ready_at']}", "",
                  f"- Cửa sổ entry tại as-of: {window_line} · theo nhánh {pw}",
                  f"- Tại lúc xuất báo cáo: {cw['current_status']} · tuổi snapshot {cw['snapshot_age_s']}s · phải kiểm lại quote/tài khoản, không tự gia hạn tín hiệu.",
                  f"- Gate: {c.get('branch_eligibility')} · plan **{plan.get('state')}** {('(' + str(plan.get('reason')) + ')') if plan.get('reason') else ''}"
                  f" · hạn entry {c.get('entry_deadline_at')}",
                  f"- Entry/SL/TP (indicative, {plan.get('certification', 'INDICATIVE')}): {plan.get('entry')} / {plan.get('sl')} / {plan.get('tp')}",
                  f"- Replay (mô phỏng quá khứ, không phải fill): {rp.get('quote_basis')} · {rp.get('evidence_grade')} · {rp.get('status')} {rp.get('reason') or ''}",
                  f"- Context (cùng snapshot): " + ", ".join(f"{k}={v:.5g}" if isinstance(v, (int, float)) else f"{k}={v}" for k, v in item["context_features"].items()),
                  f"- Card: `quant.cmd session exec --root {chr(34)}{root}{chr(34)} --name {name} -- card --snapshot {rec['snapshot_id']} --candidate {c['candidate_id']}`", ""]
        out["evening_context"] = analysis.get("evening_context") or {}
        if out["evening_context"]:
            from .reporting import render_evening_context
            L += render_evening_context(analysis, deep_ids)
    L += ["## Bước tiếp theo", "",
          "- Brainstorm/note: viết note JSON (RUNBOOK §2) rồi `quant.cmd session exec ... -- note add --file <note.json>`.",
          f"- Journal: `{d / 'data' / 'store' / 'journal'}` · Báo cáo: `{rdir}`.",
          "- Gọi lại khi cần: `quant.cmd session once --root ... --name ...` (dữ liệu cũ giữ nguyên, không ghi trùng)."]
    tag = (rec.get("cycle_id") or "none") + "_" + str(int(now_utc() * 1000))
    md, js = rdir / f"{tag}.md", rdir / f"{tag}.json"
    from .util import atomic_write_text
    out["report_ready_at"] = iso_utc(now_utc())
    out.setdefault("timings_s", {})["report_build"] = round(time.perf_counter() - report_started, 4)
    atomic_write_text(md, "\n".join(L) + "\n")
    atomic_write_json(js, out)
    return {"report_md": str(md), "report_json": str(js), "n_candidates": len(out["candidates"])}


# ------------------------------------------------------------------ control
def status(root, name: str) -> dict:
    d = sdir(root, name)
    s, h = _read(d / "session.json"), _read(d / "health.json") or {}
    if not s:
        return {"status": "ERROR", "reason": "SESSION_NOT_INITIALISED"}
    lp = _lock_path(d)
    held = _read(lp) if lp.exists() else None
    alive = False
    if held:
        ident = proc_identity(int(held["pid"]))
        alive = bool(ident and ident["alive"] and ident["create_time"] == held.get("create_time"))
    if held and alive:
        state = "RUNNING"
    elif held:
        state = "STALE_LOCK (runner process gone; next start recovers it with audit)"
    else:
        state = h.get("state", "NOT_STARTED")
    hb = h.get("heartbeat")
    age = round(now_utc() - dt.datetime.fromisoformat(hb.replace("Z", "+00:00")).timestamp(), 1) if hb else None
    cycles = read_jsonl(d / "cycles.jsonl") if (d / "cycles.jsonl").exists() else []
    return {"status": "OK", "state": state, "session_id": s["session_id"], "mode": s["mode"], "lock": held, "lock_holder_alive": alive,
            "heartbeat_age_s": age, "health": h, "n_cycles": len(cycles),
            "protocol": _read(d / "protocol.json") or s["protocol"], "identity_pin": _read(d / "identity_pin.json"),
            "ftmo": s["ftmo"], "paths": {"session_dir": str(d), "journal_dir": str(d / "data" / "store" / "journal"),
                                         "snapshots": str(d / "data" / "store" / "snapshots"), "log": str(d / "runner.log")}}


def request_stop(root, name: str, timeout_s: float = 120, force: bool = False) -> dict:
    d = sdir(root, name)
    t_req = now_utc()
    (d / "stop.request").write_text(iso_utc(t_req), encoding="utf-8")
    _event(d, "STOP_REQUESTED", {"timeout_s": timeout_s, "force": force})
    t0 = time.monotonic()
    while time.monotonic() - t0 < timeout_s:
        if not _lock_path(d).exists():
            rec = {"result": "STOPPED", "requested_at": iso_utc(t_req), "stopped_at": iso_utc(now_utc()), "waited_s": round(time.monotonic() - t0, 1)}
            _event(d, "STOP_RECEIPT", rec)
            return rec
        held = _read(_lock_path(d)) or {}
        ident = proc_identity(int(held.get("pid", 0))) if held.get("pid") else None
        if not (ident and ident["alive"]):
            break
        time.sleep(0.5)
    held = _read(_lock_path(d)) if _lock_path(d).exists() else None
    if held is None:
        rec = {"result": "STOPPED", "requested_at": iso_utc(t_req), "stopped_at": iso_utc(now_utc())}
    else:
        ident = proc_identity(int(held["pid"]))
        same = bool(ident and ident["alive"] and ident["create_time"] == held.get("create_time"))
        if not same:
            rec = {"result": "STALE_LOCK_NO_LIVE_RUNNER", "lock": held}
        elif force:
            h = _read(d / "health.json") or {}
            cc = h.get("current_cycle") or {}
            if cc.get("child_pid"):
                ci = proc_identity(int(cc["child_pid"]))
                if ci and ci["alive"] and ci["create_time"] == cc.get("child_create_time"):
                    _kill_tree(int(cc["child_pid"]))
            ok = _terminate(int(held["pid"]))
            rec = {"result": "FORCE_TERMINATED" if ok else "FORCE_FAILED", "pid": held["pid"], "identity_verified": True}
        else:
            rec = {"result": "STOP_TIMEOUT", "lock": held, "hint": "retry with --force (terminates only the verified runner pid)"}
    rec.setdefault("requested_at", iso_utc(t_req))
    _event(d, "STOP_RECEIPT", rec)
    return rec


def start_background(root, name: str, extra_args: list[str] | None = None) -> dict:
    """Hidden background runner via PowerShell Start-Process -WindowStyle Hidden; PID + log recorded."""
    import base64
    d = sdir(root, name)
    if not (d / "session.json").exists():
        return {"status": "ERROR", "reason": "SESSION_NOT_INITIALISED"}
    st = status(root, name)
    if st["state"] == "RUNNING":
        return {"status": "REFUSED", "reason": "LOCK_HELD_BY_LIVE_RUNNER"}
    args = [str(ENTRY), "session", "run", "--root", str(root), "--name", name] + (extra_args or [])
    q = lambda a: '"' + a.replace('"', '\\"') + '"'
    arglist = " ".join(q(a) for a in args)
    ps = (f"$p = Start-Process -FilePath '{sys.executable}' -ArgumentList '-I {arglist.replace(chr(39), chr(39) * 2)}' -WindowStyle Hidden "
          f"-RedirectStandardOutput '{d / 'background.stdout.txt'}' -RedirectStandardError '{d / 'background.stderr.txt'}' -PassThru; "
          f"Set-Content -LiteralPath '{d / 'background.pid'}' -Value $p.Id -Encoding ascii")
    enc = base64.b64encode(ps.encode("utf-16-le")).decode()
    pidf = d / "background.pid"
    if pidf.exists():
        pidf.unlink()
    # no pipes: the hidden child must not inherit our stdout (the caller would otherwise wait for it to exit)
    r = subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-EncodedCommand", enc], stdin=subprocess.DEVNULL,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=60)
    pid = int(pidf.read_text(encoding="ascii").strip()) if pidf.exists() else None
    rec = {"status": "STARTED" if pid else "ERROR", "launcher_pid": pid, "powershell_exit": r.returncode, "log": str(d / "runner.log")}
    _event(d, "BACKGROUND_START", rec)
    return rec


def preflight(root, name: str, process_lister=None) -> dict:
    """Runtime + source preflight. Never initialises a terminal that is not running."""
    import importlib
    import platform
    from .collector import running_terminal_paths
    from .config import config_hash
    from .util import engine_hash
    d = sdir(root, name)
    s = _read(d / "session.json")
    if not s:
        return {"status": "ERROR", "reason": "SESSION_NOT_INITIALISED"}
    pk = {}
    for m in ("numpy", "MetaTrader5"):
        try:
            pk[m] = getattr(importlib.import_module(m), "__version__", "present")
        except ImportError:
            pk[m] = None
    out = {"python": platform.python_version(), "packages": pk, "engine_hash_ok": engine_hash() == s["engine_hash"],
           "config_hash_ok": config_hash() == s["config_hash"], "mode": s["mode"], "ftmo": s["ftmo"], "initialize_called": False}
    if s["mode"] == "SYNTHETIC_FIXTURE":
        out.update({"status": "READY_SYNTHETIC", "source": "SYNTHETIC_FIXTURE (software test; not market evidence)"})
        return out
    exe = os.path.normcase(os.path.abspath(s["terminal_path"] if s["terminal_path"].lower().endswith(".exe")
                                           else os.path.join(s["terminal_path"], "terminal64.exe")))
    running = (process_lister or running_terminal_paths)()
    out.update({"selected_terminal": exe, "running_terminals": running})
    if not out["engine_hash_ok"] or not out["config_hash_ok"]:
        out.update({"status": "ERROR", "reason": "ENGINE_OR_CONFIG_CHANGED"})
    elif pk["MetaTrader5"] is None:
        out.update({"status": "ERROR", "reason": "METATRADER5_PACKAGE_MISSING"})
    elif exe not in running:
        out.update({"status": "PENDING_LIVE_SOURCE_NOT_RUNNING",
                    "next_steps": ["Mở MT5 demo đúng đường dẫn đã chọn và đăng nhập tài khoản DEMO (tự tay; công cụ không login)",
                                   "Chạy lại: quant.cmd session preflight --root <root> --name <name>"]})
    else:
        out.update({"status": "READY_TO_ATTACH", "note": "identity/trade_mode=DEMO are verified inside the first cycle before any read"})
    return out


def summary(root, name: str) -> dict:
    d = sdir(root, name)
    s = _read(d / "session.json")
    cycles = read_jsonl(d / "cycles.jsonl") if (d / "cycles.jsonl").exists() else []
    from collections import Counter
    jdir = d / "data" / "store" / "journal"
    sig = []
    for p in sorted(jdir.glob("paper_*.jsonl")) if jdir.exists() else []:
        sig += [r for r in read_jsonl(p) if r.get("kind") == "paper_signal"]
    return {"session_id": s["session_id"], "mode": s["mode"], "ftmo": s["ftmo"], "protocol": _read(d / "protocol.json") or s["protocol"],
            "cycles_by_status": dict(Counter(c["status"] for c in cycles)), "n_paper_signals": len(sig),
            "signals_by_plan_state": dict(Counter(r.get("plan_state") for r in sig)),
            "signals_by_evidence_grade": dict(Counter((r.get("replay") or {}).get("evidence_grade") for r in sig)),
            "outcome_tracking": s["outcome_tracking"],
            "statistics": "DESCRIPTIVE COUNTS ONLY — no edge, no FTMO pass/fail (challenge evaluation UNCONFIGURED, B6C2)"}
