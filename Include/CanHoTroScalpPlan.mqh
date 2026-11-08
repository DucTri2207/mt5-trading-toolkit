#ifndef CAN_HO_TRO_SCALP_PLAN
#define CAN_HO_TRO_SCALP_PLAN
#include "CanHoTroScalpTypes.mqh"

enum CHTPolicy {CHT_T05=0,CHT_T15=1,CHT_TS=2,CHT_NATIVE=3};
enum CHTState {CHT_READY=0,CHT_PENDING=1,CHT_FILLED=2,CHT_CLOSED=3,CHT_REJECTED=4,CHT_EXPIRED=5,CHT_CANCELLED=6};
enum CHTReason {CHT_NONE=0,CHT_FILL=1,CHT_STOP=2,CHT_TARGET=3,CHT_TIME=4,CHT_EXPIRE=5,
                CHT_CANCEL=6,CHT_RISK=7,CHT_GAP=8,CHT_CENSORED=9,CHT_PROPOSE=10,CHT_APPLY=11,
                CHT_TRAIL_REJECT=12,CHT_ROOM_UNKNOWN=13,CHT_ROOM=14,CHT_NO_QUOTE=15,
                CHT_SPREAD=16,CHT_LIMIT_PASSIVE=17,CHT_PLACEABLE=18};
