"""B2 acceptance — hand-computable synthetic fixtures (all SYNTHETIC, RAW_IS_UTC clock, tick 0.01).

Base day (Monday 2025-01-06): 288 flat M5 bars O=C=100, H=100.5, L=99.5 → TR=1 → ATR14=1.0 exactly,
delta=ceil(max(0.02, 0.10*1.0))=0.10, buffer=0.05, eps=0.01; zone of the 8 H1 before Tuesday 00:00: U=100.5, D=99.5.
"""
import copy
import datetime as dt

import numpy as np
import pytest

from quantmt5.data import aggregate
from quantmt5.detectors import SymbolData, detect_A, detect_B, detect_all
from quantmt5.util import canonical_json, iso_utc
from synth import PROF, T0, bars, flat_m5, symbol_data

H = T0 + 86400          # Tuesday 00:00 UTC anchor
FX = {"kind": "ROLLOVER_ONLY", "tz": "America/New_York", "rollover": "17:00", "weekly_close": "Fri 17:00"}
HOLD_L = (100.9, 101.0, 100.8, 100.9)
HOLD_S = (99.1, 99.2, 99.0, 99.1)


def A(rows_after_anchor, tail=20, tail_bar=(99.0, 99.2, 98.8, 99.0)):
    return symbol_data(flat_m5(288) + rows_after_anchor + [tail_bar] * tail)


def eps_for(sd, anchor_ts):
    eps, cands = detect_A(sd)
    return [e for e in eps if e["anchor_ts"] == anchor_ts], cands


# ---------------------------------------------------------------- Setup A
def test_A_short_mirror_positive_and_negatives():
    rows = [(100, 100.5, 99.5, 100.0),                 # h+0
            (100, 100.1, 98.8, 99.0),                  # h+5 breakout short: 99.0 <= 99.49, prev 100 > 99.49
            (99.45, 99.55, 99.1, 99.15),               # h+10 retest short ✓ (H in 99.4..99.6, C<=99.49, bearish, lower half)
            (99.15, 99.55, 99.1, 99.3),                # h+15 bullish → not a retest
            (99.45, 99.7, 99.1, 99.15),                # h+20 high 99.7 outside D±delta → not a retest
            (99.48, 99.55, 99.40, 99.495)]             # h+25 close 99.495 > D-eps 99.49 → not a retest
    rows += [HOLD_S] * 4
    sd = A(rows, tail_bar=HOLD_S)
    ep, cands = eps_for(sd, H)
    assert len(ep) == 1 and ep[0]["side"] == "SHORT" and ep[0]["D"] == 99.5 and ep[0]["delta"] == pytest.approx(0.1)
    mine = [c for c in cands if c["episode_id"] == ep[0]["episode_id"]]
    assert [c["signal_bar"]["open_at"][-9:-1] for c in mine] == ["00:10:00"]
    c = mine[0]
    assert c["level"] == 99.5 and c["buffer"] == pytest.approx(0.05) and c["atr_frozen"] == pytest.approx(1.0)
    assert c["gates"]["M2"]["edge"] == "D" and c["gates"]["M2"]["result"] == "FAIL"   # no H1 closed after breakout yet


def test_A_end_of_hour_breakout_belongs_to_its_open_hour_and_is_not_a_retest():
    # breakout bar opens h+55 (closes h+60, in the next hour) and itself looks like a retest
    rows = [(100, 100.5, 99.5, 100.0)] * 11 + [(100.45, 101.0, 100.45, 100.95)] + [HOLD_L] * 3
    sd = A(rows, tail_bar=HOLD_L)
    ep, cands = eps_for(sd, H)
    assert len(ep) == 1 and ep[0]["anchor_at"] == iso_utc(H)
    assert ep[0]["breakout_bar"]["open_at"] == iso_utc(H + 55 * 60) and ep[0]["breakout_close_at"] == iso_utc(H + 3600)
    assert not [c for c in cands if c["signal_bar"]["open_at"] == ep[0]["breakout_bar"]["open_at"]]


def _same_close_rows():
    # breakout at h+5, hold, retest bar opens h+55 → closes exactly at the H1 close h+60
    return [(100, 100.5, 99.5, 100.0), (100, 101.2, 99.9, 101.0)] + [HOLD_L] * 9 + [(100.55, 100.9, 100.45, 100.85)] + [HOLD_L] * 3


