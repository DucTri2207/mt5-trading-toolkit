#ifndef CHT_V4_TESTER_LEDGER
#define CHT_V4_TESTER_LEDGER
string V4TradeHeader()
{
   return "signal_id,mode,direction,confirm_bar_open,signal_known_time,publish_time,order_place_time,fill_time,exit_time,entry,initial_sl,tp,risk_price,risk_USD,exit_price,exit_reason,gross_USD,commission_USD,swap_USD,fee_USD,net_USD,net_R,MFE_R,MAE_R,source_zone_id,cost_R,volume,position_id,status,fill_time_msc,exit_time_msc";
}
struct SV4TesterRecord
{
   SConfirmSignal signal;
   SV4VirtualTrade virtualTrade;
   ulong position,ticket;
   double volume,riskUSD,tp,mae,spreadUSD;
   bool written;
   string requestedExit;
   long fillMsc;
};
bool V4TesterWrite(int f,const SV4TesterRecord &r,datetime exitTime,long exitMsc,double exitPrice,string reason,
                    double gross,double commission,double swap,double fee,string status)
{
   double net=gross+commission+swap+fee;
   double cost=0;
   if(r.riskUSD>0) cost=(r.spreadUSD-commission-fee)/r.riskUSD;
   ResetLastError();
   uint n=FileWrite(f,r.signal.signal_id,"REVERSAL_B0v4",r.signal.isBuy?"BUY":"SELL",(long)r.signal.confirm_bar_open,
      (long)r.signal.signal_known_time,(long)r.signal.publish_time,(long)r.signal.order_place_time,(long)r.virtualTrade.fill,
      (long)exitTime,r.virtualTrade.entry,r.signal.initialSl,r.tp,r.virtualTrade.risk,r.riskUSD,exitPrice,reason,
      gross,commission,swap,fee,net,r.riskUSD>0?DoubleToString(net/r.riskUSD,10):"NA",
      r.virtualTrade.risk>0?r.virtualTrade.mfe/r.virtualTrade.risk:0,r.mae,r.signal.source_zone_id,cost,
      r.volume,r.position,status,r.fillMsc,exitMsc);
   FileFlush(f); return n>0 && GetLastError()==0;
}
#endif
