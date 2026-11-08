"""Tick profile coverage and proxy semantics, independent of live MT5."""
import numpy as np
import pytest

from quantmt5 import fabio
from synth import symbol_data
from test_fabio import f1_rows, exec_in


def test_tick_profile_counts_actual_price_levels_only_with_full_window_coverage():
    sd = symbol_data(f1_rows())
    begin, finish = float(sd.m5.open_at[-2]), float(sd.m5.close_at[-1])
    tape = {"time_s": np.array([begin + 1, begin + 2, finish - 1]),
            "price": np.array([100.05, 100.05, 100.25]), "weight": np.ones(3),
            "covered_spans": [(begin, finish)], "basis": "MT5_BID_TICK_ACTIVITY"}
    p0, bins, basis = fabio.window_profile(sd.m5, len(sd.m5) - 2, len(sd.m5) - 1, .1, tape)
    assert basis == "MT5_BID_TICK_ACTIVITY"
    assert p0 == pytest.approx(100.0)
    assert bins.tolist() == [2.0, 0.0, 1.0]
    tape["covered_spans"] = [(begin + 10, finish)]
    _, _, basis = fabio.window_profile(sd.m5, len(sd.m5) - 2, len(sd.m5) - 1, .1, tape)
    assert basis == "MT5_BAR_TICK_VOLUME_UNIFORM_PROXY"


def test_proxy_cvd_is_not_reported_as_real_aggression():
    rows = f1_rows() + [(104.2, 105.0, 103.9, 104.9, 100)]
    sd = symbol_data(rows); n = len(sd.m5); as_of = float(sd.m5.available_at[-1])
    delta = np.full(n, 20.0)
    fl = {"status": "USABLE", "use_in_decision": True, "is_proxy": True, "delta": delta,
          "total": np.full(n, 100.0), "cvd": np.cumsum(delta), "cvd_start_index": 0,
          "volume_basis": "TICK_DIRECTION_PROXY", "route": "MT5_TICK_DIRECTION_PROXY", "source": "MT5_FIXTURE"}
    data = {"flow": fl, "exec": exec_in(as_of,bid=104.85,ask=104.95), "provenance": {"provider_kind": "SYNTHETIC_FIXTURE"}}
    r = fabio.analyze(sd, as_of, symbol="TEST", mt5_data=data)
    f1 = r["families"]["F1"]
    assert f1["gates"]["flow"]["class"] == "TICK_ACTIVITY_ALIGNED_WITH_PRICE"
    assert f1["gates"]["flow"]["is_proxy"] is True
    assert f1["variants"]["price_plus_cvd"]["is_proxy"] is True
    assert f1["variants"]["price_plus_local_aggression"]["decision"] == "DATA_UNAVAILABLE"
    assert r["capabilities_used"]["external_flow"] is False
