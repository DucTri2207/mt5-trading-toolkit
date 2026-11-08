"""Fabio F1/F2 analysis: positive/negative checks on deterministic SYNTHETIC bars (logic tests, not market evidence)."""
import copy

import numpy as np
import pytest

from quantmt5 import fabio
from quantmt5.util import iso_utc
from synth import T0, symbol_data


def flat(n, c=100.0, h=100.5, l=99.5, vol=100):
    return [(c, h, l, c, vol)] * n


def day1_spike(rows, level):
    rows = list(rows)
    o, h, l, c, v = rows[10]
    rows[10] = (o, level, l, c, v)
    return rows


def f1_rows(trigger=True, tail_break=False):
    rows = day1_spike(flat(330), 110.0)                       # 288 bars = complete UTC day 1 with PDH=110
    rows += [(100, 101.0, 100.0, 101.0, 500), (101, 102.6, 101.0, 102.5, 600), (102.5, 104.6, 102.4, 104.5, 20), (104.5, 105.6, 104.4, 105.5, 600),
             (105.5, 105.5, 103.9, 104.0, 100), (104, 104.0, 103.0, 103.3, 100)]
    if trigger:
        rows.append((103.3, 104.3, 103.2, 104.2, 150))
    else:
        rows.append((103.3, 103.4, 102.9, 103.1, 150))
    if tail_break:
        rows.append((104.2, 104.2, 102.0, 102.2, 150))         # closes below the structure low after the trigger
    return rows


def run(rows, **kw):
    sd = symbol_data(rows)
    as_of = float(sd.m5.available_at[-1])
    return fabio.analyze(sd, as_of, symbol="TEST", snapshot_id="SNAP_TEST", **kw), as_of


def exec_in(as_of, **kw):
    d = {"schema": "fabio_exec_v1", "symbol": "TEST", "known_at": iso_utc(as_of - 30), "bid": 104.15, "ask": 104.25,
         "commission_round_turn_price": 0.10, "slippage_price": 0.05, "source": "FIXTURE_SYNTHETIC"}
    d.update(kw)
    return d


def flow_file(sd_rows, as_of, route="FTMO_EXTERNAL_FLOW", basis="EXECUTED_TRADES", buy=60.0, sell=40.0, drop=(), **kw):
    sd = symbol_data(sd_rows)
    m5 = sd.m5
    bars = []
    for i in range(len(m5)):
        if i in drop:
            continue
        bars.append({"open_at": iso_utc(m5.open_at[i]), "close_at": iso_utc(m5.close_at[i]), "known_at": iso_utc(m5.available_at[i]),
                     "buy_vol": buy, "sell_vol": sell})
    f = {"schema": "fabio_flow_v1", "route": route, "source": "FIXTURE_SYNTHETIC", "provenance": "FIXTURE_SYNTHETIC", "instrument": "TEST", "contract": "TEST_FIXTURE",
         "volume_basis": basis, "side_method": "AGGRESSOR_FLAG", "sign_convention": "POSITIVE_IS_BUY_AGGRESSION",
         "mapping": {"ftmo_symbol": "TEST", "reference_symbol": "TEST", "clock_offset_s": 0, "clock_verified": True}, "bars": bars}
    f.update(kw)
    return f


# ------------------------------------------------------------------ spec lock
def test_spec_hash_locked():
    assert fabio.SPEC_HASH == fabio.hash_obj(fabio.SPEC)
    assert fabio.SPEC["version"] == "1.1.0" and "20/30" in fabio.SPEC["operationalization_note"]


# ------------------------------------------------------------------ F1 positive / negative
def test_f1_enter_candidate_with_known_economics():
    rows = f1_rows()
    sd = symbol_data(rows)
    as_of = float(sd.m5.available_at[-1])
    r, _ = run(rows, exec_in=exec_in(as_of))
    f1 = r["families"]["F1"]
    assert f1["decision"] == "ENTER_CANDIDATE" and f1["side"] == "LONG", f1
    g = f1["gates"]
    assert g["location"]["status"] == "TOUCHED" and g["trigger"]["status"] == "OBSERVED"
    assert g["economics"]["status"] == "KNOWN" and g["economics"]["net_room_R"] > fabio.P["min_net_room_R"]
    assert g["target_room"]["source"] == "PREV_DAY_HIGH" and f1["invalidation"]["level"] == pytest.approx(103.0)
    assert r["win_probability"] is None and r["broker_order"] is False and r["route"] == "FTMO_PRICE_PROXY"
    assert r["causality"]["ok"] and f1["state_known_at"] <= r["as_of"]
    assert f1["variants"]["price_plus_cvd"]["decision"] == "DATA_UNAVAILABLE"      # flow missing: not invented


