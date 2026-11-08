"""Small hand-calculated Fabio Bid/Ask oracles; synthetic software checks, not evidence of trading edge."""
import copy

import numpy as np
import pytest

from quantmt5 import fabio, fabio_replay as replay
from quantmt5.execution import TickQuotes
from quantmt5.util import hash_obj, iso_utc, sha256_file, stable_id
from synth import T0, ticks


def plan(side="LONG", **changes):
    value = {"side": side, "known_at": iso_utc(T0), "expires_at": iso_utc(T0 + 600), "chart_basis": "BID",
             "sl_chart": 98.0 if side == "LONG" else 103.0, "target_chart": 104.0 if side == "LONG" else 94.0,
             "tick_size": .01, "trigger_close": 100.0, "atr_frozen": 2.0,
             "source_fingerprint": hash_obj({"source_id": "SRC", "symbol": "TEST", "chart_basis": "BID"})}
    value.update(changes)
    return value


def run(rows, side="LONG", *, covered=None, available=None, p=None, **kwargs):
    quotes = TickQuotes(ticks([(T0 + t, b, a) for t, b, a in rows]),
                        None if available is None else np.array([(T0 + t) * 1000 for t in available]))
    return replay.replay_plan(p or plan(side), quotes, covered if covered is not None else [(T0, T0 + 4000)], **kwargs)


def test_long_uses_ask_entry_bid_exit_frozen_target_and_does_not_charge_spread_twice():
    result = run([(0, 100, 100.2), (10, 104, 104.2)], commission_price_rt=.1, slippage_price=.05)
    assert result["status"] == "EXITED" and result["reason"] == "TP"
    assert result["entry"] == pytest.approx(100.25)
    assert result["sl"] == 98 and result["target"] == 104
    assert result["primary"]["gross_price"] == pytest.approx(3.75)
    assert result["net_price"] == pytest.approx(3.65)
    assert result["net_R"] == pytest.approx(3.65 / 2.35)
    assert result["scenario"]["cost_status"] == "ASSUMED"


def test_short_uses_bid_entry_ask_exit_and_frozen_entry_spread_offset():
    result = run([(0, 100, 100.2), (10, 94, 94.4), (20, 94, 94.2)], side="SHORT",
                 commission_price_rt=.1, slippage_price=.05)
    assert result["status"] == "EXITED" and result["primary"]["exit_at"] == iso_utc(T0 + 20)
    assert result["entry"] == pytest.approx(99.95)
    assert result["sl"] == pytest.approx(103.2) and result["target"] == pytest.approx(94.2)
    assert result["net_price"] == pytest.approx(5.65)


def test_stop_gap_can_lose_more_than_one_risk_budget():
    result = run([(0, 100, 100.2), (10, 96, 96.2)], commission_price_rt=.1, slippage_price=.05)
    assert result["reason"] == "SL_GAP"
    assert result["primary"]["exit_price"] == pytest.approx(95.95)
    assert result["net_R"] < -1


@pytest.mark.parametrize("costs", [{}, {"commission_price_rt": 0}, {"slippage_price": 0}])
def test_missing_costs_keep_quote_diagnostic_but_net_unknown(costs):
    result = run([(0, 100, 100.2), (10, 104, 104.2)], **costs)
    assert result["status"] == "EXITED"
    assert result["primary"]["gross_price"] == pytest.approx(3.8)
    assert result["net_price"] is None and result["net_R"] is None
    assert result["scenario"]["cost_status"] == "UNKNOWN"


def test_explicit_zero_costs_are_assumed_and_preserved():
    result = run([(0, 100, 100.2), (10, 104, 104.2)], commission_price_rt=0, slippage_price=0)
    assert result["net_price"] == pytest.approx(3.8)
    assert result["scenario"]["cost_status"] == "ASSUMED"


def test_first_quote_guard_never_waits_for_a_better_quote():
    result = run([(0, 103, 103.2), (1, 100, 100.2), (10, 104, 104.2)])
    assert result["status"] == "SKIPPED" and result["reason"] == "ENTRY_DRIFT_EXCEEDS_ONE_ATR"
    assert "fill_at" not in result


def test_entry_deadline_is_original_event_expiry_and_not_baseline_90_seconds():
    result = run([(200, 100, 100.2), (210, 104, 104.2)], latency_s=200)
    assert result["status"] == "EXITED" and result["fill_at"] == iso_utc(T0 + 200)
    assert run([(600, 100, 100.2)])["status"] == "EXPIRED"
    assert run([(0, 100, 100.2)], latency_s=600)["status"] == "EXPIRED"


