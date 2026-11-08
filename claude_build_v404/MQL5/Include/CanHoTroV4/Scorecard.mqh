#ifndef CHT_V4_SCORECARD
#define CHT_V4_SCORECARD
#include <CanHoTroV4/Execution.mqh>
int V4LowerBar(const MqlRates &bars[],datetime t)
{
   int l=0,r=ArraySize(bars);
   while(l<r) { int m=(l+r)/2; if(bars[m].time<t) l=m+1; else r=m; }
   return l;
}
void V4NewVirtual(const SConfirmSignal &s,string source,SV4VirtualTrade &v)
{
   ZeroMemory(v); v.id=s.signal_id; v.source=source; v.zone=s.source_zone_id;
   v.known=s.signal_known_time; v.published=s.publish_time; v.buy=s.isBuy; v.initialSl=s.initialSl;
}
void V4HistEvaluate(SV4VirtualTrade &v,const MqlRates &bars[],const SV4SymbolSpec &spec,
                     ENUM_V4_EXIT rule,double spread,double slip,double commission,bool legacy=false)
{
   int i=V4LowerBar(bars,v.known),n=ArraySize(bars);
   if(i>=n) { v.reason="PENDING_DATA"; return; }
   if(legacy && bars[i].time-v.known>600) { v.closed=true; v.reason="LEGACY_ENTRY_GAP"; return; }
   if(!legacy && bars[i].time>=v.known+240*60)
   { v.closed=true; v.reason="EXPIRED_NO_QUOTE"; return; }
   double scale=1;
   if(!legacy && !V4PriceFactor(bars[i].time,scale)) {v.reason="MISSING_CLOSED_D1";return;}
   if(!V4VirtualFill(v,bars[i].time,bars[i].open,bars[i].open+spread*scale,slip*scale,commission,spec)) return;
   int end=legacy?MathMin(n,i+240):n;
   for(int j=i;j<end && !v.closed;j++)
   {
      if(!legacy && !V4PriceFactor(bars[j].time,scale)) {v.reason="MISSING_CLOSED_D1";return;}
      V4VirtualBar(v,bars[j],spread*scale,slip*scale,rule,240,legacy);
   }
   if(legacy && !v.closed && end>i)
      V4VirtualClose(v,bars[end-1].time+60,v.buy?bars[end-1].close:bars[end-1].close+spread,slip,"LEGACY_TIMEOUT_240_BARS");
   if(!v.closed) v.reason="PENDING_DATA";
}
struct SV4Stats
{
   int signals,closed,wins,excluded;
   double gross,net,profit,loss,medianCost;
};
void V4Statistics(const SV4VirtualTrade &rows[],string source,SV4Stats &a,int hour=-1,long week=-1)
{
   ZeroMemory(a); double costs[];
   for(int i=0;i<ArraySize(rows);i++)
   {
      SV4VirtualTrade v=rows[i];
      if(v.source!=source || (hour>=0 && (v.known%86400)/3600!=hour) ||
         (week>=0 && ((long)v.known+3*86400)/604800!=week)) continue;
      a.signals++;
      if(!v.closed || !v.filled || v.reason=="LIVE_GAP") { a.excluded++; continue; }
      a.closed++; if(v.netR>0) a.wins++;
      a.gross+=v.grossR; a.net+=v.netR;
      if(v.netR>0) a.profit+=v.netR; else a.loss-=v.netR;
      int n=ArraySize(costs); ArrayResize(costs,n+1); costs[n]=v.costR;
   }
   int n=ArraySize(costs); ArraySort(costs);
   if(n>0) a.medianCost=(costs[(n-1)/2]+costs[n/2])/2;
}
string V4PF(double profit,double loss)
{
   return loss>0?DoubleToString(profit/loss,3):(profit>0?"INF":"NA");
}
string V4StatsText(const SV4Stats &a)
{
   return StringFormat("n=%d closed=%d win=%.1f%% R gross/net=%.3f/%.3f PF=%s fee/R=%.1f%% pending/excl=%d",
      a.signals,a.closed,a.closed>0?100.0*a.wins/a.closed:0,
      a.closed>0?a.gross/a.closed:0,a.closed>0?a.net/a.closed:0,V4PF(a.profit,a.loss),100*a.medianCost,a.excluded);
}
SV4VirtualTrade g_v4Score[];
string g_v4ScorePath="",g_v4ScoreError="";
int g_v4ScoreSeen=0;
datetime g_v4ScoreLastM1=0;
datetime g_v4ScoreStarted=0;
void V4ScoreHeader(int f)
{
   FileWrite(f,"signal_id","source","zone_id","known","published","is_buy","filled","closed","fill","exit",
      "entry","initial_sl","stop","risk","mfe","exit_price","gross_R","net_R","cost_R","commission_R","spread","ambiguous","reason");
}
void V4ScoreWrite(int f,const SV4VirtualTrade &v)
{
   FileWrite(f,v.id,v.source,v.zone,(long)v.known,(long)v.published,(int)v.buy,(int)v.filled,(int)v.closed,
      (long)v.fill,(long)v.exit,v.entry,v.initialSl,v.stop,v.risk,v.mfe,v.exitPrice,v.grossR,v.netR,v.costR,v.commissionR,
      v.spread,(int)v.ambiguous,v.reason);
}
bool V4ScoreSave()
{
   if(g_v4ReadOnly) return true;
   if(g_v4ScorePath=="") return false;
   int f=FileOpen(g_v4ScorePath+".tmp",FILE_WRITE|FILE_CSV|FILE_ANSI,',',CP_UTF8);
   if(f==INVALID_HANDLE) return false;
   V4ScoreHeader(f);
   for(int i=0;i<ArraySize(g_v4Score);i++) V4ScoreWrite(f,g_v4Score[i]);
   FileFlush(f); FileClose(f);
   return FileMove(g_v4ScorePath+".tmp",0,g_v4ScorePath,FILE_REWRITE);
}
bool V4ScoreInit()
{
   ArrayResize(g_v4Score,0); g_v4ScoreSeen=0;
   string config=g_v4Preset+"|"+EnumToString(InpScoreExit)+"|"+DoubleToString(InpHistSpreadPrice,8)+"|"+
      DoubleToString(InpCommissionPerLot,8)+"|"+DoubleToString(InpSlippagePoints,8)+"|"+
      AccountInfoString(ACCOUNT_SERVER)+"|"+(string)AccountInfoInteger(ACCOUNT_LOGIN);
   g_v4ScorePath=InpV4LedgerFolder+"\\score_"+V4FileKey()+"_"+(string)V4Hash(config)+".csv";
   if(!FileIsExist(g_v4ScorePath)) return true;
   int f=FileOpen(g_v4ScorePath,FILE_READ|FILE_CSV|FILE_ANSI,',',CP_UTF8);
   if(f==INVALID_HANDLE) return false;
   string header="signal_id,source,zone_id,known,published,is_buy,filled,closed,fill,exit,entry,initial_sl,stop,risk,mfe,exit_price,gross_R,net_R,cost_R,commission_R,spread,ambiguous,reason";
   string expected[]; StringSplit(header,',',expected);
   for(int c=0;c<23;c++)
      if(FileReadString(f)!=expected[c]) { FileClose(f); return false; }
   while(!FileIsEnding(f))
   {
      string cols[]; ArrayResize(cols,23);
      for(int c=0;c<23;c++)
      {
         cols[c]=FileReadString(f);
         if(c<22 && FileIsLineEnding(f)) { FileClose(f); return false; }
      }
      SV4VirtualTrade v; ZeroMemory(v);
      v.id=cols[0]; v.source=cols[1]; v.zone=StringToInteger(cols[2]); v.known=(datetime)StringToInteger(cols[3]);
      v.published=(datetime)StringToInteger(cols[4]); v.buy=(bool)StringToInteger(cols[5]);
      v.filled=(bool)StringToInteger(cols[6]); v.closed=(bool)StringToInteger(cols[7]);
      v.fill=(datetime)StringToInteger(cols[8]); v.exit=(datetime)StringToInteger(cols[9]);
      v.entry=StringToDouble(cols[10]); v.initialSl=StringToDouble(cols[11]); v.stop=StringToDouble(cols[12]);
      v.risk=StringToDouble(cols[13]); v.mfe=StringToDouble(cols[14]); v.exitPrice=StringToDouble(cols[15]);
      v.grossR=StringToDouble(cols[16]); v.netR=StringToDouble(cols[17]); v.costR=StringToDouble(cols[18]);
      v.commissionR=StringToDouble(cols[19]); v.spread=StringToDouble(cols[20]);
      v.ambiguous=(bool)StringToInteger(cols[21]); v.reason=cols[22];
      if(v.id=="" || (v.source!="LIVE" && v.source!="HIST")) { FileClose(f); return false; }
      // Offline intervals have no observed live tick path; retain source and exclude the trade.
      if(v.source=="LIVE" && !v.closed) { v.closed=true; v.reason="LIVE_GAP"; }
      int n=ArraySize(g_v4Score); ArrayResize(g_v4Score,n+1); g_v4Score[n]=v;
   }
   FileClose(f); return true;
}
void V4ScoreUpdate(const MqlTick &now,bool startup)
{
   if(!InpScorecard || g_v4ScoreError=="SCORE_RELOAD_FAILED" || g_v4ScoreError=="SCORE_WRITE_FAILED") return;
   SV4SymbolSpec spec;
   if(!V4SymbolSpec(_Symbol,spec)) { g_v4ScoreError="SYMBOL_SPEC_UNAVAILABLE"; return; }
   if(g_v4ScoreError=="SYMBOL_SPEC_UNAVAILABLE") g_v4ScoreError="";
   if(g_v4ScoreStarted==0) g_v4ScoreStarted=now.time;
   double slip=InpSlippagePoints*spec.point; bool changed=false;
   int n=ArraySize(g_v4History);
   for(int i=g_v4ScoreSeen;i<n;i++)
   {
      bool found=false;
      for(int j=0;j<ArraySize(g_v4Score);j++) if(g_v4Score[j].id==g_v4History[i].signal_id) { found=true; break; }
      if(found) continue;
      SConfirmSignal s=g_v4History[i];
      int k=ArraySize(g_v4Score); ArrayResize(g_v4Score,k+1);
      string source=(!startup && s.signal_known_time>=g_v4ScoreStarted)?"LIVE":"HIST";
      V4NewVirtual(s,source,g_v4Score[k]); changed=true;
   }
   g_v4ScoreSeen=n;
   datetime lastM1=iTime(_Symbol,PERIOD_M1,1);
   if(lastM1!=g_v4ScoreLastM1 || changed)
   {
      for(int j=0;j<ArraySize(g_v4Score);j++)
      {
         if(g_v4Score[j].source!="HIST" || g_v4Score[j].closed) continue;
         MqlRates bars[]; ArraySetAsSeries(bars,false);
         datetime begin=g_v4Score[j].known;
         int copied=CopyRates(_Symbol,PERIOD_M1,begin,MathMin(now.time-60,begin+240*60+7*86400),bars);
         if(copied<=0) continue;
         // Recompute pending HIST from immutable inputs after more history arrives.
         g_v4Score[j].filled=false; g_v4Score[j].mfe=0;
         V4HistEvaluate(g_v4Score[j],bars,spec,InpScoreExit,InpHistSpreadPrice,slip,InpCommissionPerLot);
         changed=true;
      }
      g_v4ScoreLastM1=lastM1;
   }
   for(int j=0;j<ArraySize(g_v4Score);j++)
   {
      if(g_v4Score[j].source!="LIVE" || g_v4Score[j].closed) continue;
      MqlTick ticks[];
      long from=g_v4Score[j].tickCursor>0?g_v4Score[j].tickCursor:(long)g_v4Score[j].known*1000;
      int count=CopyTicksRange(_Symbol,ticks,COPY_TICKS_ALL,(ulong)from,(ulong)now.time_msc);
      int skip=g_v4Score[j].tickCursor>0?g_v4Score[j].tickSame:0;
      if(count<=0) continue;
      long tail=ticks[count-1].time_msc; int same=0;
      for(int t=count-1;t>=0 && ticks[t].time_msc==tail;t--) same++;
      for(int t=skip;t<count;t++)
      {
            if(g_v4Score[j].closed) break;
            if(!g_v4Score[j].filled && ticks[t].time>=g_v4Score[j].known+240*60)
            { g_v4Score[j].closed=true; g_v4Score[j].reason="EXPIRED_NO_QUOTE"; changed=true; continue; }
            double scale; if(!V4PriceFactor(ticks[t].time,scale)) continue;
            if(!g_v4Score[j].filled)
            {
               V4VirtualFill(g_v4Score[j],ticks[t].time,ticks[t].bid,ticks[t].ask,slip*scale,InpCommissionPerLot,spec);
               changed=true;
            }
            V4VirtualTick(g_v4Score[j],ticks[t],slip*scale,InpScoreExit);
            if(g_v4Score[j].closed) changed=true;
      }
      g_v4Score[j].tickCursor=tail; g_v4Score[j].tickSame=same;
   }
   if(changed && !V4ScoreSave()) g_v4ScoreError="SCORE_WRITE_FAILED";
}
bool V4ScoreExport()
{
   if(!V4ScoreSave()) return false;
   int f=FileOpen(g_v4ScorePath+".groups.csv",FILE_WRITE|FILE_CSV|FILE_ANSI,',',CP_UTF8);
   if(f==INVALID_HANDLE) return false;
   FileWrite(f,"source","group","key","signals","closed","win_percent","mean_gross_R","mean_net_R","PF_R","median_cost_R","excluded");
   for(int s=0;s<2;s++)
   {
      string source=s==0?"HIST":"LIVE";
      long weeks[];
      for(int i=0;i<ArraySize(g_v4Score);i++)
      {
         if(g_v4Score[i].source!=source) continue;
         long w=((long)g_v4Score[i].known+3*86400)/604800; bool found=false;
         for(int k=0;k<ArraySize(weeks);k++) if(weeks[k]==w) found=true;
         if(!found) { int k=ArraySize(weeks); ArrayResize(weeks,k+1); weeks[k]=w; }
      }
      for(int g=-1;g<24+ArraySize(weeks);g++)
      {
         SV4Stats a; V4Statistics(g_v4Score,source,a,g>=0 && g<24?g:-1,g>=24?weeks[g-24]:-1);
         FileWrite(f,source,g<0?"ALL":(g<24?"HOUR_SERVER":"WEEK_MONDAY_SERVER"),g<24?(long)g:weeks[g-24],
            a.signals,a.closed,a.closed>0?100.0*a.wins/a.closed:0,a.closed>0?a.gross/a.closed:0,
            a.closed>0?a.net/a.closed:0,V4PF(a.profit,a.loss),a.medianCost,a.excluded);
      }
   }
   FileClose(f); return true;
}
#endif
