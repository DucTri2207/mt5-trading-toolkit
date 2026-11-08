"""Regressions for codex_025 F1–F5 (B1 revision). Synthetic / fake inputs only; no MT5 connection."""
import copy
import datetime as dt
import json

import numpy as np
import pytest

from quantmt5 import collector, context, data, detectors, snapshot, util
from quantmt5.data import DataVersionMismatch

T0 = 1736121600  # Monday 2025-01-06 00:00 UTC
FX = {"kind": "ROLLOVER_ONLY", "tz": "America/New_York", "rollover": "17:00", "weekly_close": "Fri 17:00"}
XAU = {"kind": "DAILY_BREAK", "tz": "America/New_York", "daily_close": "17:00", "daily_reopen": "18:00", "weekly_close": "Fri 17:00"}
RATE = np.dtype([("time", "i8"), ("open", "f8"), ("high", "f8"), ("low", "f8"), ("close", "f8"), ("tick_volume", "u8"), ("spread", "i4"), ("real_volume", "u8")])
TICK = np.dtype([("time_msc", "i8"), ("bid", "f8"), ("ask", "f8"), ("flags", "u4")])


def rates(start, n, half=0.001, step=300):
    a = np.zeros(n, RATE)
    a["time"] = start + step * np.arange(n)
    a["open"] = a["close"] = 1.1
    a["high"], a["low"] = 1.1 + half, 1.1 - half
    a["tick_volume"], a["spread"] = 100, 10
    return a


class Bars:
    TIMEFRAME_M5 = 5

    def __init__(self, *batches):
        self.batches, self.n = list(batches), 0

    def copy_rates_range(self, sym, tf, frm, to):
        b = self.batches[min(self.n, len(self.batches) - 1)]
        self.n += 1
        return None if b is None else b[(b["time"] >= frm) & (b["time"] <= to)].copy()   # honours the requested range

    def last_error(self):
        return (-1, "fake")


class Ticks:
    COPY_TICKS_ALL = -1

    def __init__(self, *batches):
        self.batches, self.n = list(batches), 0

    def copy_ticks_range(self, *args):
        b = self.batches[min(self.n, len(self.batches) - 1)]
        self.n += 1
        return b.copy()

    def last_error(self):
        return (-1, "fake")


# ======================================================================= F1 snapshot/context pinned to data version
@pytest.fixture
def collected_registry(tmp_path, monkeypatch):
    root = tmp_path / "source"
    cd = root / "EURUSD" / "bars" / "M5"
    cd.mkdir(parents=True)
    one = collector.commit_chunk(cd, "first", "rates", rates(T0, 600))
    ck = {"chunks": [one], "windows": {"first": {"status": "OK"}}, "identity": {"fixture": "synthetic"}}
    collector.save_checkpoint(cd, ck)
    reg = copy.deepcopy(data.load_registry())
    frag = collector.registry_fragment(root, "synthetic_source", ["EURUSD"], ("M5",))["EURUSD"]
    frag["timeframes"].update({"H1": {"derive_from": "M5"}, "D1": {"derive_from": "M5"}})
    reg["source_id"], reg["symbols"] = "synthetic_source", {"EURUSD": frag}
    monkeypatch.setattr(snapshot, "load_registry", lambda: reg)
    monkeypatch.setattr(detectors, "load_registry", lambda: reg)
    return {"reg": reg, "cd": cd, "ck": ck}


def _atr(ctx):
    return next(f for f in ctx["features"] if f["name"] == "atr14_wilder" and f["tf"] == "M5")


def test_F1_old_snapshot_reads_pinned_chunks_after_backfill(collected_registry):
    cd, ck = collected_registry["cd"], collected_registry["ck"]
    as_of = T0 + 720 * 300 + 1
    s1 = snapshot.make_snapshot(as_of, ["EURUSD"], include_scan=False)
    before = context.build_market_context(s1["snapshot_id"], "EURUSD")
    ck["chunks"].append(collector.commit_chunk(cd, "backfill", "rates", rates(T0 + 600 * 300, 120, half=0.01)))
    ck["windows"]["backfill"] = {"status": "OK"}
    collector.save_checkpoint(cd, ck)
    s2 = snapshot.make_snapshot(as_of, ["EURUSD"], include_scan=False)
    assert s2["snapshot_id"] != s1["snapshot_id"] and s2["dataset_manifest_hash"] != s1["dataset_manifest_hash"]
    assert s2["symbols"]["EURUSD"]["watermark_m5_close_at"] > s1["symbols"]["EURUSD"]["watermark_m5_close_at"]
    after_old = context.build_market_context(s1["snapshot_id"], "EURUSD")
    after_new = context.build_market_context(s2["snapshot_id"], "EURUSD")
    assert _atr(after_old) == _atr(before)                               # old id → old data, exactly
    assert _atr(after_new)["value"] != _atr(before)["value"]             # new data only under the new id
    src = _atr(after_old)["source"]
    assert src["data_version_pinned"] is True and src["data_version"] == s1["data_versions"]["EURUSD"]["M5"]["content_hash"]
    assert after_old["data_versions_consumed"]["M5"] == s1["data_versions"]["EURUSD"]["M5"]["content_hash"]


