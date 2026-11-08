"""Fabio/FTMO research analysis (read-only, finite): state -> location -> trigger -> price response -> refutation -> execution.

Two research families, both OUR operationalization of a source framework (not a validated strategy):
  F1  trend: balance -> accepted exit -> pullback to a LVN of the impulse profile -> price response.
  F2  failed breakout: balance -> breakout close -> reclaim inside value -> pullback (LVN of the reclaim leg) toward the balance POC.
Default CLI analysis uses only the snapshot's MT5 bars and pinned broker ticks (available_at <= as_of).
CVD/quotes/profile are derived automatically; external data is not needed. Optional offline diagnostic inputs:
  * flow file `fabio_flow_v1` (executed buy/sell totals per M5 bar from an external feed) -> CVD / bar-delta response proxy
  * exec file `fabio_exec_v1` (FTMO Bid/Ask + cost at known_at) -> entry/SL/net room
Missing flow/exec => explicit UNKNOWN/missing; price context is still returned. No win probability. Nothing is sent to a broker.
"""
from __future__ import annotations

import math
import numbers
from numbers import Real
from typing import Any

import numpy as np

from .features import atr
from .util import STORE_DIR, ceil_to_tick, floor_to_tick, hash_obj, iso_utc, parse_utc, stable_id, write_immutable_json

SPEC = {
    "spec_id": "FABIO_FTMO_V1", "version": "1.1.0",
    "source_rules": [
        "state (balance vs imbalance) before choosing a model; UNKNOWN allowed",
        "location: LVN of the impulse/reclaim profile, price must pull back to it",
        "trigger/aggression read at location together with price progress; absorption is a question, not a signal",
        "F2: failed breakout returns to balance, trade toward balance POC after a later pullback/test",
        "M5 bar-total delta is a response-window proxy; price-level aggression requires executed trades at price",
    ],
    "operationalization_note": "every number below is a project choice (not Fabio's); NQ 20/30-contract print thresholds are NOT used "
                               "(flow is judged by volume-normalised ratios, never by contract/lot counts)",
    "params": {
        "timeframe": "M5", "min_history_bars": 120, "balance_window_bars": 24, "balance_settled": "last acceptance_closes closes inside the window value area", "balance_max_range_atr": 3.5, "balance_lookback_bars": 150,
        "value_area_frac": 0.70, "profile_bin_atr_frac": 0.125, "acceptance_closes": 2, "fail_max_bars": 6,
        "pullback_min_atr": 0.5, "lvn_frac_of_median": 0.5, "lvn_min_eligible_bins": 4, "location_tol_atr": 0.25,
        "trigger_fresh_bars": 2, "flow_response_bars": 3, "sl_buffer_atr": 0.1, "min_net_room_R": 1.5,
        "cvd_slope_bars": 6, "flow_ratio_min": 0.10, "flow_progress_pos_atr": 0.15, "flow_progress_flat_atr": 0.05,
        "flow_max_lag_s": 600, "flow_min_coverage": 0.9, "flow_window_bars": 24, "pivot_n": 2, "pivot_lookback_bars": 60,
        "quote_max_age_s": 120, "quote_max_dev_atr": 1.0,
    },
    "mt5_data_policy": "automatic snapshot-pinned MT5 broker ticks; no external feed or manually exported indicator files",
    "cvd_rule": "validated broker trade side flags + volume if present; otherwise signed midpoint uptick/downtick count (+1/-1/0), labelled proxy; UTC-day reset and no gap carry",
    "profile_volume_basis": "covered MT5 ticks at chart-basis price when available; otherwise tick_volume uniformly spread over bar range, labelled approximation",
    "execution_cost_policy": "MT5 quote read automatically; missing commission/slippage remain UNKNOWN (no default zero)",
    "trigger_rule": "price response: closed bar in trade direction with close > previous bar high (long) / < previous bar low (short), at or after the LVN touch",
    "target_rule": {"F1": "previous completed D1 high (long) / low (short) if beyond price, else UNKNOWN", "F2": "balance POC, must be on the favourable side"},
    "economics_rule": "entry=Ask(long)/Bid(short); SL trigger on opposite side (short SL uses Ask = chart level + spread); net_room_R=(reward-commission-slippage)/risk",
}
SPEC_HASH = hash_obj(SPEC)
P = SPEC["params"]
SCALP_POLICY = "scalp_mt5_v1"
SCALP_SPEC = {**SPEC, "spec_id": "SCALP_FABIO_MT5_V1", "version": "1.0.0",
              "target_rule": {"F1": "most recent earlier completed balance POC ahead of price, else UNKNOWN",
                              "F2": "frozen breakout balance POC ahead of price"},
              "freeze_rule": "lock pre-breakout balance; lock impulse profile at first confirmed pullback; only later touches qualify",
              "scope": "MT5 price response adaptation; quote CVD advisory, no price-level aggression claim",
              "reference_max_age_bars": 150,
              "episode_max_bars": 150,
              "entry_window_s": 600,
              "max_hold_s": 1800,
              "replay_rule": "first causal quote after trigger+declared latency; frozen Bid-chart SL/target, short converted once at fill spread; commission RT, slippage per market leg; gaps unresolved across uncovered spans",
              "expiry_rule": "first price trigger only, deadline=trigger close+600s; episode ends after 150 M5 bars from first exit; rearm only on a settled balance entirely after the previous breakout",
              "economics_rule": "Ask+slip long / Bid-slip short; tick-rounded frozen SL/target; short levels use first quote spread; net_room=(reward-commission-slip)/risk, same as replay",
              "profile_revision_rule": "explicit previous-analysis chain freezes balance, impulse bins and target selection; without chain each pinned snapshot is a labelled reconstruction; changed OHLC prefix rejects continuation",
              "continuation_contract": "hash source/spec/symbol metadata/snapshot/asof, frozen balance, pending balance, families and observed price prefix; reject modified continuation state",
              "research_parameters_note": "reference age, episode TTL, entry window and max hold are unoptimised project choices, not source rules"}
SCALP_SPEC_HASH = hash_obj(SCALP_SPEC)
FLOW_SCHEMA, EXEC_SCHEMA = "fabio_flow_v1", "fabio_exec_v1"
SIDE_METHODS = ("AGGRESSOR_FLAG", "TICK_RULE", "BID_ASK_CLASSIFIED")
RANK = {"ENTER_CANDIDATE": 3, "WAIT": 2, "SKIP": 1, "DATA_UNAVAILABLE": 0}


def _f(x):
    return None if x is None or (isinstance(x, float) and not math.isfinite(x)) else float(x)


