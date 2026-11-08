"""Actual-data monthly training cutoffs, detector prefixes and execution prefixes."""
import json
import math

import numpy as np

from can_ho_tro_scalp_core import bars_matrix
from prepare_can_ho_tro_scalp import sha, write_json
import research_scalp_seasonal_v10 as v


def main():
    read = lambda p: json.loads(p.read_text(encoding='utf-8'))
    lock = read(v.RUN/'EXPERIMENT_LOCK.json'); data = np.load(v.w.BASE/'rates.npz')
    gold = bars_matrix(data['m5']); market = bars_matrix(data['m1'])
    raw = np.load(v.RUN/'raw_candidates.npy'); checks = []; executions = []
    v.w.FAMILIES.update(v.NAMES)
    for year in (2022, 2025):
        cut = int(v.w.datetime(year, 1, 1, tzinfo=v.w.timezone.utc).timestamp())
        pg = gold[gold[:, 0]+300 <= cut]; pm = market[market[:, 0]+60 <= cut]
        opp = v.opportunities(pg); y, end = v.labels(opp, pm)
        actual, models = v.candidates(opp, y, end, end=cut)
        np.testing.assert_array_equal(actual, raw[raw[:, 37] < cut])
        checks.append(dict(cut=cut, candidates=len(actual), exact=True))
        for spec in v.SPECS:
            full = read(v.RUN/(spec['name']+'_BASE_trades.json'))['trades']
            rows, _ = v.execution.run_serial(actual, pm, spec, v.w.COSTS[1])
            fields = ('state', 'reason', 'entry_time', 'exit_time', 'entry', 'initial_sl', 'risk', 'r', 'commission_r', 'target')
            closed = lambda rows: [{k: r[k] for k in fields} for r in rows if r['state'] == 'CLOSED' and r['exit_time'] < cut]
            assert closed(rows) == closed(full), (spec['name'], year)
            executions.append(dict(name=spec['name'], cut=cut, closed=len(closed(rows)), exact=True))
    model_records = read(v.RUN/'MONTHLY_MODELS.json')
    for m in model_records:
        if m['status'] == 'FITTED':
            assert m['last_train_label_end'] < m['month']-7200
            assert m['first_train_signal'] >= m['month']-365*86400
    qualified = []; summary = read(v.RUN/'summary.json'); fee_rows = 0
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
    write_json(v.RUN/'VERIFICATION.json', dict(passed=True, monthly_model_provenance=len(model_records),
        detector_prefixes=checks, execution_prefixes=executions, fee_rows_audited=fee_rows,
        fresh_unchanged=preserved, qualified=qualified, historical_edge_confirmed=False))
    write_json(v.RUN/'CUMULATIVE_REGISTRY.json', dict(previous=dict(hypotheses=102, scenarios=392),
        new=dict(hypotheses=3, cost_scenarios=9), cumulative=dict(hypotheses=105, scenarios=401),
        tests=dict(previous_unique=129, new=5, total_unique=134),
        prefix=dict(detector=2, execution=6), qualified=qualified, goal_status='active;no qualifying edge'))
    print('PASS', len(model_records), 'past-only models;', len(checks), 'detector+', len(executions),
          'execution prefixes;', fee_rows, 'fee rows;qualified', qualified, flush=True)


if __name__ == '__main__':
    main()
