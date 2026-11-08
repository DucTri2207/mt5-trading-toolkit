"""Causal scalp-policy contracts on synthetic bars; these are software tests, not market evidence."""
import numpy as np
import pytest

from quantmt5 import fabio
from quantmt5.util import parse_utc
from synth import T0, symbol_data
from test_fabio import f1_rows, f2_rows, flat, exec_in


def mirror(rows):
    return [(200 - o, 200 - l, 200 - h, 200 - c, v) for o, h, l, c, v in rows]


def f1_with_target():
    # A prior completed high balance exists within 150 bars of the new balance.
    return flat(180, c=110, h=110.5, l=109.5) + f1_rows()[180:]


def f2_symmetric_rows():
    # Central mass makes the balance POC favourable on both mirrored paths.
    rows = f2_rows()
    rows[:330] = [(100, 101, 99, 100, 50) if i % 2 == 0 else (100, 100, 100, 100, 300)
                  for i in range(330)]
    rows[333:] = [(104.6, 104.7, 99.99, 100, 15), (100.2, 101.3, 100.1, 101, 100),
                  (101, 101.1, 100.02, 100.05, 100)]
    return rows


def analyze(rows, *, as_of=None, source="synthetic_source", snapshot="SNAP_TEST", start=T0, **kw):
    sd = symbol_data(rows, start=start)
    sd.prof["chart_basis"] = "BID"
    sd.source_id = source
    return fabio.analyze(sd, float(sd.m5.available_at[-1]) if as_of is None else as_of,
                         symbol="TEST", snapshot_id=snapshot, policy=fabio.SCALP_POLICY, **kw)


@pytest.mark.parametrize("family,rows", [("F1", f1_with_target()), ("F2", f2_symmetric_rows())])
@pytest.mark.parametrize("mirrored", [False, True])
def test_price_sequence_has_later_trigger_and_target_with_unknown_economics(family, rows, mirrored):
    rows = mirror(rows) if mirrored else rows
    a = analyze(rows)
    f = a["families"][family]
    g = f["gates"]
    expected_side = "LONG" if (family == "F1") != mirrored else "SHORT"
    assert f["side"] == expected_side
    assert f["setup_stage"] == "TRIGGER_OBSERVED", f
    assert f["decision"] != "ENTER_CANDIDATE"
    assert f["execution_readiness"] == "COST_UNKNOWN"
    assert g["trigger"]["trigger_known_at"] > g["pullback"]["profile_frozen_at"]
    assert g["location"]["touch_known_at"] > g["pullback"]["profile_frozen_at"]
    target = g["target_room"]["target"]
    assert (1 if expected_side == "LONG" else -1) * (target - rows[-1][3]) > 0
    assert a["win_probability"] is None and f["broker_order"] is False


def test_prefix_and_full_data_at_same_cutoff_are_identical():
    rows = f1_with_target()
    cutoff = float(symbol_data(rows).m5.available_at[-1])
    future = rows + [(104.2, 150, 90, 140, 100000)] * 24
    assert analyze(rows, as_of=cutoff) == analyze(future, as_of=cutoff)


def test_same_episode_across_snapshots_retains_id_target_profile_and_trigger():
    rows = f1_with_target()
    a = analyze(rows, snapshot="SNAP_A")
    b = analyze(rows + [(104.2, 104.4, 103.7, 104.1, 100)], snapshot="SNAP_B")
    fa, fb = a["families"]["F1"], b["families"]["F1"]
    assert a["balance"] == b["balance"]
    assert fa["opportunity_id"] == fb["opportunity_id"]
    assert fa["trigger_id"] == fb["trigger_id"]
    assert fa["expires_at"] == fb["expires_at"]
    assert fa["gates"]["location"] == fb["gates"]["location"]
    assert fa["gates"]["target_room"]["target"] == fb["gates"]["target_room"]["target"]
    assert analyze(rows, snapshot="SNAP_A") == a


def test_source_identity_changes_opportunity_but_snapshot_does_not():
    rows = f1_rows()
    a = analyze(rows, source="BROKER_A", snapshot="A")["families"]["F1"]
    b = analyze(rows, source="BROKER_A", snapshot="B")["families"]["F1"]
    c = analyze(rows, source="BROKER_B", snapshot="C")["families"]["F1"]
    assert a["opportunity_id"] == b["opportunity_id"] != c["opportunity_id"]


def test_second_price_trigger_does_not_restart_entry_window():
    rows = f1_rows()
    first = analyze(rows)["families"]["F1"]
    second = analyze(rows + [(104.2, 104.25, 103.1, 103.3, 100),
                             (103.3, 104.6, 103.2, 104.5, 100)])["families"]["F1"]
    assert first["opportunity_id"] == second["opportunity_id"]
    assert first["trigger_id"] == second["trigger_id"]
    assert first["expires_at"] == second["expires_at"]
    assert second["setup_stage"] == "EXPIRED"
    assert second["decision"] == "SKIP"


