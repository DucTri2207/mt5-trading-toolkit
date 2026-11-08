"""Fixed shallow nonlinear models of price/volatility states with quarterly past-only fitting."""
from __future__ import annotations

import hashlib
import json
import warnings

import joblib
import numpy as np
from numba import njit
import sklearn
from sklearn.experimental import enable_hist_gradient_boosting  # noqa:F401
from sklearn.ensemble import HistGradientBoostingClassifier, HistGradientBoostingRegressor
from threadpoolctl import threadpool_limits

from can_ho_tro_scalp_core import bars_matrix, ema50, metaquotes_atr
from prepare_can_ho_tro_scalp import sha, write_json
import research_scalp_payoff_v12 as v

w=v.w
RUN=w.ROOT/'reports/can_ho_tro_scalp/20261101_state_v13'
NAMES={31:'PRICE_STATE',32:'SEASONAL_PRICE_STATE',33:'INTERMARKET_PRICE_STATE'}
SPECS=[dict(name=name,sources=[f]) for f,name in NAMES.items()]
PARAMS=dict(max_iter=100,learning_rate=.05,max_depth=3,max_leaf_nodes=8,min_samples_leaf=200,
            l2_regularization=10,early_stopping=False,random_state=20261114)
FIELDS=['return5','return15','return30','return60','return240','range60','range240',
        'position60','position240','atr_ratio','log_quote_activity_ratio','body','wick_imbalance',
        'H1_close_EMA50','H1_EMA50_slope6','H1_ATR_M5_ATR']


def freeze():
    RUN.mkdir(parents=True,exist_ok=True)
    lock=dict(version='nonlinear_state_quarterly_v13',start=w.START,end_exclusive=w.END,hypotheses=SPECS,
        costs=w.COSTS,gold_sha256=sha(w.BASE/'rates.npz'),
        prior_registry_sha256=sha(v.RUN/'CUMULATIVE_REGISTRY.json'),labels_sha256=sha(v.RUN/'barrier_labels.npz'),
        fx_features_sha256=sha(w.ROOT/'reports/can_ho_tro_scalp/20261101_intermarket_v9/features.npz'),
        preserved_fresh={p:sha(w.ROOT/p) for p in w.FRESH_PATHS},
        motivation='Calendar/linear lag after-cost models failed. Test whether shallow nonlinear interactions among price location,return horizon and volatility/activity distinguish continuation from reversal. Gold-only/calendar/FX-state ablations identify added information without changing execution.',
        definitions=dict(
            opportunities='Exactly v12 opportunities/labels/money rules. All inputs known at signalclose;no changes toSL/TP/entry delay/hours/caps. Missing required features cause cash,not imputation.',
            price_features='Returns close-to-close5/15/30/60/240min divided by v12unit;60/240min high-low range/unit and close position in range minus.5;ATR14M5 divided by prior48M5ATRmean;log(last6M5tick_volume_mean/prior42M5tick_volume_mean);currentM5body/unit;upperwick-minus-lowerwick/unit;lastclosedH1(close-EMA50)/H1ATR,EMA50slope6/H1ATR,H1ATR/M5ATR. Need49contiguousM5bars,positivevolume,closedH1age<1h/index>=56. Clip every feature[-20,20]. Tick activity is not traded volume.',
            seasonal='Append4 known sin/cos24h/12h terms fromv10. Feedclock only,not verified geographic sessions.',
            intermarket='Append to seasonal state:knownv9USDz15,residualZgold-vs-USD,beta,andUSDz*goldz. Require exact known_at and valid prior-onlyv9calibration;no futureFX fill.',
            estimators='Installedsklearn0.24.2 HistGradientBoostingRegressor(netR) andClassifier(netR>0),independentBUY/SELL. All3policies use same fixed shallow parameters,no grid,no earlystopping/validation split,no model trained on evaluatedquarter.2threads for reproducibility.',
            training='At each calendarquarter start,prior730calendar days,commonfiniteBUY/SELLv12labels and all finite relevant features,labelavailable<quarterstart-7200,min4000pairs/120feed days/26feedISOweeks. Early short-historyquarters may be cash and remain in frequency denominator.',
            entry='PredictednetR>0 andPwin>=.55;selecthigherexpectedR,tieBUY,same rule asv12. Predictions for every valid opportunity,past-onlyfeatures. Actualserialexecutionmax2fills/day10/week,oneposition. BASE-derivedsignals unchanged acrossLOW/BASE/STRESS.',
            persistence='Store eachquartertrainedmodelbundle,trainingarraydigests,provenance andout-of-timeforecasts. Cache accepted only whenidentity+filehash match.',
            counting='3 policyhypotheses/9 costscenarios;fixed internal training fits/labels are not selectable backtest winners.'),
        estimator_params=PARAMS,sklearn_version=sklearn.__version__,
        objective=dict(win_rate_percent=[55,60],mean_week=[5,10],zero_empty_market_data_weeks=True),
        statistical_screen=dict(family_size=115,prior_hypotheses=112,min_trades=1000,
            annual_stability='all full years2022-2025BASEpositive',costs='BASE/STRESSpositive,familymonthlybootstraplower>0'),
        bootstrap_seed=20261114,bootstrap_resamples=100000,
        sources=[dict(url='https://www.rieti.go.jp/jp/publications/dp/17e120.pdf',use='Time-varying gold-market informational efficiency;not proof of forecastability/profits.'),
                 dict(url='https://scikit-learn.org/0.24/modules/generated/sklearn.ensemble.HistGradientBoostingRegressor.html',use='InstalledregressorAPI and shallow/regularization/noearlystopping controls.'),
                 dict(url='https://scikit-learn.org/0.24/modules/generated/sklearn.ensemble.HistGradientBoostingClassifier.html',use='InstalledbinaryclassifierAPI.')],
        caveats=['All goldtargets inspected;logicalquarterlywalkforward is retrospective,not pristineOOS.',
            'More flexible model can overfit despite regularization. Keep everyfailure,nohyperparameter rescue after results.',
            'FTMOconfirmed;userdeferredfundrules/riskuntilpositivebacktest. Costsassumed. Freshunchanged;noorders.'])
    path=RUN/'EXPERIMENT_LOCK.json'
    if path.exists():assert json.loads(path.read_text(encoding='utf-8'))==lock,'Frozen definitions changed'
    else:write_json(path,lock)
    return lock


