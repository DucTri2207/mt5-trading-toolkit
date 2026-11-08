//+------------------------------------------------------------------+
//|                                           duc_tri_can_ho_tro.mq5 |
//|                                Copyright 2026, Đức Trí Trading   |
//|                    100% Pure MQL5 - Hoàn toàn KHÔNG dùng DLL     |
//|        Giao diện PRO v4.03 - risk/state corrections                 |
//+------------------------------------------------------------------+
#property copyright   "Đức Trí"
#property link        "https://t.me/botfather6868"
#property version     "4.03"
#property description "Đức Trí Cản Hỗ Trợ v4.03 - closed-bar risk and signal-state fixes (Pure MQL5 - No DLL)"
#property indicator_chart_window
#property indicator_buffers 0
#property indicator_plots   0

#include <Canvas\Canvas.mqh>

//+------------------------------------------------------------------+
//| Enumerations                                                     |
//+------------------------------------------------------------------+
#include <CanHoTroV4/Types.mqh>
#include <CanHoTroV4/Inputs.mqh>

CCanvas              g_canvas;
string               g_cvName       = "DucTri_V4_CV";
string               g_prefix       = "DucTri_V4_";
int                  g_atrHandle    = INVALID_HANDLE;
int                  g_htfAtrHandle = INVALID_HANDLE;
int                  g_ltfAtrHandle = INVALID_HANDLE;
ENUM_LANG            g_lang         = LANG_VI;
bool                 g_isMinimized  = false; // Thu nhỏ panel dashboard

SZone                g_zones[];
SZone                g_htfZones[];
SEventLog            g_events[];

ENUM_CONFIRM_STATE   g_confirmState = STATE_IDLE;
SConfirmSignal       g_lastSignal;
datetime             g_lastAlertBar = 0;
// Identity of the most recent confirmation already processed. This prevents
// the same closed M5 candle from recreating a plan after it was stopped/closed.
datetime             g_lastSignalSeenTime = 0;
long                 g_lastSignalSeenZone = -1;
bool                 g_lastSignalSeenBuy  = false;

int                  g_statCreated  = 0;
int                  g_statDemand   = 0;
int                  g_statSupply   = 0;
int                  g_statBroken   = 0;
int                  g_statFlipped  = 0;

// Bộ nhớ đệm màu cũ của chart
long                 g_oldBgClr, g_oldFgClr, g_oldGridClr, g_oldBarUpClr, g_oldBarDnClr, g_oldBullClr, g_oldBearClr, g_oldLineClr;

// Tọa độ click nút trên canvas
int                  g_btnMinX1, g_btnMinY1, g_btnMinX2, g_btnMinY2;
int                  g_btnTgX1, g_btnTgY1, g_btnTgX2, g_btnTgY2;
int                  g_btnWebX1, g_btnWebY1, g_btnWebX2, g_btnWebY2;
int                  g_btnLangX1, g_btnLangY1, g_btnLangX2, g_btnLangY2;

string               g_tgToken      = "";
string               g_tgChatID     = "";

//+------------------------------------------------------------------+
//| Đồng bộ Cấu hình Telegram dùng chung (FILE_COMMON UTF-8)         |
//+------------------------------------------------------------------+
void SaveTelegramConfig(string token, string chatId)
{
   if(token == "" && chatId == "") return;
   int handle = FileOpen("duc_tri_tg_config.txt", FILE_WRITE|FILE_TXT|FILE_COMMON|FILE_SHARE_READ|FILE_SHARE_WRITE, 0, CP_UTF8);
   if(handle != INVALID_HANDLE)
   {
      FileWriteString(handle, token + "\r\n" + chatId + "\r\n");
      FileClose(handle);
   }
}

void LoadTelegramConfig(string &token, string &chatId)
{
   if(token != "" && chatId != "") return;
   if(!FileIsExist("duc_tri_tg_config.txt", FILE_COMMON)) return;
   int handle = FileOpen("duc_tri_tg_config.txt", FILE_READ|FILE_TXT|FILE_COMMON|FILE_SHARE_READ|FILE_SHARE_WRITE, 0, CP_UTF8);
   if(handle != INVALID_HANDLE)
   {
      string t = FileReadString(handle);
      string c = FileReadString(handle);
      StringTrimRight(t); StringTrimLeft(t);
      StringTrimRight(c); StringTrimLeft(c);
      if(token == "" && t != "") token = t;
      if(chatId == "" && c != "") chatId = c;
      FileClose(handle);
   }
}

// Helper Utilities




double GetZoneDistance(const SZone &z, double price)
{
   double zMin = MathMin(z.distal, z.proximal);
   double zMax = MathMax(z.distal, z.proximal);
   if(price > zMax) return price - zMax;
   if(price < zMin) return zMin - price;
   return 0.0;
}

// Forward Declarations
void                 ScanHtfMacroZones();
void                 DrawChartZones();
void                 DetectLtfConfirmation(bool isFirstRun = false);
void                 ManageActiveSignal(double curPrice);
void                 DrawTradePlanLines(const SConfirmSignal &sig);
void                 RemoveTradePlanLines();
void                 CheckPriceZoneInteraction(double curPrice);
void                 DrawSignalArrow(bool isBuy, datetime t, double p, double atr);
void                 SendSignalAlert(const SConfirmSignal &sig);
bool                 DispatchTelegram(string message, string token = "", string chatId = "");
bool                 SendTelegram(string message);
void                 SendSignalTelegram(const SConfirmSignal &sig);
void                 SendBeTelegram(const SConfirmSignal &sig, double favorablePips, double favorablePts);
void                 RenderDashboard(double curPrice);
void                 ApplyChartTheme(ENUM_THEME th);
bool                 IsInKillzone(datetime barTime);
void                 RefreshReferenceLevels();
void                 DrawReferenceLevels();

double               g_previousDayHigh = 0.0;
double               g_previousDayLow  = 0.0;
datetime             g_previousDayTime = 0;

//+------------------------------------------------------------------+
//| Khởi tạo chỉ báo                                                 |
//+------------------------------------------------------------------+
#include <CanHoTroV4/Identity.mqh>
#include <CanHoTroV4/Time.mqh>
#define CHT_V4_CHART_DISPLAY
SZone g_v4ZoneHistory[];
#include <CanHoTroV4/SourceZone.mqh>
#include <CanHoTroV4/Logger.mqh>
#include <CanHoTroV4/M2Panel.mqh>
#include <CanHoTroV4/LogicHelpers.mqh>
#include <CanHoTroV4/Observation.mqh>

#include <CanHoTroV4/ChartHistory.mqh>
bool g_v4LedgerReady=false;
int g_v4LedgerRetries=0;

int OnInit()
{
   if(InpPriceScaleMode<0 || InpPriceScaleMode>1 || MaxSpreadPrice <= 0.0)
      return INIT_PARAMETERS_INCORRECT;
   if(InpHistSpreadPrice<0 || InpCommissionPerLot<0 || InpSlippagePoints<0 || InpRiskPercent<=0 ||
      InpCostWarningPercent<0 || InpInitialCapital<0 || InpDailyLossPercent<=0 || InpTotalLossPercent<=0 ||
      InpResetMinuteServer<0 || InpResetMinuteServer>=1440 || InpJournalMatchMinutes<0)
      return INIT_PARAMETERS_INCORRECT;
   g_previousDayHigh=0.0;
   g_previousDayLow=0.0;
   g_previousDayTime=0;
   g_lang = DefaultLang;

   if(Theme != THEME_NONE)
   {
      ChartGetInteger(0, CHART_COLOR_BACKGROUND, 0, g_oldBgClr);
      ChartGetInteger(0, CHART_COLOR_FOREGROUND, 0, g_oldFgClr);
      ChartGetInteger(0, CHART_COLOR_GRID, 0, g_oldGridClr);
      ChartGetInteger(0, CHART_COLOR_CHART_UP, 0, g_oldBarUpClr);
      ChartGetInteger(0, CHART_COLOR_CHART_DOWN, 0, g_oldBarDnClr);
      ChartGetInteger(0, CHART_COLOR_CANDLE_BULL, 0, g_oldBullClr);
      ChartGetInteger(0, CHART_COLOR_CANDLE_BEAR, 0, g_oldBearClr);
      ChartGetInteger(0, CHART_COLOR_CHART_LINE, 0, g_oldLineClr);
      ApplyChartTheme(Theme);
   }

   g_atrHandle = iATR(_Symbol, PERIOD_CURRENT, AtrLen);
   if(g_atrHandle == INVALID_HANDLE)
   {
      Print("Đức Trí Cản Hỗ Trợ: Lỗi tạo handle iATR khung hiện tại!");
      return INIT_FAILED;
   }

   ENUM_TIMEFRAMES htf = (HtfPeriod == PERIOD_CURRENT) ? PERIOD_H1 : HtfPeriod;
   g_htfAtrHandle = iATR(_Symbol, htf, AtrLen);
   if(g_htfAtrHandle == INVALID_HANDLE)
   {
      Print("Đức Trí Cản Hỗ Trợ: Lỗi tạo handle iATR khung lớn HTF!");
   }

   ENUM_TIMEFRAMES ltf = (LtfPeriod == PERIOD_CURRENT) ? PERIOD_M5 : LtfPeriod;
   g_ltfAtrHandle = iATR(_Symbol, ltf, AtrLen);
   if(g_ltfAtrHandle == INVALID_HANDLE)
   {
      Print("Đức Trí Cản Hỗ Trợ: Lỗi tạo handle iATR khung nhỏ LTF!");
   }

   ArrayResize(g_events, 0);
   ArrayResize(g_v4History,0); g_v4LastEvaluated=0; g_v4IoFailed=false;
   ZeroMemory(g_lastSignal);
   g_lastSignalSeenTime = 0;
   g_lastSignalSeenZone = -1;
   g_lastSignalSeenBuy  = false;
   g_confirmState = STATE_IDLE;

   if(InpHistoryDays<1 || InpHistoryDays>3650 || InpCompatV301 || !UseLtfConfirm || htf!=PERIOD_H1 || ltf!=PERIOD_M5)
      return INIT_PARAMETERS_INCORRECT;
   g_isMinimized=InpDashCollapsed;
   V4ChartStart();
   g_v4LedgerReady=true;
   EventSetMillisecondTimer(100);
   // Nạp hoặc lưu cấu hình Telegram Bot
   if(TgToken != "" && TgChatID != "")
      SaveTelegramConfig(TgToken, TgChatID);
   else
      LoadTelegramConfig(g_tgToken, g_tgChatID);

   PrintFormat("Đức Trí Cản Hỗ Trợ (%s,%s) v4.03 [resolved state; indicator contract risk] khởi tạo thành công [100%% Pure MQL5 - NO DLL]!", _Symbol, EnumToString(Period()));
   return INIT_SUCCEEDED;
}

//+------------------------------------------------------------------+
//| Hủy chỉ báo & Thu dọn đồ họa                                     |
//+------------------------------------------------------------------+
void OnTimer()
{
   V4ChartStep();
}

