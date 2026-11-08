#ifndef SCALP_STRUCTURE_PLAN_MQH
#define SCALP_STRUCTURE_PLAN_MQH
#include "ScalpStructureTypes.mqh"
bool SSFillPlan(SSPlan &p,const SSCandidate &c,const datetime when,
                const double bid,const double ask,const double tick,
                const SSExitPolicy policy)
{
   ZeroMemory(p);
   if(!c.valid || when<c.time || when-c.time>60 || bid<=0 || ask<bid || tick<=0) return false;
   int d=SSDirection(c.isBuy);
   double entry=c.isBuy ? ask : bid;
   double stop=SSNormalize(c.anchor-d*.25*c.atr,tick,c.isBuy ? -1 : 1);
   double risk=d*(entry-stop),quote=c.isBuy ? bid : ask;
   if(risk<=2*tick || d*(quote-stop)<=0 || c.opposing<=0) return false;
   double room=d*(c.opposing-entry)/risk;
   if(room<1.5) return false;
   double target=SSNormalize(entry+d*1.5*risk,tick,d);
   if(d*(c.opposing-target)<-tick*1e-7)return false;
   p.active=true;p.isBuy=c.isBuy;p.signalTime=c.time;p.anchorTime=c.anchorTime;p.entryTime=when;
   p.entry=entry;p.initialStop=stop;p.stop=stop;p.risk=risk;
   p.target=target;p.roomR=room;p.policy=policy;p.result=SS_OPEN;
   return true;
}
void SSClosePlan(SSPlan &p,const double price,const datetime when,const SSResult reason)
{
   if(!p.active) return;
   p.active=false;p.exitPrice=price;p.exitTime=when;p.result=reason;
   p.resultR=SSDirection(p.isBuy)*(price-p.entry)/p.risk;
}
void SSApplyTrail(SSPlan &p,const SSTrail &proposal,const datetime when,
                  const double bid,const double ask,const double tick)
{
   if(!p.active || p.policy!=SS_STRUCTURE_TRAIL || proposal.time<=0 ||
      proposal.time>when || proposal.anchorTime<p.entryTime || proposal.isBuy!=p.isBuy) return;
   int d=SSDirection(p.isBuy);
   double s=SSNormalize(proposal.stop,tick,p.isBuy ? -1 : 1);
   double quote=p.isBuy ? bid : ask;
   if(d*(s-p.stop)>tick*.1 && d*(quote-s)>tick*.1) p.stop=s;
}
void SSOnQuote(SSPlan &p,const datetime when,const double bid,const double ask)
{
   if(!p.active) return;
   double q=p.isBuy ? bid : ask;int d=SSDirection(p.isBuy);
   if(d*(q-p.stop)<=0) {SSClosePlan(p,q,when,SS_GAP);return;}
   if(p.policy==SS_FIXED_15 && d*(q-p.target)>=0)
   {SSClosePlan(p,p.target,when,SS_TARGET);return;}
   if(when>=p.entryTime+21600) SSClosePlan(p,q,when,SS_TIME);
}
void SSOnMinuteRange(SSPlan &p,const SSBar &bar,const double spread)
{
   if(!p.active) return;
   double hi=bar.high+(p.isBuy ? 0 : spread);
   double lo=bar.low+(p.isBuy ? 0 : spread);
   if(p.isBuy ? lo<=p.stop : hi>=p.stop)
   {SSClosePlan(p,p.stop,bar.time+59,SS_STOP);return;}
   if(p.policy==SS_FIXED_15 && (p.isBuy ? hi>=p.target : lo<=p.target))
      SSClosePlan(p,p.target,bar.time+59,SS_TARGET);
}
#endif
