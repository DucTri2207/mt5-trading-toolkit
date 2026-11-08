#property strict
#define CHT_V4_NATIVE_FIXTURE
#include <CanHoTroV4/Types.mqh>
#include <CanHoTroV4/Inputs.mqh>
#include "FixtureData.mqh"
#include <CanHoTroV4/Identity.mqh>
#include <CanHoTroV4/Time.mqh>
#include <CanHoTroV4/SourceZone.mqh>
#include <CanHoTroV4/Logger.mqh>
#include <CanHoTroV4/Zones.mqh>
#include "KillzoneV301.mqh"
#include <CanHoTroV4/Signals.mqh>
#include "PlanStateV301.mqh"
#undef CopyRates
#undef CopyBuffer
#undef SymbolInfoTick
#undef SymbolInfoDouble

int failures=0,checks=0;
void Check(bool ok,string name)
{
   checks++;
   int f=FileOpen("v4_fixture\\unit_checks.csv",FILE_READ|FILE_WRITE|FILE_CSV|FILE_ANSI,',');
   FileSeek(f,0,SEEK_END); FileWrite(f,name,ok?"PASS":"FAIL"); FileClose(f);
   if(!ok) { failures++; Print("FAIL ",name); }
}

void Configure()
{
   InpPriceScaleMode=0;
   FilterKillzones=false; InpTpMode=TP_MODE_RR; InpEntryMode=ENTRY_MARKET_CONFIRM;
   AlertConfirm=false; ShowTradeLines=false; ShowArrows=false; UseReferenceLevels=false;
   AlertPopup=false; AlertPush=false; AlertSoundOn=false; TgEnable=false; AlertBeTriggered=false;
   g_v4Point=.01; g_v4RenderSource=false;
}

void UnitChecks()
{
   SZone z; ZeroMemory(z); z.timeKnown=3600; z.timeInvalid=7200;
   Check(!V4ZoneAvailable(z,3599),"F1_before_known");
   Check(V4ZoneAvailable(z,3600),"F1_at_known");
   Check(!V4SweepAvailable(z,3599),"F1_sweep_before_known");
   Check(V4SweepAvailable(z,3600),"F1_sweep_at_known");
   Check(!V4ZoneAvailable(z,7200),"F2_at_invalidation");
   Check(V4ZoneAvailable(z,7199),"F2_before_invalidation");
   double risk=5.0,point=V4Point();
   Check(!V4RrAllowed(MinRR-point/risk,2),"F4_one_point_below");
   Check(V4RrAllowed(MinRR,2),"F4_exact_floor");
   Check(V4RrAllowed(MinRR+point/risk,2),"F4_one_point_above");
   Check(V4RrAllowed(MinRR-1e-12,2),"F4_binary_roundoff");
   Check(!V4RrAllowed(MinRR,MinRR-point/risk),"F4_tp_order");
   long id=V4ZoneId(1700000000,true,2000.004,1999.001);
   Check(id==V4ZoneId(1700000000,true,2000.004,1999.001),"F3_repeat_id");
   Check(id==V4ZoneId(1700000000,true,2000.001,1999.004),"F3_point_quantization");
   Check(id!=V4ZoneId(1700000000,false,2000.004,1999.001),"F3_side_changes_id");
}

void LedgerHeader(int f)
{
   FileWrite(f,"confirm_bar_open","signal_known_time","publish_time","direction","entry","sl",
      "tp1","tp2","source_zone_id","zone_start","zone_type","distal","proximal","zone_known_time","sweep_time");
}
void WritePublished(int f,const SConfirmSignal &s)
{
   datetime start=0;
   for(int j=0;j<ArraySize(g_zones);j++) if(g_zones[j].id==s.zoneId) { start=g_zones[j].timeStart; break; }
   FileWrite(f,(long)s.time,(long)s.signal_known_time,(long)s.publish_time,s.isBuy?1:-1,
      DoubleToString(s.entry,10),DoubleToString(s.initialSl,10),DoubleToString(s.tp1,10),
      DoubleToString(s.tp2,10),s.zoneId,(long)start,s.zoneType,
      DoubleToString(s.source_distal,10),DoubleToString(s.source_proximal,10),
      (long)s.zone_known_time,(long)s.sweep_time);
}