void OnDeinit(const int reason)
{
   EventKillTimer();
   if(!g_v4ReadOnly && g_v4M2Started && g_v4ScoreError=="") V4ScoreSave();
   if(!g_v4ReadOnly) V4ZoneSnapshot(true);
   V4CloseLedger();
   if(g_v4ChartLock!=INVALID_HANDLE) FileClose(g_v4ChartLock);
   if(g_atrHandle != INVALID_HANDLE)
      IndicatorRelease(g_atrHandle);
   if(g_htfAtrHandle != INVALID_HANDLE)
      IndicatorRelease(g_htfAtrHandle);
   if(g_ltfAtrHandle != INVALID_HANDLE)
      IndicatorRelease(g_ltfAtrHandle);

   RemoveTradePlanLines();
   g_canvas.Destroy();
   ObjectsDeleteAll(0, g_prefix);

   if(RestoreTheme && Theme != THEME_NONE)
   {
      ChartSetInteger(0, CHART_COLOR_BACKGROUND, g_oldBgClr);
      ChartSetInteger(0, CHART_COLOR_FOREGROUND, g_oldFgClr);
      ChartSetInteger(0, CHART_COLOR_GRID, g_oldGridClr);
      ChartSetInteger(0, CHART_COLOR_CHART_UP, g_oldBarUpClr);
      ChartSetInteger(0, CHART_COLOR_CHART_DOWN, g_oldBarDnClr);
      ChartSetInteger(0, CHART_COLOR_CANDLE_BULL, g_oldBullClr);
      ChartSetInteger(0, CHART_COLOR_CANDLE_BEAR, g_oldBearClr);
      ChartSetInteger(0, CHART_COLOR_CHART_LINE, g_oldLineClr);
   }

   ChartRedraw(0);
}

//+------------------------------------------------------------------+
//| Vòng lặp tính toán nến                                           |
//+------------------------------------------------------------------+
int OnCalculate(const int rates_total,
                const int prev_calculated,
                const datetime &time[],
                const double &open[],
                const double &high[],
                const double &low[],
                const double &close[],
                const long &tick_volume[],
                const long &volume[],
                const int &spread[])
{
   MqlTick v4Tick;
   if(!SymbolInfoTick(_Symbol,v4Tick) || v4Tick.time<=0) return prev_calculated;
   g_v4Now=v4Tick.time;
   if(g_v4IoFailed || !g_v4LedgerReady) return prev_calculated;
   // All history and catch-up work is budgeted by OnTimer, independent of chart ticks/period.
   return rates_total;

}

//+------------------------------------------------------------------+
//| Quét vùng cản vĩ mô Khung Lớn HTF (Mặc định H1)                  |
//+------------------------------------------------------------------+


void DrawReferenceLevels()
{
   string highName=g_prefix+"REF_PDH";
   string lowName =g_prefix+"REF_PDL";
   if(!ShowReferenceLevels || g_previousDayHigh<=0.0 || g_previousDayLow<=0.0)
   {
      ObjectDelete(0,highName);
      ObjectDelete(0,lowName);
      return;
   }
   if(ObjectFind(0,highName)<0) ObjectCreate(0,highName,OBJ_HLINE,0,0,g_previousDayHigh);
   if(ObjectFind(0,lowName)<0) ObjectCreate(0,lowName,OBJ_HLINE,0,0,g_previousDayLow);
   ObjectSetDouble(0,highName,OBJPROP_PRICE,g_previousDayHigh);
   ObjectSetDouble(0,lowName,OBJPROP_PRICE,g_previousDayLow);
   ObjectSetInteger(0,highName,OBJPROP_COLOR,C'192,132,252');
   ObjectSetInteger(0,lowName,OBJPROP_COLOR,C'192,132,252');
   ObjectSetInteger(0,highName,OBJPROP_STYLE,STYLE_DOT);
   ObjectSetInteger(0,lowName,OBJPROP_STYLE,STYLE_DOT);
   ObjectSetString(0,highName,OBJPROP_TOOLTIP,"PDH - Previous completed broker D1 high");
   ObjectSetString(0,lowName,OBJPROP_TOOLTIP,"PDL - Previous completed broker D1 low");
}

#include <CanHoTroV4/Zones.mqh>
datetime g_v4ZoneScanBar=0;
void ScanHtfMacroZones()
{
   int shift=g_v4ReplayTime>0?iBarShift(_Symbol,PERIOD_H1,g_v4ReplayTime,false):0;
   datetime closed=iTime(_Symbol,PERIOD_H1,shift+1);
   if(closed>0 && closed==g_v4ZoneScanBar && g_v4ZonesReady) return;
   CZoneEngine::Scan();
   if(g_v4ZonesReady) { g_v4ZoneScanBar=closed; V4RememberZones(); }
}

//+------------------------------------------------------------------+
//| Vẽ cản lên đồ thị - Màu Pastel Dịu Mắt, Nhãn Tinh Tế             |
//+------------------------------------------------------------------+
void DrawChartZones()
{
   V4RenderZones();
}

//+------------------------------------------------------------------+
//| Kiểm tra khung giờ Killzones (London & New York)                 |
//+------------------------------------------------------------------+


//+------------------------------------------------------------------+
//| Quét cấu trúc vi mô LTF (M5) & Xác nhận Điểm Vào Lệnh (CHoCH)     |
//| 100% NON-REPAINTING: Chỉ chốt tín hiệu trên nến đã ĐÓNG CỬA [1]  |
//+------------------------------------------------------------------+
#include <CanHoTroV4/Signals.mqh>
void DetectLtfConfirmation(bool isFirstRun){ CSignalEngine::Detect(isFirstRun); }

//+------------------------------------------------------------------+
//| Quản lý vị thế lệnh đang mở và tự động dời Auto Break-Even (BE)  |
//+------------------------------------------------------------------+


//+------------------------------------------------------------------+
//| Vẽ các đường Entry, Limit, SL, BE, TP1, TP2 trên biểu đồ        |
//+------------------------------------------------------------------+
void DrawTradePlanLines(const SConfirmSignal &sig)
{
   if(!ShowTradeLines || !sig.active) return;

   datetime t1 = sig.time;
   datetime t2 = iTime(_Symbol, PERIOD_CURRENT, 0) + (PeriodSeconds() * ExtendBars);

   // 1. Entry Line (Trắng pastel)
   string objEntry = g_prefix + "PLAN_ENTRY";
   double drawEntry = sig.entry;
   if(ObjectFind(0, objEntry) < 0) ObjectCreate(0, objEntry, OBJ_TREND, 0, t1, drawEntry, t2, drawEntry);
   else { ObjectSetInteger(0, objEntry, OBJPROP_TIME, 0, t1); ObjectSetDouble(0, objEntry, OBJPROP_PRICE, 0, drawEntry);
          ObjectSetInteger(0, objEntry, OBJPROP_TIME, 1, t2); ObjectSetDouble(0, objEntry, OBJPROP_PRICE, 1, drawEntry); }
   ObjectSetInteger(0, objEntry, OBJPROP_COLOR, C'241,245,249');
   ObjectSetInteger(0, objEntry, OBJPROP_STYLE, STYLE_DASH);
   ObjectSetInteger(0, objEntry, OBJPROP_WIDTH, 1);
   ObjectSetInteger(0, objEntry, OBJPROP_RAY_RIGHT, false);
   ObjectSetString(0, objEntry, OBJPROP_TOOLTIP, StringFormat("Entry (%s): %.*f", (InpEntryMode == ENTRY_MARKET_CONFIRM ? "Market" : "Plan"), _Digits, drawEntry));

   // 2. Limit Retrace Line (Tím pastel - Nếu dùng chế độ Dual hoặc có Limit)
   string objLimit = g_prefix + "PLAN_LIMIT";
   if(InpEntryMode == ENTRY_DUAL_RECOMMEND && sig.entryLimit > 0 && MathAbs(sig.entryLimit - sig.entryMarket) > 5 * _Point)
   {
      if(ObjectFind(0, objLimit) < 0) ObjectCreate(0, objLimit, OBJ_TREND, 0, t1, sig.entryLimit, t2, sig.entryLimit);
      else { ObjectSetInteger(0, objLimit, OBJPROP_TIME, 0, t1); ObjectSetDouble(0, objLimit, OBJPROP_PRICE, 0, sig.entryLimit);
             ObjectSetInteger(0, objLimit, OBJPROP_TIME, 1, t2); ObjectSetDouble(0, objLimit, OBJPROP_PRICE, 1, sig.entryLimit); }
      ObjectSetInteger(0, objLimit, OBJPROP_COLOR, C'168,85,247');
      ObjectSetInteger(0, objLimit, OBJPROP_STYLE, STYLE_DOT);
      ObjectSetInteger(0, objLimit, OBJPROP_WIDTH, 1);
      ObjectSetInteger(0, objLimit, OBJPROP_RAY_RIGHT, false);
      ObjectSetString(0, objLimit, OBJPROP_TOOLTIP, StringFormat("Limit Retrace 50%%: %.*f", _Digits, sig.entryLimit));
   }
   else
   {
      ObjectDelete(0, objLimit);
   }

   // 3. Stop Loss / Break-Even Line
   string objSl = g_prefix + "PLAN_SL";
   if(ObjectFind(0, objSl) < 0) ObjectCreate(0, objSl, OBJ_TREND, 0, t1, sig.sl, t2, sig.sl);
   else { ObjectSetInteger(0, objSl, OBJPROP_TIME, 0, t1); ObjectSetDouble(0, objSl, OBJPROP_PRICE, 0, sig.sl);
          ObjectSetInteger(0, objSl, OBJPROP_TIME, 1, t2); ObjectSetDouble(0, objSl, OBJPROP_PRICE, 1, sig.sl); }
   ObjectSetInteger(0, objSl, OBJPROP_COLOR, sig.isBeActive ? C'56,189,248' : C'248,113,113');
   ObjectSetInteger(0, objSl, OBJPROP_STYLE, sig.isBeActive ? STYLE_SOLID : STYLE_DASH);
   ObjectSetInteger(0, objSl, OBJPROP_WIDTH, sig.isBeActive ? 2 : 1);
   ObjectSetInteger(0, objSl, OBJPROP_RAY_RIGHT, false);
   ObjectSetString(0, objSl, OBJPROP_TOOLTIP, sig.isBeActive ? StringFormat("BE suggestion (indicator simulation): %.*f", _Digits, sig.sl) : StringFormat("Stop Loss: %.*f", _Digits, sig.sl));

   // 4. Take Profit 1 Line (Xanh Mint)
   string objTp1 = g_prefix + "PLAN_TP1";
   if(ObjectFind(0, objTp1) < 0) ObjectCreate(0, objTp1, OBJ_TREND, 0, t1, sig.tp1, t2, sig.tp1);
   else { ObjectSetInteger(0, objTp1, OBJPROP_TIME, 0, t1); ObjectSetDouble(0, objTp1, OBJPROP_PRICE, 0, sig.tp1);
          ObjectSetInteger(0, objTp1, OBJPROP_TIME, 1, t2); ObjectSetDouble(0, objTp1, OBJPROP_PRICE, 1, sig.tp1); }
   ObjectSetInteger(0, objTp1, OBJPROP_COLOR, C'52,211,153');
   ObjectSetInteger(0, objTp1, OBJPROP_STYLE, STYLE_DASH);
   ObjectSetInteger(0, objTp1, OBJPROP_WIDTH, 1);
   ObjectSetInteger(0, objTp1, OBJPROP_RAY_RIGHT, false);
   ObjectSetString(0, objTp1, OBJPROP_TOOLTIP, StringFormat("Take Profit 1: %.*f", _Digits, sig.tp1));

   // 5. Take Profit 2 Line (Vàng Kim)
   string objTp2 = g_prefix + "PLAN_TP2";
   if(ObjectFind(0, objTp2) < 0) ObjectCreate(0, objTp2, OBJ_TREND, 0, t1, sig.tp2, t2, sig.tp2);
   else { ObjectSetInteger(0, objTp2, OBJPROP_TIME, 0, t1); ObjectSetDouble(0, objTp2, OBJPROP_PRICE, 0, sig.tp2);
          ObjectSetInteger(0, objTp2, OBJPROP_TIME, 1, t2); ObjectSetDouble(0, objTp2, OBJPROP_PRICE, 1, sig.tp2); }
   ObjectSetInteger(0, objTp2, OBJPROP_COLOR, C'250,204,21');
   ObjectSetInteger(0, objTp2, OBJPROP_STYLE, STYLE_DASH);
   ObjectSetInteger(0, objTp2, OBJPROP_WIDTH, 1);
   ObjectSetInteger(0, objTp2, OBJPROP_RAY_RIGHT, false);
   ObjectSetString(0, objTp2, OBJPROP_TOOLTIP, StringFormat("Take Profit 2: %.*f", _Digits, sig.tp2));

   ChartRedraw(0);
}

