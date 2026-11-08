"""B6B bounded one-shot paper workflow (no daemon, no orders, no lot sizing).

paper_run (any process): process check → read-only collect (bounded bars/ticks) into an isolated source namespace →
immutable config/source bundle → spawn `paper-scan` in a NEW process whose QUANTMT5_CONFIG_DIR is that bundle.
paper_scan (bundle process only): snapshot as-of → scan → replay through the snapshot pins (collected ticks when
they cover the entry window, else labelled M1 proxy) → append-only paper journal per source namespace, dedup by
(source namespace, candidate revision). Every run also appends one observation (no-signal / stale / errors included).
Nothing here sends, checks or sizes orders."""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Callable

from .collector import collect, running_terminal_paths
from .util import (PROJECT_DIR, STORE_DIR, append_jsonl, atomic_write_text, engine_hash, file_lock, iso_utc, now_utc,
                   parse_utc, read_jsonl, stable_id)


def paper_journal_path(source_id: str) -> Path:
    return STORE_DIR / "journal" / f"paper_{source_id}.jsonl"


def _test_crash(point: str) -> None:
    """Test-only crash injection (QUANTMT5_ALLOW_TEST_HOOKS=1 and QUANTMT5_TEST_CRASH_POINT=<point>)."""
    if os.environ.get("QUANTMT5_ALLOW_TEST_HOOKS") == "1" and os.environ.get("QUANTMT5_TEST_CRASH_POINT") == point:
        os._exit(97)


def _append_dedup(path: Path, rec: dict) -> bool:
    """Append `rec` unless a record with the same dedup_key exists (check+append under one cross-process lock).
    A partial last line left by a crash is repaired with an audit record first; a corrupt middle line raises."""
    from .util import repair_jsonl_tail
    with file_lock(path):
        repair_jsonl_tail(path)
        if any(r.get("dedup_key") == rec["dedup_key"] for r in read_jsonl(path)):
            return False
        append_jsonl(path, rec, lock=False)
        return True


def _fabio_summary(result: dict, *, report_path: str | None = None) -> dict:
    """Keep the paper observation useful without duplicating the Fabio artifact."""
    flow = result.get("flow") or {}
    families = result.get("families") or {}
    out = {
        "status": "OK",
        "symbol": result.get("symbol"),
        "snapshot_id": result.get("snapshot_id"),
        "as_of": result.get("as_of"),
        "analysis_id": result.get("analysis_id"),
        "decision": result.get("decision"),
        "reason": result.get("reason"),
        "route": result.get("route"),
        "artifact_path": result.get("artifact_path"),
        "report_path": report_path,
        "cvd": {k: flow.get(k) for k in ("status", "volume_basis", "coverage_window", "bars_used", "lag_s", "reasons")
                if k in flow},
        "price_context": result.get("price_context"), "balance": result.get("balance"),
        "flow": dict(flow), "divergence_context": result.get("divergence_context"), "state": result.get("state"),
        "execution_quote": result.get("execution_quote"),
        "families": {name: {**{k: fam.get(k) for k in ("decision", "reason", "side", "missing", "gates", "invalidation", "expires_at", "supporting_evidence", "contradicting_evidence") if k in fam},
                             **({"economics": (fam.get("gates") or {}).get("economics")} if (fam.get("gates") or {}).get("economics") else {})}
                     for name, fam in families.items() if name in ("F1", "F2")},
    }
    basis = flow.get("volume_basis")
    out["cvd"]["is_proxy"] = flow.get("is_proxy", (result.get("route") == "FTMO_PRICE_PROXY" or
                                (basis is not None and basis != "EXECUTED_TRADES")))
    return out


def _fabio_error(symbol: str, exc: Exception, snapshot_symbol: dict | None = None) -> dict:
    reason = str(exc) or type(exc).__name__
    return {"status": "ERROR", "symbol": symbol, "decision": "DATA_UNAVAILABLE", "reason": f"FABIO_SYMBOL_ERROR:{reason}",
            "route": None, "artifact_path": None, "report_path": None, "cvd": {}, "families": {},
            "snapshot_reason": (snapshot_symbol or {}).get("reason")}


