#ifndef CHT_V4_PRICE_SCALE
#define CHT_V4_PRICE_SCALE
double g_v4DecisionScale=1;
bool V4PriceFactor(datetime at,double &factor)
{
   factor=1;
   if(InpPriceScaleMode==0) return true;
   if(InpPriceScaleMode!=1 || at<=0) return false;
   string symbol=_Symbol; StringToUpper(symbol);
   if(StringFind(symbol,"XAU")<0) return true;
   MqlRates d;
#ifdef CHT_V4_NATIVE_FIXTURE
   if(!FixturePriceD1(at,d)) return false;
#else
   int shift=iBarShift(_Symbol,PERIOD_D1,at,false);
   MqlRates bars[];
   if(shift<0 || CopyRates(_Symbol,PERIOD_D1,shift+1,1,bars)!=1) return false;
   d=bars[0];
#endif
   if(d.time<=0 || d.time>=at || d.close<=0 || !MathIsValidNumber(d.close)) return false;
   factor=d.close/2000.0;
   return factor>0 && MathIsValidNumber(factor);
}
bool V4SetDecisionScale(datetime at){return V4PriceFactor(at,g_v4DecisionScale);}
double V4Distance(double baseDistance){return baseDistance*g_v4DecisionScale;}
#endif
