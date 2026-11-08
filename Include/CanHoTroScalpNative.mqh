// Native adapter for the lab COPY of the existing indicator. Its canvas is retained.
#ifndef CAN_HO_TRO_SCALP_NATIVE
#define CAN_HO_TRO_SCALP_NATIVE
#ifndef CHT_INPUTS_EARLY
input group "=== LAB 0.1: VIRTUAL PLANS / NO BROKER ORDERS ==="
input bool InpLabVirtualPlans=false; // Research gate not passed: observe by default
input CHTPolicy InpLabPolicy=CHT_TS;
input bool InpLabRoom=false;
input bool InpLabBody50=false;
input double InpLabSlippageTicks=0;
#endif

CHTPlan g_chtPlan;
CHTZone g_chtZones[];
long g_chtSeenZoneKeys[];
datetime g_chtSeenZoneTimes[];
string g_chtSeenIdeas[];
datetime g_chtWatermark=0,g_chtZoneClock=0;
long g_chtLastMsc=0;
double g_chtLastBid=0,g_chtLastAsk=0;
bool g_chtUnknown=false,g_chtLoaded=false,g_chtDataReady=false;
string g_chtConfig="",g_chtStatePath="",g_chtLogPath="";

string CHTNativeIdea(const CHTCandidate &c)
{
   return StringFormat("%I64d|%d|%d|%I64d|%d|%I64d",(long)c.v[3],(int)c.v[4],(int)c.v[5],(long)c.v[6],(int)c.v[2],(long)c.v[13]);
}
datetime CHTRememberZone(const CHTZone &zone,const datetime known)
{
   long key=(long)zone.baseTime*16+(zone.baseBars-1)*2+(int)zone.isFlip;
   int l=0,r=ArraySize(g_chtSeenZoneKeys);
   while(l<r){int m=(l+r)/2;if(g_chtSeenZoneKeys[m]<key)l=m+1;else r=m;}
   if(l<ArraySize(g_chtSeenZoneKeys) && g_chtSeenZoneKeys[l]==key)return g_chtSeenZoneTimes[l];
   int n=ArraySize(g_chtSeenZoneKeys);ArrayResize(g_chtSeenZoneKeys,n+1);ArrayResize(g_chtSeenZoneTimes,n+1);
   for(int i=n;i>l;i--){g_chtSeenZoneKeys[i]=g_chtSeenZoneKeys[i-1];g_chtSeenZoneTimes[i]=g_chtSeenZoneTimes[i-1];}
   g_chtSeenZoneKeys[l]=key;g_chtSeenZoneTimes[l]=known;return known;
}
bool CHTNativeZones(const datetime at)
{
   int shift=iBarShift(_Symbol,PERIOD_H1,at,false)+1;if(shift<1)return false;
   datetime clock=iTime(_Symbol,PERIOD_H1,shift);
   if(clock==g_chtZoneClock && ArraySize(g_chtZones)>0)return true;
   MqlRates full[];double atr[];ArraySetAsSeries(full,false);ArraySetAsSeries(atr,false);
   int n=CopyRates(_Symbol,PERIOD_H1,shift,4000,full);
   if(n<2000 || CopyBuffer(g_htfAtrHandle,0,shift,n,atr)!=n)return false;
   bool cold=ArraySize(g_chtSeenZoneKeys)==0;
   for(int hc=cold?39:n;hc<=n;hc++)
   {
      int count=MathMin(hc,2000),off=hc-count;MqlRates window[];double aa[];
      ArrayResize(window,count);ArrayResize(aa,count);ArrayCopy(window,full,0,off,count);ArrayCopy(aa,atr,0,off,count);
      CHTScanZones(window,aa,g_chtZones);
      for(int z=0;z<ArraySize(g_chtZones);z++)
      {
         datetime first=CHTRememberZone(g_chtZones[z],full[hc-1].time+3600);
         g_chtZones[z].availableAt=(datetime)MathMax((double)g_chtZones[z].availableAt,(double)first);
      }
   }
   ArrayResize(g_zones,ArraySize(g_chtZones));
   g_statCreated=0;g_statDemand=0;g_statSupply=0;g_statBroken=0;g_statFlipped=0;
   for(int z=0;z<ArraySize(g_chtZones);z++)
   {
      CHTZone a=g_chtZones[z];SZone b;
      b.id=a.id;b.type=a.type;b.isSupply=a.isSupply;b.timeStart=a.timeStart;b.timeEnd=a.timeEnd;
      b.distal=a.distal;b.proximal=a.proximal;b.testCount=a.testCount;b.isFresh=a.isFresh;
      b.isBroken=a.isBroken;b.isFlip=a.isFlip;b.score=a.score;b.departAtr=a.departAtr;b.baseBars=a.baseBars;
      b.hasHtfOverlap=a.hasHtfOverlap;b.ageBars=a.ageBars;g_zones[z]=b;
      if(a.isFlip)g_statFlipped++;else{g_statCreated++;if(a.isSupply)g_statSupply++;else g_statDemand++;if(a.isBroken)g_statBroken++;}
   }
   int dayShift=iBarShift(_Symbol,PERIOD_D1,at,false)+1;MqlRates day[];
   if(dayShift>=1 && CopyRates(_Symbol,PERIOD_D1,dayShift,1,day)==1)
   {g_previousDayHigh=day[0].high;g_previousDayLow=day[0].low;g_previousDayTime=day[0].time;}
   g_chtZoneClock=clock;DrawChartZones();DrawReferenceLevels();return true;
}
void CHTNativeSave()
{
   if(g_chtStatePath!="")CHTSaveState(g_chtStatePath,g_chtConfig,g_chtPlan,g_chtWatermark,
                                    g_chtLastMsc,g_chtLastBid,g_chtLastAsk,g_chtSeenIdeas);
}
void CHTNativeRecent(const string kind,const string reason,const datetime at,const string entry,const string stop,const string risk)
{
   string text="";
   if(kind=="CANDIDATE" && reason=="PASS")text="H1 sweep / M5 CONFIRMED";
   if(kind=="PLAN_START")text=reason=="0"?"VIRTUAL E:"+entry+" SL:"+stop+" R0:"+risk:"VIRTUAL SETUP REJECTED";
   if(kind=="PLAN_EVENT")
   {
      string label=reason=="10"?"SL PROPOSED":(reason=="11"?"SL UPDATED":(reason=="12"?"SL UPDATE REJECTED":
                   (reason=="2"||reason=="8"?"STOP":(reason=="3"?"TARGET":(reason=="4"?"TIME EXIT":"PLAN UPDATED")))));
      text="VIRTUAL "+label+" / SL "+stop;
   }
   if(text=="")return;
   SEventLog event;event.text=TimeToString(at,TIME_MINUTES)+" "+text;event.dotColor=C'56,189,248';event.barsAgo=0;
   int n=MathMin(ArraySize(g_events)+1,5);ArrayResize(g_events,n);
   for(int i=n-1;i>0;i--)g_events[i]=g_events[i-1];g_events[0]=event;
}
void CHTNativeReadRecent()
{
   int f=FileOpen(g_chtLogPath,FILE_READ|FILE_CSV|FILE_ANSI,',');if(f==INVALID_HANDLE)return;
   while(!FileIsEnding(f))
   {
      string stamp=FileReadString(f);if(stamp=="")break;
      string kind=FileReadString(f);FileReadString(f);FileReadString(f);string reason=FileReadString(f);FileReadString(f);
      string entry=FileReadString(f);FileReadString(f);string stop=FileReadString(f),risk=FileReadString(f);FileReadString(f);
      CHTNativeRecent(kind,reason,(datetime)StringToInteger(stamp),DoubleToString(StringToDouble(entry),_Digits),
                       DoubleToString(StringToDouble(stop),_Digits),DoubleToString(StringToDouble(risk),2));
   }
   FileClose(f);
}
void CHTNativeLog(const string kind,const datetime at,const CHTCandidate &c,const string reason)
{
   int f=FileOpen(g_chtLogPath,FILE_READ|FILE_WRITE|FILE_CSV|FILE_ANSI,',');if(f==INVALID_HANDLE)return;
   FileSeek(f,0,SEEK_END);
   FileWrite(f,(long)at,kind,(long)c.v[1],CHTNativeIdea(c),reason,(int)g_chtPlan.state,
             DoubleToString(g_chtPlan.entry,10),DoubleToString(g_chtPlan.initialStop,10),
             DoubleToString(g_chtPlan.stop,10),DoubleToString(g_chtPlan.risk,10),(long)g_chtPlan.eventSerial);
   FileClose(f);
   CHTNativeRecent(kind,reason,at,DoubleToString(g_chtPlan.entry,_Digits),DoubleToString(g_chtPlan.stop,_Digits),DoubleToString(g_chtPlan.risk,2));
}
void CHTNativeInit()
{
   g_chtConfig=StringFormat("%s|%s|%d|%d|%d|%d|%.2f",CHT_VERSION,_Symbol,(int)InpLabPolicy,
                           (int)InpLabRoom,(int)InpLabBody50,(int)InpLabVirtualPlans,InpLabSlippageTicks);
   string stem=StringFormat("CHT_v01_%s_%I64d_%d_%d_%d_%d_%.0f",_Symbol,ChartID(),(int)InpLabPolicy,
                            (int)InpLabRoom,(int)InpLabBody50,(int)InpLabVirtualPlans,InpLabSlippageTicks);
   g_prefix=stem+"_";g_cvName=stem+"_CV";
   g_chtStatePath=stem+".bin";g_chtLogPath=stem+"_events.csv";
   g_chtLoaded=CHTLoadState(g_chtStatePath,g_chtConfig,g_chtPlan,g_chtWatermark,g_chtLastMsc,
                          g_chtLastBid,g_chtLastAsk,g_chtSeenIdeas);
   if(!g_chtLoaded){ZeroMemory(g_chtPlan);g_chtWatermark=iTime(_Symbol,PERIOD_M5,1);}
   g_chtUnknown=g_chtLoaded && (g_chtPlan.state==CHT_FILLED || g_chtPlan.state==CHT_PENDING);
   if(g_chtLoaded)CHTNativeReadRecent();
}
void CHTNativeSync()
{
   bool alive=(g_chtPlan.state==CHT_PENDING || g_chtPlan.state==CHT_FILLED) && !g_chtUnknown;
   g_lastSignal.active=alive;
   if(!alive){RemoveTradePlanLines();return;}
   CHTPlan p=g_chtPlan;SConfirmSignal s;ZeroMemory(s);
   s.active=true;s.isBuy=p.buy;s.time=(datetime)p.candidate.v[0];s.entryMarket=p.candidate.v[21];s.entryLimit=p.candidate.v[22];
   s.entry=p.state==CHT_FILLED?p.entry:p.requested;
   double sl=p.state==CHT_FILLED?p.initialStop:p.rawStop;
   if(p.state==CHT_PENDING && p.direction*(s.entry-sl)<2.)sl=CHTRound(s.entry-p.direction*2.,p.tick,(int)-p.direction);
   s.initialSl=sl;s.sl=p.state==CHT_FILLED?p.stop:sl;
   double risk=p.direction*(s.entry-sl);
   s.tp1=p.state==CHT_FILLED?p.target:(p.policy==CHT_TS?0:CHTRound(s.entry+p.direction*(p.policy==CHT_T05?.5:1.5)*risk,p.tick,(int)p.direction));
   s.tp2=s.tp1;s.tpMacro=p.obstacle;s.rr1=risk>0?MathAbs(s.tp1-s.entry)/risk:0;s.rr2=s.rr1;
   s.sweepPrice=p.candidate.v[14];s.zoneId=(int)p.candidate.v[7];s.zoneScore=(int)p.candidate.v[8];s.zoneType="H1 SWEEP";
   s.ltfAtr=p.candidate.v[18];s.maxMfePips=p.mfe*p.risk/GetPipSize();g_lastSignal=s;
   if(ShowTradeLines)DrawTradePlanLines(g_lastSignal);
}
string CHTNativeStatus()
{
   if(g_chtUnknown)return "UNKNOWN / NEEDS TICK REPLAY";
   if(!g_chtDataReady)return "DATA WARMING";
   if(!InpLabVirtualPlans)return "OBSERVE ONLY / RESEARCH";
   if(g_chtPlan.state==CHT_PENDING)return "PENDING / NOT FILLED";
   if(g_chtPlan.state==CHT_FILLED)return StringFormat("VIRTUAL / R0 %.2f / MFE %.2fR",g_chtPlan.risk,g_chtPlan.mfe);
   if(g_chtPlan.state==CHT_CLOSED)return StringFormat("CLOSED VIRTUAL %.2fR",g_chtPlan.resultR);
   if(g_chtPlan.state==CHT_REJECTED)return "REJECTED / FILL CONDITIONS";
   if(g_chtPlan.state==CHT_EXPIRED)return "PENDING EXPIRED / NO FILL";
   if(g_chtPlan.state==CHT_CANCELLED)return "PENDING CANCELLED / NO FILL";
   return "VIRTUAL / WAITING";
}
void CHTNativeBanner()
{
   string name=g_prefix+"LAB_STATUS";
   if(ObjectFind(0,name)<0)ObjectCreate(0,name,OBJ_LABEL,0,0,0);
   ObjectSetInteger(0,name,OBJPROP_CORNER,CORNER_RIGHT_UPPER);ObjectSetInteger(0,name,OBJPROP_ANCHOR,ANCHOR_RIGHT_UPPER);
   ObjectSetInteger(0,name,OBJPROP_XDISTANCE,16);ObjectSetInteger(0,name,OBJPROP_YDISTANCE,24);
   ObjectSetInteger(0,name,OBJPROP_FONTSIZE,10);ObjectSetInteger(0,name,OBJPROP_COLOR,clrOrange);
   ObjectSetString(0,name,OBJPROP_TEXT,"SCALP LAB 0.1 | "+CHTNativeStatus()+" | INDICATOR ONLY");
}
bool CHTNativeRaw(const datetime at,CHTCandidate &out[],MqlRates &ltf[],double &atr)
{
   int shift=iBarShift(_Symbol,PERIOD_M5,at,false);if(shift<0)return false;
   ArraySetAsSeries(ltf,true);int copied=CopyRates(_Symbol,PERIOD_M5,shift,300,ltf);
   double a[1];if(copied<30 || CopyBuffer(g_ltfAtrHandle,0,shift+1,1,a)!=1)return false;
   atr=a[0];datetime cOpen=ltf[1].time;int trend=iBarShift(_Symbol,PERIOD_H1,cOpen,false)+1;
   double ema[1],ha[1];MqlRates h[1];
   if(trend<1 || CopyBuffer(g_htfMaHandle,0,trend,1,ema)!=1 || CopyBuffer(g_htfAtrHandle,0,trend,1,ha)!=1 ||
      CopyRates(_Symbol,PERIOD_H1,trend,1,h)!=1)return false;
   CHTContext ctx;ZeroMemory(ctx);ctx.trendTime=h[0].time;ctx.trendClose=h[0].close;ctx.trendMa=ema[0];ctx.trendAtr=ha[0];
   ctx.dayHigh=g_previousDayHigh;ctx.dayLow=g_previousDayLow;ctx.dayTime=g_previousDayTime;
   ctx.m5Index=iBars(_Symbol,PERIOD_M5)-shift-2;ctx.h1Count=iBars(_Symbol,PERIOD_H1)-trend;
   CHTFindRaw(ltf,atr,g_chtZones,ctx,out,true);return true;
}
bool CHTNativeSeen(const string key)
{for(int i=0;i<ArraySize(g_chtSeenIdeas);i++)if(g_chtSeenIdeas[i]==key)return true;return false;}
void CHTNativeTick(const MqlTick &tick)
{
   datetime at=tick.time;long before=g_chtPlan.eventSerial;
   if(g_chtPlan.state==CHT_FILLED)CHTQuote(g_chtPlan,at,tick.bid,tick.ask);
   if(g_chtPlan.eventSerial!=before)CHTNativeLog("PLAN_EVENT",at,g_chtPlan.candidate,IntegerToString(g_chtPlan.eventKind));
   if(!CHTNativeZones(at))return;
   CHTCandidate raw[];MqlRates ltf[];double atr=0;
   bool ready=CHTNativeRaw(at,raw,ltf,atr);datetime closed=ready?ltf[1].time:0;
   g_chtDataReady=ready;
   bool newBar=ready && closed>g_chtWatermark;
   if(g_chtWatermark==0 && ready){g_chtWatermark=closed;newBar=false;}
   if(newBar && g_chtPlan.state==CHT_FILLED && g_chtPlan.policy==CHT_TS)
   {
      MqlRates chronological[];int n=ArraySize(ltf)-1;ArrayResize(chronological,n);
      for(int i=0;i<n;i++)chronological[i]=ltf[n-i];
      CHTPivot highs[],lows[];CHTBuildPivots(chronological,highs,lows);
      double aa[];ArrayResize(aa,n);ArrayInitialize(aa,0.);aa[n-1]=atr;
      before=g_chtPlan.eventSerial;CHTStructure(g_chtPlan,at,n-1,chronological,aa,highs,lows);
      if(g_chtPlan.eventSerial!=before)CHTNativeLog("PLAN_EVENT",at,g_chtPlan.candidate,IntegerToString(g_chtPlan.eventKind));
   }
   if(g_chtPlan.state==CHT_PENDING)
   {
      int shift=iBarShift(_Symbol,PERIOD_H1,at,false)+1;MqlRates h[1];bool cancel=false;
      if(shift>=1 && CopyRates(_Symbol,PERIOD_H1,shift,1,h)==1 && h[0].time+3600>(datetime)g_chtPlan.candidate.v[1])
         cancel=g_chtPlan.buy?h[0].close<g_chtPlan.candidate.v[10]:h[0].close>g_chtPlan.candidate.v[10];
      before=g_chtPlan.eventSerial;CHTQuote(g_chtPlan,at,tick.bid,tick.ask,cancel);
      if(g_chtPlan.eventSerial!=before)CHTNativeLog("PLAN_EVENT",at,g_chtPlan.candidate,IntegerToString(g_chtPlan.eventKind));
   }
   if(newBar)
   {
      g_confirmState=STATE_IDLE;
      bool selected=false;
      for(int i=0;i<ArraySize(raw);i++)
      {
         int gate=CHTPlannedGate(raw[i],SymbolInfoDouble(_Symbol,SYMBOL_TRADE_TICK_SIZE),InpLabBody50,InpLabRoom);
         if(gate==CHT_NONE && tick.ask-tick.bid>MaxSpreadPrice+1e-9)gate=CHT_SPREAD;
         string reason=gate==CHT_NONE?(selected?"LOWER_PRIORITY":"PASS"):IntegerToString(gate);
         CHTNativeLog("CANDIDATE",at,raw[i],reason);
         if(gate!=CHT_NONE || selected)continue;selected=true;
         g_confirmState=STATE_CONFIRMED;
         if(ShowArrows && at-(datetime)raw[i].v[1]<=60)
            DrawSignalArrow((bool)raw[i].v[2],(datetime)raw[i].v[0],(bool)raw[i].v[2]?ltf[1].low:ltf[1].high,atr);
         if(!InpLabVirtualPlans || g_chtUnknown || g_chtPlan.state==CHT_PENDING || g_chtPlan.state==CHT_FILLED)continue;
         string key=CHTNativeIdea(raw[i]);if(CHTNativeSeen(key))continue;
         int n=ArraySize(g_chtSeenIdeas);ArrayResize(g_chtSeenIdeas,n+1);g_chtSeenIdeas[n]=key;
         CHTStart(g_chtPlan,raw[i],InpLabPolicy,tick.ask-tick.bid,
                  InpLabSlippageTicks*SymbolInfoDouble(_Symbol,SYMBOL_TRADE_TICK_SIZE),
                  SymbolInfoDouble(_Symbol,SYMBOL_TRADE_TICK_SIZE),InpLabRoom,InpLabBody50,at,tick.bid,tick.ask);
         CHTNativeLog("PLAN_START",at,raw[i],IntegerToString(g_chtPlan.reason));
         if(g_chtPlan.state==CHT_FILLED || g_chtPlan.state==CHT_PENDING)CHTQuote(g_chtPlan,at,tick.bid,tick.ask);
      }
      g_chtWatermark=closed;
   }
   g_chtLastMsc=tick.time_msc;g_chtLastBid=tick.bid;g_chtLastAsk=tick.ask;
   if(newBar || g_chtPlan.eventSerial!=before)CHTNativeSave();
}
void CHTNativeCalculate()
{
   MqlTick tick;if(!SymbolInfoTick(_Symbol,tick) || tick.bid<=0 || tick.ask<tick.bid)return;
   if(g_chtUnknown)
   {
      // Restore only with an unambiguous saved tick anchor and current endpoint.
      // If unavailable, retain UNKNOWN rather than inventing SL/TP history.
      MqlTick recovered[];int n=CopyTicksRange(_Symbol,recovered,COPY_TICKS_ALL,(ulong)g_chtLastMsc,(ulong)tick.time_msc);
      int anchors=0,anchor=-1;
      for(int i=0;i<n;i++)if(recovered[i].time_msc==g_chtLastMsc)
      {anchors++;if(recovered[i].bid==g_chtLastBid && recovered[i].ask==g_chtLastAsk)anchor=i;}
      if(n>0 && anchors==1 && anchor>=0 && recovered[n-1].time_msc==tick.time_msc)
      {
         g_chtUnknown=false;
         for(int i=anchor+1;i<n;i++)CHTNativeTick(recovered[i]);
      }
   }
   else if(g_chtLastMsc!=tick.time_msc || g_chtLastBid!=tick.bid || g_chtLastAsk!=tick.ask)CHTNativeTick(tick);
   CHTNativeSync();if(g_lastSignal.active)g_confirmState=STATE_CONFIRMED;
   if(ShowDash)RenderDashboard(tick.bid);CHTNativeBanner();ChartRedraw(0);
}
#endif
