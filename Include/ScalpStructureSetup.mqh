#ifndef SCALP_STRUCTURE_SETUP_MQH
#define SCALP_STRUCTURE_SETUP_MQH
#include "ScalpStructureTypes.mqh"
// Pure incremental state. No terminal reads, chart writes or order operations.
class SSDetector
{
public:
   int seconds;
   double atr,trSum;
   long usedBuy,usedSell,trailedBuy,trailedSell;
   SSBar bars[];
   SSPivot highs[],lows[];
   SSDetector(void) { Reset(300); }
   void Reset(const int period=300)
   {
      seconds=period;atr=0;trSum=0;
      usedBuy=-1;usedSell=-1;trailedBuy=-1;trailedSell=-1;
      ArrayResize(bars,0);ArrayResize(highs,0);ArrayResize(lows,0);
   }
   void AppendPivot(SSPivot &out[],const int p,const double price,const datetime known)
   {
      int n=ArraySize(out);ArrayResize(out,n+1,256);
      out[n].index=p;out[n].time=bars[p].time;out[n].known=known;out[n].price=price;
   }
   void SetCandidate(SSCandidate &c,const bool buy,const SSPivot &p,const SSBar &b)
   {
      c.valid=true;c.isBuy=buy;c.time=b.time+seconds;c.anchorTime=p.time;
      c.anchor=p.price;c.atr=atr;c.trigger=b.close;c.opposing=0;
   }
   bool Step(const SSBar &b,SSCandidate &c,SSTrail &tb,SSTrail &ts)
   {
      ZeroMemory(c);ZeroMemory(tb);ZeroMemory(ts);
      int i=ArraySize(bars);
      if(i>0 && b.time<=bars[i-1].time) return false;
      double pc=i>0 ? bars[i-1].close : b.close;
      double tr=MathMax(b.high-b.low,MathMax(MathAbs(b.high-pc),MathAbs(b.low-pc)));
      ArrayResize(bars,i+1,1024);bars[i]=b;
      if(i<14) {trSum+=tr;if(i==13) atr=trSum/14.0;}
      else atr=(atr*13.0+tr)/14.0;
      datetime known=b.time+seconds;
      if(i>=4)
      {
         int p=i-2;
         if(bars[p].high>bars[p-2].high && bars[p].high>bars[p-1].high &&
            bars[p].high>=bars[p+1].high && bars[p].high>=bars[p+2].high)
            AppendPivot(highs,p,bars[p].high,known);
         if(bars[p].low<bars[p-2].low && bars[p].low<bars[p-1].low &&
            bars[p].low<=bars[p+1].low && bars[p].low<=bars[p+2].low)
            AppendPivot(lows,p,bars[p].low,known);
      }
      int nh=ArraySize(highs),nl=ArraySize(lows);
      if(seconds!=300 || atr<=0 || nh<2 || nl<2) return false;
      SSPivot a=highs[nh-2],h=highs[nh-1],d=lows[nl-2],l=lows[nl-1];
      bool up=h.price>a.price && l.price>d.price;
      bool down=h.price<a.price && l.price<d.price;
      bool lowValid=true,highValid=true;
      for(int k=l.index+1;k<=i;k++)if(bars[k].low<l.price){lowValid=false;break;}
      for(int k=h.index+1;k<=i;k++)if(bars[k].high>h.price){highValid=false;break;}
      if(up && lowValid && l.index>h.index && i-l.index<=12 && b.close>bars[i-1].high &&
         b.close>b.open && (long)l.time!=usedBuy)
      { usedBuy=(long)l.time;SetCandidate(c,true,l,b); }
      if(down && highValid && h.index>l.index && i-h.index<=12 && b.close<bars[i-1].low &&
         b.close<b.open && (long)h.time!=usedSell)
      { usedSell=(long)h.time;SetCandidate(c,false,h,b); }
      for(int j=nh-1;j>=0;j--)
      {
         if(highs[j].index>=l.index) continue;
         if(lowValid && (long)l.time!=trailedBuy && b.close>highs[j].price)
         {trailedBuy=(long)l.time;tb.time=known;tb.isBuy=true;tb.anchorTime=l.time;tb.stop=l.price-.25*atr;}
         break;
      }
      for(int j=nl-1;j>=0;j--)
      {
         if(lows[j].index>=h.index) continue;
         if(highValid && (long)h.time!=trailedSell && b.close<lows[j].price)
         {trailedSell=(long)h.time;ts.time=known;ts.isBuy=false;ts.anchorTime=h.time;ts.stop=h.price+.25*atr;}
         break;
      }
      return c.valid;
   }
   void Consider(const double level,const bool buy,const double price,double &opposing)
   {
      if(level<=0) return;
      if(buy && level>price && (opposing==0 || level<opposing)) opposing=level;
      if(!buy && level<price && (opposing==0 || level>opposing)) opposing=level;
   }
   void AddLevels(const bool buy,const double price,const datetime asof,double &opposing)
   {
      long age=seconds==300 ? 86400 : 345600;
      if(buy)
      {
         for(int j=ArraySize(highs)-1;j>=0;j--)
         {if(asof-highs[j].time>age)break;Consider(highs[j].price,buy,price,opposing);}
      }
      else
      {
         for(int j=ArraySize(lows)-1;j>=0;j--)
         {if(asof-lows[j].time>age)break;Consider(lows[j].price,buy,price,opposing);}
      }
   }
};
#endif
