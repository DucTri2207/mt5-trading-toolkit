#define OnStart CoreOnStart
#include "TestV4Core.mq5"
#undef OnStart

string Canonical(const SConfirmSignal &s)
{
   return s.signal_id+"|"+IntegerToString((long)s.confirm_bar_open)+"|"+
      IntegerToString((long)s.signal_known_time)+"|"+IntegerToString((long)s.publish_time)+"|"+
      IntegerToString(s.source_zone_id)+"|"+IntegerToString((long)s.zone_known_time)+"|"+
      IntegerToString((long)s.sweep_time)+"|"+DoubleToString(s.entry,12)+"|"+
      DoubleToString(s.initialSl,12)+"|"+DoubleToString(s.tp1,12)+"|"+DoubleToString(s.tp2,12)+"|"+
      DoubleToString(s.source_distal,12)+"|"+DoubleToString(s.source_proximal,12)+"|"+
      DoubleToString(s.arrow_anchor,12)+"|"+DoubleToString(s.ltfAtr,12);
}
void OnStart()
{
   Configure(); FileDelete("v4_fixture\\unit_checks.csv"); UnitChecks();
   if(!ReadFixture("h1",fixtureH,fixtureHA)||!ReadFixture("m5",fixtureM,fixtureMA)) return;
   ulong began=GetTickCount64();
   RunStream(false,false,ArraySize(fixtureM),"");
   SConfirmSignal baseline[]; ArrayResize(baseline,ArraySize(g_v4History));
   for(int b=0;b<ArraySize(baseline);b++) baseline[b]=g_v4History[b];
   // Independent runs: the adapter cannot access bars beyond each selected cutoff.
   const uint seed=20261101; uint rng=seed;
   int start=0,count=200;
   int config=FileOpen("v4_fixture\\prefix_partition.csv",FILE_READ|FILE_CSV|FILE_ANSI,',');
   if(config!=INVALID_HANDLE){start=(int)FileReadNumber(config);count=(int)FileReadNumber(config);FileClose(config);}
   int passed=0,f=FileOpen("v4_fixture\\prefix_200.csv",FILE_WRITE|FILE_CSV|FILE_ANSI,',');
   FileWrite(f,"seed","case","visible_m5","cutoff","expected","actual","matched","first_mismatch");
   for(int trial=0;trial<200;trial++)
   {
      rng=1664525*rng+1013904223;
      int limit=31+(int)(rng%(uint)(ArraySize(fixtureM)-31));
      if(trial<start || trial>=start+count) continue;
      RunStream(false,false,limit,"");
      int expected=0;
      datetime cut=fixtureM[limit-1].time;
      while(expected<ArraySize(baseline) && baseline[expected].publish_time<=cut) expected++;
      int actual=ArraySize(g_v4History),bad=-1;
      if(expected!=actual) bad=MathMin(expected,actual);
      for(int j=0;j<MathMin(expected,actual);j++)
         if(Canonical(baseline[j])!=Canonical(g_v4History[j])) { bad=j; break; }
      bool ok=(bad<0); if(ok) passed++;
      FileWrite(f,seed,trial+1,limit,(long)cut,expected,actual,ok?"PASS":"FAIL",bad); FileFlush(f);
   }
   FileClose(f);
   int result=FileOpen("v4_fixture\\prefix_result.json",FILE_WRITE|FILE_TXT|FILE_ANSI);
   FileWriteString(result,StringFormat("{\"seed\":%u,\"prefix_passed\":%d,\"prefix_total\":%d,\"start\":%d,\"elapsed_ms\":%I64u}",seed,passed,count,start,GetTickCount64()-began));
   FileClose(result); Print("V4_PREFIX_DONE ",passed,"/200");
}