struct CHTPivot {int index;datetime time,known;double price;};
struct CHTPlan
{
   CHTCandidate candidate;
   CHTState state;CHTPolicy policy;int reason;
   bool buy,room,retest;double direction,tick,spread,slip,requested,rawStop,obstacle;
   double entry,initialStop,stop,risk,target,resultR,exitPrice,mfe,mae,roomR;
   datetime entryTime,exitTime,deadline,lastQuoteTime;
   long sequence,eventSerial,eventSequence;int eventKind;datetime eventTime;
   double eventOld,eventNew;
   bool proposed;double proposalStop,proposalP,proposalH;
   datetime proposalKnown,proposalPTime,proposalHTime;long proposalSequence;
   double protectedP,protectedH;datetime protectedHTime;
   datetime triedP[128];int triedCount,ambiguous;
   datetime firstHit1,firstHit15,firstHit2;
};
double CHTRound(const double price,const double tick,const int direction)
{
   return (direction<0?MathFloor(price/tick+1e-9):MathCeil(price/tick-1e-9))*tick;
}
void CHTEmit(CHTPlan &p,const int kind,const datetime at,const double oldValue=0.,const double newValue=0.)
{
   p.eventSerial++;p.eventKind=kind;p.eventTime=at;p.eventSequence=p.sequence;p.eventOld=oldValue;p.eventNew=newValue;
}
bool CHTRoomOK(const double entry,const double stop,const double obstacle,const double atr,
               const bool buy,const double tick,double &room,int &reason)
{
   room=-999.;reason=CHT_NONE;
   if(obstacle<=0){reason=CHT_ROOM_UNKNOWN;return false;}
   double d=buy?1.:-1.,risk=d*(entry-stop);
   if(risk<=0){reason=CHT_RISK;return false;}
   double boundary=obstacle-d*MathMax(tick,.10*atr);
   room=d*(boundary-entry)/risk;
   double target=CHTRound(entry+d*1.5*risk,tick,(int)d);
   bool valid=room>=1.5-1e-12 && d*(boundary-target)>=-tick*1e-8;
   if(!valid)reason=CHT_ROOM;return valid;
}
int CHTPlannedGate(const CHTCandidate &c,const double tick,const bool retest,const bool room)
{
   if(c.v[27]!=0)return 100+(int)c.v[27];
   if(c.v[28]!=0)return 105;
   bool buy=(bool)c.v[2];double d=buy?1.:-1.;
   double entry=retest?CHTRound(c.v[22],tick,(int)-d):c.v[21];
   double stop=CHTRound(c.v[19],tick,(int)-d),risk=d*(entry-stop);
   if(risk>20.+1e-9)return CHT_RISK;
   if(risk<2.)stop=CHTRound(entry-d*2.,tick,(int)-d);
   if(room)
   {
      double roomR;int reason;
      if(!CHTRoomOK(entry,stop,c.v[retest?30:29],c.v[18],buy,tick,roomR,reason))return reason;
   }
   return CHT_NONE;
}
void CHTObserve(CHTPlan &p,const double price,const datetime at)
{
   double movement=p.direction*(price-p.entry)/p.risk;
   p.mfe=MathMax(p.mfe,movement);p.mae=MathMin(p.mae,movement);
   if(movement>=1.-1e-9 && p.firstHit1==0)p.firstHit1=at;
   if(movement>=1.5-1e-9 && p.firstHit15==0)p.firstHit15=at;
   if(movement>=2.-1e-9 && p.firstHit2==0)p.firstHit2=at;
}
void CHTClose(CHTPlan &p,const double price,const datetime at,const int reason)
{
   if(p.state!=CHT_FILLED)return;
   p.state=CHT_CLOSED;p.reason=reason;p.exitPrice=price;p.exitTime=at;
   p.resultR=p.direction*(price-p.entry)/p.risk;CHTEmit(p,reason,at,p.entry,price);
}
bool CHTFill(CHTPlan &p,const datetime at,const double bid,const double ask)
{
   double price=p.retest?p.requested:(p.buy?ask+p.slip:bid-p.slip);
   double side=p.buy?bid:ask,stop=p.rawStop,risk=p.direction*(price-stop);
   if(p.direction*(side-stop)<=0 || risk<=0 || risk>20.+1e-9)
   {p.state=CHT_REJECTED;p.reason=CHT_RISK;CHTEmit(p,CHT_RISK,at);return false;}
   if(risk<2.)stop=CHTRound(price-p.direction*2.,p.tick,(int)-p.direction);
   risk=p.direction*(price-stop);
   if(risk>20.+1e-9 || p.direction*(side-stop)<p.tick-1e-9)
   {p.state=CHT_REJECTED;p.reason=CHT_PLACEABLE;CHTEmit(p,CHT_PLACEABLE,at);return false;}
   if(p.room)
   {
      int reason;
      if(!CHTRoomOK(price,stop,p.obstacle,p.candidate.v[18],p.buy,p.tick,p.roomR,reason))
      {p.state=CHT_REJECTED;p.reason=reason;CHTEmit(p,reason,at);return false;}
   }
   p.entry=price;p.entryTime=at;p.initialStop=stop;p.stop=stop;p.risk=risk;p.state=CHT_FILLED;
   p.deadline=p.policy==CHT_NATIVE?0:at+21600;
   double targetR=(p.policy==CHT_T05 || p.policy==CHT_NATIVE)?.5:1.5;
   p.target=p.policy==CHT_TS?0.:CHTRound(price+p.direction*targetR*risk,p.tick,(int)p.direction);
   p.protectedP=p.candidate.v[20];CHTEmit(p,CHT_FILL,at,stop,price);CHTObserve(p,side,at);return true;
}
void CHTStart(CHTPlan &p,const CHTCandidate &c,const CHTPolicy policy,const double spread,
               const double slip,const double tick,const bool room,const bool retest,
               const datetime at,const double bid,const double ask)
{
   ZeroMemory(p);p.candidate=c;p.state=CHT_READY;p.policy=policy;p.spread=spread;p.slip=slip;
   p.tick=tick;p.room=room;p.retest=retest;p.buy=(bool)c.v[2];p.direction=p.buy?1.:-1.;p.roomR=-999.;
   p.requested=retest?CHTRound(c.v[22],tick,(int)-p.direction):c.v[21];
   p.rawStop=CHTRound(c.v[19],tick,(int)-p.direction);p.obstacle=c.v[retest?30:29];
   int gate=CHTPlannedGate(c,tick,retest,room);
   if(gate!=CHT_NONE){p.state=CHT_REJECTED;p.reason=gate;return;}
   if(at<(datetime)c.v[1] || at-(datetime)c.v[1]>60){p.state=CHT_REJECTED;p.reason=CHT_NO_QUOTE;return;}
   if(bid<=0 || ask<bid || ask-bid>.45+1e-9){p.state=CHT_REJECTED;p.reason=CHT_SPREAD;return;}
   if(retest)
   {
      if((p.buy && p.requested>=ask-1e-12)||(!p.buy && p.requested<=bid+1e-12))
      {p.state=CHT_REJECTED;p.reason=CHT_LIMIT_PASSIVE;return;}
      p.state=CHT_PENDING;p.deadline=(datetime)c.v[1]+900;CHTEmit(p,CHT_PENDING,at,0,p.requested);
   }
   else CHTFill(p,at,bid,ask);
}
void CHTQuote(CHTPlan &p,const datetime at,const double bid,const double ask,const bool cancelPending=false)
{
   if(bid<=0 || ask<bid || (p.lastQuoteTime>0 && at<p.lastQuoteTime))return;
   p.sequence++;p.lastQuoteTime=at;double side=p.buy?bid:ask;
   if(p.state==CHT_PENDING)
   {
      MqlDateTime dt;TimeToStruct(at,dt);int hour=dt.hour;
      bool allowed=(hour==8||hour==9||hour==10||hour==11||hour==13||hour==15||hour==16||hour==17);
      bool stopCancel=p.direction*(side-p.rawStop)<=0;
      bool obstacleCancel=p.room && p.obstacle>0 && p.direction*(side-p.obstacle)>=0;
      if(at>=p.deadline || cancelPending || stopCancel || obstacleCancel || !allowed)
      {
         p.state=at>=p.deadline?CHT_EXPIRED:CHT_CANCELLED;p.reason=at>=p.deadline?CHT_EXPIRE:CHT_CANCEL;
         p.exitTime=at;CHTEmit(p,p.reason,at);return;
      }
      if((p.buy && ask<=p.requested+1e-12)||(!p.buy && bid>=p.requested-1e-12))
      {
         if(ask-bid>.45+1e-9){p.state=CHT_REJECTED;p.reason=CHT_SPREAD;return;}
         CHTFill(p,at,bid,ask);
      }
   }
   if(p.state!=CHT_FILLED)return;
   if(p.direction*(side-p.stop)<=0)
   {
      CHTObserve(p,side,at);CHTClose(p,side-p.direction*p.slip,at,
                                  p.direction*(side-p.stop)<-1e-9?CHT_GAP:CHT_STOP);return;
   }
   if(p.target>0 && p.direction*(side-p.target)>=0)
   {CHTObserve(p,p.target,at);CHTClose(p,p.target,at,CHT_TARGET);return;}
   if(p.deadline>0 && at>=p.deadline)
   {CHTObserve(p,side,at);CHTClose(p,side-p.direction*p.slip,at,CHT_TIME);return;}
   if(p.proposed && p.sequence>p.proposalSequence)
   {
      p.proposed=false;
      if(p.direction*(p.proposalStop-p.stop)>=p.tick-1e-9 && p.direction*(side-p.proposalStop)>=p.tick-1e-9)
      {
         double old=p.stop;p.stop=p.proposalStop;p.protectedP=p.proposalP;
         p.protectedH=p.proposalH;p.protectedHTime=p.proposalHTime;CHTEmit(p,CHT_APPLY,at,old,p.stop);
      }
      else CHTEmit(p,CHT_TRAIL_REJECT,at,p.stop,p.proposalStop);
   }
   CHTObserve(p,side,at);
}
bool CHTTried(const CHTPlan &p,const datetime at)
{for(int i=0;i<p.triedCount;i++)if(p.triedP[i]==at)return true;return false;}
void CHTPropose(CHTPlan &p,const datetime at,const double stop,const datetime pTime,
                 const double pPrice,const datetime hTime,const double hPrice)
{
   if(p.state!=CHT_FILLED || CHTTried(p,pTime) || p.triedCount>=128)return;
   p.triedP[p.triedCount++]=pTime;p.proposed=true;p.proposalKnown=at;p.proposalStop=stop;
   p.proposalPTime=pTime;p.proposalP=pPrice;p.proposalHTime=hTime;p.proposalH=hPrice;p.proposalSequence=p.sequence;
   CHTEmit(p,CHT_PROPOSE,at,p.stop,stop);
}
void CHTMinuteRange(CHTPlan &p,const MqlRates &bar)
{
   if(p.state!=CHT_FILLED)return;
   double high=bar.high+(p.buy?0.:p.spread),low=bar.low+(p.buy?0.:p.spread);
   bool stop=p.buy?low<=p.stop:high>=p.stop;
   bool target=p.target>0 && (p.buy?high>=p.target:low<=p.target);
   if(stop)
   {if(target)p.ambiguous++;CHTObserve(p,p.stop,bar.time+59);CHTClose(p,p.stop-p.direction*p.slip,bar.time+59,CHT_STOP);return;}
   if(target){CHTObserve(p,p.target,bar.time+59);CHTClose(p,p.target,bar.time+59,CHT_TARGET);return;}
   CHTObserve(p,p.buy?low:high,bar.time+59);CHTObserve(p,p.buy?high:low,bar.time+59);
   if(bar.close>0)CHTObserve(p,bar.close+(p.buy?0.:p.spread),bar.time+59);
}
void CHTBuildPivots(const MqlRates &bars[],CHTPivot &highs[],CHTPivot &lows[])
{
   ArrayResize(highs,0);ArrayResize(lows,0);
   for(int i=2;i<ArraySize(bars)-2;i++)
   {
      CHTPivot p;p.index=i;p.time=bars[i].time;p.known=bars[i+2].time+300;
      if(bars[i].high>MathMax(bars[i-2].high,bars[i-1].high) && bars[i].high>=MathMax(bars[i+1].high,bars[i+2].high))
      {p.price=bars[i].high;int n=ArraySize(highs);ArrayResize(highs,n+1,4096);highs[n]=p;}
      if(bars[i].low<MathMin(bars[i-2].low,bars[i-1].low) && bars[i].low<=MathMin(bars[i+1].low,bars[i+2].low))
      {p.price=bars[i].low;int n=ArraySize(lows);ArrayResize(lows,n+1,4096);lows[n]=p;}
   }
}
int CHTPivotUpperKnown(const CHTPivot &pivots[],const datetime at)
{
   int l=0,r=ArraySize(pivots);while(l<r){int m=(l+r)/2;if(pivots[m].known<=at)l=m+1;else r=m;}return l;
}
int CHTPivotLowerTime(const CHTPivot &pivots[],const datetime at)
{
   int l=0,r=ArraySize(pivots);while(l<r){int m=(l+r)/2;if(pivots[m].time<at)l=m+1;else r=m;}return l;
}
void CHTStructureSide(CHTPlan &p,const datetime at,const int ci,const MqlRates &bars[],
                       const double &atr[],const CHTPivot &anchors[],const CHTPivot &pullbacks[])
{
   for(int pi=CHTPivotUpperKnown(pullbacks,at)-1;pi>=0;pi--)
   {
      CHTPivot pb=pullbacks[pi];if(pb.time<p.entryTime)break;
      if(CHTTried(p,pb.time) || p.direction*(pb.price-p.protectedP)<p.tick-1e-9)continue;
      for(int hi=CHTPivotLowerTime(anchors,pb.time)-1;hi>=0;hi--)
      {
         CHTPivot h=anchors[hi];if(h.time<p.entryTime)break;
         if(h.known>at || h.time<=p.protectedHTime)continue;
         if(p.protectedHTime>0 && p.direction*(h.price-p.protectedH)<p.tick-1e-9)continue;
         if(p.direction*(bars[ci].close-h.price)<p.tick-1e-9)continue;
         double stop=CHTRound(pb.price-p.direction*.25*atr[ci],p.tick,(int)-p.direction);
         CHTPropose(p,at,stop,pb.time,pb.price,h.time,h.price);return;
      }
   }
}
void CHTStructure(CHTPlan &p,const datetime at,const int ci,const MqlRates &bars[],
                  const double &atr[],const CHTPivot &highs[],const CHTPivot &lows[])
{
   if(p.state!=CHT_FILLED)return;
   if(p.buy)CHTStructureSide(p,at,ci,bars,atr,highs,lows);
   else CHTStructureSide(p,at,ci,bars,atr,lows,highs);
}
void CHTPathSegment(CHTPlan &p,const datetime t0,const double x0,const datetime t1,const double x1,const datetime cancelAt=0)
{
   double cursor=x0;datetime cursorTime=t0;
   while(p.state==CHT_PENDING || p.state==CHT_FILLED)
   {
      double levels[3];int count=0;
      if(p.state==CHT_PENDING)
      {
         levels[count++]=p.requested-(p.buy?p.spread:0.);
         levels[count++]=p.rawStop-(p.buy?0.:p.spread);
         if(p.room && p.obstacle>0)levels[count++]=p.obstacle-(p.buy?0.:p.spread);
      }
      else
      {
         levels[count++]=p.stop-(p.buy?0.:p.spread);
         if(p.target>0)levels[count++]=p.target-(p.buy?0.:p.spread);
      }
      bool rising=x1>cursor,found=false;double level=0;
      for(int i=0;i<count;i++)
      {
         bool crossed=rising?(cursor+1e-10<levels[i] && levels[i]<=x1+1e-10):(x1-1e-10<=levels[i] && levels[i]<cursor-1e-10);
         if(crossed && (!found || (rising?levels[i]<level:levels[i]>level))){level=levels[i];found=true;}
      }
      datetime eventTime=t1;
      if(found && MathAbs(x1-x0)>1e-12)eventTime=t0+(datetime)MathCeil((level-x0)/(x1-x0)*(double)(t1-t0)-1e-9);
      if(p.deadline>0 && cursorTime<p.deadline && p.deadline<eventTime)
      {
         datetime when=p.deadline;double price=x0+(x1-x0)*(double)(when-t0)/(double)(t1-t0);
         CHTQuote(p,when,price,price+p.spread,cancelAt>0 && when>=cancelAt);cursorTime=when;cursor=price;continue;
      }
      if(!found){CHTQuote(p,t1,x1,x1+p.spread,cancelAt>0 && t1>=cancelAt);break;}
      CHTQuote(p,eventTime,level,level+p.spread,cancelAt>0 && eventTime>=cancelAt);cursor=level;cursorTime=eventTime;
   }
}
void CHTPendingMinute(CHTPlan &p,const MqlRates &bar,const bool highFirst,const datetime cancelAt=0)
{
   if(p.state==CHT_PENDING)
   {
      double fill=p.requested-(p.buy?p.spread:0.),cancel=p.rawStop-(p.buy?0.:p.spread),obstacle=p.obstacle-(p.buy?0.:p.spread);
      double previewStop=p.rawStop;
      if(p.direction*(p.requested-previewStop)<2.)previewStop=CHTRound(p.requested-p.direction*2.,p.tick,(int)-p.direction);
      double risk=p.direction*(p.requested-previewStop);
      double target=CHTRound(p.requested+p.direction*1.5*risk,p.tick,(int)p.direction)-(p.buy?0.:p.spread);
      if(bar.low<=fill && fill<=bar.high && ((bar.low<=cancel && cancel<=bar.high) ||
         (p.room && bar.low<=obstacle && obstacle<=bar.high) || (bar.low<=target && target<=bar.high)))p.ambiguous++;
   }
   CHTQuote(p,bar.time,bar.open,bar.open+p.spread,cancelAt>0 && bar.time>=cancelAt);
   double points[4];points[0]=bar.open;points[1]=highFirst?bar.high:bar.low;points[2]=highFirst?bar.low:bar.high;points[3]=bar.close;
   int offsets[4]={0,20,40,59};
   for(int i=0;i<3;i++)
   {
      if(p.state!=CHT_PENDING && p.state!=CHT_FILLED)break;
      CHTPathSegment(p,bar.time+offsets[i],points[i],bar.time+offsets[i+1],points[i+1],cancelAt);
   }
}
#endif
