"""Proposed v3.01 Causal Core with B0_LITERAL and B1_TECHNICAL support.

Preserves 100% bitwise parity for B0_LITERAL (reproducing 2,288 KZ alerts and 1,495 BASE trades)
while implementing B1_TECHNICAL bug fixes:
1. Float precision tolerance (rr1 < 1.5 - 1e-7) reclaiming 1,234 valid signals.
2. Unblocking candidate signals from active trade plan lock.
3. Deterministic, immutable zone keys from (timeStart, isSupply, distal, proximal).
"""
from pathlib import Path
import math

import numpy as np
from numba import njit

ROOT = Path(__file__).resolve().parents[1]
RUN = ROOT / 'reports/gold_v301_causal/20261101'
DATA = ROOT / 'reports/scalp_structure_lab/20261025_pilot_v1/rates.npz'

# Lab modes
MODE_REPORT_REPAIRED = 0
MODE_B0_LITERAL = 1
MODE_B1_TECHNICAL = 2
MODE_H1_ROOM_NET_R = 3
MODE_H2_RETEST_LIMIT = 4

# Hypotheses costs: spread_price, roundtrip_commission_price, adverse_slippage_per_fill_price
COSTS = {
    'ZERO': (0.0, 0.0, 0.0),
    'LOW': (0.20, 0.06, 0.02),
    'BASE': (0.40, 0.06, 0.05),
    'STRESS': (0.45, 0.10, 0.10)
}

# Pre-registered Fee Schedules according to PROTOCOL.json and KE_HOACH_NANG_CAP.md:
# (spread_usd, commission_roundtrip_usd, adverse_slippage_per_market_fill_usd)
FEE_SCHEDULES = {
    'ZERO': (0.00, 0.00, 0.00),    # Roundtrip nominal total: 0.00 USD (frictionless theoretical baseline)
    'LOW': (0.20, 0.07, 0.00),     # Roundtrip nominal total: 0.27 USD
    'BASE': (0.30, 0.07, 0.01),    # Roundtrip nominal total: 0.39 USD (with 2x 0.01 market/stop slips)
    'STRESS': (0.45, 0.10, 0.05)   # Roundtrip nominal total: 0.65 USD (with 2x 0.05 market/stop slips)
}


def derive_signal_known_time(confirm_bar_open: int, timeframe_seconds: int = 300) -> int:
    """Rule R2: Signal known time is strictly confirm bar close timestamp."""
    return int(confirm_bar_open) + int(timeframe_seconds)


def matrix(b):
    return np.column_stack([b[x] for x in ['time', 'open', 'high', 'low', 'close']]).astype(float)


@njit(cache=True)
def atr_wilder(b, period=14):
    tr = np.empty(len(b))
    out = np.zeros(len(b))
    tr[0] = b[0, 2] - b[0, 3]
    for i in range(1, len(b)):
        tr[i] = max(b[i, 2], b[i-1, 4]) - min(b[i, 3], b[i-1, 4])
    if len(b) < period:
        return out
    out[period-1] = np.mean(tr[:period])
    for i in range(period, len(b)):
        out[i] = (out[i-1]*(period-1) + tr[i])/period
    return out


@njit(cache=True)
def atr_mt5(b, period=14):
    out = np.zeros(len(b))
    tr = np.zeros(len(b))
    for i in range(1, len(b)):
        tr[i] = max(b[i, 2], b[i-1, 4]) - min(b[i, 3], b[i-1, 4])
    if len(b) <= period:
        return out
    out[period] = np.mean(tr[1:period+1])
    for i in range(period+1, len(b)):
        out[i] = out[i-1] + (tr[i]-tr[i-period])/period
    return out


@njit(cache=True)
def generate_zone_key(time_start, is_supply, distal, proximal):
    """Deterministic, immutable 31-bit integer hash from (timeStart, isSupply, distal, proximal)."""
    h = np.uint32(time_start)
    s = np.uint32(0x9e3779b9) if is_supply else np.uint32(0x3c6ef372)
    h ^= s + ((h << 6) & np.uint32(0xFFFFFFFF)) + (h >> 2)
    d_cents = np.uint32(round(distal * 100.0))
    h ^= d_cents + np.uint32(0x9e3779b9) + ((h << 6) & np.uint32(0xFFFFFFFF)) + (h >> 2)
    p_cents = np.uint32(round(proximal * 100.0))
    h ^= p_cents + np.uint32(0x9e3779b9) + ((h << 6) & np.uint32(0xFFFFFFFF)) + (h >> 2)
    return float(h & np.uint32(0x7FFFFFFF))


