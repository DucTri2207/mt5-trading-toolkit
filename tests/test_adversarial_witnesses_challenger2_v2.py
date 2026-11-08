"""Independent Adversarial Stress & Witness Verification Suite.

Authored by: m1_challenger_2_v2 (Empirical Challenger)
Target: scripts/gold_v301_causal_core.py

Focus Areas:
1. BUY Limit vs SL witness: Adversarial bar where low touches limit then drops to SL.
   Verify limit fill is recorded first, then SL exit is evaluated on subsequent prices/bars.
2. SELL TP vs Ask witness (short_false_tp): Bar where Bid low reaches TP price,
   but Ask low (Bid low + spread) is strictly above TP price. Verify engine REJECTS TP
   and keeps trade open, exiting via timeout or SL or subsequent true Ask TP.
3. Fee deduplication witness (double_cost): Across 100 random simulated trades, verify:
   gross_pnl_usd = (exit_price - entry_price) * size (for BUY)
   net_pnl_usd = gross_pnl_usd - commission_usd
   Verify spread and slippage are NOT subtracted twice in net_pnl_usd or net_r.
4. Edge cases: Causal window deadlines, fallback delays, and adverse selection.
"""
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
)


class TestBuyLimitVsSlWitness(unittest.TestCase):
    """Stress testing Focus 1: BUY Limit vs SL sequence and filled loss retention."""

    def setUp(self):
        self.signal_known_time = 1635326100  # 09:15:00
        self.confirm_bar_open = 1635325800   # 09:10:00
        self.cand_buy = {
            'confirm_bar_open': self.confirm_bar_open,
            'signal_known_time': self.signal_known_time,
            'publish_time': self.signal_known_time,
            'order_place_time': self.signal_known_time,
            'time_m5': self.confirm_bar_open,
            'exec_time': self.signal_known_time,
            'direction': 1,
            'entry_market': 1790.0,
            'sl_price': 1783.0,
            'risk': 7.0,
            'choch_level': 1787.0  # Limit placed here
        }
        self.spread = 0.30
        self.slip = 0.01

    def test_witness_buy_limit_then_sl_same_bar(self):
        """Adversarial Bar: Opens above limit, drops through limit, then drops to SL.
        
        The overhauled engine must record the limit fill FIRST, flag ambiguous intrabar,
        and subsequently evaluate the SL exit on the fill bar (retaining the loss).
        """
        bar_t = self.signal_known_time + 60  # 09:16:00
        # Bar: open 1789.0 (above limit 1787.0), high 1789.5, low 1782.0 (below SL 1783.0), close 1782.5
        # Ask low = 1782.0 + 0.30 = 1782.30 <= 1787.0 (limit touched!)
        adversarial_m1 = np.array([
            [bar_t, 1789.0, 1789.5, 1782.0, 1782.5],
        ])

        # Step 1: Simulate entry
        entry_res = simulate_h2_entry(self.cand_buy, adversarial_m1, spread=self.spread, slip=self.slip)
        self.assertTrue(entry_res['filled'], "Order must be FILLED when price crosses limit from above!")
        self.assertFalse(entry_res['cancelled'], "Filled loss must NOT be cancelled!")
        self.assertEqual(entry_res['entry_type'], "LIMIT")
        self.assertEqual(entry_res['entry_price'], 1787.0)
        self.assertEqual(entry_res['fill_time'], bar_t)
        self.assertTrue(entry_res['ambiguous_intrabar'], "Ambiguous intrabar must be flagged when both limit & SL are breached!")

        # Step 2: Simulate trade execution
        trade_res = simulate_1r_trade(
            entry_price=entry_res['entry_price'],
            sl_price=entry_res['sl_price'],
            direction=1,
            fill_time=entry_res['fill_time'],
            t0=self.signal_known_time,
            m5_bars=None,
            m5_start_idx=0,
            schedule='BASE',
            signal_known_time=self.signal_known_time,
            m1_bars=adversarial_m1,
            entry_type=entry_res['entry_type'],
            ambiguous_intrabar=entry_res['ambiguous_intrabar']
        )

        self.assertEqual(trade_res['exit_reason'], "SL", "Trade must exit via SL on the fill bar!")
        self.assertEqual(trade_res['exit_time'], bar_t)
        self.assertAlmostEqual(trade_res['exit_price'], 1783.0 - self.slip, places=6)
        # Gross loss = 1782.99 - 1787.0 = -4.01
        self.assertAlmostEqual(trade_res['gross_pnl_usd'], -4.01, places=6)
        # Net loss = gross - commission (0.07) = -4.08
        self.assertAlmostEqual(trade_res['net_pnl_usd'], -4.08, places=6)

    def test_witness_buy_limit_fill_then_sl_next_bar(self):
        """Sequential Bars: Bar 0 touches limit (fills), Bar 1 drops to SL.
        
        Verify trade stays open during Bar 0 and exits via SL on Bar 1.
        """
        bar0_t = self.signal_known_time + 60
        bar1_t = self.signal_known_time + 120
        # Bar 0: open 1788.0, high 1788.5, low 1786.5 (Ask low 1786.8 <= 1787.0, but > SL 1783.0), close 1786.7
        # Bar 1: open 1786.7, high 1787.0, low 1782.0 (below SL 1783.0), close 1782.5
        m1_bars = np.array([
            [bar0_t, 1788.0, 1788.5, 1786.5, 1786.7],
            [bar1_t, 1786.7, 1787.0, 1782.0, 1782.5],
        ])

        entry_res = simulate_h2_entry(self.cand_buy, m1_bars, spread=self.spread, slip=self.slip)
        self.assertTrue(entry_res['filled'])
        self.assertEqual(entry_res['entry_type'], "LIMIT")
        self.assertEqual(entry_res['fill_time'], bar0_t)
        self.assertFalse(entry_res['ambiguous_intrabar'])

        trade_res = simulate_1r_trade(
            entry_price=entry_res['entry_price'],
            sl_price=entry_res['sl_price'],
            direction=1,
            fill_time=entry_res['fill_time'],
            t0=self.signal_known_time,
            m5_bars=None,
            m5_start_idx=0,
            schedule='BASE',
            signal_known_time=self.signal_known_time,
            m1_bars=m1_bars,
            entry_type=entry_res['entry_type'],
            ambiguous_intrabar=entry_res['ambiguous_intrabar']
        )

        self.assertEqual(trade_res['exit_reason'], "SL")
        self.assertEqual(trade_res['exit_time'], bar1_t, "Exit must occur on Bar 1 where SL is touched!")
        self.assertAlmostEqual(trade_res['exit_price'], 1783.0 - self.slip, places=6)

    def test_counter_case_gap_open_below_sl_cancels(self):
        """Counter-case: Price gaps open below SL before touching limit. Must cancel."""
        bar_t = self.signal_known_time + 60
        # Bar opens at 1782.0 (strictly below SL 1783.0)
        gap_down_m1 = np.array([
            [bar_t, 1782.0, 1784.0, 1781.0, 1783.5],
        ])
        entry_res = simulate_h2_entry(self.cand_buy, gap_down_m1, spread=self.spread, slip=self.slip)
        self.assertFalse(entry_res['filled'])
        self.assertTrue(entry_res['cancelled'])
        self.assertEqual(entry_res['cancel_reason'], "SL_HIT_BEFORE_FILL")

    def test_counter_case_tp_before_limit_cancels(self):
        """Counter-case: Price rallies to TP before touching limit. Must cancel."""
        bar_t = self.signal_known_time + 60
        # baseline_tp = 1790.0 + 1.0 * 7.0 = 1797.0
        # Bar: open 1791.0, high 1798.0 (>= TP 1797.0), low 1788.0 (Ask low 1788.3 > limit 1787.0)
        rally_m1 = np.array([
            [bar_t, 1791.0, 1798.0, 1788.0, 1796.0],
        ])
        entry_res = simulate_h2_entry(self.cand_buy, rally_m1, spread=self.spread, slip=self.slip)
        self.assertFalse(entry_res['filled'])
        self.assertTrue(entry_res['cancelled'])
        self.assertEqual(entry_res['cancel_reason'], "TP_HIT_BEFORE_FILL")


