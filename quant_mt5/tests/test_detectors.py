"""Acceptance: H1 boundary (M2), lifecycle, prefix replay, future mutation, D1/DST, controls share catalog, determinism."""
import copy

import numpy as np
import pytest

from quantmt5.detectors import detect_A, detect_B, detect_all, load_symbol
from quantmt5.util import canonical_json
from synth import T0, bars, flat_m5, symbol_data

H = T0 + 24 * 3600  # Tuesday 00:00 anchor


def _setup_a_rows():
    rows = flat_m5(288)                                   # Monday: zone U=100.5 D=99.5, ATR≈1
    rows += [(100, 100.5, 99.5, 100.0)]                   # h+0
    rows += [(100, 101.2, 99.9, 101.0)]                   # h+5  breakout long (close 101.0 >= 100.51)
    rows += [(101, 101.1, 100.6, 100.9)]                  # h+10 bearish → not a retest
    rows += [(100.55, 100.9, 100.45, 100.85)]             # h+15 retest R1 (before any H1 confirmation)
    rows += [(100.9, 101.0, 100.8, 100.9)] * 8            # h+20..h+55 hold above
    rows += [(100.55, 100.9, 100.45, 100.85)]             # h+60 retest R2 (after H1 [h,h+1h) closed beyond U)
    rows += [(100.8, 100.8, 98.9, 99.0)]                  # h+65 close < U-delta → invalidated
    rows += [(99.0, 99.2, 98.8, 99.0)] * 20
    return rows


def test_setup_A_lifecycle_and_M2_h1_boundary():
    sd = symbol_data(_setup_a_rows())
    eps, cands = detect_A(sd)
    ep = [e for e in eps if e["anchor_ts"] == H and e["side"] == "LONG"]
    assert len(ep) == 1
    ep = ep[0]
    assert ep["U"] == 100.5 and ep["D"] == 99.5
    assert ep["state"] == "INVALIDATED"
    assert [t["state"] for t in ep["transitions"]] == ["WATCHING_RETEST", "INVALIDATED"]
    mine = [c for c in cands if c["episode_id"] == ep["episode_id"]]
    assert len(mine) == 2
    r1, r2 = mine
    assert r1["signal_bar"]["open_at"].endswith("00:15:00Z") and r2["signal_bar"]["open_at"].endswith("01:00:00Z")
    assert r1["gates"]["M0"]["result"] == "PASS" and r2["gates"]["M0"]["result"] == "PASS"
    # H1 that closes after R1 must not confirm R1 retroactively
    assert r1["gates"]["M2"]["result"] == "FAIL" and r1["gates"]["M2"]["h1_closed_after_breakout"] is False
    assert r2["gates"]["M2"]["result"] == "PASS"
    # EMA50 needs 250 H1 bars → UNKNOWN, never silently PASS/FAIL
    assert r1["gates"]["M1"]["result"] == "UNKNOWN" and r1["gates"]["M1"]["reason"] == "EMA50_WARMUP"
    # SL buffer / delta frozen at anchor from ATR known at h
    assert ep["delta"] == pytest.approx(0.1, abs=0.011) and ep["buffer"] >= 0.02


def test_setup_A_prefix_and_future_mutation():
    rows = _setup_a_rows()
    sd = symbol_data(rows)
    _, full = detect_A(sd)
    r1 = [c for c in full if c["signal_bar"]["open_at"].endswith("00:15:00Z") and c["side"] == "LONG"][0]
    # prefix: only data available at R1 ready
    sd_p = symbol_data(rows)
    for name in ("m5", "h1", "d1"):
        setattr(sd_p, name, getattr(sd_p, name).upto_available(r1["ready_ts"]))
    sd_p.__post_init__()
    _, pre = detect_A(sd_p)
    assert canonical_json([c for c in pre if c["ready_ts"] <= r1["ready_ts"]]) == canonical_json([c for c in full if c["ready_ts"] <= r1["ready_ts"]])
    # future mutation: change every bar after R1 → R1 unchanged
    k = r1["signal_index"]
    mut = rows[:k + 1] + [(o * 1.03, h * 1.03, l * 1.03, c * 1.03) for (o, h, l, c) in rows[k + 1:]]
    _, mfull = detect_A(symbol_data(mut))
    assert canonical_json([c for c in mfull if c["ready_ts"] <= r1["ready_ts"]]) == canonical_json([c for c in full if c["ready_ts"] <= r1["ready_ts"]])


