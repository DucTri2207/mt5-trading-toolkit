#ifndef CHT_V4_INPUTS
#define CHT_V4_INPUTS
#ifdef CHT_V4_NATIVE_FIXTURE
#define V4_INPUT
#else
#define V4_INPUT input
#endif
#ifndef CHT_V4_NATIVE_FIXTURE
input group "=== 1. NHẬN DIỆN VÙNG CẢN (ZONE DETECTION) ==="
#endif
V4_INPUT int             BaseMaxBars     = 5;           // Base tối đa (nến) / max base bars (1-5 nến)
V4_INPUT double          BaseBarATR      = 0.8;         // Mỗi nến base: biên độ <= x ATR
V4_INPUT double          BaseTotalATR    = 2.0;         // Cả cụm base: biên độ <= x ATR
V4_INPUT double          DepartATR       = 1.8;         // Cú bung đà >= x ATR (từ mép base)
V4_INPUT int             DepartBars      = 4;           // Bung đà trong tối đa N nến
V4_INPUT int             LegInBars       = 15;          // Quét leg-in (R/D) trong N nến trước base
V4_INPUT int             AtrLen          = 14;          // Chu kỳ ATR
V4_INPUT int             MaxHistory      = 3000;        // Quét N nến lịch sử gần nhất

#ifndef CHT_V4_NATIVE_FIXTURE
input group "=== 2. QUẢN LÝ VÙNG CẢN (ZONE MANAGEMENT) ==="
#endif
V4_INPUT int             MaxTests        = 4;           // Bỏ vùng sau N lần test (Mặc định 4)
V4_INPUT int             MaxAgeBars      = 1200;        // Bỏ vùng cũ hơn N nến (1200 nến H1 ~ 50 ngày)
V4_INPUT bool            UseFlip         = true;        // Vùng bị thủng -> flip đảo chiều vai trò
V4_INPUT int             FlipLifeBars    = 400;         // Vùng flip tồn tại tối đa N nến
V4_INPUT int             MaxZones        = 2;           // Vẽ tối đa N vùng mỗi phía (Mặc định 2 vùng gần nhất)
V4_INPUT int             MinScoreShow    = 35;          // Chỉ vẽ vùng có điểm số >= x

#ifndef CHT_V4_NATIVE_FIXTURE
input group "=== 3. HỆ THỐNG CHẤM ĐIỂM (SCORING) ==="
#endif
V4_INPUT double          WDepart         = 40.0;        // Điểm tối đa cho lực bứt phá (Departure)
V4_INPUT double          WBase           = 20.0;        // Điểm tối đa cho base chặt chẽ
V4_INPUT double          WFresh          = 20.0;        // Điểm cho vùng còn mới (Freshness)
V4_INPUT double          WReversal       = 10.0;        // Điểm cộng cho mô hình đảo chiều (DBR/RBD)
V4_INPUT double          WMtf            = 10.0;        // Điểm cộng khi trùng cản khung lớn (MTF Overlap)

#ifndef CHT_V4_NATIVE_FIXTURE
input group "=== 4. ĐA KHUNG THỜI GIAN & XÁC NHẬN (MTF CONFIRMATION) ==="
#endif
V4_INPUT ENUM_TIMEFRAMES HtfPeriod       = PERIOD_H1;   // Khung lớn xác định vùng Cản POI chính (Mặc định H1)
V4_INPUT ENUM_TIMEFRAMES LtfPeriod       = PERIOD_M5;   // Khung nhỏ tìm điểm kích hoạt vào lệnh (Mặc định M5)
V4_INPUT bool            UseLtfConfirm   = true;        // Bật quét tín hiệu xác nhận khung nhỏ
V4_INPUT bool            ShowArrows      = true;        // Vẽ mũi tên tín hiệu trên biểu đồ
V4_INPUT int             ArrowSize       = 2;           // Kích thước mũi tên tín hiệu
V4_INPUT double          WickRatioMin    = 0.35;        // Tỷ lệ râu quét thanh khoản tối thiểu (0.35 = 35%)
V4_INPUT bool            FilterKillzones = false;       // Lọc theo giờ vàng London/New York (Tắt = 24/5)
V4_INPUT int             LtfBarsScan     = 300;         // Số nến khung nhỏ phân tích điểm kích hoạt
V4_INPUT bool            UseReferenceLevels = true;     // Dùng PDH/PDL đã đóng làm cản tham chiếu
V4_INPUT bool            ShowReferenceLevels = true;    // Vẽ PDH/PDL trên chart
V4_INPUT double          MaxSpreadPrice   = 0.45;       // XAU: Ask-Bid tối đa (USD/oz)

