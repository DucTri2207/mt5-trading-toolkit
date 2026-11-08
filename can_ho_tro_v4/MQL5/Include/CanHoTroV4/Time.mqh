#ifndef CHT_V4_TIME
#define CHT_V4_TIME
// An observation prefix is independent of the display chart timeframe.
// Opening quotes below are display-plan replay assumptions, never fills.
datetime g_v4ReplayTime=0,g_v4PublishTime=0;
int V4DataRates(const string symbol,ENUM_TIMEFRAMES tf,int pos,int count,MqlRates &out[])
{
#ifdef CHT_V4_NATIVE_FIXTURE
   return CopyRates(symbol,tf,pos,count,out);
#else
   int shift=0;
   if(g_v4ReplayTime>0)
   {
      shift=iBarShift(symbol,tf,g_v4ReplayTime,false);
      if(shift<0) return -1;
   }
   return CopyRates(symbol,tf,shift+pos,count,out);
#endif
}
int V4DataBuffer(int handle,ENUM_TIMEFRAMES tf,int pos,int count,double &out[])
{
#ifdef CHT_V4_NATIVE_FIXTURE
   return CopyBuffer(handle,0,pos,count,out);
#else
   int shift=g_v4ReplayTime>0 ? iBarShift(_Symbol,tf,g_v4ReplayTime,false) : 0;
   if(shift<0) return -1;
   return CopyBuffer(handle,0,shift+pos,count,out);
#endif
}
bool V4DataTick(MqlTick &tick)
{
#ifdef CHT_V4_NATIVE_FIXTURE
   return SymbolInfoTick(_Symbol,tick);
#else
   if(g_v4ReplayTime==0 || InpCompatV301) return SymbolInfoTick(_Symbol,tick);
   ENUM_TIMEFRAMES tf=LtfPeriod==PERIOD_CURRENT?PERIOD_M5:LtfPeriod;
   MqlRates bars[]; ArraySetAsSeries(bars,true);
   if(V4DataRates(_Symbol,tf,0,2,bars)!=2) return false;
   ZeroMemory(tick); tick.time=g_v4ReplayTime;
   tick.bid=bars[0].open; tick.ask=tick.bid+bars[1].spread*V4Point();
   return tick.bid>0 && tick.ask>=tick.bid;
#endif
}
#include <CanHoTroV4/PriceScale.mqh>
#endif