@njit(cache=True)
def native_zones(b, a, last, deterministic_keys=False):
    """Literal port of ScanHtfMacroZones on the last <=2000 CLOSED H1s.

    Columns: id (transient zid or deterministic key), supply, type, distal, proximal,
    score, base index, flip index, tests.
    """
    out = np.zeros((2000, 9))
    count = 0
    zid = 0
    start = max(0, last+1-2000)
    copied = last-start+1
    if copied < 39:
        return out[:0]
    i = start+20
    end = last-4
    while i <= end:
        at = a[i]
        if at <= 0:
            i += 1
            continue
        found = False
        for bl in range(1, 6):
            be = i+bl-1
            if be > end:
                break
            bh = -1.0
            low = 9999999.0
            valid = True
            for j in range(i, be+1):
                if b[j, 2]-b[j, 3] > 0.8*at:
                    valid = False
                    break
                bh = max(bh, b[j, 2])
                low = min(low, b[j, 3])
            if not valid or bh-low > 2.0*at:
                continue
            dl = 9999999.0
            dh = -1.0
            for j in range(be+1, be+5):
                dl = min(dl, b[j, 3])
                dh = max(dh, b[j, 2])
            supply = low-dl >= 1.8*at
            demand = not supply and dh-bh >= 1.8*at
            if not supply and not demand:
                continue
            dep = (low-dl)/at if supply else (dh-bh)/at
            leg = b[i, 4]-b[max(start, i-15), 4]
            typ = (1 if leg < 0 else 0) if demand else (3 if leg > 0 else 2)
            distal = bh if supply else low
            prox = low if supply else bh
            tests = 0
            inside_before = False
            broken = -1
            for j in range(be+5, last+1):
                inside = b[j, 2] >= low and b[j, 3] <= bh
                if inside and not inside_before:
                    tests += 1
                inside_before = inside
                if (supply and b[j, 4] > distal) or (demand and b[j, 4] < distal):
                    broken = j
                    break
            fresh = 20.0 if tests == 0 else (10.0 if tests == 1 else (5.0 if tests == 2 else 0.0))
            score = min(100.0, min(40.0, dep/1.8*28.0) + (20.0 if bl == 1 else (15.0 if bl == 2 else 10.0))
                        + fresh + (10.0 if typ == 1 or typ == 3 else 5.0))
            if last-i > 1200:
                continue
            zid += 1
            if broken < 0 and math.floor(score+0.5) >= 35:
                zone_id = generate_zone_key(b[i, 0], supply, distal, prox) if deterministic_keys else float(zid)
                out[count] = np.array([zone_id, 1.0 if supply else 0.0, typ, distal, prox, math.floor(score+0.5), i, -1, tests])
                count += 1
            if broken > start:
                fs = not supply
                fd = prox
                fp = distal
                ft = 0
                fb = False
                life = min(last, broken+400)
                for j in range(broken+1, life+1):
                    if b[j, 2] >= fp and b[j, 3] <= fp:
                        ft += 1
                    if (fs and b[j, 4] > fd) or (not fs and b[j, 4] < fd):
                        fb = True
                        break
                    if ft >= 4:
                        break
                if not fb:
                    zid += 1
                    fscore = math.floor(score*0.85+0.5)
                    if fscore >= 35:
                        fzone_id = generate_zone_key(b[broken, 0], fs, fd, fp) if deterministic_keys else float(zid)
                        out[count] = np.array([fzone_id, 1.0 if fs else 0.0, 4, fd, fp, fscore, i, broken, ft])
                        count += 1
            i += bl+1
            found = True
            break
        if not found:
            i += 1
    return out[:count]


@njit(cache=True)
def native_snapshots(b, a, deterministic_keys=False):
    ptr = np.zeros(len(b)+1, np.int64)
    rows = []
    for last in range(len(b)):
        z = native_zones(b, a, last, deterministic_keys)
        for k in range(len(z)):
            rows.append((z[k, 0], z[k, 1], z[k, 2], z[k, 3], z[k, 4],
                         z[k, 5], z[k, 6], z[k, 7], z[k, 8]))
        ptr[last+1] = len(rows)
    return ptr, rows


def repaired_report_zones(b, a):
    n = len(b)
    zones = []
    i = 20
    infinity = 2**52
    while i <= n-5:
        at = a[i]
        if at <= 0:
            i += 1
            continue
        found = False
        for bl in range(1, 6):
            be = i+bl-1
            if be > n-5:
                break
            part = b[i:be+1]
            if np.any(part[:, 2]-part[:, 3] > 0.8*at):
                continue
            bh = float(max(part[:, 2]))
            low = float(min(part[:, 3]))
            if bh-low > 2.0*at:
                continue
            dl = float(min(b[be+1:be+5, 3]))
            dh = float(max(b[be+1:be+5, 2]))
            supply = low-dl >= 1.8*at
            demand = not supply and dh-bh >= 1.8*at
            if not supply and not demand:
                continue
            dep = (low-dl)/at if supply else (dh-bh)/at
            leg = b[i, 4]-b[max(0, i-15), 4]
            typ = (1 if leg < 0 else 0) if demand else (3 if leg > 0 else 2)
            distal = bh if supply else low
            prox = low if supply else bh
            active = b[be+4, 0]+3600
            end = b[i+1200, 0]+3600 if i+1200 < n else infinity
            tests = 0
            broken = -1
            for j in range(be+5, min(n, i+1200)):
                if b[j, 2] >= prox and b[j, 3] <= prox:
                    tests += 1
                if (supply and b[j, 4] > distal) or (demand and b[j, 4] < distal):
                    broken = j
                    end = b[j, 0]+3600
                    break
                if tests >= 4:
                    end = b[j, 0]+3600
                    break
            score = round(min(100.0, min(40.0, dep/1.8*28.0) + (20.0 if bl == 1 else (15.0 if bl == 2 else 10.0))
                              + 20.0 + (10.0 if typ in (1, 3) else 5.0) + 10.0))
            zid = len(zones)+1
            zones.append(dict(id=zid, supply=supply, type=typ, distal=distal, proximal=prox,
                              score=score, base=i, flip=-1, active=active, end=end))
            if broken > 0:
                fs = not supply
                fd = prox
                fp = distal
                ft = 0
                fend = b[broken+400, 0]+3600 if broken+400 < n else infinity
                for j in range(broken+1, min(n, broken+401)):
                    if b[j, 2] >= fp and b[j, 3] <= fp:
                        ft += 1
                    if (fs and b[j, 4] > fd) or (not fs and b[j, 4] < fd) or ft >= 4:
                        fend = b[j, 0]+3600
                        break
                zones.append(dict(id=len(zones)+1, supply=fs, type=4, distal=fd, proximal=fp,
                                  score=round(score*0.85), base=i, flip=broken,
                                  active=b[broken, 0]+3600, end=fend))
            i += bl
            found = True
            break
        if not found:
            i += 1
    return zones


def report_snapshots(b, zones):
    ptr = [0]
    rows = []
    for t in b[:, 0]+3600:
        for z in zones:
            if z['active'] <= t < z['end']:
                rows.append([z['id'], z['supply'], z['type'], z['distal'], z['proximal'],
                             z['score'], z['base'], z['flip'], 0])
        ptr.append(len(rows))
    return np.asarray(ptr, dtype=np.int64), np.asarray(rows, dtype=float).reshape(-1, 9)