def test_F1_fail_closed_when_pinned_content_is_gone_or_changed(collected_registry):
    cd = collected_registry["cd"]
    as_of = T0 + 600 * 300 + 1
    s1 = snapshot.make_snapshot(as_of, ["EURUSD"], include_scan=False)
    f = cd / s1["data_versions"]["EURUSD"]["M5"]["chunks"][0]["file"]
    raw = bytearray(f.read_bytes())
    raw[-12] ^= 0xFF
    f.write_bytes(bytes(raw))
    with pytest.raises(DataVersionMismatch):
        context.build_market_context(s1["snapshot_id"], "EURUSD")
    f.unlink()
    with pytest.raises(DataVersionMismatch, match="CHUNK_MISSING"):
        context.build_market_context(s1["snapshot_id"], "EURUSD")


def test_F1_unpinned_snapshot_rejected_after_manifest_change(collected_registry):
    cd, ck = collected_registry["cd"], collected_registry["ck"]
    s1 = snapshot.make_snapshot(T0 + 600 * 300 + 1, ["EURUSD"], include_scan=False)
    legacy = dict(s1)
    legacy.pop("data_versions")
    legacy["snapshot_id"] = "SNAP_unpinned_fixture"
    util.write_immutable_json(snapshot.snapshot_path(legacy["snapshot_id"]), legacy)
    context.build_market_context(legacy["snapshot_id"], "EURUSD")      # manifest unchanged → still allowed
    ck["chunks"].append(collector.commit_chunk(cd, "more", "rates", rates(T0 + 600 * 300, 10)))
    collector.save_checkpoint(cd, ck)
    with pytest.raises(DataVersionMismatch):
        context.build_market_context(legacy["snapshot_id"], "EURUSD")


def test_F1_legacy_archive_pin_mismatch_is_rejected():
    reg = data.load_registry()
    v = data.dataset_version(reg, "EURUSD", "M5")
    assert v["sha256"] == reg["symbols"]["EURUSD"]["timeframes"]["M5"]["sha256"] and v["content_hash"]
    bad = dict(v, content_hash="0" * 64, sha256="f" * 64)
    with pytest.raises(DataVersionMismatch):
        data.load_bars("EURUSD", "M5", reg, pins={"M5": bad})
    p = data.load_bars("EURUSD", "M5", reg, pins={"M5": v}).provenance
    assert p["data_version"] == v["content_hash"] and p["data_version_pinned"] is True


# ======================================================================= F2 boundary conflict
PEND = (T0 + 3598) * 1000
FIRST = np.array([(T0 * 1000 + 1000, 1.1, 1.11, 1), (PEND, 1.2, 1.21, 1), (PEND, 1.3, 1.31, 1)], dtype=TICK)
CONFLICT = np.array([(PEND, 9.0, 9.01, 1), ((T0 + 3601) * 1000, 1.4, 1.41, 1)], dtype=TICK)
CONSISTENT = np.array([(PEND, 1.2, 1.21, 1), (PEND, 1.3, 1.31, 1), ((T0 + 3601) * 1000, 1.4, 1.41, 1)], dtype=TICK)


def _ticks(adapter, d, **kw):
    return collector.collect_ticks(adapter, "EURUSD", T0, T0 + 7200, d, {"fixture": "s"}, FX, window_s=3600, finalize_tail=True, **kw)


