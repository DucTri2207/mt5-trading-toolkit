#ifndef CHT_V4_LOGGER
#define CHT_V4_LOGGER
bool g_v4ReadOnly=false;
int g_v4GuardFile=INVALID_HANDLE;
long g_v4GuardCandidates=0,g_v4GuardRejected=0;
int g_v4SignalsFile=INVALID_HANDLE, g_v4CandidatesFile=INVALID_HANDLE;
long g_v4Candidates=0, g_v4Published=0, g_v4Blocked=0;
SConfirmSignal g_v4History[];
string g_v4Preset="", g_v4StatePath="",g_v4LedgerWarning="";
const int V4_SIGNAL_COLUMNS=31;

bool V4WriteSignal(int f,const SConfirmSignal &s,const string status)
{
   ResetLastError();
   uint written=FileWrite(f,"V4_M1",g_v4Preset,s.signal_id,status,(long)s.confirm_bar_open,
      (long)s.signal_known_time,(long)s.publish_time,(long)s.order_place_time,
      (long)s.fill_time,(long)s.exit_time,(int)s.isBuy,s.source_zone_id,
      (long)s.zone_known_time,(long)s.sweep_time,DoubleToString(s.source_distal,12),
      DoubleToString(s.source_proximal,12),DoubleToString(s.choch_level,12),
      DoubleToString(s.entry,12),DoubleToString(s.entryMarket,12),DoubleToString(s.entryLimit,12),
      DoubleToString(s.initialSl,12),DoubleToString(s.tp1,12),DoubleToString(s.tp2,12),
      DoubleToString(s.tpMacro,12),DoubleToString(s.sweepPrice,12),s.zoneType,s.zoneScore,
      DoubleToString(s.bePrice,12),DoubleToString(s.ltfAtr,12),DoubleToString(s.arrow_anchor,12),
      (int)InpCompatV301);
   FileFlush(f);
   return written>0 && GetLastError()==0;
}

// Shadow denominator: a fully formed pre-plan candidate with temporal guards disabled.
// Rejected sweeps without a confirmation/valid risk/targets are not candidates.
void V4GuardCandidate(const SConfirmSignal &s)
{
   g_v4GuardCandidates++;
   string reason="";
   if(s.zone_known_time>s.signal_known_time) reason="F1_ZONE_NOT_KNOWN";
   else if(s.sweep_time<s.zone_known_time) reason="F1_SWEEP_BEFORE_KNOWN";
   if(reason=="") return;
   g_v4GuardRejected++;
   if(g_v4GuardFile!=INVALID_HANDLE && !V4WriteSignal(g_v4GuardFile,s,reason)) g_v4IoFailed=true;
}

void V4Candidate(const SConfirmSignal &s,const string reason)
{
   g_v4Candidates++;
   if(reason!="PUBLISHED") g_v4Blocked++;
   if(g_v4CandidatesFile!=INVALID_HANDLE && !V4WriteSignal(g_v4CandidatesFile,s,reason))
      g_v4IoFailed=true;
}

bool V4PersistPublished(const SConfirmSignal &s)
{
   // Fixtures can inspect the detector without opening an account or writing a ledger.
   if(g_v4SignalsFile!=INVALID_HANDLE && !V4WriteSignal(g_v4SignalsFile,s,"PUBLISHED"))
      return false;
   int n=ArraySize(g_v4History);
   ArrayResize(g_v4History,n+1);
   g_v4History[n]=s;
   g_v4Published++;
   return true;
}

string V4LedgerHeader()
{
   return "schema,preset,signal_id,status,confirm_bar_open,signal_known_time,publish_time,order_place_time,fill_time,exit_time,is_buy,source_zone_id,zone_known_time,sweep_bar_open,source_distal,source_proximal,choch_level,entry,entry_market,entry_limit,initial_sl,tp1,tp2,tp_macro,sweep_price,zone_type,zone_score,be_price,ltf_atr,arrow_anchor,compat";
}
bool V4Header(int f)
{
   string expected[];
   int n=StringSplit(V4LedgerHeader(),',',expected);
   if(FileSize(f)==0)
   {
      string line=V4LedgerHeader()+"\r\n";
      return FileWriteString(f,line)>0;
   }
   FileSeek(f,0,SEEK_SET);
   for(int i=0;i<n;i++)
      if(FileIsEnding(f) || FileReadString(f)!=expected[i] || (i<n-1 && FileIsLineEnding(f))) return false;
   return FileIsLineEnding(f);
}

