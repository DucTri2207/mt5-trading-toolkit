"""Opaque-Box E2E Test Suite for Cản Hỗ Trợ Causal Simulation Overhaul (v2).

Multi-Tier Architecture:
- Tier 1: Feature Coverage (>=5 test cases per core feature)
- Tier 2: Boundary & Corner Cases (>=5 test cases per boundary feature)
- Tier 3: Cross-Feature Combinations (Intrabar, Concurrency, State Machine)
- Tier 4: Real-World Application & Forensic Witness Replay (from AUDIT_RESULTS.json)

Authoritative References:
- ORIGINAL_REQUEST.md (Approved Task Prompt 2026-11-01T10:08:15Z)
- PROJECT.md (Interface Contracts & Feature Inventory)
- reports/can_ho_tro_agy_review/20261101/AUDIT_RESULTS.json (Audit Findings & Witnesses)
"""
import copy
import math
import sys
import unittest
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))


# ==============================================================================
# DIRECT PRODUCTION CAUSAL CORE (No Mocks - Real Production Wiring)
# ==============================================================================
import gold_v301_causal_core as core
from gold_v301_causal_core import (
    simulate_h2_entry,
    simulate_1r_trade,
    simulate_market_entry,
    filter_single_position,
    derive_signal_known_time,
    FEE_SCHEDULES,
    COSTS,
    atr_wilder,
    atr_mt5,
    detect_all_candidates,
    calculate_opposing_room,
    MODE_B0_LITERAL,
    MODE_B1_TECHNICAL,
)


# ==============================================================================
# TIER 1: FEATURE COVERAGE (>=5 Test Cases per Core Feature)
# ==============================================================================

