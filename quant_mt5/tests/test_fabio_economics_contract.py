"""Focused contract checks for Fabio execution economics validation."""

import math

import pytest

from quantmt5 import fabio
from quantmt5.util import iso_utc


T = 1_000_000.0


def _exec(**updates):
    value = {
        "schema": "fabio_exec_v1",
        "symbol": "S",
        "known_at": iso_utc(T - 10),
        "bid": 100.0,
        "ask": 100.2,
        "commission_round_turn_price": 0.1,
        "slippage_price": 0.1,
        "source": "FIXTURE",
    }
    value.update(updates)
    return value


def _economics(ex=None):
    return fabio.economics(ex or _exec(), "S", T, +1, 1.0, 100.0, 99.0, 0.1, 103.0)


@pytest.mark.parametrize(
    "updates",
    [
        {"commission_round_turn_price": None},
        {"slippage_price": None},
        {"commission_round_turn_price": -0.01},
        {"slippage_price": -0.01},
        {"commission_round_turn_price": True},
        {"slippage_price": False},
        {"commission_round_turn_price": float("nan")},
        {"slippage_price": float("inf")},
        {"commission_round_turn_price": "0.1"},
    ],
)
def test_missing_or_invalid_costs_are_unknown(updates):
    result = _economics(_exec(**updates))
    assert result["status"] == "UNKNOWN"
    assert result["reason"] == "EXEC_COST_INVALID_OR_MISSING"


def test_zero_costs_are_valid_explicit_values():
    result = _economics(_exec(commission_round_turn_price=0.0, slippage_price=0))
    assert result["status"] == "KNOWN" and result["cost_price"] == 0.0


def test_overflowing_cost_sum_cannot_be_known():
    result = _economics(_exec(commission_round_turn_price=1e308, slippage_price=1e308))
    assert result["status"] == "UNKNOWN"


@pytest.mark.parametrize(
    "updates",
    [
        {"known_at": "not-a-time"},
        {"known_at": None},
        {"bid": True},
        {"ask": "100.2"},
        {"bid": float("nan")},
        {"ask": float("inf")},
        {"bid": 100.0, "ask": 99.0},
    ],
)
def test_invalid_quote_or_time_is_unknown(updates):
    assert _economics(_exec(**updates))["status"] == "UNKNOWN"


@pytest.mark.parametrize(
    "kwargs",
    [
        {"as_of": math.nan},
        {"atr_now": 0.0},
        {"last_close": -1.0},
        {"dirn": 0},
        {"inval": math.inf},
        {"buf": -0.1},
        {"target": True},
    ],
)
def test_invalid_internal_economics_inputs_are_unknown(kwargs):
    args = {"as_of": T, "dirn": +1, "atr_now": 1.0, "last_close": 100.0, "inval": 99.0, "buf": 0.1, "target": 103.0}
    args.update(kwargs)
    result = fabio.economics(_exec(), "S", **args)
    assert result["status"] == "UNKNOWN"


def test_valid_long_and_short_preserve_cost_and_spread_formulas():
    ex = _exec()
    long_result = fabio.economics(ex, "S", T, +1, 1.0, 100.0, 99.0, 0.1, 103.0)
    short_result = fabio.economics(ex, "S", T, -1, 1.0, 100.0, 101.0, 0.1, 97.0)
    assert long_result["status"] == short_result["status"] == "KNOWN"
    assert long_result["risk_price"] == pytest.approx(1.3)
    assert short_result["risk_price"] == pytest.approx(1.3)
    assert long_result["cost_price"] == short_result["cost_price"] == pytest.approx(0.2)


def test_delayed_old_quote_does_not_become_fresh_on_arrival():
    result = _economics(_exec(event_at=iso_utc(T - 1000), known_at=iso_utc(T - 1)))
    assert result["status"] == "UNKNOWN" and result["reason"].startswith("EXEC_QUOTE_STALE")
