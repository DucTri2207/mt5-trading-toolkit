"""Quantify uncertainty around the candidate winrates from the M1 replay.

This reads the already-saved adaptive-policy report and does not access MT5 or
change the running paper monitor.  Jeffreys Beta posteriors and Wilson
intervals are descriptive evidence, not a profitability guarantee.
"""

from __future__ import annotations

import json
import math
import os

from scipy.stats import beta, betabinom


REPORT = "reports/causal_adaptive_h1_distance_20261024.json"
OUTPUT = "reports/causal_posterior_uncertainty_20261024.json"
POLICIES = [
    "fixed_175",
    "fixed_200_no_09",
    "fixed_200_no_09_16",
    "fixed_200_peak_no_16",
    "fixed_225_no_09",
]


def wilson(wins: int, n: int, z: float = 1.959963984540054) -> list[float]:
    if n <= 0:
        return [0.0, 0.0]
    p = wins / n
    den = 1.0 + z * z / n
    centre = (p + z * z / (2.0 * n)) / den
    half = z * math.sqrt(p * (1.0 - p) / n + z * z / (4.0 * n * n)) / den
    return [100.0 * max(0.0, centre - half), 100.0 * min(1.0, centre + half)]


def stats(wins: int, n: int) -> dict:
    losses = n - wins
    a = wins + 0.5
    b = losses + 0.5
    # Posterior predictive chance of at least 20 wins in the next 25 trades.
    next_25 = float(betabinom.sf(19, 25, a, b)) if n else 0.0
    return {
        "n": n,
        "wins": wins,
        "win_rate": 100.0 * wins / n if n else 0.0,
        "wilson_95": wilson(wins, n),
        "jeffreys_p_true_rate_ge_75": float(beta.sf(.75, a, b)) if n else 0.0,
        "jeffreys_p_true_rate_ge_80": float(beta.sf(.80, a, b)) if n else 0.0,
        "posterior_predictive_next25_at_least20_wins": next_25,
    }


def row_counts(row: dict, years: set[int]) -> tuple[int, int]:
    n = wins = 0
    for year in years:
        m = row["by_year_m1"].get(str(year), {})
        n += int(m.get("n", 0))
        wins += int(m.get("wins", 0))
    return wins, n


def main() -> None:
    with open(REPORT, encoding="utf-8") as f:
        report = json.load(f)
    rows = {row["policy"]: row for row in report["rows"]}
    out = {
        "method": "Jeffreys Beta(0.5,0.5) posterior; Wilson 95% interval; Beta-binomial predictive",
        "thresholds": {"target_win_rate": .80, "predictive_n": 25, "predictive_wins": 20},
        "policies": {},
    }
    for name in POLICIES:
        row = rows[name]
        full_w, full_n = row_counts(row, {2021, 2022, 2023, 2024, 2025, 2026})
        oos_w, oos_n = row_counts(row, {2025, 2026})
        out["policies"][name] = {
            "monthly_frequency_5y": full_n / 60.0,
            "full": stats(full_w, full_n),
            "oos_2025_2026": stats(oos_w, oos_n),
        }
        print(name, json.dumps(out["policies"][name], ensure_ascii=False))
    os.makedirs("reports", exist_ok=True)
    with open(OUTPUT, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)
    print(f"saved {OUTPUT}")


if __name__ == "__main__":
    main()
