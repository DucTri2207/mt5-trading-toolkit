// Closed-bar context for an XAU CFD indicator. No order or account operations.
// A CFD tick-volume weighted typical price is a broker activity proxy, not
// exchange traded volume, volume delta, absorption or an institutional order flow.
#ifndef GOLD_SCALP_CONTEXT_MQH
#define GOLD_SCALP_CONTEXT_MQH

struct SGscContext
{
   datetime asOfBroker;
   datetime utcDayStart;
   datetime previousDayOpen;
   bool hasPreviousDay;
   double previousDayHigh;
   double previousDayLow;
   datetime asiaStartBroker;
   datetime asiaEndBroker;
   bool hasAsiaRange;
   bool asiaSessionCovered;
   double asiaHigh;
   double asiaLow;
   datetime vwapStartBroker;
   datetime vwapLastClosedBar;
   bool hasVwap;
   bool vwapSessionCovered;
   bool isTickVolumeProxy;
   double vwap;
   double vwapStdev;
   int vwapBars;
   long vwapTickVolume;
   bool hasEma;
   double ema;
   double emaSlope;
   double lastClosedPrice;
   int emaRegime; // +1 close above rising EMA; -1 below falling EMA; 0 mixed.
};

datetime GscDayStart(const datetime timestamp)
{
   MqlDateTime parts;
   TimeToStruct(timestamp,parts);
   parts.hour=0;
   parts.min=0;
   parts.sec=0;
   return StructToTime(parts);
}

// Daily bars follow this broker's D1 session, not a fabricated UTC daily candle.
// A bar is completed only after the next broker D1 open, or after its nominal
// 24-hour boundary when no newer bar exists yet (e.g. the weekend).
bool GscPreviousCompletedDayFromRates(const MqlRates &daily[],
                                      const datetime asOfBroker,
                                      double &high,double &low,datetime &dayOpen)
{
   high=0.0;
   low=0.0;
   dayOpen=0;
   if(!ArrayGetAsSeries(daily)) return false;
   int copied=ArraySize(daily);
   for(int i=0;i<copied;i++)
   {
      if(daily[i].time>=asOfBroker) continue;
      bool completed=(i>0 && daily[i-1].time<=asOfBroker);
      if(!completed) completed=(daily[i].time+86400<=asOfBroker);
      if(!completed || daily[i].high<=0.0 || daily[i].low<=0.0 ||
         daily[i].high<daily[i].low) continue;
      high=daily[i].high;
      low=daily[i].low;
      dayOpen=daily[i].time;
      return true;
   }
   return false;
}

bool GscPreviousCompletedDay(const string symbol,const datetime asOfBroker,
                             double &high,double &low,datetime &dayOpen)
{
   MqlRates daily[];
   ArraySetAsSeries(daily,true);
   if(CopyRates(symbol,PERIOD_D1,asOfBroker-21*86400,asOfBroker,daily)<1)
   { high=0.0; low=0.0; dayOpen=0; return false; }
   return GscPreviousCompletedDayFromRates(daily,asOfBroker,high,low,dayOpen);
}

// Pure helper: the array MUST have newest bar at index 0. The clock check also
// excludes a historical bar that was still forming at the requested timestamp.
bool GscClosedBar(const MqlRates &rates[],const int shift,
                  const datetime asOfBroker,const int barSeconds=300)
{
   if(!ArrayGetAsSeries(rates) || shift<0 || shift>=ArraySize(rates) ||
      barSeconds<=0) return false;
   return rates[shift].time>0 && rates[shift].time+barSeconds<=asOfBroker;
}

