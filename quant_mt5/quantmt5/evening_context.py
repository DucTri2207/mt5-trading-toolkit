"""MT5-only descriptive context. No candidate, gate, plan or order is created here."""
from __future__ import annotations

import datetime as dt
import math
from copy import deepcopy
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import numpy as np

from .features import SeriesCache
from .data import DataVersionMismatch
from .util import hash_obj, iso_utc, parse_utc

VERSION = "A_MT5_CONTEXT_V1"
WINDOWS = (
    ("ASIA_REFERENCE", "UTC", (0, 0), (6, 0)),
    ("LONDON_OPEN_REFERENCE", "Europe/London", (8, 0), (9, 0)),
    ("NEW_YORK_OPEN_REFERENCE", "America/New_York", (9, 30), (10, 30)),
)
FIAT = frozenset("USD EUR JPY GBP CHF CAD AUD NZD SEK NOK DKK SGD HKD CNH CNY MXN ZAR TRY PLN CZK HUF BRL INR RUB KRW THB ILS AED SAR".split())


def number(value):
    if isinstance(value, (bool, np.bool_)) or not isinstance(value, (int, float, np.number)):
        return None
    return float(value) if math.isfinite(float(value)) else None


def _timestamp(value):
    if isinstance(value, str):
        try:
            return parse_utc(value)
        except (ValueError, TypeError, OverflowError):
            return None
    return number(value)


def _known(value, cutoff):
    t = _timestamp(value)
    return t is not None and t <= cutoff


