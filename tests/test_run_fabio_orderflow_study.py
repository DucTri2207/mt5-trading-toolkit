"""Synthetic integration checks only: no claimed historical performance."""
import csv
import json
import sys
import tempfile
import unittest
from dataclasses import asdict, replace
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from fabio_orderflow_core import Event
from run_fabio_orderflow_study import EVENT_FIELDS, run, sha
from test_fabio_orderflow_core import reversion_fixture


class StudyIntegrationTests(unittest.TestCase):
    def files(self, folder):
        # Shift the hand fixture into the declared London window, without changing prices.
        offset = -6 * 60 * 60 * 1_000_000_000
        events = [replace(e, ts_ns=e.ts_ns + offset) for e in reversion_fixture()]
        last = events[-1]
        events.append(Event(last.ts_ns + 500_000_000, last.sequence + 1, last.contract,
                            91., 1, 1, 90., 92.))
        events.append(Event(last.ts_ns + 1_000_000_000, last.sequence + 2, last.contract,
                            111., 0, 0, 111., 112., 'Q'))
        tape = Path(folder) / 'synthetic.csv'
        with tape.open('w', encoding='utf-8', newline='') as output:
            writer = csv.DictWriter(output, fieldnames=EVENT_FIELDS)
            writer.writeheader()
            writer.writerows({key: asdict(e)[key] for key in EVENT_FIELDS} for e in events)
        metadata = Path(folder) / 'metadata.json'
        meta = dict(dataset_id='HAND_SYNTHETIC_NOT_MARKET_EVIDENCE', source_kind='SYNTHETIC_FIXTURE',
                    contract='NQ_FIXTURE', tick_size=1., tick_value=20.,
                    source_url='synthetic://hand_fixture_not_market_evidence',
                    events_sha256=sha(tape), full_quote_updates=False, complete_sessions=0)
        metadata.write_text(json.dumps(meta), encoding='utf-8')
        return tape, metadata

    def test_all_declared_variants_export_and_replay_without_claiming_edge(self):
        with tempfile.TemporaryDirectory() as folder:
            tape, metadata = self.files(folder)
            output = Path(folder) / 'study'
            result = run(tape, metadata, output)
            self.assertEqual(result['cost_risk_scenarios'], 12)
            self.assertEqual(result['diagnostics']['BASE20']['signals'], 1)
            self.assertEqual(result['diagnostics']['FILTER30']['signals'], 0)
            self.assertEqual(result['diagnostics']['PROFILE_ONLY_CONTROL']['signals'], 1)
            self.assertTrue(result['technical_integration_only'])
            self.assertFalse(result['historical_edge_confirmed'])
            self.assertFalse(result['credible_prop_pass_evidence'])
            self.assertIsNone(result['pass_probability'])
            self.assertTrue(any(row['closed_trades'] == 1 for row in result['rows']))
            with (output / 'BASE20_signals.csv').open(encoding='utf-8', newline='') as source:
                exported = list(csv.DictReader(source))
            self.assertEqual(exported[0]['source_kind'], 'SYNTHETIC_FIXTURE')
            self.assertEqual(exported[0]['model'], 'REVERSION')
            # An identical replay obeys the existing frozen experiment and immutable exports.
            again = run(tape, metadata, output)
            self.assertEqual(again['rows'], result['rows'])

    def test_changed_tape_hash_is_rejected_before_performance(self):
        with tempfile.TemporaryDirectory() as folder:
            tape, metadata = self.files(folder)
            tape.write_text(tape.read_text(encoding='utf-8') + '\n', encoding='utf-8')
            with self.assertRaisesRegex(ValueError, 'hash differs'):
                run(tape, metadata, Path(folder) / 'study')


if __name__ == '__main__':
    unittest.main()
