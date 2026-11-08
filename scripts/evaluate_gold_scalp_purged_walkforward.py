"""Purged chronological walk-forward for the locked XAUUSD distance sweep.

Signals within one planned holding window of a train/test boundary are removed
from both sides.  This avoids a trade near New Year's crossing the split and
quietly borrowing future bars from the other fold.
"""

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


HOURS = {8, 9, 10, 11, 13, 15, 16, 17}
THRESHOLDS = (None, .75, 1.0, 1.25, 1.5, 1.75, 2.0, 2.5, 3.0)
HOLD_SECONDS = 72 * 300


def ts(year, month=1, day=1):
    return int(datetime(year, month, day, tzinfo=timezone.utc).timestamp())


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
                or s["body_atr"] < .25 or not s["trend_ok"] or hour(s) not in HOURS):
            continue
        h_idx = int(np.searchsorted(h1["time"], s["time"], side="right") - 1)
        j = max(0, h_idx - 1)
        d = abs((hc[j] - he[j]) / ha[j]) if ha[j] > 0 else 999.0
        annotated.append((s, float(d)))

    cfg = b.Config("purged_distance", True, "proximal", .50, .25,
                   True, .50, None, max_risk=20.0, cost=.20)
    candidates = {}
    for threshold in THRESHOLDS:
        signals = [s for s, d in annotated if threshold is None or d <= threshold]
        results = [b.simulate(s, highs, lows, closes, cfg) for s in signals]
        picked = serial_pairs(signals, results)
        m1_results = [fast_m1_trade(s, highs, lows, cfg, m1_data, m1_times)
                      for s, _ in picked]
        candidates[threshold] = {"picked": picked, "m1_results": m1_results}

    folds = []
    for test_year in range(2023, 2027):
        test_start = ts(test_year)
        test_end = ts(test_year + 1)
        train_start = ts(2022)
        train_cut = test_start - HOLD_SECONDS
        test_floor = test_start + HOLD_SECONDS
        ranking = []
        for threshold, row in candidates.items():
            train = [(s, r) for (s, _), r in zip(row["picked"], row["m1_results"])
                     if train_start <= s["time"] < train_cut]
            train_m = m1.metrics([r for _, r in train])
            train_months = max(1, (test_year - 2022) * 12)
            freq = train_m["n"] / train_months
            if train_m["n"] >= 20 and train_m["r"] > 0:
                ranking.append((train_m["pf"], train_m["win_rate"],
                                train_m["n"], threshold, train_m, freq))
        ranking.sort(key=lambda x: (x[0], x[1], x[2]), reverse=True)
        selected = ranking[0][3]
        row = candidates[selected]
        test = [(s, r) for (s, _), r in zip(row["picked"], row["m1_results"])
                if test_floor <= s["time"] < test_end]
        fold = {
            "test_year": test_year,
            "train_end_utc": datetime.fromtimestamp(train_cut, tz=timezone.utc).isoformat(),
            "test_start_utc": datetime.fromtimestamp(test_floor, tz=timezone.utc).isoformat(),
            "selected_max_h1_ema_distance": selected,
            "selection_train_m1": ranking[0][4],
            "selection_train_frequency": ranking[0][5],
            "test_m1": m1.metrics([r for _, r in test]),
            "test_m5": b.metrics([r for s, r in row["picked"]
                                   if test_floor <= s["time"] < test_end]),
            "ranking": [{"max_h1_ema_distance": x[3], "train_m1": x[4],
                         "train_frequency": x[5]} for x in ranking],
        }
        folds.append(fold)
        print(json.dumps(fold, ensure_ascii=False))

    nested_m1 = []
    nested_m5 = []
    for fold in folds:
        row = candidates[fold["selected_max_h1_ema_distance"]]
        y = fold["test_year"]
        floor = ts(y) + HOLD_SECONDS
        end = ts(y + 1)
        nested_m1.extend([r for (s, _), r in zip(row["picked"], row["m1_results"])
                          if floor <= s["time"] < end])
        nested_m5.extend([r for s, r in row["picked"]
                          if floor <= s["time"] < end])
    out = {
        "zones": zones,
        "pool": len(pool),
        "hold_seconds_purged": HOLD_SECONDS,
        "thresholds": list(THRESHOLDS),
        "folds": folds,
        "nested_m1": m1.metrics(nested_m1),
        "nested_m5": b.metrics(nested_m5),
    }
    os.makedirs("reports", exist_ok=True)
    with open("reports/causal_h1_distance_purged_walkforward_20261024.json", "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)
    print(json.dumps({"nested_m1": out["nested_m1"], "nested_m5": out["nested_m5"]}, ensure_ascii=False))


if __name__ == "__main__":
    main()
