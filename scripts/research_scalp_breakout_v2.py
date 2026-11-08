"""Predeclared alternative: trend-aligned 20-bar breakout, then first pullback."""
import json
from datetime import datetime, timezone
import numpy as np
from numba import njit

import research_scalp_v2 as research
from can_ho_tro_scalp_core import bars_matrix
from prepare_can_ho_tro_scalp import write_json, sha


@njit(cache=True)
def detect_breakout(h1,m5,atr1,atr5,ma1,start,stop):
    rows=[]
    active=np.zeros(2,dtype=np.int64);levels=np.zeros(2);extreme=np.zeros(2)
    for i in range(30,len(m5)):
        at=m5[i,0]+300
        if at<start:continue
        if at>=stop:break
        a=atr5[i]
        if a<=0:continue
        hour=int(m5[i,0]//3600)%24
        allowed=hour in (8,9,10,11,13,15,16,17)
        tr=np.searchsorted(h1[:,0],m5[i,0],side='right')-2
        if tr<0 or atr1[tr]<=0:continue
        distance=abs(h1[tr,4]-ma1[tr])/atr1[tr]
        o,h,l,close=m5[i,1],m5[i,2],m5[i,3],m5[i,4]
        for side in range(2):
            buy=bool(side);d=1 if buy else -1
            aligned=(h1[tr,4]-ma1[tr])*d>0 and distance<=1.75
            br=active[side]
            if br:
                if i-br>6 or not allowed or not aligned or d*(close-levels[side]) < -a:
                    active[side]=0
                else:
                    extreme[side]=min(extreme[side],l) if buy else max(extreme[side],h)
                    touched=l<=levels[side]+.10*a if buy else h>=levels[side]-.10*a
                    if touched and d*(close-levels[side])>0 and d*(close-o)>=.10*a:
                        anchor=extreme[side]
                        r=np.zeros(36)
                        r[0:8]=np.array([m5[i,0],at,int(buy),m5[br,0],1.,0.,0.,float(br)])
                        r[8:18]=np.array([100.,0.,anchor,levels[side],m5[br,0]+300,m5[br,0],anchor,m5[br,0],levels[side],m5[br,0]+300])
                        r[18:27]=np.array([a,anchor-d*.25*a,anchor,close,(o+close)/2,h1[tr,0],h1[tr,4],ma1[tr],atr1[tr]])
                        r[34:36]=np.array([i,tr+1])
                        rows.append(r);active[side]=0
            if active[side] or not allowed or not aligned:continue
            level=np.max(m5[i-20:i,2]) if buy else np.min(m5[i-20:i,3])
            if d*(close-level)>0 and d*(close-o)>=.5*a:
                active[side]=i;levels[side]=level
                # SL tracks only the subsequent pullback, not the impulse candle.
                extreme[side]=1e20 if buy else -1e20
    result=np.empty((len(rows),36))
    for i in range(len(rows)):result[i]=rows[i]
    return result


def main():
    run=research.ROOT/'reports/can_ho_tro_scalp/20261101_breakout_v2';run.mkdir(parents=True,exist_ok=True)
    specs=[dict(name='BREAKOUT_T05',target='R05',rule='ALL'),
           dict(name='BREAKOUT_T3',target='PRICE3',rule='ALL'),
           dict(name='BREAKOUT_SLOPE_T05',target='R05',rule='SLOPE'),
           dict(name='BREAKOUT_RISK6_T3',target='PRICE3',rule='RISK6')]
    lock=dict(version='breakout_pullback_v2',user_date='2026-11-01',
              source_data_sha256=sha(research.BASE/'rates.npz'),hypotheses=specs,costs=research.COSTS,
              definition='CLOSED M5 breaks preceding 20-bar high/low with directional body>=.5ATR, H1 EMA50 direction and max1.75ATR distance; first pullback within6 bars touches level+-.1ATR and reclaims with directional body>=.1ATR; cancel close beyond level by1ATR or wrong hour/trend; stop pullback extreme+.25ATR',
              family_size=32,bootstrap_seed=20261101,bootstrap_resamples=20000,
              limitations='retrospective; independent setup, not evidence for original H1-zone indicator; no native MQL parity')
    dest=run/'EXPERIMENT_LOCK.json'
    if dest.exists():assert json.loads(dest.read_text(encoding='utf-8'))==lock
    else:write_json(dest,lock)
    data=np.load(research.BASE/'rates.npz');arrays={k:bars_matrix(data[k]) for k in data.files}
    num=np.load(research.BASE/'detector_python.npz')
    start=int(datetime(2021,10,25,tzinfo=timezone.utc).timestamp());stop=int(datetime(2026,10,25,tzinfo=timezone.utc).timestamp())
    print('DETECT breakout/pullback five years',flush=True)
    raw=detect_breakout(arrays['h1'],arrays['m5'],num['atr1'],num['atr5'],num['ma1'],start,stop)
    np.savez_compressed(run/'detector_breakout.npz',raw=raw)
    print('BREAKOUT candidates',len(raw),flush=True)
    features=[research.feature(c,arrays['h1'],num['ma1']) for c in raw]
    rows=[];by_spec={}
    for spec in specs:
        for cost in research.COSTS:
            label=spec['name']+'_'+cost['id']
            trades,rejects=research.run_serial(raw,features,arrays,spec,cost)
            write_json(run/(label+'_trades.json'),trades)
            m=research.summarize(trades,lock)
            rows.append(dict(name=spec['name'],cost=cost['id'],label=label,metrics=m,rejections=rejects))
            if cost['id']=='BASE':by_spec[spec['name']]=trades
            print(label,'n',m['n'],'win',round(m['win_rate'] or 0,2),'PF',round(m['pf'] or 0,3),'R',round(m['total_r'],2),flush=True)
    write_json(run/'summary.json',dict(rows=rows,walkforward=research.evaluate_walkforward(by_spec,raw,features,arrays,specs,research.COSTS[1]),lock_sha256=sha(dest)))
    print('BREAKOUT DONE',flush=True)


if __name__=='__main__':main()
