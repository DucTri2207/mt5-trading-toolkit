"""Independent M1 timing, frozen M5 inputs, excursion state and gap handling."""
import sys
import unittest
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import research_scalp_early_mean_v5 as e


def fixture():
    m1 = np.array([[7*3600+i*60, 100, 100.1, 99.9, 100] for i in range(120)], float)
    m5 = np.array([[-6*3600+i*300, 100, 100.1, 99.9, 100] for i in range(192)], float)
    h1 = np.array([[-60*3600+i*3600, 100, 101, 99, 100] for i in range(72)], float)
    m1[62, 1:] = [99.4, 99.65, 99.2, 99.6]
    return dict(m1=m1, m5=m5, h1=h1)


def detect(arrays, family=13):
    return e.detect(arrays, family, start=0, stop=10**9)


class EarlyMeanChecks(unittest.TestCase):
    def test_m1_signal_known_before_forming_m5_close_both_sides(self):
        for buy in (True, False):
            arrays = fixture()
            if not buy:
                for bars in arrays.values():
                    old = bars[:, 1:].copy()
                    bars[:, 1:] = 200-old[:, [0, 2, 1, 3]]
            rows = detect(arrays)
            self.assertEqual(len(rows), 1)
            c = rows[0]
            self.assertEqual(bool(c[2]), buy)
            self.assertEqual(c[0], 8*3600+120)
            self.assertEqual(c[1], 8*3600+180)
            self.assertLess(c[1], 8*3600+300)
            self.assertEqual(c[12], 8*3600)
            self.assertLessEqual(c[12], c[13])
            self.assertAlmostEqual(c[29], 100)
            self.assertAlmostEqual(c[10], 99.5 if buy else 100.5)

    def test_future_m5_reversal_cannot_change_earlier_m1_candidate(self):
        arrays = fixture()
        before = detect(arrays)
        forming = arrays['m5'][:, 0] >= 8*3600
        arrays['m5'][forming, 1:] = [100, 200, 20, 30]
        after = detect(arrays)
        np.testing.assert_array_equal(before, after[after[:, 1] <= before[-1, 1]])
        # The eventual M5 candle has no bullish rejection; M1 eligibility is independent.
        self.assertLess(arrays['m5'][forming][0, 4], arrays['m5'][forming][0, 1])

    def test_band_mean_atr_and_source_stay_frozen_across_m5_boundary(self):
        arrays = fixture()
        arrays['m1'][62, 1:] = [100, 100.1, 99.9, 100]
        arrays['m1'][64, 1:] = [99.4, 99.45, 99.2, 99.3]
        arrays['m1'][65, 1:] = [99.3, 99.65, 99.25, 99.6]
        arrays['m5'][arrays['m5'][:, 0] == 8*3600, 1:] = [100, 100.1, 99.2, 99.3]
        rows = detect(arrays)
        self.assertEqual(len(rows), 1)
        c = rows[0]
        self.assertEqual(c[13], arrays['m1'][64, 0])
        self.assertEqual(c[12], 8*3600)
        self.assertAlmostEqual(c[10], 99.5)
        self.assertAlmostEqual(c[18], .2)
        self.assertAlmostEqual(c[19], 99.15)
        self.assertAlmostEqual(c[29], 100)
        current = int(np.flatnonzero(arrays['m5'][:, 0] == 8*3600)[0])
        self.assertNotEqual(c[29], e.w.ema(arrays['m5'], 20)[current])

    def test_one_signal_until_prior_m1_close_crosses_mean(self):
        arrays = fixture()
        arrays['m1'][63:67, 1:] = [99.6, 99.65, 99.55, 99.6]
        arrays['m1'][64, 1:] = arrays['m1'][62, 1:]
        arrays['m1'][66, 1:] = [99.6, 100.2, 99.55, 100.1]
        arrays['m1'][67, 1:] = arrays['m1'][62, 1:]
        rows = detect(arrays)
        np.testing.assert_array_equal(rows[:, 34], [62, 67])

    def test_reclaim_after_three_bar_window_does_not_reuse_excursion(self):
        arrays = fixture()
        arrays['m1'][62:65, 1:] = [99.4, 99.45, 99.2, 99.3]
        arrays['m1'][65, 1:] = [99.3, 99.65, 99.25, 99.6]
        self.assertEqual(len(detect(arrays)), 0)

    def test_missing_m1_bar_resets_excursion(self):
        arrays = fixture()
        arrays['m1'][62, 1:] = [99.4, 99.45, 99.2, 99.3]
        arrays['m1'][63, 1:] = [99.3, 99.4, 99.25, 99.3]
        arrays['m1'][64, 1:] = [99.3, 99.65, 99.25, 99.6]
        self.assertEqual(len(detect(arrays)), 1)
        arrays['m1'] = np.delete(arrays['m1'], 63, axis=0)
        self.assertEqual(len(detect(arrays)), 0)

    def test_stale_m5_source_prevents_reclaim(self):
        arrays = fixture()
        arrays['m1'][62, 1:] = [100, 100.1, 99.9, 100]
        arrays['m1'][65, 1:] = [99.4, 99.45, 99.2, 99.3]
        arrays['m1'][66, 1:] = [99.3, 99.65, 99.25, 99.6]
        self.assertEqual(len(detect(arrays)), 1)
        times = arrays['m5'][:, 0]
        arrays['m5'] = arrays['m5'][(times < 8*3600) | (times >= 8*3600+600)]
        self.assertEqual(len(detect(arrays)), 0)

    def test_context_and_h1_metadata_ignore_forming_and_future_h1(self):
        arrays = fixture()
        before = detect(arrays, 12)
        self.assertEqual(len(before), 1)
        self.assertEqual(before[0, 39], 8*3600)
        arrays['h1'][arrays['h1'][:, 0] >= 8*3600, 1:] = [100, 200, 20, 30]
        after = detect(arrays, 12)
        np.testing.assert_array_equal(before, after[after[:, 1] <= before[-1, 1]])
        # A change to a truly closed context bar can remove eligibility.
        arrays['h1'][arrays['h1'][:, 0] == 7*3600, 1:] = [100, 1000, 99, 999]
        self.assertEqual(len(detect(arrays, 12)), 0)


if __name__ == '__main__':
    unittest.main()
