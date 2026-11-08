"""Causal mechanical operationalization of the Fabio order-flow video.

The frozen spec records every added rule. Synthetic fixtures test the program,
not a market edge. No broker connections or order placement occur here.
"""
from __future__ import annotations

import csv
import math
import os
from collections import Counter, deque
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from numbers import Integral, Real
from pathlib import Path
from zoneinfo import ZoneInfo

MINUTE = 60_000_000_000


@dataclass(frozen=True)
class Event:
    ts_ns: int
    sequence: int
    contract: str
    price: float
    size: int
    aggressor: int
    bid: float
    ask: float
    kind: str = 'T'
    quote_usable: bool = True


@dataclass(frozen=True)
class Config:
    tick_size: float = .25
    tick_value: float = 5.
    expected_contract: str = ''
    context_m5_bars: int = 6
    value_area_fraction: float = .70
    balance_max_displacement_fraction: float = .50
    lvn_neighbor_ticks: int = 2
    lvn_volume_ratio: float = .50
    acceptance_m1_closes: int = 2
    min_trade_size: int = 20
    require_aggression: bool = True
    response_ticks: int = 1
    max_chase_ticks: int = 2
    response_seconds: float = 5.
    stop_buffer_ticks: int = 2
    minimum_target_R: float = 1.5
    balance_expiry_minutes: int = 60
    setup_expiry_minutes: int = 15
    historical_poc_days: int = 3
    max_profile_ticks: int = 4096
    enforce_sessions: bool = True
    allow_unknown_side_profile_only: bool = False

    def __post_init__(self):
        real_fields = ('tick_size', 'tick_value', 'value_area_fraction',
                       'balance_max_displacement_fraction', 'lvn_volume_ratio',
                       'response_seconds', 'minimum_target_R')
        if any(isinstance(getattr(self, name), bool) or not isinstance(getattr(self, name), Real)
               or not math.isfinite(getattr(self, name)) for name in real_fields):
            raise ValueError('Configuration real-valued parameters must be finite numbers')
        integer_fields = ('context_m5_bars', 'lvn_neighbor_ticks', 'acceptance_m1_closes',
                          'min_trade_size', 'response_ticks', 'max_chase_ticks',
                          'stop_buffer_ticks', 'balance_expiry_minutes', 'setup_expiry_minutes',
                          'historical_poc_days', 'max_profile_ticks')
        if any(isinstance(getattr(self, name), bool) or not isinstance(getattr(self, name), Integral)
               or getattr(self, name) < 1 for name in integer_fields):
            raise ValueError('Configuration thresholds must be positive integers')
        if any(type(value) is not bool for value in
               (self.require_aggression, self.enforce_sessions, self.allow_unknown_side_profile_only)):
            raise ValueError('Configuration switches must be explicit booleans')
        if not isinstance(self.expected_contract, str):
            raise ValueError('expected_contract must be a string')
        if self.tick_size <= 0 or self.tick_value <= 0:
            raise ValueError('Positive contract tick size/value required')
        if not 0 < self.value_area_fraction <= 1 or not 0 < self.lvn_volume_ratio < 1:
            raise ValueError('Invalid profile fractions')
        if min(self.context_m5_bars, self.lvn_neighbor_ticks, self.acceptance_m1_closes,
               self.min_trade_size, self.response_ticks, self.stop_buffer_ticks) < 1:
            raise ValueError('Positive integer thresholds required')
        if self.max_chase_ticks < self.response_ticks or self.response_seconds <= 0:
            raise ValueError('Invalid price-response thresholds')
        if not 0 <= self.balance_max_displacement_fraction <= 1 or self.minimum_target_R <= 0:
            raise ValueError('Invalid balance/target threshold')
        if min(self.balance_expiry_minutes, self.setup_expiry_minutes, self.historical_poc_days) <= 0:
            raise ValueError('Positive history and setup lifetimes required')


