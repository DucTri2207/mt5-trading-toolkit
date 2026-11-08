import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from replay_fabio_orderflow import ExecutionConfig, day_key, run_replay, run_two_step


START = int(datetime(2026, 10, 1, 14, tzinfo=timezone.utc).timestamp()) * 10**9


def event(milliseconds, bid=100., ask=100.25, sequence=None):
    return SimpleNamespace(ts_ns=START+int(milliseconds*10**6), sequence=int(milliseconds) if sequence is None else sequence,
                           contract='NQZ6', bid=bid, ask=ask, kind='Q')


def signal(at=START, direction=1, stop=99., target=102., sequence=0):
    return dict(model='TREND', known_at_ns=at, trigger_sequence=sequence, contract='NQZ6',
                direction=direction, stop=stop, target=target)


class ExecutionTests(unittest.TestCase):
    def config(self, **changes):
        return ExecutionConfig(**dict(initial_balance=10000., risk_fraction=.005, **changes))

    def test_fractional_contracts_and_nonfinite_config_rejected(self):
        with self.assertRaises(ValueError):
            self.config(max_contracts=1.5)
        with self.assertRaises(ValueError):
            self.config(latency_ns=float('nan'))
        with self.assertRaises(ValueError):
            self.config(tick_value=float('inf'))

    def test_correct_side_latency_slippage_commission_and_R0(self):
        data = [event(0), event(100), event(250), event(1000, 102., 102.25)]
        result = run_replay(data, [signal()], self.config())
        trade = result['trades'][0]
        self.assertEqual(trade['entry_ns'], START+250000000)
        self.assertEqual(trade['entry'], 100.5)
        self.assertEqual(trade['contracts'], 1)
        self.assertEqual(trade['exit'], 101.75)
        self.assertEqual(trade['initial_risk_cash'], 30.)
        self.assertEqual(trade['net_cash'], 20.)
        self.assertAlmostEqual(trade['net_R'], 2/3)
        self.assertEqual(result['balance'], 10020.)

    def test_short_uses_bid_entry_and_ask_exit(self):
        result = run_replay([event(0), event(250), event(1000, 97.5, 97.75)],
                            [signal(direction=-1, stop=101.25, target=98.)], self.config())
        trade = result['trades'][0]
        self.assertEqual((trade['entry'], trade['exit']), (99.75, 98.))
        self.assertEqual(trade['net_cash'], 30.)

    def test_gap_loss_not_clipped_to_one_R(self):
        result = run_replay([event(0), event(250), event(1000, 96., 96.25)], [signal()], self.config())
        trade = result['trades'][0]
        self.assertEqual(trade['reason'], 'STOP')
        self.assertEqual(trade['net_cash'], -100.)
        self.assertLess(trade['net_R'], -3.)

    def test_zero_latency_still_cannot_fill_before_signal(self):
        result = run_replay([event(0, sequence=0), event(0, sequence=1)], [signal()],
                            self.config(latency_ns=0))
        self.assertEqual(result['open_position']['entry_sequence'], 1)

    def test_eof_open_position_is_not_fabricated_closed_trade(self):
        result = run_replay([event(0), event(250)], [signal()], self.config())
        self.assertEqual(result['trades'], [])
        self.assertIsNotNone(result['open_position'])
        self.assertEqual(result['status'], 'UNFINISHED')
        self.assertIsNone(result['pass_probability'])

    def test_unusable_quote_cannot_fill_or_fabricate_a_gap_exit(self):
        bad = event(250, 96., 96.25)
        bad.quote_usable = False
        result = run_replay([event(0), bad, event(500), event(1000, 102., 102.25)], [signal()], self.config())
        self.assertEqual(result['trades'][0]['entry_ns'], START+500000000)
        self.assertEqual(result['trades'][0]['reason'], 'TARGET')
        self.assertEqual(result['unusable_quote_events_skipped_for_money'], 1)

    def test_unusable_last_quote_does_not_mark_equity_or_stop(self):
        bad = event(1000, 50., 50.25)
        bad.quote_usable = False
        result = run_replay([event(0), event(250), bad], [signal()], self.config())
        self.assertIsNotNone(result['open_position'])
        self.assertEqual(result['marked_equity'], 9987.5)
        self.assertEqual(result['last_usable_quote_ns'], START+250000000)
        self.assertEqual(result['prop_breaches'], [])

    def test_quote_gap_can_violate_prop_even_with_internal_stop(self):
        result = run_replay([event(0), event(250), event(1000, 70., 70.25)], [signal()], self.config())
        self.assertEqual(result['status'], 'FAILED')
        self.assertEqual(result['prop_breaches'][0]['reason'], 'PROP_DAILY')
        self.assertLess(result['daily_equity']['2026-10-01']['min_equity'], 9500.)

    def test_exit_fees_can_breach_on_final_event(self):
        result = run_replay([event(0), event(250), event(1000, 75.75, 76.)], [signal()], self.config())
        self.assertEqual(result['status'], 'FAILED')
        self.assertEqual(result['balance'], 9495.)
        self.assertEqual(result['prop_breaches'][0]['reason'], 'PROP_DAILY')

    def test_expired_signal_and_crossed_quote_are_rejected(self):
        result = run_replay([event(0), event(3000)], [signal()], self.config())
        self.assertEqual(result['rejected']['EXPIRED'], 1)
        with self.assertRaises(ValueError):
            run_replay([event(0, 101., 100.)], [], self.config())

    def test_no_fill_when_target_passed_during_latency(self):
        result = run_replay([event(0), event(250, 103., 103.25)], [signal()], self.config())
        self.assertEqual(result['rejected']['INVALID_AT_FILL'], 1)
        self.assertIsNone(result['open_position'])

    def test_prague_dst_boundary(self):
        before = int(datetime(2026, 10, 24, 22, 30, tzinfo=timezone.utc).timestamp())*10**9
        after = int(datetime(2026, 10, 25, 22, 30, tzinfo=timezone.utc).timestamp())*10**9
        self.assertEqual(day_key(before, 'Europe/Prague'), '2026-10-25')
        self.assertEqual(day_key(after, 'Europe/Prague'), '2026-10-25')

    def test_two_phase_targets_reset_capital_and_min_days(self):
        data, signals = [], []
        for day in range(8):
            at = START+day*86400*10**9
            target = 111. if day in (0, 4) else 100.1
            signals.append(signal(at=at, stop=99., target=target, sequence=0))
            for delta, bid, seq in [(0, 100., 0), (500000000, 100., 1), (1000000000, target, 2)]:
                data.append(SimpleNamespace(ts_ns=at+delta, sequence=seq, contract='NQZ6', bid=bid, ask=bid, kind='Q'))
        cfg = ExecutionConfig(initial_balance=1000., risk_fraction=.01, tick_size=.1, tick_value=.1,
                              commission_per_side=0., slippage_ticks=0)
        result = run_two_step(data, signals, cfg)
        self.assertEqual(result['status'], 'PASSED_TWO_PHASES')
        self.assertEqual(len(result['phase_1']['trading_days']), 4)
        self.assertEqual(len(result['phase_2']['trading_days']), 4)
        self.assertAlmostEqual(result['phase_1']['balance'], 1113.)
        self.assertAlmostEqual(result['phase_2']['balance'], 1113.)
        self.assertIsNone(result['pass_probability'])


if __name__ == '__main__':
    unittest.main()
