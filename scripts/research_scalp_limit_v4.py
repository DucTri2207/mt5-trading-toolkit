"""Predeclared entry-location test on frozen v3 signals; no broker access."""
from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime,timezone
import json

import numpy as np

from can_ho_tro_scalp_core import bars_matrix
from can_ho_tro_scalp_plan import idea_key,planned_gate,round_tick
from prepare_can_ho_tro_scalp import sha,write_json
from replay_can_ho_tro_scalp import as_result,path_segment
import research_scalp_weekly_v3 as w
import research_scalp_microzones_v3 as micro

RUN=w.ROOT/'reports/can_ho_tro_scalp/20261101_limit_v4'
SPECS=[dict(name=f'{group}_{mode}_R{int(rr*100)}',group=group,mode=mode,rr=rr)
       for group in ('WEEKLY','MICRO') for mode in ('SHALLOW','MIDPOINT','LEVEL','MARKET') for rr in (.8,1.)]
NEW_HYPOTHESES=12
PATHS=('OLHC','OHLC')


def freeze():
    RUN.mkdir(parents=True,exist_ok=True)
    candidate_paths=[w.RUN/'detector_weekly.npz']+[micro.RUN/(name+'_candidates.npz') for name in micro.NAMES.values()]
    lock=dict(version='limit_v4',start=w.START,end_exclusive=w.END,
              hypotheses=SPECS,new_hypotheses=NEW_HYPOTHESES,market_controls=4,costs=w.COSTS,paths=PATHS,
              data_sha256=sha(w.BASE/'rates.npz'),
              signals_sha256={str(p.relative_to(w.ROOT)):sha(p) for p in candidate_paths},
              preserved_fresh={p:sha(w.ROOT/p) for p in w.FRESH_PATHS},
              motivation='v3 high-frequency market entries lose even without costs; test whether paying later after confirmation is responsible, while preserving signal rules.',
              source='Frozen weekly_v3 or microzones_v3 candidates; Fresh remains market TP.5R in combined execution; priority and idea dedup preserved.',
              entry=dict(SHALLOW='limit at confirmation close minus direction*.15 trigger ATR, rounded away from market',
                         MIDPOINT='limit at original confirmation-body midpoint, rounded away from market',
                         LEVEL='limit at pre-existing reference pivot/EMA/source broken pivot, rounded away from market',
                         MARKET='same v3 market entry, control hypothesis already counted',
                         pending='must be passive on first quote<=60s; expire after15min; cancel at raw structural SL or outside08:00<=feed_hour<19:00; no fallback or chasing',
                         fills='BUY touches on Ask,SELL on Bid; fill at requested limit, no favorable gap improvement; gap across raw SL cancels before fill; no queue or tick-depth claim'),
              exit='same actual-fill SLmin2/max20, fixed TP.8/1R,120min hold and21:00 feed cutoff; Fresh market TP.5R/6h with cutoff',
              caps='single live idea including pending;max2 filled entries/feed day,max10/feed ISO week; no forced entries',
              statistical_screen=dict(family_size=70,prior_hypotheses=58,min_trades=1000,
                                      annual_stability='full years2022-2025 BASE net positive',
                                      costs='positive expectancy both paths BASE/STRESS plus adjusted bootstrap lower>0'),
              objective=dict(win_rate_min_percent=55,target_percent=[55,60],mean_trades_week=[5,10],zero_empty_market_data_weeks=True),
              selection='same fixed set only; choose using prior calendar years,120min purge,>=200 train trades,BASE net positive,>=55% net wins,mean5-10/week and no empty train weeks in BOTH paths; rank smaller BASE netR/week across paths; apply same choice to all costs/paths',
              bootstrap_seed=20261104,bootstrap_resamples=20000,
              caveats=['All historical data previously inspected; retrospective,not pristine OOS.',
                       'OHLC/OLHC piecewise paths at0/20/40/59s are scenarios,not real ticks or universal P&L bounds.',
                       'Quote touch does not verify broker execution or queue;fees/feed-clock/news/prop rules unverified.',
                       'At least70 tracked hypotheses;earlier untracked research remains additional selection bias.'])
    path=RUN/'EXPERIMENT_LOCK.json'
    # JSON converts the immutable path tuple to a list.
    lock=json.loads(json.dumps(lock))
    if path.exists():assert json.loads(path.read_text(encoding='utf-8'))==lock,'Never overwrite changed experiment definitions'
    else:write_json(path,lock)
    return lock


