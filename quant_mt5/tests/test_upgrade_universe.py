"""Expanded universe must degrade by symbol, never invent fees or lose unavailable requests."""
import json

import pytest

from quantmt5.config import cost_profiles, strategy, symbol_profiles
from quantmt5.execution import EconomicsUnavailable, economics_status, make_params
from quantmt5.source_bundle import _chunkset_hash, build_source_bundle, map_profile, tick_version
from quantmt5.universe import EXTENDED12, MAIN8, validate_map
from quantmt5.util import hash_obj, iso_utc
from synth import PROF, T0, bars, flat_m5, symbol_data


def test_evening_presets_and_explicit_suffix_mapping():
    assert MAIN8 == ("XAUUSD", "EURUSD", "USDJPY", "GBPUSD", "USDCAD", "USDCHF", "AUDUSD", "NZDUSD")
    assert EXTENDED12 == MAIN8 + ("EURJPY", "GBPJPY", "EURGBP", "AUDJPY")
    assert validate_map({"eurusd": "EURUSD.m", "USDCAD": "USDCAD"}) == {"EURUSD": "EURUSD.m", "USDCAD": "USDCAD"}


@pytest.mark.parametrize("mapping,reason", [
    ([("EURUSD", "EURUSD"), ("eurusd", "EURUSD.m")], "DUPLICATE_CANONICAL"),
    ({"EURUSD": "EURUSD", "GBPUSD": "EURUSD"}, "DUPLICATE_NATIVE"),
    ({"EURUSD": "EURUSD*"}, "NATIVE_MUST_BE_EXACT"),
    ({"USOIL": "USOIL.cash"}, "OIL_EXCLUDED"),
    ({"XAUUSD": "XBRUSD.m"}, "OIL_EXCLUDED"),
])
def test_unsafe_or_ambiguous_mapping_rejected(mapping, reason):
    with pytest.raises(ValueError, match=reason):
        validate_map(mapping)


def test_baseline_execution_parameters_unchanged():
    cost = cost_profiles()["scenarios"]["BASE"]
    profiles = symbol_profiles()["symbols"]
    for symbol, price in (("XAUUSD", 2700), ("EURUSD", 1.1), ("USDJPY", 150)):
        prof = profiles[symbol]
        p = make_params(symbol, prof, cost, "BASE", "BASE", 5, strategy()["common"], price_hint=price)
        assert p.slip_price == float(cost["slippage_points_per_side"][symbol]) * float(prof["point"])
        commission = None
        if prof.get("contract_size"):
            commission = float(cost["commission_usd_per_lot_round_trip"]) / float(prof["contract_size"])
            if prof.get("base_currency") == "USD":
                commission *= price
        assert p.commission_price_rt == commission
        assert economics_status(symbol, prof, cost)["status"] == ("ASSUMED" if prof.get("contract_size") else "UNKNOWN")


def test_missing_cost_and_cross_conversion_are_unknown_not_zero():
    base = cost_profiles()["scenarios"]["BASE"]
    e = economics_status("GBPUSD", dict(PROF, base_currency="GBP"), base)
    assert e["status"] == "UNKNOWN"
    assert any("slippage_points_per_side" in reason for reason in e["reasons"])
    with pytest.raises(EconomicsUnavailable, match="ECONOMICS_UNKNOWN"):
        make_params("GBPUSD", dict(PROF), base, "BASE", "BASE", 5, strategy()["common"])
    cross_cost = dict(base, spread_floor_points={"EURJPY": 5}, slippage_points_per_side={"EURJPY": 1})
    cross_prof = dict(PROF, base_currency="EUR", profit_currency="JPY", contract_size=100000)
    assert economics_status("EURJPY", cross_prof, cross_cost)["reasons"] == [
        "COMMISSION_CONVERSION_UNKNOWN:NO_SAME_ASOF_OBSERVED_RATE"]
    p = make_params("EURJPY", cross_prof, cross_cost, "BASE", "BASE", 5, strategy()["common"], price_hint=160)
    assert p.commission_price_rt is None


