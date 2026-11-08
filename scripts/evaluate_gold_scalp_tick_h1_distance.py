"""Tick replay of the pre-registered H1 EMA-distance filters.

The signal pool and structural levels are causal M5/H1 data.  Only broker
ticks that are actually available are replayed; missing windows are reported
and never backfilled from bars or future data.
"""

from __future__ import annotations

import json
import os
import sys
from collections import Counter
from datetime import datetime, timedelta, timezone

import MetaTrader5 as mt5
import numpy as np

sys.path.insert(0, os.path.dirname(__file__))
import backtest_causal_scalp as b
from evaluate_gold_scalp_ticklevel import metrics, serial, tick_trade


HOURS = {8, 9, 10, 11, 13, 15, 16, 17}
THRESHOLDS = (None, .75, 1.0, 1.25, 1.5, 1.75, 2.0, 2.5, 3.0)


def main() -> None:
    # Keep one MT5 IPC session for both bars and ticks.  Re-initializing after
    # a shutdown can race the terminal's live-update helper on Windows.
    if not mt5.initialize(timeout=60000):
        raise RuntimeError(f"MT5 initialize failed: {mt5.last_error()}")
    try:
        start = datetime(2021, 10, 23, tzinfo=timezone.utc)
        end = datetime(2026, 10, 23, 23, 59, 59, tzinfo=timezone.utc)
        h1 = mt5.copy_rates_range("XAUUSD", mt5.TIMEFRAME_H1, start, end)
        m5 = mt5.copy_rates_range("XAUUSD", mt5.TIMEFRAME_M5, start, end)
    except Exception:
        mt5.shutdown()
        raise
    if h1 is None or m5 is None or len(h1) == 0 or len(m5) == 0:
        err = mt5.last_error()
        mt5.shutdown()
        raise RuntimeError(f"MT5 did not return XAUUSD H1/M5 data: {err}")
    pool, zones = b.detect_candidate_pool(h1, m5)
    highs = m5["high"].astype(float)
    lows = m5["low"].astype(float)
    closes = m5["close"].astype(float)
    h1_close = h1["close"].astype(float)
    h1_atr = b.compute_wilder_atr(h1["high"].astype(float),
                                  h1["low"].astype(float), h1_close, 14)
    h1_ema = b.ema(h1_close, 50)
    cfg = b.Config("tick_h1_distance", True, "proximal", .50, .25,
                   True, .50, None, max_risk=20.0, cost=.20)

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

    cache = {}
    rows = []
    try:
        for threshold in THRESHOLDS:
            signals = [s for s, d in annotated
                       if threshold is None or d <= threshold]
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
                result.update({"year": signal["year"],
                               "m5_status": m5_result["status"],
                               "m5_r": m5_result["r"]})
                tick_rows.append(result)
            row = {
                "max_h1_ema_distance": threshold,
                "m5_serial": b.metrics([r for _, r in picked]),
                "tick": metrics(tick_rows),
                "tick_oos_2025_2026": metrics(
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
    with open("reports/causal_tick_h1_distance_20261024.json", "w",
              encoding="utf-8") as f:
        json.dump({"zones": zones, "pool": len(pool), "hours_utc": sorted(HOURS),
                   "thresholds": THRESHOLDS, "rows": rows}, f,
                  ensure_ascii=False, indent=2)


if __name__ == "__main__":
    main()
