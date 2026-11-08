"""Acceptance: Bid/Ask symmetry, SL/TP same bar ambiguity, gap stop, latency/deadline, no better-quote search,
SL touched before entry, tick grid, session end (DST)."""
import datetime as dt

import pytest

from quantmt5.execution import ExecParams, M1OpenProxy, TickQuotes, next_session_end, simulate
from quantmt5.timemap import NY
from quantmt5.util import iso_utc
from synth import T0, bars, ticks

S = T0 + 3600  # signal bar closes here
SESSION_NONE = {}


def cand(side, low=99.5, high=100.5, close=100.0, atr=1.0, buffer=0.05, setup="B"):
    return {"candidate_id": "C_test", "setup": setup, "symbol": "TEST", "side": side,
            "signal_bar": {"open_at": iso_utc(S - 300), "close_at": iso_utc(S), "o": 100.0, "h": high, "l": low, "c": close},
            "signal_close_ts": S, "ready_ts": S + 1, "atr_frozen": atr, "buffer": buffer, "episode_expires_ts": None}


def params(lat=5, slip=0.0, comm=0.0, session=SESSION_NONE):
    return ExecParams(latency_s=lat, slip_price=slip, commission_price_rt=comm, spread_guard=0.15, drift_guard_mult=0.10, tp_R=1.5,
                      max_hold_s=3600, deadline_s=90, pre_close_s=120, q=0.01, stops_level_price=0.0, session=session,
                      latency_name="T", cost_name="T")


def test_long_enters_ask_exits_bid_tp():
    tq = TickQuotes(ticks([(S - 100, 100.0, 100.02), (S + 2, 100.0, 100.02), (S + 7, 100.01, 100.03),
                           (S + 60, 100.5, 100.52), (S + 100, 100.89, 100.91),  # ask touches TP, bid does not → no exit (long exits on Bid)
                           (S + 120, 100.95, 100.97)]))
    r = simulate(cand("LONG"), tq, params())
    assert r["status"] == "FILLED"
    assert r["fill_at"] == iso_utc(S + 7)            # first quote at/after ready+latency, not the earlier S+2 tick
    assert r["entry"] == pytest.approx(100.03)       # Ask
    assert r["sl"] == pytest.approx(99.45)
    assert r["tp"] == pytest.approx(100.90)          # ceil to tick of entry+1.5R
    assert r["primary"]["exit_reason"] == "TP" and r["primary"]["exit_at"] == iso_utc(S + 120)
    assert r["primary"]["gross_R"] == pytest.approx(1.5, abs=0.02)


def test_short_enters_bid_exits_ask_and_sl_uses_ask_high():
    # ask high inside the signal bar = 100.56 (bid high 100.5 + spread)
    tq = TickQuotes(ticks([(S - 200, 100.5, 100.56), (S - 50, 100.1, 100.12), (S + 7, 100.0, 100.02),
                           (S + 60, 99.3, 99.32), (S + 90, 99.15, 99.17), (S + 200, 99.0, 99.02)]))
    r = simulate(cand("SHORT"), tq, params())
    assert r["status"] == "FILLED"
    assert r["sl"] == pytest.approx(100.61)          # ceil(ask_high 100.56 + buffer 0.05)
    assert r["sl_basis"] == "ASK_FROM_TICKS"
    assert r["entry"] == pytest.approx(100.0)        # Bid
    R = r["R_price"]
    assert r["tp"] == pytest.approx(round(100.0 - 1.5 * R - 0.005, 2), abs=0.011)
    assert r["primary"]["exit_reason"] == "TP"


def test_gap_through_stop_fills_at_quote_not_stop():
    tq = TickQuotes(ticks([(S + 7, 100.01, 100.03), (S + 60, 99.0, 99.02)]))
    r = simulate(cand("LONG"), tq, params(slip=0.01))
    assert r["primary"]["exit_reason"] == "SL_GAP"
    assert r["primary"]["exit_price"] == pytest.approx(98.99)
    assert r["primary"]["gross_R"] < -1.0             # loss can exceed planned R


def test_deadline_and_no_better_quote_search():
    late = TickQuotes(ticks([(S + 95, 100.0, 100.02), (S + 96, 100.0, 100.02)]))
    r = simulate(cand("LONG"), late, params())
    assert r["status"] == "BLOCKED" and r["reason"] == "DEADLINE_BEFORE_FIRST_QUOTE"
    # first quote fails drift guard (bid moved > 0.1 ATR); a later "nicer" quote must NOT be used
    drift = TickQuotes(ticks([(S + 7, 100.2, 100.22), (S + 8, 100.0, 100.02)]))
    r = simulate(cand("LONG"), drift, params())
    assert r["status"] == "BLOCKED" and r["reason"] == "ENTRY_DRIFT_GUARD"


def test_latency_scenarios_shift_first_quote():
    tq = TickQuotes(ticks([(S + 7, 100.01, 100.03), (S + 40, 100.02, 100.04), (S + 70, 100.03, 100.05), (S + 4000, 100.0, 100.02)]))
    assert simulate(cand("LONG"), tq, params(lat=5))["fill_at"] == iso_utc(S + 7)
    assert simulate(cand("LONG"), tq, params(lat=30))["fill_at"] == iso_utc(S + 40)
    assert simulate(cand("LONG"), tq, params(lat=60))["fill_at"] == iso_utc(S + 70)


