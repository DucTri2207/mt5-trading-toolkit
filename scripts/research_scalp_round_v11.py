"""First eligible touch of a fixed price grid: cascade/rejection and shifted controls."""
from __future__ import annotations

import json

import numpy as np
from numba import njit

from can_ho_tro_scalp_core import bars_matrix, metaquotes_atr
from prepare_can_ho_tro_scalp import sha, write_json
import research_scalp_weekly_v3 as w
import research_scalp_avwap_v7 as execution

RUN = w.ROOT/'reports/can_ho_tro_scalp/20261101_round_v11'
NAMES = {24: 'ROUND_CASCADE', 25: 'ROUND_REJECTION', 26: 'SHIFT_CASCADE', 27: 'SHIFT_REJECTION'}
SPECS = [dict(name=name, sources=[f]) for f, name in NAMES.items()]


def freeze():
    RUN.mkdir(parents=True, exist_ok=True)
    lock = dict(version='round_grid_v11', hypotheses=SPECS, costs=w.COSTS,
        start=w.START, end_exclusive=w.END, data_sha256=sha(w.BASE/'rates.npz'),
        prior_registry_sha256=sha(w.ROOT/'reports/can_ho_tro_scalp/20261101_seasonal_v10/CUMULATIVE_REGISTRY.json'),
        preserved_fresh={p: sha(w.ROOT/p) for p in w.FRESH_PATHS},
        mechanism='Order clustering can produce continuation beyond a level and reversal when it holds. Evidence is from FX; whether XAUUSD fixed dollar grids behave similarly is a new retrospective hypothesis. No actual stop orders are observed.',
        definitions=dict(
            grid='ROUND levels10*k price units;SHIFT levels10*k+3.7. Same spacing,one fixed non-round phase,not a phase/spacing grid search. Reference exists independently of future price.',
            approach='At M1 open,last3 completed contiguous M5 closes are on one side of nearest grid level in approach direction,each by>=.1 current-known M5 ATR14;latest distance.25-2ATR. Need complete contiguous M1 coverage from first of those3 M5 bars through current M1 open. No future/right pivots or H1.',
            first_touch='Only first eligible M1 high/low touch per grid index/approach direction/feed epoch day. Consume touch even if hours/confirmation fail. Re-evaluate approach from completed M5 only;no inference of where real stops are.',
            cascade='Touch candle opens on approach side and closes>=.1ATR beyond level,in approach direction;directional body>=.15ATR,range>=.3ATR,close in outer25%. SL outside extreme of last3 completed M5 bars and touch bar,+.25ATR buffer.',
            rejection='Touch penetrates>=.05ATR but closes>=.1ATR back on approach side;body>=.15ATR away from level,range>=.3ATR,close in outer25%. Trade opposite approach;SL outside touch extreme,+.25ATR buffer.',
            availability='Current M1 candle known only after60sec;enter at close+60sec,so candidate col1=M1open+120. Known M5 features must close<=M1open. New entries02:00<=confirmation M1open feed hour<19:00;clock/DST unverified.',
            execution='Unchanged v7 fee adapter/M1 adverse-first Bid/Ask engine. Actual initial riskmin2/max20,TP.8actualR,max120min/21:00feed cutoff. One position,max2 fills/day,max10/feed ISO week,no quota.',
            comparison='Keep all4 results. Shifted controls test level specificity;they are not substituted as a winner if round hypotheses fail. No claim of actual gold stop clustering from quote data.'),
        objective=dict(win_rate_percent=[55,60], mean_week=[5,10], zero_empty_market_data_weeks=True),
        statistical_screen=dict(family_size=109, prior_hypotheses=105,min_trades=1000,
            annual_stability='all full years2022-2025 BASE positive', costs='BASE/STRESS positive;family-adjusted monthly bootstrap lower>0'),
        bootstrap_seed=20261112, bootstrap_resamples=100000,
        sources=[dict(url='https://www.newyorkfed.org/research/staff_reports/sr125.html', use='FX stop/take-profit clustering at round numbers;not proof for gold.'),
                 dict(url='https://www.newyorkfed.org/medialibrary/media/research/staff_reports/sr150.pdf', use='FX positive-feedback cascades and take-profit reversals;not these thresholds or an XAUUSD edge.')],
        caveats=['All target history previously inspected;retrospective,not pristine OOS.',
                 'Dollar10 spacing is a specified hypothesis,not empirically observed gold order locations.',
                 'No centralized volume,order book,actual stop orders or futures/spot spread data. Fees assumed,not broker verified.'])
    path = RUN/'EXPERIMENT_LOCK.json'
    if path.exists():
        assert json.loads(path.read_text(encoding='utf-8')) == lock, 'Frozen definitions changed'
    else:
        write_json(path, lock)
    return lock


