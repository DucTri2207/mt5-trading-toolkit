import hashlib
from types import SimpleNamespace

import numpy as np
import pytest

from quantmt5.mt5_flow import read_snapshot_mt5
from quantmt5.util import iso_utc
from quantmt5.data import DataVersionMismatch


def _pin(tmp_path, rows, *, provider="NATIVE_TERMINAL", windows=None):
    p = tmp_path / "ticks"
    p.mkdir()
    f = p / "chunk.npz"
    np.savez(f, ticks=rows)
    sha = hashlib.sha256(f.read_bytes()).hexdigest()
    return {"chunk_dir": str(p), "chunks": [{"file": f.name, "sha256": sha}],
            "window_states": windows or {"0_300": "OK", "300_600": "OK"},
            "clock_profile": "RAW_IS_UTC", "content_hash": "pin", "provider_kind": provider}


def _m5():
    return SimpleNamespace(open_at=np.array([0., 300.]), close_at=np.array([300., 600.]))


def _rows(proxy=True):
    dt = [("time_msc", "i8"), ("bid", "f8"), ("ask", "f8"), ("flags", "i8"),
          ("last", "f8"), ("volume", "f8")]
    a = np.zeros(4, dtype=dt)
    a["time_msc"] = [1000, 1000, 200000, 400000]
    a["bid"] = [100, 100.1, 100.2, 100.1]; a["ask"] = a["bid"] + .1
    a["last"] = [0, 0, 0, 0]; a["volume"] = [0, 0, 0, 0]
    if not proxy:
        a["last"] = [100, 100.1, 100.2, 100.1]; a["volume"] = 1
        a["flags"] = [32 | 8, 64 | 8, 32 | 8, 64 | 8]
    return a


def test_proxy_preserves_same_ms_and_uses_midpoint_direction(tmp_path):
    pin = _pin(tmp_path, _rows())
    out = read_snapshot_mt5({"tick_versions": {"X": pin}}, _m5(), "X", 600)
    fl = out["flow"]
    assert fl["is_proxy"] and fl["volume_basis"] == "TICK_COUNT_PROXY"
    assert fl["delta"][0] == 2 and fl["total"][0] == 3
    assert out["profile"]["time_s"].shape[0] == 4


def test_real_flags_and_missing_costs_are_explicit(tmp_path):
    pin = _pin(tmp_path, _rows(proxy=False))
    out = read_snapshot_mt5({"tick_versions": {"X": pin}}, _m5(), "X", 600)
    assert not out["flow"]["is_proxy"]
    assert out["flow"]["volume_basis"] == "EXECUTED_TRADES"
    assert out["exec"]["source"] == "MT5"
    assert out["exec"]["commission_round_turn_price"] is None


def test_checksum_failure_happens_before_proxy_fallback(tmp_path):
    pin = _pin(tmp_path, _rows())
    (tmp_path / "ticks" / "chunk.npz").write_bytes(b"tampered")
    with pytest.raises(DataVersionMismatch):
        read_snapshot_mt5({"tick_versions": {"X": pin}}, _m5(), "X", 600)


def test_gap_keeps_missing_bar_nan_and_restarts_cvd(tmp_path):
    pin = _pin(tmp_path, _rows(), windows={"0_300": "OK", "300_600": "EMPTY_UNEXPLAINED"})
    out = read_snapshot_mt5({"tick_versions": {"X": pin}}, _m5(), "X", 600)
    fl = out["flow"]
    assert np.isfinite(fl["delta"][0]) and np.isnan(fl["delta"][1])
    assert np.isnan(fl["cvd"][1])


def test_real_ignores_quote_only_carried_volume(tmp_path):
    rows = _rows(proxy=False)
    rows["flags"][0] = 0  # carried last/volume is quote-only without update flags
    rows["volume"][0] = 9
    pin = _pin(tmp_path, rows)
    fl = read_snapshot_mt5({"tick_versions": {"X": pin}}, _m5(), "X", 600)["flow"]
    assert not fl["is_proxy"] and fl["total"][0] == 2