//+------------------------------------------------------------------+
//| Xóa các đường kế hoạch trên biểu đồ                             |
//+------------------------------------------------------------------+
void RemoveTradePlanLines()
{
   ObjectsDeleteAll(0, g_prefix + "PLAN_");
   ChartRedraw(0);
}

//+------------------------------------------------------------------+
//| Báo động & Ghi nhật ký sự kiện tương tác giá cản cơ bản         |
//+------------------------------------------------------------------+
void CheckPriceZoneInteraction(double curPrice)
{
   for(int i = ArraySize(g_zones) - 1; i >= 0; i--)
   {
      if(g_zones[i].isBroken || g_zones[i].ageBars > 100) continue;

      double zMin = MathMin(g_zones[i].distal, g_zones[i].proximal);
      double zMax = MathMax(g_zones[i].distal, g_zones[i].proximal);

      if(curPrice >= zMin && curPrice <= zMax)
      {
         string evText = "";
         string tStr = EnumToString(g_zones[i].type);
         StringReplace(tStr, "ZONE_", "");

         if(g_lang == LANG_EN)
            evText = StringFormat("Price entered %s %s %d (%s) %.2f",
                                  g_zones[i].isSupply ? "SUPPLY" : "DEMAND",
                                  tStr,
                                  g_zones[i].score,
                                  g_zones[i].testCount <= 1 ? "first test" : StringFormat("T%d", g_zones[i].testCount),
                                  curPrice);
         else
            evText = StringFormat("Giá chạm %s %s %d (%s) %.2f",
                                  g_zones[i].isSupply ? "CUNG" : "CẦU",
                                  tStr,
                                  g_zones[i].score,
                                  g_zones[i].testCount <= 1 ? "test đầu" : StringFormat("T%d", g_zones[i].testCount),
                                  curPrice);

         bool exists = false;
         for(int e = 0; e < ArraySize(g_events); e++)
         {
            if(g_events[e].text == evText) { exists = true; break; }
         }
         if(!exists)
         {
            SEventLog ev;
            ev.text = evText;
            ev.dotColor = g_zones[i].isSupply ? C'248,113,113' : C'52,211,153';
            ev.barsAgo = 0;

            ArrayResize(g_events, ArraySize(g_events) + 1);
            for(int k = ArraySize(g_events) - 1; k > 0; k--)
               g_events[k] = g_events[k - 1];
            g_events[0] = ev;
            if(ArraySize(g_events) > 5) ArrayResize(g_events, 5);

            if(AlertEnter && g_zones[i].score >= AlertMinScore)
            {
               if(AlertPopup) Alert(evText);
               if(AlertSoundOn) PlaySound(AlertSoundFile);
               if(AlertPush) SendNotification(evText);
               if(TgEnable && !TgAlertSignalsOnly) SendTelegram(evText);
            }
         }
      }
   }
}

//+------------------------------------------------------------------+
//| Vẽ Mũi Tên và Nhãn Tín Hiệu Xác Nhận - Siêu Nét, Giữ Chart Sạch |
//+------------------------------------------------------------------+
#include <CanHoTroV4/Arrow.mqh>

//+------------------------------------------------------------------+
//| Gửi Cảnh Báo Popup, Âm Thanh, Push Notification & Telegram       |
//+------------------------------------------------------------------+
void SendSignalAlert(const SConfirmSignal &sig)
{
   if(!V4RiskAlertsAllowed()) return;
   string tfLtf = EnumToString(LtfPeriod);
   StringReplace(tfLtf, "PERIOD_", "");
   string tfHtf = EnumToString(HtfPeriod);
   StringReplace(tfHtf, "PERIOD_", "");

   // 1. Popup Alert & Push Notification thoại
   string alertMsg = StringFormat(
      "⚡ [%s %s] %s CHoCH Trigger!\nEntry: %.*f | SL: %.*f\nTP1 (1:1.5): %.*f | TP2 (1:2.0): %.*f\nCản %s: %s (%d pts)",
      _Symbol, tfLtf,
      sig.isBuy ? "BUY" : "SELL",
      _Digits, sig.entry,
      _Digits, sig.sl,
      _Digits, sig.tp1,
      _Digits, sig.tp2,
      tfHtf, sig.zoneType, sig.zoneScore
   );

   if(AlertPopup) Alert(alertMsg);
   if(AlertSoundOn) PlaySound(AlertSoundFile);
   if(AlertPush) SendNotification(alertMsg);

   // 2. Chuyển tiếp tín hiệu sang Telegram Bot
   if(TgEnable) SendSignalTelegram(sig);
}

//+------------------------------------------------------------------+
//| Chuyển tiếp tin nhắn Telegram tới companion Bridge EA            |
//| (Hỗ trợ 0ms OnChartEvent + Shared Queue FILE_COMMON)             |
//+------------------------------------------------------------------+
bool DispatchTelegram(string message, string token = "", string chatId = "")
{
   if(g_tgToken == "" || g_tgChatID == "")
      LoadTelegramConfig(g_tgToken, g_tgChatID);

   string tok = (token != "")  ? token  : (TgToken != "" ? TgToken : g_tgToken);
   string cid = (chatId != "") ? chatId : (TgChatID != "" ? TgChatID : g_tgChatID);

   string msgId = StringFormat("%s_%d_%d", _Symbol, (long)TimeLocal(), MathRand());
   string payload = StringFormat("ID=%s\nTOKEN=%s\nCHATID=%s\nTEXT=%s", msgId, tok, cid, message);

   // Kênh 1: Bắn Custom Event tới EA trên cùng Chart (0ms Latency)
   EventChartCustom(0, 7777, 0, 0.0, payload);

   // Kênh 2: Ghi vào hàng đợi dùng chung FILE_COMMON cho EA ở chart khác (UTF-8 Emoji & Tiếng Việt)
   int handle = FileOpen("duc_tri_tg_queue.txt", FILE_READ|FILE_WRITE|FILE_TXT|FILE_COMMON|FILE_SHARE_READ|FILE_SHARE_WRITE, 0, CP_UTF8);
   if(handle == INVALID_HANDLE)
   {
      Sleep(20);
      handle = FileOpen("duc_tri_tg_queue.txt", FILE_READ|FILE_WRITE|FILE_TXT|FILE_COMMON|FILE_SHARE_READ|FILE_SHARE_WRITE, 0, CP_UTF8);
   }
   if(handle != INVALID_HANDLE)
   {
      FileSeek(handle, 0, SEEK_END);
      FileWriteString(handle, "===MSG_START===\r\n");
      FileWriteString(handle, payload + "\r\n");
      FileWriteString(handle, "===MSG_END===\r\n");
      FileClose(handle);
   }

   bool isBridgeOnline = false;
   if(GlobalVariableCheck("DucTri_TgBridge_Heartbeat"))
   {
      datetime hb = (datetime)GlobalVariableGet("DucTri_TgBridge_Heartbeat");
      if(TimeLocal() - hb <= 5) isBridgeOnline = true;
   }

   if(isBridgeOnline)
   {
      PrintFormat("⚡ [Đức Trí SMC] Đã chuyển tiếp tin Telegram sang Bridge EA (Trạng thái: ONLINE 🟢). MsgID: %s", msgId);
   }
   else
   {
      PrintFormat("ℹ️ [Đức Trí SMC] Tin Telegram đã đưa vào hàng đợi. Vui lòng gắn EA 'duc_tri_telegram_bridge' vào chart để gửi đi! MsgID: %s", msgId);
   }

   return true;
}

//+------------------------------------------------------------------+
//| Gửi Telegram dạng Text đơn giản                                  |
//+------------------------------------------------------------------+
bool SendTelegram(string message)
{
   return DispatchTelegram(message);
}

