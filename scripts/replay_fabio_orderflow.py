"""Event-level research execution and FTMO CFD 2-Step benchmark; never sends orders.

Prices must already be in the SAME instrument as the signal. NQ fills are not CFD fills.
Cost/risk defaults below are declared research assumptions, not verified account terms.
"""
from __future__ import annotations

import math
from collections import Counter
from dataclasses import asdict, dataclass, replace
from datetime import datetime, timezone
from functools import lru_cache
from zoneinfo import ZoneInfo


@dataclass(frozen=True)
class ExecutionConfig:
    initial_balance: float = 100000.
    risk_fraction: float = .0025
    tick_size: float = .25
    tick_value: float = 5.
    commission_per_side: float = 2.5
    slippage_ticks: int = 1
    latency_ns: int = 250000000
    entry_expiry_ns: int = 2000000000
    max_hold_ns: int = 30 * 60 * 1000000000
    max_contracts: int = 20
    internal_daily_loss_fraction: float = .02
    internal_day_zone: str = 'America/New_York'
    prop_day_zone: str = 'Europe/Prague'
    prop_daily_fraction: float = .05
    prop_total_fraction: float = .10
    target_fraction: float | None = None
    min_trading_days: int = 4

    def __post_init__(self):
        integer_fields = ('slippage_ticks', 'latency_ns', 'entry_expiry_ns', 'max_hold_ns',
                          'max_contracts', 'min_trading_days')
        if any(type(getattr(self, name)) is not int for name in integer_fields):
            raise ValueError('Contract size, delays, slippage and minimum days require integers')
        positive = (self.initial_balance, self.tick_size, self.tick_value,
                    self.internal_daily_loss_fraction, self.prop_daily_fraction,
                    self.prop_total_fraction)
        if not all(math.isfinite(v) and v > 0 for v in positive):
            raise ValueError('Capital, tick and loss limits must be finite and positive')
        if not 0 < self.risk_fraction <= self.internal_daily_loss_fraction:
            raise ValueError('Risk fraction must fit within the internal daily limit')
        if self.commission_per_side < 0 or not math.isfinite(self.commission_per_side):
            raise ValueError('Commission must be finite and nonnegative')
        if min(self.slippage_ticks, self.latency_ns) < 0 or self.entry_expiry_ns < self.latency_ns:
            raise ValueError('Negative slippage, latency or entry expiry')
        if self.max_hold_ns <= 0 or self.max_contracts < 1 or self.min_trading_days < 1:
            raise ValueError('Holding period, sizing cap and trading days must be positive')
        if self.target_fraction is not None and not 0 < self.target_fraction < 1:
            raise ValueError('Invalid phase target')
        ZoneInfo(self.internal_day_zone)
        ZoneInfo(self.prop_day_zone)


@lru_cache(maxsize=50000)
def _day_at_second(seconds, zone):
    return datetime.fromtimestamp(seconds, timezone.utc).astimezone(ZoneInfo(zone)).date().isoformat()