def test_F2_conflict_unresolved_cursor_held_evidence_kept_and_retried(tmp_path):
    r = _ticks(Ticks(FIRST, CONFLICT), tmp_path)
    ck = collector.load_checkpoint(tmp_path)
    assert r["status"] == "PARTIAL" and not r["coverage_complete"]
    assert r["window_status_counts"] == {"CONFLICT_UNRESOLVED": 1, "OK": 1}
    assert ck["committed_through_ms"] <= PEND and ck["pending_ms"] == PEND and ck["pending_rows"] == 2
    w = ck["windows"][f"{T0 + 3600}_{T0 + 7200}"]
    ev = w["conflicts"][0]["evidence"]
    with np.load(tmp_path / ev["file"]) as z:
        assert np.array_equal(z["stored"], FIRST[1:]) and np.array_equal(z["fetched"], CONFLICT[:1])   # both versions kept
    assert util.sha256_file(tmp_path / ev["file"]) == ev["sha256"]
    assert collector.read_tick_chunks(tmp_path)["time_msc"].max() < PEND                          # nothing past the group accepted
    # retry with the same disagreement → still unresolved (window not skipped as OK)
    r2 = _ticks(Ticks(CONFLICT), tmp_path)
    assert r2["window_status_counts"].get("CONFLICT_UNRESOLVED") == 1 and not r2["coverage_complete"]
    # source settles back to the stored version → resumes, full order & multiplicity
    r3 = _ticks(Ticks(CONSISTENT), tmp_path)
    assert r3["status"] == "OK" and r3["coverage_complete"]
    assert np.array_equal(collector.read_tick_chunks(tmp_path), np.r_[FIRST[:1], CONSISTENT])


def test_F2_explicit_resync_adopts_source_version_transparently(tmp_path):
    _ticks(Ticks(FIRST, CONFLICT), tmp_path)
    r = _ticks(Ticks(CONFLICT), tmp_path, resync_conflicts=True)
    ck = collector.load_checkpoint(tmp_path)
    assert r["status"] == "OK"
    res = ck["resolutions"][0]
    assert res["resolution"] == "RESYNCED_TO_SOURCE_VERSION" and res["stored_rows"] == 2 and res["source_rows"] == 1
    assert (tmp_path / res["evidence"]["file"]).exists()
    assert np.array_equal(collector.read_tick_chunks(tmp_path), np.r_[FIRST[:1], CONFLICT])


def test_F2_committed_tail_change_is_a_conflict(tmp_path):
    # same second as the pending group: an already committed tick (200 ms) changes when the second is re-read
    pend = PEND + 700
    first = np.array([(PEND + 200, 1.1, 1.11, 1), (pend, 1.2, 1.21, 1)], dtype=TICK)
    changed = np.array([(PEND + 200, 7.7, 7.71, 1), (pend, 1.2, 1.21, 1), ((T0 + 3601) * 1000, 1.4, 1.41, 1)], dtype=TICK)
    r = _ticks(Ticks(first, changed), tmp_path)
    ck = collector.load_checkpoint(tmp_path)
    assert r["window_status_counts"].get("CONFLICT_UNRESOLVED") == 1 and not r["coverage_complete"]
    assert ck["conflicts"][0]["reason"] == "SOURCE_CONFLICT_COMMITTED_TAIL" and ck["committed_through_ms"] <= pend
    # unchanged re-read of the same second is not a conflict
    ok = np.array([(PEND + 200, 1.1, 1.11, 1), (pend, 1.2, 1.21, 1), ((T0 + 3601) * 1000, 1.4, 1.41, 1)], dtype=TICK)
    assert _ticks(Ticks(ok), tmp_path)["status"] == "OK"


# ======================================================================= F3 partial (non-empty) bar windows
NOON = T0 + 12 * 3600  # Monday 12:00 UTC, FX open


def _bars(adapter, d, start=NOON, end=NOON + 3600, session=FX):
    return collector.collect_bars(adapter, "EURUSD", "M5", start, end, d, {"fixture": "s"}, session, window_s=3600)


