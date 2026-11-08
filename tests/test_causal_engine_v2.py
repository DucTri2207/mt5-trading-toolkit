"""Comprehensive Causal Engine Verification Test Suite (v2).

Validates all 5 critical audit defect fixes and Requirements R1, R2, R3, R4:
1. Causal Time Separation (R2):
   - Explicit separation of confirm_bar_open, signal_known_time, publish_time, order_place_time, fill_time, exit_time.
   - No lookahead bias: signal known strictly when confirmation bar closes (+300s for M5).
   - M1 quotes before signal_known_time are never peeked or filled.
2. LIMIT vs MARKET_FALLBACK Execution Windows (R2):
   - LIMIT fills strictly in [signal_known_time, signal_known_time + 300s).
   - MARKET_FALLBACK triggers at first quote >= deadline (signal_known_time + 300s) with max 60s delay.
   - Data gap / delay > 60s rejects fallback with DATA_GAP_DELAY_EXCEEDED (no future quote gapping).
   - Hard runtime assertions enforced: fill_time >= signal_known_time, exit_time >= fill_time,
     fallback_time >= deadline.
3. Intrabar Ordering & Adverse Path Selection (R3):
   - Resolved Witness 2 (filled_loss_erased): Price touching limit before SL records fill, then evaluates SL.
   - Immediate exit replay post-fill (evaluates remainder of fill bar).
   - Fake exit timestamp 'b_time + 120' completely eliminated.
4. Bid/Ask Price Normalization (R4):
   - BUY enters Ask, exits Bid.
   - SELL enters Bid, exits Ask.
   - Resolved Witness 3 (short_false_tp): SELL TP requires Ask <= tp_price. Bid <= tp with Ask > tp never awards TP.
   - SELL SL requires Ask >= sl_price.
5. Consistent Fee Accounting (R4):
   - Resolved Witness 4 (double_cost): Execution prices already reflect spread and slippage.
     Net P&L = Gross P&L - Commission. Spread and slippage are not deducted twice.
6. Strict 120-Minute Timeout (R2):
   - Timeout occurs at strictly signal_known_time + 7200 seconds.
"""
import math
import sys
import unittest
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))

from gold_v301_causal_core import (
    FEE_SCHEDULES,
    simulate_h2_entry,
    simulate_1r_trade,
    filter_single_position,
    detect_all_candidates,
    select_h1_candidate,
)


