"""B1 acceptance: bar status/provisional, coverage vs schedule, causal features (prefix/mutation), market context on
real cache for the three pilots, collector chunk store with fault injection (None/invalid batch, crash between chunk
and checkpoint, corrupt chunk, restart/cursor, same-ms multiplicity, source revision), API-UTC live load."""
import copy
import json
import os

import numpy as np
import pytest

from quantmt5 import util
from quantmt5.data import aggregate, provisional_bar
from synth import T0, bars

FX_SESSION = {"kind": "ROLLOVER_ONLY", "tz": "America/New_York", "rollover": "17:00", "weekly_close": "Fri 17:00"}
XAU_SESSION = {"kind": "DAILY_BREAK", "tz": "America/New_York", "daily_close": "17:00", "daily_reopen": "18:00", "weekly_close": "Fri 17:00"}


# ------------------------------------------------------------------ bar status / provisional
def test_derived_bar_status_complete_fewer_provisional():
    rows = [(100, 101, 99, 100)] * 12 + [(100, 101, 99, 100)] * 5   # hour 1 complete (12), hour 2 only 5 members
    m5 = bars(300, T0, rows)
    m5 = m5.slice(0, 12 + 5)
    # remove one member inside hour 1 → FINAL_FEWER_MEMBERS
    keep = np.r_[np.arange(0, 6), np.arange(7, 17)]
    holed = bars(300, T0, rows)
    for f in ("open_raw", "open_at", "close_at", "available_at", "o", "h", "l", "c", "tick_volume", "real_volume", "spread"):
        setattr(holed, f, getattr(holed, f)[keep])
    h_full, h_hole = aggregate(m5, "H1"), aggregate(holed, "H1")
    assert h_full.expected_members == 12 and list(h_full.member_count) == [12, 5]
    assert h_full.status(0, as_of=T0 + 7200) == "COMPLETE"
    assert h_hole.status(0, as_of=T0 + 7200) == "FINAL_FEWER_MEMBERS"
    assert h_full.status(1, as_of=T0 + 3600 + 1500) == "PROVISIONAL"            # second hour still running
    # snapshot-style cut never contains the running hour as a closed bar
    assert len(aggregate(m5, "H1").upto_available(T0 + 3600 + 1500)) == 1


def test_provisional_bar_elapsed_and_not_comparable():
    rows = [(100, 101, 99, 100, 10)] * 12 + [(100, 103, 98, 102, 7)] * 5
    m5 = bars(300, T0, rows)
    as_of = T0 + 3600 + 5 * 300 + 30                       # 5 M5 closed in hour 2, 30 s into the 6th
    pb = provisional_bar(m5, "H1", as_of)
    assert pb["status"] == "PROVISIONAL" and pb["members"] == 5 and pb["elapsed_s"] == 5 * 300 + 30
    assert pb["tick_volume_so_far"] == 35 and pb["h"] == 103 and pb["l"] == 98 and pb["c"] == 102
    assert "NOT comparable" in pb["comparability"]
    # 0.5 s into hour 2 no hour-2 M5 has closed yet: the latest known bucket (hour 1) is closed → no running bar
    assert provisional_bar(m5, "H1", T0 + 3600 + 0.5) is None
    assert provisional_bar(m5.slice(0, 12), "H1", T0 + 3601) is None          # latest bucket closed → no running bar
    # future M5 bars (not yet available at as_of) never leak into the provisional bar
    late = provisional_bar(m5, "H1", T0 + 3600 + 300 + 1)
    assert late["members"] == 1 and late["tick_volume_so_far"] == 7


