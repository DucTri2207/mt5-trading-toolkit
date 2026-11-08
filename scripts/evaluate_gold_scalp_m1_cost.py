"""M1 cost sensitivity for the selected session-filtered preset."""

from __future__ import annotations

import json
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))
import backtest_causal_scalp as b
import evaluate_gold_scalp_m1 as m1
from evaluate_causal_serial_walkforward import serial_pairs


def main() -> None:
    h1, m5 = b.load_data()
    m1_data = m1.load_m1()
    pool, zones = b.detect_candidate_pool(h1, m5)
    highs = m5["high"].astype(float)
    lows = m5["low"].astype(float)
    closes = m5["close"].astype(float)
    signals = m1.select_signals(pool, "exclude_12_14")
    rows = []
    for cost in (.20, .50, .75, 1.00):
        cfg = b.Config(f"m1_session_c{cost}", True, "proximal", .50,
                       .25, True, .50, None, max_risk=20.0, cost=cost)
        m5_results = [b.simulate(s, highs, lows, closes, cfg)
                      for s in signals]
        picked = serial_pairs(signals, m5_results)
        results = [m1.m1_trade(s, highs, lows, cfg, m1_data)
                   for s, _ in picked]
        rows.append({
            "cost": cost,
            "m1": m1.metrics(results),
            "m1_oos_2025_2026": m1.metrics(
                [r for (s, _), r in zip(picked, results)
                 if s["year"] >= 2025]),
            "m5_serial": b.metrics([r for _, r in picked]),
        })
        print(json.dumps(rows[-1], ensure_ascii=False))
    os.makedirs("reports", exist_ok=True)
    with open("reports/causal_m1_cost_20261024.json", "w",
              encoding="utf-8") as f:
        json.dump({"zones": zones, "pool": len(pool), "m1_bars": len(m1_data),
                   "rows": rows}, f, ensure_ascii=False, indent=2)


if __name__ == "__main__":
    main()
