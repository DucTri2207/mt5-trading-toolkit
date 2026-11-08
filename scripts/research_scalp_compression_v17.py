"""Frozen range episodes: compression release versus failed release,with an ablation."""
from __future__ import annotations

import argparse
import json

import numpy as np
from numba import njit

from can_ho_tro_scalp_core import bars_matrix,metaquotes_atr
from prepare_can_ho_tro_scalp import sha,write_json
import research_scalp_payoff_v12 as v

w = v.w
RUN = w.ROOT/'reports/can_ho_tro_scalp/20261101_compression_v17'
NAMES = {44:'COMPRESSION_RELEASE',45:'COMPRESSION_FAILURE',46:'BOX_RELEASE_CONTROL'}
SPECS = [dict(name=name,sources=[k]) for k,name in NAMES.items()]
EVENT_FIELDS = ['known','family','buy','arm_known','box_low','box_high','frozen_ATR',
                'compression_ratio','break_known','M5_index']


def freeze():
    RUN.mkdir(parents=True,exist_ok=True)
    protocol = dict(version='compression_v17',start=w.START,end_exclusive=w.END,hypotheses=SPECS,costs=w.COSTS,
        user_steering='55-60% wins,5-10 trades/week,every market-data week active,positive five-year netR;separate MT5 indicator after qualification. FTMO/account rules deferred;Fresh preserved.',
        motivation='Test a causal event sequence with memory:compressed local ranges can release directionally or fail back into their frozen box. Earlier band/pivot tests and broad price-state models do not establish whether this specific ordered event has value. No new external data or flexible learner.',
        definitions=dict(
            source='Frozen gold M5/M1 history only. KnownM5ATR14=MetaQuotes rolling true range mean,not Wilder. At a closedM5 half-hour boundary require49contiguous M5 bars and positiveATR.',
            compression='ratio=meanTR(last6closedM5bars)/meanTR(prior42closedM5bars),with no overlap;compressed ifratio<=.60. Freeze maxhigh/minlow oflast6closedbars andcurrentknownATR14. One compressed episode and one independent control episode;no overlapping episodes within either stream.',
            lifetime='Arm online only at half-hour boundary when inactive;never trigger on its arm bar. Episode lasts through arm+60min inclusive. Consumed episode remains in cooldown until that deadline. At an M5 timestamp gap discard both episodes;no bridge or retrospective reconstruction.',
            release='First later M5 close beyond frozenboxhigh+.1frozenATR or belowboxlow-.1frozenATR consumes first break,even if body/hours fail. Continuation requires signedM5body>=.25frozenATR and M5high-low>=1frozenATR. COMPRESSION_RELEASE follows it. BOX_RELEASE_CONTROL uses same rules without compression filter;independent episode cadence is reported,not identical signals.',
            failure='For a compressed episode after its first close break,wait atmost3latercontiguous M5bars and notpast episode expiry. First close strictly back inside frozenbox consumes failure opportunity. Admit reverse direction only if signedbody>=.15frozenATR and closein directionalouter35% ofpositivebarrange. Break neednot have passed continuation quality. No use of future stop/target outcome.',
            hours='Observe/consume all episodes online. New signals only02<=knownfeedhour<18. No named geographical session/UTC claim,or delaying a consumed out-of-hours break into valid hours.',
            money='Reuse v12candidate and exactv7execution:current-signal SL close+/-max(2,1.5currentknownM5ATR14),actualrisk2..20,TP.8actualR,120min/21feedcutoff,signalclose+60sec,Bid/Ask,slip,commission,M1adversefirst,gaps. Same rawsignals forLOW/BASE/STRESS,oneposition,max2actualfills/day10/week.',
            accounting='3newpolicyhypotheses/9costscenarios,including no-compression control. Count all261market-data weeks including zero. No threshold,entrytime,ATR orSL/TP grid after outcomes.'),
        objective=dict(win_rate_percent=[55,60],mean_week=[5,10],zero_empty_market_data_weeks=True),
        statistical_screen=dict(family_size=126,prior_hypotheses=123,min_trades=1000,
            annual_stability='all full2022-2025BASEpositive',costs='BASE/STRESSpositive,family-adjusted monthly-bootstrap lower>0'),
        bootstrap_seed=20261118,bootstrap_resamples=100000,
        sources=[dict(url='https://www.diva-portal.org/smash/get/diva2%3A732318/FULLTEXT02.pdf',
            use='Lundstrom:ORB performance varies with volatility and can fail out of time. Oil/S&P evidence,not gold;full-day volatility states can be known only later. Our causal local compression/release rules are new transfer hypotheses,not a replication or a published preset.'),
                 dict(url='https://www.sciencedirect.com/science/article/pii/S1544612312000438',
            use='HLL2013 primary publisher abstract/search text for ORB concept. Direct publisher fetch403,author PDF timeout. Not used as proof of these parameters.')],
        caveats=['All gold history already inspected;retrospective only. No guarantee of profit.',
                 'Assumed costs,feedclock/DST unverified. Quotes/tick activity are not centralized traded volume.',
                 'No fitting or forcing signals to achieve frequency. Do not rescue a failed branch with thresholds.'])
    path = RUN/'ASSAY_PROTOCOL.json'
    if path.exists():
        assert json.loads(path.read_text(encoding='utf-8'))==protocol,'Frozen compression protocol changed'
    else:
        write_json(path,protocol)
    files = ('scripts/research_scalp_compression_v17.py','scripts/research_scalp_payoff_v12.py',
             'scripts/research_scalp_avwap_v7.py','scripts/research_scalp_weekly_v3.py',
             'scripts/can_ho_tro_scalp_plan.py','scripts/can_ho_tro_scalp_core.py')
    lock = dict(protocol=protocol,start=w.START,end_exclusive=w.END,hypotheses=SPECS,costs=w.COSTS,
        statistical_screen=protocol['statistical_screen'],bootstrap_seed=protocol['bootstrap_seed'],
        bootstrap_resamples=protocol['bootstrap_resamples'],protocol_sha256=sha(path),gold_sha256=sha(w.BASE/'rates.npz'),
        previous_registry_sha256=sha(w.ROOT/'reports/can_ho_tro_scalp/20261101_flows_v16/CUMULATIVE_REGISTRY.json'),
        labels_sha256=sha(v.RUN/'barrier_labels.npz'),implementation_sha256={p:sha(w.ROOT/p) for p in files},
        preserved_fresh={p:sha(w.ROOT/p) for p in w.FRESH_PATHS})
    path = RUN/'EXPERIMENT_LOCK.json'
    if path.exists():
        assert json.loads(path.read_text(encoding='utf-8'))==lock,'Frozen compression implementation changed'
    else:
        write_json(path,lock)
    return lock


