#property strict
#define CHT_V4_NATIVE_FIXTURE
#include <CanHoTroV4/Types.mqh>
#include "Market401.mqh"
#define _Symbol "XAUUSD_FIXTURE"
#include "Indicator401.mqh"
int checks=0,failures=0;
void Check(bool ok,string name){checks++;if(!ok){failures++;Print("FAIL ",name);}}
void OnStart()
{
   AlertConfirm=false;AlertPopup=false;AlertPush=false;AlertSoundOn=false;TgEnable=false;AlertBeTriggered=false;
   ShowTradeLines=false;ShowArrows=false;ShowDash=false;g_v4RenderSource=false;g_v4QuietPlan=true;
   g_v4Point=.01;g_atrHandle=102;g_htfAtrHandle=100;g_ltfAtrHandle=101;
   MqlRates m1[];double unused[];
   if(!ReadFixture("h1",fixtureH,fixtureHA)||!ReadFixture("m5",fixtureM,fixtureMA)||!ReadFixture("m1",m1,unused))return;
   fixtureVisibleM=ArraySize(fixtureM);fixtureVisibleH=ArraySize(fixtureH);fixtureHL=fixtureVisibleH-1;
   int f=FileOpen("v4_fixture\\scale_checks.csv",FILE_WRITE|FILE_CSV|FILE_ANSI,',');
   FileWrite(f,"at","D1_open","closed_close","factor","factor_after_future_mutation","pass");
   // Distinct deterministic observations, with visible future H1 altered after each closed D1 query.
   for(int j=1;j<=200;j++)
   {
      int m=30+(int)((long)(fixtureVisibleM-31)*j/201);datetime at=fixtureM[m].time;MqlRates day;double k;
      Check(V4PriceFactor(at,k) && FixturePriceD1(at,day),"closed_D1_available");
      Check(MathAbs(k-day.close/2000.0)<1e-12 && day.time<at,"D1_scale_formula");
      double old=fixtureH[fixtureVisibleH-1].close;fixtureH[fixtureVisibleH-1].close=999999;double later;
      Check(V4PriceFactor(at,later) && later==k,"future_D1_mutation_does_not_change_scale");fixtureH[fixtureVisibleH-1].close=old;
      FileWrite(f,(long)at,(long)day.time,day.close,k,later,k==later?"PASS":"FAIL");
   }
   FileClose(f);fixtureHL=-1;
   g_v4Preset=V4Preset();g_v4SignalsFile=FileOpen("v4_fixture\\hist_signals.csv",FILE_WRITE|FILE_READ|FILE_CSV|FILE_ANSI,',',CP_UTF8);Check(V4Header(g_v4SignalsFile),"header");
   ulong began=GetTickCount64();
   for(int m=30;m<fixtureVisibleM;m++)
   {
      fixtureM0=m;
      while(fixtureHL+1<fixtureVisibleH && fixtureH[fixtureHL+1].time+3600<=fixtureM[m].time)fixtureHL++;
      if(!V4ObserveClosedBar(fixtureM[m].time,fixtureM[m].time,true) && g_v4IoFailed){Check(false,"observation_io");break;}
   }
   FileClose(g_v4SignalsFile);g_v4SignalsFile=INVALID_HANDLE;
   SV4SymbolSpec spec;spec.tickSize=.01;spec.tickValue=1;spec.point=.01;spec.minLot=.01;spec.maxLot=100;spec.step=.01;
   f=FileOpen("v4_fixture\\hist_trades.csv",FILE_WRITE|FILE_CSV|FILE_ANSI,',',CP_UTF8);V4ScoreHeader(f);
   for(int i=0;i<ArraySize(g_v4History);i++)for(int rule=0;rule<2;rule++)
   {
      SV4VirtualTrade v;V4NewVirtual(g_v4History[i],"HIST",v);V4HistEvaluate(v,m1,spec,(ENUM_V4_EXIT)rule,InpHistSpreadPrice,InpSlippagePoints*.01,InpCommissionPerLot);v.id+="_"+(string)rule;
      V4ScoreWrite(f,v);if(v.filled)Check(v.fill>=v.known && (!v.closed || v.exit>=v.fill),"hist_time_order");
   }
   FileClose(f);f=FileOpen("v4_fixture\\hist_result.json",FILE_WRITE|FILE_TXT|FILE_ANSI);
   FileWriteString(f,StringFormat("{\"checks\":%d,\"failures\":%d,\"signals\":%I64d,\"first_m1\":%I64d,\"last_m1\":%I64d,\"elapsed_ms\":%I64u}",checks,failures,g_v4Published,(long)m1[0].time,(long)m1[ArraySize(m1)-1].time,GetTickCount64()-began));FileClose(f);
   PrintFormat("V401_HIST_DONE signals=%I64d failures=%d",g_v4Published,failures);
}
