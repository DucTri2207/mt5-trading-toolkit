"""Raw equity prefixes, executable chronology and unchanged money assumptions."""
import json
import math

import numpy as np

from can_ho_tro_scalp_core import bars_matrix
from prepare_can_ho_tro_scalp import sha,write_json
import research_scalp_flight_v15 as s


def main():
    read=lambda p:json.loads(p.read_text(encoding='utf-8'));w=s.w;v=s.v
    screen_path=s.RUN/'DATA_QUALITY_SCREEN.json'
    if screen_path.exists():
        screen=read(screen_path);assert not screen['passed'] and not screen['barrier_backtest_executed']
        for name,key in (('equity_rates.npz','primary_gaps'),('equity_mini_rates.npz','replacement_gaps')):
            a=np.load(s.RUN/name)['rates'];gap=np.where(np.diff(a['time'])>=7*86400)[0]
            actual=[dict(previous=int(a['time'][i]),following=int(a['time'][i+1]),seconds=int(a['time'][i+1]-a['time'][i])) for i in gap]
            assert actual==screen[key] and sha(s.RUN/name)==screen['data_sha256'][name]
        prior=read(w.ROOT/'reports/can_ho_tro_scalp/20261101_metals_v14/EXPERIMENT_LOCK.json')
        assert all(sha(w.ROOT/p)==h for p,h in prior['preserved_fresh'].items())
        assert not (s.RUN/'summary.json').exists() and not (s.RUN/'raw_candidates.npy').exists()
        write_json(s.RUN/'VERIFICATION.json',dict(passed=True,data_gate_rejection_verified=True,
            backtest_executed=False,opened_hypotheses=0,executed_scenarios=0,fresh_unchanged=True,qualified=[]))
        print('PASSbothsourcegapsindependentlyverified;nooutcomebacktest;Freshunchanged',flush=True)
        return
    lock=read(s.RUN/'EXPERIMENT_LOCK.json');source=np.load(w.BASE/'rates.npz')
    gold=bars_matrix(source['m5']);market=bars_matrix(source['m1']);equity=bars_matrix(np.load(s.RUN/lock['equity_file'])['rates'])
    assert sha(s.RUN/lock['equity_file'])==lock['equity_sha256']
    assert sha(s.RUN/'DATA_AMENDMENT.json')==lock['data_amendment_sha256']
    f=np.load(s.RUN/'features.npy');raw=np.load(s.RUN/'raw_candidates.npy');w.FAMILIES.update(s.NAMES)
    prefixes=[];executions=[]
    for year in (2022,2025):
        cut=int(w.datetime(year,1,1,tzinfo=w.timezone.utc).timestamp());gm=gold[:,0]+300<=cut;em=equity[:,0]+300<=cut
        actual=s.features(gold[gm],equity[em]);np.testing.assert_array_equal(actual,f[gm])
        detected=s.candidates(actual,end=cut);np.testing.assert_array_equal(detected,raw[raw[:,37]<cut])
        prefixes.append(dict(cut=cut,raw_equity_gold_features_detector_exact=True,candidates=len(detected)))
        pm=market[market[:,0]+60<=cut]
        for spec in s.SPECS:
            rows,_=v.execution.run_serial(detected,pm,spec,w.COSTS[1]);full=read(s.RUN/(spec['name']+'_BASE_trades.json'))['trades']
            fields=('state','reason','entry_time','exit_time','entry','initial_sl','risk','r','commission_r','target')
            closed=lambda rr:[{k:r[k] for k in fields} for r in rr if r['state']=='CLOSED' and r['exit_time']<cut]
            assert closed(rows)==closed(full),(year,spec['name'])
            executions.append(dict(name=spec['name'],cut=cut,closed=len(closed(rows)),exact=True))
    checked=0
    # Independent direct return calculations on 256 actual valid signals/feature rows.
    for i in np.where(np.isfinite(f[:,2]))[0][::max(1,int(np.isfinite(f[:,2]).sum())//256)][:256]:
        j=np.searchsorted(equity[:,0],gold[i,0]);j1=np.searchsorted(equity[:,0],gold[i-1,0]);j48=np.searchsorted(equity[:,0],gold[i-48,0])
        assert equity[j,0]==gold[i,0] and equity[j1,0]==gold[i-1,0] and equity[j48,0]==gold[i-48,0]
        assert f[i,1]==equity[j,4]/equity[j1,4]-1 and f[i,2]==equity[j,4]/equity[j48,4]-1;checked+=1
    assert np.all(raw[:,1]==raw[:,37]+60) and np.all(raw[:,0]==raw[:,37]-300) and np.all(raw[:,2]==1)
    summary=read(s.RUN/'summary.json');fees=0;qualified=[]
    for spec in s.SPECS:
        base=next(r['metrics'] for r in summary['rows'] if r['name']==spec['name'] and r['cost']=='BASE')
        stress=next(r['metrics'] for r in summary['rows'] if r['name']==spec['name'] and r['cost']=='STRESS')
        if base['frequency_pass'] and base['economic_screen_pass'] and (base['win_rate'] or 0)>=55 and stress['economic_screen_pass']:qualified.append(spec['name'])
        for cost in w.COSTS:
            rows=read(s.RUN/(spec['name']+'_'+cost['id']+'_trades.json'))['trades']
            for r in rows:
                fees+=1
                if r['entry_time']:
                    assert r['entry_time']>=r['source_known_at']+60
                    assert math.isclose(r['commission_r'],cost['commission_price']/r['risk'],abs_tol=1e-10)
                if r['r'] is not None:assert math.isclose(r['r'],r['gross_r']-r['commission_r'],abs_tol=1e-10)
                assert 'ASSUMED_ROUND_TRIP_COMMISSION' in r['fees_status']
    fresh={p:sha(w.ROOT/p)==h for p,h in lock['preserved_fresh'].items()};assert all(fresh.values())
    implementation={p:sha(w.ROOT/p)==h for p,h in lock['implementation_sha256'].items()};assert all(implementation.values())
    write_json(s.RUN/'VERIFICATION.json',dict(passed=True,raw_feature_detector_prefixes=prefixes,execution_prefixes=executions,
        independent_return_rows=checked,fee_rows_audited=fees,fresh_unchanged=fresh,implementation_unchanged=implementation,
        qualified=qualified,historical_edge_confirmed=False,FTMO_rules_deferred_per_user=True))
    write_json(s.RUN/'CUMULATIVE_REGISTRY.json',dict(previous=dict(hypotheses=119,scenarios=443),new=dict(hypotheses=2,cost_scenarios=6),
        cumulative=dict(hypotheses=121,scenarios=449),tests=dict(previous_unique=154,new=2,total_unique=156),
        prefixes=dict(raw_feature_detector=2,execution=4),qualified=qualified,goal_status='active;researchongoing'))
    print('PASS',len(prefixes),'rawfeature/detector+',len(executions),'executionprefixes;',checked,'independentreturnrows;',fees,'feerows;qualified',qualified,flush=True)


if __name__=='__main__':main()
