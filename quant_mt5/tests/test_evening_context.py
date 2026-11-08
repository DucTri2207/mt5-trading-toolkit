"""Offline witnesses only: no MT5 terminal, external data, broker order or live claim."""
import copy
import json

import pytest

from quantmt5.data import DataVersionMismatch
from quantmt5.evening_context import (alignment, asset_metadata, build_evening_context, direction_context,
                                    exposure, price_reference, value_location, zone_distance)
from quantmt5.util import iso_utc
from tests.synth import T0, bars


def feature(name, value, tf="H1", available=T0):
    return {"name": name, "tf": tf, "value": value, "quality": "OK", "available_at": iso_utc(available), "provisional": False}


def market(p=.8, slope=.1, symbol="EURUSD"):
    return {"snapshot_id": "S", "symbol": symbol, "as_of": iso_utc(T0 + 3601),
            "price_reference": {"kind": "LAST_CLOSED_M5", "close": 103., "quality": "OK",
                                "bar_close_at": iso_utc(T0 + 3600), "available_at": iso_utc(T0 + 3601)},
            "features": [feature("h1_close_minus_ema50_over_atr", p), feature("h1_ema50_slope_over_atr", slope),
                         feature("atr14_wilder", 99., "H1"), feature("atr14_wilder", 2., "M5")],
            "asset_metadata": asset_metadata({"calc_mode": "FOREX", "base_currency": "EUR", "profit_currency": "USD"})}


def snapshot():
    return {"snapshot_id": "S", "as_of_utc": iso_utc(T0 + 3601), "universe": ["EURUSD"],
            "candidates": [{"candidate_id": "C", "setup": "A", "symbol": "EURUSD", "side": "LONG", "episode_id": "E",
                            "zone": {"U": 101., "D": 95.}, "delta": 1., "ready_at": iso_utc(T0),
                            "plan": {"entry": 102., "sl": 99., "tp": 108., "state": "FILLED_SIMULATED"},
                            "branch_eligibility": {"M0": True, "M1": False}, "entry_deadline_at": iso_utc(T0 + 100),
                            "plan_window": {"M0": "EXPIRED"}, "execution_status": "ORIGINAL"}],
            "episodes": [{"episode_id": "WATCH", "symbol": "EURUSD", "side": "SHORT", "D": 98., "U": 110., "delta": .5,
                          "breakout_available_at": iso_utc(T0), "expires_at": iso_utc(T0 + 5000), "state_at_as_of": "WATCHING_RETEST"}]}


@pytest.mark.parametrize("p,slope,want", [(.8, .1, "UP_BIAS"), (-.8, -.1, "DOWN_BIAS"),
    (.8, -.1, "MIXED_OR_FLAT"), (0, .1, "MIXED_OR_FLAT"), (None, .1, "UNKNOWN"), (True, .1, "UNKNOWN")])
def test_h1_numeric_labels(p, slope, want):
    assert direction_context(market(p, slope), T0 + 3601) == want


def test_h1_missing_late_provisional_and_quality_do_not_vote():
    for patch in ({"provisional": True}, {"available_at": iso_utc(T0 + 4000)}, {"quality": "UNKNOWN"}, {"value": float("nan")}):
        m = market()
        m["features"][0].update(patch)
        assert direction_context(m, T0 + 3601) == "UNKNOWN"
    assert alignment("UP_BIAS", "LONG") == "SUPPORTS"
    assert alignment("UP_BIAS", "SHORT") == "CONTRADICTS"
    assert alignment("MIXED_OR_FLAT", "LONG") == "NEUTRAL"
    assert alignment("DOWN_BIAS", None) == "UNKNOWN"


