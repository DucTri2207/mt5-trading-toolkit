import sys
import unittest
from datetime import datetime, timezone, date
from pathlib import Path
from zoneinfo import ZoneInfo

import numpy as np

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from prepare_us100_cached_data import broker_to_utc
from backtest_us100_cached import block_interval
import us100_ny_core as c


class CachedDataChecks(unittest.TestCase):
    def test_eu_clock_including_us_eu_mismatch_weeks(self):
        dates=['2024-01-08','2024-03-22','2024-03-26','2024-04-01',
               '2024-10-25','2024-10-28','2026-03-27','2026-03-30',
               '2026-10-23','2026-10-26']
        utc=np.array([datetime.fromisoformat(d).replace(hour=15,tzinfo=timezone.utc).timestamp() for d in dates])
        server=np.array([t+datetime.fromtimestamp(t,timezone.utc).astimezone(ZoneInfo('Europe/Helsinki')).utcoffset().total_seconds() for t in utc])
        np.testing.assert_array_equal(broker_to_utc(server),utc)
        self.assertEqual(server[1]-utc[1],7200)
        self.assertEqual(server[-2]-utc[-2],10800)

    def test_transition_ambiguous_time_rejected(self):
        t=datetime(2024,10,27,3,30,tzinfo=timezone.utc).timestamp()
        with self.assertRaises(AssertionError):broker_to_utc(np.array([t]))

    def test_simulator_uses_requested_native_price_tick(self):
        day=date(2026,1,6);start,end=c.session_bounds(day)
        ts=np.arange(start,end+60,60)
        bid=np.column_stack((ts,np.full((len(ts),4),20000.)))
        signal=c.Signal(start,1,20,19980.003)
        trade=c.simulate_day(day,[signal],bid,bid.copy(),c.COSTS[1],tick=.01)[0]
        plan=c.make_plan(signal,20000,20000,c.COSTS[1],tick=.01)
        self.assertEqual(trade['stop'],plan['stop'])
        self.assertEqual(trade['target'],plan['target'])
        self.assertAlmostEqual(trade['stop'],19978.)

    def test_weekly_bootstrap_preserves_constant_trade_mean_and_gate(self):
        days=[date(2026,1,5),date(2026,1,12),date(2026,1,19)]
        trades=[dict(date=days[0].isoformat(),r_net=.5),dict(date=days[1].isoformat(),r_net=.5)]
        result=block_interval(trades,days,reps=1000)
        np.testing.assert_allclose(result['mean_R_95pct'],[.5,.5])
        self.assertEqual(result['weeks'],3)
        self.assertFalse(result['sample_gate_met'])


if __name__=='__main__':unittest.main(verbosity=2)
