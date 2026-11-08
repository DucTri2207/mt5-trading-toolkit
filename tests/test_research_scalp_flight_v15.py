"""Equity shock returns, missing data and chronological crossing state."""
import sys
import unittest
from pathlib import Path

import numpy as np

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
import research_scalp_flight_v15 as v
from test_research_scalp_seasonal_v10 import stamp


class FlightChecks(unittest.TestCase):
    def test_exact_returns_prefix_future_perturbation_and_missing_quote(self):
        i=np.arange(1000);at=stamp(2022,1,3);c=100+.01*i+.1*np.sin(i)
        gold=np.c_[at+i*300,c,c+.5,c-.5,c]
        e=5000*np.exp(-.0003*i+.001*np.sin(i));equity=np.c_[at+i*300,e,e+1,e-1,e]
        full=v.features(gold,equity);cut=gold[700,0];keep=gold[:,0]+300<=cut
        prefix=v.features(gold[keep],equity[equity[:,0]+300<=cut]);np.testing.assert_array_equal(prefix,full[keep])
        changed=equity.copy();changed[changed[:,0]+300>cut,1:]*=2
        actual=v.features(gold,changed);np.testing.assert_array_equal(actual[keep],full[keep])
        self.assertAlmostEqual(full[500,1],e[500]/e[499]-1)
        self.assertAlmostEqual(full[500,2],e[500]/e[452]-1)
        missing=np.delete(equity,500,axis=0);actual=v.features(gold,missing)
        self.assertTrue(np.isnan(actual[500,1:3]).all());self.assertTrue(np.isnan(actual[501,1]))
        self.assertTrue(np.isnan(actual[510,2]));self.assertTrue(np.isfinite(actual[549,2]))

    def test_tail_crossing_consumption_rearm_gap_buy_and_latency(self):
        at=stamp(2022,1,3)+3*3600;times=at+np.array([0,300,600,900,1500])
        f=np.c_[times,[-.008,-.009,0,-.008,-.008],[-.02,-.02,0,-.02,-.02],np.ones(5),np.ones(5)*100,np.arange(5)]
        raw=v.candidates(f,start=at,end=times[-1]+1)
        for family in v.NAMES:
            rows=raw[raw[:,36]==family];np.testing.assert_array_equal(rows[:,37],times[[0,3,4]])
            self.assertTrue(np.all(rows[:,2]==1));np.testing.assert_array_equal(rows[:,1],rows[:,37]+60)
            np.testing.assert_array_equal(rows[:,19],np.ones(3)*98)
        # Crossing outside hours is consumed,not resurrected at entry-window open.
        times=stamp(2022,1,3)+np.array([1*3600+55*60,2*3600]);f=f[:2].copy();f[:,0]=times
        self.assertEqual(len(v.candidates(f,start=times[0],end=times[-1]+1)),0)


if __name__=='__main__':unittest.main()
