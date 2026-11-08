"""Reproducible final candidate check with serial (non-overlapping) trades."""

import json
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))
import backtest_causal_scalp as b


def serial_results(signals, results):
    picked = []
    last_exit = -1
    for s, r in zip(signals, results):
        if r["status"] == "REJECT_RISK" or s["idx"] <= last_exit:
            continue
        picked.append((s, r))
        last_exit = r["exit_idx"]
    return picked


def one(name, pool, m5, *, level, maxrisk, target, be, wick=.45, disp=.25,
        trend=True, kz=True, cost=.20):
    cfg = b.Config(name, kz, level, wick, disp, trend, target, be,
                   hold_bars=72, max_risk=maxrisk, cost=cost)
    signals = [s for s in pool if s["sweep_level"] == level
               and s["wick"] >= wick and s["body_atr"] >= disp
               and (not trend or s["trend_ok"])
               and (not kz or s["killzone"])]
    hi = m5["high"].astype(float)
    lo = m5["low"].astype(float)
    cl = m5["close"].astype(float)
    results = [b.simulate(s, hi, lo, cl, cfg) for s in signals]
    picked = serial_results(signals, results)
    serial = [r for s, r in picked]
    years = {str(y): b.metrics([r for s, r in picked if s["year"] == y])
             for y in sorted({s["year"] for s, r in picked})}
    return {"name": name, "config": cfg.__dict__, "raw_signals": len(signals),
            "independent": b.metrics(results), "serial": b.metrics(serial),
            "by_year_serial": years,
            "oos_serial": b.metrics([r for s, r in picked if s["year"] >= 2025])}


def main():
    h1, m5 = b.load_data()
    pool, zones = b.detect_candidate_pool(h1, m5)
    rows = [
        one("proxy_max10_tp05", pool, m5, level="proximal", maxrisk=10.0, target=.5, be=None),
        one("proxy_w50_max20_tp05", pool, m5, level="proximal", maxrisk=20.0, target=.5,
            be=None, wick=.50, disp=.25),
        one("distal_max20_tp075", pool, m5, level="distal", maxrisk=20.0, target=.75, be=None),
        one("distal_max20_tp06_be05", pool, m5, level="distal", maxrisk=20.0, target=.6, be=.5),
    ]
    for r in rows:
        print(r["name"], "serial", r["serial"], "OOS", r["oos_serial"])
    os.makedirs("reports", exist_ok=True)
    with open("reports/causal_candidate_check_20261024.json", "w", encoding="utf-8") as f:
        json.dump({"zones": zones, "pool": len(pool), "rows": rows}, f, ensure_ascii=False, indent=2)


if __name__ == "__main__":
    main()
