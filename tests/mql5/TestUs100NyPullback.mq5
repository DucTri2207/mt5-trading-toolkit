#property strict
#property tester_indicator "duc_tri_us100_ny_pullback_lab.ex5"
#include "../../Include/Us100NyPullback.mqh"
int checks=0,failures=0;string failed="";
void Check(const bool ok,const string name){checks++;if(!ok){failures++;failed+=name+"; ";Print("FAIL ",name);}}
void OnStart()
{
   string folder="us100_ny_fixture\\";
   MqlRates b[];int f=FileOpen(folder+"bars.csv",FILE_READ|FILE_CSV|FILE_ANSI,',');
   Check(f!=INVALID_HANDLE,"open synthetic bars");if(f==INVALID_HANDLE)return;
   while(!FileIsEnding(f))
   {
      string stamp=FileReadString(f);if(stamp=="")break;int n=ArraySize(b);ArrayResize(b,n+1);
      ZeroMemory(b[n]);b[n].time=(datetime)StringToInteger(stamp);b[n].open=FileReadNumber(f);b[n].high=FileReadNumber(f);
      b[n].low=FileReadNumber(f);b[n].close=FileReadNumber(f);b[n].tick_volume=100;b[n].spread=2000;
   }
   FileClose(f);Check(ArraySize(b)>400,"fixture loaded");
   double fast[],slow[],atr[];int warm[];UNYFeatures(b,fast,slow,atr,warm);
   f=FileOpen(folder+"core_native.csv",FILE_WRITE|FILE_CSV|FILE_ANSI,',');
   int signals=0;UNYSignal s;
   for(int i=0;i<ArraySize(b);i++)
   {
      bool found=UNYDetect(b,fast,slow,atr,warm,i,s);if(found)signals++;
      FileWrite(f,(long)b[i].time,DoubleToString(fast[i],12),DoubleToString(slow[i],12),DoubleToString(atr[i],12),warm[i],
                found?s.direction:0,found?(long)s.known_at:0,found?DoubleToString(s.extreme,9):"0");
   }
   FileClose(f);Check(signals==2,"two causal mirrored synthetic signals");
   Check(UNYInSession(UNYDate(2026,3,6,14)+35*60),"winter NY start");
   Check(UNYInSession(UNYDate(2026,3,9,13)+35*60),"summer NY start");
   Check(!UNYInSession(UNYDate(2026,3,9,15)),"11NY excluded");
   Check(UNYToUtc(UNYDate(2026,10,26,15)+35*60,2,UNY_DST_EU)==UNYDate(2026,10,26,13)+35*60,"EU US different DST week");
   Check(UNYToUtc(UNYDate(2026,10,26,16)+35*60,2,UNY_DST_US)==UNYDate(2026,10,26,13)+35*60,"FTMO US DST after EU switch");
   Check(UNYToUtc(UNYDate(2026,11,2,16)+35*60,2,UNY_DST_US)==UNYDate(2026,11,2,14)+35*60,"FTMO winter session");
   Check(UNYToUtc(UNYDate(2026,3,9,16)+35*60,2,UNY_DST_US)==UNYDate(2026,3,9,13)+35*60,"FTMO summer session");
   Check(MathAbs(UNYFloorLots(250,103,.1,.1,100)-2.4)<1e-9,"lot rounded down");
   Check(UNYFloorLots(1,103,.1,.1,100)==0,"reject below minimum lot");
   string symbol="UNY_US100_FIXTURE";
   if(!SymbolInfoInteger(symbol,SYMBOL_CUSTOM))Check(CustomSymbolCreate(symbol,"Us100NyFixtures"),"create custom symbol");
   CustomSymbolSetInteger(symbol,SYMBOL_DIGITS,3);CustomSymbolSetDouble(symbol,SYMBOL_POINT,.001);
   CustomSymbolSetDouble(symbol,SYMBOL_TRADE_TICK_SIZE,.001);CustomSymbolSetDouble(symbol,SYMBOL_TRADE_CONTRACT_SIZE,1.);
   CustomSymbolSetDouble(symbol,SYMBOL_VOLUME_MIN,.1);CustomSymbolSetDouble(symbol,SYMBOL_VOLUME_STEP,.1);
   CustomSymbolSetDouble(symbol,SYMBOL_VOLUME_MAX,100.);CustomSymbolSetInteger(symbol,SYMBOL_TRADE_CALC_MODE,SYMBOL_CALC_MODE_CFD);
   CustomSymbolSetString(symbol,SYMBOL_CURRENCY_PROFIT,"USD");CustomSymbolSetString(symbol,SYMBOL_CURRENCY_MARGIN,"USD");
   CustomRatesDelete(symbol,0,D'2030.01.01');
   Check(CustomRatesReplace(symbol,b[0].time,b[ArraySize(b)-1].time,b)==ArraySize(b),"install custom bars");
   Check(SymbolSelect(symbol,true),"select fixture symbol");long chart=ChartOpen(symbol,PERIOD_M1);
   int handle=iCustom(symbol,PERIOD_M1,"duc_tri_us100_ny_pullback_lab",true,0,UNY_DST_NONE,.25,2.,.5,0.,30,false,chart);
   Check(handle!=INVALID_HANDLE,"actual iCustom load");double values[];int copied=0;
   for(int k=0;k<40;k++){copied=CopyBuffer(handle,2,0,ArraySize(b),values);if(copied==ArraySize(b))break;Sleep(100);}
   Check(copied==ArraySize(b),"actual indicator calculated");
   f=FileOpen(folder+"expected_plans.csv",FILE_READ|FILE_CSV|FILE_ANSI,',');
   Check(f!=INVALID_HANDLE,"open Python plan oracle");
   if(f!=INVALID_HANDLE)
   {
      while(!FileIsEnding(f))
      {
         string stamp=FileReadString(f);if(stamp=="")break;datetime known=(datetime)StringToInteger(stamp);
         int direction=(int)FileReadNumber(f);double entry=FileReadNumber(f),stop=FileReadNumber(f),target=FileReadNumber(f);
         int shift=iBarShift(symbol,PERIOD_M1,known,true);double value[];
         Check(shift>=0,"arrow timestamp is next bar");
         Check(CopyBuffer(handle,2,shift,1,value)==1 && MathAbs(value[0]-entry)<1e-8,"entry parity");
         Check(CopyBuffer(handle,3,shift,1,value)==1 && MathAbs(value[0]-stop)<1e-8,"stop parity");
         Check(CopyBuffer(handle,4,shift,1,value)==1 && MathAbs(value[0]-target)<1e-8,"target parity");
         Check(CopyBuffer(handle,6,shift,1,value)==1 && value[0]==direction,"direction parity");
         Check(CopyBuffer(handle,7,shift,1,value)==1 && value[0]==(double)known,"known-at UTC parity");
      }
      FileClose(f);
   }
   int denied=iCustom(symbol,PERIOD_M1,"duc_tri_us100_ny_pullback_lab");bool blank=false;
   for(int k=0;k<30;k++)
   {
      if(CopyBuffer(denied,2,0,ArraySize(b),values)==ArraySize(b))
      {blank=true;for(int j=0;j<ArraySize(values);j++)if(values[j]!=EMPTY_VALUE)blank=false;if(blank)break;}
      Sleep(100);
   }
   Check(blank,"unconfirmed server clock blocks plans");IndicatorRelease(denied);
   double prior[];int previous=CopyBuffer(handle,2,0,ArraySize(b),prior);
   MqlRates extra[];ArrayResize(extra,1);extra[0]=b[ArraySize(b)-1];extra[0].time+=60;
   extra[0].close+=1;extra[0].high=MathMax(extra[0].high,extra[0].close);
   Check(CustomRatesUpdate(symbol,extra)==1,"append future fixture bar");
   bool stable=false;
   for(int k=0;k<30;k++)
   {
      if(CopyBuffer(handle,2,0,ArraySize(b)+1,values)==ArraySize(b)+1)
      {
         stable=previous==ArraySize(b);
         for(int j=0;j<ArraySize(b);j++)if(values[j]!=prior[j])stable=false;
         if(stable)break;
      }
      Sleep(100);
   }
   Check(stable,"closed entry buffers unchanged after future bar");
   Check(chart>0 && ChartIndicatorAdd(chart,0,handle),"attach actual indicator to fixture chart");
   ChartSetInteger(chart,CHART_MODE,CHART_CANDLES);ChartSetInteger(chart,CHART_SHOW_GRID,false);
   ChartSetInteger(chart,CHART_COLOR_BACKGROUND,C'10,16,25');ChartSetInteger(chart,CHART_COLOR_FOREGROUND,clrSilver);
   ChartSetInteger(chart,CHART_COLOR_CANDLE_BULL,clrTeal);ChartSetInteger(chart,CHART_COLOR_CANDLE_BEAR,clrSlateGray);
   ChartSetInteger(chart,CHART_COLOR_CHART_UP,clrTeal);ChartSetInteger(chart,CHART_COLOR_CHART_DOWN,clrSlateGray);
   ChartSetInteger(chart,CHART_SHOW_VOLUMES,false);ChartSetInteger(chart,CHART_SCALEFIX,true);
   ChartSetDouble(chart,CHART_FIXED_MIN,20830);ChartSetDouble(chart,CHART_FIXED_MAX,20980);
   ChartSetInteger(chart,CHART_AUTOSCROLL,false);ChartSetInteger(chart,CHART_SHIFT,true);ChartSetInteger(chart,CHART_SCALE,3);
   ChartNavigate(chart,CHART_END,0);ChartRedraw(chart);Sleep(1000);
   Check(ChartScreenShot(chart,folder+"INDICATOR_FIXTURE.png",1440,850,ALIGN_RIGHT),"render synthetic fixture");
   ChartClose(chart);IndicatorRelease(handle);
   f=FileOpen(folder+"result.json",FILE_WRITE|FILE_TXT|FILE_ANSI,0,CP_UTF8);
   FileWriteString(f,StringFormat("{\"checks\":%d,\"failures\":%d,\"failed\":\"%s\",\"raw_signals\":%d,\"kind\":\"synthetic fixture, not trading performance\"}",checks,failures,failed,signals));FileClose(f);
   Print("UNY_CHECKS ",checks," FAILURES ",failures);
}
