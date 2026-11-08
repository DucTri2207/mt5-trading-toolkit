import os
import sys

def main():
    mq5_path = r'd:\trading thử lần cuối cuối\duc_tri_can_ho_tro.mq5'
    bak_path = r'd:\trading thử lần cuối cuối\duc_tri_can_ho_tro.mq5.bak'
    
    with open(bak_path, 'r', encoding='utf-8', errors='ignore') as f:
        content = f.read()

    # 1. Update version and description
    content = content.replace(
        '#property version     "3.00"',
        '#property version     "3.20"'
    )
    content = content.replace(
        '#property description "Đức Trí Cản Hỗ Trợ Pro v3.0 - SMC Multi-Timeframe Institutional Engine (Pure MQL5 - No DLL)"',
        '#property description "Đức Trí Cản Hỗ Trợ Pro v3.2 - Master Hỗ Trợ Kháng Cự & Thanh Khoản Thể Chế Đa Tài Sản (Pure MQL5 - No DLL)"'
    )

    # 2. Add ENUM_ASSET_CLASS to Enumerations
    enum_old = """enum ENUM_LANG
{
   LANG_VI = 0, // Tiếng Việt (Mặc định)
   LANG_EN = 1  // English
};"""
    enum_new = """enum ENUM_ASSET_CLASS
{
   ASSET_METALS  = 0, // Vàng, Bạc, Kim loại quý (XAUUSD, GOLD, XAGUSD, SILVER)
   ASSET_FOREX   = 1, // Ngoại hối Majors & Crosses (EURUSD, GBPUSD, USDJPY,...)
   ASSET_INDICES = 2  // Chỉ số chứng khoán Mỹ & Toàn cầu (US30, NAS100, SPX500,...)
};

enum ENUM_LANG
{
   LANG_VI = 0, // Tiếng Việt (Mặc định)
   LANG_EN = 1  // English
};"""
    if enum_old in content:
        content = content.replace(enum_old, enum_new, 1)
    else:
        print("Error: enum_old not found!")
        return 1

    # 3. Update Input Group 2
    inputs_old = """input group "=== 2. QUẢN LÝ VÙNG CẢN (ZONE MANAGEMENT) ==="
input int             MaxTests        = 4;           // Bỏ vùng sau N lần test (Mặc định 4)
input int             MaxAgeBars      = 1200;        // Bỏ vùng cũ hơn N nến (1200 nến H1 ~ 50 ngày)
input bool            UseFlip         = true;        // Vùng bị thủng -> flip đảo chiều vai trò
input int             FlipLifeBars    = 400;         // Vùng flip tồn tại tối đa N nến
input int             MaxZones        = 2;           // Vẽ tối đa N vùng mỗi phía (Mặc định 2 vùng gần nhất)
input int             MinScoreShow    = 35;          // Chỉ vẽ vùng có điểm số >= x"""

    inputs_new = """input group "=== 2. QUẢN LÝ VÙNG CẢN (ZONE MANAGEMENT) ==="
input int             MaxTests        = 4;           // Bỏ vùng sau N lần test (Mặc định 4)
input int             MaxAgeBars      = 1200;        // Bỏ vùng cũ hơn N nến (1200 nến H1 ~ 50 ngày)
input bool            UseFlip         = true;        // Vùng bị thủng -> flip đảo chiều vai trò
input int             FlipLifeBars    = 400;         // Vùng flip tồn tại tối đa N nến
input int             MaxZones        = 2;           // Vẽ tối đa N vùng mỗi phía (Mặc định 2 vùng gần nhất)
input int             MinScoreShow    = 70;          // Chỉ vẽ vùng có điểm số >= x (Chuẩn Thể Chế >= 70)
input bool            UseCompositeOB  = true;        // Thuật toán gộp cản LuxAlgo Composite Order Block
input bool            ShowSessionLiq  = true;        // Tầng 2: Mốc thanh khoản phiên PDH/PDL & Asian Box
input bool            ShowFvg         = true;        // Tầng 3: Fair Value Gap & Consequent Encroachment (CE 50%)"""

    if inputs_old in content:
        content = content.replace(inputs_old, inputs_new, 1)
    else:
        print("Error: inputs_old not found!")
        return 1

    # 4. Update Structs and Global Variables
    structs_old = """struct SZone
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
   double            entry;         // Giá vào lệnh (Close nến xác nhận)
   double            sl;            // Stop loss mỏng (kê chóp râu nến M5 + đệm ATR)
   double            tp1;           // Chốt lời 1 (1:1.5 R:R)
   double            tp2;           // Chốt lời 2 (1:2.0 R:R)
   double            tpMacro;       // Mục tiêu Cản H1 đối diện (Macro Target)
   double            rr1;           // Tỷ lệ R:R của TP1 (1.5)
   double            rr2;           // Tỷ lệ R:R của TP2 (2.0)
   double            rrMacro;       // Tỷ lệ R:R của Cản đối diện
   double            sweepPrice;    // Đáy/đỉnh của râu quét thanh khoản
   int               zoneId;        // ID vùng cản H1 kích hoạt
   string            zoneType;      // Kiểu cản H1 (RBR, DBR, DBD, RBD, FLIP)
   int               zoneScore;     // Điểm số vùng cản
};"""

    structs_new = """struct SZone
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
   bool              isComposite;   // true: Đã gộp từ 2 cản trở lên (LuxAlgo)
   int               mergedCount;   // Số cản đơn lẻ đã hợp nhất
   double            meanThreshold; // MT 50% = (high + low) / 2
};

struct SAssetProfile
{
   ENUM_ASSET_CLASS  assetClass;
   string            className;     // "METALS", "FOREX", "INDICES"
   string            classTag;      // "[METALS]", "[FOREX]", "[INDICES]"
   string            unitName;      // "USD", "pips", "points"
   double            minSlBuffer;   // Đệm SL tối thiểu theo đơn vị giá
   double            pipSize;       // Bước giá 1 pip hoặc point
   int               sessionStartVN;// Giờ mở phiên ưu tiên (VN)
   int               sessionEndVN;  // Giờ đóng phiên ưu tiên (VN)
   string            primeSession;  // Mô tả phiên ưu tiên
};

struct SSessionLiquidity
{
   double            pdh;           // Previous Day High (D1[1])
   double            pdl;           // Previous Day Low (D1[1])
   bool              hasPdhPdl;
   double            asianHigh;     // Đỉnh phiên Á (00:00 - 08:00 GMT)
   double            asianLow;      // Đáy phiên Á (00:00 - 08:00 GMT)
   datetime          asianStart;
   datetime          asianEnd;
   bool              hasAsianRange;
};

struct SFairValueGap
{
   int               id;
   bool              isBisi;        // true: Bullish BISI, false: Bearish SIBI
   double            gapHigh;       // Mép trên FVG
   double            gapLow;        // Mép dưới FVG
   double            consequentEncroachment; // CE 50% = (gapHigh + gapLow) / 2.0
   datetime          barTime;       // Thời gian nến tạo FVG
   datetime          timeEnd;
   bool              isMitigated;   // Đã bị lấp hoàn toàn
};

struct STriggerSignal
{
   string            symbol;
   ENUM_ASSET_CLASS  assetClass;
   string            classTag;
   bool              isBuy;
   double            entryPrice;
   double            stopLoss;
   double            takeProfit1;
   double            takeProfit2;
   double            takeProfitMacro;
   double            riskRewardRatio;
   double            slBufferVal;
   string            slUnitStr;
   string            zoneType;
   int               zoneScore;
   double            sweepPrice;
   datetime          triggerTime;
   string            primeSession;
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
   double            entry;         // Giá vào lệnh (Close nến xác nhận)
   double            sl;            // Stop loss mỏng (kê chóp râu nến M5 + đệm ATR)
   double            tp1;           // Chốt lời 1 (1:1.5 R:R)
   double            tp2;           // Chốt lời 2 (1:2.0 R:R)
   double            tpMacro;       // Mục tiêu Cản H1 đối diện (Macro Target)
   double            rr1;           // Tỷ lệ R:R của TP1 (1.5)
   double            rr2;           // Tỷ lệ R:R của TP2 (2.0)
   double            rrMacro;       // Tỷ lệ R:R của Cản đối diện
   double            sweepPrice;    // Đáy/đỉnh của râu quét thanh khoản
   int               zoneId;        // ID vùng cản H1 kích hoạt
   string            zoneType;      // Kiểu cản H1 (RBR, DBR, DBD, RBD, FLIP)
   int               zoneScore;     // Điểm số vùng cản
   string            poiSource;     // Vùng POI nguồn ("COMPOSITE OB", "PDH SWEEP", "PDL SWEEP", "ASIAN SWEEP", "FVG CE 50%")
   double            slBufferVal;   // Giá trị đệm SL theo đơn vị giá
   string            slUnitStr;     // "USD", "pips", "points"
};"""

    if structs_old in content:
        content = content.replace(structs_old, structs_new, 1)
    else:
        print("Error: structs_old not found!")
        return 1

    # 5. Add Global Variables
    vars_old = """SZone                g_zones[];
SZone                g_htfZones[];
SEventLog            g_events[];"""

    vars_new = """SZone                g_zones[];
SZone                g_htfZones[];
SEventLog            g_events[];

SAssetProfile        g_assetProfile;
SSessionLiquidity    g_sessionLiq;
SFairValueGap        g_fvgs[];"""

    if vars_old in content:
        content = content.replace(vars_old, vars_new, 1)
    else:
        print("Error: vars_old not found!")
        return 1

    # 6. Add Institutional Classes before OnInit()
    classes_code = """//+------------------------------------------------------------------+
//| LỚP 0: AUTO ASSET PROFILER                                       |
//+------------------------------------------------------------------+
class CAssetProfiler
{
public:
   static SAssetProfile GetProfile(string symbol)
   {
      SAssetProfile prof;
      prof.assetClass      = ASSET_FOREX;
      prof.className       = "FOREX";
      prof.classTag        = "[FOREX]";
      prof.unitName        = "pips";
      prof.pipSize         = (_Digits == 5 || _Digits == 3) ? (_Point * 10.0) : ((_Point > 0) ? _Point : 0.0001);
      prof.minSlBuffer     = 12.0 * prof.pipSize;
      prof.sessionStartVN  = 14;
      prof.sessionEndVN    = 18;
      prof.primeSession    = "Phiên London (14:00 - 17:30 VN)";

      string sym = symbol;
      StringToUpper(sym);

      // 1. METALS Check
      if(StringFind(sym, "XAU") >= 0 || StringFind(sym, "GOLD") >= 0 ||
         StringFind(sym, "XAG") >= 0 || StringFind(sym, "SILVER") >= 0 ||
         StringFind(sym, "XPT") >= 0 || StringFind(sym, "XPD") >= 0)
      {
         prof.assetClass      = ASSET_METALS;
         prof.className       = "METALS";
         prof.classTag        = "[METALS]";
         prof.unitName        = "USD";
         prof.minSlBuffer     = 3.5;
         prof.pipSize         = 0.1;
         prof.sessionStartVN  = 19;
         prof.sessionEndVN    = 23;
         prof.primeSession    = "Phiên Tối US (19:30 - 23:00 VN)";
         return prof;
      }

      // 2. INDICES Check - Strict tokens to prevent "USDJPY" matching "DJ"
      bool isUs30 = (StringFind(sym, "US30") >= 0 || StringFind(sym, "DJ30") >= 0 ||
                     StringFind(sym, "DOW") >= 0  || StringFind(sym, "WALLSTREET") >= 0 ||
                     StringFind(sym, "WS30") >= 0);
      bool isTech = (StringFind(sym, "NAS") >= 0 || StringFind(sym, "USTEC") >= 0 ||
                     StringFind(sym, "NDX") >= 0  || StringFind(sym, "SPX") >= 0 ||
                     StringFind(sym, "US500") >= 0|| StringFind(sym, "GER") >= 0 ||
                     StringFind(sym, "DAX") >= 0);

      if(isUs30)
      {
         prof.assetClass      = ASSET_INDICES;
         prof.className       = "INDICES";
         prof.classTag        = "[INDICES]";
         prof.unitName        = "points";
         prof.minSlBuffer     = 35.0;
         prof.pipSize         = (_Point > 0) ? _Point : 1.0;
         prof.sessionStartVN  = 20;
         prof.sessionEndVN    = 23;
         prof.primeSession    = "NY Cash Open (20:30 - 22:30 VN)";
         return prof;
      }

      if(isTech)
      {
         prof.assetClass      = ASSET_INDICES;
         prof.className       = "INDICES";
         prof.classTag        = "[INDICES]";
         prof.unitName        = "points";
         prof.minSlBuffer     = 25.0;
         prof.pipSize         = (_Point > 0) ? _Point : 1.0;
         prof.sessionStartVN  = 20;
         prof.sessionEndVN    = 23;
         prof.primeSession    = "NY Cash Open (20:30 - 22:30 VN)";
         return prof;
      }

      // 3. FOREX (Default)
      prof.minSlBuffer = 12.0 * prof.pipSize;
      return prof;
   }

   static double ComputeDynamicSlBuffer(const SAssetProfile &profile, double ltfAtr, double slBufferAtrMult = 0.5)
   {
      double atrBuffer = slBufferAtrMult * ltfAtr;
      if(profile.assetClass == ASSET_METALS)
      {
         return MathMin(6.0, MathMax(3.5, atrBuffer));
      }
      else if(profile.assetClass == ASSET_FOREX)
      {
         return MathMax(profile.minSlBuffer, atrBuffer);
      }
      else if(profile.assetClass == ASSET_INDICES)
      {
         return MathMax(profile.minSlBuffer, atrBuffer);
      }
      return MathMax(profile.minSlBuffer, atrBuffer);
   }

   static bool IsInOptimalSession(string symbol, datetime barTime, int gmtOffsetSec = 0)
   {
      datetime barGmt = barTime - gmtOffsetSec;
      datetime barVn  = barGmt + 7 * 3600;
      MqlDateTime dt;
      TimeToStruct(barVn, dt);
      int minOfDay = dt.hour * 60 + dt.min;

      SAssetProfile prof = GetProfile(symbol);
      if(prof.assetClass == ASSET_METALS)
      {
         return (minOfDay >= 19 * 60 + 30 && minOfDay <= 23 * 60);
      }
      else if(prof.assetClass == ASSET_FOREX)
      {
         return (minOfDay >= 14 * 60 && minOfDay <= 17 * 60 + 30);
      }
      else if(prof.assetClass == ASSET_INDICES)
      {
         return (minOfDay >= 20 * 60 + 30 && minOfDay <= 22 * 60 + 30);
      }
      return true;
   }
};

//+------------------------------------------------------------------+
//| TẦNG 1: LUXALGO COMPOSITE ORDER BLOCK ENGINE                     |
//+------------------------------------------------------------------+
class COrderBlockEngine
{
public:
   static void MergeCompositeBlocks(SZone &zones[], double htfAtr, int minScoreMerge = 70)
   {
      int total = ArraySize(zones);
      if(total <= 1) return;

      double mergeDist = 0.8 * htfAtr;
      bool merged[];
      ArrayResize(merged, total);
      ArrayInitialize(merged, false);

      SZone compositeList[];
      ArrayResize(compositeList, 0);

      for(int i = 0; i < total; i++)
      {
         if(merged[i] || zones[i].isBroken || zones[i].score < minScoreMerge)
            continue;

         double cHigh = MathMax(zones[i].distal, zones[i].proximal);
         double cLow  = MathMin(zones[i].distal, zones[i].proximal);
         datetime cStart = zones[i].timeStart;
         datetime cEnd   = zones[i].timeEnd;
         bool isSup = zones[i].isSupply;
         int maxScore = zones[i].score;
         int maxTests = zones[i].testCount;
         bool hasFlip = zones[i].isFlip;
         int clusterCount = 1;

         merged[i] = true;

         bool foundMore = true;
         while(foundMore)
         {
            foundMore = false;
            for(int j = 0; j < total; j++)
            {
               if(merged[j] || zones[j].isBroken || zones[j].score < minScoreMerge)
                  continue;
               if(zones[j].isSupply != isSup)
                  continue;

               double zHigh = MathMax(zones[j].distal, zones[j].proximal);
               double zLow  = MathMin(zones[j].distal, zones[j].proximal);

               double gap = 0.0;
               if(zLow > cHigh) gap = zLow - cHigh;
               else if(cLow > zHigh) gap = cLow - zHigh;
               else gap = 0.0;

               if(gap < mergeDist)
               {
                  cHigh = MathMax(cHigh, zHigh);
                  cLow  = MathMin(cLow, zLow);
                  cStart = MathMin(cStart, zones[j].timeStart);
                  cEnd   = MathMax(cEnd, zones[j].timeEnd);
                  if(zones[j].score > maxScore) maxScore = zones[j].score;
                  if(zones[j].testCount > maxTests) maxTests = zones[j].testCount;
                  if(zones[j].isFlip) hasFlip = true;
                  clusterCount++;
                  merged[j] = true;
                  foundMore = true;
               }
            }
         }

         SZone comp;
         comp.id            = ArraySize(compositeList) + 1;
         comp.isSupply      = isSup;
         comp.distal        = isSup ? cHigh : cLow;
         comp.proximal      = isSup ? cLow  : cHigh;
         comp.meanThreshold = (cHigh + cLow) / 2.0;
         comp.timeStart     = cStart;
         comp.timeEnd       = cEnd;
         comp.testCount     = maxTests;
         comp.isFresh       = (maxTests == 0);
         comp.isBroken      = false;
         comp.isFlip        = hasFlip;
         comp.score         = MathMin(100, maxScore + (clusterCount - 1) * 5);
         comp.type          = hasFlip ? ZONE_FLIP : (clusterCount > 1 ? (isSup ? ZONE_DBD : ZONE_DBR) : zones[i].type);
         comp.departAtr     = zones[i].departAtr;
         comp.baseBars      = zones[i].baseBars;
         comp.hasHtfOverlap = zones[i].hasHtfOverlap;
         comp.ageBars       = zones[i].ageBars;
         comp.isComposite   = (clusterCount > 1);
         comp.mergedCount   = clusterCount;

         int sz = ArraySize(compositeList);
         ArrayResize(compositeList, sz + 1);
         compositeList[sz] = comp;
      }

      if(ArraySize(compositeList) > 0)
      {
         ArrayResize(zones, ArraySize(compositeList));
         for(int k = 0; k < ArraySize(compositeList); k++)
            zones[k] = compositeList[k];
      }
   }
};

//+------------------------------------------------------------------+
//| TẦNG 2: SESSION LIQUIDITY ENGINE (PDH / PDL & ASIAN BOX)         |
//+------------------------------------------------------------------+
class CSessionLiquidityEngine
{
public:
   static bool Calculate(string symbol, SSessionLiquidity &outLiq)
   {
      outLiq.pdh = iHigh(symbol, PERIOD_D1, 1);
      outLiq.pdl = iLow(symbol, PERIOD_D1, 1);
      outLiq.hasPdhPdl = (outLiq.pdh > 0 && outLiq.pdl > 0 && outLiq.pdh > outLiq.pdl);

      outLiq.asianHigh = 0.0;
      outLiq.asianLow  = 0.0;
      outLiq.hasAsianRange = false;
      outLiq.asianStart = 0;
      outLiq.asianEnd   = 0;

      int gmtOffsetSec = (int)(TimeCurrent() - TimeGMT());
      datetime todayBroker = iTime(symbol, PERIOD_D1, 0);
      datetime todayGmt = todayBroker - gmtOffsetSec;
      MqlDateTime dt;
      TimeToStruct(todayGmt, dt);
      dt.hour = 0; dt.min = 0; dt.sec = 0;
      datetime gmtMidnight = StructToTime(dt);

      datetime asianStartGmt = gmtMidnight;
      datetime asianEndGmt   = gmtMidnight + 8 * 3600;

      outLiq.asianStart = asianStartGmt + gmtOffsetSec;
      outLiq.asianEnd   = asianEndGmt + gmtOffsetSec;

      MqlRates m5Rates[];
      ArraySetAsSeries(m5Rates, true);
      int copied = CopyRates(symbol, PERIOD_M5, outLiq.asianStart, outLiq.asianEnd, m5Rates);
      if(copied > 0)
      {
         double aHigh = -1.0;
         double aLow  = 9999999.0;
         for(int k = 0; k < copied; k++)
         {
            if(m5Rates[k].high > aHigh) aHigh = m5Rates[k].high;
            if(m5Rates[k].low < aLow)   aLow  = m5Rates[k].low;
         }
         if(aHigh > 0 && aLow < 9999990.0 && aHigh > aLow)
         {
            outLiq.asianHigh = aHigh;
            outLiq.asianLow  = aLow;
            outLiq.hasAsianRange = true;
         }
      }

      return (outLiq.hasPdhPdl);
   }

   static void Draw(string prefix, const SSessionLiquidity &liq, datetime extendTime)
   {
      ObjectsDeleteAll(0, prefix + "LIQ_");

      if(liq.hasPdhPdl)
      {
         datetime tStart = iTime(_Symbol, PERIOD_D1, 0);
         datetime tEnd   = extendTime;

         string pdhObj = prefix + "LIQ_PDH";
         if(ObjectFind(0, pdhObj) < 0)
            ObjectCreate(0, pdhObj, OBJ_TREND, 0, tStart, liq.pdh, tEnd, liq.pdh);
         else
         {
            ObjectSetInteger(0, pdhObj, OBJPROP_TIME, 0, tStart);
            ObjectSetDouble(0, pdhObj, OBJPROP_PRICE, 0, liq.pdh);
            ObjectSetInteger(0, pdhObj, OBJPROP_TIME, 1, tEnd);
            ObjectSetDouble(0, pdhObj, OBJPROP_PRICE, 1, liq.pdh);
         }
         ObjectSetInteger(0, pdhObj, OBJPROP_COLOR, C'245,158,11');
         ObjectSetInteger(0, pdhObj, OBJPROP_STYLE, STYLE_DASH);
         ObjectSetInteger(0, pdhObj, OBJPROP_WIDTH, 1);
         ObjectSetInteger(0, pdhObj, OBJPROP_RAY_RIGHT, false);
         ObjectSetInteger(0, pdhObj, OBJPROP_BACK, true);

         string pdhLbl = prefix + "LIQ_PDH_L";
         if(ObjectFind(0, pdhLbl) < 0)
            ObjectCreate(0, pdhLbl, OBJ_TEXT, 0, tEnd, liq.pdh);
         else
         {
            ObjectSetInteger(0, pdhLbl, OBJPROP_TIME, 0, tEnd);
            ObjectSetDouble(0, pdhLbl, OBJPROP_PRICE, 0, liq.pdh);
         }
         ObjectSetString(0, pdhLbl, OBJPROP_TEXT, StringFormat(" [PDH] %.*f", _Digits, liq.pdh));
         ObjectSetString(0, pdhLbl, OBJPROP_FONT, "Segoe UI Semibold");
         ObjectSetInteger(0, pdhLbl, OBJPROP_FONTSIZE, 8);
         ObjectSetInteger(0, pdhLbl, OBJPROP_COLOR, C'245,158,11');
         ObjectSetInteger(0, pdhLbl, OBJPROP_ANCHOR, ANCHOR_LEFT_LOWER);

         string pdlObj = prefix + "LIQ_PDL";
         if(ObjectFind(0, pdlObj) < 0)
            ObjectCreate(0, pdlObj, OBJ_TREND, 0, tStart, liq.pdl, tEnd, liq.pdl);
         else
         {
            ObjectSetInteger(0, pdlObj, OBJPROP_TIME, 0, tStart);
            ObjectSetDouble(0, pdlObj, OBJPROP_PRICE, 0, liq.pdl);
            ObjectSetInteger(0, pdlObj, OBJPROP_TIME, 1, tEnd);
            ObjectSetDouble(0, pdlObj, OBJPROP_PRICE, 1, liq.pdl);
         }
         ObjectSetInteger(0, pdlObj, OBJPROP_COLOR, C'56,189,248');
         ObjectSetInteger(0, pdlObj, OBJPROP_STYLE, STYLE_DASH);
         ObjectSetInteger(0, pdlObj, OBJPROP_WIDTH, 1);
         ObjectSetInteger(0, pdlObj, OBJPROP_RAY_RIGHT, false);
         ObjectSetInteger(0, pdlObj, OBJPROP_BACK, true);

         string pdlLbl = prefix + "LIQ_PDL_L";
         if(ObjectFind(0, pdlLbl) < 0)
            ObjectCreate(0, pdlLbl, OBJ_TEXT, 0, tEnd, liq.pdl);
         else
         {
            ObjectSetInteger(0, pdlLbl, OBJPROP_TIME, 0, tEnd);
            ObjectSetDouble(0, pdlLbl, OBJPROP_PRICE, 0, liq.pdl);
         }
         ObjectSetString(0, pdlLbl, OBJPROP_TEXT, StringFormat(" [PDL] %.*f", _Digits, liq.pdl));
         ObjectSetString(0, pdlLbl, OBJPROP_FONT, "Segoe UI Semibold");
         ObjectSetInteger(0, pdlLbl, OBJPROP_FONTSIZE, 8);
         ObjectSetInteger(0, pdlLbl, OBJPROP_COLOR, C'56,189,248');
         ObjectSetInteger(0, pdlLbl, OBJPROP_ANCHOR, ANCHOR_LEFT_UPPER);
      }

      if(liq.hasAsianRange)
      {
         string boxObj = prefix + "LIQ_ASIAN_BOX";
         datetime tEndBox = MathMax(liq.asianEnd, TimeCurrent());
         if(ObjectFind(0, boxObj) < 0)
            ObjectCreate(0, boxObj, OBJ_RECTANGLE, 0, liq.asianStart, liq.asianHigh, tEndBox, liq.asianLow);
         else
         {
            ObjectSetInteger(0, boxObj, OBJPROP_TIME, 0, liq.asianStart);
            ObjectSetDouble(0, boxObj, OBJPROP_PRICE, 0, liq.asianHigh);
            ObjectSetInteger(0, boxObj, OBJPROP_TIME, 1, tEndBox);
            ObjectSetDouble(0, boxObj, OBJPROP_PRICE, 1, liq.asianLow);
         }
         ObjectSetInteger(0, boxObj, OBJPROP_COLOR, C'30,27,75');
         ObjectSetInteger(0, boxObj, OBJPROP_FILL, true);
         ObjectSetInteger(0, boxObj, OBJPROP_BACK, true);
         ObjectSetInteger(0, boxObj, OBJPROP_STYLE, STYLE_DOT);
         ObjectSetInteger(0, boxObj, OBJPROP_WIDTH, 1);

         string lblObj = prefix + "LIQ_ASIAN_L";
         if(ObjectFind(0, lblObj) < 0)
            ObjectCreate(0, lblObj, OBJ_TEXT, 0, liq.asianStart, liq.asianHigh);
         else
         {
            ObjectSetInteger(0, lblObj, OBJPROP_TIME, 0, liq.asianStart);
            ObjectSetDouble(0, lblObj, OBJPROP_PRICE, 0, liq.asianHigh);
         }
         ObjectSetString(0, lblObj, OBJPROP_TEXT, StringFormat(" [ASIAN RANGE] %.*f - %.*f", _Digits, liq.asianLow, _Digits, liq.asianHigh));
         ObjectSetString(0, lblObj, OBJPROP_FONT, "Segoe UI");
         ObjectSetInteger(0, lblObj, OBJPROP_FONTSIZE, 8);
         ObjectSetInteger(0, lblObj, OBJPROP_COLOR, C'129,140,248');
         ObjectSetInteger(0, lblObj, OBJPROP_ANCHOR, ANCHOR_LEFT_LOWER);
      }
   }
};

//+------------------------------------------------------------------+
//| TẦNG 3: FAIR VALUE GAP & CE 50% ENGINE                           |
//+------------------------------------------------------------------+
class CFvgEngine
{
public:
   static void ScanFvg(string symbol, ENUM_TIMEFRAMES tf, int barsToScan, double atrThreshold, SFairValueGap &outFvg[])
   {
      ArrayResize(outFvg, 0);

      MqlRates rates[];
      ArraySetAsSeries(rates, true);
      int copied = CopyRates(symbol, tf, 0, barsToScan, rates);
      if(copied < 10) return;

      for(int i = 1; i < copied - 2; i++)
      {
         // Bullish FVG (BISI)
         if(rates[i+2].high < rates[i].low)
         {
            double gHigh = rates[i].low;
            double gLow  = rates[i+2].high;
            if((gHigh - gLow) >= 0.25 * atrThreshold)
            {
               bool mitigated = false;
               for(int m = i - 1; m >= 0; m--)
               {
                  if(rates[m].close < gLow)
                  {
                     mitigated = true;
                     break;
                  }
               }

               if(!mitigated)
               {
                  SFairValueGap fvg;
                  fvg.id = ArraySize(outFvg) + 1;
                  fvg.isBisi = true;
                  fvg.gapHigh = gHigh;
                  fvg.gapLow = gLow;
                  fvg.consequentEncroachment = (gHigh + gLow) / 2.0;
                  fvg.barTime = rates[i+1].time;
                  fvg.timeEnd = rates[0].time;
                  fvg.isMitigated = false;

                  int sz = ArraySize(outFvg);
                  ArrayResize(outFvg, sz + 1);
                  outFvg[sz] = fvg;
               }
            }
         }
         // Bearish FVG (SIBI)
         else if(rates[i+2].low > rates[i].high)
         {
            double gHigh = rates[i+2].low;
            double gLow  = rates[i].high;
            if((gHigh - gLow) >= 0.25 * atrThreshold)
            {
               bool mitigated = false;
               for(int m = i - 1; m >= 0; m--)
               {
                  if(rates[m].close > gHigh)
                  {
                     mitigated = true;
                     break;
                  }
               }

               if(!mitigated)
               {
                  SFairValueGap fvg;
                  fvg.id = ArraySize(outFvg) + 1;
                  fvg.isBisi = false;
                  fvg.gapHigh = gHigh;
                  fvg.gapLow = gLow;
                  fvg.consequentEncroachment = (gHigh + gLow) / 2.0;
                  fvg.barTime = rates[i+1].time;
                  fvg.timeEnd = rates[0].time;
                  fvg.isMitigated = false;

                  int sz = ArraySize(outFvg);
                  ArrayResize(outFvg, sz + 1);
                  outFvg[sz] = fvg;
               }
            }
         }
      }
   }

   static void Draw(string prefix, const SFairValueGap &fvgList[], datetime extendTime)
   {
      ObjectsDeleteAll(0, prefix + "FVG_");

      int countBull = 0, countBear = 0;
      for(int i = 0; i < ArraySize(fvgList); i++)
      {
         if(fvgList[i].isMitigated) continue;

         if(fvgList[i].isBisi && countBull >= 2) continue;
         if(!fvgList[i].isBisi && countBear >= 2) continue;

         string boxObj = StringFormat("%sFVG_%d", prefix, fvgList[i].id);
         color boxClr = fvgList[i].isBisi ? C'16,68,48' : C'65,22,28';
         color lineClr = fvgList[i].isBisi ? C'52,211,153' : C'248,113,113';

         if(ObjectFind(0, boxObj) < 0)
            ObjectCreate(0, boxObj, OBJ_RECTANGLE, 0, fvgList[i].barTime, fvgList[i].gapHigh, extendTime, fvgList[i].gapLow);
         else
         {
            ObjectSetInteger(0, boxObj, OBJPROP_TIME, 0, fvgList[i].barTime);
            ObjectSetDouble(0, boxObj, OBJPROP_PRICE, 0, fvgList[i].gapHigh);
            ObjectSetInteger(0, boxObj, OBJPROP_TIME, 1, extendTime);
            ObjectSetDouble(0, boxObj, OBJPROP_PRICE, 1, fvgList[i].gapLow);
         }
         ObjectSetInteger(0, boxObj, OBJPROP_COLOR, boxClr);
         ObjectSetInteger(0, boxObj, OBJPROP_FILL, true);
         ObjectSetInteger(0, boxObj, OBJPROP_BACK, true);
         ObjectSetInteger(0, boxObj, OBJPROP_STYLE, STYLE_SOLID);

         string ceObj = boxObj + "_CE";
         if(ObjectFind(0, ceObj) < 0)
            ObjectCreate(0, ceObj, OBJ_TREND, 0, fvgList[i].barTime, fvgList[i].consequentEncroachment, extendTime, fvgList[i].consequentEncroachment);
         else
         {
            ObjectSetInteger(0, ceObj, OBJPROP_TIME, 0, fvgList[i].barTime);
            ObjectSetDouble(0, ceObj, OBJPROP_PRICE, 0, fvgList[i].consequentEncroachment);
            ObjectSetInteger(0, ceObj, OBJPROP_TIME, 1, extendTime);
            ObjectSetDouble(0, ceObj, OBJPROP_PRICE, 1, fvgList[i].consequentEncroachment);
         }
         ObjectSetInteger(0, ceObj, OBJPROP_COLOR, lineClr);
         ObjectSetInteger(0, ceObj, OBJPROP_STYLE, STYLE_DOT);
         ObjectSetInteger(0, ceObj, OBJPROP_WIDTH, 1);
         ObjectSetInteger(0, ceObj, OBJPROP_RAY_RIGHT, false);
         ObjectSetInteger(0, ceObj, OBJPROP_BACK, true);

         string lblObj = boxObj + "_L";
         if(ObjectFind(0, lblObj) < 0)
            ObjectCreate(0, lblObj, OBJ_TEXT, 0, extendTime, fvgList[i].consequentEncroachment);
         else
         {
            ObjectSetInteger(0, lblObj, OBJPROP_TIME, 0, extendTime);
            ObjectSetDouble(0, lblObj, OBJPROP_PRICE, 0, fvgList[i].consequentEncroachment);
         }
         string fvgType = fvgList[i].isBisi ? "BISI FVG CE 50%" : "SIBI FVG CE 50%";
         ObjectSetString(0, lblObj, OBJPROP_TEXT, StringFormat(" [%s] %.*f", fvgType, _Digits, fvgList[i].consequentEncroachment));
         ObjectSetString(0, lblObj, OBJPROP_FONT, "Segoe UI");
         ObjectSetInteger(0, lblObj, OBJPROP_FONTSIZE, 8);
         ObjectSetInteger(0, lblObj, OBJPROP_COLOR, lineClr);
         ObjectSetInteger(0, lblObj, OBJPROP_ANCHOR, ANCHOR_LEFT_LOWER);

         if(fvgList[i].isBisi) countBull++; else countBear++;
      }
   }
};

//+------------------------------------------------------------------+
//| ĐỘNG CƠ KÍCH HOẠT THÍCH ỨNG & FORMAT TELEGRAM 3.2                |
//+------------------------------------------------------------------+
class CAdaptiveConfirmationEngine
{
public:
   static string FormatTelegramMessage(const SConfirmSignal &sig, const SAssetProfile &profile)
   {
      string dirEmoji = sig.isBuy ? "🟢" : "🔴";
      string dirText  = sig.isBuy ? "BUY CHoCH" : "SELL CHoCH";

      double risk = MathAbs(sig.entry - sig.sl);
      double tp1Dist = MathAbs(sig.tp1 - sig.entry);
      double tp2Dist = MathAbs(sig.tp2 - sig.entry);
      double macroDist = (sig.tpMacro > 0) ? MathAbs(sig.tpMacro - sig.entry) : 0.0;
      double rrMacro = (risk > 0 && macroDist > 0) ? (macroDist / risk) : 3.5;

      double unitMult = 1.0;
      if(profile.assetClass == ASSET_FOREX) unitMult = profile.pipSize;
      else if(profile.assetClass == ASSET_METALS) unitMult = 1.0;
      else unitMult = (_Point > 0) ? _Point : 1.0;

      double slDisplay    = (unitMult > 0) ? (sig.slBufferVal / unitMult) : sig.slBufferVal;
      double tp1Display   = (unitMult > 0) ? (tp1Dist / unitMult) : tp1Dist;
      double tp2Display   = (unitMult > 0) ? (tp2Dist / unitMult) : tp2Dist;
      double macroDisplay = (unitMult > 0) ? (macroDist / unitMult) : macroDist;

      string msg = StringFormat(
         "⚡ <b>SMT / SMC M5 CHoCH TRIGGER %s</b> ⚡\\n" +
         "━━━━━━━━━━━━━━━━━━━\\n" +
         "💎 <b>Cặp tiền / Tài sản:</b> <code>%s</code> (M5) | <b>Lớp:</b> <code>%s</code>\\n" +
         "🧭 <b>Hướng:</b> %s <b>%s</b>\\n" +
         "🏛 <b>Cản kích hoạt:</b> <code>%s</code>\\n" +
         "🎯 <b>Mốc kích hoạt:</b> %s (%.*f)\\n" +
         "━━━━━━━━━━━━━━━━━━━\\n" +
         "📍 <b>Giá Entry:</b> <code>%.*f</code>\\n" +
         "🛡 <b>Stop Loss:</b> <code>%.*f</code> (Đệm an toàn: %.1f %s)\\n" +
         "🎁 <b>Take Profit 1 (1:1.5):</b> <code>%.*f</code> (+%.1f %s | R:R 1:1.5)\\n" +
         "🚀 <b>Take Profit 2 (1:2.0):</b> <code>%.*f</code> (+%.1f %s | R:R 1:2.0)\\n",
         profile.classTag,
         _Symbol, profile.className,
         dirEmoji, dirText,
         sig.zoneType,
         sig.poiSource, _Digits, sig.sweepPrice,
         _Digits, sig.entry,
         _Digits, sig.sl, slDisplay, profile.unitName,
         _Digits, sig.tp1, tp1Display, profile.unitName,
         _Digits, sig.tp2, tp2Display, profile.unitName
      );

      if(sig.tpMacro > 0 && rrMacro >= 2.0)
      {
         msg += StringFormat("🏛 <b>Target Cản đối diện:</b> <code>%.*f</code> (+%.1f %s | R:R 1:%.1f)\\n",
                             _Digits, sig.tpMacro, macroDisplay, profile.unitName, rrMacro);
      }

      msg += StringFormat(
         "━━━━━━━━━━━━━━━━━━━\\n" +
         "⏰ <b>Khung giờ:</b> <code>%s</code> | <b>Phiên:</b> <code>%s</code>\\n" +
         "⚠️ <b>Invalidation:</b> Đóng nến M5 ngược chiều bẻ gãy chóp râu quét -> Hủy kế hoạch!",
         TimeToString(sig.time, TIME_DATE|TIME_MINUTES),
         profile.primeSession
      );

      return msg;
   }
};

"""
    # Insert classes before OnInit()
    target_oninit = "//| Khởi tạo chỉ báo                                                 |"
    if target_oninit in content:
        content = content.replace(target_oninit, classes_code + target_oninit, 1)
    else:
        print("Error: target_oninit not found!")
        return 1

    # 7. Update OnInit() to initialize g_assetProfile
    init_old = """int OnInit()
{
   g_lang = DefaultLang;"""

    init_new = """int OnInit()
{
   g_lang = DefaultLang;
   g_assetProfile = CAssetProfiler::GetProfile(_Symbol);"""

    if init_old in content:
        content = content.replace(init_old, init_new, 1)
    else:
        print("Error: init_old not found!")
        return 1

    # 8. Update OnCalculate()
    calc_old = """   if(isNewBar || prev_calculated == 0 || ArraySize(g_zones) == 0)
   {
      ScanHtfMacroZones();
      if(ArraySize(g_zones) > 0)
         lastBarTime = time[rates_total - 1];
      DrawChartZones();
   }"""

    calc_new = """   if(isNewBar || prev_calculated == 0 || ArraySize(g_zones) == 0)
   {
      ScanHtfMacroZones();
      double htfAtrVal = 1.0;
      double htfAtrs[];
      int htfH = (HtfPeriod == Period()) ? g_atrHandle : g_htfAtrHandle;
      if(htfH != INVALID_HANDLE && CopyBuffer(htfH, 0, 0, 1, htfAtrs) > 0) htfAtrVal = htfAtrs[0];

      if(UseCompositeOB)
      {
         COrderBlockEngine::MergeCompositeBlocks(g_zones, htfAtrVal, MinScoreShow);
      }
      if(ShowSessionLiq)
      {
         CSessionLiquidityEngine::Calculate(_Symbol, g_sessionLiq);
      }
      if(ShowFvg)
      {
         CFvgEngine::ScanFvg(_Symbol, HtfPeriod, 150, htfAtrVal, g_fvgs);
      }

      if(ArraySize(g_zones) > 0)
         lastBarTime = time[rates_total - 1];

      DrawChartZones();
      datetime extendTime = iTime(_Symbol, PERIOD_CURRENT, 0) + (PeriodSeconds() * ExtendBars);
      if(ShowSessionLiq)
         CSessionLiquidityEngine::Draw(g_prefix, g_sessionLiq, extendTime);
      if(ShowFvg)
         CFvgEngine::Draw(g_prefix, g_fvgs, extendTime);
   }"""

    if calc_old in content:
        content = content.replace(calc_old, calc_new, 1)
    else:
        print("Error: calc_old not found!")
        return 1

    # 9. Update DrawChartZones anti-clutter staggered labels
    draw_old = """      if(ShowLabels)
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
      }"""

    draw_new = """      if(ShowLabels)
      {
         string lblName = objName + "L";
         string typeStr = EnumToString(g_zones[i].type);
         StringReplace(typeStr, "ZONE_", "");
         string compTag = g_zones[i].isComposite ? "COMPOSITE " : "";
         string text = StringFormat(" %s%s %d %s [MT: %.*f]",
                                    compTag,
                                    typeStr,
                                    g_zones[i].score,
                                    g_zones[i].isFresh ? "FRESH" : "TEST",
                                    _Digits,
                                    g_zones[i].meanThreshold);

         datetime lblTime = t2;
         // Anti-clutter staggered label (+5 bars offset when vertical distance < 15 points)
         if((g_zones[i].isSupply && drawnSupply > 0) || (!g_zones[i].isSupply && drawnDemand > 0))
         {
            lblTime += (PeriodSeconds() * 5);
         }

         if(ObjectFind(0, lblName) < 0)
         {
            ObjectCreate(0, lblName, OBJ_TEXT, 0, lblTime, p2);
         }
         else
         {
            ObjectSetInteger(0, lblName, OBJPROP_TIME, 0, lblTime);
            ObjectSetDouble(0, lblName, OBJPROP_PRICE, 0, p2);
         }
         ObjectSetString(0, lblName, OBJPROP_TEXT, text);
         ObjectSetString(0, lblName, OBJPROP_FONT, "Segoe UI Semibold");
         ObjectSetInteger(0, lblName, OBJPROP_FONTSIZE, LabelFont);
         ObjectSetInteger(0, lblName, OBJPROP_COLOR, lineClr);
         ObjectSetInteger(0, lblName, OBJPROP_ANCHOR, g_zones[i].isSupply ? ANCHOR_LEFT_LOWER : ANCHOR_LEFT_UPPER);
      }"""

    if draw_old in content:
        content = content.replace(draw_old, draw_new, 1)
    else:
        print("Error: draw_old not found!")
        return 1

    # 10. Update DetectLtfConfirmation() dynamic SL buffer and sweeps
    detect_old = """            if(isBuySignal)
            {
               sl = sweepPrice - (SlBufferATR * ltfAtr);
               risk = entry - sl;
               if(risk <= 0) { risk = 1.0 * ltfAtr; sl = entry - risk; }
               tp1 = entry + 1.5 * risk; // Chốt lời 1: Tỷ lệ 1:1.5
               tp2 = entry + 2.0 * risk; // Chốt lời 2: Tỷ lệ 1:2.0

               // TP Macro: Cản cung H1 gần nhất phía trên
               double minSupplyDist = 9999999.0;
               double targetSupply = entry + 4.5 * risk;
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
               sl = sweepPrice + (SlBufferATR * ltfAtr);
               risk = sl - entry;
               if(risk <= 0) { risk = 1.0 * ltfAtr; sl = entry + risk; }
               tp1 = entry - 1.5 * risk; // Chốt lời 1: Tỷ lệ 1:1.5
               tp2 = entry - 2.0 * risk; // Chốt lời 2: Tỷ lệ 1:2.0

               // TP Macro: Cản cầu H1 gần nhất phía dưới
               double minDemandDist = 9999999.0;
               double targetDemand = entry - 4.5 * risk;
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
            }"""

    detect_new = """            double dynSlBuffer = CAssetProfiler::ComputeDynamicSlBuffer(g_assetProfile, ltfAtr, SlBufferATR);

            if(isBuySignal)
            {
               sl = sweepPrice - dynSlBuffer;
               risk = entry - sl;
               if(risk <= 0) { risk = dynSlBuffer; sl = entry - risk; }
               tp1 = entry + 1.5 * risk; // Chốt lời 1: Tỷ lệ 1:1.5
               tp2 = entry + 2.0 * risk; // Chốt lời 2: Tỷ lệ 1:2.0

               // TP Macro: Cản cung H1 gần nhất phía trên hoặc PDH
               double minSupplyDist = 9999999.0;
               double targetSupply = entry + 3.5 * risk;
               if(g_sessionLiq.hasPdhPdl && g_sessionLiq.pdh > entry)
                  targetSupply = g_sessionLiq.pdh;

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
               sl = sweepPrice + dynSlBuffer;
               risk = sl - entry;
               if(risk <= 0) { risk = dynSlBuffer; sl = entry + risk; }
               tp1 = entry - 1.5 * risk; // Chốt lời 1: Tỷ lệ 1:1.5
               tp2 = entry - 2.0 * risk; // Chốt lời 2: Tỷ lệ 1:2.0

               // TP Macro: Cản cầu H1 gần nhất phía dưới hoặc PDL
               double minDemandDist = 9999999.0;
               double targetDemand = entry - 3.5 * risk;
               if(g_sessionLiq.hasPdhPdl && g_sessionLiq.pdl < entry)
                  targetDemand = g_sessionLiq.pdl;

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
            }"""

    if detect_old in content:
        content = content.replace(detect_old, detect_new, 1)
    else:
        print("Error: detect_old not found!")
        return 1

    # 11. Update SendSignalTelegram
    tg_old = """void SendSignalTelegram(const SConfirmSignal &sig)
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
      "⚡ <b>SMT / SMC M5 CHoCH TRIGGER</b> ⚡\\n" +
      "━━━━━━━━━━━━━━━━━━━\\n" +
      "💎 <b>Cặp tiền / Tài sản:</b> <code>%s</code> (%s)\\n" +
      "🧭 <b>Hướng:</b> %s <b>%s</b>\\n" +
      "🏛 <b>Cản %s kích hoạt:</b> <code>%s</code> (Điểm: %d/100)\\n" +
      "━━━━━━━━━━━━━━━━━━━\\n" +
      "📍 <b>Giá Entry:</b> <code>%.*f</code>\\n" +
      "🛡 <b>Stop Loss:</b> <code>%.*f</code> (kê chóp râu nến %s, %.1f pips)\\n" +
      "🎁 <b>Take Profit 1 (1:1.5):</b> <code>%.*f</code> (+%.1f pips)\\n" +
      "🚀 <b>Take Profit 2 (1:2.0):</b> <code>%.*f</code> (+%.1f pips)\\n",
      _Symbol, tfLtf,
      dirEmoji, dirText,
      tfHtf, sig.zoneType, sig.zoneScore,
      _Digits, sig.entry,
      _Digits, sig.sl, tfLtf, slPips,
      _Digits, sig.tp1, tp1Pips,
      _Digits, sig.tp2, tp2Pips
   );

   if(sig.tpMacro > 0 && sig.rrMacro > 2.0)
   {
      double macroPips = PriceToPips(sig.tpMacro - sig.entry);
      msg += StringFormat("🎯 <b>Target Cản %s đối diện:</b> <code>%.*f</code> (+%.1f pips | R:R 1:%.1f)\\n",
                          tfHtf, _Digits, sig.tpMacro, macroPips, sig.rrMacro);
   }

   msg += StringFormat(
      "━━━━━━━━━━━━━━━━━━━\\n" +
      "⏰ <b>Khung giờ:</b> <code>%s</code>\\n" +
      "💡 <i>Gợi ý: Chốt 50-70%% volume tại TP1 (1:1.5), dời SL về Hòa Vốn (BE), gồng runner đến TP2 (1:2.0) & Cản %s!</i>",
      TimeToString(sig.time, TIME_DATE|TIME_MINUTES),
      tfHtf
   );

   DispatchTelegram(msg);
}"""

    tg_new = """void SendSignalTelegram(const SConfirmSignal &sig)
{
   if(!TgEnable) return;
   string msg = CAdaptiveConfirmationEngine::FormatTelegramMessage(sig, g_assetProfile);
   DispatchTelegram(msg);
}"""

    if tg_old in content:
        content = content.replace(tg_old, tg_new, 1)
    else:
        print("Error: tg_old not found!")
        return 1

    # 12. Update badgeText in RenderDashboard
    dash_old = """   // Badge khung thời gian top-right
   string badgeText = StringFormat("%s %s/%s", _Symbol, ltfTag, htfTag);"""

    dash_new = """   // Badge khung thời gian top-right
   string badgeText = StringFormat("%s %s %s/%s", _Symbol, g_assetProfile.classTag, ltfTag, htfTag);"""

    if dash_old in content:
        content = content.replace(dash_old, dash_new, 1)
    else:
        print("Error: dash_old not found!")
        return 1

    # Save to mq5_path
    with open(mq5_path, 'w', encoding='utf-8') as f:
        f.write(content)

    print("Successfully upgraded duc_tri_can_ho_tro.mq5!")
    return 0

if __name__ == '__main__':
    sys.exit(main())
