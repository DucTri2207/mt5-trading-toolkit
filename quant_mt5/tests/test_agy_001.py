import datetime as dt
import time
from collections import Counter

import numpy as np
import pytest

from quantmt5.data import Ticks
from quantmt5.evaluate import metrics
from quantmt5.execution import TickQuotes


def make_tq(rows, kind="SYNTHETIC_FIXTURE", source="fixture"):
    t = np.array([int(round(r[0] * 1000)) for r in rows], np.int64)
    av = np.array([int(round((r[3] if len(r) > 3 else r[0]) * 1000)) for r in rows], np.int64)
    ticks = Ticks("T", t, np.array([r[1] for r in rows], float), np.array([r[2] for r in rows], float), np.zeros(len(rows), np.int64))
    return TickQuotes(ticks, av, kind=kind, source=source)


def test_version_id_changes_when_any_quote_value_changes():
    rows = [(1000.0, 1.1000, 1.1002, 1000.0), (1001.0, 1.1001, 1.1003, 1001.0)]
    base_q = make_tq(rows)
    base_v = base_q.version_id()

    # Dữ liệu y hệt -> giống nhau
    same_q = make_tq([(1000.0, 1.1000, 1.1002, 1000.0), (1001.0, 1.1001, 1.1003, 1001.0)])
    assert same_q.version_id() == base_v

    # Đổi 1 giá trị của bid
    mod_bid = make_tq([(1000.0, 1.1005, 1.1002, 1000.0), (1001.0, 1.1001, 1.1003, 1001.0)])
    assert mod_bid.version_id() != base_v

    # Đổi 1 giá trị của ask
    mod_ask = make_tq([(1000.0, 1.1000, 1.1008, 1000.0), (1001.0, 1.1001, 1.1003, 1001.0)])
    assert mod_ask.version_id() != base_v

    # Đổi 1 giá trị của thời điểm t
    mod_t = make_tq([(1000.5, 1.1000, 1.1002, 1000.5), (1001.0, 1.1001, 1.1003, 1001.0)])
    assert mod_t.version_id() != base_v

    # Đổi 1 giá trị của available_ms
    mod_av = make_tq([(1000.0, 1.1000, 1.1002, 1000.5), (1001.0, 1.1001, 1.1003, 1001.0)])
    assert mod_av.version_id() != base_v


def test_version_id_is_cached_and_fast():
    n = 1_000_000
    t = np.arange(n, dtype=np.int64) * 100
    bid = np.full(n, 100.0, dtype=float)
    ask = bid + 0.01
    flags = np.zeros(n, dtype=np.int64)
    ticks = Ticks("T", t, bid, ask, flags)
    q = TickQuotes(ticks, kind="SYNTHETIC_FIXTURE", source="fixture")

    t0 = time.perf_counter()
    v1 = q.version_id()
    dt1 = time.perf_counter() - t0

    t0 = time.perf_counter()
    v2 = q.version_id()
    dt2 = time.perf_counter() - t0

    assert v1 == v2
    assert dt1 < 0.5
    assert dt2 < 0.01


def test_version_id_length_16():
    rows = [(1000.0, 100.0, 100.05, 1000.0)]
    q = make_tq(rows)
    v = q.version_id()
    assert isinstance(v, str)
    assert len(v) == 16


def test_metrics_reports_unresolved_fills():
    r_pos = {
        "status": "FILLED",
        "net_R": 1.0,
        "fill_at": "2026-11-03T14:00:00Z",
        "side": "LONG",
        "symbol": "EURUSD",
        "primary": {"exit_at": "2026-11-03T15:00:00Z", "hold_s": 3600.0, "exit_reason": "TP"},
        "mae_R": -0.2,
        "mfe_R": 1.5,
        "cost_over_R": 0.02,
        "spread_over_R": 0.05,
        "entry_drift_over_atr": 0.01,
    }
    r_neg = {
        "status": "FILLED",
        "net_R": -1.0,
        "fill_at": "2026-11-03T14:30:00Z",
        "side": "SHORT",
        "symbol": "EURUSD",
        "primary": {"exit_at": "2026-11-03T15:30:00Z", "hold_s": 3600.0, "exit_reason": "SL"},
        "mae_R": -1.0,
        "mfe_R": 0.1,
        "cost_over_R": 0.02,
        "spread_over_R": 0.05,
        "entry_drift_over_atr": 0.01,
    }
    r_unres_exit = {
        "status": "FILLED",
        "net_R": None,
        "flags": ["EXIT_UNRESOLVED"],
        "fill_at": "2026-11-03T14:45:00Z",
        "side": "LONG",
        "symbol": "EURUSD",
        "primary": {"exit_at": None, "hold_s": None, "exit_reason": "UNRESOLVED"},
        "mae_R": 0.0,
        "mfe_R": 0.0,
        "spread_over_R": 0.0,
        "entry_drift_over_atr": 0.0,
    }
    r_unres_comm = {
        "status": "FILLED",
        "net_R": None,
        "flags": ["COMMISSION_UNKNOWN"],
        "fill_at": "2026-11-03T15:00:00Z",
        "side": "SHORT",
        "symbol": "EURUSD",
        "primary": {"exit_at": None, "hold_s": None, "exit_reason": "COMMISSION_UNKNOWN"},
        "mae_R": 0.0,
        "mfe_R": 0.0,
        "spread_over_R": 0.0,
        "entry_drift_over_atr": 0.0,
    }

    ledger = [r_pos, r_neg, r_unres_exit, r_unres_comm]
    days = [dt.date(2026, 11, 3)]
    m = metrics(ledger, days, Counter())

    assert m["n_fills"] == 2
    assert m["net_R_total"] == 0.0
    assert m["n_fills_unresolved"] == 2
    assert m["unresolved_reasons"] == {"EXIT_UNRESOLVED": 1, "COMMISSION_UNKNOWN": 1}


def test_metrics_unchanged_for_resolved_only():
    r1 = {
        "status": "FILLED",
        "net_R": 1.5,
        "fill_at": "2026-11-03T14:00:00Z",
        "side": "LONG",
        "symbol": "EURUSD",
        "primary": {"exit_at": "2026-11-03T15:00:00Z", "hold_s": 3600.0, "exit_reason": "TP"},
        "mae_R": -0.1,
        "mfe_R": 1.5,
        "cost_over_R": 0.02,
        "spread_over_R": 0.04,
        "entry_drift_over_atr": 0.01,
    }
    r2 = {
        "status": "FILLED",
        "net_R": -1.0,
        "fill_at": "2026-11-03T14:30:00Z",
        "side": "SHORT",
        "symbol": "EURUSD",
        "primary": {"exit_at": "2026-11-03T15:30:00Z", "hold_s": 3600.0, "exit_reason": "SL"},
        "mae_R": -1.0,
        "mfe_R": 0.2,
        "cost_over_R": 0.02,
        "spread_over_R": 0.04,
        "entry_drift_over_atr": 0.01,
    }
    days = [dt.date(2026, 11, 3)]
    m = metrics([r1, r2], days, Counter())

    assert m["n_fills"] == 2
    assert m["net_R_total"] == pytest.approx(0.5)
    assert m["win_rate"] == pytest.approx(0.5)
    assert m["expectancy_R_per_trade"] == pytest.approx(0.25)
    assert m["avg_win_R"] == pytest.approx(1.5)
    assert m["avg_loss_R"] == pytest.approx(-1.0)
    assert m["n_fills_unresolved"] == 0
    assert m["unresolved_reasons"] == {}
