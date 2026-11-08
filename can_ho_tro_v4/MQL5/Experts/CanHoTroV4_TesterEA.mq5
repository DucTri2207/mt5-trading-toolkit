#property strict
#property version "4.03"
#property description "Can Ho Tro v4.0.2 - Strategy Tester only"
#include <Trade/Trade.mqh>
#include <CanHoTroV4/Types.mqh>
#include <CanHoTroV4/Inputs.mqh>
input bool InpAllowMultiplePositions=false;
input int InpMaxTesterPositions=5;
input ulong InpTesterMagic=40020261102;
SZone g_zones[];
SEventLog g_events[];
SConfirmSignal g_lastSignal;
ENUM_CONFIRM_STATE g_confirmState=STATE_IDLE;
int g_atrHandle=INVALID_HANDLE,g_htfAtrHandle=INVALID_HANDLE,g_ltfAtrHandle=INVALID_HANDLE;
int g_statCreated=0,g_statDemand=0,g_statSupply=0,g_statBroken=0,g_statFlipped=0;
datetime g_lastAlertBar=0,g_lastSignalSeenTime=0,g_previousDayTime=0;
long g_lastSignalSeenZone=-1;
bool g_lastSignalSeenBuy=false;
double g_previousDayHigh=0,g_previousDayLow=0;
string g_prefix="DucTri_V4_EA_";
bool g_v4BatchArrows=false;
// UI/notification adapters: the detector and plan logic below are shared with the indicator.
void DrawSignalArrow(bool buy,datetime t,double p,double atr){}
void DrawTradePlanLines(const SConfirmSignal &s){}
void RemoveTradePlanLines(){}
void DrawReferenceLevels(){}
void SendSignalAlert(const SConfirmSignal &s){}
void SendBeTelegram(const SConfirmSignal &s,double p,double r){}
#include <CanHoTroV4/Identity.mqh>
#include <CanHoTroV4/Time.mqh>
#include <CanHoTroV4/SourceZone.mqh>
#include <CanHoTroV4/Logger.mqh>
#include <CanHoTroV4/LogicHelpers.mqh>
#include <CanHoTroV4/Zones.mqh>
#include <CanHoTroV4/Signals.mqh>
void ScanHtfMacroZones(){CZoneEngine::Scan();}
void DetectLtfConfirmation(bool quiet=false){CSignalEngine::Detect(quiet);}
#include <CanHoTroV4/Observation.mqh>
#include <CanHoTroV4/Risk.mqh>
#include <CanHoTroV4/Execution.mqh>
#include <CanHoTroV4/TesterLedger.mqh>
#include <CanHoTroV4/StopRules.mqh>
CTrade g_v4Trade;
SV4TesterRecord g_v4Trades[];
int g_v4TradeFile=INVALID_HANDLE,g_v4ExecutionEvents=INVALID_HANDLE,g_v4RiskAudit=INVALID_HANDLE;
bool g_v4TesterReady=false;

