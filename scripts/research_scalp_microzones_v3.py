"""Test Fresh's displacement/base zones at faster source scales, separately."""
from __future__ import annotations

import argparse
from collections import Counter
import json
from pathlib import Path

import numpy as np
from numba import njit

from can_ho_tro_scalp_core import bars_matrix, ema50, metaquotes_atr, raw_at, source_zones
from prepare_can_ho_tro_scalp import sha, write_json
import research_scalp_weekly_v3 as w

RUN=w.ROOT/'reports/can_ho_tro_scalp/20261101_microzones_v3'
NAMES={5:'ZONE15_M5',6:'ZONE15_M1',7:'ZONE5_M1'}
SPECS=[dict(name=group+'_R'+str(int(rr*100)),group='COMBO' if group=='MICRO_COMBO' else group,rr=rr)
       for group in ('ZONE15_M5','ZONE15_M1','ZONE5_M1','MICRO_COMBO') for rr in (.8,1.)]


def freeze():
    RUN.mkdir(parents=True,exist_ok=True)
    lock=dict(version='microzones_v3',start=w.START,end_exclusive=w.END,
              data_sha256=sha(w.BASE/'rates.npz'),hypotheses=SPECS,costs=w.COSTS,
              preserved_fresh={p:sha(w.ROOT/p) for p in w.FRESH_PATHS},
              motivation='Weekly_v3 simple pivots/pullbacks lost money even without costs; retain Fresh displacement/base quality and test more source timeframes.',
              definitions=dict(source='original source_zones with availability+source timeframe; M15 from3 complete M5 bars, M5 original; test_count<=1 BEFORE candidate selection; original base,departure,score,flip,age/rank rules',
                               trigger='original CLOSED sweep/reclaim/CHoCH raw_at on M5 or M1; original H1 EMA50 trend,distance,body and feed-hour gates; zone must be known BEFORE sweep',
                               priority='Fresh H1 first,ZONE15_M5,ZONE15_M1,ZONE5_M1; original rank within source; one position,max2 entries/day,max10/week',
                               exit='new sources TP.8/1R,120min hold,21:00 feed cutoff; Fresh TP.5R/6h with same cutoff/caps in combined experiment',
                               execution='same WeeklyPlan market Bid/Ask,SLmin2/max20,first quote<=60s,M1 adverse-first; assumed fees; no broker orders'),
              statistical_screen=dict(family_size=58,min_trades=1000,prior_hypotheses=50,
                                      annual_stability='all full years2022-2025 BASE net positive',
                                      costs='positive BASE and STRESS expectancy plus adjusted monthly bootstrap lower>0'),
              objective=dict(win_rate_percent=[55,60],average_trades_week=[5,10],no_empty_market_data_week=True),
              bootstrap_seed=20261103,bootstrap_resamples=20000,
              selection='combined variants only; same prior-year/120min purge/200train trades/frequency/netR selection as weekly_v3',
              caveats=['Previously inspected history, retrospective only.','Native parity for this new timeframe adaptation not established.',
                       'Feed clock,fees,news,prop package rules unverified; no footprint or real tick claims.',
                       'Correction covers at least58 tracked hypotheses; additional older choices remain.'])
    path=RUN/'EXPERIMENT_LOCK.json'
    if path.exists():assert json.loads(path.read_text(encoding='utf-8'))==lock
    else:write_json(path,lock)
    return lock


@njit(cache=True)
def detect_micro(source,trigger,h1,atr_source,atr_trigger,atr1,ma1,source_seconds,trigger_seconds,family,start,stop):
    rows=[];count=0;old=-1;hcount=0;zones=np.empty((0,16))
    first_seen=np.zeros((len(source),5,2))
    for c in range(29,len(trigger)):
        at=trigger[c,0]+trigger_seconds
        if at>=stop:break
        while count<len(source) and source[count,0]+source_seconds<=at:count+=1
        while hcount<len(h1) and h1[hcount,0]+3600<=at:hcount+=1
        if count!=old:
            all_zones=source_zones(source,atr_source,count,source_seconds)
            for z in all_zones:
                bi,bl,fl=int(z[0]),int(z[1])-1,int(z[3])
                if first_seen[bi,bl,fl]==0:first_seen[bi,bl,fl]=source[count-1,0]+source_seconds
                z[13]=max(z[13],first_seen[bi,bl,fl])
            # Fresh's eligibility gate precedes source priority selection.
            zones=all_zones[(all_zones[:,7]<=1)&(all_zones[:,8]==0)]
            old=count
        if at<start:continue
        found=raw_at(trigger,atr_trigger,c,zones,h1,atr1,ma1,hcount,0.,0.,0.,True,trigger_seconds)
        for candidate in found:
            if candidate[27]!=0 or candidate[28]!=0:continue
            row=np.zeros(40);row[:36]=candidate
            row[4]+=family*10  # Distinguish simultaneous ideas from different source scales.
            row[36:40]=np.array([family,candidate[12],1.,candidate[23]+3600])
            rows.append(row)
        if c%250000==0:print('SCAN',family,c,'signals',len(rows))
    out=np.empty((len(rows),40))
    for i in range(len(rows)):out[i]=rows[i]
    return out