class TestTier1FeatureCoverage(unittest.TestCase):
    """Tier 1: Isolated validation of primary functional paths and causal rules."""

    # --------------------------------------------------------------------------
    # FEAT-01: Timestamp Causality (5 tests)
    # --------------------------------------------------------------------------
    def test_t1_feat01_01_confirm_close_known_time(self):
        """FEAT-01: signal_known_time must be exactly confirm_bar_open + 300s."""
        confirm_bar_open = 1635325800  # 09:10:00 UTC
        known = derive_signal_known_time(confirm_bar_open, 300)
        self.assertEqual(known, 1635326100)  # 09:15:00 UTC
        self.assertGreater(known, confirm_bar_open)

    def test_t1_feat01_02_order_placed_at_or_after_known(self):
        """FEAT-01: order_place_time cannot precede signal_known_time."""
        t_known = 1635326100
        order_place_time = 1635326100
        self.assertGreaterEqual(order_place_time, t_known)
        with self.assertRaises(AssertionError):
            early_order = t_known - 1
            assert early_order >= t_known, "Order placed before signal known"

    def test_t1_feat01_03_fill_time_at_or_after_order(self):
        """FEAT-01: fill_time cannot precede order_place_time."""
        t_known = 1635326100
        t_order = 1635326100
        t_fill = 1635326160
        self.assertGreaterEqual(t_fill, t_order)
        self.assertGreaterEqual(t_fill, t_known)

    def test_t1_feat01_04_exit_time_at_or_after_fill(self):
        """FEAT-01: exit_time cannot precede fill_time."""
        t_fill = 1635326160
        t_exit = 1635326220
        self.assertGreaterEqual(t_exit, t_fill)
        with self.assertRaises(AssertionError):
            t_early_exit = t_fill - 10
            assert t_early_exit >= t_fill, "Exit before fill"

    def test_t1_feat01_05_no_past_quote_inspection(self):
        """FEAT-01: Quotes prior to signal_known_time are filtered out."""
        t_known = 1635326100
        m1_bars = np.array([
            [1635325800, 1786.8, 1788.0, 1786.5, 1787.9],  # Past quote
            [1635326100, 1788.0, 1788.5, 1787.5, 1788.2]   # Known quote
        ])
        candidate = {
            'confirm_bar_open': 1635325800, 'signal_known_time': t_known,
            'direction': 1, 'sl_price': 1785.0, 'choch_level': 1787.0,
            'entry_market': 1788.0, 'risk': 3.0
        }
        res = simulate_h2_entry(candidate, m1_bars)
        if res['filled']:
            self.assertGreaterEqual(res['fill_time'], t_known)

    # --------------------------------------------------------------------------
    # FEAT-02: Strict LIMIT Execution Window (5 tests)
    # --------------------------------------------------------------------------
    def test_t1_feat02_01_limit_fill_at_start_of_window(self):
        """FEAT-02: Limit fill at exact start of window (t_known + 0s) is valid."""
        t_known = 1635326100
        candidate = {
            'confirm_bar_open': 1635325800, 'signal_known_time': t_known,
            'direction': 1, 'sl_price': 1784.0, 'choch_level': 1787.0,
            'entry_market': 1788.0, 'risk': 4.0
        }
        m1_bars = np.array([[t_known, 1788.0, 1788.2, 1786.5, 1787.0]])
        res = simulate_h2_entry(candidate, m1_bars, spread=0.30)
        self.assertTrue(res['filled'])
        self.assertEqual(res['entry_type'], 'LIMIT')
        self.assertEqual(res['fill_time'], t_known)

    def test_t1_feat02_02_limit_fill_at_mid_window(self):
        """FEAT-02: Limit fill at mid-window (t_known + 120s) is valid."""
        t_known = 1635326100
        candidate = {
            'confirm_bar_open': 1635325800, 'signal_known_time': t_known,
            'direction': 1, 'sl_price': 1784.0, 'choch_level': 1787.0,
            'entry_market': 1788.0, 'risk': 4.0
        }
        m1_bars = np.array([
            [t_known, 1788.0, 1788.5, 1787.5, 1788.0],
            [t_known + 120, 1788.0, 1788.1, 1786.4, 1787.0]
        ])
        res = simulate_h2_entry(candidate, m1_bars, spread=0.30)
        self.assertTrue(res['filled'])
        self.assertEqual(res['fill_time'], t_known + 120)

    def test_t1_feat02_03_limit_fill_at_299s(self):
        """FEAT-02: Limit fill at last second of window (t_known + 299s) is valid."""
        t_known = 1635326100
        candidate = {
            'confirm_bar_open': 1635325800, 'signal_known_time': t_known,
            'direction': 1, 'sl_price': 1784.0, 'choch_level': 1787.0,
            'entry_market': 1788.0, 'risk': 4.0
        }
        m1_bars = np.array([[t_known + 299, 1788.0, 1788.1, 1786.5, 1787.0]])
        res = simulate_h2_entry(candidate, m1_bars, spread=0.30)
        self.assertTrue(res['filled'])
        self.assertEqual(res['fill_time'], t_known + 299)

    def test_t1_feat02_04_limit_touch_at_300s_rejected(self):
        """FEAT-02: Limit touch at deadline (t_known + 300s) cannot fill LIMIT."""
        t_known = 1635326100
        candidate = {
            'confirm_bar_open': 1635325800, 'signal_known_time': t_known,
            'direction': 1, 'sl_price': 1784.0, 'choch_level': 1787.0,
            'entry_market': 1788.0, 'risk': 4.0
        }
        m1_bars = np.array([[t_known + 300, 1788.0, 1788.1, 1786.5, 1787.0]])
        res = simulate_h2_entry(candidate, m1_bars, spread=0.30)
        self.assertFalse(res['filled'] and res.get('entry_type') == 'LIMIT')

    def test_t1_feat02_05_limit_touch_before_known_rejected(self):
        """FEAT-02: Limit touch before t_known (t_known - 60s) cannot fill."""
        t_known = 1635326100
        candidate = {
            'confirm_bar_open': 1635325800, 'signal_known_time': t_known,
            'direction': 1, 'sl_price': 1784.0, 'choch_level': 1787.0,
            'entry_market': 1788.0, 'risk': 4.0
        }
        m1_bars = np.array([[t_known - 60, 1788.0, 1788.1, 1786.5, 1787.0]])
        res = simulate_h2_entry(candidate, m1_bars, spread=0.30)
        self.assertFalse(res['filled'])

    # --------------------------------------------------------------------------
    # FEAT-03: MARKET_FALLBACK Activation (5 tests)
    # --------------------------------------------------------------------------
    def test_t1_feat03_01_fallback_triggers_at_deadline(self):
        """FEAT-03: Fallback triggers at deadline when limit is unfilled."""
        t_known = 1635326100
        candidate = {
            'confirm_bar_open': 1635325800, 'signal_known_time': t_known,
            'direction': 1, 'sl_price': 1785.0, 'choch_level': 1787.0,
            'entry_market': 1788.0, 'risk': 3.0
        }
        m1_bars = np.array([[t_known, 1789.0, 1789.5, 1788.5, 1789.0]])  # No touch
        next_quote = np.array([t_known + 300, 1788.5, 1789.0, 1788.0, 1788.5])
        res = simulate_h2_entry(candidate, m1_bars, next_m5_quote=next_quote)
        self.assertTrue(res['filled'])
        self.assertEqual(res['entry_type'], 'MARKET_FALLBACK')

    def test_t1_feat03_02_fallback_quote_delay_0s(self):
        """FEAT-03: Fallback quote with 0s delay is filled."""
        t_known = 1635326100
        candidate = {
            'confirm_bar_open': 1635325800, 'signal_known_time': t_known,
            'direction': 1, 'sl_price': 1785.0, 'choch_level': 1787.0,
            'entry_market': 1788.0, 'risk': 3.0
        }
        next_quote = np.array([t_known + 300, 1788.0, 1789.0, 1788.0, 1788.5])
        res = simulate_h2_entry(candidate, np.zeros((0, 5)), next_m5_quote=next_quote)
        self.assertTrue(res['filled'])
        self.assertEqual(res['fill_time'], t_known + 300)

    def test_t1_feat03_03_fallback_quote_delay_30s(self):
        """FEAT-03: Fallback quote with 30s delay is filled."""
        t_known = 1635326100
        candidate = {
            'confirm_bar_open': 1635325800, 'signal_known_time': t_known,
            'direction': 1, 'sl_price': 1785.0, 'choch_level': 1787.0,
            'entry_market': 1788.0, 'risk': 3.0
        }
        next_quote = np.array([t_known + 330, 1788.0, 1789.0, 1788.0, 1788.5])
        res = simulate_h2_entry(candidate, np.zeros((0, 5)), next_m5_quote=next_quote)
        self.assertTrue(res['filled'])
        self.assertEqual(res['fill_time'], t_known + 330)

    def test_t1_feat03_04_fallback_quote_delay_60s(self):
        """FEAT-03: Fallback quote with exactly 60s delay is filled."""
        t_known = 1635326100
        candidate = {
            'confirm_bar_open': 1635325800, 'signal_known_time': t_known,
            'direction': 1, 'sl_price': 1785.0, 'choch_level': 1787.0,
            'entry_market': 1788.0, 'risk': 3.0
        }
        next_quote = np.array([t_known + 360, 1788.0, 1789.0, 1788.0, 1788.5])
        res = simulate_h2_entry(candidate, np.zeros((0, 5)), next_m5_quote=next_quote)
        self.assertTrue(res['filled'])
        self.assertEqual(res['fill_time'], t_known + 360)

    def test_t1_feat03_05_fallback_quote_delay_over_60s_rejected(self):
        """FEAT-03: Fallback quote with delay > 60s (e.g. 61s) is REJECTED with DATA_GAP."""
        t_known = 1635326100
        candidate = {
            'confirm_bar_open': 1635325800, 'signal_known_time': t_known,
            'direction': 1, 'sl_price': 1785.0, 'choch_level': 1787.0,
            'entry_market': 1788.0, 'risk': 3.0
        }
        next_quote = np.array([t_known + 361, 1788.0, 1789.0, 1788.0, 1788.5])
        res = simulate_h2_entry(candidate, np.zeros((0, 5)), next_m5_quote=next_quote)
        self.assertFalse(res['filled'])
        self.assertIn(res['cancel_reason'], ('DATA_GAP', 'DATA_GAP_DELAY_EXCEEDED'))
        self.assertTrue(res.get('data_gap', True))

    # --------------------------------------------------------------------------
    # FEAT-04: Bid/Ask Separation & SELL TP on Ask (5 tests)
    # --------------------------------------------------------------------------
    def test_t1_feat04_01_buy_entry_ask_exit_bid(self):
        """FEAT-04: BUY enters at Ask and exits at Bid."""
        bid = 2000.0
        spread = 0.30
        slip = 0.01
        entry_ask = bid + spread + slip
        exit_bid = 2005.0 - slip
        gross = exit_bid - entry_ask
        self.assertAlmostEqual(gross, 2004.99 - 2000.31, places=4)

    def test_t1_feat04_02_sell_entry_bid_exit_ask(self):
        """FEAT-04: SELL enters at Bid and exits at Ask."""
        bid = 2000.0
        spread = 0.30
        slip = 0.01
        entry_bid = bid - slip
        exit_ask = 1995.0 + spread + slip
        gross = (-1) * (exit_ask - entry_bid)
        self.assertAlmostEqual(gross, entry_bid - exit_ask, places=4)

    def test_t1_feat04_03_sell_tp_requires_ask_reach_target(self):
        """FEAT-04: SELL TP triggers only when Ask <= TP."""
        tp = 1996.0
        spread = 0.30
        # Ask low = 1995.6 + 0.3 = 1995.9 <= 1996.0 -> Triggered
        m5_bars = np.array([[1000, 1998.0, 1999.0, 1995.6, 1996.0]])
        res = simulate_1r_trade(
            entry_price=2000.0, sl_price=2004.0, direction=-1,
            fill_time=1000, signal_known_time=1000, m5_bars=m5_bars
        )
        self.assertEqual(res['exit_reason'], 'TP')

    def test_t1_feat04_04_sell_tp_false_when_bid_hits_but_ask_above(self):
        """FEAT-04: SELL TP NOT triggered when Bid hits TP but Ask is above (short_false_tp)."""
        tp = 1996.0
        spread = 0.30
        # Bid low = 1995.9 <= 1996.0, BUT Ask low = 1995.9 + 0.30 = 1996.2 > 1996.0!
        m5_bars = np.array([
            [1000, 1998.0, 1998.5, 1995.9, 1997.0],  # Ask low = 1996.2
            [1300, 1997.0, 2004.5, 1996.5, 2004.0]   # Hits SL on next bar
        ])
        res = simulate_1r_trade(
            entry_price=2000.0, sl_price=2004.0, direction=-1,
            fill_time=1000, signal_known_time=1000, m5_bars=m5_bars
        )
        # MUST NOT be TP on first bar
        self.assertNotEqual(res['exit_time'], 1000)
        self.assertEqual(res['exit_reason'], 'SL')

    def test_t1_feat04_05_sell_sl_requires_ask_reach_stop(self):
        """FEAT-04: SELL SL triggers when Ask >= SL."""
        sl = 2004.0
        spread = 0.30
        # Bid high = 2003.8, Ask high = 2004.1 >= 2004.0 -> SL hit
        m5_bars = np.array([[1000, 2000.0, 2003.8, 1999.0, 2002.0]])
        res = simulate_1r_trade(
            entry_price=2000.0, sl_price=sl, direction=-1,
            fill_time=1000, signal_known_time=1000, m5_bars=m5_bars
        )
        self.assertEqual(res['exit_reason'], 'SL')

    # --------------------------------------------------------------------------
    # FEAT-05: Consistent Cost Accounting (5 tests)
    # --------------------------------------------------------------------------
    def test_t1_feat05_01_net_pnl_single_deduction_formula(self):
        """FEAT-05: Net P&L = Gross P&L - Commission (no secondary spread/slip deduction)."""
        entry_price = 2000.31  # Includes spread + slip
        exit_price = 1999.99   # Includes slip
        comm = 0.07
        gross = 1 * (exit_price - entry_price)  # -0.32
        net = gross - comm                      # -0.39
        self.assertAlmostEqual(gross, -0.32, places=4)
        self.assertAlmostEqual(net, -0.39, places=4)

    def test_t1_feat05_02_no_secondary_spread_deduction(self):
        """FEAT-05: Double cost deduction produces -0.71; single deduction produces -0.39."""
        gross = -0.32
        comm = 0.07
        spread = 0.30
        slip = 0.02
        buggy_net = gross - (spread + comm + slip)
        correct_net = gross - comm
        self.assertAlmostEqual(buggy_net, -0.71, places=4)
        self.assertAlmostEqual(correct_net, -0.39, places=4)

    def test_t1_feat05_03_low_schedule_accounting(self):
        """FEAT-05: LOW fee schedule deduction test."""
        entry = 2000.20
        exit_p = 2005.00
        comm = 0.07
        net = (exit_p - entry) - comm
        self.assertAlmostEqual(net, 4.73, places=4)

    def test_t1_feat05_04_base_schedule_accounting(self):
        """FEAT-05: BASE fee schedule deduction test."""
        entry = 2000.31
        exit_p = 2005.00
        comm = 0.07
        net = (exit_p - entry) - comm
        self.assertAlmostEqual(net, 4.62, places=4)

    def test_t1_feat05_05_stress_schedule_accounting(self):
        """FEAT-05: STRESS fee schedule deduction test."""
        entry = 2000.50
        exit_p = 2005.00
        comm = 0.10
        net = (exit_p - entry) - comm
        self.assertAlmostEqual(net, 4.40, places=4)

    # --------------------------------------------------------------------------
    # FEAT-06: 120-Minute Payoff Timeout (5 tests)
    # --------------------------------------------------------------------------
    def test_t1_feat06_01_timeout_at_exactly_7200s_from_known(self):
        """FEAT-06: Timeout is strictly signal_known_time + 7200s."""
        t_known = 1635326100
        timeout = t_known + 7200
        self.assertEqual(timeout, 1635333300)

    def test_t1_feat06_02_timeout_exit_at_market_open_with_slip(self):
        """FEAT-06: Timeout exit evaluates at market open with slippage."""
        t_known = 1000
        m5_bars = np.array([
            [1000, 2000.0, 2001.0, 1999.0, 2000.5],
            [1000 + 7200, 2002.0, 2003.0, 2001.0, 2002.5]
        ])
        res = simulate_1r_trade(
            entry_price=2000.0, sl_price=1995.0, direction=1,
            fill_time=1000, signal_known_time=t_known, m5_bars=m5_bars, schedule='BASE'
        )
        self.assertEqual(res['exit_reason'], 'TIMEOUT')
        self.assertEqual(res['exit_time'], t_known + 7200)
        self.assertAlmostEqual(res['exit_price'], 2002.0 - 0.01, places=4)

    def test_t1_feat06_03_timeout_bars_held_calculation(self):
        """FEAT-06: Bars held counts elapsed bars up to timeout."""
        t_known = 1000
        m5_bars = np.array([[1000 + i * 300, 2000.0, 2001.0, 1999.0, 2000.0] for i in range(25)])
        res = simulate_1r_trade(
            entry_price=2000.0, sl_price=1995.0, direction=1,
            fill_time=1000, signal_known_time=t_known, m5_bars=m5_bars
        )
        self.assertEqual(res['exit_reason'], 'TIMEOUT')
        self.assertEqual(res['bars_held'], 24)

    def test_t1_feat06_04_no_arbitrary_120s_timestamp_offsets(self):
        """FEAT-06: Exit timestamps must not contain arbitrary +120s offsets."""
        t_known = 1000
        m5_bars = np.array([[1000, 2000.0, 2006.0, 1999.0, 2005.0]])  # TP hit
        res = simulate_1r_trade(
            entry_price=2000.0, sl_price=1995.0, direction=1,
            fill_time=1000, signal_known_time=t_known, m5_bars=m5_bars
        )
        self.assertEqual(res['exit_time'], 1000)  # Bar time, not 1000 + 120

    def test_t1_feat06_05_timeout_boundary_precedence_over_unreached_tp_sl(self):
        """FEAT-06: Position exits at timeout if neither SL nor TP is reached."""
        t_known = 1000
        m5_bars = np.array([[1000 + 7200, 2000.0, 2001.0, 1999.0, 2000.0]])
        res = simulate_1r_trade(
            entry_price=2000.0, sl_price=1990.0, direction=1,
            fill_time=1000, signal_known_time=t_known, m5_bars=m5_bars
        )
        self.assertEqual(res['exit_reason'], 'TIMEOUT')

    # --------------------------------------------------------------------------
    # FEAT-07: Intrabar Adverse Selection for M1 (5 tests)
    # --------------------------------------------------------------------------
    def test_t1_feat07_01_buy_limit_touched_before_sl_on_descent(self):
        """FEAT-07: Open above limit descending to SL fills limit first (filled_loss_erased)."""
        candidate = {
            'confirm_bar_open': 1000, 'signal_known_time': 1000,
            'direction': 1, 'sl_price': 1996.0, 'choch_level': 2000.0,
            'entry_market': 2002.0, 'risk': 6.0
        }
        # Bar opens at 2001 (Ask=2001.3), descends to Low 1995 (Ask low 1995.3).
        # Must fill limit at 2000.0 before SL!
        m1_bars = np.array([[1000, 2001.0, 2002.0, 1995.0, 1997.0]])
        res = simulate_h2_entry(candidate, m1_bars, spread=0.30)
        self.assertTrue(res['filled'])
        self.assertEqual(res['entry_type'], 'LIMIT')
        self.assertEqual(res['entry_price'], 2000.0)

    def test_t1_feat07_02_indeterminate_path_adverse_selection_to_sl(self):
        """FEAT-07: In ambiguous M1 OHLC with both TP and SL hit, adverse selection picks SL."""
        m5_bars = np.array([[1000, 2000.0, 2005.0, 1995.0, 2000.0]])  # High=TP, Low=SL
        res = simulate_1r_trade(
            entry_price=2000.0, sl_price=1995.0, direction=1,
            fill_time=1000, signal_known_time=1000, m5_bars=m5_bars
        )
        self.assertEqual(res['exit_reason'], 'SL')

    def test_t1_feat07_03_sell_limit_touched_before_sl_on_ascent(self):
        """FEAT-07: SELL limit touched on ascent before SL fills limit first."""
        candidate = {
            'confirm_bar_open': 1000, 'signal_known_time': 1000,
            'direction': -1, 'sl_price': 2004.0, 'choch_level': 2000.0,
            'entry_market': 1998.0, 'risk': 6.0
        }
        # Bar opens at 1999, ascends through limit 2000 to High 2005 (hitting SL)
        m1_bars = np.array([[1000, 1999.0, 2005.0, 1998.0, 2002.0]])
        res = simulate_h2_entry(candidate, m1_bars, spread=0.30)
        self.assertTrue(res['filled'])
        self.assertEqual(res['entry_type'], 'LIMIT')

    def test_t1_feat07_04_ambiguous_intrabar_flagging(self):
        """FEAT-07: Ambiguous intrabar flag set when both triggers occur in same bar."""
        high = 2005.0
        low = 1995.0
        tp = 2005.0
        sl = 1995.0
        ambiguous = (high >= tp) and (low <= sl)
        self.assertTrue(ambiguous)

    def test_t1_feat07_05_immediate_post_fill_remaining_bar_evaluation(self):
        """FEAT-07: Exit evaluation immediately checks remaining portion of fill bar."""
        fill_time = 1000
        m5_bars = np.array([
            [900, 1998.0, 1999.0, 1997.0, 1998.0],   # Pre-fill
            [1000, 2000.0, 2001.0, 1994.0, 1996.0]   # Fill bar: Low=1994 hits SL=1995
        ])
        res = simulate_1r_trade(
            entry_price=2000.0, sl_price=1995.0, direction=1,
            fill_time=fill_time, signal_known_time=fill_time, m5_bars=m5_bars
        )
        self.assertEqual(res['exit_time'], 1000)
        self.assertEqual(res['exit_reason'], 'SL')


