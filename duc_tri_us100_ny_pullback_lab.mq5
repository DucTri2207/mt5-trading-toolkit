#property strict
#property version "1.00"
#property description "US100 NY pullback LAB. Closed M1 signals. Virtual limits. Edge unconfirmed."
#property indicator_chart_window
#property indicator_buffers 8
#property indicator_plots 8
#include "Include/Us100NyPullback.mqh"

input bool InpClockConfirmed=false;       // Confirm broker server clock before enabling
input int InpServerUtcWinterHours=2;      // Server winter UTC offset, not PC time
input UNYDst InpServerDst=UNY_DST_EU;      // Broker DST rule: none / Europe / US
input double InpRiskPercent=.25;         // Risk % of current account equity
input double InpModelSpread=2.0;         // Historical virtual spread, index price points
input double InpSlippage=.5;             // Adverse allowance per market/stop fill
input double InpCommissionPerLotRT=0;    // Round-trip commission in account currency/lot
input int InpHistoryDays=30;             // Whole UTC days used to rebuild virtual model
input bool InpPopup=false;              // Local popup only; no push/Telegram
input long InpDrawChart=0;              // 0=current chart

double Buy[],Sell[],Entry[],Stop[],Target[],Atr[],Direction[],Known[];
datetime last_bar=0,last_alert=0,live_stamp=0;
datetime live_times[];
double live_bids[],live_asks[];
long draw_chart=0;
string prefix="";

