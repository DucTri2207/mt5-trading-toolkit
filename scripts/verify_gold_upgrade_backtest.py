import sys
from datetime import datetime, timezone
import numpy as np
import os

sys.path.insert(0, os.path.dirname(__file__))

import MetaTrader5 as mt5
from backtest_can_ho_tro_yesterday import scan_htf_macro_zones, compute_wilder_atr

def detect_choch_signals(all_m5, all_h1, t_start, t_end):
    m5_highs = [r['high'] for r in all_m5]
    m5_lows = [r['low'] for r in all_m5]
    m5_closes = [r['close'] for r in all_m5]
    m5_atrs = compute_wilder_atr(m5_highs, m5_lows, m5_closes, period=14)
    h1_times = [r['time'] for r in all_h1]

    raw_signals = []
    
    for idx, r in enumerate(all_m5):
        t = r['time']
        if t < t_start or t > t_end or idx < 300:
            continue
            
        sub_m5 = all_m5[max(0, idx - 349) : idx + 1]
        ltfSeries = sub_m5[::-1]
        ltfAtr = m5_atrs[idx - 1]
        
        h1_idx = int(np.searchsorted(h1_times, t, side='right') - 1)
        if h1_idx < 100:
            continue
        sub_h1 = all_h1[max(0, h1_idx - 1999) : h1_idx + 1]
        h1_highs = [x['high'] for x in sub_h1]
        h1_lows = [x['low'] for x in sub_h1]
        h1_closes = [x['close'] for x in sub_h1]
        h1_atrs = compute_wilder_atr(h1_highs, h1_lows, h1_closes, period=14)
        
        zones = scan_htf_macro_zones(sub_h1, h1_atrs)
        
        # Scan confirmation
        copied = len(ltfSeries)
        if copied < 30: continue
        
        for z in zones:
            if z['isBroken'] or z['score'] < 35: continue
            zMin = min(z['distal'], z['proximal'])
            zMax = max(z['distal'], z['proximal'])
            isSupply = z['isSupply']
            
            priceInZone = False
            for k in range(min(21, copied)):
                if isSupply:
                    if ltfSeries[k]['high'] >= zMin - 0.2 * ltfAtr and ltfSeries[k]['low'] <= zMax + 0.5 * ltfAtr:
                        priceInZone = True; break
                else:
                    if ltfSeries[k]['low'] <= zMax + 0.2 * ltfAtr and ltfSeries[k]['high'] >= zMin - 0.5 * ltfAtr:
                        priceInZone = True; break
            if not priceInZone: continue
            
            sweepFound = False
            sweepBar = -1
            sweepPrice = -1.0 if isSupply else 9999999.0
            
            for s in range(1, min(21, copied)):
                fullRng = ltfSeries[s]['high'] - ltfSeries[s]['low']
                if fullRng < 0.25 * ltfAtr: continue
                if isSupply:
                    upperWick = ltfSeries[s]['high'] - max(ltfSeries[s]['open'], ltfSeries[s]['close'])
                    if (upperWick / fullRng) >= 0.35 and ltfSeries[s]['high'] >= zMin:
                        if ltfSeries[s]['high'] > sweepPrice:
                            sweepPrice = ltfSeries[s]['high']
                            sweepBar = s
                            sweepFound = True
                else:
                    lowerWick = min(ltfSeries[s]['open'], ltfSeries[s]['close']) - ltfSeries[s]['low']
                    if (lowerWick / fullRng) >= 0.35 and ltfSeries[s]['low'] <= zMax:
                        if ltfSeries[s]['low'] < sweepPrice:
                            sweepPrice = ltfSeries[s]['low']
                            sweepBar = s
                            sweepFound = True
                            
            if not sweepFound or sweepBar < 1: continue
            
            # Minor swing pivot
            swStart = sweepBar + 1
            swEnd = min(copied - 2, sweepBar + 8)
            if isSupply:
                chochLevel = 9999999.0
                foundPivot = False
                for sw in range(swStart, swEnd + 1):
                    if sw > 0 and sw < copied - 1:
                        if ltfSeries[sw]['low'] <= ltfSeries[sw-1]['low'] and ltfSeries[sw]['low'] <= ltfSeries[sw+1]['low']:
                            chochLevel = ltfSeries[sw]['low']
                            foundPivot = True
                            break
                if not foundPivot:
                    for sw in range(swStart, min(copied, sweepBar + 5)):
                        if ltfSeries[sw]['low'] < chochLevel:
                            chochLevel = ltfSeries[sw]['low']
            else:
                chochLevel = -1.0
                foundPivot = False
                for sw in range(swStart, swEnd + 1):
                    if sw > 0 and sw < copied - 1:
                        if ltfSeries[sw]['high'] >= ltfSeries[sw-1]['high'] and ltfSeries[sw]['high'] >= ltfSeries[sw+1]['high']:
                            chochLevel = ltfSeries[sw]['high']
                            foundPivot = True
                            break
                if not foundPivot:
                    for sw in range(swStart, min(copied, sweepBar + 5)):
                        if ltfSeries[sw]['high'] > chochLevel:
                            chochLevel = ltfSeries[sw]['high']
                            
            isBuySignal = not isSupply
            confirmBar = -1
            for c in range(sweepBar - 1, 0, -1):
                if isBuySignal:
                    if chochLevel > 0 and ltfSeries[c]['close'] > chochLevel and ltfSeries[c]['close'] > ltfSeries[c]['open']:
                        if not any(ltfSeries[p]['close'] > chochLevel for p in range(sweepBar - 1, c, -1)):
                            confirmBar = c
                            break
                else:
                    if chochLevel < 9999990.0 and ltfSeries[c]['close'] < chochLevel and ltfSeries[c]['close'] < ltfSeries[c]['open']:
                        if not any(ltfSeries[p]['close'] < chochLevel for p in range(sweepBar - 1, c, -1)):
                            confirmBar = c
                            break
                            
            if confirmBar == 1:
                sig_data = {
                    'isBuy': isBuySignal,
                    'barTime': ltfSeries[1]['time'],
                    'entryMarket': ltfSeries[1]['close'],
                    'openBar1': ltfSeries[1]['open'],
                    'closeBar1': ltfSeries[1]['close'],
                    'highBar1': ltfSeries[1]['high'],
                    'lowBar1': ltfSeries[1]['low'],
                    'sweepPrice': sweepPrice,
                    'sweepBar': sweepBar,
                    'chochLevel': chochLevel,
                    'zoneType': z['type'],
                    'zoneScore': z['score'],
                    'ltfAtr': ltfAtr,
                    'm5_idx': idx,
                    'ltfSeries': ltfSeries
                }
                if not any(s['barTime'] == sig_data['barTime'] for s in raw_signals):
                    raw_signals.append(sig_data)
                break
                
    return raw_signals

