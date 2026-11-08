"""Statistical and coverage checks; no synthetic fixture certifies a real edge."""
import hashlib
import json
import sys
import tempfile
import unittest
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from analyze_fabio_validation import (analyze_replay, bootstrap_mean_net_R, _evidence_gates,
                                      registration_payload_sha256)


def trade(day, value):
    at = datetime.fromisoformat(day + 'T12:00:00').replace(tzinfo=timezone.utc)
    return {'exit_ns': int(at.timestamp()) * 10**9, 'net_R': value}


def replay(days, trades):
    return {'config': {'prop_day_zone': 'Europe/Prague', 'prop_daily_fraction': .05, 'prop_total_fraction': .1},
            'daily_equity': {day: {'min_equity': 100000., 'max_equity': 100001.} for day in days},
            'trades': trades, 'open_position': None, 'prop_breaches': [], 'max_observed_equity_dd_cash': 0.}


class ValidationTests(unittest.TestCase):
    def test_one_profitable_day_cannot_confirm(self):
        result = analyze_replay(replay(['2026-01-05'], [trade('2026-01-05', 3.)]),
                                metadata={'dataset_id': 'PUBLIC_SAMPLE', 'source_kind': 'EXCHANGE_TRADES_BBO',
                                          'full_quote_updates': True, 'registered_unseen': True})
        self.assertFalse(result['confirmed'])
        self.assertFalse(result['gates']['minimum_sample']['passed'])
        self.assertFalse(result['gates']['prospective_registered_unseen']['passed'])
        self.assertIsNone(result['pass_probability'])

    def test_zero_trade_and_unobserved_calendar_weeks_are_preserved(self):
        days = ['2026-01-05', '2026-01-12', '2026-01-26']
        result = analyze_replay(replay(days, [trade(days[0], 1.)]))
        self.assertEqual(len(result['weekly_blocks']), 4)
        self.assertEqual([w['closed_trades'] for w in result['weekly_blocks']], [1, 0, 0, 0])
        self.assertEqual(result['weeks_without_observed_days'], 1)
        self.assertEqual(result['weekly_bootstrap']['zero_trade_blocks'], 3)
        self.assertGreater(result['weekly_bootstrap']['zero_trade_resamples'], 0)
        self.assertIsNone(result['weekly_bootstrap']['family_adjusted_lower95'])
        self.assertFalse(result['gates']['frequency_and_win_targets']['passed'])

    def test_bootstrap_deterministic_and_selection_adjustment_is_conservative(self):
        blocks = [(5., 10), (-3., 10), (2., 5), (0., 0), (8., 20)] * 8
        first = bootstrap_mean_net_R(blocks)
        second = bootstrap_mean_net_R(blocks)
        self.assertEqual(first, second)
        self.assertEqual(first['resamples'], 20000)
        self.assertEqual(first['family_size'], 24)
        self.assertLessEqual(first['family_adjusted_lower95'], first['lower95'])
        self.assertAlmostEqual(first['mean_net_R'], 12. / 45.)

    def test_family_cannot_understate_current_two_market_selection(self):
        blocks = [(5., 10), (-3., 10), (2., 5), (0., 0), (8., 20)] * 8
        with self.assertRaisesRegex(ValueError, '>=24'):
            bootstrap_mean_net_R(blocks, family_size=12)
        current = bootstrap_mean_net_R(blocks)
        larger = bootstrap_mean_net_R(blocks, family_size=48)
        self.assertEqual(larger['family_size'], 48)
        self.assertLessEqual(larger['family_adjusted_lower95'], current['family_adjusted_lower95'])

    def test_counts_and_long_coverage_do_not_replace_evidence(self):
        first = date(2025, 1, 6)
        days = [(first + timedelta(days=7 * i)).isoformat() for i in range(28)]
        trades = [trade(day, 1. if j < 6 else -1.) for day in days for j in range(8)]
        result = analyze_replay(replay(days, trades), metadata={'dataset_id': 'SYNTHETIC', 'registered_unseen': True},
                                source_coverage={'full_quote_updates': True})
        self.assertTrue(result['gates']['minimum_sample']['passed'])
        self.assertEqual(result['closed_trades'], 224)
        self.assertFalse(result['confirmed'])
        self.assertFalse(result['gates']['source_quote_coverage_inspected']['passed'])

    def test_artifact_hash_mismatch_prevents_registration_acceptance(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'registration.json'
            path.write_text(json.dumps({'kind': 'prospective_confirmation_registration'}), encoding='utf-8')
            gates = _evidence_gates({'validation_evidence': {'registration': {'path': str(path), 'sha256': '0' * 64}}}, {}, {})
            self.assertFalse(gates['prospective_registered_unseen']['passed'])
            self.assertIn('hash mismatch', gates['prospective_registered_unseen']['reason'])

    def test_trade_day_missing_from_observed_coverage_is_flagged(self):
        result = analyze_replay(replay(['2026-01-05'], [trade('2026-01-06', 1.)]))
        self.assertFalse(result['gates']['market_day_evidence_consistent']['passed'])
        self.assertEqual(result['gates']['market_day_evidence_consistent']['closed_trade_days_missing_from_input'], ['2026-01-06'])

    def test_no_closed_trades_has_no_invented_expectancy(self):
        result = analyze_replay(replay(['2026-01-05'], []))
        self.assertEqual(result['weekly_bootstrap']['status'], 'NO_CLOSED_TRADES')
        self.assertIsNone(result['weekly_bootstrap']['mean_net_R'])
        self.assertFalse(result['confirmed'])

    def test_artifact_contract_can_accept_future_registration_without_market_claim(self):
        # This tests file/hash/chronology parsing only. These local fixture receipts are
        # not an authoritative registry and make no claim of unseen market performance.
        with tempfile.TemporaryDirectory() as folder:
            folder = Path(folder)
            def write(name, value):
                path = folder / name
                path.write_text(json.dumps(value), encoding='utf-8')
                return {'path': str(path), 'sha256': hashlib.sha256(path.read_bytes()).hexdigest()}
            code = write('fixture_code.json', {'fixture': 'not production evidence'})
            registration = {'kind': 'prospective_confirmation_registration', 'dataset_id': 'FIXTURE',
                            'registered_at_ns': 1, 'confirmation_start_ns': 2, 'confirmation_end_ns': 100,
                            'data_use_policy': 'prospective_after_registration',
                            'hypotheses': ['BASE20', 'FILTER30', 'PROFILE_ONLY_CONTROL'], 'code_files': [code]}
            receipt = write('fixture_receipt.json', {'kind': 'registration_timestamp_receipt',
                            'registration_payload_sha256': registration_payload_sha256(registration),
                            'registered_at_ns': 1, 'registry_record_id': 'TEST_ONLY',
                            'registry_source': 'synthetic://parser_fixture_not_real_registry'})
            registration['timestamp_receipt'] = receipt
            reference = write('registration.json', registration)
            meta = {'dataset_id': 'FIXTURE', 'validation_evidence': {'registration': reference}}
            gates = _evidence_gates(meta, {'first_event_ns': 3, 'last_event_ns': 90}, {})
            self.assertTrue(gates['prospective_registered_unseen']['passed'])
            self.assertFalse(gates['source_quote_coverage_inspected']['passed'])
            # Changed code breaks the inspected lock rather than preserving a pass flag.
            Path(code['path']).write_text('{}', encoding='utf-8')
            changed = _evidence_gates(meta, {'first_event_ns': 3, 'last_event_ns': 90}, {})
            self.assertFalse(changed['prospective_registered_unseen']['passed'])


if __name__ == '__main__':
    unittest.main()
