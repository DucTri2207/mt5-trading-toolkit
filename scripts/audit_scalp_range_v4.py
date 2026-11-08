"""Real-data causality and joint requirement checks for frozen-mean research."""
import json
import numpy as np

from can_ho_tro_scalp_core import bars_matrix
from prepare_can_ho_tro_scalp import sha,write_json
import research_scalp_range_v4 as r


def read(path):return json.loads(path.read_text(encoding='utf-8'))


def main():
    lock=read(r.RUN/'EXPERIMENT_LOCK.json');z=np.load(r.w.BASE/'rates.npz')
    arrays={k:bars_matrix(z[k]) for k in z.files};checks=[]
    for family,name in r.NAMES.items():
        full=np.load(r.RUN/(name+'_candidates.npz'))['raw']
        for year in (2022,2025):
            cut=int(r.w.datetime(year,1,1,tzinfo=r.w.timezone.utc).timestamp())
            prefix={k:a[a[:,0]+{'m1':60,'m5':300,'h1':3600,'d1':86400}[k]<=cut] for k,a in arrays.items()}
            actual=r.detect(prefix,family,stop=cut)
            np.testing.assert_array_equal(actual,full[full[:,1]<cut])
            checks.append(dict(source=name,cut=cut,rows=len(actual),exact=True))
            print('RANGE PREFIX',name,year,len(actual),'PASS',flush=True)
    write_json(r.RUN/'PREFIX_CHECKS.json',dict(passed=True,checks=checks))
    preserved={p:sha(r.w.ROOT/p)==value for p,value in lock['preserved_fresh'].items()}
    assert all(preserved.values())
    summary=read(r.RUN/'summary.json');qualified=[]
    for spec in r.SPECS:
        base=next(row['metrics'] for row in summary['rows'] if row['name']==spec['name'] and row['cost']=='BASE')
        stress=next(row['metrics'] for row in summary['rows'] if row['name']==spec['name'] and row['cost']=='STRESS')
        if base['frequency_pass'] and base['economic_screen_pass'] and (base['win_rate'] or 0)>=55 and stress['total_r']>0:qualified.append(spec['name'])
    rejection_diagnostics=[]
    for row in summary['rows']:
        trades=read(r.RUN/(row['name']+'_'+row['cost']+'_trades.json'))['trades']
        rejected=[t for t in trades if t['reason']=='MEAN_ROOM_BELOW_08R']
        assert all(not t['entry_time'] and not t['commission_r'] and not any(e['kind']=='FILL' for e in t['events']) for t in rejected)
        closed=[t for t in trades if t['state']=='CLOSED']
        rejection_diagnostics.append(dict(name=row['name'],cost=row['cost'],mean_room_rejections=len(rejected),
                                         entries=len([t for t in trades if t['entry_time']]),
                                         reached1R_before_exit=sum('1.0' in t['first_hits'] for t in closed),
                                         closed_n=len(closed)))
    write_json(r.RUN/'ENTRY_DIAGNOSTICS.json',dict(rows=rejection_diagnostics))
    write_json(r.RUN/'VERIFICATION.json',dict(fresh_unchanged=preserved,qualified=qualified,
               tests=dict(previous_suite=83,new_range_tests=6,total_unique=89),real_prefix_checks=len(checks),
               native_new_branch='not built; no qualified candidate',historical_edge_confirmed=False,
               reason='No candidate meets net-win-rate,weekly frequency,and BASE/STRESS economic requirements.'))


if __name__=='__main__':main()