def _clean(value):
    """JSON finite values only; preserves source labels, null is never replaced by zero."""
    if isinstance(value, dict):
        return {k: _clean(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_clean(v) for v in value]
    if isinstance(value, (float, np.floating)):
        return number(value)
    if isinstance(value, np.integer):
        return int(value)
    if isinstance(value, np.bool_):
        return bool(value)
    return deepcopy(value)


def _source(snap_id, symbol, kind, key, record):
    return {"snapshot_id": snap_id, "symbol": symbol, "artifact_kind": kind, "record_key": key,
            "available_at": record.get("known_at") or record.get("available_at"),
            "source": _clean(record.get("source") or record.get("source_refs") or {}),
            "level_source": _clean(record.get("level_source")),
            "quality": _clean(record.get("quality"))}


def _bar_ref(bars, i, snapshot_id, *, prefix=False):
    indices = slice(0, i + 1) if prefix else slice(i, i + 1)
    return {"snapshot_id": snapshot_id, "symbol": bars.symbol, "artifact_kind": "PINNED_BARS",
            "record_key": f"{bars.tf}:{iso_utc(bars.open_at[i])}", "tf": bars.tf,
            "bar_open_at": iso_utc(bars.open_at[i]), "bar_close_at": iso_utc(bars.close_at[i]),
            "available_at": iso_utc(float(np.max(bars.available_at[indices]))),
            "seed_start_at": iso_utc(bars.open_at[0]) if prefix else None,
            "prefix_through_index": int(i) if prefix else None, "source": _clean(bars.provenance),
            "quality": bars.status(i)}


def _usable_bar(bars, i, cutoff):
    vals = [number(getattr(bars, k)[i]) for k in ("open_at", "close_at", "available_at", "o", "h", "l", "c")]
    if any(v is None for v in vals):
        return False
    op, cl, av, o, h, l, c = vals
    return (cl <= cutoff and av <= cutoff and cl - op == bars.tf_s and
            l <= min(o, c) <= max(o, c) <= h and bars.status(i, cutoff) != "FINAL_FEWER_MEMBERS")


def price_reference(bars, cutoff, snapshot_id, chart_basis="UNKNOWN"):
    """Last closed, known M5 in the supplied pinned prefix; no quote/provisional fallback."""
    hits = np.flatnonzero((bars.close_at <= cutoff) & (bars.available_at <= cutoff))
    base = {"kind": "LAST_CLOSED_M5", "close": None, "bar_open_at": None, "bar_close_at": None,
            "available_at": None, "chart_basis": chart_basis, "source_refs": [], "quality": "UNKNOWN"}
    if not len(hits):
        return dict(base, reason="NO_CLOSED_M5")
    i = int(hits[-1])
    if not _usable_bar(bars, i, cutoff) or float(np.max(bars.available_at[:i + 1])) > cutoff:
        return dict(base, reason="LAST_CLOSED_M5_UNUSABLE")
    ref = _bar_ref(bars, i, snapshot_id)
    return dict(base, close=float(bars.c[i]), bar_open_at=ref["bar_open_at"], bar_close_at=ref["bar_close_at"],
                available_at=ref["available_at"], source_refs=[ref], quality="OK", reason=None)


def reference_windows(bars, cutoff, snapshot_id):
    """Project reference windows, never broker schedules. Missing/late slots cannot make final extrema."""
    out = []
    for window_id, zone, start_hm, end_hm in WINDOWS:
        try:
            timezone = ZoneInfo(zone)
        except ZoneInfoNotFoundError:
            out.append({"window_id": window_id, "version": VERSION, "timezone": zone, "local_date": None,
                        "start_utc": None, "end_utc": None, "start_local": None, "end_local": None,
                        "definition_basis": "PROJECT_REFERENCE_WINDOW", "lifecycle": "UNKNOWN",
                        "item_state": "UNSUPPORTED", "reason": "TZ_DATABASE_UNAVAILABLE",
                        "expected_count": None, "observed_count": 0, "missing_slots": [],
                        "high": None, "low": None, "observed_high": None, "observed_low": None,
                        "known_at": None, "source_refs": [], "time_quality": _clean(bars.provenance)})
            continue
        local = dt.datetime.fromtimestamp(cutoff, dt.timezone.utc).astimezone(timezone)
        start = dt.datetime.combine(local.date(), dt.time(*start_hm), tzinfo=timezone).timestamp()
        end = dt.datetime.combine(local.date(), dt.time(*end_hm), tzinfo=timezone).timestamp()
        due_end = min(end, cutoff)
        slots = list(range(int(start), int(due_end) - 299, 300)) if cutoff >= start else []
        indices, missing = [], []
        for slot in slots:
            hits = np.flatnonzero(bars.open_at == slot)
            if len(hits) != 1 or not _usable_bar(bars, int(hits[0]), cutoff):
                missing.append(iso_utc(slot))
            else:
                indices.append(int(hits[0]))
        if cutoff < start:
            state = "NOT_STARTED"
        elif cutoff < end:
            state = "DEVELOPING"
        elif len(indices) == len(slots) and indices:
            state = "COMPLETED"
        else:
            state = "PARTIAL" if indices else "NO_DATA"
        high = float(np.max(bars.h[indices])) if indices else None
        low = float(np.min(bars.l[indices])) if indices else None
        refs = [_bar_ref(bars, i, snapshot_id) for i in indices]
        out.append({"window_id": window_id, "version": VERSION, "local_date": str(local.date()), "timezone": zone,
                    "start_utc": iso_utc(start), "end_utc": iso_utc(end),
                    "start_local": dt.datetime.fromtimestamp(start, timezone).isoformat(),
                    "end_local": dt.datetime.fromtimestamp(end, timezone).isoformat(),
                    "definition_basis": "PROJECT_REFERENCE_WINDOW", "lifecycle": state,
                    "item_state": "OK" if state in ("COMPLETED", "NOT_STARTED", "DEVELOPING") else "UNKNOWN",
                    "expected_count": len(slots), "observed_count": len(indices), "missing_slots": missing,
                    "high": high if state == "COMPLETED" else None, "low": low if state == "COMPLETED" else None,
                    "observed_high": high, "observed_low": low,
                    "known_at": iso_utc(max(float(bars.available_at[i]) for i in indices)) if indices else None,
                    "source_refs": refs, "time_quality": {k: _clean(bars.provenance.get(k)) for k in
                    ("clock_profile", "clock_profile_status", "time_contract", "time_basis_status", "time_quality_flags")}})
    return out


def relative_movement(bars, cutoff, snapshot_id, cache=None):
    """Exact UTC hourly endpoints, contiguous path, ATR from start (including its seed provenance)."""
    T = int(cutoff // 3600) * 3600
    atrs = (cache or SeriesCache(bars)).get("atr14")
    out = {}
    for hours in (1, 4):
        start = T - hours * 3600
        rec = {"horizon_hours": hours, "T": iso_utc(T), "start": iso_utc(start), "value": None,
               "numerator": None, "denominator": None, "denominator_at": iso_utc(start),
               "known_at": None, "input_refs": [], "quality": "UNKNOWN", "reason": "MISSING_OR_UNUSABLE_EXACT_H1",
               "unit": "ATR14_H1_AT_START", "method_version": VERSION}
        indices = []
        for close in range(start, T + 1, 3600):
            hits = np.flatnonzero(bars.close_at == close)
            if len(hits) != 1 or not _usable_bar(bars, int(hits[0]), cutoff):
                break
            indices.append(int(hits[0]))
        if len(indices) == hours + 1:
            first, last = indices[0], indices[-1]
            denominator = number(atrs[first])
            known = float(np.max(bars.available_at[:last + 1]))
            if denominator is None or denominator <= 0:
                rec["reason"] = "ATR_START_UNUSABLE"
            elif known > cutoff:
                rec["reason"] = "ATR_PREFIX_NOT_YET_KNOWN"
            else:
                numerator = float(bars.c[last] - bars.c[first])
                rec.update(value=numerator / denominator, numerator=numerator, denominator=denominator,
                           known_at=iso_utc(known), quality="OK", reason=None,
                           input_refs=[_bar_ref(bars, first, snapshot_id, prefix=True)] +
                                      [_bar_ref(bars, i, snapshot_id) for i in indices[1:]])
        out[str(hours)] = rec
    return out


def asset_metadata(profile):
    """Native metadata only, never character slicing or speculative symbol aliases."""
    base, quote, mode = profile.get("base_currency"), profile.get("profit_currency"), profile.get("calc_mode")
    asset = "UNKNOWN_ASSET_CLASS"
    if base in ("XAU", "XAG", "XPT", "XPD"):
        asset = "METAL"
    elif mode in ("FOREX", "FOREX_NO_LEVERAGE") and base in FIAT and quote in FIAT and base != quote:
        asset = "FX"
    elif mode == "CFDINDEX":
        asset = "INDEX"
    return {"asset_class": asset, "base_currency": base if asset == "FX" else None,
            "quote_currency": quote if asset == "FX" else None, "native_symbol": profile.get("native_symbol"),
            "calc_mode": mode, "metadata_status": profile.get("metadata_status", "UNKNOWN"),
            "status": "OK" if asset != "UNKNOWN_ASSET_CLASS" else "UNKNOWN",
            "basis": "PINNED_PROFILE_METADATA", "source": _clean({k: profile.get(k) for k in
            ("base_currency", "profit_currency", "calc_mode", "native_symbol", "metadata_status", "metadata_invalid", "enum_contract")})}


def exposure(metadata, side):
    if (metadata.get("asset_class") != "FX" or metadata.get("base_currency") not in FIAT or
            metadata.get("quote_currency") not in FIAT or side not in ("LONG", "SHORT")):
        return {"item_state": "UNKNOWN", "reason": "NOT_FX_OR_NO_A_SIDE", "legs": []}
    sign = 1 if side == "LONG" else -1
    return {"item_state": "OK", "basis": "DIRECTION_ONLY_NOT_LOT_OR_RISK", "legs": [
        {"currency": metadata["base_currency"], "sign": sign}, {"currency": metadata["quote_currency"], "sign": -sign}]}


def _features(market):
    return {(f.get("name"), f.get("tf")): f for f in market.get("features", [])}


def _feature_value(feature, cutoff):
    if not feature or feature.get("quality") != "OK" or feature.get("provisional"):
        return None
    if not _known(feature.get("known_at") or feature.get("available_at"), cutoff):
        return None
    return number(feature.get("value"))


def direction_context(market, cutoff):
    features = _features(market)
    p = _feature_value(features.get(("h1_close_minus_ema50_over_atr", "H1")), cutoff)
    s = _feature_value(features.get(("h1_ema50_slope_over_atr", "H1")), cutoff)
    if p is None or s is None:
        return "UNKNOWN"
    if p > 0 and s > 0:
        return "UP_BIAS"
    if p < 0 and s < 0:
        return "DOWN_BIAS"
    return "MIXED_OR_FLAT"


def alignment(direction, side):
    if side not in ("LONG", "SHORT") or direction == "UNKNOWN":
        return "UNKNOWN"
    if direction == "MIXED_OR_FLAT":
        return "NEUTRAL"
    return "SUPPORTS" if (direction == "UP_BIAS") == (side == "LONG") else "CONTRADICTS"


def zone_distance(low, high, close, atr):
    low, high, close, atr = (number(x) for x in (low, high, close, atr))
    if low is None or high is None or close is None or low > high:
        return {"distance_price": None, "distance_atr": None, "relative_position": "UNKNOWN", "reason": "UNUSABLE_ZONE_OR_PRICE"}
    distance = max(low - close, 0.0, close - high)
    return {"distance_price": distance, "distance_atr": distance / atr if atr is not None and atr > 0 else None,
            "relative_position": "BELOW" if close < low else "ABOVE" if close > high else "INSIDE",
            "reason": None if atr is not None and atr > 0 else "ATR_M5_UNUSABLE"}


def value_location(close, balance, cutoff):
    close, low, high = number(close), number(balance.get("val")), number(balance.get("vah"))
    if close is None or low is None or high is None or low > high or not _known(balance.get("known_at"), cutoff):
        return "UNKNOWN"
    return "BELOW_REFERENCE_VALUE" if close < low else "ABOVE_REFERENCE_VALUE" if close > high else "INSIDE_REFERENCE_VALUE"


def _level(key, kind, low, high, record, snap_id, symbol, close, atr, cutoff, basis):
    low, high = number(low), number(high)
    known = record.get("known_at") or record.get("available_at")
    if low is None or high is None or low > high or not _known(known, cutoff):
        return None
    return {"level_id": key, "kind": kind, "low": low, "high": high, "known_at": known,
            "basis": basis, "quality": _clean(record.get("quality", "SOURCE_LABEL_PRESERVED")),
            "is_developing": False, "source_refs": [_source(snap_id, symbol, kind, key, record)],
            **zone_distance(low, high, close, atr)}


def _distance_provenance(levels, price, atr_feature, snapshot_id, symbol):
    for level in levels:
        refs = deepcopy(level.get("source_refs", []))
        if level.get("distance_price") is not None:
            refs.append(_source(snapshot_id, symbol, "MARKET_PRICE", "price_reference", price))
        if level.get("distance_atr") is not None:
            refs.append(_source(snapshot_id, symbol, "MARKET_FEATURE", "atr14_wilder:M5", atr_feature or {}))
        times = [_timestamp(r.get("available_at")) for r in refs]
        level["input_refs"] = refs
        level["source_known_at"] = level.get("known_at")
        if times and all(t is not None for t in times):
            level["known_at"] = iso_utc(max(times))


def _levels(snap, symbol, market, fabio, close, atr, cutoff):
    out, sid = [], snap["snapshot_id"]
    features = _features(market)
    defs = (("distance_close_to_prev_day_high_over_atr", "PDH"), ("distance_close_to_prev_day_low_over_atr", "PDL"),
            ("distance_close_to_h1_8bar_high_over_atr", "DESCRIPTIVE_H1_RANGE_HIGH"),
            ("distance_close_to_h1_8bar_low_over_atr", "DESCRIPTIVE_H1_RANGE_LOW"))
    for name, kind in defs:
        rec = features.get((name, "M5"), {})
        lv = _level(kind, kind, rec.get("level"), rec.get("level"), rec, sid, symbol, close, atr, cutoff, rec.get("window"))
        if lv:
            out.append(lv)
    bal = fabio.get("balance") or {}
    for name in ("range_high", "range_low", "poc", "vah", "val"):
        lv = _level("BALANCE_" + name.upper(), "BALANCE_" + name.upper(), bal.get(name), bal.get(name), bal,
                    sid, symbol, close, atr, cutoff, bal.get("volume_basis"))
        if lv:
            out.append(lv)
    for family, fam in (fabio.get("families") or {}).items():
        loc = (fam.get("gates") or {}).get("location") or {}
        price = loc.get("lvn_price", loc.get("nearest_lvn_price"))
        times = [_timestamp(t) for t in (loc.get("known_at") or loc.get("touch_known_at"), fam.get("state_known_at"), bal.get("known_at")) if t is not None]
        rec = dict(loc, known_at=iso_utc(max(times)) if times and all(t is not None for t in times) else None)
        lv = _level(f"{family}_LVN", "LVN", price, price, rec, sid, symbol, close, atr, cutoff, bal.get("volume_basis"))
        if lv:
            out.append(lv)
    for window in market.get("reference_windows", []):
        if window.get("lifecycle") != "COMPLETED":
            continue
        for name in ("high", "low"):
            key = window["window_id"] + ":" + window["local_date"] + ":" + name
            lv = _level(key, "REFERENCE_WINDOW_" + name.upper(), window.get(name), window.get(name), window,
                        sid, symbol, close, atr, cutoff, window.get("definition_basis"))
            if lv:
                out.append(lv)
    return out


def _scenario(subject, *, candidate, snap, symbol, direction, metadata, close, atr, levels, h1_refs):
    side, sid = subject.get("side"), snap["snapshot_id"]
    ident = subject.get("candidate_id") if candidate else subject.get("episode_id")
    edge = (subject.get("zone") or {}).get("U" if side == "LONG" else "D") if candidate else subject.get("U" if side == "LONG" else "D")
    edge, delta = number(edge), number(subject.get("delta"))
    low, high = (edge - delta, edge + delta) if edge is not None and delta is not None and delta >= 0 else (None, None)
    source_known = subject.get("ready_at") if candidate else subject.get("breakout_available_at")
    source_usable = _known(source_known, parse_utc(snap["as_of_utc"]))
    if not source_usable:
        low, high = None, None
    invalidation = {"operator": "closed_M5_below" if side == "LONG" else "closed_M5_above",
                    "level": low if side == "LONG" else high, "timeframe": "M5",
                    "source_ref": {"snapshot_id": sid, "symbol": symbol, "artifact_kind": "A_CANDIDATE" if candidate else "A_EPISODE",
                                   "record_key": ident, "available_at": source_known}}
    zone = {"level_id": "FROZEN_A:" + str(ident), "kind": "FROZEN_A", "low": low, "high": high,
            "basis": "EXACT_FROZEN_A_ANCHOR", "known_at": invalidation["source_ref"]["available_at"],
            "source_refs": [invalidation["source_ref"]], "quality": "SOURCE_LABEL_PRESERVED" if source_usable else "UNKNOWN",
            "is_developing": False, **zone_distance(low, high, close, atr)}
    status = alignment(direction, side) if source_usable else "UNKNOWN"
    targets = []
    if close is not None and side in ("LONG", "SHORT"):
        sign = 1 if side == "LONG" else -1
        for level in levels:
            price = level["low"] if side == "LONG" else level["high"]
            if sign * (price - close) > 0:
                targets.append({"level_id": level["level_id"], "price": price, "distance_price": abs(price - close),
                                "source_refs": deepcopy(level["source_refs"]), "input_refs": deepcopy(level.get("input_refs", [])),
                                "known_at": level.get("known_at"), "is_tp": False})
    targets.sort(key=lambda t: (t["distance_price"], t["level_id"]))
    return {"scenario_id": f"{sid}:A:{ident}", "snapshot_id": sid, "view": "SNAPSHOT_AS_OF",
            "candidate_ref": subject.get("candidate_id") if candidate else None,
            "context_cutoff": snap["as_of_utc"], "baseline_decision_at": subject.get("ready_at") if candidate else None,
            "decision_context_is_separate": True,
            "episode_ref": subject.get("episode_id"), "preferred_side": side,
            "context_status": status, "summary_basis": "H1_DIRECTION_ONLY",
            "premise_refs": [deepcopy(invalidation["source_ref"])],
            "supporting_refs": deepcopy(h1_refs) if status == "SUPPORTS" else [],
            "contradicting_refs": deepcopy(h1_refs) if status == "CONTRADICTS" else [],
            "neutral_refs": deepcopy(h1_refs) if status in ("NEUTRAL", "UNKNOWN") else [],
            "frozen_zone": zone, "refuting_condition": invalidation, "opposite_scenario_creates_trade": False,
            "plan": deepcopy(subject.get("plan")) if candidate else None,
            "plan_ref": subject.get("candidate_id") if candidate else None,
            "baseline_status": deepcopy(subject.get("branch_eligibility")) if candidate else None,
            "execution_safety_status": deepcopy(subject.get("execution_status")),
            "plan_window": deepcopy(subject.get("plan_window")), "entry_deadline_at": subject.get("entry_deadline_at"),
            "expires_at": subject.get("expires_at"), "lifecycle": subject.get("lifecycle") if candidate else subject.get("state_at_as_of", subject.get("state")),
            "exposure": exposure(metadata, side), "reference_targets": targets, "is_inference": True,
            "trigger": "UNCHANGED_A_RULES" if candidate else "WAIT_FOR_FROZEN_ZONE_RETEST_AND_LATER_CLOSED_M5_RESPONSE",
            "missing": [] if low is not None else [{"field": "frozen_zone", "reason": "A_SOURCE_LEVEL_OR_KNOWN_TIME_UNUSABLE"}]}


def _item_state(record):
    explicit = record.get("item_state")
    if explicit in ("OK", "UNKNOWN", "TIMEOUT", "ERROR", "UNSUPPORTED"):
        return explicit
    if record.get("status") in ("TIMEOUT", "ERROR") or record.get("error"):
        return "TIMEOUT" if record.get("status") == "TIMEOUT" else "ERROR"
    if not record or record.get("status") in ("UNAVAILABLE", "DATA_UNAVAILABLE"):
        return "UNKNOWN"
    return "OK"


def _divergence(record, cutoff):
    if not record or record.get("status") != "OK":
        return deepcopy(record)
    if record.get("pivots_confirmed_only") is not True:
        return {"status": "UNKNOWN", "reason": "PIVOT_CONFIRMATION_MISSING"}
    out = deepcopy(record)
    for kind in ("high", "low"):
        pivot = out.get(kind) or {}
        if pivot.get("class") and not _known(pivot.get("pivot_known_at"), cutoff):
            out[kind] = {"status": "UNKNOWN", "reason": "PIVOT_NOT_KNOWN_AT_CUTOFF"}
    return out


def build_evening_context(snap, markets, fabio=None):
    """One deterministic per-symbol overlay from supplied artifacts; never loads another snapshot/source."""
    cutoff, sid = parse_utc(snap["as_of_utc"]), snap["snapshot_id"]
    out = {}
    for symbol in snap["universe"]:
        market, fr = markets.get(symbol) or {}, (fabio or {}).get(symbol) or {}
        for rec, kind in ((market, "MARKET"), (fr, "FABIO")):
            if rec and rec.get("snapshot_id") is not None and rec["snapshot_id"] != sid:
                raise DataVersionMismatch(f"EVENING_SNAPSHOT_MISMATCH:{kind}:{symbol}")
            if rec.get("symbol") is not None and rec["symbol"] != symbol:
                raise DataVersionMismatch(f"EVENING_SYMBOL_MISMATCH:{kind}:{symbol}")
            if rec.get("as_of") is not None and _timestamp(rec["as_of"]) != cutoff:
                raise DataVersionMismatch(f"EVENING_CUTOFF_MISMATCH:{kind}:{symbol}")
        price = market.get("price_reference") or {}
        close = number(price.get("close")) if (price.get("kind") == "LAST_CLOSED_M5" and price.get("quality") == "OK" and
                _known(price.get("available_at"), cutoff) and _known(price.get("bar_close_at"), cutoff)) else None
        features = _features(market)
        atr = _feature_value(features.get(("atr14_wilder", "M5")), cutoff)
        direction = direction_context(market, cutoff)
        h1_refs = [_source(sid, symbol, "MARKET_FEATURE", name + ":H1", features[(name, "H1")]) for name in
                   ("h1_close_minus_ema50_over_atr", "h1_ema50_slope_over_atr") if (name, "H1") in features]
        metadata = market.get("asset_metadata") or {"asset_class": "UNKNOWN_ASSET_CLASS"}
        levels = _levels(snap, symbol, market, fr, close, atr, cutoff)
        _distance_provenance(levels, price, features.get(("atr14_wilder", "M5")), sid, symbol)
        subjects = [(c, True) for c in snap.get("candidates", []) if c.get("symbol") == symbol and c.get("setup") == "A"]
        subjects += [(e, False) for e in snap.get("episodes", []) if e.get("symbol") == symbol and
                     e.get("state_at_as_of", e.get("state")) == "WATCHING_RETEST"]
        scenarios = [_scenario(s, candidate=c, snap=snap, symbol=symbol, direction=direction, metadata=metadata,
                               close=close, atr=atr, levels=levels, h1_refs=h1_refs) for s, c in subjects]
        _distance_provenance([s["frozen_zone"] for s in scenarios], price, features.get(("atr14_wilder", "M5")), sid, symbol)
        evidence = []
        for (name, tf), feature in features.items():
            if name == "news_calendar":
                continue
            record = deepcopy(feature)
            if not _known(feature.get("known_at") or feature.get("available_at"), cutoff) or feature.get("provisional"):
                record.update(value=None, quality="UNKNOWN", reason="NOT_CLOSED_AND_KNOWN_AT_CUTOFF")
            evidence.append({"evidence_id": f"{name}:{tf}", "kind": "PRICE_DERIVED_FEATURE",
                             "record": record, "source_refs": [_source(sid, symbol, "MARKET_FEATURE", f"{name}:{tf}", feature)],
                             "item_state": "OK" if _feature_value(feature, cutoff) is not None else "UNKNOWN"})
        external_flow = bool((fr.get("capabilities_used") or {}).get("external_flow")) or fr.get("route") == "FTMO_EXTERNAL_FLOW"
        flow = {"status": "UNSUPPORTED", "reason": "MT5_ONLY_NO_EXTERNAL_FLOW"} if external_flow else deepcopy(fr.get("flow"))
        if flow:
            evidence.append({"evidence_id": "MT5_FLOW", "kind": "MT5_FLOW", "record": flow,
                             "item_state": "UNSUPPORTED" if external_flow else "OK" if flow.get("status") in ("OK", "USABLE") else "UNKNOWN",
                             "source_refs": [_source(sid, symbol, "FABIO", "flow", fr)],
                             "interpretation": "FEED_TICK_ACTIVITY_NOT_MARKET_MONEY_FLOW" if flow.get("is_proxy") else "BROKER_SOURCE_ONLY_NOT_WHOLE_MARKET"})
        missing = []
        if close is None:
            missing.append({"field": "price_reference", "reason": "CLOSED_M5_PRICE_UNAVAILABLE", "source_ref": None})
        if direction == "UNKNOWN":
            missing.append({"field": "direction_context", "reason": "H1_FEATURES_UNUSABLE", "source_ref": None})
        items = {"market": _item_state(market), "fabio": _item_state(fr)}
        items.update({r["window_id"]: r.get("item_state", "UNKNOWN") for r in market.get("reference_windows", [])})
        state = "PARTIAL_FAILED" if any(s in ("ERROR", "TIMEOUT") for s in items.values()) else "COMPLETE"
        out[symbol] = {"overlay_version": VERSION, "snapshot_id": sid, "symbol": symbol, "as_of": snap["as_of_utc"],
                       "view": "SNAPSHOT_AS_OF", "subject": {"symbol": symbol, "candidate_id": None, "episode_id": None},
                       "context_state": state, "item_states": items, "context_status": "UNKNOWN", "context_status_reason": "NO_A_SIDE_AT_MARKET_ROOT",
                       "summary_basis": "H1_DIRECTION_ONLY", "direction_context": direction, "price_reference": deepcopy(price),
                       "evidence": evidence, "levels": [s["frozen_zone"] for s in scenarios] + levels, "scenarios": scenarios,
                       "value_location": value_location(close, fr.get("balance") or {}, cutoff),
                       "reference_windows": deepcopy(market.get("reference_windows", [])),
                       "relative_movement": deepcopy(market.get("relative_movement", {})), "asset_metadata": deepcopy(metadata),
                       "flow": flow, "divergence_context": None if external_flow else _divergence(fr.get("divergence_context"), cutoff), "missing": missing,
                       "news_handling": "USER_MANAGED", "news_checked_by_system": False,
                       "win_probability": None, "win_probability_reason": "NOT_CALIBRATED_NO_VOTES_OR_CONFIDENCE_SCORE",
                       "changes_baseline": False, "broker_order": False}
    return _clean(out)


def build_currency_strength(evening, universe):
    """Equal mean signed normalized movement; partial expected baskets are never ranked."""
    baskets, seen, metadata_missing = {}, set(), []
    for symbol in universe:
        meta = (evening.get(symbol) or {}).get("asset_metadata") or {}
        valid_fx = (meta.get("asset_class") == "FX" and meta.get("base_currency") in FIAT and meta.get("quote_currency") in FIAT)
        if meta.get("asset_class") == "UNKNOWN_ASSET_CLASS" or not meta.get("asset_class") or (meta.get("asset_class") == "FX" and not valid_fx):
            metadata_missing.append(symbol)
        if not valid_fx:
            continue
        native = meta.get("native_symbol") or symbol
        if native in seen:
            continue
        seen.add(native)
        for currency, sign in ((meta["base_currency"], 1), (meta["quote_currency"], -1)):
            baskets.setdefault(currency, []).append((symbol, sign))
    basket_id = hash_obj({"version": VERSION, "universe": list(universe), "baskets": baskets})
    out = {}
    for currency, constituents in baskets.items():
        out[currency] = {}
        for hours in ("1", "4"):
            observations, refs, missing, anchors, known_times = [], [], [], set(), []
            for symbol, sign in constituents:
                rec = ((evening.get(symbol) or {}).get("relative_movement") or {}).get(hours) or {}
                value = number(rec.get("value"))
                known = _timestamp(rec.get("known_at"))
                if rec.get("quality") != "OK" or value is None or not rec.get("T") or not rec.get("start") or known is None:
                    missing.append(symbol)
                else:
                    observations.append((symbol, sign * value))
                    refs.extend(deepcopy(rec.get("input_refs", [])))
                    anchors.add((rec["T"], rec["start"]))
                    known_times.append(known)
            complete = bool(observations) and not missing and not metadata_missing and len(anchors) == 1
            observed = sum(v for _, v in observations) / len(observations) if observations else None
            out[currency][hours] = {"currency": currency, "horizon_hours": int(hours), "method_version": VERSION,
                "basket_id": basket_id, "basis": "EQUAL_MEAN_SIGNED_FX_MOVEMENT_PROXY", "quality": "OK" if complete else "PARTIAL",
                "expected_constituents": [s for s, _ in constituents], "used_constituents": [s for s, _ in observations],
                "missing_constituents": missing, "unclassified_universe_members": list(metadata_missing),
                "count": len(observations), "coverage": len(observations) / len(constituents),
                "T": next(iter(anchors))[0] if len(anchors) == 1 else None,
                "start": next(iter(anchors))[1] if len(anchors) == 1 else None,
                "mean_observed": observed, "comparable_value": observed if complete else None,
                "rank": None, "input_refs": refs, "known_at": iso_utc(max(known_times)) if known_times else None,
                "narrow_basket": len(constituents) == 1}
    for hours in ("1", "4"):
        comparable = [rows[hours] for rows in out.values() if rows[hours]["comparable_value"] is not None]
        anchors = {(r["T"], r["start"]) for r in comparable}
        if len(anchors) == 1:
            for row in comparable:
                row["rank"] = 1 + sum(r["comparable_value"] > row["comparable_value"] for r in comparable)
    return _clean(out)
