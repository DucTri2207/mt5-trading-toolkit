// Integration layer: indicator-only signal simulation; never places orders.
#ifndef GOLD_SCALP_ENGINE_MQH
#define GOLD_SCALP_ENGINE_MQH

double GSETickSize()
{
   double value=SymbolInfoDouble(_Symbol,SYMBOL_TRADE_TICK_SIZE);
   return value>0 ? value : _Point;
}

int GSEUtcOffset()
{
   if(!InpAutoBrokerUtcOffset || MQLInfoInteger(MQL_TESTER))
      return InpBrokerUtcOffsetMinutes;
   // Current live offset only. Historical replay needs the broker's DST table.
   return (int)MathRound((double)(TimeTradeServer()-TimeGMT())/900.0)*15;
}

void GSEEvent(const string text,const color clr)
{
   SEventLog ev;
   ev.text=text; ev.dotColor=clr; ev.barsAgo=0;
   int n=MathMin(5,ArraySize(g_events)+1);
   ArrayResize(g_events,n);
   for(int k=n-1;k>0;k--) g_events[k]=g_events[k-1];
   g_events[0]=ev;
}

bool GSEZoneUsable(const SZone &z)
{
   return !z.isBroken && z.testCount<MaxTests && z.ageBars<=MaxAgeBars &&
          (!z.isFlip || z.ageBars<=FlipLifeBars) && z.score>=MinScoreShow;
}

void GSEScanZones(const ENUM_TIMEFRAMES tf,const int atrHandle,
                  SZone &zones[],const bool allowFlip)
{
   ArrayResize(zones,0);
   MqlRates rates[]; double atrs[];
   ArraySetAsSeries(rates,false); ArraySetAsSeries(atrs,false);
   // Shift 1 on BOTH arrays: no forming HTF candle participates.
   int n=CopyRates(_Symbol,tf,1,MaxHistory,rates);
   if(n<LegInBars+BaseMaxBars+DepartBars+15 || atrHandle==INVALID_HANDLE)
      return;
   if(CopyBuffer(atrHandle,0,1,n,atrs)!=n) return;
   int end=n-DepartBars-1;
   for(int i=LegInBars+2;i<=end;i++)
   {
      double atr=atrs[i];
      if(atr<=0) continue;
      for(int len=1;len<=BaseMaxBars;len++)
      {
         int last=i+len-1;
         if(last+DepartBars>=n) break;
         double hi=-DBL_MAX,lo=DBL_MAX; bool valid=true;
         for(int b=i;b<=last;b++)
         {
            if(rates[b].high-rates[b].low>BaseBarATR*atr) {valid=false;break;}
            hi=MathMax(hi,rates[b].high); lo=MathMin(lo,rates[b].low);
         }
         if(!valid || hi-lo>BaseTotalATR*atr) continue;
         double depHi=-DBL_MAX,depLo=DBL_MAX;
         for(int d=last+1;d<=last+DepartBars;d++)
         {depHi=MathMax(depHi,rates[d].high);depLo=MathMin(depLo,rates[d].low);}
         bool supply=(lo-depLo>=DepartATR*atr);
         bool demand=(depHi-hi>=DepartATR*atr);
         // A violent two-sided departure is ambiguous, not a directional POI.
         if(supply==demand) continue;
         double strength=(supply ? lo-depLo : depHi-hi)/atr;
         int tests=0,brokenAt=-1; bool wasInside=false;
         for(int f=last+DepartBars+1;f<n;f++)
         {
            bool inside=rates[f].high>=lo && rates[f].low<=hi;
            if(GSShouldCountTouch(wasInside,inside)) tests++;
            wasInside=inside;
            if((supply && rates[f].close>hi) || (!supply && rates[f].close<lo))
            {brokenAt=f;break;}
            // Keep scanning after MaxTests to retain correct later break/flip.
         }
         double leg=rates[i].close-rates[MathMax(0,i-LegInBars)].close;
         SZone z;
         ZeroMemory(z);
         z.id=(int)(rates[i].time/60);
         z.type=supply ? (leg>0 ? ZONE_RBD : ZONE_DBD) : (leg<0 ? ZONE_DBR : ZONE_RBR);
         z.isSupply=supply; z.timeStart=rates[i].time;
         z.timeEnd=(brokenAt>=0 ? rates[brokenAt].time : rates[n-1].time);
         z.distal=supply ? hi : lo; z.proximal=supply ? lo : hi;
         z.testCount=tests; z.isFresh=(tests==0); z.isBroken=(brokenAt>=0);
         z.departAtr=strength; z.baseBars=len; z.ageBars=n-1-i;
         double score=MathMin(WDepart,strength/DepartATR*WDepart*0.7)+
                      WBase/(1.0+0.25*(len-1))+
                      (tests==0 ? WFresh : (tests==1 ? WFresh*0.5 : tests==2 ? WFresh*0.25 : 0))+
                      ((z.type==ZONE_DBR || z.type==ZONE_RBD) ? WReversal : WReversal*0.5);
         z.score=(int)MathRound(MathMin(100.0,score));
         if(z.ageBars<=MaxAgeBars)
         {int k=ArraySize(zones);ArrayResize(zones,k+1);zones[k]=z;}
         if(allowFlip && UseFlip && brokenAt>=0 && n-1-brokenAt<=FlipLifeBars)
         {
            SZone flip=z;
            flip.id=-z.id; flip.type=ZONE_FLIP; flip.isFlip=true;
            flip.isSupply=!supply; flip.timeStart=rates[brokenAt].time;
            flip.distal=z.proximal; flip.proximal=z.distal;
            flip.ageBars=n-1-brokenAt; flip.testCount=0; flip.isBroken=false;
            wasInside=true; // break candle is not a separate retest.
            for(int f=brokenAt+1;f<n;f++)
            {
               bool inside=rates[f].high>=lo && rates[f].low<=hi;
               if(GSShouldCountTouch(wasInside,inside)) flip.testCount++;
               wasInside=inside;
               if((flip.isSupply && rates[f].close>hi) || (!flip.isSupply && rates[f].close<lo))
               {flip.isBroken=true;break;}
            }
            flip.isFresh=(flip.testCount==0);
            flip.score=(int)MathRound(score*0.85);
            int k=ArraySize(zones);ArrayResize(zones,k+1);zones[k]=flip;
         }
         i+=len-1;
         break;
      }
   }
}