def test_f1_without_exec_economics_unknown_is_wait_not_enter():
    r, _ = run(f1_rows())
    f1 = r["families"]["F1"]
    assert f1["decision"] == "WAIT" and f1["reason"] == "ECONOMICS_UNKNOWN"
    assert f1["gates"]["economics"]["status"] == "UNKNOWN" and any(m.startswith("ECONOMICS_UNKNOWN") for m in f1["missing"])


def test_f1_trigger_missing_waits():
    r, _ = run(f1_rows(trigger=False))
    assert r["families"]["F1"]["decision"] == "WAIT" and r["families"]["F1"]["reason"] == "TRIGGER_PENDING"


def test_f1_trigger_negated_by_later_close_is_skip():
    rows = f1_rows(tail_break=True)
    sd = symbol_data(rows)
    r, as_of = run(rows, exec_in=exec_in(float(sd.m5.available_at[-1])))
    f1 = r["families"]["F1"]
    assert f1["decision"] == "SKIP" and f1["reason"] == "TRIGGER_NEGATED_BY_CLOSE_BELOW_STRUCTURE"
    assert f1["contradicting_evidence"]


def test_f1_returned_to_balance_cancels():
    rows = f1_rows(trigger=False) + [(103, 103.0, 99.9, 100.0, 100)]
    r, _ = run(rows)
    assert r["families"]["F1"]["decision"] == "SKIP" and r["families"]["F1"]["reason"] == "RETURNED_TO_BALANCE"


def test_f1_target_unknown_when_prev_day_level_not_ahead():
    rows = day1_spike(flat(330), 104.0) + f1_rows()[330:]      # PDH 104 is below the 104.2 close -> not ahead
    r, as_of = run(rows)
    f1 = r["families"]["F1"]
    assert f1["gates"]["target_room"]["status"] == "UNKNOWN" and f1["decision"] == "WAIT" and f1["reason"] == "TARGET_UNKNOWN"


def test_quote_too_far_or_stale_keeps_economics_unknown():
    rows = f1_rows()
    sd = symbol_data(rows)
    as_of = float(sd.m5.available_at[-1])
    for bad in (exec_in(as_of, known_at=iso_utc(as_of - 600)), exec_in(as_of, bid=150.0, ask=150.1), exec_in(as_of, known_at=iso_utc(as_of + 5)),
                exec_in(as_of, symbol="OTHER")):
        r, _ = run(rows, exec_in=bad)
        assert r["families"]["F1"]["gates"]["economics"]["status"] == "UNKNOWN"
        assert r["families"]["F1"]["decision"] == "WAIT"


def test_stale_market_state_is_data_unavailable_but_context_kept():
    r, _ = run(f1_rows(), market_state="STALE")
    assert r["decision"] == "DATA_UNAVAILABLE" and r["price_context"]["last_close"] and r["balance"]


def test_insufficient_history():
    r, _ = run(flat(50))
    assert r["decision"] == "DATA_UNAVAILABLE" and r["reason"].startswith("HISTORY_INSUFFICIENT")


def test_no_balance_is_unknown_state_skip():
    rows = [(100 + i, 101 + i, 99 + i, 100 + i, 100) for i in range(200)]       # persistent trend, no compact balance
    r, _ = run(rows)
    assert r["state"] == "UNKNOWN" and r["families"]["F1"]["reason"] == "STATE_UNKNOWN_NO_BALANCE_FOUND"


# ------------------------------------------------------------------ F2
def f2_rows(tail="trigger"):
    base = []
    for i in range(330):                                         # centre-heavy balance: POC 99.78, VA 99.70-100.33, range 99-101
        base.append((100, 101.0, 99.0, 100, 50) if i % 2 == 0 else (100, 100.3, 99.7, 100, 300))
    base = day1_spike(base, 100.0)
    rows = base + [(100.2, 103.0, 100.1, 102.8, 400), (102.8, 106.0, 102.7, 105.8, 15), (105.8, 105.9, 104.5, 104.6, 400),
                   (104.6, 104.7, 100.1, 100.2, 15)]             # breakout run (3 closes outside) then fast reclaim inside value
    if tail == "trigger":
        rows += [(100.2, 101.3, 100.2, 101.0, 100), (101.0, 101.1, 100.12, 100.15, 100)]
    elif tail == "below_poc":
        rows += [(100.2, 100.2, 98.0, 98.2, 100)]
    elif tail == "resumed":
        rows += [(100.2, 107.0, 100.2, 106.5, 100)]
    return rows


