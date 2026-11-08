"""B3 replay: reproducible ledger rows from (candidate revision + snapshot data pins + quote/cost/latency/risk versions).

Decision fields use only data known at ready/quote time (B2 arrival contract + B3 first-usable quote); outcome fields
(exit, MAE/MFE) necessarily use quotes after the fill and are labelled as such. Nothing here sends orders.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np

from .analysis_cache import cached
from .config import config_hash, cost_profiles, strategy
from .data import Ticks
from .detectors import detect_all, load_symbol
from .execution import EXECUTION_MODEL_VERSION, M1OpenProxy, TickQuotes, economics_status, make_params, simulate
from .util import engine_hash, hash_obj, iso_utc, parse_utc, stable_id


def load_tick_file(path: str | Path, symbol: str, kind: str = "SYNTHETIC_FIXTURE") -> TickQuotes:
    """npz with a structured array `ticks` (time_msc, bid, ask[, available_msc]); times are UTC under API_UTC_CONTRACT."""
    with np.load(path, allow_pickle=False) as z:
        a = z["ticks"]
    names = a.dtype.names or ()
    t = Ticks(symbol, a["time_msc"].astype(np.int64), a["bid"].astype(float), a["ask"].astype(float),
              a["flags"].astype(np.int64) if "flags" in names else np.zeros(len(a), np.int64), {"path": str(path)})
    return TickQuotes(t, a["available_msc"] if "available_msc" in names else None, kind=kind, source=f"{kind}:{Path(path).name}")


TICK_COVERED = ("OK", "EMPTY_MARKET_CLOSED")


def tick_covered_spans(pin: dict) -> list[tuple[int, int]]:
    """Merged [start, end) spans of pinned tick windows whose status is covered; failed/unexplained/partial windows
    are holes."""
    ivs = sorted((int(k.split("_")[0]), int(k.split("_")[1])) for k, st in (pin.get("window_states") or {}).items() if st in TICK_COVERED)
    out: list[list[int]] = []
    for a, b in ivs:
        if out and a <= out[-1][1]:
            out[-1][1] = max(out[-1][1], b)
        else:
            out.append([a, b])
    return [(a, b) for a, b in out]


def _covered_end(spans, t0: float) -> float | None:
    """End of the covered span containing t0 (None if t0 itself is not covered)."""
    for a, b in spans:
        if a <= t0 < b:
            return float(b)
    return None


def pinned_tick_array(pin: dict) -> np.ndarray:
    """Every pinned tick chunk must exist with its pinned sha256 (DataVersionMismatch otherwise), whatever the
    coverage outcome later is: a proxy fallback must never hide a missing/changed pinned file."""
    a, error = pinned_tick_tape(pin)
    if error in ("TIME_FIELD_MISSING", "TIME_INVALID"):
        from .data import DataVersionMismatch
        raise DataVersionMismatch(error)
    return a


def pinned_tick_tape(pin: dict) -> tuple[np.ndarray, str | None]:
    """One decode with original-order evidence, stable same-ms multiplicity.

    Validate retention and every checksum on *every* call, including cache hits.
    A purged/replaced file must not become readable from an in-memory cache.
    """
    from .data import DataVersionMismatch
    from .retention import RetentionError, assert_tick_available, storage_lease
    from .util import sha256_file
    try:
        with storage_lease(pin["chunk_dir"]):
            assert_tick_available(pin)
            chunks = pin.get("chunks") or []
            if not chunks:
                raise DataVersionMismatch("NO_PINNED_TICK_CHUNKS")
            for ch in chunks:
                p = Path(pin["chunk_dir"]) / ch["file"]
                if not p.exists() or sha256_file(p) != ch["sha256"]:
                    raise DataVersionMismatch(f"TICK_CHUNK_MISSING_OR_CHANGED:{p}")
            def decode():
                parts = []
                for ch in chunks:
                    with np.load(Path(pin["chunk_dir"]) / ch["file"], allow_pickle=False) as z:
                        parts.append(z["ticks"])
                a = np.concatenate(parts)
                if "time_msc" not in (a.dtype.names or ()):
                    return a, "TIME_FIELD_MISSING"
                try:
                    unordered = bool(len(a) > 1 and np.any(np.diff(a["time_msc"].astype(np.int64)) < 0))
                except (TypeError, ValueError, OverflowError):
                    return a, "TIME_INVALID"
                if unordered:
                    a = a[np.argsort(a["time_msc"], kind="stable")]
                # Cached tapes are source evidence; no consumer may modify them.
                a.flags.writeable = False
                return a, "TICKS_UNSORTED" if unordered else None
            return cached("tick_tape", hash_obj(pin), decode)
    except RetentionError as exc:
        raise DataVersionMismatch(str(exc)) from exc


def pinned_ticks_utc(a: np.ndarray, pin: dict) -> np.ndarray:
    """Stored time_msc is the raw source clock; convert once with the pin's clock profile (RAW_IS_UTC = unchanged)."""
    clock = pin.get("clock_profile", "RAW_IS_UTC")
    if clock == "RAW_IS_UTC" or not len(a):
        return a
    from .timemap import server_to_utc
    a = a.copy()
    tm = a["time_msc"].astype(np.int64)
    a["time_msc"] = server_to_utc(tm // 1000, clock) * 1000 + tm % 1000
    return a


def load_pinned_ticks(pin: dict, symbol: str, provider_kind: str | None, until: float | None = None,
                      verified: np.ndarray | None = None) -> TickQuotes:
    """Exactly the pinned collected tick chunks (sha-verified). Arrival time is not recorded by the API → assumed at
    event and flagged by TickQuotes."""
    if verified is not None:
        from .data import DataVersionMismatch
        from .retention import RetentionError, assert_tick_available
        try:
            assert_tick_available(pin)
        except RetentionError as exc:
            raise DataVersionMismatch(str(exc)) from exc
    a = verified if verified is not None else pinned_tick_array(pin)
    a = pinned_ticks_utc(a, pin)
    if until is not None:
        a = a[a["time_msc"] < int(until * 1000)]                     # tape ends where verified coverage ends
    names = a.dtype.names or ()
    t = Ticks(symbol, a["time_msc"].astype(np.int64), a["bid"].astype(float), a["ask"].astype(float),
              a["flags"].astype(np.int64) if "flags" in names else np.zeros(len(a), np.int64), {"tick_pin": pin.get("content_hash")})
    kind = "COLLECTED_NATIVE_TICKS" if provider_kind == "NATIVE_TERMINAL" else "COLLECTED_SYNTHETIC_TICKS"
    return TickQuotes(t, None, kind=kind, source=f"{kind}:{pin.get('content_hash', '')[:12]}")


def _grade(quote_basis: str | None, cert: str | None, provider: str | None) -> str:
    if quote_basis is None:
        return "UNKNOWN_NO_QUOTE_MODEL"
    if quote_basis.startswith("COLLECTED_"):
        src = "NATIVE" if provider == "NATIVE_TERMINAL" else "SYNTHETIC"
        return f"{src}_TICK_" + ("EXACT" if cert == "EXACT_QUOTE_PATH" else "PARTIAL_COVERAGE")
    if quote_basis == "TICK_FILE":
        return "TICK_FILE_" + ("EXACT" if cert == "EXACT_QUOTE_PATH" else "UNKNOWN")
    return "PROXY_M1_OPEN_NOT_EVIDENCE"


def quote_model_for(sd, cost_name: str, ticks: TickQuotes | None = None):
    if ticks is not None:
        return ticks, None
    if sd.m1 is not None:
        cost = cost_profiles()["scenarios"][cost_name]
        economics = economics_status(sd.symbol, sd.prof, cost)
        if economics["status"] == "UNKNOWN":
            return None, "ECONOMICS_UNKNOWN:" + ";".join(economics["reasons"])
        return M1OpenProxy(sd.m1, float(sd.prof["point"]), float(cost["spread_floor_points"][sd.symbol])), None
    return None, "NO_QUOTE_MODEL: no ticks and no M1 for this symbol (ASK_MISSING) — execution UNKNOWN, raw candidate kept"


def ledger_row(cand: dict, qm, p, branch: str | None = None) -> dict:
    sim = simulate(cand, qm, p)
    sim["branch"] = branch
    sim["ledger_row_id"] = stable_id("LEDGER", sim["fill_id"], branch)
    return sim


def replay(candidate_id: str, symbol: str | None = None, latency: str = "BASE", cost: str = "BASE", snapshot_id: str | None = None,
           ticks_path: str | None = None, risk: dict | None = None) -> dict:
    cfg = strategy()
    costs = cost_profiles()
    pins = None
    if snapshot_id:
        from .context import snapshot_pins
        from .snapshot import load_snapshot
        snap = load_snapshot(snapshot_id)
        symbol = symbol or next((c["symbol"] for c in snap["candidates"] if c["candidate_id"] == candidate_id), None)
        if symbol is None:
            return {"found": False, "candidate_id": candidate_id, "reason": "CANDIDATE_NOT_IN_SNAPSHOT"}
        pins = snapshot_pins(snap, symbol)
    sd = load_symbol(symbol, pins=pins)
    cat = detect_all(sd, cfg)
    cand = next((c for c in cat["candidates"] if c["candidate_id"] == candidate_id), None)
    if cand is None:
        return {"found": False, "candidate_id": candidate_id}
    ep = next((e for e in cat["episodes"] if e["episode_id"] == cand.get("episode_id")), None)
    ticks = load_tick_file(ticks_path, symbol) if ticks_path else None
    quote_basis, tick_note, tick_cert = ("TICK_FILE" if ticks is not None else None), None, None
    provider = (snap.get("config_bundle") or {}).get("provider_kind") if snapshot_id else None
    if ticks is None and snapshot_id and (snap.get("tick_versions") or {}).get(symbol):
        tpin = snap["tick_versions"][symbol]
        if tpin.get("chunks"):
            verified_ticks = pinned_tick_array(tpin)          # F5: integrity first — before any coverage/proxy branch
            cc = cfg["common"]
            sig_close = float(cand["signal_close_ts"])
            need_from = (parse_utc(cand["signal_bar"]["open_at"]) if cand["side"] == "SHORT"
                         else sig_close)                                                 # short SL needs the signal-bar Ask high
            deadline = sig_close + float(cc["entry_deadline_s_after_signal_close"])
            horizon = deadline + float(cc["max_hold_minutes"]) * 60 + 300.0             # time-exit quote slack
            spans = tick_covered_spans(tpin)
            cov_end = _covered_end(spans, need_from)
            if cov_end is None or cov_end < deadline:
                tick_note = (f"PINNED_TICKS_DO_NOT_COVER_CANDIDATE_ENTRY_WINDOW: coverage gap in [{iso_utc(need_from)}, {iso_utc(deadline)}]; "
                             "first quote/deadline not decidable from ticks; M1 proxy used, labelled")
            else:
                tq = load_pinned_ticks(tpin, symbol, provider, until=None if cov_end >= horizon else cov_end, verified=verified_ticks)
                if len(tq.t) and tq.t[0] <= float(cand["ready_ts"]) and tq.t[-1] >= deadline:
                    ticks, quote_basis = tq, tq.kind
                    if cov_end >= horizon:
                        tick_cert = "EXACT_QUOTE_PATH"
                    else:
                        tick_cert = "TICK_PATH_PARTIAL_COVERAGE"
                        tick_note = f"TICK_COVERAGE_ENDS_AT {iso_utc(cov_end)} before the exit horizon {iso_utc(horizon)}: later outcome unresolved"
                else:
                    tick_note = "PINNED_TICKS_DO_NOT_COVER_CANDIDATE_ENTRY_WINDOW: proxy used, labelled"
        else:
            tick_note = "NO_PINNED_TICK_CHUNKS"
    qm, why = quote_model_for(sd, cost, ticks)
    if quote_basis is None and qm is not None:
        quote_basis = qm.name
    versions = {"engine_hash": engine_hash(), "config_hash": config_hash(), "execution_model_version": EXECUTION_MODEL_VERSION,
                "cost_profile_version": costs["cost_profile_version"], "latency_s": costs["latency_scenarios_s"][latency],
                "candidate_revision": cand["revision_id"], "risk_profile": hash_obj(risk)[:16] if risk else None,
                "data_versions": {tf: (v or {}).get("content_hash") for tf, v in (pins or {}).items()} if pins else "UNPINNED_CURRENT_REGISTRY"}
    timeline = []
    if ep:
        timeline.append({"t": ep["activated_at"], "event": "ANCHOR_ACTIVATED", "zone": {"U": ep["U"], "D": ep["D"]}, "anchor_at": ep["anchor_at"]})
        for tr in ep["transitions"]:
            timeline.append({"t": tr["available_at"], "event": f"EPISODE_{tr['state']}", "reason": tr["reason"]})
    timeline.append({"t": cand["ready_at"], "event": "CANDIDATE_READY", "gates": {k: v["result"] for k, v in cand["gates"].items()}})
    sim, flags = None, []
    economics = economics_status(symbol, sd.prof, cost_profiles()["scenarios"][cost], require_spread_floor=ticks is None)
    if economics["status"] == "UNKNOWN":
        why = "ECONOMICS_UNKNOWN:" + ";".join(economics["reasons"])
        flags = ["EXECUTION_UNKNOWN", "ECONOMICS_UNKNOWN"]
        if qm is None and ticks is None and sd.m1 is None:
            flags += ["ASK_MISSING", "HISTORY_INSUFFICIENT:M1_MISSING"]
    elif qm is None:
        flags = ["EXECUTION_UNKNOWN", "ASK_MISSING", "HISTORY_INSUFFICIENT:M1_MISSING"]
    else:
        c = cost_profiles()["scenarios"][cost]
        params = make_params(symbol, sd.prof, c, cost, latency, costs["latency_scenarios_s"][latency], cfg["common"],
                             price_hint=cand["signal_bar"]["c"], risk=risk)
        sim = ledger_row(cand, qm, params)
        flags = sim["flags"]
        for tr in sim["transitions"]:
            timeline.append({"t": tr.get("event_at"), "event": f"PLAN_{tr['state']}", "reason": tr.get("reason")})
    timeline.sort(key=lambda x: (x["t"] or "9999"))
    return {"found": True, "candidate": cand, "episode": ep, "scenario": {"latency": latency, "cost": cost},
            "quote_model": None if qm is None else {"name": qm.name, "kind": getattr(qm, "kind", None), "version": qm.version_id()},
            "execution": sim, "execution_unknown_reason": why, "timeline": timeline, "flags": flags, "versions": versions,
            "economics": economics,
            "quote_basis": quote_basis, "tick_note": tick_note,
            "certification": (tick_cert or ("EXACT_QUOTE_PATH" if (qm is not None and qm.name == "TICKS") else
                                            "PROXY_NOT_EXACT" if qm is not None else "UNKNOWN")),
            "evidence_grade": _grade(quote_basis, tick_cert or ("EXACT_QUOTE_PATH" if (qm is not None and qm.name == "TICKS") else None), provider),
            "counts_as_native_evidence": bool(provider == "NATIVE_TERMINAL" and (tick_cert == "EXACT_QUOTE_PATH")),
            "note": "outcome fields use quotes after the fill; decision fields use only data known at ready/quote time"}