void ScanHtfMacroZones()
{
   ENUM_TIMEFRAMES tf=HtfPeriod==PERIOD_CURRENT ? Period() : HtfPeriod;
   GSEScanZones(tf,g_htfAtrHandle,g_zones,true);
   GSEScanZones(InpConfluencePeriod,g_confluenceAtrHandle,g_htfZones,false);
   g_statCreated=ArraySize(g_zones);g_statSupply=0;g_statDemand=0;
   g_statBroken=0;g_statFlipped=0;
   for(int i=0;i<ArraySize(g_zones);i++)
   {
      double lo=MathMin(g_zones[i].distal,g_zones[i].proximal);
      double hi=MathMax(g_zones[i].distal,g_zones[i].proximal);
      g_zones[i].hasHtfOverlap=false;
      for(int j=0;j<ArraySize(g_htfZones);j++)
      {
         if(!GSEZoneUsable(g_htfZones[j]) || g_htfZones[j].isSupply!=g_zones[i].isSupply) continue;
         double overlap=MathMin(hi,MathMax(g_htfZones[j].distal,g_htfZones[j].proximal))-
                        MathMax(lo,MathMin(g_htfZones[j].distal,g_htfZones[j].proximal));
         if(overlap>0 && overlap>=0.25*(hi-lo))
         {g_zones[i].hasHtfOverlap=true;break;}
      }
      if(g_zones[i].hasHtfOverlap) g_zones[i].score=(int)MathMin(100,g_zones[i].score+WMtf);
      if(g_zones[i].isSupply) g_statSupply++; else g_statDemand++;
      if(g_zones[i].isBroken) g_statBroken++;
      if(g_zones[i].isFlip) g_statFlipped++;
   }
   // Nearest zones first; quality breaks equal-distance ties.
   double price=SymbolInfoDouble(_Symbol,SYMBOL_BID);
   for(int i=0;i<ArraySize(g_zones)-1;i++)
      for(int j=i+1;j<ArraySize(g_zones);j++)
         if(GetZoneDistance(g_zones[j],price)<GetZoneDistance(g_zones[i],price) ||
            (GetZoneDistance(g_zones[j],price)==GetZoneDistance(g_zones[i],price) && g_zones[j].score>g_zones[i].score))
         {SZone tmp=g_zones[i];g_zones[i]=g_zones[j];g_zones[j]=tmp;}
}