@njit(cache=True)
def state_features(gold,volume,h1,indices):
    a5=metaquotes_atr(gold);a1=metaquotes_atr(h1);ma=ema50(h1)
    out=np.full((len(indices),16),np.nan);hknown=np.zeros(len(indices))
    for row in range(len(indices)):
        i=indices[row];at=gold[i,0]+300
        if i<48 or gold[i,0]-gold[i-48,0]!=14400 or a5[i]<=0:continue
        k=np.searchsorted(h1[:,0]+3600,at,side='right')-1
        if k<56 or at-h1[k,0]-3600>=3600 or a1[k]<=0:continue
        if np.min(volume[i-48:i+1])<=0:continue
        unit=max(2.,1.5*a5[i]);r=np.zeros(16)
        lags=(1,3,6,12,48)
        for j in range(5):r[j]=(gold[i,4]-gold[i-lags[j],4])/unit
        range_ok=True
        for j,lag in enumerate((12,48)):
            high=np.max(gold[i-lag+1:i+1,2]);low=np.min(gold[i-lag+1:i+1,3]);rng=high-low
            if rng<=0:
                range_ok=False;break
            r[5+j]=rng/unit;r[7+j]=(gold[i,4]-low)/rng-.5
        if not range_ok:continue
        past_atr=np.mean(a5[i-48:i]);past_volume=np.mean(volume[i-47:i-5])
        if past_atr<=0 or past_volume<=0:continue
        r[9]=a5[i]/past_atr;r[10]=np.log(np.mean(volume[i-5:i+1])/past_volume)
        o,high,low,c=gold[i,1:5];r[11]=(c-o)/unit
        r[12]=((high-max(o,c))-(min(o,c)-low))/unit
        r[13]=(h1[k,4]-ma[k])/a1[k];r[14]=(ma[k]-ma[k-6])/a1[k];r[15]=a1[k]/a5[i]
        out[row]=np.minimum(20.,np.maximum(-20.,r));hknown[row]=h1[k,0]+3600
    return out,hknown


