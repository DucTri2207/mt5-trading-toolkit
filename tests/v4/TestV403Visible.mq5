#property strict
void OnStart()
{
 if(StringFind(TerminalInfoString(TERMINAL_DATA_PATH),"20261102_m3a_v1\\portable_terminal")<0)return;
 ENUM_TIMEFRAMES frames[2]={PERIOD_M1,PERIOD_M5};
 for(int k=0;k<2;k++)
 {
  long chart=0;for(long c=ChartFirst();c>=0;c=ChartNext(c))if(ChartSymbol(c)=="XAUUSD" && ChartPeriod(c)==frames[k] && ObjectFind(c,"DucTri_V4_STATUS")>=0){chart=c;break;}
  if(chart==0){Print("V403_VISIBLE_MISSING");return;}
  datetime latest=0;for(int i=0;i<ObjectsTotal(chart);i++){string name=ObjectName(chart,i);if(StringFind(name,"DucTri_V4_SIG_")==0)latest=MathMax(latest,(datetime)ObjectGetInteger(chart,name,OBJPROP_TIME));}
  ChartSetInteger(chart,CHART_AUTOSCROLL,false);ChartSetInteger(chart,CHART_BRING_TO_TOP,true);
  ChartNavigate(chart,CHART_END,-MathMax(0,iBarShift("XAUUSD",frames[k],latest,false)-35));ChartRedraw(chart);Sleep(2000);
  int f=FileOpen("v403_final_chart\\visible_stage.txt",FILE_WRITE|FILE_TXT|FILE_ANSI);FileWriteString(f,(string)k);FileClose(f);
  for(int w=0;w<600 && !IsStopped() && !FileIsExist("v403_final_chart\\visible_ack_"+(string)k+".flag");w++)Sleep(200);
 }
 Print("V403_VISIBLE_DONE");
}
