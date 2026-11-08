import copy

import numpy as np
import pytest

from quantmt5.evening_context import asset_metadata, build_currency_strength, relative_movement
from quantmt5.util import iso_utc
from tests.synth import T0, bars


def series():
    # Initial 24 H1 bars have exact ATR14=2, last close jumps from 100 to 104.
    return bars(3600, T0, [(100, 101, 99, 100)] * 24 + [(100, 105, 99, 104)], tf="H1", symbol="EURUSD")


def test_strength_exact_numeric_witness_uses_start_atr_not_current_atr():
    b = series()
    rec = relative_movement(b, T0 + 25 * 3600 + 1, "S")
    assert rec["1"]["denominator"] == 2
    assert rec["1"]["numerator"] == 4
    assert rec["1"]["value"] == 2
    assert rec["4"]["value"] == 2
    assert rec["1"]["T"] == iso_utc(T0 + 25 * 3600)
    assert rec["1"]["input_refs"][0]["seed_start_at"] == iso_utc(T0)
    assert rec["1"]["known_at"] == iso_utc(T0 + 25 * 3600 + 1)


def test_strength_exact_endpoint_missing_late_gap_and_partial_not_nearest_bar():
    b = series()
    cutoff = T0 + 25 * 3600 + 1
    assert relative_movement(b, cutoff - 1, "S")["1"]["value"] is None
    for defect in ("gap", "late", "partial"):
        broken = copy.deepcopy(b)
        if defect == "gap":
            broken.close_at[-3] -= 60
        elif defect == "late":
            broken.available_at[-3] = cutoff + 100
        else:
            broken.member_count, broken.expected_members = np.full(25, 12), 12
            broken.member_count[-3] = 11
        assert relative_movement(broken, cutoff, "S")["4"]["value"] is None
    assert relative_movement(b, cutoff + 3600, "S")["1"]["value"] is None


def test_strength_zero_return_zero_atr_and_warmup():
    b = bars(3600, T0, [(100, 101, 99, 100)] * 25, tf="H1")
    assert relative_movement(b, T0 + 25 * 3600 + 1, "S")["1"]["value"] == 0
    b = bars(3600, T0, [(100, 100, 100, 100)] * 25, tf="H1")
    assert relative_movement(b, T0 + 25 * 3600 + 1, "S")["1"]["reason"] == "ATR_START_UNUSABLE"
    b = bars(3600, T0, [(100, 101, 99, 100)] * 5, tf="H1")
    assert relative_movement(b, T0 + 5 * 3600 + 1, "S")["1"]["value"] is None


def test_strength_future_mutation_invariance_and_prefix_arrival():
    b = series()
    cutoff = T0 + 24 * 3600 + 1
    before = relative_movement(b, cutoff, "S")
    b.c[-1], b.h[-1] = 999, 1000
    assert relative_movement(b, cutoff, "S") == before
    b.available_at[0] = cutoff + 100
    assert relative_movement(b, cutoff, "S")["1"]["reason"] == "ATR_PREFIX_NOT_YET_KNOWN"


def overlay(base, quote, movement, native, T=None):
    return {"asset_metadata": asset_metadata({"calc_mode": "FOREX", "base_currency": base, "profit_currency": quote, "native_symbol": native}),
            "relative_movement": {str(h): {"value": movement, "quality": "OK" if movement is not None else "UNKNOWN",
                "T": T or iso_utc(T0 + 3600), "start": iso_utc(T0 + 3600 - h * 3600),
                "known_at": iso_utc(T0 + 3601), "input_refs": []} for h in (1, 4)}}


def test_currency_basket_equal_mean_signed_metadata_not_symbol_name():
    data = {"BROKER_A": overlay("EUR", "USD", 2, "EURUSD.r"), "BROKER_B": overlay("USD", "JPY", -1, "USDJPY.r")}
    result = build_currency_strength(data, list(data))
    assert result["EUR"]["1"]["comparable_value"] == 2
    assert result["USD"]["1"]["comparable_value"] == -1.5
    assert result["JPY"]["1"]["comparable_value"] == 1
    assert [result[c]["1"]["rank"] for c in ("EUR", "JPY", "USD")] == [1, 2, 3]
    assert result["USD"]["1"]["expected_constituents"] == ["BROKER_A", "BROKER_B"]


def test_currency_basket_partial_null_rank_duplicate_native_and_nonfx_excluded():
    data = {"A": overlay("EUR", "USD", 2, "EURUSD.r"), "B": overlay("USD", "JPY", None, "USDJPY.r")}
    data["DUP"] = copy.deepcopy(data["A"])
    data["XAU"] = {"asset_metadata": asset_metadata({"calc_mode": "FOREX", "base_currency": "XAU", "profit_currency": "USD"})}
    data["US100"] = {"asset_metadata": asset_metadata({"calc_mode": "CFDINDEX", "base_currency": "USD", "profit_currency": "USD"})}
    result = build_currency_strength(data, list(data))
    assert set(result) == {"EUR", "USD", "JPY"}
    usd = result["USD"]["1"]
    assert usd["count"] == 1 and usd["coverage"] == .5 and usd["mean_observed"] == -2
    assert usd["comparable_value"] is None and usd["rank"] is None and usd["missing_constituents"] == ["B"]
    assert result["EUR"]["1"]["count"] == 1


def test_unknown_universe_member_or_misaligned_endpoints_never_full_rank():
    data = {"A": overlay("EUR", "USD", 2, "EURUSD.r"), "B": overlay("USD", "JPY", 1, "USDJPY.r", iso_utc(T0 + 7200))}
    result = build_currency_strength(data, list(data))
    assert result["USD"]["1"]["comparable_value"] is None and result["EUR"]["1"]["rank"] is None
    data["C"] = {"asset_metadata": {"asset_class": "UNKNOWN_ASSET_CLASS"}}
    result = build_currency_strength(data, list(data))
    assert all(r["1"]["rank"] is None for r in result.values())
    assert all(r["1"]["comparable_value"] is None for r in result.values())
