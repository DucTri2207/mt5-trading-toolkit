#ifndef CHT_V4_CHART_HISTORY
#define CHT_V4_CHART_HISTORY
int g_v4ChartLock=INVALID_HANDLE;

datetime g_v4HistoryFrom=0,g_v4HistoryCursor=0,g_v4ChartEnd=0;
ulong g_v4InitMs=0,g_v4LastReadMs=0,g_v4ReadyMs=0;
bool g_v4HistoryDone=false;
string V4ZonePath(){return InpV4LedgerFolder+"\\zones_"+V4FileKey()+".bin";}
void V4RememberZones()
{
   for(int j=0;j<ArraySize(g_zones);j++)
   {
      SZone z=g_zones[j]; int found=-1;
      for(int i=0;i<ArraySize(g_v4ZoneHistory);i++) if(g_v4ZoneHistory[i].id==z.id){found=i;break;}
      if(found<0){found=ArraySize(g_v4ZoneHistory);ArrayResize(g_v4ZoneHistory,found+1);}
      g_v4ZoneHistory[found]=z;
   }
   // Keep source zones after they age out of the detector's rolling window.
   // Structural invalidity is the first subsequent closed H1 beyond the distal.
   for(int i=0;i<ArraySize(g_v4ZoneHistory);i++)
   {
      if(g_v4ZoneHistory[i].timeInvalid>0)continue;
      bool present=false;
      for(int j=0;j<ArraySize(g_zones);j++)if(g_zones[j].id==g_v4ZoneHistory[i].id){present=true;break;}
      if(present)continue;
      MqlRates bars[];ArraySetAsSeries(bars,false);
      int n=CopyRates(_Symbol,PERIOD_H1,g_v4ZoneHistory[i].timeEnd+3600,g_v4Now-3600,bars);
      for(int k=0;k<n;k++)
         if(g_v4ZoneHistory[i].isSupply?bars[k].close>g_v4ZoneHistory[i].distal:bars[k].close<g_v4ZoneHistory[i].distal)
         {g_v4ZoneHistory[i].timeInvalid=bars[k].time+3600;g_v4ZoneHistory[i].isBroken=true;break;}
   }
}
bool V4ZoneSnapshot(bool write)
{
   string path=V4ZonePath();
   int f=FileOpen(write?path+".tmp":path,(write?FILE_WRITE:FILE_READ)|FILE_BIN);
   if(f==INVALID_HANDLE)return false;
   bool ok=true;
   if(write)
   {
      FileWriteLong(f,(long)g_v4HistoryFrom);FileWriteLong(f,(long)g_v4HistoryCursor);
      FileWriteInteger(f,(int)g_v4HistoryDone);FileWriteInteger(f,ArraySize(g_zones));
      for(int i=0;i<ArraySize(g_zones);i++)if(FileWriteStruct(f,g_zones[i])==0)ok=false;
      FileWriteInteger(f,ArraySize(g_v4ZoneHistory));
      for(int i=0;i<ArraySize(g_v4ZoneHistory);i++)if(FileWriteStruct(f,g_v4ZoneHistory[i])==0)ok=false;
   }
   else
   {
      datetime from=(datetime)FileReadLong(f),cursor=(datetime)FileReadLong(f);
      bool done=(bool)FileReadInteger(f);int n=FileReadInteger(f);
      SZone current[],history[];
      if(n<0 || n>100000)ok=false;
      if(ok){ArrayResize(current,n);for(int i=0;i<n;i++)if(FileReadStruct(f,current[i])!=sizeof(SZone))ok=false;}
      n=ok?FileReadInteger(f):-1;
      if(n<0 || n>200000)ok=false;
      if(ok){ArrayResize(history,n);for(int i=0;i<n;i++)if(FileReadStruct(f,history[i])!=sizeof(SZone))ok=false;}
      if(ok){ArrayCopy(g_zones,current);ArrayCopy(g_v4ZoneHistory,history);g_v4HistoryFrom=from;g_v4HistoryCursor=cursor;g_v4HistoryDone=done;}
   }
   FileClose(f);
   return write?(ok && FileMove(path+".tmp",0,path,FILE_REWRITE)):ok;
}
bool V4FollowLedger()
{
   g_v4Preset=V4Preset();
   int f=FileOpen(InpV4LedgerFolder+"\\signals_"+V4FileKey()+".csv",FILE_READ|FILE_CSV|FILE_ANSI|FILE_SHARE_READ|FILE_SHARE_WRITE,',',CP_UTF8);
   if(f==INVALID_HANDLE)return false;
   SConfirmSignal rows[]; bool ok=V4Header(f);
   while(ok && !FileIsEnding(f))
   {
      SConfirmSignal s;if(!V4ReadSignal(f,s)){ok=false;break;}
      int n=ArraySize(rows);ArrayResize(rows,n+1);rows[n]=s;
   }
   FileClose(f);
   if(ok)
   {
      ArrayResize(g_v4History,ArraySize(rows));for(int i=0;i<ArraySize(rows);i++)g_v4History[i]=rows[i];
      if(ArraySize(rows)>0)g_lastSignal=rows[ArraySize(rows)-1];
      g_v4StatePath=InpV4LedgerFolder+"\\state_"+V4FileKey()+".csv";
      // A concurrent append can precede the owner's checkpoint; retry the read next timer.
      V4RestoreState();
   }
   return ok;
}
bool V4TryChartWriter()
{
   FolderCreate(InpV4LedgerFolder);
   int lock=FileOpen(InpV4LedgerFolder+"\\owner_"+V4FileKey()+".lock",FILE_READ|FILE_WRITE|FILE_BIN);
   if(lock==INVALID_HANDLE)return false;
   g_v4ChartLock=lock;g_v4ReadOnly=false;
   if(!V4OpenLedger()){FileClose(lock);g_v4ChartLock=INVALID_HANDLE;g_v4ReadOnly=true;return false;}
   V4ZoneSnapshot(false);
   g_v4HistoryFrom=(datetime)((long)TimeCurrent()-(long)InpHistoryDays*86400);
   g_v4HistoryCursor=g_v4LastEvaluated>0?g_v4LastEvaluated+600:g_v4HistoryFrom;
   datetime current=iTime(_Symbol,PERIOD_M5,0);
   g_v4HistoryDone=current>0 && g_v4HistoryCursor>current;
   if(g_v4HistoryDone){g_v4ReadyMs=MathMax(1,GetTickCount64()-g_v4InitMs);V4RenderZones();}
   g_v4M2Started=false;
   Print("V403_CHART_OWNER ",ChartID()," ",V4FileKey());return true;
}
void V4ChartStart()
{
   g_v4InitMs=GetTickCount64();g_v4Preset=V4Preset();g_v4ReadOnly=true;
   g_v4HistoryFrom=(datetime)((long)TimeCurrent()-(long)InpHistoryDays*86400);
   if(!V4TryChartWriter()){V4FollowLedger();if(V4ZoneSnapshot(false)){V4RenderZones();if(g_v4HistoryDone)g_v4ReadyMs=MathMax(1,GetTickCount64()-g_v4InitMs);}}
}
void V4RenderZoneAll(datetime end)
{
   for(int i=0;i<ArraySize(g_v4ZoneHistory);i++)
   {
      SZone z=g_v4ZoneHistory[i];bool expired=z.timeInvalid>0 && z.timeInvalid<=TimeCurrent();
      if(expired && (!InpShowExpiredZones || z.timeInvalid<g_v4HistoryFrom))continue;
      string name=g_prefix+"Z_"+(string)z.id;
      ObjectCreate(0,name,OBJ_RECTANGLE,0,z.timeStart,z.distal,expired?z.timeInvalid:end,z.proximal);
      ObjectSetInteger(0,name,OBJPROP_COLOR,expired?(z.isSupply?C'47,32,38':C'25,44,38'):(z.isSupply?C'85,28,34':C'20,68,48'));
      ObjectSetInteger(0,name,OBJPROP_BACK,true);ObjectSetInteger(0,name,OBJPROP_FILL,true);
      ObjectSetString(0,name,OBJPROP_TOOLTIP,StringFormat("H1 %s #%I64d\nknown %s\ninvalid %s",EnumToString(z.type),z.id,TimeToString(z.timeKnown),expired?TimeToString(z.timeInvalid):"active"));
   }
}
struct SV4DispZone
{
   double lo,hi; int score; datetime start; string ids; string type; bool fresh; int tests;
};
// v4.0.4 compact display: active zones only, nearest per side, overlaps merged. Display only.
void V4RenderZoneCompact(datetime end)
{
   datetime now=TimeCurrent();
   double price=SymbolInfoDouble(_Symbol,SYMBOL_BID);
   if(price<=0) return;
   double atr=0; double ab[];
   if(g_htfAtrHandle!=INVALID_HANDLE && CopyBuffer(g_htfAtrHandle,0,1,1,ab)==1) atr=ab[0];
   string info[2]; info[0]="CẦU: không còn vùng hiệu lực dưới giá"; info[1]="CUNG: không còn vùng hiệu lực trên giá";
   for(int side=0;side<2;side++)
   {
      bool supply=(side==1);
      int idx[]; double dist[]; ArrayResize(idx,0); ArrayResize(dist,0);
      for(int i=0;i<ArraySize(g_v4ZoneHistory);i++)
      {
         SZone z=g_v4ZoneHistory[i];
         if(z.isSupply!=supply) continue;
         if(z.timeKnown>now) continue;
         if(z.timeInvalid>0 && z.timeInvalid<=now) continue;
         if(z.score<MinScoreShow || z.testCount>=MaxTests) continue;
         double lo=MathMin(z.distal,z.proximal), hi=MathMax(z.distal,z.proximal);
         if(supply && hi<price-20*_Point) continue;
         if(!supply && lo>price+20*_Point) continue;
         double d=supply?MathMax(0.0,lo-price):MathMax(0.0,price-hi);
         int n=ArraySize(idx); ArrayResize(idx,n+1); ArrayResize(dist,n+1); idx[n]=i; dist[n]=d;
      }
      int cnt=ArraySize(idx);
      for(int a=0;a<cnt-1;a++) for(int b=a+1;b<cnt;b++) if(dist[b]<dist[a])
      { double td=dist[a];dist[a]=dist[b];dist[b]=td; int ti=idx[a];idx[a]=idx[b];idx[b]=ti; }
      SV4DispZone out[]; ArrayResize(out,0);
      for(int k=0;k<cnt;k++)
      {
         SZone z=g_v4ZoneHistory[idx[k]];
         double lo=MathMin(z.distal,z.proximal), hi=MathMax(z.distal,z.proximal);
         string t=EnumToString(z.type); StringReplace(t,"ZONE_","");
         bool merged=false;
         for(int o=0;o<ArraySize(out);o++)
         {
            double overlap=MathMin(hi,out[o].hi)-MathMax(lo,out[o].lo);
            double minH=MathMin(hi-lo,out[o].hi-out[o].lo);
            bool join=(overlap>0 && overlap>0.5*minH) || (overlap<=0 && atr>0 && -overlap<0.25*atr);
            if(!join) continue;
            out[o].lo=MathMin(out[o].lo,lo); out[o].hi=MathMax(out[o].hi,hi);
            out[o].start=(datetime)MathMin((long)out[o].start,(long)z.timeStart);
            out[o].ids+=","+(string)z.id;
            if(z.score>out[o].score){out[o].score=z.score;out[o].type=t;out[o].fresh=z.isFresh;out[o].tests=z.testCount;}
            merged=true; break;
         }
         if(merged || ArraySize(out)>=InpMaxZonesPerSide) continue;
         // Vùng gần nhất mỗi phía luôn hiện; các vùng sau chỉ hiện khi trong InpMaxZoneDistanceATR.
         if(ArraySize(out)>=1 && atr>0 && InpMaxZoneDistanceATR>0 && dist[k]>InpMaxZoneDistanceATR*atr) continue;
         int m=ArraySize(out); ArrayResize(out,m+1);
         out[m].lo=lo; out[m].hi=hi; out[m].score=z.score; out[m].start=z.timeStart;
         out[m].ids=(string)z.id; out[m].type=t; out[m].fresh=z.isFresh; out[m].tests=z.testCount;
      }
      if(ArraySize(out)>0) info[side]=StringFormat("%s gần nhất %s1: %.2f - %.2f (cách %.2f)",supply?"CUNG":"CẦU",supply?"S":"D",out[0].lo,out[0].hi,supply?MathMax(0.0,out[0].lo-price):MathMax(0.0,price-out[0].hi));
      for(int j=0;j<ArraySize(out);j++)
      {
         string tag=(supply?"S":"D")+(string)(j+1);
         string name=g_prefix+"Z_"+tag;
         ObjectCreate(0,name,OBJ_RECTANGLE,0,out[j].start,out[j].hi,end,out[j].lo);
         ObjectSetInteger(0,name,OBJPROP_COLOR,supply?C'85,28,34':C'20,68,48');
         ObjectSetInteger(0,name,OBJPROP_BACK,true);ObjectSetInteger(0,name,OBJPROP_FILL,true);
         ObjectSetString(0,name,OBJPROP_TOOLTIP,StringFormat("%s H1 %s điểm %d %s T%d\n%.2f - %.2f\nID: %s",
            tag,out[j].type,out[j].score,out[j].fresh?"FRESH":"",out[j].tests,out[j].lo,out[j].hi,out[j].ids));
         if(ShowLabels)
         {
            string lb=g_prefix+"Z_L"+tag;
            ObjectCreate(0,lb,OBJ_TEXT,0,end,supply?out[j].hi:out[j].lo);
            ObjectSetString(0,lb,OBJPROP_TEXT,StringFormat("%s %d %s%s",tag,out[j].score,out[j].type,out[j].fresh?" FRESH":""));
            ObjectSetInteger(0,lb,OBJPROP_ANCHOR,supply?ANCHOR_RIGHT_LOWER:ANCHOR_RIGHT_UPPER);
            ObjectSetInteger(0,lb,OBJPROP_COLOR,supply?clrTomato:clrMediumSeaGreen);
            ObjectSetInteger(0,lb,OBJPROP_FONTSIZE,LabelFont);
            ObjectSetInteger(0,lb,OBJPROP_SELECTABLE,false);
         }
      }
   }
   for(int side=0;side<2;side++)
   {
      string nm=g_prefix+"Z_INFO"+(string)side;
      ObjectCreate(0,nm,OBJ_LABEL,0,0,0);
      ObjectSetInteger(0,nm,OBJPROP_CORNER,CORNER_LEFT_LOWER);
      ObjectSetInteger(0,nm,OBJPROP_ANCHOR,ANCHOR_LEFT_LOWER);
      ObjectSetInteger(0,nm,OBJPROP_XDISTANCE,10);
      ObjectSetInteger(0,nm,OBJPROP_YDISTANCE,side==1?38:20);
      ObjectSetInteger(0,nm,OBJPROP_COLOR,side==1?clrTomato:clrMediumSeaGreen);
      ObjectSetInteger(0,nm,OBJPROP_FONTSIZE,9);
      ObjectSetInteger(0,nm,OBJPROP_SELECTABLE,false);
      ObjectSetString(0,nm,OBJPROP_TEXT,info[side]);
   }
}
void V4RenderZones()
{
   ObjectsDeleteAll(0,g_prefix+"Z_");
   datetime end=iTime(_Symbol,PERIOD_H1,0)+3600*ExtendBars;
   if(InpZoneDisplayMode==0) V4RenderZoneCompact(end); else V4RenderZoneAll(end);
   V4RestoreArrows();
}
void V4ChartControls(int x,int y,int width,int height)
{
   ObjectsDeleteAll(0,g_prefix+"RECOVERY");
   string exportName=g_prefix+"EXPORT";
   if(ObjectFind(0,exportName)<0)ObjectCreate(0,exportName,OBJ_BUTTON,0,0,0);
   ObjectSetInteger(0,exportName,OBJPROP_XDISTANCE,x+width-110);
   ObjectSetInteger(0,exportName,OBJPROP_YDISTANCE,y+height+3);
   ObjectSetInteger(0,exportName,OBJPROP_XSIZE,100);ObjectSetInteger(0,exportName,OBJPROP_YSIZE,20);
   ObjectSetString(0,exportName,OBJPROP_TEXT,"CSV");
   if(ArraySize(g_v4History)>0)
   {
      SV4SymbolSpec spec;if(V4SymbolSpec(_Symbol,spec))
      {SConfirmSignal sig=g_v4History[ArraySize(g_v4History)-1];V4Lots(AccountInfoDouble(ACCOUNT_EQUITY),InpRiskPercent,sig.isBuy,sig.entryMarket,sig.initialSl,spec);}
   }
   string warning=g_v4LedgerWarning!=""?g_v4LedgerWarning:(g_v4RiskWarning!=""?g_v4RiskWarning:g_v4ScoreError);
   string name=g_prefix+"STATUS";
   if(ObjectFind(0,name)<0)ObjectCreate(0,name,OBJ_LABEL,0,0,0);
   ObjectSetInteger(0,name,OBJPROP_XDISTANCE,x);ObjectSetInteger(0,name,OBJPROP_YDISTANCE,y+height+25);
   ObjectSetInteger(0,name,OBJPROP_COLOR,warning!=""?clrTomato:clrSilver);ObjectSetInteger(0,name,OBJPROP_FONTSIZE,8);
   string progress=g_v4HistoryDone?StringFormat("H1/M5 · %d signals · %I64u ms",ArraySize(g_v4History),g_v4ReadyMs):"Lịch sử "+TimeToString(g_v4HistoryCursor)+" / "+TimeToString(TimeCurrent());
   ObjectSetString(0,name,OBJPROP_TEXT,!g_v4HistoryDone?progress:(warning!=""?warning:progress));
   ObjectSetString(0,name,OBJPROP_TOOLTIP,(g_v4HistoryDone?"READY":"REPLAY")+"|"+(string)g_v4ReadyMs+"|"+(string)(long)g_v4HistoryCursor);
}
void V4ChartStep()
{
   if(g_v4IoFailed)return;
   ulong start=GetTickCount64();bool changed=false;
   if(g_v4ReadOnly)
   {
      if(start-g_v4LastReadMs<1000)return;
      g_v4LastReadMs=start;
      if(!V4TryChartWriter())
      {V4ScoreInit();datetime old=g_v4HistoryCursor;if(V4FollowLedger() && V4ZoneSnapshot(false) && old!=g_v4HistoryCursor) {V4RenderZones();V4ScoreInit();if(g_v4HistoryDone && g_v4ReadyMs==0)g_v4ReadyMs=GetTickCount64()-g_v4InitMs;} }
   }
   if(!g_v4ReadOnly)
   {
      MqlTick tick;if(!SymbolInfoTick(_Symbol,tick) || tick.time<=0)return;
      datetime now=tick.time;g_v4Now=now;
      MqlRates bars[];ArraySetAsSeries(bars,false);
      // A bounded prefix; next callback resumes from the committed cursor.
      int n=CopyRates(_Symbol,PERIOD_M5,g_v4HistoryCursor,now,bars);
      if(n<=0)
      {
         V4M2Update(tick,false);
         if(ShowDash)RenderDashboard(tick.bid);else V4ChartControls(DashX,DashY,220,0);
         V4M2Panel();ChartRedraw();return;
      }
      int processed=0;
      for(int i=0;i<n;i++)
      {
         if(bars[i].time<g_v4HistoryCursor)continue;
         bool quiet=bars[i].time<iTime(_Symbol,PERIOD_M5,0) || !g_v4HistoryDone;
         g_v4QuietPlan=quiet;
         bool observed=V4ObserveClosedBar(bars[i].time,quiet?bars[i].time:now,quiet);
         g_v4QuietPlan=false;
         if(!observed)break;
         // Spread rejection is still an evaluated observation, even without a candidate.
         g_v4LastEvaluated=iTime(_Symbol,PERIOD_M5,iBarShift(_Symbol,PERIOD_M5,bars[i].time,false)+1);
         g_v4HistoryCursor=bars[i].time+300;changed=true;processed++;
         if(processed>=32 || GetTickCount64()-start>=50)break;
      }
      g_v4ReplayTime=0;g_v4PublishTime=0;g_v4Now=now;
      if(changed)
      {
         V4SaveState();
         bool done=g_v4HistoryCursor>iTime(_Symbol,PERIOD_M5,0);
         if(done && !g_v4HistoryDone)g_v4ReadyMs=GetTickCount64()-g_v4InitMs;
         if(done && !g_v4HistoryDone)PrintFormat("V403_HISTORY_READY chart=%I64d tf=%s ms=%I64u signals=%d zones=%d",ChartID(),EnumToString(Period()),GetTickCount64()-g_v4InitMs,ArraySize(g_v4History),ArraySize(g_v4ZoneHistory));
         g_v4HistoryDone=done;if(!V4ZoneSnapshot(true)){g_v4IoFailed=true;g_v4LedgerWarning="Không ghi được zone snapshot";}
         if(done){V4M2Update(tick,true);V4RenderZones();}
      }
   }
   // Progress is always visible, even when the main dashboard is disabled.
   if(ShowDash)RenderDashboard(SymbolInfoDouble(_Symbol,SYMBOL_BID));
   else V4ChartControls(DashX,DashY,220,0);
   V4M2Panel();ChartRedraw();
}
#endif
