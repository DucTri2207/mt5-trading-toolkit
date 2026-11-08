"""Acceptance: clock/DST mapping, metadata NaN/0, tick grid & volume rounding, features causal, RVOL basis,
atomic/immutable writes, portfolio rules, tick same-ms merge, read-only collector guard, stale/closed status."""
import datetime as dt
import json
import math

import numpy as np
import pytest

from quantmt5 import util
from quantmt5.config import MetadataError, tick_size
from quantmt5.timemap import server_to_utc
from synth import T0, bars


def _raw(y, mo, d, h):
    return int(dt.datetime(y, mo, d, h, tzinfo=dt.timezone.utc).timestamp())


def test_server_clock_profiles_dst():
    # EET_EU: winter UTC+2, summer UTC+3, US-only-DST week still UTC+2
    assert server_to_utc(_raw(2025, 1, 15, 12), "EET_EU")[0] == _raw(2025, 1, 15, 10)
    assert server_to_utc(_raw(2025, 7, 1, 12), "EET_EU")[0] == _raw(2025, 7, 1, 9)
    assert server_to_utc(_raw(2025, 3, 12, 12), "EET_EU")[0] == _raw(2025, 3, 12, 10)
    assert server_to_utc(_raw(2025, 3, 12, 12), "NY_PLUS_7")[0] == _raw(2025, 3, 12, 9)
    assert server_to_utc(_raw(2025, 3, 12, 12), "RAW_IS_UTC")[0] == _raw(2025, 3, 12, 12)


def test_clock_evidence_is_hypothesis_evidence_only():
    from quantmt5.audit import clock_evidence
    from quantmt5.data import load_bars
    for s in ("XAUUSD", "EURUSD"):
        ev = clock_evidence(load_bars(s, "M5"))
        assert ev["verdict"] == "EET_EU_MOST_CONSISTENT", ev["profile_scores"]
        assert ev["status"] == "HYPOTHESIS_EVIDENCE_ONLY"


def test_metadata_never_defaulted():
    for bad in (None, 0, float("nan"), -0.01, "x", float("inf"), float("-inf"), True):
        with pytest.raises(MetadataError):
            tick_size("X", {"trade_tick_size": bad})
    with pytest.raises(MetadataError, match="NON_FINITE"):
        tick_size("X", {"trade_tick_size": float("inf")})
    with pytest.raises(MetadataError, match="NON_POSITIVE"):
        tick_size("X", {"trade_tick_size": 0})
    assert tick_size("X", {"trade_tick_size": 0.01}) == 0.01
    assert tick_size("X", {"trade_tick_size": "0.001"}) == 0.001
    with pytest.raises(MetadataError):
        from quantmt5.config import profile
        profile("NOPE")
    with pytest.raises(ValueError):
        util.ceil_to_tick(1.0, 0)


def test_tick_grid_rounding_direction():
    assert util.ceil_to_tick(1.234561, 1e-5) == pytest.approx(1.23457)
    assert util.floor_to_tick(1.234569, 1e-5) == pytest.approx(1.23456)
    assert util.ceil_to_tick(2650.0, 0.01) == 2650.0          # exact multiples stay put (Decimal, no float drift)
    assert util.floor_to_tick(0.3, 0.1) == pytest.approx(0.3)


def test_volume_rounds_down_and_min_lot_blocks():
    assert util.round_volume_down(0.237, 0.01, 0.01, 100) == (0.23, "OK")
    assert util.round_volume_down(0.009, 0.01, 0.01, 100) == (None, "BELOW_MIN_VOLUME_RISK_EXCEEDED")
    assert util.round_volume_down(1.0, 0, 0.01, 100)[1] == "VOLUME_METADATA_INVALID"


def test_atr_wilder_seed_and_causal():
    from quantmt5.features import atr
    rows = [(100, 101, 99, 100)] * 14 + [(100, 104, 100, 103)]
    b = bars(300, T0, rows)
    a = atr(b, 14)
    assert math.isnan(a[12]) and a[13] == pytest.approx(2.0)
    assert a[14] == pytest.approx((13 * 2.0 + 4.0) / 14)
    # appending future bars does not change past values
    b2 = bars(300, T0, rows + [(103, 110, 90, 95)] * 5)
    assert np.allclose(atr(b2, 14)[:15], a, equal_nan=True)


