#property strict
#include "../../Include/CanHoTroScalpDetector.mqh"
#include "../../Include/CanHoTroScalpPlan.mqh"
#include "../../Include/CanHoTroScalpFresh.mqh"
const string CHT_FOLDER="can_ho_tro_scalp_v1\\";
MqlRates allH1[],allM5[],allM1[];
CHTCandidate allCandidates[];
CHTPivot allHighs[],allLows[];double atrM5[];
void Progress(const string state,const int count){Print(state," ",count);}
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
void ReplayMarket(const string name,const CHTPolicy policy,const double spread,const double slip,const string cost,const bool room,const bool serial,const bool retest=false,const bool highFirst=false)
{
   string path=retest?(highFirst?"OHLC":"OLHC"):"ADVERSE_FIRST";
   string label=name+"_"+cost+"_"+path+"_"+(serial?"serial":"paired");
   int f=FileOpen(CHT_FOLDER+label+"_trades_mql.csv",FILE_WRITE|FILE_CSV|FILE_ANSI,',');
   int ef=FileOpen(CHT_FOLDER+label+"_stops_mql.csv",FILE_WRITE|FILE_CSV|FILE_ANSI,',');
   datetime chosenAt=0,busyUntil=0;string seen[];int count=0;
   for(int i=0;i<ArraySize(allCandidates);i++)
   {
      CHTCandidate c=allCandidates[i];
      if(CHTFreshGate(c,.01,retest,room)!=CHT_NONE)continue;
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

void OnStart()
{
   int checks=0,failures=0;
   CHTCandidate c;ZeroMemory(c);c.v[2]=1;c.v[19]=98;c.v[21]=100;
   c.v[9]=0;checks++;if(CHTFreshGate(c,.01,false,false)!=CHT_NONE)failures++;
   c.v[9]=1;checks++;if(CHTFreshGate(c,.01,false,false)!=CHT_NONE)failures++;
   c.v[9]=2;checks++;if(CHTFreshGate(c,.01,false,false)!=1001)failures++;
   c.v[9]=1;c.v[27]=3;checks++;if(CHTFreshGate(c,.01,false,false)!=103)failures++;
   bool loaded=ReadRates("m1",allM1);checks++;if(!loaded)failures++;
   int f=FileOpen(CHT_FOLDER+"candidates_c0_mql.csv",FILE_READ|FILE_CSV|FILE_ANSI,',');
   checks++;if(f==INVALID_HANDLE)failures++;
   if(f!=INVALID_HANDLE)
   {
      while(!FileIsEnding(f))
      {
         string stamp=FileReadString(f);if(stamp=="")break;
         CHTCandidate row;row.v[0]=StringToDouble(stamp);
         for(int j=1;j<36;j++)row.v[j]=FileReadNumber(f);
         int n=ArraySize(allCandidates);ArrayResize(allCandidates,n+1,4096);allCandidates[n]=row;
      }
      FileClose(f);
   }
   if(loaded && failures==0)
   {
      ReplayMarket("FRESH_V2",CHT_T05,.20,0.,"LOW",false,true);
      ReplayMarket("FRESH_V2",CHT_T05,.30,.01,"BASE",false,true);
      ReplayMarket("FRESH_V2",CHT_T05,.45,.05,"STRESS",false,true);
   }
   f=FileOpen(CHT_FOLDER+"fresh_v2_result.json",FILE_WRITE|FILE_TXT|FILE_ANSI);
   FileWriteString(f,StringFormat("{\"checks\":%d,\"failures\":%d,\"candidate_rows\":%d}",checks,failures,ArraySize(allCandidates)));FileClose(f);
}