def test_clock_expiry_works_without_new_bar():
    rows = f1_rows()
    first = analyze(rows)["families"]["F1"]
    later = analyze(rows, as_of=parse_utc(first["expires_at"]) + 1)["families"]["F1"]
    assert later["setup_stage"] == "EXPIRED"
    assert later["trigger_id"] == first["trigger_id"]


def test_missing_target_keeps_structure_visible_and_does_not_make_replay_plan():
    f = analyze(f1_rows())["families"]["F1"]
    assert f["setup_stage"] == "TRIGGER_OBSERVED"
    assert f["gates"]["target_room"]["status"] == "UNKNOWN"
    assert f["decision"] == "WAIT"
    assert not f.get("replay_plan") and not f.get("research_plan")


def test_freeze_bar_and_reclaim_bar_cannot_be_later_trigger():
    for rows, family in [(f1_rows()[:335], "F1"), (f2_symmetric_rows()[:334], "F2"),
                         (f2_symmetric_rows()[:335], "F2")]:
        f = analyze(rows)["families"][family]
        assert (f["gates"].get("trigger") or {}).get("status") != "OBSERVED"
        assert f["decision"] != "ENTER_CANDIDATE"


def test_extension_after_freeze_invalidates_same_opportunity():
    rows = f1_rows()
    first = analyze(rows)["families"]["F1"]
    later = analyze(rows + [(104.2, 106, 104.1, 105.8, 100)])["families"]["F1"]
    assert later["setup_stage"] == "INVALIDATED"
    assert later["opportunity_id"] == first["opportunity_id"]


@pytest.mark.parametrize("tail", [
    (104.2, 106, 104.1, 105.8, 100),  # renewed favourable extreme
    (104.2, 104.3, 99.8, 100.0, 100),  # return to original balance
    (104.2, 104.3, 102.4, 102.8, 100),  # touch/trigger structure negated
])
def test_post_trigger_invalidation_retains_original_plan_and_deadline(tail):
    rows = f1_with_target()
    first = analyze(rows)["families"]["F1"]
    later = analyze(rows + [tail])["families"]["F1"]
    assert later["setup_stage"] == "INVALIDATED", later
    assert later["trigger_id"] == first["trigger_id"]
    assert later["opportunity_id"] == first["opportunity_id"]
    assert later["expires_at"] == first["expires_at"]
    for key in ("plan_id", "known_at", "expires_at", "sl_chart", "target_chart", "profile_known_at"):
        assert later["research_plan"][key] == first["research_plan"][key]
    assert parse_utc(later["invalidated_at"]) > parse_utc(first["research_plan"]["known_at"])


def test_f2_target_crossing_does_not_erase_historical_trigger():
    rows = f2_symmetric_rows()
    first = analyze(rows)["families"]["F2"]
    later = analyze(rows + [(100.05, 100.1, 99.7, 99.8, 100)])["families"]["F2"]
    assert later["setup_stage"] == "INVALIDATED", later
    assert later["opportunity_id"] == first["opportunity_id"]
    assert later["trigger_id"] == first["trigger_id"]
    assert later["research_plan"]["plan_id"] == first["research_plan"]["plan_id"]
    assert later["research_plan"]["target_chart"] == first["research_plan"]["target_chart"]


def test_pre_trigger_extension_cannot_create_new_plan():
    rows = f1_with_target()[:335] + [(104, 106, 103.9, 105.8, 100)]
    f = analyze(rows)["families"]["F1"]
    assert f["setup_stage"] == "INVALIDATED", f
    assert not f.get("trigger_id") and not f.get("research_plan")


@pytest.mark.parametrize("age,allowed", [(149, True), (150, True), (151, False)])
def test_reference_balance_age_is_strictly_bounded(age, allowed):
    last_high = 600 - age
    rows = flat(last_high + 1, c=110, h=110.5, l=109.5) + flat(700 - last_high - 1)
    sd = symbol_data(rows)
    from quantmt5.features import atr
    target, _ = fabio._scalp_prior_poc(sd.m5, atr(sd.m5, 14), {"start_index": 600}, 104., 1, None)
    assert (target is not None) == allowed


def test_array_prefix_shift_preserves_opportunity_event_identity():
    rows = f1_with_target()
    full = analyze(rows)["families"]["F1"]
    shifted = analyze(rows[30:], start=T0 + 30 * 300)["families"]["F1"]
    assert full["opportunity_id"] == shifted["opportunity_id"]
    assert full["trigger_id"] == shifted["trigger_id"]
    assert full["expires_at"] == shifted["expires_at"]


