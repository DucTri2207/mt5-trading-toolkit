"""Statistical robustness audit for the locked v3.12 XAUUSD preset.

This is a diagnostic, not a parameter search.  It replays the fixed 1.75 ATR
H1-distance rule and reports month/year consistency plus deterministic bootstrap
intervals for the trade sequence.
"""

from __future__ import annotations

import json
import os
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone

import MetaTrader5 as mt5
import numpy as np

sys.path.insert(0, os.path.dirname(__file__))
import backtest_causal_scalp as b
import evaluate_gold_scalp_m1 as m1
from evaluate_causal_serial_walkforward import serial_pairs
from evaluate_gold_scalp_m1_stability import fast_m1_trade
from evaluate_gold_scalp_ticklevel import metrics as tick_metrics


HOURS = {8, 9, 10, 11, 13, 15, 16, 17}
DISTANCE = 1.75
COST = 0.20
SEED = 20261024
BOOTSTRAPS = 20000


def load_all():
    if not mt5.initialize(timeout=60000):
        raise RuntimeError(f"MT5 initialize failed: {mt5.last_error()}")
    try:
        start = datetime(2021, 10, 23, tzinfo=timezone.utc)
        end = datetime(2026, 10, 23, 23, 59, 59, tzinfo=timezone.utc)
        h1 = mt5.copy_rates_range("XAUUSD", mt5.TIMEFRAME_H1, start, end)
        m5 = mt5.copy_rates_range("XAUUSD", mt5.TIMEFRAME_M5, start, end)
        chunks = []
        for year in range(2021, 2027):
            ys = datetime(year, 1, 1, tzinfo=timezone.utc)
            ye = datetime(year + 1, 1, 1, tzinfo=timezone.utc)
            rates = mt5.copy_rates_range("XAUUSD", mt5.TIMEFRAME_M1, ys, ye)
            if rates is None or len(rates) == 0:
                raise RuntimeError(f"No M1 data for {year}: {mt5.last_error()}")
            chunks.append(rates)
    finally:
        mt5.shutdown()
    if h1 is None or m5 is None or len(h1) == 0 or len(m5) == 0:
        raise RuntimeError("MT5 did not return XAUUSD H1/M5 data")
    data = np.concatenate(chunks)
    order = np.argsort(data["time"], kind="stable")
    data = data[order]
    _, keep = np.unique(data["time"], return_index=True)
    return h1, m5, data[np.sort(keep)]


def hour(signal):
    return datetime.fromtimestamp(signal["time"], tz=timezone.utc).hour


def percentile(values, q=(2.5, 50, 97.5)):
    return {str(x): float(v) for x, v in zip(q, np.percentile(values, q))}


def simple_sequence_metrics(rs):
    rs = np.asarray(rs, dtype=float)
    if len(rs) == 0:
        return {"n": 0, "wins": 0, "win_rate": 0.0, "r": 0.0,
                "pf": 0.0, "max_dd": 0.0, "max_loss_streak": 0}
    wins = rs > 1e-9
    gross_profit = float(rs[rs > 0].sum())
    gross_loss = float(-rs[rs < 0].sum())
    curve = np.cumsum(rs)
    max_dd = float(np.max(np.maximum.accumulate(curve) - curve))
    streak = best = 0
    for value in rs:
        if value < -1e-9:
            streak += 1
            best = max(best, streak)
        else:
            streak = 0
    return {"n": int(len(rs)), "wins": int(wins.sum()),
            "win_rate": float(100.0 * wins.mean()), "r": float(rs.sum()),
            "pf": gross_profit / gross_loss if gross_loss else 999.0,
            "max_dd": max_dd, "max_loss_streak": int(best)}


