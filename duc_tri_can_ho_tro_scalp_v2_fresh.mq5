//+------------------------------------------------------------------+
//|                                           duc_tri_can_ho_tro.mq5 |
//|                                Copyright 2026, Đức Trí Trading   |
//|                    100% Pure MQL5 - Hoàn toàn KHÔNG dùng DLL     |
//|        Giao diện PRO SCALP LAB 0.2 FRESH - risk/state corrections                 |
//+------------------------------------------------------------------+
#property copyright   "Đức Trí"
#property link        "https://t.me/botfather6868"
#property version     "4.10"
#property description "Fresh-zone research: H1 sweep + M5; <=1 prior test; TP0.5R; EDGE NOT CONFIRMED"
#property indicator_chart_window
#property indicator_buffers 0
#property indicator_plots   0

#include <Canvas\Canvas.mqh>

//+------------------------------------------------------------------+
//| Enumerations                                                     |
//+------------------------------------------------------------------+
enum ENUM_LANG
{
   LANG_VI = 0, // Tiếng Việt (Mặc định)
   LANG_EN = 1  // English
};

enum ENUM_THEME
{
   THEME_NONE     = 0, // Giữ nguyên màu chart hiện tại
   THEME_DARK     = 1, // Modern Dark Slate (Khuyên dùng)
   THEME_MIDNIGHT = 2, // Midnight Obsidian
   THEME_LIGHT    = 3  // Clean Light
};

enum ENUM_ZONE_TYPE
{
   ZONE_RBR  = 0, // RBR (Rally-Base-Rally - Cầu tiếp diễn)
   ZONE_DBR  = 1, // DBR (Drop-Base-Rally - Cầu đảo chiều)
   ZONE_DBD  = 2, // DBD (Drop-Base-Drop - Cung tiếp diễn)
   ZONE_RBD  = 3, // RBD (Rally-Base-Drop - Cung đảo chiều)
   ZONE_FLIP = 4  // FLIP (Vùng đảo vai trò cản)
};

enum ENUM_CONFIRM_STATE
{
   STATE_IDLE      = 0, // ⚪ QUAN SÁT (IDLE) - Giá nằm ngoài cản H1
   STATE_IN_POI    = 1, // 🟡 CHẠM CẢN (IN POI) - Đang thử thách cản H1
   STATE_SWEEP     = 2, // 🟠 QUÉT RÂU (SWEEP) - Phát hiện râu rút chân >= 35%
   STATE_CONFIRMED = 3  // 🟢 ĐÃ XÁC NHẬN (CHOCH) - Nến đóng cửa phá vỡ cấu trúc
};

enum ENUM_SL_MODE
{
   SL_STRUCTURAL_SWING = 0, // Neo râu Swing gần nhất / Base nến CHoCH (Chuẩn SMC)
   SL_SWEEP_DISTAL     = 1  // Neo râu quét xa nhất (Distal Sweep Wick - Kiểu cũ)
};

enum ENUM_SWEEP_LEVEL
{
   SWEEP_PROXIMAL = 0, // Quét mép gần của vùng H1
   SWEEP_DISTAL   = 1  // Quét xuyên mép xa của vùng H1
};

enum ENUM_ENTRY_MODE
{
   ENTRY_DUAL_RECOMMEND = 0, // Song song Market & Limit đón hồi 50% (Khuyên dùng)
   ENTRY_MARKET_CONFIRM = 1, // Khớp ngay giá đóng cửa Market nến CHoCH
   ENTRY_PULLBACK_50    = 2, // Đón nhịp hồi 50% nến CHoCH (Mean Threshold)
   ENTRY_FVG_CE         = 3  // Đón nhịp hồi Consequent Encroachment (CE 50% FVG)
};

enum ENUM_TP_MODE
{
   TP_MODE_HYBRID = 0, // Hybrid: TP1 chốt nhanh theo Pips (+60p), TP2 gồng R:R (2.0R)
   TP_MODE_RR     = 1, // Thuần R:R (TP1 = 1.5R, TP2 = 2.0R)
   TP_MODE_PIPS   = 2, // Thuần Pips cố định (+60 pips & +120 pips)
   TP_MODE_SCALP  = 3  // Một mục tiêu scalp: TP1 và TP2 cùng một giá
};


//+------------------------------------------------------------------+
//| Input Parameters                                                 |
//+------------------------------------------------------------------+
#define CHT_EXTERNAL_CONFIG
#include "Include/CanHoTroScalpTypes.mqh"
#include "Include/CanHoTroScalpPlan.mqh"
#define CHT_INPUTS_EARLY
input group "=== LAB 0.2 FRESH: VIRTUAL PLANS / NO BROKER ORDERS ==="
input bool InpLabVirtualPlans=false; // Research gate not passed: observe by default
input CHTPolicy InpLabPolicy=CHT_T05;
input bool InpLabRoom=false;
input bool InpLabBody50=false;
input double InpLabSlippageTicks=0;

