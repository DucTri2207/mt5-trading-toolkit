"""Past-only monthly models of intraday drift and time-varying return response."""
from __future__ import annotations

from datetime import datetime, timezone
import json

import numpy as np

from can_ho_tro_scalp_core import bars_matrix, metaquotes_atr
from prepare_can_ho_tro_scalp import sha, write_json
import research_scalp_weekly_v3 as w
import research_scalp_avwap_v7 as execution

RUN = w.ROOT/'reports/can_ho_tro_scalp/20261101_seasonal_v10'
NAMES = {21: 'SEASONAL_DRIFT', 22: 'SEASONAL_RESPONSE', 23: 'GLOBAL_RESPONSE_CONTROL'}
SPECS = [dict(name=name, sources=[f]) for f, name in NAMES.items()]


def freeze():
    RUN.mkdir(parents=True, exist_ok=True)
    lock = dict(version='seasonal_monthly_v10', hypotheses=SPECS, costs=w.COSTS,
        start=w.START, end_exclusive=w.END, data_sha256=sha(w.BASE/'rates.npz'),
        previous_registry_sha256=sha(w.ROOT/'reports/can_ho_tro_scalp/20261101_intermarket_v9/CUMULATIVE_REGISTRY.json'),
        preserved_fresh={p: sha(w.ROOT/p) for p in w.FRESH_PATHS},
        mechanism='Persistent variation in participant activity over the feed day may produce conditional drift and time-varying continuation/reversal. Learn that relationship from past observations rather than specify chart patterns.',
        definitions=dict(
            opportunities='Every closed M5 ending on half-hour,02:00<=known feed hour<18:00. Exact7 contiguous M5 bars for current30-minute close change; current ATR14 known at signal. No named geographical session or assumption of verified DST.',
            features='Unit=max(2,1.5*known M5 rolling ATR14). Lag30=(current close-close6bars earlier)/unit,clipped[-5,5]. Periodic basis[1,sin(2pi*t/24h),cos(...),sin(4pi*t/24h),cos(...)].',
            models='SEASONAL_DRIFT:5 periodic terms;SEASONAL_RESPONSE:5 periodic terms plus their5 interactions with lag30;GLOBAL_RESPONSE_CONTROL:[1,lag30]. No USD/AVWAP/H1 filter.',
            label='Gold Bid open(signal+60s) to Bid open(entry+120min),divided by known unit. Require exact endpoints and every intervening M1 timestamp for TRAINING labels only. Missing future targets cannot affect test candidate selection.',
            training='At each calendar-month start,use previous365calendar days of opportunities whose target exit<month start-120min;min2000 samples,120 distinct feed days,26 feed ISO weeks. No use of candidate barrier outcome labels. Cache entire monthly provenance.',
            estimator='Ridge regression:standardize all nonintercept columns with training means/std;unpenalized intercept;fixed sum-squares ridge penalty100 on all other terms. No alpha/harmonic/window grid. Weekly-cluster sandwich estimate recorded descriptively;not used as an entry filter.',
            signal='Direction sign(predicted gross normalized return). Trade if abs(prediction)>BASE assumed roundtrip cost.39/unit. Same BASE-derived candidates at LOW/BASE/STRESS. First actual eligible entries online,not best two future signals in a day.',
            execution='Known signal+60sec entry;reuse v7 fee adapter and unchanged M1 adverse-first engine. SL at signal close-direction*max(2,1.5ATR),round tick. Actual filled riskmin2/max20. TP.8actualR,max120min/21:00feed cutoff. Spread/slip/commission aslocked.',
            caps='One position,max2 actual fills/feed day,max10/feed ISO week. Do not force weekly trades. No Fresh combination in this independent lab.',
            validation='Models refitted monthly from past targets;logical walk-forward on already inspected gold history,not pristine OOS. Full evaluation2021-10-25 to2026-10-25.'),
        objective=dict(win_rate_percent=[55,60], mean_week=[5,10], zero_empty_market_data_weeks=True),
        statistical_screen=dict(family_size=105, prior_hypotheses=102, min_trades=1000,
            annual_stability='each full year2022-2025 BASE positive',
            costs='BASE/STRESS positive with family-adjusted monthly bootstrap lower>0'),
        bootstrap_seed=20261111, bootstrap_resamples=100000,
        sources=[dict(url='https://journals.plos.org/plosone/article?id=10.1371/journal.pone.0174232',
            use='Intraday periodicity in precious-metal returns and liquidity;not proof of these coefficients, rules or profitability.'),
            dict(url='https://www.rieti.go.jp/jp/publications/dp/17e120.pdf',
            use='Time-varying informational efficiency and participant types in gold futures;motivates seasonal response,not proof spot CFD returns can be forecast after costs.')],
        caveats=['All gold history previously inspected;adaptive model cannot erase prior selection.',
            'Fixed-horizon training labels differ from executable stop/target results;only executable after-cost results determine qualification.',
            'Each model repeatedly learns continuous coefficients from many past half-hour samples. These internal estimates are not independently selected historical backtest winners;model complexity still creates estimation risk.',
            'Fees,feed clock/DST,news/prop account limits not account verified. No guarantee or broker orders.'])
    path = RUN/'EXPERIMENT_LOCK.json'
    if path.exists():
        assert json.loads(path.read_text(encoding='utf-8')) == lock, 'Frozen definitions changed'
    else:
        write_json(path, lock)
    return lock