# ------------------------------------------------------------------ coverage
def test_coverage_classifies_closed_vs_unexplained():
    from quantmt5.coverage import bar_coverage
    start = T0 - 2 * 86400                                   # Saturday 2025-01-04 00:00 UTC
    n = (5 * 86400 + 2 * 86400) // 300
    ts = start + 300 * np.arange(n)
    from quantmt5.coverage import scheduled_open
    open_ = scheduled_open(ts, FX_SESSION)
    rows = [(1.0, 1.1, 0.9, 1.0)] * n
    b = bars(300, start, rows)
    keep = open_.copy()
    weekday_hole = np.flatnonzero(open_)[100:110]            # 10 bars missing while scheduled open
    keep[weekday_hole] = False
    for f in ("open_raw", "open_at", "close_at", "available_at", "o", "h", "l", "c", "tick_volume", "real_volume", "spread"):
        setattr(b, f, getattr(b, f)[keep])
    c = bar_coverage(b, start, start + n * 300, FX_SESSION)
    assert c["classes"]["MISSING_UNEXPLAINED"] == 10 and c["classes"]["PRESENT_OUTSIDE_SCHEDULE"] == 0
    assert c["classes"]["SCHEDULED_CLOSED"] == int((~open_).sum())
    assert c["longest_unexplained_runs"][0]["bars"] == 10
    assert c["coverage_of_scheduled_open"] == pytest.approx(1 - 10 / int(open_.sum()))
    assert "clock profile" in c["conditional_on"]


def test_real_cache_coverage_consistent_with_schedule():
    from quantmt5.config import profile
    from quantmt5.coverage import bar_coverage
    from quantmt5.data import load_bars
    for s in ("XAUUSD", "EURUSD", "USDJPY"):
        b = load_bars(s, "M5")
        c = bar_coverage(b, b.open_at[0], b.close_at[-1], profile(s)["session"])
        assert c["classes"]["PRESENT_OUTSIDE_SCHEDULE"] <= 5      # schedule + clock hypothesis explain the bars
        assert c["coverage_of_scheduled_open"] > 0.97


# ------------------------------------------------------------------ causal features on real data
def test_features_prefix_and_future_mutation_invariant():
    from quantmt5.data import load_bars
    from quantmt5.features import SeriesCache
    b = load_bars("EURUSD", "M5").slice(0, 30000)
    cut = 20000
    full, pre = SeriesCache(b), SeriesCache(b.slice(0, cut))
    mut = copy.deepcopy(b)
    mut.c[cut:] *= 1.05
    mut.h[cut:] *= 1.05
    mut.tick_volume[cut:] = 999999
    mc = SeriesCache(mut)
    for key in ("atr14", "ema50", "rvol20", "rsi14"):
        assert np.allclose(full.get(key)[:cut], pre.get(key), equal_nan=True), key
        assert np.allclose(mc.get(key)[:cut], full.get(key)[:cut], equal_nan=True), key
    rs_full, n_full = full.get("rvol_slot")
    rs_mut, _ = mc.get("rvol_slot")
    assert np.allclose(rs_full[:cut], rs_mut[:cut], equal_nan=True)
    adx_f, adx_m = full.get("adx14")[0], mc.get("adx14")[0]
    assert np.allclose(adx_f[:cut], adx_m[:cut], equal_nan=True)


def test_rvol20_hand_computed_with_sample_count():
    from quantmt5.features import rvol_prev_median
    v = np.array([5, 7, 9, 11, 13, 15, 17, 19, 21, 23, 25, 27, 29, 31, 33, 35, 37, 39, 41, 43, 60], float)
    r = rvol_prev_median(v, 20)
    assert r[20] == pytest.approx(60 / 24.0)            # median of 5..43 step 2 = (23+25)/2
    assert np.isnan(r[:20]).all()


@pytest.fixture(scope="module")
def data_snap():
    from quantmt5.snapshot import make_snapshot
    return make_snapshot(util.parse_utc("2026-10-22T14:37:30Z"), ["XAUUSD", "EURUSD", "USDJPY"], include_scan=False)


