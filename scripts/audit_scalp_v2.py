"""Native trade parity, prefix causality, sealed new-week test and equity audit."""
import json
import shutil
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

import research_scalp_v2 as r
from research_scalp_reclaim_v2 import detect_reclaim
from research_scalp_breakout_v2 import detect_breakout
from can_ho_tro_scalp_core import bars_matrix, detect_all, metaquotes_atr, ema50
from prepare_can_ho_tro_scalp import sha, write_json


def read(p):return json.loads(p.read_text(encoding='utf-8'))


def main():
    data=np.load(r.BASE/'rates.npz');arrays={k:bars_matrix(data[k]) for k in data.files}
    num=np.load(r.BASE/'detector_python.npz');raw=num['c0_raw']
    fresh=next(s for s in r.SPECS if s['name']=='FRESH_T05')
    fixture=r.ROOT/'reports/scalp_structure_lab/20261025_pilot_v1/fixture_terminal/MQL5/Files/can_ho_tro_scalp_v1'
    native=read(fixture/'fresh_v2_result.json');assert native['failures']==0 and native['candidate_rows']==len(raw)
    native_checks=[]
    state_map={'CLOSED':3,'REJECTED':4,'CENSORED_FILLED':7,'CENSORED_OPEN':7}
    for cost in r.COSTS:
        name='FRESH_V2_'+cost['id']+'_ADVERSE_FIRST_serial_trades_mql.csv'
        a=np.loadtxt(fixture/name,delimiter=',',ndmin=2)
        py=read(r.RUN/('FRESH_T05_'+cost['id']+'_ADVERSE_FIRST_trades.json'))
        assert len(a)==len(py)
        columns=[('candidate_index',0),('signal_time',1),('entry_time',3),('entry',4),('initial_sl',5),('risk',6),('exit_time',7),('exit_price',8),('gross_r',11)]
        errors={}
        for key,col in columns:
            error=max(abs(float(t[key])-row[col]) for row,t in zip(a,py))
            assert error<1e-8,(cost,key,error)
            errors[key]=error
        assert all(int(row[9])==state_map[t['state']] for row,t in zip(a,py))
        assert all(abs((row[11]-cost['commission_price']/row[6])-t['r'])<1e-8 for row,t in zip(a,py) if t['state']=='CLOSED')
        native_checks.append(dict(cost=cost['id'],rows=len(py),max_errors=errors,net_commission_parity=True))
        shutil.copy2(fixture/name,r.RUN/name)
    write_json(r.RUN/'NATIVE_PARITY.json',dict(passed=True,fixtures=native,checks=native_checks,
               scope='Fresh T05 gate and individual trade prices/times/gross+net R; existing base detector native parity retained'))
    start=int(datetime(2021,10,25,tzinfo=timezone.utc).timestamp())
    cutoff=int(datetime(2024,6,1,tzinfo=timezone.utc).timestamp())
    h=arrays['h1'][arrays['h1'][:,0]<=cutoff].copy()
    h[h[:,0]+3600>cutoff,2:5]=h[h[:,0]+3600>cutoff,1,None]
    m5=arrays['m5'][arrays['m5'][:,0]+300<=cutoff]
    m1=arrays['m1'][arrays['m1'][:,0]+60<=cutoff]
    d=arrays['d1'][arrays['d1'][:,0]+86400<=cutoff]
    ah=metaquotes_atr(h);a5=metaquotes_atr(m5);a1=metaquotes_atr(m1);ma=ema50(h)
    checks=[]
    for label,actual,expected in [
        ('M5 preserved default',detect_all(h,m5,d,ah,a5,ma,start,cutoff,True)[0],raw),
        ('M1 independent',detect_all(h,m1,d,ah,a1,ma,start,cutoff,True,60)[0],np.load(r.RUN.parent/'20261101_m1_v2/detector_m1.npz')['raw']),
        ('direct reclaim',detect_reclaim(h,m5,ah,a5,ma,start,cutoff),np.load(r.RUN.parent/'20261101_reclaim_v2/detector_direct.npz')['raw']),
        ('breakout pullback',detect_breakout(h,m5,ah,a5,ma,start,cutoff),np.load(r.RUN.parent/'20261101_breakout_v2/detector_breakout.npz')['raw']),
    ]:
        expected=expected[expected[:,1]<cutoff]
        same=actual.shape==expected.shape and np.array_equal(actual,expected)
        checks.append(dict(label=label,cutoff='2024-06-01',rows=len(actual),passed=bool(same)))
        assert same,label
        print('PREFIX PASS',label,len(actual),flush=True)
    write_json(r.RUN/'PREFIX_CHECKS.json',dict(passed=True,checks=checks))
    # The choice is recorded before inspecting outcomes of the newly retrieved week.
    newfile=r.RUN/'new_week_rates.npz'
    lock=dict(selected=fresh,training_data_sha256=sha(r.BASE/'rates.npz'),
              new_data_sha256=sha(newfile),period='2026-10-25 <= signal < 2026-11-01',
              selected_reason='best retrospective BASE-cost PF with positive stress result; experimental, below min sample',
              analysis='single sealed one-week validation; never use it to retune this variant')
    forward_lock=r.RUN/'FORWARD_WEEK_LOCK.json'
    if forward_lock.exists():assert read(forward_lock)==lock
    else:write_json(forward_lock,lock)
    new=np.load(newfile);merged={}
    for key in data.files:
        all_rates=np.concatenate([data[key],new[key]])
        _,indexes=np.unique(all_rates['time'],return_index=True)
        merged[key]=bars_matrix(all_rates[np.sort(indexes)])
        assert np.all(np.diff(merged[key][:,0])>0)
    end=int(datetime(2026,11,1,tzinfo=timezone.utc).timestamp())
    oldend=int(datetime(2026,10,25,tzinfo=timezone.utc).timestamp())
    fresh_raw,_=detect_all(merged['h1'],merged['m5'],merged['d1'],metaquotes_atr(merged['h1']),metaquotes_atr(merged['m5']),ema50(merged['h1']),start,end,True)
    prefix=fresh_raw[fresh_raw[:,1]<oldend]
    assert prefix.shape==raw.shape and np.array_equal(prefix,raw),'New week cannot change old candidates'
    forward_raw=fresh_raw[fresh_raw[:,1]>=oldend]
    features=[r.feature(c,merged['h1'],ema50(merged['h1'])) for c in forward_raw]
    results=[]
    for cost in r.COSTS:
        trades,_=r.run_serial(forward_raw,features,merged,fresh,cost)
        write_json(r.RUN/('FRESH_NEW_WEEK_'+cost['id']+'_trades.json'),trades)
        results.append(dict(cost=cost['id'],metrics=r.metrics(trades)))
    write_json(r.RUN/'FORWARD_WEEK.json',dict(rows=results,raw_candidates=len(forward_raw),old_prefix_exact=True,
               validation='one newly acquired week; far too short to establish an edge'))
    print('NEW_WEEK',json.dumps(results),flush=True)
    # Mark-to-market DD on the selected strategy, with round-trip commission reserved.
    features=[r.feature(c,arrays['h1'],num['ma1']) for c in raw]
    equity=[]
    for cost in r.COSTS:
        trades,_=r.run_serial(raw,features,arrays,fresh,cost,record_equity=True)
        carry=0.;peak=0.;dd=0.;lastday=None;daystart=0.;worstday=0.;samples=[]
        for t in trades:
            for at,value in t.get('equity_samples',[]):
                eq=carry+value;peak=max(peak,eq);dd=max(dd,peak-eq)
                day=at//86400
                if day!=lastday:daystart=carry;lastday=day
                worstday=min(worstday,eq-daystart);samples.append((at,eq))
            if t['r'] is not None:carry+=t['r']
        np.savez_compressed(r.RUN/('fresh_equity_'+cost['id']+'.npz'),equity=np.array(samples))
        equity.append(dict(cost=cost['id'],equity_dd_r=dd,worst_feed_day_intraday_r=worstday,
                          stress_net_r=r.metrics(trades)['total_r'],commission_reserved='full roundtrip at entry; conservative fee timing',
                          warning='feed-day diagnostic only; NOT FTMO CE(S)T nor verified The5ers server-day compliance'))
    write_json(r.RUN/'FRESH_EQUITY.json',dict(rows=equity))
    print('AUDIT DONE',flush=True)


if __name__=='__main__':main()
