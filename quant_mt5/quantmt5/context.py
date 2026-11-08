"""Context for the brainstorm step: core + question-driven feature groups, all from bars available at decision time.

Every value is a feature_record (value/unit/tf/window/seed/available_at/source/quality). Missing → UNKNOWN + reason.
Indicators describe context; they are not gates and carry no win probability.
"""
from __future__ import annotations

import datetime as dt
import math
from typing import Any

import numpy as np

from .config import strategy
from .detectors import load_symbol
from .execution import next_session_end
from .features import (SeriesCache, efficiency_ratio, feature_record, geometry, index_at_or_before,
                       percentile_rank_past)
from .snapshot import load_snapshot
from .timemap import NY, UTC
from .util import iso_utc, parse_utc

CORE = ("atr", "volume", "geometry", "levels", "cost", "time")
OPTIONAL = ("ema", "adx", "rsi", "er", "atr_pct")


def check_snapshot_config(snap: dict) -> None:
    """A snapshot is read only under the config it was taken with: same bundle (B6B) and same config hash.
    Never falls back to the current/default config."""
    from .config import bundle_identity, config_hash
    from .data import DataVersionMismatch
    want = (snap.get("config_bundle") or {}).get("bundle_id")
    have = bundle_identity()["bundle_id"]
    if want != have:
        raise DataVersionMismatch(f"CONFIG_BUNDLE_MISMATCH: snapshot taken with {want} "
                                  f"({(snap.get('config_bundle') or {}).get('config_dir', 'repository config')}), process uses {have}")
    if snap.get("config_hash") and snap["config_hash"] != config_hash():
        raise DataVersionMismatch("CONFIG_VERSION_MISMATCH: config content differs from the snapshot's config_hash")


def snapshot_pins(snap: dict, symbol: str) -> dict | None:
    """Data versions the snapshot consumed for `symbol`. Snapshots without pins are accepted only while the current
    dataset manifest hash still equals the recorded one; otherwise fail closed (DATA_VERSION_MISMATCH)."""
    from .data import DataVersionMismatch, dataset_manifest, load_registry
    from .util import hash_obj
    check_snapshot_config(snap)
    if "data_versions" in snap:
        v = snap["data_versions"].get(symbol)
        if v is None or v.get("status") == "ERROR":
            raise DataVersionMismatch(f"DATA_VERSION_MISMATCH:{symbol}: snapshot has no usable pinned version")
        return v
    from . import detectors
    if hash_obj(dataset_manifest(detectors.load_registry())) != snap.get("dataset_manifest_hash"):
        raise DataVersionMismatch("DATA_VERSION_MISMATCH: unpinned snapshot and the dataset manifest changed since it was taken")
    return None


def find_candidate(snap: dict, candidate_id: str) -> dict:
    for c in snap["candidates"]:
        if c["candidate_id"] == candidate_id:
            return c
    raise KeyError(f"CANDIDATE_NOT_IN_SNAPSHOT:{candidate_id}")


