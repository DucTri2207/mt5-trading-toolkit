"""Chronological walk-forward test for the H1 EMA-distance filter.

Each test year selects a distance threshold using only prior years.  Bars are
loaded through one MT5 IPC session, then all replay calculations are local.
"""

from __future__ import annotations

import json
import os
import sys
from collections import Counter
from datetime import datetime, timezone

import MetaTrader5 as mt5
import numpy as np

sys.path.insert(0, os.path.dirname(__file__))
import backtest_causal_scalp as b
import evaluate_gold_scalp_m1 as m1
from evaluate_causal_serial_walkforward import metrics_for, serial_pairs
from evaluate_gold_scalp_m1_stability import fast_m1_trade


HOURS = {8, 9, 10, 11, 13, 15, 16, 17}
THRESHOLDS = (None, .75, 1.0, 1.25, 1.5, 1.75, 2.0, 2.5, 3.0)
BALANCE_MIN_FREQ_PER_MONTH = 2.5
BALANCE_MIN_WIN_RATE = 80.0


def load_all():
    if not mt5.initialize(timeout=60000):
        raise RuntimeError(f"MT5 initialize failed: {mt5.last_error()}")
    try:
        start = datetime(2021, 10, 23, tzinfo=timezone.utc)
        end = datetime(2026, 10, 23, 23, 59, 59, tzinfo=timezone.utc)
        h1 = mt5.copy_rates_range("XAUUSD", mt5.TIMEFRAME_H1, start, end)
        m5 = mt5.copy_rates_range("XAUUSD", mt5.TIMEFRAME_M5, start, end)
        chunks = []
        for year in range(2021, 2027):
            ys = datetime(year, 1, 1, tzinfo=timezone.utc)
            ye = datetime(year + 1, 1, 1, tzinfo=timezone.utc)
            rates = mt5.copy_rates_range("XAUUSD", mt5.TIMEFRAME_M1, ys, ye)
            if rates is None or len(rates) == 0:
                raise RuntimeError(f"No M1 data for {year}: {mt5.last_error()}")
            chunks.append(rates)
    finally:
        mt5.shutdown()
    if h1 is None or m5 is None or len(h1) == 0 or len(m5) == 0:
        raise RuntimeError("MT5 did not return XAUUSD H1/M5 data")
    m1_data = np.concatenate(chunks)
    order = np.argsort(m1_data["time"], kind="stable")
    m1_data = m1_data[order]
    _, keep = np.unique(m1_data["time"], return_index=True)
    return h1, m5, m1_data[np.sort(keep)]


def hour(signal: dict) -> int:
    return datetime.fromtimestamp(signal["time"], tz=timezone.utc).hour


