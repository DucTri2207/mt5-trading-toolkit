"""Audit GLD availability, independently reconstructed residuals and unchanged net money."""
import json
import math

import numpy as np

from can_ho_tro_scalp_core import bars_matrix
from prepare_can_ho_tro_scalp import sha,write_json
import research_scalp_flows_v16 as s


def main():
    read = lambda p:json.loads(p.read_text(encoding='utf-8'))
    w = s.w;v = s.v;lock = read(s.RUN/'EXPERIMENT_LOCK.json')
    source = np.load(w.BASE/'rates.npz');gold = bars_matrix(source['m5']);market = bars_matrix(source['m1'])
    opp = v.seasonal.opportunities(gold);inputs = np.load(s.RUN/'flow_inputs.npz')
    reports = s.load_reports();daily = inputs['daily'];raw = np.load(s.RUN/'raw_candidates.npy')
    labels = np.load(v.RUN/'barrier_labels.npz');w.FAMILIES.update(s.NAMES)
    for k,a in opp.items():
        np.testing.assert_array_equal(a,labels[k])
    np.testing.assert_array_equal(reports,inputs['reports'])
    picked = inputs['picked'];valid = np.isfinite(picked[:,0])
    assert np.all(picked[valid,1]<=opp['known'][valid])
    assert np.all(opp['known'][valid]-picked[valid,0]<=s.STALE)
    assert np.all(picked[valid,1]==picked[valid,0]+s.LAG)
    assert np.all(raw[:,12]==raw[:,17]) and np.all(raw[:,12]<=raw[:,13])
    assert np.all(raw[:,1]==raw[:,37]+60)
    assert set((raw[:,37]%86400).astype(int)) <= {8*3600,14*3600}
    prefixes = [];executions = []
    for year in (2022,2025):
        cut = int(w.datetime(year,1,1,tzinfo=w.timezone.utc).timestamp());keep = opp['known']<=cut
        rg = reports[reports[:,0]+s.LAG<=cut]
        df,cf = s.daily_features(rg);report_keep = reports[:,0]+s.LAG<=cut
        np.testing.assert_array_equal(df,daily[report_keep]);np.testing.assert_array_equal(cf,inputs['coefficients'][report_keep])
        po = v.seasonal.opportunities(gold[gold[:,0]+300<=cut])
        pf = s.asof_features(po['known'],df)
        np.testing.assert_array_equal(pf,picked[keep])
        detected = s.candidates(po,pf,end=cut)
        np.testing.assert_array_equal(detected,raw[raw[:,37]<cut])
        prefixes.append(dict(cut=cut,raw_report_gold_features_coefficients_asof_detector_exact=True,candidates=len(detected)))
        pm = market[market[:,0]+60<=cut]
        for spec in s.SPECS:
            full = read(s.RUN/(spec['name']+'_BASE_trades.json'))['trades']
            rows,_ = v.execution.run_serial(detected,pm,spec,w.COSTS[1])
            fields = ('state','reason','entry_time','exit_time','entry','initial_sl','risk','r','commission_r','target')
            closed = lambda rr:[{k:r[k] for k in fields} for r in rr if r['state']=='CLOSED' and r['exit_time']<cut]
            assert closed(rows)==closed(full),(year,spec['name'])
            executions.append(dict(name=spec['name'],cut=cut,closed=len(closed(rows)),exact=True))
    # Rebuild daily regressors independently, then solve ridge as augmented least squares.
    n = len(reports);x = np.full((n,5),np.nan);flow = np.full(n,np.nan)
    implied = reports[:,3]/reports[:,2]
    for i in range(1,n):
        if reports[i,0]-reports[i-1,0]<=4*86400:
            flow[i] = math.log(implied[i]/implied[i-1])
        if i>=20 and np.all(np.diff(reports[i-20:i+1,0])<=4*86400):
            x[i] = (1.,math.log(reports[i,1]/reports[i-1,1]),reports[i,4],reports[i-1,4],
                    math.log(reports[i,5]/sum(reports[i-20:i,5])*20))
    np.testing.assert_allclose(flow,daily[:,2],rtol=0,atol=1e-15,equal_nan=True)
    fitted = np.isfinite(daily[:,5]);assert np.all(daily[fitted,7]==126)
    assert np.all(daily[fitted,8]<daily[fitted,0])
    refits = []
    for year in range(2021,2027):
        at = int(w.datetime(year,6,1,tzinfo=w.timezone.utc).timestamp())
        eligible = np.where(fitted&(reports[:,0]>=at))[0]
        if not len(eligible):
            continue
        i = eligible[0];prior = np.where(np.all(np.isfinite(x[:i]),axis=1)&np.isfinite(flow[:i]))[0][-126:]
        assert len(prior)==daily[i,7] and reports[prior[-1],0]==daily[i,8]
        mean = x[prior].mean(axis=0);scale = x[prior].std(axis=0);mean[0] = 0.;scale[0] = 1.;scale[scale<1e-12] = 1.
        z = (x[prior]-mean)/scale;penalty = np.eye(5)*np.sqrt(10);penalty[0,0] = 0.
        beta = np.linalg.lstsq(np.vstack((z,penalty)),np.r_[flow[prior],np.zeros(5)],rcond=None)[0]
        expected = flow[i]-((x[i]-mean)/scale)@beta
        assert math.isclose(expected,daily[i,5],rel_tol=0,abs_tol=1e-12)
        np.testing.assert_allclose(np.r_[mean,scale,beta],inputs['coefficients'][i],rtol=0,atol=1e-11)
        refits.append(dict(source_date=int(reports[i,0]),n=126,last_training_source=int(reports[prior[-1],0]),
                           residual_difference=float(abs(expected-daily[i,5]))))
    fees = 0;matched = 0;qualified = [];summary = read(s.RUN/'summary.json')
    for spec in s.SPECS:
        base = next(r['metrics'] for r in summary['rows'] if r['name']==spec['name'] and r['cost']=='BASE')
        stress = next(r['metrics'] for r in summary['rows'] if r['name']==spec['name'] and r['cost']=='STRESS')
        if base['frequency_pass'] and base['economic_screen_pass'] and (base['win_rate'] or 0)>=55 and stress['economic_screen_pass']:
            qualified.append(spec['name'])
        for cost in w.COSTS:
            rows = read(s.RUN/(spec['name']+'_'+cost['id']+'_trades.json'))['trades']
            for r in rows:
                fees += 1
                if r['entry_time']:
                    assert math.isclose(r['commission_r'],cost['commission_price']/r['risk'],abs_tol=1e-10)
                if r['r'] is not None:
                    assert math.isclose(r['r'],r['gross_r']-r['commission_r'],abs_tol=1e-10)
                assert 'ASSUMED_ROUND_TRIP_COMMISSION' in r['fees_status']
                if cost['id']=='BASE' and r['state']=='CLOSED':
                    i = np.searchsorted(opp['known'],r['source_known_at']);side = 0 if r['buy'] else 1
                    assert labels['payoff'][i,side]==r['r'] and labels['risk'][i,side]==r['risk'];matched += 1
    fresh = {p:sha(w.ROOT/p)==h for p,h in lock['preserved_fresh'].items()};assert all(fresh.values())
    implementation = {p:sha(w.ROOT/p)==h for p,h in lock['implementation_sha256'].items()};assert all(implementation.values())
    for path,key in (('GLD_archive.xlsx','source_sha256'),('GLD_normalized.json','normalized_sha256'),('GLD_DATA_MANIFEST.json','manifest_sha256')):
        assert sha(s.RUN/path)==lock[key]
    assert sha(w.BASE/'rates.npz')==lock['gold_sha256'] and sha(v.RUN/'barrier_labels.npz')==lock['labels_sha256']
    write_json(s.RUN/'VERIFICATION.json',dict(passed=True,raw_report_feature_detector_prefixes=prefixes,
        execution_prefixes=executions,independent_daily_residual_refits=refits,
        daily_prior126_provenance_rows=int(fitted.sum()),asof_availability_rows=int(valid.sum()),
        fee_rows_audited=fees,base_R_risk_label_exact_matches=matched,fresh_unchanged=fresh,
        implementation_unchanged=implementation,qualified=qualified,historical_edge_confirmed=False,
        source_point_in_time_verified=False,FTMO_rules_deferred_per_user=True))
    write_json(s.RUN/'CUMULATIVE_REGISTRY.json',dict(previous=dict(hypotheses=119,scenarios=443),
        new=dict(hypotheses=4,cost_scenarios=12),cumulative=dict(hypotheses=123,scenarios=455),
        tests=dict(previous_unique=156,new=4,total_unique=160),
        prefixes=dict(raw_report_feature_detector=2,execution=8),independent_daily_refits=len(refits),
        qualified=qualified,goal_status='active;researchongoing'))
    write_json(s.RUN/'SOURCE_MANIFEST.json',dict(fresh_unchanged=True,
        files={p:sha(w.ROOT/p) for p in lock['implementation_sha256']},
        audit_sha256=sha(w.ROOT/'scripts/audit_scalp_flows_v16.py')))
    print('PASS',len(prefixes),'rawprefixes,',len(executions),'execution,',len(refits),'independentresidualrefits,',
          fees,'feerows,',matched,'exactBASElabelmatches;qualified',qualified,flush=True)


if __name__=='__main__':
    main()
