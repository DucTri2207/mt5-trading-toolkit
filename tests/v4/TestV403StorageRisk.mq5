#property strict
ENUM_TIMEFRAMES testPeriod=PERIOD_H1;
ENUM_TIMEFRAMES TestPeriod(){return testPeriod;}
#define Period TestPeriod
#define OnStart UnusedCoreStart
#include "TestV4Core.mq5"
#undef OnStart
#include <CanHoTroV4/Risk.mqh>
#include <CanHoTroV4/Scorecard.mqh>
void ResetStorage()
{
   ArrayResize(g_v4History,0);ZeroMemory(g_lastSignal);g_v4LastEvaluated=0;
   g_v4IoFailed=false;g_v4LedgerWarning="";
}
void OnStart()
{
   Configure();FileDelete("v4_fixture\\unit_checks.csv");
   InpV4LedgerFolder="v4_fixture\\v402_storage";
   HtfPeriod=PERIOD_CURRENT;LtfPeriod=PERIOD_CURRENT;
   string h1=V4Preset();HtfPeriod=PERIOD_H1;LtfPeriod=PERIOD_M5;
   Check(h1==V4Preset(),"resolved_current_equals_explicit");
   LtfPeriod=PERIOD_M5;testPeriod=PERIOD_H1;h1=V4Preset();
   ResetStorage();Check(V4OpenLedger(),"H1_fresh_open");g_v4LastEvaluated=600;V4CloseLedger();
   int debug=FileOpen(g_v4StatePath,FILE_READ|FILE_CSV|FILE_ANSI,',',CP_UTF8);
   string dp=FileReadString(debug),di=FileReadString(debug),dt=FileReadString(debug);FileClose(debug);
   PrintFormat("V402_EMPTY_STATE preset=%s id=[%s] time=[%s]",dp,di,dt);
   testPeriod=PERIOD_M5;string m5=V4Preset();Check(m5==h1,"display_frames_share_canonical_namespace");
   ResetStorage();Check(V4OpenLedger() && g_v4LastEvaluated==600,"M5_reads_H1_checkpoint");
   SConfirmSignal s;ZeroMemory(s);s.time=s.confirm_bar_open=300;s.signal_known_time=s.publish_time=600;
   s.isBuy=true;s.source_zone_id=s.zoneId=42;s.entry=s.entryMarket=100;s.initialSl=s.sl=95;s.tp1=105;s.tp2=110;s.arrow_anchor=99;s.ltfAtr=2;s.signal_id=V4SignalId(s);
   Check(V4PersistPublished(s),"M5_write_nonempty");g_lastSignal=s;g_v4LastEvaluated=600;V4CloseLedger();
   testPeriod=PERIOD_M15;ResetStorage();Check(V4OpenLedger() && g_v4LastEvaluated==600 && ArraySize(g_v4History)==1,"M15_reads_same_signals_and_state");V4CloseLedger();
   testPeriod=PERIOD_M5;ResetStorage();Check(V4OpenLedger() && ArraySize(g_v4History)==1 && g_v4History[0].signal_id==s.signal_id && g_v4LastEvaluated==600,"M5_return_same_signal_and_state");
   Check(V4ScoreInit() && StringFind(g_v4ScorePath,m5)>=0,"score_resolved_namespace");Check(V4ScoreSave(),"score_save_before_corrupt");
   V4CloseLedger();string state=g_v4StatePath;
   int f=FileOpen(state,FILE_WRITE|FILE_TXT|FILE_ANSI);FileWriteString(f,"wrong,wrong,600");FileClose(f);
   ResetStorage();Check(V4OpenLedger() && ArraySize(g_v4History)==0 && g_v4LastEvaluated==0 && !g_v4IoFailed,"corrupt_own_state_restarts");
   Check(g_v4LedgerWarning!="","corrupt_warning_visible");
   Check(!FileIsExist(g_v4ScorePath),"corrupt_score_quarantined");
   string file;long search=FileFindFirst(InpV4LedgerFolder+"\\state_"+V4FileKey()+".csv_corrupt_*",file);
   Check(search!=INVALID_HANDLE,"corrupt_state_archived");if(search!=INVALID_HANDLE)FileFindClose(search);
   V4CloseLedger();testPeriod=PERIOD_H1;ResetStorage();Check(V4OpenLedger() && g_v4LastEvaluated==0,"shared_recovery_visible_all_frames");V4CloseLedger();
   Check(MathAbs(V4ContractRisk(7.88,.63,100,1)-496.44)<1e-9,"indicator_contract_not_tick_10x");
   Check(V4ContractRisk(5,1,100,0)==0,"missing_conversion_fail_closed");
   Check(V4ContractRisk(5,1,0,1)==0,"missing_contract_fail_closed");
   Check(V4LossRate("USD","USD","","",0,0)==1,"same_currency_no_quote_needed");
   Check(V4LossRate("EUR","USD","EUR","USD",1.1,1.2)==1.2,"loss_conversion_direct_ask");
   Check(V4LossRate("USD","EUR","EUR","USD",1.1,1.2)==1/1.1,"loss_conversion_inverse_bid");
   Check(V4LossRate("JPY","EUR","EUR","USD",1.1,1.2)==0,"unrelated_pair_rejected");
   Check(V4LossRate("EUR","USD","EUR","USD",0,0)==0,"missing_quote_rejected");
   Check(V4LossRate("EUR","USD","EUR","USD",1.2,1.1)==0,"crossed_quote_rejected");
   f=FileOpen("v4_fixture\\v402_units.json",FILE_WRITE|FILE_TXT|FILE_ANSI);
   FileWriteString(f,StringFormat("{\"checks\":%d,\"failures\":%d}",checks,failures));FileClose(f);
   PrintFormat("V402_UNITS_DONE %d/%d",checks-failures,checks);
}
