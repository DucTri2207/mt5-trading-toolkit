"""A second entry hypothesis: trade the CLOSED rejection instead of waiting for CHoCH."""
from datetime import datetime, timezone
import json
import numpy as np
from numba import njit

import research_scalp_v2 as research
from can_ho_tro_scalp_core import bars_matrix, source_zones
from prepare_can_ho_tro_scalp import sha, write_json


@njit(cache=True)
def detect_reclaim(h1,m5,atr1,atr5,ma1,start,stop):
    rows=[];zones=np.empty((0,16));previous=-1;count=0
    first_seen=np.zeros((len(h1),5,2))
    for c in range(29,len(m5)):
        at=m5[c,0]+300
        if at>=stop:break
        while count<len(h1) and h1[count,0]+3600<=at:count+=1
        if count!=previous:
            zones=source_zones(h1,atr1,count)
            for z in zones:
                bi,bl,fl=int(z[0]),int(z[1])-1,int(z[3])
                if first_seen[bi,bl,fl]==0:first_seen[bi,bl,fl]=h1[count-1,0]+3600
                z[13]=max(z[13],first_seen[bi,bl,fl])
            previous=count
        if at<start:continue
        a=atr5[c];o,h,l,close=m5[c,1],m5[c,2],m5[c,3],m5[c,4]
        if a<=0 or h-l<.25*a or abs(close-o)<.25*a:continue
        hour=int(m5[c,0]//3600)%24
        if hour not in (8,9,10,11,13,15,16,17):continue
        trend=np.searchsorted(h1[:,0],m5[c,0],side='right')-2
        if trend<0 or atr1[trend]<=0:continue
        if abs(h1[trend,4]-ma1[trend])/atr1[trend]>1.75:continue
        for rank in range(len(zones)):
            z=zones[rank]
            if z[8]!=0 or z[6]<35 or z[13]>m5[c,0]:continue
            buy=not bool(z[2]);lo,hi=min(z[4],z[5]),max(z[4],z[5])
            if buy:
                if h1[trend,4]<=ma1[trend] or close<=o:continue
                if not (l<=hi and close>hi and h>=lo-.5*a):continue
                if (min(o,close)-l)/(h-l)<.5:continue
            else:
                if h1[trend,4]>=ma1[trend] or close>=o:continue
                if not (h>=lo and close<lo and l<=hi+.5*a):continue
                if (h-max(o,close))/(h-l)<.5:continue
            anchor=l if buy else h
            raw_stop=anchor+(-.25 if buy else .25)*a
            r=np.zeros(36)
            r[0:8]=np.array([m5[c,0],at,int(buy),z[11],z[1],z[3],z[15],z[14]])
            r[8:18]=np.array([z[6],z[7],z[4],z[5],z[13],m5[c,0],anchor,m5[c,0],z[5],at])
            r[18:27]=np.array([a,raw_stop,anchor,close,(o+close)/2,h1[trend,0],h1[trend,4],ma1[trend],atr1[trend]])
            r[33:36]=np.array([rank,c,count])
            rows.append(r)
    out=np.empty((len(rows),36))
    for i in range(len(rows)):out[i]=rows[i]
    return out


def main():
    run=research.ROOT/'reports/can_ho_tro_scalp/20261101_reclaim_v2';run.mkdir(parents=True,exist_ok=True)
    specs=[dict(name='DIRECT_T05',target='R05',rule='ALL'),
           dict(name='DIRECT_T3',target='PRICE3',rule='ALL'),
           dict(name='DIRECT_FRESH_T05',target='R05',rule='FRESH'),
           dict(name='DIRECT_FRESH_T3',target='PRICE3',rule='FRESH'),
           dict(name='DIRECT_FRESH_SLOPE_T05',target='R05',rule='FRESH'),
           dict(name='DIRECT_RISK6_T3',target='PRICE3',rule='RISK6')]
    lock=dict(version='direct_reclaim_v2',user_date='2026-11-01',
              source_data_sha256=sha(research.BASE/'rates.npz'),hypotheses=specs,costs=research.COSTS,
              definition='H1 source zone known BEFORE M5 open; current M5 wick >=50% range, range>=.25ATR, directional body>=.25ATR; close reclaims proximal; structural SL=current rejection extreme+.25ATR; original hours/trend/distance gates',
              selection='same source rank priority; one trade at a time; DIRECT_FRESH_SLOPE also requires aligned six-bar H1 EMA slope',
              family_size=28,bootstrap_seed=20261101,bootstrap_resamples=20000,
              limitations='retrospective; no native MQL parity for new direct trigger')
    dest=run/'EXPERIMENT_LOCK.json'
    if dest.exists():assert json.loads(dest.read_text(encoding='utf-8'))==lock
    else:write_json(dest,lock)
    data=np.load(research.BASE/'rates.npz');arrays={k:bars_matrix(data[k]) for k in data.files}
    num=np.load(research.BASE/'detector_python.npz')
    start=int(datetime(2021,10,25,tzinfo=timezone.utc).timestamp());stop=int(datetime(2026,10,25,tzinfo=timezone.utc).timestamp())
    cache=run/'detector_direct.npz'
    if cache.exists():raw=np.load(cache)['raw']
    else:
        print('DETECT direct CLOSED M5 rejection, full five years',flush=True)
        raw=detect_reclaim(arrays['h1'],arrays['m5'],num['atr1'],num['atr5'],num['ma1'],start,stop)
        np.savez_compressed(cache,raw=raw)
    print('DIRECT candidates',len(raw),flush=True)
    features=[research.feature(c,arrays['h1'],num['ma1']) for c in raw]
    rows=[];by_spec={}
    for spec in specs:
        feed=raw
        if spec['name']=='DIRECT_FRESH_SLOPE_T05':
            feed=raw.copy()
            for i,f in enumerate(features):
                if not f['slope_aligned']:feed[i,27]=99
        for cost in research.COSTS:
            label=spec['name']+'_'+cost['id']
            trades,rejects=research.run_serial(feed,features,arrays,spec,cost)
            write_json(run/(label+'_trades.json'),trades)
            m=research.summarize(trades,lock)
            rows.append(dict(name=spec['name'],cost=cost['id'],label=label,metrics=m,rejections=rejects))
            if cost['id']=='BASE':by_spec[spec['name']]=trades
            print(label,'n',m['n'],'win',round(m['win_rate'] or 0,2),'PF',round(m['pf'] or 0,3),'R',round(m['total_r'],2),flush=True)
    write_json(run/'summary.json',dict(rows=rows,walkforward=research.evaluate_walkforward(by_spec,raw,features,arrays,specs,research.COSTS[1]),lock_sha256=sha(dest)))
    print('DIRECT DONE',flush=True)


if __name__=='__main__':main()
