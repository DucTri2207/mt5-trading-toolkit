#define CHT_M2_UNITS_ONLY
#include "TestV4M2.mq5"
// Replay synthetic opening orders and deals through the production journal accumulator.
struct SFixtureOrder { ulong ticket; double initialSL,lastModifiedSL; };
SFixtureOrder orders[];
double InitialSL(ulong order)
{
   for(int i=0;i<ArraySize(orders);i++) if(orders[i].ticket==order) return orders[i].initialSL;
   return 0;
}
void OnStart()
{
   FileDelete("v4_fixture\\unit_checks.csv");
   SV4SymbolSpec spec=GoldSpec(); SV4Deal deals[];
   ArrayResize(orders,4);
   orders[0].ticket=11; orders[0].initialSL=95; orders[0].lastModifiedSL=101;
   orders[1].ticket=12; orders[1].initialSL=115; orders[1].lastModifiedSL=112;
   orders[2].ticket=13; orders[2].initialSL=117; orders[2].lastModifiedSL=123;
   orders[3].ticket=14; orders[3].initialSL=0; orders[3].lastModifiedSL=101;
   // Deal schema: position,order,time,side,entry,volume,price,profit,commission,swap,fee.
   double raw[][11]={
      {1001,11,660,1,0,1,100,0,-3,0,0},
      {1002,12,700,-1,0,.5,110,0,-1.5,0,0},
      {1004,14,800,1,0,.1,100,0,-.3,0,0},
      {1001,21,900,-1,1,.4,105,200,-1.2,-.8,-.2},
      {1002,22,1000,1,1,.5,115,-250,-1.5,-.5,0},
      {1004,24,1100,-1,1,.1,101,10,-.3,0,0},
      {1001,31,1200,-1,1,.6,102,120,-1.8,-1.2,-.3},
      {1003,13,4000,1,0,.2,120,0,-.6,0,0},
      {1003,23,4100,-1,1,.2,126,120,-.6,0,0}};
   int count=ArrayRange(raw,0); ArrayResize(deals,count);
   SV4JournalTrade positions[];
   int fixtureFile=FileOpen("v4_fixture\\journal_synthetic_deals.csv",FILE_WRITE|FILE_CSV|FILE_ANSI,',');
   FileWrite(fixtureFile,"position_id","order","time","side","entry","volume","price","initial_order_sl","deal_sl","profit","commission","swap","fee");
   for(int i=0;i<count;i++)
   {
      SV4Deal d; ZeroMemory(d); d.position=(long)raw[i][0]; d.order=(ulong)raw[i][1]; d.time=(datetime)raw[i][2];
      d.side=(int)raw[i][3]; d.entry=(int)raw[i][4]; d.volume=raw[i][5]; d.price=raw[i][6];
      d.profit=raw[i][7]; d.commission=raw[i][8]; d.swap=raw[i][9]; d.fee=raw[i][10];
      // Opening SL from opening order; modified SL at exit must never become initial risk.
      d.sl=d.entry==DEAL_ENTRY_IN?InitialSL(d.order):101;
      deals[i]=d;
      FileWrite(fixtureFile,d.position,d.order,(long)d.time,d.side,d.entry,d.volume,d.price,InitialSL(d.order),d.sl,d.profit,d.commission,d.swap,d.fee);
      Check(V4JournalApply(positions,d,spec),"synthetic_deal_applied");
   }
   FileClose(fixtureFile);
   SConfirmSignal signals[]; ArrayResize(signals,1); ZeroMemory(signals[0]);
   signals[0].signal_id="BUY_600_ZONE42"; signals[0].signal_known_time=600; signals[0].isBuy=true;
   signals[0].source_zone_id=42; signals[0].source_distal=95; signals[0].source_proximal=99;
   double expectedNet[]={311.5,-253.5,9.4,118.8};
   double expectedRisk[]={500,250,0,60};
   string expectedLabel[]={"THEO_TIN_HIEU","NGUOC_TIN_HIEU","THEO_TIN_HIEU","TU_VAO"};
   int f=FileOpen("v4_fixture\\journal_synthetic_cases.csv",FILE_WRITE|FILE_CSV|FILE_ANSI,',');
   FileWrite(f,"position_id","initial_SL","remaining","closes","actual_net","expected_net","risk_USD","expected_risk","net_R","label","expected_label","result");
   Check(ArraySize(positions)==4,"multiple_interleaved_positions");
   for(int i=0;i<ArraySize(positions);i++)
   {
      V4JournalMatch(positions[i],signals,30); SV4JournalTrade p=positions[i];
      bool ok=MathAbs(p.netUSD-expectedNet[i])<1e-9 && MathAbs(p.riskUSD-expectedRisk[i])<1e-9 &&
         p.label==expectedLabel[i] && p.remaining<1e-9 && p.riskKnown==(expectedRisk[i]>0);
      Check(ok,"synthetic_net_R_label_each_position");
      FileWrite(f,p.position,p.initialSL,p.remaining,p.partialCloses,p.netUSD,expectedNet[i],p.riskUSD,expectedRisk[i],
         p.riskKnown?DoubleToString(p.netUSD/p.riskUSD,10):"UNKNOWN",p.label,expectedLabel[i],ok?"PASS":"FAIL");
   }
   FileClose(f);
   Check(positions[0].initialSL==95 && positions[0].partialCloses==2,"modified_SL_does_not_change_initial_R");
   // Existing unit checks cover exact window edges, future signals and reversal accounting.
   M2Units();
   f=FileOpen("v4_fixture\\journal_synthetic_result.json",FILE_WRITE|FILE_TXT|FILE_ANSI);
   FileWriteString(f,StringFormat("{\"checks\":%d,\"failures\":%d,\"deals\":%d,\"positions\":%d,\"broker_history\":false}",checks,failures,count,ArraySize(positions))); FileClose(f);
   PrintFormat("V4_M3A_JOURNAL_DONE checks=%d failures=%d",checks,failures);
}
