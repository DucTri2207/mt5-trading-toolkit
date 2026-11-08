"""Hand-built synthetic exchange-shaped fixtures, not market performance evidence."""
import csv
import sys
import tempfile
import unittest
from collections import Counter
from dataclasses import asdict, replace
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from fabio_orderflow_core import (Bar, Config, Event, MINUTE, Signal, _Engine,
                                 export_signals_csv, generate_signals,
                                 session_allowed, volume_profile)


def stamp(text):
    return int(datetime.fromisoformat(text).replace(tzinfo=timezone.utc).timestamp()) * 1_000_000_000


START = stamp('2026-01-05T14:00:00')


def reversion_fixture(direction=1):
    """A dense balanced profile, first break, reclaim, later LVN aggression/response."""
    records = []
    mirror = (lambda p: p) if direction == 1 else (lambda p: 210 - p)

    def add(minute, second, price, size=1, side=1, kind='T'):
        price = mirror(price)
        records.append(Event(START + minute * MINUTE + second * 1_000_000_000,
                             len(records), 'NQ_FIXTURE', price, size, side * direction,
                             price - 1, price + 1, kind))

    for minute in range(30):
        add(minute, 0, 105)
        for j, price in enumerate(range(90, 121), 1):
            add(minute, j, price, 60 if price == 110 else 50)
        add(minute, 59, 105)
    for second, price, size in [(0, 91, 100), (1, 90, 1), (2, 89, 100), (59, 89, 1)]:
        add(30, second, price, size, -1)
    add(31, 0, 89, 100)
    add(31, 1, 90, 1)
    add(31, 2, 91, 100)
    add(31, 59, 105)
    add(32, 0, 105)
    add(32, 1, 90, 20)
    add(32, 2, 91)
    return records


class ProfileTests(unittest.TestCase):
    def test_volume_profile_tie_and_value_area_are_deterministic(self):
        result = volume_profile(Counter({10: 5, 11: 1, 12: 5}), Config(value_area_fraction=.70))
        self.assertEqual(result['poc'], 10)
        self.assertEqual((result['va_low'], result['va_high']), (10, 12))
        self.assertEqual(result['lvns'], [(11, 11)])

    def test_profile_never_mutates_input_or_includes_unknown_prices(self):
        data = Counter({10: 10, 11: 1, 12: 10})
        old = dict(data)
        result = volume_profile(data)
        self.assertEqual(dict(data), old)
        self.assertEqual(set(result['volume']), {10, 11, 12})

    def test_config_rejects_nonfinite_real_and_fractional_integer_thresholds(self):
        real_names = ('tick_size', 'tick_value', 'value_area_fraction',
                      'balance_max_displacement_fraction', 'lvn_volume_ratio',
                      'response_seconds', 'minimum_target_R')
        for name in real_names:
            for value in (float('nan'), float('inf'), -float('inf'), True):
                with self.subTest(name=name, value=value), self.assertRaises(ValueError):
                    Config(**{name: value})
        integer_names = ('context_m5_bars', 'lvn_neighbor_ticks', 'acceptance_m1_closes',
                         'min_trade_size', 'response_ticks', 'max_chase_ticks',
                         'stop_buffer_ticks', 'balance_expiry_minutes', 'setup_expiry_minutes',
                         'historical_poc_days', 'max_profile_ticks')
        for name in integer_names:
            for value in (1.5, float('nan'), float('inf'), True, 0):
                with self.subTest(name=name, value=value), self.assertRaises(ValueError):
                    Config(**{name: value})
        for name in ('require_aggression', 'enforce_sessions', 'allow_unknown_side_profile_only'):
            with self.assertRaises(ValueError):
                Config(**{name: 1})


