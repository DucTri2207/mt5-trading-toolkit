"""Range-context complement to Fresh: frozen Keltner rejection to frozen mean."""
from __future__ import annotations

import argparse
from collections import Counter
import json

import numpy as np
from numba import njit

from can_ho_tro_scalp_core import bars_matrix,ema50,metaquotes_atr
from can_ho_tro_scalp_plan import Plan,idea_key,planned_gate,round_tick
from prepare_can_ho_tro_scalp import sha,write_json
from replay_can_ho_tro_scalp import as_result
import research_scalp_weekly_v3 as w

RUN=w.ROOT/'reports/can_ho_tro_scalp/20261101_range_v4'
NAMES={8:'RANGE_M15',9:'RANGE_H1',10:'NO_CONTEXT'}
SPECS=[dict(name='RANGE_M15',sources=[8]),dict(name='RANGE_H1',sources=[9]),
       dict(name='RANGE_COMBO',sources=[0,8,9]),dict(name='NO_CONTEXT',sources=[10])]


def freeze():
    RUN.mkdir(parents=True,exist_ok=True)
    lock=dict(version='range_v4',start=w.START,end_exclusive=w.END,
              hypotheses=SPECS,costs=w.COSTS,data_sha256=sha(w.BASE/'rates.npz'),
              preserved_fresh={p:sha(w.ROOT/p) for p in w.FRESH_PATHS},
              motivation='Trend/pivot and passive-entry extensions lost money. Test a different context: fade a first band excursion only when higher-timeframe trend strength and mean slope are low.',
              definitions=dict(band='previous CLOSED M5 EMA20 +/-2.5 MetaQuotes rolling ATR14, frozen at excursion start; no current-bar band inputs',
                               context='last CLOSED M15 or H1 before sweep AND before confirmation: Wilder ADX14<=20 and abs(EMA20-EMA20[6bars earlier])<=.5 context ATR14; NO_CONTEXT is the new no-filter control',
                               trigger='first excursion beyond band; reclaim frozen band within3 M5 bars including first; directional body>=.1 frozenATR,range>=.5 frozenATR,close in directional outer35%;one signal/side until price closes across live EMA20',
                               stop='entire excursion extreme +/- .25 frozenATR;tested Plan withSLmin2/max20;actual quote fillrisk',
                               target='frozen pre-excursion EMA20 rounded outward; admit only if actual quote-side target distance / actual initialrisk >=.8; no grid of RR exits',
                               sell='EMA is computed from Bid bars; SELL target requires Ask to reach frozen EMA,not merely Bid touching EMA',
                               execution='market Bid/Ask;first quote<=60s;M1 stop-before-target if both touched;max120min and21:00feed cutoff;source0 Fresh retainsTP.5R/6h with same cutoff',
                               hours='08:00<=confirmation bar-open feed hour<19:00;clock mapping unverified',
                               caps='one position,max2 filled entries/feed day,max10/feed ISO week;no forced entries',
                               priority='Fresh then M15-range then H1-range;fixed source rank;skip signals outside selected source group'),
              statistical_screen=dict(family_size=74,prior_hypotheses=70,min_trades=1000,
                                      annual_stability='full years2022-2025 BASE net positive',
                                      costs='positive expectancy BASE/STRESS and family-adjusted monthly bootstrap lower>0'),
              objective=dict(win_rate_min_percent=55,target_percent=[55,60],mean_trades_week=[5,10],zero_empty_market_data_weeks=True),
              selection='prior calendar years,120min purge,>=200 train trades,net positive,>=55% wins,5-10 mean entries/week and no empty train weeks;rank BASE netR/marketweek;cash if none;continuous serial execution across years',
              bootstrap_seed=20261105,bootstrap_resamples=20000,
              caveats=['All data have previously been inspected;retrospective even with chronological selection.',
                       'Keltner/ADX transfer is our hypothesis,not a published XAUUSD preset.',
                       'Assumed costs,M1 adverse-first,not actual ticks;broker fees/clock/news/prop conditions unverified.',
                       'At least74 tracked hypotheses plus earlier untracked research.'])
    path=RUN/'EXPERIMENT_LOCK.json'
    if path.exists():assert json.loads(path.read_text(encoding='utf-8'))==lock
    else:write_json(path,lock)
    return lock


@njit(cache=True)
def context_ok(at,bars,seconds,ma,atr,adx):
    i=np.searchsorted(bars[:,0],at-seconds,side='right')-1
    return i>=40 and adx[i]<=20 and atr[i]>0 and abs(ma[i]-ma[i-6])<=.5*atr[i]