def test_distance_witness_boundaries_missing_atr_bool_and_invalid_zone():
    assert zone_distance(100, 102, 103, 2) == {"distance_price": 1., "distance_atr": .5, "relative_position": "ABOVE", "reason": None}
    for close in (100, 101, 102):
        assert zone_distance(100, 102, close, 2)["distance_price"] == 0
        assert zone_distance(100, 102, close, 2)["relative_position"] == "INSIDE"
    assert zone_distance(100, 102, 99, 2)["distance_atr"] == .5
    assert zone_distance(100, 102, 103, 0)["distance_atr"] is None
    assert zone_distance(102, 100, 103, 2)["distance_price"] is None
    assert zone_distance(100, 102, True, 2)["distance_price"] is None


def test_all_a_preserved_watch_plan_null_frozen_not_rolling_no_mutation():
    snap, m = snapshot(), market()
    m["features"].append(dict(feature("distance_close_to_h1_8bar_high_over_atr", 20., "M5"), level=140.))
    before = copy.deepcopy((snap, m))
    ctx = build_evening_context(snap, {"EURUSD": m})["EURUSD"]
    candidate, watch = ctx["scenarios"]
    assert candidate["plan"] == snap["candidates"][0]["plan"]
    assert candidate["baseline_status"] == {"M0": True, "M1": False}
    assert candidate["entry_deadline_at"] == iso_utc(T0 + 100)
    assert candidate["context_status"] == "SUPPORTS" and watch["context_status"] == "CONTRADICTS"
    assert candidate["frozen_zone"]["low"] == 100 and candidate["frozen_zone"]["high"] == 102
    assert candidate["frozen_zone"]["distance_atr"] == .5  # M5 ATR=2, not H1 ATR=99
    assert watch["plan"] is None and watch["candidate_ref"] is None
    assert watch["refuting_condition"]["level"] == 98.5
    assert not watch["opposite_scenario_creates_trade"]
    assert ctx["context_status"] == "UNKNOWN" and ctx["summary_basis"] == "H1_DIRECTION_ONLY"
    assert ctx["news_checked_by_system"] is False
    assert ctx["win_probability"] is None
    assert (snap, m) == before
    candidate["plan"]["entry"] = 999
    assert snap["candidates"][0]["plan"]["entry"] == 102


def test_missing_price_never_uses_fabio_quote_or_provisional():
    snap, m = snapshot(), market()
    del m["price_reference"]
    m["provisional_bars"] = {"M5": {"c": 123}}
    fr = {"snapshot_id": "S", "symbol": "EURUSD", "as_of": snap["as_of_utc"], "price_context": {"last_close": 103},
          "execution_quote": {"bid": 103, "ask": 104}, "state": {"F1": "UP"},
          "balance": {"val": 99, "vah": 102, "known_at": iso_utc(T0)}}
    ctx = build_evening_context(snap, {"EURUSD": m}, {"EURUSD": fr})["EURUSD"]
    assert ctx["value_location"] == "UNKNOWN"
    assert ctx["scenarios"][0]["frozen_zone"]["distance_price"] is None
    assert ctx["scenarios"][0]["reference_targets"] == []
    assert ctx["scenarios"][0]["plan"]["tp"] == 108


def test_balance_location_boundaries_unknown_and_reference_targets_not_tp():
    bal = {"val": 100, "vah": 102, "poc": 101, "known_at": iso_utc(T0), "volume_basis": "MT5_BAR_TICK_VOLUME_UNIFORM_PROXY"}
    assert value_location(102, bal, T0) == "INSIDE_REFERENCE_VALUE"
    assert value_location(103, bal, T0) == "ABOVE_REFERENCE_VALUE"
    assert value_location(99, bal, T0) == "BELOW_REFERENCE_VALUE"
    assert value_location(101, bal, T0 - 1) == "UNKNOWN"
    snap, m = snapshot(), market()
    m["features"].append(dict(feature("distance_close_to_prev_day_high_over_atr", 1.5, "M5"), level=106))
    fr = {"snapshot_id": "S", "symbol": "EURUSD", "as_of": snap["as_of_utc"], "balance": bal, "state": "UNKNOWN"}
    ctx = build_evening_context(snap, {"EURUSD": m}, {"EURUSD": fr})["EURUSD"]
    assert ctx["value_location"] == "ABOVE_REFERENCE_VALUE"
    targets = ctx["scenarios"][0]["reference_targets"]
    assert targets[0]["price"] == 106 and targets[0]["is_tp"] is False
    assert ctx["scenarios"][0]["plan"]["tp"] == 108


