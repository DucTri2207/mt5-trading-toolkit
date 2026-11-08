"""H4 directional choice uses only closed context and never forces a weekly entry."""
import sys
import unittest
from pathlib import Path

import numpy as np

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
import research_scalp_direction_v19 as v


def inputs():
    known = np.arange(1,5)*1800+1641196800+8*3600
    opp = dict(known=known,close=np.ones(4)*100.,unit=np.ones(4)*3.,atr=np.ones(4)*2.,index=np.arange(4))
    s4 = np.zeros((3,14));s4[:,:2] = [[known[0]-300,1],[known[2]-300,-1],[known[3]-300,0]]
    sd = np.zeros((1,14));sd[0,:2] = [known[0]-86400,1]
    return opp,s4,sd


class DirectionChecks(unittest.TestCase):
    def test_direction_and_alignment_gate_without_h1_trigger(self):
        opp,s4,sd = inputs();raw = v.candidates(opp,s4,sd,start=0,end=2e9)
        np.testing.assert_array_equal(raw[:,36],[50,51,50,51,50])
        np.testing.assert_array_equal(raw[:,2],[1,1,1,1,0])
        np.testing.assert_array_equal(raw[:,1],raw[:,37]+60)
        self.assertTrue(np.all(raw[:,39]<=raw[:,0]));self.assertTrue(np.all(raw[:,12]<=raw[:,0]))

    def test_asof_bar_open_neutral_stale_and_period_bounds(self):
        opp,s4,sd = inputs();s4[0,0] += 1
        raw = v.candidates(opp,s4,sd,start=0,end=2e9)
        self.assertEqual(raw[0,37],opp['known'][1])
        raw = v.candidates(opp,s4,sd,start=opp['known'][1],end=opp['known'][2])
        self.assertEqual(len(raw),2);self.assertTrue(np.all(raw[:,37]==opp['known'][1]))
        old = s4[:1].copy();old[0,0] = opp['known'][0]-300-28801
        self.assertEqual(len(v.candidates(opp,old,sd,start=0,end=2e9)),0)
        sd[0,0] = opp['known'][0]-300-345601
        raw = v.candidates(opp,s4,sd,start=0,end=2e9);self.assertTrue(np.all(raw[:,36]==50))

    def test_prefix_future_states_cannot_change_past_candidates(self):
        opp,s4,sd = inputs();raw = v.candidates(opp,s4,sd,start=0,end=2e9);cut = opp['known'][2]
        short = {k:a[:2] for k,a in opp.items()}
        prefix = v.candidates(short,s4[:1],sd,start=0,end=cut)
        np.testing.assert_array_equal(prefix,raw[raw[:,37]<cut])
        s4[1:,1] = 1;changed = v.candidates(opp,s4,sd,start=0,end=2e9)
        np.testing.assert_array_equal(changed[changed[:,37]<cut],prefix)


if __name__=='__main__':
    unittest.main()
