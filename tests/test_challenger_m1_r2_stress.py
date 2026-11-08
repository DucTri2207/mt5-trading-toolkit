"""Adversarial Empirical Stress Test Suite for Market Order Delay Guard and Weekend Gap Logic.

Author: m1_r2_challenger_1 (teamwork_challenger)
Target under test: scripts/gold_v301_causal_core.py

Mission Objectives:
1. Market order delay stress:
   - Next quote delayed by 30s: must fill
   - Next quote delayed by 60s: must fill
   - Next quote delayed by 61s: must cancel/reject (cancel_reason='DATA_GAP_DELAY_EXCEEDED')
2. Gap open SL/TP evaluation:
   - Simulate trade held over weekend gap where Monday opens beyond SL
   - Confirm GAP_SL is evaluated at Monday open (b_open)
   - Exit time is Monday open (b_time), NOT closed weekend time
3. Test with sample of real market data around weekend boundaries from rates.npz:
   - Scan actual weekend closures in gold rates.npz (2021-2025)
   - Verify Friday close market orders are 100% rejected as delayed
   - Verify weekend gap trades exit cleanly at Monday open without assertions crashing
   - Forensic regression on historical crash signals (112, 187, 541, 1210, 3945)
"""

import unittest
from pathlib import Path
import numpy as np

import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))

import gold_v301_causal_core as core
from gold_v301_causal_core import (
    simulate_market_entry,
    simulate_h2_entry,
    simulate_1r_trade,
    derive_signal_known_time,
    FEE_SCHEDULES
)

DATA_PATH = Path(__file__).resolve().parents[1] / 'reports/scalp_structure_lab/20261025_pilot_v1/rates.npz'


