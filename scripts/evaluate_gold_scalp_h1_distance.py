"""M1 validation of an H1 EMA-distance filter for the locked XAUUSD preset."""

from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone

import numpy as np

sys.path.insert(0, os.path.dirname(__file__))
import backtest_causal_scalp as b
import evaluate_gold_scalp_m1 as m1
from evaluate_causal_serial_walkforward import metrics_for, serial_pairs
from evaluate_gold_scalp_m1_stability import fast_m1_trade


HOURS = {8, 9, 10, 11, 13, 15, 16, 17}
THRESHOLDS = (None, .75, 1.0, 1.25, 1.5, 1.75, 2.0, 2.5, 3.0)


def main() -> None:
    h1, m5 = b.load_data()
    m1_data = m1.load_m1()
    m1_times = m1_data["time"].astype(np.int64)
    pool, zones = b.detect_candidate_pool(h1, m5)
    highs = m5["high"].astype(float)
    lows = m5["low"].astype(float)
    closes = m5["close"].astype(float)
    h1_close = h1["close"].astype(float)
    h1_atr = b.compute_wilder_atr(h1["high"].astype(float),
                                  h1["low"].astype(float), h1_close, 14)
    h1_ema = b.ema(h1_close, 50)
    cfg = b.Config("h1_distance", True, "proximal", .50, .25, True,
                   .50, None, max_risk=20.0, cost=.20)

    annotated = []
    for signal in pool:
        if (signal["sweep_level"] != "proximal" or signal["wick"] < .50
                or signal["body_atr"] < .25 or not signal["trend_ok"]
                or datetime.fromtimestamp(signal["time"], tz=timezone.utc).hour not in HOURS):
            continue
        h_idx = int(np.searchsorted(h1["time"], signal["time"], side="right") - 1)
        j = max(0, h_idx - 1)
        dist = abs((h1_close[j] - h1_ema[j]) / h1_atr[j]) if h1_atr[j] > 0 else 999.0
        annotated.append((signal, float(dist)))

    rows = []
    for threshold in THRESHOLDS:
        signals = [s for s, d in annotated
                   if threshold is None or d <= threshold]
        m5_results = [b.simulate(s, highs, lows, closes, cfg)
                      for s in signals]
        picked = serial_pairs(signals, m5_results)
        m1_results = [fast_m1_trade(s, highs, lows, cfg, m1_data, m1_times)
                      for s, _ in picked]
        row = {
            "max_h1_ema_distance": threshold,
            "raw": len(signals),
            "m5": metrics_for(picked),
            "m5_oos": metrics_for(picked, {2025, 2026}),
            "m1": m1.metrics(m1_results),
            "m1_oos": m1.metrics([r for (s, _), r in zip(picked, m1_results)
                                   if s["year"] in {2025, 2026}]),
        }
        rows.append(row)
        print(json.dumps(row, ensure_ascii=False))

    os.makedirs("reports", exist_ok=True)
    with open("reports/causal_h1_distance_20261024.json", "w",
              encoding="utf-8") as f:
        json.dump({"zones": zones, "pool": len(pool), "hours_utc": sorted(HOURS),
                   "rows": rows}, f, ensure_ascii=False, indent=2)


if __name__ == "__main__":
    main()
