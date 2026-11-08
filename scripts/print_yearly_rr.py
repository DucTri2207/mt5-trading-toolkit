import sys, os
from datetime import datetime, timezone
import numpy as np

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
from scripts.run_5year_backtest_v301 import is_in_killzone, compute_wilder_atr, build_h1_zones
import MetaTrader5 as mt5

if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')

mt5.initialize()
from_dt = datetime(2021, 10, 23, 0, 0, 0, tzinfo=timezone.utc)
to_dt = datetime(2026, 10, 23, 23, 59, 59, tzinfo=timezone.utc)
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

pip_size = 0.1
max_sl_pips = 100.0
min_sl_pips = 25.0
sl_buf_atr = 0.3

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

        priceInZone = False
        for k in range(m - 1, max(-1, m - 22), -1):
            if isSupply:
                if highs_m5[k] >= zMin - 0.2 * c_atr and lows_m5[k] <= zMax + 0.5 * c_atr:
                    priceInZone = True; break
            else:
                if lows_m5[k] <= zMax + 0.2 * c_atr and highs_m5[k] >= zMin - 0.5 * c_atr:
                    priceInZone = True; break
        if not priceInZone: continue

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

            if risk_new > max_sl_pips * pip_size:
                pass_struct_filter = False
            else:
                pass_struct_filter = True
                if risk_new < min_sl_pips * pip_size:
                    risk_new = min_sl_pips * pip_size
                    sl_new = (entryMkt - risk_new) if isBuySignal else (entryMkt + risk_new)

            tp1_rr = (entryMkt + 1.5 * risk_new) if isBuySignal else (entryMkt - 1.5 * risk_new)
            tp2_rr = (entryMkt + 2.0 * risk_new) if isBuySignal else (entryMkt - 2.0 * risk_new)

            signals.append({
                'idx': cIdx,
                'year': datetime.fromtimestamp(times_m5[cIdx], tz=timezone.utc).year,
                'isBuy': isBuySignal,
                'kz': is_in_killzone(times_m5[cIdx]),
                'entryMkt': entryMkt,
                'pass_struct': pass_struct_filter,
                'sl_new': sl_new,
                'tp1_rr': tp1_rr,
                'tp2_rr': tp2_rr,
            })
            break

max_hold = 288
for s in signals:
    if not s['pass_struct']:
        s['r_mkt_rr'] = 0.0
        continue
    cIdx = s['idx']
    isBuy = s['isBuy']
    end_bar = min(n_m5, cIdx + 1 + max_hold)
    hit_tp1_rr = False
    hit_tp2_rr = False
    be_active_rr = False
    curr_sl_rr = s['sl_new']
    be_price = (s['entryMkt'] + 0.1) if isBuy else (s['entryMkt'] - 0.1)

    for j in range(cIdx + 1, end_bar):
        h, l = highs_m5[j], lows_m5[j]
        if isBuy:
            cur_fav = h - s['entryMkt']
            if not be_active_rr and cur_fav >= 6.0:
                be_active_rr = True; curr_sl_rr = be_price
            if not hit_tp1_rr and h >= s['tp1_rr']:
                hit_tp1_rr = True
                if not be_active_rr: be_active_rr = True; curr_sl_rr = be_price
            if not hit_tp2_rr and h >= s['tp2_rr']:
                hit_tp2_rr = True; break
            if l <= curr_sl_rr: break
        else:
            cur_fav = s['entryMkt'] - l
            if not be_active_rr and cur_fav >= 6.0:
                be_active_rr = True; curr_sl_rr = be_price
            if not hit_tp1_rr and l <= s['tp1_rr']:
                hit_tp1_rr = True
                if not be_active_rr: be_active_rr = True; curr_sl_rr = be_price
            if not hit_tp2_rr and l <= s['tp2_rr']:
                hit_tp2_rr = True; break
            if h >= curr_sl_rr: break

    if hit_tp1_rr:
        r_mkt_rr = 1.75 if hit_tp2_rr else 0.75
    elif be_active_rr:
        r_mkt_rr = 0.0
    else:
        r_mkt_rr = -1.0
    s['r_mkt_rr'] = r_mkt_rr

def calc_m(sigs):
    valid = [x for x in sigs if x['pass_struct']]
    n = len(valid)
    if n == 0: return {}
    r_list = [x['r_mkt_rr'] for x in valid]
    tot_r = sum(r_list)
    wins = sum(1 for r in r_list if r > 0)
    bes = sum(1 for r in r_list if r == 0)
    losses = sum(1 for r in r_list if r < 0)
    gp = sum(r for r in r_list if r > 0)
    gl = abs(sum(r for r in r_list if r < 0))
    pf = (gp / gl) if gl > 0 else 999.0
    return {'n': n, 'w': wins, 'be': bes, 'l': losses, 'r': tot_r, 'pf': pf, 'wr': (wins/n)*100}

years = sorted(list(set(s['year'] for s in signals)))
print("\n--- CHI TIET PURE RR TUNG NAM (24/5) ---")
for y in years:
    m = calc_m([s for s in signals if s['year'] == y])
    print(f"{y} | Lenh: {m['n']} | WR: {m['wr']:.1f}% ({m['w']}) | BE: {m['be']} | SL: {m['l']} | Profit: {m['r']:+.2f}R | PF: {m['pf']:.2f}")

print("\n--- CHI TIET PURE RR TUNG NAM (KILLZONES) ---")
for y in years:
    m = calc_m([s for s in signals if s['year'] == y and s['kz']])
    print(f"{y} | Lenh: {m['n']} | WR: {m['wr']:.1f}% ({m['w']}) | BE: {m['be']} | SL: {m['l']} | Profit: {m['r']:+.2f}R | PF: {m['pf']:.2f}")
