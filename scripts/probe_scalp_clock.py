"""Compare frozen broker minute prices with independent dated Dukascopy quotes."""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime,timezone
import json
import lzma
import struct
from urllib.request import Request,urlopen

import numpy as np

from can_ho_tro_scalp_core import bars_matrix
from prepare_can_ho_tro_scalp import sha,write_json
import research_scalp_weekly_v3 as w

RUN = w.ROOT/'reports/can_ho_tro_scalp/20261101_clock_probe'
DATES = [(year,month,15) for year in range(2021,2027) for month in (1,6)]
# Move weekend samples to Monday,using only the calendar.
DATES = [datetime(y,m,d,tzinfo=timezone.utc) for y,m,d in DATES]
DATES = [dt+w.timedelta(days=7-dt.weekday()) if dt.weekday()>=5 else dt for dt in DATES]


def fetch(date):
    name = date.strftime('%Y-%m-%d');path = RUN/(name+'_BID.bi5')
    url = 'https://datafeed.dukascopy.com/datafeed/XAUUSD/'+date.strftime('%Y/')+f'{date.month-1:02d}/'+date.strftime('%d/')+'BID_candles_min_1.bi5'
    if not path.exists():
        req = Request(url,headers={'User-Agent':'Mozilla/5.0','Referer':'https://www.dukascopy.com/'})
        with urlopen(req,timeout=30) as response:
            payload = response.read()
        path.write_bytes(payload)
    payload = path.read_bytes();decoded = lzma.decompress(payload)
    assert len(decoded)%24==0 and len(decoded)>0,'Unexpected candle payload'
    raw = np.array(list(struct.iter_unpack('>5If',decoded)),float)
    assert np.all(raw[:,0]%60==0) and np.all((raw[:,0]>=0)&(raw[:,0]<86400))
    # Inspect OHLC invariants instead of accepting an arbitrary price scale/order.
    a = raw[:,[0,1,4,3,2]].copy();a[:,0] += int(date.timestamp());a[:,1:]/=1000.
    assert np.all(np.diff(a[:,0])>0)
    assert np.all(a[:,2]>=np.maximum(a[:,1],a[:,4])) and np.all(a[:,3]<=np.minimum(a[:,1],a[:,4]))
    assert np.all((a[:,4]>100)&(a[:,4]<20000))
    return a,dict(date=name,url=url,rows=len(a),sha256=sha(path),first_close=float(a[0,4]))


def main():
    RUN.mkdir(exist_ok=True)
    protocol = dict(purpose='Clock alignment only,no strategy/entry/payoff selection.',
        dates=[d.strftime('%Y-%m-%d') for d in DATES],gold_sha256=sha(w.BASE/'rates.npz'),
        offsets_hours=list(range(-4,5)),comparison='Contiguous one-minute close changes,exact timestamps. Same-day independent prices;not forecast features.',
        acceptance='At least800pairedminutechanges,bestcorrelation>=.90,marginoverrunnerup>=.50. Do not infer whole-period DST mapping from a few summer/winter checks.',
        sources=['https://www.dukascopy.com/wiki/en/development/strategy-api/historical-data/',
                 'https://www.mql5.com/en/docs/python_metatrader5/mt5copyratesrange_py'])
    path = RUN/'PROTOCOL.json'
    if path.exists():
        assert json.loads(path.read_text(encoding='utf-8'))==protocol
    else:
        write_json(path,protocol)
    gold = bars_matrix(np.load(w.BASE/'rates.npz')['m1']);records = []
    try:
        with ThreadPoolExecutor(max_workers=3) as pool:
            samples = list(pool.map(fetch,DATES))
    except Exception as error:
        write_json(RUN/'DATA_DOWNLOAD_FAILURE.json',dict(error_type=type(error).__name__,message=str(error),
            protocol_sha256=sha(path),saved_sample_files=[p.name for p in RUN.glob('*_BID.bi5')],
            strategy_backtest_executed=False,full_history_clock_mapping_verified=False,
            status='No inference from this failed download;do not repeat unchanged failed source requests.'))
        print('CLOCK_SAMPLE_DOWNLOAD_FAILED',str(error),flush=True);return
    for a,record in samples:
        rows = []
        for shift in range(-4,5):
            times = a[:,0]+shift*3600;indices = np.searchsorted(gold[:,0],times)
            ok = indices<len(gold);ok[ok] &= gold[indices[ok],0]==times[ok]
            pair = ok[1:]&ok[:-1]&(np.diff(a[:,0])==60)
            at = np.where(pair)[0]+1
            changes = a[at,4]-a[at-1,4];other = gold[indices[at],4]-gold[indices[at-1],4]
            corr = float(np.corrcoef(changes,other)[0,1]) if len(at)>=100 else None
            rows.append(dict(shift_hours=shift,n=len(at),correlation=corr,
                median_abs_close_difference=float(np.median(np.abs(a[at,4]-gold[indices[at],4]))) if len(at) else None))
        ranked = sorted(rows,key=lambda r:r['correlation'] if r['correlation'] is not None else -2,reverse=True)
        best = ranked[0];margin = best['correlation']-ranked[1]['correlation']
        passed = best['n']>=800 and best['correlation']>=.9 and margin>=.5
        record.update(offset_comparisons=rows,best=best,runnerup_margin=margin,passed=passed,
            meaning='Frozen feed epoch = independent UTC epoch + best shift hours,for this sampled date only.')
        records.append(record)
        print(record['date'],'shift',best['shift_hours'],'corr',round(best['correlation'],5),'n',best['n'],'PASS',passed,flush=True)
    write_json(RUN/'CLOCK_SAMPLE_RESULTS.json',dict(samples=records,all_sample_checks_passed=all(r['passed'] for r in records),
        protocol_sha256=sha(path),gold_unchanged=sha(w.BASE/'rates.npz')==protocol['gold_sha256'],
        strategy_backtest_executed=False,full_history_clock_mapping_verified=False))


if __name__=='__main__':
    main()