def f2_exec(rows):
    as_of = float(symbol_data(rows).m5.available_at[-1])
    return exec_in(as_of, bid=100.15, ask=100.25, commission_round_turn_price=0.05, slippage_price=0.02)


def test_f2_failed_breakout_short_to_poc_room_gate():
    rows = f2_rows()
    r, _ = run(rows, exec_in=f2_exec(rows))
    f2 = r["families"]["F2"]
    assert f2["side"] == "SHORT" and f2["failed_breakout"]["failure_extreme"] == 106.0
    assert f2["gates"]["target_room"]["source"] == "BALANCE_POC" and f2["gates"]["target_room"]["target"] == pytest.approx(r["balance"]["poc"])
    assert f2["gates"]["trigger"]["status"] == "OBSERVED" and f2["invalidation"]["level"] == pytest.approx(101.3)
    ec = f2["gates"]["economics"]                                  # short: entry Bid, SL trigger on Ask (= chart level + spread), TP on Ask
    assert ec["entry"] == 100.15 and ec["sl_trigger"] == pytest.approx(101.3 + f2["invalidation"]["sl_buffer"] + 0.10)
    assert ec["risk_price"] == pytest.approx(ec["sl_trigger"] - 100.15) and ec["reward_price"] == pytest.approx(100.15 - (r["balance"]["poc"] + 0.10))
    assert ec["net_room_R"] == pytest.approx((ec["reward_price"] - 0.07) / ec["risk_price"]) and not ec["meets_min_room"]
    assert f2["decision"] == "WAIT" and f2["reason"] == "NET_ROOM_BELOW_MIN"      # price gates pass, room after costs too small


def test_f2_poc_behind_price_is_skip():
    r, _ = run(f2_rows("below_poc"))
    assert r["families"]["F2"]["decision"] == "SKIP" and r["families"]["F2"]["reason"] == "POC_TARGET_BEHIND_PRICE"


def test_f2_breakout_resumed_beyond_failure_extreme_is_skip():
    r, _ = run(f2_rows("resumed"))
    assert r["families"]["F2"]["decision"] == "SKIP" and r["families"]["F2"]["reason"] == "BREAKOUT_RESUMED_BEYOND_FAILURE_EXTREME"


def test_economics_long_and_short_formulas_and_guards():
    t = 1_000_000.0
    ex = {"schema": "fabio_exec_v1", "symbol": "S", "known_at": iso_utc(t - 10), "bid": 100.0, "ask": 100.2,
          "commission_round_turn_price": 0.1, "slippage_price": 0.1, "source": "FIX"}
    lg = fabio.economics(ex, "S", t, +1, 1.0, 100.0, 99.0, 0.1, 103.0)       # SL 98.9 ; entry Ask 100.2
    assert lg["risk_price"] == pytest.approx(1.3) and lg["reward_price"] == pytest.approx(2.8) and lg["net_room_R"] == pytest.approx(2.6 / 1.3)
    sh = fabio.economics(ex, "S", t, -1, 1.0, 100.0, 101.0, 0.1, 97.0)       # SL 101.1 +spread 0.2 on Ask ; entry Bid 100
    assert sh["risk_price"] == pytest.approx(1.3) and sh["reward_price"] == pytest.approx(100.0 - 97.2) and sh["net_room_R"] == pytest.approx(2.6 / 1.3)
    assert fabio.economics(ex, "S", t, +1, 1.0, 100.0, None, 0.1, 103.0)["status"] == "UNKNOWN"      # invalidation unknown
    assert fabio.economics(ex, "S", t, +1, 1.0, 100.0, 99.0, 0.1, None)["status"] == "UNKNOWN"        # target unknown
    assert fabio.economics(None, "S", t, +1, 1.0, 100.0, 99.0, 0.1, 103.0)["reason"] == "EXEC_QUOTE_AND_COST_NOT_PROVIDED"