def opportunities(gold):
    a = metaquotes_atr(gold); known = gold[:, 0].astype(np.int64)+300
    i = np.arange(6, len(gold)); at = known[i]
    good = (at % 1800 == 0) & (at % 86400 >= 2*3600) & (at % 86400 < 18*3600)
    good &= (gold[i, 0]-gold[i-6, 0] == 1800) & (a[i] > 0)
    i = i[good]; at = known[i]; unit = np.maximum(2., 1.5*a[i])
    lag = np.clip((gold[i, 4]-gold[i-6, 4])/unit, -5, 5)
    phase = 2*np.pi*(at % 86400)/86400
    basis = np.c_[np.ones(len(i)), np.sin(phase), np.cos(phase), np.sin(2*phase), np.cos(2*phase)]
    return dict(index=i, known=at, unit=unit, lag=lag, basis=basis, atr=a[i], close=gold[i, 4])


def labels(opp, market):
    """All target availability is for training only; candidates never consult this mask."""
    times = market[:, 0].astype(np.int64); enter = opp['known']+60; leave = enter+7200
    left = np.searchsorted(times, enter); right = np.searchsorted(times, leave)
    gaps = np.r_[0, np.cumsum(np.diff(times) != 60)]
    valid = (left < len(times)) & (right < len(times)); ix = np.where(valid)[0]
    valid[ix] &= ((times[left[ix]] == enter[ix]) & (times[right[ix]] == leave[ix]) &
                  (gaps[right[ix]] == gaps[left[ix]]))
    out = np.full(len(enter), np.nan); ix = np.where(valid)[0]
    out[ix] = (market[right[ix], 1]-market[left[ix], 1])/opp['unit'][ix]
    return out, leave


def design(opp, family):
    if family == 21:
        return opp['basis']
    if family == 22:
        return np.c_[opp['basis'], opp['basis']*opp['lag'][:, None]]
    return np.c_[np.ones(len(opp['lag'])), opp['lag']]


def fit(x, y, weeks):
    mean = np.mean(x, axis=0); scale = np.std(x, axis=0)
    mean[0] = 0.; scale[0] = 1.; scale[scale < 1e-12] = 1.
    z = (x-mean)/scale
    penalty = np.eye(x.shape[1])*100.; penalty[0, 0] = 0.
    inverse = np.linalg.inv(z.T @ z+penalty)
    beta = inverse @ (z.T @ y); residual = y-z @ beta
    group = np.unique(weeks); meat = np.zeros((len(beta), len(beta)))
    for week in group:
        keep = weeks == week; score = z[keep].T @ residual[keep]; meat += np.outer(score, score)
    correction = len(group)/max(1, len(group)-1)*(len(y)-1)/max(1, len(y)-len(beta))
    cov = inverse @ meat @ inverse*correction
    return dict(mean=mean, scale=scale, beta=beta, cov=cov)


def predict(model, x):
    z = (x-model['mean'])/model['scale']
    pred = z @ model['beta']; se = np.sqrt(np.maximum(0., np.einsum('ij,jk,ik->i', z, model['cov'], z)))
    return pred, se


def month_bounds(start, end):
    current = datetime.fromtimestamp(start, timezone.utc).replace(day=1, hour=0, minute=0, second=0)
    while current.timestamp() < end:
        following = current.replace(year=current.year+1, month=1) if current.month == 12 else current.replace(month=current.month+1)
        yield int(current.timestamp()), int(following.timestamp())
        current = following


