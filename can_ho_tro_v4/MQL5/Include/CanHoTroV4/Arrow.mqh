#ifndef CHT_V4_ARROW
#define CHT_V4_ARROW
bool g_v4BatchArrows=false;
void DrawSignalArrow(bool isBuy, datetime t, double p, double atr)
{
   if(!ShowArrows) return;

   string id=(string)(long)t,tooltip="";
   for(int i=0;i<ArraySize(g_v4History);i++)
      if(g_v4History[i].time==t && g_v4History[i].isBuy==isBuy)
      {
         SConfirmSignal sig=g_v4History[i];id=sig.signal_id;
         tooltip=StringFormat("%s server | M5 %s | %s\nEntry %.5f SL %.5f TP1 %.5f TP2 %.5f\nZone #%I64d %s | risk %.5f (%.2f%% equity)",TimeToString(sig.signal_known_time,TIME_DATE|TIME_SECONDS),TimeToString(t),isBuy?"BUY":"SELL",sig.entry,sig.initialSl,sig.tp1,sig.tp2,sig.source_zone_id,sig.zoneType,MathAbs(sig.entry-sig.initialSl),InpRiskPercent);
         break;
      }
   string arrowName=g_prefix+"SIG_"+id,labelName=g_prefix+"LBL_"+id;
   datetime mapped=t;
   int shift=iBarShift(_Symbol,Period(),t,false);
   if(shift>=0)mapped=iTime(_Symbol,Period(),shift);
   color  sigClr    = isBuy ? C'52,211,153' : C'248,113,113';

   double arrowPrice = isBuy ? (p - 0.25 * atr) : (p + 0.25 * atr);
   double labelPrice = isBuy ? (p - 0.75 * atr) : (p + 0.75 * atr);

   if(ObjectFind(0, arrowName) < 0)
   {
      ENUM_OBJECT objType = isBuy ? OBJ_ARROW_BUY : OBJ_ARROW_SELL;
      if(ObjectCreate(0, arrowName, objType, 0, mapped, arrowPrice))
      {
         ObjectSetInteger(0, arrowName, OBJPROP_COLOR, sigClr);
         ObjectSetInteger(0, arrowName, OBJPROP_WIDTH, ArrowSize);
         ObjectSetInteger(0, arrowName, OBJPROP_BACK, false);
      }
   }

   if(ObjectFind(0, labelName) < 0)
   {
      if(ObjectCreate(0, labelName, OBJ_TEXT, 0, mapped, labelPrice))
      {
         ObjectSetString(0, labelName, OBJPROP_TEXT, isBuy ? " BUY CHoCH" : " SELL CHoCH");
         ObjectSetString(0, labelName, OBJPROP_FONT, "Segoe UI Semibold");
         ObjectSetInteger(0, labelName, OBJPROP_FONTSIZE, 8);
         ObjectSetInteger(0, labelName, OBJPROP_COLOR, sigClr);
         ObjectSetInteger(0, labelName, OBJPROP_ANCHOR, isBuy ? ANCHOR_UPPER : ANCHOR_LOWER);
      }
   }

   ObjectSetInteger(0,arrowName,OBJPROP_TIME,0,mapped);
   ObjectSetInteger(0,labelName,OBJPROP_TIME,0,mapped);
   ObjectSetString(0,arrowName,OBJPROP_TOOLTIP,tooltip);
   ObjectSetString(0,labelName,OBJPROP_TOOLTIP,tooltip);
   if(!g_v4BatchArrows) ChartRedraw(0);
}
#endif
