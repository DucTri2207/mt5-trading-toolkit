import sys
from datetime import datetime, timezone
import numpy as np

if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')

import MetaTrader5 as mt5

def compute_wilder_atr(highs, lows, closes, period=14):
    n = len(highs)
    if n == 0:
        return np.array([])
    tr = np.zeros(n)
    tr[0] = highs[0] - lows[0]
    for i in range(1, n):
        tr[i] = max(highs[i] - lows[i], abs(highs[i] - closes[i-1]), abs(lows[i] - closes[i-1]))
    atr = np.zeros(n)
    if n < period:
        return atr
    atr[period - 1] = np.mean(tr[:period])
    for i in range(period, n):
        atr[i] = (atr[i-1] * (period - 1) + tr[i]) / period
    return atr

# Constants matching MQL5
BaseMaxBars = 5
BaseBarATR = 0.8
BaseTotalATR = 2.0
DepartATR = 1.8
DepartBars = 4
LegInBars = 15
AtrLen = 14
MaxHistory = 2000
MaxTests = 4
UseFlip = True
FlipLifeBars = 400
MinScoreShow = 35
WickRatioMin = 0.35
SlBufferATR = 0.5

WDepart = 40.0
WBase = 20.0
WFresh = 20.0
WReversal = 10.0
WMtf = 10.0

