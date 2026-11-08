"""New closed-M1 continuation event after an independent reclaim has failed."""
from __future__ import annotations

import argparse
from collections import Counter
import json

import numpy as np
from numba import njit

from can_ho_tro_scalp_core import bars_matrix, ema50, metaquotes_atr
from can_ho_tro_scalp_plan import idea_key, planned_gate
from prepare_can_ho_tro_scalp import sha, write_json
import research_scalp_early_mean_v5 as early

w = early.w
RUN = w.ROOT / 'reports/can_ho_tro_scalp/20261101_failed_reclaim_v6'
NAMES = {14: 'FAILED_M15', 15: 'FAILED_H1', 16: 'FAILED_NO_CONTEXT'}
SPECS = [dict(name='FAILED_M15', sources=[14]), dict(name='FAILED_H1', sources=[15]),
         dict(name='FAILED_COMBO', sources=[0, 14, 15]), dict(name='FAILED_NO_CONTEXT', sources=[16])]


def freeze():
    RUN.mkdir(parents=True, exist_ok=True)
    lock = dict(version='failed_reclaim_v6', start=w.START, end_exclusive=w.END,
                hypotheses=SPECS, costs=w.COSTS, data_sha256=sha(w.BASE/'rates.npz'),
                preserved_fresh={p: sha(w.ROOT/p) for p in w.FRESH_PATHS},
                dependencies={p: sha(w.ROOT/p) for p in [
                    'scripts/research_scalp_early_mean_v5.py',
                    'reports/can_ho_tro_scalp/20261101_early_mean_v5/CUMULATIVE_REGISTRY.json',
                    'reports/can_ho_tro_scalp/20261101_early_mean_v5/EARLY_NO_CONTEXT_candidates.npz']},
                motivation='Earlier independent mean reclaims had1075 STOP/STOP_GAP of1714 BASE trades; test a NEW continuation event after price closes through the known excursion extreme,without using a trade outcome.',
                definitions=dict(
                    source='ALL independent EARLY_NO_CONTEXT raw reclaims,including those never admitted as trades; no P&L/stop/target label inputs',
                    activation='original reclaim must be closed; scan the next15 contiguous M1 bars only; reset on any missing M1 bar',
                    invalidation='cancel if any Bid bar touches original frozen mean before/within failure confirmation; if both mean and failure touched in same minute,cancel conservatively',
                    trigger='first CLOSED M1 in opposite direction beyond original excursion extreme by>=.1 frozenATR5; directional body>=.1 previous-M1 ATR14,range>=.5 same ATR1,close in outer35%;first qualifying failure consumes original event',
                    context='M15/H1 last closed BEFORE failure-bar open,age<=one context period,close on trend side ofEMA20 and EMA20 slope over6 bars same direction;NO_CONTEXT bypasses filter;no ADX search',
                    stop='opposite extreme across original sweep through failure confirmation +.25 frozen sourceATR5;min2/max20 actual fill-risk;never use extrema after failure confirmation',
                    target='fixed.8 initialR from actual filled risk;Fresh in combination retains.5R',
                    execution='unchanged WeeklyPlan/w.simulate:marketBid/Ask,first quote<=60s,M1 adverse-first,gap handling,commission once,120min hold/21:00feed cutoff;Fresh6h with cutoff',
                    hours='08:00<=failure-confirmation-open feed hour<19:00;not a verified London/NY clock',
                    caps='one position,max2 filled entries/feed day,max10/feed ISO week,no quota',
                    priority='Fresh then FAILED_M15 then FAILED_H1;skip sources outside chosen group',
                    provenance='candidate source_known is original reclaim close;level is original excursion extreme;sweep_time column is new failure-confirmation open'),
                statistical_screen=dict(family_size=82, prior_hypotheses=78, min_trades=1000,
                                        annual_stability='all full years2022-2025 BASE positive',
                                        costs='BASE/STRESS net positive;family-adjusted month bootstrap lower>0'),
                objective=dict(win_rate_min_percent=55, target_percent=[55, 60], mean_trades_week=[5, 10], zero_empty_market_data_weeks=True),
                selection='prior years only,120min purge,>=200 train trades,positive netR,>=55% wins,mean5-10/week,no empty train weeks;rankBASE R/week;cash if none;continuous serial execution',
                bootstrap_seed=20261107, bootstrap_resamples=20000,
                sources=[dict(url='https://www.brookstradingcourse.com/wp-content/uploads/2017/10/171017-Futures.io-Presentation-Opening-Reversals-Al-Brooks.pdf',
                              date='2017-10-17', use='concept of trend resumption after failed reversal;not the XAUUSD thresholds or performance')],
                caveats=['Retrospective;all2021-2026 history and26-30Oct2026 previously inspected.',
                         'Not the inverse of original trade returns;failure creates a later,independently priced trade.',
                         'Assumed spread/slippage/commission;actual ticks,clock/DST,news and prop package unverified.',
                         'At least82 tracked hypotheses plus earlier untracked selection.'])
    path = RUN/'EXPERIMENT_LOCK.json'
    if path.exists():
        assert json.loads(path.read_text(encoding='utf-8')) == lock, 'Never change frozen definitions'
    else:
        write_json(path, lock)
    return lock