def main():
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8')
    if hasattr(sys.stderr, 'reconfigure'):
        sys.stderr.reconfigure(encoding='utf-8')

    print("=" * 90)
    print("KIỂM CHỨNG TOÀN DIỆN HIỆU QUẢ NÂNG CẤP CHỈ BÁO TRÊN VÀNG (XAUUSD) M5")
    print("DỮ LIỆU THỰC TẾ NGÀY 19/10/2026 (01:00 UTC - 23:59 UTC)")
    print("=" * 90)

    mt5.initialize()
    all_h1 = mt5.copy_rates_from_pos('XAUUSD', mt5.TIMEFRAME_H1, 0, 1500)
    all_m5 = mt5.copy_rates_from_pos('XAUUSD', mt5.TIMEFRAME_M5, 0, 2000)
    mt5.shutdown()

    t_start = int(datetime(2026, 10, 19, 1, 0, 0, tzinfo=timezone.utc).timestamp())
    t_end = int(datetime(2026, 10, 20, 0, 0, 0, tzinfo=timezone.utc).timestamp())

    signals = detect_choch_signals(all_m5, all_h1, t_start, t_end)
    print(f"Tổng số tín hiệu M5 CHoCH ghi nhận trong ngày: {len(signals)}\n")

    pip_size = 0.1         # Gold $0.10 per pip
    max_sl_pips = 100.0    # 100 pips = $10.0 Gold
    min_sl_pips = 25.0     # 25 pips = $2.5 Gold
    be_trigger_pips = 60.0 # 60 pips = $6.0 Gold
    be_offset_pips = 1.0   # 1 pip buffer = $0.10
    tp1_pips = 60.0        # 60 pips = $6.0 Gold

    old_results = []
    upgraded_mkt_results = []
    upgraded_limit_results = []

    for i, s in enumerate(signals):
        idx = s['m5_idx']
        t_dt = datetime.fromtimestamp(s['barTime'], tz=timezone.utc)
        t_str = t_dt.strftime('%H:%M')
        dir_str = "BUY " if s['isBuy'] else "SELL"
        isBuy = s['isBuy']
        entry_mkt = s['entryMarket']
        entry_lim = (s['openBar1'] + s['closeBar1']) / 2.0
        ltfAtr = s['ltfAtr']
        ltfSeries = s['ltfSeries']
        sweepBar = s['sweepBar']
        
        # Killzone check (London 08-12, NY 13-17)
        h = t_dt.hour
        in_kz = (8 <= h <= 12) or (13 <= h <= 17)

        # =============================================================
        # 1. MODEL CŨ (Sweep Distal SL, Market Entry, Fixed R:R, No BE)
        # =============================================================
        if isBuy:
            old_sl = s['sweepPrice'] - 0.5 * ltfAtr
            old_risk = entry_mkt - old_sl
            if old_risk <= 0: old_risk = 1.0 * ltfAtr; old_sl = entry_mkt - old_risk
            old_tp1 = entry_mkt + 1.5 * old_risk
            old_tp2 = entry_mkt + 2.0 * old_risk
        else:
            old_sl = s['sweepPrice'] + 0.5 * ltfAtr
            old_risk = old_sl - entry_mkt
            if old_risk <= 0: old_risk = 1.0 * ltfAtr; old_sl = entry_mkt + old_risk
            old_tp1 = entry_mkt - 1.5 * old_risk
            old_tp2 = entry_mkt - 2.0 * old_risk

        old_hit_tp1 = False
        old_hit_tp2 = False
        old_exit = "OPEN"
        old_mfe = 0.0

        for pt in range(idx, min(len(all_m5), idx + 250)):
            b = all_m5[pt]
            hi, lo = b['high'], b['low']
            if isBuy:
                fav = hi - entry_mkt
                if fav > old_mfe: old_mfe = fav
                if not old_hit_tp1 and hi >= old_tp1: old_hit_tp1 = True
                if not old_hit_tp2 and hi >= old_tp2:
                    old_hit_tp2 = True; old_exit = "TP2"; break
                if lo <= old_sl:
                    old_exit = "SL"; break
            else:
                fav = entry_mkt - lo
                if fav > old_mfe: old_mfe = fav
                if not old_hit_tp1 and lo <= old_tp1: old_hit_tp1 = True
                if not old_hit_tp2 and lo <= old_tp2:
                    old_hit_tp2 = True; old_exit = "TP2"; break
                if hi >= old_sl:
                    old_exit = "SL"; break

        old_strat_r = -1.0
        if old_hit_tp1:
            old_strat_r = 1.75 if old_hit_tp2 else 0.75
        elif old_exit == "TP2":
            old_strat_r = 2.0

        old_results.append({
            'sl': old_sl,
            'risk': old_risk,
            'tp1': old_tp1,
            'tp2': old_tp2,
            'exit': old_exit,
            'hit_tp1': old_hit_tp1,
            'hit_tp2': old_hit_tp2,
            'strat_r': old_strat_r,
            'mfe': old_mfe,
            'in_kz': in_kz
        })

        # =============================================================
        # 2. MODEL NÂNG CẤP - VÀO LỆNH MARKET
        # =============================================================
        lookback = min(len(ltfSeries), max(6, sweepBar + 1))
        if isBuy:
            struct_low = min(ltfSeries[b]['low'] for b in range(1, lookback))
            mkt_sl = struct_low - 0.3 * ltfAtr
            mkt_risk = entry_mkt - mkt_sl
            if mkt_risk > max_sl_pips * pip_size: mkt_risk = max_sl_pips * pip_size; mkt_sl = entry_mkt - mkt_risk
            elif mkt_risk < min_sl_pips * pip_size: mkt_risk = min_sl_pips * pip_size; mkt_sl = entry_mkt - mkt_risk
            mkt_tp1 = entry_mkt + tp1_pips * pip_size
            mkt_tp2 = entry_mkt + 2.0 * mkt_risk
            mkt_be_price = entry_mkt + be_offset_pips * pip_size
        else:
            struct_high = max(ltfSeries[b]['high'] for b in range(1, lookback))
            mkt_sl = struct_high + 0.3 * ltfAtr
            mkt_risk = mkt_sl - entry_mkt
            if mkt_risk > max_sl_pips * pip_size: mkt_risk = max_sl_pips * pip_size; mkt_sl = entry_mkt + mkt_risk
            elif mkt_risk < min_sl_pips * pip_size: mkt_risk = min_sl_pips * pip_size; mkt_sl = entry_mkt + mkt_risk
            mkt_tp1 = entry_mkt - tp1_pips * pip_size
            mkt_tp2 = entry_mkt - 2.0 * mkt_risk
            mkt_be_price = entry_mkt - be_offset_pips * pip_size

        mkt_hit_tp1 = False
        mkt_hit_tp2 = False
        mkt_be_active = False
        mkt_exit = "OPEN"
        curr_mkt_sl = mkt_sl
        mkt_mfe = 0.0

        for pt in range(idx, min(len(all_m5), idx + 250)):
            b = all_m5[pt]
            hi, lo = b['high'], b['low']
            if isBuy:
                fav = hi - entry_mkt
                if fav > mkt_mfe: mkt_mfe = fav
                if not mkt_be_active and fav >= (be_trigger_pips * pip_size):
                    mkt_be_active = True
                    curr_mkt_sl = mkt_be_price
                if not mkt_hit_tp1 and hi >= mkt_tp1:
                    mkt_hit_tp1 = True
                    if not mkt_be_active:
                        mkt_be_active = True
                        curr_mkt_sl = mkt_be_price
                if not mkt_hit_tp2 and hi >= mkt_tp2:
                    mkt_hit_tp2 = True
                    mkt_exit = "TP2"
                    break
                if lo <= curr_mkt_sl:
                    mkt_exit = "BE" if mkt_be_active else "SL"
                    break
            else:
                fav = entry_mkt - lo
                if fav > mkt_mfe: mkt_mfe = fav
                if not mkt_be_active and fav >= (be_trigger_pips * pip_size):
                    mkt_be_active = True
                    curr_mkt_sl = mkt_be_price
                if not mkt_hit_tp1 and lo <= mkt_tp1:
                    mkt_hit_tp1 = True
                    if not mkt_be_active:
                        mkt_be_active = True
                        curr_mkt_sl = mkt_be_price
                if not mkt_hit_tp2 and lo <= mkt_tp2:
                    mkt_hit_tp2 = True
                    mkt_exit = "TP2"
                    break
                if hi >= curr_mkt_sl:
                    mkt_exit = "BE" if mkt_be_active else "SL"
                    break

        if mkt_hit_tp1:
            mkt_strat_r = 1.75 if mkt_hit_tp2 else 0.75
            mkt_desc = "TP1 (50%) + TP2 (+1.75R)" if mkt_hit_tp2 else "TP1 (50%) + BE Runner (+0.75R)"
        elif mkt_exit == "BE":
            mkt_strat_r = 0.05
            mkt_desc = "Auto-BE Hòa Vốn (+0.05R)"
        elif mkt_exit == "SL":
            mkt_strat_r = -1.0
            mkt_desc = "Dính SL (-1.0R)"
        else:
            mkt_strat_r = 0.0
            mkt_desc = "Đang chạy"

        upgraded_mkt_results.append({
            'sl': mkt_sl,
            'risk': mkt_risk,
            'tp1': mkt_tp1,
            'tp2': mkt_tp2,
            'exit': mkt_exit,
            'hit_tp1': mkt_hit_tp1,
            'hit_tp2': mkt_hit_tp2,
            'be_active': mkt_be_active,
            'strat_r': mkt_strat_r,
            'desc': mkt_desc,
            'mfe': mkt_mfe,
            'in_kz': in_kz
        })

        # =============================================================
        # 3. MODEL NÂNG CẤP - VÀO LỆNH LIMIT 50% RETRACE
        # =============================================================
        lim_filled = False
        lim_fill_idx = -1
        # Check if pulled back within 6 bars (30 mins)
        for pt in range(idx, min(len(all_m5), idx + 6)):
            b = all_m5[pt]
            if isBuy and b['low'] <= entry_lim:
                lim_filled = True; lim_fill_idx = pt; break
            elif not isBuy and b['high'] >= entry_lim:
                lim_filled = True; lim_fill_idx = pt; break

        if lim_filled:
            if isBuy:
                lim_sl = struct_low - 0.3 * ltfAtr
                lim_risk = entry_lim - lim_sl
                if lim_risk > max_sl_pips * pip_size: lim_risk = max_sl_pips * pip_size; lim_sl = entry_lim - lim_risk
                elif lim_risk < min_sl_pips * pip_size: lim_risk = min_sl_pips * pip_size; lim_sl = entry_lim - lim_risk
                lim_tp1 = entry_lim + tp1_pips * pip_size
                lim_tp2 = entry_lim + 2.0 * lim_risk
                lim_be_price = entry_lim + be_offset_pips * pip_size
            else:
                lim_sl = struct_high + 0.3 * ltfAtr
                lim_risk = lim_sl - entry_lim
                if lim_risk > max_sl_pips * pip_size: lim_risk = max_sl_pips * pip_size; lim_sl = entry_lim + lim_risk
                elif lim_risk < min_sl_pips * pip_size: lim_risk = min_sl_pips * pip_size; lim_sl = entry_lim + lim_risk
                lim_tp1 = entry_lim - tp1_pips * pip_size
                lim_tp2 = entry_lim - 2.0 * lim_risk
                lim_be_price = entry_lim - be_offset_pips * pip_size

            lim_hit_tp1 = False
            lim_hit_tp2 = False
            lim_be_active = False
            lim_exit = "OPEN"
            curr_lim_sl = lim_sl
            lim_mfe = 0.0

            for pt in range(lim_fill_idx, min(len(all_m5), lim_fill_idx + 250)):
                b = all_m5[pt]
                hi, lo = b['high'], b['low']
                if isBuy:
                    fav = hi - entry_lim
                    if fav > lim_mfe: lim_mfe = fav
                    if not lim_be_active and fav >= (be_trigger_pips * pip_size):
                        lim_be_active = True
                        curr_lim_sl = lim_be_price
                    if not lim_hit_tp1 and hi >= lim_tp1:
                        lim_hit_tp1 = True
                        if not lim_be_active:
                            lim_be_active = True
                            curr_lim_sl = lim_be_price
                    if not lim_hit_tp2 and hi >= lim_tp2:
                        lim_hit_tp2 = True
                        lim_exit = "TP2"
                        break
                    if lo <= curr_lim_sl:
                        lim_exit = "BE" if lim_be_active else "SL"
                        break
                else:
                    fav = entry_lim - lo
                    if fav > lim_mfe: lim_mfe = fav
                    if not lim_be_active and fav >= (be_trigger_pips * pip_size):
                        lim_be_active = True
                        curr_lim_sl = lim_be_price
                    if not lim_hit_tp1 and lo <= lim_tp1:
                        lim_hit_tp1 = True
                        if not lim_be_active:
                            lim_be_active = True
                            curr_lim_sl = lim_be_price
                    if not lim_hit_tp2 and lo <= lim_tp2:
                        lim_hit_tp2 = True
                        lim_exit = "TP2"
                        break
                    if hi >= curr_lim_sl:
                        lim_exit = "BE" if lim_be_active else "SL"
                        break

            if lim_hit_tp1:
                lim_strat_r = 1.75 if lim_hit_tp2 else 0.75
                lim_desc = "TP1 (50%) + TP2 (+1.75R)" if lim_hit_tp2 else "TP1 (50%) + BE Runner (+0.75R)"
            elif lim_exit == "BE":
                lim_strat_r = 0.05
                lim_desc = "Auto-BE Hòa Vốn (+0.05R)"
            elif lim_exit == "SL":
                lim_strat_r = -1.0
                lim_desc = "Dính SL (-1.0R)"
            else:
                lim_strat_r = 0.0
                lim_desc = "Đang chạy"
        else:
            lim_risk = 0.0
            lim_sl = 0.0
            lim_tp1 = 0.0
            lim_tp2 = 0.0
            lim_hit_tp1 = False
            lim_hit_tp2 = False
            lim_be_active = False
            lim_exit = "UNFILLED"
            lim_strat_r = 0.0
            lim_desc = "Bỏ lỡ nhịp hồi (0.0R)"
            lim_mfe = 0.0

        upgraded_limit_results.append({
            'filled': lim_filled,
            'entry': entry_lim,
            'sl': lim_sl,
            'risk': lim_risk,
            'tp1': lim_tp1,
            'tp2': lim_tp2,
            'exit': lim_exit,
            'hit_tp1': lim_hit_tp1,
            'hit_tp2': lim_hit_tp2,
            'be_active': lim_be_active,
            'strat_r': lim_strat_r,
            'desc': lim_desc,
            'mfe': lim_mfe,
            'in_kz': in_kz
        })

        print(f"#{i+1:02d} | {t_str} | {dir_str} @ Mkt {entry_mkt:.2f} (Limit 50%: {entry_lim:.2f}) | KZ: {'CÓ' if in_kz else 'KHÔNG'}")
        print(f"     [CŨ]       SL: {old_sl:.2f} (Risk: ${old_risk:.2f}) | TP1: {old_tp1:.2f} | KẾT QUẢ: {old_results[-1]['strat_r']:+.2f}R | Max Thuận: +${old_mfe:.2f} (+{old_mfe/pip_size:.0f}p)")
        print(f"     [MKT MỚI]  SL: {mkt_sl:.2f} (Risk: ${mkt_risk:.2f}) | TP1: {mkt_tp1:.2f} | KẾT QUẢ: {mkt_desc} -> {mkt_strat_r:+.2f}R | Max Thuận: +${mkt_mfe:.2f} (+{mkt_mfe/pip_size:.0f}p)")
        if lim_filled:
            print(f"     [LIMIT 50%] Khớp @ {entry_lim:.2f} (Risk: ${lim_risk:.2f}) | KẾT QUẢ: {lim_desc} -> {lim_strat_r:+.2f}R | Max Thuận: +${lim_mfe:.2f} (+{lim_mfe/pip_size:.0f}p)")
        else:
            print(f"     [LIMIT 50%] Không khớp hồi -> {lim_desc}")
        print()

    # SUMMARY COMPARISON
    old_tot_r = sum(r['strat_r'] for r in old_results)
    mkt_tot_r = sum(r['strat_r'] for r in upgraded_mkt_results)
    lim_tot_r = sum(r['strat_r'] for r in upgraded_limit_results)

    old_tp1_count = sum(1 for r in old_results if r['hit_tp1'])
    mkt_tp1_count = sum(1 for r in upgraded_mkt_results if r['hit_tp1'])
    lim_tp1_count = sum(1 for r in upgraded_limit_results if r['hit_tp1'])

    old_tp2_count = sum(1 for r in old_results if r['hit_tp2'])
    mkt_tp2_count = sum(1 for r in upgraded_mkt_results if r['hit_tp2'])
    lim_tp2_count = sum(1 for r in upgraded_limit_results if r['hit_tp2'])

    old_sl_count = sum(1 for r in old_results if r['exit'] == "SL")
    mkt_sl_count = sum(1 for r in upgraded_mkt_results if r['exit'] == "SL")
    lim_sl_count = sum(1 for r in upgraded_limit_results if r['exit'] == "SL")

    mkt_be_saved = sum(1 for r in upgraded_mkt_results if r['exit'] == "BE" and not r['hit_tp1'])
    lim_be_saved = sum(1 for r in upgraded_limit_results if r['exit'] == "BE" and not r['hit_tp1'])

    print("=" * 95)
    print("BẢNG TỔNG HỢP SO SÁNH ĐỊNH LƯỢNG 3 MÔ HÌNH TRÊN VÀNG M5 (19/10/2026):")
    print("=" * 95)
    print(f"{'Chỉ số đánh giá':<35} | {'Phiên bản CŨ':<18} | {'NÂNG CẤP (Market)':<18} | {'NÂNG CẤP (Limit 50%)':<18}")
    print("-" * 95)
    print(f"{'Khoảng cách Stop Loss TB':<35} | ${np.mean([r['risk'] for r in old_results]):<17.2f} | ${np.mean([r['risk'] for r in upgraded_mkt_results]):<17.2f} | ${np.mean([r['risk'] for r in upgraded_limit_results if r['filled']]):<17.2f}")
    print(f"{'Số kèo cắn trọn SL (-1.0R)':<35} | {old_sl_count}/{len(signals)} ({old_sl_count/len(signals)*100:.1f}%)       | {mkt_sl_count}/{len(signals)} ({mkt_sl_count/len(signals)*100:.1f}%)       | {lim_sl_count}/{len(signals)} ({lim_sl_count/len(signals)*100:.1f}%)")
    print(f"{'Tỷ lệ chạm Take Profit 1':<35} | {old_tp1_count}/{len(signals)} ({old_tp1_count/len(signals)*100:.1f}%)       | {mkt_tp1_count}/{len(signals)} ({mkt_tp1_count/len(signals)*100:.1f}%)       | {lim_tp1_count}/{len(signals)} ({lim_tp1_count/len(signals)*100:.1f}%)")
    print(f"{'Tỷ lệ chạm Take Profit 2':<35} | {old_tp2_count}/{len(signals)} ({old_tp2_count/len(signals)*100:.1f}%)        | {mkt_tp2_count}/{len(signals)} ({mkt_tp2_count/len(signals)*100:.1f}%)       | {lim_tp2_count}/{len(signals)} ({lim_tp2_count/len(signals)*100:.1f}%)")
    print(f"{'TỔNG LỢI NHUẬN TOÀN DIỆN 24/5':<35} | {old_tot_r:<+17.2f}R | {mkt_tot_r:<+17.2f}R | {lim_tot_r:<+17.2f}R")
    
    # Killzones comparison
    kz_old = [r['strat_r'] for r in old_results if r['in_kz']]
    kz_mkt = [r['strat_r'] for r in upgraded_mkt_results if r['in_kz']]
    kz_lim = [r['strat_r'] for r in upgraded_limit_results if r['in_kz']]
    kz_count = len(kz_old)
    print("-" * 95)
    print(f"{'LỢI NHUẬN TRONG GIỜ KILLZONES':<35} | {sum(kz_old):<+17.2f}R | {sum(kz_mkt):<+17.2f}R | {sum(kz_lim):<+17.2f}R")
    print(f"{'Tỷ lệ thắng trong Killzones':<35} | {sum(1 for r in old_results if r['in_kz'] and r['hit_tp1'])}/{kz_count} ({sum(1 for r in old_results if r['in_kz'] and r['hit_tp1'])/kz_count*100:.1f}%)        | {sum(1 for r in upgraded_mkt_results if r['in_kz'] and r['hit_tp1'])}/{kz_count} ({sum(1 for r in upgraded_mkt_results if r['in_kz'] and r['hit_tp1'])/kz_count*100:.1f}%)        | {sum(1 for r in upgraded_limit_results if r['in_kz'] and r['hit_tp1'])}/{kz_count} ({sum(1 for r in upgraded_limit_results if r['in_kz'] and r['hit_tp1'])/kz_count*100:.1f}%)")
    print("=" * 95)

if __name__ == '__main__':
    main()