bool GSENewsClear(const datetime now)
{
   if(!InpFilterUsdNews) return true;
   static datetime checked=0;
   static bool clear=false;
   static string reason="WAIT_NEWS_DATA";
   if(checked==0 || now-checked>=30 || now<checked)
   {
      checked=now;clear=false;reason="WAIT_NEWS_DATA";
      if(!MQLInfoInteger(MQL_TESTER))
      {
         MqlCalendarValue values[];
         ResetLastError();
         int n=CalendarValueHistory(values,now-InpNewsAfterMinutes*60,now+InpNewsBeforeMinutes*60,NULL,"USD");
         if(n>=0)
         {
            clear=true;reason="NEWS_CLEAR";
            for(int i=0;i<n;i++)
            {
               MqlCalendarEvent ev;
               if(!CalendarEventById(values[i].event_id,ev)) {clear=false;reason="WAIT_NEWS_DATA";break;}
               if(ev.importance==CALENDAR_IMPORTANCE_HIGH) {clear=false;reason="WAIT_USD_NEWS";break;}
            }
         }
      }
   }
   if(!clear) g_filterReason=reason;
   return clear;
}

bool GSESpreadClear(const MqlTick &quote)
{
   double spread=quote.ask-quote.bid;
   if(quote.bid<=0 || quote.ask<quote.bid || spread>InpMaxSpreadPrice)
   {g_filterReason="WAIT_SPREAD";return false;}
   if(g_spreadSamples>=20 && spread>2.0*g_spreadMean)
   {g_filterReason="WAIT_SPREAD_EXPANSION";return false;}
   return true;
}

void GSEDrawLevel(const string name,const double price,const color clr,const string text)
{
   string key=g_prefix+"CTX_"+name;
   if(price<=0) {ObjectDelete(0,key);return;}
   if(ObjectFind(0,key)<0) ObjectCreate(0,key,OBJ_HLINE,0,0,price);
   ObjectSetDouble(0,key,OBJPROP_PRICE,price);
   ObjectSetInteger(0,key,OBJPROP_COLOR,clr);
   ObjectSetInteger(0,key,OBJPROP_STYLE,STYLE_DOT);
   ObjectSetInteger(0,key,OBJPROP_BACK,true);
   ObjectSetString(0,key,OBJPROP_TOOLTIP,text);
}

void GSEDrawContext()
{
   if(!InpShowContextLevels) {ObjectsDeleteAll(0,g_prefix+"CTX_");return;}
   GSEDrawLevel("PDH",g_context.hasPreviousDay ? g_context.previousDayHigh : 0,C'148,163,184',"Previous completed broker D1 high");
   GSEDrawLevel("PDL",g_context.hasPreviousDay ? g_context.previousDayLow : 0,C'148,163,184',"Previous completed broker D1 low");
   GSEDrawLevel("ASIAH",g_context.hasAsiaRange ? g_context.asiaHigh : 0,C'192,132,252',"Completed Asia 00-07 UTC high");
   GSEDrawLevel("ASIAL",g_context.hasAsiaRange ? g_context.asiaLow : 0,C'192,132,252',"Completed Asia 00-07 UTC low");
   GSEDrawLevel("VWAP",g_context.hasVwap ? g_context.vwap : 0,C'251,191,36',"M5 typical price weighted by broker TICK volume; session proxy");
}

