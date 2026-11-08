import sys, time, os
from datetime import datetime, timezone
import numpy as np

if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')

import MetaTrader5 as mt5
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
from scripts.test_m5_scanning_speed import build_h1_zones, compute_wilder_atr

def is_in_killzone(bar_time):
    dt = datetime.fromtimestamp(bar_time, tz=timezone.utc)
    h = dt.hour
    return (8 <= h <= 12) or (13 <= h <= 17)

def main():
    print("=" * 85)
    print("BÁO CÁO BACKTEST ĐỊNH LƯỢNG 5 NĂM VÀNG (XAUUSD M5): 2021 - 2026")
    print("SO SÁNH TOÀN DIỆN CƠ CHẾ CŨ VÀ CƠ CHẾ NÂNG CẤP MỚI")
    print("=" * 85)
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
    print(f"Dữ liệu: {n_m5} nến M5 (2021.10.20 - 2026.10.19)")
    print(f"Quét nhận diện tín hiệu SMC CHoCH M5...")
    
    signals = []
    
    for m in range(30, n_m5):
        t_m = times_m5[m]
        c_atr = atr_m5[m - 1]
        if c_atr <= 0: continue
        h_idx = np.searchsorted(times_h1, t_m, side='right') - 1
        if h_idx < 0 or h_idx >= len(h1_zones): continue
        cur_zones = h1_zones[h_idx]
        if not cur_zones: continue
        
        for z in cur_zones:
            zMin = min(z['distal'], z['proximal'])
            zMax = max(z['distal'], z['proximal'])
            isSupply = z['isSupply']
            
            # Price in zone in last 20 bars
            priceInZone = False
            for k in range(m - 1, max(-1, m - 22), -1):
                if isSupply:
                    if highs_m5[k] >= zMin - 0.2 * c_atr and lows_m5[k] <= zMax + 0.5 * c_atr:
                        priceInZone = True; break
                else:
                    if lows_m5[k] <= zMax + 0.2 * c_atr and highs_m5[k] >= zMin - 0.5 * c_atr:
                        priceInZone = True; break
            if not priceInZone: continue
            
            # Sweep wick in last 20 bars
            sweepFound = False
            sweepBar = -1
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
            if not sweepFound or sweepBar < 1: continue
            
            # Inducement pivot
            swStart = sweepBar + 1
            swEnd = min(25, sweepBar + 8)
            chochLevel = 9999999.0 if isSupply else -1.0
            foundPivot = False
            for sw in range(swStart, swEnd + 1):
                idx = m - sw
                if idx > 0 and idx < n_m5 - 1:
                    if isSupply:
                        if lows_m5[idx] <= lows_m5[idx - 1] and lows_m5[idx] <= lows_m5[idx + 1]:
                            chochLevel = lows_m5[idx]; foundPivot = True; break
                    else:
                        if highs_m5[idx] >= highs_m5[idx - 1] and highs_m5[idx] >= highs_m5[idx + 1]:
                            chochLevel = highs_m5[idx]; foundPivot = True; break
            if not foundPivot:
                for sw in range(swStart, min(25, sweepBar + 5)):
                    idx = m - sw
                    if idx >= 0:
                        if isSupply:
                            if lows_m5[idx] < chochLevel: chochLevel = lows_m5[idx]
                        else:
                            if highs_m5[idx] > chochLevel: chochLevel = highs_m5[idx]
                            
            # Confirm candle
            confirmBar = -1
            isBuySignal = not isSupply
            for c in range(sweepBar - 1, 0, -1):
                idx = m - c
                if isBuySignal:
                    if chochLevel > 0 and closes_m5[idx] > chochLevel and closes_m5[idx] > opens_m5[idx]:
                        priorBreak = False
                        for p in range(sweepBar - 1, c, -1):
                            if closes_m5[m - p] > chochLevel: priorBreak = True; break
                        if not priorBreak: confirmBar = c; break
                else:
                    if chochLevel < 9999990.0 and closes_m5[idx] < chochLevel and closes_m5[idx] < opens_m5[idx]:
                        priorBreak = False
                        for p in range(sweepBar - 1, c, -1):
                            if closes_m5[m - p] < chochLevel: priorBreak = True; break
                        if not priorBreak: confirmBar = c; break
                        
            if confirmBar == 1:
                cIdx = m - 1
                entryMkt = closes_m5[cIdx]
                cBarOpen = opens_m5[cIdx]
                cBarHigh = highs_m5[cIdx]
                cBarLow = lows_m5[cIdx]
                
                # --- MODEL 1: CƠ CHẾ CŨ ---
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
                    
                # --- MODEL 2: CƠ CHẾ MỚI STRUCTURAL SL & AUTO BE ---
                if isBuySignal:
                    swingLow = sweepPrice
                    for b in range(m - 1, max(0, m - 1 - max(4, sweepBar)), -1):
                        if lows_m5[b] < swingLow: swingLow = lows_m5[b]
                    sl_new = swingLow - 0.5 * c_atr
                    if (entryMkt - sl_new) > 10.0: sl_new = entryMkt - 10.0 # Cap max 100 pips
                    risk_new_mkt = max(1.0 * c_atr, entryMkt - sl_new)
                    tp1_new_mkt = entryMkt + 6.0 # Hybrid 60 pips = $6.0
                    tp2_new_mkt = entryMkt + 2.0 * risk_new_mkt
                    
                    entry_limit = 0.5 * (cBarOpen + entryMkt)
                    risk_new_lmt = max(1.0 * c_atr, entry_limit - sl_new)
                    tp1_new_lmt = entry_limit + 6.0
                    tp2_new_lmt = entry_limit + 2.0 * risk_new_lmt
                else:
                    swingHigh = sweepPrice
                    for b in range(m - 1, max(0, m - 1 - max(4, sweepBar)), -1):
                        if highs_m5[b] > swingHigh: swingHigh = highs_m5[b]
                    sl_new = swingHigh + 0.5 * c_atr
                    if (sl_new - entryMkt) > 10.0: sl_new = entryMkt + 10.0 # Cap max 100 pips
                    risk_new_mkt = max(1.0 * c_atr, sl_new - entryMkt)
                    tp1_new_mkt = entryMkt - 6.0 # Hybrid 60 pips = $6.0
                    tp2_new_mkt = entryMkt - 2.0 * risk_new_mkt
                    
                    entry_limit = 0.5 * (cBarOpen + entryMkt)
                    risk_new_lmt = max(1.0 * c_atr, sl_new - entry_limit)
                    tp1_new_lmt = entry_limit - 6.0
                    tp2_new_lmt = entry_limit - 2.0 * risk_new_lmt
                    
                signals.append({
                    'idx': cIdx,
                    'time': times_m5[cIdx],
                    'year': datetime.fromtimestamp(times_m5[cIdx], tz=timezone.utc).year,
                    'isBuy': isBuySignal,
                    'kz': is_in_killzone(times_m5[cIdx]),
                    'entryMkt': entryMkt,
                    'entryLimit': entry_limit,
                    'sl_old': sl_old, 'risk_old': risk_old, 'tp1_old': tp1_old, 'tp2_old': tp2_old,
                    'sl_new': sl_new, 'risk_new_mkt': risk_new_mkt, 'tp1_new_mkt': tp1_new_mkt, 'tp2_new_mkt': tp2_new_mkt,
                    'risk_new_lmt': risk_new_lmt, 'tp1_new_lmt': tp1_new_lmt, 'tp2_new_lmt': tp2_new_lmt
                })
                break
                
    print(f"Tổng số tín hiệu phát hiện trong 5 năm: {len(signals)}")
    print(f"Đang chạy mô phỏng chi tiết 3 mô hình lệnh qua từng nến M5...")
    
    # Simulate trades
    # For each trade, track forward up to 288 bars (24 hours) or until exit
    max_hold = 288
    
    for s in signals:
        cIdx = s['idx']
        isBuy = s['isBuy']
        end_bar = min(n_m5, cIdx + 1 + max_hold)
        
        # --- 1. SIMULATE OLD MODEL (Wide SL, 1.5R/2.0R, No BE) ---
        r_old = -1.0 # default SL
        hit_tp1_old = False
        hit_tp2_old = False
        for j in range(cIdx + 1, end_bar):
            h = highs_m5[j]
            l = lows_m5[j]
            if isBuy:
                if not hit_tp1_old and h >= s['tp1_old']: hit_tp1_old = True
                if not hit_tp2_old and h >= s['tp2_old']: hit_tp2_old = True
                if l <= s['sl_old']:
                    break # hit SL
                if hit_tp2_old:
                    break
            else:
                if not hit_tp1_old and l <= s['tp1_old']: hit_tp1_old = True
                if not hit_tp2_old and l <= s['tp2_old']: hit_tp2_old = True
                if h >= s['sl_old']:
                    break # hit SL
                if hit_tp2_old:
                    break
        if hit_tp1_old:
            r_old = 1.75 if hit_tp2_old else 0.75
        else:
            r_old = -1.0
        s['r_old'] = r_old
        s['win_old'] = (r_old > 0)
        
        # --- 2. SIMULATE NEW MARKET MODEL (Structural SL, Auto BE @ 60p, TP1 60p, TP2 2.0R) ---
        r_new_mkt = -1.0
        hit_tp1_mkt = False
        hit_tp2_mkt = False
        be_active_mkt = False
        cur_sl_mkt = s['sl_new']
        mfe_mkt = 0.0
        
        for j in range(cIdx + 1, end_bar):
            h = highs_m5[j]
            l = lows_m5[j]
            if isBuy:
                cur_favorable = h - s['entryMkt']
                if cur_favorable > mfe_mkt: mfe_mkt = cur_favorable
                if not be_active_mkt and cur_favorable >= 6.0: # 60 pips
                    be_active_mkt = True
                    cur_sl_mkt = s['entryMkt'] + 0.1 # BE + 1 pip
                if not hit_tp1_mkt and h >= s['tp1_new_mkt']: hit_tp1_mkt = True
                if not hit_tp2_mkt and h >= s['tp2_new_mkt']: hit_tp2_mkt = True
                if l <= cur_sl_mkt:
                    break
                if hit_tp2_mkt:
                    break
            else:
                cur_favorable = s['entryMkt'] - l
                if cur_favorable > mfe_mkt: mfe_mkt = cur_favorable
                if not be_active_mkt and cur_favorable >= 6.0:
                    be_active_mkt = True
                    cur_sl_mkt = s['entryMkt'] - 0.1 # BE + 1 pip
                if not hit_tp1_mkt and l <= s['tp1_new_mkt']: hit_tp1_mkt = True
                if not hit_tp2_mkt and l <= s['tp2_new_mkt']: hit_tp2_mkt = True
                if h >= cur_sl_mkt:
                    break
                if hit_tp2_mkt:
                    break
                    
        if hit_tp1_mkt:
            r_new_mkt = 1.75 if hit_tp2_mkt else 0.75
        elif be_active_mkt:
            r_new_mkt = 0.0 # BE
        else:
            r_new_mkt = -1.0
            
        s['r_new_mkt'] = r_new_mkt
        s['win_new_mkt'] = (r_new_mkt > 0)
        s['be_new_mkt'] = (r_new_mkt == 0.0)
        s['loss_new_mkt'] = (r_new_mkt < 0)
        
        # --- 3. SIMULATE NEW LIMIT 50% MODEL ---
        filled_limit = False
        fill_bar = -1
        for j in range(cIdx + 1, min(n_m5, cIdx + 7)): # valid for 6 bars (30 min)
            if isBuy:
                if lows_m5[j] <= s['entryLimit']:
                    filled_limit = True
                    fill_bar = j
                    break
            else:
                if highs_m5[j] >= s['entryLimit']:
                    filled_limit = True
                    fill_bar = j
                    break
                    
        r_new_lmt = 0.0
        if filled_limit:
            hit_tp1_lmt = False
            hit_tp2_lmt = False
            be_active_lmt = False
            cur_sl_lmt = s['sl_new']
            mfe_lmt = 0.0
            
            for j in range(fill_bar, end_bar):
                h = highs_m5[j]
                l = lows_m5[j]
                if isBuy:
                    cur_favorable = h - s['entryLimit']
                    if cur_favorable > mfe_lmt: mfe_lmt = cur_favorable
                    if not be_active_lmt and cur_favorable >= 6.0:
                        be_active_lmt = True
                        cur_sl_lmt = s['entryLimit'] + 0.1
                    if not hit_tp1_lmt and h >= s['tp1_new_lmt']: hit_tp1_lmt = True
                    if not hit_tp2_lmt and h >= s['tp2_new_lmt']: hit_tp2_lmt = True
                    if l <= cur_sl_lmt: break
                    if hit_tp2_lmt: break
                else:
                    cur_favorable = s['entryLimit'] - l
                    if cur_favorable > mfe_lmt: mfe_lmt = cur_favorable
                    if not be_active_lmt and cur_favorable >= 6.0:
                        be_active_lmt = True
                        cur_sl_lmt = s['entryLimit'] - 0.1
                    if not hit_tp1_lmt and l <= s['tp1_new_lmt']: hit_tp1_lmt = True
                    if not hit_tp2_lmt and l <= s['tp2_new_lmt']: hit_tp2_lmt = True
                    if h >= cur_sl_lmt: break
                    if hit_tp2_lmt: break
            if hit_tp1_lmt:
                r_new_lmt = 1.75 if hit_tp2_lmt else 0.75
            elif be_active_lmt:
                r_new_lmt = 0.0
            else:
                r_new_lmt = -1.0
        else:
            r_new_lmt = 0.0 # Unfilled
            
        s['filled_lmt'] = filled_limit
        s['r_new_lmt'] = r_new_lmt
        s['win_new_lmt'] = (r_new_lmt > 0)
        s['loss_new_lmt'] = (r_new_lmt < 0)

    # Performance calculation helper
    def calc_metrics(sigs, key_r):
        n = len(sigs)
        if n == 0: return {}
        r_list = [x[key_r] for x in sigs]
        total_r = sum(r_list)
        wins = sum(1 for r in r_list if r > 0)
        bes = sum(1 for r in r_list if r == 0)
        losses = sum(1 for r in r_list if r < 0)
        win_rate = (wins / n) * 100
        gross_profit = sum(r for r in r_list if r > 0)
        gross_loss = abs(sum(r for r in r_list if r < 0))
        pf = (gross_profit / gross_loss) if gross_loss > 0 else 999.0
        
        # Max drawdown in R
        cum_r = np.cumsum(r_list)
        peak = np.maximum.accumulate(cum_r)
        dd = peak - cum_r
        max_dd_r = np.max(dd) if len(dd) > 0 else 0.0
        
        return {
            'total_trades': n,
            'wins': wins,
            'bes': bes,
            'losses': losses,
            'win_rate': win_rate,
            'total_r': total_r,
            'pf': pf,
            'max_dd_r': max_dd_r
        }

    # Print Results Table
    print("\n" + "=" * 95)
    print("BẢNG TỔNG KẾT HIỆU SUẤT ĐỊNH LƯỢNG 5 NĂM (2021 - 2026)")
    print("=" * 95)
    print(f"{'Tiêu chí đánh giá':<32} | {'MÔ HÌNH CŨ':<18} | {'MÔ HÌNH MỚI (Market)':<20} | {'MÔ HÌNH MỚI (Limit 50%)':<22}")
    print("-" * 95)
    
    m_old_all = calc_metrics(signals, 'r_old')
    m_new_mkt_all = calc_metrics(signals, 'r_new_mkt')
    m_new_lmt_all = calc_metrics(signals, 'r_new_lmt')
    
    print(f"{'1. TẤT CẢ TÍN HIỆU (24/5)':<32} | {'':<18} | {'':<20} | {''}")
    print(f"  - Tổng số lệnh phát sinh     | {m_old_all['total_trades']:<18} | {m_new_mkt_all['total_trades']:<20} | {m_new_lmt_all['total_trades']} (Khớp: {sum(1 for s in signals if s['filled_lmt'])})")
    print(f"  - Số lệnh Thắng (Ăn TP)      | {m_old_all['wins']} ({m_old_all['win_rate']:.1f}%)       | {m_new_mkt_all['wins']} ({m_new_mkt_all['win_rate']:.1f}%)       | {m_new_lmt_all['wins']} ({m_new_lmt_all['win_rate']:.1f}%)")
    print(f"  - Số lệnh Hòa vốn (BE)        | {m_old_all['bes']:<18} | {m_new_mkt_all['bes']} ({m_new_mkt_all['bes']/m_new_mkt_all['total_trades']*100:.1f}%)       | {m_new_lmt_all['bes']}")
    print(f"  - Số lệnh Thua cắn SL        | {m_old_all['losses']} ({m_old_all['losses']/m_old_all['total_trades']*100:.1f}%)      | {m_new_mkt_all['losses']} ({m_new_mkt_all['losses']/m_new_mkt_all['total_trades']*100:.1f}%)      | {m_new_lmt_all['losses']}")
    print(f"  - TỔNG LỢI NHUẬN (R)         | {m_old_all['total_r']:+.2f}R           | {m_new_mkt_all['total_r']:+.2f}R          | {m_new_lmt_all['total_r']:+.2f}R")
    print(f"  - Tỷ số Lời/Lỗ (Profit Factor)| {m_old_all['pf']:.2f}               | {m_new_mkt_all['pf']:.2f}                | {m_new_lmt_all['pf']:.2f}")
    print(f"  - Max Drawdown sụt giảm (R)  | {m_old_all['max_dd_r']:.2f}R             | {m_new_mkt_all['max_dd_r']:.2f}R             | {m_new_lmt_all['max_dd_r']:.2f}R")
    
    # Filter Killzones (London 08-12, NY 13-17)
    kz_signals = [s for s in signals if s['kz']]
    m_old_kz = calc_metrics(kz_signals, 'r_old')
    m_new_mkt_kz = calc_metrics(kz_signals, 'r_new_mkt')
    m_new_lmt_kz = calc_metrics(kz_signals, 'r_new_lmt')
    
    print("-" * 95)
    print(f"{'2. GIỜ VÀNG KILLZONES (Khuyên dùng)':<32} | {'':<18} | {'':<20} | {''}")
    print(f"  - Tổng số lệnh Killzones     | {m_old_kz['total_trades']:<18} | {m_new_mkt_kz['total_trades']:<20} | {m_new_lmt_kz['total_trades']}")
    print(f"  - Tỷ lệ Thắng (Ăn TP)        | {m_old_kz['wins']} ({m_old_kz['win_rate']:.1f}%)       | {m_new_mkt_kz['wins']} ({m_new_mkt_kz['win_rate']:.1f}%)       | {m_new_lmt_kz['wins']} ({m_new_lmt_kz['win_rate']:.1f}%)")
    print(f"  - Số lệnh Hòa vốn (BE)        | {m_old_kz['bes']:<18} | {m_new_mkt_kz['bes']} ({m_new_mkt_kz['bes']/m_old_kz['total_trades']*100:.1f}%)       | {m_new_lmt_kz['bes']}")
    print(f"  - Số lệnh Thua cắn SL        | {m_old_kz['losses']} ({m_old_kz['losses']/m_old_kz['total_trades']*100:.1f}%)      | {m_new_mkt_kz['losses']} ({m_new_mkt_kz['losses']/m_new_mkt_kz['total_trades']*100:.1f}%)      | {m_new_lmt_kz['losses']}")
    print(f"  - TỔNG LỢI NHUẬN (R)         | {m_old_kz['total_r']:+.2f}R           | {m_new_mkt_kz['total_r']:+.2f}R          | {m_new_lmt_kz['total_r']:+.2f}R")
    print(f"  - Tỷ số Lời/Lỗ (Profit Factor)| {m_old_kz['pf']:.2f}               | {m_new_mkt_kz['pf']:.2f}                | {m_new_lmt_kz['pf']:.2f}")
    print(f"  - Max Drawdown sụt giảm (R)  | {m_old_kz['max_dd_r']:.2f}R             | {m_new_mkt_kz['max_dd_r']:.2f}R             | {m_new_lmt_kz['max_dd_r']:.2f}R")
    
    # Yearly breakdown for New Market Model
    print("\n" + "=" * 95)
    print("CHI TIẾT LỢI NHUẬN TỪNG NĂM CỦA CƠ CHẾ NÂNG CẤP MỚI (MARKET + AUTO-BE):")
    print("=" * 95)
    print(f"{'Năm':<8} | {'Số lệnh':<8} | {'Win Rate (TP)':<14} | {'Hòa vốn (BE)':<14} | {'Thua (SL)':<12} | {'Tổng Lợi Nhuận (R)':<18} | {'Profit Factor':<12}")
    print("-" * 95)
    years = sorted(list(set(s['year'] for s in signals)))
    for y in years:
        y_sigs = [s for s in signals if s['year'] == y]
        ym = calc_metrics(y_sigs, 'r_new_mkt')
        print(f"{y:<8} | {ym['total_trades']:<8} | {ym['win_rate']:<5.1f}% ({ym['wins']:<3}) | {ym['bes']/ym['total_trades']*100:<5.1f}% ({ym['bes']:<3}) | {ym['losses']/ym['total_trades']*100:<5.1f}% ({ym['losses']:<3}) | {ym['total_r']:+8.2f}R           | {ym['pf']:<12.2f}")
    print("=" * 95)

if __name__ == '__main__':
    main()