bool V4EAObserve(datetime observation,datetime published)
{
   return V4ObserveClosedBar(observation,published,true);
}
void V4EAEvent(string id,string action,string detail)
{
   if(g_v4ExecutionEvents!=INVALID_HANDLE)
   { FileWrite(g_v4ExecutionEvents,id,(long)TimeCurrent(),action,detail); FileFlush(g_v4ExecutionEvents); }
}
void V4EAFail(string detail)
{
   V4EAEvent("","FAIL_CLOSED",detail); Print("V4 tester failed: ",detail); g_v4IoFailed=true;
   if(MQLInfoInteger(MQL_TESTER)) TesterStop();
}
bool V4EAReconcile(int i)
{
   if(g_v4Trades[i].written) return true;
   if(!HistorySelectByPosition(g_v4Trades[i].position)) return false;
   double gross=0,commission=0,swap=0,fee=0,volume=0,value=0;
   datetime exitTime=0; long exitMsc=0,dealReason=-1;
   for(int j=0;j<HistoryDealsTotal();j++)
   {
      ulong d=HistoryDealGetTicket(j);
      gross+=HistoryDealGetDouble(d,DEAL_PROFIT); commission+=HistoryDealGetDouble(d,DEAL_COMMISSION);
      swap+=HistoryDealGetDouble(d,DEAL_SWAP); fee+=HistoryDealGetDouble(d,DEAL_FEE);
      long entry=HistoryDealGetInteger(d,DEAL_ENTRY);
      if(entry==DEAL_ENTRY_OUT || entry==DEAL_ENTRY_OUT_BY)
      {
         double v=HistoryDealGetDouble(d,DEAL_VOLUME); volume+=v; value+=v*HistoryDealGetDouble(d,DEAL_PRICE);
         exitTime=(datetime)HistoryDealGetInteger(d,DEAL_TIME); exitMsc=HistoryDealGetInteger(d,DEAL_TIME_MSC);
         dealReason=HistoryDealGetInteger(d,DEAL_REASON);
      }
   }
   if(volume+1e-8<g_v4Trades[i].volume) return false;
   if(exitMsc<g_v4Trades[i].fillMsc) { V4EAFail("exit before fill"); return false; }
   string reason=g_v4Trades[i].requestedExit;
   if(dealReason==DEAL_REASON_SL) reason="BROKER_SL";
   else if(dealReason==DEAL_REASON_TP) reason="BROKER_TP_1R";
   if(reason=="") reason="TESTER_OR_EXTERNAL_CLOSE";
   if(!V4TesterWrite(g_v4TradeFile,g_v4Trades[i],exitTime,exitMsc,value/volume,reason,gross,commission,swap,fee,"CLOSED"))
   { V4EAFail("trade ledger write"); return false; }
   g_v4Trades[i].written=true; return true;
}
bool V4EAModify(int i,double sl,double tp)
{
   if(!MQLInfoInteger(MQL_TESTER) || !g_v4TesterReady) return false;
   if(!PositionSelectByTicket(g_v4Trades[i].ticket)) { V4EAFail("modify position missing"); return false; }
   double size=SymbolInfoDouble(_Symbol,SYMBOL_TRADE_TICK_SIZE);
   double oldSL=PositionGetDouble(POSITION_SL),oldTP=PositionGetDouble(POSITION_TP);
   sl=V4StopPrice(sl,size,_Digits);tp=V4StopPrice(tp,size,_Digits);
   g_v4Trades[i].virtualTrade.stop=oldSL;
   if(V4SameStops(sl,tp,oldSL,oldTP,size,_Digits))
   { V4EAEvent(g_v4Trades[i].signal.signal_id,"MODIFY_NO_CHANGE","normalized SL/TP unchanged"); return true; }
   MqlTick quote;
   if(!SymbolInfoTick(_Symbol,quote)) { V4EAFail("modify quote unavailable"); return false; }
   long stops=SymbolInfoInteger(_Symbol,SYMBOL_TRADE_STOPS_LEVEL),freeze=SymbolInfoInteger(_Symbol,SYMBOL_TRADE_FREEZE_LEVEL);
   if(!V4StopsAllowed(g_v4Trades[i].signal.isBuy,quote.bid,quote.ask,sl,tp,oldSL,oldTP,_Point,stops,freeze))
   { V4EAEvent(g_v4Trades[i].signal.signal_id,"MODIFY_DEFERRED","STOPS_LEVEL/FREEZE_LEVEL; retaining SL"); return false; }
   bool ok=g_v4Trade.PositionModify(g_v4Trades[i].ticket,sl,tp);
   uint code=g_v4Trade.ResultRetcode();
   if(ok && (code==TRADE_RETCODE_DONE || code==TRADE_RETCODE_NO_CHANGES))
   { g_v4Trades[i].virtualTrade.stop=sl; return true; }
   if(code==TRADE_RETCODE_INVALID_STOPS || code==TRADE_RETCODE_FROZEN)
   { V4EAEvent(g_v4Trades[i].signal.signal_id,"MODIFY_DEFERRED",g_v4Trade.ResultRetcodeDescription()); return false; }
   V4EAFail("modify rejected: "+g_v4Trade.ResultRetcodeDescription()); return false;
}
void V4EAManage(const MqlTick &tick)
{
   if(!MQLInfoInteger(MQL_TESTER) || !g_v4TesterReady) return;
   for(int i=0;i<ArraySize(g_v4Trades);i++)
   {
      if(g_v4Trades[i].written) continue;
      if(!PositionSelectByTicket(g_v4Trades[i].ticket))
      { if(!V4EAReconcile(i)) V4EAFail("closed position missing deals"); continue; }
      if(tick.time_msc<g_v4Trades[i].fillMsc) continue;
      double quote=g_v4Trades[i].signal.isBuy?tick.bid:tick.ask;
      double signedR=(g_v4Trades[i].signal.isBuy?1:-1)*(quote-g_v4Trades[i].virtualTrade.entry)/g_v4Trades[i].virtualTrade.risk;
      g_v4Trades[i].mae=MathMax(g_v4Trades[i].mae,-signedR);
      g_v4Trades[i].virtualTrade.mfe=MathMax(g_v4Trades[i].virtualTrade.mfe,MathMax(0,signedR)*g_v4Trades[i].virtualTrade.risk);
      double previous=g_v4Trades[i].virtualTrade.stop;
      V4VirtualTick(g_v4Trades[i].virtualTrade,tick,0,InpScoreExit);
      if(g_v4Trades[i].virtualTrade.closed)
      {
         g_v4Trades[i].requestedExit=g_v4Trades[i].virtualTrade.reason;
         if(!g_v4Trade.PositionClose(g_v4Trades[i].ticket) || g_v4Trade.ResultRetcode()!=TRADE_RETCODE_DONE)
         { V4EAFail("close rejected: "+g_v4Trade.ResultRetcodeDescription()); return; }
         if(!V4EAReconcile(i)) V4EAFail("close reconciliation");
      }
      else if(g_v4Trades[i].virtualTrade.stop!=previous)
      {
         double size=SymbolInfoDouble(_Symbol,SYMBOL_TRADE_TICK_SIZE);
         double stop=NormalizeDouble((g_v4Trades[i].signal.isBuy?MathFloor(g_v4Trades[i].virtualTrade.stop/size):MathCeil(g_v4Trades[i].virtualTrade.stop/size))*size,_Digits);
         V4EAModify(i,stop,g_v4Trades[i].tp);
         if(g_v4IoFailed) return;
      }
   }
}
void V4EASubmit(const SConfirmSignal &s,const MqlTick &tick)
{
   if(!MQLInfoInteger(MQL_TESTER) || !g_v4TesterReady || g_v4IoFailed) return;
   int active=0;
   for(int i=0;i<ArraySize(g_v4Trades);i++) if(!g_v4Trades[i].written) active++;
   if(active>=(InpAllowMultiplePositions?InpMaxTesterPositions:1)) { V4EAEvent(s.signal_id,"SKIPPED","POSITION_LIMIT"); return; }
   if(tick.time<s.signal_known_time || tick.time>=s.signal_known_time+240*60)
   { V4EAEvent(s.signal_id,"SKIPPED","EXPIRED_OR_FUTURE_SIGNAL"); return; }
   SV4SymbolSpec spec;
   if(!V4SymbolSpec(_Symbol,spec)) { V4EAFail("symbol spec"); return; }
   double quote=s.isBuy?tick.ask:tick.bid;
   double risk=(quote-s.initialSl)*(s.isBuy?1:-1);
   if(risk<=0) { V4EAEvent(s.signal_id,"SKIPPED","INVALID_STOP"); return; }
   double sl=NormalizeDouble((s.isBuy?MathFloor(s.initialSl/spec.tickSize):MathCeil(s.initialSl/spec.tickSize))*spec.tickSize,_Digits);
   risk=(quote-sl)*(s.isBuy?1:-1);
   double equity=AccountInfoDouble(ACCOUNT_EQUITY);
   double perLot=V4RiskMoney(s.isBuy,quote,sl,1,spec);
   double lots=V4LotsFromRisk(equity,InpRiskPercent,perLot,spec);
   if(lots<=0) { V4EAFail("invalid lots"); return; }
   bool sent=s.isBuy?g_v4Trade.Buy(lots,_Symbol,0,sl,0,s.signal_id):g_v4Trade.Sell(lots,_Symbol,0,sl,0,s.signal_id);
   if(!sent || (g_v4Trade.ResultRetcode()!=TRADE_RETCODE_DONE && g_v4Trade.ResultRetcode()!=TRADE_RETCODE_DONE_PARTIAL))
   { V4EAEvent(s.signal_id,"REJECTED",g_v4Trade.ResultRetcodeDescription()); return; }
   if(g_v4Trade.ResultRetcode()==TRADE_RETCODE_DONE_PARTIAL) { V4EAFail("partial market entry requires M3b validation"); return; }
   ulong deal=g_v4Trade.ResultDeal();
   if(!HistoryDealSelect(deal)) { V4EAFail("entry deal missing"); return; }
   long pos=HistoryDealGetInteger(deal,DEAL_POSITION_ID),fillMsc=HistoryDealGetInteger(deal,DEAL_TIME_MSC);
   double fill=HistoryDealGetDouble(deal,DEAL_PRICE),filledVolume=HistoryDealGetDouble(deal,DEAL_VOLUME);
   ulong ticket=0;
   for(int i=0;i<PositionsTotal();i++)
   { ulong t=PositionGetTicket(i); if(PositionGetInteger(POSITION_IDENTIFIER)==pos) { ticket=t; break; } }
   if(ticket==0 || fillMsc<(long)s.signal_known_time*1000) { V4EAFail("entry position/time mismatch"); return; }
   int n=ArraySize(g_v4Trades); ArrayResize(g_v4Trades,n+1); ZeroMemory(g_v4Trades[n]);
   g_v4Trades[n].signal=s; g_v4Trades[n].signal.initialSl=sl; g_v4Trades[n].signal.order_place_time=tick.time;
   g_v4Trades[n].position=(ulong)pos; g_v4Trades[n].ticket=ticket; g_v4Trades[n].fillMsc=fillMsc;
   g_v4Trades[n].volume=filledVolume;
   SV4VirtualTrade v; ZeroMemory(v); v.id=s.signal_id; v.source="TESTER"; v.buy=s.isBuy;
   v.known=s.signal_known_time; v.published=s.publish_time; v.initialSl=sl; v.stop=sl;
   v.entry=fill; v.fill=(datetime)(fillMsc/1000); v.filled=true; v.risk=(fill-sl)*(s.isBuy?1:-1); v.spread=tick.ask-tick.bid;
   if(v.risk<=0) { V4EAFail("fill crossed SL"); return; }
   g_v4Trades[n].virtualTrade=v; g_v4Trades[n].riskUSD=V4RiskMoney(s.isBuy,fill,sl,filledVolume,spec);
   g_v4Trades[n].spreadUSD=v.spread>0?V4RiskMoney(s.isBuy,fill,fill-(s.isBuy?1:-1)*v.spread,filledVolume,spec):0;
   g_v4Trades[n].tp=InpScoreExit==EXIT_1R?NormalizeDouble(MathRound((fill+(s.isBuy?1:-1)*v.risk)/spec.tickSize)*spec.tickSize,_Digits):0;
   if(g_v4Trades[n].riskUSD<=0 || (v.spread>0 && g_v4Trades[n].spreadUSD<=0)) { V4EAFail("fill risk oracle unavailable"); return; }
   double fillPerLot=V4RiskMoney(s.isBuy,fill,sl,1,spec);
   FileWrite(g_v4RiskAudit,s.signal_id,equity,InpRiskPercent,equity*InpRiskPercent/100,perLot,filledVolume,spec.step,g_v4Trades[n].riskUSD,fillPerLot*spec.step,V4TickRiskMoney(v.risk,filledVolume,spec),fill,sl);
   FileFlush(g_v4RiskAudit);
   V4EAModify(n,sl,g_v4Trades[n].tp);
   V4EAEvent(s.signal_id,"FILLED",(string)pos);
}
int OnInit()
{
   // This guard precedes handles, ledgers and every CTrade operation.
   if(!MQLInfoInteger(MQL_TESTER))
   {
      int f=FileOpen("V4_TESTER_OUTSIDE_REJECTED.txt",FILE_WRITE|FILE_TXT|FILE_ANSI);
      if(f!=INVALID_HANDLE) { FileWriteString(f,"INIT_FAILED: STRATEGY_TESTER_ONLY; orders_sent=0"); FileClose(f); }
      Print("V4_TESTER_OUTSIDE_REJECTED orders_sent=0"); return INIT_FAILED;
   }
   if(InpPriceScaleMode<0 || InpPriceScaleMode>1 || InpCompatV301 || !UseLtfConfirm || InpRiskPercent<=0 || InpMaxTesterPositions<1 || MaxSpreadPrice<=0 || InpSlippagePoints<0)
      return INIT_PARAMETERS_INCORRECT;
   if(InpAllowMultiplePositions && AccountInfoInteger(ACCOUNT_MARGIN_MODE)!=ACCOUNT_MARGIN_MODE_RETAIL_HEDGING)
      return INIT_PARAMETERS_INCORRECT;
   g_v4QuietPlan=true; g_v4RenderSource=false;
   g_atrHandle=iATR(_Symbol,PERIOD_CURRENT,AtrLen);
   g_htfAtrHandle=iATR(_Symbol,HtfPeriod==PERIOD_CURRENT?Period():HtfPeriod,AtrLen);
   g_ltfAtrHandle=iATR(_Symbol,LtfPeriod==PERIOD_CURRENT?Period():LtfPeriod,AtrLen);
   if(g_atrHandle==INVALID_HANDLE || g_htfAtrHandle==INVALID_HANDLE || g_ltfAtrHandle==INVALID_HANDLE) return INIT_FAILED;
   string folder=InpV4LedgerFolder+"\\Tester"; FolderCreate(InpV4LedgerFolder); FolderCreate(folder);
   g_v4DiagRejectFile=FileOpen(folder+"\\rejected_confirmations.csv",FILE_WRITE|FILE_CSV|FILE_ANSI,',');
   if(g_v4DiagRejectFile!=INVALID_HANDLE) FileWrite(g_v4DiagRejectFile,"reason","known","risk_price","max_risk_price","rr1","rr2");
   g_v4Preset=V4Preset();
   g_v4SignalsFile=FileOpen(folder+"\\signals_"+_Symbol+".csv",FILE_WRITE|FILE_READ|FILE_CSV|FILE_ANSI,',',CP_UTF8);
   g_v4TradeFile=FileOpen(folder+"\\trades_"+_Symbol+".csv",FILE_WRITE|FILE_TXT|FILE_ANSI,0,CP_UTF8);
   g_v4ExecutionEvents=FileOpen(folder+"\\execution_events_"+_Symbol+".csv",FILE_WRITE|FILE_CSV|FILE_ANSI,',',CP_UTF8);
   g_v4RiskAudit=FileOpen(folder+"\\risk_audit.csv",FILE_WRITE|FILE_CSV|FILE_ANSI,',',CP_UTF8);
   if(g_v4RiskAudit==INVALID_HANDLE) return INIT_FAILED;
   FileWrite(g_v4RiskAudit,"signal_id","equity","risk_percent","target_cash","oracle_per_lot","volume","step","actual_sl_cash","one_step_cash","tick_formula_cash","fill","sl");
   if(g_v4SignalsFile==INVALID_HANDLE || g_v4TradeFile==INVALID_HANDLE || g_v4ExecutionEvents==INVALID_HANDLE || !V4Header(g_v4SignalsFile)) return INIT_FAILED;
   FileWriteString(g_v4TradeFile,V4TradeHeader()+"\r\n"); FileClose(g_v4TradeFile);
   g_v4TradeFile=FileOpen(folder+"\\trades_"+_Symbol+".csv",FILE_READ|FILE_WRITE|FILE_CSV|FILE_ANSI,',',CP_UTF8);
   FileSeek(g_v4TradeFile,0,SEEK_END); FileWrite(g_v4ExecutionEvents,"signal_id","time","action","detail");
   g_v4Trade.SetExpertMagicNumber(InpTesterMagic); g_v4Trade.SetDeviationInPoints((ulong)MathCeil(InpSlippagePoints));
   g_v4Trade.SetAsyncMode(false); g_v4Trade.SetTypeFillingBySymbol(_Symbol); g_v4TesterReady=true;
   return INIT_SUCCEEDED;
}
void OnTick()
{
   if(!g_v4TesterReady || !MQLInfoInteger(MQL_TESTER) || g_v4IoFailed) return;
   g_v4DiagTicks++;
   MqlTick tick; if(!SymbolInfoTick(_Symbol,tick) || tick.bid<=0 || tick.ask<tick.bid) return;
   double actualSpread=tick.ask-tick.bid;g_v4DiagTickSpreadN++;
   g_v4DiagTickSpreadMin=MathMin(g_v4DiagTickSpreadMin,actualSpread);g_v4DiagTickSpreadMax=MathMax(g_v4DiagTickSpreadMax,actualSpread);g_v4DiagTickSpreadSum+=actualSpread;
   if(actualSpread>MaxSpreadPrice)g_v4DiagTickSpreadBlocked++;
   double scale; if(!V4PriceFactor(tick.time,scale)) return;
   g_v4Trade.SetDeviationInPoints((ulong)MathCeil(InpSlippagePoints*scale));
   V4EAManage(tick); if(g_v4IoFailed) return;
   ENUM_TIMEFRAMES tf=LtfPeriod==PERIOD_CURRENT?Period():LtfPeriod;
   if(iTime(_Symbol,tf,1)<=g_v4LastEvaluated) return;
   int previous=g_v4LastEvaluated>0?iBarShift(_Symbol,tf,g_v4LastEvaluated,true):1;
   if(previous<0) { V4EAFail("missing catchup history"); return; }
   int start=ArraySize(g_v4History);
   for(int shift=MathMax(0,previous-2);shift>=0;shift--)
      if(!V4EAObserve(iTime(_Symbol,tf,shift),tick.time)) break;
   g_v4ReplayTime=0; g_v4PublishTime=0; g_v4Now=tick.time;
   for(int i=start;i<ArraySize(g_v4History) && !g_v4IoFailed;i++) V4EASubmit(g_v4History[i],tick);
}
void OnDeinit(const int reason)
{
   if(!g_v4TesterReady) return;
   string diag=StringFormat("ticks=%I64d observations=%I64d zone_rates_not_ready=%I64d zone_atr_not_ready=%I64d ltf_rates_not_ready=%I64d ltf_atr_not_ready=%I64d spread_n=%I64d spread_blocked=%I64d spread_min=%.8f spread_max=%.8f spread_mean=%.8f candidates=%I64d published=%I64d last_evaluated=%I64d",
      g_v4DiagTicks,g_v4DiagObservations,g_v4DiagZoneRates,g_v4DiagZoneAtr,g_v4DiagLtfRates,g_v4DiagLtfAtr,g_v4DiagSpreadN,g_v4DiagSpreadBlocked,
      g_v4DiagSpreadN>0?g_v4DiagSpreadMin:0,g_v4DiagSpreadMax,g_v4DiagSpreadN>0?g_v4DiagSpreadSum/g_v4DiagSpreadN:0,g_v4Candidates,g_v4Published,(long)g_v4LastEvaluated);
   diag+=StringFormat(" eligible=%I64d poi=%I64d sweep=%I64d confirm=%I64d risk_rejected=%I64d rr_rejected=%I64d",g_v4DiagEligible,g_v4DiagPoi,g_v4DiagSweep,g_v4DiagConfirm,g_v4DiagRisk,g_v4DiagRR);
   diag+=StringFormat(" tick_spread_n=%I64d tick_spread_blocked=%I64d tick_spread_min=%.8f tick_spread_max=%.8f tick_spread_mean=%.8f",g_v4DiagTickSpreadN,g_v4DiagTickSpreadBlocked,g_v4DiagTickSpreadN>0?g_v4DiagTickSpreadMin:0,g_v4DiagTickSpreadMax,g_v4DiagTickSpreadN>0?g_v4DiagTickSpreadSum/g_v4DiagTickSpreadN:0);
   Print("V4_DIAGNOSTICS ",diag);
   if(g_v4DiagRejectFile!=INVALID_HANDLE) FileClose(g_v4DiagRejectFile);
   int diagnosticFile=FileOpen(InpV4LedgerFolder+"\\Tester\\diagnostics.txt",FILE_WRITE|FILE_TXT|FILE_ANSI);
   if(diagnosticFile!=INVALID_HANDLE) { FileWriteString(diagnosticFile,diag); FileClose(diagnosticFile); }
   for(int i=0;i<ArraySize(g_v4Trades);i++) if(!g_v4Trades[i].written)
   {
      if(!V4EAReconcile(i)) V4TesterWrite(g_v4TradeFile,g_v4Trades[i],0,0,0,"END_WITH_OPEN_POSITION",0,0,0,0,"OPEN_NOT_PNL");
   }
   V4CloseLedger();
   if(g_v4TradeFile!=INVALID_HANDLE) FileClose(g_v4TradeFile);
   if(g_v4ExecutionEvents!=INVALID_HANDLE) FileClose(g_v4ExecutionEvents);
   if(g_v4RiskAudit!=INVALID_HANDLE) FileClose(g_v4RiskAudit);
   IndicatorRelease(g_atrHandle); IndicatorRelease(g_htfAtrHandle); IndicatorRelease(g_ltfAtrHandle);
}
