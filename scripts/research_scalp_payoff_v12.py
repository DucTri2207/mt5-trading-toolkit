"""Monthly past-only prediction of actual after-cost barrier payoff and win rate."""
from __future__ import annotations

from collections import Counter
import hashlib
import inspect
import json

import numpy as np

from can_ho_tro_scalp_core import bars_matrix
from prepare_can_ho_tro_scalp import sha, write_json
import research_scalp_weekly_v3 as w
import research_scalp_avwap_v7 as execution
import research_scalp_seasonal_v10 as seasonal

RUN = w.ROOT/'reports/can_ho_tro_scalp/20261101_payoff_v12'
NAMES = {28: 'PAYOFF_SEASONAL_DRIFT', 29: 'PAYOFF_SEASONAL_RESPONSE', 30: 'PAYOFF_GLOBAL_CONTROL'}
SPECS = [dict(name=name, sources=[f]) for f, name in NAMES.items()]


def freeze():
    RUN.mkdir(parents=True, exist_ok=True)
    lock = dict(version='payoff_monthly_v12', start=w.START, end_exclusive=w.END,
        hypotheses=SPECS, costs=w.COSTS, data_sha256=sha(w.BASE/'rates.npz'),
        previous_registry_sha256=sha(w.ROOT/'reports/can_ho_tro_scalp/20261101_round_v11/CUMULATIVE_REGISTRY.json'),
        preserved_fresh={p: sha(w.ROOT/p) for p in w.FRESH_PATHS},
        user_steering='FTMO confirmed;first find positive after-cost five-year R while retaining requested scalp frequency/win criteria. Detailed fund/account risk assessment deferred by user.',
        motivation='v10 predicted fixed-horizon price change but executed nonlinear stop/target payoffs. Test that measurable target mismatch directly with the same low-dimensional feature families and the same fixed execution rules.',
        definitions=dict(
            opportunities='Unchanged v10:closed M5 ending every30min,02<=known feed hour<18,7 contiguous M5 closes,knownATR14;unit=max2,1.5ATR;lag30clipped[-5,5].',
            features='Same v10 families:5 Fourier/calendar terms;10 calendar/lag interaction terms;2 global intercept/lag terms. No new hours,threshold,SL/TP or feature grid.',
            labels='For every opportunity,simulate independent BUY and SELL hypothetical trades using the exact unchanged v7 BASE after-cost money engine. SL at signalclose-direction*unit;min2/max20 actual risk,TP.8actualR,120min/21feedcutoff,signalclose+60sec entry,adverse-first M1 Bid/Ask,spread.30/slip.01/commissionprice.07. These are internal learning labels,not concurrently executed portfolios or separately selectable strategies.',
            availability='Use finite CLOSED labels only,common BUY/SELL coverage. Both labels available_at=max(actualexit,scheduledsignal+7320),including maximum allowed60sec fill delay. Monthly training cutoff:available_at<monthstart-7200. No current/future test label can affect entry.',
            estimator='Separate netR ridge and positive-netR logistic regression for BUY/SELL. Both standardize from training only,unpenalized intercept,fixed nonintercept sum-loss penalty100. Logistic Newton max50,backtracking,max step objective decrease;fail lab if unconverged.',
            train='Monthly at monthstart,prior365calendar days,min2000 common labels/120feed days/26feed ISO weeks. No optimization on the evaluated month. Store all coefficients/counts/latest-label provenance.',
            signal='Eligible direction requires predicted netR>0 AND predicted P(netR>0)>=.55. If both eligible,choose higher predicted netR,tieBUY. First eligible online opportunities with unchanged occupancy/caps;no hindsight top2 perday. Same BASE-derived signals at all costs.',
            execution='Exactly same stop/target/latency/risk/hours as learning labels. Independent lab,oneposition,max2 actual fills/feedday,max10/feed ISO week,no forced entry. v7 simulator directly reused;no new fast money engine.',
            diagnostics='Report out-of-time win calibration/Brier and expected-v-realized netR across all held-period opportunity labels,not just accepted trades. These diagnostics do not change strategy or thresholds.',
            counting='3 new policy hypotheses,9 cost scenarios;hypothetical training labels are internal fixed algorithm inputs,not additional selected strategy backtests.'),
        objective=dict(win_rate_percent=[55,60],mean_week=[5,10],zero_empty_market_data_weeks=True),
        statistical_screen=dict(family_size=112,prior_hypotheses=109,min_trades=1000,
            annual_stability='all full years2022-2025 BASE positive',
            costs='BASE/STRESS positive with family-adjusted monthly-bootstrap lower>0'),
        bootstrap_seed=20261113, bootstrap_resamples=100000,
        sources=[dict(url='https://www.rieti.go.jp/jp/publications/dp/17e120.pdf',
            use='Time-varying informational efficiency motivates seasonal-response family;not these rules or profitability.'),
            dict(local='reports/can_ho_tro_scalp/20261101_seasonal_v10/EXPERIMENT_LOCK.json',
            use='Declared mismatch between fixed-hold training labels and executable SL/TP;all v10 after-cost results negative.')],
        caveats=['All historical gold targets inspected;monthly past-only fitting remains retrospective,not pristine OOS.',
            'Forecast probabilities are estimates,not a promise of realized win rate. Calibration checked on held months.',
            'Assumed costs and feed clock,not account verified. FTMO rule/position-sizing phase explicitly deferred. Fresh unchanged,no broker orders.'])
    path = RUN/'EXPERIMENT_LOCK.json'
    if path.exists():
        assert json.loads(path.read_text(encoding='utf-8')) == lock, 'Frozen definitions changed'
    else:
        write_json(path, lock)
    return lock