def test_A_same_close_H1_used_when_in_sync():
    sd = A(_same_close_rows(), tail_bar=HOLD_L)
    ep, cands = eps_for(sd, H)
    c = [c for c in cands if c["episode_id"] == ep[0]["episode_id"]][0]
    assert c["signal_close_ts"] == H + 3600
    g = c["gates"]["M2"]
    assert g["result"] == "PASS" and g["h1_close_at"] == iso_utc(H + 3600)       # same-instant H1 closing beyond U
    assert c["ready_ts"] == H + 3600 + 1


@pytest.mark.parametrize("lag,expect", [(4, "PASS"), (10, "UNKNOWN")])
def test_A_same_close_H1_late_arrival_and_sync_timeout(lag, expect):
    sd = A(_same_close_rows(), tail_bar=HOLD_L)
    j = int(np.flatnonzero(sd.h1.close_at == H + 3600)[0])
    sd.h1.available_at = sd.h1.available_at.copy()
    sd.h1.available_at[j] = H + 3600 + lag                                     # M5 available at +1 s; timeout 5 s
    ep, cands = eps_for(sd, H)
    c = [c for c in cands if c["episode_id"] == ep[0]["episode_id"]][0]
    assert c["gates"]["M2"]["result"] == expect and c["gates"]["M1"]["result"] in ("UNKNOWN",)
    if expect == "PASS":
        assert c["ready_ts"] == H + 3600 + lag
    else:
        assert c["gates"]["M2"]["reason"] == "H1_SYNC_TIMEOUT" and c["ready_ts"] == H + 3600 + 1 + 5
        assert c["gates"]["M0"]["result"] == "PASS"                             # raw candidate kept; only the H1 gates are UNKNOWN


def test_A_ttl_boundary():
    # breakout closes h+10 → expires h+100. Retest closing h+95 counts; retest closing exactly h+100 does not.
    base = [(100, 100.5, 99.5, 100.0), (100, 101.2, 99.9, 101.0)] + [HOLD_L] * 16       # bars open h+10..h+85
    ok = base + [(100.55, 100.9, 100.45, 100.85)] + [HOLD_L] * 3                         # opens h+90 closes h+95
    late = base + [HOLD_L] + [(100.55, 100.9, 100.45, 100.85)] + [HOLD_L] * 3            # opens h+95 closes h+100
    e1, c1 = eps_for(A(ok, tail_bar=HOLD_L), H)
    e2, c2 = eps_for(A(late, tail_bar=HOLD_L), H)
    assert e1[0]["expires_at"] == iso_utc(H + 100 * 60)
    assert [c["signal_close_ts"] for c in c1 if c["episode_id"] == e1[0]["episode_id"]] == [H + 95 * 60]
    assert not [c for c in c2 if c["episode_id"] == e2[0]["episode_id"]]
    assert e2[0]["state"] == "EXPIRED" and e2[0]["transitions"][-1]["event_at"] == iso_utc(H + 100 * 60)


def test_A_gap_blocks_episode():
    rows = [(100, 100.5, 99.5, 100.0), (100, 101.2, 99.9, 101.0)] + [HOLD_L] * 5
    sd = A(rows, tail_bar=HOLD_L)
    keep = np.ones(len(sd.m5), bool)
    keep[288 + 4] = False                                                       # drop the bar opening h+20
    m5 = sd.m5
    for f in ("open_raw", "open_at", "close_at", "available_at", "o", "h", "l", "c", "tick_volume", "real_volume", "spread"):
        setattr(m5, f, getattr(m5, f)[keep])
    sd2 = SymbolData("TEST", m5, aggregate(m5, "H1"), aggregate(m5, "D1"), None, 0.01, dict(PROF), "s")
    ep, _ = eps_for(sd2, H)
    assert ep[0]["state"] == "DATA_BLOCKED" and ep[0]["transitions"][-1]["reason"] == "M5_GAP_STATE_UNKNOWN"


def test_A_anchor_used_once():
    rows = [(100, 100.5, 99.5, 100.0), (100, 101.2, 99.9, 101.0),   # h+5 breakout
            (101, 101.0, 99.9, 100.0),                             # h+10 close 100.0 < U-delta → invalidated
            (100, 101.2, 99.9, 101.0)]                             # h+15 crosses again, same anchor hour
    ep, _ = eps_for(A(rows), H)
    assert len(ep) == 1 and ep[0]["state"] == "INVALIDATED"