def test_rvol_uses_only_past_and_zero_median_is_unknown():
    from quantmt5.features import rvol_prev_median
    v = np.array([10] * 20 + [30] + [1000] * 3, dtype=float)
    r = rvol_prev_median(v, 20)
    assert math.isnan(r[19]) and r[20] == pytest.approx(3.0)
    v2 = v.copy()
    v2[21:] = 1
    assert rvol_prev_median(v2, 20)[20] == r[20]
    z = rvol_prev_median(np.zeros(25), 20)
    assert np.isnan(z[20:]).all()


# ------------------------------------------------------------------ time contracts / lineage
RATES_DT = [("time", "i8"), ("open", "f8"), ("high", "f8"), ("low", "f8"), ("close", "f8"), ("tick_volume", "u8"), ("spread", "i4"), ("real_volume", "u8")]


def _tmp_registry(tmp_path, contract, applied=None, extra=None):
    t = np.array([_raw(2025, 7, 1, 12) + 300 * i for i in range(5)])
    a = np.zeros(5, dtype=RATES_DT)
    a["time"], a["open"], a["high"], a["low"], a["close"] = t, 1.0, 1.1, 0.9, 1.0
    p = tmp_path / f"{contract}.npz"
    np.savez(p, rates=a)
    tb = {"contract": contract, "source_time_basis_recorded": "fixture basis text", "source_time_basis_ref": "fixture#basis"}
    if applied:
        tb.update({"clock_profile_applied": applied, "clock_profile_status": "ASSUMED", "time_basis_status": "SOURCE_CONFLICT:TIME_BASIS",
                   "conflict_reason": "fixture conflict"})
    tb.update(extra or {})
    reg = json.loads((util.CONFIG_DIR / "datasets.json").read_text(encoding="utf-8"))
    reg["symbols"] = {"FIX": {"dataset_id": "ds_fix", "exposure": "FIXTURE", "time_basis": tb,
                              "timeframes": {"M5": {"path": str(p), "key": "rates", "sha256": util.sha256_file(p)}}}}
    return reg, t


def test_api_utc_contract_fixture_is_not_shifted(tmp_path):
    from quantmt5.data import load_bars
    reg, t = _tmp_registry(tmp_path, "API_UTC_CONTRACT")
    b = load_bars("FIX", "M5", reg)
    assert (b.open_at == t).all() and (b.open_raw == t).all()
    assert b.provenance["clock_profile"] == "RAW_IS_UTC" and b.provenance["time_contract"] == "API_UTC_CONTRACT"
    assert "SOURCE_CONFLICT:TIME_BASIS" not in b.provenance["time_quality_flags"] and "TIME_UNVERIFIED" in b.provenance["time_quality_flags"]


def test_api_utc_contract_refuses_silent_double_offset(tmp_path):
    from quantmt5.data import load_bars
    reg, _ = _tmp_registry(tmp_path, "API_UTC_CONTRACT")
    with pytest.raises(ValueError, match="TIME_DOUBLE_OFFSET_GUARD"):
        load_bars("FIX", "M5", reg, clock="EET_EU")
    b = load_bars("FIX", "M5", reg, clock="EET_EU", override_reason="sensitivity run")
    assert b.provenance["clock_profile_status"] == "OVERRIDE_FOR_SENSITIVITY" and b.provenance["clock_override_reason"] == "sensitivity run"
    reg2, _ = _tmp_registry(tmp_path, "API_UTC_CONTRACT", extra={"clock_profile_applied": "EET_EU"})
    with pytest.raises(ValueError, match="TIME_DOUBLE_OFFSET_GUARD"):
        load_bars("FIX", "M5", reg2)


def test_legacy_fixture_carries_basis_hypothesis_and_conflict(tmp_path):
    from quantmt5.data import aggregate, load_bars
    reg, t = _tmp_registry(tmp_path, "LEGACY_CACHE_HYPOTHESIS", applied="EET_EU")
    b = load_bars("FIX", "M5", reg)
    assert (b.open_raw == t).all() and set(np.unique(b.open_raw - b.open_at)) == {10800}
    p = b.provenance
    assert p["source_time_basis_recorded"] == "fixture basis text" and p["clock_profile_status"] == "ASSUMED"
    assert "SOURCE_CONFLICT:TIME_BASIS" in p["time_quality_flags"] and "CONFLICT" in p["time_basis_status"]
    assert aggregate(b, "H1").provenance["source_time_basis_recorded"] == "fixture basis text"  # lineage survives derivation