def main():
    h1, m5, m1_data = load_all()
    m1_times = m1_data["time"].astype(np.int64)
    pool, zones = b.detect_candidate_pool(h1, m5)
    highs = m5["high"].astype(float)
    lows = m5["low"].astype(float)
    closes = m5["close"].astype(float)
    hc = h1["close"].astype(float)
    ha = b.compute_wilder_atr(h1["high"].astype(float), h1["low"].astype(float), hc, 14)
    he = b.ema(hc, 50)
    annotated = []
    for signal in pool:
        if (signal["sweep_level"] != "proximal" or signal["wick"] < .50
                or signal["body_atr"] < .25 or not signal["trend_ok"]
                or hour(signal) not in HOURS):
            continue
        h_idx = int(np.searchsorted(h1["time"], signal["time"], side="right") - 1)
        j = max(0, h_idx - 1)
        distance = abs((hc[j] - he[j]) / ha[j]) if ha[j] > 0 else 999.0
        if distance <= DISTANCE:
            annotated.append(signal)
    cfg = b.Config("v3_12_robustness", True, "proximal", .50, .25,
                   True, .50, None, max_risk=20.0, cost=COST)
    m5_results = [b.simulate(s, highs, lows, closes, cfg) for s in annotated]
    picked = serial_pairs(annotated, m5_results)
    m1_results = [fast_m1_trade(s, highs, lows, cfg, m1_data, m1_times)
                  for s, _ in picked]

    trades = []
    for (signal, m5_result), m1_result in zip(picked, m1_results):
        trades.append({
            "time": int(signal["time"]),
            "month": datetime.fromtimestamp(signal["time"], tz=timezone.utc).strftime("%Y-%m"),
            "hour": datetime.fromtimestamp(signal["time"], tz=timezone.utc).hour,
            "year": int(signal["year"]),
            "buy": bool(signal["buy"]),
            "r": float(m1_result["r"]),
            "status": m1_result["status"],
            "m5_r": float(m5_result["r"]),
        })
    rs = np.array([t["r"] for t in trades], dtype=float)
    base = simple_sequence_metrics(rs)

    by_year = {}
    by_month = {}
    by_hour = {}
    for year in sorted({t["year"] for t in trades}):
        by_year[str(year)] = simple_sequence_metrics(
            [t["r"] for t in trades if t["year"] == year])
    for month in sorted({t["month"] for t in trades}):
        rows = [t for t in trades if t["month"] == month]
        by_month[month] = simple_sequence_metrics([t["r"] for t in rows])
    for hour_value in sorted({t["hour"] for t in trades}):
        by_hour[str(hour_value)] = simple_sequence_metrics(
            [t["r"] for t in trades if t["hour"] == hour_value])
    month_r = np.array([v["r"] for v in by_month.values()], dtype=float)
    month_n = np.array([v["n"] for v in by_month.values()], dtype=int)

    rng = np.random.default_rng(SEED)
    idx = rng.integers(0, len(rs), size=(BOOTSTRAPS, len(rs)))
    samples = rs[idx]
    sample_wins = (samples > 1e-9).sum(axis=1) / len(rs) * 100.0
    sample_r = samples.sum(axis=1)
    gp = np.where(samples > 0, samples, 0.0).sum(axis=1)
    gl = -np.where(samples < 0, samples, 0.0).sum(axis=1)
    sample_pf = np.divide(gp, gl, out=np.full(BOOTSTRAPS, 999.0), where=gl > 0)
    sample_dd = np.empty(BOOTSTRAPS)
    for i in range(BOOTSTRAPS):
        curve = np.cumsum(samples[i])
        sample_dd[i] = np.max(np.maximum.accumulate(curve) - curve)

    # Month-block bootstrap preserves the within-month clustering of entries
    # and therefore gives a more conservative uncertainty check than IID
    # trade resampling.  Each resample contains the same number of active
    # months, with replacement.
    month_arrays = [np.asarray([t["r"] for t in trades if t["month"] == month], dtype=float)
                    for month in sorted(by_month)]
    block_idx = rng.integers(0, len(month_arrays), size=(BOOTSTRAPS, len(month_arrays)))
    block_wr = np.empty(BOOTSTRAPS)
    block_r = np.empty(BOOTSTRAPS)
    block_pf = np.empty(BOOTSTRAPS)
    block_dd = np.empty(BOOTSTRAPS)
    for i in range(BOOTSTRAPS):
        block_rs = np.concatenate([month_arrays[j] for j in block_idx[i]])
        mm = simple_sequence_metrics(block_rs)
        block_wr[i] = mm["win_rate"]
        block_r[i] = mm["r"]
        block_pf[i] = mm["pf"]
        block_dd[i] = mm["max_dd"]

    out = {
        "zones": zones,
        "pool": len(pool),
        "m1_bars": len(m1_data),
        "preset": {"distance_atr": DISTANCE, "cost": COST,
                   "hours_utc": sorted(HOURS)},
        "base_m1": base,
        "base_m5": b.metrics([r for _, r in picked]),
        "by_year": by_year,
        "by_month": by_month,
        "by_hour": by_hour,
        "month_summary": {
            "months_with_trades": int(len(month_r)),
            "positive_months": int((month_r > 0).sum()),
            "negative_months": int((month_r < 0).sum()),
            "flat_months": int((month_r == 0).sum()),
            "median_month_r": float(np.median(month_r)) if len(month_r) else 0.0,
            "worst_month_r": float(np.min(month_r)) if len(month_r) else 0.0,
            "best_month_r": float(np.max(month_r)) if len(month_r) else 0.0,
            "median_trades_per_active_month": float(np.median(month_n)) if len(month_n) else 0.0,
        },
        "bootstrap": {
            "seed": SEED,
            "resamples": BOOTSTRAPS,
            "win_rate_percentile": percentile(sample_wins),
            "total_r_percentile": percentile(sample_r),
            "pf_percentile": percentile(sample_pf),
            "max_dd_percentile": percentile(sample_dd),
        },
        "month_block_bootstrap": {
            "seed_stream": "same deterministic RNG after trade bootstrap",
            "resamples": BOOTSTRAPS,
            "win_rate_percentile": percentile(block_wr),
            "total_r_percentile": percentile(block_r),
            "pf_percentile": percentile(block_pf),
            "max_dd_percentile": percentile(block_dd),
        },
        "trades": trades,
    }
    os.makedirs("reports", exist_ok=True)
    with open("reports/causal_h1_distance_robustness_20261024.json", "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)
    print(json.dumps({k: out[k] for k in ("base_m1", "base_m5", "month_summary", "bootstrap")}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