//+------------------------------------------------------------------+
//| Bắn Tín Hiệu Telegram Kèo M5 CHoCH Chuẩn HTML Chuyên Nghiệp      |
//+------------------------------------------------------------------+
void SendSignalTelegram(const SConfirmSignal &sig)
{
   if(!TgEnable) return;

   string dirEmoji = sig.isBuy ? "🟢" : "🔴";
   string dirText  = sig.isBuy ? "BUY CHoCH" : "SELL CHoCH";

   string tfHtf = EnumToString(HtfPeriod);
   StringReplace(tfHtf, "PERIOD_", "");
   string tfLtf = EnumToString(LtfPeriod);
   StringReplace(tfLtf, "PERIOD_", "");

   double slPips  = PriceToPips(sig.entry - sig.sl);
   double tp1Pips = PriceToPips(sig.tp1 - sig.entry);
   double tp2Pips = PriceToPips(sig.tp2 - sig.entry);

   string msg = StringFormat(
      "⚡ <b>SMT / SMC M5 CHoCH TRIGGER</b> ⚡\n" +
      "━━━━━━━━━━━━━━━━━━━\n" +
      "💎 <b>Cặp tiền / Tài sản:</b> <code>%s</code> (%s)\n" +
      "🧭 <b>Hướng:</b> %s <b>%s</b>\n" +
      "🏛 <b>Cản %s kích hoạt:</b> <code>%s</code> (Điểm: %d/100)\n" +
      "━━━━━━━━━━━━━━━━━━━\n" +
      "📍 <b>Giá Entry Market:</b> <code>%.*f</code>\n",
      _Symbol, tfLtf,
      dirEmoji, dirText,
      tfHtf, sig.zoneType, sig.zoneScore,
      _Digits, sig.entryMarket
   );

   if(sig.entryLimit > 0 && MathAbs(sig.entryLimit - sig.entryMarket) > 5 * _Point)
   {
      double limitPips = PriceToPips(sig.entryMarket - sig.entryLimit);
      msg += StringFormat("🎯 <b>Limit đón hồi (50%% FVG/Nến):</b> <code>%.*f</code> (Tối ưu thêm +%.1f pips)\n",
                          _Digits, sig.entryLimit, limitPips);
   }

   msg += StringFormat(
      "🛡 <b>Stop Loss chuẩn SMC:</b> <code>%.*f</code> (%.1f pips)\n" +
      "🎁 <b>Take Profit 1:</b> <code>%.*f</code> (+%.1f pips | R:R 1:%.1f)\n" +
      "🚀 <b>Take Profit 2:</b> <code>%.*f</code> (+%.1f pips | R:R 1:%.1f)\n",
      _Digits, sig.sl, slPips,
      _Digits, sig.tp1, tp1Pips, sig.rr1,
      _Digits, sig.tp2, tp2Pips, sig.rr2
   );

   if(sig.tpMacro > 0 && sig.rrMacro > 2.0)
   {
      double macroPips = PriceToPips(sig.tpMacro - sig.entry);
      msg += StringFormat("🎯 <b>Target Cản %s đối diện:</b> <code>%.*f</code> (+%.1f pips | R:R 1:%.1f)\n",
                          tfHtf, _Digits, sig.tpMacro, macroPips, sig.rrMacro);
   }

   string beInfo = "";
   if(InpUseAutoBE)
   {
      if(InpBeTriggerATR > 0 && InpBeTriggerPips > 0)
         beInfo = StringFormat("🛡 <b>Cơ chế Auto Break-Even:</b> Dời SL về BE khi xanh >= +%.0f pips (+%.1f$) hoặc >= %.1f ATR\n",
                               V4Distance(InpBeTriggerPips), V4Distance(InpBeTriggerPips) * GetPipSize(), InpBeTriggerATR);
      else if(InpBeTriggerATR > 0)
         beInfo = StringFormat("🛡 <b>Cơ chế Auto Break-Even:</b> Dời SL về BE khi xanh >= %.1f ATR\n", InpBeTriggerATR);
      else
         beInfo = StringFormat("🛡 <b>Cơ chế Auto Break-Even:</b> Dời SL về BE khi xanh >= +%.0f pips (+%.1f$)\n",
                               V4Distance(InpBeTriggerPips), V4Distance(InpBeTriggerPips) * GetPipSize());
   }

   msg += StringFormat(
      "━━━━━━━━━━━━━━━━━━━\n" +
      "%s" +
      "⏰ <b>Khung giờ:</b> <code>%s</code>\n" +
      "💡 <i>Gợi ý: Đón hồi tại Limit hoặc vào Market, chốt 50%% tại TP1, dời BE runner đến TP2!</i>",
      beInfo,
      TimeToString(sig.time, TIME_DATE|TIME_MINUTES)
   );

   DispatchTelegram(msg);
}

//+------------------------------------------------------------------+
//| Gửi Thông Báo Auto Break-Even (BE) qua Telegram                  |
//+------------------------------------------------------------------+
void SendBeTelegram(const SConfirmSignal &sig, double favorablePips, double favorablePts)
{
   if(!TgEnable) return;

   string tfLtf = EnumToString(LtfPeriod);
   StringReplace(tfLtf, "PERIOD_", "");

   string msg = StringFormat(
      "🛡️ <b>[AUTO BREAK-EVEN KÍCH HOẠT]</b> 🛡️\n" +
      "━━━━━━━━━━━━━━━━━━━\n" +
      "💎 <b>Tài sản:</b> <code>%s</code> (%s)\n" +
      "🧭 <b>Lệnh:</b> %s <b>%s</b>\n" +
      "🚀 <b>Lợi nhuận đã chạy:</b> <code>+%.1f pips</code> (+%.2f $)\n" +
       "🛡️ <b>Đề xuất BE (mô phỏng):</b> <code>%.*f</code> (+%.1f pips đệm phí)\n" +
      "🎁 <b>Mục tiêu TP1:</b> <code>%.*f</code>\n" +
      "🚀 <b>Mục tiêu TP2:</b> <code>%.*f</code>\n" +
      "━━━━━━━━━━━━━━━━━━━\n" +
       "<i>Mức BE chỉ là gợi ý trên indicator; broker SL không được tự sửa và vẫn có thể lỗ do phí/trượt giá.</i>",
      _Symbol, tfLtf,
      sig.isBuy ? "🟢" : "🔴",
      sig.isBuy ? "BUY CHoCH" : "SELL CHoCH",
      favorablePips, favorablePts,
      _Digits, sig.bePrice, InpBeOffsetPips,
      _Digits, sig.tp1,
      _Digits, sig.tp2
   );

   DispatchTelegram(msg);
}