def inputs(opp,gold,volume,h1,fx_features):
    base,hknown=state_features(gold,volume,h1,opp['index'].astype(np.int64))
    phase=opp['basis'][:,1:];state=np.c_[base,phase]
    f=fx_features[opp['index'].astype(np.int64)];fx=np.c_[f[:,3],f[:,6],f[:,5],f[:,3]*f[:,4]]
    fx[f[:,0]!=opp['known']]=np.nan;fx=np.clip(fx,-20,20)
    return {31:base,32:state,33:np.c_[state,fx]},hknown


def quarters(start,end):
    for month,_ in v.seasonal.month_bounds(start,end):
        date=w.datetime.fromtimestamp(month,w.timezone.utc)
        if date.month%3!=1:continue
        following=date.replace(year=date.year+1,month=1) if date.month==10 else date.replace(month=date.month+3)
        yield month,int(following.timestamp())


def digest(a):return hashlib.sha256(np.ascontiguousarray(a).tobytes()).hexdigest()


def fit_bundle(x,y):
    sides=[]
    with threadpool_limits(limits=2),warnings.catch_warnings():
        warnings.filterwarnings('ignore',message=r'the `interpolation=` argument to percentile was renamed to `method=`.*',
            category=DeprecationWarning,module=r'sklearn\.ensemble\._hist_gradient_boosting\.binning')
        for side in range(2):
            reg=HistGradientBoostingRegressor(**PARAMS).fit(x,y[:,side])
            classifier=HistGradientBoostingClassifier(**PARAMS).fit(x,(y[:,side]>1e-9).astype(int))
            sides.append((reg,classifier))
    return sides


def predict(bundle,x):
    out=np.empty((len(x),4))
    with threadpool_limits(limits=2):
        for side,(reg,classifier) in enumerate(bundle):
            out[:,side]=reg.predict(x);out[:,2+side]=classifier.predict_proba(x)[:,1]
    return out


