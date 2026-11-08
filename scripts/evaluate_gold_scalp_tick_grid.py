"""Pre-registered XAUUSD scalp variants on the broker's available ticks.

This is a comparison pass, not a parameter optimizer.  All variants use the
same causal candidate pool, closed-bar trend filter and UTC killzones; only
the declared signal/exit thresholds differ.  Missing tick windows are counted
and are never filled from OHLC or future data.
"""

from __future__ import annotations

import json
import os
import sys
from collections import Counter
from datetime import datetime, timedelta, timezone

import MetaTrader5 as mt5

sys.path.insert(0, os.path.dirname(__file__))
import backtest_causal_scalp as b
from evaluate_gold_scalp_ticklevel import metrics, serial, tick_trade


SPECS = [
    # name, sweep level, wick, displacement, max risk, target
    ("proxy_w50_d25_r20_t05", "proximal", .50, .25, 20.0, .50),
    ("proxy_w50_d25_r15_t05", "proximal", .50, .25, 15.0, .50),
    ("proxy_w50_d25_r10_t05", "proximal", .50, .25, 10.0, .50),
    ("proxy_w45_d25_r20_t05", "proximal", .45, .25, 20.0, .50),
    ("dist_w35_d25_r20_t05", "distal", .35, .25, 20.0, .50),
    ("dist_w45_d25_r20_t05", "distal", .45, .25, 20.0, .50),
    ("dist_w45_d25_r20_t075", "distal", .45, .25, 20.0, .75),
    ("dist_w45_d25_r20_t10", "distal", .45, .25, 20.0, 1.00),
    ("dist_w45_d25_r20_t125", "distal", .45, .25, 20.0, 1.25),
    ("dist_w50_d25_r20_t075", "distal", .50, .25, 20.0, .75),
    ("dist_w45_d50_r20_t075", "distal", .45, .50, 20.0, .75),
    ("proxy_w50_d50_r20_t05", "proximal", .50, .50, 20.0, .50),
]


def main() -> None:
    h1, m5 = b.load_data()
    pool, zones = b.detect_candidate_pool(h1, m5)
    highs = m5["high"].astype(float)
    lows = m5["low"].astype(float)
    closes = m5["close"].astype(float)

    if not mt5.initialize():
        raise RuntimeError(f"MT5 initialize failed: {mt5.last_error()}")

    cache = {}
    rows = []
    try:
        for name, level, wick, disp, maxrisk, target in SPECS:
            cfg = b.Config(name, True, level, wick, disp, True, target, None,
                           max_risk=maxrisk, cost=.20)
            signals = [
                s for s in pool
                if s["sweep_level"] == level
                and s["wick"] >= wick
                and s["body_atr"] >= disp
                and s["trend_ok"] and s["killzone"]
            ]
            m5_results = [b.simulate(s, highs, lows, closes, cfg)
                          for s in signals]
            picked = serial(signals, m5_results)
            tick_rows = []
            missing = []
            for signal, m5_result in picked:
                close_ts = int(signal["time"]) + 300
                start = datetime.fromtimestamp(close_ts, tz=timezone.utc)
                end = start + timedelta(minutes=5 * cfg.hold_bars + 10)
                key = (close_ts, int(end.timestamp()))
                if key not in cache:
                    cache[key] = mt5.copy_ticks_range(
                        "XAUUSD", start, end, mt5.COPY_TICKS_INFO)
                ticks = cache[key]
                if ticks is None or len(ticks) == 0:
                    missing.append(signal["year"])
                    continue
                result = tick_trade(signal, highs, lows, cfg, start, ticks)
                result["year"] = signal["year"]
                result["m5_status"] = m5_result["status"]
                result["m5_r"] = m5_result["r"]
                tick_rows.append(result)
            row = {
                "name": name,
                "level": level,
                "wick": wick,
                "displacement": disp,
                "max_risk": maxrisk,
                "target_r": target,
                "m5_serial": b.metrics([r for _, r in picked]),
                "tick": metrics(tick_rows),
                "tick_2025_2026": metrics(
                    [r for r in tick_rows if r["year"] >= 2025]),
                "replayed": len(tick_rows),
                "missing": len(missing),
                "missing_by_year": dict(Counter(str(y) for y in missing)),
            }
            rows.append(row)
            print(json.dumps(row, ensure_ascii=False))
    finally:
        mt5.shutdown()

    os.makedirs("reports", exist_ok=True)
    with open("reports/causal_tick_grid_20261024.json", "w",
              encoding="utf-8") as f:
        json.dump({"zones": zones, "pool": len(pool), "specs": SPECS,
                   "rows": rows}, f, ensure_ascii=False, indent=2)


if __name__ == "__main__":
    main()