bool SupportedSymbol()
{
   string s=_Symbol;StringToUpper(s);
   return StringFind(s,"US100")>=0 || StringFind(s,"USTEC")>=0 || StringFind(s,"NAS100")>=0 || StringFind(s,"USATECH")>=0;
}
void Label(const int row,const string text,const color ink=clrSilver)
{
   string name=prefix+"row"+IntegerToString(row);
   if(ObjectFind(draw_chart,name)<0)ObjectCreate(draw_chart,name,OBJ_LABEL,0,0,0);
   ObjectSetInteger(draw_chart,name,OBJPROP_CORNER,CORNER_LEFT_UPPER);
   ObjectSetInteger(draw_chart,name,OBJPROP_XDISTANCE,22);ObjectSetInteger(draw_chart,name,OBJPROP_YDISTANCE,32+row*25);
   ObjectSetInteger(draw_chart,name,OBJPROP_COLOR,ink);ObjectSetInteger(draw_chart,name,OBJPROP_FONTSIZE,row==0?13:11);
   ObjectSetString(draw_chart,name,OBJPROP_FONT,"Segoe UI");ObjectSetString(draw_chart,name,OBJPROP_TEXT,text);
   ObjectSetInteger(draw_chart,name,OBJPROP_SELECTABLE,false);
}
void PanelBase()
{
   string name=prefix+"panel";
   if(ObjectFind(draw_chart,name)<0)ObjectCreate(draw_chart,name,OBJ_RECTANGLE_LABEL,0,0,0);
   ObjectSetInteger(draw_chart,name,OBJPROP_XDISTANCE,12);ObjectSetInteger(draw_chart,name,OBJPROP_YDISTANCE,20);
   ObjectSetInteger(draw_chart,name,OBJPROP_XSIZE,670);ObjectSetInteger(draw_chart,name,OBJPROP_YSIZE,240);
   ObjectSetInteger(draw_chart,name,OBJPROP_BGCOLOR,C'18,28,42');ObjectSetInteger(draw_chart,name,OBJPROP_BORDER_TYPE,BORDER_FLAT);
   ObjectSetInteger(draw_chart,name,OBJPROP_COLOR,C'49,71,94');ObjectSetInteger(draw_chart,name,OBJPROP_BACK,false);
   ObjectSetInteger(draw_chart,name,OBJPROP_SELECTABLE,false);
}
void Line(const string suffix,const datetime from,const datetime to,const double price,const color ink)
{
   string name=prefix+suffix;
   ObjectDelete(draw_chart,name);ObjectCreate(draw_chart,name,OBJ_TREND,0,from,price,to,price);
   ObjectSetInteger(draw_chart,name,OBJPROP_RAY_RIGHT,false);ObjectSetInteger(draw_chart,name,OBJPROP_COLOR,ink);
   ObjectSetInteger(draw_chart,name,OBJPROP_STYLE,STYLE_DASH);ObjectSetInteger(draw_chart,name,OBJPROP_WIDTH,2);
   ObjectSetInteger(draw_chart,name,OBJPROP_SELECTABLE,false);
}
double Lots(const UNYPlan &p,double &budget)
{
   budget=AccountInfoDouble(ACCOUNT_EQUITY)*InpRiskPercent/100.;
   double size=SymbolInfoDouble(_Symbol,SYMBOL_TRADE_TICK_SIZE),value=SymbolInfoDouble(_Symbol,SYMBOL_TRADE_TICK_VALUE_LOSS);
   if(size<=0 || value<=0 || !MathIsValidNumber(value))return 0;
   double loss=(p.distance+InpSlippage)/size*value+InpCommissionPerLotRT;
   return UNYFloorLots(budget,loss,SymbolInfoDouble(_Symbol,SYMBOL_VOLUME_MIN),SymbolInfoDouble(_Symbol,SYMBOL_VOLUME_STEP),SymbolInfoDouble(_Symbol,SYMBOL_VOLUME_MAX));
}
void WritePlan(const int i,const UNYSignal &s,const UNYPlan &p)
{
   Buy[i]=p.direction==1?p.entry:EMPTY_VALUE;Sell[i]=p.direction==-1?p.entry:EMPTY_VALUE;
   Entry[i]=p.entry;Stop[i]=p.stop;Target[i]=p.target;Atr[i]=s.atr;Direction[i]=p.direction;Known[i]=(double)s.known_at;
}
int OnInit()
{
   if(InpRiskPercent<=0 || InpRiskPercent>1 || InpModelSpread<0 || InpSlippage<0 || InpCommissionPerLotRT<0 ||
      InpHistoryDays<2 || InpHistoryDays>366 || InpServerUtcWinterHours< -12 || InpServerUtcWinterHours>14)return INIT_PARAMETERS_INCORRECT;
   SetIndexBuffer(0,Buy,INDICATOR_DATA);SetIndexBuffer(1,Sell,INDICATOR_DATA);SetIndexBuffer(2,Entry,INDICATOR_DATA);
   SetIndexBuffer(3,Stop,INDICATOR_DATA);SetIndexBuffer(4,Target,INDICATOR_DATA);SetIndexBuffer(5,Atr,INDICATOR_DATA);
   SetIndexBuffer(6,Direction,INDICATOR_DATA);SetIndexBuffer(7,Known,INDICATOR_DATA);
   for(int i=0;i<8;i++){PlotIndexSetInteger(i,PLOT_DRAW_TYPE,i<2?DRAW_ARROW:DRAW_NONE);PlotIndexSetDouble(i,PLOT_EMPTY_VALUE,EMPTY_VALUE);}
   PlotIndexSetInteger(0,PLOT_ARROW,233);PlotIndexSetInteger(1,PLOT_ARROW,234);
   PlotIndexSetInteger(0,PLOT_LINE_COLOR,clrAqua);PlotIndexSetInteger(1,PLOT_LINE_COLOR,clrOrangeRed);
   PlotIndexSetInteger(0,PLOT_LINE_WIDTH,2);PlotIndexSetInteger(1,PLOT_LINE_WIDTH,2);
   string names[]={"BUY model","SELL model","Entry model","SL initial","TP 1.25R","ATR known","Direction","Known at UTC"};
   for(int i=0;i<8;i++)PlotIndexSetString(i,PLOT_LABEL,names[i]);
   IndicatorSetString(INDICATOR_SHORTNAME,"US100 NY Pullback LAB v1");IndicatorSetInteger(INDICATOR_DIGITS,_Digits);
   draw_chart=InpDrawChart==0?ChartID():InpDrawChart;prefix="UNY_"+IntegerToString((long)GetMicrosecondCount())+"_";
   PanelBase();return INIT_SUCCEEDED;
}
void OnDeinit(const int reason){ObjectsDeleteAll(draw_chart,prefix);ChartRedraw(draw_chart);}