def test_F3_partial_window_not_complete_then_retry_supersedes(tmp_path):
    r = _bars(Bars(rates(NOON, 1)), tmp_path)
    ck = collector.load_checkpoint(tmp_path)
    w = ck["windows"][f"{NOON}_{NOON + 3600}"]
    assert r["status"] == "PARTIAL" and not r["coverage_complete"] and w["status"] == "PARTIAL_GAPS"
    assert w["expected_open_slots"] == 12 and w["missing_open_slots"] == 11
    assert w["missing_open_ranges"] == [{"from": "2025-01-06T12:05:00Z", "to_exclusive": "2025-01-06T13:00:00Z", "bars": 11}]
    first_file = ck["chunks"][0]["file"]
    # loader → provenance; never presented as complete
    b, prov = data.load_collected_bars(tmp_path)
    assert prov["coverage_complete"] is False and "COVERAGE_PARTIAL_GAPS" in prov["data_quality_flags"]
    assert prov["coverage_missing_open_ranges"][0]["bars"] == 11
    # retry fills the gap: superseding completion (no conflict), old chunk kept as immutable history
    r2 = _bars(Bars(rates(NOON, 12)), tmp_path)
    ck2 = collector.load_checkpoint(tmp_path)
    assert r2["status"] == "OK" and r2["coverage_complete"] and not ck2.get("conflicts")
    assert ck2["chunks"][0]["commit"] == "SUPERSEDES_PARTIAL" and ck2["superseded"][0]["file"] == first_file
    assert (tmp_path / first_file).exists() and len(data.load_collected_bars(tmp_path)[0]) == 12


def test_F3_refetch_that_changes_accepted_bars_is_conflict(tmp_path):
    _bars(Bars(rates(NOON, 1)), tmp_path)
    changed = rates(NOON, 12)
    changed["close"][0] = changed["open"][0] = 1.1005
    r = _bars(Bars(changed), tmp_path)
    ck = collector.load_checkpoint(tmp_path)
    w = ck["windows"][f"{NOON}_{NOON + 3600}"]
    assert w["status"] == "CONFLICT_UNRESOLVED" and not r["coverage_complete"]
    assert len(data.load_collected_bars(tmp_path)[0]) == 1          # previously accepted version still the accepted one


def test_F3_scheduled_closed_slots_are_not_missing(tmp_path):
    fri = T0 - 3 * 86400 + 21 * 3600   # Friday 2025-01-03 21:00 UTC = 16:00 NY; market closes 17:00 NY
    r = _bars(Bars(rates(fri, 12)), tmp_path, start=fri, end=fri + 2 * 3600)
    ck = collector.load_checkpoint(tmp_path)
    assert r["coverage_complete"] and r["status"] == "OK"
    assert ck["windows"][f"{fri}_{fri + 3600}"]["status"] == "OK"
    assert ck["windows"][f"{fri + 3600}_{fri + 7200}"]["status"] == "EMPTY_MARKET_CLOSED"   # after 17:00 NY Friday


def test_F3_quality_reaches_snapshot_and_context(tmp_path, monkeypatch):
    root = tmp_path / "src"
    cd = root / "EURUSD" / "bars" / "M5"
    full = rates(T0, 300)
    _bars(Bars(full[:250]), cd, start=T0, end=T0 + 300 * 300)
    reg = copy.deepcopy(data.load_registry())
    frag = collector.registry_fragment(root, "s", ["EURUSD"], ("M5",))["EURUSD"]
    frag["timeframes"].update({"H1": {"derive_from": "M5"}, "D1": {"derive_from": "M5"}})
    reg["source_id"], reg["symbols"] = "s", {"EURUSD": frag}
    monkeypatch.setattr(snapshot, "load_registry", lambda: reg)
    monkeypatch.setattr(detectors, "load_registry", lambda: reg)
    s = snapshot.make_snapshot(T0 + 250 * 300 + 1, ["EURUSD"], include_scan=False)
    assert "COVERAGE_INCOMPLETE:M5" in s["symbols"]["EURUSD"]["quality_flags"]
    ctx = context.build_market_context(s["snapshot_id"], "EURUSD")
    src = _atr(ctx)["source"]
    assert src["coverage_complete"] is False and "COVERAGE_INCOMPLETE" in src["data_quality_flags"]
    assert "COVERAGE_INCOMPLETE:M5" in ctx["quality_flags"]