@njit(cache=True)
def trend_ok(at, direction, bars, seconds, ma):
    i = np.searchsorted(bars[:, 0], at-seconds, side='right')-1
    return (i >= 40 and at-bars[i, 0]-seconds <= seconds and
            direction*(bars[i, 4]-ma[i]) > 0 and direction*(ma[i]-ma[i-6]) > 0)


@njit(cache=True)
def detect_failed(events, m1, h1, ctx, ctxseconds, family, start, stop):
    amin = metaquotes_atr(m1); a1 = metaquotes_atr(h1); ma1 = ema50(h1); cma = w.ema(ctx, 20)
    rows = []
    for event in events:
        if event[1] >= stop:
            break
        buy = not bool(event[2]); d = 1 if buy else -1
        p = np.searchsorted(m1[:, 0], event[0], side='left')
        sweep = np.searchsorted(m1[:, 0], event[13], side='left')
        if p == len(m1) or m1[p, 0] != event[0] or sweep > p:
            continue
        # Include the entire known failed rebound in the protective-stop anchor.
        anchor = np.min(m1[sweep:p+1, 3]) if buy else np.max(m1[sweep:p+1, 2])
        left = np.searchsorted(m1[:, 0], event[1], side='left')
        for c in range(left, min(left+15, len(m1))):
            at = m1[c, 0]; known = at+60
            if known >= stop or at != event[1]+(c-left)*60:
                break
            o, h, l, close = m1[c, 1:5]
            # For a failed sell, its mean is below; for a failed buy it is above.
            if (l <= event[29] if buy else h >= event[29]):
                break
            anchor = min(anchor, l) if buy else max(anchor, h)
            a = amin[c-1]; rng = h-l
            valid = (a > 0 and d*(close-event[14]) >= .1*event[18] and
                     d*(close-o) >= .1*a and rng >= .5*a)
            if valid:
                valid = ((close-l)/rng if buy else (h-close)/rng) >= .65
            if not valid:
                continue
            context = family == 16 or trend_ok(at, d, ctx, ctxseconds, cma)
            if context and known >= start and 8 <= int(at//3600) % 24 < 19:
                row = w.make_candidate(m1, c, 60, buy, event[0], event[1], event[14],
                                       at, anchor, event[18], family, h1, ma1, a1)
                row[19] = anchor-d*.25*event[18]
                rows.append(row)
            # The first valid failure consumes this event even if context/hour rejects it.
            break
    out = np.empty((len(rows), 40))
    for i in range(len(rows)):
        out[i] = rows[i]
    # Original reclaims may have different delays; return new events in causal order.
    return out[np.argsort(out[:, 1])]


def detect(arrays, family, events=None, start=w.START, stop=w.END):
    if events is None:
        events = early.detect(arrays, 13, start=start, stop=stop)
    ctx = w.aggregate_complete(arrays['m5'], 900) if family == 14 else arrays['h1']
    return detect_failed(events, arrays['m1'], arrays['h1'], ctx, 900 if family == 14 else 3600,
                         family, start, stop)


def run_serial(raw, market, spec, cost, schedule=None):
    trades = []; seen = set(); busy = 0; chosen = -1
    days = Counter(); weeks = Counter(); rejects = Counter()
    for index, c in enumerate(raw):
        at = int(c[1])
        if schedule is not None:
            spec = schedule.get(w.datetime.fromtimestamp(at, w.timezone.utc).year)
            if spec is None:
                continue
        if int(c[36]) not in spec['sources'] or planned_gate(c) != 'PASS':
            continue
        if at < busy:
            rejects['BUSY'] += 1; continue
        if at == chosen:
            rejects['PRIORITY'] += 1; continue
        chosen = at; key = idea_key(c); day = at//86400; week = w.week_key(at)
        if key in seen:
            rejects['DUPLICATE'] += 1; continue
        if days[day] >= 2 or weeks[week] >= 10:
            rejects['CAP'] += 1; continue
        seen.add(key)
        row = w.simulate(index, c, market, .8, cost); trades.append(row)
        if row['entry_time']:
            days[day] += 1; weeks[week] += 1
        if row['state'].startswith('CENSORED'):
            busy = int(market[-1, 0])+60
        elif row['exit_time']:
            busy = row['exit_time']
    return trades, dict(rejects)


def walkforward(feed, raw, market, cost):
    lookup = {s['name']: s for s in SPECS}; schedule = {}; choices = []
    for year in range(2023, 2027):
        boundary = int(w.datetime(year, 1, 1, tzinfo=w.timezone.utc).timestamp()); rank = []
        for spec in SPECS:
            train = [t for t in feed[spec['name']] if t['state'] == 'CLOSED' and t['exit_time'] < boundary-7200]
            metric = w.metrics(train); f = w.weekly(train, market, w.START, boundary-7200)
            if (metric['n'] >= 200 and metric['total_r'] > 0 and (metric['win_rate'] or 0) >= 55 and
                    f['weeks'] and not f['empty_weeks'] and 5 <= f['mean'] <= 10):
                rank.append((metric['total_r']/f['weeks'], spec['name']))
        if rank:
            score, name = max(rank); schedule[year] = lookup[name]
            choices.append(dict(year=year, selected=name, train_r_week=score))
        else:
            choices.append(dict(year=year, selected='CASH'))
    trades, rejects = run_serial(raw, market, None, cost, schedule=schedule)
    return dict(choices=choices, metrics=w.metrics(trades), rejections=rejects,
                label='retrospective prior-year choice'), trades


def main():
    parser = argparse.ArgumentParser(); parser.add_argument('--freeze-only', action='store_true'); args = parser.parse_args()
    lock = freeze()
    if args.freeze_only:
        return
    w.FAMILIES.update(NAMES)
    source = np.load(w.BASE/'rates.npz'); arrays = {k: bars_matrix(source[k]) for k in source.files}
    events = np.load(early.RUN/'EARLY_NO_CONTEXT_candidates.npz')['raw']; parts = []
    for family, name in NAMES.items():
        path = RUN/(name+'_candidates.npz')
        if path.exists():
            raw = np.load(path)['raw']
        else:
            raw = detect(arrays, family, events=events); np.savez_compressed(path, raw=raw)
        assert np.all(raw[:, 12] <= raw[:, 13]) and np.all(raw[:, 39] <= raw[:, 0])
        print('CANDIDATES', name, len(raw), flush=True); parts.append(raw)
    raw = w.add_fresh(np.concatenate(parts)); rows = []; feed = {}
    for spec in SPECS:
        for cost in w.COSTS:
            label = spec['name']+'_'+cost['id']; path = RUN/(label+'_trades.json')
            if path.exists():
                saved = json.loads(path.read_text()); trades = saved['trades']; rejects = saved['rejections']
            else:
                trades, rejects = run_serial(raw, arrays['m1'], spec, cost)
                write_json(path, dict(trades=trades, rejections=rejects))
            metric = w.summarize(trades, arrays['m1'], lock); f = metric['frequency']
            rows.append(dict(name=spec['name'], cost=cost['id'], metrics=metric, rejections=rejects))
            if cost['id'] == 'BASE':
                feed[spec['name']] = trades
            print(label, 'n', metric['n'], 'win', round(metric['win_rate'] or 0, 2), 'PF', round(metric['pf'] or 0, 3),
                  'R', round(metric['total_r'], 2), 'week', round(f['mean'], 2), 'empty', len(f['empty_weeks']), flush=True)
    wf = {}
    for cost in w.COSTS:
        metric, trades = walkforward(feed, raw, arrays['m1'], cost); wf[cost['id']] = metric
        write_json(RUN/('WALKFORWARD_'+cost['id']+'_trades.json'), trades)
    write_json(RUN/'summary.json', dict(rows=rows, walkforward=wf, lock_sha256=sha(RUN/'EXPERIMENT_LOCK.json')))
    assert all(sha(w.ROOT/p) == value for p, value in lock['preserved_fresh'].items())
    write_json(RUN/'SOURCE_MANIFEST.json', dict(fresh_unchanged=True, scripts={p: sha(w.ROOT/p) for p in [
        'scripts/research_scalp_failed_reclaim_v6.py', 'scripts/research_scalp_early_mean_v5.py',
        'scripts/can_ho_tro_scalp_plan.py', 'scripts/research_scalp_weekly_v3.py']}))
    print('DONE', len(rows), 'scenarios; Fresh unchanged', flush=True)


if __name__ == '__main__':
    main()
