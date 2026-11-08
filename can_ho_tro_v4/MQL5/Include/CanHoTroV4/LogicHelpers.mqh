#ifndef CHT_V4_LOGIC_HELPERS
#define CHT_V4_LOGIC_HELPERS
bool g_v4QuietPlan=false;
double GetPipSize()
{
   string sym = _Symbol;
   StringToUpper(sym);
   if(StringFind(sym, "XAU") >= 0 || StringFind(sym, "GOLD") >= 0 ||
      StringFind(sym, "XAG") >= 0 || StringFind(sym, "SILVER") >= 0)
   {
      return 0.1;
   }
   if(_Digits == 5 || _Digits == 3)
      return _Point * 10.0;
   else if(_Digits == 4 || _Digits == 2)
      return _Point;
   else if(_Digits == 1)
      return _Point * 10.0;
   else
      return (_Point > 0) ? _Point : 1.0;
}

double PriceToPips(double priceDiff)
{
   double pipSize = GetPipSize();
   return (pipSize > 0) ? (MathAbs(priceDiff) / pipSize) : 0.0;
}

bool IsInKillzone(datetime barTime)
{
   if(!FilterKillzones)
      return true; // Chế độ 24/5 linh hoạt

   MqlDateTime dt;
   TimeToStruct(barTime, dt);
   int h = dt.hour;

   // London Killzone: 08:00 - 12:00 broker | New York Killzone: 13:00 - 17:00 broker
   bool isLondon = (h >= 8 && h <= 12);
   bool isNY     = (h >= 13 && h <= 17);
   return (isLondon || isNY);
}

void RefreshReferenceLevels()
{
   MqlRates d1[];
   ArraySetAsSeries(d1,true);
   int copied=V4DataRates(_Symbol,PERIOD_D1,1,2,d1);
   if(copied<1 || d1[0].time<=0 || d1[0].high<=d1[0].low)
      return;
   g_previousDayTime=d1[0].time;
   g_previousDayHigh=d1[0].high;
   g_previousDayLow=d1[0].low;
}

