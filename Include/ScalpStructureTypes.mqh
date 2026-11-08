#ifndef SCALP_STRUCTURE_TYPES_MQH
#define SCALP_STRUCTURE_TYPES_MQH
#define SS_VERSION "p2_structure_0.1"
struct SSBar { datetime time; double open,high,low,close; };
struct SSPivot { int index; datetime time,known; double price; };
struct SSCandidate
{
   bool valid,isBuy;
   datetime time,anchorTime;
   double anchor,atr,trigger,opposing;
};
struct SSTrail { datetime time,anchorTime; bool isBuy; double stop; };
enum SSExitPolicy { SS_FIXED_15=0, SS_STRUCTURE_TRAIL=1 };
enum SSResult { SS_OPEN=0, SS_STOP=1, SS_TARGET=2, SS_TIME=3, SS_GAP=4 };
struct SSPlan
{
   bool active,isBuy;
   datetime signalTime,anchorTime,entryTime,exitTime;
   double entry,initialStop,stop,risk,target,roomR,exitPrice,resultR;
   SSExitPolicy policy;
   SSResult result;
};
double SSNormalize(const double price,const double tick,const int direction)
{
   if(tick<=0) return price;
   return (direction<0 ? MathFloor(price/tick+1e-9) : MathCeil(price/tick-1e-9))*tick;
}
int SSDirection(const bool buy) { return buy ? 1 : -1; }
#endif
