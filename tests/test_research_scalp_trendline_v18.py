"""Confirmed swing availability, fixed rays and higher-frame gates at touch and entry."""
import sys
import unittest
from pathlib import Path

import numpy as np

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
import research_scalp_trendline_v18 as v
from test_research_scalp_seasonal_v10 import stamp


def pullback(hour=8):
    at = stamp(2022,1,3)+hour*3600
    times = at-30*3600+np.arange(30)*3600;price = 108+(times-at)/3600
    h1 = np.c_[times,price,price+1,price-1,price]
    h1[24,3] = 100;h1[27,3] = 103
    s1 = np.zeros((30,14));s1[:,0] = times+3600
    s1[-1,1:] = [1,at-6*3600,100,at-3*3600,at-3*3600,103,at,
                  at-7*3600,115,at-4*3600,at-4*3600,118,at-3600]
    mtime = at-100*60+np.arange(36)*300;c = np.ones(36)*110
    m5 = np.c_[mtime,c,c+.5,c-.5,c];m5[20,1:] = [107,108,105.9,107.8]
    s4 = np.zeros((1,14));s4[0,:2] = [at-3600,1]
    sd = np.zeros((1,14));sd[0,:2] = [at-12*3600,1]
    return m5,h1,s1,s4,sd


def detect(parts):
    return v.events(*parts,start=0,end=parts[0][-1,0]+301)


class TrendlineChecks(unittest.TestCase):
    def test_structure_two_right_bars_up_down_and_prefix(self):
        c = np.array([100,101,102,103,105,103,102,103,104,107,105,104,105,106,109,107,106,107,108,111],float)
        times = stamp(2022,1,3)+np.arange(len(c))*3600
        bars = np.c_[times,c-.2,c+.5,c-.5,c];full = v.structure(bars,3600)
        self.assertEqual(full[12,1],0);self.assertEqual(full[13,1],1)
        self.assertEqual(full[13,5],times[11]);self.assertEqual(full[13,7],times[13]+3600)
        np.testing.assert_array_equal(v.structure(bars[:14],3600),full[:14])
        changed = bars.copy();changed[14:,1:] += 100
        np.testing.assert_array_equal(v.structure(changed,3600)[:14],full[:14])
        c = 200-c;reverse = np.c_[times,c+.2,c+.5,c-.5,c]
        self.assertEqual(v.structure(reverse,3600)[13,1],-1)

    def test_ray_touch_direction_metadata_latency_and_gates(self):
        parts = pullback();m5 = parts[0];event = detect(parts)
        self.assertEqual(len(event),1);self.assertEqual(event[0,19],20);self.assertEqual(event[0,1],1)
        self.assertEqual(event[0,10],106);self.assertAlmostEqual(event[0,11],106+1/12)
        raw = v.candidates(m5,event)
        np.testing.assert_array_equal(raw[:,36],[47,48,49]);np.testing.assert_array_equal(raw[:,1],raw[:,37]+60)
        self.assertTrue(np.all(raw[:,12]<=raw[:,0]));self.assertTrue(np.all(raw[:,39]<=raw[:,0]))
        changed = list(parts);changed[3] = changed[3].copy();changed[3][0,1] = -1
        raw = v.candidates(m5,detect(tuple(changed)));np.testing.assert_array_equal(raw[:,36],[49])
        changed = list(parts);changed[4] = changed[4].copy();changed[4][0,1] = 0
        raw = v.candidates(m5,detect(tuple(changed)));np.testing.assert_array_equal(raw[:,36],[47,49])
        mirrored = [x.copy() for x in parts]
        for bars in mirrored[:2]:
            original = bars.copy();bars[:,1] = 300-original[:,1];bars[:,4] = 300-original[:,4]
            bars[:,2] = 300-original[:,3];bars[:,3] = 300-original[:,2]
        original = mirrored[2].copy();mirrored[2][:,1] *= -1
        mirrored[2][:,2:8] = original[:,8:14];mirrored[2][:,8:14] = original[:,2:8]
        for column in (3,6,9,12):
            mirrored[2][:,column] = 300-mirrored[2][:,column]
        mirrored[3][:,1] *= -1;mirrored[4][:,1] *= -1
        short = detect(tuple(mirrored));self.assertEqual(len(short),1)
        self.assertEqual(short[0,1],0);self.assertAlmostEqual(short[0,11],300-event[0,11])

    def test_higher_frame_must_align_at_touch_and_confirmation(self):
        parts = list(pullback());parts[0][20,1:] = [107,107.1,105.9,106.1]
        parts[0][21,1:] = [106.1,108,106,107.8]
        extra = parts[3].copy();extra[0,:2] = [parts[0][21,0],-1];parts[3] = np.vstack((parts[3],extra))
        event = detect(tuple(parts));self.assertEqual(len(event),1)
        self.assertEqual(event[0,12],1);self.assertEqual(event[0,13],-1)
        np.testing.assert_array_equal(v.candidates(parts[0],event)[:,36],[49])
        self.assertEqual(v.context(extra[0,0]-1,parts[3],28800)[0],1)
        self.assertEqual(v.context(extra[0,0],parts[3],28800)[0],-1)
        self.assertEqual(v.context(extra[0,0]+28801,parts[3],28800)[0],0)

    def test_pierced_ray_and_close_break_cannot_be_resurrected(self):
        parts = list(pullback());parts[1][26,3] = 70
        self.assertEqual(len(detect(tuple(parts))),0)
        parts = list(pullback());parts[0][20,1:] = [107,108,104,104.5]
        self.assertEqual(len(detect(tuple(parts))),0)

    def test_prefix_future_perturbation_and_gap_cancel(self):
        parts = pullback();full = detect(parts);cut = parts[0][20,0]+300
        prefix = (parts[0][:21],*parts[1:]);np.testing.assert_array_equal(detect(prefix),full[full[:,0]<=cut])
        changed = list(parts);changed[0] = changed[0].copy();changed[0][21:,1:] *= 2
        actual = detect(tuple(changed));np.testing.assert_array_equal(actual[actual[:,0]<=cut],full[full[:,0]<=cut])
        parts = list(pullback());parts[0][20,1:] = [107,107.1,105.9,106.1]
        parts[0][22,1:] = [106.1,108,106,107.8];parts[0] = np.delete(parts[0],21,axis=0)
        self.assertEqual(len(detect(tuple(parts))),0)

    def test_failed_touch_and_out_of_hours_event_are_consumed(self):
        parts = list(pullback());parts[0][20,1:] = [107,107.1,105.9,106.1]
        parts[0][21:24,1:] = [106.1,106.2,106,106.1]
        self.assertEqual(len(detect(tuple(parts))),0)
        self.assertEqual(len(detect(pullback(hour=1))),0)


if __name__=='__main__':
    unittest.main()
