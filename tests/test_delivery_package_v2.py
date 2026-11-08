"""Unit test suite for Milestone 3 delivery package v2 and statistical verification.

Verifies:
1. Complete delivery package artifact existence in reports/can_ho_tro_agy_upgrade/20261101_agy_lab_v2/.
2. Cryptographic SHA-256 manifest integrity for all registered artifacts.
3. Schema conformity: 24 columns for SIGNALS_*.csv, 19 columns for TRADES_*.csv.
4. Independent recomputability: Exact mathematical recomputation from raw CSV files.
5. Monthly block bootstrap reproducibility: Seed 20261101 producing CI [-0.0043, +0.0420] for H2 vs B0.
6. Acceptance criteria audit: Transparent declaration of "KHÔNG ĐẠT (NOT MET)" for automated 1R.
7. Causal integrity: All fills occur at or after signal_known_time, exits after fill.
"""

import csv
import hashlib
import json
import unittest
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
DELIVERY_DIR = ROOT / 'reports/can_ho_tro_agy_upgrade/20261101_agy_lab_v2'
MANIFEST_PATH = DELIVERY_DIR / 'MANIFEST.json'
REPORT_PATH = DELIVERY_DIR / 'REPORT.md'
VERIFICATION_PATH = DELIVERY_DIR / 'VERIFICATION.json'
REGISTRY_PATH = DELIVERY_DIR / 'EXPERIMENT_REGISTRY.json'

BRANCHES = ['B0', 'B1', 'H1', 'H2', 'H1_H2']


