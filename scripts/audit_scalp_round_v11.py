"""Actual grid detectors/execution prefixes and complete after-cost qualification audit."""
import json
import math

import numpy as np

from can_ho_tro_scalp_core import bars_matrix
from prepare_can_ho_tro_scalp import sha, write_json
import research_scalp_round_v11 as v


def main():
    read = lambda p: json.loads(p.read_text(encoding='utf-8'))
    lock = read(v.RUN/'EXPERIMENT_LOCK.json'); data = np.load(v.w.BASE/'rates.npz')
    m1 = bars_matrix(data['m1']); m5 = bars_matrix(data['m5'])
    raw = np.load(v.RUN/'raw_candidates.npy'); checks = []; executions = []
    v.w.FAMILIES.update(v.NAMES)
    for year in (2022, 2025):
        cut = int(v.w.datetime(year, 1, 1, tzinfo=v.w.timezone.utc).timestamp())
        pm = m1[m1[:, 0]+60 <= cut]; p5 = m5[m5[:, 0]+300 <= cut]; parts = []
        for offset in (0., 3.7):
            actual = v.detect(pm, p5, offset, end=cut)
            expected = raw[(raw[:, 0]+60 < cut) & (raw[:, 36] >= (26 if offset else 24)) &
                           (raw[:, 36] <= (27 if offset else 25))]
            np.testing.assert_array_equal(actual, expected)
            parts.append(actual); checks.append(dict(year=year, offset=offset, rows=len(actual), exact=True))
        actual = np.concatenate(parts); actual = actual[np.lexsort((actual[:, 36], actual[:, 1]))]
        for spec in v.SPECS:
            full = read(v.RUN/(spec['name']+'_BASE_trades.json'))['trades']
            trades, _ = v.execution.run_serial(actual, pm, spec, v.w.COSTS[1])
            fields = ('state','reason','entry_time','exit_time','entry','initial_sl','risk','r','commission_r','target')
            closed = lambda rows: [{k: r[k] for k in fields} for r in rows if r['state'] == 'CLOSED' and r['exit_time'] < cut]
            assert closed(trades) == closed(full), (year, spec['name'])
            executions.append(dict(year=year, name=spec['name'], closed=len(closed(trades)), exact=True))
    summary = read(v.RUN/'summary.json'); qualified = []; fee_rows = 0
    for spec in v.SPECS:
        base = next(r['metrics'] for r in summary['rows'] if r['name'] == spec['name'] and r['cost'] == 'BASE')
        stress = next(r['metrics'] for r in summary['rows'] if r['name'] == spec['name'] and r['cost'] == 'STRESS')
        if (base['frequency_pass'] and base['economic_screen_pass'] and (base['win_rate'] or 0) >= 55
                and stress['economic_screen_pass']):
            qualified.append(spec['name'])
        for cost in v.w.COSTS:
            trades = read(v.RUN/(spec['name']+'_'+cost['id']+'_trades.json'))['trades']
            for r in trades:
                fee_rows += 1
                if r['entry_time']:
                    assert math.isclose(r['commission_r'], cost['commission_price']/r['risk'], abs_tol=1e-10)
                if r['r'] is not None:
                    assert math.isclose(r['r'], r['gross_r']-r['commission_r'], abs_tol=1e-10)
                assert 'ASSUMED_ROUND_TRIP_COMMISSION' in r['fees_status']
    preserved = {p: sha(v.w.ROOT/p) == h for p, h in lock['preserved_fresh'].items()}
    assert all(preserved.values())
    write_json(v.RUN/'VERIFICATION.json', dict(passed=True, detector_prefixes=checks,
        execution_prefixes=executions, fee_rows_audited=fee_rows, fresh_unchanged=preserved,
        qualified=qualified, historical_edge_confirmed=False))
    write_json(v.RUN/'CUMULATIVE_REGISTRY.json', dict(previous=dict(hypotheses=105, scenarios=401),
        new=dict(hypotheses=4, cost_scenarios=12), cumulative=dict(hypotheses=109, scenarios=413),
        tests=dict(previous_unique=134, new=6, total_unique=140),
        prefix=dict(detector=4, execution=8), qualified=qualified, goal_status='active;no qualifying edge'))
    print('PASS', len(checks), 'detector+', len(executions), 'execution prefixes;', fee_rows,
          'fee rows;qualified', qualified, flush=True)


if __name__ == '__main__':
    main()
