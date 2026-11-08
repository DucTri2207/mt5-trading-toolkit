"""Supplemental contract edges collected after the first frozen full-suite run."""
import copy
import datetime as dt
import json
import socket

import pytest

from quantmt5 import retention as R, session as S
from quantmt5.evening_context import build_currency_strength, relative_movement
from quantmt5.util import append_jsonl, canonical_json, sha256_file
from tests.synth import T0
from tests.test_evening_lifecycle import _pending, _enrich, _child_ok
from tests.test_evening_strength import overlay, series


@pytest.mark.parametrize("wrong_field", ["cycle_id", "generation_id", "snapshot_id"])
def test_t22_each_expected_identity_mismatch_refuses_before_spawn(tmp_path, monkeypatch, wrong_field):
    root, name, directory, ticks, state, state_path = _pending(tmp_path, monkeypatch)
    original = sha256_file(ticks / "chunk.npz")
    continuation = dict(state["continuation"], **{wrong_field: "WRONG"})
    monkeypatch.setattr(S, "exec_in_bundle", lambda *a, **kw: pytest.fail("must refuse before optional child"))
    result = S.enrich(root, name, continuation["cycle_id"], continuation["generation_id"], continuation["snapshot_id"])
    assert result["status"] == "REFUSED" and result.get("finish_token") is None
    assert sha256_file(ticks / "chunk.npz") == original
    assert json.loads(state_path.read_text())["context_state"] == "PENDING"


def test_t24_latest_cycle_changes_during_child_cannot_commit(tmp_path, monkeypatch):
    root, name, directory, ticks, state, state_path = _pending(tmp_path, monkeypatch)
    def child(*args, **kwargs):
        record = json.loads((directory / "cycles.jsonl").read_text())
        append_jsonl(directory / "cycles.jsonl", dict(record, cycle_id="NEW_CYCLE", snapshot_id="NEW_SNAPSHOT"))
        return _child_ok()
    monkeypatch.setattr(S, "exec_in_bundle", child)
    monkeypatch.setattr(S, "build_report", lambda *a, **kw: pytest.fail("stale cycle must not render final report"))
    result = _enrich(root, name, state)
    assert result["status"] == "REFUSED" and "IDENTITY_OR_REVISION" in result["reason"]
    assert result["finish_token"] is None and (ticks / "chunk.npz").exists()
    assert json.loads(state_path.read_text())["context_state"] == "PENDING"


def test_t28_final_report_write_failure_never_registers_or_finalizes(tmp_path, monkeypatch):
    root, name, directory, ticks, state, state_path = _pending(tmp_path, monkeypatch)
    monkeypatch.setattr(S, "exec_in_bundle", _child_ok)
    def disk_failure(*args, **kwargs):
        raise OSError("SYNTHETIC_DISK_FULL_BEFORE_REPORT_COMMIT")
    monkeypatch.setattr(S, "build_report", disk_failure)
    monkeypatch.setattr(R, "record_report", lambda *a, **kw: pytest.fail("must not register missing final report"))
    result = _enrich(root, name, state)
    assert result["status"] == "REFUSED" and result["finish_token"] is None
    assert "SYNTHETIC_DISK_FULL" in result["reason"]
    assert json.loads(state_path.read_text())["context_state"] == "PENDING"
    c = state["continuation"]
    assert R.finish_session(directory, c["cycle_id"], c["generation_id"], c["snapshot_id"])["reason"] == "CONTEXT_PENDING"
    assert (ticks / "chunk.npz").exists()


def test_t43_no_network_or_news_gate_in_baseline_and_enrichment(monkeypatch):
    from quantmt5 import context, reporting
    from tests.test_evening_context import market, snapshot
    snap = snapshot()
    snap["episodes"][0]["atr_frozen"] = 2.0
    before = canonical_json(snap)
    def denied(*args, **kwargs):
        pytest.fail("network/news request forbidden in snapshot-only analysis")
    monkeypatch.setattr(socket, "create_connection", denied)
    monkeypatch.setattr(socket.socket, "connect", denied)
    monkeypatch.setattr(socket.socket, "connect_ex", denied)
    monkeypatch.setattr(context, "check_snapshot_config", lambda snap: None)
    monkeypatch.setattr(context, "build_market_context", lambda *a, **kw: market())
    monkeypatch.setattr(context, "opportunity_card", lambda *a, **kw: {"status": "OK", "context": []})
    for result in (reporting.build_baseline_packet(snap), reporting.analyze_snapshot(snap, max_cards=0)):
        assert result["news_handling"] == "USER_MANAGED"
        assert result["news_checked_by_system"] is False
        assert result["candidates"] == snap["candidates"]
    assert canonical_json(snap) == before


@pytest.mark.parametrize("date", ["2025-01-15", "2025-07-15"])
def test_t48_vietnam_display_time_is_utc_plus_seven_without_dst(date):
    utc = dt.datetime.fromisoformat(date + "T12:00:00+00:00")
    displayed = utc.astimezone(S.ICT)
    assert displayed.hour == 19 and displayed.utcoffset() == dt.timedelta(hours=7)
    assert displayed.astimezone(dt.timezone.utc) == utc


def test_t64_tick_activity_does_not_weight_h1_price_movement():
    bars = series()
    cutoff = T0 + 25 * 3600 + 1
    baseline = relative_movement(bars, cutoff, "S")
    heavy = copy.deepcopy(bars)
    heavy.tick_volume *= 100000
    heavy.real_volume[:] = 123456
    assert relative_movement(heavy, cutoff, "S") == baseline


def test_t66_rank_ties_and_input_order_are_deterministic_without_hidden_topk():
    data = {"EURUSD": overlay("EUR", "USD", 1, "EURUSD.r"),
            "GBPUSD": overlay("GBP", "USD", 1, "GBPUSD.r")}
    forward = build_currency_strength(data, ["EURUSD", "GBPUSD"])
    reversed_data = dict(reversed(list(data.items())))
    reverse = build_currency_strength(reversed_data, ["GBPUSD", "EURUSD"])
    for currency in ("EUR", "GBP", "USD"):
        for horizon in ("1", "4"):
            assert forward[currency][horizon]["comparable_value"] == reverse[currency][horizon]["comparable_value"]
            assert forward[currency][horizon]["rank"] == reverse[currency][horizon]["rank"]
    assert forward["EUR"]["1"]["rank"] == forward["GBP"]["1"]["rank"] == 1
    assert forward["USD"]["1"]["rank"] == 3
    assert set(forward) == {"EUR", "GBP", "USD"}
