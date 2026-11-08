"""Behavioral fixtures with hand-calculated prices and original-source edge cases."""
import sys
import json
import unittest
from pathlib import Path

import numpy as np

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from can_ho_tro_scalp_plan import Plan, planned_gate, room_ok, pivots, idea_key
from can_ho_tro_scalp_core import source_zones, raw_at
from replay_can_ho_tro_scalp import choose_candidates, replay, simulate, replay_pending_minute

AT=8*3600+300


def candidate(buy=True):
    c=np.zeros(36);c[0]=AT-300;c[1]=AT;c[2]=buy;c[3]=3600;c[4]=1;c[7]=1;c[8]=80
    c[10]=98 if buy else 102;c[11]=100;c[12]=4000;c[13]=AT-1800
    c[18]=1;c[19]=98 if buy else 102;c[20]=98.25 if buy else 101.75
    c[21]=100;c[22]=99 if buy else 101;c[29]=110 if buy else 90;c[30]=c[29]
    return c


def filled(buy=True,policy='T05',spread=0,tick=.01):
    p=Plan(candidate(buy),policy,spread,tick=tick)
    p.start(AT,100,100+spread)
    return p


def fallback_fixture():
    m5=np.array([[28800-39*300+i*300,100.2,100.5,100.1,100.2] for i in range(41)],float)
    m5[32,1:]=[100.1,100.4,99.,100.2]
    for i,high,close,op in [(33,100.5,100.3,100.2),(34,101.,100.5,100.3),
                           (35,102.,101.,100.5),(36,103.,102.,101.),
                           (37,104.,102.,101.8),(38,105.,102.5,102.),(39,106.,103.5,102.5)]:
        m5[i,1:]=[op,high,100.1,close]
    m5[40,1:]=104.
    h1=np.array([[i*3600,100,102,99,101] for i in range(12)],float)
    z=np.zeros((1,16));z[0,[0,1,4,5,6,11,13,14]]=[1,1,98,100,80,3600,5000,1]
    return m5,h1,z


def detect_fixture(m5,h1,z,closed=True):
    return raw_at(m5,np.ones(len(m5)),39,z,h1,np.ones(len(h1)),np.full(len(h1),100.),8,0.,0.,0.,closed)


