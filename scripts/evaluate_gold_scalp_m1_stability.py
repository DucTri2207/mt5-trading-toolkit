"""M1 stability sweep around the locked session-filtered XAUUSD preset."""

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


HOURS = {8, 9, 10, 11, 13, 15, 16, 17}


def hour(signal: dict) -> int:
    return datetime.fromtimestamp(signal["time"], tz=timezone.utc).hour


def fast_m1_trade(signal, highs, lows, cfg, m1_data, m1_times):
    """Same conservative rules as m1_trade, using indexed M1 slices."""
    start = int(signal["time"]) + 300
    end_time = start + cfg.hold_bars * 300 + 60
    left_i = int(np.searchsorted(m1_times, start, side="left"))
    right_i = int(np.searchsorted(m1_times, end_time, side="left"))
    bars = m1_data[left_i:right_i]
    if len(bars) < 2:
        return {"status": "NO_M1", "r": 0.0}
    idx = signal["idx"]
    buy = signal["buy"]
    atr = signal["atr"]
    lookback = max(4, max(0, idx - signal["sweep_idx"]))
    left = max(0, idx - lookback)
    struct_lo = float(np.min(lows[left:idx + 1]))
    struct_hi = float(np.max(highs[left:idx + 1]))
    entry = float(bars[0]["open"]) + (cfg.cost / 2.0 if buy else -cfg.cost / 2.0)
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
        if hit_stop:
            return {"status": "LOSS", "r": -1.0}
        if hit_target:
            return {"status": "WIN", "r": cfg.target_r}
    last_close = float(bars[-1]["close"])
    delta = (last_close - entry) if buy else (entry - last_close)
    return {"status": "TIME", "r": float(np.clip(delta / risk, -1.0, cfg.target_r))}


def specs():
    out = []
    # Wick and displacement perturbations around the selected proximal mode.
    for wick in (.45, .50, .55):
        out.append((f"prox_w{int(wick*100)}_d25_r20_t05", "proximal", wick, .25, 20.0, .50))
    for disp in (.15, .25, .35, .50):
        out.append((f"prox_w50_d{int(disp*100)}_r20_t05", "proximal", .50, disp, 20.0, .50))
    # Target and risk perturbations.
    for target in (.40, .50, .60, .75):
        out.append((f"prox_w50_d25_r20_t{str(target).replace('.', '')}", "proximal", .50, .25, 20.0, target))
    for maxrisk in (10.0, 15.0, 20.0):
        out.append((f"prox_w50_d25_r{int(maxrisk)}_t05", "proximal", .50, .25, maxrisk, .50))
    # Distal alternatives are included as a separate family, not merged.
    for wick, disp, target in ((.45, .25, .50), (.45, .25, .75),
                               (.50, .25, .75), (.45, .50, .75)):
        out.append((f"dist_w{int(wick*100)}_d{int(disp*100)}_r20_t{str(target).replace('.', '')}",
                    "distal", wick, disp, 20.0, target))
    return out


def main() -> None:
    h1, m5 = b.load_data()
    m1_data = m1.load_m1()
    m1_times = m1_data["time"].astype(np.int64)
    pool, zones = b.detect_candidate_pool(h1, m5)
    highs = m5["high"].astype(float)
    lows = m5["low"].astype(float)
    closes = m5["close"].astype(float)
    rows = []
    for name, level, wick, disp, maxrisk, target in specs():
        cfg = b.Config(name, True, level, wick, disp, True, target, None,
                       max_risk=maxrisk, cost=.20)
        signals = [s for s in pool if s["sweep_level"] == level
                   and s["wick"] >= wick and s["body_atr"] >= disp
                   and s["trend_ok"] and hour(s) in HOURS]
        m5_results = [b.simulate(s, highs, lows, closes, cfg) for s in signals]
        picked = serial_pairs(signals, m5_results)
        m1_results = [fast_m1_trade(s, highs, lows, cfg, m1_data, m1_times)
                      for s, _ in picked]
        row = {
            "name": name, "level": level, "wick": wick,
            "displacement": disp, "max_risk": maxrisk,
            "target_r": target, "raw": len(signals),
            "m5": metrics_for(picked),
            "m5_oos": metrics_for(picked, {2025, 2026}),
            "m1": m1.metrics(m1_results),
            "m1_oos": m1.metrics([r for (s, _), r in zip(picked, m1_results)
                                   if s["year"] in {2025, 2026}]),
        }
        rows.append(row)
        print(json.dumps(row, ensure_ascii=False))
    os.makedirs("reports", exist_ok=True)
    with open("reports/causal_m1_stability_20261024.json", "w",
              encoding="utf-8") as f:
        json.dump({"zones": zones, "pool": len(pool), "hours_utc": sorted(HOURS),
                   "rows": rows}, f, ensure_ascii=False, indent=2)


if __name__ == "__main__":
    main()