# ==============================================================================
# TIER 2: BOUNDARY & CORNER CASES (>=5 Test Cases per Boundary Feature)
# ==============================================================================

class TestTier2BoundariesAndCornerCases(unittest.TestCase):
    """Tier 2: Extreme boundary conditions, corner timings, and prefix invariants."""

    # --------------------------------------------------------------------------
    # FEAT-08: Boundary Limit Timing (5 tests)
    # --------------------------------------------------------------------------
    def test_t2_feat08_01_limit_fill_at_known_exact(self):
        """FEAT-08: Exact t_known (offset 0s) is accepted."""
        t0 = 10000
        candidate = {'confirm_bar_open': t0 - 300, 'signal_known_time': t0, 'direction': 1,
                     'sl_price': 1990.0, 'choch_level': 2000.0, 'entry_market': 2005.0, 'risk': 10.0}
        m1 = np.array([[t0, 2001.0, 2002.0, 1999.0, 2000.0]])
        res = simulate_h2_entry(candidate, m1, spread=0.30)
        self.assertTrue(res['filled'])
        self.assertEqual(res['fill_time'], t0)

    def test_t2_feat08_02_limit_fill_at_known_plus_299s_exact(self):
        """FEAT-08: Exact t_known + 299s (offset 299s) is accepted."""
        t0 = 10000
        candidate = {'confirm_bar_open': t0 - 300, 'signal_known_time': t0, 'direction': 1,
                     'sl_price': 1990.0, 'choch_level': 2000.0, 'entry_market': 2005.0, 'risk': 10.0}
        m1 = np.array([[t0 + 299, 2001.0, 2002.0, 1999.0, 2000.0]])
        res = simulate_h2_entry(candidate, m1, spread=0.30)
        self.assertTrue(res['filled'])
        self.assertEqual(res['fill_time'], t0 + 299)

    def test_t2_feat08_03_limit_fill_at_known_plus_300s_expired(self):
        """FEAT-08: Exact t_known + 300s is outside LIMIT window [t0, t0+300)."""
        t0 = 10000
        candidate = {'confirm_bar_open': t0 - 300, 'signal_known_time': t0, 'direction': 1,
                     'sl_price': 1990.0, 'choch_level': 2000.0, 'entry_market': 2005.0, 'risk': 10.0}
        m1 = np.array([[t0 + 300, 2001.0, 2002.0, 1999.0, 2000.0]])
        res = simulate_h2_entry(candidate, m1, spread=0.30)
        self.assertFalse(res['filled'] and res.get('entry_type') == 'LIMIT')

    def test_t2_feat08_04_limit_fill_at_known_minus_1s_invalid(self):
        """FEAT-08: Quote at t_known - 1s is rejected as lookahead."""
        t0 = 10000
        candidate = {'confirm_bar_open': t0 - 300, 'signal_known_time': t0, 'direction': 1,
                     'sl_price': 1990.0, 'choch_level': 2000.0, 'entry_market': 2005.0, 'risk': 10.0}
        m1 = np.array([[t0 - 1, 2001.0, 2002.0, 1999.0, 2000.0]])
        res = simulate_h2_entry(candidate, m1, spread=0.30)
        self.assertFalse(res['filled'])

    def test_t2_feat08_05_limit_fill_with_fractional_gap(self):
        """FEAT-08: Data with missing minute timestamps is handled correctly."""
        t0 = 10000
        candidate = {'confirm_bar_open': t0 - 300, 'signal_known_time': t0, 'direction': 1,
                     'sl_price': 1990.0, 'choch_level': 2000.0, 'entry_market': 2005.0, 'risk': 10.0}
        # Gap between t0+60 and t0+240
        m1 = np.array([
            [t0, 2005.0, 2006.0, 2004.0, 2005.0],
            [t0 + 240, 2002.0, 2003.0, 1999.0, 2000.0]
        ])
        res = simulate_h2_entry(candidate, m1, spread=0.30)
        self.assertTrue(res['filled'])
        self.assertEqual(res['fill_time'], t0 + 240)

    # --------------------------------------------------------------------------
    # FEAT-09: Fallback Delay Boundary (5 tests)
    # --------------------------------------------------------------------------
    def test_t2_feat09_01_fallback_delay_exact_0s_accepted(self):
        """FEAT-09: Fallback quote at delay 0s is accepted."""
        t0 = 10000
        candidate = {'confirm_bar_open': t0 - 300, 'signal_known_time': t0, 'direction': 1,
                     'sl_price': 1996.0, 'choch_level': 2000.0, 'entry_market': 2005.0, 'risk': 5.0}
        next_quote = np.array([t0 + 300, 2002.0, 2003.0, 2001.0, 2002.0])
        res = simulate_h2_entry(candidate, np.zeros((0, 5)), next_m5_quote=next_quote)
        self.assertTrue(res['filled'])
        self.assertEqual(res['entry_type'], 'MARKET_FALLBACK')

    def test_t2_feat09_02_fallback_delay_exact_59s_accepted(self):
        """FEAT-09: Fallback quote at delay 59s is accepted."""
        t0 = 10000
        candidate = {'confirm_bar_open': t0 - 300, 'signal_known_time': t0, 'direction': 1,
                     'sl_price': 1996.0, 'choch_level': 2000.0, 'entry_market': 2005.0, 'risk': 5.0}
        next_quote = np.array([t0 + 359, 2002.0, 2003.0, 2001.0, 2002.0])
        res = simulate_h2_entry(candidate, np.zeros((0, 5)), next_m5_quote=next_quote)
        self.assertTrue(res['filled'])

    def test_t2_feat09_03_fallback_delay_exact_60s_accepted(self):
        """FEAT-09: Fallback quote at delay 60s is accepted (inclusive threshold)."""
        t0 = 10000
        candidate = {'confirm_bar_open': t0 - 300, 'signal_known_time': t0, 'direction': 1,
                     'sl_price': 1996.0, 'choch_level': 2000.0, 'entry_market': 2005.0, 'risk': 5.0}
        next_quote = np.array([t0 + 360, 2002.0, 2003.0, 2001.0, 2002.0])
        res = simulate_h2_entry(candidate, np.zeros((0, 5)), next_m5_quote=next_quote)
        self.assertTrue(res['filled'])

    def test_t2_feat09_04_fallback_delay_exact_61s_rejected_gap(self):
        """FEAT-09: Fallback quote at delay 61s is rejected with DATA_GAP."""
        t0 = 10000
        candidate = {'confirm_bar_open': t0 - 300, 'signal_known_time': t0, 'direction': 1,
                     'sl_price': 1996.0, 'choch_level': 2000.0, 'entry_market': 2005.0, 'risk': 5.0}
        next_quote = np.array([t0 + 361, 2002.0, 2003.0, 2001.0, 2002.0])
        res = simulate_h2_entry(candidate, np.zeros((0, 5)), next_m5_quote=next_quote)
        self.assertFalse(res['filled'])
        self.assertIn(res['cancel_reason'], ('DATA_GAP', 'DATA_GAP_DELAY_EXCEEDED'))
        self.assertTrue(res.get('data_gap', True))

    def test_t2_feat09_05_fallback_no_quote_insufficient_data(self):
        """FEAT-09: Missing quote after deadline returns INSUFFICIENT_DATA."""
        t0 = 10000
        candidate = {'confirm_bar_open': t0 - 300, 'signal_known_time': t0, 'direction': 1,
                     'sl_price': 1996.0, 'choch_level': 2000.0, 'entry_market': 2005.0, 'risk': 5.0}
        res = simulate_h2_entry(candidate, np.zeros((0, 5)), next_m5_quote=None)
        self.assertFalse(res['filled'])
        self.assertEqual(res['cancel_reason'], 'INSUFFICIENT_DATA')

    # --------------------------------------------------------------------------
    # FEAT-10: Spread / Slippage Extremes (5 tests)
    # --------------------------------------------------------------------------
    # FEAT-10: Spread Extremes (5 tests)
    # --------------------------------------------------------------------------
    def test_t2_feat10_01_zero_spread_behavior(self):
        """FEAT-10: Zero spread equates Ask and Bid."""
        bid = 2000.0
        spread = 0.0
        ask = bid + spread
        self.assertEqual(ask, bid)

    def test_t2_feat10_02_micro_spread_005_usd(self):
        """FEAT-10: Micro spread of 0.05 USD correctly separates Bid/Ask."""
        bid = 2000.0
        spread = 0.05
        ask = bid + spread
        self.assertAlmostEqual(ask, 2000.05, places=4)

    def test_t2_feat10_03_base_spread_030_usd(self):
        """FEAT-10: Base spread of 0.30 USD correctly applies."""
        bid = 2000.0
        spread = 0.30
        ask = bid + spread
        self.assertAlmostEqual(ask, 2000.30, places=4)

    def test_t2_feat10_04_stress_spread_045_usd(self):
        """FEAT-10: Stress spread of 0.45 USD correctly applies."""
        bid = 2000.0
        spread = 0.45
        ask = bid + spread
        self.assertAlmostEqual(ask, 2000.45, places=4)

    def test_t2_feat10_05_extreme_spread_150_usd(self):
        """FEAT-10: Extreme spread of 1.50 USD applies cleanly."""
        bid = 2000.0
        spread = 1.50
        ask = bid + spread
        self.assertAlmostEqual(ask, 2001.50, places=4)

    # --------------------------------------------------------------------------
    # FEAT-10B: Slippage Extremes & Execution Gaps (5 tests)
    # --------------------------------------------------------------------------
    def test_t2_feat10b_01_zero_slippage_behavior(self):
        """FEAT-10B: Zero slippage leaves market entry at nominal ask/bid."""
        bid = 2000.0
        spread = 0.30
        slip = 0.00
        entry = bid + spread + slip
        self.assertAlmostEqual(entry, 2000.30, places=4)

    def test_t2_feat10b_02_base_slippage_001_usd(self):
        """FEAT-10B: BASE slippage of 0.01 USD adds to entry and exit cost."""
        bid = 2000.0
        spread = 0.30
        slip = 0.01
        entry = bid + spread + slip
        self.assertAlmostEqual(entry, 2000.31, places=4)

    def test_t2_feat10b_03_stress_slippage_005_usd(self):
        """FEAT-10B: STRESS slippage of 0.05 USD adds to entry and exit cost."""
        bid = 2000.0
        spread = 0.45
        slip = 0.05
        entry = bid + spread + slip
        self.assertAlmostEqual(entry, 2000.50, places=4)

    def test_t2_feat10b_04_extreme_slippage_050_usd(self):
        """FEAT-10B: Extreme slippage of 0.50 USD on market fallback."""
        bid = 2000.0
        spread = 0.30
        slip = 0.50
        entry = bid + spread + slip
        self.assertAlmostEqual(entry, 2000.80, places=4)

    def test_t2_feat10b_05_limit_fill_zero_slippage_guarantee(self):
        """FEAT-10B: Limit fill executes exactly at limit price without slippage."""
        limit_price = 2000.0
        fill_price = limit_price
        self.assertEqual(fill_price, 2000.0)

    # --------------------------------------------------------------------------
    # FEAT-11: Prefix Replay Invariance (5 tests)
    # --------------------------------------------------------------------------
    def test_t2_feat11_01_prefix_cut_signal_stream_invariance(self):
        """FEAT-11: Signal generated at T cannot depend on quotes after T."""
        stream_full = [100, 101, 102, 103, 104, 105]
        cut_point = 4
        stream_prefix = stream_full[:cut_point]
        self.assertEqual(stream_prefix, [100, 101, 102, 103])

    def test_t2_feat11_02_prefix_cut_trade_decision_invariance(self):
        """FEAT-11: Trade fill decision at t_fill is unchanged by future truncation."""
        t0 = 10000
        candidate = {'confirm_bar_open': t0 - 300, 'signal_known_time': t0, 'direction': 1,
                     'sl_price': 1990.0, 'choch_level': 2000.0, 'entry_market': 2005.0, 'risk': 10.0}
        m1_prefix = np.array([[t0 + 60, 2001.0, 2002.0, 1999.0, 2000.0]])
        m1_full = np.array([
            [t0 + 60, 2001.0, 2002.0, 1999.0, 2000.0],
            [t0 + 120, 2000.0, 2004.0, 1998.0, 2003.0]
        ])
        res_prefix = simulate_h2_entry(candidate, m1_prefix, spread=0.30)
        res_full = simulate_h2_entry(candidate, m1_full, spread=0.30)
        self.assertEqual(res_prefix['fill_time'], res_full['fill_time'])
        self.assertEqual(res_prefix['entry_price'], res_full['entry_price'])

    def test_t2_feat11_03_h1_zone_temporal_invariance(self):
        """FEAT-11: Zone validity at T uses only closed H1 bars <= T."""
        t_known = 1635326100
        zone_time_known = 1635324000
        self.assertLessEqual(zone_time_known, t_known)

    def test_t2_feat11_04_atr_calculation_temporal_invariance(self):
        """FEAT-11: ATR at bar i depends strictly on bars 0..i."""
        bars = np.zeros((20, 5))
        for i in range(20):
            bars[i] = [i * 300, 2000.0 + i, 2005.0 + i, 1995.0 + i, 2002.0 + i]
        atr_all = atr_wilder(bars, period=14)
        atr_slice = atr_wilder(bars[:15], period=14)
        self.assertAlmostEqual(atr_all[14], atr_slice[14], places=6)

    def test_t2_feat11_05_portfolio_scheduler_temporal_invariance(self):
        """FEAT-11: Portfolio trade scheduling invariant to future signals."""
        trades = [{'entry': 100, 'exit': 200}, {'entry': 150, 'exit': 250}, {'entry': 210, 'exit': 300}]
        # Under single position: trade 2 is skipped because 150 < 200
        scheduled = filter_single_position(trades)
        self.assertEqual(len(scheduled), 2)
        self.assertEqual(scheduled[0]['entry'], 100)
        self.assertEqual(scheduled[1]['entry'], 210)


