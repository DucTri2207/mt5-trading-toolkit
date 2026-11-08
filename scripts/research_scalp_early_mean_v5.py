"""Independent M1 reclaim of an already-closed M5 band, before M5 confirmation."""
from __future__ import annotations

import argparse
import json

import numpy as np
from numba import njit

from can_ho_tro_scalp_core import bars_matrix,ema50,metaquotes_atr
from prepare_can_ho_tro_scalp import sha,write_json
import research_scalp_range_v4 as prior
import research_scalp_weekly_v3 as w

RUN=w.ROOT/'reports/can_ho_tro_scalp/20261101_early_mean_v5'
NAMES={11:'EARLY_M15',12:'EARLY_H1',13:'EARLY_NO_CONTEXT'}
SPECS=[dict(name='EARLY_M15',sources=[11]),dict(name='EARLY_H1',sources=[12]),
       dict(name='EARLY_COMBO',sources=[0,11,12]),dict(name='EARLY_NO_CONTEXT',sources=[13])]


def freeze():
    RUN.mkdir(parents=True,exist_ok=True)
    lock=dict(version='early_mean_v5',start=w.START,end_exclusive=w.END,
              hypotheses=SPECS,costs=w.COSTS,data_sha256=sha(w.BASE/'rates.npz'),
              preserved_fresh={p:sha(w.ROOT/p) for p in w.FRESH_PATHS},
              prior_registry_sha256=sha(w.ROOT/'reports/can_ho_tro_scalp/20261101_limit_v4/CUMULATIVE_REGISTRY.json'),
              motivation='M5 mean-return confirmation left1248 NO_CONTEXT/BASE signals with<.8R room; test earlier independent M1 reclaim,not future-M5-conditioned M1 entries.',
              definitions=dict(source='last CLOSED M5 EMA20 +/-2.5 rolling MetaQuotes ATR14 known BEFORE M1 sweep open; source-close age<=300s;freeze band,mean,ATR5,source time on first excursion',
                               trigger='CLOSED M1 first band excursion;reclaim within3 M1 bars including first;directional body>=.1 frozen previous-M1 ATR14,range>=.5 same ATR1,close in directional outer35%;one signal/side until prior M1 close crosses latest closed-M5 EMA20',
                               causal='never require a future M5 rejection;source M5 open+300<=M1 sweep open;context uses closed bars before sweep and confirmation open',
                               context='M15/H1 Wilder ADX14<=20 andabs(EMA20-EMA20[6])<=.5 context ATR14;NO_CONTEXT is a new no-filter control',
                               stop='entire M1 excursion extreme +/- .25 frozenATR5;min2/max20 price units from tested Plan and actual fill',
                               target='frozen source EMA20 rounded outward;actual quote-side room>=.8 initialR or reject without fill/fee;SELL requires Ask at target',
                               execution='same range_v4 simulation:market Bid/Ask,M1 adverse-first,first quote<=60s,120min hold,21:00feed cutoff;Fresh TP.5R/6h with cutoff',
                               gaps='reset excursion on M1 gaps>60s or missing/stale M5 source;no forward-fill',
                               hours='08:00<=M1 confirmation-open feed hour<19:00;not claimed London/NY time',
                               caps='one position,max2 filled entries/day,max10/ISO feed week;no forced weekly trades',
                               priority='Fresh then EARLY_M15 then EARLY_H1;only selected source groups;unchanged serial engine'),
              statistical_screen=dict(family_size=78,prior_hypotheses=74,min_trades=1000,
                                      annual_stability='all full years2022-2025 BASE net positive',
                                      costs='BASE/STRESS positive net expectancy;family-adjusted month bootstrap lower>0'),
              objective=dict(win_rate_min_percent=55,target_percent=[55,60],mean_trades_week=[5,10],zero_empty_market_data_weeks=True),
              selection='prior calendar years,120min purge,>=200 train trades,positive netR,>=55% wins,mean5-10/week,no empty train weeks;rank BASE R/week;cash if none;continuous serial execution',
              bootstrap_seed=20261106,bootstrap_resamples=20000,
              caveats=['All2021-2026 data previously inspected;retrospective,not pristine OOS.',
                       'M1 ATR affects trigger body/range;candidate ATR field stores frozen source ATR5 for stop provenance.',
                       'M1OHLC cannot verify tick execution,dynamic spread or news slippage;fees/clock/prop package unverified.',
                       'At least78 tracked hypotheses plus earlier untracked research;positive historical P&L is not a profit guarantee.'])
    path=RUN/'EXPERIMENT_LOCK.json'
    if path.exists():assert json.loads(path.read_text(encoding='utf-8'))==lock,'Changed frozen definitions'
    else:write_json(path,lock)
    return lock