input group "=== 1. NHẬN DIỆN VÙNG CẢN (ZONE DETECTION) ==="
input int             BaseMaxBars     = 5;           // Base tối đa (nến) / max base bars (1-5 nến)
input double          BaseBarATR      = 0.8;         // Mỗi nến base: biên độ <= x ATR
input double          BaseTotalATR    = 2.0;         // Cả cụm base: biên độ <= x ATR
input double          DepartATR       = 1.8;         // Cú bung đà >= x ATR (từ mép base)
input int             DepartBars      = 4;           // Bung đà trong tối đa N nến
input int             LegInBars       = 15;          // Quét leg-in (R/D) trong N nến trước base
input int             AtrLen          = 14;          // Chu kỳ ATR
input int             MaxHistory      = 3000;        // Quét N nến lịch sử gần nhất

input group "=== 2. QUẢN LÝ VÙNG CẢN (ZONE MANAGEMENT) ==="
input int             MaxTests        = 4;           // Bỏ vùng sau N lần test (Mặc định 4)
input int             MaxAgeBars      = 1200;        // Bỏ vùng cũ hơn N nến (1200 nến H1 ~ 50 ngày)
input bool            UseFlip         = true;        // Vùng bị thủng -> flip đảo chiều vai trò
input int             FlipLifeBars    = 400;         // Vùng flip tồn tại tối đa N nến
input int             MaxZones        = 2;           // Vẽ tối đa N vùng mỗi phía (Mặc định 2 vùng gần nhất)
input int             MinScoreShow    = 35;          // Chỉ vẽ vùng có điểm số >= x

input group "=== 3. HỆ THỐNG CHẤM ĐIỂM (SCORING) ==="
input double          WDepart         = 40.0;        // Điểm tối đa cho lực bứt phá (Departure)
input double          WBase           = 20.0;        // Điểm tối đa cho base chặt chẽ
input double          WFresh          = 20.0;        // Điểm cho vùng còn mới (Freshness)
input double          WReversal       = 10.0;        // Điểm cộng cho mô hình đảo chiều (DBR/RBD)
input double          WMtf            = 10.0;        // Điểm cộng khi trùng cản khung lớn (MTF Overlap)

input group "=== 4. ĐA KHUNG THỜI GIAN & XÁC NHẬN (MTF CONFIRMATION) ==="
input ENUM_TIMEFRAMES HtfPeriod       = PERIOD_H1;   // Khung lớn xác định vùng Cản POI chính (Mặc định H1)
input ENUM_TIMEFRAMES LtfPeriod       = PERIOD_M5;   // Khung nhỏ tìm điểm kích hoạt vào lệnh (Mặc định M5)
input bool            UseLtfConfirm   = true;        // Bật quét tín hiệu xác nhận khung nhỏ
input bool            ShowArrows      = true;        // Vẽ mũi tên tín hiệu trên biểu đồ
input int             ArrowSize       = 2;           // Kích thước mũi tên tín hiệu
input double          WickRatioMin    = 0.50;        // Tỷ lệ râu quét thanh khoản tối thiểu (0.50 = 50%)
input ENUM_SWEEP_LEVEL SweepLevelMode  = SWEEP_PROXIMAL; // Mép vùng phải bị quét
input double          MinDisplacementATR = 0.25;     // Thân nến CHoCH tối thiểu theo ATR M5
input bool            UseHtfTrendFilter = true;      // Chỉ nhận tín hiệu cùng phía EMA H1 đã đóng
input int             HtfTrendMAPeriod = 50;         // Chu kỳ EMA H1 cho bộ lọc xu hướng
input double          MaxHtfEmaDistanceATR = 1.75;   // Khoảng cách tối đa tới EMA H1 theo ATR H1; 0 = tắt
input bool            FilterKillzones = true;        // Lọc theo giờ vàng London/New York
input int             KillzoneHourOffset = 0;        // Cộng vào giờ feed để khớp giờ kiểm định (UTC/data)
input bool            ExcludeWeakKzHours = true;     // Bỏ 12:00 và 14:00 theo giờ dữ liệu kiểm định XAUUSD
input int             LtfBarsScan     = 300;         // Số nến khung nhỏ phân tích điểm kích hoạt
input bool            UseReferenceLevels = true;     // Dùng PDH/PDL đã đóng làm cản tham chiếu
input bool            ShowReferenceLevels = true;    // Vẽ PDH/PDL trên chart
input double          MaxSpreadPrice   = 0.45;       // XAU: Ask-Bid tối đa (USD/oz)

input group "=== 5. KẾ HOẠCH VÀO LỆNH (TRADE PLAN) ==="
input ENUM_SL_MODE    InpSlMode        = SL_STRUCTURAL_SWING; // Phương pháp đặt Stop Loss (SMC Swing vs Sweep Distal)
input double          SlBufferATR      = 0.25;        // Đệm Stop Loss ngoài râu nến (x ATR)
input double          MaxSlPips        = 200.0;       // Giới hạn Stop Loss tối đa (pips, 200p = 20.0$ Vàng)
input double          MinSlPips        = 20.0;        // Giới hạn Stop Loss tối thiểu (pips, 20p = 2.0$ Vàng)
input ENUM_ENTRY_MODE InpEntryMode     = ENTRY_MARKET_CONFIRM; // Market sau nến xác nhận
input ENUM_TP_MODE    InpTpMode        = TP_MODE_SCALP; // Một mục tiêu scalp
input double          InpTp1RR         = 0.5;         // Mục tiêu scalp theo R
input double          InpTp2RR         = 1.0;         // Dùng cho các chế độ hai mục tiêu
input double          InpTp1Pips       = 60.0;        // Số pips cho TP1 (60 pips = 6.0$ Vàng)
input double          InpTp2Pips       = 120.0;       // Số pips cho TP2 (120 pips = 12.0$ Vàng)
input double          MinRR            = 0.5;         // Tỷ lệ R:R tối thiểu để đề xuất kế hoạch scalp

