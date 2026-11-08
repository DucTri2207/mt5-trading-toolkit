#property copyright "Duc Tri Fabio orderflow research lab"
#property version "1.000"
#property description "Confirmed external exchange-orderflow signals. Research only; edge and prop pass unconfirmed."
#property indicator_chart_window
#property indicator_buffers 5
#property indicator_plots 5
#property indicator_type1 DRAW_NONE
#property indicator_type2 DRAW_NONE
#property indicator_type3 DRAW_NONE
#property indicator_type4 DRAW_NONE
#property indicator_type5 DRAW_NONE
#property indicator_label1 "BUY confirmed reference"
#property indicator_label2 "SELL confirmed reference"
#property indicator_label3 "Initial SL"
#property indicator_label4 "Target"
#property indicator_label5 "POC"
#include "Include/FabioOrderflowBridge.mqh"

input string InpSignalFile="DucTriLab\\Fabio\\signals.csv"; // Terminal Common Files
input string InpDatasetId=""; // Exact frozen dataset ID
input string InpSourceContract=""; // Exact source futures contract
input string InpChartSymbol=""; // Explicit destination; must equal this chart symbol
input bool InpConfirmSamePriceInstrument=false; // Confirm contract/price scale matches this chart
input bool InpConfirmClockMapping=false;
input int InpChartEpochOffsetSeconds=0; // chart epoch = source UTC + this offset
input bool InpReplayMode=true; // Historical display; does not claim a live feed
input int InpMaxFeedAgeSeconds=120; // Live mode heartbeat limit; no-signal periods are valid
input bool InpAllowSyntheticFixtures=false; // Fixture data never counts as trading evidence
input int InpMaxSignals=10000;
input int InpReloadSeconds=5;
input long InpDisplayChartId=0; // 0: attached chart; explicit ID only for iCustom integrations

double buyBuffer[],sellBuffer[],slBuffer[],targetBuffer[],pocBuffer[];
FOLSignal signals[];
string acceptedRaw[],prefix,status="DATA REQUIRED",bridgeSourceKind="";
long bridgeLastEvent=0;
bool dataReady=false;
string loggedStatus="";
long displayChart=0;

bool CanDraw(){return ChartSymbol(displayChart)==_Symbol && ChartPeriod(displayChart)==_Period;}

void StatusLine(const int index,const string text,const color col)
{
   string name=prefix+"status_"+IntegerToString(index);
   if(ObjectFind(displayChart,name)<0)ObjectCreate(displayChart,name,OBJ_LABEL,0,0,0);
   ObjectSetInteger(displayChart,name,OBJPROP_CORNER,CORNER_LEFT_UPPER);
   ObjectSetInteger(displayChart,name,OBJPROP_XDISTANCE,12);ObjectSetInteger(displayChart,name,OBJPROP_YDISTANCE,20+index*19);
   ObjectSetInteger(displayChart,name,OBJPROP_FONTSIZE,10);ObjectSetInteger(displayChart,name,OBJPROP_COLOR,col);
   ObjectSetString(displayChart,name,OBJPROP_TEXT,text);
}

void StatusLabel()
{
   if(loggedStatus!=status){Print("Fabio bridge: ",status);loggedStatus=status;}
   if(!CanDraw())return;
   string mode=InpReplayMode ? "HISTORICAL REPLAY" : "LIVE EXTERNAL FEED";
   if(bridgeSourceKind=="SYNTHETIC_FIXTURE")mode="SYNTHETIC FIXTURE - NO MARKET EVIDENCE";
   StatusLine(0,"FABIO ORDERFLOW LAB | EDGE / PROP PASS UNCONFIRMED",clrLightSkyBlue);
   StatusLine(1,mode,bridgeSourceKind=="SYNTHETIC_FIXTURE" ? clrOrange : clrLightSkyBlue);
   StatusLine(2,status,dataReady ? clrLightSkyBlue : clrOrange);
   StatusLine(3,dataReady ? StringFormat("%s | %s | %d confirmed rows",InpSourceContract,InpDatasetId,ArraySize(signals)) : "",clrSilver);
   StatusLine(4,dataReady ? "Event UTC "+TimeToString((datetime)bridgeLastEvent,TIME_DATE|TIME_SECONDS)+" | references only" : "",clrSilver);
}

