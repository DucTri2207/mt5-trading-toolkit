#property strict
long charts[7];
ENUM_TIMEFRAMES frames[7]={PERIOD_M1,PERIOD_M5,PERIOD_M15,PERIOD_M30,PERIOD_H1,PERIOD_H4,PERIOD_D1};
string tags[7]={"M1","M5","M15","M30","H1","H4","D1"};
bool Ready(long c)
{
   for(int i=0;i<1800;i++)
   {
      if(StringFind(ObjectGetString(c,"DucTri_V4_STATUS",OBJPROP_TOOLTIP),"READY|")==0)return true;
      if(IsStopped() || FileIsExist("v403_chart\\abort.flag"))return false;
      Sleep(500);
   }
   return false;
}
string Flat(string value){StringReplace(value,"\r","");StringReplace(value,"\n"," | ");StringReplace(value,",",";");return value;}
void Capture(long c,string stage)
{
   int f=FileOpen("v403_chart\\"+stage+"_objects.csv",FILE_WRITE|FILE_CSV|FILE_ANSI,',',CP_UTF8);
   FileWrite(f,"name","type","time0","price0","time1","price1","tooltip","text");
   datetime latest=0;int arrows=0,zones=0,stats=0;
   for(int j=0;j<ObjectsTotal(c);j++)
   {
      string name=ObjectName(c,j);
      if(StringFind(name,"DucTri_V4_")!=0)continue;
      if(StringFind(name,"DucTri_V4_SIG_")==0){arrows++;latest=MathMax(latest,(datetime)ObjectGetInteger(c,name,OBJPROP_TIME));}
      if(StringFind(name,"DucTri_V4_Z_")==0)zones++;
      if(StringFind(name,"DucTri_V4_M2_")==0)stats++;
      FileWrite(f,name,ObjectGetInteger(c,name,OBJPROP_TYPE),(long)ObjectGetInteger(c,name,OBJPROP_TIME,0),ObjectGetDouble(c,name,OBJPROP_PRICE,0),(long)ObjectGetInteger(c,name,OBJPROP_TIME,1),ObjectGetDouble(c,name,OBJPROP_PRICE,1),Flat(ObjectGetString(c,name,OBJPROP_TOOLTIP)),Flat(ObjectGetString(c,name,OBJPROP_TEXT)));
   }
   FileClose(f);
   f=FileOpen("v403_chart\\stages.csv",FILE_READ|FILE_WRITE|FILE_CSV|FILE_ANSI,',',CP_UTF8);FileSeek(f,0,SEEK_END);
   FileWrite(f,stage,(int)ChartPeriod(c),arrows,zones,stats,ChartIndicatorsTotal(c,0),ObjectGetString(c,"DucTri_V4_STATUS",OBJPROP_TEXT),ObjectGetString(c,"DucTri_V4_STATUS",OBJPROP_TOOLTIP));FileClose(f);
   ChartSetInteger(c,CHART_AUTOSCROLL,false);ChartSetInteger(c,CHART_SCALE,2);
   if(latest>0)
   {
      MqlRates load[];CopyRates(ChartSymbol(c),ChartPeriod(c),latest-7*86400,TimeCurrent(),load);
      int shift=-1;for(int w=0;w<100;w++){shift=iBarShift(ChartSymbol(c),ChartPeriod(c),latest,false);if(shift>=0)break;Sleep(100);}
      ChartRedraw(c);Sleep(500);
      bool nav=ChartNavigate(c,CHART_END,-MathMax(0,shift-35));
      PrintFormat("V403_NAV stage=%s shift=%d nav=%s visible=%I64d",stage,shift,nav?"yes":"no",ChartGetInteger(c,CHART_FIRST_VISIBLE_BAR));
   }
   ChartSetInteger(c,CHART_BRING_TO_TOP,true);Sleep(500);ChartRedraw(c);
   ChartScreenShot(c,"v403_chart\\"+stage+".png",1400,900,ALIGN_RIGHT);
   PrintFormat("V403_CAPTURE %s arrows=%d zones=%d stats=%d",stage,arrows,zones,stats);
}
void Flag(string name){int f=FileOpen("v403_chart\\"+name,FILE_WRITE|FILE_TXT);FileWriteString(f,"ready");FileClose(f);}
void OnStart()
{
   if(StringFind(TerminalInfoString(TERMINAL_DATA_PATH),"20261102_m3a_v1\\portable_terminal")<0){Print("V403_WRONG_TERMINAL");return;}
   FolderCreate("v403_chart");
   bool restart=FileIsExist("v403_chart\\restart.flag");
   if(!restart)
   {
      for(long c=ChartFirst();c>=0;c=ChartNext(c))
         for(int j=ChartIndicatorsTotal(c,0)-1;j>=0;j--)
         {string name=ChartIndicatorName(c,0,j);if(StringFind(name,"duc_tri_can_ho_tro_v4")>=0)ChartIndicatorDelete(c,0,name);}
      Sleep(1500);
   }
   int f=FileOpen("v403_chart\\stages.csv",restart?FILE_READ|FILE_WRITE|FILE_CSV|FILE_ANSI:FILE_WRITE|FILE_CSV|FILE_ANSI,',',CP_UTF8);
   if(!restart)FileWrite(f,"stage","period","arrows","zones","stats_objects","indicators","status","init_meta");FileClose(f);
   ulong begun=GetTickCount64();
   for(int k=0;k<7;k++)
   {
      charts[k]=0;
      if(restart)
         for(long c=ChartFirst();c>=0;c=ChartNext(c))if(ChartSymbol(c)=="XAUUSD" && ChartPeriod(c)==frames[k] && ChartIndicatorsTotal(c,0)>0){charts[k]=c;break;}
      if(charts[k]==0){charts[k]=ChartOpen("XAUUSD",frames[k]);Print("V403_APPLY tf=",tags[k]," ok=",ChartApplyTemplate(charts[k],"v403.tpl")," err=",GetLastError());}
   }
   for(int k=0;k<7;k++)
   {
      if(!Ready(charts[k])){Print("V403_NOT_READY ",tags[k]);Flag("failed.flag");return;}
      PrintFormat("V403_READY tf=%s ms=%I64u",tags[k],GetTickCount64()-begun);
   }
   Sleep(3000);
   for(int k=0;k<7;k++)Capture(charts[k],tags[k]+(restart?"_restart":"_first"));
   if(!restart)
   {
      ChartSetSymbolPeriod(charts[0],"XAUUSD",PERIOD_H4);Sleep(2000);Capture(charts[0],"M1_to_H4");
      ChartSetSymbolPeriod(charts[0],"XAUUSD",PERIOD_M1);Sleep(2000);Capture(charts[0],"M1_return");
      string name=ChartIndicatorName(charts[0],0,0);ChartIndicatorDelete(charts[0],0,name);Sleep(1000);
      ChartApplyTemplate(charts[0],"v403.tpl");Sleep(3000);Capture(charts[0],"M1_reattach");
   }
   Flag(restart?"restart_done.flag":"done.flag");Print("V403_CHART_DONE");
}