double GSENearestObstacle(const bool buy,const double entry)
{
   double nearest=0;
   for(int i=0;i<ArraySize(g_zones);i++)
   {
      if(!GSEZoneUsable(g_zones[i]) || g_zones[i].isSupply!=buy) continue;
      double level=g_zones[i].proximal;
      if((buy && level<=entry) || (!buy && level>=entry)) continue;
      if(nearest==0 || MathAbs(level-entry)<MathAbs(nearest-entry)) nearest=level;
   }
   double levels[4];
   levels[0]=g_context.hasPreviousDay ? g_context.previousDayHigh : 0;
   levels[1]=g_context.hasPreviousDay ? g_context.previousDayLow : 0;
   levels[2]=g_context.hasAsiaRange ? g_context.asiaHigh : 0;
   levels[3]=g_context.hasAsiaRange ? g_context.asiaLow : 0;
   for(int i=0;i<4;i++)
   {
      double level=levels[i];
      if(level<=0 || (buy ? level<=entry : level>=entry)) continue;
      if(nearest==0 || MathAbs(level-entry)<MathAbs(nearest-entry)) nearest=level;
   }
   return nearest;
}

bool GSERegimeClear(const bool buy,const double atr,const double closePrice)
{
   if(!InpUseRegimeFilter) return true;
   if(!g_context.hasEma || atr<=0) {g_filterReason="WAIT_REGIME_DATA";return false;}
   int trend=(MathAbs(g_context.emaSlope)>=InpTrendSlopeATR*atr ? g_context.emaRegime : 0);
   if((trend>0 && !buy) || (trend<0 && buy))
   {g_filterReason="WAIT_TREND_ALIGNMENT";return false;}
   // In a range, avoid taking a reversal toward its own nearby mean.
   if(trend==0 && InpUseVwapContext)
   {
      if(!g_context.hasVwap) {g_filterReason="WAIT_VWAP_DATA";return false;}
      if((buy && closePrice>=g_context.vwap) || (!buy && closePrice<=g_context.vwap))
      {g_filterReason="WAIT_RANGE_EDGE";return false;}
   }
   return true;
}

