"""Tick-level replay for the fixed XAUUSD scalp preset.

Signals and structural levels come from the causal M5/H1 harness.  Quotes are
then replayed from the first tick after each closed confirmation bar, using
bid for BUY exits and ask for SELL exits.  This is a validation pass, not an
order executor; missing quote windows are reported rather than filled from
future data.
"""

from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timedelta, timezone

import MetaTrader5 as mt5
import numpy as np

sys.path.insert(0, os.path.dirname(__file__))
import backtest_causal_scalp as b


def serial(signals, results):
    out = []
    last_exit = -1
    for s, r in sorted(zip(signals, results), key=lambda x: x[0]["idx"]):
        if r["status"] == "REJECT_RISK" or s["idx"] <= last_exit:
            continue
        out.append((s, r))
        last_exit = r["exit_idx"]
    return out


def metrics(rows):
    if not rows:
        return {"n": 0, "wins": 0, "win_rate": 0.0, "r": 0.0, "pf": 0.0, "dd": 0.0}
    rs = np.array([x["r"] for x in rows], dtype=float)
    wins = int(np.sum(rs > 1e-9))
    gp = float(rs[rs > 0].sum())
    gl = float(-rs[rs < 0].sum())
    curve = np.cumsum(rs)
    dd = float(np.max(np.maximum.accumulate(curve) - curve))
    return {"n": len(rows), "wins": wins,
            "win_rate": 100.0 * wins / len(rows), "r": float(rs.sum()),
            "pf": gp / gl if gl else 999.0, "dd": dd}


def levels(signal, highs, lows, cfg):
    idx = signal["idx"]
    buy = signal["buy"]
    atr = signal["atr"]
    sweep_age = max(0, idx - signal["sweep_idx"])
    lookback = max(4, sweep_age)
    left = max(0, idx - lookback)
    lo = float(np.min(lows[left:idx + 1]))
    hi = float(np.max(highs[left:idx + 1]))
    return lo, hi, atr, buy


def tick_trade(signal, highs, lows, cfg, start_ts, ticks):
    if ticks is None or len(ticks) == 0:
        return {"status": "NO_TICKS", "r": 0.0}
    _, _, atr, buy = levels(signal, highs, lows, cfg)
    idx = signal["idx"]
    sweep_age = max(0, idx - signal["sweep_idx"])
    lookback = max(4, sweep_age)
    left = max(0, idx - lookback)
    struct_lo = float(np.min(lows[left:idx + 1]))
    struct_hi = float(np.max(highs[left:idx + 1]))
    first = ticks[0]
    entry = float(first["ask"] if buy else first["bid"])
    if entry <= 0:
        return {"status": "NO_TICKS", "r": 0.0}
    stop = struct_lo - cfg.sl_buffer_atr * atr if buy else struct_hi + cfg.sl_buffer_atr * atr
    risk = entry - stop if buy else stop - entry
    if risk > cfg.max_risk:
        return {"status": "REJECT_RISK", "r": 0.0}
    if risk < cfg.min_risk:
        risk = cfg.min_risk
        stop = entry - risk if buy else entry + risk
    target = entry + cfg.target_r * risk if buy else entry - cfg.target_r * risk
    for tick in ticks[1:]:
        bid = float(tick["bid"])
        ask = float(tick["ask"])
        if bid <= 0 or ask <= 0:
            continue
        hit_stop = bid <= stop if buy else ask >= stop
        hit_target = bid >= target if buy else ask <= target
        # Same-tick ambiguity is handled conservatively.
        if hit_stop and hit_target:
            return {"status": "LOSS", "r": -1.0}
        if hit_stop:
            return {"status": "LOSS", "r": -1.0}
        if hit_target:
            return {"status": "WIN", "r": cfg.target_r}
    last = ticks[-1]
    exit_px = float(last["bid"] if buy else last["ask"])
    delta = (exit_px - entry) if buy else (entry - exit_px)
    return {"status": "TIME", "r": float(np.clip(delta / risk, -1.0, cfg.target_r))}


def main():
    h1, m5 = b.load_data()
    pool, zones = b.detect_candidate_pool(h1, m5)
    cfg = b.Config("proxy_w50_max20_tp05", True, "proximal", .50, .25,
                   True, .5, None, max_risk=20.0, cost=.20)
    signals = [
        s for s in pool
        if s["sweep_level"] == "proximal" and s["wick"] >= .50
        and s["body_atr"] >= .25 and s["trend_ok"] and s["killzone"]
    ]
    hi = m5["high"].astype(float)
    lo = m5["low"].astype(float)
    cl = m5["close"].astype(float)
    m5_results = [b.simulate(s, hi, lo, cl, cfg) for s in signals]
    picked = serial(signals, m5_results)

    if not mt5.initialize():
        raise RuntimeError(f"MT5 initialize failed: {mt5.last_error()}")
    rows = []
    missing = []
    try:
        for number, (signal, m5_result) in enumerate(picked, 1):
            close_ts = int(signal["time"]) + 300
            start = datetime.fromtimestamp(close_ts, tz=timezone.utc)
            end = start + timedelta(minutes=5 * cfg.hold_bars + 10)
            ticks = mt5.copy_ticks_range("XAUUSD", start, end, mt5.COPY_TICKS_INFO)
            if ticks is None or len(ticks) == 0:
                missing.append({"time": signal["time"], "year": signal["year"]})
                continue
            result = tick_trade(signal, hi, lo, cfg, start, ticks)
            result.update({"time": signal["time"], "year": signal["year"],
                          "m5_status": m5_result["status"],
                          "m5_r": m5_result["r"]})
            rows.append(result)
            if number % 25 == 0:
                print(f"tick replay {number}/{len(picked)}")
    finally:
        mt5.shutdown()

    by_year = {}
    for year in sorted({r["year"] for r in rows}):
        by_year[str(year)] = metrics([r for r in rows if r["year"] == year])
    missing_by_year = {}
    for year in sorted({r["year"] for r in missing}):
        missing_by_year[str(year)] = sum(1 for r in missing if r["year"] == year)
    replayed_by_year = {}
    for year in sorted({r["year"] for r in rows}):
        replayed_by_year[str(year)] = sum(1 for r in rows if r["year"] == year)
    result = {
        "zones": zones,
        "pool": len(pool),
        "m5_serial": b.metrics([r for _, r in picked]),
        "tick": metrics(rows),
        "tick_oos": metrics([r for r in rows if r["year"] >= 2025]),
        "tick_by_year": by_year,
        "replayed": len(rows),
        "missing_ticks": len(missing),
        "replayed_by_year": replayed_by_year,
        "missing_by_year": missing_by_year,
        "missing_examples": missing[:20],
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))
    os.makedirs("reports", exist_ok=True)
    with open("reports/causal_ticklevel_20261024.json", "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)


if __name__ == "__main__":
    main()