//+------------------------------------------------------------------+
//| Vẽ bảng điều khiển Dashboard 3.0 (Canvas DucTri_CV)              |
//| Thiết kế Hiện Đại, 100% Opaque (Không Đè Nến), Khối State Engine |
//+------------------------------------------------------------------+
void RenderDashboard(double curPrice)
{
   int width  = (int)(460 * DashScale);
   int height = g_isMinimized ? (int)(44 * DashScale) : (int)(725 * DashScale);

   double s = DashScale / 1.2;
   if(s < 0.75) s = 0.75;
   if(s > 2.0)  s = 2.0;

   int posX = DashX;
   int posY = InpDashBottom?MathMax(0,(int)ChartGetInteger(0,CHART_HEIGHT_IN_PIXELS)-(g_isMinimized?(int)(44*DashScale):(int)(725*DashScale))-DashY-30):DashY;
   if(DashRight)
      posX = (int)ChartGetInteger(0, CHART_WIDTH_IN_PIXELS) - width - DashX;

   if(ObjectFind(0, g_cvName) < 0)
   {
      if(!g_canvas.CreateBitmapLabel(0, 0, g_cvName, posX, posY, width, height, COLOR_FORMAT_ARGB_NORMALIZE))
         return;
   }
   else
   {
      if(g_canvas.Height() != height || g_canvas.Width() != width)
      {
         g_canvas.Destroy();
         if(!g_canvas.CreateBitmapLabel(0, 0, g_cvName, posX, posY, width, height, COLOR_FORMAT_ARGB_NORMALIZE))
            return;
      }
   }

   // 1. Phân loại và lọc danh sách cản Demand / Supply
   int dIndices[];
   ArrayResize(dIndices, 0);
   int sIndices[];
   ArrayResize(sIndices, 0);
   int freshDemandCount = 0, freshSupplyCount = 0;

   for(int i = 0; i < ArraySize(g_zones); i++)
   {
      if(g_zones[i].isBroken) continue;

      if(g_zones[i].isSupply)
      {
         if(g_zones[i].isFresh) freshSupplyCount++;
         if(g_zones[i].distal >= curPrice - 20 * _Point)
         {
            int sz = ArraySize(sIndices);
            ArrayResize(sIndices, sz + 1);
            sIndices[sz] = i;
         }
      }
      else
      {
         if(g_zones[i].isFresh) freshDemandCount++;
         if(g_zones[i].distal <= curPrice + 20 * _Point)
         {
            int sz = ArraySize(dIndices);
            ArrayResize(dIndices, sz + 1);
            dIndices[sz] = i;
         }
      }
   }

   // Sắp xếp Demand theo khoảng cách tới giá
   for(int i = 0; i < ArraySize(dIndices) - 1; i++)
   {
      for(int j = i + 1; j < ArraySize(dIndices); j++)
      {
         double dist1 = GetZoneDistance(g_zones[dIndices[i]], curPrice);
         double dist2 = GetZoneDistance(g_zones[dIndices[j]], curPrice);
         if(dist2 < dist1)
         {
            int tmp = dIndices[i];
            dIndices[i] = dIndices[j];
            dIndices[j] = tmp;
         }
      }
   }

   // Sắp xếp Supply theo khoảng cách tới giá
   for(int i = 0; i < ArraySize(sIndices) - 1; i++)
   {
      for(int j = i + 1; j < ArraySize(sIndices); j++)
      {
         double dist1 = GetZoneDistance(g_zones[sIndices[i]], curPrice);
         double dist2 = GetZoneDistance(g_zones[sIndices[j]], curPrice);
         if(dist2 < dist1)
         {
            int tmp = sIndices[i];
            sIndices[i] = sIndices[j];
            sIndices[j] = tmp;
         }
      }
   }

   int idxSupply = (ArraySize(sIndices) > 0) ? sIndices[0] : -1;
   int idxDemand = (ArraySize(dIndices) > 0) ? dIndices[0] : -1;
   double distSupply = (idxSupply >= 0) ? GetZoneDistance(g_zones[idxSupply], curPrice) : 9999999.0;
   double distDemand = (idxDemand >= 0) ? GetZoneDistance(g_zones[idxDemand], curPrice) : 9999999.0;

   int sdScore = 50;
   if(idxSupply >= 0 && idxDemand >= 0)
   {
      if(distSupply <= 0.0 && distDemand <= 0.0)
         sdScore = 50;
      else if(distSupply <= 0.0)
         sdScore = 15; // Đang nằm trong cản cung -> Áp lực bán mạnh
      else if(distDemand <= 0.0)
         sdScore = 85; // Đang nằm trong cản cầu -> Áp lực mua mạnh
      else
      {
         double totalDist = distSupply + distDemand;
         if(totalDist > 0)
            sdScore = (int)MathRound((distSupply / totalDist) * 100.0);
      }
   }
   else if(idxSupply >= 0) sdScore = 35;
   else if(idxDemand >= 0) sdScore = 65;

   string sentiment = (sdScore > 55) ? "BULLISH" : ((sdScore < 45) ? "BEARISH" : "NEUTRAL");
   color sentimentClr = (sdScore > 55) ? C'52,211,153' : ((sdScore < 45) ? C'248,113,113' : C'250,204,21');

   bool nearIsSupply = (distSupply <= distDemand);
   int nearIdx = nearIsSupply ? idxSupply : idxDemand;

   string htfTag = EnumToString(HtfPeriod);
   StringReplace(htfTag, "PERIOD_", "");
   string ltfTag = EnumToString(LtfPeriod);
   StringReplace(ltfTag, "PERIOD_", "");

   // 1. NỀN HOÀN TOÀN ĐẶC (OPAQUE 100% - KHÔNG CHO NẾN XUYÊN THỦNG CHỮ)
   g_canvas.Erase(ColorToARGB(C'13,17,23', 255)); // Obsidian Dark
   g_canvas.Rectangle(0, 0, width - 1, height - 1, ColorToARGB(C'51,65,85', 255)); // Viền Slate thanh lịch

   // Nút Thu nhỏ / Mở rộng [ - ] hoặc [ + ]
   int btnMinW = (int)(34 * s);
   int btnMinH = (int)(30 * s);
   g_btnMinX2 = width - 16;
   g_btnMinX1 = g_btnMinX2 - btnMinW;
   g_btnMinY1 = 8;
   g_btnMinY2 = g_btnMinY1 + btnMinH;
   g_canvas.FillRectangle(g_btnMinX1, g_btnMinY1, g_btnMinX2, g_btnMinY2, ColorToARGB(C'30,41,59', 255));
   g_canvas.Rectangle(g_btnMinX1, g_btnMinY1, g_btnMinX2, g_btnMinY2, ColorToARGB(C'71,85,105', 255));
   g_canvas.FontSet("Segoe UI", (int)(14 * DashFontAdj), 700);
   g_canvas.TextOut(g_btnMinX1 + (int)(10 * s), g_btnMinY1 + (int)(3 * s), g_isMinimized ? "+" : "-", ColorToARGB(C'255,255,255', 255));

   // Badge khung thời gian top-right
   string badgeText = StringFormat("%s %s/%s", _Symbol, ltfTag, htfTag);
   int badgeW = (int)(135 * s);
   int badgeX = g_btnMinX1 - badgeW - (int)(10 * s);
   g_canvas.FillRectangle(badgeX, 8, badgeX + badgeW, g_btnMinY2, ColorToARGB(C'30,41,59', 255));
   g_canvas.Rectangle(badgeX, 8, badgeX + badgeW, g_btnMinY2, ColorToARGB(C'71,85,105', 255));
   g_canvas.FontSet("Segoe UI", (int)(10 * DashFontAdj), 700);
   g_canvas.TextOut(badgeX + (int)(10 * s), g_btnMinY1 + (int)(5 * s), badgeText, ColorToARGB(C'226,232,240', 255));

   // Tiêu đề Header (16-18pt Bold)
   g_canvas.FontSet("Segoe UI", (int)(13 * DashFontAdj), 700);
   string titleStr = (g_lang == LANG_EN ? "DUC TRI · SMC MTF PRO v4.03" : "ĐỨC TRÍ · CẢN & HỖ TRỢ PRO v4.03");
   g_canvas.TextOut(16, 12, titleStr, ColorToARGB(C'255,255,255', 255));

   V4ChartControls(posX,posY,width,height);
   if(g_isMinimized)
   {
      g_canvas.Update();
      return;
   }

   int headLineY = (int)(48 * s);
   g_canvas.Line(16, headLineY, width - 16, headLineY, ColorToARGB(C'51,65,85', 255));

   // 2. KHỐI V3.0: THANH ĐIỀU KHIỂN TRẠNG THÁI SĂN LỆNH (STATE ENGINE BAR)
   int stBarY = headLineY + (int)(8 * s);
   int stBarH = (int)(38 * s);
   int segGap = (int)(3 * s);
   int segW = (width - 32 - 3 * segGap) / 4;

   string segLabels[4];
   segLabels[0] = (g_lang == LANG_EN ? "⚪ IDLE" : "⚪ QUAN SÁT");
   segLabels[1] = (g_lang == LANG_EN ? "🟡 IN POI" : "🟡 CHẠM CẢN");
   segLabels[2] = (g_lang == LANG_EN ? "🟠 SWEEP" : "🟠 QUÉT RÂU");
   segLabels[3] = (g_lang == LANG_EN ? "🟢 CHOCH" : "🟢 XÁC NHẬN");

   color segActiveClrs[4];
   segActiveClrs[0] = C'148,163,184'; // Slate
   segActiveClrs[1] = C'250,204,21';  // Amber
   segActiveClrs[2] = C'251,146,60';  // Orange
   segActiveClrs[3] = C'52,211,153';  // Mint Emerald

   for(int s_idx = 0; s_idx < 4; s_idx++)
   {
      int x1 = 16 + s_idx * (segW + segGap);
      int x2 = x1 + segW;
      bool isActive = (g_confirmState == s_idx);

      if(isActive)
      {
         g_canvas.FillRectangle(x1, stBarY, x2, stBarY + stBarH, ColorToARGB(segActiveClrs[s_idx], 55));
         g_canvas.Rectangle(x1, stBarY, x2, stBarY + stBarH, ColorToARGB(segActiveClrs[s_idx], 255));
         g_canvas.FontSet("Segoe UI", (int)(10 * DashFontAdj), 700);
         g_canvas.TextOut(x1 + (int)(14 * s), stBarY + (int)(9 * s), segLabels[s_idx], ColorToARGB(segActiveClrs[s_idx], 255));
      }
      else
      {
         g_canvas.FillRectangle(x1, stBarY, x2, stBarY + stBarH, ColorToARGB(C'22,27,34', 255));
         g_canvas.Rectangle(x1, stBarY, x2, stBarY + stBarH, ColorToARGB(C'51,65,85', 255));
         g_canvas.FontSet("Segoe UI", (int)(10 * DashFontAdj), 700);
         g_canvas.TextOut(x1 + (int)(14 * s), stBarY + (int)(9 * s), segLabels[s_idx], ColorToARGB(C'148,163,184', 255));
      }
   }

   // 3. HÀNG 1: THẺ VÙNG GẦN NHẤT & S&D SCORE
   int cardY = stBarY + stBarH + (int)(10 * s);
   int cardH = (int)(104 * s);
   int cardGap = (int)(10 * s);
   int availW = width - 32 - cardGap;
   int cardW1 = availW * 58 / 100;
   int cardW2 = availW - cardW1;
   int card2X = 16 + cardW1 + cardGap;

   color nearClr = nearIsSupply ? C'248,113,113' : C'52,211,153';
   g_canvas.FillRectangle(16, cardY, 16 + cardW1, cardY + cardH, ColorToARGB(C'22,27,34', 255));
   g_canvas.Rectangle(16, cardY, 16 + cardW1, cardY + cardH, ColorToARGB(C'51,65,85', 255));
   g_canvas.FillRectangle(16, cardY, 21, cardY + cardH, ColorToARGB(nearClr, 255));

   g_canvas.FontSet("Segoe UI", (int)(10 * DashFontAdj), 700);
   g_canvas.TextOut(26, cardY + (int)(8 * s), (g_lang == LANG_EN ? "NEAREST HTF ZONE" : "CẢN VĨ MÔ GẦN NHẤT"), ColorToARGB(C'203,213,225', 255));

   string nearState = nearIsSupply ? (g_lang == LANG_EN ? "NEAR SUPPLY (CANH BÁN)" : "GẦN VÙNG CUNG (BÁN)") : (g_lang == LANG_EN ? "NEAR DEMAND (CANH MUA)" : "GẦN VÙNG CẦU (MUA)");
   g_canvas.FontSet("Segoe UI", (int)(11.5 * DashFontAdj), 700);
   g_canvas.TextOut(26, cardY + (int)(32 * s), nearState, ColorToARGB(nearClr, 255));

   if(nearIdx >= 0)
   {
      string tStr = EnumToString(g_zones[nearIdx].type);
      StringReplace(tStr, "ZONE_", "");
      string pillText = StringFormat("%s %d %s", tStr, g_zones[nearIdx].score, g_zones[nearIdx].isFresh ? "FRESH" : "TEST");
      int pillW = (int)(130 * s);
      int pillH = (int)(28 * s);
      int pillY = cardY + (int)(66 * s);
      g_canvas.FillRectangle(26, pillY, 26 + pillW, pillY + pillH, ColorToARGB(C'30,41,59', 255));
      g_canvas.Rectangle(26, pillY, 26 + pillW, pillY + pillH, ColorToARGB(C'71,85,105', 255));
      g_canvas.FontSet("Segoe UI", (int)(10 * DashFontAdj), 700);
      g_canvas.TextOut(34, pillY + (int)(4 * s), pillText, ColorToARGB(C'255,255,255', 255));

      double atrVal = 1.0;
      double atrs[];
      if(CopyBuffer(g_htfAtrHandle, 0, 0, 1, atrs) > 0) atrVal = atrs[0];
      double curDist = nearIsSupply ? distSupply : distDemand;
      double distAtr = curDist / (atrVal > 0 ? atrVal : 1.0);
      string distStr = (curDist <= 0.0) ? (g_lang == LANG_EN ? "IN POI (TEST)" : "ĐANG CHẠM CẢN") : StringFormat(g_lang == LANG_EN ? "dist %.1f ATR" : "cách %.1f ATR", distAtr);
      g_canvas.FontSet("Segoe UI", (int)(10.5 * DashFontAdj), 700);
      g_canvas.TextOut(26 + pillW + (int)(10 * s), pillY + (int)(4 * s), distStr, ColorToARGB(C'255,255,255', 255));
   }

   // Thẻ S&D Score
   g_canvas.FillRectangle(card2X, cardY, width - 16, cardY + cardH, ColorToARGB(C'22,27,34', 255));
   g_canvas.Rectangle(card2X, cardY, width - 16, cardY + cardH, ColorToARGB(C'51,65,85', 255));
   g_canvas.FillRectangle(card2X, cardY, card2X + 5, cardY + cardH, ColorToARGB(sentimentClr, 255));

   g_canvas.FontSet("Segoe UI", (int)(10 * DashFontAdj), 700);
   g_canvas.TextOut(card2X + (int)(12 * s), cardY + (int)(8 * s), "S&D SCORE", ColorToARGB(C'203,213,225', 255));

   int sPillW = (int)(88 * s);
   int sPillX1 = width - 16 - sPillW;
   int sPillX2 = width - 16;
   int sPillY1 = cardY + (int)(6 * s);
   int sPillY2 = sPillY1 + (int)(24 * s);
   g_canvas.FillRectangle(sPillX1, sPillY1, sPillX2, sPillY2, ColorToARGB(sentimentClr, 40));
   g_canvas.Rectangle(sPillX1, sPillY1, sPillX2, sPillY2, ColorToARGB(sentimentClr, 200));
   g_canvas.FontSet("Segoe UI", (int)(9.5 * DashFontAdj), 700);
   g_canvas.TextOut(sPillX1 + (int)(8 * s), sPillY1 + (int)(3 * s), sentiment, ColorToARGB(sentimentClr, 255));

   g_canvas.FontSet("Segoe UI", (int)(24 * DashFontAdj), 700);
   g_canvas.TextOut(card2X + (int)(12 * s), cardY + (int)(28 * s), IntegerToString(sdScore), ColorToARGB(sentimentClr, 255));
   int scoreOff = (sdScore >= 100) ? (int)(84 * s) : ((sdScore >= 10) ? (int)(66 * s) : (int)(44 * s));
   g_canvas.FontSet("Segoe UI", (int)(11 * DashFontAdj), 700);
   g_canvas.TextOut(card2X + (int)(12 * s) + scoreOff, cardY + (int)(44 * s), "/ 100", ColorToARGB(C'148,163,184', 255));

   int barW = cardW2 - (int)(24 * s);
   int fillW = barW * sdScore / 100;
   int barY = cardY + (int)(80 * s);
   int barH = (int)(10 * s);
   g_canvas.FillRectangle(card2X + (int)(12 * s), barY, card2X + (int)(12 * s) + barW, barY + barH, ColorToARGB(C'30,41,59', 255));
   g_canvas.FillRectangle(card2X + (int)(12 * s), barY, card2X + (int)(12 * s) + fillW, barY + barH, ColorToARGB(sentimentClr, 255));

   // 4. HÀNG 2: 3 THẺ PHỤ
   int row2Y = cardY + cardH + (int)(10 * s);
   int subH = (int)(70 * s);
   int subGap = (int)(8 * s);
   int subW = (width - 32 - 2 * subGap) / 3;

   // Thẻ Cầu (Demand)
   g_canvas.FillRectangle(16, row2Y, 16 + subW, row2Y + subH, ColorToARGB(C'22,27,34', 255));
   g_canvas.Rectangle(16, row2Y, 16 + subW, row2Y + subH, ColorToARGB(C'51,65,85', 255));
   g_canvas.FontSet("Segoe UI", (int)(9.5 * DashFontAdj), 700);
   g_canvas.TextOut(24, row2Y + (int)(8 * s), (g_lang == LANG_EN ? "NEAREST DEMAND" : "CẦU GẦN NHẤT"), ColorToARGB(C'203,213,225', 255));
   g_canvas.FontSet("Segoe UI", (int)(11.5 * DashFontAdj), 700);
   string dVal = (idxDemand >= 0) ? DoubleToString(g_zones[idxDemand].proximal, _Digits) : "-";
   g_canvas.TextOut(24, row2Y + (int)(30 * s), dVal, ColorToARGB(C'52,211,153', 255));
   g_canvas.FillRectangle(24, row2Y + (int)(58 * s), 24 + (int)(60 * s), row2Y + (int)(62 * s), ColorToARGB(C'16,185,129', 255));

   // Thẻ Cung (Supply)
   int sub2X = 16 + subW + subGap;
   g_canvas.FillRectangle(sub2X, row2Y, sub2X + subW, row2Y + subH, ColorToARGB(C'22,27,34', 255));
   g_canvas.Rectangle(sub2X, row2Y, sub2X + subW, row2Y + subH, ColorToARGB(C'51,65,85', 255));
   g_canvas.FontSet("Segoe UI", (int)(9.5 * DashFontAdj), 700);
   g_canvas.TextOut(sub2X + (int)(8 * s), row2Y + (int)(8 * s), (g_lang == LANG_EN ? "NEAREST SUPPLY" : "CUNG GẦN NHẤT"), ColorToARGB(C'203,213,225', 255));
   g_canvas.FontSet("Segoe UI", (int)(11.5 * DashFontAdj), 700);
   string sVal = (idxSupply >= 0) ? DoubleToString(g_zones[idxSupply].proximal, _Digits) : "-";
   g_canvas.TextOut(sub2X + (int)(8 * s), row2Y + (int)(30 * s), sVal, ColorToARGB(C'248,113,113', 255));
   g_canvas.FillRectangle(sub2X + (int)(8 * s), row2Y + (int)(58 * s), sub2X + (int)(8 * s) + (int)(60 * s), row2Y + (int)(62 * s), ColorToARGB(C'239,68,68', 255));

   // Thẻ Vùng mới
   int sub3X = sub2X + subW + subGap;
   g_canvas.FillRectangle(sub3X, row2Y, width - 16, row2Y + subH, ColorToARGB(C'22,27,34', 255));
   g_canvas.Rectangle(sub3X, row2Y, width - 16, row2Y + subH, ColorToARGB(C'51,65,85', 255));
   g_canvas.FontSet("Segoe UI", (int)(9.5 * DashFontAdj), 700);
   g_canvas.TextOut(sub3X + (int)(8 * s), row2Y + (int)(8 * s), (g_lang == LANG_EN ? "FRESH ZONES" : "VÙNG MỚI (C/C)"), ColorToARGB(C'203,213,225', 255));
   g_canvas.FontSet("Segoe UI", (int)(11.5 * DashFontAdj), 700);
   string fStr = StringFormat("%d / %d", freshDemandCount, freshSupplyCount);
   g_canvas.TextOut(sub3X + (int)(8 * s), row2Y + (int)(30 * s), fStr, ColorToARGB(C'250,204,21', 255));
   g_canvas.FillRectangle(sub3X + (int)(8 * s), row2Y + (int)(58 * s), sub3X + (int)(8 * s) + (int)(60 * s), row2Y + (int)(62 * s), ColorToARGB(C'234,179,8', 255));

   // 5. HÀNG 3: BẢNG XẾP HẠNG CẢN (ZONE RANKING)
   int rkY = row2Y + subH + (int)(10 * s);
   int rkH = (int)(194 * s);
   g_canvas.FillRectangle(16, rkY, width - 16, rkY + rkH, ColorToARGB(C'22,27,34', 255));
   g_canvas.Rectangle(16, rkY, width - 16, rkY + rkH, ColorToARGB(C'51,65,85', 255));
   g_canvas.FillRectangle(16, rkY, 21, rkY + rkH, ColorToARGB(C'56,189,248', 255));

   g_canvas.FontSet("Segoe UI", (int)(10 * DashFontAdj), 700);
   g_canvas.TextOut(28, rkY + (int)(8 * s), (g_lang == LANG_EN ? "ZONE RANKING (score ·type ·fresh ·dist)" : "XẾP HẠNG VÙNG (điểm ·kiểu ·độ mới ·cách)"), ColorToARGB(C'255,255,255', 255));

   g_canvas.FontSet("Consolas", (int)(9.5 * DashFontAdj), 700);
   int curRkY = rkY + (int)(34 * s);
   int rkPitch = (int)(26 * s);

   // 3 vùng Demand
   for(int k = 0; k < 3; k++)
   {
      string dLabel = StringFormat("▲ D%d ", k + 1);
      if(k < ArraySize(dIndices))
      {
         int idx = dIndices[k];
         double pMin = MathMin(g_zones[idx].distal, g_zones[idx].proximal);
         double pMax = MathMax(g_zones[idx].distal, g_zones[idx].proximal);
         string tStr = EnumToString(g_zones[idx].type);
         StringReplace(tStr, "ZONE_", "");
         double distP = GetZoneDistance(g_zones[idx], curPrice);
         double pts = distP / _Point;
         string ptsStr = (distP <= 0.0) ? "IN POI" : StringFormat("%4.0fpts", pts);
         string pMinStr = DoubleToString(pMin, _Digits);
         string pMaxStr = DoubleToString(pMax, _Digits);
         string pRange = pMinStr + "-" + pMaxStr;
         string rowStr = StringFormat("%s %-15s %3d  %-4s %-5s %s",
                                      dLabel, pRange, g_zones[idx].score, tStr,
                                      g_zones[idx].isFresh ? "FRESH" : "TEST ", ptsStr);
         if(k == 0)
         {
            g_canvas.FillRectangle(22, curRkY - (int)(3 * s), width - 22, curRkY + (int)(22 * s), ColorToARGB(C'52,211,153', 35));
            g_canvas.Rectangle(22, curRkY - (int)(3 * s), width - 22, curRkY + (int)(22 * s), ColorToARGB(C'52,211,153', 90));
            g_canvas.TextOut(26, curRkY, rowStr, ColorToARGB(C'52,211,153', 255));
         }
         else
         {
            g_canvas.TextOut(26, curRkY, rowStr, ColorToARGB(C'241,245,249', 255));
         }
      }
      else
      {
         g_canvas.TextOut(26, curRkY, dLabel + "-", ColorToARGB(C'148,163,184', 255));
      }
      curRkY += rkPitch;
   }

   // 3 vùng Supply
   for(int k = 0; k < 3; k++)
   {
      string sLabel = StringFormat("▼ S%d ", k + 1);
      if(k < ArraySize(sIndices))
      {
         int idx = sIndices[k];
         double pMin = MathMin(g_zones[idx].distal, g_zones[idx].proximal);
         double pMax = MathMax(g_zones[idx].distal, g_zones[idx].proximal);
         string tStr = EnumToString(g_zones[idx].type);
         StringReplace(tStr, "ZONE_", "");
         double distP = GetZoneDistance(g_zones[idx], curPrice);
         double pts = distP / _Point;
         string ptsStr = (distP <= 0.0) ? "IN POI" : StringFormat("%4.0fpts", pts);
         string pMinStr = DoubleToString(pMin, _Digits);
         string pMaxStr = DoubleToString(pMax, _Digits);
         string pRange = pMinStr + "-" + pMaxStr;
         string rowStr = StringFormat("%s %-15s %3d  %-4s %-5s %s",
                                      sLabel, pRange, g_zones[idx].score, tStr,
                                      g_zones[idx].isFresh ? "FRESH" : "TEST ", ptsStr);
         if(k == 0)
         {
            g_canvas.FillRectangle(22, curRkY - (int)(3 * s), width - 22, curRkY + (int)(22 * s), ColorToARGB(C'248,113,113', 35));
            g_canvas.Rectangle(22, curRkY - (int)(3 * s), width - 22, curRkY + (int)(22 * s), ColorToARGB(C'248,113,113', 90));
            g_canvas.TextOut(26, curRkY, rowStr, ColorToARGB(C'248,113,113', 255));
         }
         else
         {
            g_canvas.TextOut(26, curRkY, rowStr, ColorToARGB(C'241,245,249', 255));
         }
      }
      else
      {
         g_canvas.TextOut(26, curRkY, sLabel + "-", ColorToARGB(C'148,163,184', 255));
      }
      curRkY += rkPitch;
   }

   // 6. HÀNG 4: KẾ HOẠCH VÀO LỆNH XÁC NHẬN V3.0 (CONFIRMATION TRADE PLAN)
   int planY = rkY + rkH + (int)(10 * s);
   int planH = (int)(204 * s);
   g_canvas.FillRectangle(16, planY, width - 16, planY + planH, ColorToARGB(C'22,27,34', 255));
   g_canvas.Rectangle(16, planY, width - 16, planY + planH, ColorToARGB(C'51,65,85', 255));
   g_canvas.FillRectangle(16, planY, 21, planY + planH, ColorToARGB(C'168,85,247', 255)); // Tím pastel

   g_canvas.FontSet("Segoe UI", (int)(10.5 * DashFontAdj), 700);
   string planHeader = (g_lang == LANG_EN ? StringFormat("SMC CONFIRMATION PLAN (%s CHoCH & %s POI)", ltfTag, htfTag)
                                          : StringFormat("KẾ HOẠCH VÀO LỆNH XÁC NHẬN (%s CHoCH & %s POI)", ltfTag, htfTag));
   g_canvas.TextOut(28, planY + (int)(8 * s), planHeader, ColorToARGB(C'255,255,255', 255));

   int curPlanY = planY + (int)(34 * s);
   int planPitch = (int)(27 * s);
   int planValX = (int)(width - 255 * s);

   if(g_lastSignal.active)
   {
      // Hiển thị kế hoạch xác nhận gần nhất
      string sigTypeStr = g_lastSignal.isBuy ? "🟢 BUY CHoCH" : "🔴 SELL CHoCH";
      color sigClr = g_lastSignal.isBuy ? C'52,211,153' : C'248,113,113';

      g_canvas.FontSet("Segoe UI", (int)(9.8 * DashFontAdj), 700);
      g_canvas.TextOut(28, curPlanY, (g_lang == LANG_EN ? "Trigger Signal:" : "Tín hiệu kích hoạt:"), ColorToARGB(C'203,213,225', 255));
      g_canvas.TextOut(planValX, curPlanY, sigTypeStr, ColorToARGB(sigClr, 255));
      curPlanY += planPitch;

      // Trạng thái BE / Trailing
      g_canvas.TextOut(28, curPlanY, (g_lang == LANG_EN ? "Position Status:" : "Trạng thái vị thế:"), ColorToARGB(C'203,213,225', 255));
      string statusStr = "";
      color statusClr = C'203,213,225';
      if(g_lastSignal.isBeActive)
      {
          statusStr = (g_lang == LANG_EN ? "🛡️ BE SUGGESTION (SIM)" : "🛡️ GỢI Ý BE (MÔ PHỎNG)");
         statusClr = C'56,189,248'; // Cyan
      }
      else if(g_lastSignal.hitTp1)
      {
         statusStr = (g_lang == LANG_EN ? "🎉 TP1 HIT (Trailing TP2)" : "🎉 ĐÃ CHẠM TP1 (Gồng TP2)");
         statusClr = C'52,211,153'; // Green
      }
      else
      {
         string beTargetStr = (InpBeTriggerATR > 0) ? StringFormat("BE: %.1fATR", InpBeTriggerATR) : StringFormat("BE: +%.0fp", V4Distance(InpBeTriggerPips));
         statusStr = (g_lang == LANG_EN ? StringFormat("RUNNING (Max: +%.1fp / %s)", g_lastSignal.maxMfePips, beTargetStr)
                                        : StringFormat("ĐANG CHẠY (Max: +%.1fp / %s)", g_lastSignal.maxMfePips, beTargetStr));
         statusClr = C'250,204,21'; // Yellow
      }
      g_canvas.TextOut(planValX, curPlanY, statusStr, ColorToARGB(statusClr, 255));
      curPlanY += planPitch;

      // Entry Market & Limit
      g_canvas.TextOut(28, curPlanY, (g_lang == LANG_EN ? "Entry (Market/Limit):" : "Vào lệnh (Mkt/Limit):"), ColorToARGB(C'203,213,225', 255));
      string eslStr = StringFormat("%.*f / %.*f", _Digits, g_lastSignal.entryMarket, _Digits, g_lastSignal.entryLimit);
      g_canvas.TextOut(planValX, curPlanY, eslStr, ColorToARGB(C'255,255,255', 255));
      curPlanY += planPitch;

      // Stop Loss & BE
      g_canvas.TextOut(28, curPlanY, (g_lang == LANG_EN ? "Stop Loss / BE:" : "Cắt lỗ / Hòa vốn BE:"), ColorToARGB(C'203,213,225', 255));
      string slStr = StringFormat("%.*f (%.0fp) | BE: %.*f", _Digits, g_lastSignal.sl, PriceToPips(MathAbs(g_lastSignal.entry - g_lastSignal.initialSl)), _Digits, g_lastSignal.bePrice);
      g_canvas.TextOut(planValX, curPlanY, slStr, ColorToARGB(g_lastSignal.isBeActive ? C'56,189,248' : C'248,113,113', 255));
      curPlanY += planPitch;

      // TP1 & TP2
      g_canvas.TextOut(28, curPlanY, (g_lang == LANG_EN ? "TP1 / TP2 Targets:" : "Mục tiêu TP1 / TP2:"), ColorToARGB(C'203,213,225', 255));
      string tpStr = StringFormat("%.*f (+%.0fp) / %.*f (%.1fR)", _Digits, g_lastSignal.tp1, PriceToPips(MathAbs(g_lastSignal.tp1 - g_lastSignal.entry)), _Digits, g_lastSignal.tp2, g_lastSignal.rr2);
      g_canvas.TextOut(planValX, curPlanY, tpStr, ColorToARGB(C'52,211,153', 255));
      curPlanY += planPitch;

      // POI Zone
      g_canvas.TextOut(28, curPlanY, (g_lang == LANG_EN ? "POI Trigger Zone:" : "Cản kích hoạt / Râu:"), ColorToARGB(C'203,213,225', 255));
      string poiStr = StringFormat("%s #%I64d %.2f–%.2f", g_lastSignal.zoneType, g_lastSignal.source_zone_id, g_lastSignal.source_distal, g_lastSignal.source_proximal);
      g_canvas.TextOut(planValX, curPlanY, poiStr, ColorToARGB(C'203,213,225', 255));
   }
   else
   {
      // Khi chưa có tín hiệu xác nhận: Hiển thị trạng thái rình mồi
      g_canvas.FontSet("Segoe UI", (int)(9.8 * DashFontAdj), 700);

      string huntStatus = "";
      color  huntClr = C'148,163,184';
      if(g_confirmState == STATE_IDLE)
      {
         huntStatus = (g_lang == LANG_EN ? "⚪ IDLE: Waiting for H1 POI touch" : "⚪ QUAN SÁT: Chờ giá tiếp cận cản H1");
         huntClr = C'203,213,225';
      }
      else if(g_confirmState == STATE_IN_POI)
      {
         huntStatus = (g_lang == LANG_EN ? "🟡 IN POI: Scanning M5 liquidity sweeps" : "🟡 CHẠM CẢN: Kích hoạt bộ quét râu M5");
         huntClr = C'250,204,21';
      }
      else if(g_confirmState == STATE_SWEEP)
      {
         huntStatus = (g_lang == LANG_EN ? "🟠 SWEEP: Wick >= 35%! Awaiting CHoCH close" : "🟠 ĐÃ QUÉT RÂU: Chờ nến M5 đóng cửa CHoCH");
         huntClr = C'251,146,60';
      }

      g_canvas.TextOut(28, curPlanY, huntStatus, ColorToARGB(huntClr, 255));
      curPlanY += planPitch;

      // Kế hoạch Limit dự phòng
      g_canvas.TextOut(28, curPlanY, (g_lang == LANG_EN ? "Buy at demand (E/SL/TP):" : "Mua tại cầu (E/SL/TP):"), ColorToARGB(C'203,213,225', 255));
      if(ArraySize(dIndices) > 0)
      {
         int bIdx = dIndices[0];
         double entry = g_zones[bIdx].proximal;
         double atrVal = 1.0;
         double atrs[];
         if(CopyBuffer(g_htfAtrHandle, 0, 0, 1, atrs) > 0) atrVal = atrs[0];
         double sl = g_zones[bIdx].distal - (SlBufferATR * atrVal);
         double tp = (ArraySize(sIndices) > 0) ? g_zones[sIndices[0]].proximal : entry + 2.0 * MathAbs(entry - sl);
         string bPlan = StringFormat("%.5f / %.5f / %.5f", entry, sl, tp);
         g_canvas.TextOut(planValX, curPlanY, bPlan, ColorToARGB(C'52,211,153', 255));
      }
      else
      {
         g_canvas.TextOut(planValX + (int)(50 * s), curPlanY, "- / - / -", ColorToARGB(C'148,163,184', 255));
      }
      curPlanY += planPitch;

      g_canvas.TextOut(28, curPlanY, (g_lang == LANG_EN ? "Sell at supply (E/SL/TP):" : "Bán tại cung (E/SL/TP):"), ColorToARGB(C'203,213,225', 255));
      if(ArraySize(sIndices) > 0)
      {
         int sIdx = sIndices[0];
         double entry = g_zones[sIdx].proximal;
         double atrVal = 1.0;
         double atrs[];
         if(CopyBuffer(g_htfAtrHandle, 0, 0, 1, atrs) > 0) atrVal = atrs[0];
         double sl = g_zones[sIdx].distal + (SlBufferATR * atrVal);
         double tp = (ArraySize(dIndices) > 0) ? g_zones[dIndices[0]].proximal : entry - 2.0 * MathAbs(sl - entry);
         string sPlan = StringFormat("%.5f / %.5f / %.5f", entry, sl, tp);
         g_canvas.TextOut(planValX, curPlanY, sPlan, ColorToARGB(C'248,113,113', 255));
      }
      else
      {
         g_canvas.TextOut(planValX + (int)(50 * s), curPlanY, "- / - / -", ColorToARGB(C'148,163,184', 255));
      }
      curPlanY += planPitch;

      g_canvas.TextOut(28, curPlanY, (g_lang == LANG_EN ? "Stats (Created/Broken/Flip):" : "Thống kê (Tạo/Phá/Chuyển):"), ColorToARGB(C'203,213,225', 255));
      string statStr = StringFormat("%d (%dCầu %dCung) / %d / %d", g_statCreated, g_statDemand, g_statSupply, g_statBroken, g_statFlipped);
      g_canvas.TextOut(planValX, curPlanY, statStr, ColorToARGB(C'255,255,255', 255));
      curPlanY += planPitch;

      g_canvas.TextOut(28, curPlanY, (g_lang == LANG_EN ? "Killzones Filter:" : "Bộ lọc giờ vàng KZ:"), ColorToARGB(C'203,213,225', 255));
      string kzStr = FilterKillzones ? (g_lang == LANG_EN ? "ACTIVE (London/NY)" : "BẬT (London/NY)") : (g_lang == LANG_EN ? "24/5 ALL SESSIONS" : "24/5 TOÀN PHIÊN");
      g_canvas.TextOut(planValX, curPlanY, kzStr, ColorToARGB(FilterKillzones ? C'52,211,153' : C'203,213,225', 255));
   }

   // 7. HÀNG 5: SỰ KIỆN GẦN NHẤT (RECENT EVENTS)
   int evY = planY + planH + (int)(10 * s);
   int evH = (int)(96 * s);
   g_canvas.FillRectangle(16, evY, width - 16, evY + evH, ColorToARGB(C'22,27,34', 255));
   g_canvas.Rectangle(16, evY, width - 16, evY + evH, ColorToARGB(C'51,65,85', 255));
   g_canvas.FillRectangle(16, evY, 21, evY + evH, ColorToARGB(C'250,204,21', 255));

   g_canvas.FontSet("Segoe UI", (int)(10 * DashFontAdj), 700);
   g_canvas.TextOut(28, evY + (int)(8 * s), (g_lang == LANG_EN ? "RECENT CONFIRMATION EVENTS" : "SỰ KIỆN XÁC NHẬN GẦN NHẤT"), ColorToARGB(C'255,255,255', 255));

   g_canvas.FontSet("Segoe UI", (int)(9.5 * DashFontAdj), 700);
   int curEvY = evY + (int)(32 * s);
   int evPitch = (int)(21 * s);
   if(ArraySize(g_events) == 0)
   {
      g_canvas.TextOut(28, curEvY, (g_lang == LANG_EN ? "No confirmation events recorded yet" : "Chưa có sự kiện xác nhận nào"), ColorToARGB(C'148,163,184', 255));
   }
   else
   {
      for(int e = 0; e < MathMin(3, ArraySize(g_events)); e++)
      {
         g_canvas.FillCircle(34, curEvY + (int)(7 * s), (int)(5 * s), ColorToARGB(g_events[e].dotColor, 255));
         g_canvas.TextOut(46, curEvY, g_events[e].text, ColorToARGB(C'255,255,255', 255));
         curEvY += evPitch;
      }
   }

   // 8. FOOTER SECTION: TIME & BUTTONS
   int footY = height - (int)(42 * s);
   string timeStr = TimeToString(TimeCurrent(), TIME_DATE|TIME_MINUTES) + " V3.0";
   g_canvas.FontSet("Segoe UI", (int)(9.5 * DashFontAdj), 700);
   g_canvas.TextOut(16, footY + (int)(6 * s), timeStr, ColorToARGB(C'148,163,184', 255));

   int btnH = (int)(28 * s);

   // Nút chuyển ngôn ngữ VI/EN
   g_btnLangX2 = width - 16;
   g_btnLangX1 = g_btnLangX2 - (int)(52 * s);
   g_btnLangY1 = footY;
   g_btnLangY2 = footY + btnH;
   g_canvas.FillRectangle(g_btnLangX1, g_btnLangY1, g_btnLangX2, g_btnLangY2, ColorToARGB(C'30,41,59', 255));
   g_canvas.Rectangle(g_btnLangX1, g_btnLangY1, g_btnLangX2, g_btnLangY2, ColorToARGB(C'71,85,105', 255));
   g_canvas.FontSet("Segoe UI", (int)(10 * DashFontAdj), 700);
   g_canvas.TextOut(g_btnLangX1 + (int)(15 * s), g_btnLangY1 + (int)(5 * s), (g_lang == LANG_EN ? "EN" : "VI"), ColorToARGB(C'255,255,255', 255));

   // Nút INFO
   g_btnWebX2 = g_btnLangX1 - (int)(10 * s);
   g_btnWebX1 = g_btnWebX2 - (int)(64 * s);
   g_btnWebY1 = footY;
   g_btnWebY2 = footY + btnH;
   g_canvas.FillRectangle(g_btnWebX1, g_btnWebY1, g_btnWebX2, g_btnWebY2, ColorToARGB(C'30,41,59', 255));
   g_canvas.Rectangle(g_btnWebX1, g_btnWebY1, g_btnWebX2, g_btnWebY2, ColorToARGB(C'71,85,105', 255));
   g_canvas.FontSet("Segoe UI", (int)(10 * DashFontAdj), 700);
   g_canvas.TextOut(g_btnWebX1 + (int)(14 * s), g_btnWebY1 + (int)(5 * s), "INFO", ColorToARGB(C'255,255,255', 255));

   // Nút TELEGRAM
   g_btnTgX2 = g_btnWebX1 - (int)(10 * s);
   g_btnTgX1 = g_btnTgX2 - (int)(106 * s);
   g_btnTgY1 = footY;
   g_btnTgY2 = footY + btnH;
   g_canvas.FillRectangle(g_btnTgX1, g_btnTgY1, g_btnTgX2, g_btnTgY2, ColorToARGB(C'30,41,59', 255));
   g_canvas.Rectangle(g_btnTgX1, g_btnTgY1, g_btnTgX2, g_btnTgY2, ColorToARGB(C'71,85,105', 255));
   g_canvas.FontSet("Segoe UI", (int)(10 * DashFontAdj), 700);
   g_canvas.TextOut(g_btnTgX1 + (int)(14 * s), g_btnTgY1 + (int)(5 * s), "TELEGRAM", ColorToARGB(C'255,255,255', 255));

   g_canvas.Update();
}

