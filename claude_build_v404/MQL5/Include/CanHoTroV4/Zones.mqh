#ifndef CHT_V4_ZONES
#define CHT_V4_ZONES
bool g_v4ZonesReady=false;
class CZoneEngine { public: static void Scan(); };
void CZoneEngine::Scan()
{
   g_v4ZonesReady=false;
   RefreshReferenceLevels();
   DrawReferenceLevels();
   ArrayResize(g_zones, 0);
   g_statCreated = 0;
   g_statDemand  = 0;
   g_statSupply  = 0;
   g_statBroken  = 0;
   g_statFlipped = 0;

   ENUM_TIMEFRAMES scanTf = (HtfPeriod == PERIOD_CURRENT) ? PERIOD_H1 : HtfPeriod;
   int htfBarsToCopy = MathMin(MaxHistory, 2000);

   MqlRates hRates[];
   ArraySetAsSeries(hRates, false); // Index 0 là nến cũ nhất, N-1 là nến mới nhất
    // Position 0 is still forming. A zone must be built from completed HTF bars.
    int copied = V4DataRates(_Symbol, scanTf, 1, htfBarsToCopy, hRates);
   if(copied < LegInBars + BaseMaxBars + DepartBars + 15)
   { g_v4DiagZoneRates++; return; }

   double hAtr[];
   ArraySetAsSeries(hAtr, false);
   int atrH = g_htfAtrHandle;
    if(atrH == INVALID_HANDLE || V4DataBuffer(atrH, scanTf, 1, copied, hAtr) < copied)
   { g_v4DiagZoneAtr++; return; }

   g_v4ZonesReady=true;
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

         SZone zone;
         ZeroMemory(zone);
         zone.timeFormed = hRates[baseEnd + DepartBars].time;
         zone.timeKnown = zone.timeFormed + PeriodSeconds(scanTf);
         zone.timeInvalid = isBroken ? hRates[brokenBar].time + PeriodSeconds(scanTf) : 0;
         zone.id = InpCompatV301 ? ArraySize(g_zones) + 1 : V4ZoneId(hRates[baseStart].time,isSupply,zDistal,zProximal);
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

         g_statCreated++;
         if(isSupply) g_statSupply++; else g_statDemand++;
         if(isBroken) g_statBroken++;

         ArrayResize(g_zones, ArraySize(g_zones) + 1);
         g_zones[ArraySize(g_zones) - 1] = zone;

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

            if(!fBroken || !InpCompatV301)
            {
               SZone flipZ;
               ZeroMemory(flipZ);
               flipZ.timeFormed = hRates[brokenBar].time;
               flipZ.timeKnown = flipZ.timeFormed + PeriodSeconds(scanTf);
               // Invalidity is known only after the invalidating H1 closes.
               if(fBroken || fTests >= MaxTests || copied - 1 >= brokenBar + FlipLifeBars)
                  flipZ.timeInvalid = fTimeEnd + PeriodSeconds(scanTf);
               flipZ.id = InpCompatV301 ? ArraySize(g_zones) + 1 : V4ZoneId(hRates[brokenBar].time,flipSupply,fDistal,fProximal);
               flipZ.type = ZONE_FLIP;
               flipZ.isSupply = flipSupply;
               flipZ.timeStart = hRates[brokenBar].time;
               flipZ.timeEnd = fTimeEnd;
               flipZ.distal = fDistal;
               flipZ.proximal = fProximal;
               flipZ.testCount = fTests;
               flipZ.isFresh = (fTests == 0);
               flipZ.isBroken = !InpCompatV301 && flipZ.timeInvalid > 0 && flipZ.timeInvalid <= g_v4Now;
               flipZ.isFlip = true;
               flipZ.score = (int)MathRound(score * 0.85);
               flipZ.departAtr = departureStrength;
               flipZ.baseBars = baseLen;
               flipZ.hasHtfOverlap = zone.hasHtfOverlap;
               flipZ.ageBars = copied - 1 - brokenBar;

               g_statFlipped++;
               ArrayResize(g_zones, ArraySize(g_zones) + 1);
               g_zones[ArraySize(g_zones) - 1] = flipZ;
            }
         }

         i += baseLen;
         break;
      }
   }
}
#endif