bool V4ReadSignal(int f,SConfirmSignal &s)
{
   string v[];
   ArrayResize(v,V4_SIGNAL_COLUMNS);
   for(int i=0;i<V4_SIGNAL_COLUMNS;i++)
   {
      if(FileIsEnding(f)) return false;
      v[i]=FileReadString(f);
      if(i<V4_SIGNAL_COLUMNS-1 && FileIsLineEnding(f)) return false;
   }
   if(!FileIsLineEnding(f) && !FileIsEnding(f)) return false;
   if(v[0]!="V4_M1" || v[1]!=g_v4Preset || v[3]!="PUBLISHED") return false;
   ZeroMemory(s);
   s.signal_id=v[2]; s.time=s.confirm_bar_open=(datetime)StringToInteger(v[4]);
   s.signal_known_time=(datetime)StringToInteger(v[5]);
   s.publish_time=(datetime)StringToInteger(v[6]);
   s.order_place_time=(datetime)StringToInteger(v[7]);
   s.fill_time=(datetime)StringToInteger(v[8]); s.exit_time=(datetime)StringToInteger(v[9]);
   s.isBuy=(bool)StringToInteger(v[10]); s.zoneId=s.source_zone_id=StringToInteger(v[11]);
   s.zone_known_time=(datetime)StringToInteger(v[12]); s.sweep_time=(datetime)StringToInteger(v[13]);
   s.source_distal=StringToDouble(v[14]); s.source_proximal=StringToDouble(v[15]);
   s.choch_level=StringToDouble(v[16]); s.entry=StringToDouble(v[17]);
   s.entryMarket=StringToDouble(v[18]); s.entryLimit=StringToDouble(v[19]);
   s.sl=s.initialSl=StringToDouble(v[20]); s.tp1=StringToDouble(v[21]);
   s.tp2=StringToDouble(v[22]); s.tpMacro=StringToDouble(v[23]);
   s.sweepPrice=StringToDouble(v[24]); s.zoneType=v[25]; s.zoneScore=(int)StringToInteger(v[26]);
   s.bePrice=StringToDouble(v[27]); s.ltfAtr=StringToDouble(v[28]); s.arrow_anchor=StringToDouble(v[29]);
   double risk=MathAbs(s.entry-s.initialSl);
   if(s.signal_id!=V4SignalId(s) || risk<=0 || s.signal_known_time<=s.confirm_bar_open ||
      s.publish_time<s.signal_known_time) return false;
   s.rr1=MathAbs(s.tp1-s.entry)/risk; s.rr2=MathAbs(s.tp2-s.entry)/risk;
   s.rrMacro=MathAbs(s.tpMacro-s.entry)/risk; s.active=true;
   return true;
}

void V4SaveState()
{
   if(g_v4ReadOnly || g_v4SignalsFile==INVALID_HANDLE) return;
   string temp=g_v4StatePath+".tmp";
   int f=FileOpen(temp,FILE_WRITE|FILE_CSV|FILE_ANSI,',',CP_UTF8);
   if(f==INVALID_HANDLE) { g_v4IoFailed=true; return; }
   uint n=FileWrite(f,g_v4Preset,g_lastSignal.signal_id,(long)g_v4LastEvaluated,
      (int)g_lastSignal.active,DoubleToString(g_lastSignal.sl,12),(int)g_lastSignal.isBeActive,
      DoubleToString(g_lastSignal.maxMfePips,12),(int)g_lastSignal.hitTp1,(int)g_lastSignal.hitTp2,
      (long)g_lastSignalSeenTime,g_lastSignalSeenZone,(int)g_lastSignalSeenBuy,(long)g_lastAlertBar);
   FileFlush(f); FileClose(f);
   if(n==0 || !FileMove(temp,0,g_v4StatePath,FILE_REWRITE)) g_v4IoFailed=true;
}

