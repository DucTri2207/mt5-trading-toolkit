"""B3 acceptance — hand-computable quote-side execution, costs/conversion/volume, ledger, portfolio, parity.
All quote inputs here are SYNTHETIC_FIXTURE ticks (full Bid/Ask); no MT5 connection."""
import datetime as dt

import numpy as np
import pytest

from quantmt5.data import Ticks
from quantmt5.evaluate import portfolio, select_branch
from quantmt5.execution import ExecParams, TickQuotes, conversion_rate, simulate
from quantmt5.util import iso_utc
from synth import T0

S = T0 + 3600 + 12 * 3600          # Monday 13:00 UTC (FX/XAU open)
FX = {"kind": "ROLLOVER_ONLY", "tz": "America/New_York", "rollover": "17:00", "weekly_close": "Fri 17:00"}


def tq(rows, kind="SYNTHETIC_FIXTURE"):
    """rows: (event_s, bid, ask[, available_s])"""
    t = np.array([int(round(r[0] * 1000)) for r in rows], np.int64)
    av = np.array([int(round((r[3] if len(r) > 3 else r[0]) * 1000)) for r in rows], np.int64)
    ticks = Ticks("T", t, np.array([r[1] for r in rows], float), np.array([r[2] for r in rows], float), np.zeros(len(rows), np.int64))
    return TickQuotes(ticks, av, kind=kind, source="fixture")


def cand(side="LONG", low=99.5, high=100.5, close=100.0, ready=None, cid="C1", setup="B", ep=None, exp=None):
    return {"candidate_id": cid, "revision_id": "REV_" + cid, "setup": setup, "symbol": "T", "side": side, "episode_id": ep,
            "signal_bar": {"open_at": iso_utc(S - 300), "close_at": iso_utc(S), "o": 100.0, "h": high, "l": low, "c": close},
            "signal_close_ts": S, "ready_ts": S + 1 if ready is None else ready, "atr_frozen": 1.0, "buffer": 0.05,
            "episode_expires_ts": exp, "gates": {"P0": {"result": "PASS"}, "M0": {"result": "PASS"}}, "ready_at": iso_utc(S + 1)}


def P(lat=5, slip=0.0, comm=0.0, session=None, risk=None, contract=None, stops=0.0):
    return ExecParams(latency_s=lat, slip_price=slip, commission_price_rt=comm, spread_guard=0.15, drift_guard_mult=0.10, tp_R=1.5,
                      max_hold_s=3600, deadline_s=90, pre_close_s=120, q=0.01, stops_level_price=stops, freeze_level_price=0.0,
                      session=session or {}, latency_name="T", cost_name="T", risk=risk, contract=contract or {})


# ---------------------------------------------------------------- first usable quote / arrival
def test_first_usable_quote_follows_arrival_not_event_order():
    q = tq([(S + 3, 100.0, 100.02, S + 20), (S + 7, 100.01, 100.03)])      # S+3 tick arrives late (S+20)
    r = simulate(cand(), q, P())
    assert r["status"] == "FILLED" and r["fill_at"] == iso_utc(S + 7) and r["entry"] == pytest.approx(100.03)
    assert r["entry_quote"]["seq"] == 1 and r["entry_quote"]["available_at"] == iso_utc(S + 7)


def test_late_arriving_old_quote_is_stale_and_no_later_quote_is_searched():
    q = tq([(S + 2, 100.0, 100.02, S + 9), (S + 30, 100.01, 100.03)])      # first usable = event S+2 delivered at S+9
    r = simulate(cand(), q, P())
    assert r["status"] == "BLOCKED" and r["reason"] == "QUOTE_STALE" and r["quote_age_s"] == pytest.approx(7)


@pytest.mark.parametrize("q_at,expect", [(S + 6, "FILLED"), (S + 89.999, "FILLED"), (S + 90, "DEADLINE_BEFORE_FIRST_QUOTE")])
def test_latency_and_deadline_boundaries(q_at, expect):
    r = simulate(cand(), tq([(q_at, 100.0, 100.02), (S + 4000, 100.0, 100.02)]), P())
    assert (r["status"] if expect == "FILLED" else r["reason"]) == expect


