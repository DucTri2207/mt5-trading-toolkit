"""Frozen-signal identity, structural-stop prefixes, serial execution and fees."""
import json
import math
from collections import Counter

import numpy as np

from can_ho_tro_scalp_core import bars_matrix
from can_ho_tro_scalp_plan import planned_gate
from prepare_can_ho_tro_scalp import sha,write_json
import research_scalp_anchor_stop_v8 as a


def read(path):return json.loads(path.read_text(encoding='utf-8'))


def main():
    w=a.w;v=a.v;source=np.load(w.BASE/'rates.npz');arrays={k:bars_matrix(source[k]) for k in source.files}
    lock=read(a.RUN/'EXPERIMENT_LOCK.json');m15=w.aggregate_complete(arrays['m5'],900);parts=[];checks=[];gates={}
    for name in ('SWING_AVWAP','SWING_EQUAL_WEIGHT'):
        original=np.load(v.RUN/(name+'_candidates.npz'))['raw']
        full=np.load(a.RUN/(name+'_anchor_candidates.npz'))['raw'];parts.append(full)
        unchanged=[k for k in range(40) if k not in (19,20)]
        np.testing.assert_array_equal(full[:,unchanged],original[:,unchanged])
        np.testing.assert_array_equal(full,a.replace_stops(original,m15))
        d=full[:,2]*2-1
        assert np.all(d*(original[:,19]-full[:,19])>=-1e-10)
        gates[name]=dict(Counter(planned_gate(c) for c in full))
        for year in (2022,2025):
            cut=int(w.datetime(year,1,1,tzinfo=w.timezone.utc).timestamp())
            actual=a.replace_stops(original[original[:,1]<cut],m15[m15[:,0]+900<=cut])
            np.testing.assert_array_equal(actual,full[full[:,1]<cut])
            checks.append(dict(name=name,cut=cut,rows=len(actual),exact=True))
            print('ANCHOR STOP PREFIX',name,year,len(actual),'PASS',flush=True)
    w.FAMILIES.update(v.NAMES);raw=w.add_fresh(np.concatenate(parts));execution=[];diagnostics=[]
    fields=['candidate_index','state','reason','entry_time','exit_time','entry','initial_sl','risk','r','commission_r','target','deadline']
    for spec in a.SPECS:
        full=read(a.RUN/(spec['name']+'_BASE_trades.json'))['trades']
        for year in (2022,2025):
            cut=int(w.datetime(year,1,1,tzinfo=w.timezone.utc).timestamp())
            actual,_=v.run_serial(raw[raw[:,1]<cut],arrays['m1'][arrays['m1'][:,0]+60<=cut],spec,w.COSTS[1])
            closed=lambda rows:[{k:t[k] for k in fields} for t in rows if t['state']=='CLOSED' and t['exit_time']<cut]
            assert closed(actual)==closed(full),(spec['name'],year)
            execution.append(dict(name=spec['name'],cut=cut,closed=len(closed(actual)),exact=True))
            print('ANCHOR EXEC PREFIX',spec['name'],year,len(closed(actual)),'PASS',flush=True)
    summary=read(a.RUN/'summary.json');qualified=[]
    for spec in a.SPECS:
        base=next(r['metrics'] for r in summary['rows'] if r['name']==spec['name'] and r['cost']=='BASE')
        stress=next(r['metrics'] for r in summary['rows'] if r['name']==spec['name'] and r['cost']=='STRESS')
        if base['frequency_pass'] and base['economic_screen_pass'] and (base['win_rate'] or 0)>=55 and stress['total_r']>0:
            qualified.append(spec['name'])
    for row in summary['rows']:
        trades=read(a.RUN/(row['name']+'_'+row['cost']+'_trades.json'))['trades']
        cost=next(c for c in w.COSTS+[a.ZERO] if c['id']==row['cost'])
        filled=[t for t in trades if t['entry_time']];closed=[t for t in trades if t['state']=='CLOSED']
        for t in trades:
            fee=cost['commission_price']/t['risk'] if t['entry_time'] else 0.
            assert math.isclose(t['commission_r'],fee,abs_tol=1e-10)
            assert math.isclose(t['commission'],cost['commission_price']*100 if t['entry_time'] else 0.,abs_tol=1e-10)
            assert 'ASSUMED_ROUND_TRIP_COMMISSION' in t['fees_status']
            if t['r'] is not None:assert math.isclose(t['r'],t['gross_r']-fee,abs_tol=1e-10)
        assert all(b['entry_time']>=x['exit_time'] for x,b in zip(filled,filled[1:]))
        diagnostics.append(dict(name=row['name'],cost=row['cost'],filled=len(filled),closed=len(closed),
            risk_quantiles=np.quantile([t['risk'] for t in filled],[.1,.5,.9]).tolist() if filled else None,
            minimum_risk_fills=sum(t['risk']<2.01 for t in filled),
            reasons={r:sum(t['reason']==r for t in closed) for r in sorted(set(t['reason'] for t in closed))}))
    preserved={p:sha(w.ROOT/p)==value for p,value in lock['preserved_fresh'].items()};assert all(preserved.values())
    write_json(a.RUN/'PREFIX_CHECKS.json',dict(passed=True,stop_transform=checks,execution=execution))
    write_json(a.RUN/'ENTRY_DIAGNOSTICS.json',dict(rows=diagnostics,planned_gates=gates))
    write_json(a.RUN/'VERIFICATION.json',dict(qualified=qualified,fresh_unchanged=preserved,
        tests=dict(previous_unique=116,new_anchor_stop=4,total_unique=120),
        signals_unchanged_except_columns=[19,20],stop_transform_prefixes=len(checks),execution_prefixes=len(execution),
        fee_metadata_and_arithmetic_verified=True,historical_edge_confirmed=False,
        native_new_branch='not built;no qualified candidate'))


if __name__=='__main__':main()
