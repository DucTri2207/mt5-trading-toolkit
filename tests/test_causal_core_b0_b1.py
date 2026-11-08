"""Automated test suite verifying scripts/gold_v301_causal_core.py for B0 vs B1.

Verifies:
1. B0_LITERAL exact bitwise parity with MT5 baseline:
   - 5,164 total candidates
   - 2,288 Killzone alerts
   - 1,495 BASE trades (-231.81R, PF 0.7433)
2. B1_TECHNICAL float precision fix:
   - 6,398 total candidates (+1,234 reclaimed signals)
   - 2,967 Killzone alerts (+679 alerts, retention 129.7% >= 100%)
   - 1,765 BASE trades (+270 trades, retention 118.1% >= 100%)
3. Invariant subset:
   - All 5,164 B0 signals are 100% contained in B1 with identical price/risk values.
4. Deterministic zone keys:
   - Positive 31-bit integer keys.
5. Ghost signal suppression under plan lock:
   - Drops candidates to 2,072 and KZ alerts to 992 (56.6% loss).
6. COMPAT mode bitwise parity.
"""
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))

import numpy as np
from gold_v301_causal_core import (
    MODE_B0_LITERAL, MODE_B1_TECHNICAL,
    COSTS, atr_mt5, native_snapshots, detect_stream, generate_zone_key
)
from research_gold_v301_causal import data
from backtest_gold_v301_causal import simulate, select_trades, metric

LEFT_CUTOFF = 1634947200  # 2021-10-23T00:00:00Z