def main() -> None:
    h1, m5, m1_data = load_all()
    m1_times = m1_data["time"].astype(np.int64)
    pool, zones = b.detect_candidate_pool(h1, m5)
    highs = m5["high"].astype(float)
    lows = m5["low"].astype(float)
    closes = m5["close"].astype(float)
    h1_close = h1["close"].astype(float)
    h1_atr = b.compute_wilder_atr(h1["high"].astype(float),
                                  h1["low"].astype(float), h1_close, 14)
    h1_ema = b.ema(h1_close, 50)
    cfg = b.Config("h1_distance_wf", True, "proximal", .50, .25,
                   True, .50, None, max_risk=20.0, cost=.20)

    annotated = []
    for signal in pool:
        if (signal["sweep_level"] != "proximal" or signal["wick"] < .50
                or signal["body_atr"] < .25 or not signal["trend_ok"]
                or hour(signal) not in HOURS):
            continue
        h_idx = int(np.searchsorted(h1["time"], signal["time"], side="right") - 1)
        j = max(0, h_idx - 1)
        dist = abs((h1_close[j] - h1_ema[j]) / h1_atr[j]) if h1_atr[j] > 0 else 999.0
        annotated.append((signal, float(dist)))

    candidates = {}
    for threshold in THRESHOLDS:
        signals = [s for s, d in annotated
                   if threshold is None or d <= threshold]
        m5_results = [b.simulate(s, highs, lows, closes, cfg)
                      for s in signals]
        picked = serial_pairs(signals, m5_results)
        m1_results = [fast_m1_trade(s, highs, lows, cfg, m1_data, m1_times)
                      for s, _ in picked]
        candidates[threshold] = {
            "signals": signals,
            "picked": picked,
            "m1_results": m1_results,
            "m5": metrics_for(picked),
            "m1": m1.metrics(m1_results),
            "by_year_m1": {str(y): m1.metrics(
                [r for (s, _), r in zip(picked, m1_results) if s["year"] == y])
                for y in range(2021, 2027)},
            "by_month": dict(Counter(
                datetime.fromtimestamp(s["time"], tz=timezone.utc).strftime("%Y-%m")
                for s, _ in picked)),
        }

    folds = []
    for test_year in range(2023, 2027):
        train_years = set(range(2022, test_year))
        ranking = []
        for threshold, row in candidates.items():
            train_pairs = [(s, r) for (s, _), r in zip(row["picked"], row["m1_results"])
                           if s["year"] in train_years]
            train_m1 = m1.metrics([r for _, r in train_pairs])
            if train_m1["n"] >= 20 and train_m1["r"] > 0:
                ranking.append((train_m1["pf"], train_m1["win_rate"],
                                train_m1["n"], threshold, train_m1))
        ranking.sort(key=lambda x: (x[0], x[1], x[2]), reverse=True)
        if not ranking:
            raise RuntimeError(f"No eligible threshold for test year {test_year}")
        selected = ranking[0][3]
        row = candidates[selected]
        test_pairs = [(s, r) for (s, _), r in zip(row["picked"], row["m1_results"])
                      if s["year"] == test_year]
        test_m1 = m1.metrics([r for _, r in test_pairs])
        test_m5 = metrics_for(row["picked"], {test_year})
        fold = {
            "train_years": sorted(train_years),
            "test_year": test_year,
            "selected_max_h1_ema_distance": selected,
            "selection_train_m1": ranking[0][4],
            "test_m1": test_m1,
            "test_m5": test_m5,
            "ranking": [
                {"max_h1_ema_distance": x[3], "train_m1": x[4]}
                for x in ranking
            ],
        }
        folds.append(fold)
        print(json.dumps(fold, ensure_ascii=False))

    nested_results = []
    nested_m5_results = []
    for fold in folds:
        threshold = fold["selected_max_h1_ema_distance"]
        row = candidates[threshold]
        nested_results.extend([
            r for (s, _), r in zip(row["picked"], row["m1_results"])
            if s["year"] == fold["test_year"]
        ])
        nested_m5_results.extend([
            r for s, r in row["picked"] if s["year"] == fold["test_year"]
        ])
    nested_m1 = m1.metrics(nested_results)
    nested_m5 = b.metrics(nested_m5_results)

    # A separate, pre-declared balance rule reflects the user's two goals:
    # retain at least 2.5 trades/month in the training sample and at least
    # 80% training win rate, then choose the best PF among eligible filters.
    balance_folds = []
    for test_year in range(2023, 2027):
        train_years = set(range(2022, test_year))
        ranking = []
        for threshold, row in candidates.items():
            train_pairs = [(s, r) for (s, _), r in zip(row["picked"], row["m1_results"])
                           if s["year"] in train_years]
            train_m1 = m1.metrics([r for _, r in train_pairs])
            freq = train_m1["n"] / (12.0 * len(train_years)) if train_years else 0.0
            if (freq >= BALANCE_MIN_FREQ_PER_MONTH
                    and train_m1["win_rate"] >= BALANCE_MIN_WIN_RATE
                    and train_m1["r"] > 0):
                ranking.append((train_m1["pf"], train_m1["win_rate"],
                                train_m1["n"], threshold, train_m1, freq))
        ranking.sort(key=lambda x: (x[0], x[1], x[2]), reverse=True)
        if not ranking:
            raise RuntimeError(f"No eligible balanced threshold for test year {test_year}")
        selected = ranking[0][3]
        row = candidates[selected]
        test_pairs = [(s, r) for (s, _), r in zip(row["picked"], row["m1_results"])
                      if s["year"] == test_year]
        test_m1 = m1.metrics([r for _, r in test_pairs])
        test_m5 = metrics_for(row["picked"], {test_year})
        fold = {
            "train_years": sorted(train_years),
            "test_year": test_year,
            "selected_max_h1_ema_distance": selected,
            "selection_train_m1": ranking[0][4],
            "selection_train_frequency": ranking[0][5],
            "test_m1": test_m1,
            "test_m5": test_m5,
            "ranking": [
                {"max_h1_ema_distance": x[3], "train_m1": x[4],
                 "train_frequency": x[5]}
                for x in ranking
            ],
        }
        balance_folds.append(fold)
        print("BALANCE", json.dumps(fold, ensure_ascii=False))

    balance_m1_results = []
    balance_m5_results = []
    for fold in balance_folds:
        row = candidates[fold["selected_max_h1_ema_distance"]]
        balance_m1_results.extend([
            r for (s, _), r in zip(row["picked"], row["m1_results"])
            if s["year"] == fold["test_year"]
        ])
        balance_m5_results.extend([
            r for s, r in row["picked"] if s["year"] == fold["test_year"]
        ])
    balance_nested_m1 = m1.metrics(balance_m1_results)
    balance_nested_m5 = b.metrics(balance_m5_results)

    serializable = {
        "zones": zones,
        "pool": len(pool),
        "m1_bars": len(m1_data),
        "hours_utc": sorted(HOURS),
        "thresholds": [x for x in THRESHOLDS],
        "all_candidates": {
            str(k): {"m5": v["m5"], "m1": v["m1"],
                     "by_year_m1": v["by_year_m1"],
                     "by_month": v["by_month"]}
            for k, v in candidates.items()
        },
        "folds": folds,
        "nested_m1": nested_m1,
        "nested_m5": nested_m5,
        "balance_rule": {
            "min_frequency_per_month": BALANCE_MIN_FREQ_PER_MONTH,
            "min_training_win_rate": BALANCE_MIN_WIN_RATE,
        },
        "balance_folds": balance_folds,
        "balance_nested_m1": balance_nested_m1,
        "balance_nested_m5": balance_nested_m5,
    }
    os.makedirs("reports", exist_ok=True)
    with open("reports/causal_h1_distance_walkforward_20261024.json", "w",
              encoding="utf-8") as f:
        json.dump(serializable, f, ensure_ascii=False, indent=2)


if __name__ == "__main__":
    main()