def scan_htf_macro_zones(hRates, hAtr):
    copied = len(hRates)
    if copied < LegInBars + BaseMaxBars + DepartBars + 15:
        return []
    
    startIdx = max(copied - MaxHistory, LegInBars + 5)
    endIdx = copied - DepartBars - 1
    
    zones = []
    
    i = startIdx
    while i <= endIdx:
        atr = hAtr[i]
        if atr <= 0:
            i += 1
            continue
            
        found_base = False
        for baseLen in range(1, BaseMaxBars + 1):
            baseStart = i
            baseEnd = i + baseLen - 1
            if baseEnd > endIdx:
                break
                
            bHigh = -1.0
            bLow = 9999999.0
            baseValid = True
            for b in range(baseStart, baseEnd + 1):
                rng = hRates[b]['high'] - hRates[b]['low']
                if rng > BaseBarATR * atr:
                    baseValid = False
                    break
                if hRates[b]['high'] > bHigh: bHigh = hRates[b]['high']
                if hRates[b]['low'] < bLow: bLow = hRates[b]['low']
            
            if not baseValid or (bHigh - bLow) > BaseTotalATR * atr:
                continue
                
            depLow = 9999999.0
            depHigh = -1.0
            for d in range(baseEnd + 1, min(copied, baseEnd + DepartBars + 1)):
                if hRates[d]['low'] < depLow: depLow = hRates[d]['low']
                if hRates[d]['high'] > depHigh: depHigh = hRates[d]['high']
                
            isSupply = False
            isDemand = False
            departureStrength = 0.0
            
            if (bLow - depLow) >= DepartATR * atr:
                isSupply = True
                departureStrength = (bLow - depLow) / atr
            elif (depHigh - bHigh) >= DepartATR * atr:
                isDemand = True
                departureStrength = (depHigh - bHigh) / atr
                
            if not isSupply and not isDemand:
                continue
                
            legInStart = max(0, baseStart - LegInBars)
            legInMove = hRates[baseStart]['close'] - hRates[legInStart]['close']
            if isDemand:
                zType = "DBR" if legInMove < 0 else "RBR"
            else:
                zType = "RBD" if legInMove > 0 else "DBD"
                
            zDistal = bHigh if isSupply else bLow
            zProximal = bLow if isSupply else bHigh
            
            testCount = 0
            isBroken = False
            brokenBar = -1
            timeEnd = hRates[-1]['time']
            
            for f in range(baseEnd + DepartBars + 1, copied):
                if isSupply:
                    if hRates[f]['high'] >= zProximal and hRates[f]['low'] <= zProximal:
                        testCount += 1
                    if hRates[f]['close'] > zDistal:
                        isBroken = True
                        brokenBar = f
                        timeEnd = hRates[f]['time']
                        break
                else:
                    if hRates[f]['low'] <= zProximal and hRates[f]['high'] >= zProximal:
                        testCount += 1
                    if hRates[f]['close'] < zDistal:
                        isBroken = True
                        brokenBar = f
                        timeEnd = hRates[f]['time']
                        break
                if testCount >= MaxTests:
                    timeEnd = hRates[f]['time']
                    break
                    
            scoreDep = min(WDepart, (departureStrength / DepartATR) * (WDepart * 0.7))
            scoreBase = WBase if baseLen == 1 else (WBase * 0.75 if baseLen == 2 else WBase * 0.5)
            scoreFresh = WFresh if testCount == 0 else (WFresh * 0.5 if testCount == 1 else (WFresh * 0.25 if testCount == 2 else 0.0))
            scoreRev = WReversal if (zType == "DBR" or zType == "RBD") else (WReversal * 0.5)
            scoreMtf = WMtf
            
            score = scoreDep + scoreBase + scoreFresh + scoreRev + scoreMtf
            if score > 100.0: score = 100.0
            
            zone = {
                'id': len(zones) + 1,
                'type': zType,
                'isSupply': isSupply,
                'timeStart': hRates[baseStart]['time'],
                'timeEnd': timeEnd,
                'distal': zDistal,
                'proximal': zProximal,
                'testCount': testCount,
                'isFresh': (testCount == 0),
                'isBroken': isBroken,
                'isFlip': False,
                'score': int(round(score)),
                'departAtr': departureStrength,
                'baseBars': baseLen,
                'ageBars': copied - 1 - baseStart
            }
            zones.append(zone)
            
            if isBroken and UseFlip and brokenBar > 0:
                flipLife = min(copied - 1, brokenBar + FlipLifeBars)
                flipSupply = not isSupply
                fDistal = zProximal
                fProximal = zDistal
                
                fTests = 0
                fBroken = False
                fTimeEnd = hRates[flipLife]['time']
                
                for k in range(brokenBar + 1, copied):
                    if k > flipLife: break
                    if flipSupply:
                        if hRates[k]['high'] >= fProximal and hRates[k]['low'] <= fProximal:
                            fTests += 1
                        if hRates[k]['close'] > fDistal:
                            fBroken = True
                            fTimeEnd = hRates[k]['time']
                            break
                    else:
                        if hRates[k]['low'] <= fProximal and hRates[k]['high'] >= fProximal:
                            fTests += 1
                        if hRates[k]['close'] < fDistal:
                            fBroken = True
                            fTimeEnd = hRates[k]['time']
                            break
                    if fTests >= MaxTests:
                        fTimeEnd = hRates[k]['time']
                        break
                        
                if not fBroken:
                    flipZ = {
                        'id': len(zones) + 1,
                        'type': "FLIP",
                        'isSupply': flipSupply,
                        'timeStart': hRates[brokenBar]['time'],
                        'timeEnd': fTimeEnd,
                        'distal': fDistal,
                        'proximal': fProximal,
                        'testCount': fTests,
                        'isFresh': (fTests == 0),
                        'isBroken': False,
                        'isFlip': True,
                        'score': int(round(score * 0.85)),
                        'departAtr': departureStrength,
                        'baseBars': baseLen,
                        'ageBars': copied - 1 - brokenBar
                    }
                    zones.append(flipZ)
            i += baseLen
            found_base = True
            break
        if not found_base:
            i += 1
            
    return zones