@dataclass(frozen=True)
class Signal:
    model: str
    known_at_ns: int
    contract: str
    direction: int
    reference_price: float
    stop: float
    target: float
    lvn_low: float
    lvn_high: float
    poc: float
    balance_low: float
    balance_high: float
    profile_known_at_ns: int
    trigger_size: int
    trigger_sequence: int
    balance_start_ns: int
    balance_end_ns: int


@dataclass
class Bar:
    start_ns: int
    open: int
    high: int
    low: int
    close: int
    volume: Counter

    def add(self, tick, size):
        self.high = max(self.high, tick)
        self.low = min(self.low, tick)
        self.close = tick
        self.volume[tick] += size


def price_tick(price, tick_size):
    if not math.isfinite(price) or price <= 0:
        raise ValueError('Prices must be finite and positive')
    tick = round(price / tick_size)
    if abs(price - tick * tick_size) > max(1e-8, tick_size * 1e-6):
        raise ValueError('Off-grid contract price')
    return tick


def volume_profile(volumes, config=Config()):
    """Integer-tick POC, deterministic 70% value area and merged internal LVNs."""
    volume = Counter({int(k): int(v) for k, v in volumes.items() if v > 0})
    if not volume:
        raise ValueError('Empty executed-volume profile')
    low, high = min(volume), max(volume)
    if high - low + 1 > config.max_profile_ticks:
        raise ValueError('Profile too wide; investigate contract scale or data')
    poc = min(volume, key=lambda k: (-volume[k], k))
    va_low = va_high = poc
    covered, needed = volume[poc], sum(volume.values()) * config.value_area_fraction
    while covered < needed:
        left = volume[va_low - 1] if va_low > low else -1
        right = volume[va_high + 1] if va_high < high else -1
        if left >= right:
            va_low -= 1
            covered += max(left, 0)
        else:
            va_high += 1
            covered += max(right, 0)
    candidates = []
    n = config.lvn_neighbor_ticks
    for tick in range(low + 1, high):
        left = max(volume[j] for j in range(max(low, tick - n), tick))
        right = max(volume[j] for j in range(tick + 1, min(high, tick + n) + 1))
        if min(left, right) > 0 and volume[tick] <= config.lvn_volume_ratio * min(left, right):
            if candidates and candidates[-1][1] == tick - 1:
                candidates[-1] = (candidates[-1][0], tick)
            else:
                candidates.append((tick, tick))
    return {'poc': poc, 'va_low': va_low, 'va_high': va_high, 'lvns': candidates,
            'volume': dict(volume), 'low': low, 'high': high}


def session_allowed(ts_ns, model):
    if model == 'TREND':
        local = datetime.fromtimestamp(ts_ns / 1e9, timezone.utc).astimezone(ZoneInfo('America/New_York'))
        return local.weekday() < 5 and 570 <= local.hour * 60 + local.minute < 810
    if model == 'REVERSION':
        local = datetime.fromtimestamp(ts_ns / 1e9, timezone.utc).astimezone(ZoneInfo('Europe/London'))
        return local.weekday() < 5 and 480 <= local.hour * 60 + local.minute < 660
    raise ValueError('Unknown model')


def _merge_bars(bars):
    volumes = Counter()
    for bar in bars:
        volumes.update(bar.volume)
    return Bar(bars[0].start_ns, bars[0].open, max(b.high for b in bars),
               min(b.low for b in bars), bars[-1].close, volumes)