input group "=== 5B. BẢO VỆ VỊ THẾ AUTO BREAK-EVEN (BE) ==="
input bool            InpUseAutoBE     = false;       // Tắt BE trong preset scalp đã kiểm định
input double          InpBeTriggerPips = 60.0;        // Kích hoạt dời BE khi giá chạy xanh >= x pips (60p = 6.0$)
input double          InpBeTriggerATR  = 0.0;         // Kích hoạt dời BE khi giá chạy xanh >= x ATR (0.0 = chỉ theo pips)
input double          InpBeOffsetPips  = 1.0;         // Đệm phí khi dời về BE (Entry + x pips)
input bool            ShowTradeLines   = true;        // Vẽ đường Entry, SL, BE, TP1, TP2 trên Chart
input bool            AlertBeTriggered = false;        // Báo động & Telegram khi lệnh chạm ngưỡng dời BE

input group "=== 6. GIAO DIỆN CHART (APPEARANCE) ==="
input ENUM_THEME      Theme           = THEME_DARK;  // Giao diện màu nền chart
input bool            RestoreTheme    = true;        // Trả lại màu cũ khi gỡ chỉ báo
input bool            ShowLabels      = true;        // Hiển thị nhãn tên vùng & điểm số
input int             LabelFont       = 8;           // Cỡ chữ nhãn vùng
input int             ExtendBars      = 25;          // Kéo dài vùng cản về bên phải (nến)

input group "=== 7. BẢNG ĐIỀU KHIỂN (DASHBOARD) ==="
input bool            ShowDash        = true;        // Hiển thị bảng Dashboard
input bool            DashRight       = false;       // Neo góc phải (false = neo góc trái)
input int             DashX           = 20;          // Cách mép ngang (px)
input int             DashY           = 30;          // Cách mép trên (px)
input double          DashScale       = 1.2;         // Tỷ lệ kích thước Panel (1.0 - 2.0, Mặc định 1.2 cho màn hình HD/4K)
input double          DashFontAdj     = 1.4;         // Tinh chỉnh cỡ chữ (1.0 - 2.0, Mặc định 1.4 rõ nét trên màn hình High-DPI)
input ENUM_LANG       DefaultLang     = LANG_VI;     // Ngôn ngữ mặc định (VI/EN)

input group "=== 8. CẢNH BÁO (ALERTS) ==="
input bool            AlertPopup      = false;        // Bật cửa sổ Alert Popup
input bool            AlertPush       = false;        // Báo qua Push Notification điện thoại (App MT5)
input bool            AlertSoundOn    = false;        // Phát âm thanh
input string          AlertSoundFile  = "alert.wav"; // Tên file âm thanh
input bool            AlertNewZone    = false;        // Báo khi xuất hiện vùng cản mới
input bool            AlertEnter      = false;        // Báo khi giá tiến vào vùng cản
input bool            AlertBreak      = false;        // Báo khi vùng cản bị phá thủng / flip
input bool            AlertConfirm    = false;        // Báo khi nến M5 xác nhận CHoCH vào lệnh
input int             AlertMinScore   = 50;          // Chỉ báo cho các vùng có điểm >= x

input group "=== 9. THÔNG BÁO TELEGRAM (PURE MQL5 - NO DLL) ==="
input bool            TgEnable           = false;     // Bật gửi Telegram (qua companion Bridge EA)
input string          TgToken            = "";       // Telegram Bot Token (từ @BotFather)
input string          TgChatID           = "";       // Telegram Chat ID (từ @userinfobot)
input bool            TgAlertSignalsOnly = true;     // Chỉ báo KÈO CHoCH xác nhận (Tắt spam chạm cản)

input group "=== 10. THÔNG TIN (ABOUT) ==="
input string          AboutAuthor     = "Đức Trí";
input string          AboutSupport    = "https://t.me/botfather6868";

//+------------------------------------------------------------------+
//| Cấu trúc dữ liệu Vùng cản & Tín hiệu Xác nhận                   |
//+------------------------------------------------------------------+
struct SZone
{
   int               id;
   ENUM_ZONE_TYPE    type;          // RBR, DBR, DBD, RBD, FLIP
   bool              isSupply;      // true: Supply, false: Demand
   datetime          timeStart;
   datetime          timeEnd;
   double            distal;        // Vạch cản xa (Dùng đặt SL)
   double            proximal;      // Vạch cản gần giá (Dùng làm Entry)
   int               testCount;     // Số lần giá đã chạm test
   bool              isFresh;       // Vùng còn mới nguyên
   bool              isBroken;      // Đã bị đóng nến xuyên thủng
   bool              isFlip;        // Do phá cản chuyển đổi vai trò
   int               score;         // Điểm số chất lượng (0 - 100)
   double            departAtr;     // Biên độ cú bứt phá (tính bằng ATR)
   int               baseBars;      // Số nến trong cụm base
   bool              hasHtfOverlap; // Có nằm trong cản khung lớn hơn hay không
   int               ageBars;       // Tuổi thọ vùng theo số nến
};