def test_data_snapshot_three_pilots(data_snap):
    assert data_snap["contents"] == "DATA_ONLY" and not data_snap["candidates"]
    for s in ("XAUUSD", "EURUSD", "USDJPY"):
        v = data_snap["symbols"][s]
        assert v["status"] == "OK" and v["market_state"] == "FRESH"
        assert {"TIME_UNVERIFIED", "SOURCE_CONFLICT:TIME_BASIS", "ASK_MISSING", "HISTORICAL_AS_OF"} <= set(v["quality_flags"])
        d = v["data"]
        assert d["H1"]["last_closed_close_at"] <= data_snap["as_of_utc"]
        assert d["provisional"]["H1"]["status"] == "PROVISIONAL" and d["provisional"]["H1"]["elapsed_s"] == 37 * 60 + 30
        assert v["time_lineage"]["clock_profile_status"] == "ASSUMED"
    assert data_snap["symbols"]["EURUSD"]["data"]["H1"]["last_closed_status"] in ("COMPLETE", "FINAL_FEWER_MEMBERS")
    assert data_snap["symbols"]["XAUUSD"]["data"]["provisional"]["M5"]["status"] == "PROVISIONAL"
    assert data_snap["symbols"]["EURUSD"]["data"]["provisional"]["M5"]["status"] == "UNKNOWN"   # no M1 → not invented


def test_market_context_three_pilots_causal_and_labelled(data_snap):
    from quantmt5.context import build_market_context
    as_of = util.parse_utc(data_snap["as_of_utc"])
    for s in ("XAUUSD", "EURUSD", "USDJPY"):
        ctx = build_market_context(data_snap["snapshot_id"], s, ["ema", "adx", "rsi", "er", "atr_pct"])
        assert ctx["causality_check"]["ok"]
        by = {(f["name"], f.get("tf")): f for f in ctx["features"]}
        for f in ctx["features"]:
            if "available_at_ts" in f:
                assert f["available_at_ts"] <= as_of
                assert f["formula"] and f["warmup"] and f["unit"] and f["window"]
        assert by[("rvol20_tick", "M5")]["sample_count"] == 20 and by[("rvol20_tick", "M5")]["volume_basis"] == "tick"
        assert by[("real_volume", "M5")]["quality"] == "UNKNOWN"
        assert by[("spread_over_R", None)]["quality"] == "UNKNOWN"
        assert by[("news_calendar", None)]["quality"] == "UNKNOWN"
        assert "SOURCE_CONFLICT:TIME_BASIS" in by[("as_of_time_ny", None)]["time_basis"]
        assert ctx["provisional_bars"]["H1"]["rvol"]["reason"] == "PROVISIONAL_BAR_NOT_COMPARABLE"
        assert set(ctx["hashes"]) == {"dataset_manifest_hash", "engine_hash", "config_hash"}


def test_market_state_fresh_stale_closed():
    from quantmt5.detectors import SymbolData
    from quantmt5.snapshot import _market_state
    from synth import PROF
    m5 = bars(300, T0 + 86400 * 2, [(1, 1.1, 0.9, 1)] * 50)           # Wednesday
    sd = SymbolData("T", m5, aggregate(m5, "H1"), aggregate(m5, "D1"), None, 0.01, dict(PROF, session=FX_SESSION), "s")
    last = float(m5.close_at[-1])
    assert _market_state(sd, last + 60)[0] == "FRESH"
    assert _market_state(sd, last + 1800)[0] == "STALE"
    sat = T0 + 5 * 86400 + 12 * 3600
    m5b = bars(300, sat - 86400 - 7 * 3600, [(1, 1.1, 0.9, 1)] * 10)     # Friday afternoon bars
    sdb = SymbolData("T", m5b, aggregate(m5b, "H1"), aggregate(m5b, "D1"), None, 0.01, dict(PROF, session=FX_SESSION), "s")
    assert _market_state(sdb, sat)[0] == "MARKET_CLOSED_OR_BREAK"


# ------------------------------------------------------------------ collector with fake MT5 + fault injection
TICK_DT = np.dtype([("time_msc", "i8"), ("bid", "f8"), ("ask", "f8"), ("flags", "u4")])
RATE_DT = np.dtype([("time", "i8"), ("open", "f8"), ("high", "f8"), ("low", "f8"), ("close", "f8"), ("tick_volume", "u8"), ("spread", "i4"), ("real_volume", "u8")])


