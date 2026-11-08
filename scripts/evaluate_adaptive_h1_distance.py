"""Test conditional H1 EMA-distance relaxations for the XAUUSD scalp.

This is a research-only extension of the locked 1.75 ATR preset.  It tests
whether a looser H1 distance threshold in a pre-registered set of hours can
add frequency without sacrificing the out-of-sample M1 result.  Selection is
chronological and uses only earlier years; no indicator or live monitor is
changed by this script.
"""

from __future__ import annotations

import json
import os
import sys
from dataclasses import dataclass
from datetime import datetime, timezone

import numpy as np

sys.path.insert(0, os.path.dirname(__file__))
import backtest_causal_scalp as b
import evaluate_gold_scalp_m1 as m1
from evaluate_causal_serial_walkforward import metrics_for, serial_pairs
from evaluate_gold_scalp_m1_stability import fast_m1_trade


BASE_HOURS = {8, 9, 10, 11, 13, 15, 16, 17}


@dataclass(frozen=True)
class Policy:
    name: str
    hours: frozenset[int]
    base_distance: float
    relaxed_hours: frozenset[int]
    relaxed_distance: float
    min_wick: float = .50
    min_body: float = .25


def hour(signal: dict) -> int:
    return datetime.fromtimestamp(signal["time"], tz=timezone.utc).hour


def policies() -> list[Policy]:
    """Pre-register a small family before reading outcomes.

    The first three are fixed thresholds.  The remaining policies relax only
    in groups of hours that are plausible session hypotheses, so the result is
    not a search over arbitrary per-hour switches.
    """
    return [
        Policy("fixed_175", frozenset(BASE_HOURS), 1.75, frozenset(), 1.75),
        Policy("fixed_200", frozenset(BASE_HOURS), 2.00, frozenset(), 2.00),
        Policy("fixed_225", frozenset(BASE_HOURS), 2.25, frozenset(), 2.25),
        Policy("fixed_200_no_09", frozenset(BASE_HOURS - {9}), 2.00,
               frozenset(), 2.00),
        Policy("fixed_225_no_09", frozenset(BASE_HOURS - {9}), 2.25,
               frozenset(), 2.25),
        Policy("fixed_200_no_09_16", frozenset(BASE_HOURS - {9, 16}), 2.00,
               frozenset(), 2.00),
        Policy("fixed_225_no_09_16", frozenset(BASE_HOURS - {9, 16}), 2.25,
               frozenset(), 2.25),
        Policy("fixed_200_peak_no_16", frozenset({10, 11, 13, 15, 17}), 2.00,
               frozenset(), 2.00),
        Policy("fixed_225_peak_no_16", frozenset({10, 11, 13, 15, 17}), 2.25,
               frozenset(), 2.25),
        Policy("fixed_200_us_no14", frozenset({13, 15, 16, 17}), 2.00,
               frozenset(), 2.00),
        Policy("fixed_225_us_no14", frozenset({13, 15, 16, 17}), 2.25,
               frozenset(), 2.25),
        Policy("fixed_200_no_09_w55", frozenset(BASE_HOURS - {9}), 2.00,
               frozenset(), 2.00, .55, .25),
        Policy("fixed_200_no_09_d35", frozenset(BASE_HOURS - {9}), 2.00,
               frozenset(), 2.00, .50, .35),
        Policy("fixed_200_no_09_w55_d35", frozenset(BASE_HOURS - {9}), 2.00,
               frozenset(), 2.00, .55, .35),
        Policy("fixed_225_no_09_w55", frozenset(BASE_HOURS - {9}), 2.25,
               frozenset(), 2.25, .55, .25),
        Policy("fixed_225_no_09_d35", frozenset(BASE_HOURS - {9}), 2.25,
               frozenset(), 2.25, .50, .35),
        Policy("relax_200_core_10111317", frozenset(BASE_HOURS), 1.75,
               frozenset({10, 11, 13, 17}), 2.00),
        Policy("relax_225_core_10111317", frozenset(BASE_HOURS), 1.75,
               frozenset({10, 11, 13, 17}), 2.25),
        Policy("relax_200_core_1011131517", frozenset(BASE_HOURS), 1.75,
               frozenset({10, 11, 13, 15, 17}), 2.00),
        Policy("relax_225_core_1011131517", frozenset(BASE_HOURS), 1.75,
               frozenset({10, 11, 13, 15, 17}), 2.25),
        Policy("relax_200_no_09_16", frozenset(BASE_HOURS - {9, 16}), 1.75,
               frozenset({10, 11, 13, 15, 17}), 2.00),
        Policy("relax_225_no_09_16", frozenset(BASE_HOURS - {9, 16}), 1.75,
               frozenset({10, 11, 13, 15, 17}), 2.25),
        Policy("relax_200_peak", frozenset({10, 11, 13, 15, 16, 17}), 1.75,
               frozenset({10, 11, 13, 17}), 2.00),
        Policy("relax_225_peak", frozenset({10, 11, 13, 15, 16, 17}), 1.75,
               frozenset({10, 11, 13, 17}), 2.25),
    ]


def annotate(h1, pool: list[dict]) -> list[tuple[dict, float]]:
    hc = h1["close"].astype(float)
    ha = b.compute_wilder_atr(h1["high"].astype(float),
                              h1["low"].astype(float), hc, 14)
    he = b.ema(hc, 50)
    out = []
    for signal in pool:
        if signal["sweep_level"] != "proximal" or not signal["trend_ok"]:
            continue
        h_idx = int(np.searchsorted(h1["time"], signal["time"], side="right") - 1)
        j = max(0, h_idx - 1)
        distance = abs((hc[j] - he[j]) / ha[j]) if ha[j] > 0 else 999.0
        out.append((signal, float(distance)))
    return out


