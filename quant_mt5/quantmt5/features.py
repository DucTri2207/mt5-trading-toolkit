"""Shared feature core. Every function is causal: value at index i uses bars[0..i] only (closed bars).

Formulas follow setup-specs.md §1.2 and brainstorm-context.md §3 (seed versions). Feature records carry
name/version/unit/window/seed/available_at/source/volume_basis/quality so agents cite provenance, not memory.
"""
from __future__ import annotations

import math
from typing import Any

import numpy as np
import pandas as pd

from .data import Bars
from .timemap import ny_minutes_of_day
from .util import iso_utc

FEATURE_VERSION = "features-v0.2.0"


# ------------------------------------------------------------------ core series
def true_range(b: Bars) -> np.ndarray:
    tr = b.h - b.l
    if len(b) > 1:
        pc = b.c[:-1]
        tr[1:] = np.maximum.reduce([b.h[1:] - b.l[1:], np.abs(b.h[1:] - pc), np.abs(b.l[1:] - pc)])
    return tr


def wilder(x: np.ndarray, n: int) -> np.ndarray:
    """Wilder smoothing: seed = SMA of first n values (placed at index n-1), then (prev*(n-1)+x)/n."""
    out = np.full(len(x), np.nan)
    if len(x) < n:
        return out
    out[n - 1] = float(np.mean(x[:n]))
    prev = out[n - 1]
    k = (n - 1) / n
    for i in range(n, len(x)):
        prev = prev * k + x[i] / n
        out[i] = prev
    return out


def atr(b: Bars, n: int = 14) -> np.ndarray:
    return wilder(true_range(b), n)


def ema(x: np.ndarray, n: int) -> np.ndarray:
    out = np.full(len(x), np.nan)
    if len(x) < n:
        return out
    a = 2.0 / (n + 1)
    prev = float(np.mean(x[:n]))
    out[n - 1] = prev
    for i in range(n, len(x)):
        prev = prev + a * (x[i] - prev)
        out[i] = prev
    return out


def rvol_prev_median(vol: np.ndarray, n: int = 20) -> np.ndarray:
    """vol[i] / median(vol[i-n..i-1]); NaN if history < n or median == 0 (UNKNOWN, never denominator 1)."""
    s = pd.Series(vol.astype(float))
    med = s.shift(1).rolling(n, min_periods=n).median().to_numpy()
    with np.errstate(divide="ignore", invalid="ignore"):
        r = vol / med
    r[~(med > 0)] = np.nan
    return r


def rvol_same_slot(b: Bars, sessions: int = 20, min_obs: int = 10) -> tuple[np.ndarray, np.ndarray]:
    """vol / median(vol at the same America/New_York minute-of-day over the previous `sessions` occurrences).
    Returns (rvol, sample_count). Slot = NY local minute-of-day (IANA DST rules); bars only from earlier dates."""
    slot = ny_minutes_of_day(b.open_at)
    df = pd.DataFrame({"slot": slot, "v": b.tick_volume.astype(float)})
    g = df.groupby("slot")["v"]
    med = g.transform(lambda s: s.shift(1).rolling(sessions, min_periods=min_obs).median())
    cnt = g.transform(lambda s: s.shift(1).rolling(sessions, min_periods=1).count())
    medv = med.to_numpy()
    with np.errstate(divide="ignore", invalid="ignore"):
        r = df["v"].to_numpy() / medv
    r[~(medv > 0)] = np.nan
    return r, np.nan_to_num(cnt.to_numpy(), nan=0).astype(int)


def efficiency_ratio(c: np.ndarray, i: int, n: int = 20) -> tuple[float | None, str]:
    if i - n < 0:
        return None, "HISTORY_INSUFFICIENT"
    path = float(np.sum(np.abs(np.diff(c[i - n:i + 1]))))
    if path == 0:
        return 0.0, "FLAT_WINDOW"
    return abs(float(c[i] - c[i - n])) / path, "OK"


def rsi_wilder(c: np.ndarray, n: int = 14) -> np.ndarray:
    d = np.diff(c, prepend=np.nan)
    up = np.where(d > 0, d, 0.0)[1:]
    dn = np.where(d < 0, -d, 0.0)[1:]
    au, ad = wilder(up, n), wilder(dn, n)
    with np.errstate(divide="ignore", invalid="ignore"):
        rs = au / ad
        r = 100 - 100 / (1 + rs)
    r = np.where(ad == 0, np.where(au == 0, 50.0, 100.0), r)
    return np.r_[np.nan, r]


