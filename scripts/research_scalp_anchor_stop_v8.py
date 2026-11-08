"""One structural-stop experiment on the frozen AVWAP retest event stream."""
from __future__ import annotations

import argparse
import json

import numpy as np

from can_ho_tro_scalp_core import bars_matrix
from prepare_can_ho_tro_scalp import sha, write_json
import research_scalp_avwap_v7 as v

w = v.w
RUN = w.ROOT/'reports/can_ho_tro_scalp/20261101_anchor_stop_v8'
SPECS = [dict(name='ANCHOR_SWING',sources=[17]),dict(name='ANCHOR_COMBO',sources=[0,17]),
         dict(name='ANCHOR_EQUAL_WEIGHT',sources=[19])]
ZERO = dict(id='ZERO',spread=0.,slip=0.,commission_price=0.)


def freeze():
    RUN.mkdir(parents=True,exist_ok=True)
    lock = dict(version='avwap_structural_anchor_stop_v8',start=w.START,end_exclusive=w.END,
        hypotheses=SPECS,costs=w.COSTS,diagnostic_costs=[dict(spec='ANCHOR_SWING',cost=ZERO,not_deployable=True)],
        data_sha256=sha(w.BASE/'rates.npz'),
        prior_registry_sha256=sha(v.RUN/'CUMULATIVE_REGISTRY.json'),
        frozen_signal_inputs={name:sha(v.RUN/(name+'_candidates.npz')) for name in ('SWING_AVWAP','SWING_EQUAL_WEIGHT')},
        dependencies={p:sha(w.ROOT/p) for p in ['scripts/research_scalp_avwap_v7.py','scripts/research_scalp_weekly_v3.py','scripts/can_ho_tro_scalp_plan.py']},
        preserved_fresh={p:sha(w.ROOT/p) for p in w.FRESH_PATHS},
        motivation='SWING_AVWAP zero-friction:+45.64R/1678 trades vsBASE-164.81R/1676;538 BASE fills hadmin2 risk,medianrisk2.745. Test natural invalidation beyond knownM15 anchor instead of scanning widths.',
        definitions=dict(signal='EXACT frozen SWING_AVWAP/SWING_EQUAL_WEIGHT v7 candidates,unchanged times,anchors,filters,reference,hours;no regenerated signal search',
            stop='BUY:min(original touch-through-confirmation low,sourceM15 pivot low)-.25 frozenM5ATR;SELL:max(original retest high,sourceM15 pivot high)+.25 frozenATR;sourceM15 and pivot confirmation known before touch',
            risk='unchanged actualfillmin2/max20;reject >20,never squeeze protective stop inside either known structural extreme',
            target='unchanged.8 actualinitialR;Fresh.5R;max120min/21:00feed cutoff,Fresh6h withcutoff',
            execution='same v7 simulate/run_serial with correct fee metadata:Bid/Ask,slippage,commission once,M1 adverse-first,gaps,one position,max2fills/day,10/week',
            combo='Fresh plus SWING_AVWAP only;DAY_VWAP omitted because its179 fills/132 empty weeks failed frequency',
            control='equal-minute-weight anchored mean uses same protective-stop rule;one predeclared ZERO-cost weighted-only diagnostic,not a tradable fee schedule',
            provenance='columns19/20 become new stop/outer anchor;column14 keeps original retest extreme;sourceM15 price reconstructed only from matching known source time'),
        statistical_screen=dict(family_size=90,prior_hypotheses=87,min_trades=1000,
            annual_stability='all full years2022-2025 BASE positive',costs='BASE/STRESS positive and family-adjusted month bootstrap lower>0'),
        objective=dict(win_rate_min_percent=55,target_percent=[55,60],mean_trades_week=[5,10],zero_empty_market_data_weeks=True),
        selection='prior years only,120min purge,>=200 train trades,positive net,>=55% wins,mean5-10/week,no empty train weeks;rankBASE R/week;cash if none',
        bootstrap_seed=20261109,bootstrap_resamples=20000,
        caveats=['Retrospective;all history inspected;new definition motivated by already observed v7 outcomes.',
            'Stop is a new tradable hypothesis and counted;no threshold/holding/TP grid.',
            'V7 tick-volume proxy,coverage,clock andfee limitations still apply.',
            'At least90 tracked hypotheses plus earlier untracked selection;not a future-profit guarantee.'])
    path=RUN/'EXPERIMENT_LOCK.json'
    if path.exists():
        assert json.loads(path.read_text(encoding='utf-8'))==lock,'Never change frozen definitions'
    else:
        write_json(path,lock)
    return lock


