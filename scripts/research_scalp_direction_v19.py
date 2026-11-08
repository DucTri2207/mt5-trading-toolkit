"""Isolate higher-frame directional selection from the sparse H1 ray trigger."""
from __future__ import annotations

import argparse
import json

import numpy as np

from can_ho_tro_scalp_core import bars_matrix
from prepare_can_ho_tro_scalp import sha,write_json
import research_scalp_trendline_v18 as t

v = t.v;w = t.w
RUN = w.ROOT/'reports/can_ho_tro_scalp/20261101_direction_v19'
NAMES = {50:'H4_DIRECTION_ONLY',51:'D1_H4_DIRECTION_ONLY'}
SPECS = [dict(name=name,sources=[key]) for key,name in NAMES.items()]


def freeze():
    RUN.mkdir(exist_ok=True)
    assert json.loads((t.RUN/'VERIFICATION.json').read_text(encoding='utf-8'))['passed']
    protocol = dict(version='direction_v19',start=w.START,end_exclusive=w.END,hypotheses=SPECS,costs=w.COSTS,
        motivation='User proposes higher-frame trend then trading with it. V18 H1 rays supplied only217events/5years;H4-gated71fills,BASE-3.84R,197emptyweeks. Test H4 directional information directly without the ray event gate. Not threshold tuning or proof about all trend following.',
        definitions=dict(
            trend='Exactly unchangedv18:2left/2rightconfirmed pivots on nativeH4/D1;up iff last2highs and last2lows rise with close>latestlow;down iff both fall with close<latesthigh;else neutral. Pivot known after secondrightclose.',
            opportunities='Exactly unchangedv10/v12 closedM5 half-hours,02<=knownfeedhour<18,7contiguousM5closes,knownATR14. Every opportunity eligible online,subject to existingoneposition/2fillsday/10week. No future rank or forced weekly entry.',
            policies='H4_DIRECTION_ONLY chooses BUY forH4up/SELLforH4down. D1_H4_DIRECTION_ONLY additionally requires sameD1direction. Both use latestH4/D1 closed<=M5triggerbarOPEN,age<=8h/4days. Neutral/staleH4 meansnoentry;neutral/opposite/staleD1 meansnostrictentry. H1ray/pullback/bodyfilters removed entirely for this diagnostic control.',
            execution='Unchangedv12candidate/v7money:SL signalclose+/-max2,1.5M5ATR14;actualrisk2..20,TP.8actualR,signalclose+60sec,max120min/21feedcutoff,Bid/Ask/slip/commission,M1adverse-first/gaps,moneylabelsunchanged. IdenticalrawsignalsatLOW/BASE/STRESS.',
            interpretation='This isolates a simple executable directional control. Changes in realized portfolios also reflect occupancy/caps;not a matched causal effect or a claim that one candle pattern captures all trader discretion.',
            counting='2newhypotheses/6costscenarios. No new frame/pivot-width/entrytime/SL/TP grid after outcomes. Keep failed results.'),
        objective=dict(win_rate_percent=[55,60],mean_week=[5,10],zero_empty_market_data_weeks=True),
        statistical_screen=dict(family_size=131,prior_hypotheses=129,min_trades=1000,
            annual_stability='allfull2022-2025BASEpositive',costs='BASE/STRESSpositive,familymonthlybootstraplower>0'),
        bootstrap_seed=20261120,bootstrap_resamples=100000,
        sources=[dict(url='https://www.nber.org/papers/w7613',
            use='Lo,Mamaysky,Wang motivates objective pattern definitions and comparing conditional with unconditional returns. Daily USstocks1962-1996,kernel recognition;not evidence for this H4 fractal,XAUUSD,scalp frequency or profitability.')],
        caveats=['Allgoldhistorypreviouslyinspected;retrospective only,not pristineOOS.',
            'Assumedcosts and unverifiedfeedclock;cannot guarantee futureprofit. FTMO risk deferredperuser;Freshpreserved.'])
    path = RUN/'ASSAY_PROTOCOL.json'
    if path.exists():
        assert json.loads(path.read_text(encoding='utf-8'))==protocol,'Frozen direction protocol changed'
    else:
        write_json(path,protocol)
    files = ('scripts/research_scalp_direction_v19.py','scripts/research_scalp_trendline_v18.py',
             'scripts/research_scalp_payoff_v12.py','scripts/research_scalp_seasonal_v10.py',
             'scripts/research_scalp_avwap_v7.py','scripts/research_scalp_weekly_v3.py',
             'scripts/can_ho_tro_scalp_plan.py','scripts/can_ho_tro_scalp_core.py')
    lock = dict(protocol=protocol,start=w.START,end_exclusive=w.END,hypotheses=SPECS,costs=w.COSTS,
        statistical_screen=protocol['statistical_screen'],bootstrap_seed=protocol['bootstrap_seed'],bootstrap_resamples=protocol['bootstrap_resamples'],
        protocol_sha256=sha(path),h4_sha256=sha(t.RUN/'h4_rates.npz'),gold_sha256=sha(w.BASE/'rates.npz'),
        labels_sha256=sha(v.RUN/'barrier_labels.npz'),previous_registry_sha256=sha(t.RUN/'CUMULATIVE_REGISTRY.json'),
        implementation_sha256={p:sha(w.ROOT/p) for p in files},preserved_fresh={p:sha(w.ROOT/p) for p in w.FRESH_PATHS})
    path = RUN/'EXPERIMENT_LOCK.json'
    if path.exists():
        assert json.loads(path.read_text(encoding='utf-8'))==lock,'Frozen direction implementation changed'
    else:
        write_json(path,lock)
    return lock


