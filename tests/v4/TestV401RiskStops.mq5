#define OnStart UnusedCoreOnStart
#include "TestV4Core.mq5"
#undef OnStart
#define CHT_V4_TEST_ORDER_CALC
int oracleMode=0;
bool TestCalcProfit(ENUM_ORDER_TYPE type,string symbol,double lots,double entry,double exit,double &profit)
{
   if(oracleMode==1)return false;
   profit=(exit-entry)*(type==ORDER_TYPE_BUY?1:-1)*lots*100;
   if(oracleMode==2)profit=MathAbs(profit);
   if(oracleMode==3)profit=MathSqrt(-1.0);
   return true;
}
#define OrderCalcProfit TestCalcProfit
#include <CanHoTroV4/Risk.mqh>
#undef OrderCalcProfit
#include <CanHoTroV4/Execution.mqh>
#include <CanHoTroV4/StopRules.mqh>
void OnStart()
{
   FileDelete("v4_fixture\\unit_checks.csv");
   SV4SymbolSpec s;s.tickSize=.01;s.tickValue=.1;s.point=.01;s.minLot=.01;s.maxLot=100;s.step=.01;
   Check(MathAbs(V4RiskMoney(false,4125.79,4133.67,1,s)-788)<1e-6,"oracle_sell_cash_10x_tick");
   Check(g_v4RiskWarning=="broker khai báo tick value không khớp","mismatch_warning_exact");
   Check(MathAbs(V4Lots(100000,.5,false,4125.79,4133.67,s)-.63)<1e-9,"correct_lot_not_6_34");
   Check(MathAbs(V4RiskMoney(true,100,95,1,s)-500)<1e-9,"oracle_buy");
   Check(V4RiskMoney(true,100,105,1,s)==0,"invalid_stop");
   Check(MathAbs(V4CostR(true,100,95,.3,1,7,s)-.078)<1e-9,"cost_oracle_commission");
   Check(V4Lots(100000,.5,true,100,100,s)==0,"zero_risk");
   for(int mode=1;mode<=3;mode++)
   {
      oracleMode=mode;
      Check(V4Lots(100000,.5,true,100,95,s)==0,"oracle_fail_no_tick_fallback");
      Check(V4CostR(true,100,95,.3,1,7,s)==EMPTY_VALUE,"cost_fail_closed");
      SConfirmSignal sig;ZeroMemory(sig);sig.signal_id="failure";sig.isBuy=true;sig.initialSl=95;sig.signal_known_time=600;
      SV4VirtualTrade v;ZeroMemory(v);v.buy=true;v.known=600;v.initialSl=95;
      Check(!V4VirtualFill(v,600,100,100,0,7,s) && !v.filled,"virtual_fill_fail_closed");
   }
   oracleMode=0;
   Check(V4Lots(100000,.5,true,100,99.99,s)==100,"max_volume");
   Check(V4Lots(100,.1,true,100,95,s)==.01,"min_volume_reports_actual_risk");
   Check(V4SameStops(4133.67001,0,4133.67,0,.01,2),"normalized_noop");
   Check(!V4SameStops(4133.68,0,4133.67,0,.01,2),"real_change");
   Check(V4StopsAllowed(true,100,100.2,99,102,98,0,.01,50,0),"buy_allowed");
   Check(V4StopsAllowed(false,100,100.2,101,99,102,0,.01,50,0),"sell_allowed");
   Check(!V4StopsAllowed(true,100,100.2,99.8,0,98,0,.01,50,0),"buy_stops_block");
   Check(!V4StopsAllowed(false,100,100.2,100.4,0,102,0,.01,50,0),"sell_stops_block");
   Check(!V4StopsAllowed(true,100,100.2,99,0,99.9,0,.01,0,20),"freeze_old_stop");
   int f=FileOpen("v4_fixture\\risk_stops_result.json",FILE_WRITE|FILE_TXT|FILE_ANSI);
   FileWriteString(f,StringFormat("{\"checks\":%d,\"failures\":%d}",checks,failures));FileClose(f);
   PrintFormat("V401_RISK_STOPS_DONE checks=%d failures=%d",checks,failures);
}