def test_late_readiness_never_extends_the_deadline():
    r = simulate(cand(ready=S + 88), tq([(S + 93, 100.0, 100.02)]), P())
    assert r["status"] == "BLOCKED" and r["reason"] == "READY_AFTER_DEADLINE" and r["deadline_at"] == iso_utc(S + 90)


@pytest.mark.parametrize("touch_avail,expect", [(S + 30, "FILLED"), (S + 5, "SL_TOUCHED_BEFORE_ENTRY")])
def test_pre_entry_sl_touch_uses_only_ticks_known_at_fill(touch_avail, expect):
    q = tq([(S + 3, 99.40, 99.42, touch_avail), (S + 7, 100.0, 100.02), (S + 4000, 100.0, 100.02)])
    r = simulate(cand(), q, P())
    assert (r["status"] if expect == "FILLED" else r["reason"]) == expect


def test_short_sl_uses_ask_high_known_by_fill_and_missing_ask_blocks():
    q = tq([(S - 200, 100.5, 100.56), (S - 100, 100.4, 100.70, S + 100), (S + 7, 100.0, 100.02), (S + 4000, 99.0, 99.02)])
    r = simulate(cand("SHORT"), q, P())
    assert r["status"] == "BLOCKED" and r["reason"] == "ASK_IN_SIGNAL_BAR_INCOMPLETE"  # late Ask high makes the true high unknown at fill
    q2 = tq([(S - 200, 100.5, 0.0), (S + 7, 100.0, 100.02)])
    r2 = simulate(cand("SHORT"), q2, P())
    assert r2["status"] == "BLOCKED" and r2["reason"] == "ASK_MISSING_IN_SIGNAL_BAR"
    assert simulate(cand("LONG"), q2, P())["status"] == "FILLED"                       # long SL needs only Bid low


def test_market_closed_vs_missing_quote_reasons():
    fri = dt.datetime(2025, 1, 10, 21, 59, tzinfo=dt.timezone.utc).timestamp()          # Fri 16:59 NY, close 17:00 NY
    c = cand(ready=int(fri) + 61)
    c["signal_close_ts"] = int(fri) + 60
    c["signal_bar"]["close_at"], c["signal_bar"]["open_at"] = iso_utc(int(fri) + 60), iso_utc(int(fri) - 240)
    r = simulate(c, tq([(fri + 3 * 86400, 100, 100.02)]), P(session=FX))
    # ready 17:00:01 NY Friday (after the weekly close) → first quote on Monday, window closed throughout
    assert r["reason"] == "MARKET_CLOSED_BEFORE_DEADLINE"
    r_nq = simulate(c, tq([(fri - 3600, 100, 100.02)]), P(session=FX))                     # no quote at all after ready
    assert r_nq["reason"] == "MARKET_CLOSED_NO_QUOTE"
    r2 = simulate(cand(), tq([(S - 500, 100, 100.02)]), P(session=FX))                 # weekday, open, nothing after ready
    assert r2["reason"] == "NO_QUOTE_AFTER_READY"
    r3 = simulate(cand(), tq([(S + 200, 100, 100.02)]), P(session=FX))                 # weekday, quote only after deadline
    assert r3["reason"] == "DEADLINE_BEFORE_FIRST_QUOTE"


def test_time_exit_overrun_uses_first_quote_after_not_hindsight():
    q = tq([(S + 7, 100.01, 100.03), (S + 1000, 100.2, 100.22), (S + 3607 + 900, 100.1, 100.12)])   # nothing at fill+60m
    r = simulate(cand(), q, P())
    p = r["primary"]
    assert p["exit_reason"] == "TIME_EXIT" and p["exit_at"] == iso_utc(S + 3607 + 900) and p["overrun_s"] == pytest.approx(900)
    assert p["exit_price"] == pytest.approx(100.1) and "EXIT_OVERRUN_GAP" in r["flags"]


