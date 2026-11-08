"""Causal XAUUSD M5 scalp research harness.

This is a research backtest, not an order executor.  It deliberately uses only
closed H1/M5 bars, conservative same-bar ordering (stop before target), an
explicit cost assumption, and a train/validation/out-of-sample report.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import dataclass, asdict
from datetime import datetime, timezone

import numpy as np

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

import MetaTrader5 as mt5

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
from scripts.test_m5_scanning_speed import compute_wilder_atr


@dataclass(frozen=True)
class Config:
    name: str
    killzones: bool
    sweep_level: str  # "proximal" or "distal"
    wick_ratio: float
    displacement_atr: float
    trend_filter: bool
    target_r: float
    be_trigger_r: float | None
    hold_bars: int = 72  # six hours on M5
    sl_buffer_atr: float = 0.25
    min_risk: float = 2.0
    max_risk: float = 10.0
    cost: float = 0.20  # round-trip XAU price units; explicit assumption


def utc_hour(ts: int) -> int:
    return datetime.fromtimestamp(int(ts), tz=timezone.utc).hour


def in_killzone(ts: int) -> bool:
    h = utc_hour(ts)
    return 8 <= h <= 12 or 13 <= h <= 17


def find_post_pivot(highs: np.ndarray, lows: np.ndarray, sweep_idx: int,
                    confirm_idx: int, supply: bool) -> float | None:
    """Find the post-sweep pivot used by the scalp confirmation variant."""
    start = sweep_idx + 1
    stop = min(confirm_idx - 1, sweep_idx + 8)
    if stop <= start + 1:
        return None
    for p in range(start + 1, stop):
        if supply:
            if lows[p] <= lows[p - 1] and lows[p] <= lows[p + 1]:
                return float(lows[p])
        else:
            if highs[p] >= highs[p - 1] and highs[p] >= highs[p + 1]:
                return float(highs[p])
    return None


def build_causal_zones(times, opens, highs, lows, closes, atr):
    """Create H1 zones using only the base and completed departure bars.

    A zone becomes available on the H1 bar after departure completes.  Future
    closes are used only to determine when that already-known zone later breaks;
    no future test count or future score is used to admit a zone.
    """
    n = len(times)
    base_max = 5
    depart_bars = 4
    leg_in = 15
    max_age = 1200
    zones = []
    i = leg_in + 5
    while i <= n - depart_bars - 2:
        found = False
        c_atr = float(atr[i])
        if c_atr <= 0:
            i += 1
            continue
        for base_len in range(1, base_max + 1):
            base_start = i
            base_end = i + base_len - 1
            depart_end = base_end + depart_bars
            if depart_end >= n:
                break
            b_hi = float(np.max(highs[base_start:base_end + 1]))
            b_lo = float(np.min(lows[base_start:base_end + 1]))
            ranges = highs[base_start:base_end + 1] - lows[base_start:base_end + 1]
            if float(np.max(ranges)) > 0.8 * c_atr or b_hi - b_lo > 2.0 * c_atr:
                continue
            d_lo = float(np.min(lows[base_end + 1:depart_end + 1]))
            d_hi = float(np.max(highs[base_end + 1:depart_end + 1]))
            supply = (b_lo - d_lo) >= 1.8 * c_atr
            demand = (d_hi - b_hi) >= 1.8 * c_atr
            if not supply and not demand:
                continue

            # The first bar where the completed departure is known.
            active_idx = depart_end + 1
            end_idx = min(n - 1, base_start + max_age)
            distal = b_hi if supply else b_lo
            proximal = b_lo if supply else b_hi
            for f in range(active_idx, end_idx + 1):
                if (supply and closes[f] > distal) or (demand and closes[f] < distal):
                    end_idx = f
                    break
            dep_move = ((b_lo - d_lo) if supply else (d_hi - b_hi)) / c_atr
            score = float(min(100.0, 40.0 + 20.0 * min(dep_move / 1.8, 2.0)
                              + (15.0 if base_len == 1 else 8.0)))
            zones.append({
                "supply": bool(supply),
                "start": active_idx,
                "end": end_idx,
                "distal": distal,
                "proximal": proximal,
                "score": score,
                "id": len(zones),
            })
            i += base_len
            found = True
            break
        if not found:
            i += 1
    return zones


def bucket_zones(times_h1, zones):
    buckets = [[] for _ in range(len(times_h1))]
    for z in zones:
        lo = max(0, z["start"])
        hi = min(len(times_h1) - 1, z["end"])
        for k in range(lo, hi + 1):
            buckets[k].append(z)
    return buckets


def ema(values: np.ndarray, period: int) -> np.ndarray:
    out = np.zeros(len(values), dtype=np.float64)
    if len(values) == 0:
        return out
    alpha = 2.0 / (period + 1.0)
    out[0] = values[0]
    for i in range(1, len(values)):
        out[i] = alpha * values[i] + (1.0 - alpha) * out[i - 1]
    return out


def detect_signals(rates_h1, rates_m5, cfg: Config):
    t1 = rates_h1["time"].astype(np.int64)
    o1 = rates_h1["open"].astype(np.float64)
    h1 = rates_h1["high"].astype(np.float64)
    l1 = rates_h1["low"].astype(np.float64)
    c1 = rates_h1["close"].astype(np.float64)
    a1 = compute_wilder_atr(h1, l1, c1, 14)
    zones = build_causal_zones(t1, o1, h1, l1, c1, a1)
    buckets = bucket_zones(t1, zones)

    t = rates_m5["time"].astype(np.int64)
    o = rates_m5["open"].astype(np.float64)
    h = rates_m5["high"].astype(np.float64)
    l = rates_m5["low"].astype(np.float64)
    c = rates_m5["close"].astype(np.float64)
    a = compute_wilder_atr(h, l, c, 14)
    h1_ema = ema(c1, 50)
    signals = []
    seen = set()
    n = len(t)

    # c_idx is the just-closed confirmation bar.  No current/open bar data is
    # used to create the signal.
    for c_idx in range(60, n - 1):
        atr_now = float(a[c_idx - 1])
        if atr_now <= 0:
            continue
        if cfg.killzones and not in_killzone(t[c_idx]):
            continue
        hi_idx = int(np.searchsorted(t1, t[c_idx], side="right") - 1)
        # H1 zone active index is the first H1 bar after its departure close.
        if hi_idx < 0 or hi_idx >= len(buckets):
            continue
        for z in buckets[hi_idx]:
            supply = z["supply"]
            zmin, zmax = min(z["distal"], z["proximal"]), max(z["distal"], z["proximal"])
            # Touch and sweep must be in the past, before confirmation.
            touch = False
            for k in range(max(0, c_idx - 20), c_idx):
                if supply:
                    touch = (h[k] >= zmin - 0.2 * atr_now and
                             l[k] <= zmax + 0.5 * atr_now)
                else:
                    touch = (l[k] <= zmax + 0.2 * atr_now and
                             h[k] >= zmin - 0.5 * atr_now)
                if touch:
                    break
            if not touch:
                continue

            sweep_idx = -1
            sweep_price = -1.0 if supply else 1e12
            for age in range(1, 21):
                s_idx = c_idx - age
                rng = h[s_idx] - l[s_idx]
                if rng < 0.25 * atr_now:
                    continue
                wick = (h[s_idx] - max(o[s_idx], c[s_idx])) if supply else (min(o[s_idx], c[s_idx]) - l[s_idx])
                if wick / rng < cfg.wick_ratio:
                    continue
                level = z["distal"] if cfg.sweep_level == "distal" else z["proximal"]
                crossed = h[s_idx] >= level if supply else l[s_idx] <= level
                reclaimed = c[s_idx] < level if supply else c[s_idx] > level
                if not crossed or not reclaimed:
                    continue
                if (supply and h[s_idx] > sweep_price) or ((not supply) and l[s_idx] < sweep_price):
                    sweep_price = h[s_idx] if supply else l[s_idx]
                    sweep_idx = s_idx
            if sweep_idx < 0:
                continue

            # Scalp variant: confirm a post-sweep micro-structure break.
            pivot = find_post_pivot(h, l, sweep_idx, c_idx, supply)
            if pivot is None:
                continue

            body = abs(c[c_idx] - o[c_idx])
            if body < cfg.displacement_atr * atr_now:
                continue
            buy = not supply
            breaks = c[c_idx] > pivot if buy else c[c_idx] < pivot
            directional = c[c_idx] > o[c_idx] if buy else c[c_idx] < o[c_idx]
            if not breaks or not directional:
                continue
            if cfg.trend_filter:
                h_idx_for_trend = max(0, hi_idx - 1)  # prior completed H1 close
                trend_ok = c1[h_idx_for_trend] > h1_ema[h_idx_for_trend] if buy else c1[h_idx_for_trend] < h1_ema[h_idx_for_trend]
                if not trend_ok:
                    continue

            key = (int(t[c_idx]), int(z["id"]))
            if key in seen:
                continue
            seen.add(key)
            signals.append({
                "idx": c_idx,
                "time": int(t[c_idx]),
                "year": datetime.fromtimestamp(int(t[c_idx]), tz=timezone.utc).year,
                "buy": buy,
                "entry": float(c[c_idx]),
                "atr": atr_now,
                "sweep": float(sweep_price),
                "sweep_idx": sweep_idx,
                "zone_id": z["id"],
            })
            # One setup per confirmation bar keeps duplicate zone overlap from
            # inflating frequency; the best/first valid zone is retained.
            break
    return signals, len(zones)


def detect_candidate_pool(rates_h1, rates_m5):
    """Scan causal setup candidates once; configs only filter this pool."""
    t1 = rates_h1["time"].astype(np.int64)
    h1 = rates_h1["high"].astype(np.float64)
    l1 = rates_h1["low"].astype(np.float64)
    c1 = rates_h1["close"].astype(np.float64)
    a1 = compute_wilder_atr(h1, l1, c1, 14)
    zones = build_causal_zones(t1, rates_h1["open"].astype(np.float64), h1, l1, c1, a1)
    buckets = bucket_zones(t1, zones)

    t = rates_m5["time"].astype(np.int64)
    o = rates_m5["open"].astype(np.float64)
    h = rates_m5["high"].astype(np.float64)
    l = rates_m5["low"].astype(np.float64)
    c = rates_m5["close"].astype(np.float64)
    a = compute_wilder_atr(h, l, c, 14)
    h1_ema = ema(c1, 50)
    # Prefix extrema let us reject most zones without a Python loop over 20 bars.
    recent_hi = np.full(len(t), -np.inf)
    recent_lo = np.full(len(t), np.inf)
    for i in range(1, len(t)):
        left = max(0, i - 20)
        recent_hi[i] = max(recent_hi[i - 1], h[i - 1])
        recent_lo[i] = min(recent_lo[i - 1], l[i - 1])
        if i - 20 >= 0:
            # Recompute the small window when the prefix no longer represents it.
            recent_hi[i] = float(np.max(h[left:i]))
            recent_lo[i] = float(np.min(l[left:i]))

    # Keep the strongest candidate per confirmation bar and sweep definition.
    best = {}
    for c_idx in range(60, len(t) - 1):
        atr_now = float(a[c_idx - 1])
        if atr_now <= 0:
            continue
        hi_idx = int(np.searchsorted(t1, t[c_idx], side="right") - 1)
        if hi_idx < 0 or hi_idx >= len(buckets):
            continue
        for z in buckets[hi_idx]:
            zmin, zmax = min(z["distal"], z["proximal"]), max(z["distal"], z["proximal"])
            supply = z["supply"]
            if supply:
                coarse_touch = (recent_hi[c_idx] >= zmin - 0.2 * atr_now and
                                recent_lo[c_idx] <= zmax + 0.5 * atr_now)
            else:
                coarse_touch = (recent_lo[c_idx] <= zmax + 0.2 * atr_now and
                                recent_hi[c_idx] >= zmin - 0.5 * atr_now)
            if not coarse_touch:
                continue
            touch = False
            for k in range(max(0, c_idx - 20), c_idx):
                if supply:
                    touch = (h[k] >= zmin - 0.2 * atr_now and
                             l[k] <= zmax + 0.5 * atr_now)
                else:
                    touch = (l[k] <= zmax + 0.2 * atr_now and
                             h[k] >= zmin - 0.5 * atr_now)
                if touch:
                    break
            if not touch:
                continue
            modes = {"proximal": None, "distal": None}
            for age in range(1, 21):
                s_idx = c_idx - age
                rng = h[s_idx] - l[s_idx]
                if rng < 0.25 * atr_now:
                    continue
                wick = (h[s_idx] - max(o[s_idx], c[s_idx])) if supply else (min(o[s_idx], c[s_idx]) - l[s_idx])
                wick_ratio = float(wick / rng)
                if wick_ratio < 0.35:
                    continue
                for mode, level in (("proximal", z["proximal"]), ("distal", z["distal"])):
                    crossed = h[s_idx] >= level if supply else l[s_idx] <= level
                    reclaimed = c[s_idx] < level if supply else c[s_idx] > level
                    if not crossed or not reclaimed:
                        continue
                    old = modes[mode]
                    extreme = h[s_idx] if supply else l[s_idx]
                    if old is None or (extreme > old["sweep"] if supply else extreme < old["sweep"]):
                        modes[mode] = {"sweep_idx": s_idx, "sweep": float(extreme), "wick": wick_ratio}
            for mode, sw in modes.items():
                if sw is None:
                    continue
                pivot = find_post_pivot(h, l, sw["sweep_idx"], c_idx, supply)
                if pivot is None:
                    continue
                buy = not supply
                body_atr = float(abs(c[c_idx] - o[c_idx]) / atr_now)
                if not ((c[c_idx] > pivot if buy else c[c_idx] < pivot) and
                        (c[c_idx] > o[c_idx] if buy else c[c_idx] < o[c_idx])):
                    continue
                htrend = max(0, hi_idx - 1)
                trend_ok = bool(c1[htrend] > h1_ema[htrend]) if buy else bool(c1[htrend] < h1_ema[htrend])
                cand = {
                    "idx": c_idx, "time": int(t[c_idx]),
                    "year": datetime.fromtimestamp(int(t[c_idx]), tz=timezone.utc).year,
                    "buy": buy, "entry": float(c[c_idx]), "atr": atr_now,
                    "sweep": sw["sweep"], "sweep_idx": sw["sweep_idx"], "zone_id": z["id"],
                    "sweep_level": mode, "wick": sw["wick"], "body_atr": body_atr,
                    "trend_ok": trend_ok, "killzone": in_killzone(t[c_idx]),
                }
                key = (c_idx, mode)
                strength = cand["wick"] + cand["body_atr"]
                if key not in best or strength > best[key]["_strength"]:
                    cand["_strength"] = strength
                    best[key] = cand
    pool = list(best.values())
    for x in pool:
        x.pop("_strength", None)
    return pool, len(zones)


def simulate(signal, highs, lows, closes, cfg: Config, same_bar: str = "sl_first"):
    idx = signal["idx"]
    buy = signal["buy"]
    atr = signal["atr"]
    entry = signal["entry"] + (cfg.cost / 2.0 if buy else -cfg.cost / 2.0)
    # Structural stop uses only bars through the sweep/confirmation.
    # Match the MQL5 indicator's structural window: the confirmation bar plus
    # at least four earlier closed bars, or back to the sweep if it is older.
    sweep_age = max(0, idx - signal["sweep_idx"])
    lookback = max(4, sweep_age)
    left = max(0, idx - lookback)
    lo = float(np.min(lows[left:idx + 1]))
    hi = float(np.max(highs[left:idx + 1]))
    stop = lo - cfg.sl_buffer_atr * atr if buy else hi + cfg.sl_buffer_atr * atr
    risk = entry - stop if buy else stop - entry
    if risk > cfg.max_risk:
        return {"status": "REJECT_RISK", "r": 0.0, "risk": risk, "exit_idx": idx}
    if risk < cfg.min_risk:
        risk = cfg.min_risk
        stop = entry - risk if buy else entry + risk
    target = entry + cfg.target_r * risk if buy else entry - cfg.target_r * risk
    be_price = entry + 0.02 if buy else entry - 0.02
    stop_active = stop
    be_active = False
    end = min(len(highs), idx + 1 + cfg.hold_bars)
    for j in range(idx + 1, end):
        bh, bl = highs[j], lows[j]
        hit_stop = bl <= stop_active if buy else bh >= stop_active
        hit_target = bh >= target if buy else bl <= target
        if hit_stop and hit_target:
            if same_bar == "tp_first":
                return {"status": "WIN", "r": cfg.target_r, "risk": risk, "exit_idx": j}
            return {"status": "BE" if be_active else "LOSS", "r": (0.0 if be_active else -1.0), "risk": risk, "exit_idx": j}
        if hit_stop:
            return {"status": "BE" if be_active else "LOSS", "r": (0.0 if be_active else -1.0), "risk": risk, "exit_idx": j}
        if hit_target:
            return {"status": "WIN", "r": cfg.target_r, "risk": risk, "exit_idx": j}
        if cfg.be_trigger_r is not None and not be_active:
            trigger = entry + cfg.be_trigger_r * risk if buy else entry - cfg.be_trigger_r * risk
            trigger_hit = bh >= trigger if buy else bl <= trigger
            if trigger_hit:
                be_active = True
                stop_active = be_price
    # Time exit uses the next available close and is capped at the planned risk.
    delta = (closes[end - 1] - entry) if buy else (entry - closes[end - 1])
    r = float(np.clip(delta / risk, -1.0, cfg.target_r))
    return {"status": "TIME_BE" if abs(r) < 1e-9 else "TIME", "r": r, "risk": risk, "exit_idx": end - 1}


def metrics(results):
    live = [x for x in results if x["status"] != "REJECT_RISK"]
    if not live:
        return {"n": 0, "wins": 0, "win_rate": 0.0, "be": 0, "losses": 0, "r": 0.0, "pf": 0.0, "dd": 0.0}
    rs = np.array([x["r"] for x in live], dtype=float)
    gp = float(rs[rs > 0].sum())
    gl = float(-rs[rs < 0].sum())
    curve = np.cumsum(rs)
    dd = float(np.max(np.maximum.accumulate(curve) - curve)) if len(curve) else 0.0
    wins = int(np.sum(rs > 0.000001))
    be = int(np.sum(np.abs(rs) <= 0.000001))
    losses = int(np.sum(rs < -0.000001))
    return {"n": len(live), "wins": wins, "win_rate": 100.0 * wins / len(live), "be": be,
            "losses": losses, "r": float(rs.sum()), "pf": gp / gl if gl else 999.0, "dd": dd}


def load_data():
    if not mt5.initialize():
        raise RuntimeError(f"MT5 initialize failed: {mt5.last_error()}")
    try:
        start = datetime(2021, 10, 23, tzinfo=timezone.utc)
        end = datetime(2026, 10, 23, 23, 59, 59, tzinfo=timezone.utc)
        h1 = mt5.copy_rates_range("XAUUSD", mt5.TIMEFRAME_H1, start, end)
        m5 = mt5.copy_rates_range("XAUUSD", mt5.TIMEFRAME_M5, start, end)
    finally:
        mt5.shutdown()
    if h1 is None or m5 is None or len(h1) == 0 or len(m5) == 0:
        raise RuntimeError("MT5 did not return XAUUSD H1/M5 data")
    return h1, m5


def run_config(pool, m5, cfg, zone_count):
    signals = [s for s in pool
               if s["sweep_level"] == cfg.sweep_level
               and s["wick"] >= cfg.wick_ratio
               and s["body_atr"] >= cfg.displacement_atr
               and (not cfg.trend_filter or s["trend_ok"])
               and (not cfg.killzones or s["killzone"])]
    hi = m5["high"].astype(float)
    lo = m5["low"].astype(float)
    cl = m5["close"].astype(float)
    results = [simulate(s, hi, lo, cl, cfg) for s in signals]
    by_year = {}
    for y in sorted({s["year"] for s in signals}):
        yr = [r for s, r in zip(signals, results) if s["year"] == y]
        by_year[str(y)] = metrics(yr)
    return {"config": asdict(cfg), "zones": zone_count, "raw_signals": len(signals),
            "metrics": metrics(results), "by_year": by_year}


def configs():
    # Small pre-registered grid: enough to test hypotheses without searching
    # hundreds of combinations over the same five years.
    out = []
    for name, level, wick, disp, trend in [
        ("baseline_causal", "proximal", 0.35, 0.25, False),
        ("distal_reclaim", "distal", 0.35, 0.25, False),
        ("distal_wick45", "distal", 0.45, 0.25, False),
        ("distal_disp50", "distal", 0.35, 0.50, False),
        ("distal_wick45_disp50", "distal", 0.45, 0.50, False),
        ("distal_wick45_disp50_trend", "distal", 0.45, 0.50, True),
    ]:
        for kz in (False, True):
            out.append(Config(name + ("_kz" if kz else "_24h"), kz, level, wick, disp, trend, 1.0, 0.6))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", default="reports/causal_scalp_grid_20261024.json")
    args = ap.parse_args()
    h1, m5 = load_data()
    print(f"Loaded XAUUSD: {len(h1)} H1, {len(m5)} M5 bars")
    pool, zone_count = detect_candidate_pool(h1, m5)
    print(f"Causal zones={zone_count}, candidate pool={len(pool)}")
    all_results = []
    for cfg in configs():
        row = run_config(pool, m5, cfg, zone_count)
        all_results.append(row)
        m = row["metrics"]
        print(f"{cfg.name:30s} signals={row['raw_signals']:4d} n={m['n']:4d} win={m['win_rate']:5.1f}% PF={m['pf']:4.2f} R={m['r']:+7.2f} DD={m['dd']:6.2f}")
    os.makedirs(os.path.dirname(args.json), exist_ok=True)
    with open(args.json, "w", encoding="utf-8") as f:
        json.dump(all_results, f, ensure_ascii=False, indent=2)
    print(f"Saved {args.json}")


if __name__ == "__main__":
    main()
