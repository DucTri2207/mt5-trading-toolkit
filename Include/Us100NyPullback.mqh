#ifndef US100_NY_PULLBACK_V1
#define US100_NY_PULLBACK_V1

enum UNYDst { UNY_DST_NONE=0, UNY_DST_EU=1, UNY_DST_US=2 };
struct UNYSignal { int direction; datetime known_at; double atr,extreme; };
struct UNYPlan { int direction; double entry,stop,target,distance,risk_points,spread; datetime entered,deadline; };

datetime UNYDate(const int year,const int month,const int day,const int hour=0)
{
   MqlDateTime v;ZeroMemory(v);v.year=year;v.mon=month;v.day=day;v.hour=hour;return StructToTime(v);
}
int UNYSunday(const int year,const int month,const int nth)
{
   MqlDateTime v;TimeToStruct(UNYDate(year,month,1),v);return 1+(7-v.day_of_week)%7+(nth-1)*7;
}
bool UNYDstAt(const datetime utc,const UNYDst mode)
{
   MqlDateTime v;TimeToStruct(utc,v);if(mode==UNY_DST_NONE)return false;
   if(mode==UNY_DST_US)
      return utc>=UNYDate(v.year,3,UNYSunday(v.year,3,2),7) && utc<UNYDate(v.year,11,UNYSunday(v.year,11,1),6);
   int march=UNYSunday(v.year,3,4);if(march+7<=31)march+=7;
   int october=UNYSunday(v.year,10,4);if(october+7<=31)october+=7;
   return utc>=UNYDate(v.year,3,march,1) && utc<UNYDate(v.year,10,october,1);
}
datetime UNYToUtc(const datetime server,const int winter_hours,const UNYDst mode)
{
   datetime guess=server-winter_hours*3600;
   return server-(winter_hours+(UNYDstAt(guess,mode)?1:0))*3600;
}
datetime UNYToNy(const datetime utc){return utc+(-5+(UNYDstAt(utc,UNY_DST_US)?1:0))*3600;}
bool UNYInSession(const datetime utc)
{
   MqlDateTime v;TimeToStruct(UNYToNy(utc),v);int minute=v.hour*60+v.min;
   return v.day_of_week>=1 && v.day_of_week<=5 && minute>=575 && minute<660;
}
datetime UNYSessionEnd(const datetime utc)
{
   datetime local=UNYToNy(utc);return (datetime)((long)local/86400*86400+11*3600)+(utc-local);
}

void UNYFeatures(const MqlRates &b[],double &fast[],double &slow[],double &atr[],int &warm[])
{
   int n=ArraySize(b);ArrayResize(fast,n);ArrayResize(slow,n);ArrayResize(atr,n);ArrayResize(warm,n);
   double sum=0;
   for(int i=0;i<n;i++)
   {
      bool reset=i==0;
      if(i>0)reset=b[i].time-b[i-1].time!=60 || (long)b[i].time/86400!=(long)b[i-1].time/86400;
      atr[i]=0;
      if(reset){fast[i]=b[i].close;slow[i]=b[i].close;warm[i]=1;sum=b[i].high-b[i].low;}
      else
      {
         warm[i]=warm[i-1]+1;
         fast[i]=fast[i-1]+(b[i].close-fast[i-1])*2.0/21.0;
         slow[i]=slow[i-1]+(b[i].close-slow[i-1])*2.0/51.0;
         double tr=MathMax(b[i].high-b[i].low,MathMax(MathAbs(b[i].high-b[i-1].close),MathAbs(b[i].low-b[i-1].close)));
         if(warm[i]<=14)sum+=tr;
         if(warm[i]==14)atr[i]=sum/14.0;
         else if(warm[i]>14)atr[i]=(atr[i-1]*13.0+tr)/14.0;
      }
   }
}
bool UNYDetect(const MqlRates &b[],const double &f[],const double &s[],const double &a[],const int &warm[],const int i,UNYSignal &out)
{
   ZeroMemory(out);if(i<5 || warm[i]<200)return false;double atr=a[i-1];
   if(atr<=0 || b[i].high-b[i].low>2*atr || MathAbs(b[i].close-b[i].open)<.25*atr)return false;
   bool up=f[i]>s[i] && f[i-3]>s[i-3] && s[i]>s[i-5] && b[i-2].close<b[i-3].close && b[i-1].close<b[i-2].close &&
      b[i-2].close>=s[i-2] && b[i-1].close>=s[i-1] && MathMin(b[i-2].low,b[i-1].low)<=MathMax(f[i-2],f[i-1]) &&
      b[i].close>MathMax(b[i-2].high,b[i-1].high) && b[i].close>b[i].open;
   bool down=f[i]<s[i] && f[i-3]<s[i-3] && s[i]<s[i-5] && b[i-2].close>b[i-3].close && b[i-1].close>b[i-2].close &&
      b[i-2].close<=s[i-2] && b[i-1].close<=s[i-1] && MathMax(b[i-2].high,b[i-1].high)>=MathMin(f[i-2],f[i-1]) &&
      b[i].close<MathMin(b[i-2].low,b[i-1].low) && b[i].close<b[i].open;
   if(!up && !down)return false;
   out.direction=up?1:-1;out.known_at=b[i].time+60;out.atr=atr;
   out.extreme=up?MathMin(b[i].low,MathMin(b[i-1].low,b[i-2].low)):MathMax(b[i].high,MathMax(b[i-1].high,b[i-2].high));
   return true;
}
bool UNYMakePlan(const UNYSignal &s,const double bid,const double ask,const double minimum_spread,const double slip,
                 const double commission_points,const double tick,UNYPlan &p)
{
   ZeroMemory(p);if(tick<=0 || s.atr<=0 || !MathIsValidNumber(bid) || !MathIsValidNumber(ask) || bid<=0 || ask<bid)return false;
   double spread=MathMax(ask-bid,minimum_spread);
   if(spread>MathMin(3.0,.15*s.atr)+1e-9)return false;
   p.direction=s.direction;p.spread=spread;p.entry=s.direction==1?bid+spread+slip:bid-slip;
   double raw=s.direction==1?s.extreme-.1*s.atr:s.extreme+spread+.1*s.atr;
   p.stop=s.direction==1?MathFloor((raw+1e-9)/tick)*tick:MathCeil((raw-1e-9)/tick)*tick;
   p.distance=s.direction*(p.entry-p.stop);
   if(p.distance<.5*s.atr-1e-9 || p.distance>2*s.atr+1e-9)return false;
   double target=p.entry+s.direction*1.25*p.distance;
   p.target=s.direction==1?MathCeil((target-1e-9)/tick)*tick:MathFloor((target+1e-9)/tick)*tick;
   p.risk_points=p.distance+slip+commission_points;return true;
}
double UNYFloorLots(const double budget,const double loss_one_lot,const double minimum,const double step,const double maximum)
{
   if(budget<=0 || loss_one_lot<=0 || minimum<=0 || step<=0 || maximum<=0)return 0;
   double lots=MathFloor((MathMin(maximum,budget/loss_one_lot)+1e-12)/step)*step;
   return lots>=minimum-1e-12?lots:0;
}
#endif
