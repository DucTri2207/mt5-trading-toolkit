"""Read-only forward paper monitor for the locked XAUUSD v3.12 preset.

The monitor never sends orders.  It polls closed H1/M5 data, detects the same
causal candidates as the research harness, records new signals, and resolves
each paper result only after the full 72-bar holding window is available.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import MetaTrader5 as mt5
import numpy as np

sys.path.insert(0, os.path.dirname(__file__))
import backtest_causal_scalp as b


DISTANCE_ATR = 1.75
HOURS = {8, 9, 10, 11, 13, 15, 16, 17}
M5_BARS = 40000
H1_BARS = 3500
POLL_SECONDS = 60


def parse_args():
    p = argparse.ArgumentParser()
    p.add_argument("--once", action="store_true", help="poll once then exit")
    p.add_argument("--poll-seconds", type=int, default=POLL_SECONDS)
    p.add_argument("--state", default="reports/paper_shadow_trades_20261024.json")
    return p.parse_args()


def load_state(path: Path):
    if not path.exists():
        return {"version": 1, "preset": {"distance_atr": DISTANCE_ATR,
                "hours_utc": sorted(HOURS), "cost": 0.20}, "trades": []}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict) or not isinstance(data.get("trades"), list):
            raise ValueError("invalid state shape")
        return data
    except Exception as exc:
        raise RuntimeError(f"Cannot read paper state {path}: {exc}") from exc


def save_state(path: Path, state):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)


def ensure_connection():
    if mt5.terminal_info() is not None:
        return True
    if mt5.initialize(timeout=30000):
        return True
    print("MT5 initialize failed:", mt5.last_error(), flush=True)
    return False


def load_rates():
    h1 = mt5.copy_rates_from_pos("XAUUSD", mt5.TIMEFRAME_H1, 0, H1_BARS)
    m5 = mt5.copy_rates_from_pos("XAUUSD", mt5.TIMEFRAME_M5, 0, M5_BARS)
    if h1 is None or m5 is None or len(h1) < 100 or len(m5) < 500:
        raise RuntimeError(f"MT5 rates unavailable: {mt5.last_error()}")
    h1 = h1[np.argsort(h1["time"], kind="stable")]
    m5 = m5[np.argsort(m5["time"], kind="stable")]
    return h1, m5


def annotate_signals(h1, m5):
    pool, zones = b.detect_candidate_pool(h1, m5)
    h1_close = h1["close"].astype(float)
    h1_atr = b.compute_wilder_atr(h1["high"].astype(float),
                                  h1["low"].astype(float), h1_close, 14)
    h1_ema = b.ema(h1_close, 50)
    selected = []
    for signal in pool:
        if (signal["sweep_level"] != "proximal" or signal["wick"] < .50
                or signal["body_atr"] < .25 or not signal["trend_ok"]):
            continue
        hour = datetime.fromtimestamp(signal["time"], tz=timezone.utc).hour
        if hour not in HOURS:
            continue
        h_idx = int(np.searchsorted(h1["time"], signal["time"], side="right") - 1)
        j = max(0, h_idx - 1)
        distance = abs((h1_close[j] - h1_ema[j]) / h1_atr[j]) if h1_atr[j] > 0 else 999.0
        if distance <= DISTANCE_ATR:
            copy = dict(signal)
            copy["h1_distance_atr"] = float(distance)
            selected.append(copy)
    return selected, zones


def spread_snapshot():
    tick = mt5.symbol_info_tick("XAUUSD")
    if tick is None:
        return {"bid": None, "ask": None, "spread": None}
    bid = float(tick.bid)
    ask = float(tick.ask)
    return {"bid": bid, "ask": ask, "spread": ask - bid if bid > 0 and ask > 0 else None}


def poll(state):
    h1, m5 = load_rates()
    signals, zones = annotate_signals(h1, m5)
    highs = m5["high"].astype(float)
    lows = m5["low"].astype(float)
    closes = m5["close"].astype(float)
    cfg = b.Config("paper_v3_12", True, "proximal", .50, .25,
                   True, .50, None, max_risk=20.0, cost=0.20)
    # Causal serial selection over the available history prevents overlapping
    # paper trades from inflating forward frequency.
    m5_results = [b.simulate(s, highs, lows, closes, cfg) for s in signals]
    last_exit = -1
    picked = []
    for signal, result in sorted(zip(signals, m5_results), key=lambda x: x[0]["idx"]):
        if result["status"] == "REJECT_RISK" or signal["idx"] <= last_exit:
            continue
        picked.append((signal, result))
        # Use the actual historical exit when the full holding window is
        # available.  Only a still-open forward signal reserves its planned
        # 72-bar window; otherwise the monitor would undercount frequency
        # relative to the causal replay whenever a trade exits early.
        if signal["idx"] + cfg.hold_bars < len(m5):
            last_exit = int(result.get("exit_idx", signal["idx"] + cfg.hold_bars))
        else:
            last_exit = signal["idx"] + cfg.hold_bars
    existing = {str(row["time"]): row for row in state["trades"]}
    current_tick = spread_snapshot()
    now = int(datetime.now(tz=timezone.utc).timestamp())
    changed = False
    max_signal_time = max((int(s["time"]) for s, _ in picked), default=0)
    # On the first run, seed the cursor at the latest already-closed signal so
    # the monitor starts a genuine forward sample instead of counting history
    # loaded for context as new paper trades.
    if not state.get("initialized"):
        state["initialized"] = True
        state["last_seen_signal_time"] = max_signal_time
        state["last_poll_utc"] = datetime.now(tz=timezone.utc).isoformat()
        return True, len(picked), 0
    # Add signals that have become new since the previous poll.  Do not add a
    # candidate whose outcome window is already entirely outside our history.
    for signal, result in picked:
        key = str(int(signal["time"]))
        if key in existing or int(signal["time"]) <= int(state.get("last_seen_signal_time", 0)):
            continue
        row = {
            "time": int(signal["time"]),
            "time_utc": datetime.fromtimestamp(signal["time"], tz=timezone.utc).isoformat(),
            "year": int(signal["year"]),
            "buy": bool(signal["buy"]),
            "h1_distance_atr": float(signal["h1_distance_atr"]),
            "entry_model": float(signal["entry"]),
            "risk_model": float(result.get("risk", 0.0)),
            "status": "PENDING" if signal["idx"] + cfg.hold_bars >= len(m5) else result["status"],
            "r": None if signal["idx"] + cfg.hold_bars >= len(m5) else float(result["r"]),
            "detected_at_utc": datetime.fromtimestamp(now, tz=timezone.utc).isoformat(),
            "spread_snapshot": current_tick,
            "zones_seen": zones,
        }
        state["trades"].append(row)
        existing[key] = row
        changed = True
    # Resolve pending records once the full hold window is available.
    by_time = {int(s["time"]): (s, r) for s, r in picked}
    for row in state["trades"]:
        if row.get("status") != "PENDING":
            continue
        pair = by_time.get(int(row["time"]))
        if pair is None:
            continue
        signal, result = pair
        if signal["idx"] + cfg.hold_bars < len(m5):
            row["status"] = result["status"]
            row["r"] = float(result["r"])
            row["resolved_at_utc"] = datetime.now(tz=timezone.utc).isoformat()
            changed = True
    state["last_poll_utc"] = datetime.now(tz=timezone.utc).isoformat()
    state["last_seen_signal_time"] = max(max_signal_time,
                                          int(state.get("last_seen_signal_time", 0)))
    state["last_signal_count"] = len(picked)
    return changed, len(picked), sum(1 for row in state["trades"] if row.get("status") == "PENDING")


def main():
    args = parse_args()
    path = Path(args.state)
    state = load_state(path)
    if not ensure_connection():
        raise SystemExit(2)
    try:
        while True:
            try:
                changed, total, pending = poll(state)
                save_state(path, state)
                print(json.dumps({"utc": state["last_poll_utc"], "changed": changed,
                                  "signals": total, "pending": pending,
                                  "trades_logged": len(state["trades"])},
                                 ensure_ascii=False), flush=True)
            except Exception as exc:
                print("paper poll error:", repr(exc), flush=True)
            if args.once:
                break
            time.sleep(max(10, args.poll_seconds))
    finally:
        mt5.shutdown()


if __name__ == "__main__":
    main()
