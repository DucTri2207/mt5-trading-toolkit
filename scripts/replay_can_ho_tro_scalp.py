"""Locked five-year replay of the EXISTING H1/sweep/CHoCH setup and exit variants."""
from __future__ import annotations

import argparse
import json
import math
from collections import Counter
from datetime import datetime, timezone

import numpy as np

from prepare_can_ho_tro_scalp import RUN, write_json, sha
from can_ho_tro_scalp_core import bars_matrix
from can_ho_tro_scalp_plan import Plan, planned_gate, idea_key, pivots, propose_structure, round_tick


def choose_candidates(raw, tick, retest=False, room=False):
    selected=[];rejections=Counter();chosen_at=-1
    for index,c in enumerate(raw):
        gate=planned_gate(c,tick,retest,room)
        if gate!='PASS':rejections[gate]+=1;continue
        if int(c[1])==chosen_at:rejections['LOWER_PRIORITY_ZONE']+=1;continue
        selected.append((index,c));chosen_at=int(c[1])
    return selected,rejections


def cancel_context_at(c,h1):
    """Future bars are a scheduled event stream, checked ONLY when known_at arrives."""
    at=int(c[1]);end=at+900
    left=int(np.searchsorted(h1[:,0]+3600,at,side='right'))
    for i in range(left,len(h1)):
        known=int(h1[i,0])+3600
        if known>end:break
        if (bool(c[2]) and h1[i,4]<c[10]) or (not bool(c[2]) and h1[i,4]>c[10]):return known
    return 0


def path_segment(p,t0,x0,t1,x1,cancel_at=0):
    """Piecewise-linear sensitivity path; insert crossed orders BEFORE endpoints.

    This is an explicit synthetic path, not a claim about actual intraminute
    ticks or a universal best/worst bound.
    """
    cursor=x0;cursor_time=t0
    while p.state in ('PENDING','FILLED'):
        if p.state=='PENDING':
            levels=[p.requested-(p.spread if p.buy else 0),p.raw_sl-(0 if p.buy else p.spread)]
            if p.room and p.obstacle>0:levels.append(p.obstacle-(0 if p.buy else p.spread))
        else:
            levels=[p.stop-(0 if p.buy else p.spread)]
            if p.target:levels.append(p.target-(0 if p.buy else p.spread))
        rising=x1>cursor
        crossed=[v for v in levels if (cursor+1e-10<v<=x1+1e-10 if rising else x1-1e-10<=v<cursor-1e-10)]
        level=(min(crossed) if rising else max(crossed)) if crossed else None
        event_time=t1
        if level is not None and abs(x1-x0)>1e-12:
            event_time=t0+int(math.ceil((level-x0)/(x1-x0)*(t1-t0)-1e-9))
        # Include an exact time exit/expiry if it falls before the next crossing.
        if p.deadline and cursor_time<p.deadline<event_time:
            when=p.deadline
            price=x0+(x1-x0)*(when-t0)/(t1-t0)
            p.quote(when,price,price+p.spread,bool(cancel_at and when>=cancel_at))
            cursor_time=when;cursor=price
            continue
        if level is None:
            p.quote(t1,x1,x1+p.spread,bool(cancel_at and t1>=cancel_at));break
        p.quote(event_time,level,level+p.spread,bool(cancel_at and event_time>=cancel_at))
        cursor=level;cursor_time=event_time


def replay_pending_minute(p,bar,path,cancel_at=0):
    at=int(bar[0]);o,h,l,close=map(float,bar[1:5])
    was_pending=p.state=='PENDING'
    if was_pending:
        fill_level=p.requested-(p.spread if p.buy else 0)
        cancel_level=p.raw_sl-(0 if p.buy else p.spread)
        obstacle=p.obstacle-(0 if p.buy else p.spread)
        preview_stop=p.raw_sl
        if p.d*(p.requested-preview_stop)<2.:preview_stop=round_tick(p.requested-p.d*2.,p.tick,-p.d)
        preview_risk=p.d*(p.requested-preview_stop)
        preview_target=round_tick(p.requested+p.d*1.5*preview_risk,p.tick,p.d)-(0 if p.buy else p.spread)
        if l<=fill_level<=h and ((l<=cancel_level<=h) or (p.room and l<=obstacle<=h) or (l<=preview_target<=h)):
            p.ambiguous+=1
    p.quote(at,o,o+p.spread,bool(cancel_at and at>=cancel_at))
    points=[o,h,l,close] if path=='OHLC' else [o,l,h,close]
    offsets=[0,20,40,59]
    for i in range(3):
        if p.state not in ('PENDING','FILLED'):break
        path_segment(p,at+offsets[i],points[i],at+offsets[i+1],points[i+1],cancel_at)