def evaluate_policy(policy: Policy, annotated, m5, m1_data):
    signals = []
    for signal, distance in annotated:
        h = hour(signal)
        threshold = policy.relaxed_distance if h in policy.relaxed_hours else policy.base_distance
        if (h in policy.hours and signal["wick"] >= policy.min_wick
                and signal["body_atr"] >= policy.min_body
                and distance <= threshold):
            signals.append(signal)

    highs = m5["high"].astype(float)
    lows = m5["low"].astype(float)
    closes = m5["close"].astype(float)
    cfg = b.Config(policy.name, True, "proximal", .50, .25, True,
                   .50, None, max_risk=20.0, cost=.20)
    m5_results = [b.simulate(s, highs, lows, closes, cfg) for s in signals]
    picked = serial_pairs(signals, m5_results)
    m1_times = m1_data["time"].astype(np.int64)
    m1_results = [fast_m1_trade(s, highs, lows, cfg, m1_data, m1_times)
                  for s, _ in picked]
    years = sorted({s["year"] for s, _ in picked})
    return {
        "policy": policy.name,
        "hours_utc": sorted(policy.hours),
        "base_distance": policy.base_distance,
        "relaxed_hours": sorted(policy.relaxed_hours),
        "relaxed_distance": policy.relaxed_distance,
        "min_wick": policy.min_wick,
        "min_body": policy.min_body,
        "raw_signals": len(signals),
        "m5": metrics_for(picked),
        "m1": m1.metrics(m1_results),
        "by_year_m1": {
            str(y): m1.metrics([r for (s, _), r in zip(picked, m1_results)
                                if s["year"] == y])
            for y in years
        },
        "by_year_m5": {
            str(y): metrics_for(picked, {y}) for y in years
        },
        "by_hour_m1": {
            str(h): m1.metrics([r for (s, _), r in zip(picked, m1_results)
                                if hour(s) == h])
            for h in sorted(policy.hours)
        },
        "picked": picked,
        "m1_results": m1_results,
    }


def public_row(row: dict) -> dict:
    return {k: v for k, v in row.items() if k not in {"picked", "m1_results"}}


def main() -> None:
    h1, m5 = b.load_data()
    m1_data = m1.load_m1()
    pool, zones = b.detect_candidate_pool(h1, m5)
    annotated = annotate(h1, pool)
    print(f"zones={zones} pool={len(pool)} annotated_core={len(annotated)} m1={len(m1_data)}")

    rows = []
    candidates = {}
    for policy in policies():
        row = evaluate_policy(policy, annotated, m5, m1_data)
        candidates[policy.name] = row
        rows.append(public_row(row))
        print(json.dumps(public_row(row), ensure_ascii=False))

    # Nested chronological selection.  Frequency is an explicit constraint,
    # not a post-hoc preference: eligible train policies need >=2.5/month and
    # >=80% train win rate, then the highest train PF is selected.
    folds = []
    for test_year in range(2023, 2027):
        train_years = set(range(2022, test_year))
        ranking = []
        for name, row in candidates.items():
            train = [r for (s, _), r in zip(row["picked"], row["m1_results"])
                     if s["year"] in train_years]
            train_m = m1.metrics(train)
            frequency = train_m["n"] / (12.0 * len(train_years))
            if (frequency >= 2.5 and train_m["win_rate"] >= 80.0
                    and train_m["r"] > 0):
                ranking.append((train_m["pf"], train_m["win_rate"],
                                train_m["n"], name, train_m, frequency))
        ranking.sort(key=lambda x: (x[0], x[1], x[2]), reverse=True)
        if not ranking:
            raise RuntimeError(f"No eligible adaptive policy for test year {test_year}")
        selected = ranking[0][3]
        row = candidates[selected]
        test = [r for (s, _), r in zip(row["picked"], row["m1_results"])
                if s["year"] == test_year]
        fold = {
            "test_year": test_year,
            "train_years": sorted(train_years),
            "selected": selected,
            "selection_train_m1": ranking[0][4],
            "selection_train_frequency": ranking[0][5],
            "test_m1": m1.metrics(test),
            "test_m5": metrics_for(row["picked"], {test_year}),
            "ranking": [{"policy": x[3], "train_m1": x[4],
                         "train_frequency": x[5]} for x in ranking],
        }
        folds.append(fold)
        print("WF", json.dumps(fold, ensure_ascii=False))

    nested_m1 = []
    nested_m5 = []
    for fold in folds:
        row = candidates[fold["selected"]]
        nested_m1.extend([r for (s, _), r in zip(row["picked"], row["m1_results"])
                          if s["year"] == fold["test_year"]])
        nested_m5.extend([r for s, r in row["picked"]
                          if s["year"] == fold["test_year"]])

    serializable = {
        "zones": zones,
        "pool": len(pool),
        "annotated_core": len(annotated),
        "m1_bars": len(m1_data),
        "base_hours_utc": sorted(BASE_HOURS),
        "rows": rows,
        "walkforward": {
            "folds": folds,
            "nested_m1": m1.metrics(nested_m1),
            "nested_m5": b.metrics(nested_m5),
            "rule": {"min_frequency_per_month": 2.5,
                     "min_training_win_rate": 80.0},
        },
    }
    os.makedirs("reports", exist_ok=True)
    with open("reports/causal_adaptive_h1_distance_20261024.json", "w",
              encoding="utf-8") as f:
        json.dump(serializable, f, ensure_ascii=False, indent=2)
    print("saved reports/causal_adaptive_h1_distance_20261024.json")


if __name__ == "__main__":
    main()