class ScalpFixtures(unittest.TestCase):
    def test_F01_entry_minute_stop(self):
        p=filled();p.minute_range(AT,100.1,97.9)
        self.assertEqual((p.reason,p.r),('STOP',-1.))

    def test_F02_entry_minute_target(self):
        p=filled();p.minute_range(AT,101.1,99.9)
        self.assertEqual((p.reason,p.r),('TARGET',.5))

    def test_F03_both_levels_adverse_first(self):
        p=filled();p.minute_range(AT,104.,97.)
        self.assertEqual((p.r,p.ambiguous,p.mfe),(-1.,1,0.))
        self.assertFalse(p.first_hits)

    def test_F04_sell_ask_is_exit_side(self):
        p=filled(False,spread=.2);p.quote(AT+1,98.9,99.1)
        self.assertEqual(p.state,'FILLED')
        p.quote(AT+2,101.9,102.1)
        self.assertEqual(p.reason,'STOP_GAP');self.assertAlmostEqual(p.r,-1.05)

    def test_F05_gap_not_clipped(self):
        p=filled();p.quote(AT+60,97.5,97.5)
        self.assertEqual(p.r,-1.25)

    def test_F06_old_stop_cannot_be_rescued(self):
        p=filled(policy='TS');p.quote(AT+60,97.5,97.5)
        p.propose(AT+60,100.5,AT+1,100.75,AT,102.)
        self.assertIsNone(p.proposal);self.assertEqual(p.stop,98.)

    def test_F07_rejected_stop_does_not_change_protected_anchor(self):
        for buy,proposal in [(True,97.),(False,103.)]:
            p=filled(buy,policy='TS');before=(p.protected_p,p.protected_h_time)
            p.propose(AT+1,proposal,AT+1,100.,AT,102.)
            p.quote(AT+2,100.5,100.5)
            self.assertEqual((p.protected_p,p.protected_h_time),before)
            self.assertEqual(p.events[-1]['kind'],'STOP_REJECTED')

    def test_F08_pivot_known_only_after_two_right_bars(self):
        b=np.array([[i*300,100,101+(i==2)*2,99,100] for i in range(7)],float)
        hi,_=pivots(b)
        self.assertEqual((int(hi[0,1]),int(hi[0,3])),(600,1500))
        p=filled(policy='TS');p.propose(AT,100.5,AT+1,100.75,AT,102.)
        self.assertEqual(p.stop,98.)
        p.quote(AT,101,101)
        self.assertEqual(p.stop,100.5)

    def test_F09_plateau_first_pivot(self):
        b=np.array([[i*300,100,h,99,100] for i,h in enumerate([101,102,105,105,105,103,102])],float)
        hi,_=pivots(b)
        self.assertEqual(hi[:,1].tolist(),[600.])

    def test_F10_tick_size_not_digits(self):
        c=candidate();c[19]=98.13;p=Plan(c,tick=.25)
        p.start(AT,100.25,100.25)
        self.assertEqual((p.initial_sl,p.target),(98.,101.5))

    def test_F11_R0_invariant(self):
        p=filled(policy='TS');p.propose(AT,100.5,AT+1,100.75,AT,102.)
        p.quote(AT+1,101.5,101.5);p.close(101.,AT+2,'TIME')
        self.assertEqual((p.initial_sl,p.risk,p.r),(98.,2.,.5))

    def test_F12_spread_once(self):
        p=Plan(candidate(),spread=.2);p.start(AT,99.8,100.)
        p.quote(AT+1,101.,101.2)
        self.assertAlmostEqual(p.r,.5)

    def test_F13_actual_fill_recomputes_risk(self):
        p=Plan(candidate());p.start(AT,100.4,100.4)
        self.assertAlmostEqual(p.entry,100.4);self.assertAlmostEqual(p.risk,2.4)
        self.assertAlmostEqual(p.target,101.6)

    def test_F14_quote_delay_boundary(self):
        p=Plan(candidate());p.start(AT+60,100,100);self.assertEqual(p.state,'FILLED')
        p=Plan(candidate());p.start(AT+61,100,100);self.assertEqual(p.reason,'NO_ENTRY_QUOTE')

    def test_F15_end_of_data_is_censored(self):
        a=np.array([[AT,100,100.1,99.9,100]],float);empty=np.empty((0,5));piv=np.empty((0,4))
        r=simulate(0,candidate(),a,empty,empty,np.empty(0),piv,piv,'T05',0,0)
        self.assertEqual(r['state'],'CENSORED_OPEN');self.assertIsNone(r['r'])

    def test_F16_each_policy_uses_own_exit_clock(self):
        a=np.array([[AT+i*60,100,101.1,99.9,100] for i in range(370)],float)
        c1=candidate();c2=candidate();c2[0:2]+=600;c2[13]+=300
        arr={'m1':a,'m5':np.empty((0,5)),'h1':np.empty((0,5))};pi=np.empty((0,4))
        base=[(0,c1),(1,c2)];cost={'spread':0,'slippage_ticks':0}
        t05,_=replay(base,arr,np.empty(0),pi,pi,'T05',cost)
        ts,gate=replay(base,arr,np.empty(0),pi,pi,'TS',cost)
        self.assertEqual((len(t05),len(ts),gate.get('BUSY')),(2,1,1))

    def test_F18_identity_survives_array_renumber(self):
        a=candidate();b=a.copy();b[7]=99
        self.assertEqual(idea_key(a),idea_key(b))
        b[3]+=3600;self.assertNotEqual(idea_key(a),idea_key(b))

    def test_F17_native_durable_state_roundtrip(self):
        path=Path(__file__).resolve().parents[1]/'reports/scalp_structure_lab/20261025_pilot_v1/fixture_terminal/MQL5/Files/can_ho_tro_scalp_v1/state_roundtrip.json'
        result=json.loads(path.read_text())
        self.assertTrue(result['passed']);self.assertEqual(result['stop'],100.5)
        self.assertEqual((result['initial_sl'],result['risk'],result['watermark']),(98.,2.,28800))

    def test_F19_trend_uses_confirmation_open_rule(self):
        m,h,z=fallback_fixture();m[:,0]-=300
        out=detect_fixture(m,h,z)
        self.assertEqual((int(out[0,1]),int(out[0,23])),(28800,21600))

    def test_F20_forming_bar_veto_and_C0_correction(self):
        m,h,z=fallback_fixture()
        self.assertEqual(len(detect_fixture(m,h,z,False)),0)
        corrected=detect_fixture(m,h,z,True)
        m[40,1:]=107.
        self.assertEqual(len(detect_fixture(m,h,z,False)),1)
        np.testing.assert_array_equal(corrected,detect_fixture(m,h,z,True))

    def test_F21_supply_priority_when_departure_crosses_both_sides(self):
        b=np.array([[i*3600,100,100.1,99.9,100] for i in range(40)],float)
        b[21,1:]=[100,102,98,100]
        z=source_zones(b,np.ones(len(b)),len(b))
        self.assertEqual((int(z[0,0]),int(z[0,2])),(20,1))

    def test_F22_pivot_fallback_is_retained(self):
        m,h,z=fallback_fixture();out=detect_fixture(m,h,z)
        self.assertEqual((len(out),out[0,15],out[0,16]),(1,m[36,0],103.))

    def test_F23_earlier_weak_break_vetoes_later_strong_break(self):
        m,h,z=fallback_fixture();m[37,1]=103.;m[37,4]=103.1
        self.assertEqual(len(detect_fixture(m,h,z)),0)

    def test_F24_source_retains_expired_flip_with_test_quota(self):
        b=np.array([[i*3600,101.,101.2,100.8,101.] for i in range(430)],float)
        b[:25,1:]=[100.,100.1,99.9,100.];b[21,1:]=[100.,100.1,97.,98.]
        b[26:30,1:]=[100.,100.15,99.95,100.]
        z=source_zones(b,np.ones(len(b)),len(b))
        flips=z[(z[:,0]==20)&(z[:,3]==1)]
        self.assertEqual(len(flips),1);self.assertEqual(int(flips[0,7]),4)
        self.assertLess(flips[0,12],b[-1,0]);self.assertEqual(flips[0,8],0.)

    def test_F25_level_must_be_known_before_sweep(self):
        m,h,z=fallback_fixture();z[0,13]=m[36,0]
        out=detect_fixture(m,h,z);self.assertEqual(out[0,28],5.)

    def test_F26_first_eligible_zone_not_first_raw_zone(self):
        bad=candidate();bad[27]=1;good=candidate();good[7]=2
        selected,rejected=choose_candidates(np.stack([bad,good]),.01)
        self.assertEqual(selected[0][0],1);self.assertEqual(rejected['SOURCE_1'],1)

    def test_F27_terminal_event_exactly_once(self):
        p=filled();p.quote(AT+1,101,101);p.quote(AT+2,102,102)
        self.assertEqual(sum(e['kind']=='TARGET' for e in p.events),1)

    def test_F28_prefix_does_not_change_closed_only_candidate(self):
        m,h,z=fallback_fixture()
        np.testing.assert_array_equal(detect_fixture(m,h,z),detect_fixture(m[:40],h,z))

    def test_F29_pending_expiry_before_fill(self):
        p=Plan(candidate(),retest=True);p.start(AT,100,100.2)
        p.quote(AT+900,99,99.2)
        self.assertEqual(p.state,'EXPIRED');self.assertEqual(p.entry_time,0)

    def test_F30_pending_uses_correct_quote_side(self):
        for buy,bid,ask in [(True,99.,99.2),(False,100.9,101.1)]:
            p=Plan(candidate(buy),spread=.2,retest=True);p.start(AT,100,100.2)
            p.quote(AT+1,bid,ask);self.assertEqual(p.state,'PENDING')

    def test_F31_continuous_fill_before_stop_not_gap_cancellation(self):
        c=candidate();c[19]=96.5
        for path in ['OLHC','OHLC']:
            p=Plan(c,policy='T15',spread=0,retest=True);p.start(AT,100,100)
            replay_pending_minute(p,np.array([AT,100,103,96,100],float),path)
            self.assertEqual(p.state,'CLOSED');self.assertAlmostEqual(p.r,-1.)
            self.assertEqual(p.ambiguous,1)

    def test_F32_marketable_limit_rejected(self):
        c=candidate();c[22]=101;p=Plan(c,retest=True);p.start(AT,100,100.2)
        self.assertEqual(p.reason,'LIMIT_NOT_PASSIVE')

    def test_F33_cancellation_before_fill_at_gap_quote(self):
        p=Plan(candidate(),retest=True);p.start(AT,100,100.2);p.quote(AT+60,98,98.2)
        self.assertEqual(p.state,'CANCELLED');self.assertEqual(p.entry_time,0)

    def test_F34_unknown_room_not_fabricated(self):
        self.assertEqual(room_ok(100,98,0,1,True,.01)[:2],(False,'ROOM_UNKNOWN'))
        self.assertFalse(room_ok(100,98,100,1,True,.01)[0])

    def test_F35_room_recomputed_at_actual_fill(self):
        c=candidate();c[21]=99.5;c[29]=103.
        self.assertEqual(planned_gate(c,room=True),'PASS')
        p=Plan(c,policy='T15',room=True);p.start(AT,100.5,100.5)
        self.assertEqual(p.reason,'REJECT_AT_FILL_ROOM')


if __name__=='__main__':unittest.main(verbosity=2)
