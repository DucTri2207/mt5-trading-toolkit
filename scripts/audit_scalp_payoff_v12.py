"""Past-label cutoffs, prefix forecasts, exact label/execution identity and fee checks."""
import json
import math

import numpy as np

from can_ho_tro_scalp_core import bars_matrix
from prepare_can_ho_tro_scalp import sha, write_json
import research_scalp_payoff_v12 as v


def main():
    read=lambda p:json.loads(p.read_text(encoding='utf-8'))
    lock=read(v.RUN/'EXPERIMENT_LOCK.json');saved=np.load(v.RUN/'barrier_labels.npz')
    keys=('index','known','unit','lag','basis','atr','close');opp={k:saved[k] for k in keys}
    payoff=saved['payoff'];available=saved['available'];risk=saved['risk']
    raw=np.load(v.RUN/'raw_candidates.npy');forecast=np.load(v.RUN/'forecasts.npy')
    data=np.load(v.w.BASE/'rates.npz');market=bars_matrix(data['m1']);gold=bars_matrix(data['m5'])
    checks=[];executions=[];v.w.FAMILIES.update(v.NAMES)
    for year in (2022,2025):
        cut=int(v.w.datetime(year,1,1,tzinfo=v.w.timezone.utc).timestamp())
        keep=opp['known']<=cut;pg=gold[gold[:,0]+300<=cut]
        po=v.seasonal.opportunities(pg)
        for key in keys:np.testing.assert_array_equal(po[key],opp[key][keep])
        target=payoff[keep].copy();known=available[keep].copy();target[known>=cut]=np.nan
        detected,_,pred=v.candidates(po,target,known,end=cut)
        expected=raw[raw[:,37]<cut];np.testing.assert_array_equal(detected,expected)
        np.testing.assert_array_equal(pred,forecast[keep])
        checks.append(dict(cut=cut,candidates=len(detected),features_forecasts_candidates_exact=True))
        pm=market[market[:,0]+60<=cut]
        for spec in v.SPECS:
            full=read(v.RUN/(spec['name']+'_BASE_trades.json'))['trades']
            rows,_=v.execution.run_serial(detected,pm,spec,v.w.COSTS[1])
            fields=('state','reason','entry_time','exit_time','entry','initial_sl','risk','r','commission_r','target')
            closed=lambda rr:[{k:r[k] for k in fields} for r in rr if r['state']=='CLOSED' and r['exit_time']<cut]
            assert closed(rows)==closed(full),(spec['name'],year)
            executions.append(dict(name=spec['name'],cut=cut,closed=len(closed(rows)),exact=True))
    models=read(v.RUN/'MONTHLY_MODELS.json')
    for m in models:
        if m['status']=='FITTED':
            assert m['last_train_label_known']<m['month']-7200
            assert m['first_train_signal']>=m['month']-365*86400
            assert all(s['win']['converged'] for s in m['sides'])
    qualified=[];summary=read(v.RUN/'summary.json');fee_rows=0;label_matches=0
    for spec in v.SPECS:
        base=next(r['metrics'] for r in summary['rows'] if r['name']==spec['name'] and r['cost']=='BASE')
        stress=next(r['metrics'] for r in summary['rows'] if r['name']==spec['name'] and r['cost']=='STRESS')
        if base['frequency_pass'] and base['economic_screen_pass'] and (base['win_rate'] or 0)>=55 and stress['economic_screen_pass']:
            qualified.append(spec['name'])
        for cost in v.w.COSTS:
            trades=read(v.RUN/(spec['name']+'_'+cost['id']+'_trades.json'))['trades']
            for r in trades:
                fee_rows+=1
                if r['entry_time']:
                    assert math.isclose(r['commission_r'],cost['commission_price']/r['risk'],abs_tol=1e-10)
                if r['r'] is not None:
                    assert math.isclose(r['r'],r['gross_r']-r['commission_r'],abs_tol=1e-10)
                assert 'ASSUMED_ROUND_TRIP_COMMISSION' in r['fees_status']
                if cost['id']=='BASE' and r['state']=='CLOSED':
                    i=np.searchsorted(opp['known'],r['source_known_at']);side=0 if r['buy'] else 1
                    assert opp['known'][i]==r['source_known_at']
                    assert payoff[i,side]==r['r'] and risk[i,side]==r['risk'],'Actual trade differs from hypothetical training payoff definition'
                    label_matches+=1
    assert np.all(raw[:,8]>=55) and np.all(raw[:,33]>0)
    preserved={p:sha(v.w.ROOT/p)==h for p,h in lock['preserved_fresh'].items()};assert all(preserved.values())
    write_json(v.RUN/'VERIFICATION.json',dict(passed=True,detector_forecast_prefixes=checks,
        execution_prefixes=executions,fee_rows_audited=fee_rows,base_execution_label_exact_matches=label_matches,
        monthly_model_provenance=len(models),fresh_unchanged=preserved,qualified=qualified,
        historical_edge_confirmed=False,FTMO_rules_deferred_per_user=True))
    write_json(v.RUN/'CUMULATIVE_REGISTRY.json',dict(previous=dict(hypotheses=109,scenarios=413),
        new=dict(hypotheses=3,cost_scenarios=9),cumulative=dict(hypotheses=112,scenarios=422),
        tests=dict(previous_unique=140,new=5,total_unique=145),
        prefix=dict(detector_forecast=2,execution=6),qualified=qualified,goal_status='active;no qualifying edge'))
    print('PASS',len(checks),'detector/forecast+',len(executions),'execution prefixes;',fee_rows,'fee rows;',label_matches,
        'actual BASE trades equal reference payoff labels;qualified',qualified,flush=True)


if __name__=='__main__':main()
