#define OnStart CoreOnStart
#include "TestV4Core.mq5"
#undef OnStart
int indicatorHandle=INVALID_HANDLE,stage=0,waits=0;
SConfirmSignal expectedSignals[];
string defaultPreset="";
bool SeedDefaultLedger()
{
   FolderCreate("CanHoTroV4");
   g_v4Preset=defaultPreset;
   string path="CanHoTroV4\\signals_"+_Symbol+".csv";
   FileDelete(path);
   g_v4SignalsFile=FileOpen(path,FILE_WRITE|FILE_READ|FILE_CSV|FILE_ANSI,',',CP_UTF8);
   if(g_v4SignalsFile==INVALID_HANDLE || !V4Header(g_v4SignalsFile)) return false;
   for(int i=0;i<ArraySize(expectedSignals);i++) if(!V4WriteSignal(g_v4SignalsFile,expectedSignals[i],"PUBLISHED"))return false;
   g_v4StatePath="CanHoTroV4\\state_"+_Symbol+".csv";
   g_lastSignal=expectedSignals[ArraySize(expectedSignals)-1];
   g_v4LastEvaluated=g_lastSignal.time;
   V4SaveState(); FileClose(g_v4SignalsFile);g_v4SignalsFile=INVALID_HANDLE;
   FileDelete("CanHoTroV4\\candidates_"+_Symbol+".csv");
   FileDelete("CanHoTroV4\\guard_rejects_"+_Symbol+".csv");
   return !g_v4IoFailed;
}
int OnInit()
{
   defaultPreset=V4Preset(); Configure(); InpCompatV301=false;
   InpV4LedgerFolder="v4_fixture\\lifecycle";
   stage=(int)GlobalVariableGet("V4_INDICATOR_STAGE_R5");
   ArrayResize(g_v4History,0); ZeroMemory(g_lastSignal); g_v4LastEvaluated=0;
   if(!V4OpenLedger()) return INIT_FAILED;
   ArrayResize(expectedSignals,MathMin(100,ArraySize(g_v4History)));
   for(int i=0;i<ArraySize(expectedSignals);i++)expectedSignals[i]=g_v4History[i];
   V4CloseLedger();
   if(stage==0 && !SeedDefaultLedger()) return INIT_FAILED;
   bool attached=true;
   if(stage>0 && ChartIndicatorsTotal(0,0)>0) indicatorHandle=ChartIndicatorGet(0,0,ChartIndicatorName(0,0,0));
   else
   {
      indicatorHandle=iCustom(_Symbol,(ENUM_TIMEFRAMES)ChartPeriod(),"duc_tri_can_ho_tro_v4");
      attached=indicatorHandle!=INVALID_HANDLE && ChartIndicatorAdd(0,0,indicatorHandle);
   }
   if(indicatorHandle==INVALID_HANDLE || !attached)
   { Print("INDICATOR_ATTACH_FAIL ",GetLastError());return INIT_FAILED; }
   EventSetTimer(1);return INIT_SUCCEEDED;
}
void OnDeinit(const int reason)
{
   EventKillTimer();
   if(indicatorHandle!=INVALID_HANDLE)
   {
      IndicatorRelease(indicatorHandle);indicatorHandle=INVALID_HANDLE;
   }
}
void OnTimer()
{
   bool ok=ArraySize(expectedSignals)==100;
   for(int i=0;i<ArraySize(expectedSignals);i++)
   {
      SConfirmSignal s=expectedSignals[i];
      string name=StringFormat("%sSIG_%s_%s",g_prefix,s.isBuy?"BUY":"SELL",IntegerToString((long)s.time));
      double px=s.isBuy?s.arrow_anchor-.25*s.ltfAtr:s.arrow_anchor+.25*s.ltfAtr;
      if(ObjectFind(0,name)<0 || ObjectGetDouble(0,name,OBJPROP_PRICE)!=px || ObjectGetInteger(0,name,OBJPROP_TIME)!=(long)s.time) {ok=false;break;}
   }
   if(!ok && ++waits<30)return;
   int f=FileOpen("v4_fixture\\indicator_lifecycle_r5.csv",FILE_READ|FILE_WRITE|FILE_CSV|FILE_ANSI,',');
   FileSeek(f,0,SEEK_END);
   if(stage==0)FileWrite(f,"stage","chart_period","signals","actual_indicator_arrow_geometry");
   FileWrite(f,stage,(int)ChartPeriod(),ArraySize(expectedSignals),ok?"PASS":"FAIL");FileClose(f);
   if(!ok)
   { Print("V4_INDICATOR_LIFECYCLE_FAIL ",stage); GlobalVariableDel("V4_INDICATOR_STAGE_R5");TerminalClose(1);return; }
   if(stage<2)
   {
      GlobalVariableSet("V4_INDICATOR_STAGE_R5",stage+1);
      ChartSetSymbolPeriod(0,_Symbol,stage==0?PERIOD_M15:PERIOD_M5);
   }
   else
   {
      GlobalVariableDel("V4_INDICATOR_STAGE_R5");
      int out=FileOpen("v4_fixture\\indicator_lifecycle_done.json",FILE_WRITE|FILE_TXT|FILE_ANSI);
      FileWriteString(out,"{\"completed\":true,\"actual_indicator\":true,\"periods\":\"M5-M15-M5\"}");FileClose(out);
      Print("V4_INDICATOR_LIFECYCLE_DONE");TerminalClose(0);
   }
}