@njit(cache=True)
def detect_early(m1,m5,h1,ctx,ctxseconds,family,start,stop):
    ma5=w.ema(m5,20);a5=metaquotes_atr(m5);amin=metaquotes_atr(m1)
    a1=metaquotes_atr(h1);ma1=ema50(h1)
    cma=w.ema(ctx,20);catr=metaquotes_atr(ctx);cadx,_,_=w.wilder_adx(ctx)
    rows=[];state=np.zeros(2,np.int64);first=np.zeros(2,np.int64);source_index=np.zeros(2,np.int64)
    frozen_a5=np.zeros(2);frozen_amin=np.zeros(2);band=np.zeros(2);mean=np.zeros(2);anchor=np.zeros(2)
    eligible=np.zeros(2,np.bool_)
    for c in range(40,len(m1)):
        at=m1[c,0];known=at+60
        if known>=stop:break
        si=np.searchsorted(m5[:,0],at-300,side='right')-1
        if si<40 or at-(m5[si,0]+300)>300 or m1[c,0]-m1[c-1,0]!=60:
            state[:]=0;continue
        if a5[si]<=0 or amin[c-1]<=0:continue
        o,h,l,close=m1[c,1:5]
        context=family==13 or prior.context_ok(at,ctx,ctxseconds,cma,catr,cadx)
        for side in range(2):
            buy=side==0;d=1 if buy else -1
            if state[side]==2 and d*(m1[c-1,4]-ma5[si])>=0:state[side]=0
            if state[side]==0:
                boundary=ma5[si]-d*2.5*a5[si]
                if (l<=boundary if buy else h>=boundary):
                    state[side]=1;first[side]=c;source_index[side]=si;frozen_a5[side]=a5[si]
                    frozen_amin[side]=amin[c-1];band[side]=boundary;mean[side]=ma5[si]
                    anchor[side]=l if buy else h;eligible[side]=context
            if state[side]!=1:continue
            anchor[side]=min(anchor[side],l) if buy else max(anchor[side],h)
            if c-first[side]>2:state[side]=2;continue
            a=frozen_amin[side];rng=h-l
            valid=d*(close-band[side])>0 and d*(close-o)>=.1*a and rng>=.5*a
            if valid:valid=((close-l)/rng if buy else (h-close)/rng)>=.65
            if valid:
                p=first[side];source=source_index[side]
                if eligible[side] and context and known>=start and 8<=int(at//3600)%24<19:
                    row=w.make_candidate(m1,c,60,buy,m5[source,0],m5[source,0]+300,band[side],
                                         m1[p,0],anchor[side],frozen_a5[side],family,h1,ma1,a1)
                    row[19]=anchor[side]-d*.25*frozen_a5[side]
                    row[29]=mean[side];row[30]=mean[side];row[31]=m5[source,0]+300;row[32]=row[31]
                    rows.append(row)
                state[side]=2
    out=np.empty((len(rows),40))
    for i in range(len(rows)):out[i]=rows[i]
    return out


def detect(arrays,family,start=w.START,stop=w.END):
    ctx=w.aggregate_complete(arrays['m5'],900) if family==11 else arrays['h1']
    return detect_early(arrays['m1'],arrays['m5'],arrays['h1'],ctx,900 if family==11 else 3600,family,start,stop)


def walkforward(feed,raw,market,cost):
    lookup={s['name']:s for s in SPECS};schedule={};choices=[]
    for year in range(2023,2027):
        boundary=int(w.datetime(year,1,1,tzinfo=w.timezone.utc).timestamp());rank=[]
        for spec in SPECS:
            train=[t for t in feed[spec['name']] if t['state']=='CLOSED' and t['exit_time']<boundary-7200]
            metric=w.metrics(train);f=w.weekly(train,market,w.START,boundary-7200)
            if metric['n']>=200 and metric['total_r']>0 and (metric['win_rate'] or 0)>=55 and f['weeks'] and not f['empty_weeks'] and 5<=f['mean']<=10:
                rank.append((metric['total_r']/f['weeks'],spec['name']))
        if rank:
            score,name=max(rank);schedule[year]=lookup[name];choices.append(dict(year=year,selected=name,train_r_week=score))
        else:choices.append(dict(year=year,selected='CASH'))
    trades,rejects=prior.run_serial(raw,market,None,cost,schedule=schedule)
    return dict(choices=choices,metrics=w.metrics(trades),rejections=rejects,label='retrospective prior-year choice'),trades


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--freeze-only',action='store_true');args=parser.parse_args()
    lock=freeze()
    if args.freeze_only:return
    w.FAMILIES.update(NAMES);source=np.load(w.BASE/'rates.npz');arrays={k:bars_matrix(source[k]) for k in source.files};parts=[]
    for family,name in NAMES.items():
        cache=RUN/(name+'_candidates.npz')
        if cache.exists():raw=np.load(cache)['raw']
        else:raw=detect(arrays,family);np.savez_compressed(cache,raw=raw)
        assert np.all(raw[:,12]<=raw[:,13]) and np.all(raw[:,39]<=raw[:,0])
        print('CANDIDATES',name,len(raw),flush=True);parts.append(raw)
    raw=w.add_fresh(np.concatenate(parts));rows=[];feed={}
    for spec in SPECS:
        for cost in w.COSTS:
            label=spec['name']+'_'+cost['id'];path=RUN/(label+'_trades.json')
            if path.exists():saved=json.loads(path.read_text());trades=saved['trades'];rejects=saved['rejections']
            else:
                trades,rejects=prior.run_serial(raw,arrays['m1'],spec,cost)
                write_json(path,dict(trades=trades,rejections=rejects))
            metric=w.summarize(trades,arrays['m1'],lock);f=metric['frequency']
            rows.append(dict(name=spec['name'],cost=cost['id'],metrics=metric,rejections=rejects))
            if cost['id']=='BASE':feed[spec['name']]=trades
            print(label,'n',metric['n'],'win',round(metric['win_rate'] or 0,2),'PF',round(metric['pf'] or 0,3),
                  'R',round(metric['total_r'],2),'week',round(f['mean'],2),'empty',len(f['empty_weeks']),flush=True)
    wf={}
    for cost in w.COSTS:
        metric,trades=walkforward(feed,raw,arrays['m1'],cost);wf[cost['id']]=metric
        write_json(RUN/('WALKFORWARD_'+cost['id']+'_trades.json'),trades)
    write_json(RUN/'summary.json',dict(rows=rows,walkforward=wf,lock_sha256=sha(RUN/'EXPERIMENT_LOCK.json')))
    assert all(sha(w.ROOT/p)==value for p,value in lock['preserved_fresh'].items())
    write_json(RUN/'SOURCE_MANIFEST.json',dict(fresh_unchanged=True,scripts={p:sha(w.ROOT/p) for p in
        ['scripts/research_scalp_early_mean_v5.py','scripts/research_scalp_range_v4.py',
         'scripts/can_ho_tro_scalp_plan.py','scripts/research_scalp_weekly_v3.py']}))
    print('DONE',len(rows),'scenarios; Fresh unchanged',flush=True)


if __name__=='__main__':main()
