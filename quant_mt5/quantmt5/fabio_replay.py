"""Finite, read-only replay of a frozen Fabio plan against pinned MT5 Bid/Ask ticks.

The 30-minute hold is a declared project research choice, not a source strategy rule.
Unknown costs retain an unadjusted quote-path diagnostic; verified net P&L stays UNKNOWN.
No baseline candidate, baseline simulator, M1 proxy, order, or account sizing is used.
"""
from __future__ import annotations

import math
from numbers import Real

import numpy as np

from .data import Ticks
from .execution import Quote, TickQuotes, _walk
from .replay import _covered_end, load_pinned_ticks, pinned_tick_tape, pinned_ticks_utc, tick_covered_spans
from .util import STORE_DIR, ceil_to_tick, floor_to_tick, hash_obj, iso_utc, parse_utc, stable_id, write_immutable_json

REPLAY_SPEC = {
    "version": "scalp-fabio-replay-1.0.0", "default_max_hold_s": 1800,
    "entry": "first usable quote after plan known_at plus explicit latency, strictly before original expires_at",
    "short_levels": "freeze first entry spread added to BID chart stop and target; exit uses Ask",
    "costs": "explicit scenario is ASSUMED; unknown slippage uses unadjusted quote path, net UNKNOWN",
    "quote_max_age_s": 120, "entry_drift_max_atr": 1.0, "min_net_room_R": 1.5,
    "time_exit": "first tick at/after fill plus max_hold_s; no inferred session schedule",
}


def _number(value, name: str, *, positive=False, optional=False):
    if value is None and optional:
        return None
    if isinstance(value, bool) or not isinstance(value, Real) or not math.isfinite(float(value)):
        raise ValueError(f"FABIO_REPLAY_INVALID:{name}")
    value = float(value)
    invalid = value <= 0 if positive else value < 0
    if invalid:
        raise ValueError(f"FABIO_REPLAY_INVALID:{name}")
    return value


def _time(value, name):
    if not isinstance(value, str):
        raise ValueError(f"FABIO_REPLAY_INVALID:{name}")
    try:
        result = parse_utc(value)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError(f"FABIO_REPLAY_INVALID:{name}") from exc
    if not math.isfinite(result):
        raise ValueError(f"FABIO_REPLAY_INVALID:{name}")
    return result


class _FillPath:
    """Only the event sequence after this fill is eligible for the shared walker."""

    def __init__(self, quotes, fill):
        self.quotes, self.fill = quotes, fill

    def segments(self, start, end):
        for seg in self.quotes.segments(start, end):
            if seg["t"] == self.fill.t and seg["seq"] < self.fill.seq:
                continue
            if not (math.isfinite(seg["open_bid"]) and math.isfinite(seg["open_ask"])
                    and seg["open_bid"] > 0 and seg["open_ask"] >= seg["open_bid"]):
                seg = {**seg, **{key: math.nan for key in ("open_bid", "open_ask", "bid_lo", "bid_hi", "ask_lo", "ask_hi")}}
            yield seg

    def first_event_at_or_after(self, when):
        quote = self.quotes.first_event_at_or_after(when)
        if quote and not (math.isfinite(quote.bid) and math.isfinite(quote.ask) and quote.bid > 0 and quote.ask >= quote.bid):
            return Quote(quote.t, math.nan, math.nan, quote.event_at, quote.available_at, quote.seq, quote.source)
        return quote


