"""Silver information for gold: two mechanisms and a matched-coverage model control."""
from __future__ import annotations

import json

import joblib
import numpy as np

from can_ho_tro_scalp_core import bars_matrix, metaquotes_atr
from prepare_can_ho_tro_scalp import sha, write_json
import research_scalp_intermarket_v9 as cross
import research_scalp_state_v13 as state

v=state.v;w=state.w
RUN=w.ROOT/'reports/can_ho_tro_scalp/20261101_metals_v14'
NAMES={34:'SILVER_IMPULSE',35:'METAL_GAP_REVERSION',36:'METAL_STATE_CONTROL',37:'SILVER_AUGMENTED_STATE'}
SPECS=[dict(name=name,sources=[k]) for k,name in NAMES.items()]
MODEL_IDS=(36,37)
METAL_FIELDS=['silver_z15','gold_silver_residual_z15','gold_on_silver_beta15',
              'silver_return60_ATR','silver_ATR_ratio','silver_z15_times_gold_z15']


def freeze_protocol():
    RUN.mkdir(parents=True,exist_ok=True)
    protocol=dict(version='metals_v14',start=w.START,end_exclusive=w.END,symbol='XAGUSD',
        hypotheses=SPECS,costs=w.COSTS,
        user_steering='FTMO;positive after-cost five-year scalp R first. Fund/account rules deferred. Fresh preserved.',
        motivation='Test a new observable market,not another threshold grid on gold-only states. Silver may carry common precious-metal innovations or reveal a temporary gold response gap. Direction of price discovery is an empirical question;gold can lead silver,and no stable price-ratio cointegration is presumed.',
        definitions=dict(
            data='Collect XAGUSD M5 from existing terminal,2021-01-01 to before2026-10-25. Exact timestamp intersection with frozen gold;no fill,nearest-match or future quote. Verify three sampled gold days against frozen feed. Temporary MarketWatch selection may be restored after read-only collection;no account/login/order operations.',
            opportunities='Exactly the immutable v12 half-hour opportunities,closedM5,02<=knownfeedhour<18,signalclose+60sec execution. Rules use silver/gold15 features. Models require common finite gold/FX/silver inputs.',
            calibration='Reuse v9 causal rolling-return calibration with log(silverclose) replacing USD basket:gold15=a+beta*silver15,prior60calendar days,minimum5000validpairs,calibrationendsatleast15minbefore signal. No claim of cointegration of levels. Same formulas for zsilver,zgold and standardized regression residual.',
            impulse='At the first half-hour opportunity crossing abs(silver_z15)>=2,buygold forpositive silver impulse,sellfornegative. Re-arm below2 or after missing/noncontiguous opportunity (>1800sec). No gold direction filter.',
            gap='At the first opportunity crossing abs(gold_silver_residual_z15)>=2 withbeta>0,fade residual:buygoldwhen residualnegative,sellwhenpositive. Same re-arm. Gold leg only;not a hedged pair,not EFP.',
            model_features='Gold+seasonal+USD24fields fromv13,plus6metal fields:standardizedsilver15,gold-silverresidual15,beta15,silver60pricechange/knownsilverATR14,silverATR14/prior48M5ATRmean,zsilver15*zgold15. Silver needs49contiguousM5bars andpositiveATR. Clip addedfields[-20,20].',
            matched_control='METAL_STATE_CONTROL uses only24gold/seasonal/FXfields but has exactly the same commonfinite training and forecast rows as the30field augmented model. Both retrained independently with identical fixedv13params and payoff labels. Control is counted as a new policy,not hidden selection.',
            training='Unchangedv13:quarterlyprior730days,min4000labelpairs/120days/26weeks,commonfiniteBUY/SELLv12labels,labelavailable<quarterstart-7200. Store training digests,model hashes and all held-period forecasts.',
            model_entry='Unchanged E(netR)>0 andP(netR>0)>=.55;selecthigherE,tieBUY. No change to depths/trees/penalty/probability gate.',
            execution='Exactv7engine/v12money:SL signalclose +/-max(2,1.5goldM5ATR14),actualrisk2..20,TP.8actualR,120min/21feedcutoff,Bid/Ask,slip,commission,M1adversefirst,gaps,oneposition,max2fills/feedday10/feedweek. BASE-derivedsignalsusedforLOW/BASE/STRESS. No forced entries.',
            accounting='4newpolicyhypotheses/12costscenarios,includingmatchedcontrol;allfailuresretained. 261marketdataweeksincludingzero. Comparison/calibrationisdescriptive,notanextraselectablepolicy.'),
        estimator_params=state.PARAMS,
        objective=dict(win_rate_percent=[55,60],mean_week=[5,10],zero_empty_market_data_weeks=True),
        statistical_screen=dict(family_size=119,prior_hypotheses=115,min_trades=1000,
            annual_stability='allfull2022-2025BASEpositive',costs='BASE/STRESSpositive,familymonthlybootstraplower>0'),
        bootstrap_seed=20261115,bootstrap_resamples=100000,
        sources=[dict(url='https://www.efmaefm.org/0EFMAMEETINGS/EFMA%20ANNUAL%20MEETINGS/2010-Aarhus%20old/EFMA2010_0378_fullpaper.pdf',use='Gold/silverprice-discoverycanberegimedependent;long-termCOMEXevidenceisnotproofsilverleadsCFDgoldM5.'),
                 dict(url='https://arxiv.org/abs/1111.7103',use='Lead/lagcanvarybyevent/time;forecastaccuracymaynotbeatspread. Notgold-specificproof.'),
                 dict(url='https://journals.plos.org/plosone/article?id=10.1371/journal.pone.0174232',use='Intradayprecious-metalperiodicityandown-return/volatilityrelationships;notproofsilverleadsgold.')],
        caveats=['Allgoldhistoryalreadyinspected;retrospective,notpristineOOS.','Assumedcosts;feedclock/DSTunverified. SilverisbrokerCFDquotes,notcentralizedfutures/orderflow.',
                 'No guarantee of profit. No hyperparameter/threshold rescue after these results.'])
    path=RUN/'ASSAY_PROTOCOL.json'
    if path.exists():assert json.loads(path.read_text(encoding='utf-8'))==protocol,'Frozen metal protocol changed'
    else:write_json(path,protocol)
    return protocol


