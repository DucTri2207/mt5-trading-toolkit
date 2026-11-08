"""Auditable diagnostics/parity for the locked lab. Never sends orders."""
from __future__ import annotations
import argparse
import csv
import hashlib
import json
import shutil
from collections import Counter
from datetime import datetime,timezone
from pathlib import Path

import numpy as np
import replay_scalp_structure_lab as lab

RUN=lab.RUN
COMMON=Path.home()/'AppData/Roaming/MetaQuotes/Terminal/Common/Files/scalp_structure_lab_v1'

def read(name):return json.loads((RUN/name).read_text(encoding='utf-8'))
def load_csv(path,cols):
    if not path.stat().st_size:return np.empty((0,cols))
    return np.loadtxt(path,delimiter=',',ndmin=2)

def parity():
    target=RUN/'mql';target.mkdir(exist_ok=True)
    for path in COMMON.glob('*mql*'):
        if path.is_file():shutil.copy2(path,target/path.name)
    result=json.loads((target/'mql_result.json').read_text())
    checks=[]
    def compare(label,a,b,exact):
        shape=a.shape==b.shape
        equal=shape and all(np.array_equal(a[:,i],b[:,i]) for i in exact)
        error=float(np.max(np.abs(a-b))) if shape and a.size else 0.0
        checks.append(dict(label=label,rows=len(a),shape_match=shape,
                           exact_fields_match=equal,max_absolute_error=error,
                           passed=bool(equal and error<1e-7)))
    compare('candidates',load_csv(RUN/'candidates_python.csv',7),load_csv(target/'candidates_mql.csv',7),[0,1,2])
    compare('trail proposals',load_csv(RUN/'trails_python.csv',4),load_csv(target/'trails_mql.csv',4),[0,1,2])
    status={'STOP':1,'TARGET':2,'TIME':3,'STOP_GAP':4}
    for spread in (.2,.5,1.0):
        for policy in ('E0_FIXED_1_5R','E1_STRUCTURE_TRAIL'):
            trades=read(f'trades_{policy}_{spread}.json')
            rows=[];events=[]
            for r in trades:
                rows.append([r['signal_time'],int(r['buy']),r['entry_time'],r['entry'],r['initial_stop'],r['risk'],r['exit_time'],r['exit_price'],status[r['status']],r['r'],r['stop'],r['room_r']])
                for e in r['stop_events']:
                    events.append([r['signal_time'],e['time'],e['old'],e['new'],e['known'],e['anchor_time']])
            compare(f'{policy}/{spread}/trades',np.array(rows).reshape(-1,12),load_csv(target/f'trades_mql_{policy}_{spread}.csv',12),[0,1,2,6,8])
            compare(f'{policy}/{spread}/stop events',np.array(events).reshape(-1,6),load_csv(target/f'events_mql_{policy}_{spread}.csv',6),[0,1,4,5])
    out={'spec_version':'p2_structure_0.1','mql_runtime_fixtures':result,
         'checks':checks,'passed':result['failures']==0 and all(x['passed'] for x in checks)}
    lab.write_json(RUN/'dynamic_parity.json',out)
    print('PARITY',json.dumps(out),flush=True)
    if not out['passed']:raise RuntimeError('Dynamic parity failed')