def test_known_entry_coverage_gap_is_unresolved_even_with_later_winner():
    result = run([(200, 100, 100.2), (210, 104, 104.2)], covered=[(T0, T0 + 100), (T0 + 190, T0 + 4000)])
    assert result["status"] == "UNRESOLVED"
    assert result["reason"] == "ENTRY_COVERAGE_GAP_BEFORE_FIRST_QUOTE"


def test_missing_exit_coverage_censors_and_does_not_skip_to_later_target():
    result = run([(0, 100, 100.2), (210, 104, 104.2)], covered=[(T0, T0 + 100), (T0 + 190, T0 + 4000)])
    assert result["status"] == "CENSORED" and result["net_R"] is None
    assert result["primary"]["gross_R"] is None


def test_no_quote_full_window_is_expired_partial_window_is_unresolved():
    assert run([])["status"] == "EXPIRED"
    assert run([], covered=[(T0, T0 + 100)])["status"] == "UNRESOLVED"


def test_missing_exit_side_censors_instead_of_counting_win():
    result = run([(0, 100, 100.2), (10, float("nan"), 101), (20, 104, 104.2)])
    assert result["status"] == "CENSORED"
    assert result["reason"] == "EXIT_UNRESOLVED_QUOTE_SIDE_MISSING"


def test_time_exit_uses_declared_30_minutes_and_price_side():
    result = run([(0, 100, 100.2), (1800, 101, 101.2)], commission_price_rt=0, slippage_price=0)
    assert result["reason"] == "TIME_EXIT"
    assert result["primary"]["exit_at"] == iso_utc(T0 + 1800)
    assert result["primary"]["exit_price"] == 101


def test_time_exit_without_following_quote_is_censored():
    result = run([(0, 100, 100.2), (1799, 101, 101.2)])
    assert result["status"] == "CENSORED" and result["primary"]["gross_price"] is None


def test_pre_entry_stop_is_skipped_with_latency():
    result = run([(1, 97, 97.2), (20, 100, 100.2), (40, 104, 104.2)], latency_s=20)
    assert result["status"] == "SKIPPED" and result["reason"] == "SL_TOUCHED_BEFORE_ENTRY"


def test_delayed_pre_entry_event_cannot_certify_invalidation_path():
    result = run([(1, 97, 97.2), (20, 100, 100.2)], available=[40, 20], latency_s=20)
    assert result["status"] == "UNRESOLVED" and result["reason"] == "PRE_ENTRY_ARRIVAL_INCOMPLETE"


def test_same_millisecond_events_before_fill_are_not_replayed_as_exit():
    result = run([(0, 97, 97.2), (0, 100, 100.2), (1, 104, 104.2)], available=[2, 0, 1])
    assert result["status"] == "UNRESOLVED" and result["reason"] == "PRE_ENTRY_ARRIVAL_INCOMPLETE"
    assert result["entry_quote"]["seq"] == 1


def test_same_millisecond_event_after_fill_can_exit():
    result = run([(0, 100, 100.2), (0, 104, 104.2)])
    assert result["status"] == "EXITED" and result["reason"] == "TP"
    assert result["primary"]["exit_quote_seq"] == 1


@pytest.mark.parametrize("event", [(10, 104, 103), (1800, 101, 100)])
def test_crossed_bid_ask_path_censors_including_time_exit(event):
    result = run([(0, 100, 100.2), event])
    assert result["status"] == "CENSORED"


@pytest.mark.parametrize("latency,first_at", [(10, 10), (0, 10)])
def test_invalidation_known_by_first_quote_prevents_entry(latency, first_at):
    result = run([(first_at, 100, 100.2), (20, 104, 104.2)], latency_s=latency,
                 p=plan(invalidated_at=iso_utc(T0 + 10)))
    assert result["status"] == "SKIPPED" and result["reason"] == "PLAN_INVALIDATED_BEFORE_ENTRY"


def test_invalidation_after_fill_does_not_rewrite_historical_entry():
    result = run([(0, 100, 100.2), (20, 104, 104.2)], p=plan(invalidated_at=iso_utc(T0 + 10)))
    assert result["status"] == "EXITED"