class SignalTests(unittest.TestCase):
    def setUp(self):
        self.cfg = Config(tick_size=1., tick_value=20., enforce_sessions=False)

    def test_long_reversion_waits_for_reclaim_then_second_drive(self):
        events = reversion_fixture()
        signals, diagnostics = generate_signals(events, self.cfg)
        self.assertEqual(len(signals), 1)
        signal = signals[0]
        self.assertEqual((signal.model, signal.direction), ('REVERSION', 1))
        self.assertEqual((signal.reference_price, signal.stop, signal.target), (91., 88., 110.))
        self.assertEqual(signal.known_at_ns, events[-1].ts_ns)
        self.assertLess(signal.profile_known_at_ns, signal.known_at_ns)
        self.assertEqual(diagnostics['reversion_signals'], 1)

    def test_short_reversion_is_symmetric(self):
        signals, _ = generate_signals(reversion_fixture(-1), self.cfg)
        self.assertEqual(len(signals), 1)
        self.assertEqual((signals[0].direction, signals[0].stop, signals[0].target), (-1, 122., 100.))

    def test_size_threshold_and_direction_do_not_get_inferred(self):
        events = reversion_fixture()
        without_big_print = events[:-2] + [replace(events[-2], size=19), events[-1]]
        signals, _ = generate_signals(without_big_print, self.cfg)
        self.assertEqual(signals, [])
        with self.assertRaisesRegex(ValueError, 'Unknown trade aggressor'):
            generate_signals(events[:-1] + [replace(events[-1], aggressor=0)], self.cfg)

    def test_unknown_side_opt_in_preserves_real_volume_without_anchor_or_response(self):
        cfg = replace(self.cfg, allow_unknown_side_profile_only=True)
        events = reversion_fixture()
        # All context volume remains genuine; only anchor and response have classified sides.
        context_unknown = [replace(e, aggressor=0) for e in events[:-2]] + events[-2:]
        signals, diag = generate_signals(context_unknown, cfg)
        self.assertEqual(len(signals), 1)
        self.assertEqual(signals[0].target, 110.)
        self.assertEqual(diag['unknown_side_profile_only_trades'], len(events) - 2)
        self.assertEqual(diag['classified_side_trades'], 2)
        self.assertEqual(diag['unknown_side_policy'], 'PROFILE_ONLY_OPT_IN')
        for unknown_index in (-2, -1):
            changed = list(events)
            changed[unknown_index] = replace(changed[unknown_index], aggressor=0)
            for require_aggression in (True, False):
                with self.subTest(unknown_index=unknown_index, require_aggression=require_aggression):
                    found, _ = generate_signals(changed, replace(cfg, require_aggression=require_aggression))
                    self.assertEqual(found, [])

    def test_all_unknown_trades_produce_profiles_but_no_flow_signals_even_control(self):
        events = [replace(e, aggressor=0) for e in reversion_fixture()]
        cfg = replace(self.cfg, allow_unknown_side_profile_only=True, require_aggression=False)
        signals, diag = generate_signals(events, cfg)
        self.assertEqual(signals, [])
        self.assertEqual(diag['balances_frozen'], 1)
        self.assertEqual(diag['unknown_side_profile_only_trades'], len(events))

    def test_unknown_profile_mode_keeps_prefix_invariance_and_rejects_invalid_labels(self):
        cfg = replace(self.cfg, allow_unknown_side_profile_only=True)
        events = reversion_fixture()
        events = [replace(e, aggressor=0) for e in events[:-2]] + events[-2:]
        full, _ = generate_signals(events, cfg)
        for cut in (100, len(events) - 2, len(events) - 1, len(events)):
            found, _ = generate_signals(events[:cut], cfg)
            self.assertEqual(found, [s for s in full if s.known_at_ns <= events[cut - 1].ts_ns])
        with self.assertRaisesRegex(ValueError, 'Invalid trade aggressor'):
            generate_signals([replace(events[0], aggressor=2)], cfg)

    def test_prefix_invariance_and_no_EOF_flush(self):
        events = reversion_fixture()
        full, _ = generate_signals(events, self.cfg)
        for cut in [1, 100, 989, 990, len(events) - 3, len(events) - 2, len(events) - 1, len(events)]:
            prefix = events[:cut]
            found, _ = generate_signals(prefix, self.cfg)
            expected = [s for s in full if s.known_at_ns <= prefix[-1].ts_ns]
            self.assertEqual([asdict(s) for s in found], [asdict(s) for s in expected])

    def test_quote_events_do_not_add_volume_or_trigger(self):
        events = reversion_fixture()
        quote = replace(events[-1], kind='Q', size=0, aggressor=0)
        signals, diagnostics = generate_signals(events[:-1] + [quote], self.cfg)
        self.assertEqual(signals, [])
        self.assertEqual(diagnostics['quote_events'], 1)

    def test_execution_quote_quality_flag_is_boolean_and_does_not_fabricate_or_drop_volume(self):
        events = reversion_fixture()
        expected, _ = generate_signals(events, self.cfg)
        flagged = [replace(event, quote_usable=False) for event in events]
        signals, diagnostics = generate_signals(flagged, self.cfg)
        self.assertEqual(signals, expected)
        self.assertEqual(diagnostics['trade_events'], len(events))
        self.assertEqual(diagnostics['execution_quote_unusable_events'], len(events))
        self.assertTrue(events[0].quote_usable)
        for invalid in (0, 1, 'false', None):
            with self.subTest(invalid=invalid), self.assertRaisesRegex(ValueError, 'quote_usable'):
                generate_signals([replace(events[0], quote_usable=invalid)], self.cfg)

    def test_reject_bad_order_contract_off_grid_and_crossed_quote(self):
        first = reversion_fixture()[0]
        for bad in [replace(first, sequence=first.sequence), replace(first, ts_ns=first.ts_ns - 1)]:
            with self.assertRaises(ValueError):
                generate_signals([first, bad], self.cfg)
        for bad in [replace(first, contract='OTHER'), replace(first, price=100.1), replace(first, ask=first.bid - 1)]:
            with self.assertRaises(ValueError):
                generate_signals([first, replace(bad, ts_ns=first.ts_ns + 1, sequence=1)], self.cfg)

    def test_trend_requires_known_target_and_two_closed_minutes(self):
        engine = _Engine(self.cfg)
        profile = volume_profile(Counter({100: 50, 101: 500, 102: 50}), self.cfg)
        engine.balance = dict(profile=profile, start=START - 30 * MINUTE, end=START,
                              known_at=START, first_out=0, outside_count=0,
                              leg=Counter(), reclaim_seen=False)
        engine.history.append((START - 40 * MINUTE, 120))
        first = Bar(START, 103, 106, 103, 106, Counter({103: 100, 104: 1, 105: 100, 106: 100}))
        second = Bar(START + MINUTE, 106, 108, 106, 108, Counter({106: 100, 107: 100, 108: 100}))
        engine.close_minute(first, START + MINUTE)
        self.assertIsNone(engine.arm)
        engine.close_minute(second, START + 2 * MINUTE)
        self.assertEqual(engine.arm['model'], 'TREND')
        engine.update(Event(START + 2 * MINUTE + 1_000_000_000, 10, 'NQ_FIXTURE', 104, 20, 1, 103, 105))
        engine.update(Event(START + 2 * MINUTE + 2_000_000_000, 11, 'NQ_FIXTURE', 105, 1, 1, 104, 106))
        self.assertEqual(len(engine.signals), 1)
        self.assertEqual((engine.signals[0].stop, engine.signals[0].target), (102., 120.))

    def test_target_behind_or_missing_never_becomes_fixed_R_substitute(self):
        engine = _Engine(self.cfg)
        p = volume_profile(Counter({100: 10, 101: 1, 102: 10}), self.cfg)
        engine.balance = dict(profile=p, start=START, end=START, known_at=START)
        engine.arm = dict(model='TREND', direction=1, profile=p, known_at=START,
                          expires=START + MINUTE, aggression={'at': START, 'tick': 101, 'size': 20, 'low': 101, 'high': 101})
        engine.history.append((START - MINUTE, 99))
        event = Event(START + 1_000_000_000, 1, 'NQ_FIXTURE', 102, 1, 1, 101, 103)
        engine._signal(event, 102, engine.arm['aggression'])
        self.assertEqual(engine.signals, [])
        self.assertEqual(engine.stats['reject_no_known_POC_ahead'], 1)

    def test_late_data_gap_cannot_make_stale_context_look_new(self):
        engine = _Engine(self.cfg)
        for i in range(6):
            engine.context.append(Bar(START + 5 * i * MINUTE, 100, 102, 98, 100, Counter({98: 10, 100: 20, 102: 10})))
        engine._freeze_balance(START + 35 * MINUTE)
        self.assertIsNone(engine.balance)
        self.assertEqual(engine.stats['context_stale_after_data_gap'], 1)

    def test_expired_reclaim_cannot_rearm_original_stale_trend_leg(self):
        engine = _Engine(self.cfg)
        profile = volume_profile(Counter({100: 50, 101: 500, 102: 50}), self.cfg)
        engine.balance = dict(profile=profile, start=START - 30 * MINUTE, end=START,
                              known_at=START, first_out=1, outside_count=2,
                              leg=Counter({103: 100, 104: 1, 105: 100}), reclaim_seen=True)
        engine.close_minute(Bar(START + 20 * MINUTE, 104, 105, 103, 104, Counter({104: 10})),
                            START + 21 * MINUTE)
        self.assertIsNone(engine.arm)

    def test_event_gap_cannot_complete_active_aggression_response(self):
        events = reversion_fixture()
        events[-1] = replace(events[-1], ts_ns=events[-1].ts_ns + 2 * MINUTE)
        signals, diag = generate_signals(events, self.cfg)
        self.assertEqual(signals, [])
        self.assertEqual(diag['event_gap_over_one_minute_resets'], 1)
        self.assertEqual(diag['active_narratives_invalidated_for_gap'], 1)

    def test_quote_only_missing_trade_minute_invalidates_active_setup(self):
        events = reversion_fixture()[:-1]
        anchor = events[-1]
        # Quotes show that the observer stayed alive, but a whole M1 has no trades.
        for second in range(10, 121, 10):
            at = START + 32 * MINUTE + second * 1_000_000_000
            events.append(Event(at, len(events), 'NQ_FIXTURE', 90., 0, 0, 89., 91., 'Q'))
        events.append(Event(START + 34 * MINUTE + 1_000_000_000, len(events),
                            'NQ_FIXTURE', 91., 1, 1, 90., 92.))
        signals, diag = generate_signals(events, self.cfg)
        self.assertEqual(signals, [])
        self.assertGreaterEqual(diag['missing_trade_minute_resets'], 1)
        self.assertEqual(diag['active_narratives_invalidated_for_gap'], 1)

    def test_nonadjacent_closed_minutes_cannot_count_as_consecutive_acceptance(self):
        engine = _Engine(self.cfg)
        profile = volume_profile(Counter({100: 50, 101: 500, 102: 50}), self.cfg)
        engine.balance = dict(profile=profile, start=START - 30 * MINUTE, end=START,
                              known_at=START, first_out=0, outside_count=0,
                              leg=Counter(), reclaim_seen=False)
        engine.close_minute(Bar(START, 103, 106, 103, 106,
                                Counter({103: 100, 104: 1, 105: 100, 106: 100})), START + MINUTE)
        engine.close_minute(Bar(START + 3 * MINUTE, 106, 108, 106, 108,
                                Counter({106: 100, 107: 100, 108: 100})), START + 4 * MINUTE)
        self.assertIsNone(engine.arm)
        self.assertIsNone(engine.balance)
        self.assertEqual(engine.stats['missing_trade_minute_resets'], 1)

    def test_sessions_use_DST_and_half_open_boundaries(self):
        self.assertFalse(session_allowed(stamp('2026-01-05T14:29:59'), 'TREND'))
        self.assertTrue(session_allowed(stamp('2026-01-05T14:30:00'), 'TREND'))
        self.assertFalse(session_allowed(stamp('2026-01-05T18:30:00'), 'TREND'))
        self.assertTrue(session_allowed(stamp('2026-07-06T13:30:00'), 'TREND'))
        self.assertTrue(session_allowed(stamp('2026-07-06T07:00:00'), 'REVERSION'))
        self.assertFalse(session_allowed(stamp('2026-07-05T13:30:00'), 'TREND'))


