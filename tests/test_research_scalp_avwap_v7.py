"""Anchor availability, M1 volume prefixes and first AVWAP retest causality."""
import sys
import unittest
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'scripts'))
import research_scalp_avwap_v7 as v
from test_research_scalp_weekly_v3 import new_candidate
from test_can_ho_tro_scalp import AT


def fixture():
    times = np.arange(10*60)*60
    close = 100+.005*(np.arange(len(times))-420)
    m1 = np.column_stack([times, close, close+.04, close-.04, close])
    m1[480:485, 1:] = [[100.18,100.20,100.08,100.14], [100.14,100.22,100.1,100.18],
                       [100.18,100.26,100.15,100.24], [100.24,100.30,100.22,100.27],
                       [100.27,100.30,100.20,100.28]]
    m5 = np.array([[m1[i,0],m1[i,1],np.max(m1[i:i+5,2]),np.min(m1[i:i+5,3]),m1[i+4,4]]
                   for i in range(0,len(m1),5)])
    h1 = np.array([[-60*3600+i*3600,50+i,51+i,49+i,50+i] for i in range(71)],float)
    anchors = np.array([[7*3600,7*3600+2700,99.9,1]],float)
    return m1,np.ones(len(m1)),m5,h1,anchors


def detect(parts,family=17):
    return v.detect_retest(*parts,family,0,10**9)


class AvwapChecks(unittest.TestCase):
    def setUp(self):
        v.w.FAMILIES.update(v.NAMES)

    def test_tick_weighted_mean_equal_weight_control_and_closed_boundary(self):
        bars = np.array([[i*60,p,p,p,p] for i,p in enumerate((100,104,900))],float)
        volume = np.array([1.,3.,100000.])
        for equal,expected in ((False,103.),(True,102.)):
            prefix = v.price_prefix(bars,volume,equal)
            mean,complete = v.anchored_mean(0,120,bars,*prefix)
            self.assertTrue(complete);self.assertEqual(mean,expected)
            # The minute starting at120 is not closed/usable at120.
            self.assertNotEqual(mean,900.)

    def test_missing_minute_zero_volume_and_missing_anchor_are_not_imputed(self):
        bars = np.array([[i*60,100,101,99,100] for i in range(10)],float)
        volume = np.ones(10)
        for left,at in ((1,600),(0,601)):
            self.assertFalse(v.anchored_mean(left,at,bars,*v.price_prefix(bars,volume))[1])
        sparse = np.delete(bars,5,axis=0)
        self.assertFalse(v.anchored_mean(0,600,sparse,*v.price_prefix(sparse,np.ones(9)))[1])
        volume[5] = 0
        for equal in (False,True):
            self.assertFalse(v.anchored_mean(0,600,bars,*v.price_prefix(bars,volume,equal))[1])
        # A gap immediately before the anchor does not spoil its subsequent complete window.
        self.assertTrue(v.anchored_mean(360,600,sparse,*v.price_prefix(sparse,np.ones(9)))[1])

    def test_both_directions_wait_for_anchor_confirmation(self):
        for buy in (True,False):
            parts = fixture()
            if not buy:
                for bars in (parts[0],parts[2],parts[3]):
                    old = bars[:,1:].copy();bars[:,1:] = 200-old[:,[0,2,1,3]]
                parts[4][:,2] = 100.1;parts[4][:,3] = 0
            rows = detect(parts)
            self.assertEqual(len(rows),1)
            c = rows[0]
            self.assertEqual(bool(c[2]),buy)
            self.assertEqual(c[0],8*3600)
            self.assertEqual(c[12],8*3600)
            self.assertEqual(c[17],7*3600+2700)
            self.assertLessEqual(c[17],c[13])
            parts[4][:,1] = 8*3600+300
            self.assertEqual(len(detect(parts)),0)

    def test_future_m1_price_and_volume_never_change_prebar_reference(self):
        parts = fixture();before = detect(parts)
        future = parts[0][:,0] >= 8*3600
        parts[0][future,1:] = [500,1000,100,900];parts[1][future] = 100000
        after = detect(parts)
        np.testing.assert_array_equal(before,after[after[:,1]<=before[-1,1]])

    def test_frozen_reference_and_atr_survive_delayed_confirmation(self):
        parts = fixture()
        parts[2][96,1:] = [100.22,100.23,100.10,100.13]
        parts[2][97,1:] = [100.13,100.32,100.12,100.29]
        rows = detect(parts)
        self.assertEqual(len(rows),1)
        c = rows[0]
        expected,_ = v.anchored_mean(7*3600,8*3600,parts[0],*v.price_prefix(parts[0],parts[1]))
        self.assertEqual(c[0],8*3600+300)
        self.assertEqual(c[13],8*3600)
        self.assertAlmostEqual(c[10],expected)
        self.assertAlmostEqual(c[18],v.metaquotes_atr(parts[2])[95])
        self.assertAlmostEqual(c[19],100.10-.25*c[18])
        current,_ = v.anchored_mean(7*3600,8*3600+300,parts[0],*v.price_prefix(parts[0],parts[1]))
        self.assertNotEqual(c[10],current)

    def test_first_outside_hour_touch_consumed_even_if_later_retest_qualifies(self):
        parts = fixture()
        for bars in (parts[0],parts[2],parts[3]):
            bars[:,0] -= 300
        parts[4][:,:2] -= 300
        index = int(np.flatnonzero(parts[2][:,0] == 8*3600+300)[0])
        parts[2][index,1:] = [100.18,100.36,100.10,100.33]
        self.assertEqual(len(detect(parts)),0)
        parts[2][96,1:] = [100.3,100.4,100.29,100.35]
        self.assertEqual(len(detect(parts)),1)

    def test_equal_weight_candidates_do_not_depend_on_positive_volume_scale(self):
        parts = fixture();before = detect(parts,19)
        parts[1][430:460] = np.arange(30)+100
        np.testing.assert_array_equal(before,detect(parts,19))

    def test_forming_h1_cannot_change_earlier_candidate(self):
        parts = fixture();before = detect(parts)
        parts[3][parts[3][:,0]>=8*3600,1:] = [50,1000,10,20]
        after = detect(parts)
        np.testing.assert_array_equal(before,after[after[:,1]<=before[-1,1]])

    def test_day_anchors_have_first_quote_close_availability(self):
        bars = np.array([[t,100,101,99,100] for t in (3600,3660,86460,86520)],float)
        anchors = v.day_anchors(bars)
        np.testing.assert_array_equal(anchors[:,0],[3600,3600,86460,86460])
        np.testing.assert_array_equal(anchors[:,1],[3660,3660,86520,86520])
        np.testing.assert_array_equal(anchors[:,3],[0,1,0,1])

    def test_fee_metadata_is_explicit_and_money_engine_is_unchanged(self):
        cost = dict(spread=.3,slip=.01,commission_price=.07)
        c = new_candidate(family=17)
        market = np.array([[AT,100,104,99.9,103]],float)
        actual = v.simulate(0,c,market,cost);original = v.w.simulate(0,c,market,.8,cost)
        for key in ('entry','initial_sl','risk','r','gross_r','commission_r','exit_time','reason'):
            self.assertEqual(actual[key],original[key],key)
        self.assertAlmostEqual(actual['commission'],7.)
        self.assertIn('ASSUMED_ROUND_TRIP_COMMISSION',actual['fees_status'])
        rejected = v.simulate(0,c,np.array([[AT+7200,100,104,99.9,103]],float),cost)
        self.assertEqual(rejected['entry_time'],0)
        self.assertEqual(rejected['commission'],0.)


if __name__=='__main__':
    unittest.main()