def freeze():
    protocol=freeze_protocol();manifest=json.loads((RUN/'SILVER_DATA_MANIFEST.json').read_text(encoding='utf-8'))
    assert manifest['protocol_sha256']==sha(RUN/'ASSAY_PROTOCOL.json')
    assert manifest['data_sha256']==sha(RUN/'silver_rates.npz')
    assert all(r['exact_ohlc_time'] for r in manifest['gold_feed_compatibility'])
    lock=dict(protocol=protocol,start=w.START,end_exclusive=w.END,hypotheses=SPECS,costs=w.COSTS,
        statistical_screen=protocol['statistical_screen'],bootstrap_seed=protocol['bootstrap_seed'],bootstrap_resamples=protocol['bootstrap_resamples'],
        gold_sha256=sha(w.BASE/'rates.npz'),silver_sha256=sha(RUN/'silver_rates.npz'),
        labels_sha256=sha(v.RUN/'barrier_labels.npz'),v13_features_sha256=sha(state.RUN/'state_inputs.npz'),
        implementation_sha256={p:sha(w.ROOT/p) for p in ('scripts/research_scalp_metals_v14.py',
            'scripts/collect_scalp_metals_v14.py','scripts/research_scalp_state_v13.py',
            'scripts/research_scalp_intermarket_v9.py','scripts/research_scalp_payoff_v12.py',
            'scripts/research_scalp_avwap_v7.py','scripts/research_scalp_weekly_v3.py','scripts/can_ho_tro_scalp_plan.py')},
        previous_registry_sha256=sha(state.RUN/'CUMULATIVE_REGISTRY.json'),
        protocol_sha256=sha(RUN/'ASSAY_PROTOCOL.json'),preserved_fresh={p:sha(w.ROOT/p) for p in w.FRESH_PATHS})
    path=RUN/'EXPERIMENT_LOCK.json'
    if path.exists():assert json.loads(path.read_text(encoding='utf-8'))==lock,'Frozen metal lock changed'
    else:write_json(path,lock)
    return lock


