"""Rebuild H4/D1 direction decisions from raw bars and audit every BASE label identity."""
import json
import math
from collections import Counter

import numpy as np

from can_ho_tro_scalp_core import bars_matrix,metaquotes_atr
from can_ho_tro_scalp_plan import round_tick
from prepare_can_ho_tro_scalp import sha,write_json
from audit_scalp_trendline_v18 import reference_structure,asof
import research_scalp_direction_v19 as s


def reconstruct(gold,s4,sd):
    a = metaquotes_atr(gold);rows = [];opportunities = 0
    for i in range(6,len(gold)):
        known = gold[i,0]+300
        if not s.w.START<=known<s.w.END or known%1800 or not 7200<=known%86400<64800:
            continue
        if gold[i,0]-gold[i-6,0]!=1800 or a[i]<=0:
            continue
        opportunities += 1;d,k4 = asof(gold[i,0],s4,28800);dd,kd = asof(gold[i,0],sd,345600)
        if not d:
            continue
        for family in ([50,51] if d==dd else [50]):
            close = gold[i,4];stop = close-d*max(2.,1.5*a[i]);c = np.zeros(40)
            c[:8] = [known-300,known+60,int(d>0),k4,10+family,0,0,known]
            c[8:18] = [50,0,close,close,k4,known-300,stop,k4,close,k4]
            c[18:23] = [a[i],stop,stop,close,close];c[34:40] = [i,0,family,known,0,k4]
            rows.append(c)
    return np.asarray(rows,float).reshape((-1,40)),opportunities