bool V4RestoreState()
{
   if(!FileIsExist(g_v4StatePath)) return ArraySize(g_v4History)==0;
   int f=FileOpen(g_v4StatePath,FILE_READ|FILE_CSV|FILE_ANSI,',',CP_UTF8);
   if(f==INVALID_HANDLE) return false;
   string preset=FileReadString(f), id=FileReadString(f);
   bool sameId=(StringLen(id)==0 && StringLen(g_lastSignal.signal_id)==0) || id==g_lastSignal.signal_id;
   if(preset!=g_v4Preset || !sameId) { FileClose(f); return false; }
   g_v4LastEvaluated=(datetime)FileReadNumber(f); g_lastSignal.active=(bool)FileReadNumber(f);
   g_lastSignal.sl=FileReadNumber(f); g_lastSignal.isBeActive=(bool)FileReadNumber(f);
   g_lastSignal.maxMfePips=FileReadNumber(f); g_lastSignal.hitTp1=(bool)FileReadNumber(f);
   g_lastSignal.hitTp2=(bool)FileReadNumber(f); g_lastSignalSeenTime=(datetime)FileReadNumber(f);
   // Read integer IDs as strings; a double would lose bits above 2^53.
   g_lastSignalSeenZone=StringToInteger(FileReadString(f));
   g_lastSignalSeenBuy=(bool)FileReadNumber(f); g_lastAlertBar=(datetime)FileReadNumber(f);
   bool ok=FileIsLineEnding(f)||FileIsEnding(f); FileClose(f); return ok;
}

void V4CloseLedger()
{
   V4SaveState();
   if(g_v4SignalsFile!=INVALID_HANDLE) FileClose(g_v4SignalsFile);
   if(g_v4CandidatesFile!=INVALID_HANDLE) FileClose(g_v4CandidatesFile);
   if(g_v4GuardFile!=INVALID_HANDLE) FileClose(g_v4GuardFile);
   g_v4GuardFile=g_v4SignalsFile=g_v4CandidatesFile=INVALID_HANDLE;
}