def metal_inputs(gold,silver,opp,control):
    # Exact open timestamps imply identical M5 close availability; missing stays NaN.
    positions=np.searchsorted(silver[:,0],gold[:,0]);ok=positions<len(silver)
    ok[ok]&=silver[positions[ok],0]==gold[ok,0]
    logclose=np.full(len(gold),np.nan);logclose[ok]=np.log(silver[positions[ok],4])
    calibrated=cross.features(gold,logclose)
    atr=metaquotes_atr(silver);extra=np.full((len(opp['known']),6),np.nan)
    picked=calibrated[opp['index'].astype(np.int64)]
    for row,i in enumerate(opp['index'].astype(np.int64)):
        if not ok[i] or picked[row,0]!=opp['known'][row]:continue
        k=positions[i]
        if k<48 or silver[k,0]-silver[k-48,0]!=14400 or atr[k]<=0:continue
        prior=np.mean(atr[k-48:k])
        if prior<=0:continue
        extra[row]=np.clip([picked[row,3],picked[row,6],picked[row,5],
            (silver[k,4]-silver[k-12,4])/atr[k],atr[k]/prior,picked[row,3]*picked[row,4]],-20,20)
    matched=np.all(np.isfinite(extra),axis=1)&np.all(np.isfinite(control),axis=1)
    base=control.copy();augmented=np.c_[base,extra]
    base[~matched]=np.nan;augmented[~matched]=np.nan
    return {36:base,37:augmented},picked,calibrated,dict(gold_rows=len(gold),exact_silver_rows=int(ok.sum()),
        missing_silver_on_gold=int((~ok).sum()),opportunities=len(extra),matched_model_rows=int(matched.sum()))


def rule_candidates(opp,picked,start=w.START,end=w.END):
    rows=[];active=[False,False];previous=0
    for i,at in enumerate(opp['known']):
        if previous and at-previous!=1800:active=[False,False]
        previous=at
        if picked[i,0]!=at or not np.all(np.isfinite(picked[i])):
            active=[False,False];continue
        z,residual,beta=picked[i,3],picked[i,6],picked[i,5]
        eligible=[abs(z)>=2,abs(residual)>=2 and beta>0]
        for slot,family in enumerate((34,35)):
            crossing=eligible[slot] and not active[slot];active[slot]=eligible[slot]
            if not crossing or not start<=at<end:continue
            buy=z>0 if family==34 else residual<0
            c=v.make_candidate(opp,i,buy,family);c[33]=z if family==34 else residual;rows.append(c)
    return np.asarray(rows,float).reshape((-1,40))


