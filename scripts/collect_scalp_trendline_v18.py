"""Read native H4 history and reconcile it with the frozen gold M5 feed."""
import json

import MetaTrader5 as mt5
import numpy as np

from prepare_can_ho_tro_scalp import sha,write_json
import research_scalp_weekly_v3 as w

RUN = w.ROOT/'reports/can_ho_tro_scalp/20261101_trendline_v18'


def reconcile(h4,m5):
    expected = []
    for bar in h4:
        if not w.START<=bar['time']<w.END:
            continue
        selected = m5[(m5['time']>=bar['time'])&(m5['time']<bar['time']+14400)]
        if not len(selected):
            expected.append(dict(time=int(bar['time']),matched=False,reason='NO_FROZEN_M5'));continue
        values = (selected['open'][0],selected['high'].max(),selected['low'].min(),selected['close'][-1])
        actual = tuple(bar[k] for k in ('open','high','low','close'))
        if values!=actual:
            expected.append(dict(time=int(bar['time']),matched=False,native=list(map(float,actual)),m5=list(map(float,values))))
    buckets = np.unique((m5['time'][(m5['time']>=w.START)&(m5['time']<w.END)]//14400)*14400)
    native = h4['time'][(h4['time']>=w.START)&(h4['time']<w.END)]
    return dict(native_bars=len(native),frozen_m5_buckets=len(buckets),
                missing_native_buckets=np.setdiff1d(buckets,native).astype(int).tolist(),mismatches=expected,
                passed=not len(np.setdiff1d(buckets,native)) and not expected,
                method='Exact OHLC of all actual M5 quotes in each native4h bucket;session closures remain gaps,not synthetic bars.')


def main():
    RUN.mkdir(exist_ok=True)
    plan = dict(source='Existing connected MT5 native XAUUSD H4 history;no orders/login/account operations.',
        start=1609459200,end_exclusive=w.END,gold_sha256=sha(w.BASE/'rates.npz'),
        acceptance='Every evaluated nativeH4 OHLC exactly equals frozenM5 bucket;every frozenM5 bucket has nativeH4. Preserve session closures,no fill.',
        untouched='Freshsource/ex5/includes/installedindicators and existing frozen gold data.')
    path = RUN/'DATA_PLAN.json'
    if path.exists():
        assert json.loads(path.read_text(encoding='utf-8'))==plan
    else:
        write_json(path,plan)
    assert mt5.initialize(path=r'C:\Program Files\MetaTrader 5\terminal64.exe',timeout=10000),mt5.last_error()
    try:
        assert mt5.terminal_info().connected
        parts = []
        chunks = RUN/'h4_chunks';chunks.mkdir(exist_ok=True)
        for year in range(2021,2027):
            start = int(w.datetime(year,1,1,tzinfo=w.timezone.utc).timestamp())
            stop = min(int(w.datetime(year+1,1,1,tzinfo=w.timezone.utc).timestamp()),w.END)
            path = chunks/(str(year)+'.npz')
            if path.exists():
                rates = np.load(path)['rates']
            else:
                rates = mt5.copy_rates_range('XAUUSD',mt5.TIMEFRAME_H4,start,stop-1)
                assert rates is not None and len(rates),(year,mt5.last_error())
                np.savez_compressed(path,rates=rates)
            assert np.all(np.diff(rates['time'])>0) and np.all(rates['time']%14400==0)
            assert np.all((rates['time']>=start)&(rates['time']<stop));parts.append(rates)
    finally:
        mt5.shutdown()
    rates = np.concatenate(parts);path = RUN/'h4_rates.npz'
    if path.exists():
        np.testing.assert_array_equal(np.load(path)['rates'],rates)
    else:
        np.savez_compressed(path,rates=rates)
    frozen = np.load(w.BASE/'rates.npz');quality = reconcile(rates,frozen['m5'])
    gaps = np.diff(rates['time']);quality['max_gap_days'] = float(gaps.max()/86400)
    quality['passed'] = quality['passed'] and quality['max_gap_days']<=7
    manifest = dict(source='Native MT5 XAUUSD H4',data_sha256=sha(path),rows=len(rates),first=int(rates['time'][0]),
        last=int(rates['time'][-1]),data_plan_sha256=sha(RUN/'DATA_PLAN.json'),quality=quality,
        broker_epoch_clock='Retained as feed time;no new UTC/DST assertion.',no_account_login_or_order_calls=True)
    write_json(RUN/'H4_DATA_MANIFEST.json',manifest)
    print('H4',len(rates),'quality',quality['passed'],'mismatches',len(quality['mismatches']),
          'missingbuckets',len(quality['missing_native_buckets']),flush=True)


if __name__=='__main__':
    main()
