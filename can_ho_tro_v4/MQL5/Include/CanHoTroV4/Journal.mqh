#ifndef CHT_V4_JOURNAL
#define CHT_V4_JOURNAL
struct SV4Deal
{
   ulong ticket,order;
   long position;
   datetime time;
   int side,entry;
   double volume,price,sl,profit,commission,swap,fee;
};
struct SV4JournalTrade
{
   long position;
   int episode,side,partialCloses;
   datetime entryTime,exitTime;
   double entered,remaining,closedVolume,entryValue,exitValue,netUSD,riskUSD,initialSL;
   bool riskKnown,incomplete;
   string label,signalId;
   long zone;
   double zoneDistance;
};
void V4JournalMatch(SV4JournalTrade &p,const SConfirmSignal &signals[],int minutes)
{
   p.label="TU_VAO"; p.signalId=""; p.zone=0; p.zoneDistance=0;
   int same=-1,latest=-1;
   for(int i=0;i<ArraySize(signals);i++)
   {
      if(signals[i].signal_known_time>p.entryTime || p.entryTime>signals[i].signal_known_time+minutes*60) continue;
      if(latest<0 || signals[i].signal_known_time>signals[latest].signal_known_time) latest=i;
      if((signals[i].isBuy?1:-1)==p.side && (same<0 || signals[i].signal_known_time>signals[same].signal_known_time)) same=i;
   }
   int match=same>=0?same:latest;
   if(match<0) return;
   p.label=same>=0?"THEO_TIN_HIEU":"NGUOC_TIN_HIEU";
   p.signalId=signals[match].signal_id; p.zone=signals[match].source_zone_id;
   double price=p.entered>0?p.entryValue/p.entered:0;
   double lo=MathMin(signals[match].source_distal,signals[match].source_proximal);
   double hi=MathMax(signals[match].source_distal,signals[match].source_proximal);
   p.zoneDistance=MathMax(0,MathMax(lo-price,price-hi));
}
void V4JournalOpen(SV4JournalTrade &p,const SV4Deal &d,double volume,double cost,const SV4SymbolSpec &spec)
{
   if(p.entered==0) { p.entryTime=d.time; p.side=d.side; p.riskKnown=true; p.initialSL=d.sl; }
   p.entered+=volume; p.remaining+=volume; p.entryValue+=volume*d.price; p.netUSD+=cost;
   double risk=(d.price-d.sl)*d.side;
   if(d.sl<=0 || risk<=0 || V4RiskMoney(d.side>0,d.price,d.sl,volume,spec)<=0) p.riskKnown=false;
   else p.riskUSD+=V4RiskMoney(d.side>0,d.price,d.sl,volume,spec);
}
bool V4JournalApply(SV4JournalTrade &rows[],const SV4Deal &d,const SV4SymbolSpec &spec)
{
   if(d.volume<=0 || (d.side!=1 && d.side!=-1) || d.position<=0) return false;
   if(d.entry!=DEAL_ENTRY_IN && d.entry!=DEAL_ENTRY_OUT && d.entry!=DEAL_ENTRY_OUT_BY && d.entry!=DEAL_ENTRY_INOUT) return false;
   int k=-1,episode=0;
   for(int i=0;i<ArraySize(rows);i++) if(rows[i].position==d.position)
   { episode=MathMax(episode,rows[i].episode); if(rows[i].remaining>1e-8) k=i; }
   double costs=d.commission+d.swap+d.fee;
   if(d.entry==DEAL_ENTRY_IN)
   {
      if(k>=0 && rows[k].side!=d.side) return false;
      if(k<0)
      {
         k=ArraySize(rows); ArrayResize(rows,k+1); ZeroMemory(rows[k]);
         rows[k].position=d.position; rows[k].episode=episode+1;
      }
      V4JournalOpen(rows[k],d,d.volume,costs+d.profit,spec); return true;
   }
   if(k<0 || rows[k].side==d.side) return false;
   double closeVolume=MathMin(rows[k].remaining,d.volume);
   if(d.entry!=DEAL_ENTRY_INOUT && d.volume>rows[k].remaining+1e-8) return false;
   rows[k].remaining-=closeVolume; rows[k].closedVolume+=closeVolume;
   rows[k].exitValue+=closeVolume*d.price; rows[k].exitTime=d.time; rows[k].partialCloses++;
   // Reversal commission/fee is split by volume; swap and realized profit belong to the closing leg.
   rows[k].netUSD+=d.profit+d.swap+(d.commission+d.fee)*closeVolume/d.volume;
   if(d.entry==DEAL_ENTRY_INOUT && d.volume>closeVolume+1e-8)
   {
      int n=ArraySize(rows); ArrayResize(rows,n+1); ZeroMemory(rows[n]);
      rows[n].position=d.position; rows[n].episode=episode+1;
      V4JournalOpen(rows[n],d,d.volume-closeVolume,(d.commission+d.fee)*(d.volume-closeVolume)/d.volume,spec);
   }
   return true;
}
SV4JournalTrade g_v4Journal[];
string g_v4JournalStatus="NOT_RUN";
bool V4JournalCollect(datetime from,datetime to)
{
   ArrayResize(g_v4Journal,0); SV4SymbolSpec spec;
   // Include earlier entries so partial positions at 'from' are reconstructed safely.
   if(!V4SymbolSpec(_Symbol,spec) || !HistorySelect(0,to)) { g_v4JournalStatus="HISTORY_UNAVAILABLE"; return false; }
   int skipped=0;
   for(int i=0;i<HistoryDealsTotal();i++)
   {
      ulong ticket=HistoryDealGetTicket(i);
      if(HistoryDealGetString(ticket,DEAL_SYMBOL)!=_Symbol) continue;
      long type=HistoryDealGetInteger(ticket,DEAL_TYPE);
      if(type!=DEAL_TYPE_BUY && type!=DEAL_TYPE_SELL) continue;
      SV4Deal d; ZeroMemory(d); d.ticket=ticket; d.side=type==DEAL_TYPE_BUY?1:-1;
      d.order=(ulong)HistoryDealGetInteger(ticket,DEAL_ORDER);
      d.position=HistoryDealGetInteger(ticket,DEAL_POSITION_ID); d.time=(datetime)HistoryDealGetInteger(ticket,DEAL_TIME);
      d.entry=(int)HistoryDealGetInteger(ticket,DEAL_ENTRY); d.volume=HistoryDealGetDouble(ticket,DEAL_VOLUME);
      d.price=HistoryDealGetDouble(ticket,DEAL_PRICE); d.profit=HistoryDealGetDouble(ticket,DEAL_PROFIT);
      d.commission=HistoryDealGetDouble(ticket,DEAL_COMMISSION); d.swap=HistoryDealGetDouble(ticket,DEAL_SWAP);
      d.fee=HistoryDealGetDouble(ticket,DEAL_FEE);
      d.sl=HistoryOrderGetDouble(d.order,ORDER_SL);
      if(d.sl<=0) d.sl=HistoryDealGetDouble(ticket,DEAL_SL);
      if(!V4JournalApply(g_v4Journal,d,spec)) skipped++;
   }
   for(int i=ArraySize(g_v4Journal)-1;i>=0;i--)
   {
      if(g_v4Journal[i].entryTime<from && g_v4Journal[i].exitTime<from)
      { ArrayRemove(g_v4Journal,i,1); continue; }
      V4JournalMatch(g_v4Journal[i],g_v4History,InpJournalMatchMinutes);
   }
   g_v4JournalStatus=StringFormat("positions=%d unmatched_deals=%d",ArraySize(g_v4Journal),skipped);
   return skipped==0;
}
bool V4JournalExport()
{
   string path=InpV4LedgerFolder+"\\journal_"+(string)AccountInfoInteger(ACCOUNT_LOGIN)+"_"+_Symbol+".csv";
   int f=FileOpen(path,FILE_WRITE|FILE_CSV|FILE_ANSI,',',CP_UTF8);
   if(f==INVALID_HANDLE) return false;
   FileWrite(f,"position_id","episode","label","signal_id","zone_id","zone_distance","side","entry_time","exit_time",
      "entry_price","exit_price","entered_volume","closed_volume","remaining","partial_closes","initial_sl","net_USD","net_R","status");
   for(int i=0;i<ArraySize(g_v4Journal);i++)
   {
      SV4JournalTrade p=g_v4Journal[i];
      FileWrite(f,p.position,p.episode,p.label,p.signalId,p.zone,p.zoneDistance,p.side,(long)p.entryTime,(long)p.exitTime,
         p.entered>0?p.entryValue/p.entered:0,p.closedVolume>0?p.exitValue/p.closedVolume:0,p.entered,p.closedVolume,
         p.remaining,p.partialCloses,p.initialSL,p.netUSD,p.riskKnown && p.riskUSD>0?DoubleToString(p.netUSD/p.riskUSD,8):"không xác định",
         p.remaining>1e-8?"OPEN_PARTIAL":"CLOSED");
   }
   FileClose(f);
   f=FileOpen(path+".groups.csv",FILE_WRITE|FILE_CSV|FILE_ANSI,',',CP_UTF8);
   if(f==INVALID_HANDLE) return false;
   FileWrite(f,"label","closed","wins","R_known","mean_net_R","PF_R","PF_USD","total_USD","open_positions");
   string labels[]={"THEO_TIN_HIEU","TU_VAO","NGUOC_TIN_HIEU"};
   for(int l=0;l<3;l++)
   {
      int n=0,w=0,nr=0,op=0; double usd=0,r=0,rp=0,rl=0,up=0,ul=0;
      for(int i=0;i<ArraySize(g_v4Journal);i++)
      {
         SV4JournalTrade p=g_v4Journal[i]; if(p.label!=labels[l]) continue;
         if(p.remaining>1e-8) { op++; continue; }
         n++; usd+=p.netUSD; if(p.netUSD>0) { w++; up+=p.netUSD; } else ul-=p.netUSD;
         if(p.riskKnown && p.riskUSD>0)
         { nr++; double value=p.netUSD/p.riskUSD; r+=value; if(value>0) rp+=value; else rl-=value; }
      }
      FileWrite(f,labels[l],n,w,nr,nr>0?DoubleToString(r/nr,8):"không xác định",V4PF(rp,rl),V4PF(up,ul),usd,op);
   }
   FileClose(f); return true;
}
#endif