class _Engine:
    def __init__(self, config):
        self.cfg = config
        self.minute = None
        self.minutes = deque(maxlen=5)
        self.context = deque(maxlen=config.context_m5_bars)
        self.history = deque()
        self.balance = None
        self.arm = None
        self.last_context_end = -1
        self.last_event_ns = None
        self.observed_minute = None
        self.observed_minute_had_trade = False
        self.last_closed_minute = None
        self.stats = Counter()
        self.signals = []

    def _invalidate_for_gap(self, reason):
        if self.balance is not None or self.arm is not None:
            self.stats['active_narratives_invalidated_for_gap'] += 1
        self.stats[reason] += 1
        self.balance = self.arm = self.minute = None
        self.minutes.clear()
        self.context.clear()
        self.last_context_end = -1
        self.last_closed_minute = None

    def _freeze_balance(self, known_at):
        if self.balance is not None or len(self.context) < self.cfg.context_m5_bars:
            return
        bars = list(self.context)
        end = bars[-1].start_ns + 5 * MINUTE
        if end == self.last_context_end or any(b.start_ns - a.start_ns != 5 * MINUTE for a, b in zip(bars, bars[1:])):
            return
        self.last_context_end = end
        if known_at > end + MINUTE:
            self.stats['context_stale_after_data_gap'] += 1
            return
        joined = _merge_bars(bars)
        width = joined.high - joined.low
        if width <= 0 or abs(joined.close - joined.open) > self.cfg.balance_max_displacement_fraction * width:
            self.stats['context_not_balanced'] += 1
            return
        profile = volume_profile(joined.volume, self.cfg)
        self.balance = dict(profile=profile, start=bars[0].start_ns, end=end, known_at=known_at,
                            first_out=0, outside_count=0, leg=Counter(), reclaim_seen=False)
        self.history.append((known_at, profile['poc']))
        self.stats['balances_frozen'] += 1

    def _arm(self, model, direction, volume, known_at):
        profile = volume_profile(volume, self.cfg)
        if not profile['lvns']:
            self.stats['setup_without_LVN'] += 1
            return
        self.arm = dict(model=model, direction=direction, profile=profile, known_at=known_at,
                        expires=known_at + self.cfg.setup_expiry_minutes * MINUTE,
                        aggression=None)
        self.stats[model.lower() + '_armed'] += 1

    def close_minute(self, bar, known_at):
        if known_at > bar.start_ns + 2 * MINUTE:
            self._invalidate_for_gap('stale_minute_close_resets')
            return
        if self.last_closed_minute is not None:
            if bar.start_ns <= self.last_closed_minute:
                raise ValueError('Closed M1 bars must advance in time')
            if bar.start_ns != self.last_closed_minute + MINUTE:
                self._invalidate_for_gap('missing_trade_minute_resets')
        self.last_closed_minute = bar.start_ns
        self.minutes.append(bar)
        if bar.start_ns // MINUTE % 5 == 4:
            minutes = list(self.minutes)
            if len(minutes) == 5 and all(b.start_ns - a.start_ns == MINUTE for a, b in zip(minutes, minutes[1:])):
                self.context.append(_merge_bars(minutes))
                self._freeze_balance(known_at)
        balance = self.balance
        if balance is None or bar.start_ns + MINUTE <= balance['end']:
            return
        p = balance['profile']
        direction = 1 if bar.close >= p['va_high'] + 1 else -1 if bar.close <= p['va_low'] - 1 else 0
        if not balance['first_out']:
            if direction:
                balance.update(first_out=direction, outside_count=1, leg=Counter(bar.volume))
        elif direction == balance['first_out'] and not balance['reclaim_seen']:
            balance['outside_count'] += 1
            balance['leg'].update(bar.volume)
        elif direction == 0 and not balance['reclaim_seen']:
            balance['leg'].update(bar.volume)
            balance['reclaim_seen'] = True
            self.arm = None
            self._arm('REVERSION', -balance['first_out'], balance['leg'], known_at)
        elif direction and direction != balance['first_out']:
            # A move through both sides invalidates the frozen narrative.
            self.balance = self.arm = None
            self.stats['balance_crossed_both_sides'] += 1
            return
        if (balance['outside_count'] == self.cfg.acceptance_m1_closes and direction
                and not balance['reclaim_seen'] and self.arm is None):
            self._arm('TREND', direction, balance['leg'], known_at)

    def update(self, event):
        cfg = self.cfg
        start = event.ts_ns // MINUTE * MINUTE
        if self.last_event_ns is not None and event.ts_ns - self.last_event_ns > MINUTE:
            self._invalidate_for_gap('event_gap_over_one_minute_resets')
        elif self.observed_minute is not None and start > self.observed_minute:
            if start - self.observed_minute > MINUTE or not self.observed_minute_had_trade:
                self._invalidate_for_gap('missing_trade_minute_resets')
        if start != self.observed_minute:
            self.observed_minute = start
            self.observed_minute_had_trade = False
        self.last_event_ns = event.ts_ns
        cutoff = event.ts_ns - cfg.historical_poc_days * 1440 * MINUTE
        while self.history and self.history[0][0] < cutoff:
            self.history.popleft()
        if self.balance and event.ts_ns > self.balance['known_at'] + cfg.balance_expiry_minutes * MINUTE:
            self.balance = self.arm = None
            self.stats['balance_expired'] += 1
        if self.arm and event.ts_ns > self.arm['expires']:
            self.arm = None
            self.stats['setup_expired'] += 1
        if self.minute is not None and start > self.minute.start_ns:
            self.close_minute(self.minute, event.ts_ns)
            self.minute = None
        if event.kind == 'Q':
            return
        self.observed_minute_had_trade = True
        tick = price_tick(event.price, cfg.tick_size)
        if self.minute is None:
            self.minute = Bar(start, tick, tick, tick, tick, Counter({tick: event.size}))
        else:
            self.minute.add(tick, event.size)
        arm = self.arm
        if arm is None or event.ts_ns <= arm['known_at']:
            return
        if cfg.enforce_sessions and not session_allowed(event.ts_ns, arm['model']):
            self.stats['trigger_outside_session'] += 1
            return
        direction = arm['direction']
        anchor = arm['aggression']
        if anchor is not None:
            elapsed = event.ts_ns - anchor['at']
            response = direction * (tick - anchor['tick'])
            if elapsed > cfg.response_seconds * 1e9 or response < -cfg.stop_buffer_ticks:
                arm['aggression'] = None
                self.stats['aggression_expired_or_invalidated'] += 1
            elif cfg.response_ticks <= response <= cfg.max_chase_ticks and event.aggressor == direction:
                self._signal(event, tick, anchor)
                return
        if (arm['aggression'] is None and event.aggressor != 0
                and (not cfg.require_aggression or (event.aggressor == direction and event.size >= cfg.min_trade_size))):
            for low, high in arm['profile']['lvns']:
                if low <= tick <= high:
                    arm['aggression'] = dict(at=event.ts_ns, tick=tick, size=event.size, low=low, high=high)
                    self.stats['LVN_aggression_anchors'] += 1
                    break

    def _signal(self, event, tick, anchor):
        arm, balance, cfg = self.arm, self.balance, self.cfg
        direction = arm['direction']
        stop = anchor['tick'] - direction * cfg.stop_buffer_ticks
        risk = direction * (tick - stop)
        if arm['model'] == 'REVERSION':
            target = balance['profile']['poc']
        else:
            ahead = [poc for at, poc in self.history if at < arm['known_at'] and direction * (poc - tick) > 0]
            if not ahead:
                self.stats['reject_no_known_POC_ahead'] += 1
                arm['aggression'] = None
                return
            target = min(ahead, key=lambda p: direction * (p - tick))
        if risk <= 0 or direction * (target - tick) < cfg.minimum_target_R * risk:
            self.stats['reject_POC_room'] += 1
            arm['aggression'] = None
            return
        scale = cfg.tick_size
        self.signals.append(Signal(arm['model'], event.ts_ns, event.contract, direction,
                                   tick * scale, stop * scale, target * scale,
                                   anchor['low'] * scale, anchor['high'] * scale, target * scale,
                                   balance['profile']['va_low'] * scale, balance['profile']['va_high'] * scale,
                                   arm['known_at'], anchor['size'], event.sequence,
                                   balance['start'], balance['end']))
        self.stats[arm['model'].lower() + '_signals'] += 1
        self.balance = self.arm = None


