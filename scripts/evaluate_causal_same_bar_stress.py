"""Stress the fixed XAUUSD preset under same-bar SL/TP ordering choices."""

from __future__ import annotations

import json
import os
import sys

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


def main():
    h1, m5 = b.load_data()
    pool, zones = b.detect_candidate_pool(h1, m5)
    cfg = b.Config("proxy_w50_max20_tp05", True, "proximal", .50, .25,
                   True, .5, None, max_risk=20.0)
    signals = [
        s for s in pool
        if s["sweep_level"] == "proximal" and s["wick"] >= .50
        and s["body_atr"] >= .25 and s["trend_ok"] and s["killzone"]
    ]
    hi = m5["high"].astype(float)
    lo = m5["low"].astype(float)
    cl = m5["close"].astype(float)
    rows = []
    for order in ("sl_first", "tp_first"):
        results = [b.simulate(s, hi, lo, cl, cfg, same_bar=order) for s in signals]
        pairs = serial(signals, results)
        rows.append({
            "same_bar": order,
            "serial": b.metrics([r for _, r in pairs]),
            "oos": b.metrics([r for s, r in pairs if s["year"] >= 2025]),
        })
    for row in rows:
        print(row)
    os.makedirs("reports", exist_ok=True)
    with open("reports/causal_same_bar_stress_20261024.json", "w",
              encoding="utf-8") as f:
        json.dump({"zones": zones, "pool": len(pool), "rows": rows}, f,
                  ensure_ascii=False, indent=2)


if __name__ == "__main__":
    main()
