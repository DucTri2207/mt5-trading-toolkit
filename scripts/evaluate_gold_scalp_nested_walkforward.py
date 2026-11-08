"""Nested chronological walk-forward for the XAUUSD session-hour choice.

The hour rule is selected using only years before each test year.  This keeps
the final test years separate from the choice of the session filter and
reports both M5 causal and M1 replay outcomes.
"""

from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(__file__))
import backtest_causal_scalp as b
import evaluate_gold_scalp_m1 as m1
from evaluate_causal_serial_walkforward import metrics_for, serial_pairs


HOUR_SETS = {
    "base_08_12_13_17": set(range(8, 13)) | set(range(13, 18)),
    "exclude_12_14": {8, 9, 10, 11, 13, 15, 16, 17},
    "exclude_14": {8, 9, 10, 11, 12, 13, 15, 16, 17},
    "peak_10_11_13_15_17": {10, 11, 13, 15, 16, 17},
    "us_no14": {13, 15, 16, 17},
}


def hour(signal: dict) -> int:
    return datetime.fromtimestamp(signal["time"], tz=timezone.utc).hour


def main() -> None:
    h1, m5 = b.load_data()
    m1_data = m1.load_m1()
    pool, zones = b.detect_candidate_pool(h1, m5)
    highs = m5["high"].astype(float)
    lows = m5["low"].astype(float)
    closes = m5["close"].astype(float)
    cfg = b.Config("nested_session", True, "proximal", .50, .25,
                   True, .50, None, max_risk=20.0, cost=.20)
    base_signals = [s for s in pool if s["sweep_level"] == "proximal"
                    and s["wick"] >= .50 and s["body_atr"] >= .25
                    and s["trend_ok"]]
    m5_cache = {s["idx"]: b.simulate(s, highs, lows, closes, cfg)
                for s in base_signals}
    m1_cache = {s["idx"]: m1.m1_trade(s, highs, lows, cfg, m1_data)
                for s in base_signals}

    def candidate_pairs(name: str):
        signals = [s for s in base_signals if hour(s) in HOUR_SETS[name]]
        results = [m5_cache[s["idx"]] for s in signals]
        return signals, results, serial_pairs(signals, results)

    all_rows = {}
    for name in HOUR_SETS:
        signals, results, pairs = candidate_pairs(name)
        all_rows[name] = {
            "raw": len(signals),
            "all_m5": metrics_for(pairs),
            "years_m5": {str(y): metrics_for(pairs, {y})
                          for y in range(2021, 2027)},
            "years_m1": {
                str(y): m1.metrics([m1_cache[s["idx"]]
                                    for s, _ in pairs if s["year"] == y])
                for y in range(2021, 2027)
            },
        }

    folds = []
    # A partial 2021 is too small to train on; begin with 2023.
    for test_year in range(2023, 2027):
        train_years = set(range(2022, test_year))
        ranking = []
        for name in HOUR_SETS:
            train_m = all_rows[name]["years_m5"]
            train_n = sum(train_m[str(y)]["n"] for y in train_years)
            train_wins = sum(train_m[str(y)]["wins"] for y in train_years)
            train_losses = sum(train_m[str(y)]["losses"] for y in train_years)
            train_r = sum(train_m[str(y)]["r"] for y in train_years)
            gp = sum(max(0.0, train_m[str(y)]["r"]) for y in train_years)
            # Recompute PF from the yearly R totals is insufficient, so use
            # the full candidate pairs filtered to the training years.
            _, _, pairs = candidate_pairs(name)
            train_metrics = metrics_for(pairs, train_years)
            if train_metrics["n"] >= 20 and train_metrics["r"] > 0:
                ranking.append((train_metrics["pf"], train_metrics["win_rate"],
                                train_metrics["n"], name, train_metrics))
        ranking.sort(reverse=True)
        selected = ranking[0][3]
        selected_pairs = candidate_pairs(selected)[2]
        folds.append({
            "train_years": sorted(train_years),
            "test_year": test_year,
            "selected": selected,
            "selection_train_m5": ranking[0][4],
            "test_m5": metrics_for(selected_pairs, {test_year}),
            "test_m1": all_rows[selected]["years_m1"][str(test_year)],
            "ranking": [
                {"name": r[3], "train_m5": r[4]}
                for r in ranking
            ],
        })
        print(json.dumps(folds[-1], ensure_ascii=False))

    os.makedirs("reports", exist_ok=True)
    with open("reports/causal_nested_session_walkforward_20261024.json", "w",
              encoding="utf-8") as f:
        json.dump({"zones": zones, "pool": len(pool), "candidates": all_rows,
                   "folds": folds}, f, ensure_ascii=False, indent=2)


if __name__ == "__main__":
    main()
