"""Predeclared entry/regime hypotheses on the parity-checked scalp detector.

Retrospective research only. Reuses the tested quote manager; never sends orders.
"""
from __future__ import annotations

import argparse
import csv
import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

from can_ho_tro_scalp_core import bars_matrix
from can_ho_tro_scalp_plan import Plan, idea_key, planned_gate, round_tick
from prepare_can_ho_tro_scalp import sha, write_json
from replay_can_ho_tro_scalp import as_result, cancel_context_at, metrics, replay_pending_minute

ROOT = Path(__file__).resolve().parents[1]
BASE = ROOT / 'reports/can_ho_tro_scalp/20261025_v1'
RUN = ROOT / 'reports/can_ho_tro_scalp/20261101_v2'
SPECS = [
    dict(name='BASE_T05', target='R05', rule='ALL'),
    dict(name='BASE_T3', target='PRICE3', rule='ALL'),
    dict(name='SLOPE_T05', target='R05', rule='SLOPE'),
    dict(name='SLOPE_T3', target='PRICE3', rule='SLOPE'),
    dict(name='FRESH_T05', target='R05', rule='FRESH'),
    dict(name='FRESH_T3', target='PRICE3', rule='FRESH'),
    dict(name='EARLY_T05', target='R05', rule='EARLY'),
    dict(name='EARLY_T3', target='PRICE3', rule='EARLY'),
    dict(name='NO_CHASE_T05', target='R05', rule='NO_CHASE'),
    dict(name='NO_CHASE_T3', target='PRICE3', rule='NO_CHASE'),
    dict(name='RISK6_T3', target='PRICE3', rule='RISK6'),
    dict(name='RETEST_T05', target='R05', rule='ALL', retest=True),
    dict(name='RETEST_T3', target='PRICE3', rule='ALL', retest=True),
    dict(name='RETEST_SLOPE_T3', target='PRICE3', rule='SLOPE', retest=True),
    dict(name='RETEST_RISK6_T3', target='PRICE3', rule='RISK6', retest=True),
]
COSTS = [
    dict(id='LOW', spread=.20, slip=0., commission_price=.07),
    dict(id='BASE', spread=.30, slip=.01, commission_price=.07),
    dict(id='STRESS', spread=.45, slip=.05, commission_price=.10),
]


def freeze():
    RUN.mkdir(parents=True, exist_ok=True)
    lock = dict(
        version='scalp_research_v2', user_date='2026-11-01',
        period_start='2021-10-25', period_end_exclusive='2026-10-25',
        source_data_sha256=sha(BASE/'rates.npz'), detector_sha256=sha(BASE/'detector_python.npz'),
        hypotheses=SPECS, costs=COSTS,
        rules=dict(SLOPE='direction * (last CLOSED H1 EMA50 - EMA50 6 bars earlier) > 0',
                   FRESH='source test_count <= 1', EARLY='known_at - sweep_open <= 1800 seconds',
                   NO_CHASE='direction * (signal_close - broken pivot) / M5 ATR <= .5',
                   RISK6='both planned and filled initial risk <= 6 price units'),
        pending='body midpoint; expiry 15 minutes; independent OHLC/OLHC sensitivity',
        stops='original structural SL; min distance 2, max 20; single simultaneous position',
        holding_seconds=21600, commission='round trip price equivalent .07/.10; $7/$10 per 100oz lot; assumption, NOT broker verified',
        swap='not modeled; report feed-day crossings; prop suitability unverified',
        screening=dict(pf_min=1.5, stress_expectancy_positive=True, min_trades=200,
                       positive_complete_annual_blocks=True, adjusted_month_bootstrap_lower_positive=True,
                       winrate_goal='report relative to 67.1% prior baseline; no user-approved numeric minimum'),
        selection='walk forward: prior calendar years only; 6h purge; minimum 60 training trades; rank BASE-cost R/month; cash if train expectancy <=0',
        historical_status='ALL five years previously inspected; chronological tests are retrospective, NOT pristine OOS',
        bootstrap_seed=20261101, bootstrap_resamples=20000, family_size=len(SPECS),
        no_broker_orders=True,
    )
    path=RUN/'EXPERIMENT_LOCK.json'
    if path.exists():
        assert json.loads(path.read_text(encoding='utf-8')) == lock, 'Never overwrite changed experiment definitions'
    else:
        write_json(path,lock)
    return lock


