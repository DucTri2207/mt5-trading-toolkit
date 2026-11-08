#ifndef CHT_V4_TYPES
#define CHT_V4_TYPES
enum ENUM_V4_EXIT { EXIT_1R=0, EXIT_TRAIL_1R=1 };
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
   TP_MODE_PIPS   = 2  // Thuần Pips cố định (+60 pips & +120 pips)
};


struct SZone
{
   long              id;
   ENUM_ZONE_TYPE    type;          // RBR, DBR, DBD, RBD, FLIP
   bool              isSupply;      // true: Supply, false: Demand
   datetime          timeFormed;
   datetime          timeKnown;
   datetime          timeInvalid;
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
   string            signal_id;
   long              source_zone_id;
   datetime          confirm_bar_open;
   datetime          signal_known_time;
   datetime          publish_time;
   datetime          order_place_time;
   datetime          fill_time;
   datetime          exit_time;
   datetime          sweep_time;
   datetime          zone_known_time;
   double            source_distal;
   double            source_proximal;
   double            choch_level;
   double            arrow_anchor;
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
   long              zoneId;        // ID vùng cản H1 kích hoạt
   string            zoneType;      // Kiểu cản H1 (RBR, DBR, DBD, RBD, FLIP)
   int               zoneScore;     // Điểm số vùng cản
   bool              isBeActive;    // Trạng thái đã dời SL về Break-Even
   double            bePrice;       // Mức giá dời về BE (+ đệm phí)
   double            maxMfePips;    // MFE lớn nhất đã chạy (tính bằng pips)
   bool              hitTp1;        // Đã chạm TP1
   bool              hitTp2;        // Đã chạm TP2
   double            ltfAtr;        // ATR khung M5 tại thời điểm phát tín hiệu
};


#endif
