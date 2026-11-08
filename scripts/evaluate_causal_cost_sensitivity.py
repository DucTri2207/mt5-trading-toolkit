"""Cost sensitivity for the two fixed XAUUSD scalp candidates."""

from __future__ import annotations

import json
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))
import backtest_causal_scalp as b


def serial(signals, results):
    pairs = []
    last_exit = -1
    for s, r in sorted(zip(signals, results), key=lambda x: x[0]["idx"]):
        if r["status"] == "REJECT_RISK" or s["idx"] <= last_exit:
            continue
        pairs.append((s, r))
        last_exit = r["exit_idx"]
    return pairs


def main():
    h1, m5 = b.load_data()
    pool, zone_count = b.detect_candidate_pool(h1, m5)
    hi = m5["high"].astype(float)
    lo = m5["low"].astype(float)
    cl = m5["close"].astype(float)
    specs = [
        ("proxy_max10_tp05", "proximal", 10.0, .45, .5),
        ("proxy_w50_max20_tp05", "proximal", 20.0, .50, .5),
        ("distal_max20_tp075", "distal", 20.0, .45, .75),
    ]
    rows = []
    for cost in (.10, .20, .30, .50, .75):
        for name, level, maxrisk, wick, target in specs:
            cfg = b.Config(name, True, level, wick, .25, True, target, None,
                           max_risk=maxrisk, cost=cost)
            signals = [
                s for s in pool
                if s["sweep_level"] == level and s["wick"] >= wick
                and s["body_atr"] >= .25 and s["trend_ok"] and s["killzone"]
            ]
            results = [b.simulate(s, hi, lo, cl, cfg) for s in signals]
            picked = serial(signals, results)
            rows.append({
                "name": name,
                "cost": cost,
                "serial": b.metrics([r for _, r in picked]),
                "oos": b.metrics([r for s, r in picked if s["year"] >= 2025]),
                "config": cfg.__dict__,
            })
    for row in rows:
        print(row["name"], "cost", row["cost"],
              "serial", row["serial"], "OOS", row["oos"])
    os.makedirs("reports", exist_ok=True)
    with open("reports/causal_cost_sensitivity_20261024.json", "w",
              encoding="utf-8") as f:
        json.dump({"zone_count": zone_count, "pool": len(pool), "rows": rows},
                  f, ensure_ascii=False, indent=2)


if __name__ == "__main__":
    main()
