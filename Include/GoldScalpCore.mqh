#ifndef GOLD_SCALP_CORE_MQH
#define GOLD_SCALP_CORE_MQH

// Pure price/state helpers. No orders, chart operations, terminal or broker I/O.
// Distances are price units (XAUUSD dollars), never an assumed broker pip size.
enum GSPlanStatus
{
   GS_EMPTY = 0, GS_PENDING, GS_ACTIVE, GS_TP1, GS_CLOSED,
   GS_EXPIRED, GS_INVALIDATED
};

enum GSCloseReason
{
   GS_CLOSE_NONE = 0, GS_CLOSE_STOP, GS_CLOSE_TP2,
   GS_CLOSE_EXPIRY, GS_CLOSE_INVALIDATION, GS_CLOSE_TIME
};

enum GSPlanEvent
{
   GS_EVENT_NONE = 0, GS_EVENT_FILL = 1, GS_EVENT_BE = 2,
   GS_EVENT_TP1 = 4, GS_EVENT_TP2 = 8, GS_EVENT_STOP = 16,
   GS_EVENT_EXPIRED = 32, GS_EVENT_INVALIDATED = 64
};

struct GSPlan
{
   long id;
   GSPlanStatus status;
   GSCloseReason closeReason;
   bool isBuy;
   datetime createdAt;
   datetime expiresAt;
   datetime filledAt;
   datetime lastUpdate;
   double entry;
   double stop;
   double initialStop;
   double tp1;
   double tp2;
   double invalidationTarget;
   double mfe;
   bool beActive;
   bool hitTp1;
   bool hitTp2;
};

// roundDirection: -1 = down, +1 = up, 0 = nearest tick.
double GSNormalize(const double price,const double tickSize,const int roundDirection=0)
{
   if(tickSize<=0.0 || !MathIsValidNumber(price)) return price;
   double units=price/tickSize;
   if(roundDirection<0) return MathFloor(units+1e-9)*tickSize;
   if(roundDirection>0) return MathCeil(units-1e-9)*tickSize;
   return MathRound(units)*tickSize;
}

double GSFavorableMove(const bool isBuy,const double entry,
                       const double bid,const double ask)
{
   return isBuy ? bid-entry : entry-ask;
}

bool GSShouldCountTouch(const bool wasInside,const bool nowInside)
{
   return !wasInside && nowInside;
}

// Stops can expand away from price to satisfy the minimum. A structural stop
// beyond the maximum is rejected, never pulled inside its structural anchor.
bool GSBuildStop(const bool isBuy,const double entry,const double swing,
                 const double buffer,const double minDistance,
                 const double maxDistance,const double tickSize,double &stopOut)
{
   stopOut=0.0;
   if(!MathIsValidNumber(entry) || !MathIsValidNumber(swing) ||
      !MathIsValidNumber(buffer) || !MathIsValidNumber(minDistance) ||
      !MathIsValidNumber(maxDistance) || !MathIsValidNumber(tickSize) ||
      entry<=0.0 || swing<=0.0 || buffer<0.0 || minDistance<=0.0 ||
      maxDistance<minDistance || tickSize<=0.0) return false;
   if((isBuy && swing>=entry) || (!isBuy && swing<=entry)) return false;
   double raw=isBuy ? MathMin(swing-buffer,entry-minDistance)
                    : MathMax(swing+buffer,entry+minDistance);
   double candidate=GSNormalize(raw,tickSize,isBuy ? -1 : 1);
   double risk=isBuy ? entry-candidate : candidate-entry;
   if(candidate<=0.0 || risk<=0.0 || risk>maxDistance+tickSize*1e-7)
      return false;
   stopOut=candidate;
   return true;
}