def generate_signals(events, config=Config()):
    """Return signals/counters; side 0 needs explicit profile-only admission.

    The opt-in preserves genuine volume from documented-classification datasets;
    it neither classifies trades nor turns unknown trades into order-flow evidence.
    """
    engine = _Engine(config)
    previous = None
    contract = config.expected_contract
    for event in events:
        engine.stats['events'] += 1
        if type(event.quote_usable) is not bool:
            raise ValueError('quote_usable must be an explicit boolean')
        if not event.quote_usable:
            engine.stats['execution_quote_unusable_events'] += 1
        if (any(isinstance(v, bool) or not isinstance(v, Integral) or v < 0
                for v in (event.ts_ns, event.sequence))
                or not isinstance(event.contract, str) or not event.contract):
            raise ValueError('Invalid event identity')
        key = (event.ts_ns, event.sequence)
        if previous is not None and key <= previous:
            raise ValueError('Events must have strictly increasing (timestamp, sequence)')
        previous = key
        contract = contract or event.contract
        if event.contract != contract:
            raise ValueError('Interleaved/changed contract: split runs explicitly')
        if not all(isinstance(x, Real) and not isinstance(x, bool) and math.isfinite(x) and x > 0
                   for x in (event.bid, event.ask)) or event.ask < event.bid:
            raise ValueError('Invalid contemporaneous BBO')
        price_tick(event.bid, config.tick_size)
        price_tick(event.ask, config.tick_size)
        if event.kind == 'Q':
            if event.size != 0 or event.aggressor != 0:
                raise ValueError('Quote-only event cannot carry executed size or side')
            engine.stats['quote_events'] += 1
        elif event.kind == 'T':
            if isinstance(event.size, bool) or not isinstance(event.size, Integral) or event.size <= 0:
                raise ValueError('Positive integer executed contract quantity required')
            if isinstance(event.aggressor, bool) or not isinstance(event.aggressor, Integral) or event.aggressor not in (-1, 0, 1):
                raise ValueError('Invalid trade aggressor; refusing inferred order flow')
            if event.aggressor == 0 and not config.allow_unknown_side_profile_only:
                raise ValueError('Unknown trade aggressor; refusing inferred order flow')
            price_tick(event.price, config.tick_size)
            engine.stats['trade_events'] += 1
            engine.stats['unknown_side_profile_only_trades' if event.aggressor == 0 else 'classified_side_trades'] += 1
        else:
            raise ValueError('Event kind must be T or Q')
        engine.update(event)
    diagnostics = dict(engine.stats)
    diagnostics.update(signals=len(engine.signals), final_partial_bar_not_flushed=True,
                       contract=contract, version='fabio_orderflow_v1',
                       unknown_side_policy='PROFILE_ONLY_OPT_IN' if config.allow_unknown_side_profile_only else 'REJECT_RUN',
                       operationalization_not_exact_discretionary_replica=True)
    return engine.signals, diagnostics