def replay_plan(plan: dict, quotes: TickQuotes | None, covered_spans: list, *, latency_s=0.0,
                commission_price_rt=None, slippage_price=None, max_hold_s=1800.0) -> dict:
    """Pure quote-path oracle. Coverage is [start, end) UTC seconds and must be externally certified."""
    from types import SimpleNamespace

    latency = _number(latency_s, "latency_s")
    commission = _number(commission_price_rt, "commission_price_rt", optional=True)
    slippage = _number(slippage_price, "slippage_price", optional=True)
    hold = _number(max_hold_s, "max_hold_s", positive=True)
    rec = {"schema": "fabio_replay_v1", "replay_spec": REPLAY_SPEC["version"], "replay_spec_hash": hash_obj(REPLAY_SPEC),
           "status": "UNRESOLVED", "reason": None, "broker_order": False, "net_price": None, "net_R": None,
           "scenario": {"latency_s": latency, "max_hold_s": hold, "commission_price_rt": commission,
                        "slippage_price_per_side": slippage, "cost_status": "ASSUMED" if commission is not None and slippage is not None else "UNKNOWN"},
           "flags": list(quotes.flags) if quotes else [], "quote_path": "SLIPPAGE_ADJUSTED_SCENARIO" if slippage is not None else "UNADJUSTED_QUOTE_PATH",
           "notes": ["Spread is inside Bid/Ask; it is not charged again.",
                     "Cash, lot sizing, account rules and session-close scheduling are not inferred."]}

    def stop(status, reason):
        rec.update(status=status, reason=reason)
        return rec

    if not isinstance(plan, dict):
        raise ValueError("FABIO_REPLAY_INVALID:research_plan")
    side = plan.get("side")
    if side not in ("LONG", "SHORT"):
        raise ValueError("FABIO_REPLAY_INVALID:side")
    if plan.get("chart_basis") != "BID":
        return stop("UNRESOLVED", "CHART_BASIS_NOT_BID")
    ready, deadline = _time(plan.get("known_at"), "known_at"), _time(plan.get("expires_at"), "expires_at")
    invalidated = _time(plan["invalidated_at"], "invalidated_at") if plan.get("invalidated_at") is not None else None
    sl_chart = _number(plan.get("sl_chart"), "sl_chart", positive=True)
    target_chart = _number(plan.get("target_chart"), "target_chart", positive=True, optional=True)
    tick_size = _number(plan.get("tick_size"), "tick_size", positive=True)
    trigger_close = _number(plan.get("trigger_close"), "trigger_close", positive=True)
    atr = _number(plan.get("atr_frozen"), "atr_frozen", positive=True)
    rec.update(side=side, ready_at=iso_utc(ready), quote_request_at=iso_utc(ready + latency), expires_at=iso_utc(deadline),
               sl_chart=sl_chart, target_chart=target_chart)
    if target_chart is None:
        return stop("UNRESOLVED", "TARGET_UNKNOWN")
    if ready + latency >= deadline:
        return stop("EXPIRED", "READY_AFTER_OR_AT_EXPIRY")
    if invalidated is not None and ready + latency >= invalidated:
        return stop("SKIPPED", "PLAN_INVALIDATED_BEFORE_ENTRY")
    if quotes is None:
        return stop("UNRESOLVED", "PINNED_TICKS_MISSING")
    if not isinstance(quotes, TickQuotes):
        raise ValueError("FABIO_REPLAY_REQUIRES_TICKS")
    rec.update(quote_model_version=quotes.version_id(), quote_kind=quotes.kind)
    coverage_end = _covered_end(covered_spans, ready)
    if coverage_end is None:
        return stop("UNRESOLVED", "ENTRY_COVERAGE_MISSING")
    rec["coverage_end_at"] = iso_utc(coverage_end)
    first = quotes.first_usable(ready + latency)
    if first is None or first.t >= deadline:
        return stop("EXPIRED" if coverage_end >= deadline else "UNRESOLVED",
                    "NO_FILL_BEFORE_EXPIRY" if coverage_end >= deadline else "ENTRY_COVERAGE_ENDS_BEFORE_EXPIRY")
    if first.t >= coverage_end:
        return stop("UNRESOLVED", "ENTRY_COVERAGE_GAP_BEFORE_FIRST_QUOTE")
    if invalidated is not None and first.t >= invalidated:
        return stop("SKIPPED", "PLAN_INVALIDATED_BEFORE_ENTRY")
    rec["entry_quote"] = {**first.identity(), "bid": first.bid, "ask": first.ask}
    if not (math.isfinite(first.bid) and math.isfinite(first.ask) and first.bid > 0 and first.ask >= first.bid):
        return stop("UNRESOLVED", "FIRST_QUOTE_INVALID")
    if first.t - first.event_at > REPLAY_SPEC["quote_max_age_s"]:
        return stop("SKIPPED", "FIRST_QUOTE_STALE")
    direction = 1 if side == "LONG" else -1
    offset = first.ask - first.bid if side == "SHORT" else 0.0
    sl = floor_to_tick(sl_chart, tick_size) if side == "LONG" else ceil_to_tick(sl_chart + offset, tick_size)
    target = ceil_to_tick(target_chart, tick_size) if side == "LONG" else floor_to_tick(target_chart + offset, tick_size)
    rec.update(sl=sl, target=target, short_spread_offset=offset,
               level_basis="BID_CHART" if side == "LONG" else "ASK_LEVELS_FROM_ENTRY_SPREAD_ASSUMPTION")
    if sl <= 0 or target <= 0:
        return stop("UNRESOLVED", "GRID_LEVEL_NONPOSITIVE")
    # A delayed source event inside the pre-entry window leaves the invalidation path unknown at fill time.
    seq = np.arange(len(quotes.t))
    prior = (quotes.t >= ready) & ((quotes.t < first.t) | ((quotes.t == first.t) & (seq < first.seq)))
    if np.any(prior & (quotes.av > first.t)):
        return stop("UNRESOLVED", "PRE_ENTRY_ARRIVAL_INCOMPLETE")
    for i in np.flatnonzero(prior):
        bid, ask = quotes.bid[i], quotes.ask[i]
        if not (math.isfinite(bid) and math.isfinite(ask) and bid > 0 and ask >= bid):
            return stop("UNRESOLVED", "PRE_ENTRY_QUOTE_INVALID")
        px = bid if side == "LONG" else ask
        if direction * (px - sl) <= 0:
            return stop("SKIPPED", "SL_TOUCHED_BEFORE_ENTRY")
        if direction * (px - target) >= 0:
            return stop("SKIPPED", "TARGET_TOUCHED_BEFORE_ENTRY")
    if direction * (first.bid - trigger_close) > REPLAY_SPEC["entry_drift_max_atr"] * atr:
        return stop("SKIPPED", "ENTRY_DRIFT_EXCEEDS_ONE_ATR")
    stop_side = first.bid if side == "LONG" else first.ask
    if direction * (stop_side - sl) <= 0:
        return stop("SKIPPED", "FIRST_QUOTE_BEYOND_SL")
    slip_used = slippage if slippage is not None else 0.0
    entry = (first.ask if side == "LONG" else first.bid) + direction * slip_used
    risk, reward = direction * (entry - sl), direction * (target - entry)
    if risk <= 0 or reward <= 0:
        return stop("SKIPPED", "RISK_OR_TARGET_ROOM_NONPOSITIVE")
    if commission is not None and slippage is not None:
        rec["net_room_R"] = (reward - commission - slippage) / risk
        if rec["net_room_R"] < REPLAY_SPEC["min_net_room_R"]:
            return stop("SKIPPED", "NET_ROOM_BELOW_MIN")
    keep = quotes.t < coverage_end
    clipped = TickQuotes(Ticks("REPLAY", (quotes.t[keep] * 1000).round().astype(np.int64), quotes.bid[keep], quotes.ask[keep],
                               np.zeros(int(keep.sum()), dtype=np.int64)),
                         (quotes.av[keep] * 1000).round().astype(np.int64), kind=quotes.kind, source=quotes.source)
    # Clipping only removes the end, so original same-millisecond sequence identities are preserved.
    out = _walk(side, _FillPath(clipped, first), first.t, first.t, first.t + hold, entry, sl, target, risk,
                SimpleNamespace(slip_price=slip_used))
    rec.update(out)
    rec["flags"] += rec.pop("flags_add", [])
    rec.update(fill_at=iso_utc(first.t), entry=entry, risk_price=risk, time_exit_scheduled_at=iso_utc(first.t + hold))
    primary = rec["primary"]
    if primary.get("exit_at") is None:
        primary.update(gross_price=None, gross_R=None, net_price=None, net_R=None)
        return stop("CENSORED", primary["exit_reason"])
    gross = direction * (primary["exit_price"] - entry)
    primary.update(gross_price=gross, gross_R=gross / risk, net_price=None, net_R=None)
    if commission is not None and slippage is not None:
        primary.update(net_price=gross - commission, net_R=(gross - commission) / (risk + commission))
        rec.update(net_price=primary["net_price"], net_R=primary["net_R"])
    return stop("EXITED", primary["exit_reason"])


