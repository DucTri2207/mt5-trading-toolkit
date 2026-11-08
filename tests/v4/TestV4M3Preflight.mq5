#property strict
long seen=0;
datetime first=0,last=0;
void SaveProbe(bool tester,int reason)
{
   string folder="CanHoTroV4_M3_20261102";
   FolderCreate(folder,FILE_COMMON);
   int f=FileOpen(folder+"\\preflight_"+(tester?"tester":"outside")+".json",FILE_WRITE|FILE_TXT|FILE_ANSI|FILE_COMMON);
   if(f==INVALID_HANDLE) return;
   FileWriteString(f,StringFormat("{\"tester\":%s,\"ticks\":%I64d,\"first\":%I64d,\"last\":%I64d,\"reason\":%d,\"build\":%d,\"symbol\":\"%s\",\"server\":\"%s\",\"account_currency\":\"%s\",\"tick_size\":%.10f,\"tick_value\":%.10f,\"contract_size\":%.10f,\"orders_sent\":0}",
      tester?"true":"false",seen,(long)first,(long)last,reason,(int)TerminalInfoInteger(TERMINAL_BUILD),_Symbol,
      AccountInfoString(ACCOUNT_SERVER),AccountInfoString(ACCOUNT_CURRENCY),SymbolInfoDouble(_Symbol,SYMBOL_TRADE_TICK_SIZE),
      SymbolInfoDouble(_Symbol,SYMBOL_TRADE_TICK_VALUE_LOSS),SymbolInfoDouble(_Symbol,SYMBOL_TRADE_CONTRACT_SIZE)));
   FileClose(f);
}
int OnInit()
{
   if(!MQLInfoInteger(MQL_TESTER)) { SaveProbe(false,INIT_FAILED); Print("V4_M3_OUTSIDE_TESTER_REJECTED"); return INIT_FAILED; }
   Print("V4_M3_PREFLIGHT_STARTED no orders, no strategy P&L"); return INIT_SUCCEEDED;
}
void OnTick()
{
   MqlTick tick; if(!SymbolInfoTick(_Symbol,tick)) return;
   if(seen==0) first=tick.time;
   last=tick.time; seen++;
   if(seen>=1000) TesterStop();
}
void OnDeinit(const int reason)
{
   SaveProbe((bool)MQLInfoInteger(MQL_TESTER),reason);
   PrintFormat("V4_M3_PREFLIGHT_DONE ticks=%I64d",seen);
}