def build_context(snapshot_id: str, candidate_id: str, groups: list[str] | None = None, at: str = "decision") -> dict:
    snap = load_snapshot(snapshot_id)
    cand = find_candidate(snap, candidate_id)
    as_of = parse_utc(snap["as_of_utc"])
    decision = float(cand["ready_ts"]) if at == "decision" else as_of
    if decision > as_of:
        raise ValueError("DECISION_AFTER_SNAPSHOT_AS_OF")
    sd = load_symbol(cand["symbol"], cut_available_at=decision, pins=snapshot_pins(snap, cand["symbol"]))
    groups = list(CORE) + [g for g in (groups or []) if g in OPTIONAL]
    m5, h1 = sd.m5, sd.h1
    c5, ch = SeriesCache(m5), SeriesCache(h1)
    i5 = index_at_or_before(m5, decision)
    ih = index_at_or_before(h1, decision)
    feats: list[dict] = []
    atr5, atrh = c5.get("atr14"), ch.get("atr14")
    sig_open = parse_utc(cand["signal_bar"]["open_at"])
    if at == "decision":
        sig_i = i5  # the signal bar is the last available M5 at decision time
        if m5.open_at[sig_i] != sig_open:
            raise ValueError("SIGNAL_BAR_NOT_LAST_AT_DECISION")
    else:
        # as_of view: market state is the last closed bar at as_of; signal-bar features stay on the candidate's own bar
        hits = np.flatnonzero(m5.open_at[: i5 + 1] == sig_open)
        if not len(hits):
            raise ValueError("SIGNAL_BAR_NOT_IN_AS_OF_VIEW")
        sig_i = int(hits[-1])
    vb = "tick"
    if "atr" in groups:
        feats.append(feature_record("atr14_wilder", float(atr5[i5]), b=m5, i=i5, unit="price", window="14 bars, seed SMA14 at dataset start"))
        if ih >= 0:
            feats.append(feature_record("atr14_wilder", float(atrh[ih]), b=h1, i=ih, unit="price", window="14 bars"))
        feats.append(feature_record("atr_frozen_for_setup", cand.get("atr_frozen"), b=m5, i=i5, unit="price",
                                    window="frozen at anchor (A) / before mother bar (B)"))
    if "volume" in groups:
        rv = c5.get("rvol20")
        feats.append(feature_record("tick_volume", int(m5.tick_volume[sig_i]), b=m5, i=sig_i, unit="ticks (price changes)", window="signal bar", volume_basis=vb))
        feats.append(feature_record("rvol20_tick", float(rv[sig_i]), b=m5, i=sig_i, unit="ratio", window="vol / median(previous 20 closed bars)", volume_basis=vb))
        rs, cnt = c5.get("rvol_slot")
        feats.append(feature_record("rvol_same_slot_tick", float(rs[sig_i]), b=m5, i=sig_i, unit="ratio",
                                    window="vol / median(same America/New_York minute-of-day, previous 20 occurrences, min 10)",
                                    volume_basis=vb, extra={"sample_count": int(cnt[sig_i]), "slot_tz": "America/New_York (IANA, DST-aware)",
                                                            "time_basis": _time_label(m5)}))
        feats.append({"name": "real_volume", "value": None, "quality": "UNKNOWN", "reason": "REAL_VOLUME_UNAVAILABLE (all zero in source; not treated as zero activity)",
                      "volume_basis": "unavailable", "tf": "M5", "symbol": sd.symbol})
        if cand["setup"] == "A":
            bo = _index_of_open(m5, cand, "breakout")
            if bo is not None:
                feats.append(feature_record("rvol20_tick_breakout_bar", float(rv[bo]), b=m5, i=bo, unit="ratio", window="breakout bar", volume_basis=vb))
                feats.append(feature_record("tick_volume_retest_over_breakout", float(m5.tick_volume[sig_i]) / max(1.0, float(m5.tick_volume[bo])),
                                            b=m5, i=sig_i, unit="ratio", window="signal bar vs breakout bar", volume_basis=vb))
        else:
            mi = sig_i - 2
            feats.append(feature_record("rvol20_tick_mother_bar", float(rv[mi]), b=m5, i=mi, unit="ratio", window="mother bar", volume_basis=vb))
    if "geometry" in groups:
        a = float(atr5[i5])
        g = geometry(m5.o[sig_i], m5.h[sig_i], m5.l[sig_i], m5.c[sig_i], cand.get("atr_frozen") or a)
        for k, v in g.items():
            if k == "geometry_status":
                continue
            feats.append(feature_record(f"signal_{k}", v, b=m5, i=sig_i, unit="price" if k == "range" else "ratio", window="signal bar; *_over_atr uses frozen ATR"))
        if cand["setup"] == "A":
            feats.append(feature_record("retest_depth_over_atr", cand.get("retest_depth_over_atr"), b=m5, i=sig_i, unit="ATR", window="zone edge - retest extreme"))
            bo = _index_of_open(m5, cand, "breakout")
            if bo is not None:
                gb = geometry(m5.o[bo], m5.h[bo], m5.l[bo], m5.c[bo], cand["atr_frozen"])
                feats.append(feature_record("breakout_body_over_range", gb["body_over_range"], b=m5, i=bo, unit="ratio", window="breakout bar"))
                feats.append(feature_record("breakout_close_beyond_edge_over_atr",
                                            ((m5.c[bo] - cand["zone"]["U"]) if cand["side"] == "LONG" else (cand["zone"]["D"] - m5.c[bo])) / cand["atr_frozen"],
                                            b=m5, i=bo, unit="ATR", window="breakout bar"))
                feats.append(feature_record("episode_age_min", (m5.close_at[sig_i] - m5.close_at[bo]) / 60, b=m5, i=sig_i, unit="minutes", window="breakout close → signal close"))
        else:
            feats.append(feature_record("overshoot_over_atr", cand.get("overshoot_over_atr"), b=m5, i=sig_i, unit="ATR", window="beyond mother extreme"))
            feats.append(feature_record("reclaim_over_atr", cand.get("reclaim_over_atr"), b=m5, i=sig_i, unit="ATR", window="close back inside mother"))
    if "levels" in groups:
        a = cand.get("atr_frozen") or float(atr5[i5])
        lvl = cand.get("level")
        if cand["setup"] == "B":
            p1 = cand["gates"].get("P1", {})
            lvl = p1.get("PDL") if cand["side"] == "LONG" else p1.get("PDH")
            if lvl is not None:
                feats.append(feature_record("distance_close_to_prev_day_level_over_atr", abs(m5.c[sig_i] - lvl) / a, b=m5, i=sig_i, unit="ATR",
                                            window="prev broker D1 high/low"))
            opp = p1.get("PDH") if cand["side"] == "LONG" else p1.get("PDL")
            if opp is not None:
                feats.append(feature_record("distance_to_opposite_prev_day_level_over_atr", abs(opp - m5.c[sig_i]) / a, b=m5, i=sig_i, unit="ATR",
                                            window="known obstacle on the path to target"))
        else:
            feats.append(feature_record("distance_close_to_zone_edge_over_atr", abs(m5.c[sig_i] - lvl) / a, b=m5, i=sig_i, unit="ATR", window="frozen zone edge"))
            zw = (cand["zone"]["U"] - cand["zone"]["D"]) / a
            feats.append(feature_record("zone_width_over_atr", zw, b=m5, i=sig_i, unit="ATR", window="8 H1 range"))
    if "cost" in groups:
        pt = float(sd.prof["point"])
        a = cand.get("atr_frozen") or float(atr5[i5])
        feats.append(feature_record("bar_spread_field_over_atr", float(m5.spread[sig_i]) * pt / a, b=m5, i=sig_i, unit="ATR",
                                    window="signal bar spread field (bar MINIMUM spread, not a live quote)", quality="OK",
                                    extra={"caveat": "ASK_MISSING: proxy only"}))
        plan = cand.get("plan", {})
        if plan.get("spread_over_R") is not None and plan.get("state") == "FILLED_SIMULATED" and decision >= parse_utc(plan["fill_at"]):
            feats.append({"name": "spread_over_R_at_simulated_entry", "value": plan["spread_over_R"], "quality": "OK", "unit": "ratio",
                          "available_at": plan["fill_at"], "symbol": sd.symbol, "tf": "M1_OPEN_PROXY"})
    if "time" in groups:
        ny = dt.datetime.fromtimestamp(decision, UTC).astimezone(NY)
        nse = next_session_end(decision, sd.prof.get("session") or {})
        feats.append({"name": "decision_time_ny", "value": ny.strftime("%Y-%m-%d %H:%M %Z"), "quality": "OK", "unit": "time",
                      "available_at": iso_utc(decision), "time_basis": _time_label(m5), "symbol": sd.symbol})
        feats.append({"name": "minutes_to_session_end", "value": None if nse is None else (nse - decision) / 60,
                      "quality": "OK" if nse else "UNKNOWN", "unit": "minutes", "available_at": iso_utc(decision),
                      "reason": None if nse else "SESSION_SCHEDULE_UNKNOWN", "symbol": sd.symbol})
        feats.append({"name": "news_calendar", "value": None, "quality": "UNKNOWN", "reason": "NEWS_UNKNOWN (no point-in-time calendar exported)",
                      "symbol": sd.symbol})
    if "ema" in groups and ih >= 0:
        e50, e20 = ch.get("ema50"), ch.get("ema20")
        ok = ih >= 249 and math.isfinite(e50[ih]) and ih >= 3 and math.isfinite(atrh[ih])
        slope = (e50[ih] - e50[ih - 3]) / (3 * atrh[ih]) if ok else float("nan")
        feats.append(feature_record("h1_close_minus_ema50_over_atr", (h1.c[ih] - e50[ih]) / atrh[ih] if ok else float("nan"), b=h1, i=ih, unit="ATR(H1)", window="EMA50 seed SMA50"))
        feats.append(feature_record("h1_ema50_slope_over_atr", slope, b=h1, i=ih, unit="ATR(H1)/bar", window="(EMA_t-EMA_t-3)/(3*ATR_t)"))
        feats.append(feature_record("h1_ema20", float(e20[ih]), b=h1, i=ih, unit="price", window="EMA20 seed SMA20"))
    if "adx" in groups and ih >= 0:
        adx, pdi, ndi = ch.get("adx14")
        feats.append(feature_record("h1_adx14_wilder", float(adx[ih]), b=h1, i=ih, unit="index", window="ADX_Wilder 14 (project implementation, not MT5 native)"))
        feats.append(feature_record("h1_plus_di", float(pdi[ih]), b=h1, i=ih, unit="index", window="14"))
        feats.append(feature_record("h1_minus_di", float(ndi[ih]), b=h1, i=ih, unit="index", window="14"))
    if "rsi" in groups:
        feats.append(feature_record("m5_rsi14_wilder", float(c5.get("rsi14")[i5]), b=m5, i=i5, unit="index", window="RSI Wilder 14"))
        if ih >= 0:
            feats.append(feature_record("h1_rsi14_wilder", float(ch.get("rsi14")[ih]), b=h1, i=ih, unit="index", window="RSI Wilder 14"))
    if "er" in groups:
        v, why = efficiency_ratio(m5.c, i5, 20)
        feats.append(feature_record("m5_efficiency_ratio20", v, b=m5, i=i5, unit="ratio", window="n=20", reason=None if why == "OK" else why))
        if ih >= 0:
            v, why = efficiency_ratio(h1.c, ih, 20)
            feats.append(feature_record("h1_efficiency_ratio20", v, b=h1, i=ih, unit="ratio", window="n=20", reason=None if why == "OK" else why))
    if "atr_pct" in groups:
        v, nobs = percentile_rank_past(atr5, i5, 1000, 200)
        feats.append(feature_record("m5_atr_percentile_past1000", v, b=m5, i=i5, unit="percentile", window="past 1000 bars, min 200",
                                    extra={"sample_count": nobs}))
    leak = [f for f in feats if f.get("available_at_ts") is not None and f["available_at_ts"] > decision]
    return {"snapshot_id": snapshot_id, "candidate_id": candidate_id, "symbol": sd.symbol, "setup": cand["setup"], "side": cand["side"],
            "decision_at": iso_utc(decision), "decision_basis": at, "groups": groups, "features": feats,
            "feature_time_basis": {"signal_bar_features": "candidate signal bar " + iso_utc(sig_open),
                                   "market_state_features": "last closed bar at " + iso_utc(decision) + (" (decision)" if at == "decision" else " (snapshot as_of)"),
                                   "bars_after_signal": int(i5 - sig_i)},
            "causality_check": {"features_after_decision": len(leak), "ok": not leak},
            "baseline_eligibility": cand["branch_eligibility"], "plan": cand["plan"],
            "interpretation_rules": ["tick volume = price-change count, not traded contracts", "indicators are context, not gates",
                                     "no order-flow/delta/absorption inferred from candles or tick volume"]}


