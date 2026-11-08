#property strict
#property script_show_inputs
#property version "1.00"
#property description "Deterministic price/state tests; no orders or broker data."

#include "../../Include/GoldScalpCore.mqh"

int testsPassed=0;
int testsFailed=0;

void Check(const bool condition,const string name)
{
   if(condition) testsPassed++;
   else { testsFailed++; Print("FAIL: ",name); }
}

bool Near(const double left,const double right)
{
   return MathAbs(left-right)<1e-7;
}

void TestPriceAndRisk()
{
   Check(Near(GSFavorableMove(true,3000.0,2994.0,2994.2),-6.0),"buy adverse move stays negative");
   Check(Near(GSFavorableMove(false,3000.0,3005.8,3006.0),-6.0),"sell adverse move uses Ask");
   Check(Near(GSNormalize(3000.13,0.05,-1),3000.10),"round down to actual tick");
   Check(Near(GSNormalize(3000.13,0.05,1),3000.15),"round up to actual tick");
   Check(Near(GSNormalize(3000.15,0.05,-1),3000.15),"exact tick is stable");

   double stop=0.0;
   Check(!GSBuildStop(true,3000.0,2988.0,0.5,2.5,10.0,0.01,stop) && stop==0.0,
         "wide structural buy stop rejected rather than clamped inward");
   Check(!GSBuildStop(false,3000.0,3012.0,0.5,2.5,10.0,0.01,stop),
         "wide structural sell stop rejected");
   Check(GSBuildStop(true,3000.0,2999.0,0.2,2.5,10.0,0.01,stop) && Near(stop,2997.5),
         "buy minimum stop expands away from swing");
   Check(GSBuildStop(false,3000.0,3001.0,0.2,2.5,10.0,0.01,stop) && Near(stop,3002.5),
         "sell minimum stop expands away from swing");
   Check(GSBuildStop(true,3000.0,2998.99,0.11,0.2,2.0,0.05,stop) && Near(stop,2998.85),
         "buy stop rounds outward preserving buffer");
   Check(!GSBuildStop(true,3000.0,2998.99,0.11,0.2,1.1,0.05,stop),
         "tick rounding cannot silently exceed maximum risk");
   Check(!GSBuildStop(true,3000.0,3001.0,0.2,2.5,10.0,0.01,stop),
         "buy anchor must be below entry");

   double rr1=0.0,rr2=0.0;
   Check(Near(GSNetRR(true,3000.0,2995.0,3010.0,0.5),9.5/5.5),
         "net RR accounts for additional friction on reward and risk");
   Check(!GSValidateTargets(true,3000.0,2995.0,3010.0,3015.0,0.5,1.8,0.0,0.0,rr1,rr2),
         "raw 2R fails actual minimum 1.8R after costs");
   Check(GSValidateTargets(true,3000.0,2995.0,3011.0,3015.0,0.5,1.8,3016.0,0.5,rr1,rr2),
         "ordered net targets before opposing resistance pass");
   Check(!GSValidateTargets(true,3000.0,2995.0,3011.0,3015.0,0.5,1.8,3014.0,0.5,rr1,rr2),
         "target beyond nearest resistance rejected");
   Check(!GSValidateTargets(true,3000.0,2995.0,3015.0,3011.0,0.0,1.5,0.0,0.0,rr1,rr2),
         "TP1 farther than TP2 rejected");
   Check(!GSValidateTargets(false,3000.0,3005.0,2989.0,2985.0,0.5,1.8,2986.0,0.5,rr1,rr2),
         "short TP2 beyond nearest support rejected");
   Check(GSValidateTargets(false,3000.0,3005.0,2989.0,2985.0,0.5,1.8,2984.0,0.5,rr1,rr2),
         "ordered short targets use mirrored obstacle rule");
   Check(!GSValidateTargets(true,3000.0,3005.0,3011.0,3015.0,0.0,1.0,0.0,0.0,rr1,rr2),
         "stop on wrong side rejected");

   Check(GSShouldCountTouch(false,true),"new zone entry counts one visit");
   Check(!GSShouldCountTouch(true,true),"consecutive candles in zone do not count new visits");
   Check(!GSShouldCountTouch(true,false),"leaving zone does not add visit");
   Check(!GSShouldCountTouch(false,false),"outside zone does not add visit");
}

