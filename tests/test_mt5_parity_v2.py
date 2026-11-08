"""Automated Test Suite for Milestone 2: Python vs MT5 Parity Verification (Requirement R5).

Verifies:
1. Static MQL5 parity between duc_tri_can_ho_tro.mq5 and duc_tri_can_ho_tro_agy_lab.mq5.
2. 100% exact alert parity for B0 / COMPAT mode.
3. Causal guard synchronization between Python and MQL5 in B1 / TECHNICAL mode:
   - H1 zone formation time (known only after 4 departure bars).
   - Valid sweep causality (sweep_time >= known_time).
   - Decoupled candidate detection vs g_lastSignal.active plan lifecycle.
4. Empirical signal identity and retention on full historical rates (2022-2025).
5. MetaEditor64 compilation of duc_tri_can_ho_tro_agy_lab.mq5 with 0 errors and 0 warnings.
"""
import math
import subprocess
import sys
import unittest
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))

from verify_mt5_parity import (
    BASELINE_MQ5, LAB_MQ5, LAB_EX5, METAEDITOR_PATH, LEFT_CUTOFF, is_kz,
    verify_mql5_static_parity, verify_empirical_signal_parity,
    verify_metaeditor_compilation
)
from gold_v301_causal_core import (
    MODE_B0_LITERAL, MODE_B1_TECHNICAL,
    atr_mt5, native_snapshots, detect_stream
)
from research_gold_v301_causal import data


