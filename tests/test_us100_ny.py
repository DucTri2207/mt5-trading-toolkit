import sys
import unittest
from datetime import date, datetime, timezone
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import us100_ny_core as c


def fixture():
    parts = []
    for day, direction, n in ((6, 1, 302), (7, -1, 229)):
        start = int(datetime(2026, 1, day, 11, tzinfo=timezone.utc).timestamp())  # 06:00 NY
        prior = 21000.
        rows = []
        for i in range(n):
            close = 21000.+i*.5
            if i == 220:
                close = 21000.+219*.5-2.5
            if i == 221:
                close = 21000.+219*.5-3.5
            if i == 222:
                close = 21000.+219*.5+11.5
            o = prior
            h, l = max(o, close)+10, min(o, close)-10
            if direction == -1:
                rows.append([start+i*60, 42000-o, 42000-l, 42000-h, 42000-close])
            else:
                rows.append([start+i*60, o, h, l, close])
            prior = close
        parts.append(np.array(rows))
    return np.concatenate(parts)


class CoreChecks(unittest.TestCase):
    def test_dst_and_session_boundaries(self):
        for d, hour in ((date(2026, 3, 6), 14), (date(2026, 3, 9), 13),
                        (date(2026, 10, 26), 13), (date(2026, 11, 2), 14)):
            start, end = c.session_bounds(d)
            self.assertEqual(datetime.fromtimestamp(start, timezone.utc).hour, hour)
            self.assertFalse(c.session_time(start-1)); self.assertTrue(c.session_time(start))
            self.assertFalse(c.session_time(end))

    def test_signal_prefix_invariance_and_known_at(self):
        b = fixture()
        all_signals = c.detect(b)
        self.assertEqual([s.direction for s in all_signals], [1, -1])
        for n in (200, 222, 223, 250, 500):
            self.assertEqual(c.detect(b[:n]), [s for s in all_signals if s.known_at <= b[n-1, 0]+60])
        mutated = b.copy(); mutated[-1, 1:] += 1000
        cutoff = b[-1, 0]
        self.assertEqual([s for s in c.detect(mutated) if s.known_at <= cutoff],
                         [s for s in all_signals if s.known_at <= cutoff])

    def test_features_reset_on_gap_and_utc_day(self):
        b = fixture()[:210]
        b[205:, 0] += 60
        _, _, a, w = c.features(b)
        self.assertEqual(w[205], 1); self.assertEqual(a[205], 0)
        self.assertFalse(any(s.known_at >= b[205, 0] for s in c.detect(b)))

    def test_lot_rounding_does_not_exceed_budget(self):
        self.assertAlmostEqual(c.floor_lots(250, 103, .1, .1, 100), 2.4)
        self.assertEqual(c.floor_lots(1, 103, .1, .1, 100), 0)
        self.assertEqual(c.floor_lots(250, 0, .1, .1, 100), 0)
        self.assertAlmostEqual(c.floor_lots(250, 1, .1, .1, 3.5), 3.5)

    def test_spread_stop_tick_rounding(self):
        s = c.Signal(0, 1, 20, 19980)
        p = c.make_plan(s, 20000, 20001, c.COSTS[1], tick=.25)
        self.assertEqual(p['entry'], 20002.5); self.assertEqual(p['stop'], 19978.)
        self.assertGreaterEqual(p['target'], p['entry']+1.25*p['distance'])
        self.assertIsNone(c.make_plan(s, 20000, 20004, c.COSTS[1]))
        self.assertIsNone(c.make_plan(c.Signal(0, 1, 20, 19900), 20000, 20002, c.COSTS[1]))
        short = c.make_plan(c.Signal(0, -1, 20, 20020), 20000, 20002, c.COSTS[1])
        self.assertEqual(short['stop'], 20024.)

    def data(self, n=100):
        start, end = c.session_bounds(date(2026, 1, 6))
        ts = np.arange(start, end+60, 60)
        b = np.column_stack((ts, np.full((len(ts), 4), 20000.)))
        a = b.copy(); a[:, 1:] += 2
        return start, b, a

    def test_ohlc_ambiguity_stop_first_and_two_stop_limit(self):
        start, b, a = self.data()
        signals = [c.Signal(start+i*60, 1, 20, 19980) for i in (0, 6, 12)]
        for i in (0, 6, 12):
            b[i, 2:4] = [20050, 19970]; a[i, 2:4] = [20052, 19972]
        trades = c.simulate_day(date(2026, 1, 6), signals, b, a, c.COSTS[1])
        self.assertEqual(len(trades), 2)
        self.assertTrue(all(p['ambiguous'] and p['reason'] == 'SL' for p in trades))
        np.testing.assert_allclose([p['r_net'] for p in trades], [-1, -1])

    def test_tick_stop_gap_and_no_target_gap_bonus(self):
        start, b, a = self.data()
        signals = [c.Signal(start, 1, 20, 19980)]
        q = np.array([[start+.1, 20000, 20002], [start+1., 19970, 19972], [start+100, 20000, 20002]])
        p = c.simulate_day(date(2026, 1, 6), signals, b, a, c.COSTS[1], q)[0]
        self.assertLess(p['r_net'], -1); self.assertAlmostEqual(p['exit'], 19969.5)
        q[1, 1:] = [20100, 20102]
        p = c.simulate_day(date(2026, 1, 6), signals, b, a, c.COSTS[1], q)[0]
        self.assertEqual(p['exit'], p['target'])
        self.assertLess(p['mae_r'], 0)

    def test_max_three_entries_after_wins(self):
        start, b, a = self.data()
        signals = [c.Signal(start+i*60, 1, 20, 19980) for i in (0, 6, 12, 18)]
        for i in (0, 6, 12, 18):
            b[i, 2], a[i, 2] = 20100, 20102
        trades = c.simulate_day(date(2026, 1, 6), signals, b, a, c.COSTS[1])
        self.assertEqual(len(trades), 3)
        self.assertTrue(all(p['reason'] == 'TP' for p in trades))
        self.assertEqual([p['known_at'] for p in trades], [start, start+360, start+720])

    def test_short_uses_ask_and_time_exit(self):
        start, b, a = self.data()
        signals = [c.Signal(start, -1, 20, 20020)]
        # Bid remains below the short stop, Ask crosses it.
        q = np.array([[start+.1, 20000, 20002], [start+1, 20022, 20025], [start+100, 20000, 20002]])
        p = c.simulate_day(date(2026, 1, 6), signals, b, a, c.COSTS[1], q)[0]
        self.assertEqual(p['reason'], 'SL'); self.assertEqual(p['exit'], 20025.5)
        p = c.simulate_day(date(2026, 1, 6), signals, b, a, c.COSTS[1])[0]
        self.assertEqual(p['reason'], 'TIME'); self.assertEqual(p['exit_time'], start+900)

    def test_prop_two_distinct_phases_and_minimum_days(self):
        trades = []
        for i in range(8):
            t = datetime(2026, 1, 5+i, 15, tzinfo=timezone.utc).timestamp()
            trades.append(dict(entry_time=t, exit_time=t+60, r_net=10., mae_r=-.1))
        result = c.prop_attempt(trades)
        self.assertEqual(result['status'], 'BOTH_PHASES_REACHED')
        self.assertEqual([p['trading_days'] for p in result['phases']], [4, 4])
        bad = [{**trades[0], 'mae_r': -21., 'r_net': -21.}]
        self.assertEqual(c.prop_attempt(bad)['reason'], 'daily_loss')
        self.assertEqual(c.prop_attempt(trades[:2])['status'], 'CENSORED')


if __name__ == '__main__':
    unittest.main(verbosity=2)