def as_result(p,index,model):
    return dict(candidate_index=int(index),idea_id=idea_key(p.c),signal_time=int(p.c[1]),
                confirm_open=int(p.c[0]),buy=p.buy,zone_time=int(p.c[3]),sweep_time=int(p.c[13]),
                planned_entry=p.requested,entry=p.entry,entry_time=p.entry_time,initial_sl=p.initial_sl,
                stop=p.stop,risk=p.risk,r0_cash_one_lot_assumption=p.risk*100,
                state=p.state,reason=p.reason,exit_time=p.exit_time,exit_price=p.exit_price,
                r=p.r if p.state=='CLOSED' else None,room_r=p.room_r,
                mfe_r=p.mfe,mae_r=p.mae,first_hits=p.first_hits,
                ambiguous_minutes=p.ambiguous,data_gaps=p.gaps,model=model,
                stop_events=[e for e in p.events if e['kind'].startswith('STOP_')],events=p.events,
                commission=0.,swap=0.,fees_status='ZERO_ASSUMPTION_NOT_VERIFIED_BROKER_FEES')


def simulate(index,c,market,m5,h1,atr5,highs,lows,policy,spread,slip,tick=.01,room=False,retest=False,path='OLHC',diagnostic_target=None,record_equity=False):
    p=Plan(c,policy,spread,slip,tick,room,retest)
    samples=[]
    if record_equity:p.observer=lambda at,value:samples.append((at,value))
    left=int(np.searchsorted(market[:,0],c[1],side='left'))
    if left>=len(market):
        p.state='REJECTED';p.reason='NO_ENTRY_QUOTE';return as_result(p,index,'NO_QUOTE')
    first=market[left];p.start(int(first[0]),float(first[1]),float(first[1])+spread)
    if p.state not in ('PENDING','FILLED'):return as_result(p,index,'M1_'+path if retest else 'M1_ADVERSE_FIRST')
    if diagnostic_target is not None:p.target=p.entry+p.d*diagnostic_target*p.risk
    ci=int(np.searchsorted(m5[:,0]+300,int(first[0]),side='right'))
    cancel_at=cancel_context_at(c,h1) if retest else 0
    for i in range(left,len(market)):
        b=market[i];at=int(b[0]);bid=float(b[1])
        if i>left and at-int(market[i-1,0])>60:p.gaps+=1
        if retest:
            replay_pending_minute(p,b,path,cancel_at)
        else:
            p.quote(at,bid,bid+spread)
            if p.state!='FILLED':break
            if policy=='TS':
                while ci<len(m5) and m5[ci,0]+300<=at:
                    propose_structure(p,at,ci,m5,atr5,highs,lows);ci+=1
            p.minute_range(at,float(b[2]),float(b[3]),float(b[4]))
        if p.state not in ('PENDING','FILLED'):break
    if p.state=='FILLED':
        p.state='CENSORED_OPEN';p.reason='END_OF_DATA';p.event('CENSORED_OPEN',int(market[-1,0])+60)
    elif p.state=='PENDING':
        p.state='CENSORED_PENDING';p.reason='END_OF_DATA'
    result=as_result(p,index,'M1_'+path if retest else 'M1_ADVERSE_FIRST')
    if record_equity:result['equity_samples']=samples
    return result