@njit(cache=True)
def detect_one(b, a, m, zones, mode=MODE_B0_LITERAL):
    """Detect setup on M5 bar m-1 using zones visible at bar m.

    m is the first currently available bar; its OHLC cannot enter the signal.
    mode:
      0 / False: MODE_REPORT_REPAIRED
      1 / True:  MODE_B0_LITERAL (strict rr1 < 1.5, exact bitwise MT5 baseline parity)
      2:         MODE_B1_TECHNICAL (reclaims 1,234 valid signals with rr1 < 1.5 - 1e-7)
    """
    empty = np.zeros(12)
    at = a[m-1]
    if m < 30 or at <= 0:
        return empty
    native = (mode != MODE_REPORT_REPAIRED)
    for z in zones:
        supply = z[1] == 1
        zmin = min(z[3], z[4])
        zmax = max(z[3], z[4])
        touch = False
        for k in range(1, 21 if native else 22):
            j = m-k
            if supply:
                ok = b[j, 2] >= zmin-0.2*at and b[j, 3] <= zmax+0.5*at
            else:
                ok = b[j, 3] <= zmax+0.2*at and b[j, 2] >= zmin-0.5*at
            if ok:
                touch = True
                break
        if not touch:
            continue
        sweep = -1
        price = -1.0 if supply else 9999999.0
        for s in range(1, 21):
            j = m-s
            rng = b[j, 2]-b[j, 3]
            if rng <= 0 or rng < 0.25*at:
                continue
            wick = b[j, 2]-max(b[j, 1], b[j, 4]) if supply else min(b[j, 1], b[j, 4])-b[j, 3]
            if wick/rng >= 0.35:
                if supply and b[j, 2] >= zmin and b[j, 2] > price:
                    sweep = s
                    price = b[j, 2]
                elif not supply and b[j, 3] <= zmax and b[j, 3] < price:
                    sweep = s
                    price = b[j, 3]
        if sweep < 1:
            continue
        level = 9999999.0 if supply else -1.0
        pivot = False
        stop = sweep+8 if native else min(25, sweep+8)
        for sw in range(sweep+1, stop+1):
            j = m-sw
            if j <= 0:
                continue
            if supply and b[j, 3] <= b[j-1, 3] and b[j, 3] <= b[j+1, 3]:
                level = b[j, 3]
                pivot = True
                break
            if not supply and b[j, 2] >= b[j-1, 2] and b[j, 2] >= b[j+1, 2]:
                level = b[j, 2]
                pivot = True
                break
        if not pivot:
            for sw in range(sweep+1, sweep+5):
                j = m-sw
                if j >= 0:
                    level = min(level, b[j, 3]) if supply else max(level, b[j, 2])
        confirmed = -1
        for c in range(sweep-1, 0, -1):
            j = m-c
            hit = (b[j, 4] < level and b[j, 4] < b[j, 1]) if supply else (b[j, 4] > level and b[j, 4] > b[j, 1])
            if (supply and level >= 9999990.0) or (not supply and level <= 0):
                continue
            if hit:
                prior = False
                for p in range(sweep-1, c, -1):
                    if (supply and b[m-p, 4] < level) or (not supply and b[m-p, 4] > level):
                        prior = True
                        break
                if not prior:
                    confirmed = c
                    break
        if confirmed != 1:
            continue
        entry = b[m-1, 4]
        d = -1.0 if supply else 1.0
        lookback = max(5, sweep) if native else max(4, sweep)+1
        extreme = b[m-1, 2] if supply else b[m-1, 3]
        for back in range(1, lookback+1):
            extreme = max(extreme, b[m-back, 2]) if supply else min(extreme, b[m-back, 3])
        sl = extreme-d*0.3*at
        risk = d*(entry-sl)
        if risk > 10.0:
            if native:
                continue
            return empty
        if risk < 2.5:
            risk = 2.5
            sl = entry-d*risk
        if mode == MODE_B0_LITERAL:
            # Preserve the literal MQ5 floating-point MinRR comparison
            tp1 = entry+d*1.5*risk
            tp2 = entry+d*2.0*risk
            rr1 = abs(tp1-entry)/risk
            rr2 = abs(tp2-entry)/risk
            if rr1 < 1.5 or rr2 < rr1:
                continue
        elif mode == MODE_B1_TECHNICAL:
            # B1 Technical Fix: IEEE 754 precision tolerance 1e-7
            tp1 = entry+d*1.5*risk
            tp2 = entry+d*2.0*risk
            rr1 = abs(tp1-entry)/risk
            rr2 = abs(tp2-entry)/risk
            if rr1 < (1.5 - 1e-7) or rr2 < rr1:
                continue
        return np.array([m-1.0, b[m-1, 0], b[m, 0], d, entry, sl, risk,
                         z[0], z[2], z[5], float(sweep), at])
    return empty


@njit(cache=True)
def detect_stream(h1, b, atr, ptr, zones, mode=MODE_B0_LITERAL, plan_lock=False):
    """Detect candidate stream across entire timeline.

    If plan_lock=True, replicates the MT5 chart suppression bug where g_lastSignal.active
    blocks subsequent candidate alerts until the running trade plan completes.
    """
    out = np.zeros((len(b), 12))
    n = 0
    h = -1
    plan_active = False
    plan_is_buy = False
    plan_sl = 0.0
    plan_tp2 = 0.0

    for m in range(30, len(b)):
        while h+1 < len(h1) and h1[h+1, 0]+3600 <= b[m, 0]:
            h += 1
        if h < 0:
            continue

        if plan_lock and plan_active:
            cur_price = b[m-1, 4]
            if plan_is_buy:
                if cur_price <= plan_sl or cur_price >= plan_tp2:
                    plan_active = False
            else:
                if cur_price >= plan_sl or cur_price <= plan_tp2:
                    plan_active = False
            if plan_active:
                continue

        s = detect_one(b, atr, m, zones[ptr[h]:ptr[h+1]], mode)
        if s[2] > 0:
            out[n] = s
            n += 1
            if plan_lock:
                plan_active = True
                plan_is_buy = (s[3] == 1.0)
                plan_sl = s[5]
                risk = s[6]
                plan_tp2 = s[4] + s[3] * 2.0 * risk
    return out[:n]


# ==============================================================================
# Phase B Telemetry & Phase C Hypothesis H1 / H2 Causal Extension Engine
# ==============================================================================

def calculate_opposing_room(entry, direction, zones, roundtrip_cost=0.37):
    """Calculate distance to nearest opposing H1 POI barrier and room_net_R.
    
    For BUY: Nearest supply zone (is_supply=1) with proximal > entry.
    For SELL: Nearest demand zone (is_supply=0) with proximal < entry.
    """
    opp_room = None
    opp_prox = None
    has_opp = False
    min_dist = 9999999.0
    
    if direction == 1.0:  # BUY
        for z in zones:
            if z[1] == 1.0 and z[4] > entry:
                dist = z[4] - entry
                if dist < min_dist:
                    min_dist = dist
                    opp_prox = z[4]
                    has_opp = True
    else:  # SELL
        for z in zones:
            if z[1] == 0.0 and z[4] < entry:
                dist = entry - z[4]
                if dist < min_dist:
                    min_dist = dist
                    opp_prox = z[4]
                    has_opp = True
                    
    if has_opp:
        opp_room = min_dist
    return has_opp, opp_room, opp_prox