def day_key(ts_ns, zone):
    return _day_at_second(ts_ns // 1000000000, zone)


def _get(value, key):
    return value[key] if isinstance(value, dict) else getattr(value, key)


def _prop_loss_reason(equity, day_start_balance, cfg):
    if equity < cfg.initial_balance * (1 - cfg.prop_total_fraction):
        return 'PROP_TOTAL'
    if equity < day_start_balance - cfg.initial_balance * cfg.prop_daily_fraction:
        return 'PROP_DAILY'
    return None


def run_replay(events, signals, config=ExecutionConfig()):
    """Consume every quote/trade event in order; fills strictly follow signal availability.

    SL/TP are market exits when the correct-side BBO reaches the barrier. No queue/fill
    guarantee is assumed for resting limits. Reports exact observed equity minima.
    """
    cfg = config
    point_value = cfg.tick_value / cfg.tick_size
    slip = cfg.tick_size * cfg.slippage_ticks
    signals = list(signals)
    signal_keys = [(_get(s, 'known_at_ns'), _get(s, 'trigger_sequence')) for s in signals]
    if signal_keys != sorted(signal_keys) or len(signal_keys) != len(set(signal_keys)):
        raise ValueError('Signals must have unique sorted (known time, trigger sequence) keys')
    balance = cfg.initial_balance
    high_water = balance
    max_dd = 0.
    internal_day = prop_day = None
    internal_start = prop_start = balance
    locked = False
    position = None
    trades, breaches, equity_extremes = [], [], {}
    rejected = Counter()
    trading_days = set()
    pending = []
    next_signal = 0
    previous_key = None
    contract = None
    last_event = None
    last_usable_event = None
    last_marked_equity = balance
    unusable_quotes = 0
    finished_at = None
    finish_reason = None

    def mark(event):
        nonlocal high_water, max_dd, last_marked_equity
        equity = balance
        if position:
            quote = event.bid if position['direction'] > 0 else event.ask
            equity += position['direction'] * (quote - position['entry']) * point_value * position['contracts']
        high_water = max(high_water, equity)
        max_dd = max(max_dd, high_water - equity)
        row = equity_extremes.setdefault(prop_day, {'start_balance': prop_start, 'min_equity': equity,
                                                   'max_equity': equity, 'last_balance': balance})
        row['min_equity'] = min(row['min_equity'], equity)
        row['max_equity'] = max(row['max_equity'], equity)
        row['last_balance'] = balance
        last_marked_equity = equity
        return equity

    def close(event, reason):
        nonlocal position, balance
        d = position['direction']
        price = (event.bid if d > 0 else event.ask) - d * slip
        gross = d * (price - position['entry']) * point_value * position['contracts']
        exit_fee = cfg.commission_per_side * position['contracts']
        balance += gross - exit_fee
        net = gross - 2 * exit_fee
        trades.append({**position, 'exit_ns': event.ts_ns, 'exit_sequence': event.sequence,
                       'exit': price, 'reason': reason, 'net_cash': net,
                       'commission_cash': 2 * exit_fee, 'net_R': net / position['initial_risk_cash'],
                       'balance_after': balance})
        position = None

    for index, event in enumerate(events):
        key = (event.ts_ns, event.sequence)
        if previous_key is not None and key <= previous_key:
            raise ValueError('Events require strictly increasing timestamp/sequence keys')
        if not all(math.isfinite(v) and v > 0 for v in (event.bid, event.ask)) or event.bid > event.ask:
            raise ValueError('Invalid BBO: missing, nonpositive or crossed')
        if contract is None:
            contract = event.contract
        if not contract or event.contract != contract:
            raise ValueError('Replay requires one exact contract; split rolls into explicit segments')
        if getattr(event, 'kind', 'T') not in ('T', 'Q'):
            raise ValueError('Unknown event kind')
        previous_key = key
        last_event = event
        today = day_key(event.ts_ns, cfg.internal_day_zone)
        prop_today = day_key(event.ts_ns, cfg.prop_day_zone)
        if today != internal_day:
            internal_day, internal_start, locked = today, balance, False
        if prop_today != prop_day:
            prop_day, prop_start = prop_today, balance
        quote_usable = getattr(event, 'quote_usable', True)
        if type(quote_usable) is not bool:
            raise ValueError('quote_usable must be an explicit boolean')
        if not quote_usable:
            unusable_quotes += 1
            continue
        last_usable_event = event
        equity = mark(event)
        prop_reason = _prop_loss_reason(equity, prop_start, cfg)
        if prop_reason:
            breaches.append({'time_ns': event.ts_ns, 'reason': prop_reason, 'equity': equity,
                             'day_start_balance': prop_start})
            if position:
                close(event, prop_reason)
                mark(event)
            finish_reason, finished_at = 'FAILED', index
            break
        if position:
            d = position['direction']
            quote = event.bid if d > 0 else event.ask
            reason = ('STOP' if d * (quote - position['stop']) <= 0
                      else 'TARGET' if d * (quote - position['target']) >= 0
                      else 'INTERNAL_DAILY' if equity <= internal_start - cfg.initial_balance * cfg.internal_daily_loss_fraction
                      else 'TIME' if event.ts_ns >= position['entry_ns'] + cfg.max_hold_ns else None)
            if reason:
                close(event, reason)
                equity = mark(event)
                post_fee_reason = _prop_loss_reason(equity, prop_start, cfg)
                if post_fee_reason:
                    breaches.append({'time_ns': event.ts_ns, 'reason': post_fee_reason,
                                     'equity': equity, 'day_start_balance': prop_start})
                    finish_reason, finished_at = 'FAILED', index
                    break
        if equity <= internal_start - cfg.initial_balance * cfg.internal_daily_loss_fraction:
            locked = True
        if cfg.target_fraction is not None and position is None and len(trading_days) >= cfg.min_trading_days:
            if balance >= cfg.initial_balance * (1 + cfg.target_fraction):
                finish_reason, finished_at = 'PASSED', index
                break
        while next_signal < len(signals) and _get(signals[next_signal], 'known_at_ns') <= event.ts_ns:
            pending.append(signals[next_signal])
            next_signal += 1
        for signal in pending[:]:
            known = _get(signal, 'known_at_ns')
            trigger_sequence = _get(signal, 'trigger_sequence')
            if event.ts_ns < known + cfg.latency_ns or key <= (known, trigger_sequence):
                continue
            pending.remove(signal)
            if event.ts_ns > known + cfg.entry_expiry_ns:
                rejected['EXPIRED'] += 1
                continue
            if _get(signal, 'contract') != contract:
                raise ValueError('Signal contract differs from execution instrument')
            if position or locked:
                rejected['POSITION_OR_DAILY_LOCK'] += 1
                continue
            d, stop, target = (_get(signal, k) for k in ('direction', 'stop', 'target'))
            if d not in (-1, 1) or not all(math.isfinite(v) and v > 0 for v in (stop, target)):
                raise ValueError('Invalid signal direction/levels')
            entry = (event.ask if d > 0 else event.bid) + d * slip
            executable = event.bid if d > 0 else event.ask
            risk_points = d * (entry - stop)
            if risk_points <= 0 or d * (executable - stop) <= 0 or d * (target - entry) <= 0:
                rejected['INVALID_AT_FILL'] += 1
                continue
            per_contract_budget = risk_points * point_value + 2 * cfg.commission_per_side + slip * point_value
            room = internal_start - cfg.initial_balance * cfg.internal_daily_loss_fraction
            budget = min(cfg.initial_balance * cfg.risk_fraction, max(0., equity - room))
            size = min(cfg.max_contracts, math.floor((budget + 1e-10) / per_contract_budget))
            if size < 1:
                rejected['SIZE_BELOW_ONE_CONTRACT'] += 1
                continue
            position = {'model': _get(signal, 'model'), 'contract': contract, 'direction': d,
                        'known_at_ns': known, 'trigger_sequence': trigger_sequence,
                        'entry_ns': event.ts_ns, 'entry_sequence': event.sequence, 'entry': entry,
                        'stop': stop, 'target': target, 'contracts': size,
                        'initial_risk_cash': risk_points * point_value * size}
            balance -= cfg.commission_per_side * size
            trading_days.add(prop_day)
            equity = mark(event)
            post_fee_reason = _prop_loss_reason(equity, prop_start, cfg)
            if post_fee_reason:
                breaches.append({'time_ns': event.ts_ns, 'reason': post_fee_reason,
                                 'equity': equity, 'day_start_balance': prop_start})
                close(event, post_fee_reason)
                mark(event)
                finish_reason, finished_at = 'FAILED', index
                break
        if finish_reason:
            break

    # Do not invent an execution at EOF: preserve an open position and mark its equity.
    equity = last_marked_equity
    if position:
        rejected['OPEN_AT_DATA_END'] += 1
    rejected['PENDING_AT_DATA_END'] += len(pending) + len(signals) - next_signal
    gains = sum(max(t['net_cash'], 0.) for t in trades)
    losses = -sum(min(t['net_cash'], 0.) for t in trades)
    return {'config': asdict(cfg), 'contract': contract, 'trades': trades, 'balance': balance,
            'marked_equity': equity, 'open_position': position, 'max_observed_equity_dd_cash': max_dd,
            'daily_equity': equity_extremes, 'prop_breaches': breaches, 'rejected': dict(rejected),
            'trading_days': sorted(trading_days), 'status': finish_reason or 'UNFINISHED',
            'finished_event_index': finished_at, 'last_event_ns': last_event.ts_ns if last_event else None,
            'last_usable_quote_ns': last_usable_event.ts_ns if last_usable_event else None,
            'unusable_quote_events_skipped_for_money': unusable_quotes,
            'net_closed_cash': sum(t['net_cash'] for t in trades),
            'PF': gains / losses if losses else None,
            'win_rate': sum(t['net_cash'] > 0 for t in trades) / len(trades) if trades else None,
            'mean_net_R': sum(t['net_R'] for t in trades) / len(trades) if trades else None,
            'pass_probability': None,
            'limitations': ['Observed BBO replay only; source gaps/partial coverage require a separate data audit.',
                            'Unusable quote events never mark equity, trigger exits or fill entries; unobserved exposure remains unknown.',
                            'Market exits use observed BBO plus declared adverse slippage, not guaranteed fills.',
                            'No adaptive BE/trailing: fixed known POC and initial stop operationalization.',
                            'Futures execution is not evidence of execution on a CFD prop account.']}


def run_two_step(events, signals, config=ExecutionConfig()):
    """Idealized sequential benchmark, with phase-2 reset no earlier than the next prop day."""
    events, signals = list(events), list(signals)
    first = run_replay(events, signals, replace(config, target_fraction=.10))
    result = {'benchmark': 'FTMO CFD 2-Step money rules on supplied instrument; NOT account certification',
              'phase_1': first, 'phase_2': None, 'funded': None, 'status': first['status'],
              'pass_probability': None, 'administrative_delay': 'next prop calendar day, assumption'}
    if first['status'] != 'PASSED':
        return result
    end = first['finished_event_index']
    passed_day = day_key(events[end].ts_ns, config.prop_day_zone)
    rest = [e for e in events[end+1:] if day_key(e.ts_ns, config.prop_day_zone) > passed_day]
    if not rest:
        result['status'] = 'UNFINISHED_PHASE_2'
        return result
    cutoff = rest[0].ts_ns
    remaining_signals = [s for s in signals if _get(s, 'known_at_ns') >= cutoff]
    second = run_replay(rest, remaining_signals, replace(config, target_fraction=.05))
    result['phase_2'] = second
    result['status'] = ('PASSED_TWO_PHASES' if second['status'] == 'PASSED'
                        else 'FAILED_PHASE_2' if second['status'] == 'FAILED' else 'UNFINISHED_PHASE_2')
    if second['status'] == 'PASSED':
        remaining = rest[second['finished_event_index']+1:]
        if remaining:
            cutoff = remaining[0].ts_ns
            result['funded'] = run_replay(remaining, [s for s in signals if _get(s, 'known_at_ns') >= cutoff],
                                          replace(config, target_fraction=None))
    return result