def model_candidates(opp,payoff,available,xs,start=w.START,end=w.END,cache=None,progress=False):
    rows=[];records=[];forecast=np.full((len(opp['known']),2,4),np.nan)
    common=np.all(np.isfinite(payoff),axis=1);known=np.max(available,axis=1)
    if cache is not None:cache.mkdir(exist_ok=True)
    for slot,family in enumerate(MODEL_IDS):
        name=NAMES[family];x=xs[family];finite=np.all(np.isfinite(x),axis=1)
        for quarter,next_quarter in state.quarters(start,end):
            train=finite&common&(opp['known']>=quarter-730*86400)&(known<quarter-7200)
            test=finite&(opp['known']>=max(start,quarter))&(opp['known']<min(end,next_quarter))
            days=np.unique(opp['known'][train]//86400);weeks=(opp['known'][train]//86400+3)//7
            rec=dict(name=name,quarter=quarter,next_quarter=next_quarter,n=int(train.sum()),days=len(days),weeks=len(np.unique(weeks)),
                last_train_label_known=int(known[train].max()) if train.any() else None)
            if train.sum()<4000 or len(days)<120 or len(np.unique(weeks))<26:
                rec['status']='WARMUP';records.append(rec);continue
            identity=dict(params=state.PARAMS,sklearn=state.sklearn.__version__,x_sha256=state.digest(x[train]),y_sha256=state.digest(payoff[train]),
                signal_sha256=state.digest(opp['known'][train]),label_available_sha256=state.digest(available[train]))
            path=cache/(name+'_'+str(quarter)+'.joblib') if cache is not None else None
            if path is not None and path.exists():
                meta=json.loads(path.with_suffix('.json').read_text(encoding='utf-8'))
                assert meta['identity']==identity and meta['sha256']==sha(path),'Metal model cache changed'
                bundle=joblib.load(path)
            else:
                bundle=state.fit_bundle(x[train],payoff[train])
                if path is not None:
                    joblib.dump(bundle,path,compress=3);write_json(path.with_suffix('.json'),dict(identity=identity,sha256=sha(path)))
            rec.update(status='FITTED',identity=identity,model_file=path.name if path else None);records.append(rec)
            if test.any():forecast[test,slot]=state.predict(bundle,x[test])
            for i in np.where(test)[0]:
                f=forecast[i,slot];eligible=(f[:2]>0)&(f[2:]>=.55)
                if not eligible.any():continue
                side=int(np.argmax(np.where(eligible,f[:2],-np.inf)))
                c=v.make_candidate(opp,i,side==0,family,quarter);c[8]=100*f[2+side];c[33]=f[side];rows.append(c)
            if progress:print('MODEL',name,w.datetime.fromtimestamp(quarter,w.timezone.utc).strftime('%Y-%m'),'train',int(train.sum()),flush=True)
    raw=np.asarray(rows,float).reshape((-1,40))
    if len(raw):raw=raw[np.lexsort((raw[:,36],raw[:,1]))]
    return raw,records,forecast


def main():
    lock=freeze();source=np.load(w.BASE/'rates.npz');gold=bars_matrix(source['m5']);market=bars_matrix(source['m1'])
    silver=bars_matrix(np.load(RUN/'silver_rates.npz')['rates']);labels=np.load(v.RUN/'barrier_labels.npz')
    opp={k:labels[k] for k in ('index','known','unit','lag','basis','atr','close')}
    control=np.load(state.RUN/'state_inputs.npz')['33']
    xs,picked,calibrated,coverage=metal_inputs(gold,silver,opp,control)
    np.savez_compressed(RUN/'metal_inputs.npz',**{str(k):a for k,a in xs.items()},picked=picked,calibrated=calibrated)
    write_json(RUN/'COVERAGE.json',coverage)
    rules=rule_candidates(opp,picked)
    models,records,forecast=model_candidates(opp,labels['payoff'],labels['available'],xs,cache=RUN/'models',progress=True)
    raw=np.concatenate((rules,models));raw=raw[np.lexsort((raw[:,36],raw[:,1]))]
    np.save(RUN/'raw_candidates.npy',raw);np.save(RUN/'forecasts.npy',forecast);write_json(RUN/'QUARTERLY_MODELS.json',records)
    w.FAMILIES.update(NAMES);results=[]
    for spec in SPECS:
        for cost in w.COSTS:
            trades,rejects=v.execution.run_serial(raw,market,spec,cost);metric=w.summarize(trades,market,lock)
            results.append(dict(name=spec['name'],cost=cost['id'],metrics=metric,rejections=rejects))
            write_json(RUN/(spec['name']+'_'+cost['id']+'_trades.json'),dict(trades=trades,rejections=rejects))
            print(spec['name'],cost['id'],metric['n'],round(metric['win_rate'] or 0,2),round(metric['total_r'],2),'R;week',
                round(metric['frequency']['mean'],2),'empty',len(metric['frequency']['empty_weeks']),flush=True)
    write_json(RUN/'summary.json',dict(rows=results,models=len(records),lock_sha256=sha(RUN/'EXPERIMENT_LOCK.json')))
    assert all(sha(w.ROOT/p)==h for p,h in lock['preserved_fresh'].items())
    write_json(RUN/'SOURCE_MANIFEST.json',dict(fresh_unchanged=True,files={p:sha(w.ROOT/p) for p in (
        'scripts/research_scalp_metals_v14.py','scripts/research_scalp_state_v13.py','scripts/research_scalp_intermarket_v9.py',
        'scripts/research_scalp_payoff_v12.py','scripts/research_scalp_avwap_v7.py','scripts/can_ho_tro_scalp_plan.py')}))
    print('DONE4hypotheses/12costscenarios;Freshunchanged',flush=True)


if __name__=='__main__':main()