class TestCausalTimeSeparation(unittest.TestCase):
    """Test Requirement R2: Causal time separation and lookahead elimination."""

    def setUp(self):
        # M5 confirmation bar opens at 09:10:00 (1635325800) and closes at 09:15:00 (1635326100)
        self.confirm_bar_open = 1635325800
        self.signal_known_time = 1635326100  # confirm_bar_open + 300
        self.cand_buy = {
            'confirm_bar_open': self.confirm_bar_open,
            'signal_known_time': self.signal_known_time,
            'publish_time': self.signal_known_time,
            'order_place_time': self.signal_known_time,
            'time_m5': self.confirm_bar_open,
            'exec_time': self.signal_known_time,
            'direction': 1,
            'entry_market': 1788.0,
            'sl_price': 1783.0,
            'risk': 5.0,
            'choch_level': 1787.0
        }

    def test_no_fill_before_signal_known_time(self):
        """Pre-confirmation M1 quotes inside [confirm_bar_open, signal_known_time) must NEVER fill."""
        # 5 M1 bars inside the confirmation candle (09:10 to 09:14) where price crosses limit
        pre_signal_m1 = np.array([
            [self.confirm_bar_open + 0, 1787.5, 1788.0, 1786.5, 1787.0],    # Low 1786.5 + 0.30 = 1786.8 <= 1787.0
            [self.confirm_bar_open + 60, 1787.0, 1787.5, 1786.2, 1786.8],
            [self.confirm_bar_open + 120, 1786.8, 1787.2, 1786.0, 1786.5],
            [self.confirm_bar_open + 180, 1786.5, 1787.0, 1786.1, 1786.7],
            [self.confirm_bar_open + 240, 1786.7, 1787.5, 1786.5, 1787.2],
        ])
        # Next quote is at signal_known_time (09:15:00)
        next_quote = np.array([self.signal_known_time, 1788.0, 1788.5, 1787.8, 1788.2])

        # Pre-confirmation bars must be ignored; fallback cannot trigger at 09:15 because deadline is 09:20
        res = simulate_h2_entry(self.cand_buy, pre_signal_m1, next_quote, spread=0.30, slip=0.01)
        self.assertFalse(res['filled'], "Pre-signal M1 bars must NOT trigger limit fills!")
        self.assertTrue(res['cancelled'])
        self.assertEqual(res['cancel_reason'], "INSUFFICIENT_DATA")

    def test_limit_fill_strictly_in_causal_window(self):
        """Limit fill allowed strictly in [signal_known_time, signal_known_time + 300s)."""
        # M1 bars starting at 09:15:00 (signal_known_time)
        causal_m1 = np.array([
            [self.signal_known_time + 0, 1788.0, 1788.2, 1787.5, 1787.8],
            [self.signal_known_time + 60, 1787.8, 1788.0, 1786.5, 1786.9],  # Ask low = 1786.5 + 0.3 = 1786.8 <= 1787.0 -> FILLS!
            [self.signal_known_time + 120, 1786.9, 1787.5, 1786.8, 1787.2],
        ])
        next_quote = np.array([self.signal_known_time + 300, 1787.5, 1788.0, 1787.2, 1787.8])

        res = simulate_h2_entry(self.cand_buy, causal_m1, next_quote, spread=0.30, slip=0.01)
        self.assertTrue(res['filled'])
        self.assertEqual(res['entry_type'], "LIMIT")
        self.assertEqual(res['fill_time'], self.signal_known_time + 60)
        self.assertGreaterEqual(res['fill_time'], self.signal_known_time)
        self.assertLess(res['fill_time'], self.signal_known_time + 300)
        self.assertAlmostEqual(res['entry_price'], 1787.0)

    def test_market_fallback_at_deadline_with_delay_guard(self):
        """Fallback triggers at first quote >= deadline (within 60s delay)."""
        # Price hovers above limit during 5 minutes
        m1_bars = np.array([
            [self.signal_known_time + 0, 1788.0, 1788.5, 1787.8, 1788.2],
            [self.signal_known_time + 60, 1788.2, 1788.6, 1787.9, 1788.4],
            [self.signal_known_time + 120, 1788.4, 1788.8, 1788.0, 1788.5],
            [self.signal_known_time + 180, 1788.5, 1788.9, 1788.1, 1788.6],
            [self.signal_known_time + 240, 1788.6, 1789.0, 1788.2, 1788.8],
        ])
        # Quote at deadline (signal_known_time + 300, delay = 0s)
        deadline_quote = np.array([self.signal_known_time + 300, 1788.5, 1789.0, 1788.2, 1788.7])

        res = simulate_h2_entry(self.cand_buy, m1_bars, deadline_quote, spread=0.30, slip=0.01)
        self.assertTrue(res['filled'])
        self.assertEqual(res['entry_type'], "MARKET_FALLBACK")
        self.assertEqual(res['fill_time'], self.signal_known_time + 300)
        # BUY Fallback enters at Bid 1788.5 + spread 0.30 + slip 0.01 = 1788.81
        self.assertAlmostEqual(res['entry_price'], 1788.81, places=4)

    def test_market_fallback_delay_exceeded_guard(self):
        """If fallback quote delay > 60s (e.g. data gap or weekend), reject with DATA_GAP."""
        m1_bars = np.array([
            [self.signal_known_time + 0, 1788.0, 1788.5, 1787.8, 1788.2],
        ])
        # Quote arrives 120s after deadline (delay = 120s > 60s)
        gapped_quote = np.array([self.signal_known_time + 420, 1788.5, 1789.0, 1788.2, 1788.7])

        res = simulate_h2_entry(self.cand_buy, m1_bars, gapped_quote, spread=0.30, slip=0.01)
        self.assertFalse(res['filled'])
        self.assertTrue(res['cancelled'])
        self.assertEqual(res['cancel_reason'], "DATA_GAP_DELAY_EXCEEDED")
        self.assertTrue(res['data_gap'])