void TestActiveState()
{
   GSPlan plan;
   GSResetPlan(plan);
   Check(GSStartPlan(plan,101,true,false,100,0,3000,2990,3020,3030),"start market plan");
   int events=GSAdvance(plan,101,2994.0,2994.2,6.0,0.2,0.01,true,false);
   Check(events==GS_EVENT_NONE && !plan.beActive && Near(plan.mfe,0.0),
         "losing six dollars cannot trigger BE or positive MFE");
   events=GSAdvance(plan,102,3006.0,3006.2,6.0,0.2,0.01,true,false);
   Check((events&GS_EVENT_BE)!=0 && plan.beActive && Near(plan.stop,3000.2),
         "favorable six dollars activates BE behind Bid");
   Check(!GSStartPlan(plan,101,true,false,103,0,3001,2991,3021,3031) &&
         plan.beActive && Near(plan.stop,3000.2) && Near(plan.mfe,6.0),
         "same signal identity never resets BE, SL, MFE");
   Check(!GSStartPlan(plan,102,false,false,103,0,3000,3010,2980,2970),
         "new signal cannot overwrite open plan");
   events=GSAdvance(plan,104,3000.1,3000.3,6.0,0.2,0.01,true,false);
   Check(events==GS_EVENT_STOP && plan.status==GS_CLOSED && plan.closeReason==GS_CLOSE_STOP,
         "buy closes at executable Bid below tightened stop");
   Check(!GSStartPlan(plan,101,true,false,105,0,3000,2990,3020,3030),
         "closed identity cannot restart on a repeated confirmation");
   Check(GSStartPlan(plan,103,false,false,106,0,3000,3001,2998,2997),
         "different identity can replace a closed plan");
   events=GSAdvance(plan,107,3000.8,3001.0,6.0,0.0,0.01,false,false);
   Check(events==GS_EVENT_STOP && plan.status==GS_CLOSED,
         "short stop uses Ask even when Bid has not touched stop");

   GSResetPlan(plan);
   GSStartPlan(plan,201,true,false,100,0,3000,2990,3020,3030);
   events=GSAdvance(plan,101,3020.0,3020.2,1.0,0.2,0.01,false,false);
   Check(events==GS_EVENT_TP1 && plan.status==GS_TP1 && !plan.beActive,
         "TP1 is recorded exactly once with BE disabled");
   events=GSAdvance(plan,102,3021.0,3021.2,1.0,0.2,0.01,false,false);
   Check(events==GS_EVENT_NONE,"TP1 event not repeated on later ticks");
   events=GSAdvance(plan,103,3030.0,3030.2,1.0,0.2,0.01,false,false);
   Check(events==GS_EVENT_TP2 && plan.hitTp2 && plan.closeReason==GS_CLOSE_TP2,
         "TP2 event survives terminal state transition");

   GSResetPlan(plan);
   GSStartPlan(plan,202,true,false,100,0,3000,2990,3020,3030);
   events=GSAdvance(plan,101,3031.0,3031.2,1.0,0.2,0.01,true,true);
   Check(events==(GS_EVENT_TP1|GS_EVENT_TP2) && !plan.beActive,
         "jump straight to TP2 records both targets without pointless BE");

   GSResetPlan(plan);
   GSStartPlan(plan,203,true,false,100,0,3000,2990,3020,3030);
   events=GSAdvance(plan,101,3001.0,3001.2,0.5,2.0,0.01,true,false);
   Check(events==GS_EVENT_NONE && !plan.beActive,
         "BE cannot be moved ahead of current executable quote");
   events=GSAdvance(plan,99,3025.0,3025.2,0.5,0.2,0.01,true,false);
   Check(events==GS_EVENT_NONE && !plan.hitTp1 && Near(plan.mfe,1.0),
         "older observation cannot award retroactive excursion");
}

