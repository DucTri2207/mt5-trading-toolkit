"""Audit actual-data prefixes, costs and target coverage for the intermarket assay."""
import json
import math

import numpy as np

from can_ho_tro_scalp_core import bars_matrix
from prepare_can_ho_tro_scalp import sha, write_json
import research_scalp_intermarket_v9 as v


def main():
    read = lambda p: json.loads(p.read_text(encoding='utf-8'))
    lock = read(v.RUN/'EXPERIMENT_LOCK.json'); data = np.load(v.w.BASE/'rates.npz')
    gold = bars_matrix(data['m5']); market = bars_matrix(data['m1'])
    saved = np.load(v.RUN/'features.npz'); full = saved['features']; basket = saved['basket']
    fx = np.load(v.RUN/'fx_rates.npz')
    raw = np.load(v.RUN/'raw_events.npy'); checks = []; executions = []
    for year in (2022, 2024, 2026):
        cut = int(v.w.datetime(year, 1, 1, tzinfo=v.w.timezone.utc).timestamp())
        keep = gold[:, 0]+300 <= cut
        truncated_fx = {symbol: fx[symbol][fx[symbol]['time']+300 <= cut] for symbol in v.SYMBOLS}
        pb, _ = v.align(gold[keep], truncated_fx)
        np.testing.assert_array_equal(pb, basket[keep])
        prefix = v.features(gold[keep], basket[keep])
        np.testing.assert_array_equal(prefix, full[keep])
        detected = v.events(prefix, end=cut)
        np.testing.assert_array_equal(detected, raw[raw[:, 0] < cut])
        checks.append(dict(cut=cut, feature_rows=len(prefix), events=len(detected),
                           truncated_fx_alignment_exact=True, exact=True))
        if year == 2024:
            continue
        for spec in v.SPECS:
            all_fills, _ = v.selected_fills(raw, market, spec)
            pm = market[market[:, 0] < cut]
            fills, _ = v.selected_fills(detected, pm, spec)
            # Future target availability cannot alter already chosen entries.
            key = lambda r: (r['signal_time'], r['entry_time'], r['direction'], r['unit_price'])
            expected = [key(r) for r in all_fills if r['entry_time'] < cut]
            assert [key(r) for r in fills] == expected, (spec['name'], year, 'entry schedule')
            closed = lambda rows: [r for r in rows if r['state'] == 'CLOSED' and r['exit_time'] < cut]
            assert closed(fills) == closed(all_fills), (spec['name'], year, 'targets')
            executions.append(dict(name=spec['name'], cut=cut, entries=len(fills), exact=True))
    summary = read(v.RUN/'summary.json'); rows_checked = 0; diagnostics = []
    for spec in v.SPECS:
        for cost in v.w.COSTS:
            label = spec['name']+'_'+cost['id']
            rows = read(v.RUN/(label+'_trades.json'))
            s = next(x for x in summary if x['name'] == spec['name'] and x['cost'] == cost['id'])
            assert s['filled'] == len(rows)
            for r in rows:
                rows_checked += 1
                assert r['signal_time']-r['calibration_last_end'] >= 900
                assert r['entry_time']-r['signal_time'] == spec['delay']*60
                assert r['fees_status'] == 'ASSUMED_'+cost['id']
                if r['state'] != 'CLOSED':
                    assert r['r'] is None
                    continue
                expected = r['direction']*(r['bid_exit']-r['bid_entry'])-cost['spread']-2*cost['slip']-cost['commission_price']
                assert math.isclose(r['net_price'], expected, abs_tol=1e-9)
                assert math.isclose(r['r'], expected/r['unit_price'], abs_tol=1e-9)
                assert math.isclose(r['r'], r['gross_r']-r['commission_r'], abs_tol=1e-9)
            assert all(b['entry_time'] >= a['entry_time']+spec['hold']*60 for a, b in zip(rows, rows[1:]))
            diagnostics.append(dict(label=label, entries=len(rows), closed=s['n'], missing_targets=s['censored']))
    gate = read(v.RUN/'BARRIER_GATE.json'); assert not gate['passed']
    preserved = {p: sha(v.ROOT/p) == h for p, h in lock['preserved_fresh'].items()}
    assert all(preserved.values())
    write_json(v.RUN/'VERIFICATION.json', dict(passed=True, feature_and_event_prefixes=checks,
        entry_and_target_prefixes=executions, trade_rows_fee_audited=rows_checked,
        coverage=diagnostics, fresh_unchanged=preserved, qualified=[],
        no_new_native_or_broker_orders=True, barrier_lab_opened=False,
        implementation_notes=['Initial adapter used cost.name instead of existing cost.id; corrected before any scenario completed; no signal/economic definition changed.',
            'A missing future target is censored and still consumes entry caps and scheduled occupancy. Ex-post target availability never reallocates an entry to a later signal.',
            'Fixed-hold SU is a normalization unit,not initial-risk R. These assays have no SL and are not deployable.']))
    write_json(v.RUN/'CUMULATIVE_REGISTRY.json', dict(previous=dict(hypotheses=90, scenarios=344),
        new=dict(assay_hypotheses=12, fee_scenarios=36, nonselectable_same_event_control_scenarios=12,
                 conditional_barrier_hypotheses=0, scenarios=48),
        cumulative=dict(hypotheses=102, scenarios=392),
        tests=dict(previous_unique=120, new=9, total_unique=129),
        prefix=dict(features_and_events=3, entry_and_targets=24), qualified=[],
        goal_status='active; no qualifying edge',
        note='v9 statistical family105 conservatively reserves3 unopened barrier hypotheses. Actual cumulative opened hypotheses102. Earlier untracked choices remain a limitation.'))
    print('PASS', len(checks), 'feature/event prefixes,', len(executions), 'execution prefixes,', rows_checked, 'fee rows;Fresh unchanged', flush=True)


if __name__ == '__main__':
    main()
