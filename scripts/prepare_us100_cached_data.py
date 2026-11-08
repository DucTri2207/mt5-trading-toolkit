"""Audit native exported Nasdaq bars and independently resolve their feed clock."""
from pathlib import Path
from datetime import datetime, timezone, timedelta
import json,lzma,struct
from zoneinfo import ZoneInfo
import numpy as np
from collect_us100_ny import ROOT, sha, write_json, decode_m1

RUN=ROOT/'reports/us100_ny_scalp/20261101_backtest_v2'
OLD=ROOT/'reports/us100_ny_scalp/20261101_v1'
UTC=timezone.utc


def broker_to_utc(server):
    """MetaQuotes proxy clock, established by independent price alignment."""
    utc=server.copy()-7200
    for year in range(2022,2027):
        def last_sunday(month):
            next_month=datetime(year,month+1,1,tzinfo=UTC)
            last=next_month-timedelta(days=1)
            return last-timedelta(days=(last.weekday()+1)%7)
        start=last_sunday(3).replace(hour=1).timestamp()
        end=last_sunday(10).replace(hour=1).timestamp()
        # CFD history should be closed in these ambiguous/nonexistent Sunday hours.
        for transition in (start,end):
            assert not np.any((server>=transition+7200)&(server<transition+10800)), 'Ambiguous/nonexistent server hour'
        summer=(server>=start+10800)&(server<end+10800)
        utc[summer]-=3600
    return utc


def compare(raw, public, label):
    records=[]
    for shift in range(-4,5):
        target=public[:,0]+shift*3600
        at=np.searchsorted(raw[:,0],target)
        ok=at<len(raw);ok[ok]&=raw[at[ok],0]==target[ok]
        paired=ok[1:]&ok[:-1]&(np.diff(public[:,0])==60)
        indices=np.flatnonzero(paired)+1
        x=public[indices,4]-public[indices-1,4]
        y=raw[at[indices],4]-raw[at[indices-1],4]
        corr=float(np.corrcoef(x,y)[0,1]) if len(x)>=40 and np.std(x)>0 and np.std(y)>0 else None
        records.append(dict(shift_hours=shift,pairs=len(x),correlation=corr))
    ranked=sorted(records,key=lambda r:r['correlation'] if r['correlation'] is not None else -2,reverse=True)
    best=ranked[0];margin=best['correlation']-ranked[1]['correlation'] if best['correlation'] is not None and ranked[1]['correlation'] is not None else None
    return dict(sample=label,comparisons=records,best=best,runnerup_margin=margin,
                strong=best['pairs']>=80 and best['correlation'] is not None and best['correlation']>=.90 and margin is not None and margin>=.3)