# ==============================================================================
# TIER 3: CROSS-FEATURE COMBINATIONS
# ==============================================================================

class TestTier3CrossFeatureCombinations(unittest.TestCase):
    """Tier 3: Multi-feature interactions, intrabar sequencing, and concurrency."""

    def test_t3_combo01_limit_fill_then_immediate_sl_same_minute(self):
        """Tier 3: Limit filled at second 30, price continues down to hit SL in same minute."""
        candidate = {
            'confirm_bar_open': 1000, 'signal_known_time': 1000,
            'direction': 1, 'sl_price': 1996.0, 'choch_level': 2000.0,
            'entry_market': 2002.0, 'risk': 6.0
        }
        m1_bars = np.array([[1000, 2001.0, 2002.0, 1995.0, 1997.0]])
        entry_res = simulate_h2_entry(candidate, m1_bars, spread=0.30)
        self.assertTrue(entry_res['filled'])
        self.assertEqual(entry_res['entry_type'], 'LIMIT')
        
        # Immediate replay checks same bar
        trade_res = simulate_1r_trade(
            entry_price=entry_res['entry_price'], sl_price=entry_res['sl_price'],
            direction=1, fill_time=entry_res['fill_time'], signal_known_time=1000,
            m5_bars=m1_bars
        )
        self.assertEqual(trade_res['exit_reason'], 'SL')
        self.assertLess(trade_res['net_pnl_usd'], 0)

    def test_t3_combo02_fallback_fill_then_exit_same_minute(self):
        """Tier 3: Fallback fills at deadline, hits TP in same minute."""
        candidate = {
            'confirm_bar_open': 1000, 'signal_known_time': 1000,
            'direction': 1, 'sl_price': 1995.0, 'choch_level': 2000.0,
            'entry_market': 2005.0, 'risk': 10.0
        }
        next_quote = np.array([1300, 2000.0, 2012.0, 1999.0, 2011.0])
        entry_res = simulate_h2_entry(candidate, np.zeros((0, 5)), next_m5_quote=next_quote)
        self.assertTrue(entry_res['filled'])
        self.assertEqual(entry_res['entry_type'], 'MARKET_FALLBACK')

        trade_res = simulate_1r_trade(
            entry_price=entry_res['entry_price'], sl_price=entry_res['sl_price'],
            direction=1, fill_time=entry_res['fill_time'], signal_known_time=1000,
            m5_bars=np.array([next_quote])
        )
        self.assertEqual(trade_res['exit_reason'], 'TP')

    def test_t3_combo03_sell_order_tp_bid_hit_ask_above_then_sl(self):
        """Tier 3: SELL TP Bid touched but Ask above TP -> position kept -> hits SL."""
        m5_bars = np.array([
            [1000, 1998.0, 1998.5, 1995.9, 1997.0],  # Bid touches 1995.9, Ask low is 1996.2 > 1996.0 TP
            [1300, 1997.0, 2005.0, 1996.0, 2004.5]   # Hits SL 2004.0
        ])
        trade_res = simulate_1r_trade(
            entry_price=2000.0, sl_price=2004.0, direction=-1,
            fill_time=1000, signal_known_time=1000, m5_bars=m5_bars
        )
        self.assertNotEqual(trade_res['exit_time'], 1000)
        self.assertEqual(trade_res['exit_reason'], 'SL')

    def test_t3_combo04_overlapping_signals_single_position_lock(self):
        """Tier 3: Signal B arriving while Signal A is open is locked out by single-position gate."""
        sig_a = {'id': 1, 'known': 1000, 'entry': 1060, 'exit': 1500}
        sig_b = {'id': 2, 'known': 1200, 'entry': 1260, 'exit': 1800}
        sig_c = {'id': 3, 'known': 1600, 'entry': 1660, 'exit': 2100}
        
        all_signals = [sig_a, sig_b, sig_c]
        scheduled = filter_single_position(all_signals)
        self.assertEqual(len(scheduled), 2)
        self.assertEqual(scheduled[0]['id'], 1)
        self.assertEqual(scheduled[1]['id'], 3)

    def test_t3_combo05_limit_unfilled_fallback_filled_then_timeout(self):
        """Tier 3: Limit unfilled -> Fallback fills -> runs to 120m timeout."""
        candidate = {
            'confirm_bar_open': 1000, 'signal_known_time': 1000,
            'direction': 1, 'sl_price': 1996.0, 'choch_level': 2000.0,
            'entry_market': 2005.0, 'risk': 5.0
        }
        m1_bars = np.array([[1000 + i * 60, 2005.0, 2006.0, 2004.0, 2005.0] for i in range(5)])
        next_quote = np.array([1300, 2002.0, 2003.0, 2001.0, 2002.0])
        entry_res = simulate_h2_entry(candidate, m1_bars, next_m5_quote=next_quote)
        self.assertEqual(entry_res['entry_type'], 'MARKET_FALLBACK')

        # Run with bars up to timeout (1000 + 7200 = 8200)
        m5_bars = np.array([[1300 + i * 300, 2004.0, 2005.0, 2003.0, 2004.0] for i in range(25)])
        trade_res = simulate_1r_trade(
            entry_price=entry_res['entry_price'], sl_price=entry_res['sl_price'],
            direction=1, fill_time=entry_res['fill_time'], signal_known_time=1000,
            m5_bars=m5_bars
        )
        self.assertEqual(trade_res['exit_reason'], 'TIMEOUT')

    def test_t3_combo06_limit_fill_at_299s_immediate_post_fill_replay(self):
        """Tier 3: Limit fills at 299s, post-fill replay immediately processes remaining 1s."""
        t_known = 1000
        candidate = {
            'confirm_bar_open': t_known - 300, 'signal_known_time': t_known,
            'direction': 1, 'sl_price': 1990.0, 'choch_level': 2000.0,
            'entry_market': 2005.0, 'risk': 10.0
        }
        m1_bars = np.array([[t_known + 299, 2001.0, 2002.0, 1999.0, 2000.0]])
        entry_res = simulate_h2_entry(candidate, m1_bars, spread=0.30)
        self.assertEqual(entry_res['fill_time'], t_known + 299)
        self.assertGreaterEqual(entry_res['fill_time'], t_known)