def _run_fabio_for_snapshot(snapshot: dict, universe: list[str]) -> dict[str, dict]:
    """Run Fabio once per available requested symbol, preserving per-symbol failures."""
    from . import fabio

    results: dict[str, dict] = {}
    for symbol in sorted(universe):
        sv = (snapshot.get("symbols") or {}).get(symbol) or {}
        if sv.get("status") != "OK":
            results[symbol] = _fabio_error(symbol, RuntimeError("SNAPSHOT_SYMBOL_UNAVAILABLE"), sv)
            continue
        try:
            result = fabio.run_for_snapshot(snapshot["snapshot_id"], symbol, None, None, None, None, store=True)
            report_path = None
            try:
                analysis_id = result["analysis_id"]
                report_path_obj = STORE_DIR / "fabio" / snapshot["snapshot_id"] / f"{symbol}_{analysis_id}.md"
                if not report_path_obj.exists():
                    atomic_write_text(report_path_obj, fabio.render_report(result))
                report_path = str(report_path_obj)
            except Exception as report_exc:
                # The JSON artifact remains valid; surface report failure without losing the baseline scan.
                result = dict(result)
                result.setdefault("report_error", f"{type(report_exc).__name__}: {report_exc}")
            summary = _fabio_summary(result, report_path=report_path)
            if result.get("report_error"):
                summary["report_error"] = result["report_error"]
                summary["status"] = "ERROR"
            results[symbol] = summary
        except Exception as exc:  # per-symbol isolation is intentional
            results[symbol] = _fabio_error(symbol, exc, sv)
    return results


def paper_scan(as_of: float, universe: list[str] | None = None, max_cards: int = 8, analysis_mode: str = "full") -> dict:
    from .analysis_cache import analysis_scope
    from .retention import storage_lease
    started = time.perf_counter()
    with storage_lease(STORE_DIR.parent), analysis_scope() as stats:
        result = _paper_scan(as_of, universe, max_cards, analysis_mode)
        result["cache_stats"] = stats
    result.setdefault("timings_s", {})["paper_scan_total"] = round(time.perf_counter() - started, 4)
    return result