def test_A_late_anchor_never_creates_retroactive_episode():
    rows = [(100, 101.2, 99.9, 101.0)] + [HOLD_L] * 3           # breakout in the very first bar of the hour
    sd = A(rows, tail_bar=HOLD_L)
    j = int(np.flatnonzero(sd.h1.close_at == H)[0])
    sd.h1.available_at = sd.h1.available_at.copy()
    sd.h1.available_at[j] = H + 400                                 # anchor data arrives after the breakout bar (avail H+301)
    ep, _ = eps_for(sd, H)
    assert ep == [] and sd.diagnostics["breakouts_before_anchor_activation"] == 1
    sd_ok = A(rows, tail_bar=HOLD_L)
    assert len(eps_for(sd_ok, H)[0]) == 1                            # same data, on-time anchor → episode


def test_A_revision_id_changes_with_inputs_logical_id_stable():
    rows = _same_close_rows()
    c1 = [c for c in detect_A(A(rows, tail_bar=HOLD_L))[1] if c["signal_close_ts"] == H + 3600][0]
    rows2 = list(rows)
    rows2[11] = (100.55, 100.95, 100.45, 100.85)                    # retest high changes, still a retest
    c2 = [c for c in detect_A(A(rows2, tail_bar=HOLD_L))[1] if c["signal_close_ts"] == H + 3600][0]
    assert c1["candidate_id"] == c2["candidate_id"] and c1["revision_id"] != c2["revision_id"]
    assert c1["lifecycle"][0]["state"] == "DETECTED" and c1["eligibility"]["M0"] == "ELIGIBLE"
    assert c1["entry_deadline_ts"] == H + 3600 + 90


def test_A_synthetic_restart_incremental_equals_batch():
    rows = _same_close_rows()
    full_sd = A(rows, tail_bar=HOLD_L)
    j = int(np.flatnonzero(full_sd.h1.close_at == H + 3600)[0])
    full_sd.h1.available_at = full_sd.h1.available_at.copy()
    full_sd.h1.available_at[j] = H + 3600 + 4
    full = detect_all(full_sd)["candidates"]
    seen = {}
    for cut in range(H, H + 2 * 3600, 37):                          # restart every 37 s, incl. between M5 and H1 arrival
        sd = A(rows, tail_bar=HOLD_L)
        sd.h1.available_at = full_sd.h1.available_at.copy()
        for name in ("m5", "h1", "d1"):
            setattr(sd, name, getattr(sd, name).upto_available(cut))
        sd.__post_init__()
        for c in detect_all(sd)["candidates"]:
            if c["ready_ts"] <= cut:                                # decided at the restart point
                seen.setdefault(c["candidate_id"], c)
    want = {c["candidate_id"]: c for c in full if H <= c["ready_ts"] <= H + 2 * 3600 - 37}
    for cid, c in want.items():
        assert cid in seen and canonical_json(seen[cid]) == canonical_json(c), cid


# ---------------------------------------------------------------- Setup B
def B(pattern, at=300, pre=None, prof=None, start=T0):
    rows = (pre if pre is not None else flat_m5(at)) + pattern + flat_m5(10, price=100.0, half_range=0.05)
    return symbol_data(rows, start=start, prof=prof)


def _b(sd, mother_index):
    return [c for c in detect_B(sd) if c["mother_bar"]["index"] == mother_index]


SHORT_AT_PDH = [(100.2, 100.5, 99.9, 100.3), (100.2, 100.4, 100.0, 100.3), (100.3, 100.8, 100.0, 100.1)]
LONG_AT_PDL = [(100.0, 100.3, 99.5, 99.8), (99.9, 100.2, 99.6, 100.0), (99.8, 100.1, 99.3, 100.0)]


def test_B_short_at_previous_day_high():
    c = _b(B(SHORT_AT_PDH), 300)
    assert len(c) == 1 and c[0]["side"] == "SHORT"
    g = c[0]["gates"]
    assert g["P0"]["result"] == "PASS" and g["P1"]["result"] == "PASS" and g["P1"]["PDH"] == 100.5 and g["P1"]["level_used"] == 100.5
    assert c[0]["atr_frozen"] == pytest.approx(1.0) and c[0]["delta"] == pytest.approx(0.1)


def test_B_strict_inside_boundary():
    edge = [SHORT_AT_PDH[0], (100.2, 100.49, 100.0, 100.3), SHORT_AT_PDH[2]]     # H_I == H_M - eps → inside
    over = [SHORT_AT_PDH[0], (100.2, 100.50, 100.0, 100.3), SHORT_AT_PDH[2]]     # H_I == H_M → not inside
    assert len(_b(B(edge), 300)) == 1 and _b(B(over), 300) == []


