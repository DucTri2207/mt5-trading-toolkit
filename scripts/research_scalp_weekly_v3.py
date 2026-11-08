"""Separate weekly-frequency XAUUSD experiment. No terminal or order access."""
from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path

import numpy as np
from numba import njit

from can_ho_tro_scalp_core import bars_matrix, ema50, metaquotes_atr
from can_ho_tro_scalp_plan import Plan, idea_key, planned_gate, round_tick
from prepare_can_ho_tro_scalp import sha, write_json
from replay_can_ho_tro_scalp import as_result, metrics
from research_scalp_v2 import COSTS

ROOT = Path(__file__).resolve().parents[1]
BASE = ROOT/'reports/can_ho_tro_scalp/20261025_v1'
RUN = ROOT/'reports/can_ho_tro_scalp/20261101_weekly_v3'
START = int(datetime(2021, 10, 25, tzinfo=timezone.utc).timestamp())
END = int(datetime(2026, 10, 25, tzinfo=timezone.utc).timestamp())
FAMILIES = {0:'FRESH', 1:'M15_FAILURE', 2:'DAY_FAILURE', 3:'M5_PULLBACK', 4:'M15_PULLBACK'}
# Extra columns: family, source_known_at, H1 direction aligned, H1 known_at.
SPECS = [dict(name=group+'_R'+str(int(rr*100)), group=group, rr=rr)
         for group in ('M15_FAILURE','DAY_FAILURE','M5_PULLBACK','M15_PULLBACK','COMBO','COMBO_H1')
         for rr in (.8, 1., 1.2)]
FRESH_PATHS = ['duc_tri_can_ho_tro_scalp_v2_fresh.mq5',
               'duc_tri_can_ho_tro_scalp_v2_fresh.ex5',
               'Include/CanHoTroScalpFresh.mqh', 'Include/CanHoTroScalpNativeV2Fresh.mqh']


def freeze():
    RUN.mkdir(parents=True, exist_ok=True)
    lock = dict(version='weekly_v3', start=START, end_exclusive=END,
                objective=dict(win_rate_percent=[55,60], average_trades_week=[5,10],
                               every_market_data_week_has_trade=True),
                hypotheses=SPECS, costs=COSTS,
                data_sha256=sha(BASE/'rates.npz'),
                preserved_fresh={p:sha(ROOT/p) for p in FRESH_PATHS},
                definitions=dict(
                    swing='M15 strict-left/non-strict-right 2/2 pivots; known only after 2 right closes; expires after 48 feed hours',
                    day='last completed feed D1 high/low; known at open+86400; expires after 96h; no timezone claim',
                    failure='consume level on first penetration; depth .05-.75 M5 ATR; directional body >=.1ATR, range >=.5ATR, close in directional outer35%; SL extreme+.1ATR',
                    pullback='EMA20, Wilder ADX14>=30 rising over3 bars, DI and EMA6-bar slope agree, new20-bar extreme and close >=1ATR beyond EMA; first EMA touch within24bars, directional rejection within3bars; SL pullback extreme+.1ATR; closed H1 EMA50 aligned',
                    confirmation='closed M5 or M15 bars; M15 aggregated from exactly3 contiguous M5 bars; H1 features known before signal-bar open',
                    combo='Fresh first then M15 failure, day failure, M5 pullback, M15 pullback; COMBO_H1 requires H1 alignment on new failure signals',
                    execution='market; same tested Plan; minimum stop2 maximum20; 120min hold for new sources,6h for preserved Fresh; all positions close no later than21:00 feed; new entries08:00<=bar_open<19:00 feed; Fresh retains original hours',
                    caps='single position; max2 filled entries per feed day, max10 per ISO feed week; no quota or forced weekly entry',
                    fresh='test_count<=1, original source/c0 gates and TP.5R; included only in COMBO variants'),
                statistical_screen=dict(net_expectancy_positive_base_and_stress=True,
                                        annual_stability='each full year2022-2025 net positive BASE',
                                        family_adjusted_bootstrap_lower_positive=True,
                                        min_trades=1000, prior_hypotheses=32, family_size=32+len(SPECS)),
                selection='COMBO variants only; prior calendar years,120min purge, >=200 train trades, positive net R,5-10 mean entries/week and zero empty train weeks; rank netR/market-data week; cash if none qualifies; same BASE-selected schedule at all costs',
                caveats=['All historical data including Oct26-30 have been inspected; retrospective, not pristine OOS.',
                         'Assumed fixed spread/slippage/commission; M1 adverse-first execution, not actual tick fills.',
                         'Broker fees, feed clock, news calendar and prop account rules unverified.',
                         'More than32 earlier historical choices exist; family correction does not erase prior search.'],
                bootstrap_seed=20261102, bootstrap_resamples=20000, no_broker_orders=True)
    path=RUN/'EXPERIMENT_LOCK.json'
    if path.exists():
        assert json.loads(path.read_text(encoding='utf-8'))==lock, 'Changed frozen definitions'
    else:
        write_json(path,lock)
    return lock