struct SEventLog
{
   string            text;
   color             dotColor;
   int               barsAgo;
};

struct SConfirmSignal
{
   bool              active;
   bool              isBuy;         // true: BUY CHoCH, false: SELL CHoCH
   datetime          time;          // Thời gian nến xác nhận
   double            entry;         // Giá vào lệnh (Market hoặc Limit đã chọn)
   double            entryMarket;   // Giá vào lệnh Market (Close nến xác nhận)
   double            entryLimit;    // Giá Limit đón nhịp hồi 50% (Mean Threshold / FVG CE)
   double            sl;            // Stop loss hiện tại (được dời về BE khi kích hoạt)
   double            initialSl;     // Stop loss ban đầu trước khi dời BE
   double            tp1;           // Chốt lời 1
   double            tp2;           // Chốt lời 2
   double            tpMacro;       // Mục tiêu Cản H1 đối diện (Macro Target)
   double            rr1;           // Tỷ lệ R:R của TP1
   double            rr2;           // Tỷ lệ R:R của TP2
   double            rrMacro;       // Tỷ lệ R:R của Cản đối diện
   double            sweepPrice;    // Đáy/đỉnh của râu quét thanh khoản
   int               zoneId;        // ID vùng cản H1 kích hoạt
   string            zoneType;      // Kiểu cản H1 (RBR, DBR, DBD, RBD, FLIP)
   int               zoneScore;     // Điểm số vùng cản
   bool              isBeActive;    // Trạng thái đã dời SL về Break-Even
   double            bePrice;       // Mức giá dời về BE (+ đệm phí)
   double            maxMfePips;    // MFE lớn nhất đã chạy (tính bằng pips)
   bool              hitTp1;        // Đã chạm TP1
   bool              hitTp2;        // Đã chạm TP2
   double            ltfAtr;        // ATR khung M5 tại thời điểm phát tín hiệu
};

//+------------------------------------------------------------------+
//| Biến toàn cục                                                    |
//+------------------------------------------------------------------+
#include "Include/CanHoTroScalpDetector.mqh"
#include "Include/CanHoTroScalpPlan.mqh"
#include "Include/CanHoTroScalpState.mqh"
CCanvas              g_canvas;
string               g_cvName       = "DucTri_CV";
string               g_prefix       = "DucTri_";
int                  g_atrHandle    = INVALID_HANDLE;
int                  g_htfAtrHandle = INVALID_HANDLE;
int                  g_ltfAtrHandle = INVALID_HANDLE;
int                  g_htfMaHandle  = INVALID_HANDLE;
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
int                  g_lastSignalSeenZone = -1;
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
#include "Include/CanHoTroScalpNativeV2Fresh.mqh"
bool CHTLockedPreset()
{
   return BaseMaxBars==5 &&
          BaseBarATR==0.8 &&
          BaseTotalATR==2.0 &&
          DepartATR==1.8 &&
          DepartBars==4 &&
          LegInBars==15 &&
          AtrLen==14 &&
          MaxHistory==3000 &&
          MaxTests==4 &&
          MaxAgeBars==1200 &&
          UseFlip==true &&
          FlipLifeBars==400 &&
          MinScoreShow==35 &&
          WDepart==40.0 &&
          WBase==20.0 &&
          WFresh==20.0 &&
          WReversal==10.0 &&
          WMtf==10.0 &&
          WickRatioMin==0.50 &&
          MinDisplacementATR==0.25 &&
          HtfTrendMAPeriod==50 &&
          MaxHtfEmaDistanceATR==1.75 &&
          SlBufferATR==0.25 &&
          FilterKillzones==true &&
          KillzoneHourOffset==0 &&
          ExcludeWeakKzHours==true &&
          MaxSpreadPrice==0.45 &&
          MaxSlPips==200.0 &&
          MinSlPips==20.0 &&
          UseHtfTrendFilter==true &&
          UseReferenceLevels==true &&
          UseLtfConfirm==true &&
          LtfBarsScan==300 && HtfPeriod==PERIOD_H1 && LtfPeriod==PERIOD_M5 &&
          SweepLevelMode==SWEEP_PROXIMAL && InpSlMode==SL_STRUCTURAL_SWING && !InpUseAutoBE &&
          InpEntryMode==ENTRY_MARKET_CONFIRM && InpTpMode==TP_MODE_SCALP && InpTp1RR==.5 && MinRR==.5 &&
          (InpLabSlippageTicks==0 || InpLabSlippageTicks==1 || InpLabSlippageTicks==5) &&
          (!InpLabBody50 || (InpLabPolicy==CHT_T15 && InpLabRoom)) &&
          (!InpLabRoom || InpLabPolicy==CHT_T05 || InpLabPolicy==CHT_T15) &&
          InpLabPolicy==CHT_T05 && !InpLabRoom && !InpLabBody50;
}