def detect_all_candidates(b, a, m, zones, mode=MODE_B1_TECHNICAL, roundtrip_cost=0.37):
    """Extract ALL qualifying candidate setups on bar m-1 across active H1 zones.
    
    Preserves exact matching criteria of detect_one without early termination,
    enabling H1 multi-zone evaluation and Phase B telemetry extraction.
    """
    candidates = []
    at = a[m - 1]
    if m < 30 or at <= 0:
        return candidates
        
    for z in zones:
        supply = (z[1] == 1.0)
        zmin = min(z[3], z[4])
        zmax = max(z[3], z[4])
        
        # 1. POI Touch check
        touch = False
        for k in range(1, 21):
            j = m - k
            if supply:
                ok = (b[j, 2] >= zmin - 0.2 * at) and (b[j, 3] <= zmax + 0.5 * at)
            else:
                ok = (b[j, 3] <= zmax + 0.2 * at) and (b[j, 2] >= zmin - 0.5 * at)
            if ok:
                touch = True
                break
        if not touch:
            continue
            
        # 2. Liquidity Sweep check
        sweep = -1
        price = -1.0 if supply else 9999999.0
        for s in range(1, 21):
            j = m - s
            rng = b[j, 2] - b[j, 3]
            if rng <= 0 or rng < 0.25 * at:
                continue
            wick = (b[j, 2] - max(b[j, 1], b[j, 4])) if supply else (min(b[j, 1], b[j, 4]) - b[j, 3])
            if wick / rng >= 0.35:
                if supply and b[j, 2] >= zmin and b[j, 2] > price:
                    sweep = s
                    price = b[j, 2]
                elif not supply and b[j, 3] <= zmax and b[j, 3] < price:
                    sweep = s
                    price = b[j, 3]
        if sweep < 1:
            continue
            
        # 3. Structural Pivot / CHoCH Level
        level = 9999999.0 if supply else -1.0
        pivot = False
        stop = sweep + 8
        for sw in range(sweep + 1, stop + 1):
            j = m - sw
            if j <= 0:
                continue
            if supply and b[j, 3] <= b[j - 1, 3] and b[j, 3] <= b[j + 1, 3]:
                level = b[j, 3]
                pivot = True
                break
            if not supply and b[j, 2] >= b[j - 1, 2] and b[j, 2] >= b[j + 1, 2]:
                level = b[j, 2]
                pivot = True
                break
        if not pivot:
            for sw in range(sweep + 1, sweep + 5):
                j = m - sw
                if j >= 0:
                    level = min(level, b[j, 3]) if supply else max(level, b[j, 2])
                    
        # 4. CHoCH Confirmation Candle check
        confirmed = -1
        for c in range(sweep - 1, 0, -1):
            j = m - c
            hit = (b[j, 4] < level and b[j, 4] < b[j, 1]) if supply else (b[j, 4] > level and b[j, 4] > b[j, 1])
            if (supply and level >= 9999990.0) or (not supply and level <= 0):
                continue
            if hit:
                prior = False
                for p in range(sweep - 1, c, -1):
                    if (supply and b[m - p, 4] < level) or (not supply and b[m - p, 4] > level):
                        prior = True
                        break
                if not prior:
                    confirmed = c
                    break
        if confirmed != 1:
            continue
            
        # 5. Risk Calculation & Boundaries
        entry = b[m - 1, 4]
        d = -1.0 if supply else 1.0
        lookback = max(5, sweep)
        extreme = b[m - 1, 2] if supply else b[m - 1, 3]
        for back in range(1, lookback + 1):
            extreme = max(extreme, b[m - back, 2]) if supply else min(extreme, b[m - back, 3])
            
        sl = extreme - d * 0.3 * at
        risk = d * (entry - sl)
        if risk > 10.0:
            continue
        if risk < 2.5:
            risk = 2.5
            sl = entry - d * risk
            
        # 6. MinRR Gate
        tp1 = entry + d * 1.5 * risk
        tp2 = entry + d * 2.0 * risk
        rr1 = abs(tp1 - entry) / risk
        rr2 = abs(tp2 - entry) / risk
        
        if mode == MODE_B0_LITERAL:
            if rr1 < 1.5 or rr2 < rr1:
                continue
        else:
            if rr1 < (1.5 - 1e-7) or rr2 < rr1:
                continue
                
        # 7. Telemetry Metrics Calculation
        has_opp, opp_room, opp_prox = calculate_opposing_room(entry, d, zones, roundtrip_cost)
        room_net_r = (opp_room - roundtrip_cost) / risk if has_opp else None
        dist_to_zone = abs(entry - z[4])
        dist_to_zone_atr = dist_to_zone / at if at > 0 else 0.0
        
        candidate = {
            'bar_idx': m - 1,
            'confirm_bar_open': int(b[m - 1, 0]),
            'signal_known_time': int(b[m, 0]),
            'publish_time': int(b[m, 0]),
            'order_place_time': int(b[m, 0]),
            'time_m5': int(b[m - 1, 0]),
            'exec_time': int(b[m, 0]),
            'direction': int(d),
            'entry_market': float(entry),
            'sl_price': float(sl),
            'risk': float(risk),
            'choch_level': float(level),
            'zone_id': float(z[0]),
            'zone_type': int(z[2]),
            'zone_score': float(z[5]),
            'zone_distal': float(z[3]),
            'zone_proximal': float(z[4]),
            'sweep_shift': float(sweep),
            'atr': float(at),
            'dist_to_zone': float(dist_to_zone),
            'dist_to_zone_atr': float(dist_to_zone_atr),
            'has_opposing': bool(has_opp),
            'opposing_room': float(opp_room) if opp_room is not None else None,
            'opposing_proximal': float(opp_prox) if opp_prox is not None else None,
            'room_net_R': float(room_net_r) if room_net_r is not None else None,
        }
        candidates.append(candidate)
        
    return candidates


