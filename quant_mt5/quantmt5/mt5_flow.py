"""Native MT5 tick flow for FABIO.

This module is deliberately read-only: it consumes the tick pin already carried
by a snapshot and never imports or calls the MetaTrader5 package.
"""
from __future__ import annotations

import datetime as _dt
import math
from typing import Any

import numpy as np

from .replay import pinned_tick_tape, pinned_ticks_utc, tick_covered_spans
from .util import iso_utc

# MetaTrader5 TICK_FLAG_* values: BUY=32, SELL=64, LAST=8, VOLUME=16.
_BUY, _SELL, _LAST, _VOLUME = 32, 64, 8, 16
_MAX_TAPE_S = 24 * 60 * 60


def _num(v: Any, *, integer: bool = False) -> float | int | None:
    if isinstance(v, (bool, np.bool_)):
        return None
    try:
        x = int(v) if integer else float(v)
    except (TypeError, ValueError, OverflowError):
        return None
    return x if math.isfinite(float(x)) else None


def _pin(snapshot: dict, symbol: str) -> dict | None:
    if not isinstance(snapshot, dict):
        return None
    tv = snapshot.get("tick_versions") or snapshot.get("ticks") or {}
    if isinstance(tv, dict):
        p = tv.get(symbol)
        if isinstance(p, dict):
            return p
    p = snapshot.get("tick_pin")
    return p if isinstance(p, dict) else None


def _provider(snapshot: dict, pin: dict) -> str:
    return str(pin.get("provider_kind") or (snapshot.get("config_bundle") or {}).get("provider_kind")
               or snapshot.get("provider_kind") or "UNKNOWN")


def _reject(reason: str, *, source: str = "MT5", **extra: Any) -> dict:
    out = {"status": "REJECTED", "reasons": [reason], "use_in_decision": False,
           "source": source, "is_proxy": True, "evidence_kind": "MT5_INVALID"}
    out.update(extra)
    return out


def _empty(reason: str, *, provider: str, pin: dict | None = None) -> dict:
    kind = "MT5_TICK_DIRECTION_PROXY" if provider == "NATIVE_TERMINAL" else "SYNTHETIC_TICK_DIRECTION_PROXY"
    return {"status": "NO_USABLE_BARS", "reasons": [reason], "use_in_decision": False,
            "source": "MT5", "is_proxy": True, "evidence_kind": kind,
            "volume_basis": "TICK_COUNT_PROXY", "side_method": "MIDPOINT_CHANGE",
            "route": "FTMO_PRICE_PROXY", "provider_kind": provider,
            "provenance": {"provider_kind": provider, "pin_content_hash": (pin or {}).get("content_hash")}}


def _raw_ordered(pin: dict) -> tuple[np.ndarray, str | None]:
    """The verified decode retains raw-order evidence; never load a second tape."""
    return pinned_tick_tape(pin)


def _contains(spans: list[tuple[int, int]], a: float, b: float) -> bool:
    return any(float(x) <= a and b <= float(y) for x, y in spans)


def _day_start(ts: float) -> float:
    d = _dt.datetime.fromtimestamp(ts, _dt.timezone.utc).date()
    return _dt.datetime.combine(d, _dt.time.min, tzinfo=_dt.timezone.utc).timestamp()