@pytest.mark.parametrize("bad", [None, -1, float("nan"), float("inf"), True])
def test_invalid_cost_is_never_executable(bad):
    cost = dict(cost_profiles()["scenarios"]["BASE"], slippage_points_per_side={"XAUUSD": bad})
    assert economics_status("XAUUSD", dict(PROF), cost)["status"] == "UNKNOWN"
    with pytest.raises(EconomicsUnavailable):
        make_params("XAUUSD", dict(PROF), cost, "BASE", "BASE", 5, strategy()["common"])


def _mock_snapshot_inputs(monkeypatch, universe, missing=None):
    import quantmt5.config as config
    import quantmt5.snapshot as snapshot
    reg = {"source_id": "fixture", "symbols": {
        s: {"timeframes": {}, "exposure": "SYNTHETIC", "time_basis": {}} for s in universe},
        "symbol_map": {s: s + ".m" for s in universe},
        "symbol_issues": {missing: [{"reason": "NOT_COLLECTED"}]} if missing else {}}
    monkeypatch.setattr(snapshot, "load_registry", lambda: reg)
    monkeypatch.setattr(snapshot, "dataset_manifest", lambda r: {})
    monkeypatch.setattr(config, "bundle_identity", lambda: {"kind": "DEFAULT_REPO_CONFIG"})
    m1 = bars(60, T0, [(100, 100.5, 99.5, 100)] * 40, tf="M1")

    def load(symbol, *args, **kwargs):
        if symbol == missing:
            raise config.MetadataError("METADATA_MISSING:" + symbol)
        sd = symbol_data(flat_m5(8), m1=m1)
        sd.symbol = symbol
        return sd

    def detect(sd, cfg):
        close = T0 + 2400
        return {"episodes": [], "catalog_meta": {}, "candidates": [{
            "candidate_id": sd.symbol + "_C", "revision_id": "REV", "symbol": sd.symbol, "setup": "B", "side": "LONG",
            "ready_ts": close + 1, "ready_at": iso_utc(close + 1), "signal_close_ts": close,
            "entry_deadline_ts": close + 90, "entry_deadline_at": iso_utc(close + 90),
            "signal_bar": {"open_at": iso_utc(close - 300), "close_at": iso_utc(close), "c": 100, "l": 99.5, "h": 100.5},
            "eligibility": {"P0": "ELIGIBLE"}, "gates": {"P0": {"result": "ELIGIBLE"}},
            "atr_frozen": 1, "buffer": 0.05}]}

    monkeypatch.setattr(snapshot, "load_symbol", load)
    monkeypatch.setattr(snapshot, "detect_all", detect)
    return snapshot


def test_all_twelve_symbols_reported_when_one_metadata_missing(monkeypatch):
    snapshot = _mock_snapshot_inputs(monkeypatch, EXTENDED12, missing="GBPJPY")
    snap = snapshot.make_snapshot(T0 + 2401, list(EXTENDED12), write=False)
    assert set(snap["symbols"]) == set(EXTENDED12)
    assert snap["symbols"]["GBPJPY"]["status"] == "ERROR"
    assert snap["symbols"]["GBPJPY"]["collection_issues"] == [{"reason": "NOT_COLLECTED"}]
    gbp = snap["symbols"]["GBPUSD"]
    assert gbp["status"] == "OK" and gbp["economics"]["status"] == "UNKNOWN"
    assert gbp["data"]["M5"]["rows_available"] == 8
    candidate = next(c for c in snap["candidates"] if c["symbol"] == "GBPUSD")
    assert candidate["plan"]["state"] == "EXECUTION_UNKNOWN_COST"
    assert candidate["plan"]["context_only"]
    assert "entry" not in candidate["plan"]
    assert snapshot.scan(snap)["status"] == "PARTIAL"


