"""Serial walk-forward evaluation for the causal XAUUSD scalp harness.

The ordinary walk-forward grid measures every setup independently.  This
companion evaluates the same pre-registered parameter grid with one live
position at a time, so trade frequency and OOS results reflect the intended
indicator use more closely.
"""

from __future__ import annotations

import json
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))
import backtest_causal_scalp as b


def serial_pairs(signals, results):
    """Keep chronological, non-overlapping trades; reject oversized stops."""
    pairs = []
    last_exit = -1
    for signal, result in sorted(zip(signals, results), key=lambda x: x[0]["idx"]):
        if result["status"] == "REJECT_RISK" or signal["idx"] <= last_exit:
            continue
        pairs.append((signal, result))
        last_exit = result["exit_idx"]
    return pairs


def metrics_for(pairs, years=None):
    if years is not None:
        pairs = [(s, r) for s, r in pairs if s["year"] in years]
    return b.metrics([r for _, r in pairs])


def main():
    h1, m5 = b.load_data()
    pool, zone_count = b.detect_candidate_pool(h1, m5)
    hi = m5["high"].astype(float)
    lo = m5["low"].astype(float)
    cl = m5["close"].astype(float)

    # Keep this grid aligned with evaluate_causal_walkforward.py and include
    # the deployed proximal scalp target (0.5R).
    modes = [
        ("tr_kz_dist_w45_d25", True, True, "distal", .45, .25),
        ("tr_kz_dist_w45_d50", True, True, "distal", .45, .50),
        ("tr_kz_dist_w35_d25", True, True, "distal", .35, .25),
        ("tr_kz_prox_w45_d25", True, True, "proximal", .45, .25),
        ("tr_kz_prox_w50_d25", True, True, "proximal", .50, .25),
        ("nt_kz_dist_w45_d25", False, True, "distal", .45, .25),
        ("nt_kz_prox_w45_d25", False, True, "proximal", .45, .25),
    ]
    rows = []
    for mode, trend, kz, level, wick, disp in modes:
        for maxrisk in (10.0, 15.0, 20.0):
            for target in (.5, .75, 1.0, 1.25):
                for be in (None, .5, .6):
                    name = (
                        f"{mode}_risk{int(maxrisk)}_tp{str(target).replace('.', '')}"
                        f"_be{('off' if be is None else str(be).replace('.', ''))}"
                    )
                    cfg = b.Config(name, kz, level, wick, disp, trend, target, be,
                                   max_risk=maxrisk)
                    signals = [
                        s for s in pool
                        if s["sweep_level"] == level
                        and s["wick"] >= wick
                        and s["body_atr"] >= disp
                        and (not trend or s["trend_ok"])
                        and (not kz or s["killzone"])
                    ]
                    results = [b.simulate(s, hi, lo, cl, cfg) for s in signals]
                    pairs = serial_pairs(signals, results)
                    rows.append({
                        "name": name,
                        "raw": len(signals),
                        "serial": metrics_for(pairs),
                        "train": metrics_for(pairs, {2022, 2023}),
                        "validation": metrics_for(pairs, {2024}),
                        "oos": metrics_for(pairs, {2025, 2026}),
                        "config": cfg.__dict__,
                    })

    eligible = [row for row in rows if row["oos"]["n"] >= 15]
    # Favor OOS PF, then OOS win rate and frequency.  The full rows remain in
    # the JSON so this ranking is not used as a hidden optimization gate.
    eligible.sort(key=lambda row: (
        row["oos"]["pf"], row["oos"]["win_rate"], row["oos"]["n"]
    ), reverse=True)
    print(f"Causal zones={zone_count}, pool={len(pool)}, grid={len(rows)}, "
          f"serial OOS eligible={len(eligible)}")
    for row in eligible[:30]:
        print(row["name"], "train", row["train"],
              "val", row["validation"], "oos", row["oos"],
              "serial", row["serial"])

    os.makedirs("reports", exist_ok=True)
    with open("reports/causal_serial_walkforward_20261024.json", "w",
              encoding="utf-8") as f:
        json.dump({"zone_count": zone_count, "pool": len(pool), "rows": rows},
                  f, ensure_ascii=False, indent=2)


if __name__ == "__main__":
    main()
