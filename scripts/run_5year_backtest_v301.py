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
    print("=" * 95)
    print("BÁO CÁO BACKTEST ĐỊNH LƯỢNG 5 NĂM VÀNG (XAUUSD M5): 2021 - 2026")
    print("KIỂM ĐỊNH FILE BIÊN DỊCH MỚI NHẤT: duc_tri_can_ho_tro.ex5 (v3.01)")
    print("=" * 95)
    t0 = time.time()

    mt5.initialize()
    from_dt = datetime(2021, 10, 23, 0, 0, 0, tzinfo=timezone.utc)
    to_dt = datetime(2026, 10, 23, 23, 59, 59, tzinfo=timezone.utc)
    print(f"Đang tải dữ liệu M5 & H1 từ MT5 từ {from_dt.strftime('%Y-%m-%d')} đến {to_dt.strftime('%Y-%m-%d')}...")
    rates_h1 = mt5.copy_rates_range('XAUUSD', mt5.TIMEFRAME_H1, from_dt, to_dt)
    rates_m5 = mt5.copy_rates_range('XAUUSD', mt5.TIMEFRAME_M5, from_dt, to_dt)
    mt5.shutdown()

    if rates_h1 is None or len(rates_h1) == 0:
        print("[ERROR] Không tải được dữ liệu H1 từ MT5.")
        return 1
    if rates_m5 is None or len(rates_m5) == 0:
        print("[ERROR] Không tải được dữ liệu M5 từ MT5.")
        return 1

    times_h1 = rates_h1['time'].astype(np.int64)
    opens_h1 = rates_h1['open'].astype(np.float64)
    highs_h1 = rates_h1['high'].astype(np.float64)
    lows_h1 = rates_h1['low'].astype(np.float64)
    closes_h1 = rates_h1['close'].astype(np.float64)
    atr_h1 = compute_wilder_atr(highs_h1, lows_h1, closes_h1, 14)

    print(f"Xây dựng các vùng Macro H1 Supply/Demand theo thuật toán v3.01...")
    zones = build_h1_zones(times_h1, opens_h1, highs_h1, lows_h1, closes_h1, atr_h1)
    print(f"Tổng số vùng H1 hợp lệ tìm thấy: {len(zones)}")

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
    print(f"Dữ liệu: {n_m5} nến M5 (5 năm lịch sử). Đang quét tín hiệu SMC...")

    pip_size = 0.1
    max_sl_pips = 100.0  # 10.0$ max risk
    min_sl_pips = 25.0   # 2.5$ min risk
    sl_buf_atr = 0.3     # 0.3 ATR buffer (v3.01)
    be_trigger_pips = 60.0 # 60 pips = $6.0
    be_offset_pips = 1.0   # 1 pip = $0.10

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

                # 1. OLD MODEL
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

                # 2. NEW MODEL STRUCTURAL SWING SL (v3.01 exact logic)
                lookback_bars = max(4, sweepBar)
                if isBuySignal:
                    structLow = entryMkt
                    for b in range(cIdx, max(0, cIdx - lookback_bars - 1), -1):
                        if lows_m5[b] < structLow: structLow = lows_m5[b]
                    sl_new = structLow - sl_buf_atr * c_atr
                    risk_new = entryMkt - sl_new
                else:
                    structHigh = entryMkt
                    for b in range(cIdx, max(0, cIdx - lookback_bars - 1), -1):
                        if highs_m5[b] > structHigh: structHigh = highs_m5[b]
                    sl_new = structHigh + sl_buf_atr * c_atr
                    risk_new = sl_new - entryMkt

                # Gate 1: Check maximum risk (100 pips = $10.0) -> Rejection gate (Preserve structural swing)
                if risk_new > max_sl_pips * pip_size:
                    # In MQL5: if(risk > maxRisk) continue;
                    pass_struct_filter = False
                else:
                    pass_struct_filter = True
                    if risk_new < min_sl_pips * pip_size:
                        risk_new = min_sl_pips * pip_size
                        sl_new = (entryMkt - risk_new) if isBuySignal else (entryMkt + risk_new)

                # Entry limit (50% pullback)
                entry_limit = 0.5 * (cBarOpen + entryMkt)
                risk_limit = (entry_limit - sl_new) if isBuySignal else (sl_new - entry_limit)
                if risk_limit < min_sl_pips * pip_size:
                    risk_limit = min_sl_pips * pip_size

                # TP calculations
                # A. Hybrid: TP1 = +60 pips ($6.0), TP2 = 2.0R
                tp1_hybrid = (entryMkt + 6.0) if isBuySignal else (entryMkt - 6.0)
                tp2_hybrid = (entryMkt + 2.0 * risk_new) if isBuySignal else (entryMkt - 2.0 * risk_new)
                rr1_hybrid = 6.0 / risk_new if risk_new > 0 else 1.5

                # B. Pure RR: TP1 = 1.5R, TP2 = 2.0R
                tp1_rr = (entryMkt + 1.5 * risk_new) if isBuySignal else (entryMkt - 1.5 * risk_new)
                tp2_rr = (entryMkt + 2.0 * risk_new) if isBuySignal else (entryMkt - 2.0 * risk_new)

                signals.append({
                    'idx': cIdx,
                    'time': times_m5[cIdx],
                    'dt': datetime.fromtimestamp(times_m5[cIdx], tz=timezone.utc),
                    'year': datetime.fromtimestamp(times_m5[cIdx], tz=timezone.utc).year,
                    'isBuy': isBuySignal,
                    'kz': is_in_killzone(times_m5[cIdx]),
                    'entryMkt': entryMkt,
                    'entryLimit': entry_limit,
                    'sl_old': sl_old, 'risk_old': risk_old, 'tp1_old': tp1_old, 'tp2_old': tp2_old,
                    'pass_struct': pass_struct_filter,
                    'sl_new': sl_new, 'risk_new': risk_new,
                    'tp1_hybrid': tp1_hybrid, 'tp2_hybrid': tp2_hybrid, 'rr1_hybrid': rr1_hybrid,
                    'tp1_rr': tp1_rr, 'tp2_rr': tp2_rr,
                    'risk_limit': risk_limit
                })
                break

    print(f"Tổng số tín hiệu thô: {len(signals)}")
    valid_struct_sigs = sum(1 for s in signals if s['pass_struct'])
    print(f"Số tín hiệu đạt bộ lọc SL Cấu trúc SMC (< 100 pips): {valid_struct_sigs} (Loại bỏ {len(signals) - valid_struct_sigs} tín hiệu rủi ro quá lớn)")

    # Simulate Trade Execution
    max_hold = 288 # 24 hours max holding
    for s in signals:
        cIdx = s['idx']
        isBuy = s['isBuy']
        end_bar = min(n_m5, cIdx + 1 + max_hold)

        # 1. Simulate Old Model
        r_old = -1.0
        hit_tp1_old = False
        hit_tp2_old = False
        for j in range(cIdx + 1, end_bar):
            h, l = highs_m5[j], lows_m5[j]
            if isBuy:
                if not hit_tp1_old and h >= s['tp1_old']: hit_tp1_old = True
                if not hit_tp2_old and h >= s['tp2_old']: hit_tp2_old = True
                if l <= s['sl_old']: break
                if hit_tp2_old: break
            else:
                if not hit_tp1_old and l <= s['tp1_old']: hit_tp1_old = True
                if not hit_tp2_old and l <= s['tp2_old']: hit_tp2_old = True
                if h >= s['sl_old']: break
                if hit_tp2_old: break
        if hit_tp1_old:
            r_old = 1.75 if hit_tp2_old else 0.75
        else:
            r_old = -1.0
        s['r_old'] = r_old

        # 2. Simulate New Model - Market Entry + Hybrid TP (TP1 = 60p, TP2 = 2.0R) + Auto BE
        if not s['pass_struct']:
            s['r_mkt_hybrid'] = 0.0
            s['r_mkt_rr'] = 0.0
            s['r_lmt_hybrid'] = 0.0
            s['filled_lmt'] = False
            continue

        # Market Hybrid
        hit_tp1 = False
        hit_tp2 = False
        be_active = False
        curr_sl = s['sl_new']
        be_price = (s['entryMkt'] + 0.1) if isBuy else (s['entryMkt'] - 0.1)

        for j in range(cIdx + 1, end_bar):
            h, l = highs_m5[j], lows_m5[j]
            if isBuy:
                cur_fav = h - s['entryMkt']
                if not be_active and cur_fav >= 6.0:
                    be_active = True
                    curr_sl = be_price
                if not hit_tp1 and h >= s['tp1_hybrid']:
                    hit_tp1 = True
                    if not be_active:
                        be_active = True
                        curr_sl = be_price
                if not hit_tp2 and h >= s['tp2_hybrid']:
                    hit_tp2 = True
                    break
                if l <= curr_sl:
                    break
            else:
                cur_fav = s['entryMkt'] - l
                if not be_active and cur_fav >= 6.0:
                    be_active = True
                    curr_sl = be_price
                if not hit_tp1 and l <= s['tp1_hybrid']:
                    hit_tp1 = True
                    if not be_active:
                        be_active = True
                        curr_sl = be_price
                if not hit_tp2 and l <= s['tp2_hybrid']:
                    hit_tp2 = True
                    break
                if h >= curr_sl:
                    break

        # Calculate exact R return: 50% TP1, 50% TP2
        rr1_val = s['rr1_hybrid']
        if hit_tp1:
            if hit_tp2:
                r_mkt_hybrid = 0.5 * rr1_val + 0.5 * 2.0 # TP1 (50%) + TP2 (50%)
            else:
                r_mkt_hybrid = 0.5 * rr1_val + 0.5 * 0.0 # TP1 (50%) + Runner out at BE
        elif be_active:
            r_mkt_hybrid = 0.0 # Auto BE locked
        else:
            r_mkt_hybrid = -1.0 # Hit SL

        s['r_mkt_hybrid'] = r_mkt_hybrid

        # Market Pure RR (TP1 = 1.5R, TP2 = 2.0R + BE @ 60p)
        hit_tp1_rr = False
        hit_tp2_rr = False
        be_active_rr = False
        curr_sl_rr = s['sl_new']

        for j in range(cIdx + 1, end_bar):
            h, l = highs_m5[j], lows_m5[j]
            if isBuy:
                cur_fav = h - s['entryMkt']
                if not be_active_rr and cur_fav >= 6.0:
                    be_active_rr = True
                    curr_sl_rr = be_price
                if not hit_tp1_rr and h >= s['tp1_rr']:
                    hit_tp1_rr = True
                    if not be_active_rr:
                        be_active_rr = True
                        curr_sl_rr = be_price
                if not hit_tp2_rr and h >= s['tp2_rr']:
                    hit_tp2_rr = True
                    break
                if l <= curr_sl_rr:
                    break
            else:
                cur_fav = s['entryMkt'] - l
                if not be_active_rr and cur_fav >= 6.0:
                    be_active_rr = True
                    curr_sl_rr = be_price
                if not hit_tp1_rr and l <= s['tp1_rr']:
                    hit_tp1_rr = True
                    if not be_active_rr:
                        be_active_rr = True
                        curr_sl_rr = be_price
                if not hit_tp2_rr and l <= s['tp2_rr']:
                    hit_tp2_rr = True
                    break
                if h >= curr_sl_rr:
                    break

        if hit_tp1_rr:
            r_mkt_rr = 1.75 if hit_tp2_rr else 0.75
        elif be_active_rr:
            r_mkt_rr = 0.0
        else:
            r_mkt_rr = -1.0
        s['r_mkt_rr'] = r_mkt_rr

        # Limit 50% Retracement Model
        filled_limit = False
        fill_bar = -1
        for j in range(cIdx + 1, min(n_m5, cIdx + 7)): # 30 min window
            if isBuy and lows_m5[j] <= s['entryLimit']:
                filled_limit = True; fill_bar = j; break
            elif not isBuy and highs_m5[j] >= s['entryLimit']:
                filled_limit = True; fill_bar = j; break

        s['filled_lmt'] = filled_limit
        if filled_limit:
            hit_tp1_lmt = False
            hit_tp2_lmt = False
            be_active_lmt = False
            curr_sl_lmt = s['sl_new']
            be_lmt_price = (s['entryLimit'] + 0.1) if isBuy else (s['entryLimit'] - 0.1)
            tp1_lmt = (s['entryLimit'] + 6.0) if isBuy else (s['entryLimit'] - 6.0)
            tp2_lmt = (s['entryLimit'] + 2.0 * s['risk_limit']) if isBuy else (s['entryLimit'] - 2.0 * s['risk_limit'])
            rr1_lmt = 6.0 / s['risk_limit'] if s['risk_limit'] > 0 else 1.5

            for j in range(fill_bar, end_bar):
                h, l = highs_m5[j], lows_m5[j]
                if isBuy:
                    cur_fav = h - s['entryLimit']
                    if not be_active_lmt and cur_fav >= 6.0:
                        be_active_lmt = True
                        curr_sl_lmt = be_lmt_price
                    if not hit_tp1_lmt and h >= tp1_lmt:
                        hit_tp1_lmt = True
                        if not be_active_lmt:
                            be_active_lmt = True
                            curr_sl_lmt = be_lmt_price
                    if not hit_tp2_lmt and h >= tp2_lmt:
                        hit_tp2_lmt = True
                        break
                    if l <= curr_sl_lmt:
                        break
                else:
                    cur_fav = s['entryLimit'] - l
                    if not be_active_lmt and cur_fav >= 6.0:
                        be_active_lmt = True
                        curr_sl_lmt = be_lmt_price
                    if not hit_tp1_lmt and l <= tp1_lmt:
                        hit_tp1_lmt = True
                        if not be_active_lmt:
                            be_active_lmt = True
                            curr_sl_lmt = be_lmt_price
                    if not hit_tp2_lmt and l <= tp2_lmt:
                        hit_tp2_lmt = True
                        break
                    if h >= curr_sl_lmt:
                        break

            if hit_tp1_lmt:
                r_lmt = (0.5 * rr1_lmt + 0.5 * 2.0) if hit_tp2_lmt else (0.5 * rr1_lmt)
            elif be_active_lmt:
                r_lmt = 0.0
            else:
                r_lmt = -1.0
            s['r_lmt_hybrid'] = r_lmt
        else:
            s['r_lmt_hybrid'] = 0.0

    def calc_metrics(sigs, key_r):
        valid = [x for x in sigs if key_r == 'r_old' or x['pass_struct']]
        n = len(valid)
        if n == 0: return {'total_trades': 0, 'wins': 0, 'bes': 0, 'losses': 0, 'win_rate': 0, 'total_r': 0, 'pf': 0, 'max_dd_r': 0}
        r_list = [x[key_r] for x in valid]
        total_r = sum(r_list)
        wins = sum(1 for r in r_list if r > 0)
        bes = sum(1 for r in r_list if r == 0)
        losses = sum(1 for r in r_list if r < 0)
        win_rate = (wins / n) * 100
        gross_profit = sum(r for r in r_list if r > 0)
        gross_loss = abs(sum(r for r in r_list if r < 0))
        pf = (gross_profit / gross_loss) if gross_loss > 0 else 999.0

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

    print("\n" + "=" * 105)
    print("BẢNG SO SÁNH HIỆU SUẤT ĐỊNH LƯỢNG 5 NĂM (2021 - 2026)")
    print("=" * 105)
    print(f"{'Tiêu chí':<28} | {'MODEL CŨ (Distal SL)':<20} | {'MỚI (Mkt Hybrid)':<22} | {'MỚI (Mkt Pure RR)':<20} | {'MỚI (Limit 50%)':<18}")
    print("-" * 105)

    m_old = calc_metrics(signals, 'r_old')
    m_mkt_hyb = calc_metrics(signals, 'r_mkt_hybrid')
    m_mkt_rr = calc_metrics(signals, 'r_mkt_rr')
    m_lmt_hyb = calc_metrics(signals, 'r_lmt_hybrid')

    print(f"{'1. TẤT CẢ TÍN HIỆU (24/5)':<28} | {'':<20} | {'':<22} | {'':<20} | {''}")
    print(f"  - Tổng số lệnh phát sinh     | {m_old['total_trades']:<20} | {m_mkt_hyb['total_trades']:<22} | {m_mkt_rr['total_trades']:<20} | {m_lmt_hyb['total_trades']}")
    print(f"  - Số lệnh Thắng (Ăn TP)      | {m_old['wins']} ({m_old['win_rate']:.1f}%)         | {m_mkt_hyb['wins']} ({m_mkt_hyb['win_rate']:.1f}%)         | {m_mkt_rr['wins']} ({m_mkt_rr['win_rate']:.1f}%)         | {m_lmt_hyb['wins']} ({m_lmt_hyb['win_rate']:.1f}%)")
    print(f"  - Số lệnh Hòa vốn (BE)        | {m_old['bes']:<20} | {m_mkt_hyb['bes']} ({m_mkt_hyb['bes']/m_mkt_hyb['total_trades']*100:.1f}%)         | {m_mkt_rr['bes']} ({m_mkt_rr['bes']/m_mkt_rr['total_trades']*100:.1f}%)         | {m_lmt_hyb['bes']}")
    print(f"  - Số lệnh Thua cắn SL        | {m_old['losses']} ({m_old['losses']/m_old['total_trades']*100:.1f}%)        | {m_mkt_hyb['losses']} ({m_mkt_hyb['losses']/m_mkt_hyb['total_trades']*100:.1f}%)        | {m_mkt_rr['losses']} ({m_mkt_rr['losses']/m_mkt_rr['total_trades']*100:.1f}%)        | {m_lmt_hyb['losses']}")
    print(f"  - TỔNG LỢI NHUẬN (R)         | {m_old['total_r']:+.2f}R             | {m_mkt_hyb['total_r']:+.2f}R            | {m_mkt_rr['total_r']:+.2f}R            | {m_lmt_hyb['total_r']:+.2f}R")
    print(f"  - Tỷ số Lời/Lỗ (Profit Factor)| {m_old['pf']:.2f}                 | {m_mkt_hyb['pf']:.2f}                  | {m_mkt_rr['pf']:.2f}                  | {m_lmt_hyb['pf']:.2f}")
    print(f"  - Max Drawdown sụt giảm (R)  | {m_old['max_dd_r']:.2f}R               | {m_mkt_hyb['max_dd_r']:.2f}R               | {m_mkt_rr['max_dd_r']:.2f}R               | {m_lmt_hyb['max_dd_r']:.2f}R")

    # Killzones
    kz_sigs = [s for s in signals if s['kz']]
    m_old_kz = calc_metrics(kz_sigs, 'r_old')
    m_mkt_hyb_kz = calc_metrics(kz_sigs, 'r_mkt_hybrid')
    m_mkt_rr_kz = calc_metrics(kz_sigs, 'r_mkt_rr')
    m_lmt_hyb_kz = calc_metrics(kz_sigs, 'r_lmt_hybrid')

    print("-" * 105)
    print(f"{'2. GIỜ VÀNG KILLZONES (London/NY)':<28} | {'':<20} | {'':<22} | {'':<20} | {''}")
    print(f"  - Tổng số lệnh Killzones     | {m_old_kz['total_trades']:<20} | {m_mkt_hyb_kz['total_trades']:<22} | {m_mkt_rr_kz['total_trades']:<20} | {m_lmt_hyb_kz['total_trades']}")
    print(f"  - Số lệnh Thắng (Ăn TP)      | {m_old_kz['wins']} ({m_old_kz['win_rate']:.1f}%)         | {m_mkt_hyb_kz['wins']} ({m_mkt_hyb_kz['win_rate']:.1f}%)         | {m_mkt_rr_kz['wins']} ({m_mkt_rr_kz['win_rate']:.1f}%)         | {m_lmt_hyb_kz['wins']} ({m_lmt_hyb_kz['win_rate']:.1f}%)")
    print(f"  - Số lệnh Hòa vốn (BE)        | {m_old_kz['bes']:<20} | {m_mkt_hyb_kz['bes']} ({m_mkt_hyb_kz['bes']/m_old_kz['total_trades']*100:.1f}%)         | {m_mkt_rr_kz['bes']} ({m_mkt_rr_kz['bes']/m_old_kz['total_trades']*100:.1f}%)         | {m_lmt_hyb_kz['bes']}")
    print(f"  - Số lệnh Thua cắn SL        | {m_old_kz['losses']} ({m_old_kz['losses']/m_old_kz['total_trades']*100:.1f}%)        | {m_mkt_hyb_kz['losses']} ({m_mkt_hyb_kz['losses']/m_old_kz['total_trades']*100:.1f}%)        | {m_mkt_rr_kz['losses']} ({m_mkt_rr_kz['losses']/m_old_kz['total_trades']*100:.1f}%)        | {m_lmt_hyb_kz['losses']}")
    print(f"  - TỔNG LỢI NHUẬN (R)         | {m_old_kz['total_r']:+.2f}R             | {m_mkt_hyb_kz['total_r']:+.2f}R            | {m_mkt_rr_kz['total_r']:+.2f}R            | {m_lmt_hyb_kz['total_r']:+.2f}R")
    print(f"  - Tỷ số Lời/Lỗ (Profit Factor)| {m_old_kz['pf']:.2f}                 | {m_mkt_hyb_kz['pf']:.2f}                  | {m_mkt_rr_kz['pf']:.2f}                  | {m_lmt_hyb_kz['pf']:.2f}")
    print(f"  - Max Drawdown sụt giảm (R)  | {m_old_kz['max_dd_r']:.2f}R               | {m_mkt_hyb_kz['max_dd_r']:.2f}R               | {m_mkt_rr_kz['max_dd_r']:.2f}R               | {m_lmt_hyb_kz['max_dd_r']:.2f}R")

    # Yearly breakdown for Mkt Hybrid & Mkt Pure RR
    print("\n" + "=" * 105)
    print("CHI TIẾT LỢI NHUẬN TỪNG NĂM (2021 - 2026) CỦA CƠ CHẾ NÂNG CẤP V3.01 (MARKET HYBRID):")
    print("=" * 105)
    print(f"{'Năm':<8} | {'Số lệnh':<8} | {'Win Rate (TP)':<14} | {'Hòa vốn (BE)':<14} | {'Thua (SL)':<12} | {'Tổng Lợi Nhuận (R)':<18} | {'Profit Factor':<12}")
    print("-" * 105)
    years = sorted(list(set(s['year'] for s in signals)))
    for y in years:
        y_sigs = [s for s in signals if s['year'] == y]
        ym = calc_metrics(y_sigs, 'r_mkt_hybrid')
        if ym['total_trades'] > 0:
            print(f"{y:<8} | {ym['total_trades']:<8} | {ym['win_rate']:<5.1f}% ({ym['wins']:<3}) | {ym['bes']/ym['total_trades']*100:<5.1f}% ({ym['bes']:<3}) | {ym['losses']/ym['total_trades']*100:<5.1f}% ({ym['losses']:<3}) | {ym['total_r']:+8.2f}R           | {ym['pf']:<12.2f}")
    print("=" * 105)

    print("\n" + "=" * 105)
    print("CHI TIẾT LỢI NHUẬN TỪNG NĂM (2021 - 2026) - GIỜ VÀNG KILLZONES (MARKET HYBRID):")
    print("=" * 105)
    print(f"{'Năm':<8} | {'Số lệnh':<8} | {'Win Rate (TP)':<14} | {'Hòa vốn (BE)':<14} | {'Thua (SL)':<12} | {'Tổng Lợi Nhuận (R)':<18} | {'Profit Factor':<12}")
    print("-" * 105)
    for y in years:
        y_sigs = [s for s in signals if s['year'] == y and s['kz']]
        ym = calc_metrics(y_sigs, 'r_mkt_hybrid')
        if ym['total_trades'] > 0:
            print(f"{y:<8} | {ym['total_trades']:<8} | {ym['win_rate']:<5.1f}% ({ym['wins']:<3}) | {ym['bes']/ym['total_trades']*100:<5.1f}% ({ym['bes']:<3}) | {ym['losses']/ym['total_trades']*100:<5.1f}% ({ym['losses']:<3}) | {ym['total_r']:+8.2f}R           | {ym['pf']:<12.2f}")
    print("=" * 105)

if __name__ == '__main__':
    main()