def test_tp_rounding_is_not_pushed_one_tick_by_float_noise():
    from quantmt5.util import ceil_to_tick, floor_to_tick
    x = 99.99 - 1.5 * (100.61 - 99.99)                 # = 99.05999999999999 in binary floating point
    assert floor_to_tick(x, 0.01) == pytest.approx(99.06) and ceil_to_tick(100.04 + 1.5 * 0.59, 0.01) == pytest.approx(100.93)
    assert floor_to_tick(99.0649, 0.01) == pytest.approx(99.06) and ceil_to_tick(99.0601, 0.01) == pytest.approx(99.07)   # real fractions still round
    q = tq([(S - 200, 100.5, 100.56), (S + 7, 100.0, 100.02), (S + 300, 99.03, 99.08), (S + 400, 99.04, 99.06)])
    r = simulate(cand("SHORT"), q, P(slip=0.01, comm=0.07))
    assert r["tp"] == pytest.approx(99.06) and r["primary"]["exit_reason"] == "TP" and r["primary"]["exit_at"] == iso_utc(S + 400)


# ---------------------------------------------------------------- costs / conversion / volume (exact)
def test_long_costs_and_cash_exact():
    """ask 100.03 + slip 0.01 → entry 100.04; SL floor(99.5-0.05)=99.45; R=0.59; TP=ceil(100.04+0.885)=100.93.
    commission 7 USD/lot RT, contract 100 → 0.07 price/unit. gross 0.89, net 0.82, net_R 0.82/0.66.
    risk 100 USD: per-lot planned loss (0.59+0.07)*100 = 66 → raw 1.5151… → 1.51 lots (round DOWN)."""
    q = tq([(S + 7, 100.01, 100.03), (S + 120, 100.95, 100.97)])
    risk = {"account_currency": "USD", "risk_cash": 100.0, "volume_min": 0.01, "volume_step": 0.01, "volume_max": 100.0}
    r = simulate(cand(), q, P(slip=0.01, comm=0.07, risk=risk, contract={"contract_size": 100.0, "profit_currency": "USD", "base_currency": "XAU"}))
    assert r["entry"] == pytest.approx(100.04) and r["sl"] == pytest.approx(99.45) and r["R_price"] == pytest.approx(0.59)
    assert r["tp"] == pytest.approx(100.93) and r["primary"]["exit_reason"] == "TP" and r["primary"]["exit_price"] == pytest.approx(100.93)
    assert r["primary"]["gross_price"] == pytest.approx(0.89) and r["primary"]["net_price"] == pytest.approx(0.82)
    assert r["net_R"] == pytest.approx(0.82 / 0.66) and r["R_budget_price"] == pytest.approx(0.66)
    assert r["commission"]["entry_leg_price"] == pytest.approx(0.035) and r["commission"]["exit_leg_price"] == pytest.approx(0.035)
    c = r["cash"]
    assert c["status"] == "OK" and c["volume"] == pytest.approx(1.51)
    assert c["gross_cash"] == pytest.approx(0.89 * 100 * 1.51) and c["commission_cash"] == pytest.approx(0.07 * 100 * 1.51)
    assert c["net_cash"] == pytest.approx((0.89 - 0.07) * 151) and c["planned_risk_cash"] == pytest.approx(66 * 1.51)