def detect_ltf_confirmation(zones, ltfRates, ltfAtr):
    copied = len(ltfRates)
    if copied < 30:
        return None
        
    for z in zones:
        if z['isBroken'] or z['score'] < MinScoreShow:
            continue
            
        zMin = min(z['distal'], z['proximal'])
        zMax = max(z['distal'], z['proximal'])
        isSupply = z['isSupply']
        
        # 1. Price in zone (in last 20 bars)
        priceInZone = False
        for k in range(min(21, copied)):
            if isSupply:
                if ltfRates[k]['high'] >= zMin - 0.2 * ltfAtr and ltfRates[k]['low'] <= zMax + 0.5 * ltfAtr:
                    priceInZone = True
                    break
            else:
                if ltfRates[k]['low'] <= zMax + 0.2 * ltfAtr and ltfRates[k]['high'] >= zMin - 0.5 * ltfAtr:
                    priceInZone = True
                    break
                    
        if not priceInZone:
            continue
            
        # 2. Wick rejection sweep
        sweepFound = False
        sweepBar = -1
        sweepPrice = -1.0 if isSupply else 9999999.0
        
        for s in range(1, min(21, copied)):
            fullRng = ltfRates[s]['high'] - ltfRates[s]['low']
            if fullRng < 0.25 * ltfAtr:
                continue
            if isSupply:
                upperWick = ltfRates[s]['high'] - max(ltfRates[s]['open'], ltfRates[s]['close'])
                wickRatio = upperWick / fullRng
                if wickRatio >= WickRatioMin and ltfRates[s]['high'] >= zMin:
                    if ltfRates[s]['high'] > sweepPrice:
                        sweepPrice = ltfRates[s]['high']
                        sweepBar = s
                        sweepFound = True
            else:
                lowerWick = min(ltfRates[s]['open'], ltfRates[s]['close']) - ltfRates[s]['low']
                wickRatio = lowerWick / fullRng
                if wickRatio >= WickRatioMin and ltfRates[s]['low'] <= zMax:
                    if ltfRates[s]['low'] < sweepPrice:
                        sweepPrice = ltfRates[s]['low']
                        sweepBar = s
                        sweepFound = True
                        
        if not sweepFound or sweepBar < 1:
            continue
            
        # 3. Inducement minor swing pivot
        swStart = sweepBar + 1
        swEnd = min(copied - 2, sweepBar + 8)
        
        if isSupply:
            chochLevel = 9999999.0
            foundPivot = False
            for sw in range(swStart, swEnd + 1):
                if sw > 0 and sw < copied - 1:
                    if ltfRates[sw]['low'] <= ltfRates[sw-1]['low'] and ltfRates[sw]['low'] <= ltfRates[sw+1]['low']:
                        chochLevel = ltfRates[sw]['low']
                        foundPivot = True
                        break
            if not foundPivot:
                for sw in range(swStart, min(copied, sweepBar + 5)):
                    if ltfRates[sw]['low'] < chochLevel:
                        chochLevel = ltfRates[sw]['low']
        else:
            chochLevel = -1.0
            foundPivot = False
            for sw in range(swStart, swEnd + 1):
                if sw > 0 and sw < copied - 1:
                    if ltfRates[sw]['high'] >= ltfRates[sw-1]['high'] and ltfRates[sw]['high'] >= ltfRates[sw+1]['high']:
                        chochLevel = ltfRates[sw]['high']
                        foundPivot = True
                        break
            if not foundPivot:
                for sw in range(swStart, min(copied, sweepBar + 5)):
                    if ltfRates[sw]['high'] > chochLevel:
                        chochLevel = ltfRates[sw]['high']
                        
        # 4. Confirmation candle
        isBuySignal = not isSupply
        confirmBar = -1
        
        for c in range(sweepBar - 1, 0, -1):
            if isBuySignal:
                if chochLevel > 0 and ltfRates[c]['close'] > chochLevel and ltfRates[c]['close'] > ltfRates[c]['open']:
                    priorBreak = False
                    for p in range(sweepBar - 1, c, -1):
                        if ltfRates[p]['close'] > chochLevel:
                            priorBreak = True
                            break
                    if not priorBreak:
                        confirmBar = c
                        break
            else:
                if chochLevel < 9999990.0 and ltfRates[c]['close'] < chochLevel and ltfRates[c]['close'] < ltfRates[c]['open']:
                    priorBreak = False
                    for p in range(sweepBar - 1, c, -1):
                        if ltfRates[p]['close'] < chochLevel:
                            priorBreak = True
                            break
                    if not priorBreak:
                        confirmBar = c
                        break
                        
        if confirmBar == 1:
            entry = ltfRates[1]['close']
            if isBuySignal:
                sl = sweepPrice - (SlBufferATR * ltfAtr)
                risk = entry - sl
                if risk <= 0:
                    risk = 1.0 * ltfAtr
                    sl = entry - risk
                tp1 = entry + 1.5 * risk
                tp2 = entry + 2.0 * risk
            else:
                sl = sweepPrice + (SlBufferATR * ltfAtr)
                risk = sl - entry
                if risk <= 0:
                    risk = 1.0 * ltfAtr
                    sl = entry + risk
                tp1 = entry - 1.5 * risk
                tp2 = entry - 2.0 * risk
                
            return {
                'isBuy': isBuySignal,
                'barTime': ltfRates[1]['time'],
                'entry': entry,
                'sl': sl,
                'tp1': tp1,
                'tp2': tp2,
                'risk': risk,
                'zoneType': z['type'],
                'zoneScore': z['score'],
                'sweepPrice': sweepPrice,
                'chochLevel': chochLevel
            }
            
    return None