int OnInit()
{
   if(!CHTLockedPreset()){Print("Lab 0.2 FRESH requires the locked research preset; unsupported config");return INIT_PARAMETERS_INCORRECT;}

   if(MaxSpreadPrice <= 0.0)
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

   ENUM_TIMEFRAMES htf = (HtfPeriod == PERIOD_CURRENT) ? Period() : HtfPeriod;
   g_htfAtrHandle = iATR(_Symbol, htf, AtrLen);
   if(g_htfAtrHandle == INVALID_HANDLE)
   {
      Print("Đức Trí Cản Hỗ Trợ: Lỗi tạo handle iATR khung lớn HTF!");
      if(MaxHtfEmaDistanceATR > 0.0)
         return INIT_FAILED;
   }

   g_htfMaHandle = iMA(_Symbol, htf, HtfTrendMAPeriod, 0, MODE_EMA, PRICE_CLOSE);
   if(g_htfMaHandle == INVALID_HANDLE && (UseHtfTrendFilter || MaxHtfEmaDistanceATR > 0.0))
   {
      Print("Đức Trí Cản Hỗ Trợ Scalp: Lỗi tạo handle EMA xu hướng HTF!");
      return INIT_FAILED;
   }

   ENUM_TIMEFRAMES ltf = (LtfPeriod == PERIOD_CURRENT) ? Period() : LtfPeriod;
   g_ltfAtrHandle = iATR(_Symbol, ltf, AtrLen);
   if(g_ltfAtrHandle == INVALID_HANDLE)
   {
      Print("Đức Trí Cản Hỗ Trợ: Lỗi tạo handle iATR khung nhỏ LTF!");
   }

   ArrayResize(g_events, 0);
   ZeroMemory(g_lastSignal);
   g_lastSignalSeenTime = 0;
   g_lastSignalSeenZone = -1;
   g_lastSignalSeenBuy  = false;
   g_confirmState = STATE_IDLE;

   // The lab never reads/sends Telegram credentials or sends notifications.
   CHTNativeInit();
   Print("Can ho tro scalp LAB 0.2 FRESH: original canvas; H1 sweep core; indicator only");
   return INIT_SUCCEEDED;
}

//+------------------------------------------------------------------+
//| Hủy chỉ báo & Thu dọn đồ họa                                     |
//+------------------------------------------------------------------+
void OnDeinit(const int reason)
{
   CHTNativeSave();
   if(g_atrHandle != INVALID_HANDLE)
      IndicatorRelease(g_atrHandle);
   if(g_htfAtrHandle != INVALID_HANDLE)
      IndicatorRelease(g_htfAtrHandle);
   if(g_ltfAtrHandle != INVALID_HANDLE)
      IndicatorRelease(g_ltfAtrHandle);
   if(g_htfMaHandle != INVALID_HANDLE)
      IndicatorRelease(g_htfMaHandle);

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
   static bool first=true;
   if(first){MqlTick tick;bool ready=SymbolInfoTick(_Symbol,tick);Print("Lab first calculate: bars=",rates_total," chart=",ChartID()," quote=",ready," bid=",tick.bid);first=false;}
   if(rates_total<40)return 0;
   CHTNativeCalculate();
   return rates_total;
}

//+------------------------------------------------------------------+
//| Quét vùng cản vĩ mô Khung Lớn HTF (Mặc định H1)                  |
//+------------------------------------------------------------------+
void RefreshReferenceLevels()
{
   MqlRates d1[];
   ArraySetAsSeries(d1,true);
   int copied=CopyRates(_Symbol,PERIOD_D1,1,2,d1);
   if(copied<1 || d1[0].time<=0 || d1[0].high<=d1[0].low)
      return;
   g_previousDayTime=d1[0].time;
   g_previousDayHigh=d1[0].high;
   g_previousDayLow=d1[0].low;
}

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

void ScanHtfMacroZones()
{
   MqlTick tick;if(SymbolInfoTick(_Symbol,tick))CHTNativeZones(tick.time);
}