@pytest.mark.parametrize("costs", [{"latency_s": -1}, {"commission_price_rt": True}, {"slippage_price": float("nan")}, {"max_hold_s": 0}])
def test_invalid_scenarios_rejected(costs):
    with pytest.raises(ValueError, match="FABIO_REPLAY_INVALID"):
        run([(0, 100, 100.2)], **costs)


@pytest.mark.parametrize("field,value", [("sl_chart", -1), ("tick_size", 0), ("atr_frozen", float("nan")), ("trigger_close", True)])
def test_invalid_plan_numbers_rejected(field, value):
    with pytest.raises(ValueError, match="FABIO_REPLAY_INVALID"):
        run([(0, 100, 100.2)], p=plan(**{field: value}))


def test_missing_target_and_unsupported_chart_basis_remain_unresolved():
    assert run([(0, 100, 100.2)], p=plan(target_chart=None))["reason"] == "TARGET_UNKNOWN"
    assert run([(0, 100, 100.2)], p=plan(chart_basis="LAST"))["reason"] == "CHART_BASIS_NOT_BID"


def artifact():
    p = plan(schema="fabio_plan_v1", policy=fabio.SCALP_POLICY, spec_hash=fabio.SCALP_SPEC_HASH,
             source_id="SRC", symbol="TEST", family="F1", opportunity_id="FOP_TEST", trigger_id="FTRIG_TEST")
    p["plan_id"] = stable_id("FPLAN", p)
    return {"schema": "fabio_analysis_v1", "policy": fabio.SCALP_POLICY, "spec_hash": fabio.SCALP_SPEC_HASH,
            "analysis_id": "FAB_TEST", "snapshot_id": "SNAP0", "source_id": "SRC", "symbol": "TEST", "chart_basis": "BID",
            "source_fingerprint": p["source_fingerprint"], "as_of": iso_utc(T0),
            "families": {"F1": {"side": "LONG", "opportunity_id": "FOP_TEST", "revision_id": "FREV_TEST",
                                  "trigger_id": "FTRIG_TEST", "research_plan": p}}}


def pinned_snapshots(tmp_path, monkeypatch):
    from quantmt5 import snapshot
    array = np.array([(int(T0 * 1000), 100., 100.2), (int((T0 + 10) * 1000), 104., 104.2)],
                     dtype=[("time_msc", "<i8"), ("bid", "<f8"), ("ask", "<f8")])
    path = tmp_path / "ticks.npz"
    np.savez(path, ticks=array)
    pin = {"chunk_dir": str(tmp_path), "chunks": [{"file": path.name, "sha256": sha256_file(path)}],
           "clock_profile": "RAW_IS_UTC", "content_hash": "PIN", "window_states": {f"{T0}_{T0 + 4000}": "OK"}}
    source = {"snapshot_id": "SNAP0", "as_of_utc": iso_utc(T0), "source_id": "SRC", "universe": ["TEST"], "config_hash": "CFG"}
    outcome = {**source, "snapshot_id": "SNAP1", "as_of_utc": iso_utc(T0 + 30),
               "config_bundle": {"source_id": "SRC", "provider_kind": "SYNTHETIC_FIXTURE"}, "tick_versions": {"TEST": pin}}
    snapshots = {"SNAP0": source, "SNAP1": outcome}
    monkeypatch.setattr(snapshot, "load_snapshot", lambda sid: copy.deepcopy(snapshots[sid]))
    monkeypatch.setattr(replay, "STORE_DIR", tmp_path / "store")
    return snapshots, path


def test_artifact_uses_explicit_later_snapshot_and_writes_deterministic_separate_ledger(tmp_path, monkeypatch):
    pinned_snapshots(tmp_path, monkeypatch)
    result = replay.replay_artifact(artifact(), "F1", "SNAP1", commission_price_rt=0, slippage_price=0)
    again = replay.replay_artifact(artifact(), "F1", "SNAP1", commission_price_rt=0, slippage_price=0)
    assert result == again and result["status"] == "EXITED"
    assert "fabio_replay" in result["artifact_path"] and "candidate_id" not in result
    assert result["opportunity_id"] == "FOP_TEST"


@pytest.mark.parametrize("field", ["schema", "policy", "spec_hash", "symbol", "family", "opportunity_id", "trigger_id"])
def test_mixed_plan_identity_is_rejected(tmp_path, monkeypatch, field):
    pinned_snapshots(tmp_path, monkeypatch)
    a = artifact()
    a["families"]["F1"]["research_plan"][field] = "OTHER"
    with pytest.raises(ValueError, match="PLAN_IDENTITY_MISMATCH"):
        replay.replay_artifact(a, "F1", "SNAP1", store=False)