def candidates(opp, target, target_end, start=w.START, end=w.END):
    parts = []; models = []
    for family, name in NAMES.items():
        x = design(opp, family)
        for month, next_month in month_bounds(start, end):
            train = ((opp['known'] >= month-365*86400) & (target_end < month-7200) & np.isfinite(target))
            test = ((opp['known'] >= max(start, month)) & (opp['known'] < min(end, next_month)))
            days = np.unique(opp['known'][train]//86400)
            weeks = (opp['known'][train]//86400+3)//7
            provenance = dict(name=name, month=month, next_month=next_month, n=int(train.sum()),
                days=len(days), weeks=len(np.unique(weeks)),
                last_train_label_end=int(target_end[train].max()) if train.any() else None,
                first_train_signal=int(opp['known'][train].min()) if train.any() else None)
            if train.sum() < 2000 or len(days) < 120 or len(np.unique(weeks)) < 26:
                provenance['status'] = 'WARMUP'; models.append(provenance); continue
            model = fit(x[train], target[train], weeks); pred, se = predict(model, x[test])
            provenance.update(status='FITTED', parameters={k: a.tolist() for k, a in model.items()})
            models.append(provenance)
            for index, estimate, error in zip(np.where(test)[0], pred, se):
                cost = .39/opp['unit'][index]
                if abs(estimate) <= cost:
                    continue
                d = 1 if estimate > 0 else -1; c = np.zeros(40); at = int(opp['known'][index])
                i = int(opp['index'][index]); close = opp['close'][index]; stop = close-d*opp['unit'][index]
                c[:8] = [at-300, at+60, int(d > 0), month, family+10, 0, 0, at]
                c[8:18] = [50, 0, close, close, month, at, close, month, close, month]
                c[18:23] = [opp['atr'][index], stop, stop, close, close]
                c[33:40] = [error, i, 0, family, at, 0, 0]
                parts.append(c)
    raw = np.array(parts, dtype=float).reshape((-1, 40))
    if len(raw):
        raw = raw[np.lexsort((raw[:, 36], raw[:, 1]))]
    return raw, models


def main():
    lock = freeze(); data = np.load(w.BASE/'rates.npz')
    gold = bars_matrix(data['m5']); market = bars_matrix(data['m1'])
    opp = opportunities(gold); target, target_end = labels(opp, market)
    raw, models = candidates(opp, target, target_end)
    np.savez_compressed(RUN/'opportunities.npz', **opp, target=target, target_end=target_end)
    np.save(RUN/'raw_candidates.npy', raw); write_json(RUN/'MONTHLY_MODELS.json', models)
    w.FAMILIES.update(NAMES); results = []
    for spec in SPECS:
        for cost in w.COSTS:
            trades, rejects = execution.run_serial(raw, market, spec, cost)
            metric = w.summarize(trades, market, lock)
            metric['sources'] = {spec['name']: w.metrics(trades)}
            results.append(dict(name=spec['name'], cost=cost['id'], metrics=metric, rejections=rejects))
            write_json(RUN/(spec['name']+'_'+cost['id']+'_trades.json'), dict(trades=trades, rejections=rejects))
            print(spec['name'], cost['id'], metric['n'], round(metric['win_rate'] or 0, 2),
                  round(metric['total_r'], 2), 'R;week', round(metric['frequency']['mean'], 2),
                  'empty', len(metric['frequency']['empty_weeks']), flush=True)
    write_json(RUN/'summary.json', dict(rows=results, model_count=len(models), lock_sha256=sha(RUN/'EXPERIMENT_LOCK.json')))
    assert all(sha(w.ROOT/p) == value for p, value in lock['preserved_fresh'].items())
    write_json(RUN/'SOURCE_MANIFEST.json', dict(fresh_unchanged=True, files={p: sha(w.ROOT/p) for p in (
        'scripts/research_scalp_seasonal_v10.py', 'scripts/research_scalp_avwap_v7.py',
        'scripts/research_scalp_weekly_v3.py', 'scripts/can_ho_tro_scalp_plan.py')}))
    print('DONE3 models/9 after-cost barrier scenarios;Fresh unchanged', flush=True)


if __name__ == '__main__':
    main()