def replace_stops(raw,m15):
    out=raw.copy()
    for i,c in enumerate(out):
        index=int(np.searchsorted(m15[:,0],c[3],side='left'))
        if index==len(m15) or m15[index,0]!=c[3]:
            raise ValueError('Missing source M15 anchor bar')
        if not m15[index,0]+900<=c[17]<=c[13]:
            raise ValueError('M15 pivot/reference unavailable at touch')
        buy=bool(c[2]);d=1 if buy else -1
        source=m15[index,3 if buy else 2]
        outer=min(c[20],source) if buy else max(c[20],source)
        out[i,20]=outer;out[i,19]=outer-d*.25*c[18]
    return out


def candidate_parts(arrays):
    m15=w.aggregate_complete(arrays['m5'],900);parts=[]
    for name in ('SWING_AVWAP','SWING_EQUAL_WEIGHT'):
        source=np.load(v.RUN/(name+'_candidates.npz'))['raw'];path=RUN/(name+'_anchor_candidates.npz')
        if path.exists():
            raw=np.load(path)['raw']
        else:
            raw=replace_stops(source,m15);np.savez_compressed(path,raw=raw)
        unchanged=[k for k in range(40) if k not in (19,20)]
        np.testing.assert_array_equal(raw[:,unchanged],source[:,unchanged])
        parts.append(raw)
    return parts


def walkforward(feed,raw,market,cost):
    lookup={s['name']:s for s in SPECS};schedule={};choices=[]
    for year in range(2023,2027):
        boundary=int(w.datetime(year,1,1,tzinfo=w.timezone.utc).timestamp());rank=[]
        for spec in SPECS:
            train=[t for t in feed[spec['name']] if t['state']=='CLOSED' and t['exit_time']<boundary-7200]
            m=w.metrics(train);freq=w.weekly(train,market,w.START,boundary-7200)
            if m['n']>=200 and m['total_r']>0 and (m['win_rate'] or 0)>=55 and freq['weeks'] and not freq['empty_weeks'] and 5<=freq['mean']<=10:
                rank.append((m['total_r']/freq['weeks'],spec['name']))
        if rank:
            score,name=max(rank);schedule[year]=lookup[name];choices.append(dict(year=year,selected=name,train_r_week=score))
        else:
            choices.append(dict(year=year,selected='CASH'))
    trades,rejects=v.run_serial(raw,market,None,cost,schedule=schedule)
    return dict(choices=choices,metrics=w.metrics(trades),rejections=rejects,label='retrospective prior-year choice'),trades


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--freeze-only',action='store_true');args=parser.parse_args()
    lock=freeze()
    if args.freeze_only:return
    w.FAMILIES.update(v.NAMES);source=np.load(w.BASE/'rates.npz');arrays={k:bars_matrix(source[k]) for k in source.files}
    raw=w.add_fresh(np.concatenate(candidate_parts(arrays)));rows=[];feed={}
    for spec in SPECS:
        costs=w.COSTS+([ZERO] if spec['name']=='ANCHOR_SWING' else [])
        for cost in costs:
            label=spec['name']+'_'+cost['id'];path=RUN/(label+'_trades.json')
            if path.exists():
                saved=json.loads(path.read_text());trades=saved['trades'];rejects=saved['rejections']
            else:
                trades,rejects=v.run_serial(raw,arrays['m1'],spec,cost);write_json(path,dict(trades=trades,rejections=rejects))
            m=w.summarize(trades,arrays['m1'],lock);freq=m['frequency']
            rows.append(dict(name=spec['name'],cost=cost['id'],metrics=m,rejections=rejects,not_deployable=cost['id']=='ZERO'))
            if cost['id']=='BASE':feed[spec['name']]=trades
            print(label,'n',m['n'],'win',round(m['win_rate'] or 0,2),'PF',round(m['pf'] or 0,3),
                  'R',round(m['total_r'],2),'week',round(freq['mean'],2),'empty',len(freq['empty_weeks']),flush=True)
    wf={}
    for cost in w.COSTS:
        metric,trades=walkforward(feed,raw,arrays['m1'],cost);wf[cost['id']]=metric
        write_json(RUN/('WALKFORWARD_'+cost['id']+'_trades.json'),trades)
    write_json(RUN/'summary.json',dict(rows=rows,walkforward=wf,lock_sha256=sha(RUN/'EXPERIMENT_LOCK.json')))
    assert all(sha(w.ROOT/p)==value for p,value in lock['preserved_fresh'].items())
    write_json(RUN/'SOURCE_MANIFEST.json',dict(fresh_unchanged=True,scripts={p:sha(w.ROOT/p) for p in
        ['scripts/research_scalp_anchor_stop_v8.py','scripts/research_scalp_avwap_v7.py','scripts/research_scalp_weekly_v3.py','scripts/can_ho_tro_scalp_plan.py']}))
    print('DONE',len(rows),'scenarios;Fresh unchanged',flush=True)


if __name__=='__main__':main()
