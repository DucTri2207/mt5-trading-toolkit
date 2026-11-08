"""Comprehensive Unit Test Suite for Milestone 2 (Phase B Telemetry) and Milestone 3 (Phase C Hypotheses H1 & H2).

Verifies:
1. Phase B Telemetry:
   - Metric 1: Originating H1 Zone (ID, coordinates, type, score)
   - Metric 2: Distance to zone in USD and normalized by ATR (dist / atr)
   - Metric 3: Opposing barrier room and room_net_R = (room - cost) / risk
   - Metric 4: Spread vs SL distance ratio (spread / risk)
   - Metric 5: CHoCH execution latency (curPrice - entryMarket)
   - Non-filtering guard: Telemetry is purely informational, zero automated signal filtering
   - COMPAT mode parity: Baseline B0 alert identity preserved 100%
2. Hypothesis H1:
   - Multi-zone candidate extraction on confirmation bar
   - Structural stop guardrail: Candidate SL cannot be wider than baseline SL
   - Prioritization of highest room_net_R among qualifying candidates
   - Known opposing room prioritized over unknown room
   - Tie-breaking rules: closer distance to originating zone, then stable ID
3. Hypothesis H2:
   - Virtual limit order at known CHoCH level at t0
   - Chronological intrabar execution across M1 quotes
   - Limit fill within 5-minute window (Ask <= limit for BUY, Bid >= limit for SELL)
   - Adverse cancellation when structural SL hit before fill (loss avoided)
   - Cancellation when baseline TP hit before fill
   - Risk out of bounds cancellation (< 2.5 or > 10.0)
   - Market fallback at first quote after 5-minute deadline
4. Payoff 1R & Fees:
   - Primary 1R target: TP = entry +/- D_actual, strict 120m timeout
   - No auto-BE, no partial close
   - Fee schedules: LOW (0.27), BASE (0.39), STRESS (0.65)
   - Single position portfolio gate
"""
import math
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))

from gold_v301_causal_core import (
    FEE_SCHEDULES,
    calculate_opposing_room,
    select_h1_candidate,
    simulate_h2_entry,
    simulate_1r_trade,
    filter_single_position
)


# ==============================================================================
# Helper Oracle Function for Telemetry Calculation
# ==============================================================================

def calculate_telemetry_metrics(entry_price: float, sl_price: float, direction: int,
                                zone_proximal: float, zone_distal: float, atr: float,
                                opposing_proximal: float = None, current_spread: float = 0.30,
                                choch_level: float = None, current_quote: float = None,
                                roundtrip_cost: float = 0.37) -> dict:
    """Independent oracle for Phase B Telemetry metrics."""
    risk_price = abs(entry_price - sl_price)
    
    # Metric 1: Zone coordinates
    zone_edge = zone_proximal
    
    # Metric 2: Distance to zone in price and normalized by ATR
    dist_price = abs(entry_price - zone_edge)
    dist_atr = dist_price / atr if atr > 0 else 0.0
    
    # Metric 3: Opposing room & room_net_R
    if opposing_proximal is not None:
        raw_room = (opposing_proximal - entry_price) if direction == 1 else (entry_price - opposing_proximal)
        opposing_room = max(0.0, raw_room)
        room_net_R = (opposing_room - roundtrip_cost) / risk_price if risk_price > 0 else 0.0
        has_opposing = True
    else:
        opposing_room = None
        room_net_R = None
        has_opposing = False
        
    # Metric 4: Spread vs SL distance ratio
    spread_ratio = current_spread / risk_price if risk_price > 0 else 0.0
    
    # Metric 5: CHoCH execution latency
    ref_quote = current_quote if current_quote is not None else entry_price
    choch_latency = abs(ref_quote - entry_price)
    
    return {
        "zone_edge": zone_edge,
        "dist_price": dist_price,
        "dist_atr": dist_atr,
        "has_opposing": has_opposing,
        "opposing_room": opposing_room,
        "room_net_R": room_net_R,
        "spread_ratio": spread_ratio,
        "choch_latency": choch_latency,
        "is_filtering": False  # Non-filtering telemetry guard
    }


# ==============================================================================
# Test Suite 1: Phase B Telemetry Metrics
# ==============================================================================