def adx_wilder(b: Bars, n: int = 14) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    up = np.r_[np.nan, b.h[1:] - b.h[:-1]]
    dn = np.r_[np.nan, b.l[:-1] - b.l[1:]]
    pdm = np.where((up > dn) & (up > 0), up, 0.0)[1:]
    ndm = np.where((dn > up) & (dn > 0), dn, 0.0)[1:]
    tr = true_range(b)[1:]
    str_, sp, sn = wilder(tr, n), wilder(pdm, n), wilder(ndm, n)
    with np.errstate(divide="ignore", invalid="ignore"):
        pdi = 100 * sp / str_
        ndi = 100 * sn / str_
        dx = 100 * np.abs(pdi - ndi) / (pdi + ndi)
    valid = np.flatnonzero(np.isfinite(dx))
    adx = np.full(len(dx), np.nan)
    if len(valid) >= n:
        adx[valid[0]:] = wilder(np.nan_to_num(dx[valid[0]:]), n)
    pad = lambda a: np.r_[np.nan, a]
    return pad(adx), pad(pdi), pad(ndi)


def percentile_rank_past(x: np.ndarray, i: int, window: int = 1000, min_obs: int = 200) -> tuple[float | None, int]:
    past = x[max(0, i - window):i]
    past = past[np.isfinite(past)]
    if len(past) < min_obs or not math.isfinite(x[i]):
        return None, int(len(past))
    return float((past < x[i]).mean() + 0.5 * (past == x[i]).mean()), int(len(past))


def geometry(o: float, h: float, l: float, c: float, atr_v: float | None) -> dict[str, Any]:
    rng = h - l
    g = {"range": rng}
    if rng > 0:
        g.update({"body_over_range": abs(c - o) / rng, "upper_wick_over_range": (h - max(o, c)) / rng,
                  "lower_wick_over_range": (min(o, c) - l) / rng, "close_location": (c - l) / rng})
    else:
        g.update({"body_over_range": None, "upper_wick_over_range": None, "lower_wick_over_range": None,
                  "close_location": None, "geometry_status": "ZERO_RANGE"})
    g["range_over_atr"] = (rng / atr_v) if (atr_v and atr_v > 0) else None
    return g


# ------------------------------------------------------------------ cached per-Bars series
class SeriesCache:
    """Lazily computed causal series for one Bars object (feature seed = first bar of the dataset)."""

    def __init__(self, b: Bars):
        self.b = b
        self._c: dict[str, Any] = {}

    def get(self, key: str):
        if key not in self._c:
            b = self.b
            if key == "atr14":
                self._c[key] = atr(b, 14)
            elif key == "ema50":
                self._c[key] = ema(b.c, 50)
            elif key == "ema20":
                self._c[key] = ema(b.c, 20)
            elif key == "rvol20":
                self._c[key] = rvol_prev_median(b.tick_volume, 20)
            elif key == "rvol_slot":
                self._c[key] = rvol_same_slot(b)
            elif key == "rsi14":
                self._c[key] = rsi_wilder(b.c, 14)
            elif key == "adx14":
                self._c[key] = adx_wilder(b, 14)
            else:
                raise KeyError(key)
        return self._c[key]