def _fakey_rows(at_index, flat_before=None):
    rows = flat_m5(flat_before if flat_before is not None else at_index)
    rows += [(100.0, 100.3, 99.5, 99.8),     # mother: low exactly at PDL 99.5
             (99.9, 100.2, 99.6, 100.0),     # inside
             (99.8, 100.1, 99.3, 100.0)]     # fakey long: breaks below mother & PDL, closes back in, bullish
    rows += flat_m5(10, price=100.0, half_range=0.05)
    return rows


def test_setup_B_long_at_previous_day_low():
    sd = symbol_data(_fakey_rows(288 + 12))
    cands = [c for c in detect_B(sd) if c["mother_bar"]["index"] == 300]
    assert len(cands) == 1
    c = cands[0]
    assert c["side"] == "LONG"
    assert c["gates"]["P0"]["result"] == "PASS"
    assert c["gates"]["P1"]["result"] == "PASS" and c["gates"]["P1"]["PDL"] == 99.5 and c["gates"]["P1"]["prev_day_id"] == "2025-01-06"
    assert c["gates"]["P2"]["result"] == "FAIL" and c["gates"]["P2"]["in_window"] is False  # 01:15 UTC = 20:15 NY


def test_setup_B_previous_day_not_available_at_day_start():
    """Mother bar at 00:00: previous D1 is only available at 00:00:01 (assumed arrival) → P1 UNKNOWN, not FALSE."""
    sd = symbol_data(_fakey_rows(288))
    c = [c for c in detect_B(sd) if c["mother_bar"]["index"] == 288][0]
    assert c["gates"]["P0"]["result"] == "PASS"
    assert c["gates"]["P1"]["result"] == "UNKNOWN" and c["gates"]["P1"]["reason"] == "PREV_D1_NOT_AVAILABLE_BEFORE_MOTHER"
    assert c["gates"]["P1"]["prev_day_id"] == "2025-01-06" and "PDL" not in c["gates"]["P1"]
    assert c["gates"]["P2"]["result"] == "UNKNOWN"


def test_setup_B_previous_day_too_old_is_unknown():
    day1 = flat_m5(288)
    m5a = bars(300, T0, day1)
    later = T0 + 6 * 86400  # Sunday after a 5-day hole
    rows2 = flat_m5(24, start=later) + [(100.0, 100.3, 99.5, 99.8), (99.9, 100.2, 99.6, 100.0), (99.8, 100.1, 99.3, 100.0)] + flat_m5(5)
    m5b = bars(300, later, rows2)
    import numpy as _np
    from quantmt5.data import Bars, aggregate
    from quantmt5.detectors import SymbolData
    cat = lambda f: _np.concatenate([getattr(m5a, f), getattr(m5b, f)])
    m5 = Bars("TEST", "M5", **{f: cat(f) for f in ("open_raw", "open_at", "close_at", "available_at", "o", "h", "l", "c", "tick_volume", "real_volume", "spread")},
              provenance=m5a.provenance)
    from synth import PROF
    sd = SymbolData("TEST", m5, aggregate(m5, "H1"), aggregate(m5, "D1"), None, 0.01, dict(PROF), "s")
    c = [c for c in detect_B(sd) if c["setup"] == "B"]
    # the day before the mother's broker day (Saturday) has no D1 → UNKNOWN; never falls back to the older Monday D1
    assert c and c[0]["gates"]["P1"]["result"] == "UNKNOWN" and c[0]["gates"]["P1"]["reason"] == "PREV_D1_MISSING"
    assert c[0]["gates"]["P1"]["prev_day_expected"] == "2025-01-11" and "PDL" not in c[0]["gates"]["P1"]