def make_tape(start, hours):
    rng = np.random.default_rng(7)
    t = np.sort(start * 1000 + rng.integers(0, hours * 3600 * 1000, size=hours * 400))
    # same-ms multiplicity, incl. groups straddling window ends (last ms of each hour) and starts
    extra = []
    for h in range(1, hours):
        edge = (start + 3600 * h) * 1000
        extra += [edge - 1] * 3 + [edge] * 2
    t = np.sort(np.r_[t, np.array(extra, np.int64)], kind="stable")
    a = np.zeros(len(t), TICK_DT)
    a["time_msc"], a["bid"] = t, 1.1 + np.arange(len(t)) * 1e-6
    a["ask"] = a["bid"] + 2e-5
    a["ask"][5] = 0.0                                    # one Ask-missing tick
    return a


class FakeMT5:
    TIMEFRAME_M1, TIMEFRAME_M5, TIMEFRAME_H1, TIMEFRAME_D1, COPY_TICKS_ALL = 1, 5, 16385, 16408, -1

    def __init__(self, path, tape, rates, fail_ticks_calls=(), fail_rates_calls=(), unsorted_call=None):
        self.path, self.tape, self.rates = path, tape, rates
        self.fail_ticks, self.fail_rates, self.unsorted = set(fail_ticks_calls), set(fail_rates_calls), unsorted_call
        self.n_ticks = self.n_rates = 0
        self.spans = []

    def initialize(self, path=None): return True
    def shutdown(self): pass
    def last_error(self): return (-1, "fake failure")

    def terminal_info(self):
        import collections
        return collections.namedtuple("TI", "path data_path build company connected")(self.path, "D:/data", 5000, "Fake", True)

    def account_info(self):
        import collections
        return collections.namedtuple("AI", "login server trade_mode currency")(1, "Fake-Server", 0, "USD")

    def symbol_info(self, s):
        import collections
        profile = dict(name=s, path="Forex\\EURUSD", point=1e-5, digits=5, trade_tick_size=1e-5,
                       trade_tick_value=1.0, trade_contract_size=100000.0, currency_base="EUR",
                       currency_profit="USD", currency_margin="EUR", volume_min=0.01,
                       volume_max=100.0, volume_step=0.01, trade_stops_level=0,
                       trade_freeze_level=0, trade_calc_mode=0, trade_mode=4, chart_mode=0)
        return collections.namedtuple("SI", profile)(*profile.values())

    def symbol_info_tick(self, s):
        return None

    def copy_ticks_range(self, s, frm, to, flags):
        self.n_ticks += 1
        self.spans.append(to - frm)
        if self.n_ticks in self.fail_ticks:
            return None
        t = self.tape["time_msc"]
        out = self.tape[(t >= int(frm) * 1000) & (t <= int(to) * 1000 + 999)].copy()
        if self.unsorted == self.n_ticks and len(out) > 2:
            out = out[::-1]
        return out

    def copy_rates_range(self, s, tf, frm, to):
        self.n_rates += 1
        if self.n_rates in self.fail_rates:
            return None
        r = self.rates
        return r[(r["time"] >= frm) & (r["time"] <= to)].copy()


def _rates(start, n):
    a = np.zeros(n, RATE_DT)
    a["time"] = start + 300 * np.arange(n)
    a["open"] = a["close"] = 1.1
    a["high"], a["low"] = 1.2, 1.0
    return a


START = T0                        # Monday 00:00 UTC
HOURS = 6


def _run(tmp, fake, **kw):
    from quantmt5.collector import collect
    exe = os.path.normcase(os.path.abspath("C:/T/terminal64.exe"))
    fake.path = os.path.dirname(exe)
    return collect("C:/T/terminal64.exe", ["EURUSD"], START, START + HOURS * 3600, out_root=tmp, mt5_module=fake,
                   process_lister=lambda: [exe], timeframes=("M5",), tick_window_s=3600, sessions={"EURUSD": FX_SESSION}, **kw)


def _ticks_dir(r):
    return util.Path(r["root"]) / "EURUSD" / "ticks"


