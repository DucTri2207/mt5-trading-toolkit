"""Gold after observed equity losses: fast shock versus gradual four-hour decline."""
from __future__ import annotations

import json

import numpy as np
from numba import njit

from can_ho_tro_scalp_core import bars_matrix,metaquotes_atr
from collect_scalp_intermarket_v9 import stamp,validate
from prepare_can_ho_tro_scalp import sha,write_json
import research_scalp_payoff_v12 as v

w=v.w
RUN=w.ROOT/'reports/can_ho_tro_scalp/20261101_flight_v15'
NAMES={38:'FAST_EQUITY_FLIGHT',39:'GRADUAL_EQUITY_FLIGHT'}
SPECS=[dict(name=name,sources=[k]) for k,name in NAMES.items()]


def freeze_protocol():
    RUN.mkdir(parents=True,exist_ok=True)
    protocol=dict(version='equity_flight_v15',start=w.START,end_exclusive=w.END,hypotheses=SPECS,costs=w.COSTS,
        motivation='A new flow mechanism:flight to gold after equity losses. Published work finds a fast gold reaction;that may already be exhausted before a completed-bar+60sec entry. Test delayed executable R directly,including a separate gradual-decline hypothesis.',
        definitions=dict(
            data='US500M5 from same existingMT5feed,2021Jan to before2026Oct25. Metadata must be Indexes/US SPX500. BrokerCFD proxy,not officialcashindex or actualfrontfuture. Exacttimestampswithfrozengold,no fill;verify3golddays;restore MarketWatchvisibility,noaccounts/login/orders.',
            signal='EveryclosedM5 with7contiguousgoldbars andknownpositiveATR14;02<=knownfeedhour<18. Equity closes exactbothcurrentandlag. Need2contiguousequity/goldbars forfast,49for4h. Missing resets crossingstate.',
            fast='BUYgold on first crossing of simpleUS500close-to-close5minreturn<=-.0075 (-.75%). Threshold from authorsCFE2018conferenceabstract,not a claim to replicate finalpaper. Re-arm onlyabove threshold ordata gap.',
            gradual='BUYgold on first crossing of simpleUS500close-to-close240minreturn<=-.01 (-1%). This is a separate proposed operationalization of gradual equity decline;not an author-published trading rule. Re-arm onlyabove threshold ordata gap. No use of futureendofday classification.',
            state='Consume crossings even outsideentryhours/evaluationdates. Reset onmissingcurrent/laggedquote ornoncontiguousM5time. No repeatedtradeswhileconditionstaysactive.',
            execution='v12candidate/v7money engine unchanged:signalclose+60secentry,SLsignalclose-max(2,1.5knownM5ATR14),actualrisk2..20,TP.8actualR,120min/21feedcutoff,Bid/Ask,spread/slip/commission,stopfirstifambiguous,gaps. Oneposition,max2actualfills/day10/week,noforcedentries.',
            research_scope='No HGB/threshold/SL/TP grid. Tailhypothesesmayinherentlyfailrequestedweeklyfrequency;reportthat,do notbroadenafterresults. Source is an economic motivation,not evidence of this CFD strategy profitability.',
            counting='2newhypotheses/6costscenarios;allfailuresand261marketdataweeksretained.'),
        objective=dict(win_rate_percent=[55,60],mean_week=[5,10],zero_empty_market_data_weeks=True),
        statistical_screen=dict(family_size=121,prior_hypotheses=119,min_trades=1000,
            annual_stability='allfull2022-2025BASEpositive',costs='BASE/STRESSpositive,familymonthlybootstraplower>0'),
        bootstrap_seed=20261116,bootstrap_resamples=100000,
        sources=[dict(url='https://research-repository.uwa.edu.au/en/publications/the-timing-of-the-flight-to-gold-an-intra-day-analysis-of-gold-an/',use='Authorinstitutionabstract:fastgoldreactiontoextreme5minequitylosses;post-USstockhourscontinuationonlargedowndays. Neitherimpliesourentryhasedge.'),
                 dict(url='https://www.iris.unict.it/retrieve/dfe4d22c-96e7-bb0a-e053-d805fe0a78d9/BoACFECMStatistics2018.pdf',use='AuthorsconferenceabstractC1487provides5minnegative.75%reference;doesnotpublishthisSL/TPstrategy.')],
        caveats=['Allgoldhistoryinspected;retrospective,notpristineOOS.','FTMOrules/account riskdeferredbyuser;assumedcosts,unverifiedfeedclock/DST.','Freshunchanged,noorders,noguaranteeofprofit.'])
    path=RUN/'ASSAY_PROTOCOL.json'
    if path.exists():assert json.loads(path.read_text(encoding='utf-8'))==protocol,'Frozen flight protocol changed'
    else:write_json(path,protocol)
    return protocol


