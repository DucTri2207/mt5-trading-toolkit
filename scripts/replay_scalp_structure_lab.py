"""P2 structure lab: closed-bar detector and sequential M1 replay; no orders."""
from __future__ import annotations

import argparse
import bisect
import csv
import hashlib
import json
import math
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
RUN = ROOT / 'reports' / 'scalp_structure_lab' / '20261025_pilot_v1'


def write_json(path, value):
    Path(path).write_text(json.dumps(value, ensure_ascii=False, indent=2,
                                    allow_nan=False), encoding='utf-8')


def stamp(value):
    return int(datetime.fromisoformat(value).timestamp())


def iso(value):
    return datetime.fromtimestamp(int(value), timezone.utc).isoformat()


def normalized(price, tick, direction):
    units = price / tick
    return (math.floor(units + 1e-9) if direction < 0
            else math.ceil(units - 1e-9)) * tick


@dataclass
class Pivot:
    index: int
    time: int
    price: float
    known: int


class Detector:
    """Pure chronological M5/H1 swing state; no terminal or account access."""
    def __init__(self, seconds=300):
        self.seconds = seconds
        self.bars = []
        self.highs = []
        self.lows = []
        self.atr = 0.0
        self.tr_sum = 0.0
        self.used_buy = -1
        self.used_sell = -1
        self.trailed_buy = -1
        self.trailed_sell = -1

    def step(self, bar):
        t, o, h, l, c = int(bar['time']), float(bar['open']), float(bar['high']), float(bar['low']), float(bar['close'])
        if self.bars and t <= self.bars[-1][0]:
            raise ValueError('Bars must be strictly chronological')
        prev_close = self.bars[-1][4] if self.bars else c
        tr = max(h-l, abs(h-prev_close), abs(l-prev_close))
        self.bars.append((t,o,h,l,c))
        i = len(self.bars)-1
        if i < 14:
            self.tr_sum += tr
            if i == 13:
                self.atr = self.tr_sum/14.0
        else:
            self.atr = (self.atr*13.0+tr)/14.0
        known = t+self.seconds
        if i >= 4:
            p = i-2
            x = self.bars[p]
            # Strict on the left, inclusive on the right: first plateau pivot.
            if all(x[2] > self.bars[j][2] for j in (p-2,p-1)) and all(x[2] >= self.bars[j][2] for j in (p+1,p+2)):
                self.highs.append(Pivot(p,x[0],x[2],known))
            if all(x[3] < self.bars[j][3] for j in (p-2,p-1)) and all(x[3] <= self.bars[j][3] for j in (p+1,p+2)):
                self.lows.append(Pivot(p,x[0],x[3],known))
        candidates, updates = [], []
        if self.atr <= 0 or len(self.highs)<2 or len(self.lows)<2:
            return candidates, updates
        a,b = self.highs[-2:]
        d,e = self.lows[-2:]
        if self.seconds == 300:
            up = b.price>a.price and e.price>d.price
            down = b.price<a.price and e.price<d.price
            low_valid=all(x[3]>=e.price for x in self.bars[e.index+1:i+1])
            high_valid=all(x[2]<=b.price for x in self.bars[b.index+1:i+1])
            if up and low_valid and e.index>b.index and i-e.index<=12 and c>self.bars[i-1][2] and c>o and e.time!=self.used_buy:
                self.used_buy=e.time
                candidates.append(dict(time=known,buy=True,anchor_time=e.time,
                                       anchor=e.price,atr=self.atr,trigger=c))
            if down and high_valid and b.index>e.index and i-b.index<=12 and c<self.bars[i-1][3] and c<o and b.time!=self.used_sell:
                self.used_sell=b.time
                candidates.append(dict(time=known,buy=False,anchor_time=b.time,
                                       anchor=b.price,atr=self.atr,trigger=c))
            before_low=next((p for p in reversed(self.highs) if p.index<e.index),None)
            if before_low and low_valid and e.time!=self.trailed_buy and c>before_low.price:
                self.trailed_buy=e.time
                updates.append(dict(time=known,buy=True,anchor_time=e.time,
                                    stop=e.price-.25*self.atr))
            before_high=next((p for p in reversed(self.lows) if p.index<b.index),None)
            if before_high and high_valid and b.time!=self.trailed_sell and c<before_high.price:
                self.trailed_sell=b.time
                updates.append(dict(time=known,buy=False,anchor_time=b.time,
                                    stop=b.price+.25*self.atr))
        return candidates,updates

    def levels(self, buy, asof):
        pivots=self.highs if buy else self.lows
        max_age=288*300 if self.seconds==300 else 345600
        out=[]
        for p in reversed(pivots):
            if asof-p.time>max_age:break
            out.append(p.price)
        return out