def feature(c, h1, ma1):
    # h1 bars are open-labelled; search CLOSED bars only.
    i=int(np.searchsorted(h1[:,0]+3600,c[1],side='right'))-1
    d=1 if c[2] else -1
    return dict(slope_aligned=bool(i>=6 and d*(ma1[i]-ma1[i-6])>0),
                h1_feature_known_at=int(h1[i,0])+3600 if i>=0 else 0,
                test_count=int(c[9]), delay_seconds=int(c[1]-c[13]),
                chase_atr=float(d*(c[21]-c[16])/c[18]))


def accepts(c, f, spec):
    if planned_gate(c,.01,bool(spec.get('retest')),False) != 'PASS':return False
    rule=spec['rule']
    if spec['name']=='DIRECT_FRESH_SLOPE_T05':return f['test_count']<=1 and f['slope_aligned']
    if rule=='SLOPE':return f['slope_aligned']
    if rule=='FRESH':return f['test_count']<=1
    if rule=='EARLY':return f['delay_seconds']<=1800
    if rule=='NO_CHASE':return f['chase_atr']<=.5
    if rule=='RISK6':
        entry=round_tick(c[22],.01,-(1 if c[2] else -1)) if spec.get('retest') else c[21]
        return abs(entry-c[19])<=6.
    return True


class ResearchPlan(Plan):
    def fill(self,at,bid,ask):
        super().fill(at,bid,ask)
        if self.state!='FILLED':return
        if self.spec['rule']=='RISK6' and self.risk>6.+1e-9:
            self.state='REJECTED';self.reason='FILL_RISK6';self.entry_time=0
            return
        if self.spec['target']=='PRICE3':
            self.target=round_tick(self.entry+self.d*3.,self.tick,self.d)


def simulate(index,c,market,h1,spec,cost,path='OLHC',record_equity=False):
    p=ResearchPlan(c,'T05',cost['spread'],cost['slip'],.01,False,bool(spec.get('retest')))
    p.spec=spec
    samples=[]
    fee=0.
    if record_equity:
        p.observer=lambda at,r:samples.append((at,r))
    left=int(np.searchsorted(market[:,0],c[1],side='left'))
    if left==len(market):
        p.state='REJECTED';p.reason='NO_ENTRY_QUOTE'
        return as_result(p,index,'NO_QUOTE')
    first=market[left]
    p.start(int(first[0]),float(first[1]),float(first[1])+p.spread)
    cancel_at=cancel_context_at(c,h1) if p.retest else 0
    for i in range(left,len(market)):
        if p.state not in ('FILLED','PENDING'):break
        b=market[i];at=int(b[0]);o,h,l,close=map(float,b[1:5])
        if i>left and at-int(market[i-1,0])>60:p.gaps+=1
        if p.retest:
            replay_pending_minute(p,b,path,cancel_at)
        else:
            p.quote(at,o,o+p.spread)
            if p.state=='FILLED':p.minute_range(at,h,l,close)
    if p.state in ('FILLED','PENDING'):
        p.state='CENSORED_'+p.state;p.reason='END_OF_DATA'
    result=as_result(p,index,'M1_'+path if p.retest else 'M1_ADVERSE_FIRST')
    # A retest may fill later; charge commission only when actually filled.
    if p.entry_time:
        fee=cost['commission_price']/p.risk
    result['gross_r']=result['r']
    if result['r'] is not None:result['r']-=fee
    result['commission_r']=fee
    result['commission']=cost['commission_price']*100 if p.entry_time else 0.
    result['fees_status']='ASSUMED_ROUND_TRIP_COMMISSION; SWAP_UNMODELED'
    if record_equity:result['equity_samples']=[(at,r-fee) for at,r in samples]
    return result


