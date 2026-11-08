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
void V4RenderZones()
{
   ObjectsDeleteAll(0,g_prefix+"Z_");
   datetime end=iTime(_Symbol,PERIOD_H1,0)+3600*ExtendBars;
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
