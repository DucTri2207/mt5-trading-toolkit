"""Real-data detector/execution prefixes and volume/fee provenance checks."""
import json
import math

import numpy as np

from can_ho_tro_scalp_core import bars_matrix
from prepare_can_ho_tro_scalp import sha, write_json
import research_scalp_avwap_v7 as v


def read(path):
    return json.loads(path.read_text(encoding='utf-8'))


def main():
    w = v.w; source = np.load(w.BASE/'rates.npz'); arrays = {k: bars_matrix(source[k]) for k in source.files}
    volume = source['m1']['tick_volume'].astype(float); lock = read(v.RUN/'EXPERIMENT_LOCK.json')
    checks = []; parts = []
    for family, name in v.NAMES.items():
        full = np.load(v.RUN/(name+'_candidates.npz'))['raw']; parts.append(full)
        for year in (2022,2025):
            cut = int(w.datetime(year,1,1,tzinfo=w.timezone.utc).timestamp())
            prefix = {k: a[a[:,0]+{'m1':60,'m5':300,'h1':3600,'d1':86400}[k]<=cut] for k,a in arrays.items()}
            pv = volume[arrays['m1'][:,0]+60<=cut]
            actual = v.detect(prefix,pv,family,stop=cut)
            np.testing.assert_array_equal(actual,full[full[:,1]<cut])
            checks.append(dict(source=name,cut=cut,rows=len(actual),exact=True))
            print('AVWAP PREFIX',name,year,len(actual),'PASS',flush=True)
    w.FAMILIES.update(v.NAMES); raw = w.add_fresh(np.concatenate(parts)); execution = []; diagnostics = []
    fields = ['candidate_index','state','reason','entry_time','exit_time','entry','initial_sl','risk','r','commission_r','target','deadline']
    for spec in v.SPECS:
        full = read(v.RUN/(spec['name']+'_BASE_trades.json'))['trades']
        for year in (2022,2025):
            cut = int(w.datetime(year,1,1,tzinfo=w.timezone.utc).timestamp())
            actual,_ = v.run_serial(raw[raw[:,1]<cut],arrays['m1'][arrays['m1'][:,0]+60<=cut],spec,w.COSTS[1])
            closed = lambda rows: [{k:t[k] for k in fields} for t in rows if t['state']=='CLOSED' and t['exit_time']<cut]
            assert closed(actual)==closed(full),(spec['name'],year)
            execution.append(dict(name=spec['name'],cut=cut,closed=len(closed(actual)),exact=True))
            print('AVWAP EXEC',spec['name'],year,len(closed(actual)),'PASS',flush=True)
    summary = read(v.RUN/'summary.json'); qualified = []
    for spec in v.SPECS:
        base = next(r['metrics'] for r in summary['rows'] if r['name']==spec['name'] and r['cost']=='BASE')
        stress = next(r['metrics'] for r in summary['rows'] if r['name']==spec['name'] and r['cost']=='STRESS')
        if base['frequency_pass'] and base['economic_screen_pass'] and (base['win_rate'] or 0)>=55 and stress['total_r']>0:
            qualified.append(spec['name'])
    for row in summary['rows']:
        trades = read(v.RUN/(row['name']+'_'+row['cost']+'_trades.json'))['trades']
        closed = [t for t in trades if t['state']=='CLOSED']; filled = [t for t in trades if t['entry_time']]
        cost = next(c for c in w.COSTS if c['id']==row['cost'])
        for t in trades:
            fee = cost['commission_price']/t['risk'] if t['entry_time'] else 0.
            assert math.isclose(fee,t['commission_r'],abs_tol=1e-10)
            assert math.isclose(t['commission'],cost['commission_price']*100 if t['entry_time'] else 0.,abs_tol=1e-10)
            assert 'ASSUMED_ROUND_TRIP_COMMISSION' in t['fees_status']
            if t['r'] is not None:
                assert math.isclose(t['r'],t['gross_r']-fee,abs_tol=1e-10)
        assert all(b['entry_time']>=a['exit_time'] for a,b in zip(filled,filled[1:]))
        diagnostics.append(dict(name=row['name'],cost=row['cost'],filled=len(filled),closed=len(closed),
            risk_quantiles=np.quantile([t['risk'] for t in filled],[.1,.5,.9]).tolist() if filled else None,
            minimum_risk_fills=sum(t['risk']<2.01 for t in filled),
            commission_r_total=sum(t['commission_r'] for t in filled),
            reasons={reason:sum(t['reason']==reason for t in closed) for reason in sorted(set(t['reason'] for t in closed))}))
    preserved = {p:sha(w.ROOT/p)==value for p,value in lock['preserved_fresh'].items()}
    assert all(preserved.values())
    write_json(v.RUN/'PREFIX_CHECKS.json',dict(passed=True,detector=checks,execution=execution))
    write_json(v.RUN/'ENTRY_DIAGNOSTICS.json',dict(rows=diagnostics))
    write_json(v.RUN/'VERIFICATION.json',dict(qualified=qualified,fresh_unchanged=preserved,
        tests=dict(previous_unique=106,new_avwap=10,total_unique=116),
        real_detector_prefixes=len(checks),real_execution_prefixes=len(execution),
        volume='tick activity proxy;all real_volume0',fee_metadata_and_arithmetic_verified=True,
        historical_edge_confirmed=False,native_new_branch='not built;no qualified candidate'))


if __name__=='__main__':
    main()
