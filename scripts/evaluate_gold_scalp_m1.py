"""Replay XAUUSD scalp signals on the broker's available M1 OHLC history.

M1 is a higher-resolution confirmation pass than M5, not a substitute for
Bid/Ask ticks.  Entries use the first M1 open after the closed M5 signal and
the explicit cost assumption; same-bar SL/TP uses the conservative SL-first
ordering.
"""

from __future__ import annotations

import json
import os
import sys
from collections import Counter
from datetime import datetime, timezone

import MetaTrader5 as mt5
import numpy as np

sys.path.insert(0, os.path.dirname(__file__))
import backtest_causal_scalp as b
from evaluate_causal_serial_walkforward import serial_pairs
from evaluate_gold_scalp_ticklevel import metrics


HOURS = {
    "base_08_12_13_17": set(range(8, 13)) | set(range(13, 18)),
    "exclude_12_14": {8, 9, 10, 11, 13, 15, 16, 17},
    "exclude_14": {8, 9, 10, 11, 12, 13, 15, 16, 17},
    "us_no14": {13, 15, 16, 17},
}


def utc_hour(signal: dict) -> int:
    return datetime.fromtimestamp(signal["time"], tz=timezone.utc).hour


def load_m1() -> np.ndarray:
    chunks = []
    if not mt5.initialize():
        raise RuntimeError(f"MT5 initialize failed: {mt5.last_error()}")
    try:
        for year in range(2021, 2027):
            start = datetime(year, 1, 1, tzinfo=timezone.utc)
            end = datetime(year + 1, 1, 1, tzinfo=timezone.utc)
            rates = mt5.copy_rates_range("XAUUSD", mt5.TIMEFRAME_M1,
                                         start, end)
            if rates is None or len(rates) == 0:
                raise RuntimeError(f"No M1 data for {year}: {mt5.last_error()}")
            chunks.append(rates)
    finally:
        mt5.shutdown()
    out = np.concatenate(chunks)
    order = np.argsort(out["time"], kind="stable")
    out = out[order]
    _, keep = np.unique(out["time"], return_index=True)
    return out[np.sort(keep)]


def m1_trade(signal: dict, highs: np.ndarray, lows: np.ndarray,
             cfg: b.Config, m1: np.ndarray) -> dict:
    start = int(signal["time"]) + 300
    end_time = start + cfg.hold_bars * 300 + 60
    bars = m1[(m1["time"] >= start) & (m1["time"] < end_time)]
    if len(bars) < 2:
        return {"status": "NO_M1", "r": 0.0}

    idx = signal["idx"]
    buy = signal["buy"]
    atr = signal["atr"]
    sweep_age = max(0, idx - signal["sweep_idx"])
    lookback = max(4, sweep_age)
    left = max(0, idx - lookback)
    struct_lo = float(np.min(lows[left:idx + 1]))
    struct_hi = float(np.max(highs[left:idx + 1]))
    first_open = float(bars[0]["open"])
    entry = first_open + (cfg.cost / 2.0 if buy else -cfg.cost / 2.0)
    stop = struct_lo - cfg.sl_buffer_atr * atr if buy else struct_hi + cfg.sl_buffer_atr * atr
    risk = entry - stop if buy else stop - entry
    if risk > cfg.max_risk:
        return {"status": "REJECT_RISK", "r": 0.0}
    if risk < cfg.min_risk:
        risk = cfg.min_risk
        stop = entry - risk if buy else entry + risk
    target = entry + cfg.target_r * risk if buy else entry - cfg.target_r * risk

    for bar in bars[1:]:
        bh = float(bar["high"])
        bl = float(bar["low"])
        hit_stop = bl <= stop if buy else bh >= stop
        hit_target = bh >= target if buy else bl <= target
        if hit_stop and hit_target:
            return {"status": "LOSS", "r": -1.0}
        if hit_stop:
            return {"status": "LOSS", "r": -1.0}
        if hit_target:
            return {"status": "WIN", "r": cfg.target_r}

    last_close = float(bars[-1]["close"])
    delta = (last_close - entry) if buy else (entry - last_close)
    return {"status": "TIME", "r": float(np.clip(delta / risk, -1.0, cfg.target_r))}


def select_signals(pool: list[dict], family: str) -> list[dict]:
    hours = HOURS[family]
    if family.startswith("proxy") or family in HOURS:
        return [s for s in pool
                if s["sweep_level"] == "proximal" and s["wick"] >= .50
                and s["body_atr"] >= .25 and s["trend_ok"]
                and utc_hour(s) in hours]
    raise ValueError(f"unknown family {family}")


def select_ensemble(pool: list[dict]) -> list[dict]:
    candidates = [s for s in pool
                  if s["trend_ok"] and utc_hour(s) in HOURS["exclude_12_14"]
                  and ((s["sweep_level"] == "proximal" and s["wick"] >= .50
                        and s["body_atr"] >= .25)
                       or (s["sweep_level"] == "distal" and s["wick"] >= .45
                           and s["body_atr"] >= .50))]
    best = {}
    for signal in candidates:
        score = (signal["wick"] + signal["body_atr"],
                 1 if signal["sweep_level"] == "distal" else 0)
        old = best.get(signal["idx"])
        if old is None or score > old[0]:
            best[signal["idx"]] = (score, signal)
    return [x[1] for x in sorted(best.values(), key=lambda x: x[1]["idx"])]


def main() -> None:
    h1, m5 = b.load_data()
    m1 = load_m1()
    pool, zones = b.detect_candidate_pool(h1, m5)
    highs = m5["high"].astype(float)
    lows = m5["low"].astype(float)
    closes = m5["close"].astype(float)
    cfg = b.Config("m1_replay", True, "proximal", .50, .25, True,
                   .50, None, max_risk=20.0, cost=.20)
    families = list(HOURS) + ["ensemble_exclude_12_14"]
    rows = []
    for family in families:
        signals = (select_ensemble(pool) if family.startswith("ensemble")
                   else select_signals(pool, family))
        m5_results = [b.simulate(s, highs, lows, closes, cfg)
                      for s in signals]
        picked = serial_pairs(signals, m5_results)
        m1_results = [m1_trade(s, highs, lows, cfg, m1)
                      for s, _ in picked]
        missing = [s["year"] for s, r in zip((s for s, _ in picked), m1_results)
                   if r["status"] == "NO_M1"]
        row = {
            "name": family,
            "hours_utc": sorted(HOURS[family]) if family in HOURS else sorted(HOURS["exclude_12_14"]),
            "m1_bars": len(m1),
            "m5_serial": b.metrics([r for _, r in picked]),
            "m1": metrics(m1_results),
            "m1_by_year": {
                str(y): metrics([r for s, r in zip((s for s, _ in picked), m1_results)
                                 if s["year"] == y])
                for y in range(2021, 2027)
            },
            "missing_m1": len(missing),
            "missing_m1_by_year": dict(Counter(str(y) for y in missing)),
        }
        rows.append(row)
        print(json.dumps(row, ensure_ascii=False))
    os.makedirs("reports", exist_ok=True)
    with open("reports/causal_m1_replay_20261024.json", "w",
              encoding="utf-8") as f:
        json.dump({"zones": zones, "pool": len(pool), "m1_bars": len(m1),
                   "rows": rows}, f, ensure_ascii=False, indent=2)


if __name__ == "__main__":
    main()
