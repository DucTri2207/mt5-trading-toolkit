#ifndef CAN_HO_TRO_SCALP_LEGACY
#define CAN_HO_TRO_SCALP_LEGACY
#include "CanHoTroScalpTypes.mqh"
// Immutable-preset plan proposal at the confirmation close, before active-slot
// selection. This is a planned-price oracle, not a claim about broker fills.
bool CHTLegacyPlanned(const CHTCandidate &c,const CHTZone &zones[],const CHTContext &ctx,double &values[])
{
   if(c.v[27]!=0)return false;
   bool buy=(bool)c.v[2];double d=buy?1.:-1.,entry=c.v[21],stop=c.v[19],risk=d*(entry-stop);
   if(risk>20.)return false;
   if(risk<2.){risk=2.;stop=entry-d*risk;}
   double target=entry+d*.5*risk,macro=entry+d*4.5*risk,distance=9999999.;
   double day=buy?ctx.dayHigh:ctx.dayLow;
   if((buy && day>entry)||(!buy && day>0 && day<entry)){distance=MathAbs(day-entry);macro=day;}
   for(int z=0;z<ArraySize(zones);z++)
   {
      if(zones[z].isBroken || zones[z].isSupply!=buy)continue;
      double level=zones[z].proximal;
      if(((buy && level>entry)||(!buy && level<entry)) && MathAbs(level-entry)<distance)
      {distance=MathAbs(level-entry);macro=level;}
   }
   ArrayResize(values,10);
   values[0]=c.v[0];values[1]=c.v[1];values[2]=c.v[2];values[3]=c.v[7];values[4]=entry;
   values[5]=stop;values[6]=risk;values[7]=target;values[8]=target;values[9]=macro;return true;
}
bool CHTLegacyPreclose(const bool active,const bool buy,const double bid,const double sl,const double tp2)
{
   // v3.12 DetectLtfConfirmation lines1497-1503: Bid is used for both sides.
   if(active && ((buy && (bid<=sl || bid>=tp2)) || (!buy && (bid>=sl || bid<=tp2))))return false;
   return active;
}
#endif