def test_collect_full_run_keeps_multiplicity_and_bounded_windows(tmp_path):
    from quantmt5.collector import read_tick_chunks, verify_store
    tape = make_tape(START, HOURS)
    fake = FakeMT5("", tape, _rates(START, HOURS * 12))
    r = _run(tmp_path, fake)
    assert r["status"] == "OK", r["manifest"]["symbols"]["EURUSD"]["ticks"]
    got = read_tick_chunks(_ticks_dir(r))
    assert np.array_equal(got, tape)                          # every tick, order and same-ms multiplicity preserved
    assert max(fake.spans) <= 3600                             # bounded request windows (RAM)
    t = r["manifest"]["symbols"]["EURUSD"]["ticks"]
    assert t["coverage_complete"] and t["pending_rows_not_committed"] == 0
    ck = json.loads((_ticks_dir(r) / "checkpoint.json").read_text(encoding="utf-8"))
    assert any(w.get("flags") == ["ASK_MISSING"] for w in ck["windows"].values())
    assert verify_store(_ticks_dir(r))["status"] == "OK"


def test_collect_failure_is_partial_then_restart_resumes_exactly(tmp_path):
    from quantmt5.collector import read_tick_chunks, verify_store
    tape = make_tape(START, HOURS)
    fake = FakeMT5("", tape, _rates(START, HOURS * 12), fail_ticks_calls={3})
    r1 = _run(tmp_path, fake)
    t1 = r1["manifest"]["symbols"]["EURUSD"]["ticks"]
    assert r1["status"] == "PARTIAL" and t1["status"] == "PARTIAL" and not t1["coverage_complete"]
    assert t1["window_status_counts"].get("ERROR_NONE_RETURNED") == 1 and t1["window_status_counts"].get("NOT_ATTEMPTED", 0) >= 1
    assert verify_store(_ticks_dir(r1))["status"] == "INCOMPLETE_OR_CORRUPT"
    partial = read_tick_chunks(_ticks_dir(r1))
    assert len(partial) < len(tape) and np.array_equal(partial, tape[:len(partial)])
    r2 = _run(tmp_path, FakeMT5("", tape, _rates(START, HOURS * 12)))      # restart, healthy source
    assert r2["status"] == "OK"
    assert np.array_equal(read_tick_chunks(_ticks_dir(r2)), tape)          # no loss, no duplication across restart


def test_crash_between_chunk_and_checkpoint_is_safe(tmp_path):
    from quantmt5 import collector
    from quantmt5.collector import read_tick_chunks
    tape = make_tape(START, HOURS)
    calls = {"n": 0}
    real = collector.save_checkpoint

    def flaky(d, ck):
        calls["n"] += 1
        if calls["n"] == 3:
            raise OSError("simulated power loss after chunk commit")
        real(d, ck)

    exe = os.path.normcase(os.path.abspath("C:/T/terminal64.exe"))
    fake = FakeMT5(os.path.dirname(exe), tape, _rates(START, HOURS * 12))
    from quantmt5.util import Path as _P  # noqa
    d = tmp_path / "ticks"
    with pytest.raises(OSError):
        collector.collect_ticks(collector.ReadOnlyMT5(fake), "EURUSD", START, START + HOURS * 3600, d, {}, FX_SESSION, 3600, save_ck=flaky)
    res = collector.collect_ticks(collector.ReadOnlyMT5(FakeMT5("", tape, None)), "EURUSD", START, START + HOURS * 3600, d, {}, FX_SESSION, 3600)
    assert res["status"] == "OK"
    assert np.array_equal(read_tick_chunks(d), tape)
    ck = json.loads((d / "checkpoint.json").read_text(encoding="utf-8"))
    assert any(c["commit"] == "REUSED_IDENTICAL" for c in ck["chunks"])   # the orphaned chunk was recognised, not duplicated
    assert len({c["file"] for c in ck["chunks"]}) == len(ck["chunks"])


def test_corrupt_chunk_detected(tmp_path):
    from quantmt5.collector import read_tick_chunks, verify_store
    from quantmt5.data import ChunkCorrupt
    tape = make_tape(START, 3)
    r = _run(tmp_path, FakeMT5("", tape, _rates(START, 36)))
    d = _ticks_dir(r)
    ck = json.loads((d / "checkpoint.json").read_text(encoding="utf-8"))
    f = d / ck["chunks"][0]["file"]
    data = bytearray(f.read_bytes())
    data[-10] ^= 0xFF
    f.write_bytes(bytes(data))
    with pytest.raises(ChunkCorrupt):
        read_tick_chunks(d)
    assert ck["chunks"][0]["file"] in verify_store(d)["corrupt_or_missing_chunks"]


