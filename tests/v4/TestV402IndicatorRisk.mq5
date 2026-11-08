#define OnStart UnusedCoreStart
#include "TestV4Core.mq5"
#undef OnStart
#define CHT_V4_TEST_ORDER_CALC
int oracleCalls=0;
string testCurrency="USD",testProfit="USD";
double testContract=100;
long TestMQLInfo(ENUM_MQL_INFO_INTEGER property){return property==MQL_PROGRAM_TYPE?PROGRAM_INDICATOR:MQLInfoInteger(property);}
string TestAccountInfo(ENUM_ACCOUNT_INFO_STRING property){return property==ACCOUNT_CURRENCY?testCurrency:AccountInfoString(property);}
string TestSymbolString(string symbol,ENUM_SYMBOL_INFO_STRING property){return property==SYMBOL_CURRENCY_PROFIT && symbol==_Symbol?testProfit:SymbolInfoString(symbol,property);}
double TestSymbolDouble(string symbol,ENUM_SYMBOL_INFO_DOUBLE property){return property==SYMBOL_TRADE_CONTRACT_SIZE?testContract:SymbolInfoDouble(symbol,property);}
bool ForbiddenOracle(ENUM_ORDER_TYPE type,string symbol,double lots,double entry,double exit,double &profit){oracleCalls++;return false;}
#define MQLInfoInteger TestMQLInfo
#define AccountInfoString TestAccountInfo
#define SymbolInfoString TestSymbolString
#define SymbolInfoDouble TestSymbolDouble
#define OrderCalcProfit ForbiddenOracle
#include <CanHoTroV4/Risk.mqh>
void OnStart()
{
   FileDelete("v4_fixture\\unit_checks.csv");
   SV4SymbolSpec s;s.tickSize=.01;s.tickValue=.1;s.point=.01;s.step=.01;s.minLot=.01;s.maxLot=100;
   Check(MathAbs(V4RiskMoney(false,4125.79,4133.67,.63,s)-496.44)<1e-8,"indicator_primary_contract_cash");
   Check(MathAbs(V4Lots(100000,.5,false,4125.79,4133.67,s)-.63)<1e-9,"indicator_lot_correct_step");
   Check(g_v4RiskWarning=="broker khai báo tick value không khớp","indicator_tick_mismatch_warning");
   Check(MathAbs(V4CostR(true,100,95,.3,1,7,s)-.078)<1e-9,"indicator_cost_contract_currency");
   testCurrency="ZZZ";
   Check(V4Lots(100000,.5,true,100,95,s)==0,"missing_FX_no_lot");
   Check(StringFind(g_v4RiskError,"USD/ZZZ")>=0,"missing_FX_explicit_message");
   Check(V4CostR(true,100,95,.3,1,7,s)==EMPTY_VALUE,"missing_FX_no_cost");
   testCurrency="USD";testContract=0;
   Check(V4Lots(100000,.5,true,100,95,s)==0,"missing_contract_no_lot");
   testContract=100;testProfit="";
   Check(V4Lots(100000,.5,true,100,95,s)==0,"missing_currency_no_lot");
   testProfit="USD";
   Check(V4Lots(100000,.5,true,100,95,s)==1 && g_v4RiskError=="","risk_recovers_after_metadata_ready");
   Check(oracleCalls==0,"indicator_never_calls_OrderCalcProfit");
   int f=FileOpen("v4_fixture\\indicator_risk_result.json",FILE_WRITE|FILE_TXT|FILE_ANSI);
   FileWriteString(f,StringFormat("{\"checks\":%d,\"failures\":%d,\"oracle_calls\":%d}",checks,failures,oracleCalls));FileClose(f);
}