def detect(arrays,source_seconds,trigger_seconds,family,start=w.START,stop=w.END):
    source=w.aggregate_complete(arrays['m5'],900) if source_seconds==900 else arrays['m5']
    trigger=arrays['m5'] if trigger_seconds==300 else arrays['m1']
    return detect_micro(source,trigger,arrays['h1'],metaquotes_atr(source),metaquotes_atr(trigger),
                        metaquotes_atr(arrays['h1']),ema50(arrays['h1']),
                        source_seconds,trigger_seconds,family,start,stop)


def walkforward(base_trades,raw,market,cost):
    choices=[];schedule={};lookup={s['name']:s for s in SPECS}
    for year in range(2023,2027):
        boundary=int(w.datetime(year,1,1,tzinfo=w.timezone.utc).timestamp());rank=[]
        for spec in SPECS:
            if spec['group']!='COMBO':continue
            train=[t for t in base_trades[spec['name']] if t['state']=='CLOSED' and t['exit_time']<boundary-7200]
            m=w.metrics(train);f=w.weekly(train,market,w.START,boundary-7200)
            if m['n']>=200 and m['total_r']>0 and f['weeks'] and not f['empty_weeks'] and 5<=f['mean']<=10:
                rank.append((m['total_r']/f['weeks'],spec['name'],m['n']))
        if rank:
            score,name,n=max(rank);schedule[year]=lookup[name]
            choices.append(dict(year=year,selected=name,train_n=n,train_r_week=score))
        else:choices.append(dict(year=year,selected='CASH'))
    trades,rejections=w.run_serial(raw,market,None,cost,schedule=schedule)
    return dict(choices=choices,metrics=w.metrics(trades),rejections=rejections,
                label='retrospective selection; no pristine OOS'),trades


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--freeze-only',action='store_true');args=parser.parse_args()
    lock=freeze()
    if args.freeze_only:return
    w.FAMILIES.update(NAMES)
    z=np.load(w.BASE/'rates.npz');arrays={k:bars_matrix(z[k]) for k in z.files}
    parts=[]
    for family,source_seconds,trigger_seconds in [(5,900,300),(6,900,60),(7,300,60)]:
        path=RUN/(NAMES[family]+'_candidates.npz')
        if path.exists():raw=np.load(path)['raw']
        else:
            print('DETECT',NAMES[family],flush=True)
            raw=detect(arrays,source_seconds,trigger_seconds,family)
            np.savez_compressed(path,raw=raw)
        assert np.all(raw[:,12]<=raw[:,13]) and np.all(raw[:,39]<=raw[:,0])
        print('CANDIDATES',NAMES[family],len(raw),flush=True);parts.append(raw)
    raw=w.add_fresh(np.concatenate(parts));summaries=[];base_trades={}
    for spec in SPECS:
        for cost in w.COSTS:
            label=spec['name']+'_'+cost['id'];path=RUN/(label+'_trades.json')
            if path.exists():
                saved=json.loads(path.read_text());trades=saved['trades'];rejects=saved['rejections']
            else:
                trades,rejects=w.run_serial(raw,arrays['m1'],spec,cost)
                write_json(path,dict(trades=trades,rejections=rejects))
            m=w.summarize(trades,arrays['m1'],lock);f=m['frequency']
            summaries.append(dict(name=spec['name'],cost=cost['id'],metrics=m,rejections=rejects))
            if cost['id']=='BASE':base_trades[spec['name']]=trades
            print(label,'n',m['n'],'win',round(m['win_rate'] or 0,2),'PF',round(m['pf'] or 0,3),
                  'R',round(m['total_r'],2),'week',round(f['mean'],2),'empty',len(f['empty_weeks']),flush=True)
    wf={}
    for cost in w.COSTS:
        summary,trades=walkforward(base_trades,raw,arrays['m1'],cost)
        wf[cost['id']]=summary;write_json(RUN/('WALKFORWARD_'+cost['id']+'_trades.json'),trades)
    write_json(RUN/'summary.json',dict(rows=summaries,walkforward=wf,lock_sha256=sha(RUN/'EXPERIMENT_LOCK.json')))
    assert all(sha(w.ROOT/p)==expected for p,expected in lock['preserved_fresh'].items())
    write_json(RUN/'SOURCE_MANIFEST.json',dict(fresh_unchanged=True,scripts={p:sha(w.ROOT/p) for p in
        ['scripts/research_scalp_microzones_v3.py','scripts/research_scalp_weekly_v3.py','scripts/can_ho_tro_scalp_core.py','scripts/can_ho_tro_scalp_plan.py']}))
    print('DONE',len(summaries),'scenarios; Fresh unchanged',flush=True)


if __name__=='__main__':main()