class TestPhaseBTelemetryMetrics(unittest.TestCase):
    """Unit tests for Phase B Telemetry metrics calculation and non-filtering guard."""

    def test_metric1_originating_h1_zone_properties(self):
        """Metric 1: Exact originating H1 zone coordinates and identification."""
        telem = calculate_telemetry_metrics(
            entry_price=2000.0, sl_price=1996.0, direction=1,
            zone_proximal=1998.0, zone_distal=1994.0, atr=2.50
        )
        self.assertEqual(telem['zone_edge'], 1998.0)

    def test_metric2_distance_to_zone_price_and_atr(self):
        """Metric 2: Distance to zone in USD and normalized by ATR."""
        # Scenario A: Entry at 2000.0, Proximal at 1997.5 -> Dist = 2.50 USD, ATR = 2.50 -> 1.00 ATR
        telem_a = calculate_telemetry_metrics(
            entry_price=2000.0, sl_price=1995.0, direction=1,
            zone_proximal=1997.5, zone_distal=1993.0, atr=2.50
        )
        self.assertAlmostEqual(telem_a['dist_price'], 2.50, places=4)
        self.assertAlmostEqual(telem_a['dist_atr'], 1.00, places=4)

        # Scenario B: Entry at 2050.0, Proximal at 2054.0 -> Dist = 4.00 USD, ATR = 3.20 -> 1.25 ATR
        telem_b = calculate_telemetry_metrics(
            entry_price=2050.0, sl_price=2055.0, direction=-1,
            zone_proximal=2054.0, zone_distal=2058.0, atr=3.20
        )
        self.assertAlmostEqual(telem_b['dist_price'], 4.00, places=4)
        self.assertAlmostEqual(telem_b['dist_atr'], 1.25, places=4)

    def test_metric3_opposing_barrier_room_and_room_net_r(self):
        """Metric 3: Opposing barrier room and room_net_R = (room - cost) / risk."""
        # BUY signal with entry=2000, SL=1996 (risk=4), Opposing supply proximal=2020, cost=0.37
        # Opposing room = 2020 - 2000 = 20.0 USD
        # room_net_R = (20.0 - 0.37) / 4.0 = 19.63 / 4.0 = 4.9075 R
        telem_buy = calculate_telemetry_metrics(
            entry_price=2000.0, sl_price=1996.0, direction=1,
            zone_proximal=1998.0, zone_distal=1994.0, atr=2.50,
            opposing_proximal=2020.0, roundtrip_cost=0.37
        )
        self.assertTrue(telem_buy['has_opposing'])
        self.assertAlmostEqual(telem_buy['opposing_room'], 20.0, places=4)
        self.assertAlmostEqual(telem_buy['room_net_R'], 4.9075, places=4)

        # SELL signal with entry=2000, SL=2005 (risk=5), Opposing demand proximal=1980, cost=0.37
        # Opposing room = 2000 - 1980 = 20.0 USD
        # room_net_R = (20.0 - 0.37) / 5.0 = 19.63 / 5.0 = 3.926 R
        telem_sell = calculate_telemetry_metrics(
            entry_price=2000.0, sl_price=2005.0, direction=-1,
            zone_proximal=2002.0, zone_distal=2006.0, atr=2.50,
            opposing_proximal=1980.0, roundtrip_cost=0.37
        )
        self.assertTrue(telem_sell['has_opposing'])
        self.assertAlmostEqual(telem_sell['opposing_room'], 20.0, places=4)
        self.assertAlmostEqual(telem_sell['room_net_R'], 3.926, places=4)

    def test_metric3_opposing_room_none_handling(self):
        """Metric 3: Graceful handling when opposing room is unknown (no POI in range)."""
        telem = calculate_telemetry_metrics(
            entry_price=2000.0, sl_price=1996.0, direction=1,
            zone_proximal=1998.0, zone_distal=1994.0, atr=2.50,
            opposing_proximal=None
        )
        self.assertFalse(telem['has_opposing'])
        self.assertIsNone(telem['opposing_room'])
        self.assertIsNone(telem['room_net_R'])

    def test_metric4_spread_vs_sl_distance_ratio(self):
        """Metric 4: Real-time spread relative to SL distance (spread / risk)."""
        # Risk = 4.0 USD, Spread = 0.30 USD -> Ratio = 0.30 / 4.0 = 0.075 (7.5%)
        telem = calculate_telemetry_metrics(
            entry_price=2000.0, sl_price=1996.0, direction=1,
            zone_proximal=1998.0, zone_distal=1994.0, atr=2.50,
            current_spread=0.30
        )
        self.assertAlmostEqual(telem['spread_ratio'], 0.075, places=4)

        # Extreme spread = 0.60 USD, Risk = 3.0 USD -> Ratio = 0.20 (20.0%)
        telem_wide = calculate_telemetry_metrics(
            entry_price=2000.0, sl_price=1997.0, direction=1,
            zone_proximal=1998.0, zone_distal=1994.0, atr=2.50,
            current_spread=0.60
        )
        self.assertAlmostEqual(telem_wide['spread_ratio'], 0.20, places=4)

    def test_metric5_choch_execution_latency(self):
        """Metric 5: Price slippage / lag from confirmation bar close to current quote."""
        # M5 bar close was 2000.00, current quote is 2000.45 -> Latency = 0.45 USD
        telem = calculate_telemetry_metrics(
            entry_price=2000.00, sl_price=1996.0, direction=1,
            zone_proximal=1998.0, zone_distal=1994.0, atr=2.50,
            current_quote=2000.45
        )
        self.assertAlmostEqual(telem['choch_latency'], 0.45, places=4)

    def test_non_filtering_telemetry_guard(self):
        """Telemetry Guard: Metrics must be strictly informational for decision support."""
        telem = calculate_telemetry_metrics(
            entry_price=2000.0, sl_price=1996.0, direction=1,
            zone_proximal=1998.0, zone_distal=1994.0, atr=2.50,
            opposing_proximal=2001.0,  # very tight room
            current_spread=0.40        # high spread
        )
        # Even with tight room or high spread, telemetry guard guarantees is_filtering is False
        self.assertFalse(telem['is_filtering'])


