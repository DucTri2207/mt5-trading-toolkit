int g_v4SweepTraceFile=INVALID_HANDLE;
bool g_v4SelectedFrame=false;
int g_v4RrTraceFile=INVALID_HANDLE;
#define OnStart CoreOnStart
#include "TestV4TraceCore.mqh"
#undef OnStart
void OnStart()
{
   Configure(); InpCompatV301=true; g_v4Preset=V4Preset();
   if(!ReadFixture("h1",fixtureH,fixtureHA)||!ReadFixture("m5",fixtureM,fixtureMA)) return;
   ResetFixtureState();g_v4LastEvaluated=0;ArrayResize(g_v4History,0);
   fixtureHL=-1;fixtureVisibleM=ArraySize(fixtureM);fixtureVisibleH=ArraySize(fixtureH);
   int f=FileOpen("v4_fixture\\compat_zone_trace.csv",FILE_WRITE|FILE_CSV|FILE_ANSI,',');
   FileWrite(f,"confirm_bar_open","direction","compat_zone_id","stable_zone_id","source_present_v4","zone_start","distal","proximal","zone_known_time","time_invalid","broken","zone_type","zone_score");
   datetime observed[]; int n=0;
   int frameFile=FileOpen("v4_fixture\\diff_observation_times.csv",FILE_READ|FILE_CSV|FILE_ANSI,',');
   while(frameFile!=INVALID_HANDLE && !FileIsEnding(frameFile))
   { datetime stamp=(datetime)FileReadNumber(frameFile); if(stamp>0){ArrayResize(observed,n+1);observed[n++]=stamp;} }
   if(frameFile!=INVALID_HANDLE)FileClose(frameFile);
   int pointer=0,plan=FileOpen("v4_fixture\\compat_plan_trace.csv",FILE_WRITE|FILE_CSV|FILE_ANSI,',');
   FileWrite(plan,"observation_time","active_before_detect","compat_publication_on_bar","last_signal_time","last_signal_zone");
   g_v4RrTraceFile=FileOpen("v4_fixture\\compat_rr_rejections.csv",FILE_WRITE|FILE_CSV|FILE_ANSI,',');
   FileWrite(g_v4RrTraceFile,"confirm_bar_open","direction","stable_zone_id","rr1","rr2","min_rr","epsilon_allows");
   g_v4SweepTraceFile=FileOpen("v4_fixture\\compat_sweep_trace.csv",FILE_WRITE|FILE_CSV|FILE_ANSI,',');
   FileWrite(g_v4SweepTraceFile,"observation_time","stable_zone_id","zone_known_time","selected_sweep_open","confirm_bar_index","sweep_before_known");
   int count=0;
   for(int m=30;m<ArraySize(fixtureM);m++)
   {
      fixtureM0=m;g_v4Now=fixtureM[m].time;int old=fixtureHL;
      while(fixtureHL+1<ArraySize(fixtureH)&&fixtureH[fixtureHL+1].time+3600<=g_v4Now)fixtureHL++;
      if(old!=fixtureHL||ArraySize(g_zones)==0)CZoneEngine::Scan();
      while(pointer<n && observed[pointer]<g_v4Now)pointer++;
      g_v4SelectedFrame=pointer<n && observed[pointer]==g_v4Now;
      bool wasActive=g_lastSignal.active;
      long pub=g_v4Published;CSignalEngine::Detect(true);
      while(pointer<n && observed[pointer]<g_v4Now)pointer++;
      if(pointer<n && observed[pointer]==g_v4Now)
         FileWrite(plan,(long)g_v4Now,wasActive,g_v4Published>pub,(long)g_lastSignal.time,g_lastSignal.zoneId);
      if(g_v4Published>pub)
      {
         SConfirmSignal sig=g_v4History[ArraySize(g_v4History)-1];SZone source;ZeroMemory(source);
         for(int z=0;z<ArraySize(g_zones);z++)if(g_zones[z].id==sig.zoneId){source=g_zones[z];break;}
         SZone saved[];ArrayCopy(saved,g_zones);
         InpCompatV301=false;CZoneEngine::Scan();
         bool found=false;SZone v4;ZeroMemory(v4);
         for(int z=0;z<ArraySize(g_zones);z++)
            if(g_zones[z].timeStart==source.timeStart && g_zones[z].isSupply==source.isSupply &&
               MathRound(g_zones[z].distal/V4Point())==MathRound(source.distal/V4Point()) &&
               MathRound(g_zones[z].proximal/V4Point())==MathRound(source.proximal/V4Point())){v4=g_zones[z];found=true;break;}
         FileWrite(f,(long)sig.time,sig.isBuy?1:-1,sig.zoneId,
            V4ZoneId(source.timeStart,source.isSupply,source.distal,source.proximal),found,
            (long)source.timeStart,DoubleToString(source.distal,10),DoubleToString(source.proximal,10),
            (long)v4.timeKnown,(long)v4.timeInvalid,(int)v4.isBroken,(int)v4.type,v4.score);
         ArrayCopy(g_zones,saved);ArrayResize(g_zones,ArraySize(saved));InpCompatV301=true;count++;
      }
      ManageActiveSignal(fixtureM[m].open+(g_lastSignal.isBuy?0:.2));
   }
   FileClose(g_v4SweepTraceFile);
   FileClose(g_v4RrTraceFile);
   FileClose(plan);FileClose(f);Print("V4_DIFF_TRACE_DONE ",count);
}