FORMULAS: dict[str, tuple[str, str]] = {
    # name prefix → (formula, warmup)
    "atr14_wilder": ("TR=max(H-L,|H-Cprev|,|L-Cprev|); ATR seed=mean(TR[0..13]) at index 13 of the dataset, then (13*ATR+TR)/14", "14 bars (spec: 200 M5 before use in setups)"),
    "atr_frozen_for_setup": ("ATR14 Wilder frozen at anchor h (A) / at the bar before mother (B)", "200 M5"),
    "tick_volume": ("MqlRates.tick_volume of the closed bar (count of price changes)", "none"),
    "rvol20_tick": ("tick_volume[i] / median(tick_volume[i-20..i-1]); UNKNOWN if <20 prior bars or median==0", "20 closed bars"),
    "rvol_same_slot_tick": ("tick_volume[i] / median(tick_volume at same America/New_York minute-of-day over previous 20 occurrences); UNKNOWN if <10", "10 prior same-slot bars"),
    "real_volume": ("MqlRates.real_volume", "n/a — source all zero → UNAVAILABLE"),
    "signal_": ("geometry of the bar: body/range, wicks/range, close location (C-L)/(H-L), range/ATR", "ATR warmup"),
    "last_bar_": ("geometry of the last closed bar: body/range, wicks/range, close location, range/ATR14", "ATR warmup"),
    "distance_": ("|close - level| / ATR14 (level known before the bar)", "ATR warmup"),
    "bar_spread_field_over_atr": ("MqlRates.spread (bar MINIMUM spread, points) * point / ATR14", "ATR warmup"),
    "m5_atr_percentile_past1000": ("rank of ATR[i] among ATR[i-1000..i-1] (past only), ties 0.5", "200 past values"),
    "h1_ema50": ("EMA50 seed SMA50, alpha=2/51", "250 H1 for gate use"),
    "h1_close_minus_ema50_over_atr": ("(C - EMA50)/ATR14 on H1", "250 H1"),
    "h1_ema50_slope_over_atr": ("(EMA50_t - EMA50_t-3)/(3*ATR14_t) on H1", "250 H1"),
    "h1_ema20": ("EMA20 seed SMA20", "20 H1"),
    "h1_adx14_wilder": ("ADX Wilder 14 (project implementation, not MT5 native)", "~28 H1"),
    "h1_plus_di": ("+DI Wilder 14", "14 H1"), "h1_minus_di": ("-DI Wilder 14", "14 H1"),
    "m5_rsi14_wilder": ("RSI Wilder 14", "15 bars"), "h1_rsi14_wilder": ("RSI Wilder 14", "15 bars"),
    "m5_efficiency_ratio20": ("|C_t - C_t-20| / sum|C_k - C_k-1|", "21 bars"), "h1_efficiency_ratio20": ("|C_t - C_t-20| / sum|C_k - C_k-1|", "21 bars"),
}


def formula_for(name: str) -> tuple[str | None, str | None]:
    if name in FORMULAS:
        return FORMULAS[name]
    for k, v in FORMULAS.items():
        if k.endswith("_") and name.startswith(k):
            return v
    return None, None


def feature_record(name: str, value: Any, *, b: Bars, i: int, unit: str, window: str, quality: str = "OK",
                   reason: str | None = None, volume_basis: str | None = None, extra: dict | None = None,
                   provisional: bool = False, sample_count: int | None = None) -> dict:
    v = value
    if isinstance(v, float) and not math.isfinite(v):
        v, quality, reason = None, "UNKNOWN", reason or "NAN_OR_HISTORY_INSUFFICIENT"
    if v is None and quality == "OK":
        quality = "UNKNOWN"
    formula, warmup = formula_for(name)
    rec = {"name": name, "version": FEATURE_VERSION, "symbol": b.symbol, "tf": b.tf, "value": v, "unit": unit,
           "window": window, "formula": formula, "warmup": warmup, "seed_start_at": iso_utc(b.open_at[0]) if len(b) else None,
           "bar_index_from_seed": int(i), "bar_open_at": iso_utc(b.open_at[i]), "bar_close_at": iso_utc(b.close_at[i]),
           "available_at": iso_utc(b.available_at[i]), "available_at_ts": int(b.available_at[i]),
           "bar_status": b.status(i), "source": {k: b.provenance.get(k) for k in ("dataset_id", "kind", "sha256", "key", "chunk_dir", "data_version",
                                                                                 "data_version_pinned", "read_contract_hash", "coverage_complete", "data_quality_flags",
                                                                                 "clock_profile", "clock_profile_status", "time_basis_status")},
           "quality": quality, "provisional": provisional}
    if sample_count is not None:
        rec["sample_count"] = int(sample_count)
    if reason:
        rec["reason"] = reason
    if volume_basis:
        rec["volume_basis"] = volume_basis
    if extra:
        rec.update(extra)
    return rec


def index_at_or_before(b: Bars, t_available: float) -> int:
    """Index of the last bar whose whole event-ordered prefix is available at t (or -1). Uses the non-decreasing
    prefix-max of available_at, so it is valid even when arrival order differs from event order."""
    pav = np.maximum.accumulate(b.available_at) if len(b) else b.available_at
    return int(np.searchsorted(pav, t_available, side="right")) - 1
