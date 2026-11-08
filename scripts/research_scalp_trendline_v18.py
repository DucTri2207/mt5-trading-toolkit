"""Higher-timeframe structure and causal H1 trendline pullback entries."""
from __future__ import annotations

import argparse
import json

import numpy as np
from numba import njit

from can_ho_tro_scalp_core import bars_matrix,metaquotes_atr
from prepare_can_ho_tro_scalp import sha,write_json
import research_scalp_payoff_v12 as v

w = v.w
RUN = w.ROOT/'reports/can_ho_tro_scalp/20261101_trendline_v18'
NAMES = {47:'H4_H1_TRENDLINE',48:'D1_H4_H1_TRENDLINE',49:'H1_TRENDLINE_CONTROL'}
SPECS = [dict(name=name,sources=[k]) for k,name in NAMES.items()]
STATE_FIELDS = ['known','direction','low1_time','low1','low1_known','low2_time','low2','low2_known',
                'high1_time','high1','high1_known','high2_time','high2','high2_known']
EVENT_FIELDS = ['known','buy','ray_known','p1_time','p1_price','p2_time','p2_price','ray_ATR',
                'touch_open','touch_ATR','line_touch_open','line_confirm_close','touch_H4','confirm_H4',
                'touch_D1','confirm_D1','confirm_H1_known','confirm_H4_known','confirm_D1_known','M5_index']