# ------------------------------------------------------------------ profile
def profile(lo, hi, vol, bin_size: float):
    """Tick-volume profile; returns (p0, volumes per bin). Bin i covers [p0+i*bin, p0+(i+1)*bin)."""
    p0 = math.floor(float(np.min(lo)) / bin_size) * bin_size
    n = max(1, int(math.floor((float(np.max(hi)) - p0) / bin_size)) + 1)
    v = np.zeros(n)
    for l, h, w in zip(lo, hi, vol):
        a = max(0, int((l - p0) // bin_size))
        b = min(n - 1, int((h - p0) // bin_size))
        v[a:b + 1] += float(w) / (b - a + 1)
    return p0, v



def window_profile(m5, start: int, end: int, bin_size: float, mt5_profile: dict | None = None, strict: bool = False):
    """Use covered tick prices on the chart's price basis; bar-range approximation is explicit."""
    fallback = "MT5_BAR_TICK_VOLUME_UNIFORM_PROXY"
    if mt5_profile:
        begin, finish = float(m5.open_at[start]), float(m5.close_at[end])
        covered = any(a <= begin and b >= finish for a, b in mt5_profile.get("covered_spans", []))
        if covered:
            times = mt5_profile["time_s"]
            i0, i1 = np.searchsorted(times, [begin, finish], side="left") if strict else (0, len(times))
            keep = ((times[i0:i1] >= begin) & (times[i0:i1] < finish))
            known = mt5_profile.get("known_at_s")
            if known is not None:
                keep &= known[i0:i1] <= float(m5.available_at[end])
        if covered and np.any(keep):
            prices, weights = mt5_profile["price"][i0:i1][keep], mt5_profile["weight"][i0:i1][keep]
            p0 = math.floor(float(np.min(prices)) / bin_size) * bin_size
            indexes = np.floor((prices - p0) / bin_size).astype(int)
            v = np.bincount(indexes, weights=weights)
            if len(v) and np.all(np.isfinite(v)) and float(v.sum()) > 0:
                return p0, v, mt5_profile["basis"]
    if strict:
        lo, hi, weights = m5.l[start:end + 1], m5.h[start:end + 1], m5.tick_volume[start:end + 1]
        if not (np.all(np.isfinite(lo)) and np.all(np.isfinite(hi)) and np.all(hi >= lo)
                and np.all(np.isfinite(weights)) and np.all(weights >= 0) and weights.sum() > 0):
            return 0., np.array([]), "PROFILE_UNAVAILABLE"
        p0 = math.floor(float(lo.min()) / bin_size) * bin_size
        v = np.zeros(int(math.floor((float(hi.max()) - p0) / bin_size)) + 1)
        for l, h, w in zip(lo, hi, weights):
            a = max(0, int(math.floor((l - p0) / bin_size)))
            b = min(len(v) - 1, int(math.floor((h - p0) / bin_size)))
            v[a:b + 1] += float(w) / (b - a + 1)
    else:
        p0, v = profile(m5.l[start:end + 1], m5.h[start:end + 1], m5.tick_volume[start:end + 1], bin_size)
    return p0, v, fallback

def value_area(p0, v, bin_size, frac):
    poc = int(np.argmax(v))
    lo = hi = poc
    tot, acc = float(v.sum()), float(v[poc])
    while acc < frac * tot and (lo > 0 or hi < len(v) - 1):
        up = v[hi + 1] if hi < len(v) - 1 else -1.0
        dn = v[lo - 1] if lo > 0 else -1.0
        if up >= dn:
            hi += 1; acc += v[hi]
        else:
            lo -= 1; acc += v[lo]
    return {"poc": p0 + (poc + 0.5) * bin_size, "vah": p0 + (hi + 1) * bin_size, "val": p0 + lo * bin_size}


def find_balance(m5, atrs, last: int, mt5_profile: dict | None = None, strict: bool = False):
    W = P["balance_window_bars"]
    for e in range(last - 1, max(W - 1, last - P["balance_lookback_bars"]) - 1, -1):
        s = e - W + 1
        a = atrs[e]
        if s < 0 or not math.isfinite(a) or a <= 0:
            continue
        if float(m5.h[s:e + 1].max() - m5.l[s:e + 1].min()) <= P["balance_max_range_atr"] * a:
            bs = max(1e-12, a * P["profile_bin_atr_frac"])
            p0, v, profile_basis = window_profile(m5, s, e, bs, mt5_profile, strict=strict)
            if strict and (not len(v) or v.sum() <= 0):
                continue
            va = value_area(p0, v, bs, P["value_area_frac"])
            if not all(va["val"] <= float(m5.c[e - j]) <= va["vah"] for j in range(P["acceptance_closes"])):
                continue                                  # not settled: the window already ends outside its own value area
            return {"start_index": s, "end_index": e, "atr_at_end": float(a), "range_high": float(m5.h[s:e + 1].max()),
                    "range_low": float(m5.l[s:e + 1].min()), **{k: float(x) for k, x in va.items()},
                    "known_at": iso_utc(m5.available_at[e]), "volume_basis": profile_basis}
    return None


def _scalp_balance(m5, atrs, last: int, mt5_profile: dict | None, prior: dict | None = None, search_state: dict | None = None):
    """Replay discovery causally; a new balance cannot contain the old breakout."""
    found = candidate = None
    begin = P["min_history_bars"]
    def restore(saved):
        value = dict(saved)
        value["start_index"] = int(np.searchsorted(m5.open_at, parse_utc(value["start_at"])))
        value["end_index"] = int(np.searchsorted(m5.close_at, parse_utc(value["end_at"])))
        if value.get("breakout_close_at"):
            value["breakout_index"] = int(np.searchsorted(m5.close_at, parse_utc(value["breakout_close_at"])))
        return value
    if prior:
        saved_candidate = (prior.get("balance_search_state") or {}).get("candidate")
        candidate = restore(saved_candidate) if saved_candidate else None
        begin = int(np.searchsorted(m5.close_at, parse_utc(prior["price_context"]["last_bar_close_at"]), side="right"))
    if prior and (prior.get("balance") or {}).get("breakout_at"):
        found = restore(prior["balance"])
    for b in range(begin, last + 1):
        e = b - 1
        if found is None or e - P["balance_window_bars"] + 1 > found["breakout_index"]:
            settled = _scalp_balance_at(m5, atrs, e, mt5_profile)
            if settled is not None:
                candidate = settled
        if candidate is None or b - candidate["end_index"] > P["balance_lookback_bars"]:
            continue
        before = float(m5.c[b - 1]); now = float(m5.c[b])
        if candidate["val"] <= before <= candidate["vah"] and (now > candidate["vah"] or now < candidate["val"]):
            found = {**candidate, "breakout_at": iso_utc(m5.available_at[b]), "breakout_index": b,
                     "breakout_close_at": iso_utc(m5.close_at[b]),
                     "episode_expires_at": iso_utc(m5.close_at[b] + SCALP_SPEC["episode_max_bars"] * 300)}
            candidate = None
    if search_state is not None:
        search_state["candidate"] = candidate
    return found or candidate


def _scalp_balance_at(m5, atrs, end: int, mt5_profile: dict | None):
    start = end - P["balance_window_bars"] + 1
    a = float(atrs[end])
    if start < 0 or not math.isfinite(a) or a <= 0:
        return None
    hi, lo = float(m5.h[start:end + 1].max()), float(m5.l[start:end + 1].min())
    if hi - lo > P["balance_max_range_atr"] * a:
        return None
    bs = max(1e-12, a * P["profile_bin_atr_frac"])
    p0, v, basis = window_profile(m5, start, end, bs, mt5_profile, strict=True)
    if not len(v) or v.sum() <= 0:
        return None
    va = value_area(p0, v, bs, P["value_area_frac"])
    if not all(va["val"] <= m5.c[end - j] <= va["vah"] for j in range(P["acceptance_closes"])):
        return None
    return {"start_index": start, "end_index": end, "atr_at_end": a, "range_high": hi, "range_low": lo,
            **va, "known_at": iso_utc(m5.available_at[end]), "volume_basis": basis,
            "start_at": iso_utc(m5.open_at[start]), "end_at": iso_utc(m5.close_at[end])}


def _scalp_prior_poc(m5, atrs, bal: dict, last_close: float, dirn: int, mt5_profile: dict | None):
    """A reference target must be complete before the current balance begins."""
    if bal.get("target_selection_complete"):
        ref = bal.get("target_reference")
        return (ref["poc"], "PRIOR_COMPLETED_BALANCE_POC") if ref else (None, "PRIOR_BALANCE_POC_NOT_AHEAD_OR_UNAVAILABLE")
    bal["target_selection_complete"] = True
    for end in range(int(bal["start_index"]) - 1, max(P["balance_window_bars"] - 2, int(bal["start_index"]) - SCALP_SPEC["reference_max_age_bars"] - 1), -1):
        old = _scalp_balance_at(m5, atrs, end, mt5_profile)
        if old is not None and old["end_index"] < bal["start_index"] and dirn * (old["poc"] - last_close) > 0:
            bal["target_reference"] = {k: old[k] for k in ("poc", "start_at", "end_at", "known_at", "volume_basis")}
            return float(old["poc"]), "PRIOR_COMPLETED_BALANCE_POC"
    return None, "PRIOR_BALANCE_POC_NOT_AHEAD_OR_UNAVAILABLE"


def _scalp_impulse_freeze(m5, leg_start: int, last: int, dirn: int, atr_at_balance: float, not_before: int | None = None):
    H = m5.h if dirn > 0 else -m5.l
    L = m5.l if dirn > 0 else -m5.h
    for k in range(max(leg_start + 1, not_before or 0), last + 1):
        extreme = leg_start + int(np.argmax(H[leg_start:k + 1]))
        if extreme < k and float(H[extreme] - L[extreme + 1:k + 1].min()) >= P["pullback_min_atr"] * atr_at_balance:
            return extreme, k
    return None, None


# ------------------------------------------------------------------ flow input
def _flow_number(value: Any) -> float | None:
    """Return finite real numbers only; bool, strings and NaN are not flow data."""
    if isinstance(value, (bool, np.bool_)) or not isinstance(value, numbers.Real):
        return None
    try:
        value = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return value if math.isfinite(value) else None


def _flow_timestamp(value: Any) -> float | None:
    if not isinstance(value, str):
        return None
    try:
        value = parse_utc(value)
    except (TypeError, ValueError, OverflowError, OSError):
        return None
    return value if math.isfinite(value) else None


def _flow_text(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def load_flow(flow: dict | None, m5, symbol: str, as_of: float) -> dict:
    """Validate and align a ``fabio_flow_v1`` file without filling missing bars.

    The file clock is explicit: record ``open_at``/``close_at``/``known_at`` and
    ``reset_at`` are source timestamps and ``mapping.clock_offset_s`` converts
    them to the M5 UTC clock.
    A reset is an aligned M5 open in that converted clock; records before it are
    excluded and CVD restarts there. Duplicate records and malformed records
    reject the complete file, so a partial file can never become silently usable.
    """
    n = len(m5)
    if flow is None:
        return {"status": "NOT_PROVIDED", "reasons": [], "use_in_decision": False}
    if not isinstance(flow, dict):
        return {"status": "REJECTED", "reasons": ["SCHEMA_INVALID"], "use_in_decision": False}
    out = {"status": None, "reasons": [], "use_in_decision": False,
           "declared_route": flow.get("route"), "source": flow.get("source"),
           "provenance": flow.get("provenance"), "instrument": flow.get("instrument"),
           "contract": flow.get("contract"), "volume_basis": flow.get("volume_basis"),
           "side_method": flow.get("side_method")}
    def reject(reason: str) -> dict:
        out.update(status="REJECTED", reasons=[reason], use_in_decision=False)
        return out
    if flow.get("schema") != FLOW_SCHEMA or not isinstance(flow.get("bars"), list):
        return reject("SCHEMA_INVALID")
    if not all(_flow_text(flow.get(k)) for k in ("source", "provenance", "instrument", "contract")):
        return reject("IDENTITY_REQUIRED")
    basis, route = flow.get("volume_basis"), flow.get("route")
    if basis != "EXECUTED_TRADES":
        out["reasons"].append(f"{basis}_IS_NOT_EXECUTED_VOLUME")
        if route != "FTMO_PRICE_PROXY":
            out["reasons"].append("ROUTE_MISCLASSIFIED_PROXY_AS_FLOW")
        out["status"] = "PROXY_NOT_FLOW"; return out
    if flow.get("side_method") not in SIDE_METHODS:
        return reject("NO_SIDE_METHOD")
    if flow.get("sign_convention") != "POSITIVE_IS_BUY_AGGRESSION":
        return reject("SIGN_CONVENTION_UNVERIFIED")
    if route == "FUTURES_REFERENCE":
        out.update(status="REFERENCE_ONLY", reasons=["FUTURES_REFERENCE_NOT_MAPPED_TO_FTMO_PRICE"]); return out
    if route != "FTMO_EXTERNAL_FLOW":
        return reject("ROUTE_BASIS_CONTRADICTION")
    mp = flow.get("mapping")
    if not isinstance(mp, dict) or mp.get("ftmo_symbol") != symbol or mp.get("clock_verified") is not True:
        out.update(status="MAPPING_UNVERIFIED", reasons=["MAPPING_OR_CLOCK_NOT_VERIFIED"]); return out
    if not _flow_text(mp.get("reference_symbol")) or mp.get("reference_symbol") not in (flow.get("instrument"), flow.get("contract")):
        return reject("REFERENCE_SYMBOL_INCONSISTENT")
    off = _flow_number(mp.get("clock_offset_s"))
    if off is None:
        return reject("CLOCK_OFFSET_INVALID")
    as_of_n = _flow_number(as_of)
    if as_of_n is None:
        return reject("AS_OF_INVALID")
    reset_src = None
    if flow.get("reset_at") is not None:
        reset_src = _flow_timestamp(flow.get("reset_at"))
        if reset_src is None:
            return reject("RESET_TIMESTAMP_INVALID")
    reset_at = None if reset_src is None else reset_src + off
    if reset_at is not None and not math.isfinite(reset_at):
        return reject("RESET_TIMESTAMP_INVALID")
    idx = {int(t): i for i, t in enumerate(m5.open_at)}
    if reset_at is not None:
        ri = idx.get(int(reset_at))
        if ri is None or abs(float(m5.open_at[ri]) - reset_at) > 1e-6:
            return reject("RESET_NOT_M5_ALIGNED")
    buy = np.full(n, np.nan); sell = np.full(n, np.nan)
    future = kept = 0; seen = set()
    for rec_no, r in enumerate(flow["bars"]):
        if not isinstance(r, dict):
            return reject(f"RECORD_INVALID:{rec_no}:NOT_OBJECT")
        vals = {k: _flow_timestamp(r.get(k)) for k in ("open_at", "close_at", "known_at")}
        if any(v is None for v in vals.values()):
            return reject(f"RECORD_INVALID:{rec_no}:TIMESTAMP")
        bv, sv = _flow_number(r.get("buy_vol")), _flow_number(r.get("sell_vol"))
        if bv is None or sv is None or bv < 0 or sv < 0:
            return reject(f"RECORD_INVALID:{rec_no}:VOLUME")
        op, co, ka = vals["open_at"] + off, vals["close_at"] + off, vals["known_at"] + off
        if not (math.isfinite(op) and math.isfinite(co) and math.isfinite(ka)):
            return reject(f"RECORD_INVALID:{rec_no}:CLOCK_CONVERSION_NONFINITE")
        if abs((co - op) - 300.0) > 1e-6:
            return reject(f"RECORD_INVALID:{rec_no}:M5_DURATION")
        if ka + 1e-6 < co:
            return reject(f"RECORD_INVALID:{rec_no}:KNOWN_BEFORE_CLOSE")
        if n:
            grid_units = (op - float(m5.open_at[0])) / 300.0
            if abs(grid_units - round(grid_units)) > 1e-6:
                return reject(f"RECORD_INVALID:{rec_no}:M5_GRID")
        key = int(round(op))
        if key in seen:
            return reject(f"DUPLICATE_RECORD:{rec_no}")
        seen.add(key)
        i = idx.get(key)
        if i is None or abs(float(m5.open_at[i]) - op) > 1e-6:
            continue
        if abs(float(m5.close_at[i]) - co) > 1e-6:
            return reject(f"RECORD_INVALID:{rec_no}:CLOSE_MISMATCH")
        if ka > as_of_n or co > as_of_n:
            future += 1; continue
        if reset_at is not None and float(m5.open_at[i]) < reset_at:
            continue
        buy[i], sell[i] = bv, sv; kept += 1
    if future:
        out["reasons"].append(f"FUTURE_KNOWN_INPUT_EXCLUDED:{future}")
    have = np.flatnonzero(np.isfinite(buy))
    if not len(have):
        out.update(status="NO_USABLE_BARS"); return out
    lag = float(m5.close_at[-1] - m5.close_at[have[-1]])
    with np.errstate(over="ignore", invalid="ignore"):
        delta, tot = buy - sell, buy + sell
    if not (np.isfinite(delta[have]).all() and np.isfinite(tot[have]).all()):
        return reject("DERIVED_VOLUME_NONFINITE")
    win = slice(max(0, n - P["flow_window_bars"]), n)
    cov = float(np.isfinite(delta[win]).mean())
    cvd = np.full(n, np.nan)
    gaps = np.flatnonzero(~np.isfinite(delta))
    start = int(gaps[-1]) + 1 if len(gaps) else 0
    if reset_at is not None:
        start = max(start, int(np.searchsorted(m5.open_at, reset_at)))
    if start < n:
        with np.errstate(over="ignore", invalid="ignore"):
            cvd_segment = np.cumsum(delta[start:])
            total_segment = np.cumsum(tot[start:])
        if not (np.isfinite(cvd_segment).all() and np.isfinite(total_segment).all()):
            return reject("DERIVED_VOLUME_NONFINITE")
        cvd[start:] = cvd_segment
    out.update(delta=delta, total=tot, cvd=cvd, cvd_start_index=start, coverage_window=cov, lag_s=lag, bars_used=kept,
               reset_at=iso_utc(reset_at) if reset_at else None, last_flow_close_at=iso_utc(m5.close_at[have[-1]]))
    if lag > P["flow_max_lag_s"]:
        out.update(status="STALE", reasons=out["reasons"] + [f"FLOW_LAG_{int(lag)}s"]); return out
    if cov < P["flow_min_coverage"]:
        out.update(status="COVERAGE_LOW", reasons=out["reasons"] + [f"COVERAGE_{cov:.2f}"]); return out
    out.update(status="USABLE", use_in_decision=True)
    return out


def public_flow(fl: dict) -> dict:
    out = {k: v for k, v in fl.items() if k not in ("delta", "total", "cvd")}
    if "cvd" in fl:
        cv = fl["cvd"]
        out["current_cvd"] = _f(cv[-1]) if len(cv) else None
        out["latest_bar_delta"] = _f(fl["delta"][-1]) if len(cv) else None
        start = int(fl.get("cvd_start_index", len(cv)))
        out["segment_start_index"] = start
        k = len(cv) - P["cvd_slope_bars"]
        out["recent_cvd_change"] = float(cv[-1] - cv[k]) if k >= start and np.isfinite(cv[k]) and np.isfinite(cv[-1]) else None
    return out


def divergences(m5, fl: dict, last: int) -> dict:
    """Latest pair of confirmed fractal pivots (n bars each side); CVD compared at the SAME bars. Context only, never a trigger."""
    if not fl.get("use_in_decision"):
        return {"status": "UNAVAILABLE", "reason": "FLOW_" + str(fl.get("status"))}
    n, cvd = P["pivot_n"], fl["cvd"]
    lo = max(fl["cvd_start_index"], last - P["pivot_lookback_bars"])
    res = {"status": "OK", "pivots_confirmed_only": True}
    for kind, arr, cmp_ in (("high", m5.h, np.greater), ("low", m5.l, np.less)):
        piv = [k for k in range(lo + n, last - n + 1)
               if all(cmp_(arr[k], arr[k - j]) and cmp_(arr[k], arr[k + j]) for j in range(1, n + 1))]
        if len(piv) < 2:
            res[kind] = {"status": "UNAVAILABLE", "reason": "FEWER_THAN_2_PIVOTS_AFTER_RESET_OR_GAP"}; continue
        a, b = piv[-2], piv[-1]
        if not (np.isfinite(cvd[a]) and np.isfinite(cvd[b])):
            res[kind] = {"status": "UNAVAILABLE", "reason": "CVD_UNDEFINED_AT_PIVOT"}; continue
        pu, cu = arr[b] > arr[a], cvd[b] > cvd[a]
        if kind == "high":
            name = "regular_bearish" if (pu and not cu) else "hidden_bearish" if (not pu and cu) else "none"
        else:
            name = "regular_bullish" if (not pu and cu) else "hidden_bullish" if (pu and not cu) else "none"
        res[kind] = {"class": name, "pivot_indexes": [a, b], "price": [float(arr[a]), float(arr[b])], "cvd": [float(cvd[a]), float(cvd[b])],
                     "pivot_known_at": iso_utc(m5.available_at[b + n]), "basis": "same reset/gap-free CVD segment"}
    return res


# ------------------------------------------------------------------ execution economics
def _economics_real(value: Any, *, nonnegative: bool = False, positive: bool = False) -> float | None:
    """Return a finite real number, excluding booleans, for economics validation."""
    if isinstance(value, bool) or not isinstance(value, Real):
        return None
    try:
        out = float(value)
    except (TypeError, ValueError, OverflowError, OSError):
        return None
    if not math.isfinite(out) or (nonnegative and out < 0.0) or (positive and out <= 0.0):
        return None
    return out


def economics(exec_in: dict | None, symbol: str, as_of: float, dirn: int, atr_now: float, last_close: float,
              inval: float | None, buf: float, target: float | None) -> dict:
    if exec_in is None:
        return {"status": "UNKNOWN", "reason": "EXEC_QUOTE_AND_COST_NOT_PROVIDED"}
    if not isinstance(exec_in, dict) or exec_in.get("schema") != EXEC_SCHEMA or exec_in.get("symbol") != symbol:
        return {"status": "UNKNOWN", "reason": "EXEC_SCHEMA_OR_SYMBOL_MISMATCH"}
    as_of_n = _economics_real(as_of)
    atr_n = _economics_real(atr_now, positive=True)
    close_n = _economics_real(last_close, positive=True)
    if as_of_n is None or atr_n is None or close_n is None:
        return {"status": "UNKNOWN", "reason": "INTERNAL_PRICE_OR_TIME_INPUT_INVALID"}
    if dirn not in (-1, 1) or isinstance(dirn, bool):
        return {"status": "UNKNOWN", "reason": "DIRECTION_INVALID"}
    if inval is None or target is None:
        return {"status": "UNKNOWN", "reason": "INVALIDATION_OR_TARGET_UNKNOWN"}
    inval_n = _economics_real(inval, positive=True)
    target_n = _economics_real(target, positive=True)
    buf_n = _economics_real(buf, nonnegative=True)
    if inval_n is None or target_n is None or buf_n is None:
        return {"status": "UNKNOWN", "reason": "INTERNAL_PRICE_OR_BUFFER_INPUT_INVALID"}
    known_raw = exec_in.get("known_at")
    if not isinstance(known_raw, str):
        return {"status": "UNKNOWN", "reason": "EXEC_QUOTE_TIME_INVALID"}
    try:
        ka = parse_utc(known_raw)
    except (TypeError, ValueError, OverflowError):
        return {"status": "UNKNOWN", "reason": "EXEC_QUOTE_TIME_INVALID"}
    if ka > as_of_n:
        return {"status": "UNKNOWN", "reason": "EXEC_QUOTE_KNOWN_AFTER_AS_OF"}
    event_raw = exec_in.get("event_at", known_raw)
    try:
        event_at = parse_utc(event_raw) if isinstance(event_raw, str) else None
    except (TypeError, ValueError, OverflowError):
        event_at = None
    if event_at is None or event_at > ka:
        return {"status": "UNKNOWN", "reason": "EXEC_QUOTE_TIME_INVALID"}
    age = as_of_n - event_at
    if age > P["quote_max_age_s"]:
        return {"status": "UNKNOWN", "reason": f"EXEC_QUOTE_STALE_{int(age)}s"}
    bid = _economics_real(exec_in.get("bid"), positive=True)
    ask = _economics_real(exec_in.get("ask"), positive=True)
    if bid is None or ask is None or not ask >= bid or any(abs(x - close_n) > P["quote_max_dev_atr"] * atr_n for x in (bid, ask)):
        return {"status": "UNKNOWN", "reason": "EXEC_QUOTE_INVALID_OR_FAR_FROM_BAR_PRICE"}
    spread = ask - bid
    commission = _economics_real(exec_in.get("commission_round_turn_price"), nonnegative=True)
    slippage = _economics_real(exec_in.get("slippage_price"), nonnegative=True)
    if commission is None or slippage is None:
        return {"status": "UNKNOWN", "reason": "EXEC_COST_INVALID_OR_MISSING"}
    cost = commission + slippage
    sl_chart = inval_n - dirn * buf_n                         # chart (Bid) level
    if dirn > 0:
        entry, risk, reward = ask, ask - sl_chart, target_n - ask
    else:
        entry, risk, reward = bid, (sl_chart + spread) - bid, bid - (target_n + spread)
    sl_trigger = sl_chart + (spread if dirn < 0 else 0.0)
    if not all(math.isfinite(x) for x in (cost, spread, sl_chart, risk, reward, sl_trigger)) or sl_trigger <= 0.0:
        return {"status": "UNKNOWN", "reason": "ECONOMICS_NON_FINITE_OR_INVALID"}
    if risk <= 0:
        return {"status": "UNKNOWN", "reason": "RISK_NON_POSITIVE"}
    net = (reward - cost) / risk
    if not math.isfinite(net):
        return {"status": "UNKNOWN", "reason": "ECONOMICS_NON_FINITE_OR_INVALID"}
    return {"status": "KNOWN", "entry": entry, "sl_trigger": sl_trigger, "tp_chart_level": target_n,
            "risk_price": risk, "reward_price": reward, "spread_price": spread, "cost_price": cost, "net_room_R": net,
            "quote_known_at": exec_in["known_at"], "quote_source": exec_in.get("source"),
            "meets_min_room": net >= P["min_net_room_R"], "min_net_room_R": P["min_net_room_R"]}


def classify_flow(ratio: float, prog: float) -> str:
    """ratio = signed (trade direction) delta / executed volume over the response window; prog = price progress in ATR over the same window."""
    if ratio >= P["flow_ratio_min"]:
        return "AGGRESSION_CONFIRMS" if prog >= P["flow_progress_pos_atr"] else "POSSIBLE_ABSORPTION_AGAINST" if prog < P["flow_progress_flat_atr"] else "NEUTRAL"
    if ratio <= -P["flow_ratio_min"]:
        return "OPPOSING_AGGRESSION_ABSORBED" if prog >= P["flow_progress_pos_atr"] else "OPPOSING_CONFIRMED" if prog < P["flow_progress_flat_atr"] else "NEUTRAL"
    return "NEUTRAL"


# ------------------------------------------------------------------ one family in "long space"
def _family(name, m5, atrs, last, dirn, bal, state_known_at, start_edge_p, leg_start, target, target_src, extra_refute, fl, exec_in, symbol, as_of,
            reclaim_index: int | None = None, mt5_profile: dict | None = None, scalp_policy: bool = False,
            invalidation_event: tuple[int, str] | None = None, tick_size: float | None = None,
            prior_family: dict | None = None):
    """dirn=+1 long / -1 short. Transformed arrays make every branch a 'long': H'=dir*h (or -l), L'.. C'=dir*c."""
    H = m5.h if dirn > 0 else -m5.l
    L = m5.l if dirn > 0 else -m5.h
    C, O = dirn * m5.c, dirn * m5.o
    A0 = bal["atr_at_end"]; a_now = float(atrs[last])
    R: dict[str, Any] = {"family": name, "side": "LONG" if dirn > 0 else "SHORT", "gates": {}, "supporting_evidence": [],
                         "contradicting_evidence": [], "missing": [], "state_known_at": state_known_at}
    g = R["gates"]
    freeze_at = None
    frozen = (prior_family or {}).get("frozen_profile")
    if scalp_policy:
        if frozen:
            ys = int(np.searchsorted(m5.close_at, parse_utc(frozen["anchor_end_at"])))
            freeze_at = int(np.searchsorted(m5.close_at, parse_utc(frozen["freeze_bar_close_at"])))
        else:
            ys, freeze_at = _scalp_impulse_freeze(m5, leg_start, last, dirn, A0,
                                              reclaim_index + 1 if reclaim_index is not None else
                                              int(np.searchsorted(m5.available_at, parse_utc(state_known_at))))
        if ys is None:
            R.update(decision="SKIP" if invalidation_event else "WAIT",
                     reason=invalidation_event[1] if invalidation_event else "PULLBACK_NOT_DEVELOPED"); return R
        extension = next((k for k in range(freeze_at + 1, last + 1) if H[k] > H[ys]), None)
        if extension is not None and (invalidation_event is None or extension < invalidation_event[0]):
            invalidation_event = (extension, "IMPULSE_EXTENDED_AFTER_PROFILE_FREEZE")
        if invalidation_event:
            R["invalidated_at"] = iso_utc(m5.available_at[invalidation_event[0]])
    else:
        ys = int(np.argmax(H[leg_start:last + 1])) + leg_start                  # impulse extreme so far (known by as_of)
    pull = float(H[ys] - L[ys + 1:last + 1].min()) / A0 if ys < last else 0.0
    g["pullback"] = {"impulse_extreme_index": ys, "impulse_extreme": float(dirn * H[ys]), "retrace_atr": pull, "min_atr": P["pullback_min_atr"]}
    if freeze_at is not None:
        g["pullback"].update(profile_frozen_at=iso_utc(m5.available_at[freeze_at]), profile_frozen_index=freeze_at,
                             anchor_start_at=iso_utc(m5.open_at[leg_start]), anchor_end_at=iso_utc(m5.close_at[ys]))
    if ys >= last or pull < P["pullback_min_atr"]:
        R.update(decision="WAIT", reason="PULLBACK_NOT_DEVELOPED"); return R
    bs = max(1e-12, A0 * P["profile_bin_atr_frac"])
    if frozen:
        p0, v, profile_basis = frozen["p0"], np.array(frozen["volumes"]), frozen["basis"]
        bs = frozen["bin"]
    else:
        p0, v, profile_basis = window_profile(m5, leg_start, ys, bs, mt5_profile, strict=scalp_policy)
    if scalp_policy:
        R["frozen_profile"] = frozen or {"p0": p0, "volumes": v.tolist(), "bin": bs, "basis": profile_basis,
            "anchor_start_at": iso_utc(m5.open_at[leg_start]), "anchor_end_at": iso_utc(m5.close_at[ys]),
            "freeze_bar_close_at": iso_utc(m5.close_at[freeze_at]), "known_at": iso_utc(m5.available_at[freeze_at])}
        R["profile_signature"] = hash_obj({"start_at": iso_utc(m5.open_at[leg_start]), "end_at": iso_utc(m5.close_at[ys]),
                                           "p0": p0, "volumes": v.tolist(), "bin": bs, "basis": profile_basis})
        R["profile_basis"] = profile_basis
    if scalp_policy and (not len(v) or v.sum() <= 0):
        R.update(decision="WAIT", reason="PROFILE_UNAVAILABLE"); return R
    centers = dirn * (p0 + (np.arange(len(v)) + 0.5) * bs)                   # transformed centers
    elig = np.flatnonzero((centers > start_edge_p + bs) & (centers < H[ys] - bs))
    if len(elig) < P["lvn_min_eligible_bins"] or not np.any(v[elig] > 0):
        R.update(decision="WAIT", reason="LVN_NOT_DEFINED"); R["gates"]["location"] = {"status": "UNKNOWN", "reason": "TOO_FEW_PROFILE_BINS"}; return R
    thr = P["lvn_frac_of_median"] * float(np.median(v[elig][v[elig] > 0]))
    lvn = [int(i) for i in elig if v[i] <= thr]
    if not lvn:
        R.update(decision="WAIT", reason="LVN_NOT_DEFINED"); R["gates"]["location"] = {"status": "UNKNOWN", "reason": "NO_BIN_BELOW_THRESHOLD"}; return R
    tol = P["location_tol_atr"] * A0
    # location/trigger: a trigger bar r must touch an LVN band itself or directly follow a touching bar; the touch RUN adjacent to r
    # defines t (so a later or much earlier touch cannot move it). Only the last `trigger_fresh_bars` bars can trigger.
    event_start = max(ys + 1, (reclaim_index + 1) if reclaim_index is not None else ys + 1,
                      freeze_at + 1 if freeze_at is not None else ys + 1)
    reclaim_known_at = m5.available_at[reclaim_index] if reclaim_index is not None else None
    touch = {k: any(L[k] <= centers[i] + tol and H[k] >= centers[i] - tol for i in lvn)
             and (reclaim_known_at is None or m5.available_at[k] > reclaim_known_at)
             and (freeze_at is None or m5.available_at[k] > m5.available_at[freeze_at])
             for k in range(event_start, last + 1)}
    nearest = min(lvn, key=lambda i: abs(C[last] - centers[i]))
    qual = [k for k in range(last, event_start - 1, -1)
            if C[k] > O[k] and C[k] > H[k - 1] and (touch[k] or touch.get(k - 1, False))
            and (not scalp_policy or invalidation_event is None or k < invalidation_event[0])
            and (freeze_at is None or m5.available_at[k] > m5.available_at[freeze_at])
            and (reclaim_known_at is None or m5.available_at[k] > reclaim_known_at)]
    if not qual:
        recent = any(touch[k] for k in range(max(event_start, last - 2), last + 1))
        g["location"] = {"status": "TOUCHED_RECENTLY" if recent else "NOT_REACHED", "nearest_lvn_price": float(dirn * centers[nearest]), "profile_bin": bs,
                         "distance_atr": float(abs(C[last] - centers[nearest]) / a_now)}
        if scalp_policy:
            g["location"].update(volume_basis=profile_basis, profile_leg=[int(leg_start), int(ys)])
        g["trigger"] = {"status": "PENDING"}
        R.update(decision="WAIT", reason="TRIGGER_PENDING" if recent else "LOCATION_NOT_REACHED")
        if scalp_policy and invalidation_event:
            R.update(decision="SKIP", reason=invalidation_event[1])
        return R
    r = qual[-1] if scalp_policy else qual[0]
    if not scalp_policy and r < last - (P["trigger_fresh_bars"] - 1):
        g["trigger"] = {"status": "STALE", "trigger_index": int(r)}
        R.update(decision="SKIP", reason="TRIGGER_EXPIRED"); return R
    t = r if touch[r] else r - 1
    while t - 1 >= event_start and touch.get(t - 1, False):
        t -= 1
    li = min(lvn, key=lambda i: abs(C[t] - centers[i]))
    g["location"] = {"status": "TOUCHED", "lvn_price": float(dirn * centers[li]), "touch_run_start_index": int(t), "touch_known_at": iso_utc(m5.available_at[t]),
                     "tolerance": tol, "profile_bin": bs, "lvn_volume_over_median": float(v[li] / max(1e-12, thr / P["lvn_frac_of_median"])),
                     "profile_leg": [int(leg_start), int(ys)], "volume_basis": profile_basis}
    w0 = max(t, r - P["flow_response_bars"] + 1, 1)                  # local response window (<= flow_response_bars bars ending at r)
    inv0 = float(L[t:r + 1].min())
    neg = [k for k in range(r + 1, last + 1) if C[k] < inv0]
    g["trigger"] = {"status": "OBSERVED", "trigger_index": int(r), "trigger_known_at": iso_utc(m5.available_at[r]),
                    "expires_at": iso_utc(m5.close_at[r] + P["trigger_fresh_bars"] * 300), "price_response_atr":
                    float((C[r] - C[w0 - 1]) / A0)}
    R["supporting_evidence"].append({"id": "PRICE_RESPONSE_AT_LVN", "source": "M5 bars", "known_at": g["trigger"]["trigger_known_at"]})
    refs = [x for x in (neg and ["TRIGGER_NEGATED_BY_CLOSE_BELOW_STRUCTURE"]) + extra_refute(t, r) if x]
    if scalp_policy and invalidation_event and invalidation_event[1] not in refs:
        refs.append(invalidation_event[1])
    if scalp_policy and neg:
        R["invalidated_at"] = min(R.get("invalidated_at", iso_utc(m5.available_at[neg[0]])), iso_utc(m5.available_at[neg[0]]))
    g["refutation"] = {"price": refs}
    inval = float(dirn * inv0)
    R["invalidation"] = {"level": inval, "rule": "close beyond the touch->trigger structure extreme", "sl_buffer": P["sl_buffer_atr"] * A0}
    R["expires_at"] = g["trigger"]["expires_at"]
    # flow read at the response window
    flow_read = {"status": "MISSING_FLOW", "reason": "FLOW_" + str(fl.get("status"))}
    cvd_ok = agg_ok = None
    is_proxy = fl.get("is_proxy", False)
    if fl.get("use_in_decision"):
        w = slice(w0, r + 1)
        d, tt = fl["delta"][w], fl["total"][w]
        if np.all(np.isfinite(d)) and float(tt.sum()) > 0:
            ratio = dirn * float(d.sum()) / float(tt.sum())
            prog = float((C[r] - C[w0 - 1]) / A0)
            cls = classify_flow(ratio, prog)
            agg_ok = {"AGGRESSION_CONFIRMS": True, "OPPOSING_AGGRESSION_ABSORBED": True, "POSSIBLE_ABSORPTION_AGAINST": False,
                      "OPPOSING_CONFIRMED": False}.get(cls)
            if is_proxy:
                cls = {"AGGRESSION_CONFIRMS": "TICK_ACTIVITY_ALIGNED_WITH_PRICE",
                       "OPPOSING_AGGRESSION_ABSORBED": "PRICE_PROGRESS_AGAINST_TICK_ACTIVITY",
                       "POSSIBLE_ABSORPTION_AGAINST": "TICK_ACTIVITY_WITHOUT_PRICE_PROGRESS",
                       "OPPOSING_CONFIRMED": "OPPOSING_TICK_ACTIVITY"}.get(cls, cls)
            flow_read = {"status": "OK", "class": cls, "signed_delta_ratio": ratio, "price_progress_atr": prog, "window_indexes": [int(w.start), int(r)],
                         "basis": "M5_BAR_TOTALS_RESPONSE_WINDOW",
                         "note": "bar-total delta is an inference from flow vs price progress, not price-level aggression or an observed passive order"}
            k0 = r - P["cvd_slope_bars"] + 1
            cv = fl["cvd"]
            dv = divergences(m5, fl, last)
            against = {"high": "regular_bearish", "low": "regular_bullish"}
            div_against = any((dv.get(k) or {}).get("class") == against[k] for k in ("high", "low") if dirn > 0 and k == "high" or dirn < 0 and k == "low")
            if k0 >= 0 and np.isfinite(cv[k0]) and np.isfinite(cv[r]):
                cvd_ok = bool(dirn * (cv[r] - cv[k0]) > 0 and not div_against)
                flow_read["cvd_slope_aligned"] = bool(dirn * (cv[r] - cv[k0]) > 0)
                flow_read["divergence_against"] = div_against
            else:
                flow_read["cvd_slope_aligned"] = None; flow_read["cvd_reason"] = "CVD_UNDEFINED_IN_WINDOW"
            flow_read["divergence"] = dv
            (R["supporting_evidence"] if agg_ok else R["contradicting_evidence"] if agg_ok is False else []).append(
                {"id": ("TICK_PROXY_" if is_proxy else "FLOW_") + cls, "source": fl.get("source", "external executed flow"), "known_at": iso_utc(m5.available_at[r]), "is_proxy": is_proxy})
        else:
            flow_read = {"status": "MISSING_FLOW", "reason": "NO_FLOW_IN_RESPONSE_WINDOW"}
    if is_proxy:
        flow_read["note"] = "MT5 quote-direction proxy; correlated with price, cannot establish executed aggression or absorption"
    flow_read["volume_basis"] = fl.get("volume_basis")
    flow_read["is_proxy"] = is_proxy
    g["flow"] = flow_read
    # target / room / economics
    inval_buf = P["sl_buffer_atr"] * A0
    if target is None:
        g["target_room"] = {"status": "UNKNOWN", "reason": target_src}
        R["missing"].append("TARGET_UNKNOWN")
    else:
        g["target_room"] = {"status": "KNOWN", "target": float(target), "source": target_src, "room_atr": float(abs(target - m5.c[last]) / a_now)}
        if scalp_policy:
            ref = bal.get("target_reference", {}) if name == "F1" else bal
            g["target_room"].update(volume_basis=ref.get("volume_basis"), reference_known_at=ref.get("known_at"),
                                    reference_start_at=ref.get("start_at"), reference_end_at=ref.get("end_at"))
    ec = economics(exec_in, symbol, as_of, dirn, a_now, float(m5.c[last]), inval, inval_buf, target)
    if scalp_policy and ec["status"] == "KNOWN":
        q = _economics_real(tick_size, positive=True)
        if q is None:
            ec = {"status": "UNKNOWN", "reason": "TICK_SIZE_UNKNOWN"}
        else:
            slip = float(exec_in["slippage_price"])
            commission = float(exec_in["commission_round_turn_price"])
            spread = float(exec_in["ask"] - exec_in["bid"])
            entry = float(exec_in["ask"] + slip if dirn > 0 else exec_in["bid"] - slip)
            sl = floor_to_tick(inval - inval_buf, q) if dirn > 0 else ceil_to_tick(inval + inval_buf + spread, q)
            tp = ceil_to_tick(target, q) if dirn > 0 else floor_to_tick(target + spread, q)
            risk, reward = dirn * (entry - sl), dirn * (tp - entry)
            net = (reward - commission - slip) / risk if risk > 0 else -math.inf
            if not all(math.isfinite(x) and x > 0 for x in (entry, sl, tp, risk)):
                ec = {"status": "UNKNOWN", "reason": "RISK_OR_GRID_INVALID"}
            else:
                ec.update(entry=entry, sl_trigger=sl, tp_trigger=tp, risk_price=risk, reward_price=reward,
                          net_room_R=net, meets_min_room=net >= P["min_net_room_R"],
                          cost_status="ASSUMED", slippage_per_market_leg=slip,
                          note="declared scenario; entry and room use the same price-unit cost convention as Fabio replay")
    g["economics"] = ec
    if ec["status"] != "KNOWN":
        R["missing"].append("ECONOMICS_UNKNOWN:" + ec["reason"])
    if refs:
        R["contradicting_evidence"] += [{"id": x, "source": "M5 bars"} for x in refs]
        R.update(decision="SKIP", reason=refs[0]); R["variants"] = {}; return R
    # variants over the SAME opportunity (identical price gates; they differ only by the flow gate)
    def econ_gate():
        if target is None:
            return {"decision": "WAIT", "reason": "TARGET_UNKNOWN"}
        if ec["status"] != "KNOWN":
            return {"decision": "WAIT", "reason": "ECONOMICS_UNKNOWN"}
        if not ec["meets_min_room"]:
            return {"decision": "WAIT", "reason": "NET_ROOM_BELOW_MIN"}
        return None

    def variant(flow_state):
        if flow_state.startswith("MISSING"):
            return {"decision": "DATA_UNAVAILABLE", "reason": flow_state}
        if flow_state == "FAIL":
            return {"decision": "SKIP", "reason": "FLOW_CONTRADICTS_AT_LOCATION"}
        if flow_state == "NEUTRAL":
            return {"decision": "WAIT", "reason": "FLOW_NEUTRAL"}
        return econ_gate() or {"decision": "ENTER_CANDIDATE", "reason": "ALL_GATES_PASS (research candidate, not a broker order)"}

    miss = None if fl.get("use_in_decision") else "MISSING_FLOW:" + str(fl.get("status"))
    cvd_state = miss or ("MISSING_CVD_UNDEFINED_IN_WINDOW" if cvd_ok is None else "PASS" if cvd_ok else "FAIL")
    agg_state = miss or ("MISSING_NO_FLOW_IN_RESPONSE_WINDOW" if flow_read.get("status") != "OK" else "NEUTRAL" if agg_ok is None else "PASS" if agg_ok else "FAIL")
    price_level_local = {"decision": "DATA_UNAVAILABLE", "reason": "PRICE_LEVEL_EXECUTED_DATA_NOT_PROVIDED",
                         "basis": "PRICE_LEVEL_EXECUTED_TRADES_REQUIRED"}
    bar_delta = variant(agg_state)
    bar_delta["basis"] = "M5_BAR_TOTALS_RESPONSE_WINDOW"
    bar_delta["volume_basis"] = fl.get("volume_basis")
    bar_delta["is_proxy"] = is_proxy
    R["variants"] = {"price_response": variant("NA"), "price_plus_cvd": variant(cvd_state),
                      "price_plus_local_aggression": price_level_local, "price_plus_bar_delta": bar_delta}
    R["variants"]["price_plus_cvd"].update(volume_basis=fl.get("volume_basis"), is_proxy=is_proxy)
    pr = R["variants"]["price_response"]
    R.update(decision=pr["decision"], reason=pr["reason"])
    if scalp_policy and as_of >= parse_utc(R["expires_at"]):
        R.update(decision="SKIP", reason="TRIGGER_EXPIRED")
        g["trigger"]["status"] = "STALE"
        for vresult in R["variants"].values():
            if vresult["decision"] != "DATA_UNAVAILABLE":
                vresult.update(decision="SKIP", reason="TRIGGER_EXPIRED")
    return R


# ------------------------------------------------------------------ public entry
def _price_prefix(m5, start: int, end: int) -> dict:
    fields = ("open_at", "close_at", "available_at", "o", "h", "l", "c", "tick_volume")
    return {"start_at": iso_utc(m5.open_at[start]), "end_at": iso_utc(m5.close_at[end]),
            "hash": hash_obj({key: getattr(m5, key)[start:end + 1].tolist() for key in fields})}


def _continuation_hash(result: dict) -> str:
    return hash_obj({key: result.get(key) for key in ("source_fingerprint", "spec_hash", "symbol_metadata_hash", "snapshot_id", "as_of",
        "balance", "balance_search_state", "price_context", "price_prefix", "families")})


def _check_previous(prior: dict, m5, source_fingerprint: str, as_of: float, metadata_hash: str):
    if not isinstance(prior, dict) or prior.get("policy") != SCALP_POLICY or prior.get("spec_hash") != SCALP_SPEC_HASH:
        raise ValueError("FABIO_PREVIOUS_SPEC_MISMATCH")
    if prior.get("source_fingerprint") != source_fingerprint:
        raise ValueError("FABIO_PREVIOUS_SOURCE_MISMATCH")
    if prior.get("symbol_metadata_hash") != metadata_hash:
        raise ValueError("FABIO_PREVIOUS_SYMBOL_METADATA_MISMATCH")
    if parse_utc(prior["as_of"]) > as_of:
        raise ValueError("FABIO_PREVIOUS_IS_FUTURE")
    prefix = prior.get("price_prefix") or {}
    if not prefix:
        raise ValueError("FABIO_PREVIOUS_PREFIX_MISSING")
    i = int(np.searchsorted(m5.open_at, parse_utc(prefix["start_at"])))
    j = int(np.searchsorted(m5.close_at, parse_utc(prefix["end_at"])))
    if i > j or j >= len(m5) or _price_prefix(m5, i, j) != prefix:
        raise ValueError("FABIO_PREVIOUS_PRICE_HISTORY_CHANGED_OR_MISSING")
    if prior.get("continuation_hash") != _continuation_hash(prior):
        raise ValueError("FABIO_PREVIOUS_STATE_HASH_MISMATCH")


def analyze(sd, as_of: float, *, symbol: str, snapshot_id: str | None = None, market_state: str = "FRESH",
            flow: dict | None = None, exec_in: dict | None = None, quality_flags: list | None = None, mt5_data: dict | None = None,
            policy: str = "legacy", previous_analysis: dict | None = None) -> dict:
    if policy not in ("legacy", SCALP_POLICY):
        raise ValueError(f"FABIO_POLICY_UNSUPPORTED:{policy}")
    scalp_policy = policy == SCALP_POLICY
    if previous_analysis is not None and not scalp_policy:
        raise ValueError("FABIO_PREVIOUS_REQUIRES_SCALP_POLICY")
    m5, d1 = sd.m5, sd.d1
    if scalp_policy:
        m5 = m5.upto_available(as_of)
        m5 = m5.slice(0, int(np.searchsorted(m5.close_at, as_of, side="right")))
        m5.available_at = m5.prefix_available()
        d1 = d1.upto_available(as_of)
    n = len(m5); last = n - 1
    out: dict[str, Any] = {
        "schema": "fabio_analysis_v1", "spec_id": SCALP_SPEC["spec_id"] if scalp_policy else SPEC["spec_id"],
        "spec_version": SCALP_SPEC["version"] if scalp_policy else SPEC["version"], "spec_hash": SCALP_SPEC_HASH if scalp_policy else SPEC_HASH,
        "snapshot_id": snapshot_id, "symbol": symbol, "as_of": iso_utc(as_of), "timeframe": "M5",
        "kind": "RESEARCH_ANALYSIS_NOT_BASELINE_CANDIDATE", "market_state": market_state, "quality_flags": list(quality_flags or []),
        "win_probability": None, "win_probability_reason": "no calibration/model for this domain; AI votes or gate counts are not probabilities",
        "broker_order": False, "account_context": {"saved_context": "MT5 demo, FTMO 1-Step goal (from earlier session; unverified live account/stage/risk)",
                                                   "live_account_verified": False, "plan_passed_account_gate": False},
        "capabilities_used": {"price_proxy": True}, "families": {}}
    if scalp_policy:
        out["policy"] = policy
        out["source_id"] = sd.source_id
        out["chart_basis"] = sd.prof.get("chart_basis", "UNKNOWN")
        out["source_fingerprint"] = hash_obj({"source_id": sd.source_id, "symbol": symbol, "chart_basis": out["chart_basis"]})
        out["symbol_metadata_hash"] = hash_obj({"profile": sd.prof, "tick_size": sd.q})
        if previous_analysis is not None:
            _check_previous(previous_analysis, m5, out["source_fingerprint"], as_of, out["symbol_metadata_hash"])
        out["policy_parameters"] = {k: SCALP_SPEC[k] for k in ("reference_max_age_bars", "episode_max_bars", "entry_window_s", "max_hold_s")}
        out["profile_lifecycle"] = {"mode": "FROZEN_PREVIOUS_ANALYSIS_CHAIN" if previous_analysis is not None else "RECONSTRUCTED_FROM_PINNED_INPUTS",
            "rule": SCALP_SPEC["profile_revision_rule"],
            "comparison": "compare profile_signature and plan_id across observations; do not overwrite a prior frozen plan or count a data revision as a new trade"}
        if previous_analysis is not None:
            out["profile_lifecycle"].update(previous_analysis_id=previous_analysis.get("analysis_id"), previous_hash=hash_obj(previous_analysis))
        out["account_context"] = {"saved_context": "MT5 demo research; FTMO account not verified or required",
                                  "live_account_verified": False, "plan_passed_account_gate": False}
    if n < P["min_history_bars"]:
        out.update(route="FTMO_PRICE_PROXY", decision="DATA_UNAVAILABLE", reason=f"HISTORY_INSUFFICIENT:{n}<{P['min_history_bars']}")
        return out
    atrs = atr(m5, 14)
    fl = mt5_data["flow"] if mt5_data is not None else load_flow(flow, m5, symbol, as_of)
    mt5_profile = mt5_data.get("profile") if mt5_data else None
    if mt5_data is not None:
        exec_in = mt5_data.get("exec")
        out["mt5_inputs"] = mt5_data["provenance"]
        out["execution_quote"] = exec_in
    route = fl.get("route", "FTMO_PRICE_PROXY") if mt5_data is not None else ("FTMO_EXTERNAL_FLOW" if fl.get("use_in_decision") else "FTMO_PRICE_PROXY")
    out.update(route=route, flow=public_flow(fl), futures_reference_route="NOT_SUPPORTED_BY_THIS_TOOL (needs futures bars + trades dataset)")
    out["capabilities_used"]["external_flow"] = mt5_data is None and bool(fl.get("use_in_decision"))
    out["capabilities_used"]["mt5_ticks"] = mt5_data is not None and bool(fl.get("bars_used"))
    out["capabilities_used"]["execution_economics"] = exec_in is not None
    out["price_context"] = {"last_close": float(m5.c[last]), "last_bar_close_at": iso_utc(m5.close_at[last]), "atr14": _f(atrs[last]),
                            "volume_basis": "tick_volume (price activity; not executed volume)"}
    done = np.flatnonzero((d1.close_at <= as_of) & (d1.available_at <= as_of)) if len(d1) else []
    if len(done):                                            # only a COMPLETED D1 bar is a known previous-day level
        j = int(done[-1])
        out["price_context"].update(prev_day_high=float(d1.h[j]), prev_day_low=float(d1.l[j]), prev_day_close_at=iso_utc(d1.close_at[j]))
    data_ok = market_state == "FRESH" and math.isfinite(float(atrs[last]))
    if not data_ok:
        out["data_status"] = "DATA_UNAVAILABLE:MARKET_STATE_" + market_state
    search_state = {}
    bal = _scalp_balance(m5, atrs, last, mt5_profile, previous_analysis, search_state) if scalp_policy else find_balance(m5, atrs, last, mt5_profile)
    out["balance"] = bal
    if scalp_policy:
        out["balance_search_state"] = search_state
        out["price_prefix"] = _price_prefix(m5, bal["start_index"] if bal else max(0, last - 300), last)
    prior_families = (previous_analysis or {}).get("families", {}) if (bal or {}).get("breakout_at") == ((previous_analysis or {}).get("balance") or {}).get("breakout_at") else {}
    if flow is not None or mt5_data is not None:
        out["divergence_context"] = divergences(m5, fl, last)
    fam: dict[str, Any] = {}
    if bal is None:
        fam["F1"] = {"family": "F1", "decision": "SKIP", "reason": "STATE_UNKNOWN_NO_BALANCE_FOUND", "gates": {}}
        fam["F2"] = dict(fam["F1"], family="F2")
        out["state"] = "UNKNOWN"
    else:
        e, VAH, VAL, POC = bal["end_index"], bal["vah"], bal["val"], bal["poc"]
        post = range(bal.get("breakout_index", e + 1) if scalp_policy else e + 1, last + 1)
        # ---- F1: accepted exit
        k = P["acceptance_closes"]
        acc = None
        for a in post:
            if a + k - 1 > last:
                break
            if all(m5.c[a + j] > VAH for j in range(k)):
                acc = (a, +1, VAH); break
            if all(m5.c[a + j] < VAL for j in range(k)):
                acc = (a, -1, VAL); break
        if acc is None:
            fam["F1"] = {"family": "F1", "decision": "SKIP", "reason": "NO_ACCEPTANCE_OUTSIDE_VALUE", "gates": {}}
        else:
            a, dirn, edge = acc
            known = iso_utc(m5.available_at[a + k - 1])
            back = [j for j in range(a + k, last + 1) if VAL <= m5.c[j] <= VAH]
            if back and not scalp_policy:
                fam["F1"] = {"family": "F1", "side": "LONG" if dirn > 0 else "SHORT", "decision": "SKIP", "reason": "RETURNED_TO_BALANCE",
                             "state_known_at": known, "gates": {}}
            else:
                pdl = ("prev_day_high" if dirn > 0 else "prev_day_low")
                if scalp_policy:
                    tgt, target_src = _scalp_prior_poc(m5, atrs, bal, float(m5.c[a + k - 1]), dirn, mt5_profile)
                else:
                    tgt = out["price_context"].get(pdl)
                    ok_t = tgt is not None and dirn * (tgt - float(m5.c[last])) > 0
                    tgt, target_src = (tgt if ok_t else None), (pdl.upper() if ok_t else "PREV_DAY_LEVEL_NOT_AHEAD_OF_PRICE_OR_UNAVAILABLE")
                fam["F1"] = _family("F1", m5, atrs, last, dirn, bal, known, dirn * edge, a if scalp_policy else e + 1, tgt,
                                    target_src, lambda t, r: [], fl, exec_in, symbol, as_of, mt5_profile=mt5_profile,
                                    scalp_policy=scalp_policy,
                                    invalidation_event=(back[0], "RETURNED_TO_BALANCE") if scalp_policy and back else None,
                                    tick_size=sd.q, prior_family=prior_families.get("F1"))
        # ---- F2: failed breakout + reclaim
        pair = first_b = None
        for b in post:
            up, dn = m5.c[b] > bal["range_high"], m5.c[b] < bal["range_low"]
            if not (up or dn):
                continue
            first_b = b if first_b is None else first_b
            rc = next((j for j in range(b + 1, min(last, b + P["fail_max_bars"]) + 1) if VAL <= m5.c[j] <= VAH), None)
            if rc is not None:
                pair = (b, rc, +1 if up else -1)               # latest breakout that was reclaimed inside value
                if scalp_policy:
                    break
            if scalp_policy:
                break  # the first outside-range attempt owns the failure window
        if pair is None and first_b is not None:
            pend = last - first_b < P["fail_max_bars"]
            fam["F2"] = {"family": "F2", "decision": "WAIT" if pend else "SKIP",
                         "reason": "FAILURE_NOT_YET_CONFIRMED" if pend else "BREAKOUT_NOT_FAILED", "gates": {}}
        elif pair is None:
            fam["F2"] = {"family": "F2", "decision": "SKIP", "reason": "NO_BREAKOUT_OF_BALANCE_RANGE", "gates": {}}
        else:
            b, rc, bd = pair
            if True:
                dirn = -bd                                         # trade back toward balance
                b0 = b
                while b0 - 1 > e and (m5.c[b0 - 1] > bal["range_high"] if bd > 0 else m5.c[b0 - 1] < bal["range_low"]):
                    b0 -= 1                                        # start of the contiguous outside-range run
                xs = b0 + int(np.argmax(m5.h[b0:rc + 1] if bd > 0 else -m5.l[b0:rc + 1]))
                xext = float(m5.h[xs] if bd > 0 else m5.l[xs])
                tgt_ok = dirn * (POC - float(m5.c[last])) > 0
                resumed = lambda t, r: ["BREAKOUT_RESUMED_BEYOND_FAILURE_EXTREME"] if any(
                    (m5.c[j] > xext if bd > 0 else m5.c[j] < xext) for j in range(rc + 1, last + 1)) else []
                known = iso_utc(m5.available_at[rc])
                if resumed(0, 0) and not scalp_policy:
                    fam["F2"] = {"family": "F2", "side": "LONG" if dirn > 0 else "SHORT", "decision": "SKIP", "reason": resumed(0, 0)[0],
                                 "state_known_at": known, "gates": {}}
                elif not tgt_ok and not scalp_policy:
                    fam["F2"] = {"family": "F2", "side": "LONG" if dirn > 0 else "SHORT", "decision": "SKIP", "reason": "POC_TARGET_BEHIND_PRICE",
                                 "state_known_at": known, "gates": {}}
                else:
                    fam["F2"] = _family("F2", m5, atrs, last, dirn, bal, known, dirn * xext, xs,
                                         POC, "BALANCE_POC", resumed, fl, exec_in, symbol, as_of,
                                         reclaim_index=rc, mt5_profile=mt5_profile, scalp_policy=scalp_policy,
                                         invalidation_event=next(((j, "BREAKOUT_RESUMED_BEYOND_FAILURE_EXTREME")
                                             for j in range(rc + 1, last + 1) if (m5.c[j] > xext if bd > 0 else m5.c[j] < xext)), None) if scalp_policy else None,
                                         tick_size=sd.q, prior_family=prior_families.get("F2"))
                    fam["F2"]["failed_breakout"] = {"breakout_index": int(b), "reclaim_index": int(rc),
                                                     "reclaim_known_at": known, "failure_extreme_index": int(xs),
                                                     "failure_extreme": xext}
        out["state"] = {"F1": fam["F1"].get("reason"), "F2": fam["F2"].get("reason")}
    if not data_ok:
        for f in fam.values():
            f["decision_if_data_were_fresh"] = f.get("decision"); f["decision"] = "DATA_UNAVAILABLE"; f["reason"] = out["data_status"]
            for variant_result in (f.get("variants") or {}).values():
                variant_result["decision_if_data_were_fresh"] = variant_result.get("decision")
                variant_result["decision"] = "DATA_UNAVAILABLE"
                variant_result["reason"] = out["data_status"]
    out["families"] = fam
    if scalp_policy:
        for name, f in fam.items():
            g = f.get("gates") or {}
            trigger = g.get("trigger") or {}
            location = g.get("location") or {}
            if out["chart_basis"] != "BID" and trigger.get("trigger_known_at"):
                g["economics"] = {"status": "UNKNOWN", "reason": "CHART_BASIS_UNSUPPORTED:" + out["chart_basis"]}
                if f["decision"] == "ENTER_CANDIDATE":
                    f.update(decision="WAIT", reason="ECONOMICS_UNKNOWN")
                for variant_result in (f.get("variants") or {}).values():
                    if variant_result["decision"] == "ENTER_CANDIDATE":
                        variant_result.update(decision="WAIT", reason="ECONOMICS_UNKNOWN")
                f["missing"].append("EXECUTION_CHART_BASIS_UNSUPPORTED")
            if f.get("state_known_at") and bal is not None:
                f["episode_key"] = stable_id("FEP", out["source_fingerprint"], SCALP_SPEC_HASH, name, bal.get("breakout_at"), f.get("side"))
                f["opportunity_id"] = stable_id("FOP", out["source_fingerprint"], symbol, SCALP_SPEC_HASH, name, f.get("side"),
                                                  bal.get("start_at"), bal["known_at"], bal.get("breakout_at"), f["state_known_at"])
                f["profile_revision_id"] = stable_id("FPROF", f["episode_key"], bal.get("volume_basis"),
                    {k: bal.get(k) for k in ("start_at", "end_at", "poc", "vah", "val", "target_reference")}, f.get("profile_signature"))
            if f["decision"] == "DATA_UNAVAILABLE":
                stage = "DATA_UNAVAILABLE"
            elif f["decision"] == "SKIP":
                stage = "INVALIDATED" if f.get("reason") in ("RETURNED_TO_BALANCE", "BREAKOUT_RESUMED_BEYOND_FAILURE_EXTREME",
                                                               "IMPULSE_EXTENDED_AFTER_PROFILE_FREEZE", "TRIGGER_NEGATED_BY_CLOSE_BELOW_STRUCTURE",
                                                               "POC_TARGET_BEHIND_PRICE") else "EXPIRED" if f.get("reason") == "TRIGGER_EXPIRED" else "NO_STRUCTURE"
            elif trigger.get("status") == "OBSERVED":
                stage = "TRIGGER_OBSERVED"
            elif location.get("status") == "TOUCHED_RECENTLY":
                stage = "WAIT_TRIGGER"
            else:
                stage = "WAIT_LOCATION" if f.get("state_known_at") else "NO_STRUCTURE"
            ec = g.get("economics") or {}
            f["setup_stage"] = stage
            f["execution_readiness"] = ("READY_FOR_REVIEW" if f["decision"] == "ENTER_CANDIDATE" else
                                         "QUOTE_STALE" if "EXEC_QUOTE_STALE" in ec.get("reason", "") and stage == "TRIGGER_OBSERVED" else
                                         "DATA_MISSING" if "CHART_BASIS_UNSUPPORTED" in ec.get("reason", "") else
                                         "COST_UNKNOWN" if ec.get("status") == "UNKNOWN" and stage == "TRIGGER_OBSERVED" else
                                         "DATA_MISSING" if stage == "DATA_UNAVAILABLE" else "NOT_READY")
            f["broker_order"] = False
            if data_ok and bal and bal.get("episode_expires_at") and as_of >= parse_utc(bal["episode_expires_at"]):
                f.update(setup_stage="EXPIRED", decision="SKIP", reason="EPISODE_EXPIRED", execution_readiness="NOT_READY")
                for vresult in (f.get("variants") or {}).values():
                    vresult.update(decision="SKIP", reason="EPISODE_EXPIRED")
            if trigger.get("trigger_known_at"):
                f["trigger_id"] = stable_id("FTR", f["opportunity_id"], trigger["trigger_known_at"])
                inv = f.get("invalidation") or {}
                target = (g.get("target_room") or {}).get("target")
                if target is not None and inv and sd.prof.get("chart_basis") == "BID":
                    f["research_plan"] = {"schema": "fabio_plan_v1", "policy": SCALP_POLICY, "spec_hash": SCALP_SPEC_HASH,
                        "source_id": sd.source_id, "symbol": symbol, "family": name, "side": f["side"],
                        "source_fingerprint": out["source_fingerprint"],
                        "opportunity_id": f["opportunity_id"], "trigger_id": f["trigger_id"],
                        "known_at": trigger["trigger_known_at"], "expires_at": min(f["expires_at"], bal.get("episode_expires_at", f["expires_at"])),
                        "sl_chart": inv["level"] - (1 if f["side"] == "LONG" else -1) * inv["sl_buffer"],
                        "target_chart": target, "chart_basis": "BID", "tick_size": sd.q,
                        "max_hold_s": SCALP_SPEC["max_hold_s"], "atr_frozen": bal["atr_at_end"],
                        "trigger_close": float(m5.c[trigger["trigger_index"]]),
                        "profile_signature": f.get("profile_signature"), "profile_basis": f.get("profile_basis"),
                        "profile_known_at": (g.get("pullback") or {}).get("profile_frozen_at")}
                    f["research_plan"]["plan_id"] = stable_id("FPLAN", f["research_plan"])
                    if f.get("invalidated_at"):
                        f["research_plan"]["invalidated_at"] = f["invalidated_at"]
            f["revision_id"] = stable_id("FREV", f.get("opportunity_id"), f)
    best = max(fam.values(), key=lambda f: RANK[f["decision"]])
    sides = {f.get("side") for f in fam.values() if f["decision"] == "ENTER_CANDIDATE"}
    out["decision"] = "WAIT" if len(sides) > 1 else best["decision"]
    out["reason"] = "CONFLICTING_SIDES_BETWEEN_FAMILIES" if len(sides) > 1 else best.get("reason")
    out["causality"] = {"inputs_after_as_of": 0, "m5_last_available_at": iso_utc(m5.available_at[last]), "ok": bool(m5.available_at[last] <= as_of)}
    if scalp_policy:
        out["continuation_hash"] = _continuation_hash(out)
    return out


# ------------------------------------------------------------------ CLI helpers
def run_for_snapshot(snapshot_id: str, symbol: str, flow: dict | None = None, exec_in: dict | None = None, flow_sha: str | None = None, exec_sha: str | None = None,
                     store: bool = True, policy: str = "legacy", previous_analysis: dict | None = None) -> dict:
    from .context import snapshot_pins
    from .detectors import load_symbol
    from .snapshot import load_snapshot
    snap = load_snapshot(snapshot_id)
    if symbol not in snap["universe"]:
        raise KeyError(f"SYMBOL_NOT_IN_SNAPSHOT:{symbol}")
    as_of = parse_utc(snap["as_of_utc"])
    sd = load_symbol(symbol, cut_available_at=as_of, pins=snapshot_pins(snap, symbol))
    sy = snap["symbols"][symbol]
    automatic = flow is None and exec_in is None
    if automatic:
        from .mt5_flow import read_snapshot_mt5
        mt5_data = read_snapshot_mt5(snap, sd.m5, symbol, as_of, chart_basis=sd.prof.get("chart_basis", "UNKNOWN"))
    else:
        mt5_data = None
    res = analyze(sd, as_of, symbol=symbol, snapshot_id=snapshot_id, market_state=sy.get("market_state", "UNKNOWN"), flow=flow, exec_in=exec_in,
                  quality_flags=sy.get("quality_flags"), mt5_data=mt5_data, policy=policy, previous_analysis=previous_analysis)
    res["inputs"] = {"mode": "MT5_SNAPSHOT_AUTO" if automatic else "EXPLICIT_OFFLINE_INPUT", "flow_sha256": flow_sha, "exec_sha256": exec_sha, "hashes": {k: snap.get(k) for k in ("dataset_manifest_hash", "engine_hash", "config_hash")}}
    res["analysis_id"] = stable_id("FAB", snapshot_id, symbol, res["spec_hash"], res["inputs"]["mode"], flow_sha, exec_sha)
    if policy == SCALP_POLICY:
        from .util import engine_hash
        res["implementation_engine_hash"] = engine_hash()
        res["analysis_id"] = stable_id("FAB", res["analysis_id"], res["implementation_engine_hash"], hash_obj(previous_analysis) if previous_analysis else None)
    if store:
        p = STORE_DIR / "fabio" / snapshot_id / f"{symbol}_{res['analysis_id']}.json"
        write_immutable_json(p, res)
        res["artifact_path"] = str(p)
        if policy == SCALP_POLICY:
            for f in res["families"].values():
                if f.get("opportunity_id"):
                    write_immutable_json(STORE_DIR / "fabio_ledger" / f["opportunity_id"] / f"{res['analysis_id']}.json",
                                         {"schema": "fabio_observation_v1", "analysis_id": res["analysis_id"], "snapshot_id": snapshot_id,
                                          "as_of": res["as_of"], "source_id": sd.source_id, "family": f})
    return res


def render_report(res: dict) -> str:
    """Vietnamese machine-part report from the SAME analysis object (agent reasoning is added separately by the skill)."""
    L = [f"# Fabio/FTMO — {res['symbol']} (số liệu máy, spec {res['spec_id']} v{res['spec_version']})", "",
         f"- Snapshot: `{res.get('snapshot_id')}` · as-of (UTC): {res['as_of']} · phân tích: `{res.get('analysis_id')}`",
         f"- Route: **{res['route']}** · quyết định nghiên cứu: **{res['decision']}** ({res.get('reason')}) — không phải lệnh broker, không có xác suất thắng.",
         f"- Tài khoản: {res['account_context']['saved_context']}; xác minh live = {res['account_context']['live_account_verified']}; qua gate tài khoản = {res['account_context']['plan_passed_account_gate']}.",
         f"- Thị trường: {res['market_state']}; profile ghi rõ basis: tick tại giá khi đủ coverage hoặc xấp xỉ từ tick volume nến.", ""]
    fl = res.get("flow") or {}
    L.append(f"- CVD: {fl.get('status')} · basis {fl.get('volume_basis')} · proxy {fl.get('is_proxy')} · coverage {fl.get('coverage_window')} · {fl.get('reasons') or ''}")
    if res.get("mt5_inputs"):
        L.append("- Nguồn thị trường: tự đọc nến/tick đã ghim từ MT5; phí/slippage thiếu giữ UNKNOWN.")
    if res.get("profile_lifecycle"):
        L.append("- Vòng đời profile: " + res["profile_lifecycle"]["mode"] + ". Nối previous-analysis giữ vùng/target cũ; snapshot độc lập là tái dựng. So profile_revision_id và giữ plan quyết định để replay.")
    pc = res.get("price_context") or {}
    if pc:
        L.append(f"- Giá đóng M5 cuối {pc.get('last_close')} · ATR14 {pc.get('atr14')} · PDH {pc.get('prev_day_high')} · PDL {pc.get('prev_day_low')}")
    b = res.get("balance")
    L.append(f"- Cân bằng: POC {b['poc']:.5g} · VAH {b['vah']:.5g} · VAL {b['val']:.5g} (biết lúc {b['known_at']})" if b else "- Cân bằng: UNKNOWN (không tìm thấy)")
    for k, f in (res.get("families") or {}).items():
        L += ["", f"## {k} — {f['decision']} ({f.get('reason')}) {f.get('side', '')}"]
        if res.get("policy") == SCALP_POLICY:
            L.append(f"- Giai đoạn: {f.get('setup_stage')} · thực thi: {f.get('execution_readiness')} · cơ hội: `{f.get('opportunity_id')}` · revision: `{f.get('revision_id')}`")
            L.append(f"- Profile: `{f.get('profile_revision_id')}` · basis: {f.get('profile_basis')} · plan: `{(f.get('research_plan') or {}).get('plan_id')}`")
        g = f.get("gates") or {}
        for gn in ("location", "trigger", "target_room", "economics", "flow"):
            if gn in g:
                L.append(f"- {gn}: `{ {x: y for x, y in g[gn].items() if x not in ('divergence',)} }`")
        if f.get("invalidation"):
            L.append(f"- Vô hiệu: {f['invalidation']['level']} · hết hạn: {f.get('expires_at')}")
        for tag, key in (("Ủng hộ", "supporting_evidence"), ("Phản chứng", "contradicting_evidence")):
            if f.get(key):
                L.append(f"- {tag}: " + ", ".join(x["id"] for x in f[key]))
        if f.get("missing"):
            L.append("- Thiếu: " + ", ".join(f["missing"]))
        if f.get("variants"):
            L.append("- So sánh cùng cơ hội: " + "; ".join(f"{n}={v['decision']}" for n, v in f["variants"].items()))
    L += ["", "> Phần suy xét của agent (kịch bản ưu tiên/ngược, bằng chứng bác bỏ mạnh nhất) viết riêng, tách khỏi số liệu máy ở trên."]
    return "\n".join(L) + "\n"
