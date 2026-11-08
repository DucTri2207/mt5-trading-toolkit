"""Focused regression contracts for the 1.0.1 Fabio decision semantics."""
import pytest

from test_fabio import exec_in, f1_rows, f2_exec, f2_rows, flow_file, run


@pytest.mark.parametrize("market_state", ["STALE", "UNKNOWN"])
def test_nonfresh_gate_invalidates_every_active_variant(market_state):
    rows = f1_rows()
    _, as_of = run(rows)
    result, _ = run(rows, market_state=market_state, flow=flow_file(rows, as_of), exec_in=exec_in(as_of))

    assert result["decision"] == "DATA_UNAVAILABLE"
    for family in result["families"].values():
        assert family["decision"] == "DATA_UNAVAILABLE"
        assert "decision_if_data_were_fresh" in family
        for variant in (family.get("variants") or {}).values():
            assert variant["decision"] == "DATA_UNAVAILABLE"
            assert "decision_if_data_were_fresh" in variant


def test_bar_delta_proxy_is_distinct_from_price_level_aggression():
    rows = f1_rows()
    _, as_of = run(rows)
    result, _ = run(rows, flow=flow_file(rows, as_of), exec_in=exec_in(as_of))
    variants = result["families"]["F1"]["variants"]

    assert variants["price_plus_local_aggression"] == {
        "decision": "DATA_UNAVAILABLE",
        "reason": "PRICE_LEVEL_EXECUTED_DATA_NOT_PROVIDED",
        "basis": "PRICE_LEVEL_EXECUTED_TRADES_REQUIRED",
    }
    assert variants["price_plus_bar_delta"]["basis"] == "M5_BAR_TOTALS_RESPONSE_WINDOW"
    assert result["families"]["F1"]["gates"]["flow"]["basis"] == "M5_BAR_TOTALS_RESPONSE_WINDOW"


def test_f2_requires_post_reclaim_touch_then_trigger():
    # This sequence ends on the reclaim bar; no later pullback/test exists.
    rows = f2_rows()[:330] + [
        (100.2, 103.0, 100.1, 102.8, 400),
        (102.8, 106.0, 102.7, 105.8, 500),
        (105.8, 105.9, 99.2, 104.6, 15),
        (104.6, 105.2, 104.0, 105.1, 100),
        (105.1, 105.2, 100.1, 100.2, 100),
    ]
    result, _ = run(rows)
    f2 = result["families"]["F2"]
    assert f2["failed_breakout"]["reclaim_index"] == 334
    assert f2.get("gates", {}).get("trigger", {}).get("status") != "OBSERVED"


def test_f2_positive_control_uses_reclaim_then_touch_then_trigger():
    rows = f2_rows()
    result, _ = run(rows, exec_in=f2_exec(rows))
    f2 = result["families"]["F2"]
    assert f2["failed_breakout"]["reclaim_index"] == 333
    assert f2["failed_breakout"]["failure_extreme_index"] < f2["failed_breakout"]["reclaim_index"]
    assert f2["gates"]["location"]["touch_run_start_index"] == 334
    assert f2["gates"]["trigger"]["trigger_index"] == 335
    assert f2["gates"]["location"]["touch_known_at"] < f2["gates"]["trigger"]["trigger_known_at"]
    assert f2["gates"]["trigger"]["trigger_known_at"] > f2["failed_breakout"]["reclaim_known_at"]