bool GSEAcceptPlan(const int z,const MqlRates &rates[],const int sweep,
                   const double atr,const MqlTick &quote)
{
   bool buy=!g_zones[z].isSupply;
   bool limit=(InpEntryMode==ENTRY_PULLBACK_50 || InpEntryMode==ENTRY_FVG_CE);
   double tick=GSETickSize(),spread=quote.ask-quote.bid;
   double market=GSNormalize(buy ? quote.ask : quote.bid,tick,buy ? 1 : -1);
   double midpoint=(rates[1].open+rates[1].close)*0.5;
   double limitPrice=midpoint;
   bool fvg=false;
   if(buy && rates[3].high<rates[1].low)
   {limitPrice=(rates[3].high+rates[1].low)*0.5;fvg=true;}
   if(!buy && rates[3].low>rates[1].high)
   {limitPrice=(rates[3].low+rates[1].high)*0.5;fvg=true;}
   if(InpEntryMode==ENTRY_PULLBACK_50) limitPrice=midpoint;
   if(InpEntryMode==ENTRY_FVG_CE && !fvg) {g_filterReason="WAIT_FVG";return false;}
   limitPrice=GSNormalize(limitPrice,tick,buy ? -1 : 1);
   double entry=limit ? limitPrice : market;
   if(limit && (buy ? entry>=quote.ask : entry<=quote.bid))
   {g_filterReason="WAIT_VALID_LIMIT";return false;}
   if(!limit && MathAbs(market-rates[1].close)>InpMaxChaseATR*atr+spread)
   {g_filterReason="WAIT_NO_CHASE";return false;}
   double swing=buy ? rates[sweep].low : rates[sweep].high;
   if(InpSlMode==SL_STRUCTURAL_SWING)
      for(int i=1;i<=sweep;i++) swing=buy ? MathMin(swing,rates[i].low) : MathMax(swing,rates[i].high);
   if(!buy) swing+=spread; // chart bars are Bid; short stop executes on Ask.
   double sl=0;
   double buffer=MathMax(SlBufferATR*atr,2*tick);
   if(!GSBuildStop(buy,entry,swing,buffer,MinSlPips*GetPipSize(),MaxSlPips*GetPipSize(),tick,sl))
   {g_filterReason="WAIT_STRUCTURAL_SL";return false;}
   double risk=MathAbs(entry-sl),cost=InpSlippagePrice+InpCommissionPrice;
   double sign=buy ? 1.0 : -1.0;
   // Executable market entry already embeds spread. Additional costs are explicit.
   double d1=InpTpMode==TP_MODE_RR ? InpTp1RR*(risk+cost)+cost : InpTp1Pips*GetPipSize();
   double d2=InpTpMode==TP_MODE_PIPS ? InpTp2Pips*GetPipSize() : InpTp2RR*(risk+cost)+cost;
   double obstacle=GSENearestObstacle(buy,entry);
   if(!buy && obstacle>0) obstacle+=spread;
   // Range fade's first opposing mean is another obstacle, not a free target.
   if(InpUseVwapContext && g_context.hasVwap && MathAbs(g_context.emaSlope)<InpTrendSlopeATR*atr)
   {
      double v=g_context.vwap+(!buy ? spread : 0);
      if((buy ? v>entry : v<entry) && (obstacle==0 || MathAbs(v-entry)<MathAbs(obstacle-entry))) obstacle=v;
   }
   double clearance=MathMax(InpTargetClearanceATR*atr,2*tick);
   if(obstacle>0) d2=MathMin(d2,MathAbs(obstacle-entry)-clearance);
   double tp1=GSNormalize(entry+sign*d1,tick,buy ? 1 : -1);
   double tp2=GSNormalize(entry+sign*d2,tick,buy ? -1 : 1);
   double rr1=0,rr2=0;
   double requiredRR=MathMax(MinRR,limit ? InpLimitMinRR : 0.0);
   if(!GSValidateTargets(buy,entry,sl,tp1,tp2,cost,requiredRR,obstacle,clearance,rr1,rr2))
   {g_filterReason="WAIT_NET_RR_OR_OBSTACLE";return false;}
   long identity=(long)rates[1].time*2+(buy ? 1 : 0);
   if(!GSStartPlan(g_plan,identity,buy,limit,quote.time,
                   quote.time+InpPendingExpiryBars*PeriodSeconds(LtfPeriod==PERIOD_CURRENT ? Period() : LtfPeriod),entry,sl,tp1,tp2,tp1))
      return false;
   ZeroMemory(g_lastSignal);
   g_lastSignal.active=true;g_lastSignal.isBuy=buy;g_lastSignal.time=rates[1].time;
   g_lastSignal.entry=entry;g_lastSignal.entryMarket=market;
   // Only selected limit is validated. No unvalidated second entry recommendation.
   g_lastSignal.entryLimit=limit ? entry : 0;
   g_lastSignal.sl=sl;g_lastSignal.initialSl=sl;g_lastSignal.tp1=tp1;g_lastSignal.tp2=tp2;
   g_lastSignal.tpMacro=obstacle;g_lastSignal.rr1=rr1;g_lastSignal.rr2=rr2;
   g_lastSignal.rrMacro=obstacle>0 ? GSNetRR(buy,entry,sl,obstacle,cost) : 0;
   g_lastSignal.sweepPrice=buy ? rates[sweep].low : rates[sweep].high;
   g_lastSignal.zoneId=g_zones[z].id;g_lastSignal.zoneScore=g_zones[z].score;
   g_lastSignal.zoneType=EnumToString(g_zones[z].type);
   StringReplace(g_lastSignal.zoneType,"ZONE_","");
   g_lastSignal.ltfAtr=atr;
   double beOffset=MathMax(InpBeOffsetPips*GetPipSize(),cost);
   g_lastSignal.bePrice=GSNormalize(entry+sign*beOffset,tick,buy ? -1 : 1);
   g_lastAlertBar=rates[1].time;
   g_filterReason=limit ? "PENDING_LIMIT_SIMULATION" : "ACTIVE_MARKET_SIMULATION";
   DrawSignalArrow(buy,rates[1].time,buy ? rates[1].low : rates[1].high,atr);
   if(ShowTradeLines) DrawTradePlanLines(g_lastSignal);
   if(AlertConfirm && g_zones[z].score>=AlertMinScore) SendSignalAlert(g_lastSignal);
   GSEEvent(StringFormat("%s %s E:%.*f net %.2fR",buy ? "BUY" : "SELL",limit ? "LIMIT WAIT" : "CONFIRM",_Digits,entry,rr1),buy ? C'52,211,153' : C'248,113,113');
   return true;
}

