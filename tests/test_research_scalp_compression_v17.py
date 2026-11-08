"""Frozen range lifetime and first observable release/failure events."""
import sys
import unittest
from pathlib import Path

import numpy as np

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
import research_scalp_compression_v17 as v
from test_research_scalp_seasonal_v10 import stamp


def episode():
    n = 62;at = stamp(2022,1,3)+2*3600-300
    gold = np.c_[at+np.arange(n)*300,np.ones(n)*100,np.ones(n)*105,np.ones(n)*95,np.ones(n)*100]
    gold[43:49,2] = 101;gold[43:49,3] = 99
    gold[49,1:] = [100,105,98,103]
    gold[50,1:] = [103,104,99,100]
    return gold


class CompressionChecks(unittest.TestCase):
    def test_frozen_box_first_release_and_later_failure(self):
        g = episode();events = v.events(g,start=0,end=g[-1,0]+301)
        for family,buy,index in ((44,1,49),(45,0,50),(46,1,49)):
            rows = events[events[:,1]==family]
            self.assertEqual(len(rows),1);self.assertEqual(rows[0,2],buy);self.assertEqual(rows[0,9],index)
            self.assertEqual(rows[0,3],g[48,0]+300);self.assertEqual(rows[0,4],99);self.assertEqual(rows[0,5],101)
            self.assertAlmostEqual(rows[0,7],.2)
        raw = v.candidates(g,events)
        np.testing.assert_array_equal(raw[:,1],raw[:,37]+60)
        self.assertTrue(np.all(raw[:,12]<=raw[:,13]));self.assertTrue(np.all(raw[:,36]>=44))

    def test_prefix_future_perturbation_and_no_gap_bridge(self):
        g = episode();cut = g[50,0]+300;full = v.events(g,start=0,end=g[-1,0]+301)
        prefix = v.events(g[g[:,0]+300<=cut],start=0,end=cut+1)
        np.testing.assert_array_equal(prefix,full[full[:,0]<=cut])
        changed = g.copy();changed[51:,1:] *= 2
        actual = v.events(changed,start=0,end=g[-1,0]+301)
        np.testing.assert_array_equal(actual[actual[:,0]<=cut],prefix)
        gap = np.delete(g,49,axis=0)
        self.assertEqual(len(v.events(gap,start=0,end=g[-1,0]+301)),0)

    def test_first_weak_break_is_consumed_but_failure_remains_observable(self):
        g = episode();g[49,1:] = [103,105,102,103]
        events = v.events(g,start=0,end=g[-1,0]+301)
        self.assertEqual(len(events[events[:,1]==44]),0);self.assertEqual(len(events[events[:,1]==46]),0)
        self.assertEqual(len(events[events[:,1]==45]),1)
        g[50,1:] = [104,110,100,108]
        events = v.events(g,start=0,end=g[-1,0]+301)
        self.assertEqual(len(events[events[:,1]==44]),0)
        self.assertEqual(len(events[events[:,1]==46]),0)

    def test_control_compression_ablation_and_expired_failure(self):
        g = episode();g[:43,2] = 101;g[:43,3] = 99
        events = v.events(g,start=0,end=g[-1,0]+301)
        self.assertEqual(len(events[events[:,1]==44]),0);self.assertEqual(len(events[events[:,1]==45]),0)
        self.assertEqual(len(events[events[:,1]==46]),1)
        g = episode();g[50:54,1:] = [103,105,102,103]
        g[54,1:] = [103,104,99,100]
        events = v.events(g,start=0,end=g[-1,0]+301)
        self.assertEqual(len(events[events[:,1]==45]),0)


if __name__=='__main__':
    unittest.main()
