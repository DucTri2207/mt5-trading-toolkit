"""Immutable snapshots + scan lifecycle at an as-of time. Everything is computed from bars available at as_of."""
from __future__ import annotations

import json
from collections import Counter
from contextlib import ExitStack

import numpy as np
from pathlib import Path
from typing import Any

from . import ENGINE_VERSION, SCHEMA_VERSION, STRATEGY_VERSION
from .config import MetadataError, config_hash, cost_profiles, strategy
from .data import dataset_manifest, dataset_version, load_registry
from .detectors import detect_all, load_symbol
from .execution import EconomicsUnavailable, M1OpenProxy, economics_status, make_params, next_session_end, simulate
from .util import STORE_DIR, engine_hash, hash_obj, iso_utc, now_utc, stable_id, write_immutable_json

RELEVANT_LOOKBACK_S = 24 * 3600
HEADLINE = ("BASE", "BASE")  # latency, cost used for the indicative plan in a historical snapshot


def snapshot_path(snapshot_id: str) -> Path:
    return STORE_DIR / "snapshots" / f"{snapshot_id}.json"


def load_snapshot(snapshot_id: str) -> dict:
    p = snapshot_path(snapshot_id)
    if not p.exists():
        raise FileNotFoundError(f"SNAPSHOT_NOT_FOUND:{snapshot_id}")
    return json.loads(p.read_text(encoding="utf-8"))


FRESH_MAX_AGE_S = 600


