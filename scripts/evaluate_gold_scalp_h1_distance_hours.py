"""Pre-registered hour-set comparison for the locked 1.75 ATR preset."""

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
from evaluate_gold_scalp_m1_stability import fast_m1_trade
from evaluate_gold_scalp_robustness import load_all


DISTANCE = 1.75
HOUR_SETS = {
    "current_08_11_13_15_17": {8, 9, 10, 11, 13, 15, 16, 17},
    "peak_10_11_13_15_17": {10, 11, 13, 15, 16, 17},
    "exclude_09": {8, 10, 11, 13, 15, 16, 17},
    "us_no14": {13, 15, 16, 17},
}


def hour(signal):
    return datetime.fromtimestamp(signal["time"], tz=timezone.utc).hour


def main():
    h1, m5, m1_data = load_all()
    m1_times = m1_data["time"].astype(np.int64)
    pool, zones = b.detect_candidate_pool(h1, m5)
    highs = m5["high"].astype(float)
    lows = m5["low"].astype(float)
    closes = m5["close"].astype(float)
    hc = h1["close"].astype(float)
    ha = b.compute_wilder_atr(h1["high"].astype(float), h1["low"].astype(float), hc, 14)
    he = b.ema(hc, 50)
    annotated = []
    for s in pool:
        if (s["sweep_level"] != "proximal" or s["wick"] < .50
                or s["body_atr"] < .25 or not s["trend_ok"]):
            continue
        h_idx = int(np.searchsorted(h1["time"], s["time"], side="right") - 1)
        j = max(0, h_idx - 1)
        d = abs((hc[j] - he[j]) / ha[j]) if ha[j] > 0 else 999.0
        if d <= DISTANCE:
            annotated.append(s)
    cfg = b.Config("h1_distance_hours", True, "proximal", .50, .25,
                   True, .50, None, max_risk=20.0, cost=.20)
    rows = []
    candidates = {}
    for name, hours in HOUR_SETS.items():
        signals = [s for s in annotated if hour(s) in hours]
        m5_results = [b.simulate(s, highs, lows, closes, cfg) for s in signals]
        picked = serial_pairs(signals, m5_results)
        m1_results = [fast_m1_trade(s, highs, lows, cfg, m1_data, m1_times)
                      for s, _ in picked]
        row = {
            "name": name,
            "hours_utc": sorted(hours),
            "m5": metrics_for(picked),
            "m5_oos_2025_2026": metrics_for(picked, {2025, 2026}),
            "m1": m1.metrics(m1_results),
            "m1_oos_2025_2026": m1.metrics([
                r for (s, _), r in zip(picked, m1_results)
                if s["year"] in {2025, 2026}]),
            "m1_by_year": {
                str(y): m1.metrics([r for (s, _), r in zip(picked, m1_results)
                                    if s["year"] == y])
                for y in range(2021, 2027)
            },
        }
        candidates[name] = {"picked": picked, "m1_results": m1_results}
        rows.append(row)
        print(json.dumps(row, ensure_ascii=False))

    wf_folds = []
    for test_year in range(2023, 2027):
        train_years = set(range(2022, test_year))
        ranking = []
        for name, data in candidates.items():
            train = [(s, r) for (s, _), r in zip(data["picked"], data["m1_results"])
                     if s["year"] in train_years]
            train_m = m1.metrics([r for _, r in train])
            freq = train_m["n"] / (12.0 * len(train_years))
            if train_m["n"] >= 20 and train_m["r"] > 0:
                ranking.append((train_m["pf"], train_m["win_rate"],
                                train_m["n"], name, train_m, freq))
        ranking.sort(key=lambda x: (x[0], x[1], x[2]), reverse=True)
        selected = ranking[0][3]
        data = candidates[selected]
        test = [(s, r) for (s, _), r in zip(data["picked"], data["m1_results"])
                if s["year"] == test_year]
        fold = {
            "test_year": test_year,
            "train_years": sorted(train_years),
            "selected": selected,
            "selection_train_m1": ranking[0][4],
            "selection_train_frequency": ranking[0][5],
            "test_m1": m1.metrics([r for _, r in test]),
            "test_m5": metrics_for(data["picked"], {test_year}),
            "ranking": [{"name": x[3], "train_m1": x[4],
                         "train_frequency": x[5]} for x in ranking],
        }
        wf_folds.append(fold)
        print("WF", json.dumps(fold, ensure_ascii=False))
    wf_m1 = []
    wf_m5 = []
    for fold in wf_folds:
        data = candidates[fold["selected"]]
        wf_m1.extend([r for (s, _), r in zip(data["picked"], data["m1_results"])
                      if s["year"] == fold["test_year"]])
        wf_m5.extend([r for s, r in data["picked"] if s["year"] == fold["test_year"]])
    wf_summary = {"m1": m1.metrics(wf_m1), "m5": b.metrics(wf_m5), "folds": wf_folds}
    os.makedirs("reports", exist_ok=True)
    with open("reports/causal_h1_distance_hours_20261024.json", "w", encoding="utf-8") as f:
        json.dump({"zones": zones, "pool": len(pool), "distance_atr": DISTANCE,
                   "rows": rows, "walkforward": wf_summary}, f,
                  ensure_ascii=False, indent=2)


if __name__ == "__main__":
    main()