def build_market_context(snapshot_id: str, symbol: str, groups: list[str] | None = None) -> dict:
    """Symbol-level context at the snapshot as_of (no candidate needed): the same data an agent reads before or
    alongside a setup. Only bars with available_at <= as_of; the running bar is reported separately as PROVISIONAL."""
    from .data import provisional_bar
    from .evening_context import asset_metadata, price_reference, reference_windows, relative_movement
    snap = load_snapshot(snapshot_id)
    if symbol not in snap["universe"]:
        raise KeyError(f"SYMBOL_NOT_IN_SNAPSHOT:{symbol}")
    as_of = parse_utc(snap["as_of_utc"])
    sd = load_symbol(symbol, cut_available_at=as_of, pins=snapshot_pins(snap, symbol))
    groups = list(CORE) + [g for g in (groups or []) if g in OPTIONAL]
    m5, h1, d1 = sd.m5, sd.h1, sd.d1
    c5, ch = sd.cache_m5, sd.cache_h1
    i5, ih, idd = len(m5) - 1, len(h1) - 1, len(d1) - 1
    if i5 < 0:
        raise ValueError("NO_BARS_AVAILABLE_AT_AS_OF")
    atr5, atrh = c5.get("atr14"), ch.get("atr14")
    a = float(atr5[i5]) if math.isfinite(atr5[i5]) else None
    feats: list[dict] = []
    if "atr" in groups:
        feats.append(feature_record("atr14_wilder", float(atr5[i5]), b=m5, i=i5, unit="price", window="14 bars, seed SMA14 at dataset start"))
        if ih >= 0:
            feats.append(feature_record("atr14_wilder", float(atrh[ih]), b=h1, i=ih, unit="price", window="14 bars"))
    if "volume" in groups:
        rv = c5.get("rvol20")
        feats.append(feature_record("tick_volume", int(m5.tick_volume[i5]), b=m5, i=i5, unit="ticks (price changes)", window="last closed bar", volume_basis="tick"))
        feats.append(feature_record("rvol20_tick", float(rv[i5]), b=m5, i=i5, unit="ratio", window="vol / median(previous 20 closed bars)",
                                    volume_basis="tick", sample_count=min(20, i5)))
        rs, cnt = c5.get("rvol_slot")
        feats.append(feature_record("rvol_same_slot_tick", float(rs[i5]), b=m5, i=i5, unit="ratio",
                                    window="same America/New_York minute-of-day, previous 20 occurrences, min 10", volume_basis="tick",
                                    sample_count=int(cnt[i5]), extra={"slot_tz": "America/New_York (IANA)", "time_basis": _time_label(m5)}))
        feats.append({"name": "real_volume", "value": None, "quality": "UNKNOWN", "volume_basis": "unavailable", "tf": "M5", "symbol": symbol,
                      "reason": "REAL_VOLUME_UNAVAILABLE (all zero in source; not treated as zero activity)"})
    if "geometry" in groups:
        for k, v in geometry(m5.o[i5], m5.h[i5], m5.l[i5], m5.c[i5], a).items():
            if k != "geometry_status":
                feats.append(feature_record(f"last_bar_{k}", v, b=m5, i=i5, unit="price" if k == "range" else "ratio", window="last closed M5"))
    if "levels" in groups and a:
        if idd >= 0:
            pdh, pdl = float(d1.h[idd]), float(d1.l[idd])
            feats.append(feature_record("distance_close_to_prev_day_high_over_atr", abs(m5.c[i5] - pdh) / a, b=m5, i=i5, unit="ATR",
                                        window=f"last completed broker D1 ({d1.status(idd, as_of)}, {d1.provenance.get('kind')})",
                                        extra={"level": pdh, "level_bar_close_at": iso_utc(d1.close_at[idd]),
                                               "level_known_at": iso_utc(float(np.max(d1.available_at[:idd + 1]))), "level_source": d1.provenance}))
            feats.append(feature_record("distance_close_to_prev_day_low_over_atr", abs(m5.c[i5] - pdl) / a, b=m5, i=i5, unit="ATR",
                                        window="last completed broker D1", extra={"level": pdl, "level_bar_close_at": iso_utc(d1.close_at[idd]),
                                        "level_known_at": iso_utc(float(np.max(d1.available_at[:idd + 1]))), "level_source": d1.provenance}))
        if ih >= 7:
            U, D = float(h1.h[ih - 7:ih + 1].max()), float(h1.l[ih - 7:ih + 1].min())
            feats.append(feature_record("distance_close_to_h1_8bar_high_over_atr", abs(m5.c[i5] - U) / a, b=m5, i=i5, unit="ATR",
                                        window="max high of last 8 closed H1 (descriptive; not the setup A anchor)", extra={"level": U,
                                        "level_known_at": iso_utc(float(np.max(h1.available_at[ih - 7:ih + 1]))), "level_source": h1.provenance}))
            feats.append(feature_record("distance_close_to_h1_8bar_low_over_atr", abs(m5.c[i5] - D) / a, b=m5, i=i5, unit="ATR",
                                        window="min low of last 8 closed H1", extra={"level": D,
                                        "level_known_at": iso_utc(float(np.max(h1.available_at[ih - 7:ih + 1]))), "level_source": h1.provenance}))
    if "cost" in groups:
        pt = float(sd.prof["point"])
        feats.append(feature_record("bar_spread_field_over_atr", (float(m5.spread[i5]) * pt / a) if a else float("nan"), b=m5, i=i5, unit="ATR",
                                    window="last closed bar spread field (bar MINIMUM spread)", extra={"caveat": "ASK_MISSING: proxy only"}))
        feats.append({"name": "spread_over_R", "value": None, "quality": "UNKNOWN", "reason": "NO_PLAN (symbol context has no entry/SL); see candidate context",
                      "symbol": symbol})
        feats.append({"name": "bar_watermark_age_s", "value": as_of - float(m5.close_at[i5]), "unit": "s", "quality": "OK",
                      "basis": "as_of - last closed M5 close (closed-bar delay, NOT a quote age)", "symbol": symbol, "available_at": snap["as_of_utc"]})
        qa = (snap.get("symbols") or {}).get(symbol) or {}
        feats.append({"name": "quote_age_s", "value": qa.get("quote_age_s"), "unit": "s",
                      "quality": "OK" if qa.get("quote_age_s") is not None else "UNKNOWN",
                      "reason": None if qa.get("quote_age_s") is not None else (qa.get("quote_age_status") or "UNKNOWN_NO_TICK_TAPE"),
                      "basis": qa.get("quote_age_basis") or "no pinned tick tape", "symbol": symbol, "available_at": snap["as_of_utc"]})
    if "time" in groups:
        ny = dt.datetime.fromtimestamp(as_of, UTC).astimezone(NY)
        sess = sd.prof.get("session") or {}
        nse = next_session_end(as_of, sess)
        from .coverage import scheduled_open
        feats.append({"name": "as_of_time_ny", "value": ny.strftime("%Y-%m-%d %H:%M %Z"), "quality": "OK", "unit": "time", "symbol": symbol,
                      "time_basis": _time_label(m5)})
        feats.append({"name": "scheduled_open_now", "value": bool(scheduled_open(np.array([int(as_of)]), sess)[0]) if sess else None,
                      "quality": "OK" if sess else "UNKNOWN", "reason": None if sess else "SESSION_SCHEDULE_UNKNOWN",
                      "schedule_status": sess.get("status"), "symbol": symbol})
        feats.append({"name": "minutes_to_session_end", "value": None if nse is None else (nse - as_of) / 60, "unit": "minutes",
                      "quality": "OK" if nse else "UNKNOWN", "reason": None if nse else "SESSION_SCHEDULE_UNKNOWN", "symbol": symbol})
        feats.append({"name": "news_calendar", "value": None, "quality": "UNKNOWN", "reason": "NEWS_UNKNOWN (no point-in-time calendar exported)", "symbol": symbol})
    # running bars: provisional, never compared with closed-bar RVOL
    prov = {}
    for tf, base in (("M5", sd.m1), ("H1", m5)):
        if base is None:
            prov[tf] = {"status": "UNKNOWN", "reason": "HISTORY_INSUFFICIENT:base timeframe missing"}
            continue
        pb = provisional_bar(base, tf, as_of)
        if pb is not None:
            pb["rvol"] = {"value": None, "quality": "UNKNOWN", "reason": "PROVISIONAL_BAR_NOT_COMPARABLE"}
        prov[tf] = pb or {"status": "NO_RUNNING_BAR", "reason": "latest bucket already closed at as_of"}
    _optional(feats, groups, m5, h1, c5, ch, i5, ih, atr5, atrh)
    for feature in feats:
        series = {"M5": m5, "H1": h1}.get(feature.get("tf"))
        index = feature.get("bar_index_from_seed")
        if series is not None and index is not None:
            known = float(np.max(series.available_at[:index + 1]))
            if feature.get("level_known_at"):
                known = max(known, parse_utc(feature["level_known_at"]))
            feature["known_at"] = iso_utc(known)
    leak = [f for f in feats if f.get("available_at_ts") is not None and f["available_at_ts"] > as_of]
    return {"snapshot_id": snapshot_id, "symbol": symbol, "as_of": snap["as_of_utc"], "groups": groups, "features": feats,
            "price_reference": price_reference(m5, as_of, snapshot_id, sd.prof.get("chart_basis", "UNKNOWN")),
            "reference_windows": reference_windows(m5, as_of, snapshot_id),
            "relative_movement": relative_movement(h1, as_of, snapshot_id, ch),
            "asset_metadata": asset_metadata(sd.prof),
            "provisional_bars": prov, "causality_check": {"features_after_as_of": len(leak), "ok": not leak},
            "hashes": {k: snap.get(k) for k in ("dataset_manifest_hash", "engine_hash", "config_hash")},
            "data_versions_consumed": {tf: (v or {}).get("content_hash") for tf, v in (snap.get("data_versions", {}).get(symbol) or {}).items()},
            "quality_flags": snap["symbols"][symbol].get("quality_flags"),
            "interpretation_rules": ["tick volume = price-change count, not traded contracts", "indicators are context, not gates",
                                     "PROVISIONAL bars are partial intervals; never compared to closed-bar volume"]}