def entry_candidate(c,spec):
    out=c.copy();d=1 if c[2] else -1
    if int(c[36])==0 or spec['mode']=='MARKET':return out,False
    if spec['mode']=='SHALLOW':out[22]=c[21]-d*.15*c[18]
    elif spec['mode']=='LEVEL':out[22]=c[16]
    out[22]=round_tick(out[22],.01,-d)
    return out,True


def replay_minute(p,bar,path):
    at=int(bar[0]);o,h,l,close=map(float,bar[1:5])
    p.quote(at,o,o+p.spread)
    points=[o,h,l,close] if path=='OHLC' else [o,l,h,close]
    for i,(begin,end) in enumerate(((0,20),(20,40),(40,59))):
        if p.state not in ('PENDING','FILLED'):break
        path_segment(p,at+begin,points[i],at+end,points[i+1])


def simulate(index,c,market,spec,cost,path,record_equity=False):
    modified,retest=entry_candidate(c,spec)
    p=w.WeeklyPlan(modified,'T05',cost['spread'],cost['slip'],.01,False,retest)
    p.rr=spec['rr'];p.pending_hours=tuple(range(8,19));samples=[]
    if record_equity:p.observer=lambda at,r:samples.append((at,r))
    left=int(np.searchsorted(market[:,0],c[1],side='left'))
    if left==len(market):p.state='REJECTED';p.reason='NO_ENTRY_QUOTE'
    else:
        first=market[left];p.start(int(first[0]),float(first[1]),float(first[1])+p.spread)
        for i in range(left,len(market)):
            if p.state not in ('PENDING','FILLED'):break
            b=market[i]
            if i>left and b[0]-market[i-1,0]>60:p.gaps+=1
            replay_minute(p,b,path)
        if p.state in ('PENDING','FILLED'):p.state='CENSORED_'+p.state;p.reason='END_OF_DATA'
    result=as_result(p,index,'M1_SYNTHETIC_'+path)
    fee=cost['commission_price']/p.risk if p.entry_time else 0.
    result.update(gross_r=result['r'],commission_r=fee,source=w.FAMILIES[int(c[36])],
                  source_known_at=int(c[37]),h1_known_at=int(c[39]),
                  target=p.target,deadline=p.deadline,entry_mode='MARKET' if not retest else spec['mode'])
    if result['r'] is not None:result['r']-=fee
    if record_equity:result['equity_samples']=[(at,r-fee) for at,r in samples]
    return result


def run_serial(raw,market,spec,cost,path,schedule=None):
    rows=[];busy=0;seen=set();days=Counter();weeks=Counter();rejects=Counter();chosen=-1
    for index,c in enumerate(raw):
        at=int(c[1])
        if schedule is not None:
            spec=schedule.get(datetime.fromtimestamp(at,timezone.utc).year)
            if spec is None:continue
        modified,retest=entry_candidate(c,spec)
        if planned_gate(modified,retest=retest)!='PASS':continue
        if at<busy:rejects['BUSY']+=1;continue
        if at==chosen:rejects['PRIORITY']+=1;continue
        chosen=at;key=idea_key(c)
        if key in seen:rejects['DUPLICATE']+=1;continue
        day=at//86400;week=w.week_key(at)
        if days[day]>=2 or weeks[week]>=10:rejects['CAP']+=1;continue
        seen.add(key);result=simulate(index,c,market,spec,cost,path);rows.append(result)
        if result['entry_time']:days[day]+=1;weeks[week]+=1
        if result['state'].startswith('CENSORED'):busy=int(market[-1,0])+60
        elif result['exit_time']:busy=result['exit_time']
    return rows,dict(rejects)


def load_raw():
    w.FAMILIES.update(micro.NAMES)
    weekly=w.add_fresh(np.load(w.RUN/'detector_weekly.npz')['raw'])
    micro_raw=w.add_fresh(np.concatenate([np.load(micro.RUN/(name+'_candidates.npz'))['raw'] for name in micro.NAMES.values()]))
    return dict(WEEKLY=weekly,MICRO=micro_raw)


