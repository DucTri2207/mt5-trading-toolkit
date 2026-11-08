"""Incremental collection and scope reuse without weakening data contracts."""
import hashlib
from types import SimpleNamespace

import numpy as np
import pytest

from quantmt5 import collector, data, detectors, replay
from quantmt5.analysis_cache import analysis_scope
from quantmt5.mt5_flow import read_snapshot_mt5
from quantmt5.util import hash_obj
from synth import PROF, T0, flat_m5, symbol_data
from test_b1_fixes import Bars as RatesAPI, FX, rates


def _tick_pin(tmp_path, rows=None):
    if rows is None:
        rows = np.array([(1000, 1., 1.01), (1000, 1.1, 1.11), (400000, 1.2, 1.21)],
                        dtype=[("time_msc", "i8"), ("bid", "f8"), ("ask", "f8")])
    path = tmp_path / "ticks.npz"
    np.savez(path, ticks=rows)
    return {"chunk_dir": str(tmp_path), "chunks": [{"file": path.name, "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}],
            "window_states": {"0_600": "OK"}, "clock_profile": "RAW_IS_UTC", "content_hash": "test"}


def _count_decodes(monkeypatch):
    calls = []
    original = np.load
    def tracked(*args, **kwargs):
        calls.append(str(args[0]))
        return original(*args, **kwargs)
    monkeypatch.setattr(np, "load", tracked)
    return calls


def _registry(tmp_path):
    p = tmp_path / "bars.npz"
    np.savez(p, M5=rates(T0, 600), M1=rates(T0, 3000, step=60))
    sha = hashlib.sha256(p.read_bytes()).hexdigest()
    return {"source_id": "fixture", "time_contracts": {"API_UTC_CONTRACT": {"clock_profile": "RAW_IS_UTC"}},
            "symbols": {"TEST": {"dataset_id": "fixture", "time_basis": {"contract": "API_UTC_CONTRACT"},
                                   "timeframes": {"M5": {"path": str(p), "key": "M5", "sha256": sha},
                                                  "M1": {"path": str(p), "key": "M1", "sha256": sha},
                                                  "H1": {"derive_from": "M5"}, "D1": {"derive_from": "M5"}}}}}


def test_moving_lookback_fetches_only_new_closed_bars_preserves_old_pin(tmp_path):
    class API(RatesAPI):
        def __init__(self, values):
            super().__init__(values)
            self.requests = []
        def copy_rates_range(self, symbol, tf, start, end):
            self.requests.append((start, end))
            return super().copy_rates_range(symbol, tf, start, end)
    start = T0 + 12 * 3600
    api = API(rates(start, 40))
    first = collector.collect_bars(api, "EURUSD", "M5", start, start + 10800, tmp_path, {}, FX, window_s=3600)
    assert first["coverage_complete"] and len(api.requests) == 3
    ck = collector.load_checkpoint(tmp_path)
    chunks = [{k: c[k] for k in ("file", "sha256")} for c in ck["chunks"]]
    windows = {k: v["status"] for k, v in ck["windows"].items()}
    pin = {"chunks": chunks, "window_states": windows, "content_hash": data.collected_content_hash(chunks, windows)}
    old, _ = data.load_collected_bars(tmp_path, pin)
    api.requests.clear()
    second = collector.collect_bars(api, "EURUSD", "M5", start + 1200, start + 12000, tmp_path, {}, FX, window_s=3600)
    assert second["coverage_complete"] and len(api.requests) == 1
    assert api.requests[0] == (start + 10800 - 300 + 1, start + 12000 - 300)
    current, _ = data.load_collected_bars(tmp_path)
    assert len(current) == 40 and np.array_equal(data.load_collected_bars(tmp_path, pin)[0], old)
    assert all(hashlib.sha256((tmp_path / c["file"]).read_bytes()).hexdigest() == c["sha256"] for c in chunks)
    api.requests.clear()
    collector.collect_bars(api, "EURUSD", "M5", start + 1200, start + 12000, tmp_path, {}, FX, window_s=3600)
    assert api.requests == []


def test_legacy_forming_tail_is_not_cached_as_complete(tmp_path):
    start = T0 + 12 * 3600
    api = RatesAPI(rates(start, 13))
    collector.collect_bars(api, "EURUSD", "M5", start, start + 3600, tmp_path, {}, FX, window_s=3600)
    assert len(data.load_collected_bars(tmp_path)[0]) == 12
    collector.collect_bars(api, "EURUSD", "M5", start + 300, start + 3900, tmp_path, {}, FX, window_s=3600)
    assert len(data.load_collected_bars(tmp_path)[0]) == 13


def test_rolling_tick_window_reuses_coverage_and_rereads_pending_group(tmp_path):
    end = T0 + 3600
    a = np.zeros(6, dtype=[("time_msc", "i8"), ("bid", "f8"), ("ask", "f8"), ("flags", "i8")])
    a["time_msc"] = np.array([T0 * 1000 + 1000, end * 1000 - 1000, end * 1000 - 1000,
                              end * 1000 + 1000, end * 1000 + 60000, (end + 1206) * 1000])
    a["bid"] = 1 + np.arange(6) * .001; a["ask"] = a["bid"] + .001
    class API:
        COPY_TICKS_ALL = 0
        def __init__(self):
            self.requests = []
        def copy_ticks_range(self, symbol, start, stop, flags):
            self.requests.append((start, stop))
            assert start <= stop
            return a[(a["time_msc"] >= start * 1000) & (a["time_msc"] < (stop + 1) * 1000)]
    api = API()
    collector.collect_ticks(api, "EURUSD", T0, end, tmp_path, {}, FX, finalize_tail=False)
    assert collector.load_checkpoint(tmp_path)["pending_rows"] == 2
    api.requests.clear()
    out = collector.collect_ticks(api, "EURUSD", T0 + 1207, end + 1207, tmp_path, {}, FX, finalize_tail=False)
    assert out["coverage_complete"] and api.requests == [(end - 1, end + 1206)]
    np.testing.assert_array_equal(collector.read_tick_chunks(tmp_path), a[:-1])


@pytest.mark.parametrize("tf,step", [("H1", 3600), ("D1", 86400)])
def test_micro_tail_without_eligible_bar_is_complete_but_missing_real_slot_is_not(tmp_path, tf, step):
    class API(RatesAPI):
        TIMEFRAME_H1 = 60
        TIMEFRAME_D1 = 1440
    api = API(rates(T0, 6, step=step))
    session = dict(FX, d1_boundary={"tz": "UTC", "day_start": "00:00"})
    first_end = T0 + 4 * step + 1800
    first = collector.collect_bars(api, "EURUSD", tf, T0, first_end, tmp_path, {}, session)
    assert first["coverage_complete"]
    again = collector.collect_bars(api, "EURUSD", tf, T0 + 300, first_end + 300, tmp_path, {}, session)
    assert again["coverage_complete"]
    tail = list(collector.load_checkpoint(tmp_path)["windows"].values())[-1]
    assert tail["slot_check"] == "NO_ELIGIBLE_CLOSED_BAR_OPEN_IN_INTERVAL"
    missing = collector.collect_bars(API(rates(T0, 4, step=step)), "EURUSD", tf,
                                     T0 + 300, first_end + step, tmp_path, {}, session)
    assert not missing["coverage_complete"]


def test_tick_decode_once_within_scope_not_across_scopes(tmp_path, monkeypatch):
    pin = _tick_pin(tmp_path)
    decodes = _count_decodes(monkeypatch)
    bars = SimpleNamespace(open_at=np.array([0., 300.]), close_at=np.array([300., 600.]))
    with analysis_scope() as stats:
        first = replay.pinned_tick_array(pin)
        with analysis_scope() as nested:
            assert nested is stats
            assert replay.pinned_tick_array(pin) is first
        fl = read_snapshot_mt5({"tick_versions": {"X": pin}}, bars, "X", 600)["flow"]
        assert fl["total"].tolist() == [2., 1.]
        assert len(decodes) == 1 and stats["by_kind"]["tick_tape"]["hits"] == 2
    with analysis_scope():
        replay.pinned_tick_array(pin)
    assert len(decodes) == 2


@pytest.mark.parametrize("change", ["delete", "same_size_rewrite"])
def test_tick_cache_never_hides_changed_or_deleted_pin(tmp_path, change):
    pin = _tick_pin(tmp_path)
    p = tmp_path / "ticks.npz"
    with analysis_scope():
        replay.pinned_tick_array(pin)
        if change == "delete":
            p.unlink()
        else:
            blob = bytearray(p.read_bytes()); blob[-1] ^= 1
            p.write_bytes(blob)
        with pytest.raises(data.DataVersionMismatch, match="TICK_CHUNK_MISSING_OR_CHANGED"):
            replay.pinned_tick_array(pin)


def test_raw_tick_order_rejection_survives_cached_sorted_replay(tmp_path):
    a = np.array([(400000, 1., 1.01), (1000, 1.1, 1.11), (1000, 1.2, 1.21)],
                 dtype=[("time_msc", "i8"), ("bid", "f8"), ("ask", "f8")])
    pin = _tick_pin(tmp_path, a)
    bars = SimpleNamespace(open_at=np.array([0., 300.]), close_at=np.array([300., 600.]))
    with analysis_scope():
        assert replay.pinned_tick_array(pin)["time_msc"].tolist() == [1000, 1000, 400000]
        fl = read_snapshot_mt5({"tick_versions": {"X": pin}}, bars, "X", 600)["flow"]
    assert fl["status"] == "REJECTED" and fl["reasons"] == ["TICKS_UNSORTED"]


def test_symbol_bars_and_detectors_reused_but_cutoff_and_catalog_are_isolated(tmp_path, monkeypatch):
    reg = _registry(tmp_path)
    monkeypatch.setattr(detectors, "profile", lambda _: dict(PROF))
    decodes = _count_decodes(monkeypatch)
    pins = {tf: data.dataset_version(reg, "TEST", tf) for tf in ("M5", "M1", "H1", "D1")}
    with analysis_scope() as stats:
        sd = detectors.load_symbol("TEST", reg, T0 + 90001, pins)
        sd2 = detectors.load_symbol("TEST", reg, T0 + 90001, pins)
        assert sd2 is sd and len(decodes) == 1
        earlier = detectors.load_symbol("TEST", reg, T0 + 86400, pins)
        assert earlier is not sd and len(earlier.m5) < len(sd.m5)
        cat = detectors.detect_all(sd)
        original = hash_obj(cat)
        cat["candidates"].append({"caller_annotation": True})
        assert hash_obj(detectors.detect_all(sd)) == original
        assert stats["by_kind"]["catalog"]["hits"] == 1
        assert stats["by_kind"]["symbol"]["hits"] == 1


def test_bar_cache_rechecks_archive_hash_before_reuse(tmp_path, monkeypatch):
    reg = _registry(tmp_path)
    monkeypatch.setattr(detectors, "profile", lambda _: dict(PROF))
    with analysis_scope():
        detectors.load_symbol("TEST", reg)
        p = tmp_path / "bars.npz"
        blob = bytearray(p.read_bytes()); blob[-1] ^= 1
        p.write_bytes(blob)
        with pytest.raises(ValueError, match="SOURCE_HASH_MISMATCH"):
            detectors.load_symbol("TEST", reg)


def test_indexed_flow_matches_unscoped_and_respects_late_arrivals(tmp_path):
    a = np.zeros(600, dtype=[("time_msc", "i8"), ("available_msc", "i8"), ("bid", "f8"), ("ask", "f8")])
    a["time_msc"] = np.arange(600) * 1000
    a["available_msc"] = a["time_msc"]
    a["available_msc"][::3] = 900000
    a["bid"] = 1 + (np.arange(600) % 7) * .01
    a["ask"] = a["bid"] + .01
    pin = _tick_pin(tmp_path, a)
    bars = SimpleNamespace(open_at=np.array([0., 300.]), close_at=np.array([300., 600.]))
    snap = {"tick_versions": {"X": pin}}
    ordinary = read_snapshot_mt5(snap, bars, "X", 600)
    with analysis_scope():
        scoped = read_snapshot_mt5(snap, bars, "X", 600)
    for key in ("delta", "cvd", "total"):
        np.testing.assert_array_equal(ordinary["flow"][key], scoped["flow"][key])
    assert scoped["flow"]["total"].tolist() == [200., 200.]


def test_detector_catalog_scope_does_not_change_strategy_output():
    sd = symbol_data(flat_m5(600))
    expected = detectors.detect_all(sd)
    with analysis_scope():
        assert hash_obj(detectors.detect_all(sd)) == hash_obj(expected)
        assert hash_obj(detectors.detect_all(sd)) == hash_obj(expected)


def test_tape_cache_byte_budget_evicts_and_reports_without_cross_scope_state(monkeypatch):
    from quantmt5 import analysis_cache
    monkeypatch.setattr(analysis_cache, "_TICK_BYTE_LIMIT", 32)
    with analysis_scope() as stats:
        for key in range(3):
            analysis_cache.cached("tick_tape", key, lambda: (np.zeros(2, dtype=np.int64), None))
        assert stats["tick_cache_bytes"] == 32 and stats["evictions"] == 1
    with analysis_scope() as fresh:
        assert fresh["entries"] == 0 and fresh["tick_cache_bytes"] == 0


def test_replay_proxy_with_unknown_cost_remains_unknown(monkeypatch):
    monkeypatch.setattr(replay, "cost_profiles", lambda: {"scenarios": {"BASE": {
        "spread_floor_points": {"NEW": "not numeric"}, "slippage_points_per_side": {"NEW": 1},
        "commission_usd_per_lot_round_trip": 0}}})
    sd = SimpleNamespace(m1=object(), prof=dict(PROF), symbol="NEW")
    model, reason = replay.quote_model_for(sd, "BASE")
    assert model is None and "ECONOMICS_UNKNOWN" in reason