class TestSellTpVsAskWitness(unittest.TestCase):
    """Stress testing Focus 2: SELL TP vs Ask price matching (short_false_tp)."""

    def setUp(self):
        self.signal_known_time = 1635326100
        self.fill_time = self.signal_known_time
        self.entry_price = 2000.0
        self.sl_price = 2005.0
        self.d_actual = 5.0
        self.tp_price = 1995.0  # 2000.0 - 5.0
        self.spread = 0.30
        self.slip = 0.01

    def test_short_false_tp_rejected_and_subsequent_sl(self):
        """Witness short_false_tp: Bid reaches TP but Ask does not. Must REJECT TP.
        
        Bar 1: Bid low is 1994.80 (<= TP 1995.0), but Ask low is 1994.80 + 0.30 = 1995.10 (> TP).
        Bar 2: Price reverses; Ask high reaches 2005.30 (>= SL 2005.0).
        The overhauled engine must REJECT TP on Bar 1 and take SL on Bar 2!
        """
        bar1_t = self.fill_time + 60
        bar2_t = self.fill_time + 120

        # Bar 1: Bid low touches 1994.80, but Ask low is 1995.10
        # Bar 2: Rallies; Bid high 2005.00 -> Ask high 2005.30 >= SL 2005.0
        m1_bars = np.array([
            [self.fill_time, 2000.0, 2001.0, 1999.0, 1999.5],  # Fill bar
            [bar1_t, 1999.5, 2000.0, 1994.8, 1997.0],          # False TP candidate
            [bar2_t, 1997.0, 2005.0, 1996.5, 2004.0],          # Reversal to SL
        ])

        res = simulate_1r_trade(
            entry_price=self.entry_price,
            sl_price=self.sl_price,
            direction=-1,
            fill_time=self.fill_time,
            t0=self.signal_known_time,
            m5_bars=None,
            m5_start_idx=0,
            schedule='BASE',
            signal_known_time=self.signal_known_time,
            m1_bars=m1_bars,
            entry_type='LIMIT'
        )

        # Crucial check: Exit MUST NOT be TP!
        self.assertNotEqual(res['exit_reason'], "TP", "TP must NOT trigger when Ask low is above TP price!")
        self.assertEqual(res['exit_reason'], "SL", "Trade must exit via SL on Bar 2!")
        self.assertEqual(res['exit_time'], bar2_t)
        self.assertAlmostEqual(res['exit_price'], self.sl_price + self.slip, places=6)
        # Gross loss = -(2005.01 - 2000.0) = -5.01
        self.assertAlmostEqual(res['gross_pnl_usd'], -5.01, places=6)

    def test_short_false_tp_rejected_and_timeout(self):
        """Witness short_false_tp: Bid reaches TP but Ask does not, then market times out.
        
        Must exit via TIMEOUT at signal_known_time + 7200, NOT via TP.
        """
        bar1_t = self.fill_time + 60
        timeout_t = self.signal_known_time + 7200

        # Bar 1 has Bid low 1994.80 (Ask low 1995.10 > TP 1995.0)
        # Bar 2 reaches timeout time at 1997.0
        m1_bars = np.array([
            [self.fill_time, 2000.0, 2001.0, 1999.0, 1999.5],
            [bar1_t, 1999.5, 2000.0, 1994.8, 1997.0],
            [timeout_t, 1997.0, 1998.0, 1996.5, 1997.5],
        ])

        res = simulate_1r_trade(
            entry_price=self.entry_price,
            sl_price=self.sl_price,
            direction=-1,
            fill_time=self.fill_time,
            t0=self.signal_known_time,
            m5_bars=None,
            m5_start_idx=0,
            schedule='BASE',
            signal_known_time=self.signal_known_time,
            m1_bars=m1_bars,
            entry_type='LIMIT'
        )

        self.assertEqual(res['exit_reason'], "TIMEOUT")
        self.assertEqual(res['exit_time'], timeout_t)
        # SELL exit at timeout: b_open + spread + slip = 1997.0 + 0.30 + 0.01 = 1997.31
        self.assertAlmostEqual(res['exit_price'], 1997.31, places=6)

    def test_short_true_tp_when_ask_reaches_tp(self):
        """True TP: Ask reaches TP price (Bid low 1994.50 -> Ask low 1994.80 <= 1995.0)."""
        bar1_t = self.fill_time + 60
        m1_bars = np.array([
            [self.fill_time, 2000.0, 2001.0, 1999.0, 1999.5],
            [bar1_t, 1999.5, 2000.0, 1994.5, 1994.8],  # Bid low 1994.50 + 0.30 = 1994.80 <= 1995.0!
        ])

        res = simulate_1r_trade(
            entry_price=self.entry_price,
            sl_price=self.sl_price,
            direction=-1,
            fill_time=self.fill_time,
            t0=self.signal_known_time,
            m5_bars=None,
            m5_start_idx=0,
            schedule='BASE',
            signal_known_time=self.signal_known_time,
            m1_bars=m1_bars,
            entry_type='LIMIT'
        )

        self.assertEqual(res['exit_reason'], "TP")
        self.assertEqual(res['exit_time'], bar1_t)
        self.assertAlmostEqual(res['exit_price'], self.tp_price, places=6)
        # Gross profit = -(1995.0 - 2000.0) = +5.00
        self.assertAlmostEqual(res['gross_pnl_usd'], 5.00, places=6)

    def test_m5_replay_short_false_tp_parity(self):
        """Parity: M5 replay path also strictly checks Ask low <= TP."""
        m5_bars = np.array([
            [self.fill_time, 2000.0, 2001.0, 1994.8, 1997.0],  # Bid low 1994.8, Ask low 1995.10 > TP 1995.0
            [self.fill_time + 300, 1997.0, 2005.0, 1996.5, 2004.5],  # Ask high 2005.30 >= SL 2005.0
        ])

        res = simulate_1r_trade(
            entry_price=self.entry_price,
            sl_price=self.sl_price,
            direction=-1,
            fill_time=self.fill_time,
            t0=self.signal_known_time,
            m5_bars=m5_bars,
            m5_start_idx=0,
            schedule='BASE',
            signal_known_time=self.signal_known_time,
            m1_bars=None,  # Force M5 replay
            entry_type='LIMIT'
        )

        self.assertNotEqual(res['exit_reason'], "TP")
        self.assertEqual(res['exit_reason'], "SL")


