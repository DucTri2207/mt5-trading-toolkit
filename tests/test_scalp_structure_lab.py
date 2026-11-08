"""Behavior tests for actual lab replay; no terminal connection or orders."""
from pathlib import Path
import sys
import unittest

import numpy as np

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
import replay_scalp_structure_lab as lab


def bars(rows):
    return np.array(rows,dtype=[('time','i8'),('open','f8'),('high','f8'),('low','f8'),('close','f8')])


def signal(buy=True):
    return dict(id='fixture',time=0,buy=buy,anchor_time=-300,
                anchor=99.25 if buy else 100.75,atr=1.0,trigger=100.0,
                opposing=110.0 if buy else 90.0)


class ReplayTests(unittest.TestCase):
    def run_trade(self,s,rows,updates=None,policy='E0_FIXED_1_5R',spread=0.0):
        data=bars(rows);updates=updates or []
        return lab.simulate_trade(s,data,data['time'],updates,
                                 np.array([x['time'] for x in updates]),spread,.01,policy)

    def test_stop_in_first_entry_minute(self):
        r=self.run_trade(signal(),[(0,100,100.1,98.9,99.5),(60,100,100.2,99.9,100)])
        self.assertEqual(r['status'],'STOP');self.assertAlmostEqual(r['r'],-1)

    def test_target_in_first_entry_minute(self):
        r=self.run_trade(signal(),[(0,100,102,99.9,101.5)])
        self.assertEqual(r['status'],'TARGET');self.assertAlmostEqual(r['r'],1.5)
        self.assertLessEqual(r['mfe_r'],1.5)
        self.assertNotIn('2.0',r['first_hits'])

    def test_sell_uses_ask_not_bid_for_stop(self):
        r=self.run_trade(signal(False),[(0,100,100.9,99.9,100.1)],spread=.2)
        self.assertEqual(r['status'],'STOP')

    def test_both_levels_adverse_first(self):
        r=self.run_trade(signal(),[(0,100,102,98,100)])
        self.assertAlmostEqual(r['r'],-1);self.assertEqual(r['ambiguous_bars'],1)

    def test_stop_gap_is_not_clamped(self):
        r=self.run_trade(signal(),[(0,100,100.2,99.8,100),(60,98,98.4,97.5,98)])
        self.assertEqual(r['status'],'STOP_GAP');self.assertAlmostEqual(r['r'],-2)

    def test_r0_unchanged_after_trail(self):
        updates=[dict(time=60,buy=True,anchor_time=1,stop=100.5)]
        r=self.run_trade(signal(),[(0,100,101,99.5,100.8),(60,101,101.2,100.4,100.6)],updates,'E1_STRUCTURE_TRAIL')
        self.assertAlmostEqual(r['r'],.5);self.assertAlmostEqual(r['initial_stop'],99)

    def test_old_stop_gap_precedes_new_stop(self):
        updates=[dict(time=60,buy=True,anchor_time=1,stop=100.5)]
        r=self.run_trade(signal(),[(0,100,101,99.5,100.8),(60,98,102,97,101)],updates,'E1_STRUCTURE_TRAIL')
        self.assertEqual(r['status'],'STOP_GAP');self.assertEqual(r['stop_events'],[])

    def test_trail_never_loosens(self):
        updates=[dict(time=60,buy=True,anchor_time=1,stop=100.5),dict(time=120,buy=True,anchor_time=2,stop=99.5)]
        r=self.run_trade(signal(),[(0,100,101,99.5,100.8),(60,101,102,100.8,101.5),(120,101,101.2,100.4,100.6)],updates,'E1_STRUCTURE_TRAIL')
        self.assertAlmostEqual(r['stop'],100.5);self.assertEqual(len(r['stop_events']),1)

    def test_future_trail_cannot_affect_entry_bar(self):
        updates=[dict(time=60,buy=True,anchor_time=1,stop=100.5)]
        r=self.run_trade(signal(),[(0,100,101,98.9,99)],updates,'E1_STRUCTURE_TRAIL')
        self.assertAlmostEqual(r['r'],-1)

    def test_quote_delay_rejected(self):
        r=self.run_trade(signal(),[(120,100,102,99.5,101)])
        self.assertEqual(r['status'],'NO_ENTRY_QUOTE')

    def test_missing_data_not_breakeven(self):
        r=self.run_trade(signal(),[(0,100,100.3,99.8,100.1)])
        self.assertEqual(r['status'],'UNRESOLVED');self.assertNotIn('r',r)

    def test_stop_must_be_placeable_outside_current_exit_quote(self):
        s=signal();s['initial_stop']=100.1
        r=self.run_trade(s,[(0,100,101,99,100)],spread=.2)
        self.assertEqual(r['status'],'REJECT_STOP')

    def test_room_uses_fill_not_signal_close(self):
        s=signal();s['opposing']=101.5
        r=self.run_trade(s,[(0,100.2,102,99.9,101)])
        self.assertEqual(r['status'],'REJECT_ROOM')

    def test_target_is_reachable_on_tick_grid(self):
        s=signal();s['initial_stop']=99.97
        r=self.run_trade(s,[(0,100,100.06,99.99,100.05)])
        self.assertAlmostEqual(r['exit_price'],100.05)
        self.assertGreaterEqual(r['r'],1.5)

    def test_first_passage_tolerates_float_rounding(self):
        s=signal();s['initial_stop']=99.93
        data=bars([(0,100,100.14,99.99,100.13)])
        r=lab.simulate_trade(s,data,data['time'],[],np.array([]),0,.01,'E0_FIXED_1_5R',target_r=2.0)
        self.assertIn('2.0',r['first_hits'])

    def test_dd_includes_initial_zero(self):
        self.assertEqual(lab.metrics([{'r':-1},{'r':.5}])['dd'],1)

    def test_swing_available_only_after_right_bars(self):
        d=lab.Detector()
        data=bars([(i*300,100,h,99,100) for i,h in enumerate([101,102,105,103,102])])
        for b in data[:4]:d.step(b)
        self.assertEqual(len(d.highs),0)
        d.step(data[4]);self.assertEqual(d.highs[0].known,1500)

    def test_prefix_determinism_on_real_sample(self):
        cache=np.load(lab.RUN/'rates.npz')['m5']
        out=[]
        for length in (3000,5000):
            d=lab.Detector();events=[]
            for b in cache[:length]:
                c,u=d.step(b)
                events.extend(c+u)
            out.append([x for x in events if x['time']<=int(cache[2999]['time'])+300])
        self.assertEqual(out[0],out[1])

    def test_broken_anchor_invalidates_buy_before_trigger(self):
        d=lab.Detector();d.atr=1
        d.bars=[(i*300,100,103,99,102) for i in range(14)]
        d.highs=[lab.Pivot(1,300,105,1200),lab.Pivot(8,2400,110,3300)]
        d.lows=[lab.Pivot(3,900,95,1800),lab.Pivot(11,3300,98,4200)]
        found,_=d.step(bars([(4200,100,106,97,105)])[0])
        self.assertEqual(found,[])

    def test_serial_reselection_uses_actual_exit_time(self):
        s1=signal();s1['id']='first';s2=signal();s2.update(id='second',time=60)
        data=bars([(0,100,102,99.5,101),(60,100,102,99.5,101)])
        summary,trades=lab.serial_replay([s1,s2],data,[],0,.01,'E0_FIXED_1_5R')
        self.assertEqual([x['id'] for x in trades],['first','second'])


if __name__=='__main__':unittest.main(verbosity=2)