void EmptyBuffers()
{
   ArrayInitialize(buyBuffer,EMPTY_VALUE);ArrayInitialize(sellBuffer,EMPTY_VALUE);
   ArrayInitialize(slBuffer,EMPTY_VALUE);ArrayInitialize(targetBuffer,EMPTY_VALUE);ArrayInitialize(pocBuffer,EMPTY_VALUE);
}

void Level(const string key,const datetime at,const double price,const color col)
{
   string name=prefix+"S_"+key;
   ObjectCreate(displayChart,name,OBJ_TREND,0,at,price,at+900,price);
   ObjectSetInteger(displayChart,name,OBJPROP_RAY_RIGHT,false);ObjectSetInteger(displayChart,name,OBJPROP_COLOR,col);
   ObjectSetInteger(displayChart,name,OBJPROP_STYLE,STYLE_DOT);
   ObjectSetString(displayChart,name,OBJPROP_TOOLTIP,key+" - static setup reference, not an open position");
}

void DrawSignals()
{
   if(CanDraw())ObjectsDeleteAll(displayChart,prefix+"S_");EmptyBuffers();
   if(!dataReady){StatusLabel();if(CanDraw())ChartRedraw(displayChart);return;}
   int n=ArraySize(signals),lastVisible=-1;
   for(int i=0;i<n;i++)
   {
      FOLSignal row=signals[i];datetime at=(datetime)(row.knownAt+InpChartEpochOffsetSeconds);
      int shift=iBarShift(_Symbol,_Period,at,false);
      if(shift<0 || shift>=ArraySize(buyBuffer))continue;
      datetime barAt=iTime(_Symbol,_Period,shift);
      if(at<barAt || at>=barAt+PeriodSeconds(_Period))continue;
      if(row.direction>0)buyBuffer[shift]=row.reference;else sellBuffer[shift]=row.reference;
      slBuffer[shift]=row.stop;targetBuffer[shift]=row.target;pocBuffer[shift]=row.poc;
      if(!CanDraw())continue;
      string name=prefix+"S_arrow_"+IntegerToString(i);
      ObjectCreate(displayChart,name,OBJ_ARROW,0,at,row.reference);
      ObjectSetInteger(displayChart,name,OBJPROP_ARROWCODE,row.direction>0 ? 233 : 234);
      ObjectSetInteger(displayChart,name,OBJPROP_COLOR,row.direction>0 ? clrLimeGreen : clrTomato);
      ObjectSetInteger(displayChart,name,OBJPROP_WIDTH,2);
      string tip=StringFormat("%s %s | %s\nKnown UTC %s | chart %s\nTrigger reference %.8f (not a fill)\nSL %.8f | target %.8f | POC %.8f",row.model,row.direction>0 ? "BUY" : "SELL",row.contract,TimeToString((datetime)row.knownAt,TIME_DATE|TIME_SECONDS),TimeToString(at,TIME_DATE|TIME_SECONDS),row.reference,row.stop,row.target,row.poc);
      ObjectSetString(displayChart,name,OBJPROP_TOOLTIP,tip);lastVisible=i;
   }
   if(lastVisible>=0)
   {
      FOLSignal row=signals[lastVisible];datetime at=(datetime)(row.knownAt+InpChartEpochOffsetSeconds);
      Level("SL",at,row.stop,clrTomato);Level("TARGET",at,row.target,clrDodgerBlue);Level("POC",at,row.poc,clrGold);
      string zone=prefix+"S_LVN";ObjectCreate(displayChart,zone,OBJ_RECTANGLE,0,at,row.lvnLow,at+900,row.lvnHigh);
      ObjectSetInteger(displayChart,zone,OBJPROP_COLOR,clrDarkCyan);ObjectSetInteger(displayChart,zone,OBJPROP_FILL,false);
      ObjectSetString(displayChart,zone,OBJPROP_TOOLTIP,"Frozen LVN of latest visible setup; 15-minute display span is not an expiry or position duration");
   }
   StatusLabel();if(CanDraw())ChartRedraw(displayChart);
}

