"""Causal USD/gold lead-lag assays. Fixed time exits, not a deployable SL/TP bot."""
from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone
import json

import numpy as np
from numba import njit

from can_ho_tro_scalp_core import bars_matrix, metaquotes_atr
from collect_scalp_intermarket_v9 import ROOT, RUN, SYMBOLS, WEIGHTS
from prepare_can_ho_tro_scalp import sha, write_json
import research_scalp_weekly_v3 as w

NAMES = ('USD_IMPULSE', 'USD_CATCHUP', 'GOLD_MOMENTUM_CONTROL')
PRIOR_REGISTRY = ROOT/'reports/can_ho_tro_scalp/20261101_anchor_stop_v8/CUMULATIVE_REGISTRY.json'
SPECS = [dict(name=f'{name}_H{hold}_D{delay}', family=f, hold=hold, delay=delay)
         for f, name in enumerate(NAMES) for hold in (15, 60) for delay in (1, 5)]


def freeze():
    protocol = json.loads((RUN/'ASSAY_PROTOCOL.json').read_text(encoding='utf-8'))
    manifest = json.loads((RUN/'FX_DATA_MANIFEST.json').read_text(encoding='utf-8'))
    assert sha(RUN/'fx_rates.npz') == manifest['data_sha256']
    assert sha(RUN/'ASSAY_PROTOCOL.json') == manifest['protocol_sha256']
    assert all(x['exact_ohlc_time'] for x in manifest['gold_feed_compatibility'])
    lock = dict(version='intermarket_v9_assays', protocol=protocol,
        protocol_sha256=sha(RUN/'ASSAY_PROTOCOL.json'),
        fx_sha256=sha(RUN/'fx_rates.npz'), gold_sha256=sha(w.BASE/'rates.npz'),
        prior_registry_sha256=sha(PRIOR_REGISTRY), hypotheses=SPECS, costs=w.COSTS,
        diagnostic_scenarios=12, statistical_screen=dict(family_size=105, prior_hypotheses=90),
        bootstrap_seed=20261110, bootstrap_resamples=100000,
        preserved_fresh={p: sha(ROOT/p) for p in w.FRESH_PATHS},
        unit='SU = max(2,1.5*known M5 ATR14) price units. Fixed-time assays have no stop: SU is not bounded-risk R.',
        causal_dates='Retrospective; no pristine holdout. 2021/2026 partial,2022-2025 full.',
        status='12 assays opened;3 conditional barrier hypotheses not opened unless gate passes')
    path = RUN/'EXPERIMENT_LOCK.json'
    if path.exists():
        assert json.loads(path.read_text(encoding='utf-8')) == lock, 'Frozen definitions changed'
    else:
        write_json(path, lock)
    return lock


def align(gold, fx):
    times = gold[:, 0].astype(np.int64)
    close = np.full((len(gold), 6), np.nan)
    report = {}
    for k, symbol in enumerate(SYMBOLS):
        a = fx[symbol]; positions = np.searchsorted(a['time'], times)
        exists = positions < len(a)
        exists[exists] &= a['time'][positions[exists]] == times[exists]
        close[exists, k] = a['close'][positions[exists]]
        report[symbol] = dict(matched=int(exists.sum()), missing_on_gold=int((~exists).sum()))
    complete = np.all(np.isfinite(close) & (close > 0), axis=1)
    basket = np.full(len(gold), np.nan)
    basket[complete] = np.log(close[complete]) @ np.asarray(WEIGHTS)
    report['all_six'] = dict(matched=int(complete.sum()), missing_on_gold=int((~complete).sum()))
    return basket, report