def freeze():
    manifest = json.loads((RUN/'H4_DATA_MANIFEST.json').read_text(encoding='utf-8'))
    assert manifest['data_sha256']==sha(RUN/'h4_rates.npz') and manifest['quality']['passed']
    protocol = dict(version='trendline_v18',start=w.START,end_exclusive=w.END,hypotheses=SPECS,costs=w.COSTS,
        user_steering='User proposes determining trend on higher timeframes and trading with it,including trendlines. Retain55-60%wins,5-10trades/week,noemptyweeks,five-year after-costR and separate MT5 indicator. FTMO risk deferred;Fresh preserved.',
        motivation='Earlier H1 EMA/slope and ADX pullback tests did not test nativeH4/D1 confirmed-swing structure with a causal,non-redrawn H1 support/resistance ray. Test this explicit user proposal without flexible fitting.',
        definitions=dict(
            frames='NativeH4 read from existing MT5,all7742evaluatedH4 OHLC exactly reconciled with frozenM5 buckets;H1/D1/M5/M1 frozen existing gold. Preserve closures,no fill. Frame availability=open+period,used only if closed<=M5confirmationbar OPEN.',
            pivots='Consecutive actual trading bars,2left/2right. High strictly greater than twoleft and>=tworight;low strictly lower than twoleft and<=tworight. Pivot known only at secondrightbar close;ties choose earliest plateau. No ZigZag rewriting.',
            direction='Each frame up only when last2confirmed highs AND last2confirmed lows strictly rise and latestclosedclose>latestconfirmedlow. Down when both fall and latestclose<latestconfirmedhigh;else neutral. No EMA vote. Latestclosed H1 age<=2h,H4<=8h,D1<=4days at touch/confirmation.',
            ray='H1 up joins latest2confirmed lows;down joins latest2confirmed highs. Linear in feed timestamp seconds,no visual angle optimization. Pair span<=48h. New ray born when H1 structure first allows its secondanchor,using currentclosedH1ATR14. Every interveningH1low(up)/high(down) from anchor1 through birth must respect ray within.1frozenH1ATR. Freeze endpoints permanently;new pivot pair creates new identity.',
            lifetime='One setup per directional secondanchor. Ray expires12elapsedhours after birth. H1neutral/direction or anchor change,anyM5gap,or M5close beyond wrongside of projectedray by>.25previousM5ATR cancels it permanently. Cannot resurrect same consumed/invalid pair.',
            pullback='Price must first be observed>=1knownM5ATR away on trend side,including previousclosedM5 at birth. First later M5low/high within.25previousM5ATR of projectedray at baropen starts touch;freeze touchATR. Confirm within3M5bars including touch:directionalbody>=.1touchATR,range>=.5touchATR,close in directionalouter35%,and close>=.1touchATR beyond projectedray at barclose. First touch consumes setup on confirmation or expiry,even if hours/HTFfilter fail.',
            policies='Same H1 first-touch event stream. H4_H1 requires H4 direction aligned at BOTH touchbaropen and confirmationbaropen. D1_H4_H1 additionally requires D1 aligned at both. H1 control has no addedHTF gate. Neutral=no entries;not opposite trades. These are counted ablations,not a post-hoc winner choice.',
            entry='New signals02<=knownfeedhour<18,closedM5+60sec. No named London/NY session claim. Source geometry/pivots/HTFbars must already be known at touch;no hindsight endpoint selection.',
            execution='Unchangedv12candidate/v7money:SL signalclose+/-max(2,1.5currentknownM5ATR14),actualrisk2..20,TP.8actualR,120min/21feedcutoff,Bid/Ask,slip,commission,M1adversefirst,gaps. Oneposition,max2actualfills/day10/week;identicalrawsignalsLOW/BASE/STRESS.',
            counting='3newhypotheses/9costscenarios. All261marketweeks including cash/zero;keep every failure. No pivot-width,line-tolerance,expiry,frame,SL/TP or hour grid after outcomes.'),
        objective=dict(win_rate_percent=[55,60],mean_week=[5,10],zero_empty_market_data_weeks=True),
        statistical_screen=dict(family_size=129,prior_hypotheses=126,min_trades=1000,
            annual_stability='allfull2022-2025BASEpositive',costs='BASE/STRESSpositive,familymonthlybootstraplower>0'),
        bootstrap_seed=20261119,bootstrap_resamples=100000,
        sources=[dict(url='https://www.newyorkfed.org/research/epr/00v06n2/0007osle.html',
            use='Osler finds support/resistance can predict interruptions in FX,but effects vary by currency/provider. Not evidence for these diagonal rays,parameters,XAUUSD or after-cost profitability.')],
        caveats=['Allgoldhistorypreviouslyinspected;retrospective only,not pristineOOS.','Assumedcosts/feedclock;cannot guarantee profit.',
                 'Trend agreement may reduce frequency;do not force entries or lower the agreed requirements to call success.'])
    path = RUN/'ASSAY_PROTOCOL.json'
    if path.exists():
        assert json.loads(path.read_text(encoding='utf-8'))==protocol,'Frozen trendline protocol changed'
    else:
        write_json(path,protocol)
    files = ('scripts/research_scalp_trendline_v18.py','scripts/collect_scalp_trendline_v18.py',
             'scripts/research_scalp_payoff_v12.py','scripts/research_scalp_avwap_v7.py',
             'scripts/research_scalp_weekly_v3.py','scripts/can_ho_tro_scalp_plan.py','scripts/can_ho_tro_scalp_core.py')
    lock = dict(protocol=protocol,start=w.START,end_exclusive=w.END,hypotheses=SPECS,costs=w.COSTS,
        statistical_screen=protocol['statistical_screen'],bootstrap_seed=protocol['bootstrap_seed'],bootstrap_resamples=protocol['bootstrap_resamples'],
        protocol_sha256=sha(path),h4_sha256=sha(RUN/'h4_rates.npz'),h4_manifest_sha256=sha(RUN/'H4_DATA_MANIFEST.json'),
        gold_sha256=sha(w.BASE/'rates.npz'),labels_sha256=sha(v.RUN/'barrier_labels.npz'),
        previous_registry_sha256=sha(w.ROOT/'reports/can_ho_tro_scalp/20261101_compression_v17/CUMULATIVE_REGISTRY.json'),
        implementation_sha256={p:sha(w.ROOT/p) for p in files},preserved_fresh={p:sha(w.ROOT/p) for p in w.FRESH_PATHS})
    path = RUN/'EXPERIMENT_LOCK.json'
    if path.exists():
        assert json.loads(path.read_text(encoding='utf-8'))==lock,'Frozen trendline implementation changed'
    else:
        write_json(path,lock)
    return lock


