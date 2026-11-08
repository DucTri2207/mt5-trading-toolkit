"""Cost sensitivity for the pre-registered 1.5 ATR H1-distance filter."""

from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone

import MetaTrader5 as mt5
import numpy as np

sys.path.insert(0, os.path.dirname(__file__))
import backtest_causal_scalp as b
import evaluate_gold_scalp_m1 as m1
from evaluate_causal_serial_walkforward import metrics_for, serial_pairs
from evaluate_gold_scalp_m1_stability import fast_m1_trade


HOURS = {8, 9, 10, 11, 13, 15, 16, 17}
THRESHOLDS = (None, 1.5, 1.75)
COSTS = (.20, .50, .75, 1.00, 1.50)


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


def hour(s):
    return datetime.fromtimestamp(s["time"], tz=timezone.utc).hour


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
    for s in pool:
        if (s["sweep_level"] != "proximal" or s["wick"] < .50
                or s["body_atr"] < .25 or not s["trend_ok"] or hour(s) not in HOURS):
            continue
        hi = int(np.searchsorted(h1["time"], s["time"], side="right") - 1)
        j = max(0, hi - 1)
        d = abs((hc[j] - he[j]) / ha[j]) if ha[j] > 0 else 999.0
        annotated.append((s, float(d)))
    rows = []
    for threshold in THRESHOLDS:
        signals = [s for s, d in annotated if threshold is None or d <= threshold]
        for cost in COSTS:
            cfg = b.Config(f"h1_distance_{threshold}_{cost}", True, "proximal", .50,
                           .25, True, .50, None, max_risk=20.0, cost=cost)
            m5_results = [b.simulate(s, highs, lows, closes, cfg) for s in signals]
            picked = serial_pairs(signals, m5_results)
            m1_results = [fast_m1_trade(s, highs, lows, cfg, m1_data, m1_times)
                          for s, _ in picked]
            row = {
                "max_h1_ema_distance": threshold,
                "cost": cost,
                "m5": metrics_for(picked),
                "m5_oos_2025_2026": metrics_for(picked, {2025, 2026}),
                "m1": m1.metrics(m1_results),
                "m1_oos_2025_2026": m1.metrics([
                    r for (s, _), r in zip(picked, m1_results)
                    if s["year"] in {2025, 2026}]),
            }
            rows.append(row)
            print(json.dumps(row, ensure_ascii=False))
    os.makedirs("reports", exist_ok=True)
    with open("reports/causal_h1_distance_cost_20261024.json", "w", encoding="utf-8") as f:
        json.dump({"zones": zones, "pool": len(pool), "rows": rows}, f,
                  ensure_ascii=False, indent=2)


if __name__ == "__main__":
    main()
