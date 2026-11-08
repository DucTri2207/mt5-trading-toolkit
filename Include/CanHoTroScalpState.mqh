#ifndef CAN_HO_TRO_SCALP_STATE
#define CAN_HO_TRO_SCALP_STATE
#include "CanHoTroScalpPlan.mqh"
// Fixed-layout plan plus a version/config header. No account identifiers or secrets.
bool CHTSaveState(const string path,const string config,const CHTPlan &plan,
                  const datetime watermark,const long lastMsc,const double bid,const double ask,
                  const string &seen[])
{
   string temp=path+".tmp";
   int f=FileOpen(temp,FILE_WRITE|FILE_BIN|FILE_ANSI);
   if(f==INVALID_HANDLE)return false;
   FileWriteInteger(f,0x43485431);FileWriteInteger(f,StringLen(config));FileWriteString(f,config,StringLen(config));
   FileWriteLong(f,(long)watermark);FileWriteLong(f,lastMsc);FileWriteDouble(f,bid);FileWriteDouble(f,ask);
   uint written=FileWriteStruct(f,plan);FileWriteInteger(f,ArraySize(seen));
   for(int i=0;i<ArraySize(seen);i++){FileWriteInteger(f,StringLen(seen[i]));FileWriteString(f,seen[i],StringLen(seen[i]));}
   FileFlush(f);FileClose(f);
   if(written!=sizeof(CHTPlan))return false;
   return FileMove(temp,0,path,FILE_REWRITE);
}
bool CHTLoadState(const string path,const string config,CHTPlan &plan,
                  datetime &watermark,long &lastMsc,double &bid,double &ask,string &seen[])
{
   int f=FileOpen(path,FILE_READ|FILE_BIN|FILE_ANSI);if(f==INVALID_HANDLE)return false;
   bool valid=FileReadInteger(f)==0x43485431;int len=FileReadInteger(f);
   if(len<1 || len>1024){FileClose(f);return false;}
   string saved=FileReadString(f,len);valid=valid && saved==config;
   datetime wm=(datetime)FileReadLong(f);long msc=FileReadLong(f);
   double b=FileReadDouble(f),a=FileReadDouble(f);CHTPlan loaded;
   uint read=FileReadStruct(f,loaded);int count=FileReadInteger(f);
   if(!valid || read!=sizeof(CHTPlan) || count<0 || count>100000){FileClose(f);return false;}
   string keys[];ArrayResize(keys,count);
   for(int i=0;i<count;i++)
   {
      len=FileReadInteger(f);if(len<1 || len>1024){FileClose(f);return false;}
      keys[i]=FileReadString(f,len);
   }
   bool complete=FileTell(f)==FileSize(f);FileClose(f);if(!complete)return false;
   plan=loaded;watermark=wm;lastMsc=msc;bid=b;ask=a;ArrayCopy(seen,keys);return true;
}
#endif