#ifndef CHT_V4_NATIVE_FIXTURE
input group "=== 5. KẾ HOẠCH VÀO LỆNH (TRADE PLAN) ==="
#endif
V4_INPUT ENUM_SL_MODE    InpSlMode        = SL_STRUCTURAL_SWING; // Phương pháp đặt Stop Loss (SMC Swing vs Sweep Distal)
V4_INPUT double          SlBufferATR      = 0.3;         // Đệm Stop Loss ngoài râu nến (x ATR, Mặc định 0.3)
V4_INPUT double          MaxSlPips        = 100.0;       // Giới hạn Stop Loss tối đa (pips, 100p = 10.0$ Vàng)
V4_INPUT double          MinSlPips        = 25.0;        // Giới hạn Stop Loss tối thiểu (pips, 25p = 2.5$ Vàng)
V4_INPUT ENUM_ENTRY_MODE InpEntryMode     = ENTRY_DUAL_RECOMMEND; // Cơ chế vào lệnh (Market / Limit 50% / Dual)
V4_INPUT ENUM_TP_MODE    InpTpMode        = TP_MODE_HYBRID; // Phương pháp tính Chốt lời TP1 & TP2
V4_INPUT double          InpTp1RR         = 1.5;         // Tỷ lệ R:R cho TP1 (khi dùng chế độ R:R)
V4_INPUT double          InpTp2RR         = 2.0;         // Tỷ lệ R:R cho TP2 (khi dùng chế độ R:R)
V4_INPUT double          InpTp1Pips       = 60.0;        // Số pips cho TP1 (60 pips = 6.0$ Vàng)
V4_INPUT double          InpTp2Pips       = 120.0;       // Số pips cho TP2 (120 pips = 12.0$ Vàng)
V4_INPUT double          MinRR            = 1.5;         // Tỷ lệ R:R tối thiểu để đề xuất kế hoạch

#ifndef CHT_V4_NATIVE_FIXTURE
input group "=== 5B. BẢO VỆ VỊ THẾ AUTO BREAK-EVEN (BE) ==="
#endif
V4_INPUT bool            InpUseAutoBE     = true;        // Bật cơ chế Auto Break-Even (Dời SL hòa vốn)
V4_INPUT double          InpBeTriggerPips = 60.0;        // Kích hoạt dời BE khi giá chạy xanh >= x pips (60p = 6.0$)
V4_INPUT double          InpBeTriggerATR  = 0.0;         // Kích hoạt dời BE khi giá chạy xanh >= x ATR (0.0 = chỉ theo pips)
V4_INPUT double          InpBeOffsetPips  = 1.0;         // Đệm phí khi dời về BE (Entry + x pips)
V4_INPUT bool            ShowTradeLines   = true;        // Vẽ đường Entry, SL, BE, TP1, TP2 trên Chart
V4_INPUT bool            AlertBeTriggered = true;        // Báo động & Telegram khi lệnh chạm ngưỡng dời BE

#ifndef CHT_V4_NATIVE_FIXTURE
input group "=== 6. GIAO DIỆN CHART (APPEARANCE) ==="
#endif
V4_INPUT ENUM_THEME      Theme           = THEME_DARK;  // Giao diện màu nền chart
V4_INPUT bool            RestoreTheme    = true;        // Trả lại màu cũ khi gỡ chỉ báo
V4_INPUT bool            ShowLabels      = true;        // Hiển thị nhãn tên vùng & điểm số
V4_INPUT int             LabelFont       = 8;           // Cỡ chữ nhãn vùng
V4_INPUT int             ExtendBars      = 25;          // Kéo dài vùng cản về bên phải (nến)