# ======================================================================= F4 non-finite / broken OHLC quarantined
@pytest.mark.parametrize("mutate,reason", [
    (lambda a: [a[f].__setitem__(5, np.nan) for f in ("open", "high", "low", "close")], "NON_FINITE_OHLC"),
    (lambda a: a["high"].__setitem__(3, np.inf), "NON_FINITE_OHLC"),
    (lambda a: a["low"].__setitem__(2, -np.inf), "NON_FINITE_OHLC"),
    (lambda a: (a["high"].__setitem__(4, 1.0), a["low"].__setitem__(4, 1.2)), "HIGH_BELOW_LOW"),
    (lambda a: a["low"].__setitem__(6, 1.15), "LOW_ABOVE_OPEN_OR_CLOSE"),
    (lambda a: [a[f].__setitem__(7, 0.0) for f in ("open", "high", "low", "close")], "NON_POSITIVE_PRICE"),
    (lambda a: a["time"].__setitem__(8, a["time"][8] + 17), "TIME_NOT_ALIGNED_TO_TF"),
])
def test_F4_invalid_ohlc_quarantined_not_accepted(tmp_path, mutate, reason):
    a = rates(NOON, 12)
    mutate(a)
    r = _bars(Bars(a), tmp_path)
    ck = collector.load_checkpoint(tmp_path)
    w = ck["windows"][f"{NOON}_{NOON + 3600}"]
    assert r["status"] == "PARTIAL" and not r["coverage_complete"] and not ck["chunks"]
    assert w["status"] == "ERROR_INVALID_BATCH" and reason in [x["reason"] for x in w["reasons"]]
    q = w["quarantine"]
    assert (tmp_path / q["file"]).exists() and util.sha256_file(tmp_path / q["file"]) == q["sha256"]
    with pytest.raises(ValueError, match="NO_COMMITTED_CHUNKS"):
        data.load_collected_bars(tmp_path)
    # retry with a clean batch is accepted
    r2 = _bars(Bars(rates(NOON, 12)), tmp_path)
    assert r2["status"] == "OK"


def test_F4_nonfinite_ticks_quarantined(tmp_path):
    bad = np.array([(T0 * 1000 + 5, np.nan, 1.1, 1), (T0 * 1000 + 9, 1.1, np.inf, 1)], dtype=TICK)
    r = collector.collect_ticks(Ticks(bad), "EURUSD", T0, T0 + 3600, tmp_path, {}, FX, 3600, finalize_tail=True)
    ck = collector.load_checkpoint(tmp_path)
    w = next(iter(ck["windows"].values()))
    assert r["status"] == "PARTIAL" and w["status"] == "ERROR_INVALID_BATCH" and not ck["chunks"]
    assert {"NON_FINITE_BID", "NON_FINITE_ASK"} <= {x["reason"] for x in w["reasons"]}


# ======================================================================= R1 read contract (clock / TF definition) pinned
def _legacy_clock_registry(tmp_path, monkeypatch, profile="RAW_IS_UTC"):
    root = tmp_path / "source"
    cd = root / "EURUSD" / "bars" / "M5"
    cd.mkdir(parents=True)
    one = collector.commit_chunk(cd, "bars", "rates", rates(T0, 600))
    ck = {"chunks": [one], "windows": {"first": {"status": "OK"}}, "identity": {"fixture": "synthetic"}}
    collector.save_checkpoint(cd, ck)
    reg = copy.deepcopy(data.load_registry())
    frag = collector.registry_fragment(root, "fixture", ["EURUSD"], ("M5",))["EURUSD"]
    frag["timeframes"].update({"H1": {"derive_from": "M5"}, "D1": {"derive_from": "M5"}})
    frag["time_basis"] = {"contract": "LEGACY_CACHE_HYPOTHESIS", "source_time_basis_recorded": "synthetic clock fixture",
                          "clock_profile_applied": profile, "clock_profile_status": "ASSUMED", "time_basis_status": "UNVERIFIED"}
    reg["symbols"], reg["source_id"] = {"EURUSD": frag}, "fixture"
    monkeypatch.setattr(snapshot, "load_registry", lambda: reg)
    monkeypatch.setattr(detectors, "load_registry", lambda: reg)
    return reg, frag, cd, ck