def fetch_data():
    import MetaTrader5 as mt5
    RUN.mkdir(parents=True,exist_ok=True)
    cfg=json.loads((RUN/'SPEC_LOCK.json').read_text())
    if not mt5.initialize(timeout=60000):
        raise RuntimeError(str(mt5.last_error()))
    try:
        info=mt5.symbol_info('XAUUSD')
        metadata={'symbol':info.name,'point':info.point,'tick_size':info.trade_tick_size,
                  'digits':info.digits,'retrieved_utc':datetime.now(timezone.utc).isoformat()}
        start=datetime.fromisoformat(cfg['warmup_start_utc'])
        end=datetime.fromisoformat(cfg['period_end_exclusive_utc'])
        datasets={}
        for name,tf in [('m1',mt5.TIMEFRAME_M1),('m5',mt5.TIMEFRAME_M5),('h1',mt5.TIMEFRAME_H1),('d1',mt5.TIMEFRAME_D1)]:
            pieces=[]
            for year in range(start.year,end.year+1):
                left=max(start,datetime(year,1,1,tzinfo=timezone.utc))
                right=min(end,datetime(year+1,1,1,tzinfo=timezone.utc))
                if right<=left: continue
                rates=mt5.copy_rates_range('XAUUSD',tf,left,right)
                if rates is None or not len(rates):
                    raise RuntimeError(f'{name}/{year}: missing data {mt5.last_error()}')
                pieces.append(rates)
            rates=np.concatenate(pieces)
            rates=rates[np.argsort(rates['time'],kind='stable')]
            _,keep=np.unique(rates['time'],return_index=True)
            rates=rates[np.sort(keep)]
            rates=rates[rates['time']<int(end.timestamp())]
            datasets[name]=rates
            metadata[name]={'n':len(rates),'first':iso(rates[0]['time']),
                            'last':iso(rates[-1]['time'])}
            print('FETCH',name,metadata[name],flush=True)
        np.savez_compressed(RUN/'rates.npz',**datasets)
        metadata['sha256']=hashlib.sha256((RUN/'rates.npz').read_bytes()).hexdigest()
        write_json(RUN/'data_manifest.json',metadata)
    finally:
        mt5.shutdown()


def detect(data):
    m5,h1,d1=data['m5'],data['h1'],data['d1']
    fast,slow=Detector(),Detector(3600)
    hi=di=0
    candidates,updates=[],[]
    start=stamp(json.loads((RUN/'SPEC_LOCK.json').read_text())['period_start_utc'])
    for bar in m5:
        asof=int(bar['time'])+300
        while hi<len(h1) and int(h1[hi]['time'])+3600<=asof:
            slow.step(h1[hi]); hi+=1
        while di<len(d1) and int(d1[di]['time'])+86400<=asof:
            di+=1
        found,changed=fast.step(bar)
        if asof<start: continue
        updates.extend(changed)
        for s in found:
            levels=fast.levels(s['buy'],asof)+slow.levels(s['buy'],asof)
            if di:
                levels.append(float(d1[di-1]['high' if s['buy'] else 'low']))
            directional=[x for x in levels if (x>s['trigger'] if s['buy'] else x<s['trigger'])]
            s['opposing']=min(directional) if s['buy'] and directional else max(directional) if directional else 0.0
            s['id']=f"XAUUSD:P2:{'BUY' if s['buy'] else 'SELL'}:{s['anchor_time']}:{s['time']}"
            candidates.append(s)
    return candidates,updates


def metrics(trades):
    if not trades:return dict(n=0,wins=0,losses=0,be=0,win_rate=0.0,r=0.0,pf=None,dd=0.0)
    r=np.array([x['r'] for x in trades])
    gains=r[r>1e-9]; losses=r[r< -1e-9]
    equity=np.r_[0.0,np.cumsum(r)]
    return dict(n=len(r),wins=len(gains),losses=len(losses),be=int(np.sum(abs(r)<=1e-9)),
                win_rate=100*len(gains)/len(r),r=float(r.sum()),
                pf=float(gains.sum()/-losses.sum()) if len(losses) else None,
                dd=float(np.max(np.maximum.accumulate(equity)-equity)),
                mean_win_r=float(gains.mean()) if len(gains) else 0.0,
                mean_loss_r=float(losses.mean()) if len(losses) else 0.0,
                expectancy=float(r.mean()),
                realized_at_least_1_5r=int(np.sum(r>=1.5-1e-9)))