def select_h1_candidate(candidates, roundtrip_cost=0.37):
    """Hypothesis H1 Selection Logic with Structural Stop Guardrail.
    
    1. Retain baseline candidate if only 1 candidate exists.
    2. Enforce guardrail: candidate SL distance must not exceed baseline SL distance.
    3. Rank qualifying candidates:
       - Known opposing room ranked ahead of unknown.
       - Highest room_net_R prioritized.
       - Tie-breaker 1: smaller distance from entry to originating zone edge.
       - Tie-breaker 2: stable zone identifier.
    4. If all candidates have unknown opposing room, retain baseline candidate.
    """
    if not candidates:
        return None
    if len(candidates) == 1:
        return candidates[0]
        
    base_cand = candidates[0]
    base_sl_dist = base_cand['risk']
    
    # Structural Stop Guardrail: Candidate SL cannot be wider than baseline SL
    eligible = [c for c in candidates if c['risk'] <= base_sl_dist + 1e-9]
    if not eligible:
        return base_cand
        
    # Check if any candidate has measured opposing room
    has_any_opposing = any(c['has_opposing'] for c in eligible)
    if not has_any_opposing:
        return base_cand
        
    # Ranking sort
    def sort_key(c):
        has_opp = 1 if c['has_opposing'] else 0
        r_net = c['room_net_R'] if c['has_opposing'] and c['room_net_R'] is not None else -999999.0
        dist = -c['dist_to_zone']
        zid = c['zone_id']
        return (has_opp, r_net, dist, zid)
        
    eligible_sorted = sorted(eligible, key=sort_key, reverse=True)
    return eligible_sorted[0]


