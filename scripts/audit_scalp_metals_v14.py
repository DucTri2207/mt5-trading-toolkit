"""Audit raw-silver feature prefixes, common-sample model training and net money."""
import json
import math

import numpy as np

from can_ho_tro_scalp_core import bars_matrix
from prepare_can_ho_tro_scalp import sha,write_json
import research_scalp_metals_v14 as s


def main():
    read=lambda p:json.loads(p.read_text(encoding='utf-8'))
    w=s.w;v=s.v;state=s.state;lock=read(s.RUN/'EXPERIMENT_LOCK.json');source=np.load(w.BASE/'rates.npz')
    gold=bars_matrix(source['m5']);market=bars_matrix(source['m1']);h1=bars_matrix(source['h1'])
    silver=bars_matrix(np.load(s.RUN/'silver_rates.npz')['rates']);labels=np.load(v.RUN/'barrier_labels.npz')
    opp={k:labels[k] for k in ('index','known','unit','lag','basis','atr','close')}
    payoff=labels['payoff'];available=labels['available'];risk=labels['risk'];known=available.max(axis=1)
    common=np.all(np.isfinite(payoff),axis=1);features=np.load(s.RUN/'metal_inputs.npz');xs={k:features[str(k)] for k in s.MODEL_IDS}
    raw=np.load(s.RUN/'raw_candidates.npy');forecast=np.load(s.RUN/'forecasts.npy')
    fx=np.load(w.ROOT/'reports/can_ho_tro_scalp/20261101_intermarket_v9/features.npz')['features']
    prefixes=[];executions=[];w.FAMILIES.update(s.NAMES)
    np.testing.assert_array_equal(np.all(np.isfinite(xs[36]),axis=1),np.all(np.isfinite(xs[37]),axis=1))
    np.testing.assert_array_equal(xs[36],xs[37][:,:24])
    for year in (2022,2025):
        cut=int(w.datetime(year,1,1,tzinfo=w.timezone.utc).timestamp());keep=opp['known']<=cut
        gm=gold[:,0]+300<=cut;hm=h1[:,0]+3600<=cut;sm=silver[:,0]+300<=cut
        po=v.seasonal.opportunities(gold[gm])
        prior,_=state.inputs(po,gold[gm],source['m5']['tick_volume'][gm].astype(float),h1[hm],fx[gm])
        xx,picked,calibrated,_=s.metal_inputs(gold[gm],silver[sm],po,prior[33])
        for k in s.MODEL_IDS:np.testing.assert_array_equal(xx[k],xs[k][keep])
        np.testing.assert_array_equal(picked,features['picked'][keep]);np.testing.assert_array_equal(calibrated,features['calibrated'][gm])
        y=payoff[keep].copy();a=available[keep].copy();y[a>=cut]=np.nan
        model,_,pred=s.model_candidates(po,y,a,xx,end=cut,cache=s.RUN/'models')
        detected=np.concatenate((s.rule_candidates(po,picked,end=cut),model));detected=detected[np.lexsort((detected[:,36],detected[:,1]))]
        np.testing.assert_array_equal(detected,raw[raw[:,37]<cut]);np.testing.assert_array_equal(pred,forecast[keep])
        prefixes.append(dict(cut=cut,raw_silver_gold_h1_fx_features_forecast_detector_exact=True,candidates=len(detected)))
        pm=market[market[:,0]+60<=cut]
        for spec in s.SPECS:
            full=read(s.RUN/(spec['name']+'_BASE_trades.json'))['trades'];rows,_=v.execution.run_serial(detected,pm,spec,w.COSTS[1])
            fields=('state','reason','entry_time','exit_time','entry','initial_sl','risk','r','commission_r','target')
            closed=lambda rr:[{k:r[k] for k in fields} for r in rr if r['state']=='CLOSED' and r['exit_time']<cut]
            assert closed(rows)==closed(full),(year,spec['name'])
            executions.append(dict(name=spec['name'],cut=cut,closed=len(closed(rows)),exact=True))
    records=read(s.RUN/'QUARTERLY_MODELS.json');refits=[]
    for rec in records:
        family=next(k for k,name in s.NAMES.items() if name==rec['name']);x=xs[family];quarter=rec['quarter']
        twin=next(r for r in records if r['quarter']==quarter and r['name']!=rec['name'])
        for key in ('n','days','weeks','last_train_label_known','status'):assert rec[key]==twin[key]
        if rec['status']!='FITTED':continue
        for key in ('y_sha256','signal_sha256','label_available_sha256'):assert rec['identity'][key]==twin['identity'][key]
        train=common&np.all(np.isfinite(x),axis=1)&(opp['known']>=quarter-730*86400)&(known<quarter-7200)
        assert rec['n']==int(train.sum()) and rec['last_train_label_known']<quarter-7200
        for key,a in (('x_sha256',x[train]),('y_sha256',payoff[train]),('signal_sha256',opp['known'][train]),('label_available_sha256',available[train])):
            assert state.digest(a)==rec['identity'][key]
        path=s.RUN/'models'/rec['model_file'];meta=read(path.with_suffix('.json'))
        assert meta['identity']==rec['identity'] and meta['sha256']==sha(path)
        if w.datetime.fromtimestamp(quarter,w.timezone.utc).strftime('%Y-%m')=='2024-01':
            test=np.where(np.all(np.isfinite(x),axis=1)&(opp['known']>=quarter)&(opp['known']<rec['next_quarter']))[0][:64]
            bundle=state.fit_bundle(x[train],payoff[train]);actual=state.predict(bundle,x[test]);slot=s.MODEL_IDS.index(family)
            np.testing.assert_allclose(actual,forecast[test,slot],rtol=0,atol=1e-12)
            refits.append(dict(name=rec['name'],quarter=quarter,rows=len(test),max_difference=float(np.max(np.abs(actual-forecast[test,slot])))))
    fees=0;matched=0;qualified=[];summary=read(s.RUN/'summary.json')
    for spec in s.SPECS:
        base=next(r['metrics'] for r in summary['rows'] if r['name']==spec['name'] and r['cost']=='BASE')
        stress=next(r['metrics'] for r in summary['rows'] if r['name']==spec['name'] and r['cost']=='STRESS')
        if base['frequency_pass'] and base['economic_screen_pass'] and (base['win_rate'] or 0)>=55 and stress['economic_screen_pass']:
            qualified.append(spec['name'])
        for cost in w.COSTS:
            rows=read(s.RUN/(spec['name']+'_'+cost['id']+'_trades.json'))['trades']
            for r in rows:
                fees+=1
                if r['entry_time']:assert math.isclose(r['commission_r'],cost['commission_price']/r['risk'],abs_tol=1e-10)
                if r['r'] is not None:assert math.isclose(r['r'],r['gross_r']-r['commission_r'],abs_tol=1e-10)
                assert 'ASSUMED_ROUND_TRIP_COMMISSION' in r['fees_status']
                if cost['id']=='BASE' and r['state']=='CLOSED':
                    i=np.searchsorted(opp['known'],r['source_known_at']);side=0 if r['buy'] else 1
                    assert payoff[i,side]==r['r'] and risk[i,side]==r['risk'];matched+=1
    preserved={p:sha(w.ROOT/p)==h for p,h in lock['preserved_fresh'].items()};assert all(preserved.values())
    implementation={p:sha(w.ROOT/p)==h for p,h in lock['implementation_sha256'].items()};assert all(implementation.values())
    valid=np.isfinite(features['picked'][:,0]);picked=features['picked'][valid]
    assert np.all(picked[:,9]<=picked[:,0]-900) and np.all(picked[:,8]>=5000)
    write_json(s.RUN/'VERIFICATION.json',dict(passed=True,raw_feature_detector_forecast_prefixes=prefixes,execution_prefixes=executions,
        independent_refits=refits,quarterly_training_digests_and_matched_samples=len(records),fee_rows_audited=fees,
        base_R_risk_label_exact_matches=matched,calibration_cutoff_rows=int(valid.sum()),fresh_unchanged=preserved,
        implementation_unchanged=implementation,qualified=qualified,historical_edge_confirmed=False,FTMO_rules_deferred_per_user=True))
    write_json(s.RUN/'CUMULATIVE_REGISTRY.json',dict(previous=dict(hypotheses=115,scenarios=431),new=dict(hypotheses=4,cost_scenarios=12),
        cumulative=dict(hypotheses=119,scenarios=443),tests=dict(previous_unique=150,new=4,total_unique=154),
        prefixes=dict(raw_feature_detector_forecast=2,execution=8),independent_refits=2,qualified=qualified,goal_status='active;researchongoing'))
    print('PASS',len(prefixes),'rawfeature/forecast/detector+',len(executions),'executionprefixes;',len(refits),'independentrefits;',fees,
        'feerows;',matched,'exactBASElabelmatches;qualified',qualified,flush=True)


if __name__=='__main__':main()
