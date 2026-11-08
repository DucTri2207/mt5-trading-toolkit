"""Reconstruct frozen boxes/first breaks and audit serial execution after fees."""
import json
import math

import numpy as np

from can_ho_tro_scalp_core import bars_matrix,metaquotes_atr
from can_ho_tro_scalp_plan import round_tick
from prepare_can_ho_tro_scalp import sha,write_json
import research_scalp_compression_v17 as s


def main():
    read = lambda p:json.loads(p.read_text(encoding='utf-8'))
    w = s.w;v = s.v;lock = read(s.RUN/'EXPERIMENT_LOCK.json')
    source = np.load(w.BASE/'rates.npz');gold = bars_matrix(source['m5']);market = bars_matrix(source['m1'])
    raw = np.load(s.RUN/'raw_candidates.npy');events = np.load(s.RUN/'events.npy');a = metaquotes_atr(gold)
    tr = np.zeros(len(gold));tr[1:] = np.maximum.reduce((gold[1:,2]-gold[1:,3],
        np.abs(gold[1:,2]-gold[:-1,4]),np.abs(gold[1:,3]-gold[:-1,4])))
    for row in events:
        known,family,buy,armed,lo,hi,fa,ratio,broken,index = row;i = int(index)
        k = int(np.searchsorted(gold[:,0]+300,armed));j = int(np.searchsorted(gold[:,0]+300,broken))
        assert gold[k,0]+300==armed and gold[i,0]+300==known
        assert gold[i,0]-gold[k-48,0]==(i-k+48)*300
        assert hi==np.max(gold[k-5:k+1,2]) and lo==np.min(gold[k-5:k+1,3]) and fa==a[k]
        expected = np.mean(tr[k-5:k+1])/np.mean(tr[k-47:k-5])
        assert math.isclose(ratio,expected,abs_tol=1e-12)
        if family in (44,45):
            assert ratio<=.60
        assert armed<broken<=known<=armed+3600 and 2*3600<=known%86400<18*3600
        close = gold[k+1:i+1,4]
        breaks = np.where((close>hi+.1*fa)|(close<lo-.1*fa))[0]
        assert len(breaks) and k+1+breaks[0]==j
        d = 1 if gold[j,4]>hi+.1*fa else -1
        if family in (44,46):
            assert i==j and buy==int(d>0)
            assert d*(gold[i,4]-gold[i,1])>=.25*fa and gold[i,2]-gold[i,3]>=fa
        else:
            assert 0<i-j<=3 and buy==int(d<0)
            inside = np.where((gold[j+1:i+1,4]>lo)&(gold[j+1:i+1,4]<hi))[0]
            assert len(inside) and j+1+inside[0]==i
            reverse = -d;outer = ((gold[i,4]-gold[i,3]) if reverse>0 else (gold[i,2]-gold[i,4]))/(gold[i,2]-gold[i,3])
            assert reverse*(gold[i,4]-gold[i,1])>=.15*fa and outer>=.65
    assert np.all(raw[:,12]<raw[:,37]) and np.all(raw[:,12]<=raw[:,13])
    assert np.all(raw[:,1]==raw[:,37]+60)
    prefixes = [];executions = [];w.FAMILIES.update(s.NAMES)
    for year in (2022,2025):
        cut = int(w.datetime(year,1,1,tzinfo=w.timezone.utc).timestamp())
        gm = gold[gold[:,0]+300<=cut];detected = s.events(gm,end=cut)
        np.testing.assert_array_equal(detected,events[events[:,0]<cut])
        candidates = s.candidates(gm,detected)
        np.testing.assert_array_equal(candidates,raw[raw[:,37]<cut])
        prefixes.append(dict(cut=cut,raw_gold_frozen_boxes_event_detector_candidates_exact=True,events=len(detected)))
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
            rows = read(s.RUN/(spec['name']+'_'+cost['id']+'_trades.json'))['trades']
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
                    if i<len(labels['known']) and labels['known'][i]==r['source_known_at']:
                        assert labels['payoff'][i,side]==r['r'] and labels['risk'][i,side]==r['risk'];matched += 1
    fresh = {p:sha(w.ROOT/p)==h for p,h in lock['preserved_fresh'].items()};assert all(fresh.values())
    implementation = {p:sha(w.ROOT/p)==h for p,h in lock['implementation_sha256'].items()};assert all(implementation.values())
    assert sha(w.BASE/'rates.npz')==lock['gold_sha256'] and sha(v.RUN/'barrier_labels.npz')==lock['labels_sha256']
    write_json(s.RUN/'VERIFICATION.json',dict(passed=True,independent_frozen_box_first_event_checks=len(events),
        raw_feature_detector_prefixes=prefixes,execution_prefixes=executions,fee_rows_audited=fees,
        exact_exit_risk_target_deadline_money_rows=money,common_half_hour_BASE_R_risk_label_matches=matched,
        fresh_unchanged=fresh,implementation_unchanged=implementation,qualified=qualified,
        historical_edge_confirmed=False,FTMO_rules_deferred_per_user=True))
    write_json(s.RUN/'CUMULATIVE_REGISTRY.json',dict(previous=dict(hypotheses=123,scenarios=455),
        new=dict(hypotheses=3,cost_scenarios=9),cumulative=dict(hypotheses=126,scenarios=464),
        tests=dict(previous_unique=160,new=4,total_unique=164),prefixes=dict(raw_feature_detector=2,execution=6),
        qualified=qualified,goal_status='active;researchongoing'))
    write_json(s.RUN/'SOURCE_MANIFEST.json',dict(fresh_unchanged=True,
        files={p:sha(w.ROOT/p) for p in lock['implementation_sha256']},audit_sha256=sha(w.ROOT/'scripts/audit_scalp_compression_v17.py')))
    print('PASS',len(events),'independentfrozenbox/firsteventchecks;',len(prefixes),'raw+',len(executions),
          'executionprefixes;',fees,'feerows,',money,'moneyrows,',matched,'commonBASElabelmatches;qualified',qualified,flush=True)


if __name__=='__main__':
    main()
