"""Rolling calendar-window stability check for the locked 1.75 ATR preset."""

from __future__ import annotations

import calendar
import json
import os
from datetime import datetime, timezone


INPUT = "reports/causal_h1_distance_robustness_20261024.json"
OUTPUT = "reports/causal_rolling_stability_20261024.json"


def month_add(year: int, month: int, offset: int) -> tuple[int, int]:
    n = year * 12 + (month - 1) + offset
    return n // 12, n % 12 + 1


def month_key(year: int, month: int) -> str:
    return f"{year:04d}-{month:02d}"


def metrics(trades: list[dict]) -> dict:
    rs = [float(x.get("r", 0.0)) for x in trades]
    wins = sum(x > 1e-9 for x in rs)
    gross_profit = sum(x for x in rs if x > 1e-9)
    gross_loss = -sum(x for x in rs if x < -1e-9)
    curve = []
    total = 0.0
    for r in rs:
        total += r
        curve.append(total)
    dd = max((max(curve[:i + 1]) - curve[i] for i in range(len(curve))), default=0.0)
    return {
        "n": len(rs),
        "wins": wins,
        "win_rate": 100.0 * wins / len(rs) if rs else 0.0,
        "r": sum(rs),
        "pf": gross_profit / gross_loss if gross_loss else (999.0 if gross_profit else 0.0),
        "dd": dd,
    }


def main() -> None:
    with open(INPUT, encoding="utf-8") as f:
        report = json.load(f)
    trades = sorted(report["trades"], key=lambda x: int(x["time"]))
    months = [month_key(y, m) for y in range(2021, 2027)
              for m in range(1, 13)]
    # Keep only complete calendar windows that intersect the 5-year sample.
    first = "2021-10"
    last = "2026-10"
    months = [x for x in months if first <= x <= last]
    windows = []
    for i in range(len(months) - 11):
        start = months[i]
        end = months[i + 11]
        q = [x for x in trades if start <= x["month"] <= end]
        m = metrics(q)
        m.update({"start_month": start, "end_month": end,
                  "frequency_per_month": m["n"] / 12.0})
        windows.append(m)
    worst_wr = min(windows, key=lambda x: (x["win_rate"], x["n"]))
    worst_pf = min(windows, key=lambda x: (x["pf"], x["n"]))
    lowest_frequency = min(windows, key=lambda x: x["frequency_per_month"])
    out = {
        "source": INPUT,
        "preset": report["preset"],
        "window_months": 12,
        "windows": windows,
        "summary": {
            "worst_win_rate_window": worst_wr,
            "worst_pf_window": worst_pf,
            "lowest_frequency_window": lowest_frequency,
        },
    }
    os.makedirs("reports", exist_ok=True)
    with open(OUTPUT, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)
    print(json.dumps(out["summary"], ensure_ascii=False))
    print(f"saved {OUTPUT}")


if __name__ == "__main__":
    main()
