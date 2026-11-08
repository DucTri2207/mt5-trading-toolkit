import sys, time
from datetime import datetime, timezone
import numpy as np

if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')

import MetaTrader5 as mt5

def compute_wilder_atr(highs, lows, closes, period=14):
    n = len(highs)
    tr = np.zeros(n, dtype=np.float64)
    tr[0] = highs[0] - lows[0]
    for i in range(1, n):
        tr[i] = max(highs[i] - lows[i], abs(highs[i] - closes[i-1]), abs(lows[i] - closes[i-1]))
    atr = np.zeros(n, dtype=np.float64)
    atr[period - 1] = np.mean(tr[:period])
    for i in range(period, n):
        atr[i] = (atr[i-1] * (period - 1) + tr[i]) / period
    return atr

def build_h1_zones(times_h1, opens_h1, highs_h1, lows_h1, closes_h1, atr_h1):
    n = len(times_h1)
    BaseMaxBars = 5
    BaseBarATR = 0.8
    BaseTotalATR = 2.0
    DepartATR = 1.8
    DepartBars = 4
    LegInBars = 15
    MaxTests = 4
    MaxAgeBars = 1200
    FlipLifeBars = 400
    MinScoreShow = 35

    WDepart = 40.0
    WBase = 20.0
    WFresh = 20.0
    WReversal = 10.0
    WMtf = 10.0

    zones = [] # list of dicts

    i = LegInBars + 5
    while i <= n - DepartBars - 1:
        c_atr = atr_h1[i]
        if c_atr <= 0:
            i += 1
            continue
        found_base = False
        for baseLen in range(1, BaseMaxBars + 1):
            baseStart = i
            baseEnd = i + baseLen - 1
            if baseEnd > n - DepartBars - 1: break
            bHigh = -1.0
            bLow = 9999999.0
            baseValid = True
            for b in range(baseStart, baseEnd + 1):
                rng = highs_h1[b] - lows_h1[b]
                if rng > BaseBarATR * c_atr: baseValid = False; break
                if highs_h1[b] > bHigh: bHigh = highs_h1[b]
                if lows_h1[b] < bLow: bLow = lows_h1[b]
            if not baseValid or (bHigh - bLow) > BaseTotalATR * c_atr: continue
            
            depLow = 9999999.0
            depHigh = -1.0
            for d in range(baseEnd + 1, min(n, baseEnd + DepartBars + 1)):
                if lows_h1[d] < depLow: depLow = lows_h1[d]
                if highs_h1[d] > depHigh: depHigh = highs_h1[d]
                
            isSupply = False
            isDemand = False
            depStr = 0.0
            if (bLow - depLow) >= DepartATR * c_atr:
                isSupply = True
                depStr = (bLow - depLow) / c_atr
            elif (depHigh - bHigh) >= DepartATR * c_atr:
                isDemand = True
                depStr = (depHigh - bHigh) / c_atr
            if not isSupply and not isDemand: continue
            
            legInStart = max(0, baseStart - LegInBars)
            legInMove = closes_h1[baseStart] - closes_h1[legInStart]
            zType = ("DBR" if legInMove < 0 else "RBR") if isDemand else ("RBD" if legInMove > 0 else "DBD")
            zDistal = bHigh if isSupply else bLow
            zProximal = bLow if isSupply else bHigh
            
            testCount = 0
            isBroken = False
            brokenBar = -1
            timeActive = times_h1[min(n - 1, baseEnd + DepartBars)]
            timeEnd = times_h1[min(n - 1, baseStart + MaxAgeBars)]
            
            for f in range(baseEnd + DepartBars + 1, min(n, baseStart + MaxAgeBars)):
                if isSupply:
                    if highs_h1[f] >= zProximal and lows_h1[f] <= zProximal: testCount += 1
                    if closes_h1[f] > zDistal:
                        isBroken = True
                        brokenBar = f
                        timeEnd = times_h1[f]
                        break
                else:
                    if lows_h1[f] <= zProximal and highs_h1[f] >= zProximal: testCount += 1
                    if closes_h1[f] < zDistal:
                        isBroken = True
                        brokenBar = f
                        timeEnd = times_h1[f]
                        break
                if testCount >= MaxTests:
                    timeEnd = times_h1[f]
                    break
                    
            scoreDep = min(WDepart, (depStr / DepartATR) * (WDepart * 0.7))
            scoreBase = WBase if baseLen == 1 else (WBase * 0.75 if baseLen == 2 else WBase * 0.5)
            scoreFresh = WFresh if testCount == 0 else (WFresh * 0.5 if testCount == 1 else (WFresh * 0.25 if testCount == 2 else 0.0))
            scoreRev = WReversal if (zType in ["DBR", "RBD"]) else (WReversal * 0.5)
            scoreMtf = WMtf
            score = int(round(min(100.0, scoreDep + scoreBase + scoreFresh + scoreRev + scoreMtf)))
            
            if score >= MinScoreShow:
                zones.append({
                    'isSupply': isSupply,
                    'type': zType,
                    'timeActive': timeActive,
                    'timeEnd': timeEnd,
                    'distal': zDistal,
                    'proximal': zProximal,
                    'score': score,
                    'isFlip': False
                })
                
            if isBroken and brokenBar > 0:
                flipLife = min(n - 1, brokenBar + FlipLifeBars)
                flipSupply = not isSupply
                fDistal = zProximal
                fProximal = zDistal
                fTests = 0
                fBroken = False
                fTimeActive = times_h1[brokenBar]
                fTimeEnd = times_h1[flipLife]
                
                for k in range(brokenBar + 1, flipLife + 1):
                    if flipSupply:
                        if highs_h1[k] >= fProximal and lows_h1[k] <= fProximal: fTests += 1
                        if closes_h1[k] > fDistal: fBroken = True; fTimeEnd = times_h1[k]; break
                    else:
                        if lows_h1[k] <= fProximal and highs_h1[k] >= fProximal: fTests += 1
                        if closes_h1[k] < fDistal: fBroken = True; fTimeEnd = times_h1[k]; break
                    if fTests >= MaxTests: fTimeEnd = times_h1[k]; break
                    
                if not fBroken:
                    fScore = int(round(score * 0.85))
                    if fScore >= MinScoreShow:
                        zones.append({
                            'isSupply': flipSupply,
                            'type': 'FLIP',
                            'timeActive': fTimeActive,
                            'timeEnd': fTimeEnd,
                            'distal': fDistal,
                            'proximal': fProximal,
                            'score': fScore,
                            'isFlip': True
                        })
            i += baseLen
            found_base = True
            break
        if not found_base: i += 1
        
    return zones