class TestFeeDeduplicationWitness(unittest.TestCase):
    """Stress testing Focus 3: Fee deduplication across 100 random simulated trades."""

    def test_monte_carlo_100_trades_single_cost_deduction(self):
        """Empirically test 100 diverse trades across random directions, schedules, and exits.
        
        Strictly verify:
        1. gross_pnl_usd == (exit_price - entry_price) * size for BUY
        2. gross_pnl_usd == (entry_price - exit_price) * size for SELL
        3. net_pnl_usd == gross_pnl_usd - commission_usd
        4. net_r == net_pnl_usd / risk_usd
        5. Spread and slippage are NOT deducted twice:
           net_pnl_usd != gross_pnl_usd - comm - spread - slippage (when spread/slip > 0).
        """
        np.random.seed(42)  # Deterministic seed for reproducible adversarial harness
        schedules = ['LOW', 'BASE', 'STRESS']
        size = 1.0

        discrepancies_gross = []
        discrepancies_net = []
        discrepancies_net_r = []
        double_deduction_detected = []

        for i in range(100):
            sched_name = np.random.choice(schedules)
            spread, comm, slip = FEE_SCHEDULES[sched_name]
            direction = int(np.random.choice([1, -1]))
            entry_type = np.random.choice(['LIMIT', 'MARKET_FALLBACK', 'MARKET'])
            
            # Base price levels
            entry_bid = np.random.uniform(1700.0, 2400.0)
            risk_dist = np.random.uniform(2.5, 10.0)

            # Determine actual entry price according to side
            if entry_type == 'LIMIT':
                entry_price = round(entry_bid, 2)
                signal_known_time = 1635326100 + i * 3600
                fill_time = signal_known_time + int(np.random.uniform(10, 250))
            elif entry_type == 'MARKET_FALLBACK':
                direction_multiplier = 1 if direction == 1 else -1
                entry_price = round(entry_bid + spread + slip if direction == 1 else entry_bid - slip, 2)
                signal_known_time = 1635326100 + i * 3600
                fill_time = signal_known_time + 300 + int(np.random.uniform(0, 50))
            else:  # MARKET
                entry_price = round(entry_bid + spread + slip if direction == 1 else entry_bid - slip, 2)
                signal_known_time = 1635326100 + i * 3600
                fill_time = signal_known_time
            sl_price = round(entry_price - direction * risk_dist, 2)
            risk_usd = abs(entry_price - sl_price)
            tp_price = round(entry_price + direction * risk_usd, 2)
            exit_type = np.random.choice(['TP', 'SL', 'GAP_SL', 'TIMEOUT'])
            exit_time = fill_time + int(np.random.uniform(60, 7100))

            # Construct mock bars that force the selected exit_type
            if exit_type == 'TP':
                if direction == 1:
                    m1 = np.array([
                        [fill_time, entry_bid, entry_bid + 0.5, entry_bid - 0.5, entry_bid],
                        [exit_time, tp_price - 0.5, tp_price + 1.0, tp_price - 1.0, tp_price],
                    ])
                else:
                    # For SELL TP, Ask must reach tp_price -> Bid low <= tp_price - spread
                    m1 = np.array([
                        [fill_time, entry_bid, entry_bid + 0.5, entry_bid - 0.5, entry_bid],
                        [exit_time, tp_price + 0.5, tp_price + 1.0, tp_price - spread - 0.2, tp_price],
                    ])
            elif exit_type == 'SL':
                if direction == 1:
                    m1 = np.array([
                        [fill_time, entry_bid, entry_bid + 0.5, entry_bid - 0.5, entry_bid],
                        [exit_time, sl_price + 0.5, sl_price + 1.0, sl_price - 0.5, sl_price],
                    ])
                else:
                    m1 = np.array([
                        [fill_time, entry_bid, entry_bid + 0.5, entry_bid - 0.5, entry_bid],
                        [exit_time, sl_price - 0.5, sl_price - spread + 0.5, sl_price - 1.0, sl_price],
                    ])
            elif exit_type == 'GAP_SL':
                # Open gaps past SL on subsequent bar
                if direction == 1:
                    m1 = np.array([
                        [fill_time, entry_bid, entry_bid + 0.5, entry_bid - 0.5, entry_bid],
                        [exit_time, sl_price - 1.0, sl_price - 0.8, sl_price - 1.5, sl_price - 1.2],
                    ])
                else:
                    m1 = np.array([
                        [fill_time, entry_bid, entry_bid + 0.5, entry_bid - 0.5, entry_bid],
                        [exit_time, sl_price + 0.5, sl_price + 1.0, sl_price + 0.4, sl_price + 0.8],
                    ])
            else:  # TIMEOUT
                timeout_time = fill_time + 7200
                exit_time = timeout_time
                timeout_bid = round(entry_bid + np.random.uniform(-1.0, 1.0), 2)
                m1 = np.array([
                    [fill_time, entry_bid, entry_bid + 0.5, entry_bid - 0.5, entry_bid],
                    [timeout_time, timeout_bid, timeout_bid + 0.5, timeout_bid - 0.5, timeout_bid],
                ])

            # Run simulation
            res = simulate_1r_trade(
                entry_price=entry_price,
                sl_price=sl_price,
                direction=direction,
                fill_time=fill_time,
                t0=signal_known_time,
                m5_bars=None,
                m5_start_idx=0,
                schedule=sched_name,
                signal_known_time=signal_known_time,
                m1_bars=m1,
                entry_type=entry_type
            )

            # Mathematical Oracles
            actual_gross = res['gross_pnl_usd']
            actual_net = res['net_pnl_usd']
            actual_net_r = res['net_r']
            actual_comm = res['commission_usd']

            # Oracle 1: Gross PnL definition
            if direction == 1:
                expected_gross = (res['exit_price'] - res['entry_price']) * size
            else:
                expected_gross = (res['entry_price'] - res['exit_price']) * size

            diff_gross = abs(actual_gross - expected_gross)
            if diff_gross > 1e-9:
                discrepancies_gross.append((i, diff_gross))

            # Oracle 2: Net PnL single deduction
            expected_net = actual_gross - actual_comm
            diff_net = abs(actual_net - expected_net)
            if diff_net > 1e-9:
                discrepancies_net.append((i, diff_net))

            # Oracle 3: Net R
            expected_net_r = expected_net / res['risk_usd']
            diff_net_r = abs(actual_net_r - expected_net_r)
            if diff_net_r > 1e-9:
                discrepancies_net_r.append((i, diff_net_r))

            # Oracle 4: Confirm NOT double-deducted
            # Legacy buggy net PnL deducted spread and slippage AGAIN:
            legacy_buggy_net = actual_gross - actual_comm - res['spread_cost_usd'] - res['slippage_usd']
            # If spread or slippage > 0, actual_net must NOT equal legacy_buggy_net
            if (res['spread_cost_usd'] + res['slippage_usd']) > 0:
                if abs(actual_net - legacy_buggy_net) < 1e-9:
                    double_deduction_detected.append(i)

        self.assertEqual(len(discrepancies_gross), 0, f"Gross PnL discrepancies found: {discrepancies_gross}")
        self.assertEqual(len(discrepancies_net), 0, f"Net PnL discrepancies found: {discrepancies_net}")
        self.assertEqual(len(discrepancies_net_r), 0, f"Net R discrepancies found: {discrepancies_net_r}")
        self.assertEqual(len(double_deduction_detected), 0, f"Double fee deduction detected in trades: {double_deduction_detected}")