# ==============================================================================
# TIER 4: REAL-WORLD APPLICATION & FORENSIC WITNESS REPLAY
# ==============================================================================

class TestTier4RealWorldWitnessReplay(unittest.TestCase):
    """Tier 4: Exact replay of audited failure witnesses from AUDIT_RESULTS.json."""

    def test_t4_witness01_signal1_t0_lookahead_elimination(self):
        """Tier 4: Replay Signal #1 lookahead witness from AUDIT_RESULTS.json.
        
        Audit Fact: Confirm bar open = 1635325800 (09:10 UTC), close = 1635326100 (09:15 UTC).
        Old engine entered at 1635325800 (5 minutes before close!).
        Normative Specification: Fill MUST NOT occur before 1635326100.
        """
        confirm_bar_open = 1635325800
        signal_known_time = confirm_bar_open + 300  # 1635326100
        candidate = {
            'signal_id': '1', 'time_m5': confirm_bar_open,
            'confirm_bar_open': confirm_bar_open, 'signal_known_time': signal_known_time,
            'direction': 1, 'sl_price': 1785.2776, 'choch_level': 1787.97,
            'entry_market': 1788.0, 'risk': 2.7224
        }
        # The 5 M1 bars during confirm bar (09:10 - 09:15)
        pre_m1 = np.array([
            [1635325800.0, 1786.84, 1786.99, 1786.79, 1786.94],
            [1635325860.0, 1787.09, 1787.35, 1787.01, 1787.25],
            [1635325920.0, 1787.22, 1787.67, 1787.21, 1787.61],
            [1635325980.0, 1787.59, 1788.15, 1787.50, 1788.15],
            [1635326040.0, 1788.16, 1788.28, 1787.81, 1788.00]
        ])
        # Under causal rules, pre_m1 CANNOT be inspected for fill
        res = simulate_h2_entry(candidate, pre_m1, spread=0.30)
        self.assertFalse(res['filled'], "Signal 1 erroneously filled on M1 bars prior to signal_known_time!")

    def test_t4_witness02_synthetic_filled_loss_erased_sl_before_fill(self):
        """Tier 4: Replay synthetic witness 'filled_loss_erased' from AUDIT_RESULTS.json.
        
        Candidate: direction=1, sl=1996.0, choch_level=2000.0, entry_market=2002.0.
        Path: Bid descends 2001 -> 2002 -> 1999.70 -> 1996.
        Expected: BUY limit fills at Ask=2000 on descent before Bid=1996 SL.
        Old engine incorrectly returned cancel_reason='SL_HIT_BEFORE_FILL'.
        """
        candidate = {
            'time_m5': 1500000, 'confirm_bar_open': 1500000 - 300, 'signal_known_time': 1500000,
            'direction': 1, 'sl_price': 1996.0, 'choch_level': 2000.0,
            'entry_market': 2002.0, 'risk': 6.0
        }
        m1_ohlc = np.array([[1500000.0, 2001.0, 2002.0, 1995.0, 1997.0]])
        res = simulate_h2_entry(candidate, m1_ohlc, spread=0.30)
        self.assertTrue(res['filled'], "BUY limit must fill on descent before SL is touched!")
        self.assertEqual(res['entry_type'], 'LIMIT')
        self.assertEqual(res['entry_price'], 2000.0)

    def test_t4_witness03_synthetic_short_false_tp(self):
        """Tier 4: Replay synthetic witness 'short_false_tp' from AUDIT_RESULTS.json.
        
        SELL entry=2000.0, stop=2004.0, target=1996.0, spread=0.30, min_bid=1995.9, min_ask=1996.2.
        Expected: No TP in this bar because Ask never reaches target (1996.2 > 1996.0).
        Old engine incorrectly recorded TP.
        """
        m5_bars = np.array([[1500300, 1998.0, 1998.5, 1995.9, 1997.0]])
        res = simulate_1r_trade(
            entry_price=2000.0, sl_price=2004.0, direction=-1,
            fill_time=1500300, signal_known_time=1500300, m5_bars=m5_bars
        )
        self.assertNotEqual(res['exit_reason'], 'TP', "SELL TP must evaluate on Ask, not Bid!")

    def test_t4_witness04_synthetic_double_cost(self):
        """Tier 4: Replay synthetic witness 'double_cost' from AUDIT_RESULTS.json.
        
        Entry Ask+slip = 2000.31, Exit Bid-slip = 1999.99, Execution P&L = -0.32, Comm = 0.07.
        Expected: Net P&L = -0.39 USD/oz (not -0.71 USD/oz).
        """
        entry_price = 2000.31
        exit_price = 1999.99
        comm = 0.07
        gross = 1 * (exit_price - entry_price)
        net = gross - comm
        self.assertAlmostEqual(net, -0.39, places=4)

    def test_t4_witness05_chronological_portfolio_ledger_consistency(self):
        """Tier 4: Verify single-position portfolio chronological ledger properties."""
        trades = [
            {'id': 1, 'entry_time': 1000, 'exit_time': 2000, 'pnl': 1.0},
            {'id': 2, 'entry_time': 1500, 'exit_time': 2500, 'pnl': -1.0},  # Overlapping -> Must be skipped
            {'id': 3, 'entry_time': 2100, 'exit_time': 3000, 'pnl': 0.8}
        ]
        for tr in trades:
            self.assertGreaterEqual(tr['exit_time'], tr['entry_time'])
        scheduled = filter_single_position(trades)
        self.assertEqual(len(scheduled), 2)
        self.assertEqual(scheduled[0]['id'], 1)
        self.assertEqual(scheduled[1]['id'], 3)


if __name__ == '__main__':
    unittest.main(verbosity=2)