def _paper_scan(as_of: float, universe: list[str] | None = None, max_cards: int = 8, analysis_mode: str = "full") -> dict:
    if analysis_mode not in ("full", "baseline"):
        raise ValueError("ANALYSIS_MODE_INVALID")
    from .config import bundle_identity, config_hash
    from .data import load_registry
    from .replay import replay
    from .snapshot import make_snapshot, scan
    bi = bundle_identity()
    if bi["kind"] != "SOURCE_BUNDLE":
        return {"status": "ERROR", "reason": "NOT_A_SOURCE_BUNDLE: set QUANTMT5_CONFIG_DIR to a bundle built by paper-run"}
    reg = load_registry()
    universe = universe or reg.get("requested_symbols") or sorted(reg["symbols"])
    timings = {}
    stage = time.perf_counter()
    recorded = now_utc()
    jpath = paper_journal_path(reg["source_id"])
    try:
        snap = make_snapshot(as_of, universe)
    except Exception as e:  # reason-coded observation, never a silent crash
        rec = {"kind": "observation", "dedup_key": stable_id("PRUN_ERR", reg["source_id"], iso_utc(as_of), type(e).__name__, str(e)),
               "source_id": reg["source_id"], "provider_kind": bi.get("provider_kind"), "config_bundle": bi["bundle_id"],
               "engine_hash": engine_hash(), "as_of": iso_utc(as_of), "recorded_at": iso_utc(recorded), "status": "ERROR",
               "reason": f"SNAPSHOT_FAILED:{type(e).__name__}: {e}"}
        _append_dedup(jpath, rec)
        return {"status": "ERROR", "reason": rec["reason"], "journal_path": str(jpath)}
    sc = scan(snap)
    timings["snapshot"] = round(time.perf_counter() - stage, 4)
    stage = time.perf_counter()
    common = {"source_id": reg["source_id"], "provider_kind": bi.get("provider_kind"), "config_bundle": bi["bundle_id"],
              "engine_hash": engine_hash(), "config_hash": config_hash(), "snapshot_id": snap["snapshot_id"], "as_of": snap["as_of_utc"],
              "recorded_at": iso_utc(recorded),
              "note": "paper observation only; never an order; outcome fields use data available through the snapshot pins"}
    from .data import DataVersionMismatch
    written, dup, rows, replay_errors = 0, 0, [], []
    # Index once; do not replay immutable completed outcomes on every 20-minute scan.
    existing = {}
    with file_lock(jpath):
        from .util import repair_jsonl_tail
        repair_jsonl_tail(jpath)
        for old in read_jsonl(jpath):
            if old.get("kind") in ("paper_signal", "paper_outcome"):
                existing[old.get("revision_id")] = old
    for c in snap["candidates"]:
        old = existing.get(c["revision_id"])
        old_replay = (old or {}).get("replay") or {}
        exact_closed = old_replay.get("exit_at") and old_replay.get("evidence_grade") in ("NATIVE_TICK_EXACT", "SYNTHETIC_TICK_EXACT")
        if old and (exact_closed or old.get("outcome_state") == "CENSORED_AT_SESSION_END"):
            dup += 1
            rows.append({"candidate_id": c["candidate_id"], "revision_id": c["revision_id"], "written": False,
                         "replay_skipped": "FINAL_OUTCOME_ALREADY_RECORDED"})
            continue
        try:
            rp = replay(c["candidate_id"], c["symbol"], snapshot_id=snap["snapshot_id"])
        except DataVersionMismatch as e:
            # integrity failure: no paper_signal (it would lock in an unverifiable record); reason kept in the observation
            replay_errors.append({"candidate_id": c["candidate_id"], "revision_id": c["revision_id"], "reason": f"DATA_INTEGRITY:{e}"})
            continue
        ex = rp.get("execution") or {}
        prim = ex.get("primary") or {}
        rec = dict(common, kind="paper_signal", dedup_key=stable_id("PSIG", reg["source_id"], c["revision_id"]),
                   candidate_id=c["candidate_id"], revision_id=c["revision_id"], symbol=c["symbol"], setup=c["setup"], side=c["side"],
                   signal_close_at=c["signal_bar"]["close_at"], ready_at=c["ready_at"], entry_deadline_at=c.get("entry_deadline_at"),
                   branch_eligibility=c["branch_eligibility"], plan_state=c["plan"].get("state"), plan_reason=c["plan"].get("reason"),
                   replay={"quote_basis": rp.get("quote_basis"), "tick_note": rp.get("tick_note"), "certification": rp.get("certification"),
                           "evidence_grade": rp.get("evidence_grade"), "counts_as_native_evidence": rp.get("counts_as_native_evidence"),
                           "status": ex.get("status"), "reason": ex.get("reason"), "fill_at": ex.get("fill_at"), "entry": ex.get("entry"),
                           "sl": ex.get("sl"), "tp": ex.get("tp"), "exit_reason": prim.get("exit_reason"), "exit_at": prim.get("exit_at"),
                           "net_R": ex.get("net_R"), "flags": ex.get("flags")})
        if old:
            rec.update(kind="paper_outcome", dedup_key=stable_id("POUT", reg["source_id"], c["revision_id"], snap["snapshot_id"]),
                       outcome_state="CLOSED" if prim.get("exit_at") else "UNRESOLVED")
        ok = _append_dedup(jpath, rec)
        if ok:
            _test_crash("after_first_signal_append")
        written += bool(ok and not old)
        dup += bool(old or not ok)
        rows.append({"candidate_id": c["candidate_id"], "revision_id": c["revision_id"], "written": ok, "plan_state": rec["plan_state"],
                     "quote_basis": rec["replay"]["quote_basis"], "replay_status": rec["replay"]["status"]})
    timings["replay_journal"] = round(time.perf_counter() - stage, 4)
    stage = time.perf_counter()
    fabio = _run_fabio_for_snapshot(snap, universe) if analysis_mode == "full" else {}
    timings["fabio"] = round(time.perf_counter() - stage, 4)
    stage = time.perf_counter()
    from .reporting import analyze_snapshot, build_baseline_packet
    analysis = (analyze_snapshot(snap, max_cards=max_cards, fabio=fabio) if analysis_mode == "full"
                else build_baseline_packet(snap))
    timings["batch_analysis"] = round(time.perf_counter() - stage, 4)
    fabio_errors = [r for r in fabio.values() if r.get("status") == "ERROR"]
    obs = dict(common, kind="observation", dedup_key=stable_id("PRUN", reg["source_id"], snap["snapshot_id"]),
               scan_status=sc["status"], n_candidates=len(snap["candidates"]), n_signals_written=written, n_signals_duplicate=dup,
               symbols={s: {k: v.get(k) for k in ("status", "market_state", "quality_flags", "relevant_candidates", "reason", "empty_meaning", "economics")}
                        for s, v in snap["symbols"].items()}, errors=snap["errors"], replay_errors=replay_errors,
               fabio=fabio)
    obs_written = _append_dedup(jpath, obs)
    _test_crash("after_observation_append")
    return {"status": "OK" if not (snap["errors"] or replay_errors or fabio_errors or analysis["errors"]) else "PARTIAL", "snapshot_id": snap["snapshot_id"],
            "scan_status": sc["status"], "replay_errors": replay_errors,
            "journal_path": str(jpath), "signals_written": written, "signals_duplicate": dup, "observation_written": obs_written,
            "rows": rows, "config_bundle": bi, "engine_hash": common["engine_hash"], "config_hash": common["config_hash"],
            "symbols": obs["symbols"], "errors": snap["errors"], "fabio": fabio, "analysis": analysis, "timings_s": timings}


