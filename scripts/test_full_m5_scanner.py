import sys, time
from datetime import datetime, timezone
import numpy as np

if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')

import MetaTrader5 as mt5
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
from scripts.test_m5_scanning_speed import build_h1_zones, compute_wilder_atr

def is_in_killzone(bar_time):
    dt = datetime.fromtimestamp(bar_time, tz=timezone.utc)
    h = dt.hour
    return (8 <= h <= 12) or (13 <= h <= 17)

def scan_all_m5_signals():
    print("=" * 70)
    print("QUÉT TÍN HIỆU 5 NĂM VÀNG (XAUUSD) M5 (2021 - 2026)")
    print("=" * 70)
    t0 = time.time()
    
    mt5.initialize()
    from_dt = datetime(2021, 10, 20, 0, 0, 0, tzinfo=timezone.utc)
    to_dt = datetime(2026, 10, 20, 0, 0, 0, tzinfo=timezone.utc)
    rates_h1 = mt5.copy_rates_range('XAUUSD', mt5.TIMEFRAME_H1, from_dt, to_dt)
    rates_m5 = mt5.copy_rates_range('XAUUSD', mt5.TIMEFRAME_M5, from_dt, to_dt)
    mt5.shutdown()
    
    times_h1 = rates_h1['time'].astype(np.int64)
    highs_h1 = rates_h1['high'].astype(np.float64)
    lows_h1 = rates_h1['low'].astype(np.float64)
    closes_h1 = rates_h1['close'].astype(np.float64)
    atr_h1 = compute_wilder_atr(highs_h1, lows_h1, closes_h1, 14)
    zones = build_h1_zones(times_h1, rates_h1['open'].astype(np.float64), highs_h1, lows_h1, closes_h1, atr_h1)
    
    # Bucket active zones for each H1 bar
    h1_zones = [[] for _ in range(len(times_h1))]
    for z in zones:
        idx_start = max(0, np.searchsorted(times_h1, z['timeActive'], side='left'))
        idx_end = min(len(times_h1) - 1, np.searchsorted(times_h1, z['timeEnd'], side='right'))
        for k in range(idx_start, idx_end + 1):
            h1_zones[k].append(z)
            
    times_m5 = rates_m5['time'].astype(np.int64)
    opens_m5 = rates_m5['open'].astype(np.float64)
    highs_m5 = rates_m5['high'].astype(np.float64)
    lows_m5 = rates_m5['low'].astype(np.float64)
    closes_m5 = rates_m5['close'].astype(np.float64)
    atr_m5 = compute_wilder_atr(highs_m5, lows_m5, closes_m5, 14)
    
    n_m5 = len(times_m5)
    print(f"Bắt đầu quét {n_m5} nến M5...")
    
    signals = []
    
    for m in range(30, n_m5):
        t_m = times_m5[m]
        # At bar m, bar m is forming, bar m-1 just closed
        c_atr = atr_m5[m - 1]
        if c_atr <= 0:
            continue
            
        h_idx = np.searchsorted(times_h1, t_m, side='right') - 1
        if h_idx < 0 or h_idx >= len(h1_zones):
            continue
            
        cur_zones = h1_zones[h_idx]
        if not cur_zones:
            continue
            
        # Check confirmation on closed bar m-1
        sig_found = False
        for z in cur_zones:
            zMin = min(z['distal'], z['proximal'])
            zMax = max(z['distal'], z['proximal'])
            isSupply = z['isSupply']
            
            # 1. Price in zone (in last 20 bars: m-1 down to m-21)
            priceInZone = False
            for k in range(m - 1, max(-1, m - 22), -1):
                if isSupply:
                    if highs_m5[k] >= zMin - 0.2 * c_atr and lows_m5[k] <= zMax + 0.5 * c_atr:
                        priceInZone = True
                        break
                else:
                    if lows_m5[k] <= zMax + 0.2 * c_atr and highs_m5[k] >= zMin - 0.5 * c_atr:
                        priceInZone = True
                        break
            if not priceInZone:
                continue
                
            # 2. Sweep rejection wick in last 20 bars
            sweepFound = False
            sweepBar = -1 # relative offset from m: 1 is m-1, 2 is m-2, etc.
            sweepPrice = -1.0 if isSupply else 9999999.0
            
            for s in range(1, 21):
                idx = m - s
                if idx < 0: break
                fullRng = highs_m5[idx] - lows_m5[idx]
                if fullRng < 0.25 * c_atr: continue
                if isSupply:
                    upperWick = highs_m5[idx] - max(opens_m5[idx], closes_m5[idx])
                    if (upperWick / fullRng) >= 0.35 and highs_m5[idx] >= zMin:
                        if highs_m5[idx] > sweepPrice:
                            sweepPrice = highs_m5[idx]
                            sweepBar = s
                            sweepFound = True
                else:
                    lowerWick = min(opens_m5[idx], closes_m5[idx]) - lows_m5[idx]
                    if (lowerWick / fullRng) >= 0.35 and lows_m5[idx] <= zMax:
                        if lows_m5[idx] < sweepPrice:
                            sweepPrice = lows_m5[idx]
                            sweepBar = s
                            sweepFound = True
                            
            if not sweepFound or sweepBar < 1:
                continue
                
            # 3. Inducement pivot in sweepBar+1 .. sweepBar+8
            swStart = sweepBar + 1
            swEnd = min(25, sweepBar + 8)
            chochLevel = 9999999.0 if isSupply else -1.0
            foundPivot = False
            
            for sw in range(swStart, swEnd + 1):
                idx = m - sw
                if idx > 0 and idx < n_m5 - 1:
                    if isSupply:
                        if lows_m5[idx] <= lows_m5[idx - 1] and lows_m5[idx] <= lows_m5[idx + 1]:
                            chochLevel = lows_m5[idx]
                            foundPivot = True
                            break
                    else:
                        if highs_m5[idx] >= highs_m5[idx - 1] and highs_m5[idx] >= highs_m5[idx + 1]:
                            chochLevel = highs_m5[idx]
                            foundPivot = True
                            break
            if not foundPivot:
                for sw in range(swStart, min(25, sweepBar + 5)):
                    idx = m - sw
                    if idx >= 0:
                        if isSupply:
                            if lows_m5[idx] < chochLevel: chochLevel = lows_m5[idx]
                        else:
                            if highs_m5[idx] > chochLevel: chochLevel = highs_m5[idx]
                            
            # 4. Confirmation candle
            confirmBar = -1
            isBuySignal = not isSupply
            
            for c in range(sweepBar - 1, 0, -1):
                idx = m - c
                if isBuySignal:
                    if chochLevel > 0 and closes_m5[idx] > chochLevel and closes_m5[idx] > opens_m5[idx]:
                        priorBreak = False
                        for p in range(sweepBar - 1, c, -1):
                            if closes_m5[m - p] > chochLevel:
                                priorBreak = True
                                break
                        if not priorBreak:
                            confirmBar = c
                            break
                else:
                    if chochLevel < 9999990.0 and closes_m5[idx] < chochLevel and closes_m5[idx] < opens_m5[idx]:
                        priorBreak = False
                        for p in range(sweepBar - 1, c, -1):
                            if closes_m5[m - p] < chochLevel:
                                priorBreak = True
                                break
                        if not priorBreak:
                            confirmBar = c
                            break
                            
            if confirmBar == 1:
                cIdx = m - 1
                entryMkt = closes_m5[cIdx]
                cBarLow = lows_m5[cIdx]
                cBarHigh = highs_m5[cIdx]
                cBarOpen = opens_m5[cIdx]
                
                # --- OLD MECHANISM SL & TP ---
                if isBuySignal:
                    sl_old = sweepPrice - 0.5 * c_atr
                    risk_old = max(1.0 * c_atr, entryMkt - sl_old)
                    tp1_old = entryMkt + 1.5 * risk_old
                    tp2_old = entryMkt + 2.0 * risk_old
                else:
                    sl_old = sweepPrice + 0.5 * c_atr
                    risk_old = max(1.0 * c_atr, sl_old - entryMkt)
                    tp1_old = entryMkt - 1.5 * risk_old
                    tp2_old = entryMkt - 2.0 * risk_old
                    
                # --- NEW MECHANISM: Structural Swing SL ---
                # Search lowest low / highest high from confirm candle to sweep candle
                lookback_end = min(m, m - 1 + max(4, sweepBar))
                if isBuySignal:
                    swingLow = sweepPrice
                    for b in range(m - 1, max(0, m - 1 - max(4, sweepBar)), -1):
                        if lows_m5[b] < swingLow: swingLow = lows_m5[b]
                    sl_new_struct = swingLow - 0.5 * c_atr
                    # Cap Max SL to 100 pips ($10.0)
                    if (entryMkt - sl_new_struct) > 10.0:
                        sl_new_struct = entryMkt - 10.0
                    risk_new_mkt = max(1.0 * c_atr, entryMkt - sl_new_struct)
                    tp1_new_mkt = entryMkt + 6.0 # Hybrid 60 pips = $6.0
                    tp2_new_mkt = entryMkt + 2.0 * risk_new_mkt
                    entry_limit_50 = 0.5 * (cBarOpen + entryMkt)
                    risk_new_limit = max(1.0 * c_atr, entry_limit_50 - sl_new_struct)
                    tp1_new_limit = entry_limit_50 + 6.0
                    tp2_new_limit = entry_limit_50 + 2.0 * risk_new_limit
                else:
                    swingHigh = sweepPrice
                    for b in range(m - 1, max(0, m - 1 - max(4, sweepBar)), -1):
                        if highs_m5[b] > swingHigh: swingHigh = highs_m5[b]
                    sl_new_struct = swingHigh + 0.5 * c_atr
                    if (sl_new_struct - entryMkt) > 10.0:
                        sl_new_struct = entryMkt + 10.0
                    risk_new_mkt = max(1.0 * c_atr, sl_new_struct - entryMkt)
                    tp1_new_mkt = entryMkt - 6.0 # Hybrid 60 pips = $6.0
                    tp2_new_mkt = entryMkt - 2.0 * risk_new_mkt
                    entry_limit_50 = 0.5 * (cBarOpen + entryMkt)
                    risk_new_limit = max(1.0 * c_atr, sl_new_struct - entry_limit_50)
                    tp1_new_limit = entry_limit_50 - 6.0
                    tp2_new_limit = entry_limit_50 - 2.0 * risk_new_limit
                    
                signals.append({
                    'idx': cIdx,
                    'time': times_m5[cIdx],
                    'isBuy': isBuySignal,
                    'kz': is_in_killzone(times_m5[cIdx]),
                    'entryMkt': entryMkt,
                    'cBarOpen': cBarOpen,
                    'cBarHigh': cBarHigh,
                    'cBarLow': cBarLow,
                    'entryLimit50': entry_limit_50,
                    # Old model
                    'sl_old': sl_old,
                    'risk_old': risk_old,
                    'tp1_old': tp1_old,
                    'tp2_old': tp2_old,
                    # New model Market
                    'sl_new': sl_new_struct,
                    'risk_new_mkt': risk_new_mkt,
                    'tp1_new_mkt': tp1_new_mkt,
                    'tp2_new_mkt': tp2_new_mkt,
                    # New model Limit
                    'risk_new_limit': risk_new_limit,
                    'tp1_new_limit': tp1_new_limit,
                    'tp2_new_limit': tp2_new_limit,
                    'zoneType': z['type'],
                    'zoneScore': z['score']
                })
                sig_found = True
                break
                
    t1 = time.time()
    print(f"Quét hoàn tất trong {t1 - t0:.2f}s!")
    print(f"Tổng số tín hiệu M5 CHoCH tìm thấy trong 5 năm: {len(signals)}")
    return signals, rates_m5

if __name__ == '__main__':
    scan_all_m5_signals()
