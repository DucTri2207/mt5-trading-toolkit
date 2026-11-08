"""A failed reclaim creates a later causal trade, with no outcome-label inputs."""
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import research_scalp_failed_reclaim_v6 as f
from test_research_scalp_early_mean_v5 import fixture
from test_research_scalp_weekly_v3 import new_candidate
from test_can_ho_tro_scalp import AT


def failed_fixture():
    arrays = fixture()
    arrays['m1'][63, 1:] = [99.6, 99.7, 99.3, 99.4]
    arrays['m1'][64, 1:] = [99.4, 99.45, 99, 99.1]
    return arrays


def detect(arrays, family=16):
    return f.detect(arrays, family, start=0, stop=10**9)


class FailedReclaimChecks(unittest.TestCase):
    def setUp(self):
        f.w.FAMILIES.update(f.NAMES)
        f.w.FAMILIES.update(f.early.NAMES)

    def test_both_sides_require_later_closed_failure_and_use_known_anchor(self):
        for buy in (False, True):
            arrays = failed_fixture()
            if buy:
                for bars in arrays.values():
                    old = bars[:, 1:].copy()
                    bars[:, 1:] = 200-old[:, [0, 2, 1, 3]]
            rows = detect(arrays)
            self.assertEqual(len(rows), 1)
            c = rows[0]
            self.assertEqual(bool(c[2]), buy)
            self.assertEqual(c[0], 8*3600+240)
            self.assertEqual(c[1], 8*3600+300)
            self.assertEqual(c[12], 8*3600+180)
            self.assertLessEqual(c[12], c[13])
            self.assertAlmostEqual(c[10], 100.8 if buy else 99.2)
            self.assertAlmostEqual(c[19], 100.25 if buy else 99.75)

    def test_wick_beyond_extreme_without_failure_close_is_not_signal(self):
        arrays = failed_fixture()
        arrays['m1'][64, 1:] = [99.4, 99.45, 99, 99.4]
        self.assertEqual(len(detect(arrays)), 0)

    def test_original_reclaim_need_not_be_a_filled_trade(self):
        arrays = failed_fixture()
        events = f.early.detect(arrays, 13, start=0, stop=10**9)
        self.assertEqual(len(events), 1)
        cost = dict(spread=.3, slip=.01, commission_price=.07)
        original = f.early.prior.simulate(0, events[0], arrays['m1'], cost)
        self.assertEqual(original['reason'], 'MEAN_ROOM_BELOW_08R')
        self.assertEqual(original['entry_time'], 0)
        self.assertEqual(len(detect(arrays)), 1)

    def test_mean_touch_before_or_with_failure_cancels_event(self):
        for index in (63, 64):
            arrays = failed_fixture()
            arrays['m1'][index, 2] = 100
            self.assertEqual(len(detect(arrays)), 0)

    def test_missing_m1_bar_cancels_event(self):
        arrays = failed_fixture()
        arrays['m1'] = np.delete(arrays['m1'], 63, axis=0)
        self.assertEqual(len(detect(arrays)), 0)

    def test_fifteen_bar_expiry_has_no_late_reactivation(self):
        for failure_bar, expected in ((77, 1), (78, 0)):
            arrays = failed_fixture()
            arrays['m1'][63:79, 1:] = [99.5, 99.7, 99.3, 99.4]
            arrays['m1'][failure_bar, 1:] = [99.4, 99.45, 99, 99.1]
            self.assertEqual(len(detect(arrays)), expected)

    def test_future_m1_extremes_never_change_an_earlier_stop(self):
        arrays = failed_fixture()
        before = detect(arrays)
        arrays['m1'][65:, 1:] = [100, 1000, 20, 900]
        after = detect(arrays)
        np.testing.assert_array_equal(before, after[after[:, 1] <= before[-1, 1]])

    def test_trend_filter_and_h1_metadata_ignore_forming_h1(self):
        arrays = failed_fixture()
        close = 130-.2*np.arange(len(arrays['h1']))
        arrays['h1'][:, 1:] = np.column_stack([close, close+1, close-1, close])
        before = detect(arrays, 15)
        self.assertEqual(len(before), 1)
        arrays['h1'][arrays['h1'][:, 0] >= 8*3600, 1:] = [100, 1000, 20, 900]
        after = detect(arrays, 15)
        np.testing.assert_array_equal(before, after[after[:, 1] <= before[-1, 1]])
        flat = arrays['h1'].copy(); flat[:, 1:] = [100, 101, 99, 100]
        arrays['h1'] = flat
        self.assertEqual(len(detect(arrays, 15)), 0)

    def test_serial_caps_count_only_fills_and_respect_position_occupancy(self):
        raw = np.array([new_candidate(family=16) for _ in range(5)])
        raw[:, 1] = AT+np.arange(5)*300
        raw[:, 13] = raw[:, 1]-600
        def fake(index, c, *args):
            if index == 0:
                return dict(entry_time=0, exit_time=0, state='REJECTED')
            return dict(entry_time=int(c[1]), exit_time=int(c[1])+599, state='CLOSED')
        with patch.object(f.w, 'simulate', side_effect=fake):
            trades, rejects = f.run_serial(raw, np.empty((0, 5)), dict(sources=[16]), {})
        self.assertEqual(sum(bool(t['entry_time']) for t in trades), 2)
        self.assertEqual(rejects['BUSY'], 2)
        # A later fifth eligible event on this day must be blocked by the daily cap.
        extra = raw[-1].copy(); extra[1] = AT+1800; extra[13] = extra[1]-600
        with patch.object(f.w, 'simulate', side_effect=fake):
            _, rejects = f.run_serial(np.vstack([raw, extra]), np.empty((0, 5)), dict(sources=[16]), {})
        self.assertEqual(rejects['CAP'], 1)


if __name__ == '__main__':
    unittest.main()