def collect(symbol='US500'):
    assert symbol in ('US500','US500M')
    freeze_protocol();stem='equity' if symbol=='US500' else 'equity_mini'
    path=RUN/(stem+'_rates.npz');mpath=RUN/(stem.upper()+'_DATA_MANIFEST.json')
    if path.exists():
        meta=json.loads(mpath.read_text(encoding='utf-8'))
        assert meta['data_sha256']==sha(path) and meta['protocol_sha256']==sha(RUN/'ASSAY_PROTOCOL.json')
        return
    import MetaTrader5 as mt5
    chunks=RUN/(stem+'_chunks');chunks.mkdir(exist_ok=True)
    assert mt5.initialize(path=r'C:\Program Files\MetaTrader 5\terminal64.exe',timeout=10000),mt5.last_error()
    selected=False;original_visible=None
    meta=dict(source='existingMT5copy_rates_rangeM5',protocol_sha256=sha(RUN/'ASSAY_PROTOCOL.json'),requests=[],no_account_login_or_order_calls=True)
    try:
        assert mt5.terminal_info().connected
        info=mt5.symbol_info(symbol);assert info and info.path.startswith('Indexes\\')
        assert ('SPX' if symbol=='US500' else 'S&P 500') in info.description
        original_visible=info.visible
        if not original_visible:
            assert mt5.symbol_select(symbol,True),mt5.last_error();selected=True
        meta['symbol']=dict(name=symbol,description=info.description,path=info.path,original_visible=original_visible)
        parts=[]
        for year in range(2021,2027):
            start=stamp(year);stop=min(stamp(year+1),stamp(2026,10,25));chunk=chunks/(str(year)+'.npz')
            if chunk.exists():a=np.load(chunk)['rates']
            else:
                a=mt5.copy_rates_range(symbol,mt5.TIMEFRAME_M5,start,stop-1)
                assert a is not None and len(a),(symbol,year,mt5.last_error());validate(a);np.savez_compressed(chunk,rates=a)
            validate(a);assert np.all((a['time']>=start)&(a['time']<stop));parts.append(a)
            meta['requests'].append(dict(year=year,rows=len(a),first=int(a['time'][0]),last=int(a['time'][-1]),sha256=sha(chunk)))
            print(symbol,year,len(a),flush=True)
        rates=np.concatenate(parts);validate(rates);assert rates['time'][0]<=stamp(2021,1,5),'Insufficientinitialhistory'
        gold=np.load(w.BASE/'rates.npz')['m5'];checks=[]
        for year,month,day in ((2021,10,26),(2024,5,6),(2026,10,20)):
            start=stamp(year,month,day);a=mt5.copy_rates_range('XAUUSD',mt5.TIMEFRAME_M5,start,start+86400-1)
            expected=gold[(gold['time']>=start)&(gold['time']<start+86400)]
            exact=a is not None and len(a)==len(expected) and all(np.array_equal(a[k],expected[k]) for k in ('time','open','high','low','close'))
            checks.append(dict(start=start,exact_ohlc_time=bool(exact),rows=len(a) if a is not None else 0))
        assert all(r['exact_ohlc_time'] for r in checks),'Goldfeedmismatch';meta['gold_feed_compatibility']=checks
    finally:
        if selected:assert mt5.symbol_select(symbol,False),'Couldnotrestoreindexvisibility'
        meta['original_marketwatch_visibility_restored']=original_visible is not None and mt5.symbol_info(symbol).visible==original_visible
        mt5.shutdown()
    np.savez_compressed(path,rates=rates);meta.update(rows=len(rates),data_sha256=sha(path));write_json(mpath,meta)


