"""Pure quote/range manager for the existing scalp setup; no terminal access."""
from __future__ import annotations

import math
from dataclasses import dataclass, field

import numpy as np


def round_tick(price, tick, direction):
    units=price/tick
    return (math.floor(units+1e-9) if direction<0 else math.ceil(units-1e-9))*tick


def idea_key(c):
    return '|'.join(str(int(c[k])) for k in (3,4,5,6,2,13))


def room_ok(entry, stop, obstacle, atr, buy, tick):
    if obstacle<=0:
        return False, 'ROOM_UNKNOWN', None
    d=1 if buy else -1
    risk=d*(entry-stop)
    if risk<=0:
        return False,'RISK',None
    boundary=obstacle-d*max(tick,.10*atr)
    room=d*(boundary-entry)/risk
    target=round_tick(entry+d*1.5*risk,tick,d)
    valid=room>=1.5-1e-12 and d*(boundary-target)>=-tick*1e-8
    return valid,('PASS' if valid else 'ROOM'),room


def planned_gate(c, tick=.01, retest=False, room=False):
    if c[27]!=0:return 'SOURCE_'+str(int(c[27]))
    if c[28]!=0:return 'LEVEL_NOT_KNOWN_AT_SWEEP'
    buy=bool(c[2]);d=1 if buy else -1
    entry=round_tick(c[22],tick,-d) if retest else float(c[21])
    stop=round_tick(c[19],tick,-d)
    risk=d*(entry-stop)
    if risk>20.+1e-9:return 'PLANNED_MAX_RISK'
    if risk<2.:stop=round_tick(entry-d*2.,tick,-d)
    if room:
        ok,reason,_=room_ok(entry,stop,c[30 if retest else 29],c[18],buy,tick)
        if not ok:return reason
    return 'PASS'