class TestCausalWindowAdversarialBoundaries(unittest.TestCase):
    """Stress testing Focus 4: Causal window deadlines, delays, and portfolio constraints."""

    def setUp(self):
        self.signal_known_time = 1635326100  # 09:15:00
        self.confirm_bar_open = 1635325800   # 09:10:00
        self.cand_buy = {
            'confirm_bar_open': self.confirm_bar_open,
            'signal_known_time': self.signal_known_time,
            'publish_time': self.signal_known_time,
            'order_place_time': self.signal_known_time,
            'time_m5': self.confirm_bar_open,
            'exec_time': self.signal_known_time,
            'direction': 1,
            'entry_market': 1790.0,
            'sl_price': 1783.0,
            'risk': 7.0,
            'choch_level': 1787.0
        }

    def test_market_fallback_delay_boundary_60s(self):
        """Fallback delay <= 60s fills; delay > 60s rejects with DATA_GAP_DELAY_EXCEEDED."""
        deadline = self.signal_known_time + 300  # 09:20:00 (1635326400)

        # Case 1: First quote at deadline + 60s (09:21:00) -> FILLS
        quote_60s = np.array([deadline + 60, 1789.0, 1789.5, 1788.5, 1789.2])
        res_60s = simulate_h2_entry(self.cand_buy, None, next_m5_quote=quote_60s, spread=0.30, slip=0.01)
        self.assertTrue(res_60s['filled'])
        self.assertEqual(res_60s['entry_type'], "MARKET_FALLBACK")
        self.assertEqual(res_60s['fill_time'], deadline + 60)

        # Case 2: First quote at deadline + 61s (09:21:01) -> CANCELLED (DATA_GAP)
        quote_61s = np.array([deadline + 61, 1789.0, 1789.5, 1788.5, 1789.2])
        res_61s = simulate_h2_entry(self.cand_buy, None, next_m5_quote=quote_61s, spread=0.30, slip=0.01)
        self.assertFalse(res_61s['filled'])
        self.assertTrue(res_61s['cancelled'])
        self.assertEqual(res_61s['cancel_reason'], "DATA_GAP_DELAY_EXCEEDED")
        self.assertTrue(res_61s['data_gap'])

    def test_limit_order_past_deadline_rejected(self):
        """Limit order touch after deadline [signal_known_time + 300s) must NOT fill as LIMIT."""
        deadline = self.signal_known_time + 300
        # M1 bar strictly after deadline (09:20:00)
        late_m1 = np.array([
            [deadline + 0, 1788.0, 1788.5, 1786.0, 1786.5],  # Touches limit 1787.0, but AFTER deadline
        ])
        # Because late_m1 is at deadline, loop breaks; falls back to market fallback
        res = simulate_h2_entry(self.cand_buy, late_m1, spread=0.30, slip=0.01)
        self.assertNotEqual(res['entry_type'], "LIMIT", "Cannot fill as LIMIT after deadline!")
        self.assertEqual(res['entry_type'], "MARKET_FALLBACK")

    def test_portfolio_single_position_strict_seriality(self):
        """Verify filter_single_position strictly prevents concurrent overlapping positions."""
        trades = [
            {'entry_time': 1000, 'exit_time': 2000, 'trade_id': 1},
            {'entry_time': 1500, 'exit_time': 2500, 'trade_id': 2},  # Overlaps trade 1 -> rejected
            {'entry_time': 2000, 'exit_time': 3000, 'trade_id': 3},  # Exactly at exit 1 -> accepted
            {'entry_time': 2999, 'exit_time': 3500, 'trade_id': 4},  # Overlaps trade 3 -> rejected
            {'entry_time': 3100, 'exit_time': 4000, 'trade_id': 5},  # After exit 3 -> accepted
        ]
        filtered = filter_single_position(trades)
        accepted_ids = [t['trade_id'] for t in filtered]
        self.assertEqual(accepted_ids, [1, 3, 5], "Must enforce strictly 1 open position at a time!")


if __name__ == '__main__':
    unittest.main()