@njit(cache=True)
def structure(bars,seconds):
    out = np.zeros((len(bars),14));lows = np.zeros((2,3));highs = np.zeros((2,3));lc = 0;hc = 0
    for j in range(len(bars)):
        known = bars[j,0]+seconds
        if j>=4:
            p = j-2
            if bars[p,3]<min(bars[p-2,3],bars[p-1,3]) and bars[p,3]<=min(bars[p+1,3],bars[p+2,3]):
                lows[0] = lows[1];lows[1] = np.array([bars[p,0],bars[p,3],known]);lc += 1
            if bars[p,2]>max(bars[p-2,2],bars[p-1,2]) and bars[p,2]>=max(bars[p+1,2],bars[p+2,2]):
                highs[0] = highs[1];highs[1] = np.array([bars[p,0],bars[p,2],known]);hc += 1
        d = 0
        if lc>=2 and hc>=2:
            if lows[1,1]>lows[0,1] and highs[1,1]>highs[0,1] and bars[j,4]>lows[1,1]:
                d = 1
            elif lows[1,1]<lows[0,1] and highs[1,1]<highs[0,1] and bars[j,4]<highs[1,1]:
                d = -1
        out[j,0] = known;out[j,1] = d;out[j,2:8] = lows.flatten();out[j,8:14] = highs.flatten()
    return out


@njit(cache=True)
def context(at,states,max_age):
    j = np.searchsorted(states[:,0],at,side='right')-1
    if j<0:
        return 0.,0.
    return (states[j,1] if at-states[j,0]<=max_age else 0.),states[j,0]


@njit(cache=True)
def events(m5,h1,s1,s4,sd,start=w.START,end=w.END):
    a5 = metaquotes_atr(m5);a1 = metaquotes_atr(h1);rows = []
    active = False;seen = np.zeros(2);direction = 0.;p1 = 0.;v1 = 0.;p2 = 0.;v2 = 0.
    born = 0.;ray_atr = 0.;departed = False;touch = -1;touch_atr = 0.;touch_line = 0.;touch4 = 0.;touchd = 0.
    for i in range(15,len(m5)):
        at = m5[i,0];known = at+300
        if known>=end:
            break
        if m5[i,0]-m5[i-1,0]!=300:
            active = False;continue
        j = np.searchsorted(s1[:,0],at,side='right')-1
        if j<0 or at-s1[j,0]>7200 or a5[i-1]<=0:
            active = False;continue
        d = s1[j,1]
        if d==0:
            active = False;continue
        slot = 0 if d>0 else 1;column = 2 if d>0 else 8;anchor = s1[j,column+3]
        if active and (direction!=d or p2!=anchor):
            active = False
        if anchor>0 and anchor!=seen[slot]:
            seen[slot] = anchor;active = False
            t1,y1,t2,y2 = s1[j,column],s1[j,column+1],s1[j,column+3],s1[j,column+4]
            if t2<=t1 or t2-t1>48*3600 or a1[j]<=0:
                continue
            slope = (y2-y1)/(t2-t1);valid = True;k = np.searchsorted(h1[:,0],t1)
            for q in range(k,j+1):
                level = y1+slope*(h1[q,0]-t1)
                extreme = h1[q,3] if d>0 else h1[q,2]
                if d*(extreme-level)<-.1*a1[j]:
                    valid = False;break
            if not valid:
                continue
            active = True;direction = d;p1 = t1;v1 = y1;p2 = t2;v2 = y2
            born = s1[j,0];ray_atr = a1[j];touch = -1
            level = v1+slope*(at-p1)
            departed = d*(m5[i-1,4]-level)>=a5[i-1]
        if not active:
            continue
        if known>born+12*3600:
            active = False;continue
        slope = (v2-v1)/(p2-p1);line_open = v1+slope*(at-p1);line_close = v1+slope*(known-p1)
        o,h,l,close = m5[i,1:5];fa = touch_atr if touch>=0 else a5[i-1]
        if d*(close-line_close)<-.25*a5[i-1]:
            active = False;continue
        if touch<0 and departed and (l<=line_open+.25*fa if d>0 else h>=line_open-.25*fa):
            touch = i;touch_atr = a5[i-1];fa = touch_atr;touch_line = line_open
            touch4,_ = context(at,s4,8*3600);touchd,_ = context(at,sd,4*86400)
        if touch>=0:
            if i-touch>2:
                active = False;continue
            rng = h-l;outer = ((close-l)/rng if d>0 else (h-close)/rng) if rng>0 else 0.
            quality = d*(close-o)>=.1*fa and rng>=.5*fa and outer>=.65 and d*(close-line_close)>=.1*fa
            if quality:
                active = False
                if start<=known and 2*3600<=known%86400<18*3600:
                    now4,k4 = context(at,s4,8*3600);nowd,kd = context(at,sd,4*86400)
                    rows.append(np.array([known,1. if d>0 else 0.,born,p1,v1,p2,v2,ray_atr,
                        m5[touch,0],touch_atr,touch_line,line_close,touch4,now4,touchd,nowd,s1[j,0],k4,kd,float(i)]))
                continue
        elif d*(close-line_close)>=a5[i]:
            departed = True
    out = np.empty((len(rows),20))
    for i in range(len(rows)):
        out[i] = rows[i]
    return out