def metrics(trades):
    closed=[r for r in trades if r['state']=='CLOSED']
    values=np.array([r['r'] for r in closed],float)
    wins=values[values>1e-9];losses=values[values<-1e-9]
    cumulative=np.concatenate(([0.],np.cumsum(values)))
    dd=float(np.max(np.maximum.accumulate(cumulative)-cumulative)) if len(values) else 0.
    return dict(n=len(values),wins=len(wins),losses=len(losses),be=int(np.sum(np.abs(values)<=1e-9)),
                win_rate=100*len(wins)/len(values) if len(values) else None,
                total_r=float(values.sum()),expectancy=float(values.mean()) if len(values) else None,
                pf=float(wins.sum()/-losses.sum()) if len(losses) else None,
                mean_win_r=float(wins.mean()) if len(wins) else None,
                median_win_r=float(np.median(wins)) if len(wins) else None,
                realized_ge_1_5r=int(np.sum(values>=1.5-1e-9)),closed_trade_dd_r=dd,
                censored=sum(r['state'].startswith('CENSORED') for r in trades),
                filled=sum(r['entry_time']>0 for r in trades),
                ambiguous_minutes=sum(r['ambiguous_minutes'] for r in trades),
                data_gaps=sum(r['data_gaps'] for r in trades),
                outcomes=dict(Counter(r['state']+':'+r['reason'] for r in trades)))


def replay(selected,arrays,atr5,highs,lows,policy,scenario,room=False,retest=False,path='OLHC',serial=True):
    rows=[];seen=set();busy_until=0;rejects=Counter()
    for index,c in selected:
        key=idea_key(c)
        if key in seen:rejects['DUPLICATE_IDEA']+=1;continue
        if serial and int(c[1])<busy_until:rejects['BUSY']+=1;continue
        seen.add(key)
        row=simulate(index,c,arrays['m1'],arrays['m5'],arrays['h1'],atr5,highs,lows,policy,
                     scenario['spread'],scenario['slippage_ticks']*.01,room=room,retest=retest,path=path)
        rows.append(row)
        if serial:
            if row['state'].startswith('CENSORED'):busy_until=int(arrays['m1'][-1,0])+60
            elif row['exit_time']>0:busy_until=row['exit_time']
    return rows,dict(rejects)


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--phase',choices=['exits','room','retest','all'],default='exits')
    args=parser.parse_args()
    parity=json.loads((RUN/'DETECTOR_PARITY.json').read_text())
    if not parity['passed']:raise RuntimeError('Detector parity must pass first')
    cfg=json.loads((RUN/'EXPERIMENT_LOCK.json').read_text())
    original=np.load(RUN/'rates.npz');arrays={k:bars_matrix(original[k]) for k in original.files}
    numeric=np.load(RUN/'detector_python.npz');raw=numeric['c0_raw'];atr5=numeric['atr5']
    highs,lows=pivots(arrays['m5'])
    specs=[('C0_NATIVE','C0_NATIVE',False,False),('T05','T05',False,False),('T15','T15',False,False),('TS','TS',False,False)]
    if args.phase in ('room','all'):specs += [('T05_RG1','T05',True,False),('T15_RG1','T15',True,False)]
    if args.phase in ('retest','all'):specs += [('BODY50_T15_RG1','T15',True,True)]
    summaries=[]
    for name,policy,room,retest in specs:
        selected,gate_counts=choose_candidates(raw,.01,retest,room)
        for cost in cfg['costs']:
            for path in (['OLHC','OHLC'] if retest else ['ADVERSE_FIRST']):
                for serial in [False,True]:
                    rows,rejects=replay(selected,arrays,atr5,highs,lows,policy,cost,room,retest,path,serial)
                    label=f'{name}_{cost["id"]}_{path}_{"serial" if serial else "paired"}'
                    write_json(RUN/(label+'_trades.json'),rows)
                    summary={'name':name,'cost':cost['id'],'path':path,'mode':'serial' if serial else 'paired_diagnostic',
                             'selected_candidates':len(selected),'raw_gate_counts':dict(gate_counts),
                             'plan_gate_counts':rejects,'metrics':metrics(rows)}
                    if not serial:
                        summary['metrics']['diagnostic_entry_order_dd_r']=summary['metrics'].pop('closed_trade_dd_r')
                    summaries.append(summary);print(json.dumps(summary,ensure_ascii=True),flush=True)
    write_json(RUN/('summary_'+args.phase+'.json'),{'rows':summaries,'data_sha256':sha(RUN/'rates.npz'),
               'detector_parity_sha256':sha(RUN/'DETECTOR_PARITY.json'),'economic_gate':'NOT_YET_AUDITED'})


if __name__=='__main__':
    main()
