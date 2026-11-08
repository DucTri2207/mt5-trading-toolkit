#define OnStart CoreOnStart
#include "TestV4Core.mq5"
#undef OnStart
int stage=0;
string fingerprint="";
string HistoryKey()
{
   string key="";
   for(int i=0;i<ArraySize(g_v4History);i++)
   {
      SConfirmSignal s=g_v4History[i];
      key+=s.signal_id+"|"+IntegerToString((long)s.time)+"|"+DoubleToString(s.arrow_anchor,12)+"|"+DoubleToString(s.ltfAtr,12)+";";
   }
   return IntegerToString(V4Hash(key));
}
int OnInit()
{
   Configure(); InpCompatV301=false; InpV4LedgerFolder="v4_fixture\\lifecycle";
   stage=(int)GlobalVariableGet("V4_NATIVE_CHART_STAGE");
   ArrayResize(g_v4History,0); ZeroMemory(g_lastSignal); g_v4LastEvaluated=0;
   bool opened=V4OpenLedger();
   ShowArrows=true; V4RestoreArrows();
   bool actualArrows=true;
   for(int i=0;i<ArraySize(g_v4History);i++)
   {
      SConfirmSignal s=g_v4History[i];
      string name=StringFormat("%sSIG_%s_%s",g_prefix,s.isBuy?"BUY":"SELL",IntegerToString((long)s.time));
      double expectedPrice=s.isBuy?s.arrow_anchor-.25*s.ltfAtr:s.arrow_anchor+.25*s.ltfAtr;
      if(ObjectFind(0,name)<0 || ObjectGetDouble(0,name,OBJPROP_PRICE)!=expectedPrice ||
         ObjectGetInteger(0,name,OBJPROP_TIME)!=(long)s.time) actualArrows=false;
   }
   int f=FileOpen("v4_fixture\\chart_lifecycle.csv",FILE_READ|FILE_WRITE|FILE_CSV|FILE_ANSI,',');
   FileSeek(f,0,SEEK_END);
   fingerprint=HistoryKey();
   if(stage==0)
   {
      GlobalVariableSet("V4_NATIVE_CHART_HASH",(double)V4Hash(fingerprint));
      // Exact text avoids double precision loss for 63-bit hashes.
      int x=FileOpen("v4_fixture\\chart_expected.txt",FILE_WRITE|FILE_TXT|FILE_ANSI); FileWriteString(x,fingerprint); FileClose(x);
      FileWrite(f,"stage","chart_period","signals","opened","arrows_match");
   }
   int x=FileOpen("v4_fixture\\chart_expected.txt",FILE_READ|FILE_TXT|FILE_ANSI);
   string expected=FileReadString(x); FileClose(x);
   bool ok=actualArrows && opened && fingerprint==expected && ArraySize(g_v4History)>100;
   FileWrite(f,stage,(int)ChartPeriod(),ArraySize(g_v4History),opened,ok?"PASS":"FAIL");FileClose(f);
   if(!ok) { Print("V4_CHART_FAIL ",stage); return INIT_FAILED; }
   EventSetTimer(1); return INIT_SUCCEEDED;
}
void OnDeinit(const int reason) { EventKillTimer(); V4CloseLedger(); }
void OnTimer()
{
   if(stage==0)
   {
      GlobalVariableSet("V4_NATIVE_CHART_STAGE",1);
      if(!ChartSetSymbolPeriod(0,_Symbol,PERIOD_M15)) Print("TF15_ERROR ",GetLastError());
   }
   else if(stage==1)
   {
      GlobalVariableSet("V4_NATIVE_CHART_STAGE",2);
      if(!ChartSetSymbolPeriod(0,_Symbol,PERIOD_M5)) Print("TF5_ERROR ",GetLastError());
   }
   else
   {
      int f=FileOpen("v4_fixture\\chart_lifecycle_done.json",FILE_WRITE|FILE_TXT|FILE_ANSI);
      FileWriteString(f,"{\"completed\":true,\"period_sequence\":\"M5-M15-M5\"}");FileClose(f);
      GlobalVariableDel("V4_NATIVE_CHART_STAGE"); GlobalVariableDel("V4_NATIVE_CHART_HASH");
      Print("V4_CHART_LIFECYCLE_DONE"); TerminalClose(0);
   }
}