def test_f2_breakout_not_failed_waits_then_skips():
    rows = f1_rows()[:-3]                                         # A,B,C accepted outside: no reclaim
    r, _ = run(rows)
    assert r["families"]["F2"]["reason"] == "FAILURE_NOT_YET_CONFIRMED"
    r2, _ = run(rows + [(104.5, 104.6, 104.4, 104.5, 100)] * 8)
    assert r2["families"]["F2"]["reason"] == "BREAKOUT_NOT_FAILED" and r2["families"]["F2"]["decision"] == "SKIP"


# ------------------------------------------------------------------ flow contract
def test_flow_usable_gives_external_route_and_variants():
    rows = f1_rows()
    sd = symbol_data(rows)
    as_of = float(sd.m5.available_at[-1])
    r, _ = run(rows, flow=flow_file(rows, as_of), exec_in=exec_in(as_of))
    assert r["route"] == "FTMO_EXTERNAL_FLOW" and r["flow"]["status"] == "USABLE"
    v = r["families"]["F1"]["variants"]
    assert set(v) == {"price_response", "price_plus_cvd", "price_plus_local_aggression", "price_plus_bar_delta"}
    assert v["price_plus_local_aggression"]["decision"] == "DATA_UNAVAILABLE"
    assert v["price_plus_local_aggression"]["reason"] == "PRICE_LEVEL_EXECUTED_DATA_NOT_PROVIDED"
    assert v["price_plus_bar_delta"]["basis"] == "M5_BAR_TOTALS_RESPONSE_WINDOW"
    fr = r["families"]["F1"]["gates"]["flow"]
    assert fr["status"] == "OK" and fr["signed_delta_ratio"] == pytest.approx(0.2, abs=1e-3) and fr["class"] in ("AGGRESSION_CONFIRMS", "POSSIBLE_ABSORPTION_AGAINST", "NEUTRAL")


def test_quote_activity_labelled_as_flow_is_rejected_as_proxy():
    rows = f1_rows()
    as_of = float(symbol_data(rows).m5.available_at[-1])
    r, _ = run(rows, flow=flow_file(rows, as_of, basis="QUOTE_ACTIVITY"))
    assert r["flow"]["status"] == "PROXY_NOT_FLOW" and "ROUTE_MISCLASSIFIED_PROXY_AS_FLOW" in r["flow"]["reasons"]
    assert r["route"] == "FTMO_PRICE_PROXY" and r["families"]["F1"]["variants"]["price_plus_local_aggression"]["decision"] == "DATA_UNAVAILABLE"


def test_price_estimated_cvd_is_not_independent_flow():
    rows = f1_rows()
    as_of = float(symbol_data(rows).m5.available_at[-1])
    r, _ = run(rows, flow=flow_file(rows, as_of, basis="PRICE_ESTIMATED_CVD", route="FTMO_PRICE_PROXY"))
    assert r["flow"]["status"] == "PROXY_NOT_FLOW" and r["flow"]["use_in_decision"] is False


@pytest.mark.parametrize("patch,status", [({"route": "FUTURES_REFERENCE"}, "REFERENCE_ONLY"), ({"side_method": "NONE"}, "REJECTED"),
                                          ({"sign_convention": "UNKNOWN"}, "REJECTED"), ({"schema": "x"}, "REJECTED"),
                                          ({"mapping": {"ftmo_symbol": "OTHER", "clock_verified": True}}, "MAPPING_UNVERIFIED"),
                                          ({"mapping": {"ftmo_symbol": "TEST", "clock_verified": False}}, "MAPPING_UNVERIFIED")])
def test_flow_rejections(patch, status):
    rows = f1_rows()
    as_of = float(symbol_data(rows).m5.available_at[-1])
    f = flow_file(rows, as_of)
    f.update(patch)
    r, _ = run(rows, flow=f)
    assert r["flow"]["status"] == status and r["flow"]["use_in_decision"] is False


def test_future_known_flow_excluded_and_stale_flow():
    rows = f1_rows()
    sd = symbol_data(rows)
    as_of = float(sd.m5.available_at[-1])
    f = flow_file(rows, as_of)
    for k in (-1, -2, -3):                                          # last bars only known after the decision
        f["bars"][k]["known_at"] = iso_utc(as_of + 30)
    r, _ = run(rows, flow=f)
    assert any(x.startswith("FUTURE_KNOWN_INPUT_EXCLUDED") for x in r["flow"]["reasons"])
    assert r["flow"]["status"] == "STALE"
    assert r["flow"]["use_in_decision"] is False


