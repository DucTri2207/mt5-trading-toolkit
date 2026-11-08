"""Real-data prefix checks and preserved-artifact verification for v3 labs."""
import argparse
from datetime import datetime, timezone
import json

import numpy as np

from can_ho_tro_scalp_core import bars_matrix
from prepare_can_ho_tro_scalp import sha, write_json
import research_scalp_weekly_v3 as w
import research_scalp_microzones_v3 as m


def prefix(arrays,cut):
    return {k:a[a[:,0]+{'m1':60,'m5':300,'h1':3600,'d1':86400}[k]<=cut] for k,a in arrays.items()}


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--micro-only',action='store_true');args=parser.parse_args()
    z=np.load(w.BASE/'rates.npz');arrays={k:bars_matrix(z[k]) for k in z.files}
    if not args.micro_only:
        full=np.load(w.RUN/'detector_weekly.npz')['raw'];checks=[]
        for year in (2022,2024,2026):
            cut=int(datetime(year,1,1,tzinfo=timezone.utc).timestamp())
            got=w.detect(prefix(arrays,cut),end=cut)
            np.testing.assert_array_equal(got,full[full[:,1]<cut])
            checks.append(dict(cut=cut,rows=len(got),exact=True))
            print('WEEKLY PREFIX',year,len(got),'PASS',flush=True)
        write_json(w.RUN/'PREFIX_CHECKS.json',dict(passed=True,checks=checks))
    checks=[]
    for family,source_seconds,trigger_seconds in [(5,900,300),(6,900,60),(7,300,60)]:
        full=np.load(m.RUN/(m.NAMES[family]+'_candidates.npz'))['raw']
        for year in (2022,2025):
            cut=int(datetime(year,1,1,tzinfo=timezone.utc).timestamp())
            got=m.detect(prefix(arrays,cut),source_seconds,trigger_seconds,family,stop=cut)
            np.testing.assert_array_equal(got,full[full[:,1]<cut])
            assert np.all(got[:,12]<=got[:,13]) and np.all(got[:,39]<=got[:,0])
            checks.append(dict(source=m.NAMES[family],cut=cut,rows=len(got),exact=True))
            print('MICRO PREFIX',m.NAMES[family],year,len(got),'PASS',flush=True)
    write_json(m.RUN/'PREFIX_CHECKS.json',dict(passed=True,checks=checks))
    for run in (w.RUN,m.RUN):
        lock=json.loads((run/'EXPERIMENT_LOCK.json').read_text(encoding='utf-8'))
        preserved={p:sha(w.ROOT/p)==expected for p,expected in lock['preserved_fresh'].items()}
        assert all(preserved.values())
        summary=json.loads((run/'summary.json').read_text())
        qualified=[]
        for name in {row['name'] for row in summary['rows']}:
            base=next(row['metrics'] for row in summary['rows'] if row['name']==name and row['cost']=='BASE')
            stress=next(row['metrics'] for row in summary['rows'] if row['name']==name and row['cost']=='STRESS')
            if base['frequency_pass'] and base['economic_screen_pass'] and (base['win_rate'] or 0)>=55 and stress['total_r']>0:
                qualified.append(name)
        write_json(run/'VERIFICATION.json',dict(fresh_unchanged=preserved,qualified=qualified,
                   native_new_timeframes='not implemented; no native parity claim',
                   historical_edge_confirmed=False,
                   reason='Previously inspected data; frequency/economic/win-rate requirements still apply independently.'))


if __name__=='__main__':main()