def test_B_fakey_breaking_both_sides_is_rejected():
    both = [LONG_AT_PDL[0], LONG_AT_PDL[1], (99.8, 100.4, 99.3, 100.0)]           # F breaks below AND above mother
    assert _b(B(both), 300) == []


def test_B_atr_frozen_before_mother_ignores_pattern_bars():
    wild = [(100.0, 100.3, 99.5, 99.8), (99.9, 100.2, 99.6, 100.0), (99.8, 100.1, 90.0, 100.0)]   # huge F range
    c = _b(B(wild), 300)[0]
    # historical arrival assumption close+1s: bar 299 (closes at mother open) is only available 1 s AFTER the mother
    # opens, so the causal ATR state is the prefix ending at bar 298
    assert c["atr_frozen"] == pytest.approx(1.0) and c["atr_bar_close_at"] == iso_utc(T0 + 299 * 300)
    assert c["atr_source"]["stale_bars"] == 1 and c["atr_source"]["prefix_available_at"] <= c["mother_bar"]["open_at"]


def test_B_atr_warmup_keeps_raw_pattern_and_marks_p1_unknown():
    c = _b(B(LONG_AT_PDL, at=50), 50)[0]
    assert c["gates"]["P0"]["result"] == "PASS"
    assert c["gates"]["P1"] == {"result": "UNKNOWN", "reason": "ATR_WARMUP", "evaluated_at": c["ready_at"]}
    assert c["gates"]["P2"]["result"] == "UNKNOWN" and c["eligibility"]["P1"] == "UNKNOWN"


def test_B_missing_previous_trading_day_is_unknown_not_older_day():
    prof = dict(PROF, session=FX)
    mon = flat_m5(288)
    wed_pre = flat_m5(12, start=T0 + 2 * 86400)
    # Monday bars, NO Tuesday bars, Wednesday 00:00-01:00 flat then the pattern
    rows_mon = bars(300, T0, mon)
    rows_wed = bars(300, T0 + 2 * 86400, wed_pre + LONG_AT_PDL + flat_m5(5))
    from quantmt5.data import Bars
    cat = lambda f: np.concatenate([getattr(rows_mon, f), getattr(rows_wed, f)])
    m5 = Bars("TEST", "M5", **{f: cat(f) for f in ("open_raw", "open_at", "close_at", "available_at", "o", "h", "l", "c", "tick_volume", "real_volume", "spread")},
              provenance=rows_mon.provenance)
    sd = SymbolData("TEST", m5, aggregate(m5, "H1"), aggregate(m5, "D1"), None, 0.01, prof, "s")
    c = [c for c in detect_B(sd) if c["mother_bar"]["open_at"] == iso_utc(T0 + 2 * 86400 + 3600)][0]
    p1 = c["gates"]["P1"]
    assert p1["result"] == "UNKNOWN" and p1["reason"] == "PREV_D1_MISSING" and p1["prev_day_expected"] == "2025-01-07"
    assert p1["prev_day_rule"].startswith("SCHEDULE") and "RAW_DAY_BUCKET" in p1["prev_day_rule"]


MON_PATTERN = [(100.0, 100.3, 99.3, 99.8), (99.9, 100.2, 99.6, 100.0), (99.8, 100.1, 99.1, 100.0)]


def _fri_mon(prof):
    from quantmt5.data import Bars
    fri = T0 - 3 * 86400
    rows_fri = bars(300, fri, [(100, 100.7, 99.3, 100)] * 288)                   # Friday: PDH 100.7, PDL 99.3
    rows_mon = bars(300, T0, flat_m5(12) + MON_PATTERN + flat_m5(5))
    cat = lambda f: np.concatenate([getattr(rows_fri, f), getattr(rows_mon, f)])
    m5 = Bars("TEST", "M5", **{f: cat(f) for f in ("open_raw", "open_at", "close_at", "available_at", "o", "h", "l", "c", "tick_volume", "real_volume", "spread")},
              provenance=rows_fri.provenance)
    return SymbolData("TEST", m5, aggregate(m5, "H1"), aggregate(m5, "D1"), None, 0.01, prof, "s")