void ManageActiveSignal(double curPrice)
{
   if(!g_lastSignal.active) return;

   double favorablePts = g_lastSignal.isBuy ? (curPrice - g_lastSignal.entry) : (g_lastSignal.entry - curPrice);
    // PriceToPips is absolute for display distances. BE/MFE need signed
    // progress so an adverse move can never count as favorable movement.
    double favorablePips = favorablePts > 0.0 ? favorablePts / GetPipSize() : 0.0;
   if(favorablePips > g_lastSignal.maxMfePips)
      g_lastSignal.maxMfePips = favorablePips;

   // 1. Kiểm tra kích hoạt Auto Break-Even (BE)
   bool triggerBe = false;
   if(InpUseAutoBE && !g_lastSignal.isBeActive)
   {
      if(InpBeTriggerPips > 0 && favorablePips >= V4Distance(InpBeTriggerPips))
         triggerBe = true;
      if(InpBeTriggerATR > 0 && g_lastSignal.ltfAtr > 0 && favorablePts >= InpBeTriggerATR * g_lastSignal.ltfAtr)
         triggerBe = true;
   }

   if(triggerBe)
   {
      g_lastSignal.isBeActive = true;
      g_lastSignal.sl = g_lastSignal.bePrice;

      // Cập nhật đường trên biểu đồ
      if(ShowTradeLines)
         DrawTradePlanLines(g_lastSignal);

      // Bắn Alert & Telegram
      if(AlertBeTriggered && !g_v4QuietPlan)
      {
         string tfLtf = EnumToString(LtfPeriod);
         StringReplace(tfLtf, "PERIOD_", "");
          string beMsg = StringFormat("🛡️ [%s %s] BE SUGGESTION (INDICATOR ONLY)\nGiá chạy thuận +%.1f pips (+$%.2f).\nMức BE đề xuất: %.*f. Broker SL chưa bị thay đổi.",
                                     _Symbol, tfLtf, favorablePips, favorablePts, _Digits, g_lastSignal.bePrice);
         if(AlertPopup) Alert(beMsg);
         if(AlertSoundOn) PlaySound(AlertSoundFile);
         if(AlertPush) SendNotification(beMsg);
         if(TgEnable) SendBeTelegram(g_lastSignal, favorablePips, favorablePts);

         // Thêm vào nhật ký sự kiện của Dashboard
         string evText = StringFormat("🛡️ AUTO-BE %s: Dời SL về BE %.*f (+%.1fp)",
                                      g_lastSignal.isBuy ? "BUY" : "SELL", _Digits, g_lastSignal.bePrice, favorablePips);
         SEventLog ev;
         ev.text = evText;
         ev.dotColor = C'56,189,248'; // Xanh Cyan
         ev.barsAgo = 0;
         ArrayResize(g_events, ArraySize(g_events) + 1);
         for(int k = ArraySize(g_events) - 1; k > 0; k--)
            g_events[k] = g_events[k - 1];
         g_events[0] = ev;
         if(ArraySize(g_events) > 5) ArrayResize(g_events, 5);
      }
   }

   // 2. Kiểm tra chạm TP1
   if(!g_lastSignal.hitTp1)
   {
      if((g_lastSignal.isBuy && curPrice >= g_lastSignal.tp1) ||
         (!g_lastSignal.isBuy && curPrice <= g_lastSignal.tp1))
      {
         g_lastSignal.hitTp1 = true;
         // Tự động bảo hiểm dời BE nếu chưa kích hoạt
         if(InpUseAutoBE && !g_lastSignal.isBeActive)
         {
            g_lastSignal.isBeActive = true;
            g_lastSignal.sl = g_lastSignal.bePrice;
            if(ShowTradeLines) DrawTradePlanLines(g_lastSignal);
         }

         // Ghi nhật ký sự kiện TP1 vào Dashboard
         string evText = StringFormat("🎉 TP1 HIT %s: Chốt lời 1 đạt %.*f (+%.1fp)",
                                      g_lastSignal.isBuy ? "BUY" : "SELL", _Digits, g_lastSignal.tp1, PriceToPips(MathAbs(g_lastSignal.tp1 - g_lastSignal.entry)));
         SEventLog ev;
         ev.text = evText;
         ev.dotColor = C'52,211,153'; // Mint Green
         ev.barsAgo = 0;
         ArrayResize(g_events, ArraySize(g_events) + 1);
         for(int k = ArraySize(g_events) - 1; k > 0; k--)
            g_events[k] = g_events[k - 1];
         g_events[0] = ev;
         if(ArraySize(g_events) > 5) ArrayResize(g_events, 5);
      }
   }

   // 3. Kiểm tra chạm TP2
   if(!g_lastSignal.hitTp2)
   {
      if((g_lastSignal.isBuy && curPrice >= g_lastSignal.tp2) ||
         (!g_lastSignal.isBuy && curPrice <= g_lastSignal.tp2))
      {
         g_lastSignal.hitTp2 = true;

         // Ghi nhật ký sự kiện TP2 vào Dashboard
         string evText = StringFormat("🚀 TP2 HIT %s: Đạt mục tiêu TP2 %.*f (%.1fR)",
                                      g_lastSignal.isBuy ? "BUY" : "SELL", _Digits, g_lastSignal.tp2, g_lastSignal.rr2);
         SEventLog ev;
         ev.text = evText;
         ev.dotColor = C'250,204,21'; // Vàng Kim
         ev.barsAgo = 0;
         ArrayResize(g_events, ArraySize(g_events) + 1);
         for(int k = ArraySize(g_events) - 1; k > 0; k--)
            g_events[k] = g_events[k - 1];
         g_events[0] = ev;
         if(ArraySize(g_events) > 5) ArrayResize(g_events, 5);
      }
   }

   // 4. Kiểm tra kết thúc vị thế (chạm SL/BE hoặc TP2)
   bool isClosed = false;
   if(g_lastSignal.isBuy)
   {
      if(curPrice <= g_lastSignal.sl || curPrice >= g_lastSignal.tp2)
         isClosed = true;
   }
   else
   {
      if(curPrice >= g_lastSignal.sl || curPrice <= g_lastSignal.tp2)
         isClosed = true;
   }

   if(isClosed)
   {
      g_lastSignal.active = false;
      if(ShowTradeLines)
         RemoveTradePlanLines();
   }
   else if(ShowTradeLines)
   {
      // Cập nhật kéo dài đường kế hoạch theo nến mới
      DrawTradePlanLines(g_lastSignal);
   }
}
#endif