class TestMarketOrderDelayStress(unittest.TestCase):
    """Stress-tests market order delay guard at and around 60-second cutoff."""

    def setUp(self):
        self.t0 = 1640000000  # arbitrary reference timestamp
        self.signal_known_time = self.t0 + 300  # 1640000300
        self.candidate_buy = {
            'confirm_bar_open': self.t0,
            'signal_known_time': self.signal_known_time,
            'direction': 1,
            'entry_market': 1800.0,
            'sl_price': 1795.0,
            'risk': 5.0,
            'choch_level': 1800.0
        }
        self.candidate_sell = {
            'confirm_bar_open': self.t0,
            'signal_known_time': self.signal_known_time,
            'direction': -1,
            'entry_market': 1800.0,
            'sl_price': 1805.0,
            'risk': 5.0,
            'choch_level': 1800.0
        }

    def test_market_entry_delay_30s_must_fill(self):
        """Quote delayed by 30s <= 60s MUST fill for both BUY and SELL."""
        quote_time = self.signal_known_time + 30
        quote = np.array([quote_time, 1800.0, 1801.0, 1799.0, 1800.5])

        res_buy = simulate_market_entry(self.candidate_buy, quote, spread=0.30, slip=0.01)
        self.assertTrue(res_buy['filled'], "BUY delayed by 30s must fill")
        self.assertFalse(res_buy['cancelled'])
        self.assertIsNone(res_buy['cancel_reason'])
        self.assertEqual(res_buy['fill_time'], quote_time)
        self.assertEqual(res_buy['entry_type'], 'MARKET')
        self.assertAlmostEqual(res_buy['entry_price'], 1800.0 + 0.30 + 0.01)

        res_sell = simulate_market_entry(self.candidate_sell, quote, spread=0.30, slip=0.01)
        self.assertTrue(res_sell['filled'], "SELL delayed by 30s must fill")
        self.assertFalse(res_sell['cancelled'])
        self.assertEqual(res_sell['fill_time'], quote_time)
        self.assertEqual(res_sell['entry_type'], 'MARKET')
        self.assertAlmostEqual(res_sell['entry_price'], 1800.0 - 0.01)

    def test_market_entry_delay_60s_must_fill(self):
        """Quote delayed by exactly 60s (boundary) MUST fill."""
        quote_time = self.signal_known_time + 60
        quote = np.array([quote_time, 1800.0, 1801.0, 1799.0, 1800.5])

        res_buy = simulate_market_entry(self.candidate_buy, quote, spread=0.30, slip=0.01)
        self.assertTrue(res_buy['filled'], "BUY delayed by exactly 60s must fill")
        self.assertFalse(res_buy['cancelled'])
        self.assertEqual(res_buy['fill_time'], quote_time)

        res_sell = simulate_market_entry(self.candidate_sell, quote, spread=0.30, slip=0.01)
        self.assertTrue(res_sell['filled'], "SELL delayed by exactly 60s must fill")
        self.assertFalse(res_sell['cancelled'])
        self.assertEqual(res_sell['fill_time'], quote_time)

    def test_market_entry_delay_61s_must_cancel(self):
        """Quote delayed by 61s > 60s MUST cancel / reject as DATA_GAP_DELAY_EXCEEDED."""
        quote_time = self.signal_known_time + 61
        quote = np.array([quote_time, 1800.0, 1801.0, 1799.0, 1800.5])

        res_buy = simulate_market_entry(self.candidate_buy, quote, spread=0.30, slip=0.01)
        self.assertFalse(res_buy['filled'], "BUY delayed by 61s must NOT fill")
        self.assertTrue(res_buy['cancelled'], "BUY delayed by 61s must be cancelled")
        self.assertEqual(res_buy['cancel_reason'], 'DATA_GAP_DELAY_EXCEEDED')
        self.assertTrue(res_buy['data_gap'])
        self.assertIsNone(res_buy['fill_time'])
        self.assertIsNone(res_buy['entry_price'])

        res_sell = simulate_market_entry(self.candidate_sell, quote, spread=0.30, slip=0.01)
        self.assertFalse(res_sell['filled'], "SELL delayed by 61s must NOT fill")
        self.assertTrue(res_sell['cancelled'], "SELL delayed by 61s must be cancelled")
        self.assertEqual(res_sell['cancel_reason'], 'DATA_GAP_DELAY_EXCEEDED')
        self.assertTrue(res_sell['data_gap'])

    def test_market_entry_weekend_scale_delays_must_cancel(self):
        """Delays representative of weekend gaps (48h, 72h) must be rejected cleanly."""
        for delay_seconds in [3600, 86400, 177000]:  # 1h, 24h, ~49h weekend
            quote_time = self.signal_known_time + delay_seconds
            quote = np.array([quote_time, 1800.0, 1801.0, 1799.0, 1800.5])

            res = simulate_market_entry(self.candidate_buy, quote)
            self.assertFalse(res['filled'])
            self.assertTrue(res['cancelled'])
            self.assertEqual(res['cancel_reason'], 'DATA_GAP_DELAY_EXCEEDED')
            self.assertTrue(res['data_gap'])

    def test_market_fallback_h2_delay_boundary(self):
        """H2 MARKET_FALLBACK delay boundary: 30s fills, 60s fills, 61s cancels."""
        limit_deadline = self.signal_known_time + 300
        
        m1_bars = np.array([
            [self.signal_known_time + 60, 1802.0, 1803.0, 1801.0, 1802.5],
            [self.signal_known_time + 120, 1802.0, 1803.0, 1801.0, 1802.5],
            [self.signal_known_time + 180, 1802.0, 1803.0, 1801.0, 1802.5],
            [self.signal_known_time + 240, 1802.0, 1803.0, 1801.0, 1802.5],
        ])

        # Sub-test 1: Fallback quote delayed by 30s from deadline
        quote_30s = np.array([limit_deadline + 30, 1802.0, 1803.0, 1801.0, 1802.0])
        res_30s = simulate_h2_entry(self.candidate_buy, m1_bars, next_m5_quote=quote_30s)
        self.assertTrue(res_30s['filled'])
        self.assertEqual(res_30s['entry_type'], 'MARKET_FALLBACK')
        self.assertEqual(res_30s['fill_time'], limit_deadline + 30)

        # Sub-test 2: Fallback quote delayed by 60s from deadline
        quote_60s = np.array([limit_deadline + 60, 1802.0, 1803.0, 1801.0, 1802.0])
        res_60s = simulate_h2_entry(self.candidate_buy, m1_bars, next_m5_quote=quote_60s)
        self.assertTrue(res_60s['filled'])
        self.assertEqual(res_60s['entry_type'], 'MARKET_FALLBACK')
        self.assertEqual(res_60s['fill_time'], limit_deadline + 60)

        # Sub-test 3: Fallback quote delayed by 61s from deadline
        quote_61s = np.array([limit_deadline + 61, 1802.0, 1803.0, 1801.0, 1802.0])
        res_61s = simulate_h2_entry(self.candidate_buy, m1_bars, next_m5_quote=quote_61s)
        self.assertFalse(res_61s['filled'])
        self.assertTrue(res_61s['cancelled'])
        self.assertEqual(res_61s['cancel_reason'], 'DATA_GAP_DELAY_EXCEEDED')
        self.assertTrue(res_61s['data_gap'])