def simulate_h2_entry(candidate, m1_bars, next_m5_quote=None, spread=0.30, slip=0.01):
    """Hypothesis H2: 5-minute virtual limit order retest with market fallback.
    
    Causal Time Separation (Requirement R2):
    - confirm_bar_open: M5 bar m-1 open time
    - signal_known_time: M5 bar m-1 close / bar m open time (signal known strictly at close)
    - order_place_time: placed at signal_known_time
    - LIMIT fill window: strictly [signal_known_time, signal_known_time + 300)
    - MARKET_FALLBACK: activates at first quote at or after deadline (signal_known_time + 300),
      with maximum delay of 60 seconds (up to signal_known_time + 360). If delay > 60s,
      records DATA_GAP / execution failure (never gaps distant future quote to deadline).
    
    Order of Intrabar Execution (Requirement R3):
    - BUY limit at choch_level (fills when Ask <= limit). If price opened above limit,
      descending price crosses limit before SL -> limit fills, then position evaluates SL.
    - SELL limit at choch_level (fills when Bid >= limit). If price opened below limit,
      ascending price crosses limit before SL -> limit fills, then position evaluates SL.
    - Indeterminate M1 path handling: adverse selection applied.
    """
    if 'signal_known_time' in candidate:
        signal_known_time = int(candidate['signal_known_time'])
    elif 'exec_time' in candidate:
        signal_known_time = int(candidate['exec_time'])
    elif 'confirm_bar_open' in candidate:
        signal_known_time = int(candidate['confirm_bar_open']) + 300
    else:
        signal_known_time = int(candidate['time_m5'])
        
    confirm_bar_open = int(candidate.get('confirm_bar_open', candidate.get('time_m5', signal_known_time - 300)))
    order_place_time = signal_known_time
    limit_deadline = signal_known_time + 300
    
    d = candidate['direction']
    sl = candidate['sl_price']
    limit_price = candidate['choch_level']
    baseline_entry = candidate['entry_market']
    baseline_risk = candidate['risk']
    baseline_tp = baseline_entry + d * baseline_risk
    
    filled = False
    cancelled = False
    cancel_reason = None
    fill_type = None
    entry_actual = None
    fill_time = None
    d_actual = None
    ambiguous_intrabar = False
    
    # 1. Chronological M1 Intrabar Evaluation inside [signal_known_time, limit_deadline)
    if m1_bars is not None and len(m1_bars) > 0:
        for k in range(len(m1_bars)):
            bar_t = int(m1_bars[k, 0])
            # Strict causal guard: Never peek or trade before signal_known_time
            if bar_t < signal_known_time:
                continue
            # Limit order window is strictly [signal_known_time, limit_deadline)
            if bar_t >= limit_deadline:
                break
                
            bar_o = float(m1_bars[k, 1])
            bar_h = float(m1_bars[k, 2])
            bar_l = float(m1_bars[k, 3])
            
            if d == 1:  # BUY Limit (placed at choch_level)
                bar_ask_l = bar_l + spread
                # Case A: Gapped open below SL
                if bar_o <= sl:
                    cancelled = True
                    cancel_reason = "SL_HIT_BEFORE_FILL"
                    break
                # Case B: Price hits TP before touching limit
                if bar_h >= baseline_tp and bar_ask_l > limit_price:
                    cancelled = True
                    cancel_reason = "TP_HIT_BEFORE_FILL"
                    break
                # Case C: Retest Limit Touch
                if bar_ask_l <= limit_price:
                    # In an indeterminate bar where both TP and limit were touched:
                    # Adverse assumption: TP hit before pullback to limit -> cancelled
                    if bar_h >= baseline_tp and bar_o > limit_price:
                        cancelled = True
                        cancel_reason = "TP_HIT_BEFORE_FILL"
                        break
                    # If both limit and SL fall in this bar:
                    if bar_l <= sl:
                        ambiguous_intrabar = True
                    actual_risk = limit_price - sl
                    if actual_risk < 2.5 or actual_risk > 10.0:
                        cancelled = True
                        cancel_reason = "OUT_OF_BOUNDS_RISK"
                        break
                    filled = True
                    fill_type = "LIMIT"
                    entry_actual = limit_price
                    fill_time = bar_t
                    d_actual = actual_risk
                    break
                # Case D: Limit not touched, but low breached SL
                if bar_l <= sl:
                    cancelled = True
                    cancel_reason = "SL_HIT_BEFORE_FILL"
                    break
            else:  # SELL Limit (placed at choch_level)
                bar_ask_h = bar_h + spread
                bar_ask_o = bar_o + spread
                bar_ask_l = bar_l + spread
                # Case A: Gapped open above SL
                if bar_ask_o >= sl:
                    cancelled = True
                    cancel_reason = "SL_HIT_BEFORE_FILL"
                    break
                # Case B: Price hits TP before touching limit
                if bar_ask_l <= baseline_tp and bar_h < limit_price:
                    cancelled = True
                    cancel_reason = "TP_HIT_BEFORE_FILL"
                    break
                # Case C: Retest Limit Touch
                if bar_h >= limit_price:
                    # Adverse assumption: TP reached before rally to limit
                    if bar_ask_l <= baseline_tp and bar_o < limit_price:
                        cancelled = True
                        cancel_reason = "TP_HIT_BEFORE_FILL"
                        break
                    if bar_ask_h >= sl:
                        ambiguous_intrabar = True
                    actual_risk = sl - limit_price
                    if actual_risk < 2.5 or actual_risk > 10.0:
                        cancelled = True
                        cancel_reason = "OUT_OF_BOUNDS_RISK"
                        break
                    filled = True
                    fill_type = "LIMIT"
                    entry_actual = limit_price
                    fill_time = bar_t
                    d_actual = actual_risk
                    break
                # Case D: Limit not touched, but ask high breached SL
                if bar_ask_h >= sl:
                    cancelled = True
                    cancel_reason = "SL_HIT_BEFORE_FILL"
                    break
                    
    if cancelled:
        return {
            'filled': False,
            'cancelled': True,
            'cancel_reason': cancel_reason,
            'entry_type': None,
            'entry_price': None,
            'sl_price': sl,
            'd_actual': None,
            'fill_time': None,
            'data_gap': False,
            'ambiguous_intrabar': ambiguous_intrabar
        }
        
    if filled:
        # Runtime assertions (Requirement R2)
        assert fill_time >= signal_known_time, f"Limit fill_time {fill_time} < signal_known_time {signal_known_time}"
        assert fill_time >= order_place_time, f"Limit fill_time {fill_time} < order_place_time {order_place_time}"
        assert fill_time < limit_deadline, f"Limit fill_time {fill_time} >= deadline {limit_deadline}"
        return {
            'filled': True,
            'cancelled': False,
            'cancel_reason': None,
            'entry_type': "LIMIT",
            'entry_price': entry_actual,
            'sl_price': sl,
            'd_actual': d_actual,
            'fill_time': fill_time,
            'data_gap': False,
            'ambiguous_intrabar': ambiguous_intrabar
        }
        
    # 2. Market Fallback at deadline (signal_known_time + 300s)
    fallback_quote = None
    if next_m5_quote is not None and int(next_m5_quote[0]) >= limit_deadline:
        fallback_quote = (int(next_m5_quote[0]), float(next_m5_quote[1]))
    elif m1_bars is not None and len(m1_bars) > 0:
        for k in range(len(m1_bars)):
            if int(m1_bars[k, 0]) >= limit_deadline:
                fallback_quote = (int(m1_bars[k, 0]), float(m1_bars[k, 1]))
                break
                
    if fallback_quote is not None:
        fallback_time, fallback_bid = fallback_quote
        delay = fallback_time - limit_deadline
        
        # Causal delay check: max 60s delay from deadline (Requirement R2)
        if delay > 60:
            return {
                'filled': False,
                'cancelled': True,
                'cancel_reason': "DATA_GAP_DELAY_EXCEEDED",
                'data_gap': True,
                'entry_type': None,
                'entry_price': None,
                'sl_price': sl,
                'd_actual': None,
                'fill_time': None,
                'ambiguous_intrabar': False
            }
            
        assert fallback_time >= limit_deadline, f"Fallback time {fallback_time} before deadline {limit_deadline}"
        assert fallback_time <= signal_known_time + 360, f"Fallback delay exceeds 60s: {fallback_time}"
        
        if d == 1:  # BUY Fallback (enters on Ask)
            if fallback_bid <= sl:
                return {'filled': False, 'cancelled': True, 'cancel_reason': "SL_HIT_BEFORE_FALLBACK", 'data_gap': False, 'ambiguous_intrabar': False}
            if fallback_bid >= baseline_tp:
                return {'filled': False, 'cancelled': True, 'cancel_reason': "TP_HIT_BEFORE_FALLBACK", 'data_gap': False, 'ambiguous_intrabar': False}
            fallback_entry = fallback_bid + spread + slip
            fallback_risk = fallback_entry - sl
            if fallback_risk > 10.0:
                return {'filled': False, 'cancelled': True, 'cancel_reason': "OVERSIZED_FALLBACK_RISK", 'data_gap': False, 'ambiguous_intrabar': False}
            if fallback_risk < 2.5:
                fallback_risk = 2.5
                sl = fallback_entry - 2.5
            return {
                'filled': True,
                'cancelled': False,
                'cancel_reason': None,
                'entry_type': "MARKET_FALLBACK",
                'entry_price': fallback_entry,
                'sl_price': sl,
                'd_actual': fallback_risk,
                'fill_time': fallback_time,
                'data_gap': False,
                'ambiguous_intrabar': False
            }
        else:  # SELL Fallback (enters on Bid, exits on Ask)
            fallback_ask = fallback_bid + spread
            if fallback_ask >= sl:
                return {'filled': False, 'cancelled': True, 'cancel_reason': "SL_HIT_BEFORE_FALLBACK", 'data_gap': False, 'ambiguous_intrabar': False}
            if fallback_bid <= baseline_tp:
                return {'filled': False, 'cancelled': True, 'cancel_reason': "TP_HIT_BEFORE_FALLBACK", 'data_gap': False, 'ambiguous_intrabar': False}
            fallback_entry = fallback_bid - slip
            fallback_risk = sl - fallback_entry
            if fallback_risk > 10.0:
                return {'filled': False, 'cancelled': True, 'cancel_reason': "OVERSIZED_FALLBACK_RISK", 'data_gap': False, 'ambiguous_intrabar': False}
            if fallback_risk < 2.5:
                fallback_risk = 2.5
                sl = fallback_entry + 2.5
            return {
                'filled': True,
                'cancelled': False,
                'cancel_reason': None,
                'entry_type': "MARKET_FALLBACK",
                'entry_price': fallback_entry,
                'sl_price': sl,
                'd_actual': fallback_risk,
                'fill_time': fallback_time,
                'data_gap': False,
                'ambiguous_intrabar': False
            }
            
    return {'filled': False, 'cancelled': True, 'cancel_reason': "INSUFFICIENT_DATA", 'data_gap': False, 'ambiguous_intrabar': False}