def replay_artifact(analysis: dict, family: str, outcome_snapshot_id: str | None = None, *, latency_s=0.0,
                    commission_price_rt=None, slippage_price=None, max_hold_s=1800.0, store=True) -> dict:
    """Replay one saved analysis/family using its snapshot or an explicitly selected later snapshot's pins."""
    from .fabio import SCALP_POLICY, SCALP_SPEC_HASH
    from .snapshot import load_snapshot

    if not isinstance(analysis, dict) or analysis.get("schema") != "fabio_analysis_v1":
        raise ValueError("FABIO_REPLAY_ANALYSIS_SCHEMA_MISMATCH")
    if analysis.get("policy") != SCALP_POLICY or analysis.get("spec_hash") != SCALP_SPEC_HASH:
        raise ValueError("FABIO_REPLAY_SPEC_MISMATCH")
    if family not in ("F1", "F2") or family not in (analysis.get("families") or {}):
        raise ValueError("FABIO_REPLAY_FAMILY_MISSING")
    latency_s = _number(latency_s, "latency_s")
    max_hold_s = _number(max_hold_s, "max_hold_s", positive=True)
    commission_price_rt = _number(commission_price_rt, "commission_price_rt", optional=True)
    slippage_price = _number(slippage_price, "slippage_price", optional=True)
    item = analysis["families"][family]
    if not isinstance(item, dict):
        raise ValueError("FABIO_REPLAY_FAMILY_INVALID")
    plan = item.get("research_plan")
    base = {"analysis_id": analysis.get("analysis_id"), "analysis_snapshot_id": analysis.get("snapshot_id"),
            "symbol": analysis.get("symbol"), "family": family, "spec_hash": analysis["spec_hash"],
            **{key: item.get(key) for key in ("opportunity_id", "revision_id", "trigger_id")}}
    if not plan:
        rec = {**base, "schema": "fabio_replay_v1", "replay_spec": REPLAY_SPEC["version"], "replay_spec_hash": hash_obj(REPLAY_SPEC),
               "status": "SKIPPED", "reason": "NO_FROZEN_RESEARCH_PLAN", "setup_stage": item.get("setup_stage"),
               "net_R": None, "broker_order": False, "outcome_snapshot_id": outcome_snapshot_id or base["analysis_snapshot_id"],
               "scenario": {"latency_s": latency_s, "max_hold_s": max_hold_s, "commission_price_rt": commission_price_rt,
                            "slippage_price_per_side": slippage_price,
                            "cost_status": "ASSUMED" if commission_price_rt is not None and slippage_price is not None else "UNKNOWN"}}
    else:
        if not isinstance(plan, dict):
            raise ValueError("FABIO_REPLAY_PLAN_INVALID")
        expected = {"schema": "fabio_plan_v1", "policy": SCALP_POLICY, "spec_hash": analysis["spec_hash"],
                    "symbol": base["symbol"], "family": family, "source_id": analysis.get("source_id"),
                    "opportunity_id": base["opportunity_id"], "trigger_id": base["trigger_id"]}
        if any(plan.get(key) != value for key, value in expected.items()):
            raise ValueError("FABIO_REPLAY_PLAN_IDENTITY_MISMATCH")
        frozen = {key: value for key, value in plan.items() if key not in ("plan_id", "invalidated_at")}
        if plan.get("plan_id") != stable_id("FPLAN", frozen):
            raise ValueError("FABIO_REPLAY_PLAN_HASH_MISMATCH")
        if plan.get("invalidated_at") != item.get("invalidated_at"):
            raise ValueError("FABIO_REPLAY_INVALIDATION_MISMATCH")
        if plan.get("invalidated_at") is not None and _time(plan["invalidated_at"], "invalidated_at") > _time(analysis.get("as_of"), "analysis_as_of"):
            raise ValueError("FABIO_REPLAY_INVALIDATION_AFTER_ANALYSIS")
        if any(not base[key] for key in ("symbol", "analysis_snapshot_id", "opportunity_id", "revision_id", "trigger_id")):
            raise ValueError("FABIO_REPLAY_IDENTITY_MISSING")
        source_id, chart_basis = analysis.get("source_id"), analysis.get("chart_basis")
        if not isinstance(source_id, str) or not source_id:
            raise ValueError("FABIO_REPLAY_SOURCE_UNKNOWN")
        fingerprint = hash_obj({"source_id": source_id, "symbol": base["symbol"], "chart_basis": chart_basis})
        if analysis.get("source_fingerprint") != fingerprint or plan.get("source_fingerprint") != fingerprint:
            raise ValueError("FABIO_REPLAY_SOURCE_FINGERPRINT_MISMATCH")
        if plan.get("side") != item.get("side") or plan.get("chart_basis") != chart_basis:
            raise ValueError("FABIO_REPLAY_PLAN_IDENTITY_MISMATCH")
        if _time(plan.get("known_at"), "known_at") > _time(analysis.get("as_of"), "analysis_as_of"):
            raise ValueError("FABIO_REPLAY_PLAN_KNOWN_AFTER_ANALYSIS")
        source_snapshot = load_snapshot(base["analysis_snapshot_id"])
        outcome_id = outcome_snapshot_id or base["analysis_snapshot_id"]
        outcome = source_snapshot if outcome_id == base["analysis_snapshot_id"] else load_snapshot(outcome_id)
        for snapshot in (source_snapshot, outcome):
            actual = (snapshot.get("config_bundle") or {}).get("source_id") or snapshot.get("source_id")
            if actual != source_id or base["symbol"] not in snapshot.get("universe", []):
                raise ValueError("FABIO_REPLAY_SNAPSHOT_SOURCE_MISMATCH")
        if _time(plan["known_at"], "known_at") > _time(source_snapshot.get("as_of_utc"), "source_snapshot_as_of"):
            raise ValueError("FABIO_REPLAY_PLAN_KNOWN_AFTER_SOURCE_SNAPSHOT")
        if _time(outcome.get("as_of_utc"), "outcome_as_of") < _time(source_snapshot.get("as_of_utc"), "source_snapshot_as_of"):
            raise ValueError("FABIO_REPLAY_OUTCOME_PRECEDES_SOURCE_SNAPSHOT")
        source_config = source_snapshot.get("config_hash")
        if not isinstance(source_config, str) or not source_config or source_config != outcome.get("config_hash"):
            raise ValueError("FABIO_REPLAY_SNAPSHOT_CONFIG_MISMATCH")
        analysis_config = ((analysis.get("inputs") or {}).get("hashes") or {}).get("config_hash")
        if analysis_config is not None and analysis_config != source_config:
            raise ValueError("FABIO_REPLAY_ANALYSIS_CONFIG_MISMATCH")
        if (source_snapshot.get("time_basis") or {}).get(base["symbol"]) != (outcome.get("time_basis") or {}).get(base["symbol"]):
            raise ValueError("FABIO_REPLAY_SNAPSHOT_CLOCK_MISMATCH")
        source_provider = (source_snapshot.get("config_bundle") or {}).get("provider_kind")
        outcome_provider = (outcome.get("config_bundle") or {}).get("provider_kind")
        if source_provider and source_provider != outcome_provider:
            raise ValueError("FABIO_REPLAY_SNAPSHOT_PROVIDER_MISMATCH")
        pin = (outcome.get("tick_versions") or {}).get(base["symbol"])
        quotes, spans, pin_hash, provider = None, [], None, None
        if pin and pin.get("chunks"):
            raw, order_error = pinned_tick_tape(pin)  # integrity checks precede every coverage decision
            if order_error:
                raise ValueError(f"FABIO_REPLAY_TAPE_INVALID:{order_error}")
            utc = pinned_ticks_utc(raw, pin)
            names = utc.dtype.names or ()
            if not {"time_msc", "bid", "ask"}.issubset(names):
                raise ValueError("FABIO_REPLAY_TICK_FIELDS_MISSING")
            for field in ("time_msc", "available_msc"):
                if field in names:
                    numeric = utc[field].astype(float)
                    if not np.isfinite(numeric).all() or np.any(numeric <= 0) or np.any(numeric != np.floor(numeric)):
                        raise ValueError(f"FABIO_REPLAY_TICK_TIME_INVALID:{field}")
            until = _time(outcome.get("as_of_utc"), "outcome_as_of")
            tm = utc["time_msc"].astype(np.int64) / 1000.0
            spans = [(a, min(b, until + .001)) for a, b in tick_covered_spans(pin) if a <= until]
            provider = pin.get("provider_kind") or (outcome.get("config_bundle") or {}).get("provider_kind")
            if "available_msc" in names:
                av = utc["available_msc"].astype(np.int64)
                unavailable = tm[(tm <= until) & (av / 1000.0 > until)]
                if len(unavailable):
                    stop_at = float(unavailable.min())
                    spans = [(a, min(b, stop_at)) for a, b in spans if a < stop_at]
                keep = (tm <= until) & (av / 1000.0 <= until)
                quotes = TickQuotes(Ticks(base["symbol"], utc["time_msc"][keep], utc["bid"][keep], utc["ask"][keep],
                                          np.zeros(int(keep.sum()), dtype=np.int64)), av[keep],
                                    kind="COLLECTED_NATIVE_TICKS" if provider == "NATIVE_TERMINAL" else "COLLECTED_SYNTHETIC_TICKS",
                                    source=str(pin.get("content_hash")))
            else:
                quotes = load_pinned_ticks(pin, base["symbol"], provider, until=until + .001, verified=raw)
            pin_hash = pin.get("content_hash")
        rec = {**base, **replay_plan(plan, quotes, spans, latency_s=latency_s, commission_price_rt=commission_price_rt,
                                  slippage_price=slippage_price, max_hold_s=max_hold_s),
               "outcome_snapshot_id": outcome_id, "tick_pin_hash": pin_hash, "source_fingerprint": fingerprint,
               "provider_kind": provider, "evidence_scope": "SOFTWARE_RESEARCH; outcomes use ticks after the decision"}
    rec["replay_id"] = stable_id("FREPLAY", rec)
    if store:
        path = STORE_DIR / "fabio_replay" / f"{rec['replay_id']}.json"
        write_immutable_json(path, rec)
        rec["artifact_path"] = str(path)
    return rec