def make_candidate(opp, index, buy, family=28, model_month=None):
    at = int(opp['known'][index]); close = float(opp['close'][index]); d = 1 if buy else -1
    source = at-300 if model_month is None else model_month
    source_known = at if model_month is None else model_month
    stop = close-d*opp['unit'][index]; c = np.zeros(40)
    c[:8] = [at-300,at+60,int(buy),source,10+family,0,0,at]
    c[8:18] = [50,0,close,close,source_known,at-300,stop,source,close,source_known]
    c[18:23] = [opp['atr'][index],stop,stop,close,close]
    c[34:40] = [opp['index'][index],0,family,at,0,0]
    return c


def build_labels(opp, market):
    n = len(opp['known']); payoff = np.full((n,2),np.nan); available = np.zeros((n,2),np.int64)
    risk = np.full((n,2),np.nan); outcome = Counter()
    w.FAMILIES.update(NAMES)
    for i in range(n):
        for side,buy in enumerate((True,False)):
            c = make_candidate(opp,i,buy)
            r = execution.simulate(i,c,market,w.COSTS[1]); outcome[r['state']+':'+r['reason']] += 1
            if r['state'] == 'CLOSED':
                payoff[i,side] = r['r'];risk[i,side] = r['risk']
                available[i,side] = max(r['exit_time'],int(opp['known'][i])+7320)
        if (i+1)%4000 == 0:
            print('LABELS',i+1,'/',n,'opportunities;exact money engine',flush=True)
    return payoff,available,risk,dict(outcome)


def logistic_fit(x,y):
    mean=x.mean(axis=0);scale=x.std(axis=0);mean[0]=0.;scale[0]=1.;scale[scale<1e-12]=1.
    z=(x-mean)/scale;p0=float(np.clip(np.mean(y),1e-6,1-1e-6));beta=np.zeros(x.shape[1]);beta[0]=np.log(p0/(1-p0))
    penalty=np.eye(x.shape[1])*100.;penalty[0,0]=0.
    objective=lambda b: float(np.sum(np.logaddexp(0,z@b)-y*(z@b))+.5*b@penalty@b)
    converged=False;iterations=0
    for iteration in range(50):
        linear=z@beta;prob=1/(1+np.exp(-np.clip(linear,-35,35)))
        gradient=z.T@(prob-y)+penalty@beta
        if np.max(np.abs(gradient))<1e-6:
            converged=True;iterations=iteration;break
        hessian=z.T@((prob*(1-prob))[:,None]*z)+penalty
        delta=np.linalg.solve(hessian,gradient);step=1.;before=objective(beta)
        for _ in range(30):
            proposed=beta-step*delta
            if objective(proposed)<=before+1e-10:
                break
            step*=.5
        beta=proposed;iterations=iteration+1
        if np.max(np.abs(step*delta))<1e-9:
            converged=True;break
    assert converged,'Logistic estimator did not converge;do not use incomplete model'
    return dict(mean=mean,scale=scale,beta=beta,iterations=iterations,converged=converged)