def main():
    folder=RUN/'offline_terminal/MQL5/Files/nasdaq_cache_export'
    pieces=[];year_records=[]
    for path in sorted(folder.glob('20??.csv')):
        a=np.loadtxt(path,delimiter=',')
        assert a.ndim==2 and a.shape[1]==7 and np.isfinite(a).all()
        assert np.all(np.diff(a[:,0])>0) and np.all(a[:,0]%60==0)
        assert np.all(a[:,3]>1000) and np.all(a[:,2]>=np.maximum(a[:,1],a[:,4])) and np.all(a[:,3]<=np.minimum(a[:,1],a[:,4]))
        assert np.all(a[:,5]>=0)
        pieces.append(a)
        year_records.append(dict(year=int(path.stem),rows=len(a),first=int(a[0,0]),last=int(a[-1,0]),csv_sha256=sha(path)))
    raw=np.concatenate(pieces);assert np.all(np.diff(raw[:,0])>0)
    samples=[]
    for p in sorted((OLD/'raw/2024').glob('*/*/BID_candles_min_1.bi5')):
        month,day=int(p.parent.parent.name)+1,int(p.parent.name)
        date=datetime(2024,month,day,tzinfo=UTC)
        public=decode_m1(p,date)
        if len(public):samples.append(compare(raw,public,date.strftime('%Y-%m-%d')+'_Dukascopy_M1'))
    # Use every cached 2026 public hourly quote file, including partial dates, for clock checks only.
    for p in sorted((OLD/'raw/2026').glob('*/*/*h_ticks.bi5')):
        payload=p.read_bytes()
        if not payload:continue
        decoded=lzma.decompress(payload)
        assert len(decoded)%20==0
        a=np.array(list(struct.iter_unpack('>IIIff',decoded)),float)
        if len(a)<100:continue
        hour=int(p.stem[:2]);month=int(p.parent.parent.name)+1;day=int(p.parent.name)
        start=int(datetime(2026,month,day,hour,tzinfo=UTC).timestamp())
        assert np.all((a[:,0]>=0)&(a[:,0]<3600000)) and np.all(np.diff(a[:,0])>=0)
        minutes=(a[:,0]//60000).astype(int);ends=np.r_[np.flatnonzero(np.diff(minutes)!=0),len(a)-1]
        public=np.zeros((len(ends),5));public[:,0]=start+minutes[ends]*60;public[:,4]=a[ends,2]/1000
        samples.append(compare(raw,public,f'2026-{month:02d}-{day:02d}T{hour:02d}_Dukascopy_ticks'))
    strong=[s for s in samples if s['strong']]
    # European DST selected from independent prices, before strategy PnL.
    expected=[]
    for s in strong:
        day=s['sample'][:10]
        d=datetime.fromisoformat(day).replace(hour=15,tzinfo=UTC)
        offset=d.astimezone(ZoneInfo('Europe/Helsinki')).utcoffset().total_seconds()/3600
        expected.append(s['best']['shift_hours']==offset)
    clock=dict(samples=samples,strong_samples=len(strong),all_strong_match_utc2_eu_dst=bool(strong) and all(expected),
               winter_samples=sum(s['best']['shift_hours']==2 for s in strong),summer_samples=sum(s['best']['shift_hours']==3 for s in strong),
               convention='broker epoch = UTC epoch +2h winter/+3h European summer, supported by independent samples',
               whole_history_each_day_independently_verified=False)
    write_json(RUN/'CLOCK_AUDIT.json',clock)
    assert clock['all_strong_match_utc2_eu_dst'] and clock['winter_samples']>=3 and clock['summer_samples']>=3, 'Clock unresolved; do not score PnL'
    utc=broker_to_utc(raw[:,0])
    assert np.all(np.diff(utc)>0)
    bid=raw[:,:5].copy();bid[:,0]=utc
    path=RUN/'broker_m1.npz';np.savez_compressed(path,bid=bid,recorded_spread_points=raw[:,5],tick_volume=raw[:,6],server_time=raw[:,0])
    q=np.quantile(raw[:,5]*.01,[0,.1,.5,.9,.99,1]).tolist()
    manifest=dict(source='Locally cached MetaQuotes-Demo USTEC M1 through native CopyRates offline',symbol='USTEC',
        not_ftmo=True,point=.01,trade_tick_size=.01,contract_size=1.,rows=len(raw),years=year_records,
        raw_feed_clock='server wall clock encoded in epoch',converted_clock='UTC using UTC+2 / European DST+1',
        first_utc=datetime.fromtimestamp(utc[0],UTC).isoformat(),last_utc=datetime.fromtimestamp(utc[-1],UTC).isoformat(),
        clock_verified_sample_dates_only=True,clock_audit_sha256=sha(RUN/'CLOCK_AUDIT.json'),data_sha256=sha(path),
        spread_zero_fraction=float(np.mean(raw[:,5]==0)),recorded_spread_price_quantiles=q,
        spread_limit='Recorded M1 spread is not opening synchronized Ask; never use same-bar spread retrospectively for entry.',
        spec_sha256=sha(OLD/'SPEC_LOCK.json'),core_sha256=sha(ROOT/'scripts/us100_ny_core.py'))
    write_json(RUN/'DATA_MANIFEST.json',manifest)
    print(json.dumps(dict(rows=len(raw),years=year_records,clock_summary={k:v for k,v in clock.items() if k!='samples'},spread_quantiles=q)),flush=True)


if __name__=='__main__':main()