def test_empty_m5_is_per_symbol_error_not_whole_scan(monkeypatch):
    snapshot = _mock_snapshot_inputs(monkeypatch, MAIN8)
    load = snapshot.load_symbol

    def empty_one(symbol, *args, **kwargs):
        sd = load(symbol, *args, **kwargs)
        if symbol == "NZDUSD":
            sd.m5 = sd.m5.slice(0, 0)
        return sd

    monkeypatch.setattr(snapshot, "load_symbol", empty_one)
    snap = snapshot.make_snapshot(T0 + 2401, list(MAIN8), write=False)
    assert len(snap["symbols"]) == 8
    assert snap["symbols"]["NZDUSD"]["reason"] == "HISTORY_INSUFFICIENT:M5_EMPTY"
    assert snap["symbols"]["GBPUSD"]["status"] == "OK"


def _collect_fixture(tmp_path):
    chunks = tmp_path / "bars"
    chunks.mkdir()
    (chunks / "checkpoint.json").write_text(json.dumps({"chunks": [], "windows": {}}), encoding="utf-8")
    native = {"trade_tick_size": 0.00001, "point": 0.00001, "digits": 5, "trade_contract_size": 100000,
              "currency_profit": "USD", "currency_base": "GBP", "chart_mode": 0}
    return {"status": "PARTIAL", "manifest_path": str(tmp_path / "manifest.json"),
            "manifest": {"identity_rechecked_after_batch": True, "provider_kind": "SYNTHETIC_FIXTURE", "source_id": "fixture",
                         "identity": {"provider_kind": "SYNTHETIC_FIXTURE", "account_currency": "USD"},
                         "symbols": {"GBPUSD.m": {"status": "OK", "profile": native,
                                                  "profile_check": {"status": "OK", "invalid": []}, "bars": {}},
                                     "EURJPY.m": {"status": "ERROR", "reason": "NATIVE_SYMBOL_NOT_FOUND"}}},
            "registry_fragment": {"GBPUSD.m": {"provider_kind": "SYNTHETIC_FIXTURE", "time_basis": {"contract": "API_UTC_CONTRACT"},
                                                "timeframes": {"M5": {"chunk_dir": str(chunks)}}, "exposure": "SYNTHETIC"}}}


def test_bundle_retains_requested_missing_symbols_and_does_not_copy_profiles(tmp_path):
    collect = _collect_fixture(tmp_path)
    mapping = {"GBPUSD": "GBPUSD.m", "EURJPY": "EURJPY.m"}
    result = build_source_bundle(collect, tmp_path / "bundles", mapping)
    from pathlib import Path
    bundle = Path(result["config_dir"])
    registry = json.loads((bundle / "datasets.json").read_text(encoding="utf-8"))
    profiles = json.loads((bundle / "symbol_profiles.json").read_text(encoding="utf-8"))["symbols"]
    assert registry["requested_symbols"] == ["EURJPY", "GBPUSD"]
    assert registry["symbol_map"] == mapping
    assert registry["symbol_issues"]["EURJPY"][0]["reason"] == "NATIVE_SYMBOL_NOT_FOUND"
    assert profiles["GBPUSD"]["session"] is None
    assert profiles["GBPUSD"]["session_status"] == "UNKNOWN_NOT_OBSERVED"
    assert profiles["GBPUSD"]["volume_min"] is None
    assert "GBPUSD" not in json.loads((bundle / "cost_profiles.json").read_text(encoding="utf-8"))["scenarios"]["BASE"]["spread_floor_points"]


def test_missing_profile_is_explicit_not_borrowed():
    p = map_profile("GBPUSD.m", {}, "SYNTHETIC_FIXTURE", None)
    assert p["trade_tick_size"] is None
    assert p["metadata_status"] == "UNKNOWN_NATIVE_PROFILE_MISSING"
    assert p["session"] is None


def test_missing_tick_checkpoint_keeps_bar_context_publishable(tmp_path):
    from pathlib import Path
    collect = _collect_fixture(tmp_path)
    collect["registry_fragment"]["GBPUSD.m"]["ticks"] = {"format": "collector_ticks_v1", "chunk_dir": str(tmp_path / "missing_ticks")}
    result = build_source_bundle(collect, tmp_path / "bundles", {"GBPUSD": "GBPUSD.m"})
    registry = json.loads((Path(result["config_dir"]) / "datasets.json").read_text(encoding="utf-8"))
    assert registry["symbols"]["GBPUSD"]["ticks"] is None
    assert registry["symbols"]["GBPUSD"]["ticks_status"] == "NOT_COLLECTED"
    assert registry["symbols"]["GBPUSD"]["timeframes"]["M5"]


