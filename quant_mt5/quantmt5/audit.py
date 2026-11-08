"""B0/B1 data audit: integrity, coverage, volume basis, spread-field semantics, price grid, clock evidence."""
from __future__ import annotations

import datetime as dt
from collections import Counter
from typing import Any

import numpy as np

from .data import Bars, aggregate, load_bars, load_registry
from .timemap import ATHENS, NY, UTC

WEEKEND_GAP_S = 36 * 3600


def integrity(b: Bars) -> dict[str, Any]:
    d = np.diff(b.open_raw)
    ohlc_bad = ~((b.l <= np.minimum(b.o, b.c)) & (b.h >= np.maximum(b.o, b.c)) & (b.h >= b.l) & (b.l > 0))
    finite_bad = ~(np.isfinite(b.o) & np.isfinite(b.h) & np.isfinite(b.l) & np.isfinite(b.c))
    tfs = b.tf_s
    gaps = d[d > tfs]
    intra = gaps[gaps < WEEKEND_GAP_S]
    return {
        "rows": int(len(b)),
        "first_raw": int(b.open_raw[0]), "last_raw": int(b.open_raw[-1]),
        "first_open_utc": _iso(b.open_at[0]), "last_close_utc": _iso(b.close_at[-1]),
        "strictly_increasing": bool((d > 0).all()),
        "duplicates": int((d == 0).sum()),
        "misaligned_to_tf": int((b.open_raw % tfs != 0).sum()) if tfs < 86400 else int((b.open_raw % 86400 != 0).sum()),
        "ohlc_invalid": int(ohlc_bad.sum()), "nonfinite": int(finite_bad.sum()),
        "gaps_total": int(len(gaps)), "gaps_weekend_like_ge36h": int((gaps >= WEEKEND_GAP_S).sum()),
        "gaps_intraweek": int(len(intra)),
        "intraweek_missing_bars": int(((intra // tfs) - 1).sum()),
        "intraweek_gap_minutes_quantiles": [float(x) for x in np.quantile(intra / 60, [0.5, 0.9, 0.99, 1.0])] if len(intra) else [],
    }


def volume_basis(b: Bars) -> dict[str, Any]:
    rv_nz = int((b.real_volume != 0).sum())
    tv_nz = int((b.tick_volume != 0).sum())
    return {
        "tick_volume_nonzero_rows": tv_nz, "real_volume_nonzero_rows": rv_nz, "rows": int(len(b)),
        "real_volume_status": "UNAVAILABLE_ALL_ZERO_IN_SOURCE" if rv_nz == 0 else "PRESENT_PARTIAL" if rv_nz < len(b) else "PRESENT",
        "volume_basis_selected": "tick" if rv_nz == 0 else "real_and_tick_labelled",
        "note": "tick_volume counts price changes in the bar (MT5 Volumes doc), not traded contracts; all-zero real_volume is treated as UNAVAILABLE, never as true zero activity.",
    }


def spread_field(b: Bars) -> dict[str, Any]:
    s = b.spread.astype(float)
    return {"zero_fraction": float((s == 0).mean()),
            "quantiles_points_p01_p10_p50_p90_p99": [float(x) for x in np.quantile(s, [0.01, 0.1, 0.5, 0.9, 0.99])],
            "max_points": float(s.max())}


def spread_semantics(m1: Bars, m5: Bars, sample: int = 200_000) -> dict[str, Any]:
    """Compare M5 spread field with min/first/last/max of the member M1 spread fields."""
    bucket = m1.open_raw // 300
    starts = np.flatnonzero(np.r_[True, bucket[1:] != bucket[:-1]])
    ends = np.r_[starts[1:], len(bucket)]
    agg = {"min": np.minimum.reduceat(m1.spread, starts), "max": np.maximum.reduceat(m1.spread, starts),
           "first": m1.spread[starts], "last": m1.spread[ends - 1]}
    keys = bucket[starts] * 300
    idx = np.searchsorted(m5.open_raw, keys)
    ok = (idx < len(m5)) & (m5.open_raw[np.minimum(idx, len(m5) - 1)] == keys)
    res = {}
    for k, v in agg.items():
        res[f"m5_equals_m1_{k}_fraction"] = float((m5.spread[idx[ok]] == v[ok]).mean())
    res["buckets_compared"] = int(ok.sum())
    best = max((k for k in res if k.endswith("fraction")), key=lambda k: res[k])
    res["best_match"] = best
    res["interpretation"] = ("Bar spread field behaves like an aggregate (best match above) of finer-bar spreads. It is NOT a "
                             "synchronized Ask at any instant; used only as a labelled proxy for Ask = Bid + spread*point.")
    return res


def price_grid(b: Bars, max_digits: int = 6) -> dict[str, Any]:
    prices = np.concatenate([b.o, b.h, b.l, b.c])
    for d in range(0, max_digits + 1):
        scaled = prices * (10 ** d)
        if np.all(np.abs(scaled - np.round(scaled)) < 1e-6 * max(1.0, 10 ** d / 1e3)):
            return {"inferred_digits": d, "inferred_tick_size": 10.0 ** -d, "status": "INFERRED_FROM_PRICE_GRID",
                    "caveat": "grid of observed prices; true trade_tick_size could be a multiple and must be confirmed by symbol_info"}
    return {"inferred_digits": None, "inferred_tick_size": None, "status": "GRID_NOT_FOUND"}


def _iso(t) -> str:
    return dt.datetime.fromtimestamp(int(t), UTC).isoformat().replace("+00:00", "Z")


def _regime_of_server_day(raw_day_start: int) -> str:
    d = dt.datetime.fromtimestamp(int(raw_day_start), UTC).date()
    noon = dt.datetime(d.year, d.month, d.day, 12)
    us = bool(noon.replace(tzinfo=NY).dst())
    eu = bool(noon.replace(tzinfo=ATHENS).dst())
    return "US_DST_ONLY" if us and not eu else "EU_DST_ONLY" if eu and not us else "BOTH_DST" if us else "NEITHER_DST"


# Server hour at which 17:00 America/New_York falls, per profile and DST regime.
_NY_OFF = {"BOTH_DST": -4, "US_DST_ONLY": -4, "NEITHER_DST": -5, "EU_DST_ONLY": -5}
_SERVER_OFF = {"NY_PLUS_7": {"BOTH_DST": 3, "US_DST_ONLY": 3, "NEITHER_DST": 2, "EU_DST_ONLY": 2},
               "EET_EU": {"BOTH_DST": 3, "US_DST_ONLY": 2, "NEITHER_DST": 2, "EU_DST_ONLY": 3},
               "RAW_IS_UTC": {k: 0 for k in _NY_OFF}}


def predicted_ny1700_server_hour(profile: str, regime: str) -> int:
    return (17 - _NY_OFF[regime] + _SERVER_OFF[profile][regime]) % 24


def clock_evidence(b: Bars) -> dict[str, Any]:
    """Falsification test for the server clock using events pinned to 17:00 America/New_York:
    (1) the FX rollover spread spike (hour with the highest mean bar-spread field) and
    (2) the start of the metals daily break (modal last-bar close Mon–Thu, only if the symbol has a daily break).
    Weeks where US DST is on but EU DST is off (2nd Sun Mar → last Sun Mar; last Sun Oct → 1st Sun Nov)
    discriminate NY_PLUS_7 (event stays at server 00:00) from EET_EU (event moves to server 23:00).
    The weekly open is reported but is NOT used: brokers clip FX open to the server-week boundary."""
    raw = b.open_raw
    day = raw // 86400
    udays, inv = np.unique(day, return_inverse=True)
    reg_day = np.array([_regime_of_server_day(int(u) * 86400) for u in udays])
    reg = reg_day[inv]
    hour = (raw % 86400) // 3600
    starts = np.flatnonzero(np.r_[True, day[1:] != day[:-1]])
    wd = np.array([dt.datetime.fromtimestamp(int(raw[s]), UTC).weekday() for s in starts])
    obs: dict[str, dict] = {}
    for rg in sorted(set(reg_day)):
        m = reg == rg
        means = [(float(b.spread[m & (hour == hh)].mean()), hh) for hh in range(24) if (m & (hour == hh)).sum() > 50]
        first = Counter(int((raw[s] % 86400) // 3600) for s, w in zip(starts, wd) if reg[s] == rg and 1 <= w <= 4)
        weekly = Counter(dt.datetime.fromtimestamp(int(raw[i]), UTC).strftime("%a %H:%M")
                         for i in np.flatnonzero(np.diff(raw) >= WEEKEND_GAP_S) + 1 if reg[i] == rg)
        obs[rg] = {"rollover_spread_spike_server_hour": max(means)[1] if means else None,
                   "daily_first_bar_server_hour_mode_tue_fri": first.most_common(1)[0] if first else None,
                   "weekly_first_bar_mode": weekly.most_common(1)[0] if weekly else None,
                   "server_days": int((reg_day == rg).sum())}
    ref = obs.get("NEITHER_DST") or next(iter(obs.values()))
    has_break = bool(ref["daily_first_bar_server_hour_mode_tue_fri"] and ref["daily_first_bar_server_hour_mode_tue_fri"][0] != 0)
    test_kind = ("DAILY_BREAK_END = 18:00 New York (first bar of Tue–Fri server days)" if has_break
                 else "ROLLOVER_SPREAD_SPIKE = 17:00 New York (hour with highest mean spread field)")
    scores = {}
    for prof in _SERVER_OFF:
        ok = 0
        for rg, o in obs.items():
            pred = predicted_ny1700_server_hour(prof, rg)
            if has_break:
                ok += int(o["daily_first_bar_server_hour_mode_tue_fri"][0] == (pred + 1) % 24)
            else:
                ok += int(o["rollover_spread_spike_server_hour"] == pred)
        scores[prof] = {"matches": ok, "tests": len(obs)}
    best = [p for p, s in scores.items() if s["matches"] == s["tests"]]
    disc = "US_DST_ONLY" in obs or "EU_DST_ONLY" in obs
    verdict = (best[0] + "_MOST_CONSISTENT") if (len(best) == 1 and disc) else "INCONCLUSIVE"
    return {"test": test_kind, "observations_by_regime": obs, "profile_scores": scores, "verdict": verdict,
            "predicted_server_hour_of_NY1700": {p: {rg: predicted_ny1700_server_hour(p, rg) for rg in obs} for p in _SERVER_OFF},
            "status": "HYPOTHESIS_EVIDENCE_ONLY",
            "limits": "Session/rollover timing is indirect evidence about how the stored numbers were produced; it does not verify "
                      "the broker clock and does not override the recorded source basis. Assumes the 17:00 New York anchor of "
                      "XAU daily break / FX rollover held on this feed.",
            "note": "Weekly first bar is reported only; FX open is clipped to the server-week boundary so it cannot discriminate."}


def time_basis_section(reg: dict, symbol: str, b: Bars, evidence: dict) -> dict[str, Any]:
    """Recorded source basis vs applied hypothesis vs evidence, with an explicit conflict status."""
    tb = reg["symbols"][symbol]["time_basis"]
    applied = b.provenance["clock_profile"]
    offsets = sorted({int(x) for x in np.unique(b.open_raw - b.open_at)})
    recorded = tb.get("source_time_basis_recorded") or ""
    recorded_says_utc = "UTC" in recorded.upper()
    best = evidence["verdict"].replace("_MOST_CONSISTENT", "") if evidence["verdict"].endswith("_MOST_CONSISTENT") else None
    if best is None:
        rel = "EVIDENCE_INCONCLUSIVE"
    elif best == "RAW_IS_UTC":
        rel = "EVIDENCE_AGREES_WITH_UTC_READING"
    else:
        rel = "SOURCE_CONFLICT:TIME_BASIS" if (recorded_says_utc or tb.get("time_basis_status", "").startswith("SOURCE_CONFLICT")) else "EVIDENCE_ONLY"
    return {"contract": tb["contract"], "source_time_basis_recorded": recorded, "source_time_basis_ref": tb.get("source_time_basis_ref"),
            "source_time_basis_ref_sha256": tb.get("source_time_basis_ref_sha256"),
            "recorded_basis_mentions_utc": recorded_says_utc, "clock_profile_applied": applied,
            "clock_profile_status": b.provenance.get("clock_profile_status"), "applied_offsets_raw_minus_utc_s": offsets,
            "evidence_most_consistent_profile": best, "evidence_scores": evidence["profile_scores"],
            "relation": rel, "registry_time_basis_status": tb.get("time_basis_status"),
            "verified": False,
            "consequence": "Session-dependent outputs (P2 New-York window, D1/H1 boundary interpretation, NY buckets) are conditional "
                           "on the applied profile; rerun with clock override RAW_IS_UTC / NY_PLUS_7 for sensitivity."}


def session_profile(b: Bars) -> dict[str, Any]:
    """Typical first/last bar time per server weekday (used to declare a session schedule ASSUMPTION)."""
    sdt = b.open_raw
    day = sdt // 86400
    starts = np.flatnonzero(np.r_[True, day[1:] != day[:-1]])
    ends = np.r_[starts[1:], len(day)] - 1
    res = {}
    for wd in range(7):
        firsts, lasts = Counter(), Counter()
        for s, e in zip(starts, ends):
            w = dt.datetime.fromtimestamp(int(sdt[s]), UTC).weekday()
            if w != wd:
                continue
            firsts[dt.datetime.fromtimestamp(int(sdt[s]), UTC).strftime("%H:%M")] += 1
            lasts[dt.datetime.fromtimestamp(int(sdt[e]) + b.tf_s, UTC).strftime("%H:%M")] += 1
        if firsts:
            res[["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"][wd]] = {
                "first_open_mode": firsts.most_common(1)[0], "last_close_mode": lasts.most_common(1)[0], "days": sum(firsts.values())}
    return res


def native_vs_derived(native: Bars, m5: Bars) -> dict[str, Any]:
    der = aggregate(m5, native.tf)
    common, i1, i2 = np.intersect1d(native.open_raw, der.open_raw, return_indices=True)
    mism = (np.abs(native.o[i1] - der.o[i2]) > 1e-9) | (np.abs(native.h[i1] - der.h[i2]) > 1e-9) | \
           (np.abs(native.l[i1] - der.l[i2]) > 1e-9) | (np.abs(native.c[i1] - der.c[i2]) > 1e-9)
    return {"tf": native.tf, "native_rows": int(len(native)), "derived_rows": int(len(der)), "common": int(len(common)),
            "ohlc_mismatch": int(mism.sum()), "native_only": int(len(native) - len(common)), "derived_only": int(len(der) - len(common))}


def run_audit(symbols: list[str] | None = None) -> dict[str, Any]:
    reg = load_registry()
    symbols = symbols or list(reg["symbols"])
    out: dict[str, Any] = {"source_id": reg["source_id"], "source_identity": reg["source_identity"],
                           "time_contracts": reg.get("time_contracts"), "symbols": {}}
    for s in symbols:
        rec: dict[str, Any] = {"exposure": reg["symbols"][s]["exposure"], "timeframes": {}, "flags": []}
        bars = {tf: load_bars(s, tf, reg) for tf in ("M1", "M5", "H1", "D1")}
        for tf, b in bars.items():
            spec = reg["symbols"][s]["timeframes"].get(tf)
            if b is None:
                rec["timeframes"][tf] = {"status": "UNAVAILABLE_IN_CACHE"}
                continue
            rec["timeframes"][tf] = {"kind": b.provenance.get("kind"), "source": spec, "integrity": integrity(b),
                                     "volume": volume_basis(b), "spread_field": spread_field(b)}
        m5 = bars["M5"]
        rec["price_grid_M5"] = price_grid(m5)
        rec["clock_evidence_M5"] = clock_evidence(m5)
        rec["time_basis"] = time_basis_section(reg, s, m5, rec["clock_evidence_M5"])
        rec["session_profile_M5"] = session_profile(m5)
        if bars["M1"] is not None:
            rec["spread_semantics_M1_vs_M5"] = spread_semantics(bars["M1"], m5)
        for tf in ("H1", "D1"):
            if bars[tf] is not None and bars[tf].provenance.get("kind") == "BROKER_NATIVE":
                rec[f"native_vs_derived_{tf}"] = native_vs_derived(bars[tf], m5)
        if bars["M1"] is None:
            rec["flags"] += ["HISTORY_INSUFFICIENT:M1_MISSING", "ASK_MISSING", "TICKS_MISSING"]
        else:
            rec["flags"] += ["ASK_MISSING", "TICKS_MISSING"]
        rec["flags"] += list(m5.provenance.get("time_quality_flags", ["TIME_UNVERIFIED"])) + ["NEWS_UNKNOWN"]
        if rec["time_basis"]["relation"].startswith("SOURCE_CONFLICT") and "SOURCE_CONFLICT:TIME_BASIS" not in rec["flags"]:
            rec["flags"].append("SOURCE_CONFLICT:TIME_BASIS")
        if rec["timeframes"]["M5"]["volume"]["real_volume_nonzero_rows"] == 0:
            rec["flags"].append("REAL_VOLUME_UNAVAILABLE")
        out["symbols"][s] = rec
    return out
