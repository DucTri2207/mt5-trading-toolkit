#property strict

void OnStart()
{
   FolderCreate("nasdaq_cache_export");
   if(!SymbolSelect("USTEC",true))return;
   MqlTick ticks[];ResetLastError();
   int count=CopyTicksRange("USTEC",ticks,COPY_TICKS_ALL,(ulong)D'2026.10.01'*1000,(ulong)D'2026.10.31'*1000-1);
   int error=GetLastError();
   string folder="nasdaq_cache_export\\";
   int f=FileOpen(folder+"ticks.status.json",FILE_WRITE|FILE_TXT|FILE_ANSI);
   FileWriteString(f,StringFormat("{\"rows\":%d,\"error\":%d,\"range\":\"2026-10-01 through 2026-10-30 server clock\"}",count,error));FileClose(f);
   if(count<=0)return;
   f=FileOpen(folder+"ticks.csv",FILE_WRITE|FILE_CSV|FILE_ANSI,',');
   for(int i=0;i<count;i++)FileWrite(f,ticks[i].time_msc,DoubleToString(ticks[i].bid,8),DoubleToString(ticks[i].ask,8),ticks[i].flags);
   FileClose(f);
}
