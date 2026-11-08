// Fixture adapters expose only the closed prefix and the next bar's opening quote.
MqlRates fixtureH[],fixtureM[];
double fixtureHA[],fixtureMA[];
int fixtureHL=-1,fixtureM0=-1,fixtureVisibleM=0,fixtureVisibleH=0;
SZone g_zones[];
SEventLog g_events[];
SConfirmSignal g_lastSignal;
ENUM_CONFIRM_STATE g_confirmState=STATE_IDLE;
int g_atrHandle=102,g_htfAtrHandle=100,g_ltfAtrHandle=101;
int g_statCreated=0,g_statDemand=0,g_statSupply=0,g_statBroken=0,g_statFlipped=0;
datetime g_lastAlertBar=0,g_lastSignalSeenTime=0;
long g_lastSignalSeenZone=-1;
bool g_lastSignalSeenBuy=false;
double g_previousDayHigh=0,g_previousDayLow=0;
double GetPipSize(){return .1;}
double PriceToPips(double p){return MathAbs(p)/GetPipSize();}
void RefreshReferenceLevels(){}
void DrawReferenceLevels(){}
#ifdef CHT_V4_NATIVE_FIXTURE
string g_prefix="DucTri_V4_";
#include <CanHoTroV4/Arrow.mqh>
#else
void DrawSignalArrow(bool buy,datetime t,double p,double a){}
#endif
void DrawTradePlanLines(const SConfirmSignal &s){}
void RemoveTradePlanLines(){}
void SendSignalAlert(const SConfirmSignal &s){}
void SendBeTelegram(const SConfirmSignal &s,double p,double r){}
bool FixtureTick(const string symbol,MqlTick &tick)
{
   if(fixtureM0<0 || fixtureM0>=fixtureVisibleM) return false;
   ZeroMemory(tick); tick.bid=fixtureM[fixtureM0].open; tick.ask=tick.bid+.2;
   tick.time=fixtureM[fixtureM0].time; tick.time_msc=(long)tick.time*1000; return true;
}
double FixtureDouble(const string symbol,const ENUM_SYMBOL_INFO_DOUBLE kind)
{
   return fixtureM[fixtureM0].open+(kind==SYMBOL_ASK ? .2 : 0.);
}
// Synthetic D1 from fully closed frozen H1; never reads the current/future calendar day.
bool FixturePriceD1(datetime at,MqlRates &bar)
{
   int n=MathMin(fixtureVisibleH,fixtureHL+1); if(n<=0)return false;
   datetime day=(datetime)((long)at/86400*86400);
   int l=0,r=n;
   while(l<r){int m=(l+r)/2;if(fixtureH[m].time<day && fixtureH[m].time+3600<=at)l=m+1;else r=m;}
   int last=l-1;if(last<0)return false;
   datetime d=(datetime)((long)fixtureH[last].time/86400*86400);int first=last;
   while(first>0 && fixtureH[first-1].time>=d)first--;
   ZeroMemory(bar);bar.time=d;bar.open=fixtureH[first].open;bar.high=fixtureH[first].high;bar.low=fixtureH[first].low;bar.close=fixtureH[last].close;
   for(int i=first+1;i<=last;i++){bar.high=MathMax(bar.high,fixtureH[i].high);bar.low=MathMin(bar.low,fixtureH[i].low);}
   return bar.close>0;
}
int FixtureRates(const string symbol,const ENUM_TIMEFRAMES tf,const int pos,const int requested,MqlRates &out[])
{
   if(tf==PERIOD_D1)
   {
      if(pos<1 || fixtureM0<0)return -1;
      datetime at=fixtureM[fixtureM0].time;MqlRates day;
      for(int skip=1;skip<pos;skip++){if(!FixturePriceD1(at,day))return -1;at=day.time;}
      MqlRates days[];int n=0;
      for(int i=0;i<requested;i++){if(!FixturePriceD1(at,day))break;ArrayResize(days,n+1);days[n++]=day;at=day.time;}
      bool series=ArrayGetAsSeries(out);ArraySetAsSeries(out,false);ArrayResize(out,n);
      for(int i=0;i<n;i++)out[i]=days[n-1-i];ArraySetAsSeries(out,series);return n;
   }
   bool h=(tf==PERIOD_H1);
   int last=h?fixtureHL:fixtureM0-pos;
   int visible=h?fixtureVisibleH:fixtureVisibleM;
   if(last>=visible || last<0) return -1;
   int n=MathMin(requested,last+1);
   bool series=ArrayGetAsSeries(out); ArraySetAsSeries(out,false); ArrayResize(out,n);
   for(int j=0;j<n;j++) out[j]=h?fixtureH[last-n+1+j]:fixtureM[last-n+1+j];
   if(!h && pos==0 && n>0) out[n-1].high=out[n-1].low=out[n-1].close=out[n-1].open;
   ArraySetAsSeries(out,series); return n;
}
int FixtureBuffer(const int handle,const int buffer,const int pos,const int requested,double &out[])
{
   bool h=(handle==100); int last=h?fixtureHL:fixtureM0-pos;
   if(last<0 || last>=(h?fixtureVisibleH:fixtureVisibleM)) return -1;
   int n=MathMin(requested,last+1); bool series=ArrayGetAsSeries(out);
   ArraySetAsSeries(out,false); ArrayResize(out,n);
   for(int j=0;j<n;j++) out[j]=h?fixtureHA[last-n+1+j]:fixtureMA[last-n+1+j];
   ArraySetAsSeries(out,series); return n;
}
bool ReadFixture(const string name,MqlRates &out[],double &atr[])
{
   int f=FileOpen("v4_fixture\\"+name+".csv",FILE_READ|FILE_CSV|FILE_ANSI,',');
   if(f==INVALID_HANDLE) return false;
   int n=0;
   while(!FileIsEnding(f))
   {
      string stamp=FileReadString(f); if(stamp=="") break;
      ArrayResize(out,n+1,65536); ArrayResize(atr,n+1,65536); ZeroMemory(out[n]);
      out[n].time=(datetime)StringToDouble(stamp); out[n].open=FileReadNumber(f);
      out[n].high=FileReadNumber(f); out[n].low=FileReadNumber(f); out[n].close=FileReadNumber(f);
      atr[n]=FileReadNumber(f); n++;
   }
   FileClose(f); return n>0;
}
void ResetFixtureState()
{
   ZeroMemory(g_lastSignal); g_lastSignalSeenTime=0; g_lastSignalSeenZone=-1;
   g_lastSignalSeenBuy=false; g_lastAlertBar=0; ArrayResize(g_events,0);
   ArrayResize(g_zones,0); g_confirmState=STATE_IDLE;
}
#define CopyRates FixtureRates
#define CopyBuffer FixtureBuffer
#define SymbolInfoTick FixtureTick
#define SymbolInfoDouble FixtureDouble
