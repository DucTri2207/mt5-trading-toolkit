#property strict

void OnStart()
{
   string folder="nasdaq_cache_export\\";FolderCreate("nasdaq_cache_export");
   int progress=FileOpen(folder+"probe.json",FILE_WRITE|FILE_TXT|FILE_ANSI);
   bool exists=SymbolSelect("USTEC",true);
   FileWriteString(progress,StringFormat("{\"symbols\":%d,\"ustec_exists\":%s,\"digits\":%d,\"point\":%.8f,\"tick_size\":%.8f,\"contract_size\":%.8f}",
      SymbolsTotal(false),exists?"true":"false",(int)SymbolInfoInteger("USTEC",SYMBOL_DIGITS),SymbolInfoDouble("USTEC",SYMBOL_POINT),
      SymbolInfoDouble("USTEC",SYMBOL_TRADE_TICK_SIZE),SymbolInfoDouble("USTEC",SYMBOL_TRADE_CONTRACT_SIZE)));
   FileClose(progress);if(!exists)return;
   for(int year=2022;year<=2026;year++)
   {
      datetime from=StringToTime(IntegerToString(year)+".01.01");
      datetime until=year==2026?D'2026.10.31':StringToTime(IntegerToString(year+1)+".01.01");
      MqlRates bars[];ResetLastError();int count=CopyRates("USTEC",PERIOD_M1,from,until-1,bars);int error=GetLastError();
      int f=FileOpen(folder+IntegerToString(year)+".status.json",FILE_WRITE|FILE_TXT|FILE_ANSI);
      FileWriteString(f,StringFormat("{\"year\":%d,\"rows\":%d,\"error\":%d}",year,count,error));FileClose(f);
      if(count<=0)continue;
      f=FileOpen(folder+IntegerToString(year)+".csv",FILE_WRITE|FILE_CSV|FILE_ANSI,',');
      for(int i=0;i<count;i++)FileWrite(f,(long)bars[i].time,DoubleToString(bars[i].open,8),DoubleToString(bars[i].high,8),
         DoubleToString(bars[i].low,8),DoubleToString(bars[i].close,8),bars[i].spread,bars[i].tick_volume);
      FileClose(f);Print("EXPORT_YEAR ",year," ROWS ",count);
   }
}
