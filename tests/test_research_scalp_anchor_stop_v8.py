"""Only the two declared stop columns may change; source must already be known."""
import sys
import unittest
from pathlib import Path

import numpy as np

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
import research_scalp_anchor_stop_v8 as a
from test_research_scalp_weekly_v3 import new_candidate
from test_can_ho_tro_scalp import AT


def fixture(buy=True):
    c=new_candidate(buy,family=17);c[3]=AT-3600;c[17]=AT-900;c[13]=AT-600
    c[20]=98 if buy else 102;c[14]=c[20];c[18]=1.;c[19]=c[20]-(.25 if buy else -.25)
    bars=np.array([[AT-3600,100,106,94,100],[AT+900,100,200,10,100]],float)
    return c[None,:],bars


class AnchorStopChecks(unittest.TestCase):
    def test_both_directions_use_outer_source_stop_and_leave_signals_unchanged(self):
        for buy in (True,False):
            raw,bars=fixture(buy);before=raw.copy();result=a.replace_stops(raw,bars)
            self.assertEqual(result[0,20],94 if buy else 106)
            self.assertEqual(result[0,19],93.75 if buy else 106.25)
            columns=[i for i in range(40) if i not in (19,20)]
            np.testing.assert_array_equal(result[:,columns],raw[:,columns])
            np.testing.assert_array_equal(raw,before)

    def test_retest_extreme_remains_protected_if_it_is_beyond_source_pivot(self):
        for buy in (True,False):
            raw,bars=fixture(buy);raw[0,20]=92 if buy else 108
            result=a.replace_stops(raw,bars)
            self.assertEqual(result[0,20],92 if buy else 108)
            self.assertEqual(result[0,19],91.75 if buy else 108.25)

    def test_future_m15_extremes_cannot_change_earlier_source_stop(self):
        raw,bars=fixture();before=a.replace_stops(raw,bars)
        bars[1,1:]=[100,10000,1,9999]
        np.testing.assert_array_equal(before,a.replace_stops(raw,bars))
        np.testing.assert_array_equal(before,a.replace_stops(raw,bars[:1]))

    def test_missing_or_unconfirmed_source_is_rejected(self):
        raw,bars=fixture()
        with self.assertRaisesRegex(ValueError,'Missing'):
            a.replace_stops(raw,bars[1:])
        raw[0,17]=raw[0,13]+1
        with self.assertRaisesRegex(ValueError,'unavailable'):
            a.replace_stops(raw,bars)


if __name__=='__main__':unittest.main()