def test_R1_clock_mapping_change_fails_closed_for_old_snapshot(tmp_path, monkeypatch):
    reg, frag, cd, ck = _legacy_clock_registry(tmp_path, monkeypatch)
    s1 = snapshot.make_snapshot(T0 + 720 * 300 + 1, ["EURUSD"], include_scan=False)
    before = context.build_market_context(s1["snapshot_id"], "EURUSD")
    assert _atr(before)["source"]["clock_profile"] == "RAW_IS_UTC"
    assert s1["data_versions"]["EURUSD"]["M5"]["read_contract"]["clock_profile"] == "RAW_IS_UTC"
    frag["time_basis"]["clock_profile_applied"] = "EET_EU"
    with pytest.raises(DataVersionMismatch, match=r"READ_CONTRACT_MISMATCH:EURUSD:.*clock_profile"):
        context.build_market_context(s1["snapshot_id"], "EURUSD")
    s2 = snapshot.make_snapshot(T0 + 720 * 300 + 1, ["EURUSD"], include_scan=False)
    assert s2["snapshot_id"] != s1["snapshot_id"]                     # new interpretation → new identity
    assert _atr(context.build_market_context(s2["snapshot_id"], "EURUSD"))["source"]["clock_profile"] == "EET_EU"
    frag["time_basis"]["clock_profile_applied"] = "RAW_IS_UTC"         # revert → the old id reads exactly as before
    assert _atr(context.build_market_context(s1["snapshot_id"], "EURUSD")) == _atr(before)


def test_R1_derived_tf_definition_change_fails_closed(tmp_path, monkeypatch):
    reg, frag, cd, ck = _legacy_clock_registry(tmp_path, monkeypatch)
    s1 = snapshot.make_snapshot(T0 + 720 * 300 + 1, ["EURUSD"], include_scan=False)
    frag["timeframes"]["H1"] = {"format": "collector_bars_v1", "chunk_dir": str(cd)}   # H1 redefined as native
    with pytest.raises(DataVersionMismatch, match="READ_CONTRACT_MISMATCH:EURUSD:H1"):
        context.build_market_context(s1["snapshot_id"], "EURUSD")


def test_R1_pinned_read_survives_valid_backfill(tmp_path, monkeypatch):
    reg, frag, cd, ck = _legacy_clock_registry(tmp_path, monkeypatch)
    s1 = snapshot.make_snapshot(T0 + 720 * 300 + 1, ["EURUSD"], include_scan=False)
    before = context.build_market_context(s1["snapshot_id"], "EURUSD")
    ck["chunks"].append(collector.commit_chunk(cd, "backfill", "rates", rates(T0 + 600 * 300, 120, half=0.01)))
    collector.save_checkpoint(cd, ck)
    assert _atr(context.build_market_context(s1["snapshot_id"], "EURUSD")) == _atr(before)


def test_R1_snapshot_without_read_contract_pin_is_rejected(tmp_path, monkeypatch):
    reg, frag, cd, ck = _legacy_clock_registry(tmp_path, monkeypatch)
    s1 = snapshot.make_snapshot(T0 + 720 * 300 + 1, ["EURUSD"], include_scan=False)
    old = copy.deepcopy(s1)
    for v in old["data_versions"]["EURUSD"].values():
        v.pop("read_contract_hash", None)
        v.pop("read_contract", None)
    old["snapshot_id"] = "SNAP_rev2_style_pin_fixture"
    util.write_immutable_json(snapshot.snapshot_path(old["snapshot_id"]), old)
    with pytest.raises(DataVersionMismatch, match="READ_CONTRACT_NOT_PINNED"):
        context.build_market_context(old["snapshot_id"], "EURUSD")


# ======================================================================= R2 empty overlap must confirm the pending group
def test_R2_empty_reread_of_known_pending_group_is_conflict(tmp_path):
    pms = (T0 + 3598) * 1000
    first = np.array([(T0 * 1000 + 1000, 1.1, 1.11, 1), (pms, 1.2, 1.21, 1)], dtype=TICK)
    r = _ticks(Ticks(first, first[:0]), tmp_path)
    ck = collector.load_checkpoint(tmp_path)
    w = ck["windows"][f"{T0 + 3600}_{T0 + 7200}"]
    assert not r["coverage_complete"] and w["status"] == "CONFLICT_UNRESOLVED"
    assert w["conflicts"][0]["reason"] == "SOURCE_CONFLICT_PENDING_GROUP_MISSING_ON_REREAD"
    assert ck["pending_ms"] == pms and ck["committed_through_ms"] <= pms
    assert collector.read_tick_chunks(tmp_path)["time_msc"].max() < pms        # held group not finalized
    # retry once the source returns the group again (+ new data) → resolves with exact multiplicity
    later = np.array([(pms, 1.2, 1.21, 1), ((T0 + 3700) * 1000, 1.3, 1.31, 1)], dtype=TICK)
    r2 = _ticks(Ticks(later), tmp_path)
    assert r2["status"] == "OK" and np.array_equal(collector.read_tick_chunks(tmp_path), np.r_[first, later[1:]])