// Pure daily/session statistics. Bars must fit entirely in [start,end], and be
// closed at asOf. Exact endpoint coverage + no missing M5 interval is reported
// separately so a partially downloaded session is never advertised as complete.
bool GscSessionStats(const MqlRates &rates[],const datetime startBroker,
                     const datetime endBroker,const datetime asOfBroker,
                     double &high,double &low,double &vwap,double &stdev,
                     int &barCount,long &tickVolume,bool &covered,
                     datetime &lastClosedBar)
{
   high=0.0; low=0.0; vwap=0.0; stdev=0.0;
   barCount=0; tickVolume=0; covered=false; lastClosedBar=0;
   if(!ArrayGetAsSeries(rates) || endBroker<=startBroker) return false;
   double weightedMean=0.0,weightedM2=0.0,totalWeight=0.0;
   datetime firstBar=0,previousBar=0;
   bool continuous=true;
   int count=ArraySize(rates);
   // Oldest to newest for deterministic weighted online variance.
   for(int i=count-1;i>=0;i--)
   {
      if(rates[i].time<startBroker || rates[i].time+300>endBroker ||
         !GscClosedBar(rates,i,asOfBroker)) continue;
      if(rates[i].high<=0.0 || rates[i].low<=0.0 ||
         rates[i].high<rates[i].low || rates[i].close<=0.0 ||
         rates[i].close>rates[i].high || rates[i].close<rates[i].low) continue;
      if(firstBar==0) { firstBar=rates[i].time; high=rates[i].high; low=rates[i].low; }
      if(previousBar!=0 && rates[i].time-previousBar!=300) continuous=false;
      previousBar=rates[i].time;
      lastClosedBar=rates[i].time;
      high=MathMax(high,rates[i].high);
      low=MathMin(low,rates[i].low);
      barCount++;
      // Zero tick-volume bars can contribute range, but never invented volume.
      if(rates[i].tick_volume<=0) continue;
      double weight=(double)rates[i].tick_volume;
      double typical=(rates[i].high+rates[i].low+rates[i].close)/3.0;
      double newWeight=totalWeight+weight;
      double delta=typical-weightedMean;
      weightedMean+=weight*delta/newWeight;
      weightedM2+=weight*delta*(typical-weightedMean);
      totalWeight=newWeight;
      tickVolume+=rates[i].tick_volume;
   }
   datetime effectiveEnd=(endBroker<asOfBroker ? endBroker : asOfBroker);
   // Do not require an incomplete M5 bar at the end of a live session.
   datetime expectedEnd=(datetime)((long)effectiveEnd/300*300);
   covered=barCount>0 && firstBar==startBroker &&
           lastClosedBar+300==expectedEnd && continuous;
   if(totalWeight>0.0)
   {
      vwap=weightedMean;
      stdev=MathSqrt(MathMax(0.0,weightedM2/totalWeight));
   }
   return barCount>0;
}

// Finite warm-up EMA seeded with the oldest closed close in the supplied array.
// >= 5 periods of warm-up are required. This avoids handle/current-bar ambiguity.
bool GscClosedEma(const MqlRates &rates[],const datetime asOfBroker,
                  const int period,const int slopeBars,double &ema,
                  double &slope,double &lastClose,int &regime)
{
   ema=0.0; slope=0.0; lastClose=0.0; regime=0;
   if(!ArrayGetAsSeries(rates) || period<2 || slopeBars<1) return false;
   double alpha=2.0/(period+1.0),state=0.0,past=0.0;
   int closedCount=0;
   // Locate the most recent closed bar independently of the live index 0.
   int latest=-1;
   for(int i=0;i<ArraySize(rates);i++)
      if(GscClosedBar(rates,i,asOfBroker)) { latest=i; break; }
   if(latest<0 || rates[latest].close<=0.0) return false;
   for(int i=ArraySize(rates)-1;i>=latest;i--)
   {
      if(!GscClosedBar(rates,i,asOfBroker) || rates[i].close<=0.0) continue;
      if(closedCount==0) state=rates[i].close;
      else state=alpha*rates[i].close+(1.0-alpha)*state;
      closedCount++;
      if(i==latest+slopeBars) past=state;
   }
   if(closedCount<period*5+slopeBars || past<=0.0) return false;
   ema=state;
   slope=state-past;
   lastClose=rates[latest].close;
   if(lastClose>ema && slope>0.0) regime=1;
   else if(lastClose<ema && slope<0.0) regime=-1;
   return true;
}