def test_jpy_profit_converted_with_own_quote_and_unknowns_stay_unknown():
    """USDJPY-like: entry 150.00 (ask 149.99 + slip 0.01), SL 149.45, R 0.55, TP ceil(150+0.825)=150.83; contract 100000 JPY/lot/price.
    Profit JPY → USD via 1/exit price. Missing contract → cash UNKNOWN; commission UNKNOWN → net None (never 0)."""
    q = tq([(S + 7, 149.97, 149.99), (S + 300, 150.9, 150.92)])
    c0 = cand(low=149.5, high=150.2, close=150.0)
    c0["signal_bar"]["o"] = 149.9
    risk = {"account_currency": "USD", "risk_cash": 1000.0, "volume_min": 0.01, "volume_step": 0.01, "volume_max": 100.0}
    con = {"contract_size": 100000.0, "profit_currency": "JPY", "base_currency": "USD"}
    r = simulate(c0, q, P(slip=0.01, comm=0.0, risk=risk, contract=con))
    assert r["entry"] == pytest.approx(150.0) and r["tp"] == pytest.approx(150.83)
    cash = r["cash"]
    per_lot = 0.55 * 100000 / 150.0
    vol = int(1000.0 / per_lot * 100) / 100
    assert cash["volume"] == pytest.approx(vol) and cash["gross_cash"] == pytest.approx(0.83 * 100000 * vol / 150.83)
    assert conversion_rate({"profit_currency": "JPY", "base_currency": "EUR"}, "USD", 160.0)[0] is None   # cross not defined
    r2 = simulate(c0, q, P(comm=None, risk=risk, contract=con))
    assert r2["net_R"] is None and r2["cash"]["status"] == "UNKNOWN" and "COMMISSION_UNKNOWN" in r2["flags"]
    r3 = simulate(c0, q, P(comm=0.0, risk=risk, contract={"profit_currency": "JPY"}))
    assert r3["cash"]["status"] == "UNKNOWN" and r3["cash"]["reason"] == "CONTRACT_SIZE_OR_COMMISSION_UNKNOWN"
    r4 = simulate(c0, q, P(comm=0.0))
    assert r4["cash"]["reason"].startswith("NO_RISK_PROFILE") and r4["net_R"] is not None


def test_volume_below_min_is_blocked_not_rounded_up():
    q = tq([(S + 7, 100.01, 100.03), (S + 120, 100.95, 100.97)])
    risk = {"account_currency": "USD", "risk_cash": 0.5, "volume_min": 0.01, "volume_step": 0.01, "volume_max": 100.0}
    r = simulate(cand(), q, P(comm=0.07, risk=risk, contract={"contract_size": 100.0, "profit_currency": "USD"}))
    assert r["cash"]["status"] == "BLOCKED" and r["cash"]["reason"] == "BELOW_MIN_VOLUME_RISK_EXCEEDED"


def test_stop_gap_can_exceed_planned_risk():
    q = tq([(S + 7, 100.01, 100.03), (S + 60, 98.0, 98.02)])
    r = simulate(cand(), q, P(slip=0.01, comm=0.07))
    assert r["primary"]["exit_reason"] == "SL_GAP" and r["primary"]["exit_price"] == pytest.approx(97.99)
    assert r["net_R"] < -1.0                                         # gap loss beyond the R budget


# ---------------------------------------------------------------- selection / portfolio
def _filled(cid, setup, side, sym, ready, fill, exit_, spr=0.05, net=1.0):
    return {"candidate_id": cid, "setup": setup, "side": side, "symbol": sym, "status": "FILLED", "net_R": net, "fill_id": "F_" + cid,
            "fill_at": iso_utc(fill), "primary": {"exit_at": iso_utc(exit_)}, "spread_over_R": spr}