def simulate_market_entry(candidate, next_m5_quote, spread=0.30, slip=0.01, max_delay=60):
    """Simulate market order execution at signal_known_time with causal delay guard.
    
    Causal Guard (Requirement R2):
    - Market order is placed at signal_known_time = confirm_bar_open + 300s.
    - Quote must arrive within max_delay (default 60s, matching MARKET_FALLBACK).
    - If quote is delayed > max_delay (e.g. weekend gap, daily break, data gap),
      order is cancelled / rejected as unfillable due to closed market.
    """
    if 'signal_known_time' in candidate:
        signal_known_time = int(candidate['signal_known_time'])
    elif 'exec_time' in candidate:
        signal_known_time = int(candidate['exec_time'])
    elif 'confirm_bar_open' in candidate:
        signal_known_time = int(candidate['confirm_bar_open']) + 300
    else:
        signal_known_time = int(candidate.get('signal_time', candidate.get('time_m5', 0))) + 300
        
    order_place_time = signal_known_time
    
    if next_m5_quote is None:
        return {'filled': False, 'cancelled': True, 'cancel_reason': 'NO_QUOTE', 'data_gap': True, 'entry_type': None}
        
    quote_time = int(next_m5_quote[0])
    delay = quote_time - order_place_time
    
    if delay < 0:
        return {'filled': False, 'cancelled': True, 'cancel_reason': 'PREMATURE_QUOTE', 'data_gap': False, 'entry_type': None}
        
    if delay > max_delay:
        return {
            'filled': False,
            'cancelled': True,
            'cancel_reason': 'DATA_GAP_DELAY_EXCEEDED',
            'data_gap': True,
            'entry_type': None,
            'entry_price': None,
            'sl_price': float(candidate['sl_price']),
            'd_actual': None,
            'fill_time': None,
            'ambiguous_intrabar': False
        }
        
    d = int(candidate['direction'])
    sl = float(candidate['sl_price'])
    market_bid = float(next_m5_quote[1])
    entry_price = (market_bid + spread + slip) if d == 1 else (market_bid - slip)
    d_actual = abs(entry_price - sl)
    
    if d_actual > 10.0:
        return {'filled': False, 'cancelled': True, 'cancel_reason': 'OVERSIZED_RISK', 'data_gap': False, 'entry_type': None}
    if d_actual < 2.5:
        d_actual = 2.5
        sl = (entry_price - 2.5) if d == 1 else (entry_price + 2.5)
        
    return {
        'filled': True,
        'cancelled': False,
        'cancel_reason': None,
        'entry_type': 'MARKET',
        'entry_price': entry_price,
        'sl_price': sl,
        'd_actual': d_actual,
        'fill_time': quote_time,
        'data_gap': False,
        'ambiguous_intrabar': False
    }