def diagnostics():
    data=np.load(RUN/'rates.npz');m1=data['m1'];times=m1['time'].astype(np.int64)
    candidates=read('candidates.json');updates=read('trailing_proposals.json')
    ut=np.array([x['time'] for x in updates]);lookup={s['id']:s for s in candidates}
    reports=[]
    for row in read('backtest_summary.json')['rows']:
        policy=row['policy'];spread=row['spread']
        trades=read(f'trades_{policy}_{spread}.json')
        year=[]
        for y in (2023,2024,2025,2026):
            left=lab.stamp(f'{y}-01-01T00:00:00+00:00')+21600
            right=min(lab.stamp(f'{y+1}-01-01T00:00:00+00:00'),lab.stamp('2026-10-25T00:00:00+00:00'))
            year.append({'test_year':y,'training_end_exclusive':f'{y}-01-01',
                         'purge_hours':6,'parameter_fitting':'none; fixed spec retrospective',
                         'metrics':lab.metrics([x for x in trades if x['entry_time']>=left and x['exit_time']<right])})
        months=[str(x) for x in np.arange(np.datetime64('2021-11'),np.datetime64('2026-10'),np.timedelta64(1,'M'))]
        def month(r):return datetime.fromtimestamp(r['entry_time'],timezone.utc).strftime('%Y-%m')
        rolling=[]
        for i in range(len(months)-11):
            subset=[x for x in trades if months[i]<=month(x)<=months[i+11]]
            m=lab.metrics(subset);m.update(start=months[i],end=months[i+11],trades_per_month=len(subset)/12)
            rolling.append(m)
        gaps=[];trail_count=0
        for r in trades:
            l=int(np.searchsorted(times,r['entry_time']));q=int(np.searchsorted(times,r['exit_time'],side='right'))
            if np.any(np.diff(times[l:q])>60):gaps.append(r['id'])
            trail_count+=len(r['stop_events'])
        reports.append({'policy':policy,'spread':spread,'chronological_purged_blocks':year,
                        'rolling_12_months':rolling,'worst_rolling_r':min(rolling,key=lambda x:x['r']),
                        'minimum_rolling_frequency':min(rolling,key=lambda x:x['n']),
                        'trades_with_observed_minute_gaps':len(gaps),
                        'minute_gap_trade_ids':gaps,'applied_trailing_events':trail_count,
                        'extra_cost_diagnostic_0_05R_each_trade':lab.metrics([{'r':r['r']-.05} for r in trades])})
    e0=read('trades_E0_FIXED_1_5R_0.2.json')
    paired=[]
    for r in e0:
        other=lab.simulate_trade(lookup[r['id']],m1,times,updates,ut,.2,.01,'E1_STRUCTURE_TRAIL')
        if 'r' in other:paired.append({'id':r['id'],'e0':r['r'],'e1':other['r'],'delta':other['r']-r['r']})
    out={'rows':reports,'paired_e0_entry_cohort':{'n':len(paired),
        'e0':lab.metrics([{'r':r['e0']} for r in paired]),
        'e1':lab.metrics([{'r':r['e1']} for r in paired]),
        'sum_delta_r':sum(r['delta'] for r in paired),
        'scope':'Same E0 entries; E1 exits independently. This diagnostic allows overlapping E1 holds and is not a deployable portfolio.'},
        'not_claimed':['pristine out of sample','parameter optimization walk forward','fund pass probability']}
    lab.write_json(RUN/'stability_diagnostics.json',out)
    print('DIAGNOSTICS',json.dumps(out['paired_e0_entry_cohort']),flush=True)

