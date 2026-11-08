#ifndef CHT_V4_RISK
#define CHT_V4_RISK
struct SV4SymbolSpec
{
   double tickSize,tickValue,point,minLot,maxLot,step;
};
bool V4SymbolSpec(string symbol,SV4SymbolSpec &s)
{
   s.tickSize=SymbolInfoDouble(symbol,SYMBOL_TRADE_TICK_SIZE);
   s.tickValue=SymbolInfoDouble(symbol,SYMBOL_TRADE_TICK_VALUE_LOSS);
   s.point=SymbolInfoDouble(symbol,SYMBOL_POINT);
   s.minLot=SymbolInfoDouble(symbol,SYMBOL_VOLUME_MIN);
   s.maxLot=SymbolInfoDouble(symbol,SYMBOL_VOLUME_MAX);
   s.step=SymbolInfoDouble(symbol,SYMBOL_VOLUME_STEP);
   return s.tickSize>0 && s.point>0 && s.minLot>0 && s.maxLot>=s.minLot && s.step>0;
}
string g_v4RiskWarning="";
string g_v4RiskError="";
bool g_v4RiskErrorLogged=false;

double V4LossRate(string from,string to,string base,string quote,double bid,double ask)
{
   if(from==to)return 1;
   if(!MathIsValidNumber(bid) || !MathIsValidNumber(ask) || bid<=0 || ask<bid)return 0;
   if(base==from && quote==to)return ask;
   if(base==to && quote==from)return 1/bid;
   return 0;
}
struct SV4CurrencyPair{string from,to,symbol;datetime retry;};
SV4CurrencyPair g_v4CurrencyPairs[];
double V4CurrencyRate(string from,string to)
{
   if(from=="" || to=="")return 0;
   if(from==to)return 1;
   int n=0;
   for(;n<ArraySize(g_v4CurrencyPairs);n++)if(g_v4CurrencyPairs[n].from==from && g_v4CurrencyPairs[n].to==to)break;
   if(n==ArraySize(g_v4CurrencyPairs))
   {ArrayResize(g_v4CurrencyPairs,n+1);g_v4CurrencyPairs[n].from=from;g_v4CurrencyPairs[n].to=to;}
   if(g_v4CurrencyPairs[n].symbol=="" && TimeCurrent()>=g_v4CurrencyPairs[n].retry)
   {
      g_v4CurrencyPairs[n].retry=TimeCurrent()+60;
      for(int i=0;i<SymbolsTotal(false);i++)
      {
         string name=SymbolName(i,false),base=SymbolInfoString(name,SYMBOL_CURRENCY_BASE),quote=SymbolInfoString(name,SYMBOL_CURRENCY_PROFIT);
         if((base==from && quote==to) || (base==to && quote==from))
            if(SymbolSelect(name,true)){g_v4CurrencyPairs[n].symbol=name;break;}
      }
   }
   string symbol=g_v4CurrencyPairs[n].symbol;MqlTick tick;
   if(symbol=="" || !SymbolInfoTick(symbol,tick))return 0;
   return V4LossRate(from,to,SymbolInfoString(symbol,SYMBOL_CURRENCY_BASE),SymbolInfoString(symbol,SYMBOL_CURRENCY_PROFIT),tick.bid,tick.ask);
}
double V4ContractRisk(double distance,double lots,double contract,double rate)
{
   if(!MathIsValidNumber(contract) || !MathIsValidNumber(rate) || contract<=0 || rate<=0)return 0;
   return distance*lots*contract*rate;
}
double V4IndicatorRisk(double distance,double lots)
{
   string profit=SymbolInfoString(_Symbol,SYMBOL_CURRENCY_PROFIT),account=AccountInfoString(ACCOUNT_CURRENCY);
   double rate=V4CurrencyRate(profit,account);
   if(rate<=0 && profit!="USD" && account!="USD")rate=V4CurrencyRate(profit,"USD")*V4CurrencyRate("USD",account);
   double money=V4ContractRisk(distance,lots,SymbolInfoDouble(_Symbol,SYMBOL_TRADE_CONTRACT_SIZE),rate);
   if(money<=0)
   {
      g_v4RiskError="Lot N/A: thiếu contract hoặc tỷ giá "+profit+"/"+account;
      if(!g_v4RiskErrorLogged){Print("V4_RISK_FAIL_CLOSED ",g_v4RiskError);g_v4RiskErrorLogged=true;}
   }
   return money;
}
double V4TickRiskMoney(double distance,double lots,const SV4SymbolSpec &s)
{
   if(distance<=0 || lots<=0 || s.tickSize<=0 || s.tickValue<=0)return 0;
   return distance/s.tickSize*s.tickValue*lots;
}
double V4RiskMoney(bool buy,double entry,double sl,double lots,const SV4SymbolSpec &s)
{
   double distance=(entry-sl)*(buy?1:-1);
   if(entry<=0 || sl<=0 || distance<=0 || lots<=0)return 0;
   double money=0;
#ifdef CHT_V4_NATIVE_FIXTURE
#ifndef CHT_V4_TEST_ORDER_CALC
#define CHT_V4_FROZEN_RISK
#endif
#endif
#ifdef CHT_V4_FROZEN_RISK
   // Frozen offline fixtures have an explicit contract; no broker/account is involved.
   money=V4TickRiskMoney(distance,lots,s);
#else
   if(MQLInfoInteger(MQL_PROGRAM_TYPE)==PROGRAM_INDICATOR)money=V4IndicatorRisk(distance,lots);
   else
   {
   double profit=0;
   if(!OrderCalcProfit(buy?ORDER_TYPE_BUY:ORDER_TYPE_SELL,_Symbol,lots,entry,sl,profit) ||
      !MathIsValidNumber(profit) || profit>=0)
   {
      g_v4RiskError="Lot N/A: OrderCalcProfit thất bại";
      if(!g_v4RiskErrorLogged){Print("V4_RISK_FAIL_CLOSED ",g_v4RiskError);g_v4RiskErrorLogged=true;}
      return 0;
   }
   money=-profit;
   }
#endif
   if(money<=0)return 0;
   g_v4RiskError="";
   double reference=V4TickRiskMoney(distance,lots,s);
   if(money>0 && MathAbs(reference-money)/money>0.01)
   {
      if(g_v4RiskWarning=="")PrintFormat("V4_RISK_WARNING broker khai báo tick value không khớp: primary=%.8f tick_formula=%.8f; %s",money,reference,MQLInfoInteger(MQL_PROGRAM_TYPE)==PROGRAM_INDICATOR?"using contract size/conversion":"using OrderCalcProfit");
      g_v4RiskWarning="broker khai báo tick value không khớp";
   }
   return money;
}
double V4LotsFromRisk(double equity,double percent,double perLot,const SV4SymbolSpec &s)
{
   if(equity<=0 || percent<=0 || perLot<=0 || s.step<=0 || s.minLot<=0 || s.maxLot<s.minLot)return 0;
   double raw=equity*percent/100/perLot;
   return NormalizeDouble(MathMax(s.minLot,MathFloor(MathMin(raw,s.maxLot)/s.step+1e-10)*s.step),8);
}
double V4Lots(double equity,double percent,bool buy,double entry,double sl,const SV4SymbolSpec &s)
{
   return V4LotsFromRisk(equity,percent,V4RiskMoney(buy,entry,sl,1,s),s);
}
double V4CostR(bool buy,double entry,double sl,double spread,double slipPoints,double commission,const SV4SymbolSpec &s)
{
   double risk=V4RiskMoney(buy,entry,sl,1,s);
   if(risk<=0 || spread<0 || slipPoints<0 || commission<0)return EMPTY_VALUE;
   double distance=spread+2*slipPoints*s.point;
   double priceCost=distance>0?V4RiskMoney(buy,entry,entry-(buy?1:-1)*distance,1,s):0;
   if(distance>0 && priceCost<=0)return EMPTY_VALUE;
   return (priceCost+commission)/risk;
}
#ifdef CHT_V4_NATIVE_FIXTURE
// Legacy fixture-only signatures; production callers must supply direction/entry/SL.
double V4RiskMoney(double distance,double lots,const SV4SymbolSpec &s){return V4TickRiskMoney(distance,lots,s);}
double V4Lots(double equity,double percent,double distance,const SV4SymbolSpec &s){return V4LotsFromRisk(equity,percent,V4TickRiskMoney(distance,1,s),s);}
double V4CostR(double distance,double spread,double slipPoints,double commission,const SV4SymbolSpec &s)
{
   double risk=V4TickRiskMoney(distance,1,s);
   if(risk<=0 || spread<0 || slipPoints<0 || commission<0)return EMPTY_VALUE;
   return (V4TickRiskMoney(spread+2*slipPoints*s.point,1,s)+commission)/risk;
}
#endif
datetime V4ResetDay(datetime serverTime,int resetMinute)
{
   long shifted=(long)serverTime-resetMinute*60;
   return (datetime)(shifted-shifted%86400+resetMinute*60);
}
struct SV4Limits
{
   double dailyRemaining,totalRemaining,dayBalance;
   bool ready,hit;
};
SV4Limits g_v4Limits;
void V4ComputeLimits(double initial,double dayBalance,double equity,double dailyPercent,double totalPercent,SV4Limits &out)
{
   ZeroMemory(out);
   if(initial<=0 || dailyPercent<=0 || totalPercent<=0) return;
   out.dayBalance=dayBalance; out.dailyRemaining=equity-(dayBalance-initial*dailyPercent/100);
   out.totalRemaining=equity-initial*(1-totalPercent/100); out.ready=true;
   out.hit=out.dailyRemaining<=0 || out.totalRemaining<=0;
}
void V4UpdateLimits(datetime now)
{
   ZeroMemory(g_v4Limits);
   if(InpInitialCapital<=0 || !HistorySelect(V4ResetDay(now,InpResetMinuteServer),now)) return;
   double cash=0;
   for(int i=0;i<HistoryDealsTotal();i++)
   {
      ulong d=HistoryDealGetTicket(i);
      cash+=HistoryDealGetDouble(d,DEAL_PROFIT)+HistoryDealGetDouble(d,DEAL_COMMISSION)
            +HistoryDealGetDouble(d,DEAL_SWAP)+HistoryDealGetDouble(d,DEAL_FEE);
   }
   V4ComputeLimits(InpInitialCapital,AccountInfoDouble(ACCOUNT_BALANCE)-cash,AccountInfoDouble(ACCOUNT_EQUITY),
      InpDailyLossPercent,InpTotalLossPercent,g_v4Limits);
   string key="V4_DAILY_"+(string)V4Hash(AccountInfoString(ACCOUNT_SERVER)+"|"+(string)AccountInfoInteger(ACCOUNT_LOGIN)+
      "|"+(string)InpResetMinuteServer+"|"+DoubleToString(InpInitialCapital,2));
   datetime day=V4ResetDay(now,InpResetMinuteServer);
   if(g_v4Limits.dailyRemaining<=0) { GlobalVariableSet(key,(double)day); GlobalVariablesFlush(); }
   if(GlobalVariableCheck(key) && GlobalVariableGet(key)==(double)day) g_v4Limits.hit=true;
}
bool V4RiskAlertsAllowed()
{
   return !InpMuteAtDailyLimit || (g_v4Limits.ready && !g_v4Limits.hit);
}
#endif