class TestWitnessAuditVerifications(unittest.TestCase):
    """Test resolution of exact synthetic witnesses from audit report."""

    def setUp(self):
        self.t0 = 1500000

    def test_witness2_filled_loss_erased_resolved(self):
        """Witness 2: Price touching limit before SL must record fill then evaluate SL (not erase loss)."""
        candidate = {
            "time_m5": self.t0,
            "exec_time": self.t0,
            "signal_known_time": self.t0,
            "direction": 1,
            "sl_price": 1996.0,
            "choch_level": 2000.0,
            "entry_market": 2002.0,
            "risk": 6.0
        }
        # Continuous Bid path: 2001 -> 2002 -> 1999.7 (Ask=2000.0, LIMIT FILLS) -> 1996.0 (SL HITS) -> 1995 -> 1997
        one_minute = np.array([[self.t0, 2001.0, 2002.0, 1995.0, 1997.0]])

        # 1. Verify Entry: Must FILL limit, NOT cancel as SL_HIT_BEFORE_FILL
        entry_res = simulate_h2_entry(candidate, one_minute, None, spread=0.30, slip=0.01)
        self.assertTrue(entry_res['filled'], "Order must be filled when price crosses limit before SL!")
        self.assertEqual(entry_res['entry_type'], "LIMIT")
        self.assertAlmostEqual(entry_res['entry_price'], 2000.0)
        self.assertTrue(entry_res['ambiguous_intrabar'])

        # 2. Verify Payoff: Position must evaluate remainder of the bar and hit SL
        trade = simulate_1r_trade(
            entry_price=entry_res['entry_price'],
            sl_price=entry_res['sl_price'],
            direction=1,
            fill_time=entry_res['fill_time'],
            t0=self.t0,
            m5_bars=None,
            m5_start_idx=0,
            schedule='BASE',
            is_limit=True,
            signal_known_time=self.t0,
            m1_bars=one_minute
        )
        self.assertEqual(trade['exit_reason'], "SL")
        self.assertAlmostEqual(trade['exit_price'], 1996.0 - 0.01)  # SL minus exit slippage = 1995.99
        self.assertLess(trade['net_pnl_usd'], 0.0, "Must be recorded as a real losing trade, not erased!")
        self.assertLess(trade['net_r'], 0.0)

    def test_witness3_short_false_tp_resolved(self):
        """Witness 3: SELL TP requires Ask <= tp_price. Bid reaching TP while Ask > TP must NOT award TP."""
        # SELL entry 2000.0, stop 2004.0, target 1996.0, spread 0.30
        # M5 bar: Bid Low = 1995.90 -> Ask Low = 1996.20 > TP 1996.00
        sell_bars = np.array([[self.t0 + 300, 1999.0, 2000.5, 1995.9, 1997.0]])

        trade = simulate_1r_trade(
            entry_price=2000.0,
            sl_price=2004.0,
            direction=-1,
            fill_time=self.t0 + 300,
            t0=self.t0,
            m5_bars=sell_bars,
            m5_start_idx=0,
            schedule='BASE',
            is_limit=False,
            signal_known_time=self.t0
        )
        # Ask low was 1996.20, target was 1996.00 -> Ask NEVER reached TP!
        self.assertNotEqual(trade['exit_reason'], "TP", "SELL TP must check Ask price, not Bid!")

        # Now test when Ask DOES reach TP (Bid low = 1995.60 -> Ask low = 1995.90 <= 1996.00)
        sell_bars_hit = np.array([[self.t0 + 300, 1999.0, 2000.5, 1995.6, 1997.0]])
        trade_hit = simulate_1r_trade(
            entry_price=2000.0,
            sl_price=2004.0,
            direction=-1,
            fill_time=self.t0 + 300,
            t0=self.t0,
            m5_bars=sell_bars_hit,
            m5_start_idx=0,
            schedule='BASE',
            is_limit=False,
            signal_known_time=self.t0
        )
        self.assertEqual(trade_hit['exit_reason'], "TP")
        self.assertAlmostEqual(trade_hit['exit_price'], 1996.0)

    def test_witness4_double_cost_accounting_resolved(self):
        """Witness 4: Single-deduction accounting. Net P&L = Gross P&L - Commission."""
        # BUY entry (Ask + slip) = 2000.31, exit (Bid - slip) = 1999.99
        # Execution PnL = 1999.99 - 2000.31 = -0.32 USD
        # Commission (BASE) = 0.07 USD
        # Correct Net P&L = -0.32 - 0.07 = -0.39 USD (NOT -0.71 USD)
        timeout_bars = np.array([[self.t0 + 7200, 2000.0, 2000.0, 2000.0, 2000.0]])

        trade = simulate_1r_trade(
            entry_price=2000.31,
            sl_price=1996.31,
            direction=1,
            fill_time=self.t0 + 300,
            t0=self.t0,
            m5_bars=timeout_bars,
            m5_start_idx=0,
            schedule='BASE',
            is_limit=False,
            signal_known_time=self.t0
        )
        self.assertEqual(trade['exit_reason'], "TIMEOUT")
        self.assertAlmostEqual(trade['gross_pnl_usd'], -0.32, places=4)
        self.assertAlmostEqual(trade['commission_usd'], 0.07, places=4)
        # Net P&L must be exactly -0.39 (single commission deduction)
        self.assertAlmostEqual(trade['net_pnl_usd'], -0.39, places=4)
        self.assertNotAlmostEqual(trade['net_pnl_usd'], -0.71, places=2)

    def test_witness5_exit_timing_no_fake_120(self):
        """Witness 5: Exit timestamps must NOT be hardcoded to fake 'b_time + 120'."""
        m5_bars = np.array([
            [self.t0 + 300, 2001.0, 2005.0, 2000.5, 2004.5],  # High touches TP
        ])
        trade = simulate_1r_trade(
            entry_price=2000.0,
            sl_price=1996.0,
            direction=1,
            fill_time=self.t0 + 300,
            t0=self.t0,
            m5_bars=m5_bars,
            m5_start_idx=0,
            schedule='BASE',
            is_limit=False,
            signal_known_time=self.t0
        )
        self.assertEqual(trade['exit_reason'], "TP")
        # Exit time must be bar native timestamp, NOT b_time + 120
        self.assertNotEqual(trade['exit_time'], self.t0 + 300 + 120)
        self.assertEqual(trade['exit_time'], self.t0 + 300)
        self.assertGreaterEqual(trade['exit_time'], trade['entry_time'])