@njit(cache=True)
def features(gold, basket, minimum=5000, lookback=60*86400):
    """Row i only uses bars closed by gold[i].time+300; calibration ends15m earlier.

    Columns: known,USD15,gold15,USDz,goldz,beta,residualZ,ATR,count,trainLast,
    residual,known15minLow,known15minHigh,M5index.
    """
    n = len(gold); times = gold[:, 0]+300
    x = np.zeros(n); y = np.zeros(n); valid = np.zeros(n, np.bool_)
    sums = np.zeros((n+1, 6))
    atr = metaquotes_atr(gold)
    for i in range(n):
        good = i >= 3
        if good:
            for j in range(i-3, i+1):
                if not np.isfinite(basket[j]) or (j > i-3 and times[j]-times[j-1] != 300):
                    good = False
        if good:
            x[i] = basket[i]-basket[i-3]; y[i] = np.log(gold[i, 4]/gold[i-3, 4]); valid[i] = True
        sums[i+1] = sums[i]
        if good:
            sums[i+1, 0] += 1; sums[i+1, 1] += x[i]; sums[i+1, 2] += y[i]
            sums[i+1, 3] += x[i]*x[i]; sums[i+1, 4] += y[i]*y[i]; sums[i+1, 5] += x[i]*y[i]
    out = np.full((n, 14), np.nan)
    left = 0
    for i in range(n):
        if not valid[i] or atr[i] <= 0:
            continue
        while left < i and times[left] < times[i]-lookback:
            left += 1
        right = np.searchsorted(times, times[i]-900, side='right')
        a = sums[right]-sums[left]; count = a[0]
        if count < minimum:
            continue
        mx = a[1]/count; my = a[2]/count
        vx = a[3]/count-mx*mx; vy = a[4]/count-my*my; cov = a[5]/count-mx*my
        if vx <= 1e-20 or vy <= 1e-20:
            continue
        beta = cov/vx; vr = max(1e-20, vy-cov*cov/vx)
        residual = y[i]-(my+beta*(x[i]-mx))
        out[i] = np.array([times[i], x[i], y[i], (x[i]-mx)/np.sqrt(vx),
            (y[i]-my)/np.sqrt(vy), beta, residual/np.sqrt(vr), atr[i], count,
            times[right-1], residual, np.min(gold[i-2:i+1, 3]),
            np.max(gold[i-2:i+1, 2]), i])
    return out