//+------------------------------------------------------------------+
//| Xử lý sự kiện Click chuột trên Dashboard                         |
//+------------------------------------------------------------------+
void OnChartEvent(const int id,
                  const long &lparam,
                  const double &dparam,
                  const string &sparam)
{
   if(id==CHARTEVENT_OBJECT_CLICK && (sparam==g_prefix+"M2_EXPORT" || sparam==g_prefix+"EXPORT")) { V4M2Export(); return; }
   if(id == CHARTEVENT_CLICK)
   {
      int clickX = (int)lparam;
      int clickY = (int)dparam;

      int width  = (int)(460 * DashScale);
      int posX = DashX;
      int posY = InpDashBottom?MathMax(0,(int)ChartGetInteger(0,CHART_HEIGHT_IN_PIXELS)-(g_isMinimized?(int)(44*DashScale):(int)(725*DashScale))-DashY-30):DashY;
      if(DashRight)
         posX = (int)ChartGetInteger(0, CHART_WIDTH_IN_PIXELS) - width - DashX;

      int relX = clickX - posX;
      int relY = clickY - posY;

      // Nút thu nhỏ / mở rộng [ - ] hoặc [ + ]
      if(relX >= g_btnMinX1 && relX <= g_btnMinX2 && relY >= g_btnMinY1 && relY <= g_btnMinY2)
      {
         g_isMinimized = !g_isMinimized;
         RenderDashboard(SymbolInfoDouble(_Symbol, SYMBOL_BID));
         ChartRedraw(0);
         return;
      }

      if(g_isMinimized) return;

      // Click nút chuyển đổi ngôn ngữ
      if(relX >= g_btnLangX1 && relX <= g_btnLangX2 && relY >= g_btnLangY1 && relY <= g_btnLangY2)
      {
         g_lang = (g_lang == LANG_EN) ? LANG_VI : LANG_EN;
         RenderDashboard(SymbolInfoDouble(_Symbol, SYMBOL_BID));
         ChartRedraw(0);
         return;
      }

      // Click nút INFO
      if(relX >= g_btnWebX1 && relX <= g_btnWebX2 && relY >= g_btnWebY1 && relY <= g_btnWebY2)
      {
         Alert(StringFormat("Đức Trí Cản Hỗ Trợ Pro v4.03 [resolved state; indicator contract risk]\nTác giả: %s\nHỗ trợ Telegram: %s", AboutAuthor, AboutSupport));
         return;
      }

      // Click nút TELEGRAM
      if(relX >= g_btnTgX1 && relX <= g_btnTgX2 && relY >= g_btnTgY1 && relY <= g_btnTgY2)
      {
         bool isBridgeOnline = false;
         if(GlobalVariableCheck("DucTri_TgBridge_Heartbeat"))
         {
            datetime hb = (datetime)GlobalVariableGet("DucTri_TgBridge_Heartbeat");
            if(TimeLocal() - hb <= 5) isBridgeOnline = true;
         }

         if(!isBridgeOnline)
         {
            string warnMsg = (g_lang == LANG_EN) ?
               "⚠️ Telegram Bridge EA is OFFLINE!\n\nTo enable Telegram alerts:\n1. Open MT5 -> Tools -> Options -> Expert Advisors -> Allow WebRequest for 'https://api.telegram.org'\n2. Attach EA 'duc_tri_telegram_bridge' to any chart.\n\n(Tip: 'AlertPush = true' is enabled by default to receive instant push alerts on MT5 Mobile App!)" :
               "⚠️ EA Telegram Bridge chưa hoạt động (OFFLINE)!\n\nĐể nhận tin nhắn Telegram:\n1. Vào MT5 -> Tools -> Options -> Expert Advisors -> Allow WebRequest cho 'https://api.telegram.org'\n2. Kéo EA 'duc_tri_telegram_bridge' vào bất kỳ chart nào.\n\n(Mẹo: 'AlertPush = true' đã được bật sẵn để nhận thông báo đẩy tức thì trên điện thoại qua app MT5!)";
            Alert(warnMsg);
         }
         else
         {
            string testMsg = StringFormat(
               "🎉 <b>KẾT NỐI TELEGRAM BOT THÀNH CÔNG!</b>\n" +
               "━━━━━━━━━━━━━━━━━━━\n" +
               "🤖 <b>Bot:</b> Đức Trí SMC Institutional Engine v3.1\n" +
               "💎 <b>Tài sản test:</b> <code>%s</code>\n" +
               "⏱ <b>Thời gian:</b> <code>%s</code>\n" +
               "━━━━━━━━━━━━━━━━━━━\n" +
               "✅ <i>Cổng chuyển tiếp Telegram Bridge đang hoạt động hoàn hảo! Bạn sẽ nhận được thông báo ngay khi có kèo M5 CHoCH mới.</i>",
               _Symbol, TimeToString(TimeLocal(), TIME_DATE|TIME_MINUTES)
            );
            DispatchTelegram(testMsg);
            Alert("✅ Đã gửi tín hiệu kiểm tra kết nối tới Telegram Bot qua Bridge EA!");
         }
         return;
      }
   }
}