def test_profile_future_and_uncovered_ticks_do_not_change_fallback():
    m5 = symbol_data(flat(30)).m5
    tick_time = np.array([float(m5.open_at[0]), float(m5.open_at[0]) + 10.])
    profile = {"time_s": tick_time, "known_at_s": np.full(2, float(m5.available_at[-1]) + 1000),
               "price": np.array([101., 150.]), "weight": np.ones(2), "basis": "SYNTHETIC_TICK_ACTIVITY",
               "covered_spans": [(float(m5.open_at[0]), float(m5.close_at[-1]))]}
    baseline = fabio.window_profile(m5, 0, 23, 0.125, strict=True)
    future = fabio.window_profile(m5, 0, 23, 0.125, profile, strict=True)
    profile["known_at_s"] = tick_time
    profile["covered_spans"] = []
    uncovered = fabio.window_profile(m5, 0, 23, 0.125, profile, strict=True)
    for observed in (future, uncovered):
        assert baseline[0] == observed[0] and baseline[2] == observed[2]
        np.testing.assert_array_equal(baseline[1], observed[1])


def test_flat_zero_volume_does_not_manufacture_balance():
    a = analyze(flat(150, vol=0))
    assert a["balance"] is None
    assert a["decision"] != "ENTER_CANDIDATE"


def test_strict_profile_fallback_conserves_tick_weights():
    m5 = symbol_data([(100, 100.3, 99.7, 100, 17), (100, 100.5, 99.5, 100, 19)]).m5
    _, volume, basis = fabio.window_profile(m5, 0, 1, 0.1, strict=True)
    assert np.sum(volume) == pytest.approx(36)
    assert basis == "MT5_BAR_TICK_VOLUME_UNIFORM_PROXY"


def test_default_and_explicit_legacy_are_equal():
    for rows in [f1_rows(), f2_rows(), flat(50)]:
        sd = symbol_data(rows)
        as_of = float(sd.m5.available_at[-1])
        kw = dict(symbol="TEST", snapshot_id="SNAP_TEST", exec_in=exec_in(as_of))
        assert fabio.analyze(sd, as_of, **kw) == fabio.analyze(sd, as_of, policy="legacy", **kw)
        legacy = fabio.analyze(sd, as_of, **kw)
        assert legacy["spec_hash"] == fabio.SPEC_HASH and legacy["spec_version"] == "1.1.0"
        assert "policy" not in legacy


@pytest.mark.parametrize("basis", ["LAST", "UNKNOWN"])
def test_unsupported_chart_basis_never_becomes_execution_ready(basis):
    sd = symbol_data(f1_with_target())
    sd.prof["chart_basis"] = basis
    as_of = float(sd.m5.available_at[-1])
    f = fabio.analyze(sd, as_of, symbol="TEST", policy=fabio.SCALP_POLICY,
                      exec_in=exec_in(as_of))["families"]["F1"]
    assert f["setup_stage"] == "TRIGGER_OBSERVED"
    assert f["decision"] != "ENTER_CANDIDATE" and f["execution_readiness"] == "DATA_MISSING"
    assert not f.get("research_plan")


def test_late_impulse_bar_cannot_backdate_a_profile_or_trigger():
    sd = symbol_data(f1_with_target())
    sd.prof["chart_basis"] = "BID"
    sd.m5.available_at[332] = sd.m5.available_at[-1] + 60
    original = sd.m5.available_at.copy()
    as_of = float(sd.m5.available_at.max())
    f = fabio.analyze(sd, as_of, symbol="TEST", policy=fabio.SCALP_POLICY)["families"]["F1"]
    assert not f.get("research_plan")
    assert (f["gates"].get("trigger") or {}).get("status") != "OBSERVED"
    assert parse_utc(f["gates"]["pullback"]["profile_frozen_at"]) >= as_of
    assert np.array_equal(sd.m5.available_at, original)


def test_scalp_readiness_and_replay_use_identical_cost_room_at_boundary():
    from quantmt5.execution import TickQuotes
    from quantmt5.fabio_replay import replay_plan
    from synth import ticks
    rows = f1_with_target()
    at = float(symbol_data(rows).m5.available_at[-1])
    result = analyze(rows, exec_in=exec_in(at, commission_round_turn_price=3.2, slippage_price=.05))
    f = result["families"]["F1"]
    qm = TickQuotes(ticks([(at, 104.15, 104.25)]))
    replay = replay_plan(f["research_plan"], qm, [(at, at + 3600)], commission_price_rt=3.2, slippage_price=.05)
    assert f["decision"] == "WAIT" and replay["status"] == "SKIPPED"
    assert f["gates"]["economics"]["net_room_R"] == pytest.approx(replay["net_room_R"])