def baseline():
    import backtest_causal_scalp as old
    from evaluate_gold_scalp_m1_stability import fast_m1_trade
    from evaluate_causal_serial_walkforward import serial_pairs
    from evaluate_adaptive_h1_distance import annotate
    data=np.load(RUN/'rates.npz');m1=data['m1'];times=m1['time'].astype(np.int64)
    start=lab.stamp('2021-10-23T00:00:00+00:00')
    print('BASELINE audit starting original detector',flush=True)
    h1=data['h1'];h1=h1[h1['time']>=start]
    m5=data['m5'];m5=m5[m5['time']>=start]
    pool,zones=old.detect_candidate_pool(h1,m5)
    hours={8,9,10,11,13,15,16,17}
    selected=[s for s,d in annotate(h1,pool) if d<=1.75 and s['wick']>=.5 and s['body_atr']>=.25 and datetime.fromtimestamp(s['time'],timezone.utc).hour in hours]
    cfg=old.Config('baseline_audit',True,'proximal',.5,.25,True,.5,None,max_risk=20,cost=.2)
    hi=m5['high'];lo=m5['low'];cl=m5['close']
    m5_results=[old.simulate(s,hi,lo,cl,cfg) for s in selected]
    picked=serial_pairs(selected,m5_results)
    legacy=[fast_m1_trade(s,hi,lo,cfg,m1,times) for s,_ in picked]
    # Isolate skipped-entry-minute effect without changing any other legacy rule.
    import inspect
    source=inspect.getsource(fast_m1_trade).replace('for bar in bars[1:]:','for bar in bars:').replace('def fast_m1_trade(','def fixed_entry_minute(')
    namespace=dict(fast_m1_trade.__globals__);exec(compile(source,'<entry-minute-audit>','exec'),namespace)
    fixed=[namespace['fixed_entry_minute'](s,hi,lo,cfg,m1,times) for s,_ in picked]
    changed=[{'time':s['time'],'legacy':a,'first_minute_included':b} for (s,_),a,b in zip(picked,legacy,fixed) if a!=b]
    signals=[];rejected=Counter()
    for s in selected:
        when=s['time']+300;i=int(np.searchsorted(times,when))
        if i>=len(times) or int(times[i])-when>60:rejected['NO_QUOTE']+=1;continue
        d=1 if s['buy'] else -1;entry=float(m1[i]['open'])+(.2 if s['buy'] else 0)
        left=max(0,s['idx']-max(4,s['idx']-s['sweep_idx']))
        raw=(float(np.min(lo[left:s['idx']+1]))-.25*s['atr'] if s['buy'] else float(np.max(hi[left:s['idx']+1]))+.25*s['atr'])
        risk=d*(entry-raw)
        if risk>20:rejected['MAX_RISK']+=1;continue
        if risk<2:raw=entry-d*2
        signals.append({'id':f"BASE:{s['idx']}",'time':when,'buy':s['buy'],
                        'anchor_time':s['time'],'anchor':raw,'atr':0,
                        'initial_stop':raw,'trigger':s['entry'],'opposing':0})
    comparisons=[];base_cohort=[]
    for target in (.5,1.0,1.5,2.0):
        summary,trades=lab.serial_replay(signals,m1,[],.2,.01,'E0_FIXED_1_5R',True,target)
        comparisons.append({'target_r':target,'summary':summary})
        if target==.5:base_cohort=trades
    lookup={s['id']:s for s in signals};passage=[]
    for r in base_cohort:
        longer=lab.simulate_trade(lookup[r['id']],m1,times,[],np.array([]),.2,.01,'E0_FIXED_1_5R',True,2.0)
        passage.append(longer)
    out={'zones':zones,'raw_selected':len(selected),'legacy_cohort_n':len(picked),
         'legacy_same_cohort':lab.metrics([r for r in legacy if r['status']!='NO_M1']),
         'only_first_minute_fixed_same_cohort':lab.metrics([r for r in fixed if r['status']!='NO_M1']),
         'first_minute_changed_trades':changed,'corrected_execution_serial':comparisons,
         'initial_signal_rejects':dict(rejected),'first_passage_same_0_5R_entry_cohort':{
             'n':len(passage),'unresolved_extended':sum(r['status']=='UNRESOLVED' for r in passage),'hit_before_stop_or_timeout_conservative':{
                 str(x):sum(str(x) in r['first_hits'] for r in passage) for x in (1.0,1.5,2.0)}},
         'limits':['Legacy cohort uses original M5 selection to isolate entry-minute bug.',
                   'Corrected serial uses actual M1 exit, Bid/Ask, directional tick rounding and adverse gap fills; several execution differences are combined.',
                   'Baseline preserves legacy minimum-risk stop clamp for comparison only; the P2 model does not use that clamp.',
                   'First-passage figures are diagnostic; same-bar uncertainty is adverse-first.']}
    lab.write_json(RUN/'baseline_audit.json',out)
    print('BASELINE',json.dumps({k:out[k] for k in ['raw_selected','legacy_cohort_n','legacy_same_cohort','only_first_minute_fixed_same_cohort','first_passage_same_0_5R_entry_cohort']}),flush=True)

def main():
    p=argparse.ArgumentParser();p.add_argument('command',choices=['parity','diagnostics','baseline']);a=p.parse_args()
    {'parity':parity,'diagnostics':diagnostics,'baseline':baseline}[a.command]()
if __name__=='__main__':main()