def freeze():
    protocol=freeze_protocol();collect()
    primary=np.load(RUN/'equity_rates.npz')['rates'];gap=np.where(np.diff(primary['time'])>7*86400)[0]
    amendment=dict(reason='US500 has a55dayholein2025. Change the complete predictor source to US500M before any barrier backtest;no splice or P&L-based source selection.',
        original_protocol_sha256=sha(RUN/'ASSAY_PROTOCOL.json'),original_data_sha256=sha(RUN/'equity_rates.npz'),
        gaps=[dict(previous=int(primary['time'][i]),following=int(primary['time'][i+1]),seconds=int(primary['time'][i+1]-primary['time'][i])) for i in gap],
        replacement='US500M,S&P500mini,Indexes;brokerCFDnotofficialcashindex/frontfuture',
        rules_and_costs_unchanged=True,prior_to_any_target_outcome_execution=True)
    assert len(gap)>0,'This explicit amendment requires the documented primary-source gap'
    path=RUN/'DATA_AMENDMENT.json'
    if path.exists():assert json.loads(path.read_text(encoding='utf-8'))==amendment
    else:
        assert not (RUN/'summary.json').exists() and not (RUN/'raw_candidates.npy').exists()
        write_json(path,amendment)
    collect('US500M');equity_file='equity_mini_rates.npz'
    mini=np.load(RUN/equity_file)['rates'];mini_gap=np.where(np.diff(mini['time'])>=7*86400)[0]
    if len(mini_gap):
        prior=json.loads((w.ROOT/'reports/can_ho_tro_scalp/20261101_metals_v14/EXPERIMENT_LOCK.json').read_text(encoding='utf-8'))
        fresh={p:sha(w.ROOT/p)==h for p,h in prior['preserved_fresh'].items()};assert all(fresh.values())
        screen=dict(passed=False,reason='Both independent complete-source candidates have multiweek holes. No splicing,imputation or five-year profitability inference.',
            protocol_sha256=sha(RUN/'ASSAY_PROTOCOL.json'),amendment_sha256=sha(RUN/'DATA_AMENDMENT.json'),
            data_sha256={name:sha(RUN/name) for name in ('equity_rates.npz','equity_mini_rates.npz')},
            primary_gaps=amendment['gaps'],replacement_gaps=[dict(previous=int(mini['time'][i]),following=int(mini['time'][i+1]),
                seconds=int(mini['time'][i+1]-mini['time'][i])) for i in mini_gap],fresh_unchanged=fresh,
            barrier_backtest_executed=False,proposed_hypotheses=2,opened_hypotheses=0,executed_cost_scenarios=0)
        write_json(RUN/'DATA_QUALITY_SCREEN.json',screen)
        write_json(RUN/'CUMULATIVE_REGISTRY.json',dict(previous=dict(hypotheses=119,scenarios=443),
            proposed_hypotheses=2,new=dict(opened_hypotheses=0,executed_cost_scenarios=0),
            cumulative=dict(hypotheses=119,scenarios=443),tests=dict(previous_unique=154,new=2,total_unique=156),
            qualified=[],goal_status='active;researchongoing',lab_status='data_gate_failed_before_barrier_outcomes'))
        return None
    meta=json.loads((RUN/'EQUITY_MINI_DATA_MANIFEST.json').read_text(encoding='utf-8'))
    lock=dict(protocol=protocol,start=w.START,end_exclusive=w.END,hypotheses=SPECS,costs=w.COSTS,
        statistical_screen=protocol['statistical_screen'],bootstrap_seed=protocol['bootstrap_seed'],bootstrap_resamples=protocol['bootstrap_resamples'],
        gold_sha256=sha(w.BASE/'rates.npz'),equity_sha256=meta['data_sha256'],equity_file=equity_file,
        protocol_sha256=sha(RUN/'ASSAY_PROTOCOL.json'),data_amendment_sha256=sha(RUN/'DATA_AMENDMENT.json'),
        prior_registry_sha256=sha(w.ROOT/'reports/can_ho_tro_scalp/20261101_metals_v14/CUMULATIVE_REGISTRY.json'),
        preserved_fresh={p:sha(w.ROOT/p) for p in w.FRESH_PATHS},implementation_sha256={p:sha(w.ROOT/p) for p in (
            'scripts/research_scalp_flight_v15.py','scripts/research_scalp_payoff_v12.py','scripts/research_scalp_avwap_v7.py',
            'scripts/research_scalp_weekly_v3.py','scripts/can_ho_tro_scalp_plan.py')})
    path=RUN/'EXPERIMENT_LOCK.json'
    if path.exists():assert json.loads(path.read_text(encoding='utf-8'))==lock,'Frozenflightlockchanged'
    else:write_json(path,lock)
    return lock