def test_controls_share_one_raw_catalog(xau_catalog):
    cands = xau_catalog["candidates"]
    a = [c for c in cands if c["setup"] == "A"]
    b = [c for c in cands if c["setup"] == "B"]
    # every candidate carries all branch gates; gates never remove a candidate from the catalog
    assert all(set(c["gates"]) == {"M0", "M1", "M2"} for c in a)
    assert all(set(c["gates"]) == {"P0", "P1", "P2"} for c in b)
    p1 = {c["candidate_id"] for c in b if c["gates"]["P1"]["result"] == "PASS"}
    p2 = {c["candidate_id"] for c in b if c["gates"]["P2"]["result"] == "PASS"}
    p0 = {c["candidate_id"] for c in b if c["gates"]["P0"]["result"] == "PASS"}
    assert p2 <= p1 <= p0
    assert len({c["candidate_id"] for c in cands}) == len(cands)


def test_prefix_replay_real_xau(xau, xau_catalog):
    """Batch over a prefix must reproduce exactly what the full run emitted for that prefix (IDs, gates, levels)."""
    full = xau_catalog
    ts = [c["ready_ts"] for c in full["candidates"]]
    for q in (0.25, 0.6, 0.9):
        T = float(np.quantile(ts, q))
        sd_p = load_symbol("XAUUSD", cut_available_at=T)
        pre = detect_all(sd_p)
        want = sorted([c for c in full["candidates"] if c["ready_ts"] <= T], key=lambda c: c["candidate_id"])
        got = sorted([c for c in pre["candidates"] if c["ready_ts"] <= T], key=lambda c: c["candidate_id"])
        assert canonical_json(got) == canonical_json(want), f"prefix mismatch at q={q}"
        ep_want = {e["episode_id"] for e in full["episodes"] if e["breakout_available_at"] <= _iso(T)}
        ep_got = {e["episode_id"] for e in pre["episodes"] if e["breakout_available_at"] <= _iso(T)}
        assert ep_got == ep_want


def test_future_mutation_real_xau(xau_catalog):
    from quantmt5.detectors import SymbolData
    ts = sorted(c["ready_ts"] for c in xau_catalog["candidates"])
    T = ts[len(ts) // 2]
    sd = load_symbol("XAUUSD")
    m = copy.deepcopy(sd.m5)
    later = m.available_at > T
    for f in ("o", "h", "l", "c"):
        getattr(m, f)[later] *= 1.07
    m.tick_volume[later] = 1
    from quantmt5.data import aggregate
    sd2 = SymbolData("XAUUSD", m, sd.h1, sd.d1, sd.m1, sd.q, sd.prof, sd.source_id)
    h1 = copy.deepcopy(sd.h1)
    hl = h1.available_at > T
    for f in ("o", "h", "l", "c"):
        getattr(h1, f)[hl] *= 1.07
    sd2.h1 = h1
    sd2.__post_init__()
    mutated = detect_all(sd2)
    want = [c for c in xau_catalog["candidates"] if c["ready_ts"] <= T]
    got = [c for c in mutated["candidates"] if c["ready_ts"] <= T]
    assert canonical_json(sorted(got, key=lambda c: c["candidate_id"])) == canonical_json(sorted(want, key=lambda c: c["candidate_id"]))


def test_two_agents_same_snapshot_inputs_same_outputs():
    a = detect_all(load_symbol("USDJPY"))
    b = detect_all(load_symbol("USDJPY"))
    assert canonical_json(a) == canonical_json(b)


def _iso(t):
    from quantmt5.util import iso_utc
    return iso_utc(t)