def test_invalid_and_empty_batches_are_not_ok(tmp_path):
    tape = make_tape(START, HOURS)
    r = _run(tmp_path / "a", FakeMT5("", tape, _rates(START, HOURS * 12), unsorted_call=2))
    t = r["manifest"]["symbols"]["EURUSD"]["ticks"]
    assert t["status"] == "PARTIAL" and t["window_status_counts"].get("ERROR_INVALID_BATCH") == 1
    rb = _run(tmp_path / "b", FakeMT5("", tape, _rates(START, HOURS * 12), fail_rates_calls={1}))
    assert rb["manifest"]["symbols"]["EURUSD"]["bars"]["M5"]["status"] == "PARTIAL" and rb["status"] == "PARTIAL"
    # weekday window with no ticks = unexplained; weekend window = market closed
    from quantmt5 import collector
    empty = np.zeros(0, TICK_DT)
    wd = collector.collect_ticks(collector.ReadOnlyMT5(FakeMT5("", empty, None)), "EURUSD", START + 3600, START + 7200, tmp_path / "c", {}, FX_SESSION, 3600)
    assert wd["window_status_counts"] == {"EMPTY_UNEXPLAINED": 1} and wd["status"] == "PARTIAL"
    sat = START - 2 * 86400 + 6 * 3600
    we = collector.collect_ticks(collector.ReadOnlyMT5(FakeMT5("", empty, None)), "EURUSD", sat, sat + 7200, tmp_path / "d", {}, FX_SESSION, 3600)
    assert we["window_status_counts"] == {"EMPTY_MARKET_CLOSED": 2} and we["status"] == "OK"


def test_source_revision_never_overwrites(tmp_path):
    from quantmt5.collector import commit_chunk
    a = np.zeros(3, TICK_DT)
    i1 = commit_chunk(tmp_path, "w", "ticks", a)
    i2 = commit_chunk(tmp_path, "w", "ticks", a)
    b = a.copy()
    b["bid"] = 9
    i3 = commit_chunk(tmp_path, "w", "ticks", b)
    assert i1["commit"] == "NEW" and i2["commit"] == "REUSED_IDENTICAL"
    assert i3["commit"] == "NEW_REVISION" and i3["file"] == "w.rev2.npz" and i3["conflict"] == "SOURCE_CONFLICT:CHUNK_REVISION"
    assert util.sha256_file(tmp_path / "w.npz") == i1["sha256"]


def test_live_bars_load_under_api_utc_contract_without_offset(tmp_path):
    from quantmt5.data import load_bars
    tape = make_tape(START, HOURS)
    rates = _rates(START, HOURS * 12)                  # every open slot of the requested span
    r = _run(tmp_path, FakeMT5("", tape, rates))
    frag = r["registry_fragment"]["EURUSD"]
    reg = json.loads((util.CONFIG_DIR / "datasets.json").read_text(encoding="utf-8"))
    reg["symbols"] = {"EURUSD": frag}
    b = load_bars("EURUSD", "M5", reg)
    assert (b.open_at == rates["time"]).all() and (b.open_raw == rates["time"]).all()
    p = b.provenance
    assert p["time_contract"] == "API_UTC_CONTRACT" and p["clock_profile"] == "RAW_IS_UTC" and p["coverage_complete"] is True
    assert "SOURCE_CONFLICT:TIME_BASIS" not in p["time_quality_flags"]
    h1 = load_bars("EURUSD", "H1", dict(reg, symbols={"EURUSD": dict(frag, timeframes={"M5": frag["timeframes"]["M5"], "H1": {"derive_from": "M5"}})}))
    assert h1.provenance["kind"] == "DERIVED_FROM_M5" and list(h1.member_count) == [12] * HOURS