@njit(cache=True)
def aggregate_complete(bars, seconds):
    count=seconds//300
    rows=[]
    for i in range(len(bars)-count+1):
        if int(bars[i,0])%seconds:continue
        good=True
        for j in range(count):
            if bars[i+j,0]!=bars[i,0]+j*300:good=False;break
        if good:
            rows.append(np.array([bars[i,0],bars[i,1],np.max(bars[i:i+count,2]),
                                  np.min(bars[i:i+count,3]),bars[i+count-1,4]]))
    out=np.empty((len(rows),5))
    for i in range(len(rows)):out[i]=rows[i]
    return out


@njit(cache=True)
def ema(bars, period):
    out=np.zeros(len(bars))
    if not len(bars):return out
    out[0]=bars[0,4]
    alpha=2./(period+1)
    for i in range(1,len(bars)):out[i]=alpha*bars[i,4]+(1-alpha)*out[i-1]
    return out


@njit(cache=True)
def wilder_adx(bars, period=14):
    n=len(bars);tr=np.zeros(n);plus=np.zeros(n);minus=np.zeros(n)
    for i in range(1,n):
        tr[i]=max(bars[i,2],bars[i-1,4])-min(bars[i,3],bars[i-1,4])
        up=bars[i,2]-bars[i-1,2];down=bars[i-1,3]-bars[i,3]
        if up>down and up>0:plus[i]=up
        if down>up and down>0:minus[i]=down
    pdi=np.zeros(n);mdi=np.zeros(n);dx=np.zeros(n);adx=np.zeros(n)
    if n<=2*period:return adx,pdi,mdi
    st=np.sum(tr[1:period+1]);sp=np.sum(plus[1:period+1]);sm=np.sum(minus[1:period+1])
    for i in range(period,n):
        if i>period:
            st=st-st/period+tr[i];sp=sp-sp/period+plus[i];sm=sm-sm/period+minus[i]
        if st>0:pdi[i]=100*sp/st;mdi[i]=100*sm/st
        if pdi[i]+mdi[i]>0:dx[i]=100*abs(pdi[i]-mdi[i])/(pdi[i]+mdi[i])
        if i==2*period-1:adx[i]=np.mean(dx[period:2*period])
        elif i>=2*period:adx[i]=(adx[i-1]*(period-1)+dx[i])/period
    return adx,pdi,mdi


@njit(cache=True)
def swing_levels(bars, seconds=900):
    rows=[]
    for p in range(2,len(bars)-2):
        known=bars[p+2,0]+seconds
        # A gap cannot create a pivot using missing right-hand candles.
        if bars[p+2,0]-bars[p-2,0]!=4*seconds:continue
        if bars[p,2]>max(bars[p-2,2],bars[p-1,2]) and bars[p,2]>=max(bars[p+1,2],bars[p+2,2]):
            rows.append(np.array([bars[p,0],known,bars[p,2],0.]))
        if bars[p,3]<min(bars[p-2,3],bars[p-1,3]) and bars[p,3]<=min(bars[p+1,3],bars[p+2,3]):
            rows.append(np.array([bars[p,0],known,bars[p,3],1.]))
    out=np.empty((len(rows),4))
    for i in range(len(rows)):out[i]=rows[i]
    return out


@njit(cache=True)
def day_levels(d1):
    out=np.empty((len(d1)*2,4))
    for i,b in enumerate(d1):
        out[i*2]=np.array([b[0],b[0]+86400,b[2],0.])
        out[i*2+1]=np.array([b[0],b[0]+86400,b[3],1.])
    return out