@njit(cache=True)
def features(gold,equity):
    n=len(gold);atr=metaquotes_atr(gold);out=np.full((n,6),np.nan)
    close=np.full(n,np.nan)
    for i in range(n):
        k=np.searchsorted(equity[:,0],gold[i,0])
        if k<len(equity) and equity[k,0]==gold[i,0]:close[i]=equity[k,4]
    for i in range(6,n):
        if atr[i]<=0 or gold[i,0]-gold[i-6,0]!=1800:continue
        fast=np.nan;slow=np.nan
        if np.isfinite(close[i]) and np.isfinite(close[i-1]) and close[i-1]>0:
            fast=close[i]/close[i-1]-1
        if i>=48 and gold[i,0]-gold[i-48,0]==14400:
            valid=True
            for j in range(i-48,i+1):
                if not np.isfinite(close[j]) or close[j]<=0:valid=False;break
            if valid:slow=close[i]/close[i-48]-1
        out[i]=np.array([gold[i,0]+300,fast,slow,atr[i],gold[i,4],i])
    return out


def candidates(feature,start=w.START,end=w.END):
    rows=[];active=[False,False];previous=0
    for f in feature:
        if not np.isfinite(f[0]):active=[False,False];previous=0;continue
        at=f[0]
        if previous and at-previous!=300:active=[False,False]
        previous=at
        for slot,(family,threshold) in enumerate(((38,-.0075),(39,-.01))):
            if not np.isfinite(f[1+slot]):active[slot]=False;continue
            eligible=f[1+slot]<=threshold;crossing=eligible and not active[slot];active[slot]=eligible
            if not crossing or not start<=at<end or not 2<=int(at//3600)%24<18:continue
            opp=dict(known=np.array([at]),close=np.array([f[4]]),unit=np.array([max(2.,1.5*f[3])]),atr=np.array([f[3]]),index=np.array([int(f[5])]))
            c=v.make_candidate(opp,0,True,family);c[33]=f[1+slot];rows.append(c)
    raw=np.asarray(rows,float).reshape((-1,40))
    if len(raw):raw=raw[np.lexsort((raw[:,36],raw[:,1]))]
    return raw


def main():
    lock=freeze()
    if lock is None:
        print('DATA_GATE_FAILED;bothindexsourceshavehistoryholes;0barrierbacktests;do notcount2proposalsasopenedstrategies',flush=True)
        return
    source=np.load(w.BASE/'rates.npz');gold=bars_matrix(source['m5']);market=bars_matrix(source['m1'])
    equity=bars_matrix(np.load(RUN/lock['equity_file'])['rates']);f=features(gold,equity);raw=candidates(f)
    np.save(RUN/'features.npy',f);np.save(RUN/'raw_candidates.npy',raw)
    pos=np.searchsorted(equity[:,0],gold[:,0]);ok=pos<len(equity);ok[ok]&=equity[pos[ok],0]==gold[ok,0]
    write_json(RUN/'COVERAGE.json',dict(gold_rows=len(gold),equity_rows=len(equity),exact_matches=int(ok.sum()),missing_on_gold=int((~ok).sum()),
        fast_valid=int(np.isfinite(f[:,1]).sum()),slow_valid=int(np.isfinite(f[:,2]).sum()),raw_by_source={name:int((raw[:,36]==k).sum()) for k,name in NAMES.items()}))
    w.FAMILIES.update(NAMES);results=[]
    for spec in SPECS:
        for cost in w.COSTS:
            trades,rejects=v.execution.run_serial(raw,market,spec,cost);metric=w.summarize(trades,market,lock)
            results.append(dict(name=spec['name'],cost=cost['id'],metrics=metric,rejections=rejects))
            write_json(RUN/(spec['name']+'_'+cost['id']+'_trades.json'),dict(trades=trades,rejections=rejects))
            print(spec['name'],cost['id'],metric['n'],round(metric['win_rate'] or 0,2),round(metric['total_r'],2),'R;week',
                round(metric['frequency']['mean'],3),'empty',len(metric['frequency']['empty_weeks']),flush=True)
    write_json(RUN/'summary.json',dict(rows=results,lock_sha256=sha(RUN/'EXPERIMENT_LOCK.json')))
    assert all(sha(w.ROOT/p)==h for p,h in lock['preserved_fresh'].items())
    print('DONE2hypotheses/6costscenarios;Freshunchanged',flush=True)


if __name__=='__main__':main()