def test_select_branch_one_fill_per_episode_retest_after_block_and_records_everything():
    c1 = dict(cand(cid="r1", setup="A", ep="E1", exp=S + 5400), ready_ts=S + 1)
    c2 = dict(cand(cid="r2", setup="A", ep="E1", exp=S + 5400), ready_ts=S + 600)
    c3 = dict(cand(cid="r3", setup="A", ep="E1", exp=S + 5400), ready_ts=S + 900)
    c4 = dict(cand(cid="g", setup="A", ep="E2", exp=S + 5400), ready_ts=S + 50)
    c4["gates"] = {"M2": {"result": "FAIL", "reason": "x"}}
    for c in (c1, c2, c3):
        c["gates"] = {"M2": {"result": "PASS"}}
    outcome = {"r1": "BLOCKED", "r2": "FILLED", "r3": "FILLED"}
    run = lambda c: {"candidate_id": c["candidate_id"], "status": outcome[c["candidate_id"]], "fill_id": "F" + c["candidate_id"], "reason": "SPREAD_GUARD"}
    led, st = select_branch([c3, c1, c4, c2], "M2", run)
    by = {r["candidate_id"]: r for r in led}
    assert by["r1"]["status"] == "BLOCKED" and by["r2"]["status"] == "FILLED"            # blocked → next retest tried
    assert by["r3"]["status"] == "SKIPPED" and by["r3"]["filled_by"] == "Fr2"              # max one fill per episode
    assert by["g"]["status"] == "NOT_ELIGIBLE" and len(led) == 4                           # gate-blocked rows are recorded


def test_portfolio_same_event_by_signal_bar_priority_conflict_budget_and_restart():
    A1, B1 = _filled("a1", "A", "LONG", "XAU", 101, 110, 500), _filled("b1", "B", "LONG", "XAU", 103, 112, 400)   # same bar, ready differs
    A2 = _filled("a2", "A", "LONG", "EUR", 200, 210, 300)
    A3, B3 = _filled("a3", "A", "LONG", "JPY", 900, 910, 950), _filled("b3", "B", "SHORT", "JPY", 900, 910, 950)
    U = dict(_filled("u", "A", "LONG", "EUR", 600, 610, 700, net=None))                   # commission UNKNOWN → still selectable
    cands = {"a1": {"ready_ts": 101, "signal_close_ts": 100}, "b1": {"ready_ts": 103, "signal_close_ts": 100},
             "a2": {"ready_ts": 200, "signal_close_ts": 199}, "a3": {"ready_ts": 900, "signal_close_ts": 899},
             "b3": {"ready_ts": 900, "signal_close_ts": 899}, "u": {"ready_ts": 600, "signal_close_ts": 599}}
    cfg = {"max_positions_per_symbol": 1, "max_open_risk_units_total": 1}
    pf = portfolio({"M2": [A1, A2, A3, U], "P1": [B1, B3]}, cands, cfg)
    assert [r["candidate_id"] for r in pf["accepted"]] == ["a1", "u"]
    reasons = {r["candidate_id"]: r["portfolio_reason"] for r in pf["rejected"] + pf["dropped"]}
    assert reasons == {"b1": "SAME_EVENT_LINKED_TO_A", "a2": "RISK_BUDGET_FULL", "a3": "CONFLICT_OPPOSITE_SIDES_DROP_BOTH",
                       "b3": "CONFLICT_OPPOSITE_SIDES_DROP_BOTH"}
    pf2 = portfolio({"P1": [B3, B1], "M2": [U, A3, A2, A1]}, cands, cfg)                    # restart / different input order
    assert [r["portfolio_row_id"] for r in pf2["accepted"]] == [r["portfolio_row_id"] for r in pf["accepted"]]


def test_spread_rank_breaks_ties_with_known_values():
    X = _filled("x", "A", "LONG", "XAU", 100, 110, 500, spr=0.10)
    Y = _filled("y", "A", "LONG", "EUR", 100, 110, 500, spr=0.02)
    cands = {"x": {"ready_ts": 100, "signal_close_ts": 99}, "y": {"ready_ts": 100, "signal_close_ts": 98}}
    pf = portfolio({"M2": [X, Y]}, cands, {"max_positions_per_symbol": 1, "max_open_risk_units_total": 1})
    assert [r["candidate_id"] for r in pf["accepted"]] == ["y"] and pf["rejected"][0]["portfolio_reason"] == "RISK_BUDGET_FULL"


# ---------------------------------------------------------------- reproducible ledger via snapshot pins (real cache, PROXY)
@pytest.fixture(scope="module")
def real_snap():
    from quantmt5.snapshot import make_snapshot
    from quantmt5.util import parse_utc
    return make_snapshot(parse_utc("2026-10-22T16:00:00Z"), ["XAUUSD", "EURUSD"])