def test_real_xau_lineage_preserves_recorded_utc_basis():
    from quantmt5.data import load_bars
    original = json.loads((util.WORKSPACE_DIR / "reports/can_ho_tro_scalp/20261025_v1/data_manifest.json").read_text(encoding="utf-8"))
    for tf in ("M1", "M5", "H1", "D1"):
        p = load_bars("XAUUSD", tf).provenance
        assert p["source_time_basis_recorded"] == original["timestamp_basis"]
        assert p["time_basis_status"] == "SOURCE_CONFLICT:TIME_BASIS" and p["clock_profile_status"] == "ASSUMED"
        assert p["source_time_basis_ref_sha256"] == util.sha256_file(util.WORKSPACE_DIR / "reports/can_ho_tro_scalp/20261025_v1/data_manifest.json")
    raw_utc = load_bars("XAUUSD", "M5", clock="RAW_IS_UTC", override_reason="sensitivity")
    assert (raw_utc.open_raw == raw_utc.open_at).all()


def test_audit_time_basis_section_reports_conflict():
    from quantmt5.audit import run_audit
    r = run_audit(["XAUUSD"])["symbols"]["XAUUSD"]
    tb = r["time_basis"]
    assert tb["relation"] == "SOURCE_CONFLICT:TIME_BASIS" and tb["verified"] is False
    assert tb["recorded_basis_mentions_utc"] is True and tb["applied_offsets_raw_minus_utc_s"] == [7200, 10800]
    assert "SOURCE_CONFLICT:TIME_BASIS" in r["flags"] and "TIME_UNVERIFIED" in r["flags"]


def test_real_volume_unavailable_not_zero():
    from quantmt5.audit import volume_basis
    from quantmt5.data import load_bars
    vb = volume_basis(load_bars("XAUUSD", "M5"))
    assert vb["real_volume_status"] == "UNAVAILABLE_ALL_ZERO_IN_SOURCE" and vb["volume_basis_selected"] == "tick"


def test_source_hash_verified():
    from quantmt5.data import _verified_npz, resolve
    with pytest.raises(ValueError, match="SOURCE_HASH_MISMATCH"):
        _verified_npz(str(resolve("reports/can_ho_tro_scalp/20261101_intermarket_v9/fx_rates.npz")), "0" * 64)


def test_immutable_and_append_only(tmp_path):
    p = tmp_path / "x.json"
    util.write_immutable_json(p, {"a": 1})
    assert util.write_immutable_json(p, {"a": 1})[1] is False
    with pytest.raises(FileExistsError):
        util.write_immutable_json(p, {"a": 2})
    j = tmp_path / "j.jsonl"
    util.append_jsonl(j, {"n": 1})
    util.append_jsonl(j, {"n": 2})
    assert [r["n"] for r in util.read_jsonl(j)] == [1, 2]
    assert not list(tmp_path.glob("*.tmp"))


def test_stable_ids_independent_of_order():
    assert util.stable_id("C", "a", 1) == util.stable_id("C", "a", 1) != util.stable_id("C", 1, "a")


# ------------------------------------------------------------------ ticks: same-millisecond multiplicity
TDT = np.dtype([("time_msc", "i8"), ("bid", "f8"), ("ask", "f8")])


def _t(rows):
    return np.array(rows, dtype=TDT)


def test_tick_merge_keeps_same_ms_multiplicity():
    from quantmt5.collector import merge_tick_batch
    stored = _t([(1000, 1.0, 1.1), (2000, 1.0, 1.1), (2000, 1.0, 1.1)])  # two identical ticks in the same ms
    batch = _t([(2000, 1.0, 1.1), (2000, 1.0, 1.1), (2000, 1.01, 1.11), (3000, 1.02, 1.12)])  # group grew by one
    merged, pending, conf = merge_tick_batch(stored, 2000, batch)
    assert not conf
    assert list(merged["time_msc"]) == [1000, 2000, 2000, 2000, 3000]
    assert pending == 3000
    # restart re-reading the same tail is idempotent (no duplication)
    again, p2, c2 = merge_tick_batch(merged, 3000, _t([(3000, 1.02, 1.12)]))
    assert len(again) == 5 and not c2