def walkforward(all_trades,raw_by_group,market,cost,path):
    schedule={};choices=[];lookup={s['name']:s for s in SPECS}
    for year in range(2023,2027):
        boundary=int(datetime(year,1,1,tzinfo=timezone.utc).timestamp());rank=[]
        for spec in SPECS:
            candidates=[]
            for train_path in PATHS:
                train=[t for t in all_trades[spec['name']+'_'+train_path] if t['state']=='CLOSED' and t['exit_time']<boundary-7200]
                metric=w.metrics(train);f=w.weekly(train,market,w.START,boundary-7200)
                if not (metric['n']>=200 and metric['total_r']>0 and (metric['win_rate'] or 0)>=55 and f['weeks'] and not f['empty_weeks'] and 5<=f['mean']<=10):break
                candidates.append(metric['total_r']/f['weeks'])
            if len(candidates)==2:rank.append((min(candidates),spec['name']))
        if rank:
            score,name=max(rank);schedule[year]=lookup[name];choices.append(dict(year=year,selected=name,train_worst_path_r_week=score))
        else:choices.append(dict(year=year,selected='CASH'))
    # Source groups are alternative strategies; only the selected group supplies events each year.
    pieces=[]
    for year,spec in schedule.items():
        raw=raw_by_group[spec['group']]
        left=int(datetime(year,1,1,tzinfo=timezone.utc).timestamp());right=int(datetime(year+1,1,1,tzinfo=timezone.utc).timestamp())
        pieces.append(raw[(raw[:,1]>=left)&(raw[:,1]<right)])
    selected=np.concatenate(pieces) if pieces else np.empty((0,40))
    if len(selected):selected=selected[np.lexsort((selected[:,33],selected[:,36],selected[:,1]))]
    trades,rejects=run_serial(selected,market,None,cost,path,schedule=schedule)
    return dict(choices=choices,metrics=w.metrics(trades),rejections=rejects,
                label='retrospective prior-year selection;same BASE/both-path schedule for all scenarios'),trades


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--freeze-only',action='store_true');args=parser.parse_args()
    lock=freeze()
    if args.freeze_only:return
    raw_by_group=load_raw();data=np.load(w.BASE/'rates.npz');market=bars_matrix(data['m1'])
    summaries=[];base_trades={}
    for spec in SPECS:
        for cost in w.COSTS:
            for path in PATHS:
                label=spec['name']+'_'+cost['id']+'_'+path;dest=RUN/(label+'_trades.json')
                if dest.exists():saved=json.loads(dest.read_text());trades=saved['trades'];rejects=saved['rejections']
                else:
                    trades,rejects=run_serial(raw_by_group[spec['group']],market,spec,cost,path)
                    write_json(dest,dict(trades=trades,rejections=rejects))
                metric=w.summarize(trades,market,lock);f=metric['frequency']
                summaries.append(dict(name=spec['name'],mode=spec['mode'],cost=cost['id'],path=path,metrics=metric,rejections=rejects))
                if cost['id']=='BASE':base_trades[spec['name']+'_'+path]=trades
                print(label,'n',metric['n'],'win',round(metric['win_rate'] or 0,2),'PF',round(metric['pf'] or 0,3),
                      'R',round(metric['total_r'],2),'week',round(f['mean'],2),'empty',len(f['empty_weeks']),flush=True)
    wf={}
    for cost in w.COSTS:
        for path in PATHS:
            metric,trades=walkforward(base_trades,raw_by_group,market,cost,path)
            wf[cost['id']+'_'+path]=metric;write_json(RUN/('WALKFORWARD_'+cost['id']+'_'+path+'_trades.json'),trades)
    write_json(RUN/'summary.json',dict(rows=summaries,walkforward=wf,lock_sha256=sha(RUN/'EXPERIMENT_LOCK.json')))
    assert all(sha(w.ROOT/p)==value for p,value in lock['preserved_fresh'].items())
    write_json(RUN/'SOURCE_MANIFEST.json',dict(fresh_unchanged=True,scripts={p:sha(w.ROOT/p) for p in
        ['scripts/research_scalp_limit_v4.py','scripts/can_ho_tro_scalp_plan.py','scripts/replay_can_ho_tro_scalp.py','scripts/research_scalp_weekly_v3.py']}))
    print('DONE',len(summaries),'scenarios; Fresh unchanged',flush=True)


if __name__=='__main__':main()