#ifndef CHT_V4_NATIVE_FIXTURE
input group "=== 7. BẢNG ĐIỀU KHIỂN (DASHBOARD) ==="
#endif
V4_INPUT int InpHistoryDays = 90; // Causal M5 replay, calendar days
V4_INPUT bool InpShowExpiredZones = true;
V4_INPUT bool InpShowStatsPanel = false;
V4_INPUT bool InpDashCollapsed = true;
V4_INPUT bool InpDashBottom = false; // Together with DashRight selects four corners
V4_INPUT bool            ShowDash        = true;        // Hiển thị bảng Dashboard
V4_INPUT bool            DashRight       = false;       // Neo góc phải (false = neo góc trái)
V4_INPUT int             DashX           = 20;          // Cách mép ngang (px)
V4_INPUT int             DashY           = 30;          // Cách mép trên (px)
V4_INPUT double          DashScale       = 1.2;         // Tỷ lệ kích thước Panel (1.0 - 2.0, Mặc định 1.2 cho màn hình HD/4K)
V4_INPUT double          DashFontAdj     = 1.4;         // Tinh chỉnh cỡ chữ (1.0 - 2.0, Mặc định 1.4 rõ nét trên màn hình High-DPI)
V4_INPUT ENUM_LANG       DefaultLang     = LANG_VI;     // Ngôn ngữ mặc định (VI/EN)

#ifndef CHT_V4_NATIVE_FIXTURE
input group "=== 8. CẢNH BÁO (ALERTS) ==="
#endif
V4_INPUT bool            AlertPopup      = true;        // Bật cửa sổ Alert Popup
V4_INPUT bool            AlertPush       = true;        // Báo qua Push Notification điện thoại (App MT5)
V4_INPUT bool            AlertSoundOn    = true;        // Phát âm thanh
V4_INPUT string          AlertSoundFile  = "alert.wav"; // Tên file âm thanh
V4_INPUT bool            AlertNewZone    = true;        // Báo khi xuất hiện vùng cản mới
V4_INPUT bool            AlertEnter      = true;        // Báo khi giá tiến vào vùng cản
V4_INPUT bool            AlertBreak      = true;        // Báo khi vùng cản bị phá thủng / flip
V4_INPUT bool            AlertConfirm    = true;        // Báo khi nến M5 xác nhận CHoCH vào lệnh
V4_INPUT int             AlertMinScore   = 50;          // Chỉ báo cho các vùng có điểm >= x

#ifndef CHT_V4_NATIVE_FIXTURE
input group "=== 9. THÔNG BÁO TELEGRAM (PURE MQL5 - NO DLL) ==="
#endif
V4_INPUT bool            TgEnable           = true;     // Bật gửi Telegram (qua companion Bridge EA)
V4_INPUT string          TgToken            = "";       // Telegram Bot Token (từ @BotFather)
V4_INPUT string          TgChatID           = "";       // Telegram Chat ID (từ @userinfobot)
V4_INPUT bool            TgAlertSignalsOnly = true;     // Chỉ báo KÈO CHoCH xác nhận (Tắt spam chạm cản)

#ifndef CHT_V4_NATIVE_FIXTURE
input group "=== 10. THÔNG TIN (ABOUT) ==="
#endif
V4_INPUT string          AboutAuthor     = "Đức Trí";
V4_INPUT string          AboutSupport    = "https://t.me/botfather6868";

V4_INPUT int InpPriceScaleMode = 1; // 0: v4.0 distances; 1: closed D1 close / 2000 for XAU
V4_INPUT bool InpCompatV301 = false; // true: literal v3.01 core comparison; causal guards disabled
V4_INPUT string InpV4LedgerFolder = "CanHoTroV4";
// M2 commission is round trip per lot in account currency.
V4_INPUT bool InpScorecard = true;
V4_INPUT ENUM_V4_EXIT InpScoreExit = EXIT_1R;
V4_INPUT double InpHistSpreadPrice = 0.30;
V4_INPUT double InpCommissionPerLot = 7.0;
V4_INPUT double InpSlippagePoints = 1.0;
V4_INPUT double InpRiskPercent = 0.5;
V4_INPUT double InpCostWarningPercent = 10.0;
V4_INPUT double InpInitialCapital = 0; // 0 = unknown loss-limit baseline.
V4_INPUT double InpDailyLossPercent = 5.0;
V4_INPUT double InpTotalLossPercent = 10.0;
V4_INPUT int InpResetMinuteServer = 0; // Explicit server reset; user maps CE(S)T.
V4_INPUT bool InpMuteAtDailyLimit = false;
V4_INPUT int InpJournalMatchMinutes = 30;
V4_INPUT datetime InpJournalFrom = D'2021.01.01';
#undef V4_INPUT
#endif