@pytest.mark.parametrize("field,value", [("snapshot_id", "OTHER"), ("symbol", "USDJPY"), ("as_of", iso_utc(T0 + 4000))])
def test_identity_mismatch_is_typed_integrity_error(field, value):
    m = market()
    m[field] = value
    with pytest.raises(DataVersionMismatch, match="MISMATCH"):
        build_evening_context(snapshot(), {"EURUSD": m})


def test_proxy_copy_no_local_aggression_no_fabio_veto_and_json_finite():
    snap = snapshot()
    fr = {"snapshot_id": "S", "symbol": "EURUSD", "as_of": snap["as_of_utc"], "decision": "SKIP",
          "flow": {"is_proxy": True, "status": "OK", "volume_basis": "TICK_DIRECTION_PROXY", "current_cvd": 0,
                   "latest_bar_delta": float("nan"), "segment_start_index": 50},
          "families": {"F1": {"decision": "SKIP", "variants": {"price_plus_local_aggression": {"decision": "DATA_UNAVAILABLE"}}}}}
    result = build_evening_context(snap, {"EURUSD": market()}, {"EURUSD": fr})
    assert result["EURUSD"]["flow"]["current_cvd"] == 0
    assert result["EURUSD"]["flow"]["latest_bar_delta"] is None
    assert result["EURUSD"]["scenarios"][0]["plan"] == snap["candidates"][0]["plan"]
    serialized = json.dumps(result, allow_nan=False)
    assert "price_plus_local_aggression" not in serialized


def test_metadata_not_symbol_slicing_and_exposure_sign_only():
    fx = asset_metadata({"calc_mode": "FOREX", "base_currency": "EUR", "profit_currency": "USD", "native_symbol": "EURUSD.r"})
    assert fx["asset_class"] == "FX" and fx["status"] == "OK"
    assert exposure(fx, "LONG")["legs"] == [{"currency": "EUR", "sign": 1}, {"currency": "USD", "sign": -1}]
    assert exposure(fx, "SHORT")["legs"] == [{"currency": "EUR", "sign": -1}, {"currency": "USD", "sign": 1}]
    assert asset_metadata({"calc_mode": "CFDINDEX", "base_currency": "USD", "profit_currency": "USD"})["asset_class"] == "INDEX"
    assert asset_metadata({"calc_mode": "FOREX", "base_currency": "XAU", "profit_currency": "USD"})["asset_class"] == "METAL"
    assert asset_metadata({"native_symbol": "EURUSD"})["asset_class"] == "UNKNOWN_ASSET_CLASS"


def test_closed_price_reference_and_arrival_hole_no_fallback():
    b = bars(300, T0, [(100, 102, 99, 101), (101, 105, 100, 104)])
    assert price_reference(b, T0 + 600, "S")["close"] == 101
    assert price_reference(b, T0 + 601, "S")["close"] == 104
    b.available_at[0] = T0 + 900
    assert price_reference(b, T0 + 601, "S")["close"] is None