def test_changed_frozen_target_is_rejected(tmp_path, monkeypatch):
    pinned_snapshots(tmp_path, monkeypatch)
    a = artifact()
    a["families"]["F1"]["research_plan"]["target_chart"] += 1
    with pytest.raises(ValueError, match="PLAN_HASH_MISMATCH"):
        replay.replay_artifact(a, "F1", "SNAP1", store=False)


def test_changed_invalidation_must_match_owning_family(tmp_path, monkeypatch):
    pinned_snapshots(tmp_path, monkeypatch)
    a = artifact()
    a["families"]["F1"]["research_plan"]["invalidated_at"] = iso_utc(T0 - 1)
    with pytest.raises(ValueError, match="INVALIDATION_MISMATCH"):
        replay.replay_artifact(a, "F1", "SNAP1", store=False)


def test_missing_same_snapshot_outcome_is_unresolved_not_future_peek(tmp_path, monkeypatch):
    pinned_snapshots(tmp_path, monkeypatch)
    result = replay.replay_artifact(artifact(), "F1", store=False)
    assert result["status"] == "UNRESOLVED" and result["reason"] == "PINNED_TICKS_MISSING"


def test_source_mismatch_rejected_before_using_outcome(tmp_path, monkeypatch):
    snapshots, _ = pinned_snapshots(tmp_path, monkeypatch)
    snapshots["SNAP1"]["config_bundle"]["source_id"] = "OTHER"
    with pytest.raises(ValueError, match="SNAPSHOT_SOURCE_MISMATCH"):
        replay.replay_artifact(artifact(), "F1", "SNAP1", store=False)


@pytest.mark.parametrize("field,value,reason", [("config_hash", "OTHER", "CONFIG_MISMATCH"),
                                               ("time_basis", {"TEST": "OTHER"}, "CLOCK_MISMATCH"),
                                               ("as_of_utc", iso_utc(T0 - 10), "OUTCOME_PRECEDES")])
def test_outcome_metadata_mismatch_rejected(tmp_path, monkeypatch, field, value, reason):
    snapshots, _ = pinned_snapshots(tmp_path, monkeypatch)
    snapshots["SNAP1"][field] = value
    with pytest.raises(ValueError, match=reason):
        replay.replay_artifact(artifact(), "F1", "SNAP1", store=False)


def test_missing_config_or_mismatched_analysis_config_is_rejected(tmp_path, monkeypatch):
    snapshots, _ = pinned_snapshots(tmp_path, monkeypatch)
    changed = artifact(); changed["inputs"] = {"hashes": {"config_hash": "OTHER"}}
    with pytest.raises(ValueError, match="ANALYSIS_CONFIG_MISMATCH"):
        replay.replay_artifact(changed, "F1", "SNAP1", store=False)
    snapshots["SNAP0"].pop("config_hash")
    snapshots["SNAP1"].pop("config_hash")
    with pytest.raises(ValueError, match="SNAPSHOT_CONFIG_MISMATCH"):
        replay.replay_artifact(artifact(), "F1", "SNAP1", store=False)


def test_tampered_tick_pin_fails_even_when_coverage_missing(tmp_path, monkeypatch):
    from quantmt5.data import DataVersionMismatch
    snapshots, path = pinned_snapshots(tmp_path, monkeypatch)
    snapshots["SNAP1"]["tick_versions"]["TEST"]["window_states"] = {}
    path.write_bytes(b"changed")
    with pytest.raises(DataVersionMismatch, match="TICK_CHUNK_MISSING_OR_CHANGED"):
        replay.replay_artifact(artifact(), "F1", "SNAP1", store=False)


def test_legacy_policy_rejected_and_no_plan_is_logged_as_skipped(tmp_path, monkeypatch):
    pinned_snapshots(tmp_path, monkeypatch)
    old = artifact(); old["policy"] = "legacy"
    with pytest.raises(ValueError, match="SPEC_MISMATCH"):
        replay.replay_artifact(old, "F1", store=False)
    empty = artifact(); empty["families"]["F1"].pop("research_plan")
    result = replay.replay_artifact(empty, "F1", store=False)
    assert result["status"] == "SKIPPED" and result["reason"] == "NO_FROZEN_RESEARCH_PLAN"
