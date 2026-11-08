"""B6A source readiness (read-only): process inventory → selected terminal → (only if already running) attach,
verify identity, read pilot symbol profiles and a clock probe. Never launches, logs in, switches accounts or sends
orders; if the selected terminal is not running, `initialize` is NOT called (it could start a terminal)."""
from __future__ import annotations

import os
from typing import Callable

from .collector import ReadOnlyMT5, clock_probe, running_terminal_paths, runtime_enum_contract, validate_profile, verify_attached_identity
from .util import iso_utc, now_utc
from .universe import MAIN8

PILOT = ("XAUUSD", "EURUSD", "USDJPY")
PROFILE_FIELDS = ("name", "path", "digits", "point", "trade_tick_size", "trade_tick_value", "trade_contract_size", "currency_base",
                  "currency_profit", "currency_margin", "volume_min", "volume_max", "volume_step", "trade_stops_level",
                  "trade_freeze_level", "trade_calc_mode", "trade_mode")
COLLECTION_PLAN = {"bars": {"timeframes": ["M1", "M5", "H1", "D1"], "lookback_calendar_days": 35,
                            "reason": "enough H1 history for EMA50/ATR warmup per config; missing warmup is reported, never invented"},
                   "ticks": {"window_minutes": 240, "chunk_s": 300, "reason": "bounded CVD/profile warmup; no multi-year tick download"},
                   "command": "quant.cmd paper-run --terminal-path <selected terminal exe> --universe-preset main8 "
                              "--out-root <isolated operational data> --require-trade-mode 0 --tick-minutes 240",
                   "output": "isolated source store (never config/datasets.json or the main store); registry fragment returned for B6B"}


def _selected_exe(registry: dict) -> str:
    sel = registry["source_identity"]["terminal_executable"]
    return os.path.normcase(os.path.abspath(sel if sel.lower().endswith(".exe") else os.path.join(sel, "terminal64.exe")))


def source_readiness(registry: dict | None = None, symbols=MAIN8, sessions: dict | None = None, attach: bool = True,
                     process_lister: Callable[[], list[str]] = running_terminal_paths, mt5_module=None, now_fn=None) -> dict:
    if registry is None:
        from .data import load_registry
        registry = load_registry()
    exe = _selected_exe(registry)
    running = process_lister()
    out = {"checked_at": iso_utc((now_fn or now_utc)()), "selected_terminal": exe, "running_terminals": running,
           "initialize_called": False, "attach_performed": False, "symbols": {}, "collection_plan": COLLECTION_PLAN,
           "legacy_cache_clock": "UNCHANGED: 2021-2026 cache stays EET_EU ASSUMED / SOURCE_CONFLICT:TIME_BASIS / TIME_UNVERIFIED; "
                                 "a current API probe never verifies the legacy clock or DST history",
           "live_result": None,
           "runtime_contract": runtime_enum_contract() if mt5_module is None else {"status": "NOT_EVALUATED_INJECTED_MODULE_SYNTHETIC"}}
    if exe not in running:
        out.update({"status": "PENDING_LIVE_SOURCE_NOT_RUNNING", "live_result": "PENDING",
                    "reason": "selected terminal not running" + ("; other terminals running (not selected, not used)" if running else ""),
                    "next_step": "user starts the selected terminal (already logged in), then `quant.cmd readiness`"})
        return out
    if len(running) > 1 and running.count(exe) > 1:
        out.update({"status": "AMBIGUOUS_SOURCE", "live_result": "PENDING", "reason": "several processes at the selected path"})
        return out
    if not attach:
        out.update({"status": "READY_TO_ATTACH_NOT_ATTACHED", "live_result": "PENDING"})
        return out
    if mt5_module is None:
        import MetaTrader5 as mt5_module  # noqa: N813
    mt5 = ReadOnlyMT5(mt5_module)
    if exe not in process_lister():                      # re-check immediately before attach
        out.update({"status": "PENDING_LIVE_SOURCE_NOT_RUNNING", "live_result": "PENDING", "reason": "terminal closed before attach"})
        return out
    out["initialize_called"] = True
    if not mt5.initialize(path=exe):
        out.update({"status": "ERROR", "reason": "INITIALIZE_FAILED", "live_result": "ERROR"})
        return out
    out["attach_performed"] = True
    try:
        identity, why = verify_attached_identity(mt5, exe)
        if identity is None:
            out.update({"status": "ERROR", "reason": why, "live_result": "ERROR"})
            return out
        out["identity"] = identity
        complete = True
        for sym in symbols:
            si = mt5.symbol_info(sym)
            if si is None:
                out["symbols"][sym] = {"status": "SYMBOL_NOT_FOUND", "note": "suffix mapping only after contract/calc metadata checks"}
                complete = False
                continue
            sd = si._asdict() if hasattr(si, "_asdict") else dict(si)
            prof = {k: sd.get(k) for k in PROFILE_FIELDS}
            chk = validate_profile(prof)
            complete &= chk["status"] == "COMPLETE"
            out["symbols"][sym] = {"profile": prof, "profile_observed_at": iso_utc(now_utc()), "profile_check": chk,
                                   "clock_probe": clock_probe(mt5, sym, (sessions or {}).get(sym), now_fn=now_fn)}
        out.update({"status": "LIVE_IDENTITY_OK" + ("_PROFILES_COMPLETE" if complete else "_PROFILES_INCOMPLETE"),
                    "live_result": "IDENTITY_OK_CLOCK_NOT_VERIFIED"})
        return out
    finally:
        mt5.shutdown()