def main():
    print("Testing 5-year data loading and zone extraction...")
    t0 = time.time()
    mt5.initialize()
    from_dt = datetime(2021, 10, 20, 0, 0, 0, tzinfo=timezone.utc)
    to_dt = datetime(2026, 10, 20, 0, 0, 0, tzinfo=timezone.utc)
    rates_h1 = mt5.copy_rates_range('XAUUSD', mt5.TIMEFRAME_H1, from_dt, to_dt)
    rates_m5 = mt5.copy_rates_range('XAUUSD', mt5.TIMEFRAME_M5, from_dt, to_dt)
    mt5.shutdown()
    
    times_h1 = rates_h1['time'].astype(np.int64)
    opens_h1 = rates_h1['open'].astype(np.float64)
    highs_h1 = rates_h1['high'].astype(np.float64)
    lows_h1 = rates_h1['low'].astype(np.float64)
    closes_h1 = rates_h1['close'].astype(np.float64)
    atr_h1 = compute_wilder_atr(highs_h1, lows_h1, closes_h1, 14)
    
    zones = build_h1_zones(times_h1, opens_h1, highs_h1, lows_h1, closes_h1, atr_h1)
    t1 = time.time()
    print(f"Loaded {len(rates_m5)} M5 bars and {len(rates_h1)} H1 bars.")
    print(f"Built {len(zones)} active H1 zones in {t1 - t0:.2f}s")

if __name__ == '__main__':
    main()