@njit(cache=True)
def events(gold,start=w.START,end=w.END):
    a = metaquotes_atr(gold);tr = np.zeros(len(gold));rows = []
    for i in range(1,len(gold)):
        tr[i] = max(gold[i,2]-gold[i,3],abs(gold[i,2]-gold[i-1,4]),abs(gold[i,3]-gold[i-1,4]))
    # Parallel streams:compressed episode shared by release/failure,unfiltered control.
    active = np.zeros(2,np.bool_);phase = np.zeros(2,np.int64)
    armed = np.zeros(2);expires = np.zeros(2);low = np.zeros(2);high = np.zeros(2)
    atr = np.zeros(2);ratio = np.zeros(2);broken = np.zeros(2);direction = np.zeros(2)
    for i in range(48,len(gold)):
        known = gold[i,0]+300
        if known>=end:
            break
        if gold[i,0]-gold[i-1,0]!=300:
            active[:] = False;continue
        eligible_hour = 2*3600<=known%86400<18*3600
        for stream in range(2):
            if active[stream] and known>expires[stream]:
                active[stream] = False
            if not active[stream]:
                if known%1800!=0 or gold[i,0]-gold[i-48,0]!=48*300 or a[i]<=0:
                    continue
                prior = np.mean(tr[i-47:i-5])
                if prior<=0:
                    continue
                compression = np.mean(tr[i-5:i+1])/prior
                if stream==0 and compression>.60:
                    continue
                active[stream] = True;phase[stream] = 1;armed[stream] = known;expires[stream] = known+3600
                low[stream] = np.min(gold[i-5:i+1,3]);high[stream] = np.max(gold[i-5:i+1,2])
                atr[stream] = a[i];ratio[stream] = compression;broken[stream] = 0.;direction[stream] = 0.
                continue
            o,h,l,close = gold[i,1:5];rng = h-l;fa = atr[stream]
            if phase[stream]==1:
                d = 1. if close>high[stream]+.1*fa else (-1. if close<low[stream]-.1*fa else 0.)
                if d!=0:
                    phase[stream] = 2;broken[stream] = known;direction[stream] = d
                    quality = d*(close-o)>=.25*fa and rng>=fa
                    if quality and eligible_hour and start<=known:
                        family = 44 if stream==0 else 46
                        rows.append(np.array([known,float(family),1. if d>0 else 0.,armed[stream],low[stream],high[stream],fa,
                                              ratio[stream],broken[stream],float(i)]))
            elif phase[stream]==2 and stream==0 and known>broken[stream]:
                if known>broken[stream]+900:
                    phase[stream] = 3
                elif low[stream]<close<high[stream]:
                    phase[stream] = 3;d = -direction[stream]
                    outer = ((close-l)/rng if d>0 else (h-close)/rng) if rng>0 else 0.
                    quality = d*(close-o)>=.15*fa and outer>=.65
                    if quality and eligible_hour and start<=known:
                        rows.append(np.array([known,45.,1. if d>0 else 0.,armed[stream],low[stream],high[stream],fa,
                                              ratio[stream],broken[stream],float(i)]))
    out = np.empty((len(rows),10))
    for i in range(len(rows)):
        out[i] = rows[i]
    return out


def candidates(gold,detected):
    a = metaquotes_atr(gold)
    opp = dict(known=gold[:,0]+300,close=gold[:,4],unit=np.maximum(2.,1.5*a),atr=a,index=np.arange(len(gold)))
    rows = []
    for event in detected:
        i = int(event[9]);c = v.make_candidate(opp,i,bool(event[2]),int(event[1]),int(event[3]))
        c[33] = event[7];rows.append(c)
    raw = np.asarray(rows,float).reshape((-1,40))
    if len(raw):
        raw = raw[np.lexsort((raw[:,36],raw[:,1]))]
    return raw


def main():
    parser = argparse.ArgumentParser();parser.add_argument('--freeze-only',action='store_true');args = parser.parse_args()
    lock = freeze()
    if args.freeze_only:
        print('LOCKED before outcomes;3policies/9plannedscenarios',flush=True);return
    source = np.load(w.BASE/'rates.npz');gold = bars_matrix(source['m5']);market = bars_matrix(source['m1'])
    detected = events(gold);raw = candidates(gold,detected)
    np.save(RUN/'events.npy',detected);np.save(RUN/'raw_candidates.npy',raw)
    write_json(RUN/'COVERAGE.json',dict(event_fields=EVENT_FIELDS,
        raw_candidates={name:int(np.sum(raw[:,36]==k)) for k,name in NAMES.items()},
        limitation='Unfiltered control has independent cadence;an ablation,not an identical-entry matched causal effect.'))
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
    print('DONE3newpolicies/9costscenarios;Freshunchanged',flush=True)


if __name__=='__main__':
    main()
