"""Limit fills must follow quote side, event order and actual entry risk."""
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
import research_scalp_limit_v4 as v
from can_ho_tro_scalp_plan import Plan
from test_can_ho_tro_scalp import candidate,AT
from test_research_scalp_weekly_v3 import new_candidate

SPEC=dict(group='WEEKLY',mode='MIDPOINT',rr=.8)
COST=dict(spread=.3,slip=0.,commission_price=.07)


class LimitChecks(unittest.TestCase):
    def test_price_before_fill_cannot_close_unfilled_order(self):
        market=np.array([[AT,100,102,98.5,98.6]],float)
        late=v.simulate(0,new_candidate(),market,SPEC,COST,'OHLC')
        early=v.simulate(0,new_candidate(),market,SPEC,COST,'OLHC')
        self.assertEqual(late['state'],'CENSORED_FILLED')
        self.assertEqual(late['exit_time'],0)
        self.assertEqual(early['state'],'CLOSED');self.assertEqual(early['reason'],'TARGET')
        self.assertAlmostEqual(early['entry'],99.)
        self.assertAlmostEqual(early['risk'],2.)
        self.assertAlmostEqual(early['r'],.765)

    def test_gap_across_source_stop_cancels_before_fill_without_fees(self):
        market=np.array([[AT,100,100.1,99.8,100],[AT+60,97.5,98,97,97.5]],float)
        for path in v.PATHS:
            r=v.simulate(0,new_candidate(),market,SPEC,COST,path)
            self.assertEqual(r['state'],'CANCELLED');self.assertEqual(r['entry_time'],0)
            self.assertEqual(r['commission_r'],0.)

    def test_continuous_move_fills_before_stop(self):
        market=np.array([[AT,100,100.1,96,97]],float)
        for path in v.PATHS:
            r=v.simulate(0,new_candidate(),market,SPEC,COST,path)
            self.assertEqual(r['state'],'CLOSED');self.assertEqual(r['reason'],'STOP')
            self.assertAlmostEqual(r['r'],-1.035)

    def test_quote_side_rejects_bid_only_buy_touch(self):
        market=np.array([[AT,100,100.1,98.9,99.5]],float)
        r=v.simulate(0,new_candidate(),market,SPEC,COST,'OLHC')
        self.assertEqual(r['state'],'CENSORED_PENDING');self.assertEqual(r['entry_time'],0)
        sell=np.array([[AT,100,100.9,99.8,100.5]],float)
        r=v.simulate(0,new_candidate(False),sell,SPEC,COST,'OHLC')
        self.assertEqual(r['state'],'CENSORED_PENDING')

    def test_expiry_precedes_touch_at_exact_deadline(self):
        market=np.array([[AT,100,100.1,99.8,100],[AT+900,98.7,100,98.5,99]],float)
        r=v.simulate(0,new_candidate(),market,SPEC,COST,'OLHC')
        self.assertEqual(r['state'],'EXPIRED');self.assertEqual(r['entry_time'],0)
        self.assertEqual(r['commission_r'],0.)

    def test_marketable_limit_and_delayed_quote_are_rejected(self):
        c=new_candidate();market=np.array([[AT,98.5,101,98.4,100]],float)
        r=v.simulate(0,c,market,SPEC,COST,'OLHC')
        self.assertEqual(r['reason'],'LIMIT_NOT_PASSIVE')
        market[:,0]+=120
        r=v.simulate(0,c,market,SPEC,COST,'OLHC')
        self.assertEqual(r['reason'],'NO_ENTRY_QUOTE');self.assertEqual(r['commission_r'],0.)

    def test_custom_pending_hours_do_not_change_default(self):
        c=candidate();c[1]=11*3600+55*60;c[0]=c[1]-300
        default=Plan(c,retest=True,spread=.3)
        broad=Plan(c,retest=True,spread=.3);broad.pending_hours=tuple(range(8,19))
        for p in (default,broad):p.start(int(c[1]),100,100.3);p.quote(12*3600,98.7,99.)
        self.assertEqual(default.state,'CANCELLED');self.assertEqual(broad.state,'FILLED')

    def test_entry_modes_round_away_and_preserve_source(self):
        for buy in (True,False):
            c=new_candidate(buy);c[16]=99.123 if buy else 100.877
            d=1 if buy else -1
            for mode in ('SHALLOW','MIDPOINT','LEVEL'):
                modified,retest=v.entry_candidate(c,dict(mode=mode))
                self.assertTrue(retest);self.assertLess(d*(modified[22]-c[21]),0)
                self.assertEqual(modified[19],c[19]);self.assertEqual(modified[1],c[1])
            modified,retest=v.entry_candidate(new_candidate(buy,0),dict(mode='LEVEL'))
            self.assertFalse(retest)

    def test_pending_blocks_next_signal_but_only_fills_count_toward_cap(self):
        raw=np.array([new_candidate() for _ in range(5)])
        raw[:,1]=AT+np.array([0,300,1200,1500,1800]);raw[:,13]=raw[:,1]-600
        def fake(index,c,*args):
            return dict(state='EXPIRED' if index==0 else 'CLOSED',entry_time=0 if index==0 else int(c[1]),
                        exit_time=int(c[1])+(900 if index==0 else 60))
        with patch.object(v,'simulate',side_effect=fake) as sim:
            rows,rejects=v.run_serial(raw,np.empty((0,5)),SPEC,{},'OLHC')
        self.assertEqual(len(rows),3);self.assertEqual(sim.call_count,3)
        self.assertEqual(rejects['BUSY'],1);self.assertEqual(rejects['CAP'],1)

    def test_limit_entry_has_no_worse_than_limit_slippage(self):
        market=np.array([[AT,100,102,98.5,100.5]],float)
        cost=dict(spread=.45,slip=.05,commission_price=.1)
        for path in v.PATHS:
            r=v.simulate(0,new_candidate(),market,SPEC,cost,path)
            self.assertEqual(r['entry'],99.)
            self.assertAlmostEqual(r['commission_r'],.05)


if __name__=='__main__':unittest.main()