def test_B_short_open_sunday_without_D1_is_unknown_not_friday():
    """F2: UTC-day buckets + FX schedule → Sunday UTC has 2 h scheduled open (22:00–24:00) → it IS the previous broker
    day. No Sunday D1 supplied → UNKNOWN; never substituted by Friday (no 6-hour rule)."""
    sd = _fri_mon(dict(PROF, session=FX))
    c = [c for c in detect_B(sd) if c["mother_bar"]["open_at"] == iso_utc(T0 + 3600)][0]
    p1 = c["gates"]["P1"]
    assert p1["result"] == "UNKNOWN" and p1["reason"] == "PREV_D1_MISSING" and p1["prev_day_expected"] == "2025-01-05"
    assert p1["skipped_closed_days"] == []
    # without a schedule the previous CALENDAR day is required → also UNKNOWN, never Friday by guess
    sd2 = _fri_mon(dict(PROF))
    c2 = [c for c in detect_B(sd2) if c["mother_bar"]["open_at"] == iso_utc(T0 + 3600)][0]
    assert c2["gates"]["P1"]["result"] == "UNKNOWN" and c2["gates"]["P1"]["reason"] == "PREV_D1_MISSING"
    assert c2["gates"]["P1"]["prev_day_rule"].startswith("NO_SCHEDULE")


def test_B_fully_closed_weekend_under_declared_boundary_uses_friday():
    """Declared broker boundary 00:00 Europe/Athens (EET-like server day): Sat and Sun Athens days have zero scheduled
    FX minutes (FX reopens Mon 00:00 Athens) → skipped as closed; previous broker day = Friday."""
    from quantmt5.data import Bars
    sess = dict(FX, d1_boundary={"tz": "Europe/Athens", "day_start": "00:00", "status": "DECLARED_FOR_FIXTURE"})
    fri0 = int(dt.datetime(2025, 1, 2, 22, tzinfo=dt.timezone.utc).timestamp())   # Fri 00:00 Athens
    mon0 = int(dt.datetime(2025, 1, 5, 22, tzinfo=dt.timezone.utc).timestamp())   # Mon 00:00 Athens
    rows_fri = bars(300, fri0, [(100, 100.7, 99.3, 100)] * 288)
    rows_mon = bars(300, mon0, flat_m5(12) + MON_PATTERN + flat_m5(5))
    cat = lambda f: np.concatenate([getattr(rows_fri, f), getattr(rows_mon, f)])
    m5 = Bars("TEST", "M5", **{f: cat(f) for f in ("open_raw", "open_at", "close_at", "available_at", "o", "h", "l", "c", "tick_volume", "real_volume", "spread")},
              provenance=rows_fri.provenance)
    d1 = bars(86400, fri0, [(100, 100.7, 99.3, 100)], tf="D1")                    # native Friday D1 opening at Athens midnight
    sd = SymbolData("TEST", m5, aggregate(m5, "H1"), d1, None, 0.01, dict(PROF, session=sess), "s")
    c = [c for c in detect_B(sd) if c["mother_bar"]["open_at"] == iso_utc(mon0 + 3600)][0]
    p1 = c["gates"]["P1"]
    assert p1["prev_day_id"] == "2025-01-03" and p1["PDL"] == 99.3 and p1["result"] == "PASS"
    assert p1["skipped_closed_days"] == ["2025-01-05", "2025-01-04"] and "DECLARED_BOUNDARY" in p1["prev_day_rule"]
    # a missing working day under the same contract → UNKNOWN (Thursday mother needs Wednesday)
    sd2 = SymbolData("TEST", m5, aggregate(m5, "H1"), bars(86400, mon0, [(100, 100.7, 99.3, 100)], tf="D1"), None, 0.01, dict(PROF, session=sess), "s")
    c2 = [c for c in detect_B(sd2) if c["mother_bar"]["open_at"] == iso_utc(mon0 + 3600)][0]
    assert c2["gates"]["P1"]["result"] == "UNKNOWN" and c2["gates"]["P1"]["reason"] == "PREV_D1_MISSING"
    assert c2["gates"]["P1"]["prev_day_expected"] == "2025-01-03"