//+------------------------------------------------------------------+
//| Vẽ cản lên đồ thị - Màu Pastel Dịu Mắt, Nhãn Tinh Tế             |
//+------------------------------------------------------------------+
void DrawChartZones()
{
   ObjectsDeleteAll(0, g_prefix + "Z_");

   datetime extendTime = iTime(_Symbol, PERIOD_CURRENT, 0) + (PeriodSeconds() * ExtendBars);
   double curPrice = SymbolInfoDouble(_Symbol, SYMBOL_BID);
   int drawnDemand = 0, drawnSupply = 0;

   ENUM_TIMEFRAMES scanTf = (HtfPeriod == PERIOD_CURRENT) ? Period() : HtfPeriod;
   string htfTag = EnumToString(scanTf);
   StringReplace(htfTag, "PERIOD_", "");

   for(int i = ArraySize(g_zones) - 1; i >= 0; i--)
   {
       if(g_zones[i].isBroken || g_zones[i].score < MinScoreShow ||
          g_zones[i].testCount >= MaxTests || g_zones[i].ageBars > MaxAgeBars)
         continue;

      double p1 = g_zones[i].distal;
      double p2 = g_zones[i].proximal;
      double zMax = MathMax(p1, p2);
      double zMin = MathMin(p1, p2);

      // Đảm bảo cản cung nằm TRÊN giá (hoặc đang test) và cản cầu nằm DƯỚI giá (hoặc đang test)
      if(g_zones[i].isSupply && zMax < curPrice - 20 * _Point)
         continue;
      if(!g_zones[i].isSupply && zMin > curPrice + 20 * _Point)
         continue;

      if(g_zones[i].isSupply && drawnSupply >= MaxZones) continue;
      if(!g_zones[i].isSupply && drawnDemand >= MaxZones) continue;

      string objName = StringFormat("%sZ_%d", g_prefix, g_zones[i].id);
      datetime t1 = g_zones[i].timeStart;

      // Cản chưa bị phá và đang được giá tiếp cận/chạm test thì BẮT BUỘC kéo dài hộp đến nến hiện tại
       datetime t2 = extendTime;

      color boxClr, lineClr;
      if(g_zones[i].isSupply)
      {
         if(g_zones[i].isFlip)
         {
            boxClr  = C'80,32,58';   // Flip Supply: Tím mận rõ nét
            lineClr = C'244,114,182'; // Hồng tím pastel
         }
         else if(g_zones[i].isFresh)
         {
            boxClr  = C'85,28,34';   // Fresh Supply: Đỏ mận tươi
            lineClr = C'248,113,113'; // Đỏ cam san hô pastel
         }
         else
         {
            boxClr  = C'65,22,28';   // Tested Supply: Đỏ trầm rõ ràng
            lineClr = C'220,38,38';
         }
      }
      else
      {
         if(g_zones[i].isFlip)
         {
            boxClr  = C'28,58,85';   // Flip Demand: Lam khói rõ nét
            lineClr = C'96,165,250';  // Xanh lam pastel
         }
         else if(g_zones[i].isFresh)
         {
            boxClr  = C'20,68,48';   // Fresh Demand: Xanh lục bảo rõ nét
            lineClr = C'52,211,153';  // Xanh ngọc mint pastel
         }
         else
         {
            boxClr  = C'18,48,34';   // Tested Demand: Xanh rêu tươi
            lineClr = C'16,140,90';
         }
      }

      if(ObjectFind(0, objName) < 0)
      {
         ObjectCreate(0, objName, OBJ_RECTANGLE, 0, t1, p1, t2, p2);
      }
      else
      {
         ObjectSetInteger(0, objName, OBJPROP_TIME, 0, t1);
         ObjectSetDouble(0, objName, OBJPROP_PRICE, 0, p1);
         ObjectSetInteger(0, objName, OBJPROP_TIME, 1, t2);
         ObjectSetDouble(0, objName, OBJPROP_PRICE, 1, p2);
      }
      ObjectSetInteger(0, objName, OBJPROP_COLOR, boxClr);
      ObjectSetInteger(0, objName, OBJPROP_STYLE, STYLE_SOLID);
      ObjectSetInteger(0, objName, OBJPROP_WIDTH, 1);
      ObjectSetInteger(0, objName, OBJPROP_FILL, true);
      ObjectSetInteger(0, objName, OBJPROP_BACK, true);

      if(ShowLabels)
      {
         string lblName = objName + "L";
         string typeStr = EnumToString(g_zones[i].type);
         StringReplace(typeStr, "ZONE_", "");
         string text = StringFormat(" %s %d %s [%s]",
                                    typeStr,
                                    g_zones[i].score,
                                    g_zones[i].isFresh ? "FRESH" : "TEST",
                                    htfTag);

         if(ObjectFind(0, lblName) < 0)
         {
            ObjectCreate(0, lblName, OBJ_TEXT, 0, t2, p2);
         }
         else
         {
            ObjectSetInteger(0, lblName, OBJPROP_TIME, 0, t2);
            ObjectSetDouble(0, lblName, OBJPROP_PRICE, 0, p2);
         }
         ObjectSetString(0, lblName, OBJPROP_TEXT, text);
         ObjectSetString(0, lblName, OBJPROP_FONT, "Segoe UI Semibold");
         ObjectSetInteger(0, lblName, OBJPROP_FONTSIZE, LabelFont);
         ObjectSetInteger(0, lblName, OBJPROP_COLOR, lineClr);
         ObjectSetInteger(0, lblName, OBJPROP_ANCHOR, ANCHOR_LEFT_LOWER);
      }

      if(g_zones[i].isSupply) drawnSupply++; else drawnDemand++;
   }

   ChartRedraw(0);
}

//+------------------------------------------------------------------+
//| Kiểm tra khung giờ Killzones (London & New York)                 |
//+------------------------------------------------------------------+
bool IsInKillzone(datetime barTime)
{
   if(!FilterKillzones)
      return true; // Chế độ 24/5 linh hoạt

   MqlDateTime dt;
   TimeToStruct(barTime, dt);
   int h = dt.hour + KillzoneHourOffset;
   while(h < 0) h += 24;
   while(h >= 24) h -= 24;

   // London Killzone: 08:00 - 12:00 broker | New York Killzone: 13:00 - 17:00 broker
   bool isLondon = (h >= 8 && h <= 12);
   bool isNY     = (h >= 13 && h <= 17);
   if(ExcludeWeakKzHours && (h == 12 || h == 14))
      return false;
   return (isLondon || isNY);
}

