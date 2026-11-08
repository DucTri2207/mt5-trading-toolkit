"""Causal implementation of SPEC_LOCK.json. One frozen setup, no optimizer."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, time, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo
import lzma
import struct

import numpy as np

UTC = timezone.utc
NY = ZoneInfo('America/New_York')
PRAGUE = ZoneInfo('Europe/Prague')
RISK = .0025
TICK = .001  # Public feed price resolution; MT5 uses the broker's actual trade tick.


@dataclass(frozen=True)
class Signal:
    known_at: int
    direction: int
    atr: float
    extreme: float


@dataclass(frozen=True)
class Costs:
    name: str
    floor: float
    slip: float
    commission: float = 0.


COSTS = (Costs('LOW', 0., 0.), Costs('BASE', 2., .5), Costs('STRESS', 3., 1.))


def features(bid):
    n = len(bid)
    fast, slow, atr = np.zeros(n), np.zeros(n), np.zeros(n)
    warm = np.zeros(n, dtype=int)
    tr_sum = 0.
    for i in range(n):
        t, o, h, l, c = bid[i]
        reset = i == 0 or t - bid[i-1, 0] != 60 or int(t)//86400 != int(bid[i-1, 0])//86400
        if reset:
            fast[i] = slow[i] = c
            tr_sum = h-l
            warm[i] = 1
        else:
            warm[i] = warm[i-1]+1
            fast[i] = fast[i-1] + (c-fast[i-1])*2./21.
            slow[i] = slow[i-1] + (c-slow[i-1])*2./51.
            tr = max(h-l, abs(h-bid[i-1, 4]), abs(l-bid[i-1, 4]))
            if warm[i] <= 14:
                tr_sum += tr
            if warm[i] == 14:
                atr[i] = tr_sum/14.
            elif warm[i] > 14:
                atr[i] = (atr[i-1]*13.+tr)/14.
    return fast, slow, atr, warm


def detect(bid):
    fast, slow, atr, warm = features(bid)
    out = []
    for i in np.flatnonzero(warm >= 200):
        a = atr[i-1]
        if a <= 0 or bid[i, 2]-bid[i, 3] > 2*a:
            continue
        c, o = bid[i, 4], bid[i, 1]
        if abs(c-o) < .25*a:
            continue
        up = (fast[i] > slow[i] and fast[i-3] > slow[i-3] and slow[i] > slow[i-5]
              and bid[i-2, 4] < bid[i-3, 4] and bid[i-1, 4] < bid[i-2, 4]
              and bid[i-2, 4] >= slow[i-2] and bid[i-1, 4] >= slow[i-1]
              and min(bid[i-2, 3], bid[i-1, 3]) <= max(fast[i-2], fast[i-1])
              and c > max(bid[i-2, 2], bid[i-1, 2]) and c > o)
        down = (fast[i] < slow[i] and fast[i-3] < slow[i-3] and slow[i] < slow[i-5]
                and bid[i-2, 4] > bid[i-3, 4] and bid[i-1, 4] > bid[i-2, 4]
                and bid[i-2, 4] <= slow[i-2] and bid[i-1, 4] <= slow[i-1]
                and max(bid[i-2, 2], bid[i-1, 2]) >= min(fast[i-2], fast[i-1])
                and c < min(bid[i-2, 3], bid[i-1, 3]) and c < o)
        if up or down:
            d = 1 if up else -1
            extreme = min(bid[i-2:i+1, 3]) if up else max(bid[i-2:i+1, 2])
            out.append(Signal(int(bid[i, 0])+60, d, float(a), float(extreme)))
    return out


def session_bounds(day):
    start = datetime.combine(day, time(9, 35), NY)
    end = datetime.combine(day, time(11), NY)
    return int(start.timestamp()), int(end.timestamp())


def ny_day(stamp):
    return datetime.fromtimestamp(stamp, UTC).astimezone(NY).date()


def session_time(stamp):
    d = datetime.fromtimestamp(stamp, UTC).astimezone(NY)
    return d.weekday() < 5 and (9*60+35) <= d.hour*60+d.minute < 11*60


def make_plan(signal, bid, ask, cost, tick=TICK):
    spread = max(ask-bid, cost.floor)
    if not np.isfinite(spread) or spread < 0 or spread > min(3., .15*signal.atr) + 1e-9:
        return None
    d = signal.direction
    entry = bid + spread + cost.slip if d == 1 else bid - cost.slip
    raw_stop = signal.extreme - .1*signal.atr if d == 1 else signal.extreme + spread + .1*signal.atr
    stop = np.floor((raw_stop+1e-9)/tick)*tick if d == 1 else np.ceil((raw_stop-1e-9)/tick)*tick
    distance = d*(entry-stop)
    if not .5*signal.atr - 1e-9 <= distance <= 2.*signal.atr + 1e-9:
        return None
    target = entry + d*1.25*distance
    target = np.ceil((target-1e-9)/tick)*tick if d == 1 else np.floor((target+1e-9)/tick)*tick
    return dict(direction=d, entry=float(entry), stop=float(stop), target=float(target),
                spread=float(spread), distance=float(distance), risk_points=float(distance+cost.slip+cost.commission))


def floor_lots(budget, loss_one_lot, minimum, step, maximum):
    if not all(np.isfinite(x) and x > 0 for x in (budget, loss_one_lot, minimum, step, maximum)):
        return 0.
    lots = np.floor((min(maximum, budget/loss_one_lot)+1e-12)/step)*step
    return float(lots) if lots >= minimum-1e-12 else 0.


def m1_eligible_days(bid):
    observed = set(bid[:, 0].astype(int).tolist())
    first = datetime.fromtimestamp(bid[0, 0], UTC).date()
    last = datetime.fromtimestamp(bid[-1, 0], UTC).date()
    accepted, rejected = [], []
    day = first
    while day <= last:
        if day.weekday() < 5:
            start, end = session_bounds(day)
            missing = [t for t in range(start-200*60, end+60, 60) if t not in observed]
            if missing:
                rejected.append(dict(date=day.isoformat(), missing_required_minutes=len(missing)))
            else:
                accepted.append(day)
        day += timedelta(days=1)
    return accepted, rejected


def load_ticks(raw_dir: Path, day):
    parts = []
    start, end = session_bounds(day)
    for hour in sorted({int(datetime.fromtimestamp(t, UTC).hour) for t in (start-300, end+60)} |
                       set(range(datetime.fromtimestamp(start-300, UTC).hour,
                                 datetime.fromtimestamp(end+60, UTC).hour+1))):
        path = raw_dir / f'{day.year}/{day.month-1:02d}/{day.day:02d}/{hour:02d}h_ticks.bi5'
        if not path.exists():
            raise ValueError(f'Missing {hour:02d}h tick file')
        payload = path.read_bytes()
        if not payload:
            continue
        raw = lzma.decompress(payload)
        if len(raw) % 20:
            raise ValueError('Bad hourly tick schema')
        a = np.array(list(struct.iter_unpack('>IIIff', raw)), dtype=float)
        if len(a) == 0:
            continue
        assert np.all((a[:, 0] >= 0) & (a[:, 0] < 3600000))
        assert np.all(np.diff(a[:, 0]) >= 0)
        t0 = int(datetime(day.year, day.month, day.day, hour, tzinfo=UTC).timestamp())
        part = np.column_stack((a[:, 0]/1000.+t0, a[:, 2]/1000., a[:, 1]/1000.))
        parts.append(part)
    if not parts:
        raise ValueError('Empty tick day')
    ticks = np.concatenate(parts)
    ticks = ticks[(ticks[:, 0] >= start-300) & (ticks[:, 0] <= end+60)]
    if len(ticks) < 2 or ticks[0, 0] > start-240 or ticks[-1, 0] < end:
        raise ValueError('Missing execution-window endpoints')
    if np.max(np.diff(ticks[:, 0])) > 60:
        raise ValueError('Quote gap >60s inside execution window')
    if not np.isfinite(ticks).all() or np.any(ticks[:, 2] < ticks[:, 1]) or np.any(ticks[:, 1] < 1000):
        raise ValueError('Invalid/crossed public quotes')
    return ticks


def simulate_day(day, signals, bid, ask, cost, ticks=None, tick=TICK):
    """Return closed trades in R; no account balance or future information in decisions."""
    start, end = session_bounds(day)
    candidates = {s.known_at: s for s in signals if start <= s.known_at < end}
    if ticks is None:
        keep = (bid[:, 0] >= start) & (bid[:, 0] <= end)
        b, a = bid[keep], ask[keep]
        # Events: t, bid open/high/low/close, ask open/high/low/close.
        events = np.column_stack((b, a[:, 1:]))
    else:
        q = ticks[ticks[:, 0] >= start]
        events = np.column_stack((q[:, 0], np.repeat(q[:, 1:2], 4, axis=1), np.repeat(q[:, 2:3], 4, axis=1)))
    trades, position = [], None
    entries = stops = 0
    cooldown = -1.
    last_minute = -1

    def finish(p, timestamp, price, reason, ambiguous=False):
        r = (p['direction']*(price-p['entry'])-cost.commission)/p['risk_points']
        row = {**p, 'exit_time': float(timestamp), 'exit': float(price), 'reason': reason,
               'r_net': float(r), 'mae_r': float(min(p['mae_r'], r)), 'ambiguous': ambiguous,
               'date': day.isoformat(), 'execution': 'TICK' if ticks is not None else 'M1_SL_FIRST'}
        trades.append(row)
        return None

    for row in events:
        t, bo, bh, bl, bc, ao, ah, al, ac = row
        ao, ah, al, ac = (max(ao, bo+cost.floor), max(ah, bh+cost.floor),
                          max(al, bl+cost.floor), max(ac, bc+cost.floor))
        minute = int(t)//60*60
        if position is not None:
            p = position
            mark = bo if p['direction'] == 1 else ao
            p['mae_r'] = min(p['mae_r'], (p['direction']*(mark-p['entry'])-cost.commission)/p['risk_points'])
            gap_stop = mark <= p['stop'] if p['direction'] == 1 else mark >= p['stop']
            target_open = mark >= p['target'] if p['direction'] == 1 else mark <= p['target']
            if gap_stop:
                position = finish(p, t, mark-p['direction']*cost.slip, 'SL')
                stops += 1; cooldown = t+300
            elif target_open:
                position = finish(p, t, p['target'], 'TP')
                cooldown = t+300
            elif t >= p['deadline']:
                position = finish(p, t, mark-p['direction']*cost.slip, 'TIME')
                cooldown = t+300
        if minute != last_minute:
            last_minute = minute
            if position is None and entries < 3 and stops < 2 and t >= cooldown and minute in candidates and t < end:
                signal = candidates[minute]
                p = make_plan(signal, bo, ao, cost, tick=tick)
                if p is not None:
                    position = {**p, 'known_at': signal.known_at, 'entry_time': float(t),
                                'deadline': min(t+900, end), 'mae_r': 0.}
                    mark = bo if p['direction'] == 1 else ao
                    position['mae_r'] = min(0., (p['direction']*(mark-p['entry'])-cost.commission)/p['risk_points'])
                    entries += 1
        if position is not None and ticks is None:
            p = position
            low_mark, high_mark = (bl, bh) if p['direction'] == 1 else (al, ah)
            stop_hit = low_mark <= p['stop'] if p['direction'] == 1 else high_mark >= p['stop']
            target_hit = high_mark >= p['target'] if p['direction'] == 1 else low_mark <= p['target']
            adverse = max(low_mark, p['stop']) if p['direction'] == 1 else min(high_mark, p['stop'])
            p['mae_r'] = min(p['mae_r'], (p['direction']*(adverse-p['entry'])-cost.commission)/p['risk_points'])
            if stop_hit:
                position = finish(p, t+60, p['stop']-p['direction']*cost.slip, 'SL', bool(target_hit))
                stops += 1; cooldown = t+60+300
            elif target_hit:
                position = finish(p, t+60, p['target'], 'TP')
                cooldown = t+60+300
    if position is not None:
        raise ValueError('Execution window ended with an unclosed virtual position')
    return trades


def account_path(trades):
    balance = peak = 1.
    max_dd = 0.
    for p in trades:
        budget = balance*RISK
        floor = balance+budget*p['mae_r']
        max_dd = max(max_dd, (peak-floor)/peak)
        balance += budget*p['r_net']
        peak = max(peak, balance)
    return dict(return_pct=(balance-1)*100, drawdown_vs_closed_balance_peak_pct=max_dd*100)


def prop_attempt(trades, initial=100000.):
    """Sequential two-phase benchmark; all model trades are intraday in Prague too."""
    balance = initial
    phase = 0
    used_days = set()
    day, day_start, skip_day = None, initial, None
    records = []
    for p in trades:
        local_day = datetime.fromtimestamp(p['entry_time'], UTC).astimezone(PRAGUE).date().isoformat()
        assert local_day == datetime.fromtimestamp(p['exit_time'], UTC).astimezone(PRAGUE).date().isoformat()
        if local_day == skip_day:
            continue
        if local_day != day:
            day, day_start = local_day, balance
        used_days.add(day)
        budget = balance*RISK
        equity_floor = balance+budget*p['mae_r']
        if equity_floor < initial*.9 or equity_floor < day_start-initial*.05:
            return dict(status='FAIL', phase=phase+1, date=day, balance=balance,
                        reason='total_loss' if equity_floor < initial*.9 else 'daily_loss', phases=records)
        balance += budget*p['r_net']
        if balance >= initial*(1.+(.10 if phase == 0 else .05)) and len(used_days) >= 4:
            records.append(dict(phase=phase+1, completed=day, trading_days=len(used_days), balance=balance))
            if phase == 1:
                return dict(status='BOTH_PHASES_REACHED', phases=records)
            phase, balance, used_days, skip_day = 1, initial, set(), day
            day, day_start = None, initial
    return dict(status='CENSORED', phase=phase+1, balance=balance, trading_days=len(used_days), phases=records)


def summary(trades):
    if not trades:
        return dict(trades=0, win_rate_pct=None, net_R=0., mean_R=None, profit_factor=None,
                    return_pct=0., drawdown_vs_closed_balance_peak_pct=0.)
    rs = np.array([p['r_net'] for p in trades])
    wins, losses = rs[rs > 0].sum(), -rs[rs < 0].sum()
    return dict(trades=len(trades), win_rate_pct=float(np.mean(rs > 0)*100), net_R=float(rs.sum()),
                mean_R=float(rs.mean()), profit_factor=float(wins/losses) if losses else None,
                sl_exits=sum(p['reason'] == 'SL' for p in trades),
                both_hit_m1=sum(p['ambiguous'] for p in trades),
                **account_path(trades))
