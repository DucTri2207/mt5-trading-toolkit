import sys
import unittest
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from audit_video_orderflow_data import audit_bars


class OrderflowDataAuditTests(unittest.TestCase):
    def bars(self):
        return np.array([(1, 10., 12., 9., 11., 5, 0), (61, 11., 13., 10., 12., 8, 0)],
                        dtype=[('time', 'i8'), ('open', 'f8'), ('high', 'f8'), ('low', 'f8'),
                               ('close', 'f8'), ('tick_volume', 'u8'), ('real_volume', 'u8')])

    def test_quote_volume_does_not_establish_orderflow(self):
        result = audit_bars(self.bars())
        self.assertEqual(result['tick_volume']['nonzero_bars'], 2)
        self.assertEqual(result['real_volume']['nonzero_bars'], 0)
        self.assertFalse(result['faithful_video_execution_replay_possible'])

    def test_positive_bar_volume_still_lacks_price_and_side(self):
        bars = self.bars()
        bars['real_volume'] = 10
        result = audit_bars(bars)
        self.assertEqual(result['real_volume']['nonzero_bars'], 2)
        self.assertFalse(result['executed_volume_at_price_available'])
        self.assertFalse(result['aggressor_side_available'])

    def test_reject_duplicate_time(self):
        bars = self.bars()
        bars['time'] = 1
        with self.assertRaises(ValueError):
            audit_bars(bars)

    def test_reject_missing_fields(self):
        with self.assertRaises(ValueError):
            audit_bars(np.zeros(2, dtype=[('time', 'i8')]))


if __name__ == '__main__':
    unittest.main()