def test_sl_touched_before_entry_blocks():
    tq = TickQuotes(ticks([(S + 3, 99.40, 99.42), (S + 7, 100.0, 100.02)]))
    r = simulate(cand("LONG"), tq, params())
    assert r["status"] == "BLOCKED" and r["reason"] == "SL_TOUCHED_BEFORE_ENTRY"


def test_spread_guard_blocks():
    tq = TickQuotes(ticks([(S + 7, 100.0, 100.10)]))
    r = simulate(cand("LONG", low=99.9), tq, params())   # R small (~0.25) → spread/R 0.4
    assert r["status"] == "BLOCKED" and r["reason"] == "SPREAD_GUARD"


def test_m1_proxy_same_bar_sl_tp_is_ambiguous_and_reports_both():
    # 5 M1 bars of the signal M5, then the fill minute, then a minute touching both SL and TP
    rows = [(100, 100.5, 99.5, 100.0, 10, 2)] * 5 + [(100.0, 100.1, 99.9, 100.0, 10, 2), (100.0, 101.5, 99.0, 100.0, 10, 2)] + [(100, 100.1, 99.9, 100, 10, 2)] * 70
    m1 = bars(60, S - 300, rows, tf="M1")
    qm = M1OpenProxy(m1, 0.01, spread_floor_points=2)
    r = simulate(cand("LONG"), qm, params())
    assert r["status"] == "FILLED"
    # latency quantised: first M1 open at/after ready+5s is S+60 (the open at S is earlier than S+6)
    assert r["fill_at"] == iso_utc(S + 60)
    assert r["entry"] == pytest.approx(100.02)        # Bid open + previous bar spread field (2 pts)
    assert r["ambiguous_sl_tp"] is True
    assert r["primary"]["exit_reason"] == "SL_AMBIGUOUS_ADVERSE_FIRST"
    assert r["favorable_first"]["exit_reason"] == "TP_AMBIGUOUS_FAVORABLE_FIRST"
    assert "TICK_PATH_AMBIGUOUS" in r["flags"] and "QUOTE_MODEL_M1_OPEN_PROXY" in r["flags"]
    assert r["net_R"] == r["primary"]["net_R"] < 0     # headline never picks the favourable side


def test_m1_proxy_slow_latency_misses_deadline():
    rows = [(100, 100.5, 99.5, 100.0, 10, 2)] * 5 + [(100, 100.1, 99.9, 100, 10, 2)] * 80
    m1 = bars(60, S - 300, rows, tf="M1")
    r = simulate(cand("LONG"), M1OpenProxy(m1, 0.01, 2), params(lat=60))
    assert r["status"] == "BLOCKED" and r["reason"] == "DEADLINE_BEFORE_FIRST_QUOTE"


def test_time_exit_after_max_hold():
    tq = TickQuotes(ticks([(S + 7, 100.01, 100.03)] + [(S + 7 + 60 * k, 100.05, 100.07) for k in range(1, 70)]))
    r = simulate(cand("LONG"), tq, params())
    assert r["primary"]["exit_reason"] == "TIME_EXIT"
    assert r["primary"]["hold_s"] >= 3600


def test_session_end_dst_aware():
    xau = {"kind": "DAILY_BREAK", "tz": "America/New_York", "daily_close": "17:00", "weekly_close": "Fri 17:00"}
    winter = dt.datetime(2025, 1, 14, 15, 0, tzinfo=dt.timezone.utc).timestamp()
    summer = dt.datetime(2025, 7, 15, 15, 0, tzinfo=dt.timezone.utc).timestamp()
    assert dt.datetime.fromtimestamp(next_session_end(winter, xau), dt.timezone.utc).hour == 22
    assert dt.datetime.fromtimestamp(next_session_end(summer, xau), dt.timezone.utc).hour == 21
    fx = {"kind": "ROLLOVER_ONLY", "tz": "America/New_York", "weekly_close": "Fri 17:00"}
    tue = dt.datetime(2025, 7, 15, 15, 0, tzinfo=dt.timezone.utc).timestamp()
    e = dt.datetime.fromtimestamp(next_session_end(tue, fx), dt.timezone.utc).astimezone(NY)
    assert e.weekday() == 4 and e.hour == 17
    # entry already past session_end-2min is skipped
    late = dt.datetime(2025, 7, 15, 20, 59, 0, tzinfo=dt.timezone.utc).timestamp()  # 16:59 NY
    c = cand("LONG")
    c["signal_close_ts"], c["ready_ts"] = late - 1, late
    c["signal_bar"]["close_at"], c["signal_bar"]["open_at"] = iso_utc(late - 1), iso_utc(late - 301)
    r = simulate(c, TickQuotes(ticks([(late + 6, 100.0, 100.02)])), params(session=xau))
    assert r["status"] == "BLOCKED" and r["reason"] == "PAST_PRE_SESSION_END"


def test_commission_unknown_is_not_zero():
    tq = TickQuotes(ticks([(S + 7, 100.01, 100.03), (S + 120, 100.95, 100.97)]))
    r = simulate(cand("LONG"), tq, params(comm=None))
    assert r["net_R"] is None and "COMMISSION_UNKNOWN" in r["flags"]
