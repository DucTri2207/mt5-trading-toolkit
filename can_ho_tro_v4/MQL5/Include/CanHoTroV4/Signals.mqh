#ifndef CHT_V4_SIGNALS
#define CHT_V4_SIGNALS
class CSignalEngine { public: static void Detect(bool isFirstRun=false,bool guardProbe=false); };
void CSignalEngine::Detect(bool isFirstRun,bool guardProbe)
{
   ENUM_TIMEFRAMES ltf = (LtfPeriod == PERIOD_CURRENT) ? PERIOD_M5 : LtfPeriod;
   int barsNeeded = MathMin(LtfBarsScan, 350);

   MqlRates ltfRates[];
   ArraySetAsSeries(ltfRates, true); // Index 0 là nến đang chạy, 1 là nến đóng cửa gần nhất
   int copied = V4DataRates(_Symbol, ltf, 0, barsNeeded, ltfRates);
   if(copied < 30)
   { g_v4DiagLtfRates++; return; }

   double ltfAtrBuffer[];
   ArraySetAsSeries(ltfAtrBuffer, true);
   int atrH = g_ltfAtrHandle;
   if(atrH == INVALID_HANDLE || V4DataBuffer(atrH, ltf, 0, copied, ltfAtrBuffer) < copied)
   { g_v4DiagLtfAtr++; return; }

   if(!guardProbe && !InpCompatV301 && ltfRates[1].time <= g_v4LastEvaluated) return;
   double ltfAtr = (ltfAtrBuffer[1] > 0) ? ltfAtrBuffer[1] : (GetPipSize() * 10);
   double curPrice = SymbolInfoDouble(_Symbol, SYMBOL_BID);
   MqlTick liveTick;
   if(!V4DataTick(liveTick) || liveTick.bid<=0.0 || liveTick.ask<liveTick.bid)
      return;
   if(!guardProbe)
   {
      double spread=liveTick.ask-liveTick.bid; g_v4DiagSpreadN++;
      g_v4DiagSpreadMin=MathMin(g_v4DiagSpreadMin,spread); g_v4DiagSpreadMax=MathMax(g_v4DiagSpreadMax,spread); g_v4DiagSpreadSum+=spread;
   }
   if((liveTick.ask-liveTick.bid) > V4Distance(MaxSpreadPrice))
   {
      if(!guardProbe) g_v4DiagSpreadBlocked++;
      g_confirmState=STATE_IDLE;
      return;
   }
   if(!InpCompatV301) curPrice=liveTick.bid;
   if(!InpCompatV301 && !guardProbe) { Detect(isFirstRun,true); g_v4LastEvaluated = ltfRates[1].time; }

   // Trạng thái quét ban đầu
   ENUM_CONFIRM_STATE calculatedState = STATE_IDLE;
   bool sweepFoundGlobal = false;
   bool inPoiGlobal = false;

   // 1. Quét tương tác với các vùng cản H1
   for(int z = 0; z < ArraySize(g_zones); z++)
   {
      if(g_zones[z].isBroken || g_zones[z].score < MinScoreShow)
         continue;

      if(!InpCompatV301 && !guardProbe && !V4ZoneAvailable(g_zones[z],g_v4Now)) continue;
      if(!guardProbe) g_v4DiagEligible++;
      double zMin = MathMin(g_zones[z].distal, g_zones[z].proximal);
      double zMax = MathMax(g_zones[z].distal, g_zones[z].proximal);
      bool isSupply = g_zones[z].isSupply;

      // Kiểm tra giá hiện tại hoặc các nến gần đây có chạm cản H1 không
      bool priceInZone = false;
       // The forming LTF bar (index 0) cannot establish POI interaction.
       for(int k = 1; k <= 20 && k < copied; k++)
      {
         if(isSupply)
         {
            if(ltfRates[k].high >= zMin - 0.2 * ltfAtr && ltfRates[k].low <= zMax + 0.5 * ltfAtr)
            {
               priceInZone = true;
               break;
            }
         }
         else
         {
            if(ltfRates[k].low <= zMax + 0.2 * ltfAtr && ltfRates[k].high >= zMin - 0.5 * ltfAtr)
            {
               priceInZone = true;
               break;
            }
         }
      }

      if(!priceInZone) continue;
      if(!guardProbe) g_v4DiagPoi++;
      inPoiGlobal = true;

      // 2. Phát hiện Râu Quét Thanh Khoản (Liquidity Sweep / Wick Rejection >= 35%)
      bool sweepFound = false;
      int sweepBar = -1;
      double sweepPrice = isSupply ? -1.0 : 9999999.0;

      for(int s = 1; s <= 20 && s < copied; s++)
      {
         if(!InpCompatV301 && !guardProbe && !V4SweepAvailable(g_zones[z],ltfRates[s].time)) continue;
         double fullRng = ltfRates[s].high - ltfRates[s].low;
         if(fullRng < 0.25 * ltfAtr) continue; // Bỏ qua nến nhiễu biên độ quá nhỏ

         if(isSupply)
         {
            double upperWick = ltfRates[s].high - MathMax(ltfRates[s].open, ltfRates[s].close);
            double wickRatio = upperWick / fullRng;
            if(wickRatio >= WickRatioMin && ltfRates[s].high >= zMin)
            {
               if(ltfRates[s].high > sweepPrice)
               {
                  sweepPrice = ltfRates[s].high;
                  sweepBar = s;
                  sweepFound = true;
               }
            }
         }
         else
         {
            double lowerWick = MathMin(ltfRates[s].open, ltfRates[s].close) - ltfRates[s].low;
            double wickRatio = lowerWick / fullRng;
            if(wickRatio >= WickRatioMin && ltfRates[s].low <= zMax)
            {
               if(ltfRates[s].low < sweepPrice)
               {
                  sweepPrice = ltfRates[s].low;
                  sweepBar = s;
                  sweepFound = true;
               }
            }
         }
      }

      if(!sweepFound || sweepBar < 1) continue;
      if(!guardProbe) g_v4DiagSweep++;
      sweepFoundGlobal = true;

      // 3. Tìm Đỉnh/Đáy vi mô dẫn dụ (Minor Swing Pivot) ngay trước cú quét
      double chochLevel = 0.0;
      int swStart = sweepBar + 1;
      int swEnd   = MathMin(copied - 2, sweepBar + 8);

      if(isSupply)
      {
         // Canh BÁN: Tìm minor swing low dẫn dụ trước cú quét lên cản
         chochLevel = 9999999.0;
         bool foundPivot = false;
         for(int sw = swStart; sw <= swEnd; sw++)
         {
            if(sw > 0 && sw < copied - 1)
            {
               if(ltfRates[sw].low <= ltfRates[sw - 1].low && ltfRates[sw].low <= ltfRates[sw + 1].low)
               {
                  chochLevel = ltfRates[sw].low;
                  foundPivot = true;
                  break;
               }
            }
         }
         if(!foundPivot)
         {
            for(int sw = swStart; sw <= MathMin(copied - 1, sweepBar + 4); sw++)
            {
               if(ltfRates[sw].low < chochLevel)
                  chochLevel = ltfRates[sw].low;
            }
         }
      }
      else
      {
         // Canh MUA: Tìm minor swing high dẫn dụ trước cú quét xuống cản
         chochLevel = -1.0;
         bool foundPivot = false;
         for(int sw = swStart; sw <= swEnd; sw++)
         {
            if(sw > 0 && sw < copied - 1)
            {
               if(ltfRates[sw].high >= ltfRates[sw - 1].high && ltfRates[sw].high >= ltfRates[sw + 1].high)
               {
                  chochLevel = ltfRates[sw].high;
                  foundPivot = true;
                  break;
               }
            }
         }
         if(!foundPivot)
         {
            for(int sw = swStart; sw <= MathMin(copied - 1, sweepBar + 4); sw++)
            {
               if(ltfRates[sw].high > chochLevel)
                  chochLevel = ltfRates[sw].high;
            }
         }
      }

      // 4. Kiểm tra nến xác nhận CHoCH đã đóng cửa hoàn chỉnh (100% NON-REPAINTING)
      bool isBuySignal = !isSupply;
      int confirmBar = -1;

      for(int c = sweepBar - 1; c >= 1; c--)
      {
         if(isBuySignal)
         {
            // BUY CHoCH: Nến xanh đóng cửa cao hơn swing high dẫn dụ
            if(chochLevel > 0 && ltfRates[c].close > chochLevel && ltfRates[c].close > ltfRates[c].open)
            {
               bool priorBreak = false;
               for(int p = sweepBar - 1; p > c; p--)
               {
                  if(ltfRates[p].close > chochLevel) { priorBreak = true; break; }
               }
               if(!priorBreak)
               {
                  confirmBar = c;
                  break;
               }
            }
         }
         else
         {
            // SELL CHoCH: Nến đỏ đóng cửa thấp hơn swing low dẫn dụ
            if(chochLevel < 9999990.0 && ltfRates[c].close < chochLevel && ltfRates[c].close < ltfRates[c].open)
            {
               bool priorBreak = false;
               for(int p = sweepBar - 1; p > c; p--)
               {
                  if(ltfRates[p].close < chochLevel) { priorBreak = true; break; }
               }
               if(!priorBreak)
               {
                  confirmBar = c;
                  break;
               }
            }
         }
      }

      // Nếu tìm thấy nến xác nhận
      if(confirmBar >= 1)
      {
         // Nếu nến xác nhận vừa đóng cửa ở bar 1 (Tín hiệu thời gian thực)
         // Hoặc nến xác nhận gần đây (bar 1..20) khi khởi động lại indicator mà vị thế chưa chạm SL/TP2
         bool isRealtimeBar1 = (confirmBar == 1);
          // Do not resurrect a historical plan on attach/reload. A signal is
          // actionable only when its newly closed confirmation bar is observed.
          bool shouldRestore  = false;

         if((isRealtimeBar1 || shouldRestore) && IsInKillzone(ltfRates[confirmBar].time))
         {
            if(!guardProbe) g_v4DiagConfirm++;
            int cBar = confirmBar;
            calculatedState = STATE_CONFIRMED;

            double pipSize = GetPipSize();
            double entryMarket = ltfRates[cBar].close;
            double bodyMid = (ltfRates[cBar].open + ltfRates[cBar].close) / 2.0;
            double entryLimit = bodyMid;

            // Kiểm tra FVG vi mô hình thành bởi nến xác nhận
            bool hasFvg = false;
            double fvgCe = bodyMid;
            if(isBuySignal)
            {
               if(cBar + 2 < copied && ltfRates[cBar + 2].high < ltfRates[cBar].low)
               {
                  hasFvg = true;
                  fvgCe = (ltfRates[cBar + 2].high + ltfRates[cBar].low) / 2.0;
                  entryLimit = fvgCe;
               }
            }
            else
            {
               if(cBar + 2 < copied && ltfRates[cBar + 2].low > ltfRates[cBar].high)
               {
                  hasFvg = true;
                  fvgCe = (ltfRates[cBar + 2].low + ltfRates[cBar].high) / 2.0;
                  entryLimit = fvgCe;
               }
            }

            double entry = entryMarket;
            if(InpEntryMode == ENTRY_PULLBACK_50)
               entry = bodyMid;
            else if(InpEntryMode == ENTRY_FVG_CE)
               entry = entryLimit;

            // 1. Tính toán Stop Loss chuẩn SMC Cấu Trúc (Structural Swing / Displacement Base)
            double sl = 0.0, risk = 0.0;
            double maxRisk = V4Distance(MaxSlPips) * pipSize;
            double minRisk = V4Distance(MinSlPips) * pipSize;

            if(InpSlMode == SL_STRUCTURAL_SWING)
            {
               int lookback = MathMin(copied - 1, MathMax(cBar + 4, sweepBar));
               if(isBuySignal)
               {
                  double structLow = ltfRates[cBar].low;
                  for(int b = cBar; b <= lookback; b++)
                  {
                     if(ltfRates[b].low < structLow) structLow = ltfRates[b].low;
                  }
                  sl = structLow - (SlBufferATR * ltfAtr);
                  risk = entry - sl;
                   // Preserve the structural swing. Reject an oversized stop
                   // instead of pulling it inside the invalidation level.
                   if(risk > maxRisk) { if(!guardProbe) {g_v4DiagRisk++; V4DiagReject("RISK_MAX",ltfRates[cBar].time+PeriodSeconds(ltf),risk,maxRisk);} continue; }
                  else if(risk < minRisk) { risk = minRisk; sl = entry - risk; }
               }
               else
               {
                  double structHigh = ltfRates[cBar].high;
                  for(int b = cBar; b <= lookback; b++)
                  {
                     if(ltfRates[b].high > structHigh) structHigh = ltfRates[b].high;
                  }
                  sl = structHigh + (SlBufferATR * ltfAtr);
                  risk = sl - entry;
                   // Preserve the structural swing. Reject an oversized stop
                   // instead of pulling it inside the invalidation level.
                   if(risk > maxRisk) { if(!guardProbe) {g_v4DiagRisk++; V4DiagReject("RISK_MAX",ltfRates[cBar].time+PeriodSeconds(ltf),risk,maxRisk);} continue; }
                  else if(risk < minRisk) { risk = minRisk; sl = entry + risk; }
               }
            }
            else // SL_SWEEP_DISTAL
            {
               if(isBuySignal)
               {
                  sl = sweepPrice - (SlBufferATR * ltfAtr);
                  risk = entry - sl;
                  if(risk <= 0) { risk = 1.0 * ltfAtr; sl = entry - risk; }
               }
               else
               {
                  sl = sweepPrice + (SlBufferATR * ltfAtr);
                  risk = sl - entry;
                  if(risk <= 0) { risk = 1.0 * ltfAtr; sl = entry + risk; }
               }
            }

            // 2. Tính toán Take Profit TP1 & TP2 linh hoạt (Hybrid / RR / Pips)
            double tp1 = 0.0, tp2 = 0.0;
            if(InpTpMode == TP_MODE_HYBRID)
            {
               double tp1Dist = V4Distance(InpTp1Pips) * pipSize;
               double tp2Dist = InpTp2RR * risk;
               tp1 = isBuySignal ? (entry + tp1Dist) : (entry - tp1Dist);
               tp2 = isBuySignal ? (entry + tp2Dist) : (entry - tp2Dist);
            }
            else if(InpTpMode == TP_MODE_PIPS)
            {
               double tp1Dist = V4Distance(InpTp1Pips) * pipSize;
               double tp2Dist = V4Distance(InpTp2Pips) * pipSize;
               tp1 = isBuySignal ? (entry + tp1Dist) : (entry - tp1Dist);
               tp2 = isBuySignal ? (entry + tp2Dist) : (entry - tp2Dist);
            }
            else // TP_MODE_RR
            {
               tp1 = isBuySignal ? (entry + InpTp1RR * risk) : (entry - InpTp1RR * risk);
               tp2 = isBuySignal ? (entry + InpTp2RR * risk) : (entry - InpTp2RR * risk);
            }

            // TP Macro: Cản H1 đối diện
            double tpMacro = 0.0;
            if(isBuySignal)
            {
               double minSupplyDist = 9999999.0;
               double targetSupply = entry + 4.5 * risk;
               if(UseReferenceLevels && g_previousDayHigh > entry &&
                  (g_previousDayHigh - entry) < minSupplyDist)
               {
                  minSupplyDist = g_previousDayHigh - entry;
                  targetSupply = g_previousDayHigh;
               }
               for(int s = 0; s < ArraySize(g_zones); s++)
               {
                  if(g_zones[s].isSupply && !g_zones[s].isBroken && g_zones[s].proximal > entry)
                  {
                     if((g_zones[s].proximal - entry) < minSupplyDist)
                     {
                        minSupplyDist = g_zones[s].proximal - entry;
                        targetSupply = g_zones[s].proximal;
                     }
                  }
               }
               tpMacro = targetSupply;
            }
            else
            {
               double minDemandDist = 9999999.0;
               double targetDemand = entry - 4.5 * risk;
               if(UseReferenceLevels && g_previousDayLow > 0.0 && g_previousDayLow < entry &&
                  (entry - g_previousDayLow) < minDemandDist)
               {
                  minDemandDist = entry - g_previousDayLow;
                  targetDemand = g_previousDayLow;
               }
               for(int d = 0; d < ArraySize(g_zones); d++)
               {
                  if(!g_zones[d].isSupply && !g_zones[d].isBroken && g_zones[d].proximal < entry)
                  {
                     if((entry - g_zones[d].proximal) < minDemandDist)
                     {
                        minDemandDist = entry - g_zones[d].proximal;
                        targetDemand = g_zones[d].proximal;
                     }
                  }
               }
               tpMacro = targetDemand;
            }

             double rr1 = (risk > 0) ? MathAbs(tp1 - entry) / risk : 1.5;
             double rr2 = (risk > 0) ? MathAbs(tp2 - entry) / risk : 2.0;
             if((isBuySignal && tp1 >= tp2) || (!isBuySignal && tp1 <= tp2) ||
                (InpCompatV301 ? (rr1 < MinRR || rr2 < rr1) : !V4RrAllowed(rr1,rr2)))
             { if(!guardProbe) {g_v4DiagRR++; V4DiagReject("TP_RR",ltfRates[cBar].time+PeriodSeconds(ltf),risk,maxRisk,rr1,rr2);} continue; }
            double rrMacro = (risk > 0) ? MathAbs(tpMacro - entry) / risk : 4.5;
            double bePrice = isBuySignal ? (entry + V4Distance(InpBeOffsetPips) * pipSize) : (entry - V4Distance(InpBeOffsetPips) * pipSize);

            string zTypeStr = EnumToString(g_zones[z].type);
            StringReplace(zTypeStr, "ZONE_", "");

             SConfirmSignal candidate;
             ZeroMemory(candidate);
             candidate.active      = true;
            candidate.isBuy       = isBuySignal;
            candidate.time        = ltfRates[cBar].time;
            candidate.entry       = entry;
            candidate.entryMarket = entryMarket;
            candidate.entryLimit  = entryLimit;
            candidate.sl          = sl;
            candidate.initialSl   = sl;
            candidate.tp1         = tp1;
            candidate.tp2         = tp2;
            candidate.tpMacro     = tpMacro;
            candidate.rr1         = rr1;
            candidate.rr2         = rr2;
            candidate.rrMacro     = rrMacro;
            candidate.sweepPrice  = sweepPrice;
            candidate.zoneId      = g_zones[z].id;
            candidate.zoneType    = zTypeStr;
            candidate.zoneScore   = g_zones[z].score;
            candidate.isBeActive  = false;
            candidate.bePrice     = bePrice;
            candidate.maxMfePips  = 0.0;
            candidate.hitTp1      = false;
            candidate.hitTp2      = false;
             candidate.ltfAtr      = ltfAtr;

             candidate.confirm_bar_open = ltfRates[cBar].time;
             candidate.signal_known_time = ltfRates[cBar].time + PeriodSeconds(ltf);
             candidate.publish_time = g_v4PublishTime>0 ? g_v4PublishTime : g_v4Now;
             candidate.source_zone_id = g_zones[z].id;
             candidate.zone_known_time = g_zones[z].timeKnown;
             candidate.source_distal = g_zones[z].distal;
             candidate.source_proximal = g_zones[z].proximal;
             candidate.sweep_time = ltfRates[sweepBar].time;
             candidate.choch_level = chochLevel;
             candidate.arrow_anchor = isBuySignal ? ltfRates[cBar].low : ltfRates[cBar].high;
             candidate.signal_id = V4SignalId(candidate);
             if(guardProbe)
             {
                V4GuardCandidate(candidate);
                continue;
             }
             bool sameProcessedSignal = (g_lastSignalSeenTime == candidate.time &&
                                         g_lastSignalSeenZone == candidate.zoneId &&
                                         g_lastSignalSeenBuy == candidate.isBuy);
             bool blocked = sameProcessedSignal || g_lastSignal.active;
             // The detector always exposes candidates; the plan controls publication separately.
             V4Candidate(candidate, blocked ? (sameProcessedSignal ? "DUPLICATE" : "ACTIVE_PLAN") : "PUBLISHED");
             if(blocked) continue;
             if(!V4PersistPublished(candidate)) { g_v4IoFailed = true; return; }
             g_lastSignal = candidate;
             g_lastSignalSeenTime = candidate.time;
             g_lastSignalSeenZone = candidate.zoneId;
             g_lastSignalSeenBuy = candidate.isBuy;
             double arrowAnchor = isBuySignal ? ltfRates[confirmBar].low : ltfRates[confirmBar].high;
             V4DrawSourceZone(candidate);
             DrawSignalArrow(isBuySignal, ltfRates[confirmBar].time, arrowAnchor, ltfAtr);

            // Nếu là khôi phục nến cũ khi reload indicator, kiểm tra xem vị thế đã kết thúc chưa
            if(shouldRestore)
            {
               double pNow = SymbolInfoDouble(_Symbol, SYMBOL_BID);
               bool alreadyClosed = isBuySignal ? (pNow <= sl || pNow >= tp2) : (pNow >= sl || pNow <= tp2);
               if(alreadyClosed)
                  g_lastSignal.active = false;
            }

            if(g_lastSignal.active && ShowTradeLines)
               DrawTradePlanLines(g_lastSignal);

            // Bắn Cảnh Báo (Chỉ bắn 1 lần duy nhất cho mỗi cây nến xác nhận thời gian thực)
            if(isRealtimeBar1 && g_lastAlertBar != ltfRates[1].time)
            {
               g_lastAlertBar = ltfRates[1].time;

               if(AlertConfirm && !isFirstRun)
               {
                  SendSignalAlert(g_lastSignal);
               }

               // Ghi nhật ký sự kiện vào Dashboard
               string sigText = StringFormat("%s CHoCH %s (Cản %s %d) E:%.5f SL:%.5f",
                                             isBuySignal ? "BUY" : "SELL",
                                             EnumToString(ltf),
                                             zTypeStr,
                                             g_zones[z].score,
                                             entry, sl);
               StringReplace(sigText, "PERIOD_", "");

               SEventLog ev;
               ev.text = sigText;
               ev.dotColor = isBuySignal ? C'52,211,153' : C'248,113,113';
               ev.barsAgo = 1;

               ArrayResize(g_events, ArraySize(g_events) + 1);
               for(int k = ArraySize(g_events) - 1; k > 0; k--)
                  g_events[k] = g_events[k - 1];
               g_events[0] = ev;
               if(ArraySize(g_events) > 5) ArrayResize(g_events, 5);
            }
            if(InpCompatV301) break;
         }
         else if(confirmBar <= 10 && g_lastSignal.active)
         {
            // Tín hiệu đã xác nhận cách đây vài nến và vẫn còn hiệu lực
            if((g_lastSignal.isBuy && curPrice > g_lastSignal.sl && curPrice < g_lastSignal.tp2) ||
               (!g_lastSignal.isBuy && curPrice < g_lastSignal.sl && curPrice > g_lastSignal.tp2))
            {
               calculatedState = STATE_CONFIRMED;
            }
         }
      }
   }

   if(guardProbe) return;

   // Xác định trạng thái cuối nếu chưa CHoCH
   if(calculatedState == STATE_IDLE)
   {
      if(sweepFoundGlobal)
         calculatedState = STATE_SWEEP;
      else if(inPoiGlobal)
         calculatedState = STATE_IN_POI;
   }

   if(!InpCompatV301 && !g_lastSignal.isBuy) curPrice=liveTick.ask;

   // Kiểm tra hiệu lực của tín hiệu đang hiển thị trên Dashboard
   if(g_lastSignal.active)
   {
      // Nếu giá đã chạm SL hoặc hoàn thành TP2
      if((g_lastSignal.isBuy && (curPrice <= g_lastSignal.sl || curPrice >= g_lastSignal.tp2)) ||
         (!g_lastSignal.isBuy && (curPrice >= g_lastSignal.sl || curPrice <= g_lastSignal.tp2)))
      {
         g_lastSignal.active = false;
         if(calculatedState == STATE_CONFIRMED)
            calculatedState = STATE_IDLE;
      }
   }

   g_confirmState = calculatedState;
}
#endif