// costPrice is additional round-trip friction relative to entry: spread,
// slippage/commission converted to price. Do not count costs already embedded
// in executable entry twice. Stress risk by +cost and reduce reward by cost.
double GSNetRR(const bool isBuy,const double entry,const double stop,
               const double target,const double costPrice)
{
   if(!MathIsValidNumber(entry) || !MathIsValidNumber(stop) ||
      !MathIsValidNumber(target) || !MathIsValidNumber(costPrice) ||
      entry<=0.0 || stop<=0.0 || target<=0.0 || costPrice<0.0) return -1.0;
   double risk=isBuy ? entry-stop : stop-entry;
   double reward=isBuy ? target-entry : entry-target;
   if(risk<=0.0 || reward<=costPrice) return -1.0;
   return (reward-costPrice)/(risk+costPrice);
}

// opposingLevel=0 means no known obstacle; otherwise both targets must remain
// in front of the nearest opposing level, including the requested clearance.
bool GSValidateTargets(const bool isBuy,const double entry,const double stop,
                       const double tp1,const double tp2,const double costPrice,
                       const double minRR,const double opposingLevel,
                       const double clearance,double &rr1,double &rr2)
{
   rr1=GSNetRR(isBuy,entry,stop,tp1,costPrice);
   rr2=GSNetRR(isBuy,entry,stop,tp2,costPrice);
   if(!MathIsValidNumber(minRR) || !MathIsValidNumber(opposingLevel) ||
      !MathIsValidNumber(clearance) || minRR<=0.0 || clearance<0.0 ||
      rr1+1e-9<minRR || rr2<=rr1) return false;
   if((isBuy && tp2<=tp1) || (!isBuy && tp2>=tp1)) return false;
   if(opposingLevel>0.0)
   {
      if(isBuy && (opposingLevel<=entry || tp2>opposingLevel-clearance+1e-9))
         return false;
      if(!isBuy && (opposingLevel>=entry || tp2<opposingLevel+clearance-1e-9))
         return false;
   }
   return true;
}

bool GSIsOpen(const GSPlan &plan)
{
   return plan.status==GS_PENDING || plan.status==GS_ACTIVE || plan.status==GS_TP1;
}

void GSResetPlan(GSPlan &plan)
{
   plan.id=0;
   plan.status=GS_EMPTY;
   plan.closeReason=GS_CLOSE_NONE;
   plan.isBuy=false;
   plan.createdAt=0; plan.expiresAt=0; plan.filledAt=0; plan.lastUpdate=0;
   plan.entry=0.0; plan.stop=0.0; plan.initialStop=0.0;
   plan.tp1=0.0; plan.tp2=0.0; plan.invalidationTarget=0.0;
   plan.mfe=0.0; plan.beActive=false; plan.hitTp1=false; plan.hitTp2=false;
}

// A stable signal identity cannot restart the same plan, even after it closes.
// A new signal also cannot overwrite a still-open pending/active plan.
bool GSStartPlan(GSPlan &plan,const long id,const bool isBuy,const bool isLimit,
                 const datetime now,const datetime expiresAt,const double entry,
                 const double stop,const double tp1,const double tp2,
                 const double invalidationTarget=0.0)
{
   if((plan.status!=GS_EMPTY && plan.id==id) || GSIsOpen(plan)) return false;
   double rr1=0.0,rr2=0.0;
   if(!GSValidateTargets(isBuy,entry,stop,tp1,tp2,0.0,1e-9,0.0,0.0,rr1,rr2))
      return false;
   if(now<0 || (isLimit && expiresAt<=now) ||
      !MathIsValidNumber(invalidationTarget) || invalidationTarget<0.0 ||
      (invalidationTarget>0.0 && (isBuy ? invalidationTarget<=entry : invalidationTarget>=entry)))
      return false;
   GSResetPlan(plan);
   plan.id=id; plan.isBuy=isBuy; plan.createdAt=now;
   plan.expiresAt=expiresAt; plan.lastUpdate=now;
   plan.status=isLimit ? GS_PENDING : GS_ACTIVE;
   plan.filledAt=isLimit ? 0 : now;
   plan.entry=entry; plan.stop=stop; plan.initialStop=stop;
   plan.tp1=tp1; plan.tp2=tp2; plan.invalidationTarget=invalidationTarget;
   return true;
}

