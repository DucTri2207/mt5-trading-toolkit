"""Read-only FX history collection from the existing connected MT5 terminal."""
from datetime import datetime, timezone
import json
from pathlib import Path

import MetaTrader5 as mt5
import numpy as np

from prepare_can_ho_tro_scalp import sha, write_json

ROOT = Path(__file__).resolve().parents[1]
RUN = ROOT/'reports/can_ho_tro_scalp/20261101_intermarket_v9'
SYMBOLS = ('EURUSD', 'USDJPY', 'GBPUSD', 'USDCAD', 'USDSEK', 'USDCHF')
WEIGHTS = (-.576, .136, -.119, .091, .042, .036)


def stamp(year, month=1, day=1):
    return int(datetime(year, month, day, tzinfo=timezone.utc).timestamp())


def validate(a):
    assert len(a) and np.all(np.diff(a['time']) > 0), 'Missing/unordered history'
    assert not np.any(a['time'] % 300), 'M5 alignment error'
    assert np.all(np.isfinite(a['close'])) and np.all(a['low'] > 0)
    assert np.all(a['high'] >= np.maximum(a['open'], a['close']))
    assert np.all(a['low'] <= np.minimum(a['open'], a['close']))


def main():
    RUN.mkdir(parents=True, exist_ok=True)
    chunks = RUN/'fx_chunks'; chunks.mkdir(exist_ok=True)
    assert (RUN/'ASSAY_PROTOCOL.json').exists(), 'Freeze protocol before collecting outcomes'
    assert mt5.initialize(path=r'C:\Program Files\MetaTrader 5\terminal64.exe', timeout=10000), mt5.last_error()
    meta = dict(source='existing connected MT5 terminal; copy_rates_range M5',
                clock='numeric epoch timestamps; same-feed compatibility checked against frozen gold',
                utc_request_bounds=True, symbols={}, requests=[], no_account_login_or_order_calls=True,
                protocol_sha256=sha(RUN/'ASSAY_PROTOCOL.json'))
    history = {}
    try:
        assert mt5.terminal_info().connected
        for symbol, weight in zip(SYMBOLS, WEIGHTS):
            info = mt5.symbol_info(symbol)
            assert info and info.visible and info.path.startswith('Forex\\'), symbol
            parts = []
            for year in range(2021, 2027):
                start = stamp(year); stop = min(stamp(year+1), stamp(2026, 10, 25))
                path = chunks/(symbol+'_'+str(year)+'.npz')
                if path.exists():
                    a = np.load(path)['rates']
                else:
                    a = mt5.copy_rates_range(symbol, mt5.TIMEFRAME_M5, start, stop-1)
                    assert a is not None and len(a), (symbol, year, mt5.last_error())
                    validate(a); np.savez_compressed(path, rates=a)
                validate(a)
                assert np.all((a['time'] >= start) & (a['time'] < stop))
                parts.append(a)
                meta['requests'].append(dict(symbol=symbol, start=start, end_exclusive=stop,
                    rows=len(a), first=int(a['time'][0]), last=int(a['time'][-1]), sha256=sha(path)))
                print(symbol, year, len(a), flush=True)
            combined = np.concatenate(parts); validate(combined); history[symbol] = combined
            meta['symbols'][symbol] = dict(description=info.description, path=info.path, weight=weight,
                rows=len(combined), first=int(combined['time'][0]), last=int(combined['time'][-1]),
                missing_intervals=int(np.sum(np.diff(combined['time']) != 300)))
        # Establish that the current terminal is compatible with the frozen gold feed.
        gold = np.load(ROOT/'reports/can_ho_tro_scalp/20261025_v1/rates.npz')['m5']
        checks = []
        for year, month, day in ((2021, 10, 26), (2024, 5, 6), (2026, 10, 20)):
            start = stamp(year, month, day)
            a = mt5.copy_rates_range('XAUUSD', mt5.TIMEFRAME_M5, start, start+86400-1)
            assert a is not None and len(a)
            expected = gold[(gold['time'] >= start) & (gold['time'] < start+86400)]
            fields = ('time', 'open', 'high', 'low', 'close')
            equal = len(a) == len(expected) and all(np.array_equal(a[k], expected[k]) for k in fields)
            checks.append(dict(start=start, rows_current=len(a), rows_frozen=len(expected), exact_ohlc_time=equal))
        meta['gold_feed_compatibility'] = checks
        assert all(row['exact_ohlc_time'] for row in checks), 'Current terminal and frozen gold differ'
    finally:
        mt5.shutdown()
    path = RUN/'fx_rates.npz'
    if path.exists():
        old = np.load(path)
        assert all(np.array_equal(old[s], a) for s, a in history.items()), 'Frozen FX data changed'
    else:
        np.savez_compressed(path, **history)
    meta['data_sha256'] = sha(path)
    write_json(RUN/'FX_DATA_MANIFEST.json', meta)
    print('DONE', meta['data_sha256'], flush=True)


if __name__ == '__main__':
    main()