//+------------------------------------------------------------------+
//| Quét cấu trúc vi mô LTF (M5) & Xác nhận Điểm Vào Lệnh (CHoCH)     |
//| 100% NON-REPAINTING: Chỉ chốt tín hiệu trên nến đã ĐÓNG CỬA [1]  |
//+------------------------------------------------------------------+
void DetectLtfConfirmation(bool isFirstRun = false)
{
   // Replaced by raw candidate adapter. It cannot mutate plan lifecycle.
}

//+------------------------------------------------------------------+
//| Quản lý vị thế lệnh đang mở và tự động dời Auto Break-Even (BE)  |
//+------------------------------------------------------------------+
void ManageActiveSignal(double curPrice)
{
   // CHTQuote is the sole lifecycle owner. Legacy double-close path retired.
}

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
   ObjectSetString(0, objEntry, OBJPROP_TOOLTIP, StringFormat("Entry (%s): %.*f", (g_chtPlan.state==CHT_FILLED?"Fill":"Requested"), _Digits, drawEntry));

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

   if(sig.tp1<=0 && sig.tp2<=0)
   {ObjectDelete(0,g_prefix+"PLAN_TP1");ObjectDelete(0,g_prefix+"PLAN_TP2");ChartRedraw(0);return;}
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
void DrawSignalArrow(bool isBuy, datetime t, double p, double atr)
{
   if(!ShowArrows) return;

   string arrowName = StringFormat("%sSIG_%s_%s", g_prefix, isBuy ? "BUY" : "SELL", IntegerToString((long)t));
   string labelName = StringFormat("%sLBL_%s_%s", g_prefix, isBuy ? "BUY" : "SELL", IntegerToString((long)t));
   color  sigClr    = isBuy ? C'52,211,153' : C'248,113,113';

   double arrowPrice = isBuy ? (p - 0.25 * atr) : (p + 0.25 * atr);
   double labelPrice = isBuy ? (p - 0.75 * atr) : (p + 0.75 * atr);

   if(ObjectFind(0, arrowName) < 0)
   {
      ENUM_OBJECT objType = isBuy ? OBJ_ARROW_BUY : OBJ_ARROW_SELL;
      if(ObjectCreate(0, arrowName, objType, 0, t, arrowPrice))
      {
         ObjectSetInteger(0, arrowName, OBJPROP_COLOR, sigClr);
         ObjectSetInteger(0, arrowName, OBJPROP_WIDTH, ArrowSize);
         ObjectSetInteger(0, arrowName, OBJPROP_BACK, false);
      }
   }

   if(ObjectFind(0, labelName) < 0)
   {
      if(ObjectCreate(0, labelName, OBJ_TEXT, 0, t, labelPrice))
      {
         ObjectSetString(0, labelName, OBJPROP_TEXT, isBuy ? " BUY CHoCH" : " SELL CHoCH");
         ObjectSetString(0, labelName, OBJPROP_FONT, "Segoe UI Semibold");
         ObjectSetInteger(0, labelName, OBJPROP_FONTSIZE, 8);
         ObjectSetInteger(0, labelName, OBJPROP_COLOR, sigClr);
         ObjectSetInteger(0, labelName, OBJPROP_ANCHOR, isBuy ? ANCHOR_UPPER : ANCHOR_LOWER);
      }
   }

   ChartRedraw(0);
}

//+------------------------------------------------------------------+
//| Gửi Cảnh Báo Popup, Âm Thanh, Push Notification & Telegram       |
//+------------------------------------------------------------------+
void SendSignalAlert(const SConfirmSignal &sig)
{
   return; // lab events are local only
}