def test_future_trade_does_not_change_current_proxy_mode(tmp_path):
    rows = _rows(proxy=True)
    extra = rows[-1].copy(); extra["time_msc"] = 900000; extra["flags"] = 32 | 8; extra["last"] = 100; extra["volume"] = 1
    rows = np.concatenate([rows, np.array([extra], dtype=rows.dtype)])
    pin = _pin(tmp_path, rows)
    fl = read_snapshot_mt5({"tick_versions": {"X": pin}}, _m5(), "X", 600)["flow"]
    assert fl["is_proxy"]


def test_ambiguous_trade_side_is_explicit_proxy(tmp_path):
    rows = _rows(proxy=False); rows["flags"][0] = 32 | 64 | 8
    pin = _pin(tmp_path, rows)
    fl = read_snapshot_mt5({"tick_versions": {"X": pin}}, _m5(), "X", 600)["flow"]
    assert fl["is_proxy"] and "AMBIGUOUS_TRADE_SIDE_PROXY" in fl["reasons"]


def test_last_profile_uses_trade_price_and_volume(tmp_path):
    pin = _pin(tmp_path, _rows(proxy=False))
    out = read_snapshot_mt5({"tick_versions": {"X": pin}}, _m5(), "X", 600, chart_basis="LAST")
    assert out["profile"]["basis"] == "MT5_LAST_EXECUTED_VOLUME"
    assert np.allclose(out["profile"]["price"], [100, 100.1, 100.2, 100.1])



def test_side_only_trade_flags_and_zero_real_volume_use_integer_volume(tmp_path):
    base = _rows(proxy=False)
    rows = np.empty(len(base), dtype=base.dtype.descr + [("volume_real", "f8")])
    for name in base.dtype.names:
        rows[name] = base[name]
    rows["volume_real"] = 0.0
    rows["flags"] = [32, 64, 32, 64]
    fl = read_snapshot_mt5({"tick_versions": {"X": _pin(tmp_path, rows)}}, _m5(), "X", 600)["flow"]
    assert fl["is_proxy"] is False
    assert fl["delta"].tolist() == [1.0, -1.0]
    assert fl["total"].tolist() == [3.0, 1.0]


def test_missing_m5_bar_resets_cvd_and_tick_comparison(tmp_path):
    rows = _rows()
    rows["time_msc"][-1] = 700000
    bars = SimpleNamespace(open_at=np.array([0., 600.]), close_at=np.array([300., 900.]))
    pin = _pin(tmp_path, rows, windows={"0_900": "OK"})
    fl = read_snapshot_mt5({"tick_versions": {"X": pin}}, bars, "X", 900)["flow"]
    assert fl["cvd_start_index"] == 1
    assert fl["delta"][1] == 0.0 and fl["cvd"][1] == 0.0


def test_available_after_as_of_is_excluded_from_mode_and_quote(tmp_path):
    base = _rows(proxy=False)
    rows = np.empty(len(base),dtype=base.dtype.descr + [("available_msc","i8")])
    for name in base.dtype.names:
        rows[name] = base[name]
    rows["available_msc"] = 900000
    pin = _pin(tmp_path, rows)
    out = read_snapshot_mt5({"tick_versions": {"X": pin}}, _m5(), "X", 600)
    assert out["flow"]["use_in_decision"] is False
    assert out["exec"] is None


def test_utc_day_reset_marks_latest_segment(tmp_path):
    rows = _rows()
    rows["time_msc"] = [86101000,86101000,86300000,86500000]
    bars = SimpleNamespace(open_at=np.array([86100.,86400.]),close_at=np.array([86400.,86700.]))
    fl = read_snapshot_mt5({"tick_versions": {"X": _pin(tmp_path, rows, windows={"86100_86700":"OK"})}},bars,"X",86700)["flow"]
    assert fl["cvd_start_index"] == 1
    assert fl["cvd"][1] == fl["delta"][1]
    assert fl["reset_at"] == iso_utc(86400)


def test_source_clock_is_converted_once(tmp_path):
    rows = _rows()
    rows["time_msc"] += 7200 * 1000
    pin = _pin(tmp_path, rows)
    pin["clock_profile"] = "EET_EU"
    out = read_snapshot_mt5({"tick_versions": {"X": pin}}, _m5(), "X", 600)
    assert out["flow"]["delta"].tolist() == [2.0, -1.0]
    assert out["exec"]["event_at"] == iso_utc(400)
