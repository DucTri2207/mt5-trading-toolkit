"""Money and causality checks for the new research variants."""
import sys
import unittest
from unittest.mock import patch
from datetime import datetime, timezone
from pathlib import Path
import numpy as np

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from research_scalp_v2 import ResearchPlan, simulate, feature, SPECS, run_serial
from test_can_ho_tro_scalp import candidate, AT, fallback_fixture
from can_ho_tro_scalp_core import raw_at


class ResearchChecks(unittest.TestCase):
    def test_fixed_three_uses_actual_fill_both_sides(self):
        for buy in [True,False]:
            p=ResearchPlan(candidate(buy),spread=.3,slip=.01)
            p.spec=dict(target='PRICE3',rule='ALL')
            p.start(AT,100,100.3)
            self.assertEqual(p.state,'FILLED')
            self.assertAlmostEqual((p.target-p.entry)*p.d,3.)

    def test_round_trip_commission_once(self):
        market=np.array([[AT,100,101.5,99.9,101.]],float)
        r=simulate(0,candidate(),market,np.empty((0,5)),SPECS[0],dict(spread=0.,slip=0.,commission_price=.07))
        self.assertAlmostEqual(r['gross_r'],.5)
        self.assertAlmostEqual(r['r'],.465)
        self.assertAlmostEqual(r['commission_r'],.035)

    def test_gaps_can_lose_more_than_one_r(self):
        market=np.array([[AT,100,100.1,99.9,100],[AT+60,97,97.1,96.9,97]],float)
        r=simulate(0,candidate(),market,np.empty((0,5)),SPECS[0],dict(spread=0.,slip=.05,commission_price=.07))
        self.assertLess(r['r'],-1.4)
        self.assertEqual(r['reason'],'STOP_GAP')

    def test_no_fees_for_rejected_entry(self):
        market=np.array([[AT+120,100,104,99,103]],float)
        r=simulate(0,candidate(),market,np.empty((0,5)),SPECS[0],dict(spread=0.,slip=0.,commission_price=.07))
        self.assertEqual(r['state'],'REJECTED');self.assertEqual(r['commission_r'],0.)

    def test_risk6_rejects_actual_gap_fill(self):
        p=ResearchPlan(candidate(),spread=.3)
        p.spec=dict(target='PRICE3',rule='RISK6')
        p.start(AT,104,104.3)
        self.assertEqual(p.state,'REJECTED');self.assertEqual(p.entry_time,0)

    def test_features_ignore_unclosed_h1(self):
        c=candidate();h=np.array([[i*3600,100,105,95,100+i] for i in range(12)],float)
        ma=np.arange(12,dtype=float)
        f=feature(c,h,ma)
        # Mutating all future and currently forming H1 bars cannot change features.
        mask=h[:,0]+3600>c[1];h[mask,1:]=1e10;ma[mask]=-1e10
        self.assertEqual(f,feature(c,h,ma))
        self.assertLessEqual(f['h1_feature_known_at'],c[1])

    def test_default_detector_unchanged_and_m1_known_time(self):
        m,h,z=fallback_fixture();args=(m,np.ones(len(m)),39,z,h,np.ones(len(h)),np.full(len(h),100.),8,0.,0.,0.,True)
        old=raw_at(*args);default=raw_at(*args,300);minute=raw_at(*args,60)
        np.testing.assert_array_equal(old,default)
        self.assertTrue(len(old)>0)
        np.testing.assert_array_equal(old[:,1]-minute[:,1],np.full(len(old),240.))
        np.testing.assert_array_equal(old[:,17]-minute[:,17],np.full(len(old),240.))

    def test_walkforward_unselected_past_position_cannot_block(self):
        boundary=int(datetime(2023,1,1,tzinfo=timezone.utc).timestamp())
        a=candidate();b=candidate();a[1]=boundary-300;b[1]=boundary+300;b[13]+=300
        market={'m1':np.array([[boundary+86400,100,101,99,100]],float),'h1':np.empty((0,5))}
        with patch('research_scalp_v2.accepts',return_value=True),patch('research_scalp_v2.simulate',return_value=dict(state='CLOSED',exit_time=boundary+3600)) as sim:
            rows,_=run_serial(np.array([a,b]),[{},{}],market,None,{},schedule={2023:SPECS[0]})
        self.assertEqual(len(rows),1);self.assertEqual(sim.call_args[0][0],1)

    def test_walkforward_selected_position_carries_across_year(self):
        boundary=int(datetime(2023,1,1,tzinfo=timezone.utc).timestamp())
        a=candidate();b=candidate();a[1]=boundary-300;b[1]=boundary+300;b[13]+=300
        market={'m1':np.array([[boundary+86400,100,101,99,100]],float),'h1':np.empty((0,5))}
        with patch('research_scalp_v2.accepts',return_value=True),patch('research_scalp_v2.simulate',return_value=dict(state='CLOSED',exit_time=boundary+3600)):
            rows,rejects=run_serial(np.array([a,b]),[{},{}],market,None,{},schedule={2022:SPECS[0],2023:SPECS[0]})
        self.assertEqual(len(rows),1);self.assertEqual(rejects['BUSY'],1)


if __name__=='__main__':unittest.main()