def test_scenario_evidence_refs_known_time_and_future_subject_are_not_inferences():
    snap = snapshot()
    ctx = build_evening_context(snap, {"EURUSD": market()})["EURUSD"]
    candidate, watch = ctx["scenarios"]
    assert len(candidate["supporting_refs"]) == 2 and candidate["contradicting_refs"] == []
    assert len(watch["contradicting_refs"]) == 2 and watch["supporting_refs"] == []
    assert candidate["premise_refs"][0]["record_key"] == "C"
    assert candidate["frozen_zone"]["known_at"] == iso_utc(T0 + 3601)
    assert candidate["frozen_zone"]["source_known_at"] == iso_utc(T0)
    assert len(candidate["frozen_zone"]["input_refs"]) == 3
    assert candidate["frozen_zone"]["is_developing"] is False
    assert candidate["context_cutoff"] != candidate["baseline_decision_at"]
    snap["episodes"][0]["breakout_available_at"] = iso_utc(T0 + 6000)
    bad = build_evening_context(snap, {"EURUSD": market()})["EURUSD"]["scenarios"][1]
    assert bad["context_status"] == "UNKNOWN" and bad["frozen_zone"]["low"] is None


def test_context_lifecycle_is_not_direction_or_data_availability():
    snap = snapshot()
    for state, want in (("UNKNOWN", "COMPLETE"), ("ERROR", "PARTIAL_FAILED"), ("TIMEOUT", "PARTIAL_FAILED"), ("UNSUPPORTED", "COMPLETE")):
        ctx = build_evening_context(snap, {"EURUSD": {"status": "UNAVAILABLE", "item_state": state}})["EURUSD"]
        assert ctx["context_state"] == want and ctx["context_status"] == "UNKNOWN"
        assert len(ctx["scenarios"]) == 2
    ctx = build_evening_context(snap, {"EURUSD": market()}, {"EURUSD": {"status": "ERROR", "reason": "fixture"}})["EURUSD"]
    assert ctx["context_state"] == "PARTIAL_FAILED" and ctx["scenarios"][0]["context_status"] == "SUPPORTS"


def test_unconfirmed_or_future_divergence_and_external_flow_are_not_reused():
    snap = snapshot()
    fr = {"snapshot_id": "S", "symbol": "EURUSD", "as_of": snap["as_of_utc"],
          "divergence_context": {"status": "OK", "pivots_confirmed_only": True,
                                 "high": {"class": "regular_bearish", "pivot_known_at": iso_utc(T0 + 4000), "cvd": [1, 2]}}}
    ctx = build_evening_context(snap, {"EURUSD": market()}, {"EURUSD": fr})["EURUSD"]
    assert ctx["divergence_context"]["high"]["reason"] == "PIVOT_NOT_KNOWN_AT_CUTOFF"
    fr["route"], fr["flow"] = "FTMO_EXTERNAL_FLOW", {"current_cvd": 999, "status": "USABLE"}
    ctx = build_evening_context(snap, {"EURUSD": market()}, {"EURUSD": fr})["EURUSD"]
    assert ctx["flow"]["status"] == "UNSUPPORTED" and "current_cvd" not in ctx["flow"]
    assert ctx["divergence_context"] is None


def test_build_market_context_uses_loaded_closed_bars_and_shared_cache(monkeypatch):
    import quantmt5.context as context
    from tests.synth import symbol_data
    sd = symbol_data([(100, 101, 99, 100)] * 360)
    snap = {"snapshot_id": "S", "as_of_utc": iso_utc(T0 + 360 * 300 + 1), "universe": ["TEST"], "symbols": {"TEST": {}}}
    monkeypatch.setattr(context, "load_snapshot", lambda _: snap)
    monkeypatch.setattr(context, "snapshot_pins", lambda *_: {})
    monkeypatch.setattr(context, "load_symbol", lambda *_, **__: sd)
    result = context.build_market_context("S", "TEST", groups=["ema", "er"])
    assert result["price_reference"]["close"] == 100
    assert result["price_reference"]["bar_close_at"] == iso_utc(T0 + 360 * 300)
    assert result["relative_movement"]["1"]["value"] == 0
    assert "atr14" in sd.cache_h1._c and "ema50" in sd.cache_h1._c
    assert result["reference_windows"][0]["definition_basis"] == "PROJECT_REFERENCE_WINDOW"