void DetectLtfConfirmation(bool isFirstRun=false)
{
   ENUM_TIMEFRAMES tf=LtfPeriod==PERIOD_CURRENT ? Period() : LtfPeriod;
   MqlRates rates[]; double atrs[];
   ArraySetAsSeries(rates,true);ArraySetAsSeries(atrs,true);
   int n=CopyRates(_Symbol,tf,0,MathMax(80,LtfBarsScan),rates);
   if(n<60 || CopyBuffer(g_ltfAtrHandle,0,0,n,atrs)!=n)
   {g_filterReason="WAIT_LTF_DATA";return;}
   datetime asOf=rates[0].time;
   GscBuildContext(_Symbol,asOf,GSEUtcOffset(),0,0,7,20,3,g_context);
   GSEDrawContext();
   if(GSIsOpen(g_plan)) {g_confirmState=STATE_CONFIRMED;return;}
   g_confirmState=STATE_IDLE;g_filterReason="WAIT_POI_SWEEP";
   // On attachment/reload wait for the NEXT closed bar; never revive stale plans.
   if(isFirstRun) {g_filterReason="WARMUP_WAIT_NEXT_CLOSE";return;}
   if(g_lastAlertBar==rates[1].time) return;
   MqlTick quote;
   if(!SymbolInfoTick(_Symbol,quote) || quote.time<asOf || quote.time-asOf>PeriodSeconds(tf))
   {g_filterReason="WAIT_FRESH_QUOTE";return;}
   if(!GSESpreadClear(quote) || !GSENewsClear(quote.time)) return;
   if(!IsInKillzone(asOf)) {g_filterReason="WAIT_SESSION_UTC";return;}
   double atr=atrs[1];
   if(atr<=0) {g_filterReason="WAIT_ATR";return;}
   for(int z=0;z<ArraySize(g_zones);z++)
   {
      if(!GSEZoneUsable(g_zones[z])) continue;
      bool buy=!g_zones[z].isSupply;
      double lo=MathMin(g_zones[z].distal,g_zones[z].proximal);
      double hi=MathMax(g_zones[z].distal,g_zones[z].proximal);
      for(int s=2;s<=MathMin(InpSweepMaxBars,n-InpSweepLookback-4);s++)
      {
         if(rates[s].time<g_zones[z].timeStart+PeriodSeconds(HtfPeriod==PERIOD_CURRENT ? Period() : HtfPeriod)*(g_zones[z].baseBars+DepartBars)) continue;
         if(rates[s].high<lo-0.1*atr || rates[s].low>hi+0.1*atr) continue;
         g_confirmState=STATE_IN_POI;
         double level=0;int pivot=-1;
         if(!GscFindSweepReclaim(rates,s,buy,InpSweepLookback,2,
                                 MathMax(2*GSETickSize(),InpSweepPenetrationATR*atrs[s]),level,pivot)) continue;
         double range=rates[s].high-rates[s].low;
         double wick=buy ? MathMin(rates[s].open,rates[s].close)-rates[s].low : rates[s].high-MathMax(rates[s].open,rates[s].close);
         if(range<=0 || wick/range<WickRatioMin) continue;
         g_confirmState=STATE_SWEEP;
         if(!GscHasDisplacement(rates,1,atr,InpDisplacementATR,InpDisplacementBodyFraction,buy))
         {g_filterReason="WAIT_DISPLACEMENT";continue;}
         // A confirmed pivot that was already known before the sweep.
         double trigger=buy ? -DBL_MAX : DBL_MAX;
         bool found=false;
         for(int p=s+3;p<=MathMin(n-3,s+10);p++)
         {
            bool isPivot=true;
            for(int k=1;k<=2;k++)
               if(buy ? (rates[p].high<=rates[p-k].high || rates[p].high<=rates[p+k].high) :
                        (rates[p].low>=rates[p-k].low || rates[p].low>=rates[p+k].low)) {isPivot=false;break;}
            if(isPivot) {trigger=buy ? rates[p].high : rates[p].low;found=true;break;}
         }
         if(!found) continue;
         bool crossed=buy ? rates[1].close>trigger : rates[1].close<trigger;
         for(int p=s-1;p>=2;p--)
            if(buy ? rates[p].close>trigger : rates[p].close<trigger) crossed=false;
         if(!crossed) {g_filterReason="WAIT_STRUCTURE_BREAK";continue;}
         // An intervening close through distal invalidates this reversal setup.
         bool invalid=false;
         for(int p=s-1;p>=1;p--)
            if(buy ? rates[p].close<lo : rates[p].close>hi) invalid=true;
         if(invalid) {g_filterReason="WAIT_POI_RECLAIM";continue;}
         if(!GSERegimeClear(buy,atr,rates[1].close)) continue;
         if(GSEAcceptPlan(z,rates,s,atr,quote)) {g_confirmState=STATE_CONFIRMED;return;}
      }
   }
}