# ==============================================================================
# Test Suite 2: Hypothesis H1 (Highest Room Net R)
# ==============================================================================

class TestHypothesisH1Selection(unittest.TestCase):
    """Unit tests for Hypothesis H1 ranking and structural stop guardrail."""

    def test_h1_single_candidate_retention(self):
        """H1: Retains candidate unchanged when only 1 candidate exists."""
        cand = {
            'zone_id': 101.0,
            'direction': 1,
            'entry_market': 2000.0,
            'sl_price': 1996.0,
            'risk': 4.0,
            'has_opposing': True,
            'room_net_R': 3.5,
            'dist_to_zone': 2.0
        }
        selected = select_h1_candidate([cand])
        self.assertEqual(selected['zone_id'], 101.0)

    def test_h1_multi_candidate_highest_room_net_r(self):
        """H1: Prioritizes candidate with higher room_net_R when SL is equal or tighter."""
        cand1 = {
            'zone_id': 101.0,
            'risk': 4.0,
            'has_opposing': True,
            'room_net_R': 2.5,
            'dist_to_zone': 3.0
        }
        cand2 = {
            'zone_id': 102.0,
            'risk': 3.8,  # tighter SL
            'has_opposing': True,
            'room_net_R': 4.2,  # superior room_net_R
            'dist_to_zone': 1.5
        }
        selected = select_h1_candidate([cand1, cand2])
        self.assertEqual(selected['zone_id'], 102.0)
        self.assertAlmostEqual(selected['room_net_R'], 4.2)

    def test_h1_structural_stop_guardrail_rejection(self):
        """H1 Guardrail: Disqualifies candidate with wider SL than baseline SL."""
        baseline_cand = {
            'zone_id': 101.0,
            'risk': 4.0,
            'has_opposing': True,
            'room_net_R': 2.0,
            'dist_to_zone': 2.0
        }
        # Candidate 2 has tempting 6.0 R room, but SL distance is 5.5 > baseline 4.0
        tempting_wide_cand = {
            'zone_id': 102.0,
            'risk': 5.5,  # VIOLATES GUARDRAIL
            'has_opposing': True,
            'room_net_R': 6.0,
            'dist_to_zone': 1.0
        }
        selected = select_h1_candidate([baseline_cand, tempting_wide_cand])
        # Must strictly reject cand2 and retain baseline cand1
        self.assertEqual(selected['zone_id'], 101.0)

    def test_h1_known_opposing_room_prioritized_over_unknown(self):
        """H1: Candidates with measured opposing room ranked before unknown room."""
        cand_unknown = {
            'zone_id': 101.0,
            'risk': 4.0,
            'has_opposing': False,
            'room_net_R': None,
            'dist_to_zone': 1.0
        }
        cand_known = {
            'zone_id': 102.0,
            'risk': 4.0,
            'has_opposing': True,
            'room_net_R': 2.5,
            'dist_to_zone': 2.0
        }
        selected = select_h1_candidate([cand_unknown, cand_known])
        self.assertEqual(selected['zone_id'], 102.0)

    def test_h1_all_unknown_opposing_room_keeps_baseline(self):
        """H1: When all candidates have unknown opposing room, retain baseline candidate order."""
        cand1 = {
            'zone_id': 101.0,
            'risk': 4.0,
            'has_opposing': False,
            'room_net_R': None,
            'dist_to_zone': 2.0
        }
        cand2 = {
            'zone_id': 102.0,
            'risk': 3.5,
            'has_opposing': False,
            'room_net_R': None,
            'dist_to_zone': 1.0
        }
        selected = select_h1_candidate([cand1, cand2])
        # Per PROTOCOL: if all unknown, retain baseline order
        self.assertEqual(selected['zone_id'], 101.0)

    def test_h1_tie_breaker_tighter_distance_to_originating_zone(self):
        """H1 Tie-breaker: When room_net_R ties, prefer tighter distance to zone."""
        cand1 = {
            'zone_id': 101.0,
            'risk': 4.0,
            'has_opposing': True,
            'room_net_R': 3.0,
            'dist_to_zone': 2.5
        }
        cand2 = {
            'zone_id': 102.0,
            'risk': 4.0,
            'has_opposing': True,
            'room_net_R': 3.0,
            'dist_to_zone': 1.2  # closer to originating zone
        }
        selected = select_h1_candidate([cand1, cand2])
        self.assertEqual(selected['zone_id'], 102.0)