def simulate_trade(signal, bars, times, updates, update_times, spread, tick,
                   policy, skip_room=False, target_r=1.5):
    start=int(np.searchsorted(times,signal['time'],side='left'))
    if start>=len(bars) or int(times[start])-signal['time']>60:
        return {'status':'NO_ENTRY_QUOTE','id':signal['id']}
    buy=signal['buy']
    direction=1 if buy else -1
    entry_time=int(times[start])
    entry=float(bars[start]['open'])+(spread if buy else 0.0)
    raw_stop=signal.get('initial_stop',signal['anchor']+(-.25 if buy else .25)*signal['atr'])
    stop=normalized(raw_stop,tick,-1 if buy else 1)
    risk=direction*(entry-stop)
    exit_open=float(bars[start]['open'])+(0.0 if buy else spread)
    if risk<=2*tick or direction*(exit_open-stop)<=0:
        return {'status':'REJECT_STOP','id':signal['id']}
    room=direction*(signal['opposing']-entry)/risk if signal['opposing'] else None
    if not skip_room and (room is None or room<1.5):
        return {'status':'REJECT_ROOM','id':signal['id'],'room_r':room}
    target=normalized(entry+direction*target_r*risk,tick,direction)
    effective_target_r=direction*(target-entry)/risk
    if not skip_room and direction*(signal['opposing']-target)<-tick*1e-7:
        return {'status':'REJECT_ROOM','id':signal['id'],'room_r':room}
    deadline=entry_time+21600
    u=int(np.searchsorted(update_times,entry_time,side='left'))
    events=[]
    mfe=mae=0.0
    first_hits={}
    ambiguous=0
    row=dict(id=signal['id'],buy=buy,signal_time=signal['time'],entry_time=entry_time,
             entry=entry,initial_stop=stop,risk=risk,room_r=room,policy=policy)
    def finish(price, when, reason, minute_index):
        row.update(exit_time=int(when),exit_price=price,status=reason,
                   r=direction*(price-entry)/risk,stop=stop,mfe_r=mfe,
                   mae_r=mae,first_hits=first_hits,ambiguous_bars=ambiguous,
                   stop_events=events,exit_minute_index=minute_index)
        return row
    for i in range(start,len(bars)):
        bar=bars[i]; now=int(times[i])
        open_px=float(bar['open'])+(0.0 if buy else spread)
        high=float(bar['high'])+(0.0 if buy else spread)
        low=float(bar['low'])+(0.0 if buy else spread)
        adverse_open=direction*(open_px-stop)<=0
        if adverse_open:
            mae=min(mae,direction*(open_px-entry)/risk)
            return finish(open_px,now,'STOP_GAP',i)
        if policy=='E0_FIXED_1_5R' and direction*(open_px-target)>=0:
            mfe=max(mfe,effective_target_r)
            for threshold in (1.0,1.5,2.0):
                if effective_target_r>=threshold-1e-9:first_hits.setdefault(str(threshold),now)
            return finish(target,now,'TARGET',i)
        if now>=deadline:
            return finish(open_px,now,'TIME',i)
        # A stop proposal is known at this minute's open, never before it.
        if policy=='E1_STRUCTURE_TRAIL':
            while u<len(updates) and updates[u]['time']<=now:
                ev=updates[u];u+=1
                if ev['buy']!=buy or ev['anchor_time']<entry_time:continue
                candidate=normalized(ev['stop'],tick,-1 if buy else 1)
                if direction*(candidate-stop)>tick*.1 and direction*(open_px-candidate)>tick*.1:
                    events.append({'time':now,'known':ev['time'],'old':stop,'new':candidate,
                                   'anchor_time':ev['anchor_time']})
                    stop=candidate
        stop_hit=(low<=stop if buy else high>=stop)
        target_hit=(high>=target if buy else low<=target)
        if stop_hit:
            if policy=='E0_FIXED_1_5R' and target_hit:ambiguous+=1
            mae=min(mae,direction*(stop-entry)/risk)
            return finish(stop,now+59,'STOP',i)
        favorable=direction*((high if buy else low)-entry)/risk
        if policy=='E0_FIXED_1_5R':favorable=min(favorable,effective_target_r)
        adverse=direction*((low if buy else high)-entry)/risk
        mfe=max(mfe,favorable);mae=min(mae,adverse)
        for threshold in (1.0,1.5,2.0):
            if favorable>=threshold-1e-9:first_hits.setdefault(str(threshold),now+59)
        if policy=='E0_FIXED_1_5R' and target_hit:
            return finish(target,now+59,'TARGET',i)
    row.update(status='UNRESOLVED',mfe_r=mfe,mae_r=mae,first_hits=first_hits,
               stop_events=events)
    return row


