"""Causality, money, and weekly census checks for the separate experiment."""
import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

import numpy as np

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
import research_scalp_weekly_v3 as w
from test_can_ho_tro_scalp import candidate, AT
from research_scalp_v2 import simulate as old_simulate
from can_ho_tro_scalp_core import source_zones


def new_candidate(buy=True,family=1):
    c=np.zeros(40);c[:36]=candidate(buy);c[36]=family;c[38]=1
    return c


class WeeklyChecks(unittest.TestCase):
    def test_source_clock_parameter_preserves_default_and_only_changes_availability(self):
        b=np.array([[i*3600,100,100.1,99.9,100] for i in range(40)],float)
        b[21,1:]=[100,102,98,100]
        default=source_zones(b,np.ones(len(b)),len(b))
        explicit=source_zones(b,np.ones(len(b)),len(b),3600)
        fast=source_zones(b,np.ones(len(b)),len(b),900)
        np.testing.assert_array_equal(default,explicit)
        self.assertGreater(len(default),0)
        fast[:,13]+=2700
        np.testing.assert_array_equal(default,fast)

    def test_targets_use_actual_risk_and_bid_ask_both_sides(self):
        for buy in (True,False):
            for rr in (.8,1.,1.2):
                p=w.WeeklyPlan(new_candidate(buy),spread=.3,slip=.01);p.rr=rr
                p.start(AT,100,100.3)
                self.assertEqual(p.state,'FILLED')
                self.assertGreaterEqual(p.d*(p.target-p.entry)/p.risk,rr-1e-12)
                self.assertLess(p.d*(p.target-p.entry)/p.risk,rr+.01/p.risk+1e-12)
                self.assertEqual(p.deadline,AT+7200)

    def test_stop_first_and_commission_once(self):
        market=np.array([[AT,100,104,97,100]],float)
        for buy in (True,False):
            r=w.simulate(0,new_candidate(buy),market,1.,dict(spread=0.,slip=0.,commission_price=.07))
            self.assertEqual(r['reason'],'STOP')
            self.assertEqual(r['ambiguous_minutes'],1)
            self.assertAlmostEqual(r['r'],-1.035)

    def test_time_exit_and_missing_quote_are_not_free_fills(self):
        c=new_candidate();cost=dict(spread=.3,slip=.01,commission_price=.07)
        market=np.array([[AT,100,100.5,99.9,100],[AT+7200,99,99.5,98.9,99]],float)
        r=w.simulate(0,c,market,1.,cost)
        self.assertEqual(r['reason'],'TIME');self.assertLess(r['r'],0)
        rejected=w.simulate(0,c,market[1:],1.,cost)
        self.assertEqual(rejected['state'],'REJECTED');self.assertEqual(rejected['commission_r'],0)

    def test_fresh_simulation_matches_existing_plan_before_cutoff(self):
        market=np.array([[AT,100,100.5,99.9,100],[AT+60,101,101.5,100.9,101]],float)
        cost=dict(spread=.3,slip=.01,commission_price=.07)
        for buy in (True,False):
            old=old_simulate(0,candidate(buy),market,np.empty((0,5)),dict(rule='FRESH',target='R05'),cost)
            new=w.simulate(0,new_candidate(buy,0),market,1.2,cost)
            for key in ('state','reason','entry','initial_sl','risk','entry_time','exit_time','r','commission_r'):
                self.assertEqual(old[key],new[key],key)

    def test_census_includes_empty_weeks(self):
        start=int(datetime(2022,1,3,tzinfo=timezone.utc).timestamp())
        market=np.array([[start+i*604800,100,101,99,100] for i in range(3)],float)
        rows=[dict(entry_time=start+604800,state='CLOSED',r=.8)]
        f=w.weekly(rows,market,start,start+3*604800)
        self.assertEqual(f['weeks'],3);self.assertEqual(len(f['empty_weeks']),2)
        self.assertEqual(f['min'],0);self.assertAlmostEqual(f['mean'],1/3)

    def test_level_must_be_known_before_sweep_and_first_test_consumed(self):
        bars=np.array([[28800-30*300+i*300,101.1,101.3,100.5,101.2] for i in range(33)],float)
        bars[30,1:]=[100.4,101.,99.8,100.9]
        levels=np.array([[27000,28800,100.,1.]],float)
        h=np.array([[0,101,102,100,101]],float)
        args=(np.ones(len(bars)),h,np.array([100.]),np.array([1.]),1,0,999999)
        self.assertEqual(len(w.detect_failure(bars,levels,*args)),1)
        unknown=levels.copy();unknown[0,1]+=1
        self.assertEqual(len(w.detect_failure(bars,unknown,*args)),0)
        bars[31]=bars[30];bars[31,0]+=300
        bars[30,1:]=[100.2,100.3,99.,99.2]
        self.assertEqual(len(w.detect_failure(bars,levels,*args)),0)

    def test_adx_warmup_and_complete_aggregation(self):
        bars=np.array([[i*300,100+i,101+i,99+i,100.5+i] for i in range(60)],float)
        adx,pdi,mdi=w.wilder_adx(bars)
        self.assertTrue(np.all(adx[:27]==0));self.assertAlmostEqual(adx[-1],100.)
        self.assertGreater(pdi[-1],mdi[-1])
        self.assertEqual(len(w.aggregate_complete(bars,900)),20)
        self.assertEqual(len(w.aggregate_complete(np.delete(bars,1,axis=0),900)),19)
        self.assertEqual(len(w.swing_levels(bars[:4])),0)

    def test_caps_count_actual_entries_and_single_position(self):
        raw=np.array([new_candidate() for _ in range(4)])
        raw[:,1]=AT+np.arange(4)*300;raw[:,13]=raw[:,1]-600
        fake=lambda i,c,*args:dict(entry_time=int(c[1]),exit_time=int(c[1])+60,state='CLOSED')
        with patch.object(w,'simulate',side_effect=fake):
            rows,rejects=w.run_serial(raw,np.empty((0,5)),dict(group='M15_FAILURE',rr=1.),{})
        self.assertEqual(len(rows),2);self.assertEqual(rejects['CAP'],2)


if __name__=='__main__':unittest.main()