def read_snapshot_mt5(snapshot: dict, m5, symbol: str, as_of: float, chart_basis: str = "BID") -> dict:
    """Return aligned MT5 CVD/proxy flow plus latest causal bid/ask quote.

    A valid BUY/SELL flag and positive trade volume on every trade event yields
    executed delta. Any ambiguous trade event downgrades the complete tape to a
    midpoint-change proxy; it never fabricates signed M1 volume.
    """
    asof = _num(as_of)
    pin = _pin(snapshot, symbol)
    provider = _provider(snapshot if isinstance(snapshot, dict) else {}, pin or {})
    if asof is None:
        return {"flow": _reject("AS_OF_INVALID"), "exec": None,
                "provenance": {"provider_kind": provider}}
    if pin is None or not pin.get("chunks"):
        fl = _empty("NO_MT5_TICK_PIN", provider=provider, pin=pin)
        return {"flow": fl, "exec": None,
                "provenance": {"provider_kind": provider, "source": "MT5"}}
    try:
        arr, order_error = _raw_ordered(pin)
    except Exception:
        # DataVersionMismatch is intentionally allowed through: callers must not hide a tampered pin.
        raise
    if order_error:
        fl = _reject(order_error, provider_kind=provider)
        return {"flow": fl, "exec": None, "provenance": {"provider_kind": provider, "source": "MT5"}}
    try:
        arr = pinned_ticks_utc(arr, pin)  # exactly one clock conversion
    except Exception:
        fl = _reject("CLOCK_CONVERSION_INVALID", provider_kind=provider)
        return {"flow": fl, "exec": None, "provenance": {"provider_kind": provider, "source": "MT5"}}
    names = arr.dtype.names or ()
    required = {"time_msc", "bid", "ask"}
    if not required.issubset(names):
        fl = _reject("TICK_FIELDS_MISSING", provider_kind=provider)
        return {"flow": fl, "exec": None, "provenance": {"provider_kind": provider, "source": "MT5"}}
    try:
        tm = arr["time_msc"].astype(np.int64)
        bid = arr["bid"].astype(float); ask = arr["ask"].astype(float)
    except (TypeError, ValueError, OverflowError):
        fl = _reject("TICK_NUMERIC_INVALID", provider_kind=provider)
        return {"flow": fl, "exec": None, "provenance": {"provider_kind": provider, "source": "MT5"}}
    if not (np.isfinite(tm).all() and np.isfinite(bid).all() and np.isfinite(ask).all()):
        fl = _reject("TICK_NUMERIC_INVALID", provider_kind=provider)
        return {"flow": fl, "exec": None, "provenance": {"provider_kind": provider, "source": "MT5"}}
    if np.any(bid <= 0) or np.any(ask <= 0) or np.any(ask < bid):
        fl = _reject("QUOTE_INVALID", provider_kind=provider)
        return {"flow": fl, "exec": None, "provenance": {"provider_kind": provider, "source": "MT5"}}
    avail = arr["available_msc"].astype(np.int64) if "available_msc" in names else None
    if avail is not None and (np.any(avail < 0) or not np.isfinite(avail).all()):
        fl = _reject("AVAILABLE_TIME_INVALID", provider_kind=provider)
        return {"flow": fl, "exec": None, "provenance": {"provider_kind": provider, "source": "MT5"}}
    volumes = [arr[k].astype(float) for k in ("volume_real", "volume") if k in names]
    vol = volumes[0] if volumes else None
    if any(not np.isfinite(v).all() or np.any(v < 0) for v in volumes):
        fl = _reject("VOLUME_INVALID", provider_kind=provider)
        return {"flow": fl, "exec": None, "provenance": {"provider_kind": provider, "source": "MT5"}}
    if len(volumes) == 2:
        vol = np.where(volumes[0] > 0, volumes[0], volumes[1])
    flags = arr["flags"].astype(np.int64) if "flags" in names else np.zeros(len(arr), dtype=np.int64)
    last = arr["last"].astype(float) if "last" in names else None
    if last is not None and (not np.isfinite(last).all() or np.any(last < 0)):
        fl = _reject("LAST_INVALID", provider_kind=provider)
        return {"flow": fl, "exec": None, "provenance": {"provider_kind": provider, "source": "MT5"}}

    event_s = tm.astype(float) / 1000.0
    event_ordered = bool(len(event_s) < 2 or np.all(np.diff(event_s) >= 0))
    known_s = avail.astype(float) / 1000.0 if avail is not None else event_s
    causal = (event_s <= asof + 1e-9) & (known_s <= asof + 1e-9)
    # The quote path is independent of coverage and remains available on a sparse tape.
    ex = None
    for i in np.flatnonzero(causal)[::-1]:
        if bid[i] > 0 and ask[i] >= bid[i]:
            ex = {"schema": "fabio_exec_v1", "symbol": symbol, "event_at": iso_utc(float(event_s[i])),
                  "known_at": iso_utc(max(float(event_s[i]), float(known_s[i]))),
                  "bid": float(bid[i]), "ask": float(ask[i]), "commission_round_turn_price": None,
                  "slippage_price": None, "source": "MT5", "provenance": "NATIVE_TERMINAL" if provider == "NATIVE_TERMINAL" else provider}
            break

    spans = tick_covered_spans(pin)
    n = len(m5.open_at)
    try:
        m5_open = np.asarray(m5.open_at, dtype=float); m5_close = np.asarray(m5.close_at, dtype=float)
        if len(m5_open) != len(m5_close) or not np.isfinite(m5_open).all() or not np.isfinite(m5_close).all():
            raise ValueError
    except (TypeError, ValueError, OverflowError):
        fl = _reject("M5_NUMERIC_INVALID", provider_kind=provider)
        return {"flow": fl, "exec": ex, "provenance": {"provider_kind": provider, "source": "MT5"}}
    delta = np.full(n, np.nan); total = np.full(n, np.nan)
    lower = asof - _MAX_TAPE_S
    retained_mode = causal & (event_s >= lower)
    real_possible = bool(last is not None and vol is not None)
    ambiguous_trade = False
    if real_possible:
        # A positive carried volume/last without an update flag is quote-only data.
        trade = (flags & (_BUY | _SELL | _LAST | _VOLUME)) != 0
        side = ((flags & _BUY) != 0).astype(int) - ((flags & _SELL) != 0).astype(int)
        active_trade = trade & retained_mode
        ambiguous_trade = bool(np.any(active_trade & ~((vol > 0) & (last > 0) & (side != 0))))
        real_possible = bool(np.any(active_trade) and not ambiguous_trade)
    basis = "EXECUTED_TRADES" if real_possible else "TICK_COUNT_PROXY"
    method = "MT5_BUY_SELL_FLAGS" if real_possible else "MIDPOINT_CHANGE"
    prev_mid = None
    for j in range(n):
        op, cl = float(m5_open[j]), float(m5_close[j])
        if j and op != float(m5_close[j - 1]):
            prev_mid = None
        bar_known = float(m5.available_at[j]) if hasattr(m5, "available_at") else cl
        if op < lower or cl > asof + 1e-9 or bar_known > asof + 1e-9 or cl <= op or not _contains(spans, op, cl):
            prev_mid = None
            continue
        # Event time is ordered; arrival time need not be. Apply causal masking
        # within the indexed interval, retaining each same-millisecond quote.
        if event_ordered:
            lo = int(np.searchsorted(event_s, op, side="left"))
            hi = int(np.searchsorted(event_s, cl, side="left"))
            ii = np.flatnonzero(causal[lo:hi]) + lo
        else:  # Preserve source-order semantics for a non-monotone clock mapping.
            ii = np.flatnonzero(causal & (event_s >= op) & (event_s < cl))
        if not len(ii):
            prev_mid = None
            continue
        if real_possible:
            ti = ii[trade[ii]]
            d = np.sum(side[ti] * vol[ti]) if len(ti) else 0.0
            t = np.sum(vol[ti]) if len(ti) else 0.0
        else:
            mids = bid[ii] / 2.0 + ask[ii] / 2.0
            signs = np.zeros(len(mids), dtype=float)
            if prev_mid is not None:
                signs[0] = np.sign(mids[0] - prev_mid)
            if len(mids) > 1:
                signs[1:] = np.sign(mids[1:] - mids[:-1])
            prev_mid = float(mids[-1])
            d = float(np.sum(signs)); t = float(len(ii))
        if not (math.isfinite(float(d)) and math.isfinite(float(t))):
            fl = _reject("DERIVED_FLOW_NONFINITE", provider_kind=provider)
            return {"flow": fl, "exec": ex, "provenance": {"provider_kind": provider, "source": "MT5"}}
        delta[j], total[j] = float(d), float(t)

    cvd = np.full(n, np.nan); start = n; segment_start = n
    reset_at = None
    running = 0.0
    prev_day = None
    for j in range(n):
        if not np.isfinite(delta[j]):
            prev_day = None
            segment_start = n
            continue
        if j and m5_open[j] != m5_close[j - 1]:
            prev_day = None
        day = _dt.datetime.fromtimestamp(float(m5_open[j]), _dt.timezone.utc).date()
        if prev_day is None or day != prev_day:
            running = 0.0; reset_at = _day_start(float(m5_open[j])); segment_start = j
        running += float(delta[j]); cvd[j] = running; prev_day = day
        if not math.isfinite(running):
            fl = _reject("DERIVED_FLOW_NONFINITE", provider_kind=provider)
            return {"flow": fl, "exec": ex, "provenance": {"provider_kind": provider, "source": "MT5"}}
    have = np.flatnonzero(np.isfinite(delta))
    start = segment_start if len(have) else n
    with np.errstate(over="ignore", invalid="ignore"):
        totals_finite = np.isfinite(np.cumsum(total[have])).all()
    if not (np.isfinite(delta[have]).all() and np.isfinite(total[have]).all() and totals_finite):
        fl = _reject("DERIVED_FLOW_NONFINITE", provider_kind=provider)
        return {"flow": fl, "exec": ex, "provenance": {"provider_kind": provider, "source": "MT5"}}
    recent = slice(max(0, n - 24), n)
    cov = float(np.isfinite(delta[recent]).mean()) if n else 0.0
    provenance = {"provider_kind": provider, "source": "MT5", "clock_profile": pin.get("clock_profile", "RAW_IS_UTC"),
                  "arrival_assumption": "available_msc" if avail is not None else "event_time_assumed", "covered_spans": spans,
                  "tape_window_s": _MAX_TAPE_S}
    native = provider == "NATIVE_TERMINAL"
    trade_route = "FTMO_NATIVE_TICK_FLOW" if native else "SYNTHETIC_TICK_FLOW"
    trade_kind = "MT5_EXECUTED_TRADE_FLOW" if native else "SYNTHETIC_EXECUTED_TRADE_FLOW"
    proxy_kind = "MT5_TICK_DIRECTION_PROXY" if native else "SYNTHETIC_TICK_DIRECTION_PROXY"
    stale = bool(len(have) and asof - m5_close[have[-1]] > 600.0)
    reasons = []
    if ambiguous_trade:
        reasons.append("AMBIGUOUS_TRADE_SIDE_PROXY")
    if not len(have):
        reasons.append("NO_FULL_M5_WINDOWS")
    elif cov < 0.9:
        reasons.append("COVERAGE_LOW")
    if stale:
        reasons.append(f"FLOW_LAG_{int(asof - m5_close[have[-1]])}s")
    fl = {"status": "NO_USABLE_BARS" if not len(have) else "STALE" if stale else "COVERAGE_LOW" if cov < 0.9 else "USABLE",
          "reasons": reasons,
          "use_in_decision": bool(len(have) and cov >= 0.9 and not stale), "delta": delta, "total": total, "cvd": cvd,
          "cvd_start_index": int(start), "coverage_window": cov,
          "lag_s": (float(asof - m5_close[have[-1]]) if len(have) else None), "bars_used": int(len(have)),
          "reset_at": iso_utc(reset_at) if reset_at is not None else None,
          "last_flow_close_at": iso_utc(float(m5.close_at[have[-1]])) if len(have) else None,
          "volume_basis": basis, "side_method": method,
          "route": trade_route if real_possible else "FTMO_PRICE_PROXY", "source": "MT5",
          "provenance": provenance, "provider_kind": provider, "is_proxy": not real_possible,
          "evidence_kind": trade_kind if real_possible else proxy_kind}
    if len(have):
        fl["latest_delta"] = float(delta[have[-1]])
        fl["last_cvd"] = float(cvd[have[-1]]) if np.isfinite(cvd[have[-1]]) else None
    retained = retained_mode
    clipped_spans = [(max(float(a), lower), min(float(b), asof)) for a, b in spans if float(b) > lower and float(a) < asof]
    profile = None
    if chart_basis == "BID":
        profile = {"time_s": event_s[retained],
                   "price": bid[retained], "weight": np.ones(int(np.sum(retained))),
                   "known_at_s": known_s[retained], "covered_spans": clipped_spans,
                   "basis": "MT5_BID_TICK_ACTIVITY"}
    elif chart_basis == "LAST" and real_possible and last is not None:
        trade_retained = retained & trade
        profile = {"time_s": event_s[trade_retained], "price": last[trade_retained], "weight": vol[trade_retained],
                   "known_at_s": known_s[trade_retained], "covered_spans": clipped_spans,
                   "basis": "MT5_LAST_EXECUTED_VOLUME"}
    return {"flow": fl, "exec": ex, "provenance": provenance, "profile": profile}