def serial_replay(signals, m1, updates, spread, tick, policy,skip_room=False,target_r=1.5):
    times=m1['time'].astype(np.int64)
    update_times=np.array([x['time'] for x in updates],dtype=np.int64)
    trades,rejected=[],Counter()
    busy_until=-1
    for s in signals:
        if s['time']<=busy_until:
            rejected['OVERLAP']+=1;continue
        row=simulate_trade(s,m1,times,updates,update_times,spread,tick,policy,skip_room,target_r)
        if 'r' not in row:
            rejected[row['status']]+=1
            if row['status']=='UNRESOLVED':busy_until=int(times[-1])+60
            continue
        trades.append(row)
        busy_until=row['exit_time']
    summary=metrics(trades)
    summary['trades_per_month']=len(trades)/60.0
    summary['rejected']=dict(rejected)
    summary['by_year']={str(y):metrics([r for r in trades if datetime.fromtimestamp(r['entry_time'],timezone.utc).year==y]) for y in range(2021,2027)}
    summary['oos_retrospective_2025_2026']=metrics([r for r in trades if datetime.fromtimestamp(r['entry_time'],timezone.utc).year>=2025])
    summary['by_side']={side:metrics([r for r in trades if r['buy']==buy]) for side,buy in [('BUY',True),('SELL',False)]}
    summary['months']=dict(Counter(datetime.fromtimestamp(r['entry_time'],timezone.utc).strftime('%Y-%m') for r in trades))
    summary['ambiguities']=sum(r['ambiguous_bars'] for r in trades)
    return summary,trades


def export_detector_csv(data, candidates, updates):
    for name in ('m1','m5','h1','d1'):
        with (RUN/f'{name}.csv').open('w',newline='',encoding='ascii') as f:
            writer=csv.writer(f)
            for bar in data[name]:
                writer.writerow([int(bar['time'])]+[format(float(bar[k]),'.10f') for k in ('open','high','low','close')])
    with (RUN/'candidates_python.csv').open('w',newline='',encoding='ascii') as f:
        writer=csv.writer(f)
        for s in candidates:
            writer.writerow([s['time'],int(s['buy']),s['anchor_time'],s['anchor'],s['atr'],s['trigger'],s['opposing']])
    with (RUN/'trails_python.csv').open('w',newline='',encoding='ascii') as f:
        writer=csv.writer(f)
        for s in updates:writer.writerow([s['time'],int(s['buy']),s['anchor_time'],s['stop']])


def run_backtest(export_csv=True):
    data=np.load(RUN/'rates.npz')
    manifest=json.loads((RUN/'data_manifest.json').read_text())
    candidates,updates=detect(data)
    write_json(RUN/'candidates.json',candidates)
    write_json(RUN/'trailing_proposals.json',updates)
    if export_csv:export_detector_csv(data,candidates,updates)
    print('DETECT',len(candidates),'candidates',len(updates),'trails',flush=True)
    summaries=[]
    for spread in (.2,.5,1.0):
        for policy in ('E0_FIXED_1_5R','E1_STRUCTURE_TRAIL'):
            summary,trades=serial_replay(candidates,data['m1'],updates,spread,
                                         manifest['tick_size'],policy)
            summary.update(spread=spread,policy=policy)
            summaries.append(summary)
            write_json(RUN/f'trades_{policy}_{spread}.json',trades)
            print('RESULT',spread,policy,json.dumps({k:summary[k] for k in ['n','win_rate','r','pf','dd','mean_win_r','rejected']}),flush=True)
    write_json(RUN/'backtest_summary.json',{'spec_version':'p2_structure_0.1',
        'generated_utc':datetime.now(timezone.utc).isoformat(),
        'raw_candidates':len(candidates),'trailing_proposals':len(updates),
        'rows':summaries,'limitations':['synthetic spread on Bid M1 OHLC; not tick replay',
        'same-minute path unknown; adverse-first',
        '2025-2026 is retrospective, not pristine OOS',
        'zero extra commission is unverified; no claim of fund pass']})


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('command',choices=['fetch','run'])
    parser.add_argument('--skip-csv',action='store_true',help='Reuse unchanged raw CSV inputs for a replay-only rerun')
    args=parser.parse_args()
    if args.command=='fetch':fetch_data();return
    run_backtest(not args.skip_csv)


if __name__=='__main__':main()