def _optional(feats, groups, m5, h1, c5, ch, i5, ih, atr5, atrh):
    if "ema" in groups and ih >= 0:
        e50, e20 = ch.get("ema50"), ch.get("ema20")
        ok = ih >= 249 and math.isfinite(e50[ih]) and ih >= 3 and math.isfinite(atrh[ih])
        feats.append(feature_record("h1_close_minus_ema50_over_atr", (h1.c[ih] - e50[ih]) / atrh[ih] if ok else float("nan"), b=h1, i=ih, unit="ATR(H1)", window="EMA50"))
        feats.append(feature_record("h1_ema50_slope_over_atr", (e50[ih] - e50[ih - 3]) / (3 * atrh[ih]) if ok else float("nan"), b=h1, i=ih, unit="ATR(H1)/bar", window="3 bars"))
    if "adx" in groups and ih >= 0:
        adx, pdi, ndi = ch.get("adx14")
        feats.append(feature_record("h1_adx14_wilder", float(adx[ih]), b=h1, i=ih, unit="index", window="14"))
        feats.append(feature_record("h1_plus_di", float(pdi[ih]), b=h1, i=ih, unit="index", window="14"))
        feats.append(feature_record("h1_minus_di", float(ndi[ih]), b=h1, i=ih, unit="index", window="14"))
    if "rsi" in groups:
        feats.append(feature_record("m5_rsi14_wilder", float(c5.get("rsi14")[i5]), b=m5, i=i5, unit="index", window="14"))
    if "er" in groups:
        v, why = efficiency_ratio(m5.c, i5, 20)
        feats.append(feature_record("m5_efficiency_ratio20", v, b=m5, i=i5, unit="ratio", window="n=20", reason=None if why == "OK" else why))
    if "atr_pct" in groups:
        v, nobs = percentile_rank_past(atr5, i5, 1000, 200)
        feats.append(feature_record("m5_atr_percentile_past1000", v, b=m5, i=i5, unit="percentile", window="past 1000 bars, min 200", sample_count=nobs))


