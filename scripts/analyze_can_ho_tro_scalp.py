"""Causal-prefix checks, correction attribution and fixed-spec historical diagnostics."""
from __future__ import annotations

import argparse
import json
import math
from collections import Counter
from datetime import datetime, timezone

import numpy as np

from prepare_can_ho_tro_scalp import RUN, write_json, sha
from can_ho_tro_scalp_core import bars_matrix, metaquotes_atr, ema50, detect_all
from can_ho_tro_scalp_plan import pivots
from replay_can_ho_tro_scalp import simulate, replay, choose_candidates, metrics


def month(t):return datetime.fromtimestamp(int(t),timezone.utc).strftime('%Y-%m')


def month_labels():
    return [f'{year}-{m:02d}' for year in range(2021,2027) for m in range(1,13)
            if '2021-10'<=f'{year}-{m:02d}'<='2026-10']


def wilson(wins,n):
    if not n:return None
    z=1.959963984540054;p=wins/n;den=1+z*z/n
    center=(p+z*z/(2*n))/den;half=z*math.sqrt(p*(1-p)/n+z*z/(4*n*n))/den
    return [100*(center-half),100*(center+half)]


def prefix_checks(arrays,numerical,cfg):
    cutoffs=['2022-01-03T12:00:00+00:00','2023-06-01T12:35:00+00:00',
             '2024-12-31T14:00:00+00:00','2026-10-16T12:35:00+00:00']
    checks=[];start=int(datetime.fromisoformat(cfg['period_start']).timestamp())
    for text in cutoffs:
        at=int(datetime.fromisoformat(text).timestamp())
        # iBarShift needs the current H1 opening timestamp. Its unfinished OHLC
        # is replaced by its open, and must never enter a gate or zone.
        h=arrays['h1'][arrays['h1'][:,0]<=at].copy()
        unfinished=h[:,0]+3600>at
        h[unfinished,2:5]=h[unfinished,1,None]
        m=arrays['m5'][arrays['m5'][:,0]+300<=at]
        d=arrays['d1'][arrays['d1'][:,0]+86400<=at]
        raw,snap=detect_all(h,m,d,metaquotes_atr(h),metaquotes_atr(m),ema50(h),start,at,True)
        expected=numerical['c0_raw'];expected=expected[expected[:,1]<at]
        expected_snap=numerical['snapshots'];expected_snap=expected_snap[expected_snap[:,0]<at]
        snap=snap[snap[:,0]<at]
        same=raw.shape==expected.shape and np.array_equal(raw,expected)
        same_snapshot=snap.shape==expected_snap.shape and np.array_equal(snap,expected_snap)
        checks.append({'cutoff':text,'candidate_rows':len(raw),'candidate_exact':same,'snapshot_exact':same_snapshot,
                       'passed':bool(same and same_snapshot)})
        print('PREFIX',text,checks[-1]['passed'],flush=True)
    result={'checks':checks,'passed':all(c['passed'] for c in checks),'rule':'known_at strictly before cutoff; closed bars only'}
    write_json(RUN/'PREFIX_PARITY.json',result)
    if not result['passed']:raise RuntimeError('Causal prefix mismatch')