def test_tick_identity_includes_generation_without_changing_legacy_identity(tmp_path, monkeypatch):
    import quantmt5.retention as retention
    monkeypatch.setattr(retention, "assert_tick_available", lambda p: None)
    checkpoint = tmp_path / "checkpoint.json"
    ck = {"chunks": [{"file": "chunk.npz", "sha256": "abc", "first_ms": 1, "last_ms": 2}], "windows": {}}
    checkpoint.write_text(json.dumps(ck), encoding="utf-8")
    reg = {"symbols": {"XAUUSD": {"ticks": {"format": "npy", "chunk_dir": str(tmp_path)}}}}
    legacy = tick_version(reg, "XAUUSD")
    assert legacy["content_hash"] == hash_obj({"chunks": legacy["chunks"], "windows": {}})
    identities, build_hashes = [], []
    for generation in ("TG_1", "TG_2"):
        ck["tick_generation_id"] = generation
        checkpoint.write_text(json.dumps(ck), encoding="utf-8")
        pin = tick_version(reg, "XAUUSD")
        identities.append(pin["content_hash"])
        build_hashes.append(_chunkset_hash(tmp_path))
        assert pin["tick_generation_id"] == generation
    assert identities[0] != identities[1]
    assert build_hashes[0] != build_hashes[1]
    reg["symbols"]["XAUUSD"]["ticks"]["tick_generation_id"] = "TG_1"
    with pytest.raises(ValueError, match="TICK_GENERATION_CHANGED_AFTER_BUNDLE"):
        tick_version(reg, "XAUUSD")


def test_managed_bundle_and_snapshot_register_generation_consumers(tmp_path, monkeypatch):
    import quantmt5.config as config
    from pathlib import Path
    from quantmt5.retention import ensure_tick_generation, init_retention
    session = tmp_path / "session"
    session.mkdir()
    (session / "session.json").write_text(json.dumps({"session_id": "fixture"}), encoding="utf-8")
    init_retention(session, "fixture")
    tick_dir = session / "data" / "raw" / "fixture" / "GBPUSD.m" / "ticks"
    metadata = ensure_tick_generation(tick_dir)
    tick_dir.mkdir(parents=True)
    (tick_dir / "checkpoint.json").write_text(json.dumps({"chunks": [], "windows": {}, **metadata}), encoding="utf-8")
    collect = _collect_fixture(tmp_path)
    collect["registry_fragment"]["GBPUSD.m"]["ticks"] = {"format": "npy", "chunk_dir": str(tick_dir)}
    result = build_source_bundle(collect, session / "data" / "bundles", {"GBPUSD": "GBPUSD.m"})
    registry = json.loads((Path(result["config_dir"]) / "datasets.json").read_text(encoding="utf-8"))
    assert registry["symbols"]["GBPUSD"]["ticks"]["tick_generation_id"] == metadata["tick_generation_id"]
    snapshot = _mock_snapshot_inputs(monkeypatch, ["GBPUSD"])
    registry["symbols"]["GBPUSD"]["timeframes"] = {}
    monkeypatch.setattr(snapshot, "load_registry", lambda: registry)
    monkeypatch.setattr(snapshot, "STORE_DIR", session / "data" / "store")
    monkeypatch.setattr(config, "bundle_identity", lambda: {"kind": "SOURCE_BUNDLE", **result})
    snap = snapshot.make_snapshot(T0 + 2401, ["GBPUSD"], write=True)
    assert snap["tick_versions"]["GBPUSD"]["tick_generation_id"] == metadata["tick_generation_id"]
    refs = json.loads((session / "data" / "retention" / "consumers.json").read_text(encoding="utf-8"))["references"]
    assert {r["kind"] for r in refs.values()} == {"bundle", "snapshot"}
    assert all(not r["outside_session"] for r in refs.values())
