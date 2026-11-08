"""Download the frozen public Nasdaq CFD research sample; no MT5/account access."""
from __future__ import annotations

import argparse
import hashlib
import json
import lzma
import struct
import time as clock
from datetime import datetime, timedelta, timezone
from pathlib import Path
import numpy as np
import requests

ROOT = Path(__file__).resolve().parents[1]
RUN = ROOT / 'reports/us100_ny_scalp/20261101_v1'
RAW = RUN / 'raw'
UTC = timezone.utc
SESSION = requests.Session()
SESSION.headers.update({'User-Agent': 'Mozilla/5.0', 'Referer': 'https://www.dukascopy.com/'})


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def write_json(path, value):
    Path(path).write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')


def fetch(task):
    day, suffix = task
    relative = f'{day.year}/{day.month-1:02d}/{day.day:02d}/{suffix}.bi5'
    url = 'https://datafeed.dukascopy.com/datafeed/USATECHIDXUSD/' + relative
    path = RAW / relative
    record = dict(date=day.strftime('%Y-%m-%d'), suffix=suffix, url=url)
    try:
        if not path.exists():
            response = SESSION.get(url, timeout=(4, 8))
            if response.status_code == 429:
                return {**record, 'status': 'rate_limited', 'retry_after': response.headers.get('Retry-After')}
            response.raise_for_status()
            payload = response.content
            if len(payload) > 20_000_000:
                raise ValueError('Unexpected file >20MB')
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(payload)
        payload = path.read_bytes()
        record.update(status='ok' if payload else 'empty', bytes=len(payload), sha256=sha(path))
    except Exception as error:
        missing = isinstance(error, requests.HTTPError) and error.response.status_code == 404
        record.update(status='missing' if missing else 'error',
                      error_type=type(error).__name__, error=str(error))
    return record


def decode_m1(path, day):
    payload = Path(path).read_bytes()
    if not payload:
        return np.empty((0, 5))
    raw = lzma.decompress(payload)
    if not raw or len(raw) % 24:
        raise ValueError(f'Invalid M1 payload: {path}')
    a = np.array(list(struct.iter_unpack('>5If', raw)), dtype=float)
    # Feed stores timestamp, open, close, low, high, quote-volume. Volume is unused.
    out = a[:, [0, 1, 4, 3, 2]].copy()
    assert np.all(out[:, 0] % 60 == 0) and np.all((out[:, 0] >= 0) & (out[:, 0] < 86400))
    assert np.all(np.diff(out[:, 0]) > 0)
    out[:, 0] += day.timestamp()
    out[:, 1:] /= 1000.
    assert np.isfinite(out).all() and (out[:, 3] > 1000).all() and (out[:, 2] < 100000).all()
    assert np.all(out[:, 2] >= np.maximum(out[:, 1], out[:, 4]))
    assert np.all(out[:, 3] <= np.minimum(out[:, 1], out[:, 4]))
    return out


