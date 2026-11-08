"""Publication lag, expense-neutral shares, missing reports and causal daily residuals."""
import sys
import unittest
from pathlib import Path

import numpy as np

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
import research_scalp_flows_v16 as v
from test_research_scalp_seasonal_v10 import stamp


def sample_reports(n=240):
    i = np.arange(n);date = stamp(2021,1,1)+i*86400
    price = 170*np.exp(.0002*i+.005*np.sin(i/5))
    oz_share = .094*np.exp(-.00001*i)
    shares = 300e6*np.exp(.001*np.sin(i/9))
    return np.c_[date,price,oz_share,oz_share*shares,.0001*np.cos(i),1e7*(1+.2*np.sin(i/3))]


class FlowChecks(unittest.TestCase):
    def test_expense_adjustment_and_missing_are_not_zero(self):
        r = sample_reports(30);r[:,3] = r[:,2]*300e6
        f,_ = v.daily_features(r)
        np.testing.assert_allclose(f[1:,2],0,rtol=0,atol=1e-15)
        np.testing.assert_allclose(f[5:,3],0,rtol=0,atol=1e-15)
        self.assertTrue(np.isnan(f[:5,3]).all())
        np.testing.assert_allclose(f[5:,4],np.log(r[5:,1]/r[:-5,1]))
        gap = r.copy();gap[10:,0] += 5*86400
        f,_ = v.daily_features(gap)
        self.assertTrue(np.isnan(f[10,2]));self.assertTrue(np.isnan(f[10:15,3]).all())

    def test_availability_boundary_stale_and_no_future_fill(self):
        r = sample_reports(12);f,_ = v.daily_features(r)
        at = r[7,0]+v.LAG
        times = np.array([f[0,1]-1,at-1,at,f[-1,0]+v.STALE,f[-1,0]+v.STALE+1])
        picked = v.asof_features(times,f)
        self.assertTrue(np.isnan(picked[0]).all())
        self.assertEqual(picked[1,0],r[6,0]);self.assertEqual(picked[2,0],r[7,0])
        self.assertEqual(picked[3,0],r[-1,0]);self.assertTrue(np.isnan(picked[4]).all())

    def test_residual_prior_only_prefix_future_perturbation_and_null_premium(self):
        r = sample_reports();f,b = v.daily_features(r)
        prefix,pb = v.daily_features(r[:210]);np.testing.assert_array_equal(prefix,f[:210]);np.testing.assert_array_equal(pb,b[:210])
        changed = r.copy();changed[210:,1:] *= 2
        actual,ab = v.daily_features(changed)
        np.testing.assert_array_equal(actual[:210],f[:210]);np.testing.assert_array_equal(ab[:210],b[:210])
        finite = np.isfinite(f[:,5]);self.assertTrue(finite.any())
        self.assertTrue(np.all(f[finite,7]==126));self.assertTrue(np.all(f[finite,8]<f[finite,0]))
        missing = r.copy();missing[180,4] = np.nan
        actual,_ = v.daily_features(missing)
        self.assertTrue(np.isnan(actual[180:182,5]).all());self.assertTrue(np.isnan(actual[180:186,6]).all())
        self.assertTrue(np.isfinite(actual[186,6]))

    def test_scheduled_directions_metadata_latency_and_deadband(self):
        at = stamp(2022,1,3);times = at+np.array([8,10,14])*3600
        opp = dict(known=times,close=np.ones(3)*1800,unit=np.ones(3)*3,atr=np.ones(3)*2,index=np.arange(3))
        picked = np.ones((3,9));picked[:,0] = at-4*86400;picked[:,1] = at-86400
        picked[:,3] = .001;picked[:,4] = -.002;picked[:,6] = -.003
        raw = v.candidates(opp,picked,start=at,end=at+86400)
        self.assertEqual(len(raw),8)
        for family,buy in ((40,1),(41,0),(42,0),(43,0)):
            rows = raw[raw[:,36]==family]
            np.testing.assert_array_equal(rows[:,37],times[[0,2]])
            np.testing.assert_array_equal(rows[:,1],rows[:,37]+60)
            self.assertTrue(np.all(rows[:,2]==buy));self.assertTrue(np.all(rows[:,12]==picked[0,1]))
            self.assertEqual(rows[0,13]+6*3600,rows[1,13])
        picked[:,3:7] = v.DEADBAND/2
        self.assertEqual(len(v.candidates(opp,picked,start=at,end=at+86400)),0)
        picked[:,3] = v.DEADBAND
        self.assertEqual(len(v.candidates(opp,picked,start=at,end=at+86400)),4)


if __name__=='__main__':
    unittest.main()
