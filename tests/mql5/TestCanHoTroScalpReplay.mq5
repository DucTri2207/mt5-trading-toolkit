#property strict
#include "../../Include/CanHoTroScalpDetector.mqh"
#include "../../Include/CanHoTroScalpPlan.mqh"
#include "../../Include/CanHoTroScalpState.mqh"
#include "../../Include/CanHoTroScalpLegacy.mqh"

const string CHT_FOLDER="can_ho_tro_scalp_v1\\";
MqlRates allH1[],allM5[],allD1[],allM1[];
CHTCandidate allCandidates[];
CHTPivot allHighs[],allLows[];
double atrH1[],atrM5[],maH1[];
int failures=0,checks=0;

void Check(const bool ok,const string label)
{
   checks++;if(!ok){failures++;Print("FAIL ",label);}
}
bool ReadRates(const string name,MqlRates &out[])
{
   int f=FileOpen(CHT_FOLDER+name+".csv",FILE_READ|FILE_CSV|FILE_ANSI,',');
   if(f==INVALID_HANDLE)return false;
   int n=0;
   while(!FileIsEnding(f))
   {
      string stamp=FileReadString(f);if(stamp=="")break;
      ArrayResize(out,n+1,65536);ZeroMemory(out[n]);
      out[n].time=(datetime)StringToInteger(stamp);out[n].open=FileReadNumber(f);
      out[n].high=FileReadNumber(f);out[n].low=FileReadNumber(f);out[n].close=FileReadNumber(f);
      out[n].tick_volume=1;n++;
   }
   FileClose(f);ArraySetAsSeries(out,false);return n>0;
}
void Progress(const string state,const int count)
{
   int f=FileOpen(CHT_FOLDER+"progress.json",FILE_WRITE|FILE_TXT|FILE_ANSI);
   FileWriteString(f,StringFormat("{\"state\":\"%s\",\"count\":%d}",state,count));FileClose(f);
}
void NativeProbe(const string name,const MqlRates &source[],const int limit,const bool probeMA)
{
   int n=MathMin(limit,ArraySize(source));MqlRates rates[];ArrayResize(rates,n);
   ArrayCopy(rates,source,0,ArraySize(source)-n,n);
   if(!SymbolInfoInteger(name,SYMBOL_EXIST))Check(CustomSymbolCreate(name,"DucTriLab"),"create native probe symbol");
   CustomSymbolSetInteger(name,SYMBOL_DIGITS,2);CustomSymbolSetDouble(name,SYMBOL_POINT,.01);
   CustomSymbolSetInteger(name,SYMBOL_TRADE_MODE,SYMBOL_TRADE_MODE_DISABLED);
   SymbolSelect(name,true);CustomRatesDelete(name,0,D'2030.01.01');
   Check(CustomRatesUpdate(name,rates)==n,"native probe rates update");
   int ah=iATR(name,PERIOD_M1,14),mh=INVALID_HANDLE;
   if(probeMA)mh=iMA(name,PERIOD_M1,50,0,MODE_EMA,PRICE_CLOSE);
   double aa[],mm[];int copied=-1,mcopied=-1;
   for(int attempt=0;attempt<200;attempt++)
   {
      copied=CopyBuffer(ah,0,0,n,aa);
      if(probeMA)mcopied=CopyBuffer(mh,0,0,n,mm);
      if(copied==n && (!probeMA || mcopied==n))break;
      Sleep(50);
   }
   Check(copied==n,"native ATR buffer complete");
   if(probeMA)Check(mcopied==n,"native EMA buffer complete");
   int f=FileOpen(CHT_FOLDER+name+"_native.csv",FILE_WRITE|FILE_CSV|FILE_ANSI,',');
   if(copied==n && (!probeMA || mcopied==n))
      for(int i=0;i<n;i++)FileWrite(f,(long)rates[i].time,DoubleToString(aa[i],12),DoubleToString(probeMA?mm[i]:0.,12));
   FileClose(f);IndicatorRelease(ah);if(probeMA)IndicatorRelease(mh);
}
void ExportRaw()
{
   CHTATR(allH1,atrH1);CHTATR(allM5,atrM5);CHTEMA(allH1,maH1);
   int cf=FileOpen(CHT_FOLDER+"candidates_mql.csv",FILE_WRITE|FILE_TXT|FILE_ANSI);
   int c0f=FileOpen(CHT_FOLDER+"candidates_c0_mql.csv",FILE_WRITE|FILE_TXT|FILE_ANSI);
   int lpf=FileOpen(CHT_FOLDER+"legacy_planned_mql.csv",FILE_WRITE|FILE_TXT|FILE_ANSI);
   int sf=FileOpen(CHT_FOLDER+"snapshots_mql.csv",FILE_WRITE|FILE_CSV|FILE_ANSI,',');
   int hc=0,oldHC=-1,dc=0,rawCount=0;
   double firstSeen[];ArrayResize(firstSeen,ArraySize(allH1)*10);ArrayInitialize(firstSeen,0.);
   CHTZone zones[];
   for(int c=29;c<ArraySize(allM5);c++)
   {
      datetime at=allM5[c].time+300;if(at>D'2026.10.25 00:00')break;
      while(hc<ArraySize(allH1) && allH1[hc].time+3600<=at)hc++;
      if(hc!=oldHC)
      {
         int n=MathMin(hc,2000),off=hc-n;MqlRates window[];double aa[];
         ArrayResize(window,n);ArrayResize(aa,n);ArrayCopy(window,allH1,0,off,n);ArrayCopy(aa,atrH1,0,off,n);
         CHTScanZones(window,aa,zones);
         double scoreSum=0,testSum=0;
         for(int z=0;z<ArraySize(zones);z++)
         {
            int base=CHTLower(allH1,zones[z].baseTime);
            int slot=(base*5+zones[z].baseBars-1)*2+(int)zones[z].isFlip;
            if(firstSeen[slot]==0)firstSeen[slot]=(double)allH1[hc-1].time+3600;
            zones[z].availableAt=(datetime)MathMax((double)zones[z].availableAt,firstSeen[slot]);
            scoreSum+=zones[z].score;testSum+=zones[z].testCount;
         }
         if(at>=D'2021.10.25 00:00')FileWrite(sf,(long)at,hc,ArraySize(zones),DoubleToString(scoreSum,10),DoubleToString(testSum,10));
         oldHC=hc;if(hc%2000==0)Progress("detector",hc);
      }
      while(dc<ArraySize(allD1) && allD1[dc].time+86400<=at)dc++;
      if(at<D'2021.10.25 00:00' || at>=D'2026.10.25 00:00')continue;
      int ti=CHTLower(allH1,allM5[c].time+1)-2;if(ti<0)continue;
      CHTContext ctx;ZeroMemory(ctx);
      ctx.trendTime=allH1[ti].time;ctx.trendClose=allH1[ti].close;
      ctx.trendMa=maH1[ti];ctx.trendAtr=atrH1[ti];ctx.m5Index=c;ctx.h1Count=hc;
      if(dc>0){ctx.dayHigh=allD1[dc-1].high;ctx.dayLow=allD1[dc-1].low;ctx.dayTime=allD1[dc-1].time;}
      MqlRates ltf[];int copied=MathMin(c+2,300);ArrayResize(ltf,copied);ArraySetAsSeries(ltf,true);
      ZeroMemory(ltf[0]);ltf[0].time=at;
      ltf[0].open=(c+1<ArraySize(allM5))?allM5[c+1].open:allM5[c].close;
      ltf[0].high=ltf[0].open;ltf[0].low=ltf[0].open;ltf[0].close=ltf[0].open;
      for(int k=1;k<copied;k++)ltf[k]=allM5[c+1-k];
      CHTCandidate raw[];CHTFindRaw(ltf,atrM5[c],zones,ctx,raw);
      bool planned=false;
      for(int j=0;j<ArraySize(raw);j++)
      {
         string line="";for(int k=0;k<36;k++){if(k>0)line+=",";line+=DoubleToString(raw[j].v[k],10);}
         FileWriteString(cf,line+"\r\n");rawCount++;
         double values[];
         if(!planned && CHTLegacyPlanned(raw[j],zones,ctx,values))
         {
            planned=true;string proposal="";
            for(int k=0;k<10;k++){if(k>0)proposal+=",";proposal+=DoubleToString(values[k],10);}
            FileWriteString(lpf,proposal+"\r\n");
         }
      }
      CHTFindRaw(ltf,atrM5[c],zones,ctx,raw,true);
      for(int j=0;j<ArraySize(raw);j++)
      {
         string line="";for(int k=0;k<36;k++){if(k>0)line+=",";line+=DoubleToString(raw[j].v[k],10);}
         FileWriteString(c0f,line+"\r\n");
         int n=ArraySize(allCandidates);ArrayResize(allCandidates,n+1,4096);allCandidates[n]=raw[j];
      }
   }
   FileClose(cf);FileClose(c0f);FileClose(lpf);FileClose(sf);Progress("detector_complete",rawCount);
}
string IdeaKey(const CHTCandidate &c)
{
   return StringFormat("%I64d|%d|%d|%I64d|%d|%I64d",(long)c.v[3],(int)c.v[4],(int)c.v[5],(long)c.v[6],(int)c.v[2],(long)c.v[13]);
}
void ExportStopEvent(const int f,const int index,const CHTPlan &p,const long before)
{
   if(p.eventSerial==before || p.eventKind<CHT_PROPOSE)return;
   FileWrite(f,index,p.eventKind,(long)p.eventTime,(long)p.eventSequence,
             DoubleToString(p.eventOld,10),DoubleToString(p.eventNew,10),
             (long)p.proposalKnown,(long)p.proposalPTime,(long)p.proposalHTime);
}
void ReplayMarket(const string name,const CHTPolicy policy,const double spread,const double slip,
                  const string cost,const bool room,const bool serial,const bool retest=false,const bool highFirst=false)
{
   string path=retest?(highFirst?"OHLC":"OLHC"):"ADVERSE_FIRST";
   string label=name+"_"+cost+"_"+path+"_"+(serial?"serial":"paired");
   int f=FileOpen(CHT_FOLDER+label+"_trades_mql.csv",FILE_WRITE|FILE_CSV|FILE_ANSI,',');
   int ef=FileOpen(CHT_FOLDER+label+"_stops_mql.csv",FILE_WRITE|FILE_CSV|FILE_ANSI,',');
   datetime chosenAt=0,busyUntil=0;string seen[];int count=0;
   for(int i=0;i<ArraySize(allCandidates);i++)
   {
      CHTCandidate c=allCandidates[i];
      if(CHTPlannedGate(c,.01,retest,room)!=CHT_NONE)continue;
      datetime known=(datetime)c.v[1];if(known==chosenAt)continue;chosenAt=known;
      string key=IdeaKey(c);bool duplicate=false;
      for(int s=0;s<ArraySize(seen);s++)if(seen[s]==key){duplicate=true;break;}
      if(duplicate || (serial && known<busyUntil))continue;
      int n=ArraySize(seen);ArrayResize(seen,n+1);seen[n]=key;
      int entry=CHTLower(allM1,known);CHTPlan p;
      if(entry>=ArraySize(allM1)){ZeroMemory(p);p.candidate=c;p.state=CHT_REJECTED;p.reason=CHT_NO_QUOTE;}
      else
      {
         CHTStart(p,c,policy,spread,slip,.01,room,retest,allM1[entry].time,allM1[entry].open,allM1[entry].open+spread);
         int ci=CHTLower(allM5,allM1[entry].time-299);
         datetime cancelAt=0;
         if(retest)
         {
            int h=CHTLower(allH1,known-3599);
            for(;h<ArraySize(allH1);h++)
            {
               datetime at=allH1[h].time+3600;if(at>known+900)break;
               if((p.buy && allH1[h].close<c.v[10]) || (!p.buy && allH1[h].close>c.v[10])){cancelAt=at;break;}
            }
         }
         for(int j=entry;j<ArraySize(allM1) && (p.state==CHT_PENDING || p.state==CHT_FILLED);j++)
         {
            if(retest){CHTPendingMinute(p,allM1[j],highFirst,cancelAt);continue;}
            long before=p.eventSerial;
            CHTQuote(p,allM1[j].time,allM1[j].open,allM1[j].open+spread);
            ExportStopEvent(ef,i,p,before);if(p.state!=CHT_FILLED)break;
            if(policy==CHT_TS)
               while(ci<ArraySize(allM5) && allM5[ci].time+300<=allM1[j].time)
               {
                  before=p.eventSerial;CHTStructure(p,allM1[j].time,ci,allM5,atrM5,allHighs,allLows);
                  ExportStopEvent(ef,i,p,before);ci++;
               }
            CHTMinuteRange(p,allM1[j]);
         }
      }
      int state=(p.state==CHT_FILLED)?7:(int)p.state;
      if(serial)
      {
         if(state==7)busyUntil=allM1[ArraySize(allM1)-1].time+60;
         else if(p.exitTime>0)busyUntil=p.exitTime;
      }
      FileWrite(f,i,(long)known,(int)p.buy,(long)p.entryTime,DoubleToString(p.entry,10),
                DoubleToString(p.initialStop,10),DoubleToString(p.risk,10),(long)p.exitTime,
                DoubleToString(p.exitPrice,10),state,p.reason,DoubleToString(p.resultR,10),
                DoubleToString(p.mfe,10),DoubleToString(p.mae,10),DoubleToString(p.stop,10),p.ambiguous,
                (long)p.firstHit1,(long)p.firstHit15,(long)p.firstHit2);
      count++;
   }
   FileClose(f);FileClose(ef);Progress(label,count);
}
CHTCandidate PlanFixture(const bool buy=true)
{
   CHTCandidate c;ZeroMemory(c);c.v[0]=28800;c.v[1]=29100;c.v[2]=(double)buy;
   c.v[3]=3600;c.v[4]=1;c.v[13]=27300;c.v[18]=1;c.v[19]=buy?98.:102.;
   c.v[20]=buy?98.25:101.75;c.v[21]=100;c.v[22]=buy?99.:101.;c.v[29]=buy?110.:90.;c.v[30]=c.v[29];return c;
}
void PlanFixtures()
{
   CHTPlan p;CHTCandidate c=PlanFixture();MqlRates bar;ZeroMemory(bar);bar.time=29100;
   CHTStart(p,c,CHT_T05,0,0,.01,false,false,29100,100,100);bar.high=100.1;bar.low=97.9;CHTMinuteRange(p,bar);
   Check(p.reason==CHT_STOP && MathAbs(p.resultR+1)<1e-9,"F01 entry minute stop");
   CHTStart(p,c,CHT_T05,0,0,.01,false,false,29100,100,100);bar.high=101.1;bar.low=99.9;CHTMinuteRange(p,bar);
   Check(p.reason==CHT_TARGET && MathAbs(p.resultR-.5)<1e-9,"F02 entry minute target");
   CHTStart(p,c,CHT_T05,0,0,.01,false,false,29100,100,100);bar.high=104;bar.low=97;CHTMinuteRange(p,bar);
   Check(p.resultR==-1 && p.ambiguous==1 && p.mfe==0,"F03 adverse first");
   c=PlanFixture(false);CHTStart(p,c,CHT_T05,.2,0,.01,false,false,29100,100,100.2);
   CHTQuote(p,29101,98.9,99.1);Check(p.state==CHT_FILLED,"F04 sell Bid target does not exit");
   Check(!CHTLegacyPreclose(true,false,98.9,102,99),"L0 preclose falsely deactivates SELL using Bid before Ask target");
   CHTQuote(p,29102,101.9,102.1);Check(p.reason==CHT_GAP,"F04 sell Ask stop");
   c=PlanFixture();CHTStart(p,c,CHT_T05,0,0,.01,false,false,29100,100,100);CHTQuote(p,29160,97.5,97.5);
   Check(p.resultR==-1.25,"F05 gap not clipped");
   CHTPropose(p,29160,100.5,29101,100.75,29100,102);Check(!p.proposed,"F06 no resurrection");
   CHTStart(p,c,CHT_TS,0,0,.01,false,false,29100,100,100);double anchor=p.protectedP;
   CHTPropose(p,29100,97,29101,100.75,29100,102);CHTQuote(p,29101,101,101);
   Check(p.stop==98 && p.protectedP==anchor && p.protectedHTime==0,"F07 rejected stop keeps anchors");
   CHTStart(p,c,CHT_TS,0,0,.01,false,false,29100,100,100);
   CHTPropose(p,29100,100.5,29101,100.75,29100,102);Check(p.stop==98,"F08 proposal delayed");
   CHTQuote(p,29101,101.5,101.5);CHTClose(p,101,29102,CHT_TIME);
   Check(p.initialStop==98 && p.risk==2 && p.resultR==.5,"F11 immutable R0");
   CHTStart(p,c,CHT_T05,0,0,.01,false,false,29161,100,100);Check(p.reason==CHT_NO_QUOTE,"F14 quote delay");
   CHTStart(p,c,CHT_T15,.2,0,.01,false,true,29100,100,100.2);CHTQuote(p,30000,99,99.2);
   Check(p.state==CHT_EXPIRED && p.entryTime==0,"F29 expiry before fill");
   CHTStart(p,c,CHT_T15,.2,0,.01,false,true,29100,100,100.2);CHTQuote(p,29101,99,99.2);
   Check(p.state==CHT_PENDING,"F30 limit Ask side");
   CHTQuote(p,29160,98,98.2);Check(p.state==CHT_CANCELLED && p.entryTime==0,"F33 pending cancel before fill");
   double room;int reason;Check(!CHTRoomOK(100,98,0,1,true,.01,room,reason) && reason==CHT_ROOM_UNKNOWN,"F34 room unknown");
   CHTStart(p,c,CHT_TS,0,0,.01,false,false,29100,100,100);
   CHTPropose(p,29100,100.5,29101,100.75,29100,102);CHTQuote(p,29101,101.5,101.5);
   string seen[1]={"fixture_idea"};
   bool stored=CHTSaveState(CHT_FOLDER+"state_fixture.bin","F17_v01",p,28800,29101000,101.5,101.5,seen);
   CHTPlan loaded;datetime wm=0;long msc=0;double bid=0,ask=0;string restored[];
   bool recovered=CHTLoadState(CHT_FOLDER+"state_fixture.bin","F17_v01",loaded,wm,msc,bid,ask,restored);
   bool stateOK=stored && recovered && loaded.stop==100.5 && loaded.initialStop==98 && loaded.risk==2 &&
                loaded.eventSerial==p.eventSerial && loaded.triedCount==1 && wm==28800 && msc==29101000 &&
                ArraySize(restored)==1 && restored[0]=="fixture_idea";
   Check(stateOK,"F17 durable state and dedup watermark");
   int sf=FileOpen(CHT_FOLDER+"state_roundtrip.json",FILE_WRITE|FILE_TXT|FILE_ANSI);
   FileWriteString(sf,StringFormat("{\"passed\":%s,\"stop\":%.2f,\"initial_sl\":%.2f,\"risk\":%.2f,\"watermark\":%I64d,\"event_serial\":%I64d}",
                                  stateOK?"true":"false",loaded.stop,loaded.initialStop,loaded.risk,(long)wm,loaded.eventSerial));FileClose(sf);
}
void OnStart()
{
   Progress("loading",0);
   PlanFixtures();
   bool loaded=ReadRates("h1",allH1)&&ReadRates("m5",allM5)&&ReadRates("d1",allD1)&&ReadRates("m1",allM1);
   Check(loaded,"input files");
   if(loaded)
   {
      Progress("native_probe",0);
      NativeProbe("_CHT_H1_20261025",allH1,50000,true);
      NativeProbe("_CHT_M5_20261025",allM5,4096,false);
      ExportRaw();
      CHTBuildPivots(allM5,allHighs,allLows);
      string names[6]={"C0_NATIVE","T05","T15","TS","T05_RG1","T15_RG1"};
      CHTPolicy policies[6]={CHT_NATIVE,CHT_T05,CHT_T15,CHT_TS,CHT_T05,CHT_T15};
      double spreads[3]={.2,.3,.45},slips[3]={0,.01,.05};string costs[3]={"C_A","C_B","C_C"};
      for(int s=0;s<6;s++)for(int k=0;k<3;k++)for(int serial=0;serial<2;serial++)
         ReplayMarket(names[s],policies[s],spreads[k],slips[k],costs[k],s>=4,(bool)serial);
      for(int k=0;k<3;k++)for(int serial=0;serial<2;serial++)for(int path=0;path<2;path++)
         ReplayMarket("BODY50_T15_RG1",CHT_T15,spreads[k],slips[k],costs[k],true,(bool)serial,true,(bool)path);
   }
   int f=FileOpen(CHT_FOLDER+"mql_result.json",FILE_WRITE|FILE_TXT|FILE_ANSI);
   FileWriteString(f,StringFormat("{\"version\":\"%s\",\"checks\":%d,\"failures\":%d}",CHT_VERSION,checks,failures));FileClose(f);
   Print("CAN HO TRO SCALP ORACLE DONE checks=",checks," failures=",failures);
}