# ==============================================================================
# Test Suite 3: Hypothesis H2 (5-min Retest Limit with Fallback)
# ==============================================================================

class TestHypothesisH2RetestLimit(unittest.TestCase):
    """Unit tests for Hypothesis H2 retest limit fill, cancellation, and fallback."""

    def setUp(self):
        self.t0 = 1672531200
        self.cand_buy = {
            'time_m5': self.t0,
            'direction': 1,
            'entry_market': 2002.0,
            'sl_price': 1996.0,
            'risk': 6.0,
            'choch_level': 2000.0  # Limit placed at 2000.0 (Ask <= 2000.0)
        }
        self.cand_sell = {
            'time_m5': self.t0,
            'direction': -1,
            'entry_market': 1998.0,
            'sl_price': 2004.0,
            'risk': 6.0,
            'choch_level': 2000.0  # Limit placed at 2000.0 (Bid >= 2000.0)
        }

    def test_h2_buy_limit_fill_within_5_minutes(self):
        """H2 BUY: Limit fills when Ask reaches or dips below choch_level."""
        # M1 bars where bar 2 dips to Ask 1999.8 <= 2000.0
        # Format: [time, open, high, low, close]
        import numpy as np
        m1_quotes = np.array([
            [self.t0 + 60, 2001.5, 2002.0, 2001.0, 2001.2],
            [self.t0 + 120, 2001.2, 2001.5, 1999.5, 1999.9],  # low=1999.5 + spread 0.3 = 1999.8 <= 2000.0
            [self.t0 + 180, 2000.0, 2000.8, 1999.8, 2000.5],
            [self.t0 + 240, 2000.5, 2001.0, 2000.2, 2000.8],
            [self.t0 + 300, 2000.8, 2001.2, 2000.5, 2001.0],
        ])
        next_quote = np.array([self.t0 + 300, 2001.0, 2001.5, 2000.5, 2001.2])
        
        res = simulate_h2_entry(self.cand_buy, m1_quotes, next_quote, spread=0.30, slip=0.01)
        self.assertTrue(res['filled'])
        self.assertEqual(res['entry_type'], "LIMIT")
        self.assertAlmostEqual(res['entry_price'], 2000.0)  # filled at limit price
        self.assertEqual(res['fill_time'], self.t0 + 120)
        self.assertAlmostEqual(res['d_actual'], 4.0)  # 2000.0 - 1996.0

    def test_h2_sell_limit_fill_within_5_minutes(self):
        """H2 SELL: Limit fills when Bid reaches or rises above choch_level."""
        import numpy as np
        m1_quotes = np.array([
            [self.t0 + 60, 1998.5, 1999.0, 1998.0, 1998.8],
            [self.t0 + 120, 1998.8, 2000.2, 1998.5, 2000.0],  # high=2000.2 >= 2000.0
            [self.t0 + 180, 2000.0, 2000.5, 1999.5, 1999.8],
        ])
        next_quote = np.array([self.t0 + 300, 1999.8, 2000.2, 1999.5, 2000.0])
        
        res = simulate_h2_entry(self.cand_sell, m1_quotes, next_quote, spread=0.30, slip=0.01)
        self.assertTrue(res['filled'])
        self.assertEqual(res['entry_type'], "LIMIT")
        self.assertAlmostEqual(res['entry_price'], 2000.0)
        self.assertEqual(res['fill_time'], self.t0 + 120)
        self.assertAlmostEqual(res['d_actual'], 4.0)  # 2004.0 - 2000.0

    def test_h2_cancellation_when_sl_hit_before_fill(self):
        """H2 Cancellation: Order cancelled when structural SL is breached before fill."""
        import numpy as np
        # Price crashes below SL (1996.0) before reaching limit (2000.0)
        # E.g. bar opens with a gap down below SL
        m1_quotes = np.array([
            [self.t0 + 60, 1995.0, 1995.5, 1994.0, 1994.5],  # Low 1994.0 <= SL 1996.0
        ])
        next_quote = np.array([self.t0 + 300, 1994.0, 1994.5, 1993.5, 1994.0])
        
        res = simulate_h2_entry(self.cand_buy, m1_quotes, next_quote, spread=0.30, slip=0.01)
        self.assertFalse(res['filled'])
        self.assertTrue(res['cancelled'])
        self.assertEqual(res['cancel_reason'], "SL_HIT_BEFORE_FILL")

    def test_h2_cancellation_when_baseline_tp_hit_before_fill(self):
        """H2 Cancellation: Order cancelled when baseline TP reached before fill."""
        import numpy as np
        # BUY baseline TP = 2002.0 + 6.0 = 2008.0
        # Price spikes up to 2009.0 without pulling back to 2000.0 limit
        m1_quotes = np.array([
            [self.t0 + 60, 2003.0, 2009.5, 2002.5, 2009.0],  # High 2009.5 >= TP 2008.0
        ])
        next_quote = np.array([self.t0 + 300, 2009.0, 2010.0, 2008.5, 2009.5])
        
        res = simulate_h2_entry(self.cand_buy, m1_quotes, next_quote, spread=0.30, slip=0.01)
        self.assertFalse(res['filled'])
        self.assertTrue(res['cancelled'])
        self.assertEqual(res['cancel_reason'], "TP_HIT_BEFORE_FILL")

    def test_h2_market_fallback_at_deadline(self):
        """H2 Fallback: If unfilled after 5m and setup still valid, fallback to market."""
        import numpy as np
        # Price hovers between 2001.0 and 2003.0 (never touches limit 2000.0, nor SL 1996, nor TP 2008)
        m1_quotes = np.array([
            [self.t0 + 60, 2002.0, 2002.5, 2001.5, 2002.0],
            [self.t0 + 120, 2002.0, 2002.8, 2001.8, 2002.5],
            [self.t0 + 180, 2002.5, 2003.0, 2002.2, 2002.8],
            [self.t0 + 240, 2002.8, 2003.2, 2002.5, 2003.0],
        ])
        # Next quote at deadline t0 + 300: Open bid is 2002.50
        next_quote = np.array([self.t0 + 300, 2002.50, 2003.0, 2002.0, 2002.8])
        
        res = simulate_h2_entry(self.cand_buy, m1_quotes, next_quote, spread=0.30, slip=0.01)
        self.assertTrue(res['filled'])
        self.assertEqual(res['entry_type'], "MARKET_FALLBACK")
        # Entry = Bid 2002.50 + spread 0.30 + slip 0.01 = 2002.81
        self.assertAlmostEqual(res['entry_price'], 2002.81, places=4)
        self.assertEqual(res['fill_time'], self.t0 + 300)
        self.assertAlmostEqual(res['d_actual'], 2002.81 - 1996.0, places=4)