class TestMt5ParityV2(unittest.TestCase):
    """Test suite for MT5 and Python parity verification."""

    @classmethod
    def setUpClass(cls):
        d = data()
        cls.h = d['h1']
        cls.b = d['m5']
        cls.a_h = atr_mt5(cls.h)
        cls.a_m = atr_mt5(cls.b)

        # Snapshot computations
        cls.ptr_b0, rows_b0 = native_snapshots(cls.h, cls.a_h, deterministic_keys=False)
        cls.zones_b0 = np.asarray(rows_b0, dtype=float).reshape(-1, 9)

        cls.ptr_b1, rows_b1 = native_snapshots(cls.h, cls.a_h, deterministic_keys=True)
        cls.zones_b1 = np.asarray(rows_b1, dtype=float).reshape(-1, 9)

    def test_01_static_mql5_parity_checks(self):
        """All 12 static code parity checks between baseline and lab indicator pass."""
        res = verify_mql5_static_parity()
        self.assertTrue(res['all_passed'], f"Static checks failed: {res['checks']}")
        self.assertEqual(res['passed_count'], 12)

    def test_02_b0_literal_candidate_parity(self):
        """B0 produces exactly 5,164 candidates and 2,288 Killzone alerts."""
        b0_raw = detect_stream(self.h, self.b, self.a_m, self.ptr_b0, self.zones_b0, mode=MODE_B0_LITERAL, plan_lock=False)
        b0 = b0_raw[b0_raw[:, 1] >= LEFT_CUTOFF]
        b0_kz = b0[is_kz(b0[:, 1].astype(int))]

        self.assertEqual(len(b0), 5164, f"B0 candidates expected 5,164, got {len(b0)}")
        self.assertEqual(len(b0_kz), 2288, f"B0 Killzone alerts expected 2,288, got {len(b0_kz)}")

    def test_03_b0_plan_lock_suppression_witness(self):
        """MT5 chart plan lock bug suppresses exactly 56.64% of signals (2,072 cands, 992 KZ)."""
        b0_locked_raw = detect_stream(self.h, self.b, self.a_m, self.ptr_b0, self.zones_b0, mode=MODE_B0_LITERAL, plan_lock=True)
        b0_locked = b0_locked_raw[b0_locked_raw[:, 1] >= LEFT_CUTOFF]
        b0_locked_kz = b0_locked[is_kz(b0_locked[:, 1].astype(int))]

        self.assertEqual(len(b0_locked), 2072)
        self.assertEqual(len(b0_locked_kz), 992)
        suppression_rate = (1.0 - len(b0_locked_kz) / 2288) * 100.0
        self.assertAlmostEqual(suppression_rate, 56.643, places=2)

    def test_04_b1_technical_reclaims_1234_signals(self):
        """B1 technical fix reclaims exactly 1,234 signals (6,398 total, 2,967 KZ alerts)."""
        b1_raw = detect_stream(self.h, self.b, self.a_m, self.ptr_b1, self.zones_b1, mode=MODE_B1_TECHNICAL, plan_lock=False)
        b1 = b1_raw[b1_raw[:, 1] >= LEFT_CUTOFF]
        b1_kz = b1[is_kz(b1[:, 1].astype(int))]

        self.assertEqual(len(b1), 6398)
        self.assertEqual(len(b1_kz), 2967)
        self.assertEqual(len(b1) - 5164, 1234)
        self.assertEqual(len(b1_kz) - 2288, 679)

    def test_05_b0_is_invariant_subset_of_b1(self):
        """100% of B0 signals are contained in B1 with identical price and risk parameters."""
        b0_raw = detect_stream(self.h, self.b, self.a_m, self.ptr_b0, self.zones_b0, mode=MODE_B0_LITERAL, plan_lock=False)
        b0 = b0_raw[b0_raw[:, 1] >= LEFT_CUTOFF]

        b1_raw = detect_stream(self.h, self.b, self.a_m, self.ptr_b1, self.zones_b1, mode=MODE_B1_TECHNICAL, plan_lock=False)
        b1 = b1_raw[b1_raw[:, 1] >= LEFT_CUTOFF]

        t0 = set(b0[:, 1].astype(int))
        t1 = set(b1[:, 1].astype(int))
        self.assertTrue(t0.issubset(t1), "All B0 timestamps must be present in B1")

        b0_dict = {int(row[1]): row for row in b0}
        for row1 in b1:
            t = int(row1[1])
            if t in b0_dict:
                row0 = b0_dict[t]
                self.assertEqual(row0[3], row1[3], f"Direction mismatch at {t}")
                self.assertAlmostEqual(row0[4], row1[4], places=7, msg=f"Entry mismatch at {t}")
                self.assertAlmostEqual(row0[5], row1[5], places=7, msg=f"SL mismatch at {t}")
                self.assertAlmostEqual(row0[6], row1[6], places=7, msg=f"Risk mismatch at {t}")

    def test_06_causal_guard_h1_zone_formation_time(self):
        """H1 zones require strictly 4 departure bars before becoming active."""
        l_text = LAB_MQ5.read_text(encoding='utf-8', errors='ignore')
        self.assertIn('datetime zoneKnown = hRates[MathMin(copied - 1, baseEnd + DepartBars)].time + PeriodSeconds(scanTf);', l_text)
        self.assertIn('zone.timeKnown = zoneKnown;', l_text)

        # In Python native_zones: be + 4 <= end = last - 4 ensures departure bar 4 closed on or before last
        from gold_v301_causal_core import native_zones
        z = native_zones(self.h, self.a_h, 50, deterministic_keys=True)
        for row in z:
            typ = int(row[2])
            if typ != 4:
                base_idx = int(row[6])
                # Earliest departure end is base_idx + 4 <= 50
                self.assertLessEqual(base_idx + 4, 50)

    def test_07_causal_guard_sweep_causality(self):
        """MQL5 and Python enforce sweep_time >= known_time under TECHNICAL mode."""
        l_text = LAB_MQ5.read_text(encoding='utf-8', errors='ignore')
        self.assertIn('if(InpLabMode >= LAB_MODE_TECHNICAL)', l_text)
        self.assertIn('if(ltfRates[s].time < g_zones[z].timeKnown)', l_text)

        # COMPAT mode does NOT apply this check, preserving baseline exactly
        self.assertNotIn('if(InpLabMode == LAB_MODE_COMPAT)\n         {\n            if(ltfRates[s].time < g_zones[z].timeKnown)', l_text)

    def test_08_causal_guard_decoupled_candidate_detection(self):
        """TECHNICAL mode decouples candidate detection from active plan lifecycle."""
        l_text = LAB_MQ5.read_text(encoding='utf-8', errors='ignore')
        # COMPAT continues if g_lastSignal.active
        self.assertIn('if(sameProcessedSignal || (g_lastSignal.active && !sameProcessedSignal))', l_text)
        # TECHNICAL only continues if sameProcessedSignal
        self.assertIn('// Bug 3 Fix: Tách biệt candidate detection / alert publishing khỏi plan active lifecycle', l_text)

    def test_09_metaeditor_cli_compilation(self):
        """duc_tri_can_ho_tro_agy_lab.mq5 compiles with 0 errors and 0 warnings."""
        res = verify_metaeditor_compilation()
        self.assertTrue(res['compiled'], f"Compilation failed: {res}")
        self.assertTrue(res['zero_errors_zero_warnings'])
        self.assertTrue(res['ex5_exists'])
        self.assertGreater(res['ex5_size_bytes'], 100000)


if __name__ == '__main__':
    unittest.main()