def predeclared_configs(config=Config()):
    return {'BASE20': replace(config, min_trade_size=20, require_aggression=True),
            'FILTER30': replace(config, min_trade_size=30, require_aggression=True),
            'PROFILE_ONLY_CONTROL': replace(config, min_trade_size=20, require_aggression=False)}


SIGNAL_CSV_FIELDS = ['schema_version', 'source_kind', 'dataset_id', 'contract', 'known_at_utc',
                     'model', 'direction', 'reference_price', 'stop', 'target', 'lvn_low',
                     'lvn_high', 'poc', 'balance_low', 'balance_high']
STATUS_CSV_FIELDS = ['schema_version', 'source_kind', 'dataset_id', 'contract', 'last_event_utc', 'signal_rows']


def _atomic_csv(path, fields, rows):
    temporary = Path(str(path) + '.tmp')
    with temporary.open('w', encoding='utf-8', newline='') as output:
        writer = csv.DictWriter(output, fieldnames=fields, lineterminator='\n')
        writer.writeheader()
        writer.writerows(rows)
    os.replace(temporary, path)


def export_signals_csv(path, signals, dataset_id, source_kind, last_event_ns, *, contract=None):
    """Publish an immutable signal prefix and separate real-event heartbeat.

    Caller owns provenance: EXCHANGE_TRADES_BBO must never label synthetic data.
    Empty signal files require contract metadata rather than guessing a symbol.
    """
    path = Path(path)
    signals = list(signals)
    if source_kind not in ('EXCHANGE_TRADES_BBO', 'SYNTHETIC_FIXTURE'):
        raise ValueError('Unsupported source_kind')
    if (not dataset_id or isinstance(last_event_ns, bool)
            or not isinstance(last_event_ns, Integral) or last_event_ns < 0):
        raise ValueError('Dataset id and last event timestamp required')
    contract = contract or (signals[0].contract if signals else None)
    if not contract:
        raise ValueError('contract is required for an empty signal export')
    rows = []
    previous = -1
    for signal in signals:
        if signal.contract != contract or signal.known_at_ns < previous or signal.known_at_ns > last_event_ns:
            raise ValueError('Signal contract/order/time inconsistent with event stream')
        previous = signal.known_at_ns
        row = {'schema_version': 'fabio_orderflow_v1', 'source_kind': source_kind,
               'dataset_id': dataset_id, 'contract': contract,
               'known_at_utc': str((signal.known_at_ns + 999_999_999) // 1_000_000_000),
               'model': signal.model, 'direction': str(signal.direction)}
        for key in SIGNAL_CSV_FIELDS[7:]:
            row[key] = format(getattr(signal, key), '.17g')
        rows.append(row)
    if path.exists():
        with path.open('r', encoding='utf-8', newline='') as previous_file:
            reader = csv.DictReader(previous_file)
            if reader.fieldnames != SIGNAL_CSV_FIELDS:
                raise ValueError('Existing indicator CSV has another schema')
            old_rows = list(reader)
        if len(old_rows) > len(rows) or rows[:len(old_rows)] != old_rows:
            raise ValueError('Refusing mutation/removal of finalized signal prefix')
    status_path = Path(str(path) + '.status.csv')
    if status_path.exists():
        with status_path.open('r', encoding='utf-8', newline='') as old_status:
            reader = csv.DictReader(old_status)
            if reader.fieldnames != STATUS_CSV_FIELDS:
                raise ValueError('Existing indicator heartbeat has another schema')
            statuses = list(reader)
        if len(statuses) != 1:
            raise ValueError('Invalid existing heartbeat')
        old = statuses[0]
        if any(old[k] != str(v) for k, v in [('dataset_id', dataset_id), ('source_kind', source_kind), ('contract', contract)]):
            raise ValueError('Refusing dataset identity change on an existing feed')
        if int(old['last_event_utc']) > (last_event_ns + 999_999_999) // 1_000_000_000:
            raise ValueError('Heartbeat cannot go backward')
    path.parent.mkdir(parents=True, exist_ok=True)
    _atomic_csv(path, SIGNAL_CSV_FIELDS, rows)
    status = dict(schema_version='fabio_orderflow_v1', source_kind=source_kind,
                  dataset_id=dataset_id, contract=contract,
                  last_event_utc=str((last_event_ns + 999_999_999) // 1_000_000_000), signal_rows=str(len(rows)))
    _atomic_csv(status_path, STATUS_CSV_FIELDS, [status])
    return path, status_path