def test_flow_gap_blocks_cvd_across_gap_and_coverage():
    rows = f1_rows()
    as_of = float(symbol_data(rows).m5.available_at[-1])
    f = flow_file(rows, as_of, drop=set(range(len(rows) - 12, len(rows) - 8)))
    r, _ = run(rows, flow=f, exec_in=exec_in(as_of))
    assert r["flow"]["status"] in ("USABLE", "COVERAGE_LOW")
    if r["flow"]["status"] == "USABLE":
        assert r["flow"]["cvd_start_index"] == len(rows) - 8            # CVD restarts after the gap, never bridged


def test_flow_reset_excludes_bars_before_reset():
    rows = f1_rows()
    sd = symbol_data(rows)
    as_of = float(sd.m5.available_at[-1])
    f = flow_file(rows, as_of, reset_at=iso_utc(sd.m5.open_at[len(rows) - 10]))
    r, _ = run(rows, flow=f)
    assert r["flow"]["status"] == "COVERAGE_LOW" or r["flow"]["cvd_start_index"] == len(rows) - 10


def test_divergence_requires_same_cvd_segment_and_names_classes():
    rows = []
    for i in range(130):                                           # zig-zag so fractal pivots exist
        p = 100 + (1.0 if (i // 5) % 2 else 0.0) + 0.02 * i
        rows.append((p, p + 0.3, p - 0.3, p, 100))
    sd = symbol_data(rows)
    as_of = float(sd.m5.available_at[-1])
    f = flow_file(rows, as_of)
    fl = fabio.load_flow(f, sd.m5, "TEST", as_of)
    assert fl["status"] == "USABLE"
    dv = fabio.divergences(sd.m5, fl, len(rows) - 1)
    assert dv["status"] == "OK"
    for k in ("high", "low"):
        assert dv[k].get("class") in ("none", "regular_bearish", "hidden_bearish", "regular_bullish", "hidden_bullish") or dv[k]["status"] == "UNAVAILABLE"
    fl2 = dict(fl, use_in_decision=False, status="STALE")
    assert fabio.divergences(sd.m5, fl2, len(rows) - 1)["status"] == "UNAVAILABLE"


def test_flow_classes_follow_ratio_and_price_progress():
    c = fabio.classify_flow
    assert c(0.3, 0.5) == "AGGRESSION_CONFIRMS" and c(0.3, -0.5) == "POSSIBLE_ABSORPTION_AGAINST" and c(0.3, 0.1) == "NEUTRAL"
    assert c(-0.3, 0.5) == "OPPOSING_AGGRESSION_ABSORBED" and c(-0.3, -0.5) == "OPPOSING_CONFIRMED" and c(-0.3, 0.1) == "NEUTRAL"
    assert c(0.05, 1.0) == "NEUTRAL" and c(-0.05, -1.0) == "NEUTRAL"             # ratio inside the dead zone: no claim


def test_contradicting_flow_changes_variant_not_price_response():
    rows = f1_rows()
    as_of = float(symbol_data(rows).m5.available_at[-1])
    r, _ = run(rows, flow=flow_file(rows, as_of, buy=20.0, sell=80.0), exec_in=exec_in(as_of))
    f1 = r["families"]["F1"]
    assert f1["gates"]["flow"]["class"] == "OPPOSING_CONFIRMED"                    # selling aggression while price pulls back: no absorption claim
    assert f1["variants"]["price_response"]["decision"] == "ENTER_CANDIDATE"       # price-only variant is unchanged
    assert f1["variants"]["price_plus_bar_delta"]["decision"] == "SKIP"
    assert any(e["id"] == "FLOW_OPPOSING_CONFIRMED" for e in f1["contradicting_evidence"])


def test_no_inputs_mutated_and_json_serialisable():
    import json
    from quantmt5.util import canonical_json
    rows = f1_rows()
    as_of = float(symbol_data(rows).m5.available_at[-1])
    f = flow_file(rows, as_of)
    before = copy.deepcopy(f)
    r, _ = run(rows, flow=f, exec_in=exec_in(as_of))
    assert f == before
    json.loads(canonical_json(r))
    assert fabio.render_report(dict(r, analysis_id="A"))