class ExportTests(unittest.TestCase):
    def test_header_only_feed_has_real_event_heartbeat_and_immutable_identity(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'signals.csv'
            _, status = export_signals_csv(path, [], 'fixture', 'SYNTHETIC_FIXTURE', START, contract='NQ_FIXTURE')
            with status.open(newline='', encoding='utf-8') as source:
                rows = list(csv.DictReader(source))
            self.assertEqual(rows[0]['signal_rows'], '0')
            self.assertEqual(rows[0]['last_event_utc'], str(START // 1_000_000_000))
            with self.assertRaises(ValueError):
                export_signals_csv(path, [], 'other', 'SYNTHETIC_FIXTURE', START, contract='NQ_FIXTURE')

    def test_signal_prefix_cannot_be_redrawn(self):
        signals, _ = generate_signals(reversion_fixture(), Config(tick_size=1., enforce_sessions=False))
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'signals.csv'
            export_signals_csv(path, signals, 'fixture', 'SYNTHETIC_FIXTURE', signals[-1].known_at_ns)
            export_signals_csv(path, signals, 'fixture', 'SYNTHETIC_FIXTURE', signals[-1].known_at_ns + MINUTE)
            with self.assertRaises(ValueError):
                export_signals_csv(path, [replace(signals[0], stop=80)], 'fixture', 'SYNTHETIC_FIXTURE', signals[-1].known_at_ns + MINUTE)

    def test_native_seconds_precision_is_rounded_up_never_before_availability(self):
        signals, _ = generate_signals(reversion_fixture(), Config(tick_size=1., enforce_sessions=False))
        signal = replace(signals[0], known_at_ns=signals[0].known_at_ns + 1)
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'signals.csv'
            _, status = export_signals_csv(path, [signal], 'fixture', 'SYNTHETIC_FIXTURE', signal.known_at_ns)
            with path.open(encoding='utf-8', newline='') as source:
                row = next(csv.DictReader(source))
            with status.open(encoding='utf-8', newline='') as source:
                heartbeat = next(csv.DictReader(source))
            self.assertEqual(int(row['known_at_utc']), signals[0].known_at_ns // 1_000_000_000 + 1)
            self.assertEqual(row['known_at_utc'], heartbeat['last_event_utc'])


if __name__ == '__main__':
    unittest.main()
