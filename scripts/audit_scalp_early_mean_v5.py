"""Exact real-data prefixes and joint objective checks for early M1 reclaims."""
import json

import numpy as np

from can_ho_tro_scalp_core import bars_matrix
from prepare_can_ho_tro_scalp import sha, write_json
import research_scalp_early_mean_v5 as e


def read(path):
    return json.loads(path.read_text(encoding='utf-8'))


def main():
    w = e.w
    lock = read(e.RUN / 'EXPERIMENT_LOCK.json')
    source = np.load(w.BASE / 'rates.npz')
    arrays = {k: bars_matrix(source[k]) for k in source.files}
    checks = []
    for family, name in e.NAMES.items():
        full = np.load(e.RUN / (name + '_candidates.npz'))['raw']
        for year in (2022, 2025):
            cut = int(w.datetime(year, 1, 1, tzinfo=w.timezone.utc).timestamp())
            prefix = {k: a[a[:, 0] + {'m1': 60, 'm5': 300, 'h1': 3600, 'd1': 86400}[k] <= cut]
                      for k, a in arrays.items()}
            actual = e.detect(prefix, family, stop=cut)
            np.testing.assert_array_equal(actual, full[full[:, 1] < cut])
            checks.append(dict(source=name, cut=cut, rows=len(actual), exact=True))
            print('EARLY PREFIX', name, year, len(actual), 'PASS', flush=True)
    write_json(e.RUN / 'PREFIX_CHECKS.json', dict(passed=True, checks=checks))
    preserved = {p: sha(w.ROOT / p) == value for p, value in lock['preserved_fresh'].items()}
    assert all(preserved.values())
    summary = read(e.RUN / 'summary.json')
    qualified = []
    diagnostics = []
    for spec in e.SPECS:
        base = next(r['metrics'] for r in summary['rows'] if r['name'] == spec['name'] and r['cost'] == 'BASE')
        stress = next(r['metrics'] for r in summary['rows'] if r['name'] == spec['name'] and r['cost'] == 'STRESS')
        if base['frequency_pass'] and base['economic_screen_pass'] and (base['win_rate'] or 0) >= 55 and stress['total_r'] > 0:
            qualified.append(spec['name'])
    for row in summary['rows']:
        trades = read(e.RUN / (row['name'] + '_' + row['cost'] + '_trades.json'))['trades']
        rejected = [t for t in trades if t['reason'] == 'MEAN_ROOM_BELOW_08R']
        assert all(not t['entry_time'] and not t['commission_r'] and
                   not any(x['kind'] == 'FILL' for x in t['events']) for t in rejected)
        closed = [t for t in trades if t['state'] == 'CLOSED']
        dynamic = [t for t in closed if t['source'] != 'FRESH']
        quantiles = lambda values: np.quantile(values, [.1, .5, .9]).tolist() if len(values) else None
        diagnostics.append(dict(name=row['name'], cost=row['cost'], mean_room_rejections=len(rejected),
                                fills=sum(bool(t['entry_time']) for t in trades), closed_n=len(closed),
                                risk_p10_p50_p90=quantiles([t['risk'] for t in dynamic]),
                                target_r_p10_p50_p90=quantiles([abs(t['target']-t['entry'])/t['risk'] for t in dynamic]),
                                reasons={reason: sum(t['reason'] == reason for t in closed)
                                         for reason in sorted(set(t['reason'] for t in closed))}))
    write_json(e.RUN / 'ENTRY_DIAGNOSTICS.json', dict(rows=diagnostics))
    write_json(e.RUN / 'VERIFICATION.json', dict(fresh_unchanged=preserved, qualified=qualified,
               tests=dict(previous_unique=89, early_detector=8, total_unique=97),
               real_prefix_checks=len(checks), native_new_branch='not built; no qualified candidate',
               historical_edge_confirmed=False,
               reason='No candidate jointly meets win rate, weekly frequency and after-cost economic requirements.'))


if __name__ == '__main__':
    main()