void ManageActiveSignal(double curPrice)
{
   if(!GSIsOpen(g_plan)) return;
   MqlTick quote;
   if(!SymbolInfoTick(_Symbol,quote)) return;
   // Pending fills must pass the current spread/news gate too.
   if(g_plan.status==GS_PENDING && (!GSESpreadClear(quote) || !GSENewsClear(quote.time) || !IsInKillzone(quote.time)))
   {
      g_plan.status=GS_INVALIDATED;g_plan.closeReason=GS_CLOSE_INVALIDATION;
      GSEEvent("LIMIT cancelled: spread/news/session gate",C'248,113,113');
   }
   double trigger=InpBeTriggerPips>0 ? InpBeTriggerPips*GetPipSize() : DBL_MAX;
   if(InpBeTriggerATR>0) trigger=MathMin(trigger,InpBeTriggerATR*g_lastSignal.ltfAtr);
   double offset=MathMax(InpBeOffsetPips*GetPipSize(),InpSlippagePrice+InpCommissionPrice);
   int events=GSAdvance(g_plan,quote.time,quote.bid,quote.ask,trigger,offset,GSETickSize(),InpUseAutoBE,true);
   if((g_plan.status==GS_ACTIVE || g_plan.status==GS_TP1) &&
      quote.time-g_plan.filledAt>=InpMaxHoldBars*PeriodSeconds(LtfPeriod==PERIOD_CURRENT ? Period() : LtfPeriod))
   {
      g_plan.status=GS_CLOSED;g_plan.closeReason=GS_CLOSE_TIME;
      GSEEvent("TIME EXIT (simulation)",C'251,191,36');
   }
   g_lastSignal.active=GSIsOpen(g_plan);
   g_lastSignal.sl=g_plan.stop;g_lastSignal.isBeActive=g_plan.beActive;
   g_lastSignal.hitTp1=g_plan.hitTp1;g_lastSignal.hitTp2=g_plan.hitTp2;
   g_lastSignal.maxMfePips=g_plan.mfe/GetPipSize();
   if(events&GS_EVENT_FILL) GSEEvent("LIMIT FILLED (quote simulation)",C'52,211,153');
   if(events&GS_EVENT_TP1) GSEEvent("TP1 touched (simulation)",C'52,211,153');
   if(events&GS_EVENT_TP2) GSEEvent("TP2 touched (simulation)",C'52,211,153');
   if(events&GS_EVENT_STOP) GSEEvent("STOP touched (simulation)",C'248,113,113');
   if(events&GS_EVENT_EXPIRED) GSEEvent("LIMIT expired",C'148,163,184');
   if(events&GS_EVENT_INVALIDATED) GSEEvent("LIMIT invalidated before fill",C'248,113,113');
   if((events&GS_EVENT_BE) && AlertBeTriggered)
   {
      string message=StringFormat("[%s] BE suggestion %.*f. Indicator simulation; broker SL is unchanged.",_Symbol,_Digits,g_plan.stop);
      if(AlertPopup) Alert(message);
      if(AlertPush) SendNotification(message);
      if(AlertSoundOn) PlaySound(AlertSoundFile);
      if(TgEnable) SendBeTelegram(g_lastSignal,g_lastSignal.maxMfePips,g_plan.mfe);
      GSEEvent("BE suggestion (simulation)",C'56,189,248');
   }
   if(g_lastSignal.active && ShowTradeLines) DrawTradePlanLines(g_lastSignal);
   else
   {
      RemoveTradePlanLines();g_confirmState=STATE_IDLE;
      g_filterReason="PLAN_CLOSED_WAIT_NEXT_SIGNAL";
   }
}

#endif
