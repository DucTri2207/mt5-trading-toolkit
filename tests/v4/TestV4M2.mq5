#define OnStart V4M1UnusedOnStart
#include "TestV4Core.mq5"
#undef OnStart
#include <CanHoTroV4/Risk.mqh>
#include <CanHoTroV4/Scorecard.mqh>
#include <CanHoTroV4/Journal.mqh>

SV4SymbolSpec GoldSpec()
{
   SV4SymbolSpec s; s.tickSize=.01; s.tickValue=1; s.point=.01; s.minLot=.01; s.maxLot=100; s.step=.01; return s;
}
void M2Units()
{
   SV4SymbolSpec s=GoldSpec();
   Check(MathAbs(V4Lots(100000,.5,5,s)-1)<1e-9,"lot_gold");
   s.tickSize=.00001; s.tickValue=1; s.point=.00001;
   Check(MathAbs(V4Lots(100000,.5,.002,s)-2.5)<1e-9,"lot_fx");
   s.tickSize=.25; s.tickValue=12.5; s.point=.25; s.step=.1; s.minLot=.1; s.maxLot=5;
   Check(MathAbs(V4Lots(100000,.5,5,s)-2)<1e-9,"lot_index");
   Check(MathAbs(V4Lots(100000,.5,5.3,s)-1.8)<1e-9,"lot_floor");
   Check(V4Lots(100000,.5,.1,s)==5,"lot_max_clamp");
   Check(V4Lots(100,.1,100,s)==.1,"lot_min_clamp_report_actual_risk");
   Check(V4Lots(100000,.5,0,s)==0,"lot_zero_sl");
   s=GoldSpec(); Check(MathAbs(V4CostR(5,.3,1,7,s)-.078)<1e-9,"cost_once_039_price");
   Check(V4ResetDay(90000,60)==90000,"reset_exact");
   Check(V4ResetDay(89999,60)==3600,"reset_before");
   SV4Limits limit; V4ComputeLimits(100000,102000,98000,5,10,limit);
   Check(limit.ready && limit.dailyRemaining==1000 && limit.totalRemaining==8000 && !limit.hit,"limits_equity_includes_floating_loss");
   V4ComputeLimits(100000,102000,97000,5,10,limit); Check(limit.hit && limit.dailyRemaining==0,"limits_at_daily_boundary");
   V4ComputeLimits(0,102000,97000,5,10,limit); Check(!limit.ready,"limits_missing_initial_unknown");
   SConfirmSignal sig; ZeroMemory(sig); sig.signal_id="unit"; sig.signal_known_time=600; sig.publish_time=600;
   sig.isBuy=true; sig.initialSl=95;
   SV4VirtualTrade v; V4NewVirtual(sig,"HIST",v);
   Check(!V4VirtualFill(v,599,100,100.3,.01,7,s),"no_fill_before_known");
   Check(V4VirtualFill(v,600,100,100.3,.01,7,s),"ask_buy_entry");
   Check(MathAbs(v.entry-100.31)<1e-9,"entry_slip_once");
   V4VirtualClose(v,600,100,.01,"UNIT");
   Check(MathAbs(v.netR-(-.39/5.31))<1e-9,"net_spread_slip_commission_once");
   Check(MathAbs(v.grossR)<1e-9,"gross_zero_flat_bid_path");
   sig.isBuy=false; sig.initialSl=105; V4NewVirtual(sig,"HIST",v); V4VirtualFill(v,600,100,100.3,.01,7,s);
   V4VirtualClose(v,601,100.3,.01,"UNIT");
   Check(MathAbs(v.entry-99.99)<1e-9 && MathAbs(v.netR+.39/5.01)<1e-9,"sell_bid_entry_ask_exit");
   sig.isBuy=true; sig.initialSl=95; V4NewVirtual(sig,"HIST",v); V4VirtualFill(v,600,100,100,0,0,s);
   MqlRates b; ZeroMemory(b); b.time=600; b.open=100; b.high=106; b.low=94; b.close=102;
   V4VirtualBar(v,b,0,0,EXIT_1R);
   Check(v.closed && v.netR==-1 && v.ambiguous,"ambiguous_SL_first");
   V4NewVirtual(sig,"HIST",v); V4VirtualFill(v,600,100,100,0,0,s);
   b.time=540; V4VirtualBar(v,b,0,0,EXIT_1R); Check(!v.closed,"ignore_prefill_bar");
   b.time=600; b.low=99; b.high=106; V4VirtualBar(v,b,0,0,EXIT_TRAIL_1R);
   Check(!v.closed && v.stop==101,"trail_after_one_R");
   b.time=660; b.open=102; b.low=100; b.high=103; V4VirtualBar(v,b,0,0,EXIT_TRAIL_1R);
   Check(v.closed && MathAbs(v.netR-.2)<1e-9,"trail_exit_conservative_next_bar");
   V4NewVirtual(sig,"HIST",v); V4VirtualFill(v,600,100,100,0,0,s);
   b.time=15000; b.open=102; b.low=1; b.high=200; V4VirtualBar(v,b,0,0,EXIT_1R);
   Check(v.reason=="TIMEOUT_GAP" && MathAbs(v.netR-.4)<1e-9,"clock_gap_no_post_deadline_high_low");
   MqlRates bars[]; ArrayResize(bars,2); bars[0]=b; bars[0].time=540; bars[1]=b; bars[1].time=15000;
   V4NewVirtual(sig,"HIST",v); V4HistEvaluate(v,bars,s,EXIT_1R,0,0,0);
   Check(!v.filled && v.reason=="EXPIRED_NO_QUOTE","expired_no_quote");
   MqlTick t; ZeroMemory(t); t.time=600; t.bid=106; t.ask=106.3;
   V4NewVirtual(sig,"LIVE",v); V4VirtualFill(v,600,100,100,0,0,s); V4VirtualTick(v,t,0,EXIT_1R);
   Check(v.closed && v.netR==1.2,"live_real_quote_exit");
   V4NewVirtual(sig,"LIVE",v); V4VirtualFill(v,600,100,100,0,0,s);
   t.bid=0; V4VirtualTick(v,t,0,EXIT_1R); Check(!v.closed,"live_reject_empty_quote");
   t.bid=106; V4VirtualTick(v,t,0,EXIT_1R);
   SV4VirtualTrade rows[]; ArrayResize(rows,2); rows[0]=v; rows[1]=v;
   rows[0].netR=1; rows[0].grossR=1.1; rows[0].costR=.1;
   rows[1].netR=-.5; rows[1].grossR=-.3; rows[1].costR=.2;
   SV4Stats a; V4Statistics(rows,"LIVE",a);
   Check(a.signals==2 && a.wins==1 && a.net==.5 && a.profit/a.loss==2 && MathAbs(a.medianCost-.15)<1e-9,"stats_PF_R_median");
   V4Statistics(rows,"HIST",a); Check(a.signals==0,"sources_never_mix");
   SV4Deal d; ZeroMemory(d); d.position=1; d.time=600; d.side=1; d.entry=DEAL_ENTRY_IN;
   d.volume=1; d.price=100; d.sl=95; d.commission=-2;
   SV4JournalTrade jp[]; Check(V4JournalApply(jp,d,s),"journal_entry");
   d.side=-1; d.entry=DEAL_ENTRY_OUT; d.volume=.4; d.price=103; d.profit=120; d.commission=-1;
   Check(V4JournalApply(jp,d,s) && MathAbs(jp[0].remaining-.6)<1e-9,"journal_partial_close");
   d.volume=.6; d.profit=-30; d.commission=-1; d.swap=-3; d.fee=-1;
   V4JournalApply(jp,d,s);
   Check(MathAbs(jp[0].netUSD-82)<1e-9 && jp[0].partialCloses==2 && jp[0].riskUSD==500,"journal_net_all_costs_and_R");
   ArrayResize(jp,0); d.entry=DEAL_ENTRY_IN; d.side=1; d.volume=1; d.sl=0; d.profit=0;
   V4JournalApply(jp,d,s); Check(!jp[0].riskKnown,"journal_missing_SL_unknown_R");
   d.entry=DEAL_ENTRY_INOUT; d.side=-1; d.volume=2; d.sl=108; d.price=103; d.profit=30; d.swap=0; d.commission=-4; d.fee=0;
   Check(V4JournalApply(jp,d,s) && ArraySize(jp)==2 && jp[0].remaining==0 && jp[1].remaining==1,"journal_netting_reversal");
   SConfirmSignal signals[]; ArrayResize(signals,1); signals[0]=sig; signals[0].source_zone_id=42;
   signals[0].source_distal=95; signals[0].source_proximal=99;
   SV4JournalTrade p; ZeroMemory(p); p.side=1; p.entryTime=600; p.entered=1; p.entryValue=100;
   V4JournalMatch(p,signals,30); Check(p.label=="THEO_TIN_HIEU" && p.zone==42 && p.zoneDistance==1,"journal_same_direction_match");
   p.side=-1; V4JournalMatch(p,signals,30); Check(p.label=="NGUOC_TIN_HIEU","journal_opposite");
   p.entryTime=2401; V4JournalMatch(p,signals,30); Check(p.label=="TU_VAO","journal_outside_window");
   p.entryTime=599; V4JournalMatch(p,signals,30); Check(p.label=="TU_VAO","journal_no_future_signal");
   FolderCreate(InpV4LedgerFolder); g_v4Preset="M2_UNIT_PERSISTENCE";
   Check(V4ScoreInit(),"score_init_empty");
   ArrayResize(g_v4Score,2); g_v4Score[0]=rows[0]; g_v4Score[1]=rows[1];
   g_v4Score[0].id="closed"; g_v4Score[1].id="active"; g_v4Score[1].closed=false;
   Check(V4ScoreSave(),"score_atomic_save");
   Check(V4ScoreInit() && ArraySize(g_v4Score)==2 && g_v4Score[0].netR==1 && g_v4Score[1].reason=="LIVE_GAP","score_reload_preserves_closed_excludes_live_gap");
   Check(V4ScoreExport(),"score_export_groups");
   FileDelete(g_v4ScorePath); FileDelete(g_v4ScorePath+".groups.csv");
}
void LegacyParity()
{
   MqlRates bars[]; double unused[]; if(!ReadFixture("m1",bars,unused)) { Check(false,"read_m1"); return; }
   SV4SymbolSpec spec=GoldSpec();
   int signalFile=FileOpen("v4_fixture\\probe_signals.csv",FILE_READ|FILE_CSV|FILE_ANSI,',');
   int out=FileOpen("v4_fixture\\legacy_native.csv",FILE_WRITE|FILE_CSV|FILE_ANSI,',');
   FileWrite(out,"id","known","side","risk","tp1_R","trail_R","valid");
   while(!FileIsEnding(signalFile))
   {
      string id=FileReadString(signalFile); if(id=="") break;
      SConfirmSignal s; ZeroMemory(s); s.signal_id=id; s.signal_known_time=(datetime)FileReadNumber(signalFile);
      s.isBuy=FileReadNumber(signalFile)>0; s.initialSl=FileReadNumber(signalFile);
      SV4VirtualTrade a,b; V4NewVirtual(s,"LEGACY",a); V4NewVirtual(s,"LEGACY",b);
      V4HistEvaluate(a,bars,spec,EXIT_1R,0,0,0,true); V4HistEvaluate(b,bars,spec,EXIT_TRAIL_1R,0,0,0,true);
      FileWrite(out,id,(long)a.known,s.isBuy?1:-1,a.risk,a.netR,b.netR,(int)(a.filled && a.closed));
   }
   FileClose(signalFile); FileClose(out);
   // Measure production V4 and capture region age/tests at observation, without changing detector behavior.
   Configure(); ReadFixture("h1",fixtureH,fixtureHA); ReadFixture("m5",fixtureM,fixtureMA);
   ResetFixtureState(); fixtureHL=-1; fixtureVisibleM=ArraySize(fixtureM); fixtureVisibleH=ArraySize(fixtureH);
   g_v4Published=0; g_v4LastEvaluated=0; ArrayResize(g_v4History,0); InpCompatV301=false; g_v4Preset=V4Preset();
   int exposure=FileOpen("v4_fixture\\normal_zone_exposure.csv",FILE_WRITE|FILE_CSV|FILE_ANSI,',');
   FileWrite(exposure,"signal_id","known","observed","zone_id","zone_type","test_count","age_bars","max_tests","max_age","over_tests","over_age");
   for(int m=30;m<fixtureVisibleM;m++)
   {
      fixtureM0=m; g_v4Now=fixtureM[m].time; int old=fixtureHL;
      while(fixtureHL+1<fixtureVisibleH && fixtureH[fixtureHL+1].time+3600<=g_v4Now) fixtureHL++;
      if(old!=fixtureHL || ArraySize(g_zones)==0) CZoneEngine::Scan();
      long prior=g_v4Published; CSignalEngine::Detect(true);
      if(g_v4Published>prior)
      {
         SConfirmSignal s=g_v4History[ArraySize(g_v4History)-1];
         // For delayed publication, measure the H1 prefix at signal_known_time itself.
         SZone observedZones[]; ArrayCopy(observedZones,g_zones); int observedHL=fixtureHL;
         if(s.signal_known_time<g_v4Now)
         {
            fixtureHL=-1;
            while(fixtureHL+1<fixtureVisibleH && fixtureH[fixtureHL+1].time+3600<=s.signal_known_time) fixtureHL++;
            g_v4Now=s.signal_known_time; CZoneEngine::Scan();
         }
         for(int z=0;z<ArraySize(g_zones);z++) if(g_zones[z].id==s.source_zone_id && !g_zones[z].isFlip)
            FileWrite(exposure,s.signal_id,(long)s.signal_known_time,(long)fixtureM[m].time,s.source_zone_id,s.zoneType,g_zones[z].testCount,g_zones[z].ageBars,
               MaxTests,MaxAgeBars,(int)(g_zones[z].testCount>=MaxTests),(int)(g_zones[z].ageBars>MaxAgeBars));
         ArrayCopy(g_zones,observedZones); fixtureHL=observedHL; g_v4Now=fixtureM[m].time;
      }
      ManageActiveSignal(fixtureM[m].open+(g_lastSignal.isBuy?0:.2));
   }
   FileClose(exposure); Check(g_v4Published==1393,"M1_publications_unchanged");
   out=FileOpen("v4_fixture\\scorecard_hist.csv",FILE_WRITE|FILE_CSV|FILE_ANSI,',');
   V4ScoreHeader(out); ArrayResize(g_v4Score,0);
   for(int i=0;i<ArraySize(g_v4History);i++)
   {
      for(int rule=0;rule<2;rule++)
      {
         SV4VirtualTrade v; V4NewVirtual(g_v4History[i],"HIST",v);
         V4HistEvaluate(v,bars,spec,(ENUM_V4_EXIT)rule,.3,.01,7); v.id+="_"+(string)rule;
         V4ScoreWrite(out,v); int n=ArraySize(g_v4Score); ArrayResize(g_v4Score,n+1); g_v4Score[n]=v;
         if(v.filled) Check(v.fill>=v.known && (!v.closed || v.exit>=v.fill),"score_time_order");
      }
   }
   FileClose(out);
}
void RecoveredFixture()
{
   int f=FileOpen("v4_fixture\\recovered.csv",FILE_READ|FILE_CSV|FILE_ANSI,',');
   int out=FileOpen("v4_fixture\\journal_recovered.csv",FILE_WRITE|FILE_CSV|FILE_ANSI,',');
   FileWrite(out,"position_id","expected_gross_USD","native_USD","error","R_status","provenance");
   SV4SymbolSpec s=GoldSpec();
   while(!FileIsEnding(f))
   {
      string id=FileReadString(f); if(id=="") break;
      SV4Deal d; ZeroMemory(d); d.position=StringToInteger(id); d.side=(int)FileReadNumber(f);
      d.time=(datetime)FileReadNumber(f); datetime end=(datetime)FileReadNumber(f);
      d.price=FileReadNumber(f); double exit=FileReadNumber(f); d.volume=FileReadNumber(f); double profit=FileReadNumber(f);
      d.entry=DEAL_ENTRY_IN; SV4JournalTrade p[]; V4JournalApply(p,d,s);
      d.profit=(exit-d.price)*d.side*d.volume*s.tickValue/s.tickSize;
      d.side=-d.side; d.time=end; d.price=exit; d.entry=DEAL_ENTRY_OUT;
      V4JournalApply(p,d,s);
      FileWrite(out,id,profit,p[0].netUSD,p[0].netUSD-profit,"UNKNOWN_INITIAL_SL","RECOVERED_PRICES_ASSUMED_CONTRACT_100_NO_FEES");
      Check(MathAbs(p[0].netUSD-profit)<1e-8 && !p[0].riskKnown,"recovered_accounting_only");
   }
   FileClose(f); FileClose(out);
}
#ifndef CHT_M2_UNITS_ONLY
void OnStart()
{
   FileDelete("v4_fixture\\unit_checks.csv"); M2Units(); LegacyParity(); RecoveredFixture();
   // Exercise the real read-only account API, even when this isolated demo has no XAUUSD deals.
   bool history=HistorySelect(0,TimeCurrent());
   int f=FileOpen("v4_fixture\\m2_result.json",FILE_WRITE|FILE_TXT|FILE_ANSI);
   FileWriteString(f,StringFormat("{\"checks\":%d,\"failures\":%d,\"published\":%d,\"history_selected\":%s,\"demo_deals\":%d}",
      checks,failures,(int)g_v4Published,history?"true":"false",HistoryDealsTotal())); FileClose(f);
   PrintFormat("V4_M2_DONE checks=%d failures=%d",checks,failures);
}
#endif
