#property strict
#include "../../Include/GoldScalpContext.mqh"

int failures=0;
int checks=0;
void Expect(const bool condition,const string name)
{
   checks++;
   if(!condition) { failures++; Print("FAIL: ",name); }
}
bool Near(const double actual,const double expected,const double tolerance=0.000001)
{
   return MathAbs(actual-expected)<tolerance;
}
void MakeBars(MqlRates &rates[],const int count,const datetime newest)
{
   ArrayResize(rates,count);
   ArraySetAsSeries(rates,true);
   for(int i=0;i<count;i++)
   {
      ZeroMemory(rates[i]);
      rates[i].time=newest-i*300;
      rates[i].open=100.0;
      rates[i].high=102.0;
      rates[i].low=98.0;
      rates[i].close=100.0;
      rates[i].tick_volume=1;
   }
}
void OnStart()
{
   datetime day=D'2026.10.23 00:00:00';
   MqlRates rates[];
   MakeBars(rates,4,day+900);
   rates[0].high=10000.0; rates[0].low=1.0; rates[0].close=9000.0;
   rates[0].tick_volume=100000;
   rates[1].high=104.0; rates[1].low=100.0; rates[1].close=102.0;
   rates[1].tick_volume=3;
   double high,low,vwap,stdev; int count; long volume; bool covered; datetime last;
   bool found=GscSessionStats(rates,day,day+1020,day+1020,
               high,low,vwap,stdev,count,volume,covered,last);
   Expect(found && count==3 && volume==5,"exclude live bar from session and volume");
   Expect(Near(high,104.0) && Near(low,98.0),"live extremes excluded");
   Expect(Near(vwap,101.2) && Near(stdev,MathSqrt(0.96)),"weighted VWAP and variance");
   Expect(covered && last==day+600,"coverage ends at latest completed five-minute boundary");
   Expect(!GscClosedBar(rates,0,day+1020),"forming bar is not closed");
   Expect(GscClosedBar(rates,1,day+1020),"earlier completed bar is closed");
   GscSessionStats(rates,day,day+900,day+600,high,low,vwap,stdev,count,volume,covered,last);
   Expect(count==2 && Near(high,102.0),"as-of excludes future closed bars from historical decision");
   rates[2].time+=1;
   GscSessionStats(rates,day,day+1020,day+1020,high,low,vwap,stdev,count,volume,covered,last);
   Expect(!covered,"history gap not advertised as full session");

   MakeBars(rates,10,day+2700);
   rates[5].low=95.0;
   rates[1].low=94.0; rates[1].close=99.0;
   double level; int pivot;
   Expect(GscFindSweepReclaim(rates,1,true,8,1,0.1,level,pivot) &&
          Near(level,95.0) && pivot==5,"buy sweep reclaims known prior swing");
   rates[1].close=94.5;
   Expect(!GscFindSweepReclaim(rates,1,true,8,1,0.1,level,pivot),"sweep without reclaim rejected");
   rates[1].close=99.0; rates[3].low=94.5; rates[2].low=94.5;
   Expect(!GscFindSweepReclaim(rates,1,true,8,1,0.1,level,pivot),"previously taken liquidity is rejected");
   MakeBars(rates,10,day+2700);
   rates[5].high=105.0; rates[1].high=106.0; rates[1].close=101.0;
   Expect(GscFindSweepReclaim(rates,1,false,8,1,0.1,level,pivot) &&
          Near(level,105.0),"sell sweep reclaims known prior swing");
   Expect(!GscFindSweepReclaim(rates,0,false,8,1,0.1,level,pivot),"live sweep is rejected");

   rates[1].open=100; rates[1].close=103; rates[1].high=104; rates[1].low=99;
   Expect(GscHasDisplacement(rates,1,2,1.0,0.5,true),"directional displacement accepted");
   Expect(!GscHasDisplacement(rates,1,2,1.0,0.5,false),"wrong direction rejected");
   Expect(!GscHasDisplacement(rates,0,2,1.0,0.5,true),"live displacement rejected");

   MakeBars(rates,130,day+129*300);
   for(int i=0;i<130;i++) rates[i].close=200.0-i*0.1;
   rates[0].close=100000;
   double ema,slope,lastClose; int regime;
   Expect(GscClosedEma(rates,rates[0].time+60,20,3,ema,slope,lastClose,regime) &&
          regime==1 && Near(lastClose,199.9) && ema<200.0,
          "EMA uses closed bars, rising regime, ignores live spike");
   rates[0].close=0.1;
   double ema2,slope2,last2; int regime2;
   GscClosedEma(rates,rates[0].time+60,20,3,ema2,slope2,last2,regime2);
   Expect(Near(ema,ema2) && Near(slope,slope2),"EMA invariant to current-bar mutation");
   ArraySetAsSeries(rates,false);
   Expect(!GscHasDisplacement(rates,1,2,1.0,0.5,true),"wrong array orientation rejected");
   Expect(GscDayStart(day+45678)==day,"UTC day boundary helper");
   MakeBars(rates,4,day+86400);
   for(int i=0;i<4;i++) rates[i].time=day+(1-i)*86400;
   rates[0].high=99999.0;
   rates[1].high=80000.0;
   rates[2].high=150.0; rates[2].low=90.0;
   datetime previousOpen;
   Expect(GscPreviousCompletedDayFromRates(rates,day+3600,high,low,previousOpen) &&
          Near(high,150.0) && previousOpen==day-86400,
          "D1 excludes unfinished current day and future daily bars");
   rates[0].high=1000000.0; rates[1].high=9000000.0;
   Expect(GscPreviousCompletedDayFromRates(rates,day,high,low,previousOpen) &&
          Near(high,150.0),"D1 exact midnight decision invariant to future/current high");
   MakeBars(rates,1,day);
   rates[0].high=125;
   Expect(!GscPreviousCompletedDayFromRates(rates,day+86399,high,low,previousOpen),
          "D1 one second before completion unavailable");
   Expect(GscPreviousCompletedDayFromRates(rates,day+86400,high,low,previousOpen) &&
          Near(high,125.0),"D1 weekend completion without next daily bar");
   PrintFormat("GoldScalpContext: %d checks, %d failures",checks,failures);
   int report=FileOpen("TestGoldScalpContext.result.txt",FILE_WRITE|FILE_TXT|FILE_ANSI);
   if(report!=INVALID_HANDLE)
   {
      FileWrite(report,"checks="+IntegerToString(checks));
      FileWrite(report,"failures="+IntegerToString(failures));
      FileClose(report);
   }
   else Print("FAIL: cannot write TestGoldScalpContext.result.txt; error ",GetLastError());
}