def _time_label(b) -> str:
    p = b.provenance
    return (f"clock_profile={p.get('clock_profile')} ({p.get('clock_profile_status')}); contract={p.get('time_contract')}; "
            f"status={p.get('time_basis_status')}; flags={','.join(p.get('time_quality_flags', []))}")


def _index_of_open(m5, cand: dict, which: str) -> int | None:
    # breakout bar open time is stored on the episode; candidate keeps breakout_close_at
    t = parse_utc(cand["breakout_close_at"]) - 300
    i = int(np.searchsorted(m5.open_at, t, side="left"))
    if i < len(m5) and m5.open_at[i] == t:
        return i
    return None


def explain(snapshot_id: str, candidate_id: str) -> dict:
    snap = load_snapshot(snapshot_id)
    c = find_candidate(snap, candidate_id)
    sig = c["signal_bar"]
    conds = []
    if c["setup"] == "A":
        U, D, dl, e = c["zone"]["U"], c["zone"]["D"], c["delta"], c["epsilon"]
        if c["side"] == "LONG":
            conds += [("retest low within U±delta", f"{U - dl} <= {sig['l']} <= {U + dl}", U - dl <= sig["l"] <= U + dl),
                      ("close >= U+eps and bullish", f"{sig['c']} >= {U + e} and c>o", sig["c"] >= U + e and sig["c"] > sig["o"]),
                      ("close in upper half", f"2*(c-l)={2 * (sig['c'] - sig['l']):.5g} >= range={sig['h'] - sig['l']:.5g}", 2 * (sig["c"] - sig["l"]) >= sig["h"] - sig["l"])]
        else:
            conds += [("retest high within D±delta", f"{D - dl} <= {sig['h']} <= {D + dl}", D - dl <= sig["h"] <= D + dl),
                      ("close <= D-eps and bearish", f"{sig['c']} <= {D - e} and c<o", sig["c"] <= D - e and sig["c"] < sig["o"]),
                      ("close in lower half", f"2*(h-c)={2 * (sig['h'] - sig['c']):.5g} >= range={sig['h'] - sig['l']:.5g}", 2 * (sig["h"] - sig["c"]) >= sig["h"] - sig["l"])]
    else:
        M, I, F, e = c["mother_bar"], c["inside_bar"], sig, c["epsilon"]
        conds.append(("strict inside bar", f"H_I={I['h']} <= H_M-eps={M['h'] - e:.10g} and L_I={I['l']} >= L_M+eps={M['l'] + e:.10g}",
                      I["h"] <= M["h"] - e and I["l"] >= M["l"] + e))
        conds.append(("F opens inside mother", f"{M['l']} <= O_F={F['o']} <= {M['h']}", M["l"] <= F["o"] <= M["h"]))
        if c["side"] == "LONG":
            conds += [("F breaks below mother", f"L_F={F['l']} <= L_M-eps={M['l'] - e:.10g}", F["l"] <= M["l"] - e),
                      ("F does not break above mother", f"H_F={F['h']} <= H_M={M['h']}", F["h"] <= M["h"]),
                      ("F closes back inside, bullish", f"{M['l'] + e:.10g} <= C_F={F['c']} <= {M['h'] - e:.10g} and C>O", M["l"] + e <= F["c"] <= M["h"] - e and F["c"] > F["o"])]
        else:
            conds += [("F breaks above mother", f"H_F={F['h']} >= H_M+eps={M['h'] + e:.10g}", F["h"] >= M["h"] + e),
                      ("F does not break below mother", f"L_F={F['l']} >= L_M={M['l']}", F["l"] >= M["l"]),
                      ("F closes back inside, bearish", f"{M['l'] + e:.10g} <= C_F={F['c']} <= {M['h'] - e:.10g} and C<O", M["l"] + e <= F["c"] <= M["h"] - e and F["c"] < F["o"])]
        p1 = c["gates"].get("P1", {})
        if p1.get("PDL") is not None:
            lvl, dl = (p1["PDL"], c["delta"]) if c["side"] == "LONG" else (p1["PDH"], c["delta"])
            ext = M["l"] if c["side"] == "LONG" else M["h"]
            conds.append((f"P1 mother extreme within delta of {'PDL' if c['side'] == 'LONG' else 'PDH'}", f"|{ext}-{lvl}| <= {dl}", abs(ext - lvl) <= dl))
    return {"candidate_id": candidate_id, "snapshot_id": snapshot_id, "setup": c["setup"], "symbol": c["symbol"], "side": c["side"],
            "strategy_version": c["strategy_version"], "source_bars": {k: c[k] for k in ("mother_bar", "inside_bar", "signal_bar") if k in c},
            "frozen": {k: c.get(k) for k in ("level", "zone", "delta", "buffer", "atr_frozen", "epsilon", "atr_bar_close_at")},
            "conditions": [{"condition": a, "values": b, "pass": bool(p)} for a, b, p in conds],
            "gates": c["gates"], "plan": c["plan"], "plan_window": c.get("plan_window"), "episode_id": c.get("episode_id"),
            "revision_id": c.get("revision_id"), "lifecycle": c.get("lifecycle"), "entry_deadline_at": c.get("entry_deadline_at"),
            "candidate_quality_flags": c.get("quality_flags"), "execution_status": c.get("execution_status"),
            "episode": next(({k: e.get(k) for k in ("episode_id", "revision_id", "anchor_at", "activated_at", "U", "D", "h1_bars", "atr_frozen",
                                                     "atr_bar_close_at", "breakout_bar", "expires_at", "state", "transitions")}
                             for e in snap["episodes"] if e["episode_id"] == c.get("episode_id")), None),
            "evidence": "RESEARCH; strategy verdict per latest evaluate report; data HISTORICAL_EXPOSED" if "HISTORICAL_AS_OF" in
                        snap["symbols"][c["symbol"]].get("quality_flags", []) else "RESEARCH",
            "quality_flags": snap["symbols"][c["symbol"]].get("quality_flags")}