def weekdays():
    day = datetime(2024, 1, 1, tzinfo=UTC)
    while day < datetime(2026, 10, 31, tzinfo=UTC):
        if day.weekday() < 5:
            yield day
        day += timedelta(days=1)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--ticks', action='store_true')
    parser.add_argument('--cache-only', action='store_true')
    parser.add_argument('--year', type=int, choices=[2024, 2025, 2026])
    parser.add_argument('--max-seconds', type=int, default=600)
    args = parser.parse_args()
    assert (RUN / 'SPEC_LOCK.json').exists()
    records, tasks = [], []
    days = list(weekdays())
    if args.year:
        days = [d for d in days if d.year == args.year]
    if args.ticks:
        # UTC 13:00-16:59 encompasses the declared NY execution window in both DST regimes.
        days = [d for d in days if d.year == 2026]
        tasks = [(d, f'{hour:02d}h_ticks') for d in days for hour in (13, 14, 15, 16)]
    else:
        tasks = [(d, side + '_candles_min_1') for d in days for side in ('BID', 'ASK')]
    started = clock.monotonic()
    consecutive_errors = 0
    for task in tasks:
        day, suffix = task
        cached = (RAW / f'{day.year}/{day.month-1:02d}/{day.day:02d}/{suffix}.bi5').exists()
        if not cached and (args.cache_only or clock.monotonic()-started > args.max_seconds):
            continue
        record = fetch(task)
        records.append(record)
        consecutive_errors = consecutive_errors+1 if record['status'] == 'error' else 0
        if record['status'] == 'rate_limited':
            print('RATE_LIMIT_STOP', record['retry_after'], flush=True)
            break
        if consecutive_errors >= 10:
            print('NETWORK_CIRCUIT_STOP', consecutive_errors, flush=True)
            break
        if not cached:
            clock.sleep(1.)
        if len(records) % 20 == 0:
            print('DOWNLOAD', len(records), '/', len(tasks), 'errors', sum(r['status'] == 'error' for r in records), flush=True)
            write_json(RUN / ('TICK_PROGRESS.json' if args.ticks else 'M1_PROGRESS.json'), records)
    records.sort(key=lambda r: (r['date'], r['suffix']))
    label = ('TICK' if args.ticks else 'M1') + ('_CACHE' if args.cache_only else '') + (f'_{args.year}' if args.year else '')
    write_json(RUN / (label+'_REQUESTS.json'),
               dict(spec_sha256=sha(RUN / 'SPEC_LOCK.json'), source='Official public Dukascopy quote feed', requests=records))
    if args.ticks:
        print('TICKS_SAVED', len(records), flush=True)
        return
    bid, ask, rejected = [], [], []
    for day in days:
        parts = []
        for side in ('BID', 'ASK'):
            path = RAW / f'{day.year}/{day.month-1:02d}/{day.day:02d}/{side}_candles_min_1.bi5'
            try:
                parts.append(decode_m1(path, day))
            except Exception as error:
                rejected.append(dict(date=day.strftime('%Y-%m-%d'), side=side, error=str(error)))
                break
        if len(parts) != 2 or not all(len(a) for a in parts):
            continue
        if not np.array_equal(parts[0][:, 0], parts[1][:, 0]):
            rejected.append(dict(date=day.strftime('%Y-%m-%d'), error='M1 side timestamps differ'))
            continue
        # Every corresponding ASK OHLC must be >= BID OHLC; never silently repair crossed sides.
        if np.any(parts[1][:, 1:] < parts[0][:, 1:] - 1e-9):
            rejected.append(dict(date=day.strftime('%Y-%m-%d'), error='Crossed side OHLC'))
            continue
        bid.append(parts[0]); ask.append(parts[1])
    if not bid:
        raise RuntimeError('No validated paired M1 days')
    path = RUN / 'm1_bid_ask.npz'
    b, a = np.concatenate(bid), np.concatenate(ask)
    assert np.all(np.diff(b[:, 0]) > 0)
    np.savez_compressed(path, bid=b, ask=a)
    write_json(RUN / 'DATA_MANIFEST.json', dict(symbol='USATECH.IDX/USD', public_path_symbol='USATECHIDXUSD',
        source='Dukascopy public CFD BID/ASK M1 candles, not futures or FTMO quotes', clock='UTC',
        scale_divisor=1000, rows=len(b), first=int(b[0, 0]), last=int(b[-1, 0]), sha256=sha(path),
        spec_sha256=sha(RUN / 'SPEC_LOCK.json'), rejected_days=rejected,
        price_scale_check='Raw price ~21 million /1000 = ~21,000 index points; cross-check tick/M1 prices before PnL.',
        terminal_attempt='Existing MT5 read-only IPC attach timed out; no data/account/order changes.'))
    print('M1_VALIDATED', len(b), 'rejected_days', len(rejected), flush=True)


if __name__ == '__main__':
    main()