@dataclass
class Plan:
    c: np.ndarray
    policy: str='T05'
    spread: float=.2
    slip: float=0.
    tick: float=.01
    room: bool=False
    retest: bool=False
    state: str='READY'
    reason: str=''
    entry: float=0.
    entry_time: int=0
    initial_sl: float=0.
    stop: float=0.
    risk: float=0.
    target: float=0.
    deadline: int=0
    exit_price: float=0.
    exit_time: int=0
    r: float=0.
    mfe: float=0.
    mae: float=0.
    room_r: object=None
    seq: int=0
    proposal: object=None
    protected_p: float=0.
    protected_h: float=0.
    protected_h_time: int=0
    tried_p: set=field(default_factory=set)
    events: list=field(default_factory=list)
    first_hits: dict=field(default_factory=dict)
    ambiguous: int=0
    gaps: int=0
    last_quote_time: int=0
    observer: object=None
    pending_hours: tuple=(8,9,10,11,13,15,16,17)

    @property
    def buy(self):return bool(self.c[2])

    @property
    def d(self):return 1 if self.buy else -1

    @property
    def requested(self):
        return round_tick(self.c[22],self.tick,-self.d) if self.retest else float(self.c[21])

    @property
    def obstacle(self):return float(self.c[30 if self.retest else 29])

    @property
    def raw_sl(self):return round_tick(self.c[19],self.tick,-self.d)

    def event(self,kind,at,**values):
        self.events.append(dict(kind=kind,time=int(at),sequence=self.seq,**values))

    def observe(self,price,at):
        progress=self.d*(price-self.entry)/self.risk
        if self.observer is not None:self.observer(int(at),float(progress))
        self.mfe=max(self.mfe,progress);self.mae=min(self.mae,progress)
        for threshold in (1.,1.5,2.):
            if progress>=threshold-1e-9:self.first_hits.setdefault(str(threshold),int(at))

    def close(self,price,at,reason):
        if self.state!='FILLED':return
        self.state='CLOSED';self.reason=reason;self.exit_price=float(price);self.exit_time=int(at)
        self.r=self.d*(price-self.entry)/self.risk
        if self.observer is not None:self.observer(int(at),float(self.r))
        self.event(reason,at,price=price,r=self.r)

    def fill(self,at,bid,ask):
        price=self.requested if self.retest else ((ask+self.slip) if self.buy else (bid-self.slip))
        side=bid if self.buy else ask
        stop=self.raw_sl;risk=self.d*(price-stop)
        if self.d*(side-stop)<=0 or risk<=0 or risk>20.+1e-9:
            self.state='REJECTED';self.reason='REJECT_AT_FILL_RISK';self.event(self.reason,at);return
        if risk<2.:stop=round_tick(price-self.d*2.,self.tick,-self.d)
        risk=self.d*(price-stop)
        if risk>20.+1e-9 or self.d*(side-stop)<self.tick-1e-9:
            self.state='REJECTED';self.reason='REJECT_AT_FILL_STOP';self.event(self.reason,at);return
        if self.room:
            ok,reason,self.room_r=room_ok(price,stop,self.obstacle,self.c[18],self.buy,self.tick)
            if not ok:
                self.state='REJECTED';self.reason='REJECT_AT_FILL_'+reason;self.event(self.reason,at);return
        self.entry=float(price);self.entry_time=int(at);self.initial_sl=float(stop);self.stop=float(stop);self.risk=float(risk)
        self.state='FILLED';self.deadline=0 if self.policy=='C0_NATIVE' else int(at)+21600
        target_r=0.5 if self.policy in ('T05','C0_NATIVE') else 1.5
        self.target=0. if self.policy=='TS' else round_tick(price+self.d*target_r*risk,self.tick,self.d)
        self.protected_p=float(self.c[20]);self.event('FILL',at,price=price,initial_sl=stop,risk=risk)
        self.observe(side,at)

    def start(self,at,bid,ask):
        gate=planned_gate(self.c,self.tick,self.retest,self.room)
        if gate!='PASS':self.state='REJECTED';self.reason=gate;return
        if not (0<=at-int(self.c[1])<=60):self.state='REJECTED';self.reason='NO_ENTRY_QUOTE';return
        if bid<=0 or ask<bid or ask-bid>.45+1e-9:
            self.state='REJECTED';self.reason='SPREAD_OR_QUOTE';return
        if self.retest:
            if (self.buy and self.requested>=ask-1e-12) or (not self.buy and self.requested<=bid+1e-12):
                self.state='REJECTED';self.reason='LIMIT_NOT_PASSIVE';return
            self.state='PENDING';self.deadline=int(self.c[1])+900
            self.event('PENDING',at,requested=self.requested)
        else:self.fill(at,bid,ask)

    def quote(self,at,bid,ask,cancel_pending=False):
        if bid<=0 or ask<bid or (self.last_quote_time and at<self.last_quote_time):return
        self.seq+=1;self.last_quote_time=int(at)
        side=bid if self.buy else ask
        if self.state=='PENDING':
            hour=int(at//3600)%24
            stop_cancel=self.d*(side-self.raw_sl)<=0
            obstacle_cancel=self.room and self.obstacle>0 and self.d*(side-self.obstacle)>=0
            if at>=self.deadline or cancel_pending or stop_cancel or obstacle_cancel or hour not in self.pending_hours:
                self.state='EXPIRED' if at>=self.deadline else 'CANCELLED'
                self.reason=self.state;self.exit_time=int(at);self.event(self.state,at);return
            if (self.buy and ask<=self.requested+1e-12) or (not self.buy and bid>=self.requested-1e-12):
                if ask-bid>.45+1e-9:
                    self.state='REJECTED';self.reason='REJECT_AT_FILL_SPREAD';return
                self.fill(at,bid,ask)
        if self.state!='FILLED':return
        if self.d*(side-self.stop)<=0:
            self.observe(side,at)
            self.close(side-self.d*self.slip,at,'STOP_GAP' if self.d*(side-self.stop)<-1e-9 else 'STOP');return
        if self.target and self.d*(side-self.target)>=0:
            self.observe(self.target,at);self.close(self.target,at,'TARGET');return
        if self.deadline and at>=self.deadline:
            self.observe(side,at);self.close(side-self.d*self.slip,at,'TIME');return
        if self.proposal and self.seq>self.proposal['sequence']:
            prop=self.proposal;self.proposal=None
            valid=self.d*(prop['stop']-self.stop)>=self.tick-1e-9 and self.d*(side-prop['stop'])>=self.tick-1e-9
            if valid:
                old=self.stop;self.stop=prop['stop'];self.protected_p=prop['p_price'];self.protected_h=prop['h_price'];self.protected_h_time=prop['h_time']
                self.event('STOP_APPLIED',at,old=old,new=self.stop,known=prop['known'],p_time=prop['p_time'],h_time=prop['h_time'])
            else:self.event('STOP_REJECTED',at,proposed=prop['stop'])
        self.observe(side,at)

    def propose(self,at,stop,p_time,p_price,h_time,h_price):
        if self.state!='FILLED' or p_time in self.tried_p:return
        self.tried_p.add(p_time)
        self.proposal=dict(known=int(at),stop=stop,p_time=int(p_time),p_price=p_price,h_time=int(h_time),h_price=h_price,sequence=self.seq)
        self.event('STOP_PROPOSED',at,old=self.stop,new=stop,p_time=int(p_time),h_time=int(h_time))

    def minute_range(self,at,high,low,close=None):
        if self.state!='FILLED':return
        h=high+(0 if self.buy else self.spread)
        l=low+(0 if self.buy else self.spread)
        hit_stop=l<=self.stop if self.buy else h>=self.stop
        hit_target=bool(self.target) and (h>=self.target if self.buy else l<=self.target)
        if hit_stop:
            if hit_target:self.ambiguous+=1
            self.observe(self.stop,at+59);self.close(self.stop-self.d*self.slip,at+59,'STOP');return
        if hit_target:
            self.observe(self.target,at+59);self.close(self.target,at+59,'TARGET');return
        self.observe(l if self.buy else h,at+59);self.observe(h if self.buy else l,at+59)
        if close is not None:self.observe(close+(0 if self.buy else self.spread),at+59)


def pivots(m5):
    high=[];low=[]
    for p in range(2,len(m5)-2):
        time=int(m5[p,0]);known=int(m5[p+2,0])+300
        if m5[p,2]>max(m5[p-2,2],m5[p-1,2]) and m5[p,2]>=max(m5[p+1,2],m5[p+2,2]):
            high.append((p,time,float(m5[p,2]),known))
        if m5[p,3]<min(m5[p-2,3],m5[p-1,3]) and m5[p,3]<=min(m5[p+1,3],m5[p+2,3]):
            low.append((p,time,float(m5[p,3]),known))
    return np.array(high,dtype=float).reshape(-1,4),np.array(low,dtype=float).reshape(-1,4)


def propose_structure(p,at,c_index,m5,atr5,highs,lows):
    if p.state!='FILLED':return
    hp,pp=(highs,lows) if p.buy else (lows,highs)
    close=float(m5[c_index,4])
    for pi in range(np.searchsorted(pp[:,3],at,side='right')-1,-1,-1):
        pullback=pp[pi];p_time=int(pullback[1]);p_price=float(pullback[2])
        if p_time<p.entry_time:break
        if p_time in p.tried_p or p.d*(p_price-p.protected_p)<p.tick-1e-9:continue
        for hi in range(np.searchsorted(hp[:,1],p_time,side='left')-1,-1,-1):
            anchor=hp[hi];h_time=int(anchor[1]);h_price=float(anchor[2])
            if h_time<p.entry_time:break
            if anchor[3]>at or h_time<=p.protected_h_time:continue
            if p.protected_h_time and p.d*(h_price-p.protected_h)<p.tick-1e-9:continue
            if p.d*(close-h_price)<p.tick-1e-9:continue
            stop=round_tick(p_price-p.d*.25*atr5[c_index],p.tick,-p.d)
            p.propose(at,stop,p_time,p_price,h_time,h_price)
            return