@njit(cache=True)
def events(feature, start=w.START, end=w.END):
    rows = []; active = np.zeros(3, np.bool_); last = np.full(3, -1e12)
    previous = 0.
    for r in feature:
        if not np.isfinite(r[0]):
            active[:] = False; previous = 0.; continue
        at = r[0]
        if previous and at-previous != 300:
            active[:] = False
        previous = at
        impulse = abs(r[3]) >= 2
        catchup = impulse and r[5] < 0 and abs(r[6]) >= 1 and r[3]*r[6] > 0
        momentum = abs(r[4]) >= 2
        eligible = (impulse, catchup, momentum)
        for f in range(3):
            crossing = eligible[f] and not active[f]
            active[f] = eligible[f]
            if not crossing or at-last[f] < 1800:
                continue
            # Consume first crossings outside the trading hours too.
            last[f] = at
            hour = int((at-300)//3600) % 24
            if not start <= at < end or not 8 <= hour < 19:
                continue
            d = (1 if r[4] > 0 else -1) if f == 2 else (-1 if r[3] > 0 else 1)
            out = np.empty(16); out[:14] = r; out[14] = f; out[15] = d; rows.append(out)
    result = np.empty((len(rows), 16))
    for i in range(len(rows)):
        result[i] = rows[i]
    return result


def selected_fills(raw, market, spec, end=w.END):
    """Enter on known quotes. Unobserved/gappy future targets consume entry caps too."""
    rows = []; busy = 0; days = Counter(); weeks = Counter(); rejects = Counter()
    times = market[:, 0].astype(np.int64)
    gaps = np.r_[0, np.cumsum(np.diff(times) != 60)]
    for index, c in enumerate(raw):
        if int(c[14]) != spec['family']:
            continue
        enter = int(c[0])+spec['delay']*60; leave = enter+spec['hold']*60
        day = enter//86400; week = w.week_key(enter)
        if enter < busy:
            rejects['BUSY'] += 1; continue
        if days[day] >= 2 or weeks[week] >= 10:
            rejects['CAP'] += 1; continue
        l = np.searchsorted(times, enter); r = np.searchsorted(times, leave)
        if enter >= end or l >= len(times) or times[l] != enter:
            rejects['NO_ENTRY_QUOTE'] += 1; continue
        days[day] += 1; weeks[week] += 1; busy = leave
        unit = max(2., 1.5*c[7]); d = int(c[15])
        complete = leave < end and r < len(times) and times[r] == leave and gaps[r] == gaps[l]
        state = 'CLOSED' if complete else 'CENSORED_FILLED'
        reason = 'FIXED_TIME_ASSAY' if complete else 'MISSING_EXACT_TARGET_PATH'
        if not complete:
            rejects['TARGET_UNOBSERVED_BUT_ENTRY_COUNTED'] += 1
        rows.append(dict(index=index, signal_time=int(c[0]), source=NAMES[spec['family']],
            entry_time=enter, exit_time=leave if complete else 0, bid_entry=float(market[l, 1]),
            bid_exit=float(market[r, 1]) if complete else None,
            direction=d, gold_control_direction=1 if c[2] >= 0 else -1,
            unit_price=float(unit), usd_z=float(c[3]), gold_z=float(c[4]), beta=float(c[5]),
            residual_z=float(c[6]), calibration_count=int(c[8]), calibration_last_end=int(c[9]),
            state=state, reason=reason, ambiguous_minutes=0, data_gaps=0 if complete else 1))
    return rows, dict(rejects)


def with_cost(fills, cost, control=False):
    result = []
    for fill in fills:
        r = dict(fill)
        d = r['gold_control_direction'] if control else r['direction']
        r['direction'] = d
        r['entry'] = r['bid_entry']+(cost['spread']+cost['slip'] if d > 0 else -cost['slip'])
        r['commission_r'] = cost['commission_price']/r['unit_price']
        if r['state'] == 'CLOSED':
            r['exit'] = r['bid_exit']+(-cost['slip'] if d > 0 else cost['spread']+cost['slip'])
            r['gross_price'] = d*(r['bid_exit']-r['bid_entry'])
            r['execution_net_price'] = d*(r['exit']-r['entry'])
            r['net_price'] = r['execution_net_price']-cost['commission_price']
            r['r'] = r['net_price']/r['unit_price']
            r['gross_r'] = r['execution_net_price']/r['unit_price']
        else:
            r.update(exit=None, gross_price=None, execution_net_price=None, net_price=None, r=None, gross_r=None)
        r['fees_status'] = 'ASSUMED_'+cost['id']; r['commission_price'] = cost['commission_price']
        r['spread_price'] = cost['spread']; r['slip_each_side_price'] = cost['slip']
        r['unit_label'] = 'SU:not bounded risk R;no SL in fixed-hold assay'
        result.append(r)
    return result


def paired_control(rows, control, market, lock):
    # Exact same entry/exit timestamps: measure value of direction rather than different samples.
    paired = []
    for a, b in zip(rows, control):
        assert (a['entry_time'], a['exit_time']) == (b['entry_time'], b['exit_time'])
        r = dict(a)
        if r['r'] is not None:
            r['r'] -= b['r']
        paired.append(r)
    return w.summarize(paired, market, lock)


def associations(feature, market):
    times = market[:, 0].astype(np.int64)
    gaps = np.r_[0, np.cumsum(np.diff(times) != 60)]
    valid = np.isfinite(feature[:, 0])
    f = feature[valid]
    hours = ((f[:, 0]-300)//3600).astype(np.int64) % 24
    f = f[(f[:, 0] >= w.START) & (f[:, 0] < w.END) & (hours >= 8) & (hours < 19)]
    report = dict(n_calibrated=len(f), contemporaneous_USD15_gold15=float(np.corrcoef(f[:, 1], f[:, 2])[0, 1]),
                  caveat='descriptive full-sample correlations only; not selection or significance tests', future={})
    for hold in (15, 60):
        for delay in (1, 5):
            enter = f[:, 0]+delay*60; leave = enter+hold*60
            l = np.searchsorted(times, enter); r = np.searchsorted(times, leave)
            ok = (l < len(times)) & (r < len(times)) & (leave < w.END)
            ix = np.where(ok)[0]; il = l[ok]; ir = r[ok]
            exact = (times[il] == enter[ok]) & (times[ir] == leave[ok]) & (gaps[ir] == gaps[il])
            ix = ix[exact]; il = il[exact]; ir = ir[exact]
            target = np.log(market[ir, 1]/market[il, 1]); q = f[ix]
            report['future'][f'H{hold}_D{delay}'] = dict(n=len(target),
                usd15_vs_future_gold=float(np.corrcoef(q[:, 1], target)[0, 1]),
                residual_vs_future_gold=float(np.corrcoef(q[:, 10], target)[0, 1]),
                gold15_vs_future_gold=float(np.corrcoef(q[:, 2], target)[0, 1]))
    return report


def main():
    lock = freeze(); data = np.load(w.BASE/'rates.npz'); fx = np.load(RUN/'fx_rates.npz')
    gold = bars_matrix(data['m5']); market = bars_matrix(data['m1'])
    basket, report = align(gold, fx); write_json(RUN/'ALIGNMENT.json', report)
    f = features(gold, basket); raw = events(f)
    np.savez_compressed(RUN/'features.npz', features=f, basket=basket)
    np.save(RUN/'raw_events.npy', raw)
    write_json(RUN/'ASSOCIATIONS.json', associations(f, market))
    summaries = []; metrics_by_name = {}; controls = []
    for spec in SPECS:
        fills, rejects = selected_fills(raw, market, spec)
        for cost in w.COSTS:
            rows = with_cost(fills, cost); summary = w.summarize(rows, market, lock)
            summary.update(name=spec['name'], cost=cost['id'], rejects=rejects,
                           unit=lock['unit'], sources={NAMES[spec['family']]: w.metrics(rows)})
            write_json(RUN/(spec['name']+'_'+cost['id']+'_trades.json'), rows)
            summaries.append(summary); metrics_by_name[(spec['name'], cost['id'])] = summary
            print(spec['name'], cost['id'], summary['n'], round(summary['win_rate'] or 0, 2),
                  round(summary['total_r'], 2), 'SU', flush=True)
            if spec['family'] == 0:
                control = with_cost(fills, cost, control=True)
                pair = paired_control(rows, control, market, lock)
                diagnostic = dict(name=spec['name']+'_SAME_EVENT_GOLD_DIRECTION', cost=cost['id'],
                    nonselectable=True, control=w.summarize(control, market, lock),
                    paired_usd_minus_gold=pair,
                    attribution='Same selected timestamps, price cost and units. P&L difference comes only from signal direction; descriptive retrospective comparison.')
                controls.append(diagnostic)
                write_json(RUN/(diagnostic['name']+'_'+cost['id']+'_trades.json'), control)
    gates = []
    for spec in SPECS:
        if spec['family'] == 2:
            continue
        base = metrics_by_name[(spec['name'], 'BASE')]; stress = metrics_by_name[(spec['name'], 'STRESS')]
        other_name = spec['name'].rsplit('_D', 1)[0]+'_D'+str(5 if spec['delay'] == 1 else 1)
        other = metrics_by_name[(other_name, 'BASE')]
        other_stress = metrics_by_name[(other_name, 'STRESS')]
        passes = (base['frequency_pass'] and base['economic_screen_pass'] and stress['economic_screen_pass']
                  and other['total_r'] > 0 and other_stress['total_r'] > 0)
        gates.append(dict(name=spec['name'], passed=bool(passes),
            base_net_positive=base['total_r'] > 0, stress_net_positive=stress['total_r'] > 0,
            base_screen=base['economic_screen_pass'], stress_screen=stress['economic_screen_pass'],
            frequency=base['frequency_pass'], other_delay_net_positive=other['total_r'] > 0,
            other_delay_stress_net_positive=other_stress['total_r'] > 0))
    write_json(RUN/'summary.json', summaries)
    write_json(RUN/'SAME_EVENT_CONTROL.json', controls)
    write_json(RUN/'BARRIER_GATE.json', dict(passed=any(x['passed'] for x in gates), rows=gates,
        conditional_barrier_hypotheses_opened=0, caveat='Do not tune thresholds, latency or horizon after failed gate.'))
    assert all(sha(ROOT/p) == expected for p, expected in lock['preserved_fresh'].items())
    write_json(RUN/'SOURCE_MANIFEST.json', dict(fresh_unchanged=True,
        files={p: sha(ROOT/p) for p in ('scripts/collect_scalp_intermarket_v9.py',
            'scripts/research_scalp_intermarket_v9.py', 'scripts/research_scalp_weekly_v3.py')},
        protocol_sha256=lock['protocol_sha256']))
    print('DONE 36 assay fee scenarios+12 nonselectable paired controls;gate', any(x['passed'] for x in gates), flush=True)


if __name__ == '__main__':
    main()