long RunStream(const bool compat,const bool idle,const int limit,const string output)
{
   ResetFixtureState(); g_v4LastEvaluated=0; ArrayResize(g_v4History,0);
   g_v4Candidates=g_v4Published=g_v4Blocked=0; g_v4GuardCandidates=g_v4GuardRejected=0;
   InpCompatV301=compat; g_v4Preset=V4Preset();
   fixtureHL=-1; fixtureVisibleM=limit; fixtureVisibleH=ArraySize(fixtureH);
   int f=INVALID_HANDLE;
   if(output!="") { f=FileOpen(output,FILE_WRITE|FILE_CSV|FILE_ANSI,','); LedgerHeader(f); }
   long digest=0;
   for(int m=30;m<limit;m++)
   {
      fixtureM0=m; g_v4Now=fixtureM[m].time;
      int old=fixtureHL;
      while(fixtureHL+1<ArraySize(fixtureH) && fixtureH[fixtureHL+1].time+3600<=g_v4Now) fixtureHL++;
      if(!V4SetDecisionScale(g_v4Now)) continue;
      if(old!=fixtureHL || ArraySize(g_zones)==0) CZoneEngine::Scan();
      if(idle) { ZeroMemory(g_lastSignal); g_lastSignalSeenTime=0; g_lastSignalSeenZone=-1; }
      long published=g_v4Published;
      CSignalEngine::Detect(true);
      if(g_v4Published>published)
      {
         SConfirmSignal s=g_v4History[ArraySize(g_v4History)-1];
         if(f!=INVALID_HANDLE) WritePublished(f,s);
         digest=V4Hash(IntegerToString(digest)+"|"+s.signal_id+"|"+DoubleToString(s.entry,10)+"|"+DoubleToString(s.initialSl,10));
      }
      double px=fixtureM[m].open+(g_lastSignal.isBuy?0:.2);
      ManageActiveSignal(px);
   }
   if(f!=INVALID_HANDLE) FileClose(f);
   return digest;
}

void OnStart()
{
   Configure();
   FileDelete("v4_fixture\\unit_checks.csv");
   UnitChecks();
   if(!ReadFixture("h1",fixtureH,fixtureHA)||!ReadFixture("m5",fixtureM,fixtureMA))
   { Print("V4_FIXTURE_READ_FAILED"); return; }
   ulong t=GetTickCount64();
   long digest=RunStream(true,false,ArraySize(fixtureM),"v4_fixture\\compat_stream.csv");
   long compatPublished=g_v4Published;
   Print("V4_COMPAT_STREAM ",compatPublished," elapsed_ms ",GetTickCount64()-t);
   RunStream(true,true,ArraySize(fixtureM),"v4_fixture\\compat_idle.csv");
   long compatIdle=g_v4Published;
   Print("V4_COMPAT_IDLE ",compatIdle," elapsed_ms ",GetTickCount64()-t);
   g_v4CandidatesFile=FileOpen("v4_fixture\\v4_candidates.csv",FILE_WRITE|FILE_CSV|FILE_ANSI,',');
   V4Header(g_v4CandidatesFile);
   g_v4GuardFile=FileOpen("v4_fixture\\guard_rejects.csv",FILE_WRITE|FILE_CSV|FILE_ANSI,','); V4Header(g_v4GuardFile);
   RunStream(false,false,ArraySize(fixtureM),"v4_fixture\\v4_stream.csv");
   FileClose(g_v4GuardFile); g_v4GuardFile=INVALID_HANDLE;
   FileClose(g_v4CandidatesFile); g_v4CandidatesFile=INVALID_HANDLE;
   long candidates=g_v4Candidates,published=g_v4Published,blocked=g_v4Blocked;
   Check(candidates==published+blocked,"F5_candidate_accounting");
   int result=FileOpen("v4_fixture\\core_result.json",FILE_WRITE|FILE_TXT|FILE_ANSI);
   FileWriteString(result,StringFormat("{\"checks\":%d,\"failures\":%d,\"compat_stream\":%I64d,\"compat_idle\":%I64d,\"candidates\":%I64d,\"published\":%I64d,\"blocked\":%I64d,\"guard_candidates\":%I64d,\"guard_rejected\":%I64d,\"elapsed_ms\":%I64d}",checks,failures,compatPublished,compatIdle,candidates,published,blocked,g_v4GuardCandidates,g_v4GuardRejected,GetTickCount64()-t));
   FileClose(result); Print("V4_CORE_DONE");
}
