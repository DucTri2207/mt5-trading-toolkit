"""Source-faithful H1 zone / sweep / confirmation research primitives.

Chronological OHLC arrays: time, open, high, low, close. This is NOT the P2
detector. The zone loop, score, flip, fallback and first-break veto reproduce
duc_tri_can_ho_tro_scalp.mq5 v3.12, with explicit closed-bar inputs.
"""
from __future__ import annotations

import math
import numpy as np
from numba import njit

ZONE_COLUMNS = ['base_index', 'base_len', 'supply', 'flip', 'distal', 'proximal',
                'score', 'tests', 'broken', 'age', 'broken_index', 'base_time',
                'time_end', 'available_at', 'native_id', 'flip_origin']
CANDIDATE_COLUMNS = [
    'confirm_open', 'known_at', 'buy', 'zone_time', 'base_len', 'flip', 'flip_origin',
    'native_zone_id', 'score', 'test_count', 'distal', 'proximal', 'zone_available_at',
    'sweep_time', 'sweep_price', 'pivot_time', 'pivot_price', 'pivot_known_at',
    'atr', 'raw_stop', 'structural_anchor', 'signal_close', 'body50',
    'trend_time', 'trend_close', 'trend_ema', 'trend_atr', 'source_gate',
    'c0_gate', 'obstacle_market', 'obstacle_body50', 'obstacle_market_time',
    'obstacle_body50_time', 'zone_rank', 'm5_index', 'h1_count',
]
GATE_NAMES = {0: 'PASS', 1: 'BODY', 2: 'HOUR', 3: 'TREND', 4: 'EMA_DISTANCE',
              5: 'LEVEL_NOT_KNOWN_AT_SWEEP'}


def bars_matrix(rates):
    return np.column_stack([rates[n] for n in ('time', 'open', 'high', 'low', 'close')]).astype(np.float64)


@njit(cache=True)
def metaquotes_atr(bars, period=14):
    """MetaQuotes Examples/ATR.mq5: rolling mean TR, NOT Wilder smoothing."""
    out = np.zeros(len(bars))
    tr = np.zeros(len(bars))
    for i in range(1, len(bars)):
        tr[i] = max(bars[i, 2], bars[i-1, 4]) - min(bars[i, 3], bars[i-1, 4])
    if len(bars) <= period:
        return out
    value = 0.
    for i in range(1, period+1):
        value += tr[i]
    out[period] = value / period
    for i in range(period+1, len(bars)):
        out[i] = out[i-1] + (tr[i]-tr[i-period])/period
    return out


@njit(cache=True)
def ema50(bars):
    out = np.empty(len(bars))
    if len(bars):
        out[0] = bars[0, 4]
    for i in range(1, len(bars)):
        out[i] = bars[i, 4]*(2./51.)+out[i-1]*(49./51.)
    return out


@njit(cache=True)
def source_zones(bars, atr, count, bar_seconds=3600):
    """Original ScanHtfMacroZones numerical body; count contains closed H1 only.

    Ignoring bases already beyond MaxAge is equivalent to the original inner
    continue: none can append a zone or advance i by baseLen there.
    """
    out = np.empty((4000, 16))
    used = 0
    n = min(count, 2000)
    offset = count-n
    if n < 39:
        return out[:0]
    i = max(20, n-1-1200)
    end = n-5
    while i <= end:
        a = atr[offset+i]
        if a <= 0:
            i += 1
            continue
        accepted = 0
        for base_len in range(1, 6):
            base_end = i+base_len-1
            if base_end > end:
                break
            b_high, b_low = -1., 9999999.
            valid = True
            for b in range(i, base_end+1):
                high, low = bars[offset+b, 2], bars[offset+b, 3]
                if high-low > .8*a:
                    valid = False
                    break
                b_high, b_low = max(b_high, high), min(b_low, low)
            if not valid or b_high-b_low > 2.*a:
                continue
            dep_low, dep_high = 9999999., -1.
            for d in range(base_end+1, base_end+5):
                dep_low = min(dep_low, bars[offset+d, 3])
                dep_high = max(dep_high, bars[offset+d, 2])
            supply = False
            strength = 0.
            if b_low-dep_low >= 1.8*a:
                supply = True
                strength = (b_low-dep_low)/a
            elif dep_high-b_high >= 1.8*a:
                strength = (dep_high-b_high)/a
            else:
                continue
            leg_move = bars[offset+i, 4]-bars[offset+max(0, i-15), 4]
            reversal = (supply and leg_move > 0) or (not supply and leg_move < 0)
            distal = b_high if supply else b_low
            proximal = b_low if supply else b_high
            tests, broken, broken_bar = 0, False, -1
            inside_before = False
            time_end = bars[count-1, 0]
            for f in range(base_end+5, n):
                inside = bars[offset+f, 2] >= b_low and bars[offset+f, 3] <= b_high
                if inside and not inside_before:
                    tests += 1
                inside_before = inside
                if (supply and bars[offset+f, 4] > distal) or (not supply and bars[offset+f, 4] < distal):
                    broken = True
                    broken_bar = f
                    time_end = bars[offset+f, 0]
                    break
            score_dep = min(40., (strength/1.8)*28.)
            score_base = 20. if base_len == 1 else (15. if base_len == 2 else 10.)
            score_fresh = 20. if tests == 0 else (10. if tests == 1 else (5. if tests == 2 else 0.))
            score = min(100., score_dep+score_base+score_fresh+(10. if reversal else 5.))
            available = bars[offset+base_end+4, 0]+bar_seconds
            out[used] = np.array([offset+i, base_len, int(supply), 0, distal, proximal,
                                  math.floor(score+.5), tests, int(broken), n-1-i,
                                  offset+broken_bar if broken else -1, bars[offset+i, 0],
                                  time_end, available, used+1, 0.])
            used += 1
            if broken and broken_bar > 0:
                life = min(n-1, broken_bar+400)
                flip_supply = not supply
                f_tests, f_broken = 0, False
                f_time_end = bars[offset+life, 0]
                for k in range(broken_bar+1, n):
                    if k > life:
                        break
                    if bars[offset+k, 2] >= distal and bars[offset+k, 3] <= distal:
                        f_tests += 1
                    if (flip_supply and bars[offset+k, 4] > proximal) or (not flip_supply and bars[offset+k, 4] < proximal):
                        f_broken = True
                        f_time_end = bars[offset+k, 0]
                        break
                    if f_tests >= 4:
                        f_time_end = bars[offset+k, 0]
                        break
                if not f_broken:
                    out[used] = np.array([offset+i, base_len, int(flip_supply), 1,
                                          proximal, distal, math.floor(score*.85+.5),
                                          f_tests, 0, n-1-broken_bar, offset+broken_bar,
                                          bars[offset+i, 0], f_time_end,
                                          bars[offset+broken_bar, 0]+bar_seconds, used+1,
                                          bars[offset+broken_bar, 0]])
                    used += 1
            accepted = base_len
            break
        # Source is a for-loop: explicit i+=baseLen followed by outer ++i.
        i += accepted+1
    return out[:used]