def main():
    mt5.initialize()
    # Fetch all H1 bars
    all_h1 = mt5.copy_rates_from_pos('XAUUSD', mt5.TIMEFRAME_H1, 0, 1500)
    all_m5 = mt5.copy_rates_from_pos('XAUUSD', mt5.TIMEFRAME_M5, 0, 2000)
    mt5.shutdown()
    
    print(f"Total H1: {len(all_h1)}, Total M5: {len(all_m5)}")
    
    # Pre-calculate M5 ATR
    m5_highs = [r['high'] for r in all_m5]
    m5_lows = [r['low'] for r in all_m5]
    m5_closes = [r['close'] for r in all_m5]
    m5_atrs = compute_wilder_atr(m5_highs, m5_lows, m5_closes, period=14)
    
    # We want to scan M5 bars for yesterday: 2026-10-19 01:00 to 2026-10-20 00:00 UTC
    t_start = int(datetime(2026, 10, 19, 1, 0, 0, tzinfo=timezone.utc).timestamp())
    t_end = int(datetime(2026, 10, 20, 0, 0, 0, tzinfo=timezone.utc).timestamp())
    
    m5_times = [r['time'] for r in all_m5]
    h1_times = [r['time'] for r in all_h1]
    
    signals = []
    
    for idx, r in enumerate(all_m5):
        t = r['time']
        if t < t_start or t > t_end:
            continue
            
        # At bar idx, the bar idx is forming (bar 0 in series), bar idx-1 just closed (bar 1 in series)
        # We need the series of M5 up to idx (reversed, so idx is 0, idx-1 is 1, etc.)
        if idx < 300:
            continue
            
        sub_m5 = all_m5[max(0, idx - 349) : idx + 1]
        # Invert to series: index 0 is current forming, 1 is closed
        ltfSeries = sub_m5[::-1]
        ltfAtr = m5_atrs[idx - 1]
        
        # Get H1 rates up to current time t
        # In MQL5: CopyRates(_Symbol, PERIOD_H1, 0, 2000, hRates)
        # This copies H1 bars where bar 0 is the H1 bar containing time t
        h1_idx = np.searchsorted(h1_times, t, side='right') - 1
        if h1_idx < 100:
            continue
        sub_h1 = all_h1[max(0, h1_idx - 1999) : h1_idx + 1]
        
        h1_highs = [x['high'] for x in sub_h1]
        h1_lows = [x['low'] for x in sub_h1]
        h1_closes = [x['close'] for x in sub_h1]
        h1_atrs = compute_wilder_atr(h1_highs, h1_lows, h1_closes, period=14)
        
        zones = scan_htf_macro_zones(sub_h1, h1_atrs)
        sig = detect_ltf_confirmation(zones, ltfSeries, ltfAtr)
        if sig is not None:
            sig_time = datetime.fromtimestamp(sig['barTime'], tz=timezone.utc)
            # check if not already added
            if not any(s['barTime'] == sig['barTime'] for s in signals):
                signals.append(sig)
                print(f"--> FOUND SIGNAL at {sig_time}: {'BUY' if sig['isBuy'] else 'SELL'} @ {sig['entry']} | SL: {sig['sl']} | TP1: {sig['tp1']} | TP2: {sig['tp2']} | Zone: {sig['zoneType']} ({sig['zoneScore']})")

    print(f"\nTOTAL SIGNALS FOUND ON 2026-10-19: {len(signals)}")

if __name__ == '__main__':
    main()