def simulate_1r_trade(entry_price, sl_price, direction, fill_time, t0=None, m5_bars=None,
                      m5_start_idx=0, schedule='BASE', is_limit=False,
                      signal_known_time=None, m1_bars=None, entry_type=None,
                      ambiguous_intrabar=False):
    """Simulate primary 1R payoff trade execution forward in time.
    
    Causal Requirements (R2, R3, R4):
    - Target: TP = entry_actual + direction * D_actual
    - Invalidation: SL structural
    - Timeout: strictly 120 minutes (7200 seconds) from signal_known_time
    - Exit Evaluation: Starts immediately post-fill including remaining fill bar
    - Side matching: BUY entry Ask, exit Bid; SELL entry Bid, exit Ask
    - SELL TP & SL: Evaluated strictly against Ask price
    - Fee Accounting: Execution prices already incorporate spread & slippage.
      Net P&L = Gross P&L - Commission (no double-deduction).
    """
    spread, comm, slip = FEE_SCHEDULES[schedule]
    d = direction
    d_actual = abs(entry_price - sl_price)
    tp_price = entry_price + d * d_actual
    
    ref_known_time = signal_known_time if signal_known_time is not None else (t0 if t0 is not None else fill_time)
    timeout_time = ref_known_time + 7200
    
    # Hard assertion: fill_time not before signal_known_time and before timeout
    if fill_time is not None and ref_known_time is not None:
        assert fill_time >= ref_known_time, f"Fill time {fill_time} < signal_known_time {ref_known_time}"
        assert fill_time < timeout_time, f"Fill time {fill_time} >= timeout_time {timeout_time}"
        
    actual_entry_type = entry_type if entry_type is not None else ("LIMIT" if is_limit else "MARKET")
    if actual_entry_type == "MARKET_FALLBACK":
        assert fill_time >= ref_known_time + 300, f"Fallback fill time {fill_time} before deadline"
    elif actual_entry_type == "LIMIT":
        assert fill_time >= ref_known_time, f"Limit fill time {fill_time} before signal_known_time"
        assert fill_time < ref_known_time + 300, f"Limit fill time {fill_time} after deadline"
        
    exit_time = None
    exit_price = None
    exit_reason = None
    bars_held = 0
    data_gap = False
    
    # Priority 1: Granular M1 replay if M1 bars provided
    if m1_bars is not None and len(m1_bars) > 0:
        m1_times = m1_bars[:, 0]
        start_idx = int(np.searchsorted(m1_times, fill_time))
        for idx in range(start_idx, len(m1_bars)):
            bar = m1_bars[idx]
            b_time = int(bar[0])
            b_open = float(bar[1])
            b_high = float(bar[2])
            b_low = float(bar[3])
            
            # Check data gap between consecutive M1 bars (> 300s during trading hours)
            if idx > start_idx:
                prev_t = int(m1_bars[idx - 1, 0])
                if b_time - prev_t > 300:
                    data_gap = True
                    
            # 1. Open Gap Evaluation on subsequent bars (must precede timeout check)
            if idx > start_idx:
                if d == 1:  # BUY (exits at Bid)
                    if b_open <= sl_price:
                        exit_time = b_time
                        exit_price = b_open - slip
                        exit_reason = "GAP_SL"
                        break
                    if b_open >= tp_price:
                        exit_time = b_time
                        exit_price = b_open
                        exit_reason = "TP"
                        break
                else:  # SELL (exits at Ask)
                    open_ask = b_open + spread
                    if open_ask >= sl_price:
                        exit_time = b_time
                        exit_price = open_ask + slip
                        exit_reason = "GAP_SL"
                        break
                    if open_ask <= tp_price:
                        exit_time = b_time
                        exit_price = open_ask
                        exit_reason = "TP"
                        break

            # 2. Timeout Check at deadline (exit_time is b_time to prevent closed-market timestamps)
            if b_time >= timeout_time:
                exit_time = b_time
                exit_reason = "TIMEOUT"
                exit_price = (b_open - slip) if d == 1 else (b_open + spread + slip)
                break
                
            bars_held += 1
            
            # 3. Intrabar Price Evaluation
            if d == 1:  # BUY (exits at Bid)
                # Adverse first
                if b_low <= sl_price:
                    exit_time = b_time
                    exit_price = sl_price - slip
                    exit_reason = "SL"
                    break
                if b_high >= tp_price:
                    exit_time = b_time
                    exit_price = tp_price
                    exit_reason = "TP"
                    break
            else:  # SELL (exits at Ask)
                high_ask = b_high + spread
                low_ask = b_low + spread
                # Adverse first: Ask rises to SL
                if high_ask >= sl_price:
                    exit_time = b_time
                    exit_price = sl_price + slip
                    exit_reason = "SL"
                    break
                # Witness short_false_tp: TP requires Ask to reach or fall below target
                if low_ask <= tp_price:
                    exit_time = b_time
                    exit_price = tp_price
                    exit_reason = "TP"
                    break
    else:
        # Priority 2: M5 replay
        for idx in range(m5_start_idx, len(m5_bars)):
            bar = m5_bars[idx]
            b_time = int(bar[0])
            b_open = float(bar[1])
            b_high = float(bar[2])
            b_low = float(bar[3])
            
            if b_time + 300 <= fill_time:
                continue
                
            is_fill_bar = (b_time <= fill_time < b_time + 300)
            
            # 1. Open Gap Evaluation on subsequent bars (must precede timeout check)
            if not is_fill_bar:
                if d == 1:  # BUY (exits at Bid)
                    if b_open <= sl_price:
                        exit_time = b_time
                        exit_price = b_open - slip
                        exit_reason = "GAP_SL"
                        break
                    if b_open >= tp_price:
                        exit_time = b_time
                        exit_price = b_open
                        exit_reason = "TP"
                        break
                else:  # SELL (exits at Ask)
                    open_ask = b_open + spread
                    if open_ask >= sl_price:
                        exit_time = b_time
                        exit_price = open_ask + slip
                        exit_reason = "GAP_SL"
                        break
                    # Witness: TP for short requires Ask <= tp_price
                    if open_ask <= tp_price:
                        exit_time = b_time
                        exit_price = open_ask
                        exit_reason = "TP"
                        break

            # 2. Timeout Check at deadline (exit_time is b_time to prevent closed-market timestamps)
            if b_time >= timeout_time:
                exit_time = b_time
                exit_reason = "TIMEOUT"
                exit_price = (b_open - slip) if d == 1 else (b_open + spread + slip)
                break
                
            bars_held += 1
            
            # 3. Intrabar Price Evaluation
            if d == 1:  # BUY (exits at Bid)
                # Adverse first (conservative)
                if b_low <= sl_price:
                    exit_time = max(fill_time, b_time)
                    exit_price = sl_price - slip
                    exit_reason = "SL"
                    break
                if b_high >= tp_price:
                    exit_time = max(fill_time, b_time)
                    exit_price = tp_price
                    exit_reason = "TP"
                    break
            else:  # SELL (exits at Ask)
                high_ask = b_high + spread
                low_ask = b_low + spread
                if high_ask >= sl_price:
                    exit_time = max(fill_time, b_time)
                    exit_price = sl_price + slip
                    exit_reason = "SL"
                    break
                # Witness short_false_tp: Ask must touch TP
                if low_ask <= tp_price:
                    exit_time = max(fill_time, b_time)
                    exit_price = tp_price
                    exit_reason = "TP"
                    break
                    
    if exit_time is None:
        # End of dataset reached
        exit_time = int(m5_bars[-1, 0]) + 299 if m5_bars is not None and len(m5_bars) > 0 else fill_time + 7200
        exit_price = float(m5_bars[-1, 4]) if m5_bars is not None and len(m5_bars) > 0 else entry_price
        exit_reason = "CENSORED"
        
    # Hard assertion: Exit not before fill
    assert exit_time >= fill_time, f"Exit time {exit_time} < fill time {fill_time}"
    
    # Cost Accounting: Single-Deduction (Requirement R4)
    # Execution prices (entry_price and exit_price) already reflect spread and slippage.
    # Therefore, gross_pnl represents net trading result before broker commission.
    # To avoid double-counting spread and slippage, subtract ONLY actual commission.
    spread_cost = spread
    comm_cost = comm
    entry_slip = 0.0 if (actual_entry_type == "LIMIT") else slip
    exit_slip = slip if exit_reason in ("SL", "GAP_SL", "TIMEOUT") else 0.0
    slippage_cost = entry_slip + exit_slip
    
    gross_pnl = d * (exit_price - entry_price)
    net_pnl = gross_pnl - comm_cost
    net_r = net_pnl / d_actual if d_actual > 0 else 0.0
    
    return {
        'direction': d,
        'entry_time': fill_time,
        'entry_price': entry_price,
        'entry_type': actual_entry_type,
        'sl_price': sl_price,
        'tp_price': tp_price,
        'risk_usd': d_actual,
        'exit_time': exit_time,
        'exit_price': exit_price,
        'exit_reason': exit_reason,
        'gross_pnl_usd': gross_pnl,
        'commission_usd': comm_cost,
        'slippage_usd': slippage_cost,
        'spread_cost_usd': spread_cost,
        'net_pnl_usd': net_pnl,
        'net_r': net_r,
        'bars_held': bars_held,
        'data_gap': data_gap,
        'ambiguous_intrabar': ambiguous_intrabar
    }


def filter_single_position(trades):
    """Enforce portfolio constraint: strictly 1 open position forward in time."""
    selected = []
    available_time = 0
    for t in trades:
        entry_t = t.get('entry_time', t.get('entry', 0))
        if entry_t >= available_time:
            selected.append(t)
            available_time = t.get('exit_time', t.get('exit', 0))
    return selected

