"""Causal first retest of pivot/day anchored M1 tick-weighted price proxies."""
from __future__ import annotations

import argparse
from collections import Counter
import json

import numpy as np
from numba import njit

from can_ho_tro_scalp_core import bars_matrix, ema50, metaquotes_atr
from can_ho_tro_scalp_plan import idea_key, planned_gate
from prepare_can_ho_tro_scalp import sha, write_json
import research_scalp_weekly_v3 as w

RUN = w.ROOT/'reports/can_ho_tro_scalp/20261101_avwap_v7'
NAMES = {17: 'SWING_AVWAP', 18: 'DAY_VWAP', 19: 'SWING_EQUAL_WEIGHT', 20: 'SWING_NO_H1'}
SPECS = [dict(name=name, sources=[source]) for source, name in NAMES.items()]
SPECS.insert(2, dict(name='AVWAP_FRESH_COMBO', sources=[0, 17, 18]))


def quality(source):
    result = dict(data_sha256=sha(w.BASE/'rates.npz'), volume_label='broker tick activity proxy,not traded volume',
                  real_volume_available=False, clock_mapping='unverified;day means feed epoch day', frames={})
    for key in source.files:
        a = source[key]; tv = a['tick_volume']; rv = a['real_volume']
        result['frames'][key] = dict(rows=len(a), tick_zero=int(np.sum(tv == 0)),
            real_nonzero=int(np.sum(rv != 0)),
            tick_quantiles=np.quantile(tv, [0, .01, .1, .5, .9, .99, 1]).tolist(),
            invalid_ohlc=int(np.sum((a['high'] < np.maximum(a['open'], a['close'])) |
                                   (a['low'] > np.minimum(a['open'], a['close'])) | (a['low'] <= 0))))
    a = source['m1']; times = a['time']; days, first = np.unique(times//86400, return_index=True)
    result['m1'] = dict(nonincreasing_times=int(np.sum(np.diff(times) <= 0)),
        non60_second_intervals=int(np.sum(np.diff(times) != 60)),
        data_days=len(days), first_quote_hours={str(h): int(np.sum((times[first] % 86400)//3600 == h)) for h in range(24)})
    return result


def freeze():
    RUN.mkdir(parents=True, exist_ok=True)
    source = np.load(w.BASE/'rates.npz'); report = quality(source); write_json(RUN/'DATA_QUALITY.json', report)
    assert all(not row['invalid_ohlc'] for row in report['frames'].values())
    assert not report['m1']['nonincreasing_times']
    lock = dict(version='avwap_first_retest_v7', start=w.START, end_exclusive=w.END,
        hypotheses=SPECS, costs=w.COSTS, data_sha256=report['data_sha256'], quality_sha256=sha(RUN/'DATA_QUALITY.json'),
        previous_registry_sha256=sha(w.ROOT/'reports/can_ho_tro_scalp/20261101_failed_reclaim_v6/CUMULATIVE_REGISTRY.json'),
        preserved_fresh={p: sha(w.ROOT/p) for p in w.FRESH_PATHS},
        motivation='Mean-band reclaims and their later failures both lost money. Test a different known reference:price/quote-activity average from a causally confirmed pivot,with equal-weight ablation and feed-day reference.',
        definitions=dict(
            price='M1 typical(H+L+C)/3,weighted by broker tick_volume;SWING_EQUAL_WEIGHT uses1 per minute on the same valid coverage;never called exchange VWAP or footprint',
            swing_anchor='latest M15 low forBUY/high forSELL,2left+2right pivot;all5 M15 bars contiguous;available only after second right bar closes;expires6h from pivot open;new anchor cancels old state',
            day_anchor='first available M1 quote of each feed epoch day;known after its close;not a named exchange session or verified full-session VWAP;expires next feed day',
            coverage='M1 anchor bar must exist;every minute from anchor through last minute before M5 open must exist and have positive tick volume;latest M1 must close exactly at M5 open;no imputed volume or missing minutes',
            arming='need two valid anchored means30min apart;first eligible move-away when prior closed M5 close>=.75 prior-M5 ATR14 on direction side of current pre-bar mean,and pre-bar mean slope over30min has same sign',
            h1='except SWING_NO_H1,lastH1 closed before arming AND confirmation-open must have directional(close-EMA50)>0 and directionalEMA50 slope6bars>0;age<=1H',
            touch='first eligible M5 low<=pre-bar mean+.1ATR forBUY,high>=mean-.1ATR forSELL;freeze reference,ATR and reference-known time at first touch;consume first touch even if confirmation/hour fails',
            trigger='within3 contiguous M5 bars including touch,close on direction side of frozen mean,body>=.1 frozenATR,range>=.5 frozenATR,close in outer35%;cancel close beyond reference by>.5ATR or missing/stale coverage',
            stop='touch-through-confirmation extreme +/- .25 frozen previous-M5 rolling MetaQuotesATR14;actual-riskmin2/max20;no future extrema',
            target='fixed.8 actual initialR;Fresh in combination retains.5R',
            execution='unchanged WeeklyPlan/M1 adverse-first;actual Bid/Ask,spread/slippage,commission once,gaps;max120min/21:00feed cutoff;Fresh6h withcutoff',
            hours='08:00<=M5 confirmation-open feed hour<19:00;all other first touches still consumed',
            caps='one position,max2 actual fills/feed day,max10/feed ISO week;no quota',
            priority='Fresh then SWING_AVWAP then DAY_VWAP;equal-weight/noH1 are separate controls',
            provenance='candidate source_time=pivot/day anchor;source_known/reference-known=first touch open;pivot_known_at column17=anchor availability;frozen VWAP in columns10/11'),
        statistical_screen=dict(family_size=87, prior_hypotheses=82, min_trades=1000,
            annual_stability='all full years2022-2025 BASE positive', costs='BASE/STRESS positive net and family-adjusted monthly bootstrap lower>0'),
        objective=dict(win_rate_min_percent=55, target_percent=[55, 60], mean_trades_week=[5, 10], zero_empty_market_data_weeks=True),
        selection='prior years only,120min purge,>=200 train trades,positive net,>=55% wins,mean5-10/week,no empty train weeks;rankBASE R/week;cash if none;continuous execution',
        bootstrap_seed=20261108, bootstrap_resamples=20000,
        sources=[dict(url='https://alphatrends.net/anchored-vwap/', use='known event anchors,price relative to average and its slope;not these XAUUSD rules or performance'),
                 dict(url='https://www.mql5.com/en/docs/constants/structures/mqlrates', use='tick_volume and real_volume are distinct fields')],
        caveats=['All2021-2026 history and26-30Oct2026 previously inspected;retrospective.',
                 'All real_volume values0;tick-weighted HLC3 is a broker quote-activity proxy,not average actual transaction cost.',
                 'Feed-day anchor and assumed fees/clock/prop/news require later verification;no broker orders.',
                 'At least87 tracked hypotheses plus earlier untracked research;no future-profit guarantee.'])
    path = RUN/'EXPERIMENT_LOCK.json'
    if path.exists():
        assert json.loads(path.read_text(encoding='utf-8')) == lock, 'Never change frozen definitions'
    else:
        write_json(path, lock)
    return lock


@njit(cache=True)
def price_prefix(m1, volume, equal_weight=False):
    n = len(m1); pv = np.zeros(n+1); weight = np.zeros(n+1); gaps = np.zeros(n+1, np.int64); bad = np.zeros(n+1, np.int64)
    for i in range(n):
        v = 1. if equal_weight else volume[i]
        pv[i+1] = pv[i]+v*(m1[i, 2]+m1[i, 3]+m1[i, 4])/3
        weight[i+1] = weight[i]+v
        gaps[i+1] = gaps[i]+int(i > 0 and m1[i, 0]-m1[i-1, 0] != 60)
        bad[i+1] = bad[i]+int(volume[i] <= 0)
    return pv, weight, gaps, bad


@njit(cache=True)
def anchored_mean(anchor, at, m1, pv, weight, gaps, bad):
    left = np.searchsorted(m1[:, 0], anchor, side='left')
    right = np.searchsorted(m1[:, 0], at-60, side='right')-1
    if left >= len(m1) or right < left or m1[left, 0] != anchor or m1[right, 0]+60 != at:
        return 0., False
    if gaps[right+1]-gaps[left+1] or bad[right+1]-bad[left]:
        return 0., False
    v = weight[right+1]-weight[left]
    return ((pv[right+1]-pv[left])/v, True) if v > 0 else (0., False)


@njit(cache=True)
def day_anchors(m1):
    rows = []; previous = -10000000
    for b in m1:
        day = int(b[0])//86400
        if day == previous:
            continue
        previous = day
        for buy in range(2):
            rows.append(np.array([b[0], b[0]+60, b[1], buy]))
    out = np.empty((len(rows), 4))
    for i in range(len(rows)):
        out[i] = rows[i]
    return out


@njit(cache=True)
def h1_ok(at, direction, h1, ma):
    i = np.searchsorted(h1[:, 0], at-3600, side='right')-1
    return (i >= 50 and at-h1[i, 0]-3600 <= 3600 and direction*(h1[i, 4]-ma[i]) > 0 and
            direction*(ma[i]-ma[i-6]) > 0)


@njit(cache=True)
def detect_retest(m1, volume, m5, h1, anchors, family, start, stop):
    pv, weight, gaps, bad = price_prefix(m1, volume, family == 19)
    a5 = metaquotes_atr(m5); a1 = metaquotes_atr(h1); ma1 = ema50(h1)
    latest = np.full(2, -1, np.int64); state = np.zeros(2, np.int64); touched = np.zeros(2, np.int64)
    reference = np.zeros(2); frozen_atr = np.zeros(2); extreme = np.zeros(2); cursor = 0; rows = []
    for c in range(40, len(m5)):
        at = m5[c, 0]; known = at+300
        if known >= stop:
            break
        while cursor < len(anchors) and anchors[cursor, 1] <= at:
            side = 0 if anchors[cursor, 3] else 1
            latest[side] = cursor; state[side] = 0; cursor += 1
        if m5[c, 0]-m5[c-1, 0] != 300:
            state[:] = 0; continue
        o, h, l, close = m5[c, 1:5]
        for side in range(2):
            if latest[side] < 0:
                continue
            source = anchors[latest[side]]; buy = side == 0; d = 1 if buy else -1
            if (family == 18 and int(source[0])//86400 != int(at)//86400) or (family != 18 and at-source[0] > 21600):
                state[side] = 3; continue
            mean, complete = anchored_mean(source[0], at, m1, pv, weight, gaps, bad)
            if not complete:
                state[side] = 3; continue
            context = family == 20 or h1_ok(at, d, h1, ma1)
            if state[side] == 3:
                continue
            if state[side] == 0:
                old, old_complete = anchored_mean(source[0], at-1800, m1, pv, weight, gaps, bad)
                a = a5[c-1]
                if old_complete and context and a > 0 and d*(mean-old) > 0 and d*(m5[c-1, 4]-mean) >= .75*a:
                    state[side] = 1
            if state[side] == 1:
                if not context:
                    state[side] = 0; continue
                touch = l <= mean+.1*a5[c-1] if buy else h >= mean-.1*a5[c-1]
                if touch:
                    state[side] = 2; touched[side] = c; reference[side] = mean
                    frozen_atr[side] = a5[c-1]; extreme[side] = l if buy else h
            if state[side] != 2:
                continue
            extreme[side] = min(extreme[side], l) if buy else max(extreme[side], h)
            a = frozen_atr[side]; level = reference[side]; rng = h-l
            if c-touched[side] > 2 or d*(close-level) < -.5*a:
                state[side] = 3; continue
            valid = d*(close-level) > 0 and d*(close-o) >= .1*a and rng >= .5*a
            if valid:
                valid = ((close-l)/rng if buy else (h-close)/rng) >= .65
            if valid:
                p = touched[side]
                if context and known >= start and 8 <= int(at//3600) % 24 < 19:
                    r = w.make_candidate(m5, c, 300, buy, source[0], m5[p, 0], level,
                                         m5[p, 0], extreme[side], a, family, h1, ma1, a1)
                    r[17] = source[1]; r[19] = extreme[side]-d*.25*a
                    rows.append(r)
                state[side] = 3
    out = np.empty((len(rows), 40))
    for i in range(len(rows)):
        out[i] = rows[i]
    return out


def detect(arrays, volume, family, start=w.START, stop=w.END):
    anchors = day_anchors(arrays['m1']) if family == 18 else w.swing_levels(w.aggregate_complete(arrays['m5'], 900))
    return detect_retest(arrays['m1'], volume, arrays['m5'], arrays['h1'], anchors, family, start, stop)


def simulate(index, c, market, cost):
    result = w.simulate(index, c, market, .8, cost)
    result.update(commission=cost['commission_price']*100 if result['entry_time'] else 0.,
                  fees_status='ASSUMED_ROUND_TRIP_COMMISSION; SPREAD_SLIP_IN_PRICES; SWAP_UNMODELED',
                  commission_cash_unit='100oz-lot assumption,not actual account charge',
                  assumed_spread=cost['spread'], assumed_slippage=cost['slip'], assumed_commission_price=cost['commission_price'])
    return result


def run_serial(raw, market, spec, cost, schedule=None):
    rows = []; seen = set(); busy = 0; chosen = -1; days = Counter(); weeks = Counter(); rejects = Counter()
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
        seen.add(key); result = simulate(index, c, market, cost); rows.append(result)
        if result['entry_time']:
            days[day] += 1; weeks[week] += 1
        if result['state'].startswith('CENSORED'):
            busy = int(market[-1, 0])+60
        elif result['exit_time']:
            busy = result['exit_time']
    return rows, dict(rejects)


def walkforward(feed, raw, market, cost):
    choices = []; schedule = {}; lookup = {s['name']: s for s in SPECS}
    for year in range(2023, 2027):
        boundary = int(w.datetime(year, 1, 1, tzinfo=w.timezone.utc).timestamp()); rank = []
        for spec in SPECS:
            train = [t for t in feed[spec['name']] if t['state'] == 'CLOSED' and t['exit_time'] < boundary-7200]
            metric = w.metrics(train); frequency = w.weekly(train, market, w.START, boundary-7200)
            if metric['n'] >= 200 and metric['total_r'] > 0 and (metric['win_rate'] or 0) >= 55 and frequency['weeks'] and not frequency['empty_weeks'] and 5 <= frequency['mean'] <= 10:
                rank.append((metric['total_r']/frequency['weeks'], spec['name']))
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
    volume = source['m1']['tick_volume'].astype(float); parts = []
    for family, name in NAMES.items():
        cache = RUN/(name+'_candidates.npz')
        if cache.exists():
            raw = np.load(cache)['raw']
        else:
            raw = detect(arrays, volume, family); np.savez_compressed(cache, raw=raw)
        assert np.all(raw[:, 12] <= raw[:, 13]) and np.all(raw[:, 17] <= raw[:, 13]) and np.all(raw[:, 39] <= raw[:, 0])
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
            metric = w.summarize(trades, arrays['m1'], lock); frequency = metric['frequency']
            rows.append(dict(name=spec['name'], cost=cost['id'], metrics=metric, rejections=rejects))
            if cost['id'] == 'BASE':
                feed[spec['name']] = trades
            print(label, 'n', metric['n'], 'win', round(metric['win_rate'] or 0, 2), 'PF', round(metric['pf'] or 0, 3),
                  'R', round(metric['total_r'], 2), 'week', round(frequency['mean'], 2), 'empty', len(frequency['empty_weeks']), flush=True)
    wf = {}
    for cost in w.COSTS:
        metric, trades = walkforward(feed, raw, arrays['m1'], cost); wf[cost['id']] = metric
        write_json(RUN/('WALKFORWARD_'+cost['id']+'_trades.json'), trades)
    write_json(RUN/'summary.json', dict(rows=rows, walkforward=wf, lock_sha256=sha(RUN/'EXPERIMENT_LOCK.json')))
    assert all(sha(w.ROOT/p) == value for p, value in lock['preserved_fresh'].items())
    write_json(RUN/'SOURCE_MANIFEST.json', dict(fresh_unchanged=True, scripts={p: sha(w.ROOT/p) for p in [
        'scripts/research_scalp_avwap_v7.py', 'scripts/research_scalp_weekly_v3.py', 'scripts/can_ho_tro_scalp_plan.py']}))
    print('DONE', len(rows), 'scenarios; Fresh unchanged', flush=True)


if __name__ == '__main__':
    main()