def test_tick_merge_conflict_keeps_stored():
    from quantmt5.collector import merge_tick_batch
    stored = _t([(2000, 1.0, 1.1), (2000, 1.0, 1.1)])
    merged, _, conf = merge_tick_batch(stored, 2000, _t([(2000, 1.5, 1.6), (4000, 1.0, 1.1)]))
    assert conf and conf[0]["reason"] == "SOURCE_CONFLICT_BOUNDARY_GROUP"
    assert list(merged["time_msc"]) == [2000, 2000, 4000]


# ------------------------------------------------------------------ collector safety
class FakeMT5:
    TIMEFRAME_M1, TIMEFRAME_M5, TIMEFRAME_H1, TIMEFRAME_D1, COPY_TICKS_ALL = 1, 5, 16385, 16408, -1

    def __init__(self, path):
        self.calls, self.path = [], path

    def __getattr__(self, k):
        raise AttributeError(k)

    def initialize(self, path=None):
        self.calls.append("initialize")
        return True

    def shutdown(self):
        self.calls.append("shutdown")

    def last_error(self):
        return (0, "ok")

    def terminal_info(self):
        import collections
        return collections.namedtuple("TI", "path data_path build company connected")(self.path, "D:/data", 5000, "MetaQuotes", True)

    def account_info(self):
        import collections
        return collections.namedtuple("AI", "login server trade_mode currency")(123, "Demo-Server", 0, "USD")

    def symbol_info(self, s):
        import collections
        profile = dict(name=s, path="Metals\\XAUUSD", digits=2, point=0.01, trade_tick_size=0.01,
                       trade_tick_value=1.0, trade_contract_size=100.0, currency_base="XAU",
                       currency_profit="USD", currency_margin="USD", volume_min=0.01,
                       volume_max=100.0, volume_step=0.01, trade_stops_level=0,
                       trade_freeze_level=0, trade_calc_mode=2, trade_mode=4, chart_mode=0)
        return collections.namedtuple("SI", profile)(*profile.values())

    def symbol_info_tick(self, s):
        import collections
        import time
        return collections.namedtuple("TK", "time time_msc bid ask")(int(time.time()), int(time.time() * 1000), 1.0, 1.1)

    def copy_rates_range(self, s, tf, a, b):
        self.calls.append("copy_rates_range")
        step = {self.TIMEFRAME_M1: 60, self.TIMEFRAME_M5: 300, self.TIMEFRAME_H1: 3600, self.TIMEFRAME_D1: 86400}[tf]
        t = np.arange(-(-a // step) * step, b + 1, step)   # every slot of the requested window (B1 checks coverage)
        r = np.zeros(len(t), dtype=[("time", "i8"), ("open", "f8"), ("high", "f8"), ("low", "f8"), ("close", "f8"),
                                    ("tick_volume", "u8"), ("spread", "i4"), ("real_volume", "u8")])
        r["time"] = t
        r["open"] = r["close"] = r["high"] = r["low"] = 1.0
        return r

    def copy_ticks_range(self, s, a, b, flags):
        self.calls.append("copy_ticks_range")
        tape = _t([(1000, 1.0, 1.1), (1000, 1.0, 1.1), (3_600_500, 1.0, 1.1), (5_000_000, 1.0, 1.1)])   # fixed tape, same-ms pair
        return tape[(tape["time_msc"] >= int(a) * 1000) & (tape["time_msc"] <= int(b) * 1000 + 999)]

    def order_send(self, *a):  # must be unreachable through the guard
        raise AssertionError("order_send reached")


def test_read_only_guard_blocks_trading_calls():
    from quantmt5.collector import ReadOnlyMT5
    g = ReadOnlyMT5(FakeMT5("C:/T"))
    for name in ("order_send", "order_check", "positions_get", "Buy"):
        with pytest.raises(PermissionError):
            getattr(g, name)


def test_collect_refuses_when_terminal_not_running(tmp_path):
    from quantmt5.collector import collect
    fake = FakeMT5("C:/T")
    r = collect("C:/T/terminal64.exe", ["XAUUSD"], 0, 3600, out_root=tmp_path, mt5_module=fake, process_lister=lambda: [])
    assert r["status"] == "ERROR" and r["reason"] == "TERMINAL_NOT_RUNNING_AT_SELECTED_PATH"
    assert fake.calls == []  # never initialised → never launched


def test_collect_attaches_only_to_running_selected_terminal(tmp_path):
    import os
    from quantmt5.collector import collect
    exe = os.path.normcase(os.path.abspath("C:/T/terminal64.exe"))
    fake = FakeMT5(os.path.dirname(exe))
    r = collect("C:/T/terminal64.exe", ["XAUUSD"], 0, 7200, out_root=tmp_path, mt5_module=fake, process_lister=lambda: [exe], tick_window_s=3600,
                timeframes=("M1", "M5", "H1"))   # D1 without schedule/boundary is unverifiable by design (test_b1_fixes R3)
    assert r["status"] == "OK"
    m = r["manifest"]
    assert m["identity"]["account_fingerprint"] and "login" not in json.dumps(m["identity"])
    t = m["symbols"]["XAUUSD"]["ticks"]
    assert t["status"] == "OK" and t["rows_committed"] >= 2 and t["coverage_complete"]
    assert set(fake.calls) <= {"initialize", "shutdown", "copy_rates_range", "copy_ticks_range"}
    assert m["time_contract"] == "API_UTC_CONTRACT" and m["time_basis_status"] == "DOC_CONTRACT_TIME_UNVERIFIED"
    pr = m["symbols"]["XAUUSD"]["clock_probe"]
    assert pr["status"] == "PROBE_RECORDED_NOT_VERIFIED" and pr["nearest_whole_offset_s"] == 0


# ------------------------------------------------------------------ portfolio
def _fill(cid, setup, side, sym, ready, fill, exit_, r=1.0, sr=0.05):
    return {"candidate_id": cid, "setup": setup, "side": side, "symbol": sym, "status": "FILLED", "net_R": r, "fill_at": util.iso_utc(fill),
            "primary": {"exit_at": util.iso_utc(exit_), "net_R": r}, "spread_over_R": sr}


def test_portfolio_dedup_conflict_budget():
    from quantmt5.evaluate import portfolio
    P = {"max_positions_per_symbol": 1, "max_open_risk_units_total": 1}
    A1 = _fill("a1", "A", "LONG", "XAU", 100, 110, 500)
    B1 = _fill("b1", "B", "LONG", "XAU", 100, 110, 400)     # same event, same side → linked to A
    A2 = _fill("a2", "A", "LONG", "EUR", 200, 210, 300)     # overlaps A1 → budget full
    A3 = _fill("a3", "A", "LONG", "JPY", 900, 910, 950)
    B3 = _fill("b3", "B", "SHORT", "JPY", 900, 910, 950)    # opposite side same event → drop both
    A4 = _fill("a4", "A", "SHORT", "XAU", 1000, 1010, 1100)
    cands = {c["candidate_id"]: {"ready_ts": t, "signal_close_ts": t - 1} for c, t in ((A1, 100), (B1, 100), (A2, 200), (A3, 900), (B3, 900), (A4, 1000))}
    pf = portfolio({"M2": [A1, A2, A3, A4], "P1": [B1, B3]}, cands, P)
    acc = [r["candidate_id"] for r in pf["accepted"]]
    assert acc == ["a1", "a4"]
    reasons = {r["candidate_id"]: r["portfolio_reason"] for r in pf["rejected"] + pf["dropped"]}
    assert reasons == {"b1": "SAME_EVENT_LINKED_TO_A", "a2": "RISK_BUDGET_FULL", "a3": "CONFLICT_OPPOSITE_SIDES_DROP_BOTH",
                       "b3": "CONFLICT_OPPOSITE_SIDES_DROP_BOTH"}


def test_holm_and_bootstrap_deterministic():
    from quantmt5.evaluate import bootstrap_ci, holm
    x = np.r_[np.ones(50), -np.ones(50)] * 0.1
    assert bootstrap_ci(x) == bootstrap_ci(x)
    h = holm({"a": 0.01, "b": 0.04, "c": 0.03, "d": 0.5})
    assert h["a"] == pytest.approx(0.04) and h["c"] == pytest.approx(0.09) and h["b"] == pytest.approx(0.09) and h["d"] == 0.5
