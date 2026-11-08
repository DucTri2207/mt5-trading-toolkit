#property strict
// Controller only: initial production attachment is through the terminal UI, then a saved chart template.
#define CHT_V4_NATIVE_FIXTURE
#include <CanHoTroV4/Types.mqh>
#include <CanHoTroV4/Inputs.mqh>
ENUM_TIMEFRAMES targetPeriod=PERIOD_M5;
ENUM_TIMEFRAMES TargetPeriod(){return targetPeriod;}
#define Period TargetPeriod
#include <CanHoTroV4/Identity.mqh>
SConfirmSignal g_lastSignal;
datetime g_lastSignalSeenTime=0,g_lastAlertBar=0;
long g_lastSignalSeenZone=-1;
bool g_lastSignalSeenBuy=false,g_v4BatchArrows=false;
string g_prefix="V402_CONTROLLER_";
void DrawSignalArrow(bool buy,datetime t,double p,double atr){}
void V4DrawSourceZone(const SConfirmSignal &s){}
#include <CanHoTroV4/Logger.mqh>
#undef Period
long targetChart=0;
bool failed=false;
void Fail(string reason){failed=true;Print("V402_CHART_FAIL ",reason);}
bool Attach()
{
   return ChartApplyTemplate(targetChart,"v402_m5.tpl");
}
bool Ready()
{
   for(int i=0;i<720;i++)
   {
      if(ObjectFind(targetChart,"DucTri_V4_M2_8")>=0 && ChartIndicatorsTotal(targetChart,0)>0)return true;
      if(i%40==0)Print("V402_READY_WAIT indicators=",ChartIndicatorsTotal(targetChart,0)," objects=",ObjectsTotal(targetChart)," period=",(int)ChartPeriod(targetChart));
      Sleep(250);
   }
   return false;
}
void Capture(string stage)
{
   Sleep(1500);ChartRedraw(targetChart);
   int f=FileOpen("v402_chart\\"+stage+"_arrows.csv",FILE_WRITE|FILE_CSV|FILE_ANSI,',',CP_UTF8);
   FileWrite(f,"name","time","price");
   for(int i=0;i<ObjectsTotal(targetChart,0,-1);i++)
   {
      string name=ObjectName(targetChart,i,0,-1);
      if(StringFind(name,"DucTri_V4_SIG_")==0)FileWrite(f,name,(long)ObjectGetInteger(targetChart,name,OBJPROP_TIME),DoubleToString(ObjectGetDouble(targetChart,name,OBJPROP_PRICE),10));
   }
   FileClose(f);
   string text=ObjectGetString(targetChart,"DucTri_V4_M2_8",OBJPROP_TEXT);
   f=FileOpen("v402_chart\\stages.csv",FILE_READ|FILE_WRITE|FILE_CSV|FILE_ANSI,',',CP_UTF8);FileSeek(f,0,SEEK_END);
   FileWrite(f,stage,(int)ChartPeriod(targetChart),ChartIndicatorsTotal(targetChart,0),text,ObjectGetString(targetChart,"DucTri_V4_M2_10",OBJPROP_TEXT),ObjectGetString(targetChart,"DucTri_V4_RECOVERY",OBJPROP_TEXT));FileFlush(f);FileClose(f);
   ChartScreenShot(targetChart,"v402_chart\\"+stage+".png",1400,900,ALIGN_RIGHT);
   Print("V402_CHART_STAGE ",stage," period=",(int)ChartPeriod(targetChart)," ",text);
}
bool Change(ENUM_TIMEFRAMES tf,string stage)
{
   if(!ChartSetSymbolPeriod(targetChart,_Symbol,tf))return false;
   for(int i=0;i<40 && ChartPeriod(targetChart)!=tf;i++)Sleep(250);
   Sleep(2000);if(!Ready())return false;Capture(stage);return true;
}
bool SeedAcceptedM5()
{
   int f=FileOpen("v402_chart\\accepted_broker_signals.csv",FILE_READ|FILE_CSV|FILE_ANSI,',',CP_UTF8);
   if(f==INVALID_HANDLE || !V4Header(f))return false;
   FileReadString(f);g_v4Preset=FileReadString(f);FileSeek(f,0,SEEK_SET);V4Header(f);
   SConfirmSignal accepted[];
   while(!FileIsEnding(f))
   {
      SConfirmSignal s;if(!V4ReadSignal(f,s)){FileClose(f);return false;}
      int n=ArraySize(accepted);ArrayResize(accepted,n+1);accepted[n]=s;
   }
   FileClose(f);if(ArraySize(accepted)!=29)return false;
   targetPeriod=PERIOD_M5;
   if(!V4OpenLedger())return false;
   if(ArraySize(g_v4History)==0)
      for(int i=0;i<ArraySize(accepted);i++)if(!V4PersistPublished(accepted[i]))return false;
   if(ArraySize(g_v4History)!=29)return false;
   g_lastSignal=accepted[ArraySize(accepted)-1];g_lastSignal.active=false;
   g_v4LastEvaluated=iTime(_Symbol,PERIOD_M5,0);V4CloseLedger();
   f=FileOpen("v402_chart\\risk_expected.csv",FILE_WRITE|FILE_CSV|FILE_ANSI,',',CP_UTF8);
   FileWrite(f,"equity","percent","entry","sl","contract","step","min_lot","max_lot","profit_ccy","account_ccy","fingerprint");
   FileWrite(f,AccountInfoDouble(ACCOUNT_EQUITY),InpRiskPercent,g_lastSignal.entryMarket,g_lastSignal.initialSl,SymbolInfoDouble(_Symbol,SYMBOL_TRADE_CONTRACT_SIZE),SymbolInfoDouble(_Symbol,SYMBOL_VOLUME_STEP),SymbolInfoDouble(_Symbol,SYMBOL_VOLUME_MIN),SymbolInfoDouble(_Symbol,SYMBOL_VOLUME_MAX),SymbolInfoString(_Symbol,SYMBOL_CURRENCY_PROFIT),AccountInfoString(ACCOUNT_CURRENCY),V4Preset());FileClose(f);
   return true;
}
void OnStart()
{
   if(StringFind(TerminalInfoString(TERMINAL_DATA_PATH),"20261102_m3a_v1\\portable_terminal")<0){Print("V402_WRONG_TERMINAL_REJECTED");return;}
   FolderCreate("v402_chart");
   // Clear only production indicators left by this portable's interrupted chart test.
   for(long chart=ChartFirst();chart>=0;chart=ChartNext(chart))
      if(ChartSymbol(chart)==_Symbol)
         for(int i=ChartIndicatorsTotal(chart,0)-1;i>=0;i--)
         {string name=ChartIndicatorName(chart,0,i);if(StringFind(name,"duc_tri_can_ho_tro_v4")>=0)ChartIndicatorDelete(chart,0,name);}
   Sleep(2500);
   int f=FileOpen("v402_chart\\stages.csv",FILE_WRITE|FILE_CSV|FILE_ANSI,',',CP_UTF8);FileWrite(f,"stage","period","indicator_count","lot_panel","risk_warning","recovery_warning");FileClose(f);
   if(!SeedAcceptedM5()){Fail("seed accepted broker ledger");return;}
   targetChart=ChartOpen(_Symbol,PERIOD_H1);if(targetChart==0){Fail("H1 chart open");return;}
   ChartSetInteger(targetChart,CHART_BRING_TO_TOP,true);
   Comment("V402 controller: attach production indicator on the new XAUUSD H1 chart.");
   f=FileOpen("v402_chart\\waiting_ui.json",FILE_WRITE|FILE_TXT|FILE_ANSI);FileWriteString(f,"{\"attach_via_UI\":true}");FileClose(f);
   if(!Ready()){Fail("H1 UI attach timeout");return;}Capture("H1_first");
   if(!Change(PERIOD_M5,"M5_first") || !Change(PERIOD_M15,"M15") || !Change(PERIOD_M5,"M5_return")){Fail("period sequence");return;}
   string name=ChartIndicatorName(targetChart,0,0);
   if(!ChartSaveTemplate(targetChart,"v402_m5.tpl")){Fail("save actual chart template");return;}
   f=FileOpen("v402_chart\\template_ready.flag",FILE_WRITE|FILE_TXT|FILE_ANSI);FileWriteString(f,"ready");FileClose(f);
   for(int i=0;i<480 && !FileIsExist("v402_chart\\template_clean.flag");i++)Sleep(250);
   if(!FileIsExist("v402_chart\\template_clean.flag")){Fail("clean template timeout");return;}
   if(!ChartIndicatorDelete(targetChart,0,name)){Fail("detach");return;}Sleep(2000);
   if(!Attach() || !Ready()){Fail("reattach");return;}Capture("M5_reattach");
   f=FileOpen("v402_chart\\normal_done.json",FILE_WRITE|FILE_TXT|FILE_ANSI);FileWriteString(f,"{\"completed\":true,\"actual_production_indicator\":true,\"accepted_broker_seed\":29}");FileClose(f);
   // Pause for the host's UI observation, then exercise recovery on this test configuration only.
   for(int i=0;i<600 && !FileIsExist("v402_chart\\continue_recovery.flag");i++)Sleep(250);
   if(!FileIsExist("v402_chart\\continue_recovery.flag")){Fail("host observation timeout; recovery not run");return;}
   name=ChartIndicatorName(targetChart,0,0);if(!ChartIndicatorDelete(targetChart,0,name)){Fail("detach before recovery");return;}Sleep(2000);
   targetPeriod=PERIOD_M5;string state=InpV4LedgerFolder+"\\state_"+V4FileKey()+".csv";
   FileCopy(state,0,"v402_chart\\state_before_corruption.csv",0);
   f=FileOpen(state,FILE_WRITE|FILE_TXT|FILE_ANSI);FileWriteString(f,"mismatched,mismatched,600");FileClose(f);
   if(!Attach() || !Ready()){Fail("corrupt recovery attach");return;}Capture("M5_recovered");
   if(ObjectGetString(targetChart,"DucTri_V4_RECOVERY",OBJPROP_TEXT)==""){Fail("recovery warning missing");return;}
   f=FileOpen("v402_chart\\done.json",FILE_WRITE|FILE_TXT|FILE_ANSI);FileWriteString(f,"{\"completed\":true,\"actual_production_indicator\":true,\"recovery_warning\":true}");FileClose(f);
   Print("V402_CHART_DONE");
}