def test_R2_overlap_only_window_is_evaluated_as_empty(tmp_path):
    """The pending group is re-read identically but the new open hour has no ticks of its own → unexplained, not OK."""
    pms = (T0 + 3598) * 1000
    first = np.array([(T0 * 1000 + 1000, 1.1, 1.11, 1), (pms, 1.2, 1.21, 1)], dtype=TICK)
    r = _ticks(Ticks(first, first[1:]), tmp_path)
    ck = collector.load_checkpoint(tmp_path)
    w = ck["windows"][f"{T0 + 3600}_{T0 + 7200}"]
    assert w["status"] == "EMPTY_UNEXPLAINED" and w["received_rows_new"] == 0 and w["overlap_group_confirmed_rows"] == 1
    assert not r["coverage_complete"] and ck["pending_ms"] == pms


def test_R2_closed_market_after_confirmed_group_finalizes_cleanly(tmp_path):
    fri = int(_utc(2025, 1, 3, 21))          # Fri 16:00 NY; next hour (17:00-18:00 NY) is closed
    pms = (fri + 3590) * 1000
    first = np.array([((fri + 10) * 1000, 1.1, 1.11, 1), (pms, 1.2, 1.21, 1), (pms, 1.25, 1.26, 1)], dtype=TICK)
    r = collector.collect_ticks(Ticks(first, first[1:]), "EURUSD", fri, fri + 7200, tmp_path, {}, FX, window_s=3600, finalize_tail=True)
    ck = collector.load_checkpoint(tmp_path)
    assert r["status"] == "OK" and r["coverage_complete"] and ck["pending_ms"] is None
    assert ck["windows"][f"{fri + 3600}_{fri + 7200}"]["status"] == "EMPTY_MARKET_CLOSED"
    assert np.array_equal(collector.read_tick_chunks(tmp_path), first)


# ======================================================================= R3 D1 coverage
def _d1(adapter, d, session, start=T0, days=5):
    class A(Bars):
        TIMEFRAME_D1 = 16408
    adapter.__class__ = A
    return collector.collect_bars(adapter, "EURUSD", "D1", start, start + days * 86400, d, {"fixture": "s"}, session, window_s=days * 86400)


def test_R3_truncated_D1_without_boundary_is_gaps(tmp_path):
    r = _d1(Bars(rates(T0, 1, step=86400)), tmp_path, FX)
    w = next(iter(collector.load_checkpoint(tmp_path)["windows"].values()))
    assert not r["coverage_complete"] and w["status"] == "PARTIAL_GAPS"
    assert w["slot_check"] == "D1_BOUNDARY_UNKNOWN_LOWER_BOUND_ONLY" and w["min_bars_boundary_free"] == 3


def test_R3_full_D1_without_boundary_is_unverified_not_complete(tmp_path):
    r = _d1(Bars(rates(T0, 5, step=86400)), tmp_path, FX)
    w = next(iter(collector.load_checkpoint(tmp_path)["windows"].values()))
    assert w["status"] == "COVERAGE_UNVERIFIED_D1_BOUNDARY" and not r["coverage_complete"]
    b, prov = data.load_collected_bars(tmp_path)
    assert prov["coverage_complete"] is False and "COVERAGE_COVERAGE_UNVERIFIED_D1_BOUNDARY" in prov["data_quality_flags"]


def test_R3_declared_boundary_checks_each_day_and_retries(tmp_path):
    sess = dict(FX, d1_boundary={"tz": "UTC", "day_start": "00:00", "status": "DECLARED_FOR_FIXTURE"})
    full = rates(T0, 5, step=86400)
    r = _d1(Bars(full[[0, 1, 3, 4]]), tmp_path, sess)                     # Wednesday missing
    w = next(iter(collector.load_checkpoint(tmp_path)["windows"].values()))
    assert w["status"] == "PARTIAL_GAPS" and w["missing_open_days"] == ["2025-01-08T00:00:00Z"] and not r["coverage_complete"]
    r2 = _d1(Bars(full), tmp_path, sess)                                   # retry completes (superseding, no conflict)
    assert r2["status"] == "OK" and r2["coverage_complete"]
    # a fully closed day (Saturday) is not expected: empty window = market closed, complete
    sat = T0 - 2 * 86400
    r3 = _d1(Bars(rates(T0, 1, step=86400)), tmp_path / "wk", sess, start=sat, days=1)
    assert r3["status"] == "OK" and r3["window_status_counts"] == {"EMPTY_MARKET_CLOSED": 1}


