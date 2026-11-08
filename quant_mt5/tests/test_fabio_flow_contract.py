"""Focused contract tests for the Fabio external-flow validation boundary."""
import copy

import pytest

from quantmt5 import fabio
from quantmt5.util import iso_utc
from synth import symbol_data
from test_fabio import f1_rows, flow_file


def _flow():
    rows = f1_rows()
    sd = symbol_data(rows)
    as_of = float(sd.m5.available_at[-1])
    return sd, as_of, flow_file(rows, as_of)


@pytest.mark.parametrize(
    "mutator, reason",
    [
        (lambda f: f.pop("source"), "IDENTITY_REQUIRED"),
        (lambda f: f.update(contract=""), "IDENTITY_REQUIRED"),
        (lambda f: f["mapping"].update(reference_symbol="OTHER"), "REFERENCE_SYMBOL_INCONSISTENT"),
        (lambda f: f["mapping"].update(clock_offset_s=True), "CLOCK_OFFSET_INVALID"),
        (lambda f: f["bars"][0].update(buy_vol=-1), "VOLUME"),
        (lambda f: f["bars"][0].update(sell_vol=float("nan")), "VOLUME"),
        (lambda f: f["bars"][0].update(close_at=f["bars"][0]["open_at"]), "M5_DURATION"),
        (lambda f: f["bars"][0].update(open_at=iso_utc(fabio.parse_utc(f["bars"][0]["open_at"]) + 1), close_at=iso_utc(fabio.parse_utc(f["bars"][0]["close_at"]) + 1), known_at=iso_utc(fabio.parse_utc(f["bars"][0]["known_at"]) + 1)), "M5_GRID"),
        (lambda f: f["bars"].append(copy.deepcopy(f["bars"][0])), "DUPLICATE_RECORD"),
    ],
)
def test_malformed_or_inconsistent_records_reject_file(mutator, reason):
    sd, as_of, flow = _flow()
    mutator(flow)
    out = fabio.load_flow(flow, sd.m5, "TEST", as_of)
    assert out["status"] == "REJECTED"
    assert any(reason in item for item in out["reasons"])
    assert out["use_in_decision"] is False


def test_clock_offset_maps_all_record_times_and_preserves_300s_grid():
    sd, as_of, flow = _flow()
    offset = 60
    flow["mapping"]["clock_offset_s"] = offset
    for rec in flow["bars"]:
        for key in ("open_at", "close_at", "known_at"):
            rec[key] = iso_utc(fabio.parse_utc(rec[key]) - offset)
    out = fabio.load_flow(flow, sd.m5, "TEST", as_of)
    assert out["status"] == "USABLE" and out["bars_used"] == len(sd.m5)


def test_reset_is_source_clock_aligned_and_restarts_cvd_without_pre_reset_data():
    sd, as_of, flow = _flow()
    reset_i = len(sd.m5) - 10
    flow["reset_at"] = iso_utc(sd.m5.open_at[reset_i])
    out = fabio.load_flow(flow, sd.m5, "TEST", as_of)
    assert out["status"] in ("USABLE", "COVERAGE_LOW")
    assert out["cvd_start_index"] == reset_i
    assert out["bars_used"] == 10
    assert all(not (out["delta"][i] == out["delta"][i]) for i in range(reset_i))


def test_known_before_actual_close_rejects_instead_of_reporting_usable():
    sd, as_of, flow = _flow()
    flow["bars"][0]["known_at"] = flow["bars"][0]["open_at"]
    out = fabio.load_flow(flow, sd.m5, "TEST", as_of)
    assert out["status"] == "REJECTED" and "KNOWN_BEFORE_CLOSE" in out["reasons"][0]


def test_out_of_snapshot_record_known_before_close_rejects_whole_file():
    sd, as_of, flow = _flow()
    op = float(sd.m5.open_at[0]) - 300
    flow["bars"].append({"open_at": iso_utc(op), "close_at": iso_utc(op + 300),
                         "known_at": iso_utc(op), "buy_vol": 1, "sell_vol": 1})
    out = fabio.load_flow(flow, sd.m5, "TEST", as_of)
    assert out["status"] == "REJECTED" and "KNOWN_BEFORE_CLOSE" in out["reasons"][0]
    assert out["use_in_decision"] is False


def test_derived_volume_overflow_rejects_instead_of_emitting_infinite_arrays():
    sd, as_of, flow = _flow()
    flow["bars"][0].update(buy_vol=1e308, sell_vol=1e308)
    out = fabio.load_flow(flow, sd.m5, "TEST", as_of)
    assert out["status"] == "REJECTED" and out["reasons"] == ["DERIVED_VOLUME_NONFINITE"]


def test_cumulative_volume_overflow_rejects_even_when_each_bar_is_finite():
    sd, as_of, flow = _flow()
    for rec in flow["bars"]:
        rec.update(buy_vol=1e307, sell_vol=0.0)
    out = fabio.load_flow(flow, sd.m5, "TEST", as_of)
    assert out["status"] == "REJECTED" and out["reasons"] == ["DERIVED_VOLUME_NONFINITE"]