def test_B_atr_late_dependencies_are_unknown_or_older_prefix():
    """F1: (a) last bar before mother arrives late → older fully-available prefix is used (stale_bars recorded);
    (b) a bar in the middle of the seed prefix arrives late → no fully available prefix past warmup → UNKNOWN,
    raw P0 kept; (c) no retroactive change: the same candidate computed later stays identical."""
    sd = B(LONG_AT_PDL)
    mo = int(sd.m5.open_at[300])
    sd.m5.available_at = sd.m5.available_at.copy()
    sd.m5.available_at[299] = mo + 3600
    c = _b(sd, 300)[0]
    assert c["atr_source"]["index"] == 298 and c["atr_source"]["stale_bars"] == 1
    sd_mid = B(LONG_AT_PDL)
    sd_mid.m5.available_at = sd_mid.m5.available_at.copy()
    sd_mid.m5.available_at[150] = mo + 7200
    cm = _b(sd_mid, 300)[0]
    assert cm["gates"]["P0"]["result"] == "PASS" and cm["atr_frozen"] is None
    assert cm["gates"]["P1"]["result"] == "UNKNOWN" and cm["gates"]["P1"]["reason"] == "ATR_SOURCE_NOT_AVAILABLE_AT_FREEZE"
    cw = _b(B(LONG_AT_PDL, at=50), 50)[0]
    assert cw["gates"]["P1"]["reason"] == "ATR_WARMUP"                      # warmup shortage is a different reason


def test_revision_tracks_dependencies_but_not_unrelated_future():
    """F3: logical ids stable; revision changes with breakout/expiry; appending unrelated future bars changes nothing."""
    early = [(100, 101.2, 99.9, 101.0)] + [HOLD_L] * 10 + [(100.55, 100.9, 100.45, 100.85)] + [HOLD_L] * 3
    late = [(100, 100.5, 99.5, 100)] + [(100, 101.2, 99.9, 101.0)] + [HOLD_L] * 9 + [(100.55, 100.9, 100.45, 100.85)] + [HOLD_L] * 3
    pick = lambda sd: [c for c in detect_A(sd)[1] if c["signal_close_ts"] == H + 3600][0]
    a, b = pick(A(early, tail_bar=HOLD_L)), pick(A(late, tail_bar=HOLD_L))
    assert a["candidate_id"] == b["candidate_id"] and a["revision_id"] != b["revision_id"]
    a_more = pick(A(early, tail=200, tail_bar=HOLD_L))                         # unrelated future appended
    assert a_more["revision_id"] == a["revision_id"]
    cb1 = _b(B(SHORT_AT_PDH), 300)[0]
    cb2 = _b(B(SHORT_AT_PDH + [(100, 100.2, 99.8, 100)] * 50), 300)[0]
    assert cb1["revision_id"] == cb2["revision_id"]


@pytest.mark.parametrize("start,expect_in", [(T0, False),                                       # Jan: 12:30 UTC = 07:30 NY
                                             (int(dt.datetime(2025, 7, 7, tzinfo=dt.timezone.utc).timestamp()), True)])  # Jul: 08:30 NY
def test_B_p2_window_is_dst_aware(start, expect_in):
    # pattern on day 2 so that F closes at 12:30 UTC; previous day = day 1 (flat, PDL 99.5)
    pre = flat_m5(288 + 12 * 12 + 3)                                 # mother = bar 147 of day 2 → opens 12:15; F 12:25–12:30
    sd = B(LONG_AT_PDL, pre=pre, start=start)
    c = [c for c in detect_B(sd) if c["signal_bar"]["close_at"] == iso_utc(start + 86400 + 12 * 3600 + 1800)][0]
    assert c["gates"]["P1"]["result"] == "PASS"
    assert c["gates"]["P2"]["in_window"] is expect_in and c["gates"]["P2"]["result"] == ("PASS" if expect_in else "FAIL")


def test_B_future_mutation_and_prefix_do_not_change_past():
    sd = B(SHORT_AT_PDH)
    full = detect_B(sd)
    c = _b(sd, 300)[0]
    T = c["ready_ts"]
    sd_mut = B(SHORT_AT_PDH)
    later = sd_mut.m5.available_at > T
    for f in ("o", "h", "l", "c"):
        getattr(sd_mut.m5, f)[later] *= 1.1
    sd_mut.d1 = aggregate(sd_mut.m5, "D1")
    sd_mut.__post_init__()
    got = [x for x in detect_B(sd_mut) if x["ready_ts"] <= T]
    assert canonical_json(got) == canonical_json([x for x in full if x["ready_ts"] <= T])