def test_replay_ledger_is_reproducible_and_labelled(real_snap):
    from quantmt5.replay import replay
    xau = [c for c in real_snap["candidates"] if c["symbol"] == "XAUUSD"]
    fx = [c for c in real_snap["candidates"] if c["symbol"] == "EURUSD"]
    assert xau and fx
    r1 = replay(xau[0]["candidate_id"], snapshot_id=real_snap["snapshot_id"], latency="MANUAL", cost="ADVERSE")
    r2 = replay(xau[0]["candidate_id"], snapshot_id=real_snap["snapshot_id"], latency="MANUAL", cost="ADVERSE")
    assert r1["execution"]["fill_id"] == r2["execution"]["fill_id"] and r1["execution"] == r2["execution"]
    assert r1["certification"] == "PROXY_NOT_EXACT" and "QUOTE_MODEL_M1_OPEN_PROXY" in r1["flags"]
    assert r1["versions"]["candidate_revision"] == xau[0]["revision_id"] and r1["versions"]["latency_s"] == 30
    assert r1["versions"]["data_versions"]["M5"] == real_snap["data_versions"]["XAUUSD"]["M5"]["content_hash"]
    rf = replay(fx[0]["candidate_id"], snapshot_id=real_snap["snapshot_id"])
    assert rf["execution"] is None and rf["certification"] == "UNKNOWN" and "ASK_MISSING" in rf["flags"]


def test_tick_file_loader_keeps_arrival_and_identity(tmp_path):
    from quantmt5.replay import load_tick_file
    a = np.zeros(3, dtype=[("time_msc", "i8"), ("bid", "f8"), ("ask", "f8"), ("available_msc", "i8")])
    a["time_msc"] = [1000, 1000, 2000]
    a["available_msc"] = [1500, 1200, 2000]
    a["bid"], a["ask"] = [1, 1.1, 1.2], [1.01, 1.11, 1.21]
    np.savez(tmp_path / "t.npz", ticks=a)
    qm = load_tick_file(tmp_path / "t.npz", "T")
    q = qm.first_usable(1.0)
    assert q.seq == 1 and q.available_at == pytest.approx(1.2)                    # same-ms pair: arrival decides, identity kept
    assert "TICK_ARRIVAL_ASSUMED_AT_EVENT" not in qm.flags


# ---------------------------------------------------------------- MT5 parity (read-only calculators)
def test_parity_pending_without_terminal_and_match_with_fake():
    import os
    from quantmt5.parity import profit_parity
    row = {"status": "FILLED", "fill_id": "F1", "side": "LONG", "symbol": "XAUUSD", "entry": 100.04, "primary": {"exit_price": 100.93},
           "cash": {"status": "OK", "volume": 1.51, "gross_cash": 0.89 * 151, "account_currency": "USD"}}   # B6A H1: explicit unit
    assert profit_parity([row], "C:/T", process_lister=lambda: [])["status"] == "PENDING_LIVE"

    class Fake:
        ORDER_TYPE_BUY, ORDER_TYPE_SELL = 0, 1
        def initialize(self, path=None): return True
        def shutdown(self): pass
        def order_calc_profit(self, t, s, v, a, b): return (b - a) * 100 * v
        def order_send(self, *a): raise AssertionError("must be unreachable")
        # B6A H1 (Codex-approved): identity + account currency required after attach
        def terminal_info(self): return {"path": os.path.dirname(exe), "data_path": "C:/T/data", "connected": True, "build": 5000}
        def account_info(self): return {"login": 1, "server": "FAKE", "currency": "USD", "trade_mode": 0}
    exe = os.path.normcase(os.path.abspath("C:/T/terminal64.exe"))
    res = profit_parity([row], "C:/T", mt5_module=Fake(), process_lister=lambda: [exe])
    assert res["status"] == "OK" and res["rows"][0]["status"] == "MATCH"
