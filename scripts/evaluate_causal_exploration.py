"""Exploratory but fully causal serial grid for XAUUSD M5.

This is a discovery report, not a deployment optimizer.  It keeps train,
validation, and untouched OOS metrics separate and stores every row so a
candidate cannot be selected from a hidden subset of the data.
"""

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


def m(pairs, years=None):
    if years is not None:
        pairs = [(s, r) for s, r in pairs if s["year"] in years]
    return b.metrics([r for _, r in pairs])


def main():
    h1, m5 = b.load_data()
    pool, zones = b.detect_candidate_pool(h1, m5)
    hi = m5["high"].astype(float)
    lo = m5["low"].astype(float)
    cl = m5["close"].astype(float)
    rows = []
    # Thresholds are intentionally modest and predeclared.  A second pass can
    # be made only after inspecting this complete discovery report.
    for level in ("proximal", "distal"):
        for trend in (True, False):
            for kz in (True, False):
                for wick in (.35, .40, .45, .50, .55):
                    for disp in (.15, .25, .35, .50):
                        for maxrisk in (10.0, 15.0, 20.0):
                            for target in (.50, .60, .75, 1.0):
                                name = (
                                    f"{level}_tr{int(trend)}_kz{int(kz)}"
                                    f"_w{int(wick*100)}_d{int(disp*100)}"
                                    f"_risk{int(maxrisk)}_tp{str(target).replace('.', '')}"
                                )
                                cfg = b.Config(name, kz, level, wick, disp,
                                               trend, target, None,
                                               max_risk=maxrisk)
                                sig = [
                                    s for s in pool
                                    if s["sweep_level"] == level
                                    and s["wick"] >= wick
                                    and s["body_atr"] >= disp
                                    and (not trend or s["trend_ok"])
                                    and (not kz or s["killzone"])
                                ]
                                res = [b.simulate(s, hi, lo, cl, cfg) for s in sig]
                                pairs = serial(sig, res)
                                rows.append({
                                    "name": name,
                                    "raw": len(sig),
                                    "serial": m(pairs),
                                    "train": m(pairs, {2022, 2023}),
                                    "validation": m(pairs, {2024}),
                                    "oos": m(pairs, {2025, 2026}),
                                    "config": cfg.__dict__,
                                })
    eligible = [
        r for r in rows
        if r["oos"]["n"] >= 20
        and r["train"]["r"] > 0
        and r["validation"]["r"] > 0
        and r["oos"]["r"] > 0
    ]
    eligible.sort(key=lambda r: (
        r["oos"]["pf"], r["oos"]["win_rate"], r["oos"]["n"]
    ), reverse=True)
    print(f"Causal zones={zones}, pool={len(pool)}, grid={len(rows)}, "
          f"robust eligible={len(eligible)}")
    for r in eligible[:40]:
        print(r["name"], "train", r["train"],
              "val", r["validation"], "oos", r["oos"],
              "serial", r["serial"])
    os.makedirs("reports", exist_ok=True)
    with open("reports/causal_exploration_20261024.json", "w",
              encoding="utf-8") as f:
        json.dump({"zones": zones, "pool": len(pool), "rows": rows},
                  f, ensure_ascii=False, indent=2)


if __name__ == "__main__":
    main()