# ---------------------------------------------------------------- F4 arrival boundaries (out-of-order arrival)
def _late(sd, idx_to_delay: dict):
    sd.m5.available_at = sd.m5.available_at.copy()
    for i, t in idx_to_delay.items():
        sd.m5.available_at[i] = t
    sd.h1 = aggregate(sd.m5, "H1")
    sd.d1 = aggregate(sd.m5, "D1")
    sd.__post_init__()
    return sd


def test_F4a_asof_view_never_contains_future_arrivals_and_withholds_after_hole():
    sd = B(LONG_AT_PDL)
    cut = int(sd.m5.available_at[302])
    _late(sd, {150: cut + 3600})
    v = sd.m5.upto_available(cut)
    assert (v.available_at <= cut).all() and len(v) == 150                    # prefix stops before the hole
    assert v.provenance["asof_withheld_rows"] == 302 - 150 and "ARRIVAL_HOLE_BARS_WITHHELD" in v.provenance["data_quality_flags"]
    after = sd.m5.upto_available(cut + 3600)                                    # hole filled → full prefix, nothing withheld
    assert len(after) == len(sd.m5) and "asof_withheld_rows" not in after.provenance
    h1v = sd.h1.upto_available(cut)
    assert (h1v.available_at <= cut).all()                                       # derived H1 inherits member arrival


def test_F4b_mother_or_inside_late_delays_decision_not_deadline():
    for late_idx in (300, 301):                                                 # mother, inside
        sd = B(LONG_AT_PDL)
        f_known = int(sd.m5.available_at[302])
        _late(sd, {late_idx: f_known + 1800})
        c = _b(sd, 300)[0]
        assert c["ready_ts"] == f_known + 1800 and c["gates"]["P0"]["evaluated_at"] == iso_utc(f_known + 1800)
        assert c["entry_deadline_ts"] == c["signal_close_ts"] + 90                # deadline stays at F.close + 90 s
        from quantmt5.snapshot import plan_window
        assert plan_window(c, c["ready_ts"])["P0"] == "EXPIRED"                 # known only after deadline → never an open entry
        assert c["lifecycle"][0]["available_at"] == iso_utc(f_known + 1800)


def test_F4c_cross_waits_for_predecessor_and_late_after_ttl_never_offers_entry():
    rows = [(100, 100.5, 99.5, 100.0)] + _same_close_rows()                    # breakout bar = index 290 (opens h+10)
    # (i) predecessor arrives 20 min late, still inside TTL → episode known then; retests ready >= that
    sd = _late(A(rows, tail_bar=HOLD_L), {289: H + 1800})
    ep, cands = eps_for(sd, H)
    assert ep and ep[0]["breakout_available_at"] == iso_utc(H + 1800)
    assert all(c["ready_ts"] >= H + 1800 for c in cands if c["episode_id"] == ep[0]["episode_id"])
    # (ii) predecessor arrives after the TTL → episode recorded as EXPIRED, no retest candidates at all
    sd2 = _late(A(rows, tail_bar=HOLD_L), {289: H + 7200})
    ep2, cands2 = eps_for(sd2, H)
    assert ep2[0]["state"] == "EXPIRED" and ep2[0]["transitions"][-1]["reason"] == "BREAKOUT_KNOWN_ONLY_AFTER_TTL"
    assert not [c for c in cands2 if c["episode_id"] == ep2[0]["episode_id"]]


def test_F4_batch_equals_restart_decisions_with_out_of_order_arrivals():
    """Same rule for batch and as-of restarts: every candidate decided at a restart point equals the batch record."""
    rows = flat_m5(288) + [(100, 100.5, 99.5, 100.0)] + _same_close_rows()[1:] + LONG_AT_PDL + SHORT_AT_PDH + [HOLD_L] * 40
    base = A(rows[288:], tail_bar=HOLD_L)
    delays = {150: H + 600, 289: H + 1500, 300: H + 4000, int(len(base.m5) - 30): H + 9000}
    full_sd = _late(A(rows[288:], tail_bar=HOLD_L), delays)
    full = detect_all(full_sd)["candidates"]
    span = range(int(H), int(H + 4 * 3600), 113)
    seen = {}
    for cut in span:
        sd = _late(A(rows[288:], tail_bar=HOLD_L), delays)
        for name in ("m5", "h1", "d1"):
            setattr(sd, name, getattr(sd, name).upto_available(cut))
        sd.__post_init__()
        for c in detect_all(sd)["candidates"]:
            if c["ready_ts"] <= cut:
                assert canonical_json(c) == canonical_json(next(x for x in full if x["candidate_id"] == c["candidate_id"])), (cut, c["candidate_id"])
                seen[c["candidate_id"]] = cut
    want = [c["candidate_id"] for c in full if c["ready_ts"] <= span[-1]]
    assert want and set(want) <= set(seen)                                       # nothing decided only in batch
    assert all(seen[c["candidate_id"]] >= c["ready_ts"] for c in full if c["candidate_id"] in seen)


