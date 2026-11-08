"""Causal daily GLD creation/pressure hypotheses, executed by the existing scalp engine."""
from __future__ import annotations

import argparse
import json

import numpy as np

from can_ho_tro_scalp_core import bars_matrix
from prepare_can_ho_tro_scalp import sha, write_json
import research_scalp_payoff_v12 as v

w = v.w
RUN = w.ROOT/'reports/can_ho_tro_scalp/20261101_flows_v16'
NAMES = {40:'GLD_CREATION_TREND',41:'GLD_PRESSURE_REVERSAL',42:'GLD_RESIDUAL_FLOW',43:'GLD_PRICE_CONTROL'}
SPECS = [dict(name=name,sources=[k]) for k,name in NAMES.items()]
LAG = 72*3600
STALE = 10*86400
DEADBAND = .0001
DAILY_FIELDS = ['source_date','assumed_available_at','flow1','flow5','price5',
                'residual1','residual5','training_n','last_training_source_date']


def freeze():
    RUN.mkdir(parents=True,exist_ok=True)
    manifest = json.loads((RUN/'GLD_DATA_MANIFEST.json').read_text(encoding='utf-8'))
    assert manifest['source_sha256'] == sha(RUN/'GLD_archive.xlsx')
    assert manifest['normalized_sha256'] == sha(RUN/'GLD_normalized.json')
    assert not manifest['required_window']['gaps_over_four_days']
    protocol = dict(version='flows_v16',start=w.START,end_exclusive=w.END,hypotheses=SPECS,costs=w.COSTS,
        user_steering='55-60% wins,5-10 trades/week,every market-data week active,positive five-year netR;separate MT5 indicator after qualification. FTMO/account rules deferred;Fresh preserved.',
        motivation='Test an external physical-holdings/ETF creation proxy rather than fitting more gold/FX/silver price configurations. Daily flow may contain persistent information or temporary pressure;the direction is not assumed to transfer to a two-hour gold scalp.',
        definitions=dict(
            source='Official GLD Historical Archive XLSX,current vintage,normalized without workbook edits. Use source dates from2020-01-01,positive close/oz-per-share/totaloz/volume;ignore holiday rows,retain missing premiums asNaN. No filling or retrospective repair.',
            shares='Infer shares as total gold ounces/ounces per share to reduce expense-driven declines in raw tonnage. This is an approximate implied share count,not direct observed primary transactions. No basket-size rounding or historical quantization assumption.',
            daily='flow1=log(impliedshares[t]/impliedshares[t-1]);flow5=sum(last5flow1);price5=log(close[t]/close[t-5]). A step longer than4calendar days is missing,not bridged. All5 steps must be finite.',
            residual='Daily flow residual after contemporaneous GLD return,premium fraction,prior-report premium fraction,log(currentvolume/prior20report meanvolume). Prior126complete rows only;standardize from training only,ridge sum-loss penalty10,unpenalized intercept. residual5=sum(last5residuals). No next-day input or gold outcome. This is a causal proxy,not replication of Xu etal decomposition.',
            availability='Assume each source calendar date00:00+72hours on the same naive epoch basis as the gold feed. Latest assumed-published valid primary report,age<=10calendar days. Preserve null premium,so affected residual windows and all matched policies are cash. 72hours is an operational assumption;publication timestamps/revisions and historical feedoffset are unverified.',
            schedule='Exactly closedM5 opportunities known at08:00 and14:00 feed time each day from immutable v12 opportunities. Two fixed separated slots,oneposition,max2actualfills/day10/week. Not named geographical sessions;not chosen on these outcomes.',
            signals='Four policies on the same finite flow5/residual5/price5 availability:follow flow5;oppose flow5;follow residual5;follow price5 control. Buypositive,sellnegative. Absolute logscore>=1bp for each own score;otherwise cash. No forcing or model probability claim.',
            execution='Exactv7engine/v12money:SL signalclose+/-max(2,1.5knownM5ATR14),actualrisk2..20,TP.8actualR,120min/21feedcutoff,signalclose+60sec entry,Bid/Ask,slip,commission,M1adversefirst,gaps. Same rawsignals forLOW/BASE/STRESS;do not retune to rescue results.',
            counting='4new policies/12cost scenarios including matched price control. Keep all failures;count all261market-data weeks including zero. Independent retrospective research,not pristine OOS.'),
        objective=dict(win_rate_percent=[55,60],mean_week=[5,10],zero_empty_market_data_weeks=True),
        statistical_screen=dict(family_size=123,prior_hypotheses=119,min_trades=1000,
            annual_stability='all full2022-2025BASEpositive',costs='BASE/STRESSpositive,family-adjusted monthly-bootstrap lower>0'),
        bootstrap_seed=20261117,bootstrap_resamples=100000,
        sources=[dict(url=manifest['official_page'],use='Archive,units,current publication windows,trade-date versus settlement-date holdings.'),
                 dict(url='https://onlinelibrary.wiley.com/doi/full/10.1111/fima.12396',
                      use='ETF flow components can have different return relations;general ETF evidence is not evidence for GLD/gold scalp. Original decomposition includes anticipated next-day arbitrage;not imported here.')],
        caveats=['Current-vintage archive,not proven point-in-time;lag cannot remove revisions.',
                 'All gold history already inspected;retrospective only. Assumed trading costs/feed clock.',
                 'Positive retrospective R alone cannot confirm edge or guarantee future profit.'])
    path = RUN/'ASSAY_PROTOCOL.json'
    if path.exists():
        assert json.loads(path.read_text(encoding='utf-8')) == protocol, 'Frozen GLD protocol changed'
    else:
        write_json(path,protocol)
    files = ('scripts/research_scalp_flows_v16.py','scripts/extract_scalp_flows_v16.py',
             'scripts/research_scalp_payoff_v12.py','scripts/research_scalp_seasonal_v10.py',
             'scripts/research_scalp_avwap_v7.py','scripts/research_scalp_weekly_v3.py',
             'scripts/can_ho_tro_scalp_plan.py','scripts/can_ho_tro_scalp_core.py')
    lock = dict(protocol=protocol,start=w.START,end_exclusive=w.END,costs=w.COSTS,hypotheses=SPECS,
        statistical_screen=protocol['statistical_screen'],bootstrap_seed=protocol['bootstrap_seed'],
        bootstrap_resamples=protocol['bootstrap_resamples'],protocol_sha256=sha(path),
        source_sha256=sha(RUN/'GLD_archive.xlsx'),normalized_sha256=sha(RUN/'GLD_normalized.json'),
        manifest_sha256=sha(RUN/'GLD_DATA_MANIFEST.json'),gold_sha256=sha(w.BASE/'rates.npz'),
        labels_sha256=sha(v.RUN/'barrier_labels.npz'),
        previous_registry_sha256=sha(w.ROOT/'reports/can_ho_tro_scalp/20261101_flight_v15/CUMULATIVE_REGISTRY.json'),
        implementation_sha256={p:sha(w.ROOT/p) for p in files},preserved_fresh={p:sha(w.ROOT/p) for p in w.FRESH_PATHS})
    path = RUN/'EXPERIMENT_LOCK.json'
    if path.exists():
        assert json.loads(path.read_text(encoding='utf-8')) == lock, 'Frozen GLD implementation changed'
    else:
        write_json(path,lock)
    return lock


