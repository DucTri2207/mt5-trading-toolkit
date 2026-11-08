#define OnStart CoreOnStart
#include "TestV4Core.mq5"
#undef OnStart
string HistoryKey()
{
   string key="";
   for(int i=0;i<ArraySize(g_v4History);i++)
   {
      SConfirmSignal s=g_v4History[i];
      key+=s.signal_id+"|"+IntegerToString((long)s.time)+"|"+
         DoubleToString(s.arrow_anchor,12)+"|"+DoubleToString(s.ltfAtr,12)+";";
   }
   return key;
}
void ClearRuntime()
{
   ResetFixtureState(); ArrayResize(g_v4History,0); g_v4LastEvaluated=0;
   g_v4IoFailed=false; g_v4Candidates=g_v4Published=g_v4Blocked=0;
}
void OnStart()
{
   Configure(); FileDelete("v4_fixture\\unit_checks.csv");
   if(!ReadFixture("h1",fixtureH,fixtureHA)||!ReadFixture("m5",fixtureM,fixtureMA)) return;
   RunStream(false,false,ArraySize(fixtureM),"");
   SConfirmSignal expected[]; ArrayResize(expected,ArraySize(g_v4History));
   for(int i=0;i<ArraySize(expected);i++) expected[i]=g_v4History[i];
   datetime evaluated=g_v4LastEvaluated;
   string before=HistoryKey();
   // Persist through exactly the production writer/checkpoint/loader.
   InpV4LedgerFolder="v4_fixture\\lifecycle";
   FolderCreate(InpV4LedgerFolder);
   string base=InpV4LedgerFolder+"\\";
   FileDelete(base+"signals_"+_Symbol+".csv");
   FileDelete(base+"candidates_"+_Symbol+".csv");
   FileDelete(base+"guard_rejects_"+_Symbol+".csv");
   FileDelete(base+"state_"+_Symbol+".csv");
   ClearRuntime(); Check(V4OpenLedger(),"F7_open_fresh");
   for(int i=0;i<ArraySize(expected);i++)
   {
      Check(V4PersistPublished(expected[i]),"F7_write_signal");
      g_lastSignal=expected[i];
   }
   g_v4LastEvaluated=evaluated; V4SaveState();
   Check(!g_v4IoFailed,"F7_save_state"); V4CloseLedger();
   ClearRuntime(); Check(V4OpenLedger(),"F7_reload_open");
   Check(HistoryKey()==before,"F7_reload_arrows_exact");
   Check(g_v4LastEvaluated==evaluated,"F7_reload_evaluated_exact");
   // Verify actual OBJ_RECTANGLE coordinates against logged source geometry.
   g_v4RenderSource=true;
   int f=FileOpen("v4_fixture\\source_geometry_100.csv",FILE_WRITE|FILE_CSV|FILE_ANSI,',');
   FileWrite(f,"sample","signal_id","source_zone_id","expected_distal","expected_proximal","object_distal","object_proximal","matched");
   uint rng=20261101; bool sampled[]; ArrayResize(sampled,ArraySize(expected)); ArrayInitialize(sampled,false);
   for(int n=0;n<100;n++)
   {
      int idx; do { rng=1664525*rng+1013904223; idx=(int)(rng%(uint)ArraySize(expected)); } while(sampled[idx]);
      sampled[idx]=true;
      SConfirmSignal s=expected[idx]; bool drawn=V4DrawSourceZone(s); ChartRedraw();
      string obj=V4SourceObject(s);
      double distal=ObjectGetDouble(0,obj,OBJPROP_PRICE,0),proximal=ObjectGetDouble(0,obj,OBJPROP_PRICE,1);
      bool ok=drawn && distal==s.source_distal && proximal==s.source_proximal &&
         ObjectGetInteger(0,obj,OBJPROP_TIME,0)==s.zone_known_time &&
         ObjectGetString(0,obj,OBJPROP_TOOLTIP)=="Source zone #"+IntegerToString(s.source_zone_id);
      Check(ok,"F6_source_object_geometry");
      FileWrite(f,n+1,s.signal_id,s.source_zone_id,DoubleToString(s.source_distal,12),DoubleToString(s.source_proximal,12),DoubleToString(distal,12),DoubleToString(proximal,12),ok?"PASS":"FAIL");
   }
   FileClose(f); g_v4RenderSource=false;
   // Simulated disconnected period: no detector calls; reconnect reloads durable arrows.
   V4CloseLedger(); ClearRuntime(); Sleep(1000);
   Check(V4OpenLedger() && HistoryKey()==before,"F7_disconnect_reload_preserves_arrows");
   V4CloseLedger();
   int out=FileOpen("v4_fixture\\lifecycle_result.json",FILE_WRITE|FILE_TXT|FILE_ANSI);
   FileWriteString(out,StringFormat("{\"checks\":%d,\"failures\":%d,\"signals\":%d,\"source_samples\":100,\"reload\":true,\"chart_periods\":\"see_chart_EA_test\",\"disconnect\":\"simulated_no_callbacks\"}",checks,failures,ArraySize(expected)));
   FileClose(out); Print("V4_LIFECYCLE_DONE ",checks," ",failures);
}
