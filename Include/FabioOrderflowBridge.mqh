#ifndef FABIO_ORDERFLOW_BRIDGE_MQH
#define FABIO_ORDERFLOW_BRIDGE_MQH

const string FOL_SCHEMA="fabio_orderflow_v1";
const string FOL_HEADER="schema_version,source_kind,dataset_id,contract,known_at_utc,model,direction,reference_price,stop,target,lvn_low,lvn_high,poc,balance_low,balance_high";
const string FOL_STATUS_HEADER="schema_version,source_kind,dataset_id,contract,last_event_utc,signal_rows";

struct FOLSignal
{
   string sourceKind,dataset,contract,model;
   long knownAt;
   int direction;
   double reference,stop,target,lvnLow,lvnHigh,poc,balanceLow,balanceHigh;
};

bool FOLLong(const string value,long &out)
{
   int n=StringLen(value);if(n==0 || n>18)return false;
   for(int i=0;i<n;i++){ushort c=StringGetCharacter(value,i);if(c<'0' || c>'9')return false;}
   out=StringToInteger(value);return true;
}

bool FOLReal(const string value,double &out)
{
   int n=StringLen(value),digits=0,dots=0,exponent=-1;
   if(n==0)return false;
   for(int i=0;i<n;i++)
   {
      ushort c=StringGetCharacter(value,i);
      if(c>='0' && c<='9'){digits++;continue;}
      if((c=='+' || c=='-') && (i==0 || i==exponent+1))continue;
      if(c=='.' && exponent<0 && dots==0){dots++;continue;}
      if((c=='e' || c=='E') && exponent<0 && digits>0)
      {exponent=i;digits=0;continue;}
      return false;
   }
   if(digits==0)return false;
   out=StringToDouble(value);return MathIsValidNumber(out) && out>0;
}

string FOLWithoutBOM(string line)
{
   if(StringLen(line)>0 && StringGetCharacter(line,0)==65279)line=StringSubstr(line,1);
   return line;
}

bool FOLSource(const string value,const bool allowFixture)
{return value=="EXCHANGE_TRADES_BBO" || (allowFixture && value=="SYNTHETIC_FIXTURE");}

bool FOLParse(const string line,const string contract,const string dataset,const bool allowFixture,FOLSignal &out,string &error)
{
   string a[];int n=StringSplit(line,',',a);
   if(n!=15){error="CSV column count";return false;}
   if(a[0]!=FOL_SCHEMA){error="Unknown schema";return false;}
   if(!FOLSource(a[1],allowFixture)){error="Unverified or synthetic source";return false;}
   if(a[2]!=dataset || dataset==""){error="Dataset mismatch";return false;}
   if(a[3]!=contract || contract==""){error="Contract mismatch";return false;}
   if(!FOLLong(a[4],out.knownAt) || out.knownAt<946684800){error="Invalid signal UTC time";return false;}
   if(a[5]!="TREND" && a[5]!="REVERSION"){error="Unknown model";return false;}
   if(a[6]!="1" && a[6]!="-1"){error="Invalid direction";return false;}
   out.sourceKind=a[1];out.dataset=a[2];out.contract=a[3];out.model=a[5];out.direction=(int)StringToInteger(a[6]);
   if(!FOLReal(a[7],out.reference) || !FOLReal(a[8],out.stop) || !FOLReal(a[9],out.target) ||
      !FOLReal(a[10],out.lvnLow) || !FOLReal(a[11],out.lvnHigh) || !FOLReal(a[12],out.poc) ||
      !FOLReal(a[13],out.balanceLow) || !FOLReal(a[14],out.balanceHigh))
   {error="Invalid numeric level";return false;}
   if(out.direction*(out.reference-out.stop)<=0 || out.direction*(out.target-out.reference)<=0)
   {error="Stop or target on wrong side";return false;}
   if(out.lvnLow>out.lvnHigh || out.balanceLow>=out.balanceHigh)
   {error="Inverted LVN or balance";return false;}
   error="";return true;
}

bool FOLPrefix(const string &accepted[],const string &candidate[],string &error)
{
   if(ArraySize(candidate)<ArraySize(accepted)){error="Historical signal truncation";return false;}
   for(int i=0;i<ArraySize(accepted);i++)
      if(accepted[i]!=candidate[i]){error="Historical signal rewrite";return false;}
   return true;
}

bool FOLRead(const string path,const bool common,const string contract,const string dataset,
             const bool allowFixture,const long utcNow,const int maxAgeSeconds,const int maxRows,
             FOLSignal &rows[],string &raw[],string &sourceKind,long &lastEvent,string &error)
{
   ArrayResize(rows,0);ArrayResize(raw,0);sourceKind="";lastEvent=0;
   if(path=="" || StringFind(path,"..")>=0 || StringFind(path,":")>=0 || maxRows<1)
   {error="Invalid source path or row limit";return false;}
   int flags=FILE_READ|FILE_TXT|FILE_ANSI|FILE_SHARE_READ|FILE_SHARE_WRITE;
   if(common)flags|=FILE_COMMON;
   int f=FileOpen(path,flags,0,CP_UTF8);
   if(f==INVALID_HANDLE){error="DATA REQUIRED: signal CSV missing";return false;}
   string header=FOLWithoutBOM(FileReadString(f));
   if(header!=FOL_HEADER){FileClose(f);error="Signal header mismatch";return false;}
   while(!FileIsEnding(f))
   {
      string line=FileReadString(f);if(line=="")continue;
      int n=ArraySize(rows);
      if(n>=maxRows){FileClose(f);error="Signal row limit exceeded";return false;}
      FOLSignal row;
      if(!FOLParse(line,contract,dataset,allowFixture,row,error)){FileClose(f);return false;}
      if(row.knownAt>utcNow+5){FileClose(f);error="Future signal rejected";return false;}
      if(n>0 && (row.knownAt<rows[n-1].knownAt || row.sourceKind!=rows[0].sourceKind))
      {FileClose(f);error="Unsorted or mixed signal source";return false;}
      ArrayResize(rows,n+1,256);ArrayResize(raw,n+1,256);rows[n]=row;raw[n]=line;
   }
   FileClose(f);
   f=FileOpen(path+".status.csv",flags,0,CP_UTF8);
   if(f==INVALID_HANDLE){error="DATA REQUIRED: event heartbeat missing";return false;}
   header=FOLWithoutBOM(FileReadString(f));
   string line=FileReadString(f),a[];
   if(header!=FOL_STATUS_HEADER || StringSplit(line,',',a)!=6)
   {FileClose(f);error="Heartbeat header or column count";return false;}
   while(!FileIsEnding(f))
      if(FileReadString(f)!=""){FileClose(f);error="Multiple heartbeat records";return false;}
   FileClose(f);
   long count;
   if(a[0]!=FOL_SCHEMA || !FOLSource(a[1],allowFixture) || a[2]!=dataset || dataset=="" || a[3]!=contract || contract=="")
   {error="Heartbeat source or mapping mismatch";return false;}
   if(!FOLLong(a[4],lastEvent) || lastEvent<946684800 || lastEvent>utcNow+5 || !FOLLong(a[5],count))
   {error="Invalid event heartbeat";return false;}
   int n=ArraySize(rows);
   if(count!=n || (n>0 && (a[1]!=rows[0].sourceKind || lastEvent<rows[n-1].knownAt)))
   {error="CSV and heartbeat inconsistent";return false;}
   if(maxAgeSeconds>=0 && utcNow-lastEvent>maxAgeSeconds)
   {error="STALE event feed";return false;}
   sourceKind=a[1];error="";return true;
}

#endif