def main():
    read = lambda p:json.loads(p.read_text(encoding='utf-8'))
    w = s.w;v = s.v;lock = read(s.RUN/'EXPERIMENT_LOCK.json')
    source = np.load(w.BASE/'rates.npz');gold = bars_matrix(source['m5']);market = bars_matrix(source['m1'])
    d1 = bars_matrix(source['d1']);h4 = bars_matrix(np.load(s.t.RUN/'h4_rates.npz')['rates'])
    s4,c4 = reference_structure(h4,14400);sd,cd = reference_structure(d1,86400)
    np.testing.assert_array_equal(s4,s.t.structure(h4,14400));np.testing.assert_array_equal(sd,s.t.structure(d1,86400))
    expected,opportunities = reconstruct(gold,s4,sd);raw = np.load(s.RUN/'raw_candidates.npy')
    np.testing.assert_array_equal(expected,raw)
    assert np.all(raw[:,39]<=raw[:,0]) and np.all(raw[:,12]<=raw[:,0]) and np.all(raw[:,1]==raw[:,37]+60)
    prefixes = [];executions = [];w.FAMILIES.update(s.NAMES)
    for year in (2022,2025):
        cut = int(w.datetime(year,1,1,tzinfo=w.timezone.utc).timestamp())
        gm = gold[gold[:,0]+300<=cut];h = h4[h4[:,0]+14400<=cut];d = d1[d1[:,0]+86400<=cut]
        hs = s.t.structure(h,14400);ds = s.t.structure(d,86400)
        np.testing.assert_array_equal(hs,s4[:len(h)]);np.testing.assert_array_equal(ds,sd[:len(d)])
        candidates = s.candidates(v.seasonal.opportunities(gm),hs,ds,end=cut)
        np.testing.assert_array_equal(candidates,raw[raw[:,37]<cut])
        prefixes.append(dict(cut=cut,raw_M5_H4_D1_pivots_direction_candidates_exact=True,candidates=len(candidates)))
        pm = market[market[:,0]+60<=cut]
        for spec in s.SPECS:
            full = read(s.RUN/(spec['name']+'_BASE_trades.json'))['trades']
            rows,_ = v.execution.run_serial(candidates,pm,spec,w.COSTS[1])
            fields = ('state','reason','entry_time','exit_time','entry','initial_sl','risk','r','commission_r','target')
            closed = lambda rr:[{k:r[k] for k in fields} for r in rr if r['state']=='CLOSED' and r['exit_time']<cut]
            assert closed(rows)==closed(full),(year,spec['name'])
            executions.append(dict(name=spec['name'],cut=cut,closed=len(closed(rows)),exact=True))
    labels = np.load(v.RUN/'barrier_labels.npz');fees = 0;matched = 0;money = 0;qualified = [];summary = read(s.RUN/'summary.json')
    for spec in s.SPECS:
        base = next(r['metrics'] for r in summary['rows'] if r['name']==spec['name'] and r['cost']=='BASE')
        stress = next(r['metrics'] for r in summary['rows'] if r['name']==spec['name'] and r['cost']=='STRESS')
        if base['frequency_pass'] and base['economic_screen_pass'] and (base['win_rate'] or 0)>=55 and stress['economic_screen_pass']:
            qualified.append(spec['name'])
        for cost in w.COSTS:
            rows = read(s.RUN/(spec['name']+'_'+cost['id']+'_trades.json'))['trades'];filled = [r for r in rows if r['entry_time']]
            assert max(Counter(r['entry_time']//86400 for r in filled).values(),default=0)<=2
            assert max(Counter(w.week_key(r['entry_time']) for r in filled).values(),default=0)<=10
            assert all(b['entry_time']>=a['exit_time'] for a,b in zip(filled,filled[1:]))
            for r in rows:
                fees += 1;d = 1 if r['buy'] else -1
                if r['entry_time']:
                    assert 2.-1e-9<=r['risk']<=20.+1e-9
                    assert math.isclose(r['risk'],d*(r['entry']-r['initial_sl']),abs_tol=1e-10)
                    assert math.isclose(r['commission_r'],cost['commission_price']/r['risk'],abs_tol=1e-10)
                    assert r['target']==round_tick(r['entry']+d*.8*r['risk'],.01,d)
                    assert r['deadline']==min(r['entry_time']+7200,r['entry_time']//86400*86400+21*3600)
                if r['r'] is not None:
                    assert math.isclose(r['gross_r'],d*(r['exit_price']-r['entry'])/r['risk'],abs_tol=1e-10)
                    assert math.isclose(r['r'],r['gross_r']-r['commission_r'],abs_tol=1e-10);money += 1
                assert 'ASSUMED_ROUND_TRIP_COMMISSION' in r['fees_status']
                if cost['id']=='BASE' and r['state']=='CLOSED':
                    i = np.searchsorted(labels['known'],r['source_known_at']);side = 0 if r['buy'] else 1
                    assert i<len(labels['known']) and labels['known'][i]==r['source_known_at']
                    assert labels['payoff'][i,side]==r['r'] and labels['risk'][i,side]==r['risk'];matched += 1
    fresh = {p:sha(w.ROOT/p)==h for p,h in lock['preserved_fresh'].items()};assert all(fresh.values())
    implementation = {p:sha(w.ROOT/p)==h for p,h in lock['implementation_sha256'].items()};assert all(implementation.values())
    assert sha(w.BASE/'rates.npz')==lock['gold_sha256'] and sha(v.RUN/'barrier_labels.npz')==lock['labels_sha256']
    assert sha(s.t.RUN/'h4_rates.npz')==lock['h4_sha256']
    write_json(s.RUN/'VERIFICATION.json',dict(passed=True,independent_structure=dict(h4=dict(rows=len(h4),**c4),d1=dict(rows=len(d1),**cd)),
        independently_checked_opportunities=opportunities,independent_direction_candidate_rows=len(raw),
        raw_feature_detector_prefixes=prefixes,execution_prefixes=executions,fee_rows_audited=fees,
        exact_exit_risk_target_deadline_money_rows=money,all_closed_BASE_R_risk_label_matches=matched,
        fresh_unchanged=fresh,implementation_unchanged=implementation,qualified=qualified,
        historical_edge_confirmed=False,FTMO_rules_deferred_per_user=True))
    write_json(s.RUN/'CUMULATIVE_REGISTRY.json',dict(previous=dict(hypotheses=129,scenarios=473),
        new=dict(hypotheses=2,cost_scenarios=6),cumulative=dict(hypotheses=131,scenarios=479),
        tests=dict(previous_unique=170,new=3,total_unique=173),prefixes=dict(raw_feature_detector=2,execution=4),
        qualified=qualified,goal_status='active;researchongoing'))
    write_json(s.RUN/'SOURCE_MANIFEST.json',dict(fresh_unchanged=True,
        files={p:sha(w.ROOT/p) for p in lock['implementation_sha256']},audit_sha256=sha(w.ROOT/'scripts/audit_scalp_direction_v19.py'),
        independent_pivot_reference_sha256=sha(w.ROOT/'scripts/audit_scalp_trendline_v18.py')))
    print('PASS',opportunities,'independent opportunities;',len(raw),'direction candidates;',len(prefixes),'raw+',len(executions),
          'execution prefixes;',fees,'fee rows,',money,'money rows,',matched,'all closed BASE labels;qualified',qualified,flush=True)


if __name__=='__main__':
    main()