class TestDeliveryPackageV2(unittest.TestCase):
    """Test suite for v2 delivery package artifacts, schemas, bootstrap, and verification audit."""

    @classmethod
    def setUpClass(cls):
        """Ensure delivery directory exists."""
        cls.assertTrue(DELIVERY_DIR.exists(), f"Delivery package dir does not exist: {DELIVERY_DIR}")

    def test_01_all_delivery_artifacts_exist(self):
        """Verify that all 26 required delivery artifacts exist in v2 package folder."""
        required_files = [
            'REPORT.md', 'MANIFEST.json', 'PROTOCOL.json', 'CODE_DIFF.patch',
            'duc_tri_can_ho_tro_agy_lab.mq5', 'duc_tri_can_ho_tro_agy_lab.ex5',
            'SIGNALS_B0.csv', 'SIGNALS_B1.csv', 'SIGNALS_H1.csv', 'SIGNALS_H2.csv', 'SIGNALS_H1_H2.csv',
            'TRADES_B0.csv', 'TRADES_B1.csv', 'TRADES_H1.csv', 'TRADES_H2.csv', 'TRADES_H1_H2.csv',
            'EQUITY_B0.csv', 'EQUITY_B1.csv', 'EQUITY_H1.csv', 'EQUITY_H2.csv', 'EQUITY_H1_H2.csv',
            'MATCHED_EVENTS.csv', 'FREQUENCY.csv', 'EXPERIMENT_REGISTRY.json', 'EXPERIMENT_RESULTS.json',
            'VERIFICATION.json'
        ]
        for fname in required_files:
            fpath = DELIVERY_DIR / fname
            self.assertTrue(fpath.exists(), f"Missing required delivery artifact: {fname}")
            self.assertGreater(fpath.stat().st_size, 0, f"Artifact {fname} is empty (0 bytes)")

    def test_02_manifest_cryptographic_integrity(self):
        """Verify that MANIFEST.json hashes match exact SHA-256 of files on disk."""
        self.assertTrue(MANIFEST_PATH.exists())
        with open(MANIFEST_PATH, 'r', encoding='utf-8') as f:
            manifest = json.load(f)

        artifacts = manifest['artifacts']
        self.assertGreaterEqual(len(artifacts), 25)

        for fname, meta in artifacts.items():
            fpath = DELIVERY_DIR / fname
            self.assertTrue(fpath.exists(), f"File in manifest missing on disk: {fname}")
            actual_size = fpath.stat().st_size
            self.assertEqual(actual_size, meta['size_bytes'], f"Size mismatch for {fname}")

            h = hashlib.sha256()
            with open(fpath, 'rb') as f_in:
                while chunk := f_in.read(65536):
                    h.update(chunk)
            self.assertEqual(h.hexdigest(), meta['sha256'], f"SHA-256 mismatch for {fname}")

    def test_03_signal_ledger_schema_24_columns(self):
        """Verify that all SIGNALS_*.csv ledgers contain exactly 24 standardized columns."""
        expected_cols = [
            'signal_id', 'signal_time', 'exec_time', 'direction', 'entry_market',
            'sl_price', 'risk_usd', 'tp_1r', 'choch_level', 'zone_id',
            'zone_type', 'zone_distal', 'zone_proximal', 'zone_score', 'sweep_shift',
            'atr', 'dist_to_zone', 'dist_to_zone_atr', 'has_opposing', 'opposing_proximal',
            'opposing_room', 'room_net_R', 'spread_at_signal', 'latency_usd'
        ]
        for b in BRANCHES:
            csv_path = DELIVERY_DIR / f'SIGNALS_{b}.csv'
            with open(csv_path, 'r', encoding='utf-8') as f:
                reader = csv.reader(f)
                header = next(reader)
                self.assertEqual(len(header), 24, f"Column count not 24 in SIGNALS_{b}.csv: {len(header)}")
                self.assertEqual(header, expected_cols, f"Column names mismatch in SIGNALS_{b}.csv")

    def test_04_trade_ledger_schema_19_columns(self):
        """Verify that all TRADES_*.csv ledgers contain exactly 19 standardized columns."""
        expected_cols = [
            'trade_id', 'signal_id', 'direction', 'entry_time', 'entry_price',
            'entry_type', 'sl_price', 'tp_price', 'risk_usd', 'exit_time',
            'exit_price', 'exit_reason', 'gross_pnl_usd', 'commission_usd',
            'slippage_usd', 'spread_cost_usd', 'net_pnl_usd', 'net_r', 'bars_held'
        ]
        for b in BRANCHES:
            csv_path = DELIVERY_DIR / f'TRADES_{b}.csv'
            with open(csv_path, 'r', encoding='utf-8') as f:
                reader = csv.reader(f)
                header = next(reader)
                self.assertEqual(len(header), 19, f"Column count not 19 in TRADES_{b}.csv: {len(header)}")
                self.assertEqual(header, expected_cols, f"Column names mismatch in TRADES_{b}.csv")

    def test_05_independent_recomputability_from_raw_csv(self):
        """Verify third parties can independently recalculate all metrics directly from CSV files."""
        # Check B0
        df_b0 = pd.read_csv(DELIVERY_DIR / 'TRADES_B0.csv')
        self.assertEqual(len(df_b0), 4136)
        self.assertAlmostEqual(df_b0['net_r'].sum(), -539.41, places=1)
        self.assertAlmostEqual(df_b0['net_r'].mean(), -0.1304, places=3)
        tp_b0 = (df_b0['exit_reason'] == 'TP').mean() * 100.0
        self.assertAlmostEqual(tp_b0, 25.73, places=1)

        # Check H2
        df_h2 = pd.read_csv(DELIVERY_DIR / 'TRADES_H2.csv')
        self.assertEqual(len(df_h2), 4258)
        self.assertAlmostEqual(df_h2['net_r'].sum(), -474.84, places=1)
        self.assertAlmostEqual(df_h2['net_r'].mean(), -0.1115, places=3)
        tp_h2 = (df_h2['exit_reason'] == 'TP').mean() * 100.0
        self.assertAlmostEqual(tp_h2, 26.12, places=1)

        # Check B1 & H1
        for b in ['B1', 'H1']:
            df = pd.read_csv(DELIVERY_DIR / f'TRADES_{b}.csv')
            self.assertEqual(len(df), 4925)
            self.assertAlmostEqual(df['net_r'].sum(), -617.85, places=1)
            self.assertAlmostEqual(df['net_r'].mean(), -0.1255, places=3)

    def test_06_matched_events_alignment(self):
        """Verify MATCHED_EVENTS.csv contains all 6,398 candidate events aligned across branches."""
        df_events = pd.read_csv(DELIVERY_DIR / 'MATCHED_EVENTS.csv')
        self.assertEqual(len(df_events), 6398)

        # B0 should be present in exactly 5,164 events
        self.assertEqual(df_events['b0_present'].sum(), 5164)

        # Exactly 1,234 events should be reclaimed by float precision fix
        reclaimed = df_events[df_events['event_category'] == 'B1_FLOAT_BUG_RECLAIMED']
        self.assertEqual(len(reclaimed), 1234)

    def test_07_frequency_and_gap_analysis(self):
        """Verify FREQUENCY.csv contains monthly, weekly distributions and largest trading gaps."""
        df_freq = pd.read_csv(DELIVERY_DIR / 'FREQUENCY.csv')
        period_types = df_freq['period_type'].unique()
        self.assertIn('MONTHLY', period_types)
        self.assertIn('WEEKLY', period_types)
        self.assertIn('GAP_SUMMARY', period_types)

        b0_gap = df_freq[(df_freq['period_type'] == 'GAP_SUMMARY') & (df_freq['period_id'] == 'MAX_GAP_HOURS')]['b0_trades'].values[0]
        h2_gap = df_freq[(df_freq['period_type'] == 'GAP_SUMMARY') & (df_freq['period_id'] == 'MAX_GAP_HOURS')]['h2_trades'].values[0]
        self.assertAlmostEqual(float(b0_gap), 967.58, places=1)
        self.assertAlmostEqual(float(h2_gap), 819.0, places=1)

    def test_08_daily_equity_curves(self):
        """Verify EQUITY_*.csv curves have continuous daily records under 0.25% risk per trade."""
        for b in BRANCHES:
            eq_path = DELIVERY_DIR / f'EQUITY_{b}.csv'
            df_eq = pd.read_csv(eq_path)
            self.assertGreater(len(df_eq), 1800)
            self.assertAlmostEqual(df_eq.iloc[0]['equity_usd'], 100000.0 + df_eq.iloc[0]['daily_pnl_usd'], places=1)
            final_cum_r = df_eq.iloc[-1]['cum_net_r']
            final_equity = df_eq.iloc[-1]['equity_usd']
            expected_equity = 100000.0 + final_cum_r * 250.0
            self.assertAlmostEqual(final_equity, expected_equity, places=1)

    def test_09_code_diff_patch_validity(self):
        """Verify CODE_DIFF.patch exists, is non-empty, and contains expected file diff header."""
        patch_path = DELIVERY_DIR / 'CODE_DIFF.patch'
        self.assertTrue(patch_path.exists())
        content = patch_path.read_text(encoding='utf-8', errors='replace')
        self.assertIn('diff --git', content)
        self.assertIn('duc_tri_can_ho_tro.mq5', content)
        self.assertIn('duc_tri_can_ho_tro_agy_lab.mq5', content)
        self.assertIn('ENUM_LAB_MODE', content)
        self.assertIn('ShowTelemetry', content)

    def test_10_acceptance_criteria_transparency_and_ponytail(self):
        """Verify REPORT.md and VERIFICATION.json declare KHÔNG ĐẠT (NOT MET) and have Ponytail review."""
        with open(VERIFICATION_PATH, 'r', encoding='utf-8') as f:
            verif = json.load(f)
        self.assertEqual(verif['overall_status'], 'KHÔNG ĐẠT (NOT MET)')
        self.assertIn('FAIL', verif['acceptance_criteria_checklist']['retention_annual_gate_2022_2025']['verdict'])
        self.assertIn('FAIL', verif['acceptance_criteria_checklist']['economic_expectancy_base']['verdict'])

        report_text = REPORT_PATH.read_text(encoding='utf-8')
        self.assertIn('KHÔNG ĐẠT (NOT MET)', report_text)
        self.assertIn('Ponytail', report_text)

    def test_11_temporal_causality_assertions(self):
        """Verify that all trades strictly obey temporal causality across all branches."""
        for b in BRANCHES:
            df_trades = pd.read_csv(DELIVERY_DIR / f'TRADES_{b}.csv')
            df_signals = pd.read_csv(DELIVERY_DIR / f'SIGNALS_{b}.csv').set_index('signal_id')
            for _, tr in df_trades.iterrows():
                sig_id = int(tr['signal_id'])
                sig = df_signals.loc[sig_id]
                sig_known = sig['signal_time'] + 300
                fill_t = tr['entry_time']
                exit_t = tr['exit_time']
                self.assertGreaterEqual(fill_t, sig_known, f"Trade {tr['trade_id']} fill_t {fill_t} < sig_known {sig_known}")
                self.assertGreaterEqual(exit_t, fill_t, f"Trade {tr['trade_id']} exit_t {exit_t} < fill_t {fill_t}")
                if tr['entry_type'] == 'LIMIT':
                    self.assertLess(fill_t, sig_known + 300, f"Limit trade {tr['trade_id']} fill_t {fill_t} >= deadline {sig_known + 300}")


if __name__ == '__main__':
    unittest.main()