bool V4LoadLedger(bool &corrupt)
{
   corrupt=false; g_v4Preset=V4Preset();
   ArrayResize(g_v4History,0);ZeroMemory(g_lastSignal);g_v4LastEvaluated=0;
   FolderCreate(InpV4LedgerFolder);
   string base=InpV4LedgerFolder+"\\";
   g_v4StatePath=base+"state_"+V4FileKey()+".csv";
   // One writer per resolved signal configuration; display charts share read snapshots.
   g_v4SignalsFile=FileOpen(base+"signals_"+V4FileKey()+".csv",
      FILE_READ|FILE_WRITE|FILE_CSV|FILE_ANSI|FILE_SHARE_READ,',',CP_UTF8);
   if(g_v4SignalsFile==INVALID_HANDLE) return false;
   if(!V4Header(g_v4SignalsFile)) { Print("V4 ledger header invalid");corrupt=true; return false; }
   while(!FileIsEnding(g_v4SignalsFile))
   {
      SConfirmSignal s;
      if(!V4ReadSignal(g_v4SignalsFile,s))
      {
         Print("V4 ledger row invalid");corrupt=true; return false;
      }
      int n=ArraySize(g_v4History);
      if(n>0 && s.time<g_v4History[n-1].time) {corrupt=true;return false;}
      ArrayResize(g_v4History,n+1); g_v4History[n]=s; g_lastSignal=s;
   }
   ResetLastError();
   if(!V4RestoreState())
   {
      Print("V4 checkpoint inconsistent with its ledger");corrupt=GetLastError()!=5004; return false;
   }
   FileSeek(g_v4SignalsFile,0,SEEK_END);
   g_v4CandidatesFile=FileOpen(base+"candidates_"+V4FileKey()+".csv",
      FILE_READ|FILE_WRITE|FILE_CSV|FILE_ANSI|FILE_SHARE_READ,',',CP_UTF8);
   if(g_v4CandidatesFile==INVALID_HANDLE)
   { FileClose(g_v4SignalsFile); g_v4SignalsFile=INVALID_HANDLE; return false; }
   if(!V4Header(g_v4CandidatesFile)) { corrupt=true; return false; }
   FileSeek(g_v4CandidatesFile,0,SEEK_END);
   g_v4GuardFile=FileOpen(base+"guard_rejects_"+V4FileKey()+".csv",FILE_READ|FILE_WRITE|FILE_CSV|FILE_ANSI|FILE_SHARE_READ,',',CP_UTF8);
   if(g_v4GuardFile==INVALID_HANDLE) return false;
   if(!V4Header(g_v4GuardFile)) { corrupt=true; return false; }
   FileSeek(g_v4GuardFile,0,SEEK_END);
   return true;
}
void V4ReleaseLedgerHandles()
{
   if(g_v4SignalsFile!=INVALID_HANDLE)FileClose(g_v4SignalsFile);
   if(g_v4CandidatesFile!=INVALID_HANDLE)FileClose(g_v4CandidatesFile);
   if(g_v4GuardFile!=INVALID_HANDLE)FileClose(g_v4GuardFile);
   g_v4SignalsFile=g_v4CandidatesFile=g_v4GuardFile=INVALID_HANDLE;
}
bool V4ArchiveFile(string path,string stamp)
{
   if(!FileIsExist(path))return true;
   string archived=path+"_corrupt_"+stamp;
   if(!FileMove(path,0,archived,0)){Print("V4 recovery cannot archive ",path);return false;}
   Print("V4_CORRUPT_ARCHIVED ",archived);return true;
}
bool V4QuarantineLedger()
{
   string base=InpV4LedgerFolder+"\\",key=V4FileKey();
   string stamp=(string)(long)TimeLocal()+"_"+(string)GetMicrosecondCount();
   string names[]={"signals_","state_","candidates_","guard_rejects_"};
   for(int i=0;i<ArraySize(names);i++)
      if(!V4ArchiveFile(base+names[i]+key+".csv",stamp) || !V4ArchiveFile(base+names[i]+key+".csv.tmp",stamp))return false;
   string file;long search=FileFindFirst(base+"score_"+key+"_*.csv*",file);
   if(search!=INVALID_HANDLE)
   {
      bool ok=true;
      do {if(StringFind(file,"_corrupt_")<0 && !V4ArchiveFile(base+file,stamp)){ok=false;break;}}while(FileFindNext(search,file));
      FileFindClose(search);if(!ok)return false;
   }
   if(!V4ArchiveFile(base+"zones_"+key+".bin",stamp))return false;
   ArrayResize(g_v4History,0);ZeroMemory(g_lastSignal);g_v4LastEvaluated=0;
   g_lastSignalSeenTime=0;g_lastSignalSeenZone=-1;g_lastSignalSeenBuy=false;g_lastAlertBar=0;
   g_v4Candidates=g_v4Published=g_v4Blocked=0;
   g_v4LedgerWarning="Đã cách ly ledger/state lỗi; khởi tạo lại.";
   Print("V4_LEDGER_RECOVERED ",key," ",g_v4LedgerWarning);return true;
}
bool V4OpenLedger()
{
   bool corrupt=false;
   if(V4LoadLedger(corrupt))return true;
   V4ReleaseLedgerHandles();
   if(!corrupt)return false;
   if(!V4QuarantineLedger())return false;
   return V4LoadLedger(corrupt);
}

void V4RestoreArrows()
{
   g_v4BatchArrows=true;
   for(int i=0;i<ArraySize(g_v4History);i++)
   {
      SConfirmSignal s=g_v4History[i];
      DrawSignalArrow(s.isBuy,s.time,s.arrow_anchor,s.ltfAtr);
      V4DrawSourceZone(s);
   }
   g_v4BatchArrows=false; ChartRedraw(0);
}
#endif