@njit(cache=True)
def make_candidate(bars,c,seconds,buy,source_time,source_known,level,sweep_time,anchor,a,family,h1,ma1,atr1):
    at=bars[c,0];known=at+seconds;d=1 if buy else -1
    r=np.zeros(40)
    i=np.searchsorted(h1[:,0]+3600,at,side='right')-1
    aligned=i>=0 and d*(h1[i,4]-ma1[i])>0
    r[0:8]=np.array([at,known,int(buy),source_time,10+family,0,0,source_time])
    r[8:18]=np.array([50,0,level,level,source_known,sweep_time,anchor,source_time,level,source_known])
    r[18:23]=np.array([a,anchor-d*.1*a,anchor,bars[c,4],(bars[c,1]+bars[c,4])/2])
    if i>=0:r[23:27]=np.array([h1[i,0],h1[i,4],ma1[i],atr1[i]])
    r[34:40]=np.array([c,i+1,family,source_known,int(aligned),h1[i,0]+3600 if i>=0 else 0])
    return r


@njit(cache=True)
def detect_failure(bars,levels,atr,h1,ma1,atr1,family,start,stop):
    rows=[];used=np.zeros(len(levels),np.bool_);end=0
    for c in range(30,len(bars)):
        at=bars[c,0];known=at+300
        if known>=stop:break
        while end<len(levels) and levels[end,1]<=at:end+=1
        a=atr[c]
        if a<=0:continue
        o,h,l,close=bars[c,1:5];rng=h-l
        for k in range(end-1,-1,-1):
            source,available,level,buy=levels[k]
            if family==2 and k<end-2:break
            if at-available>(172800 if family==1 else 345600):break
            if used[k]:continue
            penetration=level-l if buy else h-level
            if penetration<.05*a:continue
            used[k]=True
            hour=int(at//3600)%24
            if known<start or not 8<=hour<19 or penetration>.75*a or rng<.5*a:continue
            d=1 if buy else -1
            if d*(close-o)<.1*a or d*(close-level)<=0:continue
            if ((close-l)/rng if buy else (h-close)/rng)<.65:continue
            anchor=l if buy else h
            rows.append(make_candidate(bars,c,300,bool(buy),source,available,level,at,anchor,a,family,h1,ma1,atr1))
            rows[-1][33]=end-1-k
    out=np.empty((len(rows),40))
    for i in range(len(rows)):out[i]=rows[i]
    return out


class WeeklyPlan(Plan):
    def fill(self,at,bid,ask):
        super().fill(at,bid,ask)
        if self.state!='FILLED':return
        fresh=int(self.c[36])==0
        self.target=round_tick(self.entry+self.d*(.5 if fresh else self.rr)*self.risk,self.tick,self.d)
        self.deadline=min(int(at)+(21600 if fresh else 7200),int(at)//86400*86400+21*3600)


def simulate(index,c,market,rr,cost,record_equity=False):
    p=WeeklyPlan(c,'T05',cost['spread'],cost['slip'],.01)
    p.rr=rr;samples=[]
    if record_equity:p.observer=lambda at,r:samples.append((at,r))
    left=int(np.searchsorted(market[:,0],c[1],side='left'))
    if left==len(market):p.state='REJECTED';p.reason='NO_ENTRY_QUOTE'
    else:
        first=market[left];p.start(int(first[0]),float(first[1]),float(first[1])+p.spread)
        for i in range(left,len(market)):
            if p.state!='FILLED':break
            b=market[i];at=int(b[0])
            if i>left and at-int(market[i-1,0])>60:p.gaps+=1
            p.quote(at,float(b[1]),float(b[1])+p.spread)
            if p.state=='FILLED':p.minute_range(at,float(b[2]),float(b[3]),float(b[4]))
        if p.state=='FILLED':p.state='CENSORED_FILLED';p.reason='END_OF_DATA'
    result=as_result(p,index,'M1_ADVERSE_FIRST')
    fee=cost['commission_price']/p.risk if p.entry_time else 0.
    result.update(gross_r=result['r'],commission_r=fee,source=FAMILIES[int(c[36])],
                  source_known_at=int(c[37]),h1_known_at=int(c[39]),
                  target=p.target,deadline=p.deadline)
    if result['r'] is not None:result['r']-=fee
    if record_equity:result['equity_samples']=[(at,r-fee) for at,r in samples]
    return result


def accepts(c,spec):
    family=int(c[36]);group=spec['group']
    if group.startswith('COMBO'):
        if group=='COMBO_H1' and family in (1,2) and not c[38]:return False
    elif FAMILIES[family]!=group:return False
    return planned_gate(c)== 'PASS'


def week_key(at):return (int(at)//86400+3)//7


def run_serial(raw,market,spec,cost,schedule=None,record_equity=False):
    rows=[];busy=0;seen=set();days=Counter();weeks=Counter();rejects=Counter();chosen=-1
    for index,c in enumerate(raw):
        at=int(c[1])
        if schedule is not None:
            spec=schedule.get(datetime.fromtimestamp(at,timezone.utc).year)
            if spec is None:continue
        if not accepts(c,spec):continue
        if at<busy:rejects['BUSY']+=1;continue
        if at==chosen:rejects['PRIORITY']+=1;continue
        chosen=at
        key=idea_key(c)
        if key in seen:rejects['DUPLICATE']+=1;continue
        day=at//86400;week=week_key(at)
        if days[day]>=2 or weeks[week]>=10:rejects['CAP']+=1;continue
        seen.add(key)
        result=simulate(index,c,market,spec['rr'],cost,record_equity)
        rows.append(result)
        if result['entry_time']:
            days[day]+=1;weeks[week]+=1
        if result['state'].startswith('CENSORED'):busy=int(market[-1,0])+60
        elif result['exit_time']:busy=result['exit_time']
    return rows,dict(rejects)


def weekly(rows,market,start=START,end=END):
    times=market[(market[:,0]>=start)&(market[:,0]<end),0].astype(np.int64)
    keys=np.unique((times//86400+3)//7)
    by_week={int(k):dict(n=0,closed=0,r=0.,wins=0) for k in keys}
    for row in rows:
        if not row['entry_time'] or not start<=row['entry_time']<end:continue
        w=by_week.get(week_key(row['entry_time']))
        if w is None:continue
        w['n']+=1
        if row['state']=='CLOSED':
            w['closed']+=1;w['r']+=row['r'];w['wins']+=int(row['r']>1e-12)
    result=[]
    market_days=np.unique(times//86400)
    day_counts=Counter((market_days+3)//7)
    for k,record in by_week.items():
        monday=(k*7-3)*86400
        result.append(dict(week_start=datetime.fromtimestamp(monday,timezone.utc).strftime('%Y-%m-%d'),
                           market_days=int(day_counts[k]),**record))
    ns=[w['n'] for w in result]
    return dict(weeks=len(result),empty_weeks=[w['week_start'] for w in result if not w['n']],
                mean=float(np.mean(ns)) if ns else 0.,median=float(np.median(ns)) if ns else 0.,
                min=min(ns) if ns else 0,max=max(ns) if ns else 0,
                weeks_with_5_to_10=sum(5<=n<=10 for n in ns),
                weeks_below_5=sum(n<5 for n in ns),weekly=result)


def summarize(rows,market,lock,start=START,end=END):
    result=metrics(rows);result['frequency']=weekly(rows,market,start,end)
    closed=[x for x in rows if x['state']=='CLOSED']
    filled=[x for x in rows if x['entry_time']]
    result['by_year']={str(y):metrics([x for x in closed if datetime.fromtimestamp(x['entry_time'],timezone.utc).year==y]) for y in range(2021,2027)}
    result['sources']={name:metrics([x for x in rows if x['source']==name]) for name in FAMILIES.values()}
    result['mean_holding_minutes']=float(np.mean([(x['exit_time']-x['entry_time'])/60 for x in closed])) if closed else None
    result['day_crossings']=sum(x['entry_time']//86400!=x['exit_time']//86400 for x in closed)
    gaps=[(b['entry_time']-a['entry_time'])/86400 for a,b in zip(filled,filled[1:])]
    result['max_entry_gap_days']=max(gaps) if gaps else None
    months=[];current=datetime.fromtimestamp(start,timezone.utc).replace(day=1)
    while current.timestamp()<end:
        months.append(current.strftime('%Y-%m'))
        current=current.replace(year=current.year+1,month=1) if current.month==12 else current.replace(month=current.month+1)
    amounts=np.zeros(len(months));counts=np.zeros(len(months))
    for row in closed:
        # Entry cohort keeps post-boundary exits attached to their signal month.
        key=datetime.fromtimestamp(row['entry_time'],timezone.utc).strftime('%Y-%m')
        if key not in months:continue
        i=months.index(key);amounts[i]+=row['r'];counts[i]+=1
    rng=np.random.default_rng(lock['bootstrap_seed'])
    draws=rng.integers(len(months),size=(lock['bootstrap_resamples'],len(months)))
    nums=counts[draws].sum(axis=1);profits=amounts[draws].sum(axis=1)
    bs=profits[nums>0]/nums[nums>0]
    result['expectancy_month_bootstrap_95']=np.quantile(bs,[.025,.975]).tolist() if len(bs) else None
    result['expectancy_month_bootstrap_lower_family95']=float(np.quantile(bs,.05/lock['statistical_screen']['family_size'])) if len(bs) else None
    f=result['frequency']
    result['frequency_pass']=bool(f['weeks'] and not f['empty_weeks'] and 5<=f['mean']<=10)
    result['economic_screen_pass']=bool(result['n']>=1000 and result['total_r']>0 and
        (result['expectancy_month_bootstrap_lower_family95'] or 0)>0 and
        all(result['by_year'][str(y)]['total_r']>0 for y in range(2022,2026)))
    return result


def detect(arrays,start=START,end=END):
    h1=arrays['h1'];m5=arrays['m5'];m15=aggregate_complete(m5,900)
    a1=metaquotes_atr(h1);a5=metaquotes_atr(m5);a15=metaquotes_atr(m15);ma1=ema50(h1)
    parts=[detect_failure(m5,swing_levels(m15),a5,h1,ma1,a1,1,start,end),
           detect_failure(m5,day_levels(arrays['d1']),a5,h1,ma1,a1,2,start,end),
           detect_pullback(m5,300,a5,h1,ma1,a1,start,end),
           detect_pullback(m15,900,a15,h1,ma1,a1,start,end)]
    raw=np.concatenate(parts)
    raw=raw[np.lexsort((raw[:,33],raw[:,36],raw[:,1]))]
    assert np.all(raw[:,37]<=raw[:,13]), 'Reference level must be known before sweep'
    assert np.all(raw[:,39]<=raw[:,0]), 'H1 must be closed before trigger-bar open'
    return raw


def add_fresh(raw):
    previous=np.load(BASE/'detector_python.npz')['c0_raw']
    fresh=previous[(previous[:,9]<=1)&(previous[:,27]==0)&(previous[:,28]==0)]
    out=np.zeros((len(fresh),40));out[:,:36]=fresh
    out[:,37]=fresh[:,12];out[:,38]=1;out[:,39]=fresh[:,23]+3600
    raw=np.concatenate([out,raw])
    return raw[np.lexsort((raw[:,33],raw[:,36],raw[:,1]))]


def walkforward(all_trades,raw,market,cost):
    choices=[];schedule={};lookup={s['name']:s for s in SPECS}
    for year in range(2023,2027):
        boundary=int(datetime(year,1,1,tzinfo=timezone.utc).timestamp());rank=[]
        for spec in SPECS:
            if not spec['group'].startswith('COMBO'):continue
            train=[t for t in all_trades[spec['name']] if t['state']=='CLOSED' and t['exit_time']<boundary-7200]
            m=metrics(train);f=weekly(train,market,START,boundary-7200)
            if m['n']>=200 and m['total_r']>0 and f['weeks'] and not f['empty_weeks'] and 5<=f['mean']<=10:
                rank.append((m['total_r']/f['weeks'],spec['name'],m['n']))
        if rank:
            score,name,n=max(rank);schedule[year]=lookup[name]
            choices.append(dict(year=year,selected=name,train_n=n,train_r_week=score))
        else:choices.append(dict(year=year,selected='CASH'))
    trades,rejects=run_serial(raw,market,None,cost,schedule=schedule)
    for c in choices:
        c['test']=metrics([t for t in trades if datetime.fromtimestamp(t['signal_time'],timezone.utc).year==c['year']])
    return dict(choices=choices,metrics=metrics(trades),rejections=rejects,
                label='Retrospective prior-year selection; no pristine holdout'),trades


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--freeze-only',action='store_true');parser.add_argument('--detect-only',action='store_true')
    args=parser.parse_args();lock=freeze()
    if args.freeze_only:return
    source=np.load(BASE/'rates.npz');arrays={k:bars_matrix(source[k]) for k in source.files}
    cache=RUN/'detector_weekly.npz'
    if cache.exists():raw=np.load(cache)['raw']
    else:
        raw=detect(arrays);np.savez_compressed(cache,raw=raw)
    print('CANDIDATES',dict(Counter(FAMILIES[int(c[36])] for c in raw)),flush=True)
    raw=add_fresh(raw)
    if args.detect_only:return
    summaries=[];base_trades={}
    for spec in SPECS:
        for cost in COSTS:
            label=spec['name']+'_'+cost['id']
            path=RUN/(label+'_trades.json')
            if path.exists():
                saved=json.loads(path.read_text(encoding='utf-8'));trades=saved['trades'];rejects=saved['rejections']
            else:
                trades,rejects=run_serial(raw,arrays['m1'],spec,cost)
                write_json(path,dict(trades=trades,rejections=rejects))
            m=summarize(trades,arrays['m1'],lock)
            summaries.append(dict(name=spec['name'],cost=cost['id'],metrics=m,rejections=rejects))
            if cost['id']=='BASE':base_trades[spec['name']]=trades
            f=m['frequency']
            print(label,'n',m['n'],'win',round(m['win_rate'] or 0,2),'PF',round(m['pf'] or 0,3),'R',round(m['total_r'],2),
                  'week',round(f['mean'],2),'empty',len(f['empty_weeks']),flush=True)
    wf={}
    for cost in COSTS:
        summary,trades=walkforward(base_trades,raw,arrays['m1'],cost)
        wf[cost['id']]=summary;write_json(RUN/('WALKFORWARD_'+cost['id']+'_trades.json'),trades)
    write_json(RUN/'summary.json',dict(rows=summaries,walkforward=wf,lock_sha256=sha(RUN/'EXPERIMENT_LOCK.json')))
    assert all(sha(ROOT/p)==expected for p,expected in lock['preserved_fresh'].items())
    write_json(RUN/'SOURCE_MANIFEST.json',dict(script_sha256=sha(Path(__file__)),fresh_unchanged=True))
    print('DONE',len(summaries),'scenarios; Fresh hashes unchanged',flush=True)


@njit(cache=True)
def detect_pullback(bars,seconds,atr,h1,ma1,atr1,start,stop):
    ma=ema(bars,20);adx,pdi,mdi=wilder_adx(bars)
    rows=[];armed=0;arm=-1;touch=-1;anchor=0.;source_known=0.
    family=3 if seconds==300 else 4
    for c in range(40,len(bars)):
        at=bars[c,0];known=at+seconds
        if known>=stop:break
        if bars[c,0]-bars[c-1,0]>seconds:armed=0;touch=-1
        a=atr[c]
        if a<=0:continue
        o,h,l,close=bars[c,1:5]
        i=np.searchsorted(h1[:,0]+3600,at,side='right')-1
        if i<0:continue
        if armed:
            d=armed
            if c-arm>24 or d*(h1[i,4]-ma1[i])<=0:armed=0;touch=-1
            else:
                if touch<0 and (l<=ma[c] if d==1 else h>=ma[c]):
                    touch=c;anchor=l if d==1 else h
                if touch>=0:
                    anchor=min(anchor,l) if d==1 else max(anchor,h)
                    if c-touch>2 or d*(close-ma[c])<-.5*a:armed=0;touch=-1
                    elif d*(close-o)>=.1*a and d*(close-ma[c])>0 and h>l and ((close-l)/(h-l) if d==1 else (h-close)/(h-l))>=.65:
                        if known>=start and 8<=int(at//3600)%24<19:
                            rows.append(make_candidate(bars,c,seconds,d==1,bars[arm,0],source_known,ma[touch],bars[touch,0],anchor,a,family,h1,ma1,atr1))
                        armed=0;touch=-1
                        continue
        if not armed and adx[c]>=30 and adx[c]>adx[c-3]:
            d=1 if pdi[c]>mdi[c] else -1
            extreme=h>np.max(bars[c-20:c,2]) if d==1 else l<np.min(bars[c-20:c,3])
            if extreme and d*(close-ma[c])>=a and d*(ma[c]-ma[c-6])>0 and d*(h1[i,4]-ma1[i])>0:
                armed=d;arm=c;source_known=known;touch=-1
    out=np.empty((len(rows),40))
    for i in range(len(rows)):out[i]=rows[i]
    return out


if __name__=='__main__':main()