class TestWeekendGapOpenEvaluation(unittest.TestCase):
    """Stress-tests weekend gap open SL/TP evaluation and exit timestamp accuracy."""

    def setUp(self):
        self.t_fri_fill = 1639179900  # 2021-12-10 23:45:00 UTC
        self.signal_known_time = 1639179900
        self.t_mon_open = 1639357500  # 2021-12-13 01:05:00 UTC (49.3 hours later)

    def test_buy_weekend_gap_down_sl_evaluation_m1(self):
        """BUY held over weekend gap where Monday opens below SL:
        - Must trigger GAP_SL (NOT TIMEOUT)
        - Exit price must be b_open - slip (actual Monday open price)
        - Exit time must be Monday open (b_time), NOT closed weekend time
        - exit_time >= fill_time assertion holds
        """
        entry_price = 1800.0
        sl_price = 1795.0
        tp_price = 1805.0

        m1_bars = np.array([
            [self.t_fri_fill, 1800.0, 1801.0, 1799.0, 1800.0],
            [self.t_mon_open, 1790.0, 1792.0, 1788.0, 1791.0]
        ])

        res = simulate_1r_trade(
            entry_price=entry_price,
            sl_price=sl_price,
            direction=1,
            fill_time=self.t_fri_fill,
            signal_known_time=self.signal_known_time,
            m1_bars=m1_bars,
            schedule='BASE'
        )

        self.assertEqual(res['exit_reason'], 'GAP_SL', "Gap below SL must be classified as GAP_SL")
        self.assertEqual(res['exit_time'], self.t_mon_open, "Exit time must be Monday open, NOT closed weekend")
        self.assertGreaterEqual(res['exit_time'], self.t_fri_fill)
        self.assertAlmostEqual(res['exit_price'], 1790.0 - 0.01)
        self.assertAlmostEqual(res['gross_pnl_usd'], (1790.0 - 0.01) - 1800.0)

    def test_buy_weekend_gap_up_tp_evaluation_m1(self):
        """BUY held over weekend gap where Monday opens above TP:
        - Must trigger TP
        - Exit price must be b_open (Monday gap open price)
        - Exit time must be Monday open
        """
        entry_price = 1800.0
        sl_price = 1795.0
        tp_price = 1805.0

        m1_bars = np.array([
            [self.t_fri_fill, 1800.0, 1801.0, 1799.0, 1800.0],
            [self.t_mon_open, 1810.0, 1812.0, 1809.0, 1811.0]
        ])

        res = simulate_1r_trade(
            entry_price=entry_price,
            sl_price=sl_price,
            direction=1,
            fill_time=self.t_fri_fill,
            signal_known_time=self.signal_known_time,
            m1_bars=m1_bars,
            schedule='BASE'
        )

        self.assertEqual(res['exit_reason'], 'TP')
        self.assertEqual(res['exit_time'], self.t_mon_open)
        self.assertAlmostEqual(res['exit_price'], 1810.0)

    def test_buy_weekend_normal_open_timeout_evaluation_m1(self):
        """BUY held over weekend where Monday opens between SL and TP:
        - Since timeout elapsed over weekend, must trigger TIMEOUT at Monday open
        - Exit price must be b_open - slip
        - Exit time must be Monday open (NOT Saturday)
        """
        entry_price = 1800.0
        sl_price = 1795.0
        tp_price = 1805.0

        m1_bars = np.array([
            [self.t_fri_fill, 1800.0, 1801.0, 1799.0, 1800.0],
            [self.t_mon_open, 1801.0, 1802.0, 1800.5, 1801.5]
        ])

        res = simulate_1r_trade(
            entry_price=entry_price,
            sl_price=sl_price,
            direction=1,
            fill_time=self.t_fri_fill,
            signal_known_time=self.signal_known_time,
            m1_bars=m1_bars,
            schedule='BASE'
        )

        self.assertEqual(res['exit_reason'], 'TIMEOUT')
        self.assertEqual(res['exit_time'], self.t_mon_open)
        self.assertAlmostEqual(res['exit_price'], 1801.0 - 0.01)

    def test_sell_weekend_gap_up_sl_evaluation_m1(self):
        """SELL held over weekend gap where Monday opens above SL (evaluated against Ask):
        - Must trigger GAP_SL
        - Exit price must be open_ask + slip = (b_open + spread) + slip
        - Exit time must be Monday open
        """
        entry_price = 1800.0
        sl_price = 1805.0
        tp_price = 1795.0
        spread = 0.30
        slip = 0.01

        m1_bars = np.array([
            [self.t_fri_fill, 1800.0, 1801.0, 1799.0, 1800.0],
            [self.t_mon_open, 1806.0, 1808.0, 1805.5, 1807.0]
        ])

        res = simulate_1r_trade(
            entry_price=entry_price,
            sl_price=sl_price,
            direction=-1,
            fill_time=self.t_fri_fill,
            signal_known_time=self.signal_known_time,
            m1_bars=m1_bars,
            schedule='BASE'
        )

        self.assertEqual(res['exit_reason'], 'GAP_SL')
        self.assertEqual(res['exit_time'], self.t_mon_open)
        expected_exit = (1806.0 + spread) + slip
        self.assertAlmostEqual(res['exit_price'], expected_exit)

    def test_sell_weekend_gap_down_tp_evaluation_m1(self):
        """SELL held over weekend gap where Monday opens below TP:
        - Must trigger TP
        - Exit price must be open_ask = b_open + spread
        - Exit time must be Monday open
        """
        entry_price = 1800.0
        sl_price = 1805.0
        tp_price = 1795.0
        spread = 0.30

        m1_bars = np.array([
            [self.t_fri_fill, 1800.0, 1801.0, 1799.0, 1800.0],
            [self.t_mon_open, 1790.0, 1791.0, 1789.0, 1790.5]
        ])

        res = simulate_1r_trade(
            entry_price=entry_price,
            sl_price=sl_price,
            direction=-1,
            fill_time=self.t_fri_fill,
            signal_known_time=self.signal_known_time,
            m1_bars=m1_bars,
            schedule='BASE'
        )

        self.assertEqual(res['exit_reason'], 'TP')
        self.assertEqual(res['exit_time'], self.t_mon_open)
        self.assertAlmostEqual(res['exit_price'], 1790.0 + spread)

    def test_weekend_gap_evaluation_m5_parity(self):
        """Verify exact same GAP_SL / TIMEOUT / TP behavior holds under M5 bar replay."""
        entry_price = 1800.0
        sl_price = 1795.0

        m5_bars = np.array([
            [self.t_fri_fill - 300, 1800.0, 1801.0, 1799.0, 1800.0],
            [self.t_fri_fill, 1800.0, 1801.0, 1799.0, 1800.0],
            [self.t_mon_open, 1785.0, 1787.0, 1784.0, 1786.0]
        ])

        res_m5 = simulate_1r_trade(
            entry_price=entry_price,
            sl_price=sl_price,
            direction=1,
            fill_time=self.t_fri_fill,
            signal_known_time=self.signal_known_time,
            m5_bars=m5_bars,
            m5_start_idx=1,
            schedule='BASE'
        )

        self.assertEqual(res_m5['exit_reason'], 'GAP_SL')
        self.assertEqual(res_m5['exit_time'], self.t_mon_open)
        self.assertAlmostEqual(res_m5['exit_price'], 1785.0 - 0.01)