// asOfBroker is the decision time (normally confirmation-bar open + M5 seconds).
// Offset is BROKER minus UTC, in minutes; set explicitly for broker DST changes.
// The Asia range belongs to the current UTC date; it is unavailable before its
// end, never filled using future bars or yesterday's range without disclosure.
bool GscBuildContext(const string symbol,const datetime asOfBroker,
                      const int brokerUtcOffsetMinutes,const int utcSessionStartHour,
                      const int asiaStartUtcHour,const int asiaEndUtcHour,
                      const int emaPeriod,const int emaSlopeBars,SGscContext &context)
{
   ZeroMemory(context);
   context.asOfBroker=asOfBroker;
   context.isTickVolumeProxy=true;
   if(asOfBroker<=0 || utcSessionStartHour<0 || utcSessionStartHour>23 ||
      asiaStartUtcHour<0 || asiaStartUtcHour>23 || asiaEndUtcHour<=asiaStartUtcHour ||
      asiaEndUtcHour>24 || emaPeriod<2 || emaPeriod>500 ||
      emaSlopeBars<1 || emaSlopeBars>100 ||
      brokerUtcOffsetMinutes<-14*60 || brokerUtcOffsetMinutes>14*60) return false;
   int offsetSeconds=brokerUtcOffsetMinutes*60;
   datetime utcNow=asOfBroker-offsetSeconds;
   context.utcDayStart=GscDayStart(utcNow);
   context.asiaStartBroker=context.utcDayStart+asiaStartUtcHour*3600+offsetSeconds;
   context.asiaEndBroker=context.utcDayStart+asiaEndUtcHour*3600+offsetSeconds;
   context.vwapStartBroker=context.utcDayStart+utcSessionStartHour*3600+offsetSeconds;
   if(context.vwapStartBroker>asOfBroker) context.vwapStartBroker-=86400;
   context.hasPreviousDay=GscPreviousCompletedDay(symbol,asOfBroker,
                           context.previousDayHigh,context.previousDayLow,
                           context.previousDayOpen);
   datetime first=context.vwapStartBroker;
   if(context.asiaStartBroker<first) first=context.asiaStartBroker;
   // Add one calendar day to the EMA warm-up to tolerate ordinary session gaps.
   datetime emaFirst=asOfBroker-(emaPeriod*8+emaSlopeBars+10)*300-86400;
   if(emaFirst<first) first=emaFirst;
   MqlRates rates[];
   ArraySetAsSeries(rates,true);
   int copied=CopyRates(symbol,PERIOD_M5,first,asOfBroker,rates);
   if(copied<1) return context.hasPreviousDay;
   double unusedVwap=0.0,unusedStdev=0.0;
   int unusedBars=0;
   long unusedVolume=0;
   datetime unusedLast=0;
   if(asOfBroker>=context.asiaEndBroker)
   {
      bool hasRange=GscSessionStats(rates,context.asiaStartBroker,
                       context.asiaEndBroker,asOfBroker,context.asiaHigh,
                       context.asiaLow,unusedVwap,unusedStdev,unusedBars,
                       unusedVolume,context.asiaSessionCovered,unusedLast);
      context.hasAsiaRange=hasRange && context.asiaSessionCovered;
   }
   double unusedHigh=0.0,unusedLow=0.0;
   GscSessionStats(rates,context.vwapStartBroker,asOfBroker,asOfBroker,
                  unusedHigh,unusedLow,context.vwap,context.vwapStdev,
                  context.vwapBars,context.vwapTickVolume,
                  context.vwapSessionCovered,context.vwapLastClosedBar);
   context.hasVwap=context.vwapTickVolume>0 && context.vwapSessionCovered;
   context.hasEma=GscClosedEma(rates,asOfBroker,emaPeriod,emaSlopeBars,
                  context.ema,context.emaSlope,context.lastClosedPrice,context.emaRegime);
   return context.hasPreviousDay || context.hasAsiaRange || context.hasVwap || context.hasEma;
}

// Strict local pivot known BEFORE the sweep candle opened. A long wick alone
// is insufficient: price must exceed that prior pivot and close back inside it.
bool GscFindSweepReclaim(const MqlRates &rates[],const int sweepShift,
                         const bool isBuy,const int lookbackBars,
                         const int pivotStrength,const double minPenetration,
                         double &liquidityLevel,int &pivotShift)
{
   liquidityLevel=0.0; pivotShift=-1;
   int count=ArraySize(rates);
   if(!ArrayGetAsSeries(rates) || sweepShift<1 || sweepShift>=count ||
      lookbackBars<1 || pivotStrength<1 || minPenetration<0.0) return false;
   int first=sweepShift+pivotStrength+1;
   int last=(int)MathMin(count-pivotStrength-1,sweepShift+lookbackBars);
   for(int p=first;p<=last;p++)
   {
      bool pivot=true;
      double level=(isBuy ? rates[p].low : rates[p].high);
      for(int j=1;j<=pivotStrength;j++)
      {
         if(isBuy && (level>=rates[p-j].low || level>=rates[p+j].low)) { pivot=false; break; }
         if(!isBuy && (level<=rates[p-j].high || level<=rates[p+j].high)) { pivot=false; break; }
      }
      if(!pivot) continue;
      // Once taken by an intervening candle, this level is no longer an
      // untouched swing liquidity pool for a later candle to sweep again.
      for(int k=p-1;k>sweepShift;k--)
      {
         if((isBuy && rates[k].low<level) || (!isBuy && rates[k].high>level))
         { pivot=false; break; }
      }
      if(!pivot) continue;
      bool reclaim=isBuy ? rates[sweepShift].low<level-minPenetration && rates[sweepShift].close>level
                         : rates[sweepShift].high>level+minPenetration && rates[sweepShift].close<level;
      if(reclaim) { liquidityLevel=level; pivotShift=p; return true; }
   }
   return false;
}

bool GscHasDisplacement(const MqlRates &rates[],const int closedShift,
                        const double atr,const double minBodyAtr,
                        const double minBodyFraction,const bool isBuy)
{
   if(!ArrayGetAsSeries(rates) || closedShift<1 || closedShift>=ArraySize(rates) ||
      atr<=0.0 || minBodyAtr<0.0 || minBodyFraction<0.0 || minBodyFraction>1.0) return false;
   double body=rates[closedShift].close-rates[closedShift].open;
   if((isBuy && body<=0.0) || (!isBuy && body>=0.0)) return false;
   double range=rates[closedShift].high-rates[closedShift].low;
   if(range<=0.0) return false;
   return MathAbs(body)>=minBodyAtr*atr && MathAbs(body)/range>=minBodyFraction;
}

#endif // GOLD_SCALP_CONTEXT_MQH