int OnCalculate(const int total,const int prev,const datetime &time[],const double &open[],const double &high[],const double &low[],
                const double &close[],const long &tick_volume[],const long &volume[],const int &spread[])
{
   ArraySetAsSeries(time,false);ArraySetAsSeries(open,false);ArraySetAsSeries(high,false);ArraySetAsSeries(low,false);ArraySetAsSeries(close,false);
   if(total<1)return 0;
   if(prev>0 && last_bar==time[total-1])return total;
   last_bar=time[total-1];
   ArrayInitialize(Buy,EMPTY_VALUE);ArrayInitialize(Sell,EMPTY_VALUE);ArrayInitialize(Entry,EMPTY_VALUE);ArrayInitialize(Stop,EMPTY_VALUE);
   ArrayInitialize(Target,EMPTY_VALUE);ArrayInitialize(Atr,EMPTY_VALUE);ArrayInitialize(Direction,EMPTY_VALUE);ArrayInitialize(Known,EMPTY_VALUE);
   Label(0,"US100 | NY PULLBACK LAB v1",clrWhite);
   Label(1,"M1 | 09:35-11:00 New York | TP 1.25R | max 15 phut");
   Label(7,"Gioi han LENH AO; ban tu quan ly lenh that va quy.",clrKhaki);
   Label(8,"CHUA XAC NHAN EDGE | Lich su la mo phong, khong phai fill that.",clrOrange);
   if(_Period!=PERIOD_M1 || !SupportedSymbol() || !InpClockConfirmed)
   {
      Label(2,_Period!=PERIOD_M1?"CAN CHART M1":(!SupportedSymbol()?"CAN SYMBOL US100 / USTEC / NAS100":"CAN XAC NHAN MUI GIO SERVER"),clrOrange);
      Label(3,"Inputs: ClockConfirmed, UTC winter offset, DST rule.");Label(4,"Doi chieu 09:35 New York truoc khi dung.");
      Label(5,"");Label(6,"");ChartRedraw(draw_chart);return total;
   }
   datetime utc_last=UNYToUtc(time[total-1],InpServerUtcWinterHours,InpServerDst);
   bool realtime=MathAbs((double)(utc_last-TimeGMT()))<120;
   datetime cutoff=(datetime)(((long)utc_last/86400-InpHistoryDays)*86400);
   int offset=0;while(offset<total && UNYToUtc(time[offset],InpServerUtcWinterHours,InpServerDst)<cutoff)offset++;
   int n=total-offset;MqlRates b[];ArrayResize(b,n);
   for(int j=0;j<n;j++)
   {
      int k=offset+j;b[j].time=UNYToUtc(time[k],InpServerUtcWinterHours,InpServerDst);
      b[j].open=open[k];b[j].high=high[k];b[j].low=low[k];b[j].close=close[k];
   }
   double fast[],slow[],atr[];int warm[];UNYFeatures(b,fast,slow,atr,warm);
   MqlTick quote;bool has_quote=SymbolInfoTick(_Symbol,quote);
   // Only the first observed tick of a new minute can define a live entry quote.
   if(realtime && has_quote && quote.time>=time[total-1] && quote.time-time[total-1]<=5 && live_stamp!=time[total-1])
   {
      live_stamp=time[total-1];int z=ArraySize(live_times);
      ArrayResize(live_times,z+1);ArrayResize(live_bids,z+1);ArrayResize(live_asks,z+1);
      live_times[z]=utc_last;live_bids[z]=quote.bid;live_asks[z]=quote.ask;
   }
   int entries=0,stops=0;long day=-1;datetime cooldown=0;bool active=false,has_last=false;
   UNYPlan p,last;ZeroMemory(p);ZeroMemory(last);UNYSignal sig;string result="CHO SETUP";datetime last_exit=0;
   double tick=SymbolInfoDouble(_Symbol,SYMBOL_TRADE_TICK_SIZE);if(tick<=0)tick=_Point;
   int live_index=0;
   for(int j=1;j<n;j++)
   {
      datetime t=b[j].time;long d=(long)UNYToNy(t)/86400;
      if(d!=day){entries=0;stops=0;day=d;}
      double bo=b[j].open,ao=bo+InpModelSpread;
      while(live_index<ArraySize(live_times) && live_times[live_index]<t)live_index++;
      if(live_index<ArraySize(live_times) && live_times[live_index]==t){bo=live_bids[live_index];ao=live_asks[live_index];}
      if(active)
      {
         double mark=p.direction==1?bo:ao;
         bool sl=p.direction==1?mark<=p.stop:mark>=p.stop;
         bool tp=p.direction==1?mark>=p.target:mark<=p.target;
         if(sl || tp || t>=p.deadline)
         {active=false;stops+=sl?1:0;cooldown=t+300;last_exit=t;result=sl?"SL AO":(tp?"TP AO":"HET GIO AO");}
      }
      if(!active && entries<3 && stops<2 && t>=cooldown && UNYInSession(t) && b[j].time-b[j-1].time==60 &&
         UNYDetect(b,fast,slow,atr,warm,j-1,sig) && UNYMakePlan(sig,bo,ao,InpModelSpread,InpSlippage,0,tick,p))
      {
         active=true;entries++;p.entered=t;p.deadline=(datetime)MathMin((long)t+900,(long)UNYSessionEnd(t));last=p;has_last=true;
         WritePlan(offset+j,sig,p);result="KE HOACH AO DANG MO";
      }
      if(active && j<n-1)
      {
         bool sl=p.direction==1?b[j].low<=p.stop:b[j].high+InpModelSpread>=p.stop;
         bool tp=p.direction==1?b[j].high>=p.target:b[j].low+InpModelSpread<=p.target;
         if(sl || tp){active=false;stops+=sl?1:0;cooldown=t+60+300;last_exit=t+60;result=sl?"SL AO": "TP AO";}
      }
   }
   if(active && last.entered<utc_last)result="THEO DOI LENH AO | KHONG VAO DUOI";
   Label(2,(realtime?(UNYInSession(utc_last)?"TRONG PHIEN":"NGOAI PHIEN"):"LICH SU / MO PHONG")+" | "+result,active?clrAqua:clrSilver);
   Label(3,StringFormat("Ngay NY %s: %d/3 lenh ao | %d/2 SL | Risk %.2f%%",TimeToString(UNYToNy(utc_last),TIME_DATE),entries,stops,InpRiskPercent));
   if(has_last)
   {
      Label(4,StringFormat("%s | Entry %.*f | SL %.*f | TP %.*f",last.direction==1?"BUY":"SELL",_Digits,last.entry,_Digits,last.stop,_Digits,last.target),clrWhite);
      double budget=0,lots=0;bool fresh=realtime && active && last.entered==utc_last && live_stamp==time[total-1];
      if(fresh)lots=Lots(last,budget);string money=AccountInfoString(ACCOUNT_CURRENCY);
      double minimum=SymbolInfoInteger(_Symbol,SYMBOL_TRADE_STOPS_LEVEL)*_Point;
      if(fresh && has_quote && ((last.direction==1 && (quote.bid-last.stop<minimum || last.target-quote.bid<minimum)) ||
         (last.direction==-1 && (last.stop-quote.ask<minimum || quote.ask-last.target<minimum))))lots=0;
      Label(5,lots>0?StringFormat("Lot tham khao %.4f | Risk budget %.2f %s (equity hien tai)",lots,budget,money):"Lot -- | chi hien khi co tin hieu moi va quy cach hop le",clrSilver);
      Label(6,"Ke hoach gan nhat UTC: "+TimeToString(last.entered,TIME_DATE|TIME_MINUTES)+(active?"":" | DA HET HIEU LUC"));
      datetime from=last.entered+(time[total-1]-utc_last);
      datetime until=(active?last.deadline:last_exit)+(time[total-1]-utc_last);
      Line("entry",from,until,last.entry,clrAqua);Line("sl",from,until,last.stop,clrTomato);Line("tp",from,until,last.target,clrLimeGreen);
      if(InpPopup && fresh && lots>0 && last_alert!=utc_last)
      {last_alert=utc_last;Alert("US100 NY LAB: ",last.direction==1?"BUY":"SELL"," entry ",last.entry," SL ",last.stop," TP ",last.target,". Virtual model; edge unconfirmed.");}
   }
   else{Label(4,"Cho 2 nen hoi + nen xac nhan tiep dien.");Label(5,"Khong co ke hoach hop le trong lich su da nap.");Label(6,"");}
   ChartRedraw(draw_chart);return total;
}