def candidates(m5,detected):
    a = metaquotes_atr(m5)
    opp = dict(known=m5[:,0]+300,close=m5[:,4],unit=np.maximum(2.,1.5*a),atr=a,index=np.arange(len(m5)))
    rows = []
    for event in detected:
        d = 1 if event[1] else -1
        h4 = event[12]==d and event[13]==d;d1 = event[14]==d and event[15]==d
        for family,eligible in ((47,h4),(48,h4 and d1),(49,True)):
            if not eligible:
                continue
            c = v.make_candidate(opp,int(event[19]),bool(event[1]),family,int(event[2]))
            c[3] = event[5];c[15] = event[3];c[39] = event[16]
            c[33] = (event[6]-event[4])/(event[5]-event[3])*3600;rows.append(c)
    raw = np.asarray(rows,float).reshape((-1,40))
    if len(raw):
        raw = raw[np.lexsort((raw[:,36],raw[:,1]))]
    return raw


def main():
    parser = argparse.ArgumentParser();parser.add_argument('--freeze-only',action='store_true');args = parser.parse_args()
    lock = freeze()
    if args.freeze_only:
        print('LOCKED before outcomes;3policies/9plannedscenarios',flush=True);return
    source = np.load(w.BASE/'rates.npz');m5 = bars_matrix(source['m5']);h1 = bars_matrix(source['h1']);d1 = bars_matrix(source['d1'])
    h4 = bars_matrix(np.load(RUN/'h4_rates.npz')['rates']);market = bars_matrix(source['m1'])
    s1 = structure(h1,3600);s4 = structure(h4,14400);sd = structure(d1,86400)
    detected = events(m5,h1,s1,s4,sd);raw = candidates(m5,detected)
    np.savez_compressed(RUN/'structure_inputs.npz',h1=s1,h4=s4,d1=sd)
    np.save(RUN/'events.npy',detected);np.save(RUN/'raw_candidates.npy',raw)
    write_json(RUN/'COVERAGE.json',dict(state_fields=STATE_FIELDS,event_fields=EVENT_FIELDS,H1_events=len(detected),
        raw_candidates={name:int(np.sum(raw[:,36]==k)) for k,name in NAMES.items()},
        periods=dict(H1=len(h1),H4=len(h4),D1=len(d1)),
        filter_comparison='Identical H1 first-touch opportunity stream;H4 and D1 gates applied before serial caps. Executed portfolios may differ through occupancy/caps.'))
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
