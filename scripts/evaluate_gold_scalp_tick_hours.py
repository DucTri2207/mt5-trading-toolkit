"""Tick replay for a small, pre-declared UTC-session comparison."""

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


HOUR_SETS = {
    "base_08_12_13_17": set(range(8, 13)) | set(range(13, 18)),
    "exclude_12_14": {8, 9, 10, 11, 13, 15, 16, 17},
    "exclude_14": {8, 9, 10, 11, 12, 13, 15, 16, 17},
    "peak_10_11_13_15_17": {10, 11, 13, 15, 16, 17},
    "eu_08_12": set(range(8, 13)),
    "us_no14": {13, 15, 16, 17},
}


def hour(signal: dict) -> int:
    return datetime.fromtimestamp(signal["time"], tz=timezone.utc).hour


def main() -> None:
    h1, m5 = b.load_data()
    pool, zones = b.detect_candidate_pool(h1, m5)
    highs = m5["high"].astype(float)
    lows = m5["low"].astype(float)
    closes = m5["close"].astype(float)
    cfg = b.Config("proxy_w50_hours", True, "proximal", .50, .25,
                   True, .50, None, max_risk=20.0, cost=.20)

    if not mt5.initialize():
        raise RuntimeError(f"MT5 initialize failed: {mt5.last_error()}")
    cache = {}
    rows = []
    try:
        for name, hours in HOUR_SETS.items():
            signals = [
                s for s in pool
                if s["sweep_level"] == "proximal"
                and s["wick"] >= .50
                and s["body_atr"] >= .25
                and s["trend_ok"]
                and hour(s) in hours
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
                tick_rows.append(result)
            row = {
                "name": name,
                "hours_utc": sorted(hours),
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
    with open("reports/causal_tick_hours_20261024.json", "w",
              encoding="utf-8") as f:
        json.dump({"zones": zones, "pool": len(pool), "rows": rows}, f,
                  ensure_ascii=False, indent=2)


if __name__ == "__main__":
    main()