def paper_run(terminal_path: str, symbol_map: dict[str, str], *, out_root: Path, end_utc: float | None = None, lookback_days: float = 35,
              tick_minutes: float = 240, tick_start_utc: float | None = None, as_of: float | None = None, scan: bool = True,
              process_lister: Callable[[], list[str]] = running_terminal_paths, mt5_module=None, sessions: dict | None = None,
              require_trade_mode: int | None = None, expect_identity: dict | None = None, scan_timeout_s: float = 300,
              clock_profile: str | None = None, max_cards: int = 8, analysis_mode: str = "full") -> dict:
    """Bounded one-shot. symbol_map: canonical -> native name (declared). Terminal absent → PENDING (no initialize)."""
    from .config import symbol_profiles
    from .source_bundle import BundleError, build_source_bundle
    from .retention import storage_lease
    from .universe import validate_map
    if analysis_mode not in ("full", "baseline"):
        raise ValueError("ANALYSIS_MODE_INVALID")
    symbol_map = validate_map(symbol_map)
    started = time.perf_counter()
    out_root = Path(out_root).resolve()
    exe = os.path.normcase(os.path.abspath(terminal_path if terminal_path.lower().endswith(".exe") else os.path.join(terminal_path, "terminal64.exe")))
    if exe not in process_lister():
        return {"status": "PENDING_LIVE_SOURCE_NOT_RUNNING", "initialize_called": False, "selected": exe,
                "next_step": "user starts the selected terminal (logged in), then rerun paper-run"}
    t_end = end_utc if end_utc is not None else now_utc()
    start = t_end - lookback_days * 86400
    t_tick = tick_start_utc if tick_start_utc is not None else t_end - tick_minutes * 60
    if sessions is None:
        legacy = symbol_profiles()["symbols"]
        sessions = {native: (legacy.get(canon) or {}).get("session") for canon, native in symbol_map.items()}
    # Release the parent storage lease BEFORE starting the bundle child process.
    with storage_lease(out_root):
        col = collect(terminal_path, list(symbol_map.values()), start, t_end, out_root=out_root / "raw", mt5_module=mt5_module,
                      process_lister=process_lister, sessions=sessions, tick_start_utc=t_tick, tick_window_s=300,
                      require_trade_mode=require_trade_mode, expect_identity=expect_identity, clock_profile=clock_profile)
        collect_s = time.perf_counter() - started
        b, bundle_error = None, None
        bundle_started = time.perf_counter()
        if col["status"] != "ERROR" and col.get("registry_fragment"):
            try:
                b = build_source_bundle(col, out_root / "bundles", symbol_map)
            except BundleError as exc:
                bundle_error = str(exc)
        bundle_s = time.perf_counter() - bundle_started
    ident = (col.get("manifest") or {}).get("identity") or {}
    res = {"status": None, "collect_status": col["status"], "collect_reason": col.get("reason"), "collect_manifest": col.get("manifest_path"),
           "identity": {k: ident.get(k) for k in ("executable", "data_path", "server", "account_fingerprint", "account_currency",
                                                   "provider_kind", "trade_mode", "build", "connected")} if ident else None,
           "source_id": (col.get("manifest") or {}).get("source_id"),
           "provider_kind": col.get("provider_kind"),
           "clock": {k: (col.get("clock") or {}).get(k) for k in ("status", "reason", "profile", "clock_profile_status", "offset_now_s",
                                                                  "alternatives", "fresh_offsets_s", "flags", "policy",
                                                                  "pinned_by_session", "recheck")} if col.get("clock") else None,
           "window": {"bars_start": iso_utc(start), "end": iso_utc(t_end), "ticks_start": iso_utc(t_tick)}}
    if col["status"] == "ERROR" or not col.get("registry_fragment"):
        res.update({"status": "ERROR", "reason": col.get("reason")})
        return res
    if bundle_error:
        res.update({"status": "ERROR", "reason": bundle_error})
        return res
    res["bundle"] = b
    if not scan:
        res["status"] = "BUNDLE_ONLY"
        return res
    env = dict(os.environ, QUANTMT5_CONFIG_DIR=b["config_dir"], QUANTMT5_STORE=str(out_root / "store"))
    argv = [sys.executable, "-I", "-c", f"import sys; sys.path.insert(0, r'{PROJECT_DIR}'); from quantmt5.cli import main; sys.exit(main(sys.argv[1:]))",
            "paper-scan", "--as-of", iso_utc(as_of if as_of is not None else t_end),
            "--universe", ",".join(symbol_map), "--max-cards", str(max_cards), "--analysis-mode", analysis_mode]
    try:
        p = subprocess.run(argv, env=env, capture_output=True, timeout=scan_timeout_s, stdin=subprocess.DEVNULL)
    except subprocess.TimeoutExpired:
        res.update({"status": "ERROR", "reason": f"SCAN_TIMEOUT_AFTER_{scan_timeout_s}s"})
        return res
    out = p.stdout.decode("utf-8", "replace")
    res["scan_process"] = {"argv": argv[3:], "exit_code": p.returncode, "env": {"QUANTMT5_CONFIG_DIR": b["config_dir"],
                                                                                "QUANTMT5_STORE": str(out_root / "store")},
                           "stderr_tail": p.stderr.decode("utf-8", "replace")[-2000:]}
    try:
        res["scan"] = json.loads(out)
    except json.JSONDecodeError:
        res["scan"] = {"status": "ERROR", "raw": out[-2000:]}
    st = (res["scan"].get("data") or {}).get("status") if isinstance(res["scan"].get("data"), dict) else res["scan"].get("status")
    res["status"] = "OK" if (col["status"] == "OK" and st == "OK" and p.returncode == 0) else "PARTIAL"
    if st == "ERROR" or not isinstance(res["scan"].get("data"), dict):
        res["status"] = "ERROR"
        res["reason"] = ((res["scan"].get("data") or {}).get("reason") or
                         str(res["scan"].get("errors") or res["scan"].get("raw") or res["scan_process"]["stderr_tail"]) or "SCAN_NO_DATA")
    res["timings_s"] = {"collect": round(collect_s, 4), "bundle": round(bundle_s, 4),
                        "paper_run_total": round(time.perf_counter() - started, 4),
                        **((res.get("scan", {}).get("data") or {}).get("timings_s") or {})}
    return res