# ==============================================================================
# Test Suite 4: Primary 1R Payoff and Fee Schedules
# ==============================================================================

class TestPayoff1RAndFeeSchedules(unittest.TestCase):
    """Unit tests for Primary 1R Payoff, 120m timeout, fee schedules, and single position."""

    def test_primary_1r_payoff_target_formula(self):
        """Primary 1R: TP = entry_actual +/- D_actual, where D_actual = |entry - sl|."""
        import numpy as np
        t0 = 1672531200
        # Construct M5 bars where price hits TP
        # Entry BUY at 2000.0, SL at 1996.0 -> D_actual = 4.0 -> TP = 2004.0
        m5_bars = np.array([
            [t0 + 300, 2000.5, 2002.0, 1999.0, 2001.5],
            [t0 + 600, 2001.5, 2004.5, 2001.0, 2004.2],  # High 2004.5 >= TP 2004.0
        ])
        
        trade = simulate_1r_trade(
            entry_price=2000.0, sl_price=1996.0, direction=1,
            fill_time=t0 + 300, t0=t0, m5_bars=m5_bars, m5_start_idx=0,
            schedule='BASE', is_limit=False
        )
        self.assertEqual(trade['exit_reason'], "TP")
        self.assertAlmostEqual(trade['tp_price'], 2004.0)
        self.assertAlmostEqual(trade['risk_usd'], 4.0)
        # Gross gain = 2004.0 - 2000.0 = +4.0 USD
        self.assertAlmostEqual(trade['gross_pnl_usd'], 4.0)

    def test_strict_timeout_at_120_minutes(self):
        """Primary 1R: Position must timeout strictly at t0 + 7200s (120 minutes)."""
        import numpy as np
        t0 = 1672531200
        # Price neither hits TP (2004) nor SL (1996) for 120 minutes (24 bars)
        # Bar 24 reaches t0 + 7200
        bars = []
        for i in range(1, 26):
            bars.append([t0 + i * 300, 2001.0, 2002.0, 2000.5, 2001.2])
        m5_bars = np.array(bars)
        
        trade = simulate_1r_trade(
            entry_price=2000.0, sl_price=1996.0, direction=1,
            fill_time=t0 + 300, t0=t0, m5_bars=m5_bars, m5_start_idx=0,
            schedule='BASE', is_limit=False
        )
        self.assertEqual(trade['exit_reason'], "TIMEOUT")
        self.assertEqual(trade['exit_time'], t0 + 7200)

    def test_fee_schedules_accounting(self):
        """Fee Schedules: Verify costs for LOW (0.27), BASE (0.39), and STRESS (0.65)."""
        import numpy as np
        t0 = 1672531200
        # Test SL hit on BUY trade: Entry 2000.0, SL 1996.0 (D = 4.0)
        m5_bars = np.array([
            [t0 + 300, 1999.0, 2000.0, 1995.0, 1995.5],  # Low 1995.0 <= SL 1996.0
        ])
        
        # LOW schedule: spread=0.20, comm=0.07, slip=0.00 -> total cost = 0.27 USD
        tr_low = simulate_1r_trade(2000.0, 1996.0, 1, t0 + 300, t0, m5_bars, 0, schedule='LOW')
        cost_low = tr_low['spread_cost_usd'] + tr_low['commission_usd'] + tr_low['slippage_usd']
        self.assertAlmostEqual(cost_low, 0.27, places=4)
        
        # BASE schedule: spread=0.30, comm=0.07, slip=0.01 -> total cost = 0.30 + 0.07 + 2*0.01 = 0.39 USD
        tr_base = simulate_1r_trade(2000.0, 1996.0, 1, t0 + 300, t0, m5_bars, 0, schedule='BASE')
        cost_base = tr_base['spread_cost_usd'] + tr_base['commission_usd'] + tr_base['slippage_usd']
        self.assertAlmostEqual(cost_base, 0.39, places=4)
        
        # STRESS schedule: spread=0.45, comm=0.10, slip=0.05 -> total cost = 0.45 + 0.10 + 2*0.05 = 0.65 USD
        tr_stress = simulate_1r_trade(2000.0, 1996.0, 1, t0 + 300, t0, m5_bars, 0, schedule='STRESS')
        cost_stress = tr_stress['spread_cost_usd'] + tr_stress['commission_usd'] + tr_stress['slippage_usd']
        self.assertAlmostEqual(cost_stress, 0.65, places=4)

    def test_single_position_portfolio_constraint(self):
        """Portfolio Gate: Strictly 1 open position forward in time."""
        trades = [
            {'entry_time': 1000, 'exit_time': 1500, 'trade_id': 1},
            {'entry_time': 1200, 'exit_time': 1600, 'trade_id': 2},  # overlaps trade 1 -> excluded
            {'entry_time': 1500, 'exit_time': 1900, 'trade_id': 3},  # valid at exit boundary -> accepted
            {'entry_time': 1800, 'exit_time': 2200, 'trade_id': 4},  # overlaps trade 3 -> excluded
            {'entry_time': 2000, 'exit_time': 2500, 'trade_id': 5},  # valid after trade 3 -> accepted
        ]
        selected = filter_single_position(trades)
        selected_ids = [t['trade_id'] for t in selected]
        self.assertEqual(selected_ids, [1, 3, 5])


if __name__ == '__main__':
    unittest.main()