def test_F4_scan_is_partial_not_empty_when_bars_are_withheld(tmp_path, monkeypatch):
    from quantmt5.snapshot import scan
    snap = {"symbols": {"S": {"status": "OK", "quality_flags": ["ARRIVAL_HOLE_BARS_WITHHELD:M5"]}}, "candidates": [], "episodes": [], "errors": []}
    assert scan(snap)["status"] == "PARTIAL"
    snap["symbols"]["S"]["quality_flags"] = []
    assert scan(snap)["status"] == "OK_EMPTY"


@pytest.fixture(scope="module")
def real_snap():
    from quantmt5.snapshot import make_snapshot
    from quantmt5.util import parse_utc
    return make_snapshot(parse_utc("2026-10-22T16:00:00Z"), ["XAUUSD", "EURUSD", "USDJPY"])


def test_snapshot_scan_b2_fields_on_real_cache(real_snap):
    from quantmt5.snapshot import scan
    from quantmt5.util import parse_utc
    as_of = parse_utc(real_snap["as_of_utc"])
    assert real_snap["candidates"], "fixture as_of must contain decided candidates"
    for c in real_snap["candidates"]:
        assert c["ready_ts"] <= as_of and c["revision_id"].startswith("REV_") and c["lifecycle"][0]["state"] == "DETECTED"
        assert set(c["plan_window"]) == set(c["gates"]) and "INDICATIVE_PROXY" in c["plan"]["certification"]
        assert "TIME_UNVERIFIED" in c["quality_flags"] and "SOURCE_CONFLICT:TIME_BASIS" in c["quality_flags"]
        if c["symbol"] != "XAUUSD":
            assert c["plan"]["state"] in ("EXECUTION_UNKNOWN_NO_QUOTE_MODEL", "NOT_YET_READY")   # FX: no quote model, raw kept
    rows = scan(real_snap)["rows"]
    assert all("plan_window" in r and r["revision_id"] for r in rows)
    for s in ("XAUUSD", "EURUSD", "USDJPY"):
        assert "pending_sync_candidates" in real_snap["symbols"][s] and real_snap["symbols"][s]["exposure"].startswith("HISTORICAL_EXPOSED")


def test_catalog_view_uses_pins_and_matches_direct_detection(real_snap):
    from quantmt5.context import snapshot_pins
    from quantmt5.detectors import load_symbol
    from quantmt5.snapshot import catalog_view
    from quantmt5.util import parse_utc
    as_of = parse_utc(real_snap["as_of_utc"])
    for s in ("XAUUSD", "EURUSD", "USDJPY"):
        v = catalog_view(real_snap["snapshot_id"], s, limit=5)
        sd = load_symbol(s, cut_available_at=as_of, pins=snapshot_pins(real_snap, s))
        direct = [c for c in detect_all(sd)["candidates"] if c["ready_ts"] <= as_of]
        assert v["candidates_total"] == len(direct) and len(v["rows"]) == 5
        assert v["data_versions_consumed"]["M5"] == real_snap["data_versions"][s]["M5"]["content_hash"]
        assert set(v["gate_counts"]) == {"M0", "M1", "M2", "P0", "P1", "P2"}
        assert v["gate_counts"]["M0"].get("PASS", 0) == v["by_setup_side"].get("A_LONG", 0) + v["by_setup_side"].get("A_SHORT", 0)
        assert v["gate_counts"]["P0"].get("PASS", 0) == v["by_setup_side"].get("B_LONG", 0) + v["by_setup_side"].get("B_SHORT", 0)


def test_B_running_D1_of_mother_day_is_never_used():
    # Tuesday's own D1 (running at mother time) has a much lower low; P1 must use Monday's PDL 99.5
    pat = LONG_AT_PDL
    sd = B(pat + [(95.0, 95.5, 94.0, 95.0)] * 5)
    c = _b(sd, 300)[0]
    assert c["gates"]["P1"]["prev_day_id"] == "2025-01-06" and c["gates"]["P1"]["PDL"] == 99.5