def test_changed_profile_basis_is_an_explicit_reconstruction_revision():
    rows = f1_with_target()
    sd = symbol_data(rows)
    original = analyze(rows)
    times, prices = [], []
    for k in range(330, 334):
        times.extend(np.linspace(sd.m5.open_at[k], sd.m5.close_at[k], 1000, endpoint=False))
        prices.extend(np.linspace(sd.m5.l[k], sd.m5.h[k], 1000))
    profile = {"time_s": np.array(times), "price": np.array(prices), "weight": np.ones(len(times)),
               "covered_spans": [(sd.m5.open_at[330], sd.m5.close_at[333])], "basis": "MT5_BID_TICK_ACTIVITY"}
    data = {"profile": profile, "flow": fabio.load_flow(None, sd.m5, "TEST", sd.m5.available_at[-1]),
            "exec": None, "provenance": {"provider_kind": "SYNTHETIC_FIXTURE"}}
    changed = analyze(rows, mt5_data=data)
    a, b = original["families"]["F1"], changed["families"]["F1"]
    assert a["episode_key"] == b["episode_key"]
    assert a["profile_revision_id"] != b["profile_revision_id"]
    assert a["profile_basis"] != b["profile_basis"]
    assert changed["profile_lifecycle"]["mode"] == "RECONSTRUCTED_FROM_PINNED_INPUTS"
    assert a["research_plan"]["plan_id"]  # original evidence is retained, not mutated
    continued = analyze(rows, mt5_data=data, previous_analysis=original)
    f = continued["families"]["F1"]
    assert continued["profile_lifecycle"]["mode"] == "FROZEN_PREVIOUS_ANALYSIS_CHAIN"
    assert f["frozen_profile"] == a["frozen_profile"]
    assert f["research_plan"] == a["research_plan"]
    assert f["trigger_id"] == a["trigger_id"]
    assert f["profile_revision_id"] == a["profile_revision_id"]


@pytest.mark.parametrize("change,reason", [("future", "PREVIOUS_IS_FUTURE"), ("source", "PREVIOUS_SOURCE_MISMATCH"),
                                          ("price", "PRICE_HISTORY_CHANGED_OR_MISSING"), ("spec", "PREVIOUS_SPEC_MISMATCH")])
def test_previous_analysis_chain_rejects_incompatible_history(change, reason):
    rows = f1_with_target()
    previous = analyze(rows)
    if change == "future":
        previous["as_of"] = fabio.iso_utc(parse_utc(previous["as_of"]) + 60)
    elif change == "source":
        previous["source_fingerprint"] = "OTHER"
    elif change == "spec":
        previous["spec_hash"] = "OTHER"
    else:
        o, h, l, c, v = rows[-1]
        rows[-1] = (o, h + .1, l, c, v)
    with pytest.raises(ValueError, match=reason):
        analyze(rows, previous_analysis=previous)


def test_previous_analysis_chain_preserves_original_expiry_after_next_trigger():
    rows = f1_with_target()
    previous = analyze(rows)
    continued = analyze(rows + [(104.2, 104.25, 103.1, 103.3, 100), (103.3, 104.6, 103.2, 104.5, 100)],
                        previous_analysis=previous)
    a, b = previous["families"]["F1"], continued["families"]["F1"]
    assert a["research_plan"] == b["research_plan"]
    assert a["trigger_id"] == b["trigger_id"]
    assert b["setup_stage"] == "EXPIRED"


def test_previous_chain_keeps_pending_balance_for_next_breakout():
    rows = f1_with_target() + flat(40, c=104, h=104.5, l=103.5) + [(104, 115, 95, 104, 100)]
    previous = analyze(rows)
    future = rows + [(104, 106.2, 103.9, 106, 100), (106, 106.5, 105.9, 106.3, 100)]
    independent, chained = analyze(future), analyze(future, previous_analysis=previous)
    assert independent["balance"]["breakout_at"] != previous["balance"]["breakout_at"]
    assert chained["balance"] == independent["balance"]


def test_modified_frozen_profile_is_rejected_before_continuation():
    rows = f1_with_target()
    previous = analyze(rows)
    values = previous["families"]["F1"]["frozen_profile"]["volumes"]
    previous["families"]["F1"]["frozen_profile"]["volumes"] = [1000] * len(values)
    with pytest.raises(ValueError, match="PREVIOUS_STATE_HASH_MISMATCH"):
        analyze(rows, previous_analysis=previous)


def test_previous_chain_rejects_changed_symbol_metadata():
    rows = f1_with_target()
    previous = analyze(rows)
    sd = symbol_data(rows)
    sd.prof["chart_basis"] = "BID"
    sd.q = .1
    with pytest.raises(ValueError, match="SYMBOL_METADATA_MISMATCH"):
        fabio.analyze(sd, float(sd.m5.available_at[-1]), symbol="TEST", policy=fabio.SCALP_POLICY,
                      previous_analysis=previous)