def test_R3_declared_boundary_sunday_open_expects_the_day(tmp_path):
    sess = dict(FX, d1_boundary={"tz": "UTC", "day_start": "00:00"})
    sun = T0 - 86400                                                        # Sun 2025-01-05 UTC: FX opens 22:00 UTC
    r = _d1(Bars(rates(T0, 1, step=86400)), tmp_path, sess, start=sun, days=2)
    w = next(iter(collector.load_checkpoint(tmp_path)["windows"].values()))
    assert w["missing_open_days"] == ["2025-01-05T00:00:00Z"] and not r["coverage_complete"]   # honest: Sunday UTC has open minutes


def test_R3_D1_quality_reaches_snapshot(tmp_path, monkeypatch):
    root = tmp_path / "src"
    m5d, d1d = root / "EURUSD" / "bars" / "M5", root / "EURUSD" / "bars" / "D1"
    _bars(Bars(rates(T0, 300)), m5d, start=T0, end=T0 + 300 * 300)
    _d1(Bars(rates(T0, 1, step=86400)), d1d, FX)
    reg = copy.deepcopy(data.load_registry())
    frag = collector.registry_fragment(root, "s", ["EURUSD"], ("M5", "D1"))["EURUSD"]
    frag["timeframes"]["H1"] = {"derive_from": "M5"}
    reg["source_id"], reg["symbols"] = "s", {"EURUSD": frag}
    monkeypatch.setattr(snapshot, "load_registry", lambda: reg)
    monkeypatch.setattr(detectors, "load_registry", lambda: reg)
    s = snapshot.make_snapshot(T0 + 300 * 300 + 1, ["EURUSD"], include_scan=False)
    assert "COVERAGE_INCOMPLETE:D1" in s["symbols"]["EURUSD"]["quality_flags"]


# ======================================================================= F5 stale vs closed by schedule at as_of
def _sd(last_close, session):
    from quantmt5.detectors import SymbolData
    b = data._from_rates("EURUSD", "M5", rates(last_close - 12 * 300, 12), "RAW_IS_UTC", {"kind": "SYNTHETIC", "clock_profile": "RAW_IS_UTC"})
    return SymbolData("EURUSD", b, data.aggregate(b, "H1"), data.aggregate(b, "D1"), None, 1e-5, {"session": session}, "s")


def _utc(*a):
    return dt.datetime(*a, tzinfo=dt.timezone.utc).timestamp()


def test_F5_market_state_follows_schedule_at_as_of():
    mon_0100 = T0 + 3600
    st = snapshot._market_state
    assert st(_sd(mon_0100, FX), T0 + 2 * 86400 + 12 * 3600) == ("STALE", ["STALE", "FEED_STALE_DURING_SCHEDULED_OPEN"])   # Wed noon, >36h old
    fri_close = _utc(2025, 1, 3, 21, 55)                         # Fri 16:55 NY last bar
    assert st(_sd(fri_close, FX), _utc(2025, 1, 4, 12))[0] == "MARKET_CLOSED_OR_BREAK"                   # Saturday
    assert st(_sd(fri_close, FX), _utc(2025, 1, 5, 22, 3)) == ("STALE", ["STALE", "AWAITING_FIRST_BAR_AFTER_REOPEN"])   # Sun 17:03 NY
    assert st(_sd(fri_close, FX), _utc(2025, 1, 5, 23, 30)) == ("STALE", ["STALE", "FEED_STALE_DURING_SCHEDULED_OPEN"])  # Sun 18:30 NY
    tue_1655 = _utc(2025, 1, 7, 21, 55)
    assert st(_sd(tue_1655, XAU), _utc(2025, 1, 7, 22, 30))[0] == "MARKET_CLOSED_OR_BREAK"               # XAU daily break 17:30 NY
    assert st(_sd(tue_1655, XAU), _utc(2025, 1, 7, 23, 4)) == ("STALE", ["STALE", "AWAITING_FIRST_BAR_AFTER_REOPEN"])    # 18:04 NY
    assert st(_sd(mon_0100, {}), T0 + 3 * 86400)[0] == "UNKNOWN_SCHEDULE"                                # no schedule → no claim
    assert st(_sd(mon_0100, FX), mon_0100 + 300)[0] == "FRESH"