bool Mapping(string &error)
{
   if(InpDatasetId=="" || InpSourceContract=="" || InpChartSymbol=="")
   {error="DATA REQUIRED: set dataset, source contract and chart symbol";return false;}
   if(InpChartSymbol!=_Symbol || !InpConfirmSamePriceInstrument)
   {error="Contract/chart price mapping NOT CONFIRMED";return false;}
   if(!InpConfirmClockMapping || MathAbs(InpChartEpochOffsetSeconds)>50400)
   {error="UTC-to-chart clock mapping NOT CONFIRMED";return false;}
   return true;
}

void Reload()
{
   string error;
   if(!Mapping(error)){dataReady=false;status=error;DrawSignals();return;}
   FOLSignal next[];string raw[],kind;long eventTime;
   int maxAge=InpReplayMode ? -1 : InpMaxFeedAgeSeconds;
   if(!FOLRead(InpSignalFile,true,InpSourceContract,InpDatasetId,InpAllowSyntheticFixtures,
               (long)TimeGMT(),maxAge,InpMaxSignals,next,raw,kind,eventTime,error) || !FOLPrefix(acceptedRaw,raw,error))
   {dataReady=false;status=error;DrawSignals();return;}
   if(eventTime<bridgeLastEvent){dataReady=false;status="Event heartbeat moved backward";DrawSignals();return;}
   int n=ArraySize(next);bool changed=n!=ArraySize(signals) || !dataReady;
   ArrayResize(signals,n);ArrayResize(acceptedRaw,n);
   for(int i=0;i<n;i++){signals[i]=next[i];acceptedRaw[i]=raw[i];}
   bridgeSourceKind=kind;bridgeLastEvent=eventTime;dataReady=true;status=n>0 ? "CONFIRMED SIGNAL REFERENCES" : "FEED READY; NO QUALIFYING SIGNALS";
   if(changed)DrawSignals();else StatusLabel();
}

int OnInit()
{
   if(InpMaxSignals<1 || InpMaxSignals>100000 || InpReloadSeconds<1 || InpReloadSeconds>3600 || InpMaxFeedAgeSeconds<1)
      return INIT_PARAMETERS_INCORRECT;
   SetIndexBuffer(0,buyBuffer,INDICATOR_DATA);SetIndexBuffer(1,sellBuffer,INDICATOR_DATA);
   SetIndexBuffer(2,slBuffer,INDICATOR_DATA);SetIndexBuffer(3,targetBuffer,INDICATOR_DATA);SetIndexBuffer(4,pocBuffer,INDICATOR_DATA);
   ArraySetAsSeries(buyBuffer,true);ArraySetAsSeries(sellBuffer,true);ArraySetAsSeries(slBuffer,true);
   ArraySetAsSeries(targetBuffer,true);ArraySetAsSeries(pocBuffer,true);
   prefix=StringFormat("DucTriFabio_%I64d_%I64d_",ChartID(),(long)GetTickCount64());
   displayChart=InpDisplayChartId>0 ? InpDisplayChartId : ChartID();
   IndicatorSetString(INDICATOR_SHORTNAME,"Fabio Orderflow LAB 1.0 - confirmed external feed");
   EventSetTimer(InpReloadSeconds);StatusLabel();return INIT_SUCCEEDED;
}

int OnCalculate(const int rates_total,const int prev_calculated,const datetime &time[],const double &open[],const double &high[],const double &low[],const double &close[],const long &tick_volume[],const long &volume[],const int &spread[])
{
   if(prev_calculated==0){EmptyBuffers();Reload();DrawSignals();}
   else if(rates_total!=prev_calculated)DrawSignals();
   return rates_total;
}

void OnTimer(){Reload();}
void OnDeinit(const int reason){EventKillTimer();if(CanDraw())ObjectsDeleteAll(displayChart,prefix);}