def candidates(opp,payoff,available,xs,start=w.START,end=w.END,cache=None,progress=False):
    rows=[];records=[];forecast=np.full((len(opp['known']),3,4),np.nan)
    common=np.all(np.isfinite(payoff),axis=1);known=np.max(available,axis=1)
    if cache is not None:cache.mkdir(exist_ok=True)
    for slot,(family,name) in enumerate(NAMES.items()):
        x=xs[family];finite=np.all(np.isfinite(x),axis=1)
        for quarter,next_quarter in quarters(start,end):
            train=finite&common&(opp['known']>=quarter-730*86400)&(known<quarter-7200)
            test=finite&(opp['known']>=max(start,quarter))&(opp['known']<min(end,next_quarter))
            days=np.unique(opp['known'][train]//86400);weeks=(opp['known'][train]//86400+3)//7
            rec=dict(name=name,quarter=quarter,next_quarter=next_quarter,n=int(train.sum()),days=len(days),weeks=len(np.unique(weeks)),
                last_train_label_known=int(known[train].max()) if train.any() else None,
                first_train_signal=int(opp['known'][train].min()) if train.any() else None)
            if train.sum()<4000 or len(days)<120 or len(np.unique(weeks))<26:
                rec['status']='WARMUP';records.append(rec);continue
            identity=dict(params=PARAMS,sklearn=sklearn.__version__,x_sha256=digest(x[train]),y_sha256=digest(payoff[train]),
                signal_sha256=digest(opp['known'][train]),label_available_sha256=digest(available[train]))
            path=cache/(name+'_'+str(quarter)+'.joblib') if cache is not None else None
            if path is not None and path.exists():
                meta=json.loads(path.with_suffix('.json').read_text(encoding='utf-8'))
                assert meta['identity']==identity and meta['sha256']==sha(path),'Quartermodelcache changed'
                bundle=joblib.load(path)
            else:
                bundle=fit_bundle(x[train],payoff[train])
                if path is not None:
                    joblib.dump(bundle,path,compress=3);write_json(path.with_suffix('.json'),dict(identity=identity,sha256=sha(path)))
            rec.update(status='FITTED',identity=identity,model_file=path.name if path else None)
            if test.any():forecast[test,slot]=predict(bundle,x[test])
            records.append(rec)
            for i in np.where(test)[0]:
                f=forecast[i,slot];eligible=(f[:2]>0)&(f[2:]>=.55)
                if not eligible.any():continue
                side=int(np.argmax(np.where(eligible,f[:2],-np.inf)))
                c=v.make_candidate(opp,i,side==0,family,quarter);c[8]=100*f[2+side];c[33]=f[side];rows.append(c)
            if progress:print('MODEL',name,w.datetime.fromtimestamp(quarter,w.timezone.utc).strftime('%Y-%m'),'train',int(train.sum()),'PASS',flush=True)
    raw=np.asarray(rows,float).reshape((-1,40))
    if len(raw):raw=raw[np.lexsort((raw[:,36],raw[:,1]))]
    return raw,records,forecast


def main():
    lock=freeze();source=np.load(w.BASE/'rates.npz');gold=bars_matrix(source['m5']);h1=bars_matrix(source['h1']);market=bars_matrix(source['m1'])
    labels=np.load(v.RUN/'barrier_labels.npz');keys=('index','known','unit','lag','basis','atr','close');opp={k:labels[k] for k in keys}
    payoff=labels['payoff'];available=labels['available'];fx=np.load(w.ROOT/'reports/can_ho_tro_scalp/20261101_intermarket_v9/features.npz')['features']
    xs,hknown=inputs(opp,gold,source['m5']['tick_volume'].astype(float),h1,fx)
    np.savez_compressed(RUN/'state_inputs.npz',**{str(k):a for k,a in xs.items()},h1_known=hknown)
    raw,models,forecasts=candidates(opp,payoff,available,xs,cache=RUN/'models',progress=True)
    np.save(RUN/'raw_candidates.npy',raw);np.save(RUN/'forecasts.npy',forecasts);write_json(RUN/'QUARTERLY_MODELS.json',models)
    calibration=v.calibration(opp,payoff,forecasts)
    for row in calibration['rows']:row['name']=list(NAMES.values())[list(v.NAMES.values()).index(row['name'])]
    write_json(RUN/'CALIBRATION.json',calibration);w.FAMILIES.update(NAMES);results=[]
    for spec in SPECS:
        for cost in w.COSTS:
            trades,rejects=v.execution.run_serial(raw,market,spec,cost);metric=w.summarize(trades,market,lock)
            metric['sources']={spec['name']:w.metrics(trades)}
            results.append(dict(name=spec['name'],cost=cost['id'],metrics=metric,rejections=rejects))
            write_json(RUN/(spec['name']+'_'+cost['id']+'_trades.json'),dict(trades=trades,rejections=rejects))
            print(spec['name'],cost['id'],metric['n'],round(metric['win_rate'] or 0,2),round(metric['total_r'],2),
                'R;week',round(metric['frequency']['mean'],2),'empty',len(metric['frequency']['empty_weeks']),flush=True)
    write_json(RUN/'summary.json',dict(rows=results,models=len(models),lock_sha256=sha(RUN/'EXPERIMENT_LOCK.json')))
    assert all(sha(w.ROOT/p)==h for p,h in lock['preserved_fresh'].items())
    write_json(RUN/'SOURCE_MANIFEST.json',dict(fresh_unchanged=True,files={p:sha(w.ROOT/p) for p in (
        'scripts/research_scalp_state_v13.py','scripts/research_scalp_payoff_v12.py','scripts/research_scalp_seasonal_v10.py',
        'scripts/research_scalp_avwap_v7.py','scripts/research_scalp_weekly_v3.py','scripts/can_ho_tro_scalp_plan.py')}))
    print('DONE3 hypotheses/9fee scenarios;Freshunchanged',flush=True)


if __name__=='__main__':main()
