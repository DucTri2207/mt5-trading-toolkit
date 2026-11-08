#ifndef CHT_V4_M2_PANEL
#define CHT_V4_M2_PANEL
#include <CanHoTroV4/Risk.mqh>
#include <CanHoTroV4/Scorecard.mqh>
#include <CanHoTroV4/Journal.mqh>
bool g_v4M2Started=false;
void V4M2Label(int line,string text,color clr)
{
   string name=g_prefix+"M2_"+(string)line;
   if(ObjectFind(0,name)<0) ObjectCreate(0,name,OBJ_LABEL,0,0,0);
   ObjectSetInteger(0,name,OBJPROP_CORNER,DashRight?CORNER_LEFT_UPPER:CORNER_RIGHT_UPPER);
   ObjectSetInteger(0,name,OBJPROP_ANCHOR,DashRight?ANCHOR_LEFT_UPPER:ANCHOR_RIGHT_UPPER);
   ObjectSetInteger(0,name,OBJPROP_XDISTANCE,20);
   ObjectSetInteger(0,name,OBJPROP_YDISTANCE,20+line*17);
   ObjectSetInteger(0,name,OBJPROP_COLOR,clr); ObjectSetInteger(0,name,OBJPROP_FONTSIZE,9);
   ObjectSetString(0,name,OBJPROP_FONT,"Segoe UI"); ObjectSetString(0,name,OBJPROP_TEXT,text==""?" ":text);
}
string V4CompactStats(const SV4Stats &a)
{
   return StringFormat("n%d C%d W%.1f%% Rg/n %.3f/%.3f PF%s",a.signals,a.closed,
      a.closed>0?100.0*a.wins/a.closed:0,a.closed>0?a.gross/a.closed:0,
      a.closed>0?a.net/a.closed:0,V4PF(a.profit,a.loss));
}
void V4M2Panel()
{
   if(!ShowDash || !InpShowStatsPanel) { ObjectsDeleteAll(0,g_prefix+"M2_"); return; }
   string bg=g_prefix+"M2_BG";
   if(ObjectFind(0,bg)<0) ObjectCreate(0,bg,OBJ_RECTANGLE_LABEL,0,0,0);
   ObjectSetInteger(0,bg,OBJPROP_CORNER,DashRight?CORNER_LEFT_UPPER:CORNER_RIGHT_UPPER);
   ObjectSetInteger(0,bg,OBJPROP_XDISTANCE,DashRight?12:632);
   ObjectSetInteger(0,bg,OBJPROP_YDISTANCE,12);
   ObjectSetInteger(0,bg,OBJPROP_XSIZE,620); ObjectSetInteger(0,bg,OBJPROP_YSIZE,217);
   ObjectSetInteger(0,bg,OBJPROP_BGCOLOR,C'22,27,34'); ObjectSetInteger(0,bg,OBJPROP_COLOR,clrSilver);
   SV4Stats h,l,week,hour;
   V4Statistics(g_v4Score,"HIST",h); V4Statistics(g_v4Score,"LIVE",l);
   // OBJ_LABEL truncates text at 63 characters on the tested MT5 build.
   V4M2Label(0,"Thống kê theo quy tắc cố định,",clrSilver);
   V4M2Label(1,"không phải kết quả giao dịch của bạn",clrSilver);
   V4M2Label(2,"HIST "+V4CompactStats(h),clrSilver);
   V4M2Label(3,"LIVE "+V4CompactStats(l),clrSilver);
   V4M2Label(4,StringFormat("Median phí/R HIST %.1f%% LIVE %.1f%% | C=closed, Rg/n=gross/net",100*h.medianCost,100*l.medianCost),clrSilver);
   for(int s=0;s<2;s++)
   {
      string source=s==0?"HIST":"LIVE";
      V4Statistics(g_v4Score,source,week,-1,((long)TimeCurrent()+3*86400)/604800);
      V4Statistics(g_v4Score,source,hour,(int)(TimeCurrent()%86400/3600));
      V4M2Label(5+s,StringFormat("%s tuần n%d R%.3f | giờ n%d R%.3f",source,week.closed,
         week.closed>0?week.net/week.closed:0,hour.closed,hour.closed>0?hour.net/hour.closed:0),clrSilver);
   }
   string risk="Risk: cần InpInitialCapital; reset server ánh xạ CE(S)T";
   if(g_v4Limits.ready) risk=StringFormat("Còn ngày %.2f / tổng %.2f (account CCY)",g_v4Limits.dailyRemaining,g_v4Limits.totalRemaining);
   V4M2Label(7,risk,g_v4Limits.hit?clrTomato:clrSilver);
   SV4SymbolSpec spec; string detail="Chưa có tín hiệu"; bool warning=false;
   if(V4SymbolSpec(_Symbol,spec) && ArraySize(g_v4History)>0)
   {
      SConfirmSignal s=g_v4History[ArraySize(g_v4History)-1];
      double cost=V4CostR(s.isBuy,s.entryMarket,s.initialSl,V4Distance(InpHistSpreadPrice),V4Distance(InpSlippagePoints),InpCommissionPerLot,spec);
      double lot=V4Lots(AccountInfoDouble(ACCOUNT_EQUITY),InpRiskPercent,s.isBuy,s.entryMarket,s.initialSl,spec);
      double actual=V4RiskMoney(s.isBuy,s.entryMarket,s.initialSl,lot,spec);
      warning=cost!=EMPTY_VALUE && cost*100>InpCostWarningPercent;
      detail=(lot<=0 || actual<=0 || cost==EMPTY_VALUE)?(g_v4RiskError!=""?g_v4RiskError:"Lot N/A: không tính được risk"):StringFormat("Lot %.3f Risk %.2f Phí/R %.1f%% %s",lot,actual,cost*100,warning?"PHÍ CAO":"");
   }
   V4M2Label(8,detail,warning?clrTomato:clrSilver);
   V4M2Label(9,"Journal: "+g_v4JournalStatus,clrSilver);
   V4M2Label(10,g_v4LedgerWarning!=""?g_v4LedgerWarning:(g_v4RiskWarning!=""?g_v4RiskWarning:g_v4ScoreError),clrTomato);
   string button=g_prefix+"M2_EXPORT";
   if(ObjectFind(0,button)<0) ObjectCreate(0,button,OBJ_BUTTON,0,0,0);
   ObjectSetInteger(0,button,OBJPROP_CORNER,DashRight?CORNER_LEFT_UPPER:CORNER_RIGHT_UPPER);
   ObjectSetInteger(0,button,OBJPROP_XDISTANCE,DashRight?20:620);
   ObjectSetInteger(0,button,OBJPROP_YDISTANCE,198);
   ObjectSetInteger(0,button,OBJPROP_XSIZE,100); ObjectSetInteger(0,button,OBJPROP_YSIZE,24);
   ObjectSetString(0,button,OBJPROP_TEXT,"Xuất CSV");
   ObjectSetString(0,button,OBJPROP_TOOLTIP,"Xuất Scorecard + Journal CSV");
}
void V4M2Update(const MqlTick &tick,bool startup)
{
   if(g_v4ReadOnly) { V4ScoreInit(); V4M2Panel(); return; }
   if(!g_v4M2Started)
   {
      g_v4M2Started=true;
      if(!V4ScoreInit()) g_v4ScoreError="SCORE_RELOAD_FAILED";
      V4JournalCollect(InpJournalFrom,tick.time);
   }
   V4UpdateLimits(tick.time);
   V4ScoreUpdate(tick,startup); V4M2Panel();
}
void V4M2Export()
{
   bool score=V4ScoreExport(); bool journal=V4JournalCollect(InpJournalFrom,TimeCurrent());
   journal=V4JournalExport() && journal;
   PrintFormat("V4 M2 CSV export score=%s journal=%s: %s",score?"OK":"FAIL",journal?"OK":"FAIL",g_v4ScorePath);
   ObjectSetInteger(0,g_prefix+"M2_EXPORT",OBJPROP_STATE,false); V4M2Panel();
}
#endif