def opportunity_card(snapshot_id: str, candidate_id: str, notes_as_of: str | None = None) -> dict:
    """Immutable core (identity/why/baseline/context/evidence) comes from the snapshot; brainstorm notes are the
    append-only overlay for THIS snapshot, cut at `notes_as_of` (system recorded time) when given, so an earlier
    card can be rebuilt exactly. `notes_revision` identifies the note set shown."""
    from .notes import list_notes, note_effective_at
    from .util import hash_obj
    snap = load_snapshot(snapshot_id)
    try:
        cand = find_candidate(snap, candidate_id)
    except KeyError:
        raise KeyError("CANDIDATE_NOT_FOUND")

    as_of = snap["as_of_utc"]
    identity = {
        "symbol": cand["symbol"],
        "setup": cand["setup"],
        "side": cand["side"],
        "candidate_id": cand["candidate_id"],
        "revision_id": cand.get("revision_id"),
        "snapshot_id": snapshot_id,
        "as_of": as_of,
    }

    exp = explain(snapshot_id, candidate_id)
    why = {
        "conditions": exp.get("conditions", []),
        "source_bars": exp.get("source_bars", {}),
        "frozen": exp.get("frozen", {}),
    }
    if exp.get("episode"):
        why["episode"] = exp["episode"]

    plan_src = cand.get("plan") or {}
    plan_data = {
        "state": plan_src.get("state"),
        "reason": plan_src.get("reason"),
        "certification": plan_src.get("certification"),
        "entry_deadline_at": cand.get("entry_deadline_at") or plan_src.get("deadline_at"),
    }
    for k in ("entry", "sl", "tp"):
        if k in plan_src:
            plan_data[k] = plan_src[k]

    baseline = {
        "branch_eligibility": cand.get("branch_eligibility", {}),
        "plan": plan_data,
    }

    ctx = build_context(snapshot_id, candidate_id, groups=None, at="decision")
    context_features = ctx.get("features", [])

    cut = parse_utc(notes_as_of) if notes_as_of else None
    notes = [n for n in list_notes(candidate_id) if n.get("snapshot_id") == snapshot_id
             and (cut is None or note_effective_at(n) <= cut)]
    notes_revision = {"n_notes": len(notes), "note_ids_hash": hash_obj([n["note_id"] for n in notes])[:16],
                      "notes_as_of": notes_as_of or "CURRENT",
                      "last_recorded_at": max((n.get("recorded_at") or n.get("created_at") for n in notes), default=None)}

    sym_meta = snap.get("symbols", {}).get(cand["symbol"], {})
    q_flags = sym_meta.get("quality_flags", [])
    exposure = sym_meta.get("exposure", "")
    is_historical = "HISTORICAL_AS_OF" in q_flags or "HISTORICAL_EXPOSED" in exposure
    hist_prefix = "HISTORICAL_EXPOSED" if is_historical else "LIVE_SAMPLE"
    qm = plan_src.get("quote_model", "NO_QUOTE_MODEL")
    cert = plan_src.get("certification", "INDICATIVE")
    evidence_str = f"{hist_prefix}; quote_model={qm}; certification={cert}; chưa có bằng chứng lợi nhuận"

    return {
        "status": "OK",
        "identity": identity,
        "why": why,
        "baseline": baseline,
        "context": context_features,
        "brainstorm_notes": notes,
        "notes_revision": notes_revision,
        "evidence": evidence_str,
    }