def load_reports():
    rows = json.loads((RUN/'GLD_normalized.json').read_text(encoding='utf-8'))['rows']
    result = []
    for r in rows:
        if r['date'] < '2020-01-01':
            continue
        fields = [r[k] for k in ('close','oz_per_share','total_oz','volume')]
        if any(x is None or not np.isfinite(x) or x<=0 for x in fields):
            continue
        premium = np.nan if r['premium_percent'] is None else r['premium_percent']/100
        result.append([r['date_epoch'],*fields[:3],premium,fields[3]])
    reports = np.asarray(result,float)
    assert reports.shape[1] == 6 and np.all(np.diff(reports[:,0])>0)
    return reports


def ridge_predict(x,y,current):
    mean = x.mean(axis=0);scale = x.std(axis=0)
    mean[0] = 0.;scale[0] = 1.;scale[scale<1e-12] = 1.
    z = (x-mean)/scale
    penalty = np.eye(x.shape[1])*10.;penalty[0,0] = 0.
    beta = np.linalg.solve(z.T@z+penalty,z.T@y)
    return float(((current-mean)/scale)@beta),np.r_[mean,scale,beta]


def daily_features(reports):
    n = len(reports);out = np.full((n,len(DAILY_FIELDS)),np.nan)
    out[:,0] = reports[:,0];out[:,1] = reports[:,0]+LAG
    x = np.full((n,5),np.nan);coefficients = np.full((n,15),np.nan)
    shares = reports[:,3]/reports[:,2]
    for i in range(1,n):
        if reports[i,0]-reports[i-1,0] > 4*86400:
            continue
        out[i,2] = np.log(shares[i]/shares[i-1])
        if i>=20 and np.all(np.diff(reports[i-20:i+1,0])<=4*86400):
            x[i] = [1.,np.log(reports[i,1]/reports[i-1,1]),reports[i,4],reports[i-1,4],
                    np.log(reports[i,5]/np.mean(reports[i-20:i,5]))]
        if not np.all(np.isfinite(x[i])):
            continue
        prior = np.where(np.all(np.isfinite(x[:i]),axis=1)&np.isfinite(out[:i,2]))[0][-126:]
        if len(prior)<126:
            continue
        pred,coefficients[i] = ridge_predict(x[prior],out[prior,2],x[i])
        out[i,5] = out[i,2]-pred;out[i,7] = len(prior);out[i,8] = reports[prior[-1],0]
    for i in range(5,n):
        if np.all(np.isfinite(out[i-4:i+1,2])):
            out[i,3] = out[i-4:i+1,2].sum()
            out[i,4] = np.log(reports[i,1]/reports[i-5,1])
        if np.all(np.isfinite(out[i-4:i+1,5])):
            out[i,6] = out[i-4:i+1,5].sum()
    return out,coefficients