def data_audit(data):
    results=[]
    m1=data['m1'];times=m1['time'].astype(np.int64)
    for name,seconds in [('m5',300),('h1',3600)]:
        bucket=times//seconds*seconds
        unique,first,count=np.unique(bucket,return_index=True,return_counts=True)
        op=m1['open'][first];hi=np.maximum.reduceat(m1['high'],first);lo=np.minimum.reduceat(m1['low'],first)
        close=m1['close'][first+count-1]
        original=data[name];idx=np.searchsorted(unique,original['time'])
        present=idx<len(unique);present[present]=unique[idx[present]]==original['time'][present]
        selected=idx[present];errors=[]
        for field,agg in [('open',op),('high',hi),('low',lo),('close',close)]:
            errors.append(np.abs(original[field][present]-agg[selected]))
        maximum=float(np.max(np.array(errors))) if len(selected) else None
        mismatch=int(np.sum(np.any(np.array(errors)>1e-8,axis=0)))
        results.append({'timeframe':name,'matched_buckets':int(present.sum()),'missing_buckets':int((~present).sum()),
                        'ohlc_mismatch_buckets':mismatch,'max_price_error':maximum,
                        'buckets_with_fewer_than_scheduled_minutes':int(np.sum(count<seconds//60)),
                        'interpretation':'No-price-update minutes and missing history cannot be distinguished solely from these rates'})
    write_json(RUN/'DATA_AUDIT.json',{'results':results,'passed_ohlc':all(r['ohlc_mismatch_buckets']==0 and r['missing_buckets']==0 for r in results)})


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--prefix-only',action='store_true');args=parser.parse_args()
    cfg=json.loads((RUN/'EXPERIMENT_LOCK.json').read_text());data=np.load(RUN/'rates.npz')
    arrays={k:bars_matrix(data[k]) for k in data.files};numerical=np.load(RUN/'detector_python.npz')
    prefix_checks(arrays,numerical,cfg)
    if args.prefix_only:return
    data_audit(data)
    high,low=pivots(arrays['m5']);atr=numerical['atr5'];raw=numerical['c0_raw']
    corrections=[]
    for label,feed,known_gate in [('L0_FIRST_QUOTE_DETECTOR_WITH_C0_EXEC',numerical['raw'],False),
                                  ('C0_CLOSED_ONLY_WITHOUT_KNOWN_LEVEL_GATE',raw,False),
                                  ('C0_CLOSED_ONLY_KNOWN_LEVEL_GATE',raw,True)]:
        feed=feed.copy()
        if not known_gate:feed[:,28]=0
        selected,gates=choose_candidates(feed,.01)
        trades,rejects=replay(selected,arrays,atr,high,low,'T05',cfg['costs'][0])
        corrections.append({'name':label,'selected':len(selected),'gate_counts':dict(gates),'plan_rejects':rejects,'metrics':metrics(trades)})
    write_json(RUN/'CORRECTION_ATTRIBUTION.json',{'rows':corrections,
               'scope':'Detector corrections held against the SAME C0 execution/6h policy, NOT literal original-indicator P&L',
               'original_intrabar_manager':'Original two-owner/Bid-only close path is retired and fixture-tested; no invented old broker fills'})
    summaries=json.loads((RUN/'summary_all.json').read_text())['rows']
    labels=month_labels();lookup={name:i for i,name in enumerate(labels)}
    results=[];monthly={};equity_curves={}
    for row in summaries:
        if row['mode']!='serial':continue
        name,cost,path=row['name'],row['cost'],row['path'];label=f'{name}_{cost}_{path}_serial'
        trades=json.loads((RUN/(label+'_trades.json')).read_text())
        amounts=np.zeros(len(labels));counts=np.zeros(len(labels));entries=np.zeros(len(labels))
        closed=[t for t in trades if t['state']=='CLOSED']
        for trade in trades:
            if trade['entry_time']>0:entries[lookup[month(trade['entry_time'])]]+=1
            if trade['state']=='CLOSED':
                j=lookup[month(trade['exit_time'])];amounts[j]+=trade['r'];counts[j]+=1
        monthly[label]=(amounts,counts)
        years=[]
        for year in range(2021,2027):
            bucket=[t for t in trades if t['entry_time'] and datetime.fromtimestamp(t['entry_time'],timezone.utc).year==year]
            years.append({'year':year,'partial_year':year in (2021,2026),'metrics':metrics(bucket)})
        # Recreate the declared M1 scenario, now with mark-to-market observations.
        policy='C0_NATIVE' if name=='C0_NATIVE' else ('TS' if name=='TS' else ('T05' if name.startswith('T05') else 'T15'))
        room='RG1' in name;retest=name.startswith('BODY50');scenario=next(c for c in cfg['costs'] if c['id']==cost)
        carry=0.;peak=0.;eq_dd=0.;samples=[]
        for trade in trades:
            if not trade['entry_time']:continue
            check=simulate(trade['candidate_index'],raw[trade['candidate_index']],arrays['m1'],arrays['m5'],arrays['h1'],atr,
                           high,low,policy,scenario['spread'],scenario['slippage_ticks']*.01,
                           room=room,retest=retest,path=path,record_equity=True)
            assert check['state']==trade['state'] and check['exit_time']==trade['exit_time']
            assert check['r'] is None or abs(check['r']-trade['r'])<1e-9
            for at,value in check['equity_samples']:
                equity=carry+value;peak=max(peak,equity);eq_dd=max(eq_dd,peak-equity);samples.append([at,equity])
            if trade['r'] is not None:carry+=trade['r']
        equity_curves[label]=samples
        m=row['metrics'];total_n=m['n'];win_ci=wilson(m['wins'],total_n)
        holdings=[t['exit_time']-t['entry_time'] for t in closed]
        giveback=[max(0.,t['mfe_r']-t['r']) for t in closed]
        enriched={'label':label,'name':name,'cost':cost,'path':path,'metrics':m,
                  'winrate_wilson_95':win_ci,'filled_trades_per_elapsed_month':m['filled']/60,
                  'total_elapsed_months':60,'calendar_bins_including_partial_months':len(labels),
                  'zero_entry_months':int(np.sum(entries==0)),
                  'r_per_elapsed_month':m['total_r']/60,
                  'monthly':[{'month':key,'filled':int(entries[i]),'closed':int(counts[i]),'realized_r':float(amounts[i])} for i,key in enumerate(labels)],
                  'by_entry_year':years,'mean_holding_minutes':float(np.mean(holdings)/60) if holdings else None,
                  'mean_giveback_r':float(np.mean(giveback)) if giveback else None,
                  'equity_dd_model_r':eq_dd,
                  'equity_definition':'M1 synthetic adverse-first execution / declared retest path; 1 initial-risk unit per idea, not account-percent DD',
                  'screening_pf_1_5_pass':m['pf'] is not None and m['pf']>=1.5 and (m['expectancy'] or 0)>0}
        results.append(enriched);print('ANALYZED',label,'equity DD',round(eq_dd,3),flush=True)
    comparisons=[];rng=np.random.default_rng(cfg['bootstrap_seed']);draws=rng.integers(0,len(labels),size=(cfg['bootstrap_resamples'],len(labels)))
    for cost in ['C_A','C_B','C_C']:
        base=f'T05_{cost}_ADVERSE_FIRST_serial';base_r,base_n=monthly[base]
        for name in ['T15','TS','T05_RG1','T15_RG1']:
            candidate=f'{name}_{cost}_ADVERSE_FIRST_serial';r,n=monthly[candidate]
            delta=(r[draws].sum(axis=1)-base_r[draws].sum(axis=1))/len(labels)
            nr=n[draws].sum(axis=1);nb=base_n[draws].sum(axis=1);valid=(nr>0)&(nb>0)
            de=r[draws].sum(axis=1)[valid]/nr[valid]-base_r[draws].sum(axis=1)[valid]/nb[valid]
            comparisons.append({'candidate':candidate,'baseline':base,
                'delta_r_per_calendar_month_ci95':np.quantile(delta,[.025,.975]).tolist(),
                'delta_expectancy_ci95':np.quantile(de,[.025,.975]).tolist(),
                'resampling':'same calendar-month blocks for both policies; includes months0; retrospective small-sample limitations'})
    paired=json.loads((RUN/'T05_C_A_ADVERSE_FIRST_paired_trades.json').read_text());passage=[]
    for trade in paired:
        if not trade['entry_time']:continue
        passage.append(simulate(trade['candidate_index'],raw[trade['candidate_index']],arrays['m1'],arrays['m5'],arrays['h1'],atr,
                                high,low,'T05',.2,0,diagnostic_target=2.))
    first={'n':len(passage),'hits_before_initial_stop_or_6h':{t:sum(t in x['first_hits'] for x in passage) for t in ['1.0','1.5','2.0']},
           'not_realized_pnl':True,'cohort':'All unique C0 valid paired entries under C_A; overlaps allowed'}
    # Explicit paired cohort equality across the three exits.
    paired_checks=[]
    for cost in ['C_A','C_B','C_C']:
        cohorts=[]
        for name in ['T05','T15','TS']:
            records=json.loads((RUN/f'{name}_{cost}_ADVERSE_FIRST_paired_trades.json').read_text())
            cohorts.append([(x['candidate_index'],x['entry_time'],x['entry'],x['initial_sl']) for x in records if x['entry_time']])
        paired_checks.append({'cost':cost,'same_entry_stop_cohort':cohorts[0]==cohorts[1]==cohorts[2],'n':len(cohorts[0])})
    assert all(c['same_entry_stop_cohort'] for c in paired_checks)
    write_json(RUN/'STABILITY_DIAGNOSTICS.json',{'rows':results,'bootstrap':comparisons,'first_passage':first,
               'paired_cohort_checks':paired_checks,'historical_label':cfg['historical_label'],
               'fees_status':cfg['fee_status'],'no_tick_coverage_claim':True})
    np.savez_compressed(RUN/'equity_curves.npz',**{key:np.array(value).reshape(-1,2) for key,value in equity_curves.items()})
    print('DIAGNOSTICS_DONE',len(results),flush=True)


if __name__=='__main__':main()