def logistic_predict(model,x):
    linear=((x-model['mean'])/model['scale'])@model['beta']
    return 1/(1+np.exp(-np.clip(linear,-35,35)))


def candidates(opp,payoff,available,start=w.START,end=w.END):
    rows=[];models=[];forecasts=np.full((len(opp['known']),3,4),np.nan)
    common=np.all(np.isfinite(payoff),axis=1);last_known=np.max(available,axis=1)
    for slot,(family,name) in enumerate(NAMES.items()):
        x=seasonal.design(opp,family-7)
        for month,next_month in seasonal.month_bounds(start,end):
            train=(common&(opp['known']>=month-365*86400)&(last_known<month-7200))
            test=(opp['known']>=max(start,month))&(opp['known']<min(end,next_month))
            days=np.unique(opp['known'][train]//86400);weeks=(opp['known'][train]//86400+3)//7
            record=dict(name=name,month=month,next_month=next_month,n=int(train.sum()),days=len(days),
                weeks=len(np.unique(weeks)),last_train_label_known=int(last_known[train].max()) if train.any() else None,
                first_train_signal=int(opp['known'][train].min()) if train.any() else None)
            if train.sum()<2000 or len(days)<120 or len(np.unique(weeks))<26:
                record['status']='WARMUP';models.append(record);continue
            record.update(status='FITTED',sides=[])
            for side,buy in enumerate((True,False)):
                target=payoff[train,side];net=seasonal.fit(x[train],target,weeks)
                win=logistic_fit(x[train],(target>1e-9).astype(float))
                er,_=seasonal.predict(net,x[test]);prob=logistic_predict(win,x[test])
                forecasts[test,slot,side]=er;forecasts[test,slot,2+side]=prob
                serialize=lambda m:{k:a.tolist() if isinstance(a,np.ndarray) else a for k,a in m.items()}
                record['sides'].append(dict(buy=buy,train_netR_mean=float(target.mean()),train_win=float(np.mean(target>1e-9)),
                    net=serialize(net),win=serialize(win)))
            models.append(record)
            for i in np.where(test)[0]:
                f=forecasts[i,slot];eligible=(f[:2]>0)&(f[2:]>=.55)
                if not np.any(eligible):
                    continue
                score=np.where(eligible,f[:2],-np.inf);side=int(np.argmax(score))
                c=make_candidate(opp,i,side==0,family,month);c[8]=f[2+side]*100;c[33]=f[side]
                rows.append(c)
    raw=np.asarray(rows,dtype=float).reshape((-1,40))
    if len(raw):raw=raw[np.lexsort((raw[:,36],raw[:,1]))]
    return raw,models,forecasts


def calibration(opp,payoff,forecasts):
    rows=[]
    for slot,(family,name) in enumerate(NAMES.items()):
        for side,buy in enumerate((True,False)):
            p=forecasts[:,slot,2+side];er=forecasts[:,slot,side]
            keep=np.isfinite(p)&np.isfinite(payoff[:,side]);p=p[keep];er=er[keep];r=payoff[keep,side];y=(r>1e-9).astype(float)
            bins=[]
            for lower,upper in ((0.,.5),(.5,.55),(.55,.6),(.6,.7),(.7,1.000001)):
                k=(p>=lower)&(p<upper)
                bins.append(dict(lower=lower,upper=min(1.,upper),n=int(k.sum()),
                    predicted_win=float(p[k].mean()) if k.any() else None,
                    observed_win=float(y[k].mean()) if k.any() else None,
                    predicted_netR=float(er[k].mean()) if k.any() else None,
                    observed_netR=float(r[k].mean()) if k.any() else None))
            rows.append(dict(name=name,buy=buy,n=len(p),brier=float(np.mean((p-y)**2)) if len(p) else None,bins=bins))
    return dict(label='Retrospective held-month calibration,all opportunity sides;not independent OOS or an executed portfolio',rows=rows)


def main():
    lock=freeze();data=np.load(w.BASE/'rates.npz');gold=bars_matrix(data['m5']);market=bars_matrix(data['m1'])
    opp=seasonal.opportunities(gold);path=RUN/'barrier_labels.npz';meta=RUN/'LABEL_MANIFEST.json'
    identity=dict(gold_sha256=lock['data_sha256'],make_candidate_sha256=hashlib.sha256(inspect.getsource(make_candidate).encode()).hexdigest(),
        sources={p:sha(w.ROOT/p) for p in ('scripts/research_scalp_weekly_v3.py','scripts/research_scalp_avwap_v7.py','scripts/can_ho_tro_scalp_plan.py','scripts/research_scalp_seasonal_v10.py')},
        cost=w.COSTS[1],label_protocol=lock['definitions']['labels'],availability=lock['definitions']['availability'])
    if path.exists():
        m=json.loads(meta.read_text(encoding='utf-8'));assert m['identity']==identity and m['sha256']==sha(path),'Label cache changed'
        saved=np.load(path);payoff=saved['payoff'];available=saved['available'];risk=saved['risk']
    else:
        payoff,available,risk,outcome=build_labels(opp,market)
        np.savez_compressed(path,payoff=payoff,available=available,risk=risk,**opp)
        write_json(meta,dict(identity=identity,sha256=sha(path),opportunities=len(opp['known']),hypothetical_sides=2*len(opp['known']),
            finite_closed=int(np.isfinite(payoff).sum()),outcomes=outcome,exact_existing_money_engine=True))
    raw,models,forecasts=candidates(opp,payoff,available)
    np.save(RUN/'raw_candidates.npy',raw);np.save(RUN/'forecasts.npy',forecasts)
    write_json(RUN/'MONTHLY_MODELS.json',models);write_json(RUN/'CALIBRATION.json',calibration(opp,payoff,forecasts))
    w.FAMILIES.update(NAMES);results=[]
    for spec in SPECS:
        for cost in w.COSTS:
            trades,rejects=execution.run_serial(raw,market,spec,cost);metric=w.summarize(trades,market,lock)
            metric['sources']={spec['name']:w.metrics(trades)}
            results.append(dict(name=spec['name'],cost=cost['id'],metrics=metric,rejections=rejects))
            write_json(RUN/(spec['name']+'_'+cost['id']+'_trades.json'),dict(trades=trades,rejections=rejects))
            print(spec['name'],cost['id'],metric['n'],round(metric['win_rate'] or 0,2),round(metric['total_r'],2),
                'R;week',round(metric['frequency']['mean'],2),'empty',len(metric['frequency']['empty_weeks']),flush=True)
    write_json(RUN/'summary.json',dict(rows=results,models=len(models),lock_sha256=sha(RUN/'EXPERIMENT_LOCK.json')))
    assert all(sha(w.ROOT/p)==h for p,h in lock['preserved_fresh'].items())
    write_json(RUN/'SOURCE_MANIFEST.json',dict(fresh_unchanged=True,files={p:sha(w.ROOT/p) for p in (
        'scripts/research_scalp_payoff_v12.py','scripts/research_scalp_seasonal_v10.py','scripts/research_scalp_avwap_v7.py','scripts/research_scalp_weekly_v3.py','scripts/can_ho_tro_scalp_plan.py')}))
    print('DONE3 hypotheses/9 fee scenarios;Fresh unchanged',flush=True)


if __name__=='__main__':main()
