"""Detector and execution prefixes for failed-reclaim continuation research."""
import json

import numpy as np

from can_ho_tro_scalp_core import bars_matrix
from prepare_can_ho_tro_scalp import sha, write_json
import research_scalp_failed_reclaim_v6 as f


def read(path):
    return json.loads(path.read_text(encoding='utf-8'))


def main():
    w = f.w
    lock = read(f.RUN/'EXPERIMENT_LOCK.json')
    source = np.load(w.BASE/'rates.npz'); arrays = {k: bars_matrix(source[k]) for k in source.files}
    checks = []; parts = []
    for family, name in f.NAMES.items():
        full = np.load(f.RUN/(name+'_candidates.npz'))['raw']; parts.append(full)
        assert np.all(full[:, 1] <= full[:, 12]+900)
        for year in (2022, 2025):
            cut = int(w.datetime(year, 1, 1, tzinfo=w.timezone.utc).timestamp())
            prefix = {k: a[a[:, 0]+{'m1': 60, 'm5': 300, 'h1': 3600, 'd1': 86400}[k] <= cut]
                      for k, a in arrays.items()}
            actual = f.detect(prefix, family, stop=cut)
            np.testing.assert_array_equal(actual, full[full[:, 1] < cut])
            checks.append(dict(source=name, cut=cut, rows=len(actual), exact=True))
            print('FAILED PREFIX', name, year, len(actual), 'PASS', flush=True)
    f.w.FAMILIES.update(f.NAMES)
    raw = w.add_fresh(np.concatenate(parts)); execution = []
    fields = ['candidate_index', 'state', 'reason', 'entry_time', 'exit_time', 'entry',
              'initial_sl', 'risk', 'r', 'commission_r', 'target', 'deadline']
    for spec in f.SPECS:
        full = read(f.RUN/(spec['name']+'_BASE_trades.json'))['trades']
        for year in (2022, 2025):
            cut = int(w.datetime(year, 1, 1, tzinfo=w.timezone.utc).timestamp())
            actual, _ = f.run_serial(raw[raw[:, 1] < cut], arrays['m1'][arrays['m1'][:, 0]+60 <= cut], spec, w.COSTS[1])
            closed = lambda rows: [{k: t[k] for k in fields} for t in rows if t['state'] == 'CLOSED' and t['exit_time'] < cut]
            assert closed(actual) == closed(full), (spec['name'], year)
            execution.append(dict(name=spec['name'], cut=cut, closed=len(closed(actual)), exact=True))
            print('EXEC PREFIX', spec['name'], year, len(closed(actual)), 'PASS', flush=True)
    write_json(f.RUN/'PREFIX_CHECKS.json', dict(passed=True, detector=checks, execution=execution))
    preserved = {p: sha(w.ROOT/p) == value for p, value in lock['preserved_fresh'].items()}
    assert all(preserved.values())
    summary = read(f.RUN/'summary.json'); qualified = []
    for spec in f.SPECS:
        base = next(r['metrics'] for r in summary['rows'] if r['name'] == spec['name'] and r['cost'] == 'BASE')
        stress = next(r['metrics'] for r in summary['rows'] if r['name'] == spec['name'] and r['cost'] == 'STRESS')
        if base['frequency_pass'] and base['economic_screen_pass'] and (base['win_rate'] or 0) >= 55 and stress['total_r'] > 0:
            qualified.append(spec['name'])
    diagnostics = []
    for row in summary['rows']:
        trades = read(f.RUN/(row['name']+'_'+row['cost']+'_trades.json'))['trades']
        closed = [t for t in trades if t['state'] == 'CLOSED']
        filled = [t for t in trades if t['entry_time']]
        assert all(b['entry_time'] >= a['exit_time'] for a, b in zip(filled, filled[1:]))
        diagnostics.append(dict(name=row['name'], cost=row['cost'],
                                closed=len(closed), filled=len(filled),
                                reasons={reason: sum(t['reason'] == reason for t in closed)
                                         for reason in sorted(set(t['reason'] for t in closed))},
                                censored=sum(t['state'].startswith('CENSORED') for t in trades)))
    write_json(f.RUN/'ENTRY_DIAGNOSTICS.json', dict(rows=diagnostics))
    write_json(f.RUN/'VERIFICATION.json', dict(fresh_unchanged=preserved, qualified=qualified,
               tests=dict(previous_unique=97, new_failed_reclaim=9, total_unique=106),
               real_detector_prefix_checks=len(checks), real_execution_prefix_checks=len(execution),
               native_new_branch='not built; no qualified candidate', historical_edge_confirmed=False,
               reason='No candidate jointly meets win rate, weekly frequency and BASE/STRESS economic requirements.'))


if __name__ == '__main__':
    main()