@njit(cache=True)
def obstacle(zones, buy, entry, day_high, day_low, day_time):
    best = 0.
    best_time = 0.
    level = day_high if buy else day_low
    if (buy and level > entry) or (not buy and 0 < level < entry):
        best, best_time = level, day_time
    for z in zones:
        if z[8] != 0 or bool(z[2]) == (not buy):
            continue
        lo, hi = min(z[4], z[5]), max(z[4], z[5])
        if lo <= entry <= hi:
            return entry, z[11]
        level = z[5]
        if (buy and level > entry) or (not buy and level < entry):
            if best == 0 or abs(level-entry) < abs(best-entry):
                best, best_time = level, z[11]
    return best, best_time


@njit(cache=True)
def raw_at(m5, atr5, c, zones, h1, atr1, ma1, h_count, day_high=0., day_low=0., day_time=0., closed_only=False, bar_seconds=300):
    out = np.empty((len(zones), 36))
    used = 0
    if c < 28 or atr5[c] <= 0:
        return out[:0]
    a = atr5[c]
    for rank in range(len(zones)):
        z = zones[rank]
        if z[8] != 0 or z[6] < 35:
            continue
        supply = bool(z[2])
        lo, hi = min(z[4], z[5]), max(z[4], z[5])
        touched = False
        for age in range(1, 21):
            k = c+1-age
            if supply:
                touched = m5[k, 2] >= lo-.2*a and m5[k, 3] <= hi+.5*a
            else:
                touched = m5[k, 3] <= hi+.2*a and m5[k, 2] >= lo-.5*a
            if touched:
                break
        if not touched:
            continue
        sweep, sweep_age = (-1. if supply else 9999999.), -1
        for age in range(1, 21):
            k = c+1-age
            rng = m5[k, 2]-m5[k, 3]
            if rng < .25*a:
                continue
            wick = m5[k, 2]-max(m5[k, 1], m5[k, 4]) if supply else min(m5[k, 1], m5[k, 4])-m5[k, 3]
            level = lo if supply else hi
            reclaimed = (m5[k, 2] >= level and m5[k, 4] < level) if supply else (m5[k, 3] <= level and m5[k, 4] > level)
            extreme = m5[k, 2] if supply else m5[k, 3]
            if wick/rng >= .5 and reclaimed and ((supply and extreme > sweep) or (not supply and extreme < sweep)):
                sweep, sweep_age = extreme, age
        if sweep_age < 1:
            continue
        start, end = sweep_age-2, max(1, sweep_age-8)
        pivot_age, pivot = -1, (9999999. if supply else -1.)
        for sw in range(start, end-1, -1):
            p = c+1-sw
            if sw < 1 or (closed_only and sw == 1):
                continue
            price = m5[p, 3] if supply else m5[p, 2]
            # Source can let a forming-bar neighbour validate pivot age1,
            # vetoing its fallback despite no later closed confirmation.
            # L0 reproduces that veto; C0 removes that dependency explicitly.
            newer = (m5[c+1, 1] if c+1 < len(m5) else m5[c, 4]) if sw == 1 else (m5[p+1, 3] if supply else m5[p+1, 2])
            if (supply and price <= m5[p-1, 3] and price <= newer) or (not supply and price >= m5[p-1, 2] and price >= newer):
                pivot_age, pivot = sw, price
                break
        if pivot_age < 0:
            for sw in range(start, max(1, sweep_age-4)-1, -1):
                p = c+1-sw
                price = m5[p, 3] if supply else m5[p, 2]
                if (supply and price < pivot) or (not supply and price > pivot):
                    pivot_age, pivot = sw, price
        confirm_age = -1
        for age in range(pivot_age-1, 0, -1):
            k = c+1-age
            if (not supply and pivot > 0 and m5[k, 4] > pivot and m5[k, 4] > m5[k, 1]) or (supply and pivot < 9999990 and m5[k, 4] < pivot and m5[k, 4] < m5[k, 1]):
                confirm_age = age
                break
        if confirm_age != 1:
            continue
        buy = not supply
        gate = 0
        if abs(m5[c, 4]-m5[c, 1]) < .25*a:
            gate = 1
        hour = int(m5[c, 0]//3600) % 24
        if gate == 0 and hour not in (8, 9, 10, 11, 13, 15, 16, 17):
            gate = 2
        trend = np.searchsorted(h1[:, 0], m5[c, 0], side='right')-2
        if trend < 0:
            continue
        if gate == 0 and ((buy and h1[trend, 4] <= ma1[trend]) or (not buy and h1[trend, 4] >= ma1[trend])):
            gate = 3
        if gate == 0 and (atr1[trend] <= 0 or abs(h1[trend, 4]-ma1[trend])/atr1[trend] > 1.75):
            gate = 4
        sweep_idx = c+1-sweep_age
        left = c+1-max(5, sweep_age)
        anchor = m5[c, 3] if buy else m5[c, 2]
        for k in range(max(0, left), c+1):
            anchor = min(anchor, m5[k, 3]) if buy else max(anchor, m5[k, 2])
        raw_stop = anchor+(-.25 if buy else .25)*a
        midpoint = (m5[c, 1]+m5[c, 4])/2.
        obs_m, obs_mt = obstacle(zones, buy, m5[c, 4], day_high, day_low, day_time)
        obs_l, obs_lt = obstacle(zones, buy, midpoint, day_high, day_low, day_time)
        p = c+1-pivot_age
        c0_gate = 5 if z[13] > m5[sweep_idx, 0] else 0
        out[used] = np.array([m5[c, 0], m5[c, 0]+bar_seconds, int(buy), z[11], z[1], z[3], z[15],
                             z[14], z[6], z[7], z[4], z[5], z[13], m5[sweep_idx, 0], sweep,
                             m5[p, 0], pivot, m5[min(c, p+1), 0]+bar_seconds, a, raw_stop, anchor,
                             m5[c, 4], midpoint, h1[trend, 0], h1[trend, 4], ma1[trend],
                             atr1[trend], gate, c0_gate, obs_m, obs_l, obs_mt, obs_lt,
                             rank, c, h_count])
        used += 1
    return out[:used]


@njit(cache=True)
def detect_all(h1, m5, d1, atr1, atr5, ma1, start, stop, closed_only=False, bar_seconds=300):
    chunks = []
    first_seen = np.zeros((len(h1), 5, 2))
    h_count, old_h_count, day_count = 0, -1, 0
    zones = np.empty((0, 16))
    snapshot_rows = []
    for c in range(29, len(m5)):
        at = m5[c, 0]+bar_seconds
        if at > stop:
            break
        while h_count < len(h1) and h1[h_count, 0]+3600 <= at:
            h_count += 1
        if h_count != old_h_count:
            zones = source_zones(h1, atr1, h_count)
            for z in zones:
                bi, bl, fl = int(z[0]), int(z[1])-1, int(z[3])
                if first_seen[bi, bl, fl] == 0:
                    first_seen[bi, bl, fl] = h1[h_count-1, 0]+3600
                z[13] = max(z[13], first_seen[bi, bl, fl])
            if at >= start:
                snapshot_rows.append(np.array([at, h_count, len(zones), np.sum(zones[:, 6]), np.sum(zones[:, 7])]))
            old_h_count = h_count
        while day_count < len(d1) and d1[day_count, 0]+86400 <= at:
            day_count += 1
        if at < start or at >= stop:
            continue
        dh, dl, dt = (d1[day_count-1, 2], d1[day_count-1, 3], d1[day_count-1, 0]) if day_count else (0., 0., 0.)
        found = raw_at(m5, atr5, c, zones, h1, atr1, ma1, h_count, dh, dl, dt, closed_only, bar_seconds)
        for row in found:
            chunks.append(row)
    result = np.empty((len(chunks), 36))
    for i in range(len(chunks)):
        result[i] = chunks[i]
    snaps = np.empty((len(snapshot_rows), 5))
    for i in range(len(snapshot_rows)):
        snaps[i] = snapshot_rows[i]
    return result, snaps