def run_serial(raw,features,arrays,spec,cost,path='OLHC',record_equity=False,schedule=None):
    out=[];seen=set();busy=0;chosen=-1;rejects=Counter()
    for index,c in enumerate(raw):
        if schedule is not None:
            spec=schedule.get(datetime.fromtimestamp(int(c[1]),timezone.utc).year)
            if spec is None:continue
        if not accepts(c,features[index],spec):continue
        at=int(c[1])
        if at==chosen:rejects['PRIORITY']+=1;continue
        chosen=at
        key=idea_key(c)
        if key in seen:rejects['DUPLICATE']+=1;continue
        if at<busy:rejects['BUSY']+=1;continue
        seen.add(key)
        r=simulate(index,c,arrays['m1'],arrays['h1'],spec,cost,path,record_equity)
        out.append(r)
        if r['state'].startswith('CENSORED'):busy=int(arrays['m1'][-1,0])+60
        elif r['exit_time']:busy=r['exit_time']
    return out,dict(rejects)


def iso(at):return datetime.fromtimestamp(at,timezone.utc).isoformat()


def summarize(rows,lock):
    m=metrics(rows)
    closed=[x for x in rows if x['state']=='CLOSED']
    m['trades_per_month']=m['n']/60
    m['r_per_month']=m['total_r']/60
    m['day_crossings']=sum(x['entry_time']//86400!=x['exit_time']//86400 for x in closed)
    m['mean_holding_minutes']=float(np.mean([(x['exit_time']-x['entry_time'])/60 for x in closed])) if closed else None
    m['by_year']={str(y):metrics([x for x in closed if iso(x['entry_time'])[:4]==str(y)]) for y in range(2021,2027)}
    start=datetime(2021,10,1,tzinfo=timezone.utc)
    months=[f'{y:04d}-{mo:02d}' for y in range(2021,2027) for mo in range(1,13) if '2021-10'<=f'{y:04d}-{mo:02d}'<='2026-10']
    amounts=np.zeros(len(months));counts=np.zeros(len(months))
    for x in closed:
        j=months.index(iso(x['exit_time'])[:7]);amounts[j]+=x['r'];counts[j]+=1
    rng=np.random.default_rng(lock['bootstrap_seed'])
    draws=rng.integers(len(months),size=(lock['bootstrap_resamples'],len(months)))
    br=amounts[draws].sum(axis=1);bn=counts[draws].sum(axis=1)
    ex=br[bn>0]/bn[bn>0]
    m['expectancy_month_bootstrap_95']=np.quantile(ex,[.025,.975]).tolist() if len(ex) else None
    m['expectancy_month_bootstrap_lower_family95']=float(np.quantile(ex,.05/lock['family_size'])) if len(ex) else None
    m['bootstrap_note']='calendar-month resampling incl zero months; Bonferroni covers only this NEW family; earlier searches remain unadjusted'
    m['monthly']=[dict(month=s,r=float(r),n=int(n)) for s,r,n in zip(months,amounts,counts)]
    if m['n']:
        z=1.959963984540054;p=m['wins']/m['n'];n=m['n'];den=1+z*z/n
        delta=z*np.sqrt(p*(1-p)/n+z*z/(4*n*n))
        m['winrate_wilson95']=[100*(p+z*z/(2*n)-delta)/den,100*(p+z*z/(2*n)+delta)/den]
    else:m['winrate_wilson95']=None
    m['pf_screen_pass']=bool(m['n']>=200 and (m['pf'] or 0)>=1.5 and (m['expectancy'] or 0)>0
                             and (m['expectancy_month_bootstrap_lower_family95'] or 0)>0
                             and all(m['by_year'][str(y)]['total_r']>0 for y in range(2022,2026)))
    return m


def walkforward(trades_by_spec):
    rows=[];choices=[]
    for y in range(2023,2027):
        boundary=int(datetime(y,1,1,tzinfo=timezone.utc).timestamp())
        end=int(datetime(y+1,1,1,tzinfo=timezone.utc).timestamp())
        candidates=[]
        for name,trades in trades_by_spec.items():
            train=[t for t in trades if t['state']=='CLOSED' and t['exit_time']<boundary-21600]
            m=metrics(train)
            if m['n']>=60 and m['total_r']>0:candidates.append((m['total_r'],name,m))
        if not candidates:
            choices.append(dict(year=y,selected='CASH',train_n=0));continue
        _,name,train=max(candidates,key=lambda x:(x[0],x[1]))
        test=[t for t in trades_by_spec[name] if boundary<=t['signal_time']<end]
        rows.extend(test)
        choices.append(dict(year=y,selected=name,train_n=train['n'],train_r=train['total_r'],test=metrics(test)))
    return dict(choices=choices,metrics=metrics(rows),label='retrospective chronological selection; previously inspected history')


def evaluate_walkforward(training_feed,raw,features,arrays,specs,cost,path='OLHC'):
    selection=walkforward(training_feed)
    lookup={s['name']:s for s in specs}
    schedule={x['year']:lookup.get(x['selected']) for x in selection['choices']}
    # Execute the selected schedule chronologically; unselected past positions
    # must not suppress a test-period signal, and selected positions carry across years.
    trades,_=run_serial(raw,features,arrays,None,cost,path,schedule=schedule)
    for choice in selection['choices']:
        choice['test']=metrics([t for t in trades if datetime.fromtimestamp(t['signal_time'],timezone.utc).year==choice['year']])
    return dict(choices=selection['choices'],metrics=metrics(trades),
                label='prior-year selection, 6h training purge, continuous serial execution; retrospective NOT pristine OOS')


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--freeze-only',action='store_true');args=parser.parse_args()
    lock=freeze()
    if args.freeze_only:return
    assert json.loads((BASE/'DETECTOR_PARITY.json').read_text())['passed']
    source=np.load(BASE/'rates.npz');arrays={k:bars_matrix(source[k]) for k in source.files}
    numerical=np.load(BASE/'detector_python.npz');raw=numerical['c0_raw'];ma1=numerical['ma1']
    features=[feature(c,arrays['h1'],ma1) for c in raw]
    assert all(f['h1_feature_known_at']<=int(c[1]) for c,f in zip(raw,features))
    write_json(RUN/'candidate_features.json',features)
    # Audit legacy parity before evaluating new hypotheses, with zero fees.
    check,_=run_serial(raw,features,arrays,SPECS[0],dict(spread=.2,slip=0.,commission_price=0.))
    old=json.loads((BASE/'T05_C_A_ADVERSE_FIRST_serial_trades.json').read_text())
    keys=['candidate_index','state','entry_time','exit_time','entry','initial_sl','r']
    assert len(check)==len(old)
    for a,b in zip(check,old):
        assert all(a[k]==b[k] or (isinstance(a[k],float) and abs(a[k]-b[k])<1e-9) for k in keys),(a,b)
    write_json(RUN/'BASELINE_PARITY.json',dict(passed=True,rows=len(check),fields=keys))
    print('BASELINE_PARITY',len(check),'PASS',flush=True)
    summaries=[];all_trades={}
    for spec in SPECS:
        for cost in COSTS:
            for path in (['OLHC','OHLC'] if spec.get('retest') else ['ADVERSE_FIRST']):
                label=spec['name']+'_'+cost['id']+'_'+path
                trades,rejects=run_serial(raw,features,arrays,spec,cost,path)
                write_json(RUN/(label+'_trades.json'),trades)
                m=summarize(trades,lock)
                summaries.append(dict(name=spec['name'],cost=cost['id'],path=path,label=label,metrics=m,rejections=rejects))
                all_trades[label]=trades
                print(label,'n',m['n'],'win',round(m['win_rate'] or 0,2),'PF',round(m['pf'] or 0,3),'R',round(m['total_r'],2),flush=True)
    wf={}
    for cost in COSTS:
        for path in ['OLHC','OHLC']:
            feed={s['name']:all_trades[s['name']+'_'+cost['id']+'_'+(path if s.get('retest') else 'ADVERSE_FIRST')] for s in SPECS}
            # Select on BASE cost only, then evaluate the SAME choices at other costs.
            base_feed={s['name']:all_trades[s['name']+'_BASE_'+(path if s.get('retest') else 'ADVERSE_FIRST')] for s in SPECS}
            wf[cost['id']+'_'+path]=evaluate_walkforward(base_feed,raw,features,arrays,SPECS,cost,path)
    write_json(RUN/'summary.json',dict(rows=summaries,walkforward=wf,lock_sha256=sha(RUN/'EXPERIMENT_LOCK.json')))
    print('DONE',len(summaries),'scenario rows',flush=True)


if __name__=='__main__':main()