class TestRealMarketWeekendData(unittest.TestCase):
    """Stress-tests delay guard and gap evaluation with real market data from rates.npz."""

    @classmethod
    def setUpClass(cls):
        if not DATA_PATH.exists():
            raise unittest.SkipTest(f"Data file not found at {DATA_PATH}")
        data = np.load(DATA_PATH)
        cls.m5 = data['m5']
        cls.m1 = data['m1']

        # Find real weekend boundaries in m5: where delta time > 36 hours (129600s)
        deltas = np.diff(cls.m5['time'])
        cls.weekend_indices = np.where(deltas > 129600)[0]
        print(f"\n[TestRealMarketWeekendData] Identified {len(cls.weekend_indices)} weekend gaps in rates.npz")

    def test_real_friday_close_market_orders_100pct_cancelled(self):
        """Every market order placed at Friday market close with next quote on Monday
        MUST be cancelled with DATA_GAP_DELAY_EXCEEDED (100% rejection rate).
        """
        rejections = 0
        tested = min(50, len(self.weekend_indices))

        for idx in self.weekend_indices[:tested]:
            fri_bar = self.m5[idx]
            mon_bar = self.m5[idx + 1]

            fri_time = int(fri_bar['time'])
            mon_time = int(mon_bar['time'])
            delay = mon_time - (fri_time + 300)

            self.assertGreater(delay, 60, f"Weekend delay {delay}s should be > 60s")

            candidate = {
                'confirm_bar_open': fri_time,
                'signal_known_time': fri_time + 300,
                'direction': 1,
                'entry_market': float(fri_bar['close']),
                'sl_price': float(fri_bar['close']) - 5.0,
                'risk': 5.0
            }

            next_quote = np.array([mon_time, float(mon_bar['open']), float(mon_bar['high']), float(mon_bar['low']), float(mon_bar['close'])])
            res = simulate_market_entry(candidate, next_quote)

            self.assertFalse(res['filled'], f"Friday close order at {fri_time} must not fill on Monday {mon_time}")
            self.assertTrue(res['cancelled'])
            self.assertEqual(res['cancel_reason'], 'DATA_GAP_DELAY_EXCEEDED')
            self.assertTrue(res['data_gap'])
            rejections += 1

        self.assertEqual(rejections, tested)
        print(f"[TestRealMarketWeekendData] Verified 100% rejection ({rejections}/{tested}) on real Friday close orders")

    def test_real_weekend_gap_positions_exit_cleanly(self):
        """Positions held over real weekends exit cleanly at Monday open
        with correct GAP_SL, TP, and TIMEOUT, and zero assertion crashes.
        """
        m1_times = self.m1['time']
        gap_down_count = 0
        gap_up_count = 0
        timeout_count = 0

        for idx in self.weekend_indices:
            mon_bar = self.m5[idx + 1]
            idx_mon_m1 = np.searchsorted(m1_times, mon_bar['time'])
            fri_last_m1 = self.m1[idx_mon_m1 - 1]

            m1_slice = np.column_stack([
                self.m1['time'][idx_mon_m1 - 1:idx_mon_m1 + 3],
                self.m1['open'][idx_mon_m1 - 1:idx_mon_m1 + 3],
                self.m1['high'][idx_mon_m1 - 1:idx_mon_m1 + 3],
                self.m1['low'][idx_mon_m1 - 1:idx_mon_m1 + 3],
                self.m1['close'][idx_mon_m1 - 1:idx_mon_m1 + 3]
            ]).astype(float)

            fill_t = int(fri_last_m1['time'])
            mon_m1_t = int(m1_slice[1, 0])
            fri_open = float(fri_last_m1['open'])
            fri_low = float(fri_last_m1['low'])
            fri_high = float(fri_last_m1['high'])
            mon_open = float(m1_slice[1, 1])

            # 1. Real Gap Down Test: Monday open < Friday low - 1.0 (BUY GAP_SL)
            if mon_open < fri_low - 1.0 and gap_down_count < 10:
                sl = (mon_open + fri_low) / 2.0
                d_act = fri_open - sl
                tp = fri_open + d_act

                if tp > fri_high:
                    res_gap_sl = simulate_1r_trade(
                        entry_price=fri_open,
                        sl_price=sl,
                        direction=1,
                        fill_time=fill_t,
                        signal_known_time=fill_t,
                        m1_bars=m1_slice,
                        schedule='BASE'
                    )

                    self.assertEqual(res_gap_sl['exit_reason'], 'GAP_SL')
                    self.assertEqual(res_gap_sl['exit_time'], mon_m1_t)
                    self.assertAlmostEqual(res_gap_sl['exit_price'], mon_open - 0.01)
                    self.assertGreaterEqual(res_gap_sl['exit_time'], fill_t)
                    gap_down_count += 1

            # 2. Real Gap Up Test: Monday open > Friday high + 1.0 (BUY TP)
            if mon_open > fri_high + 1.0 and gap_up_count < 10:
                tp = (mon_open + fri_high) / 2.0
                d_act = tp - fri_open
                sl = fri_open - d_act

                if sl < fri_low:
                    res_tp = simulate_1r_trade(
                        entry_price=fri_open,
                        sl_price=sl,
                        direction=1,
                        fill_time=fill_t,
                        signal_known_time=fill_t,
                        m1_bars=m1_slice,
                        schedule='BASE'
                    )

                    self.assertEqual(res_tp['exit_reason'], 'TP')
                    self.assertEqual(res_tp['exit_time'], mon_m1_t)
                    self.assertAlmostEqual(res_tp['exit_price'], mon_open)
                    self.assertGreaterEqual(res_tp['exit_time'], fill_t)
                    gap_up_count += 1

            # 3. Real Timeout Test: Monday open between wide SL and TP
            if timeout_count < 10:
                sl = fri_low - 200.0

                res_timeout = simulate_1r_trade(
                    entry_price=fri_open,
                    sl_price=sl,
                    direction=1,
                    fill_time=fill_t,
                    signal_known_time=fill_t,
                    m1_bars=m1_slice,
                    schedule='BASE'
                )

                self.assertEqual(res_timeout['exit_reason'], 'TIMEOUT')
                self.assertEqual(res_timeout['exit_time'], mon_m1_t)
                self.assertAlmostEqual(res_timeout['exit_price'], mon_open - 0.01)
                self.assertGreaterEqual(res_timeout['exit_time'], fill_t)
                timeout_count += 1

            if gap_down_count >= 10 and gap_up_count >= 10 and timeout_count >= 10:
                break

        self.assertEqual(gap_down_count, 10)
        self.assertEqual(gap_up_count, 10)
        self.assertEqual(timeout_count, 10)
        print(f"[TestRealMarketWeekendData] Verified 30 real weekend gap trades (10 GAP_SL, 10 TP, 10 TIMEOUT) - all 100% passed")

    def test_forensic_historical_crash_signals(self):
        """Forensic regression on the exact signals that crashed before remediation:
        Signal 112 (2021-12-10 23:50 UTC, Friday)
        Signal 187 (2021-12-23 23:50 UTC, Christmas)
        Signal 541 (2022-03-18 23:50 UTC, Friday)
        Signal 1210 (2022-10-21 23:50 UTC, Friday)
        Signal 3945 (2024-12-27 23:50 UTC, Friday)
        """
        crash_signal_times = [
            1639180200,  # Sig 112: Fri 2021-12-10 23:50 UTC
            1640303400,  # Sig 187: Thu 2021-12-23 23:50 UTC (Christmas)
            1647643800,  # Sig 541: Fri 2022-03-18 23:50 UTC
            1666396500,  # Sig 1210: Fri 2022-10-21 23:50 UTC
            1735343700   # Sig 3945: Fri 2024-12-27 23:50 UTC
        ]

        m5_times = self.m5['time']

        for t0 in crash_signal_times:
            order_place_time = t0 + 300
            m5_idx = int(np.searchsorted(m5_times, order_place_time))
            next_quote_bar = self.m5[m5_idx]
            next_quote = np.array([
                next_quote_bar['time'],
                next_quote_bar['open'],
                next_quote_bar['high'],
                next_quote_bar['low'],
                next_quote_bar['close']
            ])

            delay = int(next_quote_bar['time']) - order_place_time
            self.assertGreater(delay, 60, f"Signal at {t0} must have delay > 60s (was {delay}s)")

            cand = {
                'confirm_bar_open': t0,
                'signal_known_time': order_place_time,
                'direction': 1,
                'entry_market': 1800.0,
                'sl_price': 1795.0,
                'risk': 5.0
            }

            res = simulate_market_entry(cand, next_quote)
            self.assertFalse(res['filled'], f"Signal at {t0} must be rejected")
            self.assertTrue(res['cancelled'])
            self.assertEqual(res['cancel_reason'], 'DATA_GAP_DELAY_EXCEEDED')
            self.assertTrue(res['data_gap'])

        print(f"[TestRealMarketWeekendData] All 5 historical crash signals verified 100% cleanly rejected")


if __name__ == '__main__':
    unittest.main()
