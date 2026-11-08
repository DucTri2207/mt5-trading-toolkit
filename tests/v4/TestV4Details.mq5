#define OnStart CoreOnStart
#include "TestV4Core.mq5"
#undef OnStart
bool SameZone(const SZone &a,const SZone &b)
{
   return a.timeStart==b.timeStart && a.isSupply==b.isSupply &&
      MathRound(a.distal/V4Point())==MathRound(b.distal/V4Point()) &&
      MathRound(a.proximal/V4Point())==MathRound(b.proximal/V4Point());
}
void SetFrame(int m)
{
   fixtureM0=m; g_v4Now=fixtureM[m].time; fixtureHL=-1;
   fixtureVisibleM=ArraySize(fixtureM); fixtureVisibleH=ArraySize(fixtureH);
   while(fixtureHL+1<ArraySize(fixtureH) && fixtureH[fixtureHL+1].time+3600<=g_v4Now) fixtureHL++;
}
bool FindSource(long id)
{
   for(int i=0;i<ArraySize(g_v4History);i++) if(g_v4History[i].source_zone_id==id) return true;
   return false;
}
void OnStart()
{
   Configure(); InpCompatV301=false;
   FileDelete("v4_fixture\\unit_checks.csv"); UnitChecks();
   if(!ReadFixture("h1",fixtureH,fixtureHA)||!ReadFixture("m5",fixtureM,fixtureMA)) return;
   int zfile=FileOpen("v4_fixture\\zone_identity.csv",FILE_WRITE|FILE_CSV|FILE_ANSI,',');
   FileWrite(zfile,"frame","window_a","window_b","zone_start","supply","distal","proximal","id_a","id_b","matched");
   int matches=0,collisions=0,flips=0;
   for(int trial=1;trial<=30;trial++)
   {
      SetFrame(30+(ArraySize(fixtureM)-31)*trial/31); MaxHistory=2000; CZoneEngine::Scan();
      SZone full[]; ArrayResize(full,ArraySize(g_zones));
      for(int i=0;i<ArraySize(full);i++) full[i]=g_zones[i];
      CZoneEngine::Scan();
      Check(ArraySize(full)==ArraySize(g_zones),"F3_repeat_count");
      for(int i=0;i<ArraySize(full);i++) Check(full[i].id==g_zones[i].id,"F3_repeat_real_zone");
      MaxHistory=1000; CZoneEngine::Scan();
      for(int j=0;j<ArraySize(g_zones);j++)
      {
         if(g_zones[j].isFlip) flips++;
         for(int i=0;i<ArraySize(full);i++)
         {
            if(full[i].id==g_zones[j].id && !SameZone(full[i],g_zones[j])) collisions++;
            if(SameZone(full[i],g_zones[j]))
            {
               bool ok=(full[i].id==g_zones[j].id); Check(ok,"F3_two_start_windows");matches++;
               FileWrite(zfile,trial,2000,1000,(long)full[i].timeStart,(int)full[i].isSupply,DoubleToString(full[i].distal,12),DoubleToString(full[i].proximal,12),full[i].id,g_zones[j].id,ok?"PASS":"FAIL");
            }
         }
      }
   }
   FileClose(zfile); Check(matches>100 && collisions==0,"F3_real_identity_and_collisions");
   Check(flips>0,"F2_real_flip_records_present"); MaxHistory=3000;
   double originalMin=MinRR;
   int rrfile=FileOpen("v4_fixture\\rr_modes.csv",FILE_WRITE|FILE_CSV|FILE_ANSI,',');
   FileWrite(rrfile,"tp_mode","signal_id","risk","rr1","offset_points","min_rr","eligible","expected");
   for(int mode=0;mode<=2;mode++)
   {
      InpTpMode=(ENUM_TP_MODE)mode; MinRR=originalMin;
      // Find a genuine first eligible signal independently for each target mode.
      ResetFixtureState(); g_v4LastEvaluated=0; ArrayResize(g_v4History,0);
      fixtureHL=-1; fixtureVisibleM=ArraySize(fixtureM); fixtureVisibleH=ArraySize(fixtureH);
      int m=30;
      for(;m<ArraySize(fixtureM);m++)
      {
         fixtureM0=m;g_v4Now=fixtureM[m].time;int old=fixtureHL;
         while(fixtureHL+1<ArraySize(fixtureH)&&fixtureH[fixtureHL+1].time+3600<=g_v4Now) fixtureHL++;
         if(old!=fixtureHL||ArraySize(g_zones)==0) CZoneEngine::Scan();
         CSignalEngine::Detect(true);
         if(ArraySize(g_v4History)>0) break;
      }
      Check(ArraySize(g_v4History)>0,"F4_real_signal_for_mode");
      if(ArraySize(g_v4History)==0) continue;
      SConfirmSignal s=g_v4History[0]; double risk=MathAbs(s.entry-s.initialSl);
      for(int offset=-1;offset<=1;offset++)
      {
         ResetFixtureState();g_v4LastEvaluated=0;ArrayResize(g_v4History,0);SetFrame(m);CZoneEngine::Scan();
         MinRR=s.rr1+offset*V4Point()/risk; CSignalEngine::Detect(true);
         bool eligible=FindSource(s.source_zone_id),expected=(offset<=0);
         Check(eligible==expected,"F4_detector_mode_point_boundary");
         FileWrite(rrfile,mode,s.signal_id,DoubleToString(risk,12),DoubleToString(s.rr1,12),offset,DoubleToString(MinRR,12),eligible,expected);
      }
   }
   MinRR=originalMin;FileClose(rrfile);
   int f=FileOpen("v4_fixture\\details_result.json",FILE_WRITE|FILE_TXT|FILE_ANSI);
   FileWriteString(f,StringFormat("{\"checks\":%d,\"failures\":%d,\"real_zone_matches\":%d,\"collisions\":%d,\"flip_records\":%d,\"rr_modes\":3}",checks,failures,matches,collisions,flips));FileClose(f);
   Print("V4_DETAILS_DONE ",checks," ",failures);
}