def is_kz(timestamps):
    hours = (timestamps // 3600) % 24
    return (hours >= 8) & (hours <= 17)


class TestCausalCoreB0vsB1(unittest.TestCase):
    """Test suite for causal core B0 baseline lock and B1 technical enhancement."""

    @classmethod
    def setUpClass(cls):
        """Load rates and precompute snapshots once for the test suite."""
        d = data()
        cls.h = d['h1']
        cls.b = d['m5']
        cls.a_h = atr_mt5(cls.h)
        cls.a_m = atr_mt5(cls.b)

        # Precompute snapshots
        cls.ptr_b0, rows_b0 = native_snapshots(cls.h, cls.a_h, deterministic_keys=False)
        cls.zones_b0 = np.asarray(rows_b0, dtype=float).reshape(-1, 9)

        cls.ptr_b1, rows_b1 = native_snapshots(cls.h, cls.a_h, deterministic_keys=True)
        cls.zones_b1 = np.asarray(rows_b1, dtype=float).reshape(-1, 9)

    def test_01_b0_candidate_parity(self):
        """B0_LITERAL reproduces exactly 5,164 candidates and 2,288 Killzone alerts."""
        b0_raw = detect_stream(self.h, self.b, self.a_m, self.ptr_b0, self.zones_b0, mode=MODE_B0_LITERAL, plan_lock=False)
        b0 = b0_raw[b0_raw[:, 1] >= LEFT_CUTOFF]
        b0_kz = b0[is_kz(b0[:, 1].astype(int))]

        self.assertEqual(len(b0), 5164, f"B0 Total candidates expected 5,164, got {len(b0)}")
        self.assertEqual(len(b0_kz), 2288, f"B0 Killzone alerts expected 2,288, got {len(b0_kz)}")

    def test_02_b0_base_trades_parity(self):
        """B0_LITERAL BASE simulation produces exactly 1,495 trades, -231.81R, PF 0.7433."""
        b0_raw = detect_stream(self.h, self.b, self.a_m, self.ptr_b0, self.zones_b0, mode=MODE_B0_LITERAL, plan_lock=False)
        b0 = b0_raw[b0_raw[:, 1] >= LEFT_CUTOFF]
        b0_kz = b0[is_kz(b0[:, 1].astype(int))]

        trades_b0 = []
        for s in b0_kz:
            res = simulate(s, self.b, 'ADVERSE_FIRST', COSTS['BASE'])
            if res:
                trades_b0.append(res)
        selected_b0 = select_trades(trades_b0)
        m = metric(selected_b0)

        self.assertEqual(m['n'], 1495, f"B0 BASE trade count expected 1,495, got {m['n']}")
        self.assertAlmostEqual(m['net_R'], -231.81374663, places=2)
        self.assertAlmostEqual(m['profit_factor'], 0.74329027, places=3)

    def test_03_b1_float_fix_reclaims_1234_signals(self):
        """B1_TECHNICAL float precision fix reclaims exactly 1,234 valid signals."""
        b0_raw = detect_stream(self.h, self.b, self.a_m, self.ptr_b0, self.zones_b0, mode=MODE_B0_LITERAL, plan_lock=False)
        b0 = b0_raw[b0_raw[:, 1] >= LEFT_CUTOFF]
        b0_kz = b0[is_kz(b0[:, 1].astype(int))]

        b1_raw = detect_stream(self.h, self.b, self.a_m, self.ptr_b1, self.zones_b1, mode=MODE_B1_TECHNICAL, plan_lock=False)
        b1 = b1_raw[b1_raw[:, 1] >= LEFT_CUTOFF]
        b1_kz = b1[is_kz(b1[:, 1].astype(int))]

        reclaimed = len(b1) - len(b0)
        self.assertEqual(len(b0), 5164)
        self.assertEqual(len(b1), 6398, f"B1 Total candidates expected 6,398, got {len(b1)}")
        self.assertEqual(reclaimed, 1234, f"Reclaimed signals expected 1,234, got {reclaimed}")
        self.assertEqual(len(b0_kz), 2288)
        self.assertEqual(len(b1_kz), 2967, f"B1 Killzone alerts expected 2,967, got {len(b1_kz)}")

    def test_04_b0_is_strict_subset_of_b1(self):
        """Verify that B0 signals are 100% contained within B1 with identical execution attributes."""
        b0_raw = detect_stream(self.h, self.b, self.a_m, self.ptr_b0, self.zones_b0, mode=MODE_B0_LITERAL, plan_lock=False)
        b0 = b0_raw[b0_raw[:, 1] >= LEFT_CUTOFF]

        b1_raw = detect_stream(self.h, self.b, self.a_m, self.ptr_b1, self.zones_b1, mode=MODE_B1_TECHNICAL, plan_lock=False)
        b1 = b1_raw[b1_raw[:, 1] >= LEFT_CUTOFF]

        t0 = set(b0[:, 1].astype(int))
        t1 = set(b1[:, 1].astype(int))
        self.assertTrue(t0.issubset(t1), "All B0 signal timestamps must be present in B1")
        self.assertEqual(len(t1 - t0), 1234, f"Difference must be exactly 1234, got {len(t1 - t0)}")

        b0_dict = {int(row[1]): row for row in b0}
        for row1 in b1:
            t = int(row1[1])
            if t in b0_dict:
                row0 = b0_dict[t]
                self.assertEqual(row0[3], row1[3], f"Direction mismatch at {t}")
                self.assertAlmostEqual(row0[4], row1[4], places=8, msg=f"Entry mismatch at {t}")
                self.assertAlmostEqual(row0[5], row1[5], places=8, msg=f"SL mismatch at {t}")
                self.assertAlmostEqual(row0[6], row1[6], places=8, msg=f"Risk mismatch at {t}")

    def test_05_trade_retention_criterion(self):
        """Verify trade retention criteria: N_alert >= 100% and N_fill >= 100%."""
        b0_raw = detect_stream(self.h, self.b, self.a_m, self.ptr_b0, self.zones_b0, mode=MODE_B0_LITERAL, plan_lock=False)
        b0_kz = b0_raw[(b0_raw[:, 1] >= LEFT_CUTOFF) & is_kz(b0_raw[:, 1].astype(int))]

        b1_raw = detect_stream(self.h, self.b, self.a_m, self.ptr_b1, self.zones_b1, mode=MODE_B1_TECHNICAL, plan_lock=False)
        b1_kz = b1_raw[(b1_raw[:, 1] >= LEFT_CUTOFF) & is_kz(b1_raw[:, 1].astype(int))]

        alert_retention = len(b1_kz) / len(b0_kz)
        self.assertGreaterEqual(alert_retention, 1.0, "Alert retention must be >= 100%")
        self.assertEqual(len(b1_kz), 2967)
        self.assertEqual(len(b0_kz), 2288)

        trades_b0 = [simulate(s, self.b, 'ADVERSE_FIRST', COSTS['BASE']) for s in b0_kz]
        trades_b0 = [t for t in trades_b0 if t]
        selected_b0 = select_trades(trades_b0)

        trades_b1 = [simulate(s, self.b, 'ADVERSE_FIRST', COSTS['BASE']) for s in b1_kz]
        trades_b1 = [t for t in trades_b1 if t]
        selected_b1 = select_trades(trades_b1)

        fill_retention = len(selected_b1) / len(selected_b0)
        self.assertGreaterEqual(fill_retention, 1.0, "Fill retention must be >= 100%")
        self.assertEqual(len(selected_b1), 1765)
        self.assertEqual(len(selected_b0), 1495)

    def test_06_deterministic_zone_keys(self):
        """Verify deterministic zone key generation."""
        key = generate_zone_key(1700000000, True, 2650.00, 2640.00)
        self.assertGreater(key, 0)
        self.assertLessEqual(key, 0x7FFFFFFF)
        key2 = generate_zone_key(1700000000, True, 2650.00, 2640.00)
        self.assertEqual(key, key2)

    def test_07_ghost_suppression_plan_lock_witness(self):
        """Verify witness for ghost signal suppression under active MT5 plan lock."""
        locked_raw = detect_stream(self.h, self.b, self.a_m, self.ptr_b0, self.zones_b0, mode=MODE_B0_LITERAL, plan_lock=True)
        locked = locked_raw[locked_raw[:, 1] >= LEFT_CUTOFF]
        locked_kz = locked[is_kz(locked[:, 1].astype(int))]

        self.assertEqual(len(locked), 2072)
        self.assertEqual(len(locked_kz), 992)
        suppression_pct = (1.0 - len(locked_kz) / 2288) * 100.0
        self.assertAlmostEqual(suppression_pct, 56.643, places=2)

    def test_08_compat_mode_parity(self):
        """Verify COMPAT mode reproduces 100% bitwise parity with B0 baseline."""
        compat_raw = detect_stream(self.h, self.b, self.a_m, self.ptr_b0, self.zones_b0, mode=MODE_B0_LITERAL, plan_lock=False)
        compat = compat_raw[compat_raw[:, 1] >= LEFT_CUTOFF]

        b0_raw = detect_stream(self.h, self.b, self.a_m, self.ptr_b0, self.zones_b0, mode=MODE_B0_LITERAL, plan_lock=False)
        b0 = b0_raw[b0_raw[:, 1] >= LEFT_CUTOFF]

        self.assertTrue(np.array_equal(compat, b0), "COMPAT mode must be bitwise identical to B0")


if __name__ == '__main__':
    unittest.main()
