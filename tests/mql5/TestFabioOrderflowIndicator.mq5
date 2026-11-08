#property strict
#property tester_indicator "duc_tri_fabio_orderflow_lab.ex5"

int checks=0,failures=0;
string failed="";
void Check(const bool ok,const string name)
{checks++;if(!ok){failures++;failed+=name+"; ";Print("FAIL ",name);}}

void OnStart()
{
   string symbol="FOL_NQ_FIXTURE",dataset="indicator_fixture_only";
   string file="DucTriLab\\Fabio\\native_indicator_fixture.csv";
   FolderCreate("DucTriLab",FILE_COMMON);FolderCreate("DucTriLab\\Fabio",FILE_COMMON);
   int f=FileOpen(file,FILE_WRITE|FILE_TXT|FILE_ANSI|FILE_COMMON,0,CP_UTF8);
   FileWriteString(f,"schema_version,source_kind,dataset_id,contract,known_at_utc,model,direction,reference_price,stop,target,lvn_low,lvn_high,poc,balance_low,balance_high\r\n");
   FileWriteString(f,"fabio_orderflow_v1,SYNTHETIC_FIXTURE,"+dataset+",NQZ5,1760000100,TREND,1,22000,21998,22010,21999.75,22000.25,22010,21980,21995\r\n");
   FileWriteString(f,"fabio_orderflow_v1,SYNTHETIC_FIXTURE,"+dataset+",NQZ5,1760000220,REVERSION,-1,22000,22002,21990,21999.75,22000.25,21990,21985,22015\r\n");FileClose(f);
   f=FileOpen(file+".status.csv",FILE_WRITE|FILE_TXT|FILE_ANSI|FILE_COMMON,0,CP_UTF8);
   FileWriteString(f,"schema_version,source_kind,dataset_id,contract,last_event_utc,signal_rows\r\n");
   FileWriteString(f,"fabio_orderflow_v1,SYNTHETIC_FIXTURE,"+dataset+",NQZ5,1760001720,2\r\n");FileClose(f);
   if(!SymbolInfoInteger(symbol,SYMBOL_CUSTOM))CustomSymbolCreate(symbol,"FabioFixtures");
   CustomSymbolSetInteger(symbol,SYMBOL_DIGITS,2);
   CustomSymbolSetDouble(symbol,SYMBOL_POINT,.01);CustomSymbolSetDouble(symbol,SYMBOL_TRADE_TICK_SIZE,.25);
   MqlRates rates[];ArrayResize(rates,30);
   for(int i=0;i<30;i++)
   {
      ZeroMemory(rates[i]);rates[i].time=(datetime)(1759999980+i*60);
      rates[i].open=22000;rates[i].high=22012;rates[i].low=21988;rates[i].close=22000+i*.25;
      rates[i].tick_volume=100;rates[i].real_volume=100;
   }
   Check(CustomRatesUpdate(symbol,rates)==30,"create 30 custom fixture bars");
   Check(SymbolSelect(symbol,true),"select custom fixture symbol");
   long chart=ChartOpen(symbol,PERIOD_M1);
   int handle=iCustom(symbol,PERIOD_M1,"duc_tri_fabio_orderflow_lab",file,dataset,"NQZ5",symbol,true,true,0,true,120,true,100,1,chart);
   Check(handle!=INVALID_HANDLE,"load actual iCustom bridge");
   double values[];int copied=0;
   for(int i=0;i<30;i++){copied=CopyBuffer(handle,0,0,30,values);if(copied==30 && values[2]==22000)break;Sleep(100);}
   Check(copied==30,"actual indicator calculated buffers");
   int buyShift=iBarShift(symbol,PERIOD_M1,(datetime)1760000100,false);
   int sellShift=iBarShift(symbol,PERIOD_M1,(datetime)1760000220,false);
   double one[];
   Check(CopyBuffer(handle,0,buyShift,1,one)==1 && one[0]==22000,"native BUY reference buffer");
   Check(CopyBuffer(handle,1,sellShift,1,one)==1 && one[0]==22000,"native SELL reference buffer");
   Check(CopyBuffer(handle,2,buyShift,1,one)==1 && one[0]==21998,"native initial SL buffer");
   Check(CopyBuffer(handle,3,sellShift,1,one)==1 && one[0]==21990,"native target buffer");
   Check(CopyBuffer(handle,4,buyShift,1,one)==1 && one[0]==22010,"native POC buffer");
   int blankHandle=iCustom(symbol,PERIOD_M1,"duc_tri_fabio_orderflow_lab");
   bool blank=false;
   for(int i=0;i<30;i++)
   {
      if(CopyBuffer(blankHandle,0,0,30,values)==30)
      {blank=true;for(int j=0;j<30;j++)if(values[j]!=EMPTY_VALUE)blank=false;if(blank)break;}
      Sleep(100);
   }
   Check(blank,"unconfigured indicator has no BUY arrows");IndicatorRelease(blankHandle);
   int deniedHandle=iCustom(symbol,PERIOD_M1,"duc_tri_fabio_orderflow_lab",file,dataset,"NQZ5",symbol,true,true,0,true,120,false,100,1);
   bool denied=false;
   for(int i=0;i<30;i++)
   {
      if(CopyBuffer(deniedHandle,0,0,30,values)==30)
      {denied=true;for(int j=0;j<30;j++)if(values[j]!=EMPTY_VALUE)denied=false;if(denied)break;}
      Sleep(100);
   }
   Check(denied,"synthetic data denied in actual indicator by default");IndicatorRelease(deniedHandle);
   Check(chart>0 && ChartIndicatorAdd(chart,0,handle),"attach only isolated fixture chart");
   ChartSetInteger(chart,CHART_AUTOSCROLL,false);ChartSetInteger(chart,CHART_SHIFT,false);
   ChartSetInteger(chart,CHART_MODE,CHART_CANDLES);ChartSetInteger(chart,CHART_SCALE,4);
   ChartSetInteger(chart,CHART_SHOW_GRID,false);ChartSetInteger(chart,CHART_COLOR_BACKGROUND,clrBlack);
   ChartSetInteger(chart,CHART_COLOR_FOREGROUND,clrSilver);ChartSetInteger(chart,CHART_COLOR_CANDLE_BULL,clrDarkSlateGray);
   ChartSetInteger(chart,CHART_COLOR_CHART_UP,clrDarkSlateGray);ChartSetInteger(chart,CHART_COLOR_CHART_DOWN,clrDarkSlateGray);
   ChartNavigate(chart,CHART_END,0);ChartRedraw(chart);Sleep(1000);
   Check(ChartScreenShot(chart,"fabio_orderflow_fixture\\indicator_fixture.png",1280,720,ALIGN_RIGHT),"render actual fixture chart");
   ChartClose(chart);IndicatorRelease(handle);
   f=FileOpen("fabio_orderflow_fixture\\indicator_result.json",FILE_WRITE|FILE_TXT|FILE_ANSI,0,CP_UTF8);
   FileWriteString(f,StringFormat("{\"checks\":%d,\"failures\":%d,\"failed\":\"%s\",\"kind\":\"actual iCustom import and render on synthetic fixture only\"}",checks,failures,failed));FileClose(f);
   Print("FABIO_INDICATOR_CHECKS ",checks," FAILURES ",failures);
}
