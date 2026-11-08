"""BUY/SELL symmetry report for the locked XAUUSD session preset."""

from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(__file__))
import backtest_causal_scalp as b
from evaluate_causal_serial_walkforward import metrics_for, serial_pairs


HOURS = {8, 9, 10, 11, 13, 15, 16, 17}


def main() -> None:
    h1, m5 = b.load_data()
    pool, zones = b.detect_candidate_pool(h1, m5)
    highs = m5["high"].astype(float)
    lows = m5["low"].astype(float)
    closes = m5["close"].astype(float)
    cfg = b.Config("direction_symmetry", True, "proximal", .50, .25,
                   True, .50, None, max_risk=20.0, cost=.20)
    signals = [s for s in pool if s["sweep_level"] == "proximal"
               and s["wick"] >= .50 and s["body_atr"] >= .25
               and s["trend_ok"]
               and datetime.fromtimestamp(s["time"], tz=timezone.utc).hour in HOURS]
    results = [b.simulate(s, highs, lows, closes, cfg) for s in signals]
    pairs = serial_pairs(signals, results)
    rows = []
    for label, predicate in (("BUY", lambda s: s["buy"]),
                             ("SELL", lambda s: not s["buy"]),
                             ("ALL", lambda s: True)):
        q = [(s, r) for s, r in pairs if predicate(s)]
        row = {
            "side": label,
            "all": metrics_for(q),
            "by_year": {str(y): metrics_for(q, {y})
                        for y in range(2021, 2027)},
        }
        rows.append(row)
        print(json.dumps(row, ensure_ascii=False))
    os.makedirs("reports", exist_ok=True)
    with open("reports/causal_direction_symmetry_20261024.json", "w",
              encoding="utf-8") as f:
        json.dump({"zones": zones, "pool": len(pool), "hours_utc": sorted(HOURS),
                   "rows": rows}, f, ensure_ascii=False, indent=2)


if __name__ == "__main__":
    main()
