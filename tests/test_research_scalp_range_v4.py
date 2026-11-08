"""Frozen source levels, context times and actual quote-side mean targets."""
import sys
import unittest
from pathlib import Path

import numpy as np

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
import research_scalp_range_v4 as r
from test_research_scalp_weekly_v3 import new_candidate
from test_can_ho_tro_scalp import AT


class RangeChecks(unittest.TestCase):
    def setUp(self):r.w.FAMILIES.update(r.NAMES)

    def test_mean_target_uses_actual_fill_risk_and_quote_side_both_directions(self):
        cost=dict(spread=.3,slip=.01,commission_price=.07)
        for buy in (True,False):
            c=new_candidate(buy,8);c[29]=103 if buy else 97
            market=np.array([[AT,100,103.5,96.5,100]],float)
            # Isolate target without the other extreme crossing the protective stop.
            market[0,3 if buy else 2]=99.9 if buy else 100.1
            result=r.simulate(0,c,market,cost)
            self.assertEqual(result['reason'],'TARGET')
            self.assertEqual(result['exit_price'],c[29])
            direction=1 if buy else -1
            expected=(direction*(c[29]-result['entry'])-.07)/result['risk']
            self.assertAlmostEqual(result['r'],expected)

    def test_insufficient_mean_room_never_creates_fill_or_commission(self):
        c=new_candidate(family=8);c[29]=101
        result=r.simulate(0,c,np.array([[AT,100,110,99.9,105]],float),dict(spread=.3,slip=.01,commission_price=.07))
        self.assertEqual(result['state'],'REJECTED');self.assertEqual(result['reason'],'MEAN_ROOM_BELOW_08R')
        self.assertEqual(result['entry_time'],0);self.assertEqual(result['commission_r'],0.)
        self.assertFalse(any(event['kind']=='FILL' for event in result['events']))

    def test_both_hit_minute_remains_stop_first(self):
        c=new_candidate(family=8);c[29]=103
        result=r.simulate(0,c,np.array([[AT,100,104,97,100]],float),dict(spread=.3,slip=0.,commission_price=.07))
        self.assertEqual(result['reason'],'STOP');self.assertEqual(result['ambiguous_minutes'],1)
        self.assertLess(result['r'],-1.)

    def test_context_ignores_forming_and_future_bars(self):
        bars=np.array([[i*3600,100,101,99,100] for i in range(50)],float)
        ma=np.full(50,100.);atr=np.ones(50);adx=np.full(50,10.)
        at=42*3600
        self.assertTrue(r.context_ok(at,bars,3600,ma,atr,adx))
        ma[42:]=1e12;adx[42:]=100
        self.assertTrue(r.context_ok(at,bars,3600,ma,atr,adx))
        adx[41]=30
        self.assertFalse(r.context_ok(at,bars,3600,ma,atr,adx))

    def test_band_and_mean_are_frozen_before_excursion_and_signal_is_single(self):
        m5=np.array([[28800+i*300,100,100.1,99.9,100] for i in range(80)],float)
        m5[60,1:]=[99.4,99.65,99.2,99.6]
        m5[61,1:]=[99.4,99.65,99.2,99.6]
        h1=np.array([[i*3600,100,101,99,100] for i in range(50)],float)
        rows=r.detect_range(m5,h1,h1,3600,10,0,999999999)
        self.assertEqual(len(rows),1)
        c=rows[0];self.assertEqual(c[0],m5[60,0])
        self.assertLessEqual(c[12],c[13]);self.assertAlmostEqual(c[29],100.)
        self.assertNotEqual(c[29],r.w.ema(m5,20)[60])

    def test_fresh_keeps_its_original_fixed_r_exit(self):
        c=new_candidate(family=0);c[29]=101
        market=np.array([[AT,100,102,99.9,101]],float)
        cost=dict(spread=.3,slip=.01,commission_price=.07)
        actual=r.simulate(0,c,market,cost);expected=r.w.simulate(0,c,market,1.2,cost)
        for key in ('state','reason','entry_time','exit_time','entry','initial_sl','risk','r','commission_r'):
            self.assertEqual(actual[key],expected[key],key)
        self.assertIsNone(actual['frozen_mean'])


if __name__=='__main__':unittest.main()