//+------------------------------------------------------------------+
//| Chuyển tiếp tin nhắn Telegram tới companion Bridge EA            |
//| (Hỗ trợ 0ms OnChartEvent + Shared Queue FILE_COMMON)             |
//+------------------------------------------------------------------+
bool DispatchTelegram(string message, string token = "", string chatId = "")
{
   return false; // no external messaging from this lab
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
                               InpBeTriggerPips, InpBeTriggerPips * GetPipSize(), InpBeTriggerATR);
      else if(InpBeTriggerATR > 0)
         beInfo = StringFormat("🛡 <b>Cơ chế Auto Break-Even:</b> Dời SL về BE khi xanh >= %.1f ATR\n", InpBeTriggerATR);
      else
         beInfo = StringFormat("🛡 <b>Cơ chế Auto Break-Even:</b> Dời SL về BE khi xanh >= +%.0f pips (+%.1f$)\n",
                               InpBeTriggerPips, InpBeTriggerPips * GetPipSize());
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
   int posY = DashY;
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
   string titleStr = (g_lang == LANG_EN ? "DUC TRI · SMC MTF PRO SCALP LAB 0.2 FRESH" : "ĐỨC TRÍ · CẢN & HỖ TRỢ PRO SCALP LAB 0.2 FRESH");
   g_canvas.TextOut(16, 12, titleStr, ColorToARGB(C'255,255,255', 255));

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
      if(CopyBuffer(g_atrHandle, 0, 0, 1, atrs) > 0) atrVal = atrs[0];
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
            g_canvas.FillRectangle(22, curRkY - (int)(3 * s), width - 22, curRkY + (int)(22 * s), ColorToARGB(C'26,52,50', 255));
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
            g_canvas.FillRectangle(22, curRkY - (int)(3 * s), width - 22, curRkY + (int)(22 * s), ColorToARGB(C'53,39,45', 255));
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
         string beTargetStr = (InpBeTriggerATR > 0) ? StringFormat("BE: %.1fATR", InpBeTriggerATR) : StringFormat("BE: +%.0fp", InpBeTriggerPips);
         statusStr = (g_lang == LANG_EN ? StringFormat("RUNNING (Max: +%.1fp / %s)", g_lastSignal.maxMfePips, beTargetStr)
                                        : StringFormat("ĐANG CHẠY (Max: +%.1fp / %s)", g_lastSignal.maxMfePips, beTargetStr));
         statusClr = C'250,204,21'; // Yellow
      }
      statusStr=CHTNativeStatus();
      g_canvas.TextOut(planValX, curPlanY, statusStr, ColorToARGB(statusClr, 255));
      curPlanY += planPitch;

      // Entry Market & Limit
      g_canvas.TextOut(28, curPlanY, (g_lang == LANG_EN ? "Fill / Requested:" : "Khớp / Dự kiến:"), ColorToARGB(C'203,213,225', 255));
      string eslStr = StringFormat("%.*f / %.*f", _Digits, g_lastSignal.entry, _Digits, g_chtPlan.requested);
      g_canvas.TextOut(planValX, curPlanY, eslStr, ColorToARGB(C'255,255,255', 255));
      curPlanY += planPitch;

      // Stop Loss & BE
      g_canvas.TextOut(28, curPlanY, (g_lang == LANG_EN ? "SL current / initial:" : "SL hiện tại / ban đầu:"), ColorToARGB(C'203,213,225', 255));
      string slStr = StringFormat("%.*f / %.*f | ", _Digits, g_lastSignal.sl, _Digits, g_lastSignal.initialSl)+(g_chtPlan.state==CHT_PENDING?"R0 PENDING":StringFormat("R0 %.2f",g_chtPlan.risk));
      g_canvas.TextOut(planValX, curPlanY, slStr, ColorToARGB(g_lastSignal.isBeActive ? C'56,189,248' : C'248,113,113', 255));
      curPlanY += planPitch;

      // TP1 & TP2
      g_canvas.TextOut(28, curPlanY, (g_lang == LANG_EN ? "TP1 / TP2 Targets:" : "Mục tiêu TP1 / TP2:"), ColorToARGB(C'203,213,225', 255));
      string tpStr = g_chtPlan.policy==CHT_TS ? "STRUCTURE TRAIL / NO FIXED TP" : StringFormat("%.*f (%.2fR)",_Digits,g_lastSignal.tp1,g_lastSignal.rr1);
      g_canvas.TextOut(planValX, curPlanY, tpStr, ColorToARGB(C'52,211,153', 255));
      curPlanY += planPitch;

      // POI Zone
      g_canvas.TextOut(28, curPlanY, (g_lang == LANG_EN ? "POI Trigger Zone:" : "Cản kích hoạt / Râu:"), ColorToARGB(C'203,213,225', 255));
      string poiStr = StringFormat("%s %d pts | Râu: %.*f", g_lastSignal.zoneType, g_lastSignal.zoneScore, _Digits, g_lastSignal.sweepPrice);
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

      g_canvas.TextOut(28,curPlanY,CHTNativeStatus(),ColorToARGB(C'250,204,21',255));
      curPlanY+=planPitch;
      g_canvas.TextOut(28,curPlanY,"H1 level -> sweep -> closed M5 confirmation",ColorToARGB(C'148,163,184',255));
      curPlanY+=planPitch;
      g_canvas.TextOut(28, curPlanY, (g_lang == LANG_EN ? "Stats (Created/Broken/Flip):" : "Thống kê (Tạo/Phá/Chuyển):"), ColorToARGB(C'203,213,225', 255));
      string statStr = StringFormat("%d (%dCầu %dCung) / %d / %d", g_statCreated, g_statDemand, g_statSupply, g_statBroken, g_statFlipped);
      g_canvas.TextOut(planValX, curPlanY, statStr, ColorToARGB(C'255,255,255', 255));
      curPlanY += planPitch;

      g_canvas.TextOut(28, curPlanY, (g_lang == LANG_EN ? "Killzones Filter:" : "Bộ lọc giờ vàng KZ:"), ColorToARGB(C'203,213,225', 255));
      string kzStr;
      if(!FilterKillzones)
         kzStr = (g_lang == LANG_EN ? "24/5 ALL SESSIONS" : "24/5 TOÀN PHIÊN");
      else if(ExcludeWeakKzHours)
         kzStr = (g_lang == LANG_EN ? "ACTIVE (08-11/13/15-17)" : "BẬT (08-11/13/15-17)");
      else
         kzStr = (g_lang == LANG_EN ? "ACTIVE (London/NY)" : "BẬT (London/NY)");
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
   if(id == CHARTEVENT_CLICK)
   {
      int clickX = (int)lparam;
      int clickY = (int)dparam;

      int width  = (int)(460 * DashScale);
      int posX = DashX;
      int posY = DashY;
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
         Alert(StringFormat("Đức Trí Cản Hỗ Trợ Pro SCALP LAB 0.2 FRESH [closed-bar risk/state fixes]\nTác giả: %s\nHỗ trợ Telegram: %s", AboutAuthor, AboutSupport));
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