void TestPendingState()
{
   GSPlan plan;
   GSResetPlan(plan);
   Check(GSStartPlan(plan,301,true,true,100,200,3000,2990,3020,3030,3015),
         "start pending buy limit");
   int events=GSAdvance(plan,101,2999.9,3000.1,0.1,0.01,0.01,true,true);
   Check(events==GS_EVENT_NONE && plan.status==GS_PENDING && !plan.beActive && Near(plan.mfe,0.0),
         "Bid touching buy limit cannot fill while Ask remains above entry");
   events=GSAdvance(plan,102,2999.8,3000.0,0.1,0.01,0.01,true,true);
   Check(events==GS_EVENT_FILL && plan.status==GS_ACTIVE && plan.filledAt==102 &&
         !plan.beActive && Near(plan.mfe,0.0),
         "buy fills on Ask and cannot earn pre-fill MFE or BE on fill observation");
   events=GSAdvance(plan,103,3001.0,3001.2,0.5,0.1,0.01,true,false);
   Check((events&GS_EVENT_BE)!=0,"only a later favorable quote can activate pending plan BE");

   GSResetPlan(plan);
   GSStartPlan(plan,302,false,true,100,200,3000,3010,2980,2970,2985);
   events=GSAdvance(plan,101,2999.9,3000.1,0.1,0.0,0.01,true,false);
   Check(events==GS_EVENT_NONE && plan.status==GS_PENDING,
         "Ask touching sell limit cannot fill while Bid remains below entry");
   events=GSAdvance(plan,102,3000.0,3000.2,0.1,0.0,0.01,true,false);
   Check(events==GS_EVENT_FILL && plan.status==GS_ACTIVE && !plan.beActive,
         "sell limit fills on Bid and returns only fill event");

   GSResetPlan(plan);
   GSStartPlan(plan,303,true,true,100,200,3000,2990,3020,3030,3015);
   events=GSAdvance(plan,200,2999.8,3000.0,0.5,0.1,0.01,true,false);
   Check(events==GS_EVENT_EXPIRED && plan.status==GS_EXPIRED && plan.filledAt==0,
         "expiry wins over same-observation entry touch");

   GSResetPlan(plan);
   GSStartPlan(plan,304,true,true,100,200,3000,2990,3020,3030,3015);
   events=GSAdvance(plan,101,3015.0,3015.2,0.5,0.1,0.01,true,false);
   Check(events==GS_EVENT_INVALIDATED && plan.status==GS_INVALIDATED && !plan.hitTp1,
         "opposing liquidity reached before entry cancels plan without claiming profit");

   GSResetPlan(plan);
   GSStartPlan(plan,305,true,true,100,200,3000,2990,3020,3030);
   events=GSAdvance(plan,101,2989.0,2989.2,0.5,0.1,0.01,true,false);
   Check(events==GS_EVENT_INVALIDATED && plan.filledAt==0,
         "gap through entry and stop conservatively invalidates instead of inventing fill history");
   Check(!GSStartPlan(plan,305,true,true,102,202,3000,2990,3020,3030),
         "invalidated same identity cannot be restored");

   GSResetPlan(plan);
   Check(!GSStartPlan(plan,306,true,true,100,100,3000,2990,3020,3030),
         "pending expiry must be later than creation");
   Check(GSStartPlan(plan,307,true,true,100,200,3000,2990,3020,3030),
         "valid pending after rejected start");
   events=GSAdvance(plan,101,3000.0,2999.9,0.5,0.1,0.01,true,false);
   Check(events==GS_EVENT_NONE && plan.status==GS_PENDING,
         "crossed invalid quote cannot fill or change state");
}

void RunGoldScalpCoreTests()
{
   testsPassed=0;
   testsFailed=0;
   TestPriceAndRisk();
   TestActiveState();
   TestPendingState();
   PrintFormat("GOLD_SCALP_CORE_TESTS passed=%d failed=%d",testsPassed,testsFailed);
   // Test artifact only, in this isolated terminal's local MQL5/Files directory.
   // The production helper header remains entirely free of terminal/file I/O.
   int result=FileOpen("TestGoldScalpCore.result.txt",FILE_WRITE|FILE_TXT|FILE_ANSI);
   if(result!=INVALID_HANDLE)
   {
      FileWrite(result,StringFormat("GOLD_SCALP_CORE_TESTS passed=%d failed=%d",testsPassed,testsFailed));
      FileClose(result);
   }
   else Print("FAIL: could not write local test result artifact, error=",GetLastError());
}

void OnStart()
{
   RunGoldScalpCoreTests();
}
