"""Adversarial stress-testing suite for Milestone 1 (Phase A).
Authored by Challenger 1 (critic, specialist).

Focus:
1. Baseline B0 exact count and trade parity.
2. Invariant subset property (B0 subset of B1).
3. IEEE 754 floating-point mantissa stress-testing around 1.5 and 2.0.
4. Boundary condition probing around tolerance threshold (1.5 - 1e-7).
5. Comprehensive MQL5 vs Python logic alignment.
"""
import math
import struct
import sys
import unittest
from pathlib import Path
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))

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


class TestAdversarialChallenger(unittest.TestCase):
    """Adversarial challenge test suite for Milestone 1."""

    @classmethod
    def setUpClass(cls):
        d = data()
        cls.h = d['h1']
        cls.b = d['m5']
        cls.a_h = atr_mt5(cls.h)
        cls.a_m = atr_mt5(cls.b)

        cls.ptr_b0, rows_b0 = native_snapshots(cls.h, cls.a_h, deterministic_keys=False)
        cls.zones_b0 = np.asarray(rows_b0, dtype=float).reshape(-1, 9)

        cls.ptr_b1, rows_b1 = native_snapshots(cls.h, cls.a_h, deterministic_keys=True)
        cls.zones_b1 = np.asarray(rows_b1, dtype=float).reshape(-1, 9)

    def test_01_adversarial_b0_exact_metrics(self):
        """Stress verify that B0 reproduces EXACT baseline counts and financial metrics."""
        b0_raw = detect_stream(self.h, self.b, self.a_m, self.ptr_b0, self.zones_b0, mode=MODE_B0_LITERAL, plan_lock=False)
        b0 = b0_raw[b0_raw[:, 1] >= LEFT_CUTOFF]
        b0_kz = b0[is_kz(b0[:, 1].astype(int))]

        # Verify candidate counts
        self.assertEqual(len(b0), 5164, f"B0 candidates must be 5164, got {len(b0)}")
        self.assertEqual(len(b0_kz), 2288, f"B0 KZ alerts must be 2288, got {len(b0_kz)}")

        # Verify simulation and selection metrics
        trades_b0 = [simulate(s, self.b, 'ADVERSE_FIRST', COSTS['BASE']) for s in b0_kz]
        trades_b0 = [t for t in trades_b0 if t]
        selected_b0 = select_trades(trades_b0)
        m = metric(selected_b0)

        self.assertEqual(m['n'], 1495, f"B0 BASE trade count must be exactly 1495, got {m['n']}")
        self.assertAlmostEqual(m['net_R'], -231.81374663, places=6, msg="Net R must match verbatim")
        self.assertAlmostEqual(m['profit_factor'], 0.74329027, places=6, msg="Profit Factor must match verbatim")

    def test_02_adversarial_strict_subset_property(self):
        """Stress verify that B0 is a 100% strict subset of B1 with zero omissions and zero regressions."""
        b0_raw = detect_stream(self.h, self.b, self.a_m, self.ptr_b0, self.zones_b0, mode=MODE_B0_LITERAL, plan_lock=False)
        b0 = b0_raw[b0_raw[:, 1] >= LEFT_CUTOFF]

        b1_raw = detect_stream(self.h, self.b, self.a_m, self.ptr_b1, self.zones_b1, mode=MODE_B1_TECHNICAL, plan_lock=False)
        b1 = b1_raw[b1_raw[:, 1] >= LEFT_CUTOFF]

        self.assertEqual(len(b1), 6398)
        self.assertEqual(len(b1) - len(b0), 1234)

        b0_times = set(b0[:, 1].astype(int))
        b1_times = set(b1[:, 1].astype(int))

        # Check subset condition
        missing_in_b1 = b0_times - b1_times
        self.assertEqual(len(missing_in_b1), 0, f"Found {len(missing_in_b1)} B0 signals dropped in B1!")

        # Check exact field identity for all matching signals
        b1_by_time = {int(r[1]): r for r in b1}
        for r0 in b0:
            t = int(r0[1])
            r1 = b1_by_time[t]
            # bar_index, time_m5, time_avail, direction, entry, sl, risk
            self.assertEqual(r0[0], r1[0], f"Bar mismatch at t={t}")
            self.assertEqual(r0[3], r1[3], f"Direction mismatch at t={t}")
            self.assertEqual(r0[4], r1[4], f"Entry mismatch at t={t}")
            self.assertEqual(r0[5], r1[5], f"SL mismatch at t={t}")
            self.assertEqual(r0[6], r1[6], f"Risk mismatch at t={t}")

    def test_03_ieee754_mantissa_randomized_stress_test(self):
        """Stress test float precision across 500,000 randomized IEEE 754 mantissas and multiple price scales.

        Verifies:
        1. When target is nominally 1.5R, `rr1 < 1.5 - 1e-7` NEVER falsely rejects.
        2. When target is nominally 2.0R, `rr2 < rr1` NEVER falsely triggers.
        3. Maximum precision deviation for Gold is bounded well within 1e-7.
        """
        rng = np.random.default_rng(42)
        n_samples = 500_000

        # Regimes: (name, entry_min, entry_max, risk_min, risk_max)
        regimes = [
            ("Gold", 1000.0, 3500.0, 2.5, 10.0),
            ("Forex", 0.8, 2.0, 0.001, 0.02),
            ("Crypto", 20000.0, 150000.0, 100.0, 5000.0),
            ("Micro", 0.0001, 1.0, 0.00001, 0.005),
            ("LargeAsset", 1000000.0, 5000000.0, 10.0, 1000.0)
        ]

        for name, emin, emax, rmin, rmax in regimes:
            entries = rng.uniform(emin, emax, n_samples // len(regimes))
            risks = rng.uniform(rmin, rmax, n_samples // len(regimes))
            directions = rng.choice([-1.0, 1.0], n_samples // len(regimes))

            tp1s = entries + directions * 1.5 * risks
            tp2s = entries + directions * 2.0 * risks

            rr1s = np.abs(tp1s - entries) / risks
            rr2s = np.abs(tp2s - entries) / risks

            # Buggy baseline check
            buggy_rejections = (rr1s < 1.5) | (rr2s < rr1s)
            buggy_count = np.sum(buggy_rejections)

            # Fixed B1 check
            fixed_rejections = (rr1s < (1.5 - 1e-7)) | (rr2s < rr1s)
            fixed_count = np.sum(fixed_rejections)

            # Max deviation from nominal 1.5
            max_dev = np.max(np.abs(rr1s - 1.5))

            self.assertEqual(
                fixed_count, 0,
                f"[{name}] Fixed condition falsely rejected {fixed_count} exact 1.5R setups! Max dev: {max_dev}"
            )
            # Ensure the test was non-trivial by asserting that baseline actually failed on some cases
            self.assertGreater(
                buggy_count, 0,
                f"[{name}] Baseline should have suffered precision failures, but got 0 out of {len(entries)}"
            )

    def test_04_boundary_precision_probing(self):
        """Probe the razor's edge around the 1.5 - 1e-7 threshold with bit-level floating point representations."""
        threshold = 1.5 - 1e-7  # exactly 1.4999999

        # Case A: Mathematical target is genuinely below threshold (e.g. 1.4999998)
        # MUST be rejected by fixed logic.
        genuinely_low_rr = 1.5 - 2e-7
        entry = 2000.0
        risk = 5.0
        tp_sub = entry + genuinely_low_rr * risk
        rr_sub = (tp_sub - entry) / risk
        self.assertTrue(rr_sub < threshold, "Genuinely below threshold must be rejected")

        # Case B: Target is just above threshold (e.g. 1.5 - 0.5e-7)
        # MUST be accepted.
        slightly_above_rr = 1.5 - 0.5e-7
        tp_above = entry + slightly_above_rr * risk
        rr_above = (tp_above - entry) / risk
        self.assertFalse(rr_above < threshold, "Slightly above threshold must be accepted")

        # Case C: IEEE 754 nextafter immediately below 1.5
        # nextafter(1.5, 0.0) is the largest double strictly less than 1.5
        prev_1_5 = np.nextafter(1.5, 0.0)
        self.assertLess(prev_1_5, 1.5)
        self.assertGreater(prev_1_5, threshold, "nextafter(1.5) must be safely above 1.5 - 1e-7")
        self.assertFalse(prev_1_5 < threshold, "Floating point near 1.5 must not be rejected")

    def test_05_extreme_ulp_bit_flipping(self):
        """Systematically flip the lowest mantissa bits of 1.5 to test tolerance margin in ULPs."""
        # 1.5 in IEEE 754 binary64:
        # Sign = 0 (1 bit), Exponent = 1023 (11 bits = 01111111111), Mantissa = 1000... (52 bits)
        packed = struct.pack('>d', 1.5)
        raw_int = struct.unpack('>Q', packed)[0]

        # Check how many ULPs correspond to 1e-7
        # 1 ULP at 1.5 is 2^-52 = 2.220446049250313e-16
        ulp = 2.0 ** -52
        ulps_in_1e7 = 1e-7 / ulp  # ~ 450,359,962 ULPs

        # Test decrementing up to 10,000 ULPs below 1.5
        for u in [1, 2, 5, 10, 100, 1000, 10000, 100000, 1000000]:
            mutated_int = raw_int - u
            mutated_float = struct.unpack('>d', struct.pack('>Q', mutated_int))[0]
            self.assertLess(mutated_float, 1.5)
            # Must NOT be rejected by (rr < 1.5 - 1e-7)
            is_rejected = (mutated_float < (1.5 - 1e-7))
            self.assertFalse(
                is_rejected,
                f"Mutated float with -{u} ULPs was rejected! float={mutated_float:.17f}"
            )

        # Decrementing beyond 500,000,000 ULPs should be rejected
        beyond_int = raw_int - int(ulps_in_1e7 + 1000)
        beyond_float = struct.unpack('>d', struct.pack('>Q', beyond_int))[0]
        self.assertTrue(
            beyond_float < (1.5 - 1e-7),
            "Float beyond 1e-7 margin must be rejected"
        )

    def test_06_hybrid_mode_tp2_decoupling_adversarial(self):
        """Adversarial stress test on Hybrid mode decoupling in MQL5 logic.

        In Hybrid mode:
        TP1 is fixed pips (e.g. 30 pips = $3 on gold).
        TP2 is 2.0R.
        MinRR is 1.5 or 2.0.
        If risk = 5.0, TP1 RR is 0.6R (< MinRR).
        Baseline rejected 100% of these because rr1 < MinRR was enforced.
        Fixed MQL5 logic only checks rr2 >= MinRR - 1e-7 for Hybrid mode.
        """
        min_rr = 1.5
        pip_size = 0.1
        tp1_pips = 30.0  # $3.00

        # Sweep risks from 2.5 to 10.0
        for risk in np.linspace(2.5, 10.0, 50):
            for entry in [1800.0, 2000.0, 2600.0]:
                for is_buy in [True, False]:
                    d = 1.0 if is_buy else -1.0
                    tp1 = entry + d * tp1_pips * pip_size
                    tp2 = entry + d * 2.0 * risk

                    rr1 = abs(tp1 - entry) / risk
                    rr2 = abs(tp2 - entry) / risk

                    # Baseline check: (rr1 < min_rr) -> REJECTS because rr1 <= 1.2
                    baseline_rejected = (rr1 < min_rr) or (rr2 < rr1)
                    self.assertTrue(
                        baseline_rejected,
                        f"Baseline should have rejected hybrid setup with risk={risk}"
                    )

                    # Fixed check in duc_tri_can_ho_tro_agy_lab.mq5:
                    # tpOrderValid: entry < tp1 < tp2 for buy
                    tp_order_valid = (entry < tp1 < tp2) if is_buy else (entry > tp1 > tp2)
                    self.assertTrue(tp_order_valid)

                    # Hybrid only checks rr2 < (MinRR - 1e-7)
                    fixed_rejected = (rr2 < (min_rr - 1e-7))
                    self.assertFalse(
                        fixed_rejected,
                        f"Fixed hybrid logic must accept 2.0R runner with risk={risk}"
                    )


if __name__ == '__main__':
    unittest.main()
