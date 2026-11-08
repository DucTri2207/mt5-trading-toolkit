"""Grid controls, first eligible touches, strict availability and entry latency."""
import sys
import unittest
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'scripts'))
import research_scalp_round_v11 as v
from test_research_scalp_seasonal_v10 import stamp

AT = stamp(2021, 10, 26)+8*3600


def fixture(buy=True, reject=False, at=AT):
    times = at+np.arange(400)*60
    m1 = np.c_[times, np.full(400, 99.), np.full(400, 99.1), np.full(400, 98.9), np.full(400, 99.)]
    m5 = np.c_[at+np.arange(80)*300, np.full(80, 99.), np.full(80, 100.), np.full(80, 98.), np.full(80, 99.)]
    m1[91, 1:] = [99.8, 100.3, 99.2, 99.3] if reject else [99.4, 100.6, 99.3, 100.5]
    if not buy:
        for a in (m1, m5):
            a[:, 1:] = 200-a[:, 1:]; a[:, [2, 3]] = a[:, [3, 2]]
    return m1, m5


class RoundChecks(unittest.TestCase):
    def test_cascade_both_directions_with_prior_known_source_stop(self):
        for buy in (True, False):
            m1, m5 = fixture(buy); raw = v.detect(m1, m5, start=AT, end=AT+40000)
            self.assertEqual(len(raw), 1); c = raw[0]
            self.assertEqual(c[2], buy); self.assertEqual(c[36], 24)
            self.assertEqual(c[10], 100); self.assertLessEqual(c[12], c[0])
            self.assertEqual(c[1]-c[0], 120)
            self.assertAlmostEqual(c[19], 97.5 if buy else 102.5)

    def test_rejection_both_directions_uses_touch_extreme(self):
        for approach_buy in (True, False):
            m1, m5 = fixture(approach_buy, True)
            raw = v.detect(m1, m5, start=AT, end=AT+40000); self.assertEqual(len(raw), 1)
            c = raw[0]; self.assertEqual(c[2], not approach_buy); self.assertEqual(c[36], 25)
            self.assertAlmostEqual(c[19], 100.8 if approach_buy else 99.2)

    def test_failed_or_outside_hour_first_touch_is_consumed(self):
        m1, m5 = fixture(); m1[110, 1:] = m1[91, 1:]
        m1[91, 1:] = [99.95, 100.2, 99.2, 99.95]
        self.assertEqual(len(v.detect(m1, m5, start=AT, end=AT+40000)), 0)
        midnight = AT//86400*86400; m1, m5 = fixture(at=midnight)
        m1[181, 1:] = m1[91, 1:]
        self.assertEqual(len(v.detect(m1, m5, start=midnight, end=midnight+40000)), 0)

    def test_shifted_grid_uses_identical_logic_after_price_translation(self):
        m1, m5 = fixture(); raw = v.detect(m1, m5, start=AT, end=AT+40000)
        m1[:, 1:] += 3.7; m5[:, 1:] += 3.7
        shifted = v.detect(m1, m5, 3.7, AT, AT+40000)
        shifted[:, [10, 11, 14, 16, 19, 20, 21, 22]] -= 3.7
        shifted[:, [4, 36]] -= 2
        np.testing.assert_allclose(raw, shifted, atol=1e-12, rtol=0)

    def test_prefix_and_future_extrema_do_not_change_signal(self):
        m1, m5 = fixture(); full = v.detect(m1, m5, start=AT, end=AT+40000)
        cut = AT+120*60; prefix = v.detect(m1[:120], m5[:24], start=AT, end=cut)
        np.testing.assert_array_equal(prefix, full[full[:, 0]+60 < cut])
        m1[120:, 2] += 1000; m5[24:, 2] += 1000
        changed = v.detect(m1, m5, start=AT, end=cut)
        np.testing.assert_array_equal(changed, prefix)

    def test_missing_recent_m1_or_unclosed_m5_invalidates_context(self):
        m1, m5 = fixture(); broken = np.delete(m1, 85, axis=0)
        self.assertEqual(len(v.detect(broken, m5, start=AT, end=AT+40000)), 0)
        self.assertEqual(len(v.detect(m1, m5[:15], start=AT, end=AT+40000)), 0)


if __name__ == '__main__':
    unittest.main()