@njit(cache=True)
def detect_range(m5,h1,ctx,ctxseconds,family,start,stop):
    atr=metaquotes_atr(m5);ma=w.ema(m5,20);a1=metaquotes_atr(h1);ma1=ema50(h1)
    context_ma=w.ema(ctx,20);context_atr=metaquotes_atr(ctx);context_adx,_,_=w.wilder_adx(ctx)
    rows=[];state=np.zeros(2,np.int64);first=np.zeros(2,np.int64)
    frozen_atr=np.zeros(2);band=np.zeros(2);mean=np.zeros(2);anchor=np.zeros(2);eligible=np.zeros(2,np.bool_)
    for c in range(40,len(m5)):
        at=m5[c,0];known=at+300
        if known>=stop:break
        if m5[c,0]-m5[c-1,0]!=300:state[:]=0;continue
        a=atr[c-1]
        if a<=0:continue
        o,h,l,close=m5[c,1:5]
        ctx_now=family==10 or context_ok(at,ctx,ctxseconds,context_ma,context_atr,context_adx)
        for side in range(2):
            buy=side==0;d=1 if buy else -1
            if state[side]==2 and d*(m5[c-1,4]-ma[c-1])>=0:state[side]=0
            if state[side]==0:
                boundary=ma[c-1]-d*2.5*a
                if (l<=boundary if buy else h>=boundary):
                    state[side]=1;first[side]=c;frozen_atr[side]=a;band[side]=boundary
                    mean[side]=ma[c-1];anchor[side]=l if buy else h;eligible[side]=ctx_now
            if state[side]!=1:continue
            anchor[side]=min(anchor[side],l) if buy else max(anchor[side],h)
            if c-first[side]>2:state[side]=2;continue
            fa=frozen_atr[side];rng=h-l
            valid=d*(close-band[side])>0 and d*(close-o)>=.1*fa and rng>=.5*fa
            if valid:valid=((close-l)/rng if buy else (h-close)/rng)>=.65
            if valid:
                p=first[side]
                if eligible[side] and ctx_now and known>=start and 8<=int(at//3600)%24<19:
                    r=w.make_candidate(m5,c,300,buy,m5[p-1,0],m5[p-1,0]+300,
                                       band[side],m5[p,0],anchor[side],fa,family,h1,ma1,a1)
                    r[19]=anchor[side]-d*.25*fa
                    r[29]=mean[side];r[30]=mean[side];r[31]=m5[p-1,0]+300;r[32]=r[31]
                    rows.append(r)
                state[side]=2
    out=np.empty((len(rows),40))
    for i in range(len(rows)):out[i]=rows[i]
    return out


def detect(arrays,family,start=w.START,stop=w.END):
    ctx=w.aggregate_complete(arrays['m5'],900) if family==8 else arrays['h1']
    seconds=900 if family==8 else 3600
    return detect_range(arrays['m5'],arrays['h1'],ctx,seconds,family,start,stop)


def simulate(index,c,market,cost):
    p=w.WeeklyPlan(c,'T05',cost['spread'],cost['slip'],.01);p.rr=.8
    left=int(np.searchsorted(market[:,0],c[1],side='left'))
    if left==len(market):p.state='REJECTED';p.reason='NO_ENTRY_QUOTE'
    else:
        first=market[left];p.start(int(first[0]),float(first[1]),float(first[1])+p.spread)
        if p.state=='FILLED' and int(c[36])!=0:
            target=round_tick(c[29],.01,p.d)
            if p.d*(target-p.entry)/p.risk<.8-1e-12:
                # The preview used the first available quote. No trade is admitted or charged.
                p=w.WeeklyPlan(c,'T05',cost['spread'],cost['slip'],.01)
                p.state='REJECTED';p.reason='MEAN_ROOM_BELOW_08R'
            else:p.target=target
        for i in range(left,len(market)):
            if p.state!='FILLED':break
            b=market[i];at=int(b[0])
            if i>left and at-market[i-1,0]>60:p.gaps+=1
            p.quote(at,float(b[1]),float(b[1])+p.spread)
            if p.state=='FILLED':p.minute_range(at,float(b[2]),float(b[3]),float(b[4]))
        if p.state=='FILLED':p.state='CENSORED_FILLED';p.reason='END_OF_DATA'
    result=as_result(p,index,'M1_ADVERSE_FIRST')
    fee=cost['commission_price']/p.risk if p.entry_time else 0.
    result.update(gross_r=result['r'],commission_r=fee,source=w.FAMILIES[int(c[36])],
                  source_known_at=int(c[37]),h1_known_at=int(c[39]),target=p.target,deadline=p.deadline,
                  frozen_mean=float(c[29]) if int(c[36]) else None)
    if result['r'] is not None:result['r']-=fee
    return result


def run_serial(raw,market,spec,cost,schedule=None):
    out=[];seen=set();busy=0;chosen=-1;days=Counter();weeks=Counter();rejects=Counter()
    for index,c in enumerate(raw):
        at=int(c[1])
        if schedule is not None:
            spec=schedule.get(w.datetime.fromtimestamp(at,w.timezone.utc).year)
            if spec is None:continue
        if int(c[36]) not in spec['sources'] or planned_gate(c)!='PASS':continue
        if at<busy:rejects['BUSY']+=1;continue
        if at==chosen:rejects['PRIORITY']+=1;continue
        chosen=at;key=idea_key(c);day=at//86400;week=w.week_key(at)
        if key in seen:rejects['DUPLICATE']+=1;continue
        if days[day]>=2 or weeks[week]>=10:rejects['CAP']+=1;continue
        seen.add(key);row=simulate(index,c,market,cost);out.append(row)
        if row['entry_time']:days[day]+=1;weeks[week]+=1
        if row['state'].startswith('CENSORED'):busy=int(market[-1,0])+60
        elif row['exit_time']:busy=row['exit_time']
    return out,dict(rejects)


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
    trades,rejects=run_serial(raw,market,None,cost,schedule=schedule)
    return dict(choices=choices,metrics=w.metrics(trades),rejections=rejects,label='retrospective prior-year choice'),trades


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--freeze-only',action='store_true');args=parser.parse_args()
    lock=freeze()
    if args.freeze_only:return
    w.FAMILIES.update(NAMES);data=np.load(w.BASE/'rates.npz');arrays={k:bars_matrix(data[k]) for k in data.files};parts=[]
    for family,name in NAMES.items():
        path=RUN/(name+'_candidates.npz')
        if path.exists():raw=np.load(path)['raw']
        else:raw=detect(arrays,family);np.savez_compressed(path,raw=raw)
        assert np.all(raw[:,12]<=raw[:,13]) and np.all(raw[:,39]<=raw[:,0])
        print('CANDIDATES',name,len(raw),flush=True);parts.append(raw)
    raw=w.add_fresh(np.concatenate(parts));rows=[];feed={}
    for spec in SPECS:
        for cost in w.COSTS:
            label=spec['name']+'_'+cost['id'];path=RUN/(label+'_trades.json')
            if path.exists():saved=json.loads(path.read_text());trades=saved['trades'];rejects=saved['rejections']
            else:
                trades,rejects=run_serial(raw,arrays['m1'],spec,cost);write_json(path,dict(trades=trades,rejections=rejects))
            metric=w.summarize(trades,arrays['m1'],lock);f=metric['frequency']
            rows.append(dict(name=spec['name'],cost=cost['id'],metrics=metric,rejections=rejects))
            if cost['id']=='BASE':feed[spec['name']]=trades
            print(label,'n',metric['n'],'win',round(metric['win_rate'] or 0,2),'PF',round(metric['pf'] or 0,3),
                  'R',round(metric['total_r'],2),'week',round(f['mean'],2),'empty',len(f['empty_weeks']),flush=True)
    wf={}
    for cost in w.COSTS:
        summary,trades=walkforward(feed,raw,arrays['m1'],cost);wf[cost['id']]=summary
        write_json(RUN/('WALKFORWARD_'+cost['id']+'_trades.json'),trades)
    write_json(RUN/'summary.json',dict(rows=rows,walkforward=wf,lock_sha256=sha(RUN/'EXPERIMENT_LOCK.json')))
    assert all(sha(w.ROOT/p)==value for p,value in lock['preserved_fresh'].items())
    write_json(RUN/'SOURCE_MANIFEST.json',dict(fresh_unchanged=True,scripts={p:sha(w.ROOT/p) for p in
        ['scripts/research_scalp_range_v4.py','scripts/can_ho_tro_scalp_plan.py','scripts/research_scalp_weekly_v3.py']}))
    print('DONE',len(rows),'scenarios; Fresh unchanged',flush=True)


if __name__=='__main__':main()