def _last_reopen(as_of: float, sess: dict, lookback_s: int = 4 * 86400) -> float | None:
    """Most recent scheduled closed→open transition at/before as_of (minute resolution), or None."""
    from .coverage import scheduled_open
    ts = np.arange(int(as_of) // 60 * 60 - lookback_s, int(as_of) + 1, 60, dtype=np.int64)
    op = scheduled_open(ts, sess)
    edges = np.flatnonzero(op[1:] & ~op[:-1]) + 1
    return float(ts[edges[-1]]) if len(edges) else None


def _market_state(sd, as_of: float) -> tuple[str, list[str]]:
    """FRESH / STALE / MARKET_CLOSED_OR_BREAK / UNKNOWN_SCHEDULE — decided by the schedule AT as_of, never by
    data age alone. A long-silent feed while the schedule says open is STALE (incl. just after a reopen)."""
    last_close = float(sd.m5.close_at[-1]) if len(sd.m5) else None
    if last_close is None:
        return "NO_DATA", ["HISTORY_INSUFFICIENT"]
    age = as_of - last_close
    if age <= FRESH_MAX_AGE_S:
        return "FRESH", []
    sess = sd.prof.get("session") or {}
    if not sess or sess.get("tz") != "America/New_York":
        return "UNKNOWN_SCHEDULE", ["STALE_OR_CLOSED_UNKNOWN", "SESSION_SCHEDULE_UNKNOWN"]
    from .coverage import scheduled_open
    if not bool(scheduled_open(np.array([int(as_of)]), sess)[0]):
        return "MARKET_CLOSED_OR_BREAK", ["MARKET_CLOSED"]
    reopen = _last_reopen(as_of, sess)
    if reopen is not None and last_close <= reopen and as_of - reopen <= FRESH_MAX_AGE_S:
        return "STALE", ["STALE", "AWAITING_FIRST_BAR_AFTER_REOPEN"]
    return "STALE", ["STALE", "FEED_STALE_DURING_SCHEDULED_OPEN"]


def plan_status(c: dict, as_of: float, sim: dict | None, economics: dict | None = None) -> dict:
    """Plan lifecycle at as_of, causal: a simulated fill is shown only if its quote time <= as_of."""
    deadline = c["signal_close_ts"] + strategy()["common"]["entry_deadline_s_after_signal_close"]
    if c.get("episode_expires_ts"):
        deadline = min(deadline, c["episode_expires_ts"])
    st = {"deadline_at": iso_utc(deadline),
          "certification": "INDICATIVE_PROXY — quote-side fill/SL Ask/costs are certified in B3, not B2"}
    if as_of < c["ready_ts"]:
        st["state"] = "NOT_YET_READY"
    elif economics and economics.get("status") == "UNKNOWN":
        st.update({"state": "EXECUTION_UNKNOWN_COST", "reason": ";".join(economics["reasons"]),
                   "economics_status": "UNKNOWN", "context_only": True})
    elif sim is None:
        st["state"] = "EXECUTION_UNKNOWN_NO_QUOTE_MODEL"
        st["reason"] = "ASK_MISSING / no M1 or ticks: plan not computable; raw pattern kept"
    else:
        q_at = sim.get("entry_quote", {}).get("t")
        q_ts = _ts(q_at) if q_at else None
        if q_ts is not None and q_ts > as_of:
            st["state"] = "ENTRY_WINDOW_PENDING_QUOTE" if as_of < deadline else "EXPIRED"
        elif sim["status"] == "BLOCKED":
            # decided_at: when the block became known (entry quote time, else the quote request time)
            st.update({"state": "BLOCKED", "reason": sim["reason"], "decided_at": q_at or sim.get("quote_request_at")})
        else:
            st.update({"state": "FILLED_SIMULATED", "decided_at": sim["fill_at"], "fill_at": sim["fill_at"], "entry": sim["entry"], "sl": sim["sl"],
                       "tp": sim["tp"], "R_price": sim["R_price"], "spread_over_R": sim.get("spread_over_R"),
                       "quote_model": sim["quote_model"], "flags": sim["flags"]})
    return st


def plan_window(c: dict, as_of: float) -> dict:
    """B2 lifecycle of a candidate at as_of, independent of execution: per branch
    NOT_YET_READY / ENTRY_WINDOW (eligible, before deadline) / EXPIRED / BLOCKED_BY_GATE / UNKNOWN."""
    out = {}
    for br, el in c["eligibility"].items():
        if as_of < c["ready_ts"]:
            out[br] = "NOT_YET_READY"
        elif el != "ELIGIBLE":
            out[br] = el
        else:
            out[br] = "ENTRY_WINDOW" if as_of < c["entry_deadline_ts"] else "EXPIRED"
    return out


def _ts(iso: str) -> float:
    import datetime as dt
    return dt.datetime.fromisoformat(iso.replace("Z", "+00:00")).timestamp()


def data_state(sd, as_of: float) -> dict:
    """Per-timeframe watermark, last closed bar status and the running (PROVISIONAL) bar — B1 data view."""
    from .data import provisional_bar
    out = {}
    for tf, b in (("M1", sd.m1), ("M5", sd.m5), ("H1", sd.h1), ("D1", sd.d1)):
        if b is None or len(b) == 0:
            out[tf] = {"status": "UNAVAILABLE"}
            continue
        i = len(b) - 1
        out[tf] = {"kind": b.provenance.get("kind"), "rows_available": len(b), "last_closed_open_at": iso_utc(b.open_at[i]),
                   "last_closed_close_at": iso_utc(b.close_at[i]), "last_closed_status": b.status(i, as_of),
                   "last_closed_members": None if b.member_count is None else int(b.member_count[i]),
                   "expected_members_nominal": b.expected_members, "age_s": as_of - float(b.close_at[i])}
    base = {"M5": sd.m1, "H1": sd.m5, "D1": sd.m5}
    out["provisional"] = {tf: (provisional_bar(bb, tf, as_of) if bb is not None else
                               {"status": "UNKNOWN", "reason": "HISTORY_INSUFFICIENT:base timeframe missing"}) for tf, bb in base.items()}
    return out


def make_snapshot(as_of: float, universe: list[str], write: bool = True, include_scan: bool = True) -> dict:
    reg = load_registry()
    from .retention import storage_lease
    paths = sorted({reg["symbols"][s]["ticks"]["chunk_dir"] for s in universe
                    if s in reg["symbols"] and reg["symbols"][s].get("ticks")})
    with ExitStack() as stack:
        for path in paths:
            stack.enter_context(storage_lease(path))
        return _make_snapshot(as_of, universe, reg, write, include_scan)


def _make_snapshot(as_of: float, universe: list[str], reg: dict, write: bool, include_scan: bool) -> dict:
    cfg = strategy()
    costs = cost_profiles()
    versions = {}
    for s in sorted(universe):
        if s in reg["symbols"]:
            try:
                versions[s] = {tf: dataset_version(reg, s, tf) for tf in reg["symbols"][s]["timeframes"]}
            except (OSError, ValueError, KeyError) as e:
                versions[s] = {"status": "ERROR", "reason": str(e)}
    snap_core = {"as_of_utc": iso_utc(as_of), "universe": sorted(universe), "dataset_manifest_hash": hash_obj(dataset_manifest(reg)),
                 "data_versions": versions,
                 "engine_hash": engine_hash(), "config_hash": config_hash(), "strategy_version": STRATEGY_VERSION,
                 "contents": "DATA_AND_SCAN" if include_scan else "DATA_ONLY"}
    from .config import bundle_identity
    from .source_bundle import tick_version
    bi = bundle_identity()
    if bi["kind"] == "SOURCE_BUNDLE":
        # B6B: pin the config/source bundle and the exact collected tick chunk set (replay reads only these).
        snap_core["config_bundle"] = {"bundle_id": bi["bundle_id"], "config_dir": bi["config_dir"], "source_id": bi.get("source_id"),
                                      "provider_kind": bi.get("provider_kind")}
        snap_core["tick_versions"] = {s: tick_version(reg, s) for s in sorted(universe) if s in reg["symbols"] and reg["symbols"][s].get("ticks")}
    sid = stable_id("SNAP", snap_core)
    symbols: dict[str, Any] = {}
    episodes_out, cands_out = [], []
    errors = []
    historical = as_of < now_utc() - 86400
    for sym in sorted(universe):
        try:
            sd = load_symbol(sym, reg, cut_available_at=as_of, pins=versions.get(sym))
        except (MetadataError, KeyError, FileNotFoundError, ValueError) as e:
            errors.append({"symbol": sym, "reason": str(e)})
            symbols[sym] = {"status": "ERROR", "reason": str(e),
                            "native_symbol": (reg.get("symbol_map") or {}).get(sym),
                            "collection_issues": (reg.get("symbol_issues") or {}).get(sym, []),
                            "economics": {"status": "UNKNOWN", "reasons": ["SYMBOL_DATA_OR_METADATA_UNAVAILABLE"]}}
            continue
        if not len(sd.m5):
            errors.append({"symbol": sym, "reason": "HISTORY_INSUFFICIENT:M5_EMPTY"})
            symbols[sym] = {"status": "ERROR", "reason": "HISTORY_INSUFFICIENT:M5_EMPTY",
                            "economics": {"status": "UNKNOWN", "reasons": ["SYMBOL_DATA_OR_METADATA_UNAVAILABLE"]}}
            continue
        state, flags = _market_state(sd, as_of)
        if not sd.prof.get("session"):
            flags.append("SESSION_SCHEDULE_UNKNOWN")
        cost = (costs.get("scenarios") or {}).get(HEADLINE[1]) or {}
        economics = economics_status(sym, sd.prof, cost)
        if economics["status"] == "UNKNOWN":
            flags.append("ECONOMICS_UNKNOWN_CONTEXT_ONLY")
        tv = (snap_core.get("tick_versions") or {}).get(sym) or {}
        ask_flag = ("ASK_FROM_COLLECTED_TICKS_LIMITED_WINDOW:" + str((snap_core.get("config_bundle") or {}).get("provider_kind"))
                    if tv.get("chunks") else "ASK_MISSING")
        flags += list(sd.m5.provenance.get("time_quality_flags", ["TIME_UNVERIFIED"])) + ["NEWS_UNKNOWN", ask_flag]
        for b in (sd.m1, sd.m5, sd.h1, sd.d1):
            if b is not None:
                flags += [f"{f}:{b.tf}" for f in b.provenance.get("data_quality_flags", [])]
        if sd.m1 is None:
            flags.append("HISTORY_INSUFFICIENT:M1_MISSING")
        if historical:
            flags.append("HISTORICAL_AS_OF")
        if not include_scan:
            symbols[sym] = {"status": "OK", "market_state": state, "quality_flags": flags, "economics": economics,
                            "watermark_m5_close_at": iso_utc(sd.m5.close_at[-1]), "bar_watermark_age_s": as_of - float(sd.m5.close_at[-1]),
                            **_quote_age(tv, as_of),
                            "data": data_state(sd, as_of), "exposure": reg["symbols"][sym]["exposure"],
                            "time_lineage": {k: sd.m5.provenance.get(k) for k in ("time_contract", "source_time_basis_recorded", "clock_profile",
                                                                                   "clock_profile_status", "time_basis_status")}}
            continue
        cat = detect_all(sd, cfg)
        rel_from = as_of - RELEVANT_LOOKBACK_S
        qm = params = None
        if sd.m1 is not None and len(sd.m1) and economics["status"] != "UNKNOWN":
            try:
                params = make_params(sym, sd.prof, cost, HEADLINE[1], HEADLINE[0], costs["latency_scenarios_s"][HEADLINE[0]], cfg["common"])
                qm = M1OpenProxy(sd.m1, float(sd.prof["point"]), cost["spread_floor_points"][sym])
            except EconomicsUnavailable as exc:
                economics = {"status": "UNKNOWN", "reasons": [str(exc)]}
                flags.append("ECONOMICS_UNKNOWN_CONTEXT_ONLY")
        rel = [c for c in cat["candidates"] if rel_from <= c["ready_ts"] <= as_of]   # decided at as_of only
        pending_sync = [c["candidate_id"] for c in cat["candidates"] if c["ready_ts"] > as_of]
        for c in rel:
            sim = simulate(c, qm, params) if qm is not None else None
            c2 = {k: v for k, v in c.items() if k not in ("signal_index",)}
            c2["branch_eligibility"] = {g: v["result"] for g, v in c["gates"].items()}
            c2["plan_window"] = plan_window(c, as_of)
            c2["plan"] = plan_status(c, as_of, sim, economics if sd.m1 is not None else None)
            cands_out.append(c2)
        active = [e for e in cat["episodes"] if e["state"] == "WATCHING_RETEST" or e["breakout_close_ts"] >= rel_from]
        for e in active:
            e2 = dict(e)
            if e2["state"] == "WATCHING_RETEST" and as_of >= e2["expires_ts"]:
                e2["state_at_as_of"] = "EXPIRED_PENDING_NEXT_BAR"
            else:
                e2["state_at_as_of"] = e2["state"]
            episodes_out.append(e2)
        symbols[sym] = {"status": "OK", "market_state": state, "quality_flags": flags, "economics": economics,
                        "watermark_m5_close_at": iso_utc(sd.m5.close_at[-1]), "bar_watermark_age_s": as_of - float(sd.m5.close_at[-1]),
                        **_quote_age(tv, as_of),
                        "bars_considered": {"M5": len(sd.m5), "H1": len(sd.h1), "D1": len(sd.d1), "M1": len(sd.m1) if sd.m1 is not None else 0},
                        "catalog_total_to_as_of": len(cat["candidates"]) - len(pending_sync), "relevant_candidates": len(rel),
                        "pending_sync_candidates": pending_sync, "catalog_meta": cat["catalog_meta"],
                        "empty_meaning": ("NO_SETUP_IN_LOOKBACK (scanned OK)" if not rel else None),
                        "relevant_by_setup": dict(Counter(c["setup"] for c in rel)), "execution_quote_model": qm.name if qm else "NONE",
                        "exposure": reg["symbols"][sym]["exposure"], "data": data_state(sd, as_of)}
    snap = {"schema_version": SCHEMA_VERSION, "snapshot_id": sid, **snap_core, "engine_version": ENGINE_VERSION,
            "source_id": reg["source_id"],
            "time_basis": {s: reg["symbols"][s]["time_basis"] for s in sorted(universe) if s in reg["symbols"]},
            "feature_seed_start": "first bar of each registered dataset", "relevant_lookback_s": RELEVANT_LOOKBACK_S,
            "indicative_plan_scenario": {"latency": HEADLINE[0], "cost": HEADLINE[1]},
            "calendar": "UNKNOWN (no point-in-time economic calendar exported)",
            "evidence_status": "ENGINE_VERIFIED only if test suite passes; strategy evidence: see latest evaluate report (RESEARCH/INCONCLUSIVE)",
            "symbols": symbols, "episodes": episodes_out, "candidates": cands_out, "errors": errors}
    if write:
        write_immutable_json(snapshot_path(sid), snap)
        from .retention import register_consumer
        for pin in snap.get("tick_versions", {}).values():
            if pin:
                register_consumer(pin, snapshot_path(sid), kind="snapshot")
    return snap


def catalog_view(snapshot_id: str, symbol: str, from_iso: str | None = None, setup: str | None = None, limit: int = 50) -> dict:
    """Full raw catalog of one symbol up to the snapshot as_of, read through the snapshot's pins/read contract.
    Counts are over every decided candidate; `rows` is a bounded, time-ordered listing."""
    from .context import snapshot_pins
    from .util import parse_utc
    snap = load_snapshot(snapshot_id)
    as_of = parse_utc(snap["as_of_utc"])
    sd = load_symbol(symbol, cut_available_at=as_of, pins=snapshot_pins(snap, symbol))
    cat = detect_all(sd, strategy())
    cands = [c for c in cat["candidates"] if c["ready_ts"] <= as_of and (setup is None or c["setup"] == setup)]
    lo = parse_utc(from_iso) if from_iso else None
    listed = [c for c in cands if lo is None or c["ready_ts"] >= lo]
    gate_counts = {}
    for c in cands:
        for g, v in c["gates"].items():
            gate_counts.setdefault(g, Counter())[v["result"]] += 1
    unknown_reasons = {}
    for c in cands:
        for g, v in c["gates"].items():
            if v["result"] == "UNKNOWN":
                unknown_reasons.setdefault(g, Counter())[v.get("reason")] += 1
    return {"snapshot_id": snapshot_id, "symbol": symbol, "as_of": snap["as_of_utc"], "data_versions_consumed": {
                tf: v.get("content_hash") for tf, v in snap["data_versions"].get(symbol, {}).items()},
            "catalog_meta": cat["catalog_meta"], "candidates_total": len(cands),
            "by_setup_side": dict(Counter(f"{c['setup']}_{c['side']}" for c in cands)),
            "gate_counts": {g: dict(v) for g, v in gate_counts.items()}, "unknown_reasons": {g: dict(v) for g, v in unknown_reasons.items()},
            "episodes_total": len(cat["episodes"]), "episode_states": dict(Counter(e["state"] for e in cat["episodes"])),
            "rows": [{"candidate_id": c["candidate_id"], "revision_id": c["revision_id"], "setup": c["setup"], "side": c["side"],
                      "signal_close_at": c["signal_bar"]["close_at"], "ready_at": c["ready_at"],
                      "gates": {g: v["result"] for g, v in c["gates"].items()}, "plan_window": plan_window(c, as_of)}
                     for c in listed[-limit:]],
            "rows_note": f"last {min(limit, len(listed))} of {len(listed)} listed (from={from_iso}); counts cover all",
            "quality_flags": snap["symbols"].get(symbol, {}).get("quality_flags")}


def scan(snap: dict) -> dict:
    """Summarise a snapshot into the scanner view: pending / eligible / blocked / expired, by symbol."""
    rows = []
    for c in snap["candidates"]:
        rows.append({"candidate_id": c["candidate_id"], "revision_id": c.get("revision_id"), "symbol": c["symbol"], "setup": c["setup"],
                     "side": c["side"], "ready_at": c["ready_at"], "branch_eligibility": c["branch_eligibility"],
                     "plan_window": c.get("plan_window"), "entry_deadline_at": c.get("entry_deadline_at"),
                     "plan_state": c["plan"]["state"], "plan_reason": c["plan"].get("reason"), "plan_certification": c["plan"].get("certification"), "level": c.get("level") or (c["gates"].get("P1", {}).get("PDL") if c["side"] == "LONG" else c["gates"].get("P1", {}).get("PDH"))})
    ok_syms = [s for s, v in snap["symbols"].items() if v.get("status") == "OK"]
    if not ok_syms:
        status = "ERROR"
    elif len(ok_syms) < len(snap["symbols"]) or any(
            f.startswith("ARRIVAL_HOLE_BARS_WITHHELD") for v in snap["symbols"].values() for f in v.get("quality_flags", [])):
        status = "PARTIAL"        # some arrived bars are withheld behind a not-yet-arrived bar: not a full scan
    elif not rows:
        status = "OK_EMPTY"
    else:
        status = "OK"
    return {"status": status, "rows": rows, "by_symbol": {s: dict(Counter(r["plan_state"] for r in rows if r["symbol"] == s)) for s in snap["symbols"]},
            "active_episodes": [{"episode_id": e["episode_id"], "symbol": e["symbol"], "side": e["side"], "U": e["U"], "D": e["D"],
                                 "state_at_as_of": e["state_at_as_of"], "expires_at": e["expires_at"]} for e in snap["episodes"]],
            "symbols_considered": {s: {k: v.get(k) for k in ("status", "market_state", "quality_flags", "watermark_m5_close_at",
                                                                "relevant_candidates", "reason", "economics", "collection_issues")} for s, v in snap["symbols"].items()}}


def _quote_age(tv: dict, as_of: float) -> dict:
    """043 F2: quote age comes only from a pinned collected tick tape (UTC via its clock profile); a closed bar is not a quote.
    Without a tape the age is UNKNOWN (bar_watermark_age_s is the separate closed-bar delay)."""
    lasts = [int(c["last_ms"]) for c in (tv or {}).get("chunks") or [] if c.get("last_ms") is not None]
    if not lasts:
        return {"quote_age_s": None, "quote_age_status": "UNKNOWN_NO_TICK_TAPE", "quote_age_basis": "no pinned tick tape"}
    import numpy as _np
    from .replay import pinned_ticks_utc
    raw = _np.zeros(1, dtype=[("time_msc", "i8")])
    raw["time_msc"][0] = max(lasts)
    last = int(pinned_ticks_utc(raw, tv)["time_msc"][0]) / 1000.0
    if last > as_of + 1e-9:
        return {"quote_age_s": None, "quote_age_status": "ERROR_TICK_AFTER_AS_OF", "last_tick_at": iso_utc(last),
                "quote_age_basis": "pinned tick newer than as_of: clock mismatch suspected, not treated as fresh"}
    return {"quote_age_s": round(as_of - last, 3), "quote_age_status": "FROM_PINNED_TICK_TAPE", "last_tick_at": iso_utc(last),
            "quote_age_basis": "as_of - last committed pinned tick (clock " + str(tv.get("clock_profile", "RAW_IS_UTC")) + "); not a live quote"}
