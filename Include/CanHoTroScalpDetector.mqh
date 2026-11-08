// Numerical loops copied from immutable v3.12, with trace-only adapters.
#ifndef CAN_HO_TRO_SCALP_DETECTOR
#define CAN_HO_TRO_SCALP_DETECTOR
#include "CanHoTroScalpTypes.mqh"
void CHTScanZones(const MqlRates &hRates[],const double &hAtr[],CHTZone &scanZones[])
{
   int copied=ArraySize(hRates);ArrayResize(scanZones,0);
   if(copied<39)return;
   int scanStatCreated=0,scanStatDemand=0,scanStatSupply=0,scanStatBroken=0,scanStatFlipped=0;
   int scanTf=PERIOD_H1;
   int startIdx = MathMax(copied - MaxHistory, LegInBars + 5);
   int endIdx   = copied - DepartBars - 1;

   for(int i = startIdx; i <= endIdx; i++)
   {
      double atr = hAtr[i];
      if(atr <= 0) continue;

      for(int baseLen = 1; baseLen <= BaseMaxBars; baseLen++)
      {
         int baseStart = i;
         int baseEnd   = i + baseLen - 1;
         if(baseEnd > endIdx) break;

         double bHigh = -1.0, bLow = 9999999.0;
         bool baseValid = true;
         for(int b = baseStart; b <= baseEnd; b++)
         {
            double rng = hRates[b].high - hRates[b].low;
            if(rng > BaseBarATR * atr) { baseValid = false; break; }
            if(hRates[b].high > bHigh) bHigh = hRates[b].high;
            if(hRates[b].low  < bLow)  bLow  = hRates[b].low;
         }
         if(!baseValid || (bHigh - bLow) > BaseTotalATR * atr)
            continue;

         double depLow = 9999999.0, depHigh = -1.0;
         for(int d = baseEnd + 1; d <= MathMin(copied - 1, baseEnd + DepartBars); d++)
         {
            if(hRates[d].low < depLow)   depLow = hRates[d].low;
            if(hRates[d].high > depHigh) depHigh = hRates[d].high;
         }

         bool isSupply = false, isDemand = false;
         double departureStrength = 0.0;

         if((bLow - depLow) >= DepartATR * atr)
         {
            isSupply = true;
            departureStrength = (bLow - depLow) / atr;
         }
         else if((depHigh - bHigh) >= DepartATR * atr)
         {
            isDemand = true;
            departureStrength = (depHigh - bHigh) / atr;
         }

         if(!isSupply && !isDemand)
            continue;

         ENUM_ZONE_TYPE zType = ZONE_RBR;
         int legInStart = MathMax(0, baseStart - LegInBars);
         double legInMove = hRates[baseStart].close - hRates[legInStart].close;
         if(isDemand)
            zType = (legInMove < 0) ? ZONE_DBR : ZONE_RBR;
         else
            zType = (legInMove > 0) ? ZONE_RBD : ZONE_DBD;

         double zDistal   = isSupply ? bHigh : bLow;
         double zProximal = isSupply ? bLow : bHigh;
          double zMin      = MathMin(zDistal, zProximal);
          double zMax      = MathMax(zDistal, zProximal);

          int testCount = 0;
          bool wasInside = false;
         bool isBroken = false;
         int brokenBar = -1;
         datetime timeEnd = hRates[copied - 1].time;

         for(int f = baseEnd + DepartBars + 1; f < copied; f++)
         {
            if(isSupply)
            {
                bool inside = (hRates[f].high >= zMin && hRates[f].low <= zMax);
                if(inside && !wasInside) testCount++;
                wasInside = inside;
               if(hRates[f].close > zDistal)
               {
                  isBroken = true;
                  brokenBar = f;
                  timeEnd = hRates[f].time;
                  break;
               }
            }
            else
            {
                bool inside = (hRates[f].high >= zMin && hRates[f].low <= zMax);
                if(inside && !wasInside) testCount++;
                wasInside = inside;
               if(hRates[f].close < zDistal)
               {
                  isBroken = true;
                  brokenBar = f;
                  timeEnd = hRates[f].time;
                  break;
               }
            }

             // Keep scanning after the test quota so a later structural break
             // can still invalidate this zone correctly.
         }

         double scoreDep = MathMin(WDepart, (departureStrength / DepartATR) * (WDepart * 0.7));
         double scoreBase = (baseLen == 1 ? WBase : (baseLen == 2 ? WBase * 0.75 : WBase * 0.5));
         double scoreFresh = (testCount == 0 ? WFresh : (testCount == 1 ? WFresh * 0.5 : (testCount == 2 ? WFresh * 0.25 : 0)));
         double scoreRev = (zType == ZONE_DBR || zType == ZONE_RBD) ? WReversal : (WReversal * 0.5);
          // A single scan timeframe cannot prove higher-timeframe overlap.
          // Do not award WMtf without an actual second-zone intersection.
          double scoreMtf = 0.0;

         double score = scoreDep + scoreBase + scoreFresh + scoreRev + scoreMtf;
         if(score > 100.0) score = 100.0;

         CHTZone zone;
          zone.baseTime=hRates[baseStart].time;zone.flipOrigin=0;
          zone.availableAt=hRates[baseEnd+DepartBars].time+3600;
         zone.id = ArraySize(scanZones) + 1;
         zone.type = zType;
         zone.isSupply = isSupply;
         zone.timeStart = hRates[baseStart].time;
         zone.timeEnd = timeEnd;
         zone.distal = zDistal;
         zone.proximal = zProximal;
         zone.testCount = testCount;
         zone.isFresh = (testCount == 0);
         zone.isBroken = isBroken;
         zone.isFlip = false;
         zone.score = (int)MathRound(score);
         zone.departAtr = departureStrength;
         zone.baseBars = baseLen;
         zone.hasHtfOverlap = (scanTf >= PERIOD_H1);
         zone.ageBars = copied - 1 - baseStart;

          if(zone.ageBars > MaxAgeBars)
             continue;

         scanStatCreated++;
         if(isSupply) scanStatSupply++; else scanStatDemand++;
         if(isBroken) scanStatBroken++;

         ArrayResize(scanZones, ArraySize(scanZones) + 1);
         scanZones[ArraySize(scanZones) - 1] = zone;

         // Xử lý cản đảo vai trò Flip
         if(isBroken && UseFlip && brokenBar > 0)
         {
            int flipLife = MathMin(copied - 1, brokenBar + FlipLifeBars);
            bool flipSupply = !isSupply;
            double fDistal = zProximal;
            double fProximal = zDistal;

            int fTests = 0;
            bool fBroken = false;
            datetime fTimeEnd = hRates[flipLife].time;

            for(int k = brokenBar + 1; k < copied; k++)
            {
               if(k > flipLife) break;

               if(flipSupply)
               {
                  if(hRates[k].high >= fProximal && hRates[k].low <= fProximal) fTests++;
                  if(hRates[k].close > fDistal) { fBroken = true; fTimeEnd = hRates[k].time; break; }
               }
               else
               {
                  if(hRates[k].low <= fProximal && hRates[k].high >= fProximal) fTests++;
                  if(hRates[k].close < fDistal) { fBroken = true; fTimeEnd = hRates[k].time; break; }
               }
               if(fTests >= MaxTests) { fTimeEnd = hRates[k].time; break; }
            }

            if(!fBroken)
            {
               CHTZone flipZ;
                flipZ.baseTime=hRates[baseStart].time;
                flipZ.flipOrigin=hRates[brokenBar].time;flipZ.availableAt=flipZ.flipOrigin+3600;
               flipZ.id = ArraySize(scanZones) + 1;
               flipZ.type = ZONE_FLIP;
               flipZ.isSupply = flipSupply;
               flipZ.timeStart = hRates[brokenBar].time;
               flipZ.timeEnd = fTimeEnd;
               flipZ.distal = fDistal;
               flipZ.proximal = fProximal;
               flipZ.testCount = fTests;
               flipZ.isFresh = (fTests == 0);
               flipZ.isBroken = false;
               flipZ.isFlip = true;
               flipZ.score = (int)MathRound(score * 0.85);
               flipZ.departAtr = departureStrength;
               flipZ.baseBars = baseLen;
               flipZ.hasHtfOverlap = zone.hasHtfOverlap;
               flipZ.ageBars = copied - 1 - brokenBar;

               scanStatFlipped++;
               ArrayResize(scanZones, ArraySize(scanZones) + 1);
               scanZones[ArraySize(scanZones) - 1] = flipZ;
            }
         }

         i += baseLen;
         break;
      }
   }

}
bool CHTInKillzone(datetime barTime)
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
double CHTObstacle(const CHTZone &zones[],const bool buy,const double entry,
                   const CHTContext &ctx,datetime &origin)
{
   double best=0;origin=0;
   double day=buy?ctx.dayHigh:ctx.dayLow;
   if((buy && day>entry)||(!buy && day>0 && day<entry)){best=day;origin=ctx.dayTime;}
   for(int j=0;j<ArraySize(zones);j++)
   {
      if(zones[j].isBroken || zones[j].isSupply==(!buy))continue;
      double lo=MathMin(zones[j].distal,zones[j].proximal),hi=MathMax(zones[j].distal,zones[j].proximal);
      if(lo<=entry && entry<=hi){origin=zones[j].baseTime;return entry;}
      double level=zones[j].proximal;
      if((buy && level>entry)||(!buy && level<entry))
         if(best==0 || MathAbs(level-entry)<MathAbs(best-entry)){best=level;origin=zones[j].baseTime;}
   }
   return best;
}
void CHTFindRaw(const MqlRates &ltfRates[],const double ltfAtr,const CHTZone &zones[],
                const CHTContext &ctx,CHTCandidate &out[],const bool closedOnly=false)
{
   ArrayResize(out,0);int copied=ArraySize(ltfRates);
   if(copied<30 || ltfAtr<=0)return;
   bool inPoiGlobal=false,sweepFoundGlobal=false;
   for(int z = 0; z < ArraySize(zones); z++)
   {
      if(zones[z].isBroken || zones[z].score < MinScoreShow)
         continue;

      double zMin = MathMin(zones[z].distal, zones[z].proximal);
      double zMax = MathMax(zones[z].distal, zones[z].proximal);
      bool isSupply = zones[z].isSupply;

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
      inPoiGlobal = true;

      // 2. Phát hiện Râu Quét Thanh Khoản (Liquidity Sweep / Wick Rejection >= 35%)
      bool sweepFound = false;
      int sweepBar = -1;
      double sweepPrice = isSupply ? -1.0 : 9999999.0;

      for(int s = 1; s <= 20 && s < copied; s++)
      {
         double fullRng = ltfRates[s].high - ltfRates[s].low;
         if(fullRng < 0.25 * ltfAtr) continue; // Bỏ qua nến nhiễu biên độ quá nhỏ

         if(isSupply)
         {
            double upperWick = ltfRates[s].high - MathMax(ltfRates[s].open, ltfRates[s].close);
            double wickRatio = upperWick / fullRng;
            double sweepLevel = (SweepLevelMode == SWEEP_DISTAL) ? zMax : zMin;
            if(wickRatio >= WickRatioMin && ltfRates[s].high >= sweepLevel && ltfRates[s].close < sweepLevel)
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
            double sweepLevel = (SweepLevelMode == SWEEP_DISTAL) ? zMin : zMax;
            if(wickRatio >= WickRatioMin && ltfRates[s].low <= sweepLevel && ltfRates[s].close > sweepLevel)
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
      sweepFoundGlobal = true;

      // 3. Tìm Đỉnh/Đáy vi mô sau cú quét để xác nhận CHoCH
      double chochLevel = 0.0;
      int pivotBar = -1;
      int swStart = MathMin(copied - 2, sweepBar - 2);
      int swEnd   = MathMax(1, sweepBar - 8);

      if(isSupply)
      {
         // Canh BÁN: Tìm minor swing low sau cú quét lên cản
         chochLevel = 9999999.0;
         bool foundPivot = false;
         for(int sw = swStart; sw >= swEnd; sw--)
         {
            if(sw > (closedOnly?1:0) && sw < copied - 1)
            {
               if(ltfRates[sw].low <= ltfRates[sw - 1].low && ltfRates[sw].low <= ltfRates[sw + 1].low)
               {
                  chochLevel = ltfRates[sw].low;
                  pivotBar = sw;
                  foundPivot = true;
                  break;
               }
            }
         }
         if(!foundPivot)
         {
            for(int sw = swStart; sw >= MathMax(1, sweepBar - 4); sw--)
            {
               if(ltfRates[sw].low < chochLevel)
               {
                  chochLevel = ltfRates[sw].low;
                  pivotBar = sw;
               }
            }
         }
      }
      else
      {
         // Canh MUA: Tìm minor swing high sau cú quét xuống cản
         chochLevel = -1.0;
         bool foundPivot = false;
         for(int sw = swStart; sw >= swEnd; sw--)
         {
            if(sw > (closedOnly?1:0) && sw < copied - 1)
            {
               if(ltfRates[sw].high >= ltfRates[sw - 1].high && ltfRates[sw].high >= ltfRates[sw + 1].high)
               {
                  chochLevel = ltfRates[sw].high;
                  pivotBar = sw;
                  foundPivot = true;
                  break;
               }
            }
         }
         if(!foundPivot)
         {
            for(int sw = swStart; sw >= MathMax(1, sweepBar - 4); sw--)
            {
               if(ltfRates[sw].high > chochLevel)
               {
                  chochLevel = ltfRates[sw].high;
                  pivotBar = sw;
               }
            }
         }
      }

      // 4. Kiểm tra nến xác nhận CHoCH đã đóng cửa hoàn chỉnh (100% NON-REPAINTING)
      bool isBuySignal = !isSupply;
      int confirmBar = -1;

      for(int c = pivotBar - 1; c >= 1; c--)
      {
         if(isBuySignal)
         {
            // BUY CHoCH: Nến xanh đóng cửa cao hơn swing high dẫn dụ
            if(chochLevel > 0 && ltfRates[c].close > chochLevel && ltfRates[c].close > ltfRates[c].open)
            {
               confirmBar = c;
               break;
            }
         }
         else
         {
            // SELL CHoCH: Nến đỏ đóng cửa thấp hơn swing low dẫn dụ
            if(chochLevel < 9999990.0 && ltfRates[c].close < chochLevel && ltfRates[c].close < ltfRates[c].open)
            {
               confirmBar = c;
               break;
            }
         }
      }


      if(confirmBar!=1)continue;
      bool buy=!isSupply;int gate=0;
      if(MathAbs(ltfRates[1].close-ltfRates[1].open)<MinDisplacementATR*ltfAtr)gate=1;
      if(gate==0 && !CHTInKillzone(ltfRates[1].time))gate=2;
      if(gate==0 && ((buy && ctx.trendClose<=ctx.trendMa)||(!buy && ctx.trendClose>=ctx.trendMa)))gate=3;
      if(gate==0 && (ctx.trendAtr<=0 || MathAbs(ctx.trendClose-ctx.trendMa)/ctx.trendAtr>MaxHtfEmaDistanceATR))gate=4;
      int lookback=MathMin(copied-1,MathMax(5,sweepBar));
      double anchor=buy?ltfRates[1].low:ltfRates[1].high;
      for(int b=1;b<=lookback;b++)anchor=buy?MathMin(anchor,ltfRates[b].low):MathMax(anchor,ltfRates[b].high);
      double stop=anchor+(buy?-SlBufferATR:SlBufferATR)*ltfAtr;
      double mid=(ltfRates[1].open+ltfRates[1].close)/2.;
      datetime omt,olt;
      double om=CHTObstacle(zones,buy,ltfRates[1].close,ctx,omt);
      double ol=CHTObstacle(zones,buy,mid,ctx,olt);
      int count=ArraySize(out);ArrayResize(out,count+1);CHTCandidate r;
      r.v[0]=(double)ltfRates[1].time;r.v[1]=r.v[0]+300;r.v[2]=(double)buy;
      r.v[3]=(double)zones[z].baseTime;r.v[4]=zones[z].baseBars;r.v[5]=(double)zones[z].isFlip;
      r.v[6]=(double)zones[z].flipOrigin;r.v[7]=zones[z].id;r.v[8]=zones[z].score;r.v[9]=zones[z].testCount;
      r.v[10]=zones[z].distal;r.v[11]=zones[z].proximal;r.v[12]=(double)zones[z].availableAt;
      r.v[13]=(double)ltfRates[sweepBar].time;r.v[14]=sweepPrice;
      r.v[15]=(double)ltfRates[pivotBar].time;r.v[16]=chochLevel;
      r.v[17]=(double)ltfRates[pivotBar-1].time+300;r.v[18]=ltfAtr;r.v[19]=stop;r.v[20]=anchor;
      r.v[21]=ltfRates[1].close;r.v[22]=mid;r.v[23]=(double)ctx.trendTime;
      r.v[24]=ctx.trendClose;r.v[25]=ctx.trendMa;r.v[26]=ctx.trendAtr;r.v[27]=gate;
      r.v[28]=zones[z].availableAt>ltfRates[sweepBar].time?5:0;
      r.v[29]=om;r.v[30]=ol;r.v[31]=(double)omt;r.v[32]=(double)olt;
      r.v[33]=z;r.v[34]=ctx.m5Index;r.v[35]=ctx.h1Count;out[count]=r;
   }
}
void CHTATR(const MqlRates &rates[],double &out[])
{
   int n=ArraySize(rates);ArrayResize(out,n);ArrayInitialize(out,0.0);if(n<=14)return;
   double tr[];ArrayResize(tr,n);tr[0]=0;double sum=0;
   for(int i=1;i<n;i++)tr[i]=MathMax(rates[i].high,rates[i-1].close)-MathMin(rates[i].low,rates[i-1].close);
   for(int i=1;i<=14;i++)sum+=tr[i];out[14]=sum/14.;
   for(int i=15;i<n;i++)out[i]=out[i-1]+(tr[i]-tr[i-14])/14.;
}
void CHTEMA(const MqlRates &rates[],double &out[])
{
   int n=ArraySize(rates);ArrayResize(out,n);if(n==0)return;out[0]=rates[0].close;
   for(int i=1;i<n;i++)out[i]=rates[i].close*(2./51.)+out[i-1]*(49./51.);
}
int CHTLower(const MqlRates &rates[],datetime at)
{
   int l=0,r=ArraySize(rates);while(l<r){int m=(l+r)/2;if(rates[m].time<at)l=m+1;else r=m;}return l;
}
#endif