def candidates(opp,s4,sd,start=w.START,end=w.END):
    rows = []
    for i,known in enumerate(opp['known']):
        if not start<=known<end:
            continue
        d,k4 = t.context(known-300,s4,28800);dd,kd = t.context(known-300,sd,345600)
        if d==0:
            continue
        for family,eligible in ((50,True),(51,dd==d)):
            if not eligible:
                continue
            c = v.make_candidate(opp,i,d>0,family,int(k4));c[39] = k4;rows.append(c)
    raw = np.asarray(rows,float).reshape((-1,40))
    if len(raw):
        raw = raw[np.lexsort((raw[:,36],raw[:,1]))]
    return raw


def main():
    parser = argparse.ArgumentParser();parser.add_argument('--freeze-only',action='store_true');args = parser.parse_args()
    lock = freeze()
    if args.freeze_only:
        print('LOCKED before outcomes;2policies/6plannedscenarios',flush=True);return
    source = np.load(w.BASE/'rates.npz');m5 = bars_matrix(source['m5']);market = bars_matrix(source['m1'])
    h4 = bars_matrix(np.load(t.RUN/'h4_rates.npz')['rates']);d1 = bars_matrix(source['d1'])
    s4 = t.structure(h4,14400);sd = t.structure(d1,86400);opp = v.seasonal.opportunities(m5)
    raw = candidates(opp,s4,sd);np.save(RUN/'raw_candidates.npy',raw)
    write_json(RUN/'COVERAGE.json',dict(raw_candidates={name:int(np.sum(raw[:,36]==k)) for k,name in NAMES.items()},
        source='Same half-hour opportunity grid and unchangedH4/D1structure,withoutH1raygate. Neutral/stale remainscash.'))
    w.FAMILIES.update(NAMES);results = []
    for spec in SPECS:
        for cost in w.COSTS:
            trades,rejects = v.execution.run_serial(raw,market,spec,cost);metric = w.summarize(trades,market,lock)
            results.append(dict(name=spec['name'],cost=cost['id'],metrics=metric,rejections=rejects))
            write_json(RUN/(spec['name']+'_'+cost['id']+'_trades.json'),dict(trades=trades,rejections=rejects))
            print(spec['name'],cost['id'],metric['n'],round(metric['win_rate'] or 0,2),round(metric['total_r'],2),'R;week',
                  round(metric['frequency']['mean'],2),'empty',len(metric['frequency']['empty_weeks']),flush=True)
    write_json(RUN/'summary.json',dict(rows=results,lock_sha256=sha(RUN/'EXPERIMENT_LOCK.json')))
    assert all(sha(w.ROOT/p)==h for p,h in lock['preserved_fresh'].items())
    print('DONE2newpolicies/6costscenarios;Freshunchanged',flush=True)


if __name__=='__main__':
    main()
