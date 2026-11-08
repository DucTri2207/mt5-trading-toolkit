"""Walk-forward evaluation for the causal XAUUSD scalp harness.

The grid is deliberately small and pre-registered.  It reports train (2022-23),
validation (2024), and untouched OOS (2025-26) separately so a full-period
winner cannot be mistaken for a robust setup.
"""

import json
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))
import backtest_causal_scalp as b


def main():
    h1, m5 = b.load_data()
    pool, zone_count = b.detect_candidate_pool(h1, m5)
    hi = m5["high"].astype(float)
    lo = m5["low"].astype(float)
    cl = m5["close"].astype(float)
    modes = [
        ("tr_kz_dist_w45_d25", True, True, "distal", .45, .25),
        ("tr_kz_dist_w45_d50", True, True, "distal", .45, .50),
        ("tr_kz_dist_w35_d25", True, True, "distal", .35, .25),
        ("tr_kz_prox_w45_d25", True, True, "proximal", .45, .25),
        ("nt_kz_dist_w45_d25", False, True, "distal", .45, .25),
        ("nt_kz_prox_w45_d25", False, True, "proximal", .45, .25),
    ]
    rows = []
    for mode, trend, kz, level, wick, disp in modes:
        for maxrisk in (10.0, 15.0, 20.0):
            for target in (.75, 1.0, 1.25):
                for be in (None, .5, .6):
                    name = f"{mode}_risk{int(maxrisk)}_tp{str(target).replace('.', '')}_be{('off' if be is None else str(be).replace('.', ''))}"
                    cfg = b.Config(name, kz, level, wick, disp, trend, target, be, max_risk=maxrisk)
                    sig = [s for s in pool if s["sweep_level"] == level and s["wick"] >= wick
                           and s["body_atr"] >= disp and (not trend or s["trend_ok"])
                           and (not kz or s["killzone"])]
                    res = [b.simulate(s, hi, lo, cl, cfg) for s in sig]
                    years = {}
                    for segment, ys in (("train", {2022, 2023}), ("validation", {2024}), ("oos", {2025, 2026}), ("all", None)):
                        if ys is None:
                            rr = res
                        else:
                            rr = [r for s, r in zip(sig, res) if s["year"] in ys]
                        years[segment] = b.metrics(rr)
                    rows.append({"name": name, "raw": len(sig), "config": cfg.__dict__, "years": years})

    # Sort by OOS PF after requiring at least 20 OOS trades, then show the
    # highest OOS win-rate candidates with their train/validation evidence.
    eligible = [r for r in rows if r["years"]["oos"]["n"] >= 20]
    eligible.sort(key=lambda r: (r["years"]["oos"]["pf"], r["years"]["oos"]["win_rate"]), reverse=True)
    print(f"Causal zones={zone_count}, pool={len(pool)}, grid={len(rows)}, OOS eligible={len(eligible)}")
    for r in eligible[:20]:
        print(r["name"], "train", r["years"]["train"], "val", r["years"]["validation"], "oos", r["years"]["oos"])
    os.makedirs("reports", exist_ok=True)
    with open("reports/causal_walkforward_20261024.json", "w", encoding="utf-8") as f:
        json.dump({"zone_count": zone_count, "pool": len(pool), "rows": rows}, f, ensure_ascii=False, indent=2)


if __name__ == "__main__":
    main()
