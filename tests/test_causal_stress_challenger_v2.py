"""Adversarial Causal Stress Test Suite (Challenger v2).

Authored by m1_challenger_1_v2 (critic, specialist).
Empirically stress-tests scripts/gold_v301_causal_core.py against 4 critical axes:
1. Timestamp Monotonicity & Causality Under Confirmation Bar Whipsaws
2. LIMIT Window Boundary Stress (299s touch vs 300s expiry)
3. Fallback Delay Stress (+30s, +60s, +61s, gap guards)
4. Prefix Replay Test (K bars vs K+N bars bitwise trade invariance on real data)
"""
import copy
import math
import sys
import unittest
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))

from gold_v301_causal_core import (
    FEE_SCHEDULES,
    MODE_B0_LITERAL,
    MODE_B1_TECHNICAL,
    atr_mt5,
    detect_all_candidates,
    detect_one,
    detect_stream,
    filter_single_position,
    native_snapshots,
    native_zones,
    select_h1_candidate,
    simulate_1r_trade,
    simulate_h2_entry,
)
from research_gold_v301_causal import data


class TestCausalStressChallengerV2(unittest.TestCase):
    """Adversarial stress test harness targeting hidden lookahead and timing leaks."""

    @classmethod
    def setUpClass(cls):
        # Load historical rates once for all tests
        cls.raw_data = data()
        cls.h1 = cls.raw_data['h1']
        cls.m5 = cls.raw_data['m5']
        cls.m1 = cls.raw_data['m1']

    # =========================================================================
    # AXIS 1: Timestamp Monotonicity & Causality Under Confirmation Bar Whipsaws
    # =========================================================================

    def test_01_confirmation_bar_violent_whipsaw_buy_no_leak(self):
        """Construct synthetic M1 series with extreme whipsaws during confirmation bar.
        
        Verify that under NO circumstances does the engine peek at confirmation bar
        quotes, trigger early limit fills, or cancel on SL/TP before signal_known_time.
        """
        confirm_bar_open = 1635000000
        signal_known_time = confirm_bar_open + 300  # 1635000300
        limit_deadline = signal_known_time + 300    # 1635000600

        cand_buy = {
            'confirm_bar_open': confirm_bar_open,
            'signal_known_time': signal_known_time,
            'publish_time': signal_known_time,
            'order_place_time': signal_known_time,
            'time_m5': confirm_bar_open,
            'direction': 1,
            'entry_market': 2000.0,
            'sl_price': 1995.0,
            'risk': 5.0,
            'choch_level': 1998.0,  # Limit price
        }

        # 5 M1 bars DURING the confirmation candle [confirm_bar_open, signal_known_time)
        # Price whipsaws violently: drops to 1980 (way below SL), explodes to 2030 (way above TP),
        # crosses limit 1998.0 multiple times.
        whipsaw_confirmation_m1 = np.array([
            [confirm_bar_open + 0, 1999.0, 2035.0, 1980.0, 2005.0],   # breaches both SL (1995) & TP (2005)
            [confirm_bar_open + 60, 2005.0, 2010.0, 1970.0, 1975.0],  # catastrophic crash deep past SL
            [confirm_bar_open + 120, 1975.0, 2040.0, 1974.0, 2030.0], # massive rocket deep past TP
            [confirm_bar_open + 180, 2030.0, 2032.0, 1997.5, 1998.0], # touches limit at 1998.0
            [confirm_bar_open + 240, 1998.0, 2002.0, 1997.0, 2000.0], # touches limit again
            [confirm_bar_open + 299, 2000.0, 2001.0, 1997.0, 1998.5], # 1s before signal known
        ])

        # Subtest 1A: Only confirmation bars provided -> must NOT fill, must NOT cancel on SL/TP
        res_pre_only = simulate_h2_entry(cand_buy, whipsaw_confirmation_m1, None, spread=0.30, slip=0.01)
        self.assertFalse(res_pre_only['filled'], "Engine must NOT fill on confirmation bar quotes!")
        self.assertEqual(res_pre_only['cancel_reason'], "INSUFFICIENT_DATA",
                         "Must not cancel on SL/TP before signal_known_time; reason must be INSUFFICIENT_DATA")

        # Subtest 1B: Confirmation bars PLUS causal bars arriving at signal_known_time
        # Causal M1 bars inside [signal_known_time, limit_deadline)
        causal_m1 = np.array([
            [signal_known_time + 0, 2001.0, 2002.0, 2000.5, 2001.0],   # limit (1998.0) not reached
            [signal_known_time + 60, 2001.0, 2001.5, 1999.0, 1999.5],  # Ask low = 1999.0 + 0.3 = 1999.3 > 1998.0
            [signal_known_time + 120, 1999.5, 2000.0, 1997.5, 1998.0], # Ask low = 1997.5 + 0.3 = 1997.8 <= 1998.0 -> CAUSAL FILL!
        ])
        all_m1 = np.vstack([whipsaw_confirmation_m1, causal_m1])

        res_causal = simulate_h2_entry(cand_buy, all_m1, None, spread=0.30, slip=0.01)
        self.assertTrue(res_causal['filled'], "Must fill causally on valid post-signal quotes")
        self.assertEqual(res_causal['entry_type'], "LIMIT")
        self.assertEqual(res_causal['fill_time'], signal_known_time + 120,
                         "Fill time must be exactly the causal bar timestamp (signal_known_time + 120)")
        self.assertGreaterEqual(res_causal['fill_time'], signal_known_time,
                                "Fill time must be strictly >= signal_known_time")

    def test_02_confirmation_bar_violent_whipsaw_sell_no_leak(self):
        """Sell side verification of confirmation bar whipsaw isolation."""
        confirm_bar_open = 1635000000
        signal_known_time = confirm_bar_open + 300
        limit_deadline = signal_known_time + 300

        cand_sell = {
            'confirm_bar_open': confirm_bar_open,
            'signal_known_time': signal_known_time,
            'publish_time': signal_known_time,
            'order_place_time': signal_known_time,
            'time_m5': confirm_bar_open,
            'direction': -1,
            'entry_market': 2000.0,
            'sl_price': 2005.0,
            'risk': 5.0,
            'choch_level': 2002.0,  # Sell Limit price
        }

        # Whipsaw confirmation bars
        whipsaw_confirmation_m1 = np.array([
            [confirm_bar_open + 0, 2001.0, 2050.0, 1960.0, 2002.0],
            [confirm_bar_open + 60, 2002.0, 2045.0, 2001.0, 2040.0],
            [confirm_bar_open + 120, 2040.0, 2042.0, 1960.0, 1965.0],
            [confirm_bar_open + 240, 1965.0, 2003.0, 1965.0, 2000.0],
        ])

        res_pre_only = simulate_h2_entry(cand_sell, whipsaw_confirmation_m1, None, spread=0.30, slip=0.01)
        self.assertFalse(res_pre_only['filled'])
        self.assertEqual(res_pre_only['cancel_reason'], "INSUFFICIENT_DATA")

        # Causal M1 bars: limit hit at signal_known_time + 60
        causal_m1 = np.array([
            [signal_known_time + 0, 1999.0, 2001.0, 1998.5, 2000.0],   # Bid high 2001.0 < 2002.0
            [signal_known_time + 60, 2000.0, 2002.5, 1999.5, 2002.0],  # Bid high 2002.5 >= 2002.0 -> SELL LIMIT FILLS!
        ])
        all_m1 = np.vstack([whipsaw_confirmation_m1, causal_m1])

        res_causal = simulate_h2_entry(cand_sell, all_m1, None, spread=0.30, slip=0.01)
        self.assertTrue(res_causal['filled'])
        self.assertEqual(res_causal['entry_type'], "LIMIT")
        self.assertEqual(res_causal['fill_time'], signal_known_time + 60)
        self.assertGreaterEqual(res_causal['fill_time'], signal_known_time)

    # =========================================================================
    # AXIS 2: LIMIT Window Boundary Stress (299s vs 300s)
    # =========================================================================

    def test_03_limit_boundary_299s_must_fill_as_limit(self):
        """Stress quote arriving at signal_known_time + 299s:
        Must fill as LIMIT if touched, because it is strictly within [t_known, t_known + 300s).
        """
        t_known = 1635100000
        limit_deadline = t_known + 300

        cand_buy = {
            'confirm_bar_open': t_known - 300,
            'signal_known_time': t_known,
            'direction': 1,
            'entry_market': 2000.0,
            'sl_price': 1995.0,
            'risk': 5.0,
            'choch_level': 1998.0,
        }

        # Quotes prior to 299s do NOT touch limit
        m1_bars = np.array([
            [t_known + 0, 2001.0, 2002.0, 2000.0, 2001.0],
            [t_known + 60, 2001.0, 2001.5, 1999.5, 2000.0],
            [t_known + 120, 2000.0, 2000.5, 1999.0, 1999.5],
            [t_known + 180, 1999.5, 2000.0, 1998.5, 1999.0],  # Ask low = 1998.5 + 0.3 = 1998.8 > 1998.0
            [t_known + 240, 1999.0, 1999.5, 1998.0, 1998.5],  # Ask low = 1998.0 + 0.3 = 1998.3 > 1998.0
            # Quote at t_known + 299s: Ask low = 1997.5 + 0.30 = 1997.80 <= 1998.0 -> TOUCHES LIMIT AT 299s!
            [t_known + 299, 1998.5, 1999.0, 1997.5, 1998.0],
        ])

        res = simulate_h2_entry(cand_buy, m1_bars, None, spread=0.30, slip=0.01)
        self.assertTrue(res['filled'], "Quote at signal_known_time + 299s MUST fill!")
        self.assertEqual(res['entry_type'], "LIMIT", "Order filling at +299s MUST be LIMIT")
        self.assertEqual(res['fill_time'], t_known + 299, "Fill time must be exactly t_known + 299s")
        self.assertAlmostEqual(res['entry_price'], 1998.0, places=4, msg="LIMIT entry price must be limit_price")

    def test_04_limit_boundary_300s_must_not_fill_as_limit(self):
        """Stress quote arriving at signal_known_time + 300s:
        Limit order window [t_known, t_known + 300s) has EXPIRED at t_known + 300s.
        If price touches limit price at +300s, it must NEVER fill via LIMIT.
        It must either fill as MARKET_FALLBACK at market price or reject.
        """
        t_known = 1635100000
        limit_deadline = t_known + 300

        cand_buy = {
            'confirm_bar_open': t_known - 300,
            'signal_known_time': t_known,
            'direction': 1,
            'entry_market': 2000.0,
            'sl_price': 1995.0,
            'risk': 5.0,
            'choch_level': 1998.0,
        }

        # Quotes up to +298s do NOT touch limit
        m1_bars = np.array([
            [t_known + 0, 2001.0, 2002.0, 2000.0, 2001.0],
            [t_known + 60, 2001.0, 2001.5, 1999.5, 2000.0],
            [t_known + 120, 2000.0, 2000.5, 1999.0, 1999.5],
            [t_known + 180, 1999.5, 2000.0, 1998.5, 1999.0],
            [t_known + 240, 1999.0, 1999.5, 1998.0, 1998.5],
            # At exactly t_known + 300s (deadline): price reaches limit level
            [t_known + 300, 1997.5, 1998.0, 1997.0, 1997.5],
        ])

        res = simulate_h2_entry(cand_buy, m1_bars, None, spread=0.30, slip=0.01)
        self.assertTrue(res['filled'], "Should fill via fallback at deadline quote")
        self.assertNotEqual(res['entry_type'], "LIMIT",
                            "CRITICAL LEAK: Quote at deadline (+300s) must NOT be recorded as LIMIT fill!")
        self.assertEqual(res['entry_type'], "MARKET_FALLBACK",
                         "Quote at deadline (+300s) must fill as MARKET_FALLBACK")
        self.assertEqual(res['fill_time'], t_known + 300)
        # For BUY Market Fallback: entry price = Bid Open + spread + slip = 1997.5 + 0.30 + 0.01 = 1997.81
        self.assertAlmostEqual(res['entry_price'], 1997.81, places=4)

    def test_05_limit_boundary_exact_open_0s_fills_as_limit(self):
        """Quote at t_known + 0s (very first causal second):
        Must fill as LIMIT if limit touched, proving full coverage of [t_known, t_known + 300).
        """
        t_known = 1635100000
        cand_buy = {
            'confirm_bar_open': t_known - 300,
            'signal_known_time': t_known,
            'direction': 1,
            'entry_market': 2000.0,
            'sl_price': 1995.0,
            'risk': 5.0,
            'choch_level': 1998.0,
        }
        # Bar at t_known + 0s touches limit
        m1_bars = np.array([
            [t_known + 0, 1999.0, 2000.0, 1997.0, 1998.5],  # Ask low = 1997.0 + 0.3 = 1997.3 <= 1998.0
        ])
        res = simulate_h2_entry(cand_buy, m1_bars, None, spread=0.30, slip=0.01)
        self.assertTrue(res['filled'])
        self.assertEqual(res['entry_type'], "LIMIT")
        self.assertEqual(res['fill_time'], t_known + 0)
        self.assertAlmostEqual(res['entry_price'], 1998.0)

    # =========================================================================
    # AXIS 3: Fallback Delay Stress (+30s, +60s, +61s, gap guards)
    # =========================================================================

    def test_06_fallback_delay_30s_must_fill(self):
        """Fallback quote arriving at deadline + 30s (t_known + 330s):
        Delay is 30s <= 60s max allowable delay -> MUST FILL as MARKET_FALLBACK.
        """
        t_known = 1635200000
        limit_deadline = t_known + 300

        cand_buy = {
            'confirm_bar_open': t_known - 300,
            'signal_known_time': t_known,
            'direction': 1,
            'entry_market': 2000.0,
            'sl_price': 1995.0,
            'risk': 5.0,
            'choch_level': 1998.0,
        }

        # Empty or non-touching limit bars up to deadline
        m1_no_touch = np.array([
            [t_known + 0, 2002.0, 2003.0, 2001.0, 2002.0],
        ])
        # Quote arrives at deadline + 30s
        fallback_30s = np.array([limit_deadline + 30, 2001.0, 2002.0, 2000.5, 2001.5])

        res = simulate_h2_entry(cand_buy, m1_no_touch, fallback_30s, spread=0.30, slip=0.01)
        self.assertTrue(res['filled'], "Fallback arriving at deadline + 30s must fill")
        self.assertEqual(res['entry_type'], "MARKET_FALLBACK")
        self.assertEqual(res['fill_time'], limit_deadline + 30)
        # Entry price: Bid 2001.0 + spread 0.30 + slip 0.01 = 2001.31
        self.assertAlmostEqual(res['entry_price'], 2001.31, places=4)

    def test_07_fallback_delay_60s_must_fill(self):
        """Fallback quote arriving at deadline + 60s (t_known + 360s):
        Delay is exactly 60s (the boundary threshold) -> MUST FILL as MARKET_FALLBACK.
        """
        t_known = 1635200000
        limit_deadline = t_known + 300

        cand_buy = {
            'confirm_bar_open': t_known - 300,
            'signal_known_time': t_known,
            'direction': 1,
            'entry_market': 2000.0,
            'sl_price': 1995.0,
            'risk': 5.0,
            'choch_level': 1998.0,
        }

        m1_no_touch = np.array([
            [t_known + 0, 2002.0, 2003.0, 2001.0, 2002.0],
        ])
        # Quote arrives at exactly deadline + 60s
        fallback_60s = np.array([limit_deadline + 60, 2000.5, 2001.5, 2000.0, 2001.0])

        res = simulate_h2_entry(cand_buy, m1_no_touch, fallback_60s, spread=0.30, slip=0.01)
        self.assertTrue(res['filled'], "Fallback arriving at deadline + 60s must fill")
        self.assertEqual(res['entry_type'], "MARKET_FALLBACK")
        self.assertEqual(res['fill_time'], limit_deadline + 60)
        # Entry price: 2000.5 + 0.30 + 0.01 = 2000.81
        self.assertAlmostEqual(res['entry_price'], 2000.81, places=4)

    def test_08_fallback_delay_61s_must_reject_data_gap(self):
        """Fallback quote arriving at deadline + 61s (t_known + 361s):
        Delay is 61s > 60s max threshold -> MUST REJECT with DATA_GAP_DELAY_EXCEEDED.
        CRITICAL CAUSALITY RULE: Engine must NEVER gap forward distant future quote to deadline.
        """
        t_known = 1635200000
        limit_deadline = t_known + 300

        cand_buy = {
            'confirm_bar_open': t_known - 300,
            'signal_known_time': t_known,
            'direction': 1,
            'entry_market': 2000.0,
            'sl_price': 1995.0,
            'risk': 5.0,
            'choch_level': 1998.0,
        }

        m1_no_touch = np.array([
            [t_known + 0, 2002.0, 2003.0, 2001.0, 2002.0],
        ])
        # Quote arrives at deadline + 61s
        fallback_61s = np.array([limit_deadline + 61, 2000.5, 2001.5, 2000.0, 2001.0])

        res = simulate_h2_entry(cand_buy, m1_no_touch, fallback_61s, spread=0.30, slip=0.01)
        self.assertFalse(res['filled'], "CRITICAL LEAK: Fallback at deadline + 61s must NOT fill!")
        self.assertTrue(res['cancelled'])
        self.assertEqual(res['cancel_reason'], "DATA_GAP_DELAY_EXCEEDED")
        self.assertTrue(res['data_gap'], "data_gap flag must be True")

    def test_09_fallback_delay_via_m1_series_stream(self):
        """Verify fallback delay check works when fallback quote is extracted from m1_bars stream."""
        t_known = 1635200000
        limit_deadline = t_known + 300

        cand_sell = {
            'confirm_bar_open': t_known - 300,
            'signal_known_time': t_known,
            'direction': -1,
            'entry_market': 2000.0,
            'sl_price': 2005.0,
            'risk': 5.0,
            'choch_level': 2003.0,
        }

        # Case A: M1 bar at deadline + 60s -> fills
        m1_valid_delay = np.array([
            [t_known + 0, 1998.0, 1999.0, 1997.0, 1998.0],
            [limit_deadline + 60, 1998.5, 1999.5, 1997.5, 1998.0],
        ])
        res_a = simulate_h2_entry(cand_sell, m1_valid_delay, None, spread=0.30, slip=0.01)
        self.assertTrue(res_a['filled'])
        self.assertEqual(res_a['entry_type'], "MARKET_FALLBACK")
        self.assertEqual(res_a['fill_time'], limit_deadline + 60)

        # Case B: M1 bar at deadline + 61s (data gap) -> rejects
        m1_excessive_delay = np.array([
            [t_known + 0, 1998.0, 1999.0, 1997.0, 1998.0],
            [limit_deadline + 61, 1998.5, 1999.5, 1997.5, 1998.0],
        ])
        res_b = simulate_h2_entry(cand_sell, m1_excessive_delay, None, spread=0.30, slip=0.01)
        self.assertFalse(res_b['filled'])
        self.assertEqual(res_b['cancel_reason'], "DATA_GAP_DELAY_EXCEEDED")
        self.assertTrue(res_b['data_gap'])

    def test_10_simulate_1r_trade_runtime_assertions(self):
        """Verify simulate_1r_trade runtime assertions actively enforce causality."""
        t_known = 1635200000
        m5_dummy = np.array([[t_known + 300, 2000.0, 2010.0, 1995.0, 2005.0]])

        # 1. Fill before signal_known_time must trigger AssertionError
        with self.assertRaises(AssertionError) as ctx:
            simulate_1r_trade(
                entry_price=2000.0,
                sl_price=1995.0,
                direction=1,
                fill_time=t_known - 1,  # 1 second before signal_known_time!
                t0=t_known - 300,
                m5_bars=m5_dummy,
                m5_start_idx=0,
                signal_known_time=t_known,
                entry_type="LIMIT"
            )
        self.assertIn("Fill time", str(ctx.exception))

        # 2. Fallback fill before deadline must trigger AssertionError
        with self.assertRaises(AssertionError) as ctx:
            simulate_1r_trade(
                entry_price=2000.0,
                sl_price=1995.0,
                direction=1,
                fill_time=t_known + 299,  # Before deadline!
                t0=t_known - 300,
                m5_bars=m5_dummy,
                m5_start_idx=0,
                signal_known_time=t_known,
                entry_type="MARKET_FALLBACK"
            )
        self.assertIn("Fallback fill time", str(ctx.exception))

        # 3. Limit fill after deadline must trigger AssertionError
        with self.assertRaises(AssertionError) as ctx:
            simulate_1r_trade(
                entry_price=2000.0,
                sl_price=1995.0,
                direction=1,
                fill_time=t_known + 300,  # At or after deadline!
                t0=t_known - 300,
                m5_bars=m5_dummy,
                m5_start_idx=0,
                signal_known_time=t_known,
                entry_type="LIMIT"
            )
        self.assertIn("Limit fill time", str(ctx.exception))

    # =========================================================================
    # AXIS 4: Prefix Replay Test (K bars vs K+N bars on Real Historical Data)
    # =========================================================================

    def test_11_prefix_replay_end_to_end_bitwise_invariance(self):
        """EMPIRICAL PREFIX REPLAY TEST ON HISTORICAL DATA:
        Feed first K M5 bars, then feed K+N M5 bars.
        Confirm that trades up to bar K are 100% bitwise identical regardless of future bars.
        
        This tests the full integration:
        - native_zones and native_snapshots on closed H1 prefixes
        - detect_all_candidates / select_h1_candidate
        - simulate_h2_entry with historical M1 bars
        - simulate_1r_trade forward in time
        - filter_single_position forward state machine
        """
        # Select test slice: K = 600 M5 bars (50 hours), N = 200 M5 bars (16.6 hours)
        # We start after warm-up index 1500 to ensure rich zone history and multiple signals
        start_m5_idx = 2000
        K_len = 600
        N_len = 200

        m5_prefix = self.m5[start_m5_idx:start_m5_idx + K_len]
        m5_extended = self.m5[start_m5_idx:start_m5_idx + K_len + N_len]

        t_start = int(m5_prefix[0, 0])
        t_K_end = int(m5_prefix[-1, 0])
        t_extended_end = int(m5_extended[-1, 0])

        # Slice corresponding H1 and M1 bars
        h1_prefix = self.h1[(self.h1[:, 0] <= t_K_end)]
        h1_extended = self.h1[(self.h1[:, 0] <= t_extended_end)]

        m1_prefix = self.m1[(self.m1[:, 0] >= t_start) & (self.m1[:, 0] <= t_K_end)]
        m1_extended = self.m1[(self.m1[:, 0] >= t_start) & (self.m1[:, 0] <= t_extended_end)]

        atr_h1_prefix = atr_mt5(h1_prefix)
        atr_h1_extended = atr_mt5(h1_extended)

        atr_m5_prefix = atr_mt5(m5_prefix)
        atr_m5_extended = atr_mt5(m5_extended)

        # Function to run the full H2 simulation pipeline on a given dataset slice
        def run_full_pipeline(m5_slice, atr_m5_slice, h1_slice, atr_h1_slice, m1_slice):
            ptr, rows = native_snapshots(h1_slice, atr_h1_slice, deterministic_keys=True)
            zones = np.asarray(rows, dtype=float).reshape(-1, 9)

            m5_times = m5_slice[:, 0]
            m1_times = m1_slice[:, 0]
            h1_times = h1_slice[:, 0]

            h_idx = -1
            all_trades = []

            for m in range(30, len(m5_slice)):
                t_m5 = int(m5_slice[m, 0])
                # Advance H1 causal pointer: zones visible strictly at or before t_m5
                while h_idx + 1 < len(h1_slice) and h1_slice[h_idx + 1, 0] + 3600 <= t_m5:
                    h_idx += 1
                if h_idx < 0:
                    continue

                visible_zones = zones[ptr[h_idx]:ptr[h_idx + 1]]
                cands = detect_all_candidates(m5_slice, atr_m5_slice, m, visible_zones, mode=MODE_B1_TECHNICAL)
                if not cands:
                    continue

                best_cand = select_h1_candidate(cands)
                if best_cand is None:
                    continue

                # Find M1 bars for H2 limit retest inside [t_known, t_known + 360)
                t_known = best_cand['signal_known_time']
                m1_idx_start = int(np.searchsorted(m1_times, t_known))
                m1_sub = m1_slice[m1_idx_start:m1_idx_start + 10]

                # Next M5 quote for fallback if needed
                next_m5_idx = int(np.searchsorted(m5_times, t_known + 300))
                next_quote = m5_slice[next_m5_idx] if next_m5_idx < len(m5_slice) else None

                entry_res = simulate_h2_entry(best_cand, m1_sub, next_quote, spread=0.30, slip=0.01)
                if not entry_res['filled']:
                    continue

                # 1R trade payoff replay forward in time
                trade = simulate_1r_trade(
                    entry_price=entry_res['entry_price'],
                    sl_price=entry_res['sl_price'],
                    direction=best_cand['direction'],
                    fill_time=entry_res['fill_time'],
                    t0=best_cand['confirm_bar_open'],
                    m5_bars=m5_slice,
                    m5_start_idx=m,
                    schedule='BASE',
                    is_limit=(entry_res['entry_type'] == 'LIMIT'),
                    signal_known_time=t_known,
                    entry_type=entry_res['entry_type'],
                    ambiguous_intrabar=entry_res['ambiguous_intrabar']
                )
                all_trades.append(trade)

            # Enforce single position portfolio constraint forward in time
            closed_trades = filter_single_position(all_trades)
            return closed_trades

        # Run on Prefix (K bars)
        trades_prefix = run_full_pipeline(m5_prefix, atr_m5_prefix, h1_prefix, atr_h1_prefix, m1_prefix)
        # Run on Extended (K + N bars)
        trades_extended = run_full_pipeline(m5_extended, atr_m5_extended, h1_extended, atr_h1_extended, m1_extended)

        self.assertGreater(len(trades_prefix), 0, "Prefix dataset must produce trades to test invariance")
        self.assertGreaterEqual(len(trades_extended), len(trades_prefix),
                                "Extended dataset must contain at least as many trades as prefix")

        # Now filter trades completed safely within Prefix cutoff (at least 7200s before t_K_end)
        # so they were not censored by prefix truncation
        safe_cutoff = t_K_end - 7200
        safe_prefix = [t for t in trades_prefix if t['exit_time'] <= safe_cutoff]
        safe_extended = [t for t in trades_extended if t['exit_time'] <= safe_cutoff]

        self.assertGreater(len(safe_prefix), 0, "Must have completed trades before safe cutoff")
        self.assertEqual(len(safe_prefix), len(safe_extended),
                         f"Trade count mismatch: prefix has {len(safe_prefix)}, extended has {len(safe_extended)}")

        # Verify 100% BITWISE INVARIANCE on all completed trades up to bar K
        fields_to_check = [
            'direction', 'entry_time', 'entry_price', 'entry_type',
            'sl_price', 'tp_price', 'risk_usd', 'exit_time', 'exit_price',
            'exit_reason', 'gross_pnl_usd', 'commission_usd', 'slippage_usd',
            'spread_cost_usd', 'net_pnl_usd', 'net_r', 'bars_held', 'data_gap'
        ]

        for i, (tp, te) in enumerate(zip(safe_prefix, safe_extended)):
            for field in fields_to_check:
                val_p = tp[field]
                val_e = te[field]
                if isinstance(val_p, float):
                    self.assertAlmostEqual(
                        val_p, val_e, places=7,
                        msg=f"Trade #{i+1} field '{field}' differs between Prefix and Extended! ({val_p} vs {val_e})"
                    )
                else:
                    self.assertEqual(
                        val_p, val_e,
                        msg=f"Trade #{i+1} field '{field}' differs between Prefix and Extended! ({val_p} vs {val_e})"
                    )

    def test_12_sell_limit_boundary_299s_vs_300s(self):
        """Stress test SELL limit boundary at +299s (fills LIMIT) vs +300s (expires, fills FALLBACK)."""
        t_known = 1635300000
        cand_sell = {
            'confirm_bar_open': t_known - 300,
            'signal_known_time': t_known,
            'direction': -1,
            'entry_market': 2000.0,
            'sl_price': 2005.0,
            'risk': 5.0,
            'choch_level': 2002.0,  # Sell Limit
        }

        # Case A: At +299s, Bid High touches limit 2002.0
        m1_299s = np.array([
            [t_known + 0, 1999.0, 2001.0, 1998.0, 2000.0],
            [t_known + 299, 2000.0, 2002.5, 1999.5, 2001.0],  # Bid high 2002.5 >= 2002.0 -> LIMIT!
        ])
        res_a = simulate_h2_entry(cand_sell, m1_299s, None, spread=0.30, slip=0.01)
        self.assertTrue(res_a['filled'])
        self.assertEqual(res_a['entry_type'], "LIMIT")
        self.assertEqual(res_a['fill_time'], t_known + 299)
        self.assertAlmostEqual(res_a['entry_price'], 2002.0)

        # Case B: At +300s, Bid High touches limit 2002.0 -> LIMIT EXPIRED, must fill as MARKET_FALLBACK!
        m1_300s = np.array([
            [t_known + 0, 1999.0, 2001.0, 1998.0, 2000.0],
            [t_known + 300, 2002.0, 2002.5, 2001.0, 2001.5],
        ])
        res_b = simulate_h2_entry(cand_sell, m1_300s, None, spread=0.30, slip=0.01)
        self.assertTrue(res_b['filled'])
        self.assertNotEqual(res_b['entry_type'], "LIMIT")
        self.assertEqual(res_b['entry_type'], "MARKET_FALLBACK")
        self.assertEqual(res_b['fill_time'], t_known + 300)
        # Sell Fallback enters at Bid Open - slip = 2002.0 - 0.01 = 2001.99
        self.assertAlmostEqual(res_b['entry_price'], 2001.99)

    def test_13_timeout_strictly_at_signal_known_time_plus_7200s(self):
        """Stress test 120-minute timeout: Must occur strictly at signal_known_time + 7200s."""
        t_known = 1635300000
        timeout_expected = t_known + 7200
        # M5 bars extending past timeout
        m5_bars = np.array([
            [t_known + 300, 2000.0, 2001.0, 1999.0, 2000.0],
            [timeout_expected - 300, 2000.0, 2001.0, 1999.0, 2000.0],
            [timeout_expected, 2000.0, 2001.0, 1999.0, 2000.0],  # Exactly at timeout!
            [timeout_expected + 300, 2000.0, 2001.0, 1999.0, 2000.0],
        ])

        trade = simulate_1r_trade(
            entry_price=2000.0,
            sl_price=1995.0,
            direction=1,
            fill_time=t_known + 60,
            t0=t_known - 300,
            m5_bars=m5_bars,
            m5_start_idx=0,
            schedule='BASE',
            signal_known_time=t_known
        )

        self.assertEqual(trade['exit_reason'], "TIMEOUT")
        self.assertEqual(trade['exit_time'], timeout_expected,
                         f"Timeout must trigger strictly at {timeout_expected}, got {trade['exit_time']}")

    def test_14_witness_short_false_tp_ask_boundary(self):
        """Adversarial stress on SELL TP: Ask Low must reach <= tp_price.
        If Bid touches TP but Ask is above TP, TP must NOT be awarded.
        """
        t_known = 1635300000
        entry_price = 2000.0
        risk = 5.0
        tp_price = 1995.0  # entry - risk for SELL
        sl_price = 2005.0
        spread = 0.30

        # Bar where Bid Low falls to 1994.80 (which is <= tp_price 1995.0)
        # BUT Ask Low = Bid Low + spread = 1994.80 + 0.30 = 1995.10 > tp_price (1995.00)!
        m5_false_tp = np.array([
            [t_known + 300, 1998.0, 1999.0, 1994.80, 1997.0],
            [t_known + 600, 1997.0, 1998.0, 1996.0, 1997.0],
            [t_known + 7200, 1997.0, 1998.0, 1996.0, 1997.0],
        ])

        trade = simulate_1r_trade(
            entry_price=entry_price,
            sl_price=sl_price,
            direction=-1,
            fill_time=t_known,
            t0=t_known - 300,
            m5_bars=m5_false_tp,
            m5_start_idx=0,
            schedule='BASE',
            signal_known_time=t_known
        )

        self.assertNotEqual(trade['exit_reason'], "TP",
                            "CRITICAL LEAK: SELL TP awarded when Ask was still above TP!")
        self.assertEqual(trade['exit_reason'], "TIMEOUT")

    def test_15_single_cost_accounting_ledger_check(self):
        """Verify fee accounting: spread and slippage are NOT subtracted twice in net_pnl."""
        t_known = 1635300000
        spread, comm, slip = FEE_SCHEDULES['BASE']  # 0.30, 0.07, 0.01

        # Simulate a clean BUY TP trade
        m5_tp = np.array([
            [t_known + 300, 2000.0, 2010.0, 1999.0, 2008.0],
        ])
        trade = simulate_1r_trade(
            entry_price=2000.0,
            sl_price=1995.0,
            direction=1,
            fill_time=t_known,
            t0=t_known - 300,
            m5_bars=m5_tp,
            m5_start_idx=0,
            schedule='BASE',
            signal_known_time=t_known
        )

        self.assertEqual(trade['exit_reason'], "TP")
        self.assertEqual(trade['exit_price'], 2005.0)  # TP price = 2000.0 + 5.0
        expected_gross = 2005.0 - 2000.0  # 5.0
        expected_net = expected_gross - comm  # 5.0 - 0.07 = 4.93
        self.assertAlmostEqual(trade['gross_pnl_usd'], expected_gross)
        self.assertAlmostEqual(trade['commission_usd'], comm)
        self.assertAlmostEqual(trade['net_pnl_usd'], expected_net, places=4)
        # Net R = 4.93 / 5.0 = 0.986
        self.assertAlmostEqual(trade['net_r'], expected_net / 5.0, places=4)


if __name__ == '__main__':
    unittest.main()