//+------------------------------------------------------------------+
//| Áp dụng Theme màu Chart                                          |
//+------------------------------------------------------------------+
void ApplyChartTheme(ENUM_THEME th)
{
   if(th == THEME_DARK)
   {
      ChartSetInteger(0, CHART_COLOR_BACKGROUND, C'13,17,23');
      ChartSetInteger(0, CHART_COLOR_FOREGROUND, C'163,173,184');
      ChartSetInteger(0, CHART_COLOR_GRID, C'24,30,40');
      ChartSetInteger(0, CHART_COLOR_CHART_UP, C'52,211,153');
      ChartSetInteger(0, CHART_COLOR_CHART_DOWN, C'248,113,113');
      ChartSetInteger(0, CHART_COLOR_CANDLE_BULL, C'52,211,153');
      ChartSetInteger(0, CHART_COLOR_CANDLE_BEAR, C'248,113,113');
      ChartSetInteger(0, CHART_COLOR_CHART_LINE, C'56,189,248');
   }
   else if(th == THEME_MIDNIGHT)
   {
      ChartSetInteger(0, CHART_COLOR_BACKGROUND, C'10,14,23');
      ChartSetInteger(0, CHART_COLOR_FOREGROUND, C'148,163,184');
      ChartSetInteger(0, CHART_COLOR_GRID, C'20,28,44');
      ChartSetInteger(0, CHART_COLOR_CHART_UP, C'56,189,248');
      ChartSetInteger(0, CHART_COLOR_CHART_DOWN, C'244,63,94');
      ChartSetInteger(0, CHART_COLOR_CANDLE_BULL, C'56,189,248');
      ChartSetInteger(0, CHART_COLOR_CANDLE_BEAR, C'244,63,94');
      ChartSetInteger(0, CHART_COLOR_CHART_LINE, C'168,85,247');
   }
   else if(th == THEME_LIGHT)
   {
      ChartSetInteger(0, CHART_COLOR_BACKGROUND, C'248,250,252');
      ChartSetInteger(0, CHART_COLOR_FOREGROUND, C'30,41,59');
      ChartSetInteger(0, CHART_COLOR_GRID, C'226,232,240');
      ChartSetInteger(0, CHART_COLOR_CHART_UP, C'16,185,129');
      ChartSetInteger(0, CHART_COLOR_CHART_DOWN, C'239,68,68');
      ChartSetInteger(0, CHART_COLOR_CANDLE_BULL, C'16,185,129');
      ChartSetInteger(0, CHART_COLOR_CANDLE_BEAR, C'239,68,68');
      ChartSetInteger(0, CHART_COLOR_CHART_LINE, C'14,165,233');
   }
   ChartRedraw(0);
}
//+------------------------------------------------------------------+
