#ifndef CHT_V4_STOP_RULES
#define CHT_V4_STOP_RULES
double V4StopPrice(double price,double size,int digits){return price==0?0:NormalizeDouble(MathRound(price/size)*size,digits);}
bool V4SameStops(double sl,double tp,double oldSL,double oldTP,double size,int digits)
{
   return V4StopPrice(sl,size,digits)==V4StopPrice(oldSL,size,digits) && V4StopPrice(tp,size,digits)==V4StopPrice(oldTP,size,digits);
}
bool V4StopsAllowed(bool buy,double bid,double ask,double sl,double tp,double oldSL,double oldTP,double point,long stops,long freeze)
{
   double quote=buy?bid:ask,side=buy?1:-1,minDistance=MathMax(stops,freeze)*point;
   if(sl>0 && ((quote-sl)*side<=0 || (quote-sl)*side+1e-9<minDistance))return false;
   if(tp>0 && ((tp-quote)*side<=0 || (tp-quote)*side+1e-9<minDistance))return false;
   if(freeze>0 && ((oldSL>0 && MathAbs(quote-oldSL)<=freeze*point+1e-9) || (oldTP>0 && MathAbs(quote-oldTP)<=freeze*point+1e-9)))return false;
   return true;
}
#endif
