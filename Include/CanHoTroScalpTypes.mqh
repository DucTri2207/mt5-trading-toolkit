// Generated from v3.12; run scripts/generate_can_ho_tro_oracle.py.
#ifndef CAN_HO_TRO_SCALP_TYPES
#define CAN_HO_TRO_SCALP_TYPES
#ifndef CHT_EXTERNAL_CONFIG
enum ENUM_ZONE_TYPE
{
   ZONE_RBR  = 0, // RBR (Rally-Base-Rally - Cầu tiếp diễn)
   ZONE_DBR  = 1, // DBR (Drop-Base-Rally - Cầu đảo chiều)
   ZONE_DBD  = 2, // DBD (Drop-Base-Drop - Cung tiếp diễn)
   ZONE_RBD  = 3, // RBD (Rally-Base-Drop - Cung đảo chiều)
   ZONE_FLIP = 4  // FLIP (Vùng đảo vai trò cản)
};

const int BaseMaxBars=5;
const double BaseBarATR=0.8;
const double BaseTotalATR=2.0;
const double DepartATR=1.8;
const int DepartBars=4;
const int LegInBars=15;
const int AtrLen=14;
const int MaxHistory=3000;
const int MaxTests=4;
const int MaxAgeBars=1200;
const bool UseFlip=true;
const int FlipLifeBars=400;
const int MinScoreShow=35;
const double WDepart=40.0;
const double WBase=20.0;
const double WFresh=20.0;
const double WReversal=10.0;
const double WMtf=10.0;
const double WickRatioMin=0.50;
const double MinDisplacementATR=0.25;
const int HtfTrendMAPeriod=50;
const double MaxHtfEmaDistanceATR=1.75;
const double SlBufferATR=0.25;
const bool FilterKillzones=true;
const int KillzoneHourOffset=0;
const bool ExcludeWeakKzHours=true;
const int SweepLevelMode=0; // original default SWEEP_PROXIMAL
const int SWEEP_DISTAL=1;
#endif
struct CHTZone
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
   datetime baseTime,flipOrigin,availableAt;
};


struct CHTCandidate { double v[36]; };
struct CHTContext
{
   double trendClose,trendMa,trendAtr,dayHigh,dayLow;
   datetime trendTime,dayTime;
   int m5Index,h1Count;
};
#define CHT_VERSION "can_ho_tro_scalp_0.1"
#endif
