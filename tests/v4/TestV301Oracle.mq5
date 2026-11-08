#property strict
#include "OracleV301.mqh"
#include "FixtureData.mqh"
#include "OracleFunctions.mqh"
#include "PlanStateV301.mqh"
#undef CopyRates
#undef CopyBuffer
#undef SymbolInfoTick
#undef SymbolInfoDouble

void Configure()
{
   FilterKillzones=false; InpTpMode=TP_MODE_RR; InpEntryMode=ENTRY_MARKET_CONFIRM;
   AlertConfirm=false; ShowTradeLines=false; ShowArrows=false; UseReferenceLevels=false;
   AlertPopup=false; AlertPush=false; AlertSoundOn=false; TgEnable=false; AlertBeTriggered=false;
}
int RunOracle(bool idle,string output)
{
   ResetFixtureState(); fixtureHL=-1;
   fixtureVisibleM=ArraySize(fixtureM); fixtureVisibleH=ArraySize(fixtureH);
   int count=0,f=FileOpen(output,FILE_WRITE|FILE_CSV|FILE_ANSI,',');
   FileWrite(f,"confirm_bar_open","signal_known_time","publish_time","direction","entry","sl",
      "tp1","tp2","source_zone_id","zone_start","zone_type","distal","proximal");
   for(int m=30;m<ArraySize(fixtureM);m++)
   {
      fixtureM0=m; int old=fixtureHL;
      while(fixtureHL+1<ArraySize(fixtureH) && fixtureH[fixtureHL+1].time+3600<=fixtureM[m].time) fixtureHL++;
      if(old!=fixtureHL || ArraySize(g_zones)==0) ScanHtfMacroZones();
      if(idle) { ZeroMemory(g_lastSignal); g_lastSignalSeenTime=0; g_lastSignalSeenZone=-1; }
      datetime prior=g_lastSignalSeenTime; long zone=g_lastSignalSeenZone;
      DetectLtfConfirmation(true);
      if(g_lastSignalSeenTime!=prior || g_lastSignalSeenZone!=zone)
      {
         SConfirmSignal s=g_lastSignal; SZone z; ZeroMemory(z);
         for(int j=0;j<ArraySize(g_zones);j++) if(g_zones[j].id==s.zoneId) { z=g_zones[j]; break; }
         FileWrite(f,(long)s.time,(long)(s.time+300),(long)fixtureM[m].time,s.isBuy?1:-1,
            DoubleToString(s.entry,10),DoubleToString(s.initialSl,10),DoubleToString(s.tp1,10),
            DoubleToString(s.tp2,10),s.zoneId,(long)z.timeStart,s.zoneType,
            DoubleToString(z.distal,10),DoubleToString(z.proximal,10)); count++;
      }
      ManageActiveSignal(fixtureM[m].open+(g_lastSignal.isBuy?0:.2));
   }
   FileClose(f); return count;
}
void OnStart()
{
   Configure();
   if(!ReadFixture("h1",fixtureH,fixtureHA)||!ReadFixture("m5",fixtureM,fixtureMA)) return;
   int stream=RunOracle(false,"v4_fixture\\oracle_stream.csv");
   int idle=RunOracle(true,"v4_fixture\\oracle_idle.csv");
   int f=FileOpen("v4_fixture\\oracle_result.json",FILE_WRITE|FILE_TXT|FILE_ANSI);
   FileWriteString(f,StringFormat("{\"stream\":%d,\"idle\":%d}",stream,idle)); FileClose(f);
   Print("V301_ORACLE_DONE ",stream," ",idle);
}
