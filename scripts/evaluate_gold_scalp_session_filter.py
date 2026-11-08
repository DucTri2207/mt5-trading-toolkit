"""Causal five-year check for the XAUUSD session-hour filter."""

from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(__file__))
import backtest_causal_scalp as b
from evaluate_causal_serial_walkforward import metrics_for, serial_pairs


HOUR_SETS = {
    "base_08_12_13_17": set(range(8, 13)) | set(range(13, 18)),
    "exclude_12_14": {8, 9, 10, 11, 13, 15, 16, 17},
    "exclude_14": {8, 9, 10, 11, 12, 13, 15, 16, 17},
    "peak_10_11_13_15_17": {10, 11, 13, 15, 16, 17},
    "eu_08_12": set(range(8, 13)),
    "us_no14": {13, 15, 16, 17},
}


def main() -> None:
    h1, m5 = b.load_data()
    pool, zones = b.detect_candidate_pool(h1, m5)
    highs = m5["high"].astype(float)
    lows = m5["low"].astype(float)
    closes = m5["close"].astype(float)
    rows = []
    for name, hours in HOUR_SETS.items():
        for cost in (.20, .50, .75):
            cfg = b.Config(f"{name}_c{cost}", True, "proximal", .50,
                           .25, True, .50, None, max_risk=20.0,
                           cost=cost)
            signals = [
                s for s in pool
                if s["sweep_level"] == "proximal"
                and s["wick"] >= .50
                and s["body_atr"] >= .25
                and s["trend_ok"]
                and datetime.fromtimestamp(s["time"], tz=timezone.utc).hour in hours
            ]
            results = [b.simulate(s, highs, lows, closes, cfg)
                       for s in signals]
            picked = serial_pairs(signals, results)
            rows.append({
                "name": name,
                "hours_utc": sorted(hours),
                "cost": cost,
                "raw": len(signals),
                "all": metrics_for(picked),
                "train_2022_2023": metrics_for(picked, {2022, 2023}),
                "validation_2024": metrics_for(picked, {2024}),
                "oos_2025_2026": metrics_for(picked, {2025, 2026}),
                "by_year": {
                    str(y): metrics_for(picked, {y})
                    for y in range(2021, 2027)
                },
            })
    os.makedirs("reports", exist_ok=True)
    with open("reports/causal_session_filter_20261024.json", "w",
              encoding="utf-8") as f:
        json.dump({"zones": zones, "pool": len(pool), "rows": rows}, f,
                  ensure_ascii=False, indent=2)
    for row in rows:
        m = row["all"]
        o = row["oos_2025_2026"]
        print(row["name"], row["cost"], "n", m["n"],
              "win", round(m["win_rate"], 2), "pf", round(m["pf"], 3),
              "oos_n", o["n"], "oos_win", round(o["win_rate"], 2),
              "oos_pf", round(o["pf"], 3))


if __name__ == "__main__":
    main()
