#ifndef CHT_V4_EXECUTION
#define CHT_V4_EXECUTION
struct SV4VirtualTrade
{
   string id,source,reason;
   long zone;
   bool buy,filled,closed,ambiguous;
   datetime known,published,fill,exit;
   long tickCursor;
   int tickSame;
   double entry,initialSl,stop,risk,mfe,exitPrice,grossR,netR,costR,commissionR,spread;
};
bool V4VirtualFill(SV4VirtualTrade &v,datetime when,double bid,double ask,double slip,
                   double commission,const SV4SymbolSpec &spec)
{
   if(v.filled || v.closed || when<v.known || bid<=0 || ask<bid || slip<0 || commission<0 || spec.point<=0) return false;
   double entry=v.buy?ask+slip:bid-slip;
   double risk=v.buy?entry-v.initialSl:v.initialSl-entry;
   if(risk<=0) {v.closed=true;v.reason="INVALID_STOP";return false;}
   double riskMoney=V4RiskMoney(v.buy,entry,v.initialSl,1,spec);
   double cost=V4CostR(v.buy,entry,v.initialSl,ask-bid,slip/spec.point,commission,spec);
   if(riskMoney<=0 || cost==EMPTY_VALUE){v.closed=true;v.reason="RISK_CALC_UNAVAILABLE";return false;}
   v.entry=entry;v.risk=risk;v.stop=v.initialSl;v.spread=ask-bid;v.fill=when;v.filled=true;
   v.commissionR=commission/riskMoney;v.costR=cost;
   return true;
}
void V4VirtualClose(SV4VirtualTrade &v,datetime when,double quote,double slip,string reason)
{
   if(!v.filled || v.closed || when<v.fill) return;
   v.exitPrice=quote+(v.buy?-slip:slip); v.exit=when; v.closed=true; v.reason=reason;
   v.netR=(v.buy?1:-1)*(v.exitPrice-v.entry)/v.risk-v.commissionR;
   // Gross excludes costs; net uses executable fills plus commission only.
   v.grossR=v.netR+v.costR;
}
void V4VirtualBar(SV4VirtualTrade &v,const MqlRates &b,double spread,double slip,ENUM_V4_EXIT rule,
                  int timeoutMinutes=240,bool legacy=false)
{
   if(!v.filled || v.closed || b.time<v.fill) return;
   datetime deadline=v.known+timeoutMinutes*60;
   if(!legacy && b.time>=deadline)
   { V4VirtualClose(v,b.time,v.buy?b.open:b.open+spread,slip,"TIMEOUT_GAP"); return; }
   double hi=b.high+(v.buy?0:spread),lo=b.low+(v.buy?0:spread);
   double target=v.entry+(v.buy?1:-1)*v.risk;
   bool stopHit=v.buy?lo<=v.stop:hi>=v.stop;
   bool targetHit=v.buy?hi>=target:lo<=target;
   if(stopHit)
   {
      v.ambiguous=targetHit;
      double opening=v.buy?b.open:b.open+spread;
      V4VirtualClose(v,b.time,legacy?v.stop:(v.buy?MathMin(opening,v.stop):MathMax(opening,v.stop)),slip,"SL"); return;
   }
   if(rule==EXIT_1R && targetHit)
   { V4VirtualClose(v,b.time,target,slip,"TP_1R"); return; }
   v.mfe=MathMax(v.mfe,v.buy?hi-v.entry:v.entry-lo);
   if(rule==EXIT_TRAIL_1R && v.mfe>=v.risk)
   {
      double next=v.entry+(v.buy?1:-1)*(v.mfe-v.risk);
      v.stop=v.buy?MathMax(v.stop,next):MathMin(v.stop,next);
   }
   if(!legacy && b.time+60>=deadline)
      V4VirtualClose(v,b.time+60,v.buy?b.close:b.close+spread,slip,"TIMEOUT");
}
void V4VirtualTick(SV4VirtualTrade &v,const MqlTick &tick,double slip,ENUM_V4_EXIT rule,int timeoutMinutes=240)
{
   if(!v.filled || v.closed || tick.time<v.fill || tick.bid<=0 || tick.ask<tick.bid) return;
   double quote=v.buy?tick.bid:tick.ask;
   if(tick.time>=v.known+timeoutMinutes*60)
   { V4VirtualClose(v,tick.time,quote,slip,"TIMEOUT"); return; }
   if(v.buy?quote<=v.stop:quote>=v.stop)
   { V4VirtualClose(v,tick.time,quote,slip,"SL"); return; }
   if(rule==EXIT_1R && (v.buy?quote>=v.entry+v.risk:quote<=v.entry-v.risk))
   { V4VirtualClose(v,tick.time,quote,slip,"TP_1R"); return; }
   v.mfe=MathMax(v.mfe,(v.buy?1:-1)*(quote-v.entry));
   if(rule==EXIT_TRAIL_1R && v.mfe>=v.risk)
   {
      double next=v.entry+(v.buy?1:-1)*(v.mfe-v.risk);
      v.stop=v.buy?MathMax(v.stop,next):MathMin(v.stop,next);
   }
}
#endif