class TestHardRuntimeAssertions(unittest.TestCase):
    """Test hard runtime assertions enforcing physical simulation causality."""

    def test_assert_fill_time_not_before_signal_known(self):
        """Engine must raise AssertionError if fill_time < signal_known_time."""
        with self.assertRaises(AssertionError):
            simulate_1r_trade(
                entry_price=2000.0,
                sl_price=1996.0,
                direction=1,
                fill_time=1500000,
                t0=1500300,
                m5_bars=np.array([[1500300, 2000.0, 2005.0, 1999.0, 2004.0]]),
                m5_start_idx=0,
                signal_known_time=1500300  # fill_time 1500000 < signal_known_time 1500300 -> MUST ASSERT!
            )

    def test_assert_fallback_not_before_deadline(self):
        """Engine must raise AssertionError if MARKET_FALLBACK fill_time < deadline."""
        with self.assertRaises(AssertionError):
            simulate_1r_trade(
                entry_price=2000.0,
                sl_price=1996.0,
                direction=1,
                fill_time=1500100,  # before deadline 1500000 + 300 = 1500300
                t0=1500000,
                m5_bars=np.array([[1500300, 2000.0, 2005.0, 1999.0, 2004.0]]),
                m5_start_idx=0,
                signal_known_time=1500000,
                entry_type="MARKET_FALLBACK"
            )


if __name__ == '__main__':
    unittest.main()
