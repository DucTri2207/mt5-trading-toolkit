"""Synthetic bar/tick fixtures (RAW_IS_UTC clock) for deterministic edge-case tests."""
import numpy as np

from quantmt5.data import Bars, Ticks, aggregate
from quantmt5.detectors import SymbolData

T0 = 1736121600  # 2025-01-06 00:00 UTC, a Monday


def bars(tf_s, start, rows, symbol="TEST", tf="M5"):
    """rows: list of (o,h,l,c) or (o,h,l,c,vol,spread)."""
    n = len(rows)
    a = np.array([r[:4] for r in rows], dtype=float)
    vol = np.array([r[4] if len(r) > 4 else 100 for r in rows], dtype=np.int64)
    spr = np.array([r[5] if len(r) > 5 else 5 for r in rows], dtype=np.int64)
    op = start + tf_s * np.arange(n, dtype=np.int64)
    return Bars(symbol, tf, open_raw=op.copy(), open_at=op.copy(), close_at=op + tf_s, available_at=op + tf_s + 1,
                o=a[:, 0], h=a[:, 1], l=a[:, 2], c=a[:, 3], tick_volume=vol, real_volume=np.zeros(n, np.int64),
                spread=spr, provenance={"clock_profile": "RAW_IS_UTC", "kind": "SYNTHETIC", "dataset_id": "synthetic"})


def flat_m5(n, price=100.0, half_range=0.5, start=T0):
    return [(price, price + half_range, price - half_range, price)] * n


PROF = {"trade_tick_size": 0.01, "point": 0.01, "digits": 2, "contract_size": 100.0, "profit_currency": "USD",
        "stops_level_points": 0, "session": {}}


def symbol_data(m5_rows, start=T0, m1=None, prof=None):
    m5 = bars(300, start, m5_rows)
    h1 = aggregate(m5, "H1")
    d1 = aggregate(m5, "D1")
    return SymbolData("TEST", m5, h1, d1, m1, 0.01, prof or dict(PROF), "synthetic_source")


def ticks(rows, symbol="TEST"):
    """rows: (t_seconds_float, bid, ask)."""
    t = np.array([int(round(r[0] * 1000)) for r in rows], dtype=np.int64)
    return Ticks(symbol, t, np.array([r[1] for r in rows], float), np.array([r[2] for r in rows], float), np.zeros(len(rows), np.int64))
