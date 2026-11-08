#property copyright "Duc Tri structure research lab"
#property version "1.000"
#property indicator_chart_window
#property indicator_plots 0
#include "Include/ScalpStructureSetup.mqh"
#include "Include/ScalpStructurePlan.mqh"

// Research-only adapter. There are no broker order operations in this package.
input bool InpPaperEnabled=false; // Disabled until the research gate passes
input bool InpWriteLog=true;
SSDetector fast,slow;
SSPlan plans[2];
MqlRates hourly[],daily[];
int hourIndex=0,dayIndex=0,logHandle=INVALID_HANDLE;
datetime lastBar=0;
long session=0;
string prefix="DucTriStructureLab_";
bool ready=false;

SSBar ToBar(const MqlRates &r)
{SSBar b;b.time=r.time;b.open=r.open;b.high=r.high;b.low=r.low;b.close=r.close;return b;}
void LogEvent(const string kind,const datetime at,const int policy=-1,const double price=0,const double r=0)
{
   if(logHandle==INVALID_HANDLE)return;
   string detail="";
   if(policy>=0 && policy<2)
   {
      SSPlan p=plans[policy];
      detail=StringFormat(",\"idea_id\":\"XAUUSD:P2:%s:%I64d:%I64d\",\"signal_time\":%I64d,\"entry_time\":%I64d,\"entry\":%.10f,\"initial_stop\":%.10f,\"current_stop\":%.10f,\"risk_0\":%.10f,\"room_r\":%.10f,\"result_code\":%d",p.isBuy?"BUY":"SELL",(long)p.anchorTime,(long)p.signalTime,(long)p.signalTime,(long)p.entryTime,p.entry,p.initialStop,p.stop,p.risk,p.roomR,(int)p.result);
   }
   FileWriteString(logHandle,StringFormat("{\"schema\":1,\"spec\":\"%s\",\"session\":%I64d,\"event\":\"%s\",\"time\":%I64d,\"policy\":%d,\"price\":%.10f,\"r\":%.10f%s}\r\n",SS_VERSION,session,kind,(long)at,policy,price,r,detail));
   FileFlush(logHandle);
}
bool Context()
{
   ArraySetAsSeries(hourly,false);ArraySetAsSeries(daily,false);
   datetime from=D'2021.09.25 00:00';
   int h=CopyRates(_Symbol,PERIOD_H1,from,TimeCurrent(),hourly);
   int d=CopyRates(_Symbol,PERIOD_D1,from,TimeCurrent(),daily);
   return h>30 && d>2;
}
void Quote(const MqlTick &tick)
{
   for(int j=0;j<2;j++)
   {
      bool active=plans[j].active;
      SSOnQuote(plans[j],tick.time,tick.bid,tick.ask);
      if(active && !plans[j].active)LogEvent("EXIT",tick.time,j,plans[j].exitPrice,plans[j].resultR);
   }
}
void Trail(const SSTrail &t,const MqlTick &tick)
{
   double old=plans[1].stop;
   SSApplyTrail(plans[1],t,tick.time,tick.bid,tick.ask,SymbolInfoDouble(_Symbol,SYMBOL_TRADE_TICK_SIZE));
   if(plans[1].stop!=old)LogEvent("TRAIL",tick.time,1,plans[1].stop);
}
void ProcessBar(const MqlRates &r,const bool bootstrap,const MqlTick &tick)
{
   datetime at=r.time+300;
   SSCandidate c,unused;SSTrail tb,ts,x,y;
   while(hourIndex<ArraySize(hourly) && hourly[hourIndex].time+3600<=at)
   {slow.Step(ToBar(hourly[hourIndex]),unused,x,y);hourIndex++;}
   while(dayIndex<ArraySize(daily) && daily[dayIndex].time+86400<=at)dayIndex++;
   fast.Step(ToBar(r),c,tb,ts);lastBar=r.time;
   if(bootstrap)return;
   // Catch-up history updates context but must not move an active stop late.
   bool fresh=tick.time>=at && tick.time-at<=60;
   if(fresh && InpPaperEnabled){Trail(tb,tick);Trail(ts,tick);}
   if(!c.valid)return;
   fast.AddLevels(c.isBuy,c.trigger,at,c.opposing);
   slow.AddLevels(c.isBuy,c.trigger,at,c.opposing);
   if(dayIndex>0)fast.Consider(c.isBuy ? daily[dayIndex-1].high : daily[dayIndex-1].low,c.isBuy,c.trigger,c.opposing);
   LogEvent(fresh ? "CANDIDATE" : "CATCHUP_NO_FILL",at,-1,c.trigger);
   if(!fresh || !InpPaperEnabled)return;
   double tickSize=SymbolInfoDouble(_Symbol,SYMBOL_TRADE_TICK_SIZE);
   for(int j=0;j<2;j++)
   {
      if(plans[j].active)continue;
      if(SSFillPlan(plans[j],c,tick.time,tick.bid,tick.ask,tickSize,(SSExitPolicy)j))
         LogEvent("PAPER_ENTRY",tick.time,j,plans[j].entry);
      else LogEvent("REJECT_PLAN",tick.time,j,c.trigger);
   }
}
void Line(const string name,const double price,const color col)
{
   string key=prefix+name;
   if(price<=0){ObjectDelete(0,key);return;}
   if(ObjectFind(0,key)<0)ObjectCreate(0,key,OBJ_HLINE,0,0,price);
   ObjectSetDouble(0,key,OBJPROP_PRICE,price);ObjectSetInteger(0,key,OBJPROP_COLOR,col);
   ObjectSetString(0,key,OBJPROP_TEXT,name);
}
void Display()
{
   string text="DUC TRI STRUCTURE LAB | "+SS_VERSION+"\nEXPERIMENTAL: P2 failed historical research gate\n";
   text+=(InpPaperEnabled ? "Paper session only (reset on reload)" : "Review mode; paper entries disabled");
   text+="\nM5 confirmed swings / H1 + prior D1 levels | last closed: "+TimeToString(lastBar,TIME_DATE|TIME_MINUTES);
   for(int j=0;j<2;j++)
   {
      string p=j==0 ? "E0" : "E1";
      if(plans[j].active)
         text+=StringFormat("\n%s %s entry %.2f | SL0 %.2f | SL %.2f | room %.2fR",p,plans[j].isBuy?"BUY":"SELL",plans[j].entry,plans[j].initialStop,plans[j].stop,plans[j].roomR);
      Line(p+"_entry",plans[j].active ? plans[j].entry : 0,clrDodgerBlue);
      Line(p+"_initial_SL",plans[j].active ? plans[j].initialStop : 0,clrOrange);
      Line(p+"_current_SL",plans[j].active ? plans[j].stop : 0,clrRed);
      Line(p+"_target",plans[j].active && j==0 ? plans[j].target : 0,clrLimeGreen);
   }
   if(!ready)text+="\nWaiting for complete closed-bar history";
   Comment(text);
}
int OnInit()
{
   if(_Symbol!="XAUUSD")return INIT_PARAMETERS_INCORRECT;
   fast.Reset(300);slow.Reset(3600);session=(long)TimeLocal();
   IndicatorSetString(INDICATOR_SHORTNAME,"DucTri Structure LAB "+SS_VERSION);
   if(InpWriteLog)
   {
      FolderCreate("DucTriLab",FILE_COMMON);
      string file=StringFormat("DucTriLab\\structure_%I64d_%I64d.jsonl",session,ChartID());
      logHandle=FileOpen(file,FILE_WRITE|FILE_TXT|FILE_ANSI|FILE_COMMON|FILE_SHARE_READ,0,CP_UTF8);
   }
   LogEvent("INIT_NEW_SESSION_NO_RESUME",TimeCurrent());
   return INIT_SUCCEEDED;
}
int OnCalculate(const int rates_total,const int prev_calculated,const datetime &time[],const double &open[],const double &high[],const double &low[],const double &close[],const long &tick_volume[],const long &volume[],const int &spread[])
{
   MqlTick tick;
   if(!SymbolInfoTick(_Symbol,tick) || tick.bid<=0 || tick.ask<tick.bid)return rates_total;
   Quote(tick);
   datetime currentOpen=iTime(_Symbol,PERIOD_M5,0);
   if(ready && currentOpen<=lastBar+300){Display();return rates_total;}
   MqlRates bars[];ArraySetAsSeries(bars,false);
   datetime from=lastBar>0 ? lastBar+300 : D'2021.09.25 00:00';
   int count=CopyRates(_Symbol,PERIOD_M5,from,TimeCurrent(),bars);
   if(count>0 && Context())
   {
      bool bootstrap=!ready;
      for(int i=0;i<count;i++)
         if(bars[i].time+300<=tick.time)ProcessBar(bars[i],bootstrap,tick);
      if(lastBar>0 && !ready){ready=true;LogEvent("READY_HISTORY_SUPPRESSED",tick.time);}
   }
   Display();return rates_total;
}
void OnDeinit(const int reason)
{
   LogEvent("END_SESSION",TimeCurrent());
   if(logHandle!=INVALID_HANDLE)FileClose(logHandle);
   ObjectsDeleteAll(0,prefix);Comment("");
}
