#property strict
#include "../../Include/FabioOrderflowBridge.mqh"

int checks=0,failures=0;
string failed="";
void Check(const bool ok,const string name)
{checks++;if(!ok){failures++;failed+=name+"; ";Print("FAIL ",name);}}

const string FOLDER="fabio_orderflow_fixture\\";
const string LONG_ROW="fabio_orderflow_v1,EXCHANGE_TRADES_BBO,fixture_import,NQZ5,1760000000,TREND,1,22000,21998,22010,21999.75,22000.25,22010,21980,21995";
const string SHORT_ROW="fabio_orderflow_v1,EXCHANGE_TRADES_BBO,fixture_import,NQZ5,1760000001,REVERSION,-1,22000,22002,21990,21999.75,22000.25,21990,21985,22015";

void WriteCase(const string name,const string rows,const string heartbeat)
{
   int f=FileOpen(FOLDER+name,FILE_WRITE|FILE_TXT|FILE_ANSI,0,CP_UTF8);
   FileWriteString(f,FOL_HEADER+"\r\n"+rows);FileClose(f);
   f=FileOpen(FOLDER+name+".status.csv",FILE_WRITE|FILE_TXT|FILE_ANSI,0,CP_UTF8);
   FileWriteString(f,FOL_STATUS_HEADER+"\r\n"+heartbeat+"\r\n");FileClose(f);
}

void OnStart()
{
   FolderCreate("fabio_orderflow_fixture");
   FOLSignal row,rows[];string error,raw[],kind;long lastEvent;
   Check(FOLParse(LONG_ROW,"NQZ5","fixture_import",false,row,error),"parse long");
   Check(row.direction==1 && row.knownAt==1760000000 && row.reference==22000 && row.stop==21998,"long exact values");
   Check(FOLParse(SHORT_ROW,"NQZ5","fixture_import",false,row,error),"parse short");
   Check(row.direction==-1 && row.target==21990,"short exact values");
   Check(!FOLParse(LONG_ROW,"GCZ5","fixture_import",false,row,error),"reject contract mismatch");
   Check(!FOLParse(LONG_ROW,"NQZ5","other",false,row,error),"reject dataset mismatch");
   string changed=LONG_ROW;StringReplace(changed,"EXCHANGE_TRADES_BBO","SYNTHETIC_FIXTURE");
   Check(!FOLParse(changed,"NQZ5","fixture_import",false,row,error),"reject synthetic default");
   Check(FOLParse(changed,"NQZ5","fixture_import",true,row,error),"explicit synthetic fixture allowed");
   changed=LONG_ROW;StringReplace(changed,"TREND,1,","TREND,0,");
   Check(!FOLParse(changed,"NQZ5","fixture_import",false,row,error),"reject direction zero");
   changed=LONG_ROW;StringReplace(changed,",21998,22010,",",22002,22010,");
   Check(!FOLParse(changed,"NQZ5","fixture_import",false,row,error),"reject inverted stop");
   changed=LONG_ROW;StringReplace(changed,",22000,21998,",",NaN,21998,");
   Check(!FOLParse(changed,"NQZ5","fixture_import",false,row,error),"reject NaN");
   double value;
   Check(!FOLReal("22000garbage",value),"reject partial number");
   Check(FOLReal("2.2e4",value) && value==22000,"exponent number");
   Check(!FOLReal("1e+",value),"reject incomplete exponent");
   string accepted[],next[];ArrayResize(accepted,1);accepted[0]=LONG_ROW;
   ArrayResize(next,2);next[0]=LONG_ROW;next[1]=SHORT_ROW;
   Check(FOLPrefix(accepted,next,error),"append-only prefix");
   next[0]=SHORT_ROW;Check(!FOLPrefix(accepted,next,error),"reject history rewrite");
   ArrayResize(next,0);Check(!FOLPrefix(accepted,next,error),"reject history truncation");
   WriteCase("valid.csv",LONG_ROW+"\r\n"+SHORT_ROW+"\r\n","fabio_orderflow_v1,EXCHANGE_TRADES_BBO,fixture_import,NQZ5,1760000002,2");
   Check(FOLRead(FOLDER+"valid.csv",false,"NQZ5","fixture_import",false,1760000010,120,100,rows,raw,kind,lastEvent,error),"read valid files");
   Check(ArraySize(rows)==2 && lastEvent==1760000002 && kind=="EXCHANGE_TRADES_BBO","native file import exact");
   WriteCase("empty.csv","","fabio_orderflow_v1,EXCHANGE_TRADES_BBO,fixture_import,NQZ5,1760000002,0");
   Check(FOLRead(FOLDER+"empty.csv",false,"NQZ5","fixture_import",false,1760000010,120,100,rows,raw,kind,lastEvent,error) && ArraySize(rows)==0,"valid no-signal heartbeat");
   Check(!FOLRead(FOLDER+"valid.csv",false,"NQZ5","fixture_import",false,1760001000,120,100,rows,raw,kind,lastEvent,error),"reject stale live feed");
   Check(FOLRead(FOLDER+"valid.csv",false,"NQZ5","fixture_import",false,1760001000,-1,100,rows,raw,kind,lastEvent,error),"historical replay accepts old event");
   Check(!FOLRead(FOLDER+"valid.csv",false,"NQZ5","fixture_import",false,1759999900,-1,100,rows,raw,kind,lastEvent,error),"reject future signal");
   WriteCase("count.csv",LONG_ROW+"\r\n","fabio_orderflow_v1,EXCHANGE_TRADES_BBO,fixture_import,NQZ5,1760000002,2");
   Check(!FOLRead(FOLDER+"count.csv",false,"NQZ5","fixture_import",false,1760000010,120,100,rows,raw,kind,lastEvent,error),"reject incomplete publication");
   Check(!FOLRead(FOLDER+"missing.csv",false,"NQZ5","fixture_import",false,1760000010,120,100,rows,raw,kind,lastEvent,error),"reject missing source");
   WriteCase("unsorted.csv",SHORT_ROW+"\r\n"+LONG_ROW+"\r\n","fabio_orderflow_v1,EXCHANGE_TRADES_BBO,fixture_import,NQZ5,1760000002,2");
   Check(!FOLRead(FOLDER+"unsorted.csv",false,"NQZ5","fixture_import",false,1760000010,120,100,rows,raw,kind,lastEvent,error),"reject unsorted signal times");
   int f=FileOpen(FOLDER+"result.json",FILE_WRITE|FILE_TXT|FILE_ANSI,0,CP_UTF8);
   FileWriteString(f,StringFormat("{\"checks\":%d,\"failures\":%d,\"failed\":\"%s\",\"kind\":\"native parser fixtures, not market evidence\"}",checks,failures,failed));FileClose(f);
   Print("FABIO_BRIDGE_CHECKS ",checks," FAILURES ",failures);
}
