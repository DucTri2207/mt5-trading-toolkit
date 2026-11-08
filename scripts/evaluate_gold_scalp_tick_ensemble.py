"""Tick replay for the session-filtered proximal/distal ensemble candidates."""

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


HOURS = {8, 9, 10, 11, 13, 15, 16, 17}


def is_allowed(signal: dict) -> bool:
    return datetime.fromtimestamp(signal["time"], tz=timezone.utc).hour in HOURS


def build_family(pool: list[dict], name: str) -> list[dict]:
    families = {
        "proxy_only": ("proximal", .50, .25),
        "proxy_plus_distal_d45d50": None,
        "proxy_plus_distal_w50": None,
    }
    if name == "proxy_only":
        level, wick, disp = families[name]
        return [s for s in pool if s["sweep_level"] == level
                and s["wick"] >= wick and s["body_atr"] >= disp
                and s["trend_ok"] and is_allowed(s)]

    distal_wick, distal_disp = ((.45, .50) if name.endswith("d45d50")
                                else (.50, .25))
    candidates = [s for s in pool if s["trend_ok"] and is_allowed(s)
                  and ((s["sweep_level"] == "proximal" and s["wick"] >= .50
                        and s["body_atr"] >= .25)
                       or (s["sweep_level"] == "distal"
                           and s["wick"] >= distal_wick
                           and s["body_atr"] >= distal_disp))]
    best = {}
    for signal in candidates:
        # One confirmation bar remains one opportunity.  Prefer the stronger
        # distal candidate only when its feature score is better.
        score = (signal["wick"] + signal["body_atr"],
                 1 if signal["sweep_level"] == "distal" else 0)
        old = best.get(signal["idx"])
        if old is None or score > old[0]:
            best[signal["idx"]] = (score, signal)
    return [x[1] for x in sorted(best.values(), key=lambda x: x[1]["idx"])]


def main() -> None:
    h1, m5 = b.load_data()
    pool, zones = b.detect_candidate_pool(h1, m5)
    highs = m5["high"].astype(float)
    lows = m5["low"].astype(float)
    closes = m5["close"].astype(float)
    cfg = b.Config("session_ensemble", True, "proximal", .50, .25,
                   True, .50, None, max_risk=20.0, cost=.20)
    names = ["proxy_only", "proxy_plus_distal_d45d50", "proxy_plus_distal_w50"]

    if not mt5.initialize():
        raise RuntimeError(f"MT5 initialize failed: {mt5.last_error()}")
    cache = {}
    rows = []
    try:
        for name in names:
            signals = build_family(pool, name)
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
                "hours_utc": sorted(HOURS),
                "m5_serial": b.metrics([r for _, r in picked]),
                "tick": metrics(tick_rows),
                "replayed": len(tick_rows),
                "missing": len(missing),
                "missing_by_year": dict(Counter(str(y) for y in missing)),
            }
            rows.append(row)
            print(json.dumps(row, ensure_ascii=False))
    finally:
        mt5.shutdown()

    os.makedirs("reports", exist_ok=True)
    with open("reports/causal_tick_ensemble_20261024.json", "w",
              encoding="utf-8") as f:
        json.dump({"zones": zones, "pool": len(pool), "rows": rows}, f,
                  ensure_ascii=False, indent=2)


if __name__ == "__main__":
    main()