@njit(cache=True)
def detect(m1, m5, offset=0., start=w.START, end=w.END):
    a5 = metaquotes_atr(m5); used = np.full((2, 65536), -1, np.int64)
    gap = np.zeros(len(m1), np.int64)
    for i in range(1, len(m1)):
        gap[i] = gap[i-1]+int(m1[i, 0]-m1[i-1, 0] != 60)
    rows = []; j = -1
    for i in range(len(m1)):
        at = m1[i, 0]
        if at+60 >= end:
            break
        while j+1 < len(m5) and m5[j+1, 0]+300 <= at:
            j += 1
        if j < 15 or m5[j, 0]+300 > at or at-(m5[j, 0]+300) >= 300:
            continue
        if m5[j, 0]-m5[j-2, 0] != 600:
            continue
        left = np.searchsorted(m1[:, 0], m5[j-2, 0])
        if left > i or m1[left, 0] != m5[j-2, 0] or gap[i] != gap[left]:
            continue
        a = a5[j]
        if a <= 0:
            continue
        o, h, l, close = m1[i, 1:5]; rng = h-l
        for side in range(2):
            d = 1 if side == 0 else -1
            k = int(np.ceil((m5[j, 4]-offset)/10)) if d > 0 else int(np.floor((m5[j, 4]-offset)/10))
            if k < 0 or k >= 65536:
                continue
            level = 10*k+offset; distance = d*(level-m5[j, 4])
            day = int(at)//86400
            if used[side, k] == day or distance < .25*a or distance > 2*a:
                continue
            good = True
            for t in range(j-2, j+1):
                if d*(level-m5[t, 4]) < .1*a:
                    good = False
            if not good or (h < level if d > 0 else l > level):
                continue
            used[side, k] = day
            if not start <= at+60 < end or not 2 <= int(at//3600) % 24 < 19 or rng < .3*a:
                continue
            cascade = (d*(o-level) <= 0 and d*(close-level) >= .1*a and
                       d*(close-o) >= .15*a and ((close-l)/rng if d > 0 else (h-close)/rng) >= .75)
            penetration = h-level if d > 0 else level-l
            rejection = (penetration >= .05*a and d*(close-level) <= -.1*a and
                         d*(close-o) <= -.15*a and ((h-close)/rng if d > 0 else (close-l)/rng) >= .75)
            if not cascade and not rejection:
                continue
            trade_d = d if cascade else -d
            family = (24 if cascade else 25)+(2 if offset else 0)
            if cascade:
                anchor = min(l, np.min(m5[j-2:j+1, 3])) if trade_d > 0 else max(h, np.max(m5[j-2:j+1, 2]))
            else:
                anchor = l if trade_d > 0 else h
            available = m5[j, 0]+300; c = np.zeros(40)
            c[:8] = np.array([at, at+120, int(trade_d > 0), m5[j, 0], 10+family, 0, 0, k])
            c[8:18] = np.array([50, 0, level, level, available, at, anchor, m5[j, 0], level, available])
            c[18:23] = np.array([a, anchor-trade_d*.25*a, anchor, close, (o+close)/2])
            c[34:40] = np.array([i, 0, family, available, 0, 0])
            rows.append(c)
    result = np.empty((len(rows), 40))
    for i in range(len(rows)):
        result[i] = rows[i]
    return result


def main():
    lock = freeze(); source = np.load(w.BASE/'rates.npz')
    m1 = bars_matrix(source['m1']); m5 = bars_matrix(source['m5'])
    parts = [detect(m1, m5, offset) for offset in (0., 3.7)]
    raw = np.concatenate(parts); raw = raw[np.lexsort((raw[:, 36], raw[:, 1]))]
    np.save(RUN/'raw_candidates.npy', raw); w.FAMILIES.update(NAMES); rows = []
    for spec in SPECS:
        for cost in w.COSTS:
            trades, rejects = execution.run_serial(raw, m1, spec, cost)
            metric = w.summarize(trades, m1, lock); metric['sources'] = {spec['name']: w.metrics(trades)}
            rows.append(dict(name=spec['name'], cost=cost['id'], metrics=metric, rejections=rejects))
            write_json(RUN/(spec['name']+'_'+cost['id']+'_trades.json'), dict(trades=trades, rejections=rejects))
            print(spec['name'], cost['id'], metric['n'], round(metric['win_rate'] or 0, 2),
                  round(metric['total_r'], 2), 'R;week', round(metric['frequency']['mean'], 2),
                  'empty', len(metric['frequency']['empty_weeks']), flush=True)
    write_json(RUN/'summary.json', dict(rows=rows, lock_sha256=sha(RUN/'EXPERIMENT_LOCK.json')))
    assert all(sha(w.ROOT/p) == h for p, h in lock['preserved_fresh'].items())
    write_json(RUN/'SOURCE_MANIFEST.json', dict(fresh_unchanged=True, files={p: sha(w.ROOT/p) for p in (
        'scripts/research_scalp_round_v11.py','scripts/research_scalp_avwap_v7.py',
        'scripts/research_scalp_weekly_v3.py','scripts/can_ho_tro_scalp_plan.py')}))
    print('DONE4 hypotheses/12 fee scenarios;Fresh unchanged', flush=True)


if __name__ == '__main__':
    main()