// Process chronological quote observations only, never historical candle
// highs/lows preceding entry. BUY fills on Ask and exits on Bid; SELL fills on
// Bid and exits on Ask. A fill returns immediately, so one observed quote cannot
// also earn a pre-entry excursion or retroactive TP/BE.
int GSAdvance(GSPlan &plan,const datetime now,const double bid,const double ask,
              const double beTriggerDistance,const double beOffset,
              const double tickSize,const bool enableBE=true,const bool beOnTp1=true)
{
   if(!GSIsOpen(plan) || now<plan.lastUpdate ||
      !MathIsValidNumber(bid) || !MathIsValidNumber(ask) ||
      bid<=0.0 || ask<bid || tickSize<=0.0) return GS_EVENT_NONE;
   plan.lastUpdate=now;
   double exitPrice=plan.isBuy ? bid : ask;
   bool stopped=plan.isBuy ? exitPrice<=plan.stop : exitPrice>=plan.stop;
   if(plan.status==GS_PENDING)
   {
      if(now>=plan.expiresAt)
      {
         plan.status=GS_EXPIRED; plan.closeReason=GS_CLOSE_EXPIRY;
         return GS_EVENT_EXPIRED;
      }
      bool targetGone=plan.invalidationTarget>0.0 &&
         (plan.isBuy ? exitPrice>=plan.invalidationTarget : exitPrice<=plan.invalidationTarget);
      if(stopped || targetGone)
      {
         plan.status=GS_INVALIDATED; plan.closeReason=GS_CLOSE_INVALIDATION;
         return GS_EVENT_INVALIDATED;
      }
      bool filled=plan.isBuy ? ask<=plan.entry : bid>=plan.entry;
      if(!filled) return GS_EVENT_NONE;
      plan.status=GS_ACTIVE; plan.filledAt=now;
      return GS_EVENT_FILL;
   }
   if(stopped)
   {
      plan.status=GS_CLOSED; plan.closeReason=GS_CLOSE_STOP;
      return GS_EVENT_STOP;
   }
   double favorable=GSFavorableMove(plan.isBuy,plan.entry,bid,ask);
   plan.mfe=MathMax(plan.mfe,MathMax(0.0,favorable));
   int events=GS_EVENT_NONE;
   bool atTp1=plan.isBuy ? exitPrice>=plan.tp1 : exitPrice<=plan.tp1;
   bool atTp2=plan.isBuy ? exitPrice>=plan.tp2 : exitPrice<=plan.tp2;
   if(!plan.hitTp1 && atTp1)
   {
      plan.hitTp1=true; plan.status=GS_TP1; events|=GS_EVENT_TP1;
   }
   if(atTp2)
   {
      plan.hitTp2=true; plan.status=GS_CLOSED; plan.closeReason=GS_CLOSE_TP2;
      return events|GS_EVENT_TP2;
   }
   bool trigger=enableBE && !plan.beActive && beOffset>=0.0 &&
      ((beTriggerDistance>0.0 && favorable>=beTriggerDistance) || (beOnTp1 && plan.hitTp1));
   if(trigger)
   {
      double candidate=GSNormalize(plan.isBuy ? plan.entry+beOffset : plan.entry-beOffset,
                                   tickSize,plan.isBuy ? -1 : 1);
      // Only tighten while remaining strictly behind the executable exit quote.
      if((plan.isBuy && candidate>plan.stop && candidate<bid) ||
         (!plan.isBuy && candidate<plan.stop && candidate>ask))
      {
         plan.stop=candidate; plan.beActive=true; events|=GS_EVENT_BE;
      }
   }
   return events;
}

#endif