def asof_features(known,daily):
    picked = np.full((len(known),len(DAILY_FIELDS)),np.nan)
    positions = np.searchsorted(daily[:,1],known,side='right')-1
    valid = positions>=0
    valid[valid] &= known[valid]-daily[positions[valid],0]<=STALE
    picked[valid] = daily[positions[valid]]
    return picked


def candidates(opp,picked,start=w.START,end=w.END):
    rows = []
    for i,at in enumerate(opp['known']):
        if not start<=at<end or at%86400 not in (8*3600,14*3600):
            continue
        f = picked[i]
        if not np.all(np.isfinite(f[[0,1,3,4,6]])):
            continue
        assert f[1]<=at and at-f[0]<=STALE
        scores = (f[3],-f[3],f[6],f[4])
        for family,score in zip(NAMES,scores):
            if abs(score)<DEADBAND:
                continue
            c = v.make_candidate(opp,i,score>0,family,int(f[0]))
            c[12] = f[1];c[17] = f[1];c[33] = score
            rows.append(c)
    raw = np.asarray(rows,float).reshape((-1,40))
    if len(raw):
        raw = raw[np.lexsort((raw[:,36],raw[:,1]))]
    return raw


def main():
    parser = argparse.ArgumentParser();parser.add_argument('--freeze-only',action='store_true');args = parser.parse_args()
    lock = freeze()
    if args.freeze_only:
        print('LOCKED before gold outcome;4policies/12plannedscenarios',flush=True);return
    reports = load_reports();daily,coefficients = daily_features(reports)
    source = np.load(w.BASE/'rates.npz');gold = bars_matrix(source['m5']);market = bars_matrix(source['m1'])
    opp = v.seasonal.opportunities(gold)
    picked = asof_features(opp['known'],daily);raw = candidates(opp,picked)
    np.savez_compressed(RUN/'flow_inputs.npz',reports=reports,daily=daily,coefficients=coefficients,picked=picked)
    np.save(RUN/'raw_candidates.npy',raw)
    scheduled = ((opp['known']%86400==8*3600)|(opp['known']%86400==14*3600))&(opp['known']>=w.START)&(opp['known']<w.END)
    matched = np.all(np.isfinite(picked[:,[0,1,3,4,6]]),axis=1)
    write_json(RUN/'COVERAGE.json',dict(reports=len(reports),daily_fields=DAILY_FIELDS,
        scheduled=int(scheduled.sum()),common_finite=int((scheduled&matched).sum()),
        unavailable_slots=opp['known'][scheduled&~matched].astype(int).tolist(),
        raw_candidates={name:int(np.sum(raw[:,36]==k)) for k,name in NAMES.items()},
        max_report_age_days=float(np.max((opp['known'][scheduled&matched]-picked[scheduled&matched,0])/86400))))
    w.FAMILIES.update(NAMES);results = []
    for spec in SPECS:
        for cost in w.COSTS:
            trades,rejects = v.execution.run_serial(raw,market,spec,cost)
            metric = w.summarize(trades,market,lock)
            results.append(dict(name=spec['name'],cost=cost['id'],metrics=metric,rejections=rejects))
            write_json(RUN/(spec['name']+'_'+cost['id']+'_trades.json'),dict(trades=trades,rejections=rejects))
            print(spec['name'],cost['id'],metric['n'],round(metric['win_rate'] or 0,2),round(metric['total_r'],2),'R;week',
                  round(metric['frequency']['mean'],2),'empty',len(metric['frequency']['empty_weeks']),flush=True)
    write_json(RUN/'summary.json',dict(rows=results,lock_sha256=sha(RUN/'EXPERIMENT_LOCK.json')))
    assert all(sha(w.ROOT/p)==h for p,h in lock['preserved_fresh'].items())
    print('DONE4newpolicies/12costscenarios;Freshunchanged',flush=True)


if __name__=='__main__':
    main()
