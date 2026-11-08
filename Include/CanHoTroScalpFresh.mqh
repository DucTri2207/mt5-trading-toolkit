#ifndef CAN_HO_TRO_SCALP_FRESH
#define CAN_HO_TRO_SCALP_FRESH
#include "CanHoTroScalpPlan.mqh"
int CHTFreshGate(const CHTCandidate &c,const double tick,const bool retest,const bool room)
{
   int gate=CHTPlannedGate(c,tick,retest,room);
   if(gate!=CHT_NONE)return gate;
   return c.v[9]<=1. ? CHT_NONE : 1001;
}
#endif
