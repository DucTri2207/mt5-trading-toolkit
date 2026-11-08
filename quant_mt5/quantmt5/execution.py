"""Causal execution simulator (B3): candidate → first usable quote → blocked | intent → fill → exit → costs.

Quote models
* ``TICKS``         Bid/Ask ticks with identity (seq) and arrival (`available_at`). Native broker ticks or labelled
                    synthetic fixtures. Exact path; same-ms ticks keep source order. If arrival is not observed it is
                    ASSUMED equal to event time and flagged.
* ``M1_OPEN_PROXY`` no tick tape: quotes only at M1 opens (Bid = M1 open, Ask = Bid + max(previous completed M1 spread
                    field, scenario floor)*point). Arrival ASSUMED at event; intra-minute order unknown → SL&TP in one
                    M1 is AMBIGUOUS (both orders reported, headline adverse-first). Never presented as exact.

Contract (setup-specs §4): first quote USABLE (available) at/after ready+latency; never a later "nicer" quote after a
guard blocks; entry strictly before min(signal close+90 s, episode expiry); pre-entry SL touch and Ask-high use only
ticks known by the fill; long enters Ask / exits Bid, short enters Bid / exits Ask; SL from Bid low (long) or Ask
high in the signal bar (short) ± buffer; TP 1.5R rounded away from entry on the tick grid; stop gaps fill at the
first quote through the stop with adverse slippage; TP fills at the level; time exit at the first quote at/after
min(fill+60 min, session_end−2 min). Costs per leg; spread is inside Bid/Ask (never charged twice). Nothing here
sends orders.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import math
from dataclasses import dataclass, field
from typing import Any, Iterator

import numpy as np

from .data import Bars, Ticks
from .timemap import NY, UTC
from .util import ceil_to_tick, floor_to_tick, hash_obj, iso_utc, round_volume_down, stable_id

LONG, SHORT = "LONG", "SHORT"
EXECUTION_MODEL_VERSION = "exec-v0.3.2"   # 0.3.1: missing exit-side quote → EXIT_UNRESOLVED; M1 proxy version hashes payload
#                                           0.3.2: invalid Ask in signal bar / missing stop side before entry → BLOCKED


# ------------------------------------------------------------------ session schedule
def next_session_end(t: float, sess: dict) -> float | None:
    """Next scheduled close (UTC epoch) at/after t from a NY-time schedule; None if unknown."""
    if not sess or sess.get("tz") != "America/New_York":
        return None
    ny = dt.datetime.fromtimestamp(t, UTC).astimezone(NY)
    for add in range(0, 8):
        d = (ny + dt.timedelta(days=add)).date()
        wd = d.weekday()
        if sess.get("kind") == "DAILY_BREAK" and sess.get("daily_close") and wd <= 4:
            hh, mm = map(int, sess["daily_close"].split(":"))
        elif wd == 4 and sess.get("weekly_close"):
            hh, mm = map(int, sess["weekly_close"].split()[1].split(":"))
        else:
            continue
        cand = dt.datetime(d.year, d.month, d.day, hh, mm, tzinfo=NY).timestamp()
        if cand >= t:
            return cand
    return None


# ------------------------------------------------------------------ quote models
@dataclass
class Quote:
    t: float            # usable time = max(event_at, available_at)
    bid: float
    ask: float
    event_at: float = 0.0
    available_at: float = 0.0
    seq: int = -1
    source: str = ""

    def identity(self) -> dict:
        return {"source": self.source, "seq": int(self.seq), "event_at": iso_utc(self.event_at),
                "available_at": iso_utc(self.available_at), "usable_at": iso_utc(self.t)}


class QuoteModel:
    name = "BASE"
    kind = "UNKNOWN"
    flags: tuple[str, ...] = ()

    def first_usable(self, t: float) -> Quote | None: ...

    def first_at_or_after(self, t: float) -> Quote | None:    # backwards-compatible alias
        return self.first_usable(t)

    def first_event_at_or_after(self, t: float) -> Quote | None:
        """Broker-side path (exits): first quote by EVENT time at/after t."""
        ...

    def segments(self, t_from: float, t_to: float, known_by: float | None = None) -> Iterator[dict]: ...

    def ask_high_in(self, t0: float, t1: float, bid_high: float, known_by: float | None = None) -> tuple[float | None, str]: ...

    def version_id(self) -> str: ...


class TickQuotes(QuoteModel):
    name = "TICKS"
    flags = ()

    def __init__(self, ticks: Ticks, available_ms: np.ndarray | None = None, kind: str = "SYNTHETIC_FIXTURE", source: str = ""):
        self.t = ticks.time_msc / 1000.0
        self.bid, self.ask = ticks.bid, ticks.ask
        if np.any(np.diff(self.t) < 0):
            raise ValueError("TICKS_NOT_SORTED")
        if available_ms is None:
            self.av = self.t.copy()
            self.flags = ("TICK_ARRIVAL_ASSUMED_AT_EVENT",)
        else:
            self.av = np.asarray(available_ms, dtype=float) / 1000.0
            if np.any(self.av < self.t):
                raise ValueError("TICK_AVAILABLE_BEFORE_EVENT")
            self.flags = ()
        self.kind, self.source = kind, source or kind
        self.order = np.lexsort((np.arange(len(self.t)), self.av))   # arrival order, ties by source sequence
        self.av_sorted = self.av[self.order]
        self._version_cache: str | None = None

    def _q(self, i: int) -> Quote:
        return Quote(float(max(self.t[i], self.av[i])), float(self.bid[i]), float(self.ask[i]), float(self.t[i]), float(self.av[i]), int(i), self.source)

    def first_usable(self, t):
        k = int(np.searchsorted(self.av_sorted, t, side="left"))
        if k >= len(self.order):
            return None
        return self._q(int(self.order[k]))

    def first_event_at_or_after(self, t):
        i = int(np.searchsorted(self.t, t, side="left"))
        return None if i >= len(self.t) else self._q(i)

    def segments(self, t_from, t_to, known_by=None):
        i0 = int(np.searchsorted(self.t, t_from, side="left"))
        i1 = int(np.searchsorted(self.t, t_to, side="left"))
        for i in range(i0, i1):
            if known_by is not None and self.av[i] > known_by:
                continue
            b, a = float(self.bid[i]), float(self.ask[i])
            yield {"t": float(self.t[i]), "seq": i, "open_bid": b, "open_ask": a, "bid_hi": b, "bid_lo": b, "ask_hi": a, "ask_lo": a, "exact": True}

    def ask_high_in(self, t0, t1, bid_high, known_by=None):
        i0, i1 = int(np.searchsorted(self.t, t0, "left")), int(np.searchsorted(self.t, t1, "left"))
        all_idx = np.arange(i0, i1)
        if known_by is not None and np.any(self.av[all_idx] > known_by):
            # A historical replay can see that part of the signal-bar tick
            # stream arrived after the fill. The true Ask high is therefore
            # not observable at the decision time; using the known prefix as
            # if it were complete would understate the short stop risk.
            return None, "ASK_IN_SIGNAL_BAR_INCOMPLETE"
        a = self.ask[all_idx]
        ok = np.isfinite(a) & (a > 0)
        if not ok.any():
            return None, "ASK_MISSING_IN_SIGNAL_BAR"                 # no Ask at all in the window
        if not ok.all():
            # One unknown Ask can exceed the known maximum: the Ask high is not certified (raw ticks kept as-is).
            return None, "ASK_INVALID_IN_SIGNAL_BAR"
        return float(a.max()), "ASK_FROM_TICKS"

    def version_id(self):
        # Identity must change when any quote content changes, including Bid,
        # Ask or arrival metadata. Length/range-only identities allowed a
        # modified tick file to reuse old fill/revision IDs.
        if getattr(self, "_version_cache", None) is None:
            h = hashlib.sha256()
            for s in (self.name, self.kind, self.source):
                h.update(str(s).encode("utf-8"))
            for f in self.flags:
                h.update(str(f).encode("utf-8"))
            for arr in (self.t, self.bid, self.ask, self.av):
                a = np.ascontiguousarray(arr)
                h.update(str(a.dtype).encode("utf-8"))
                h.update(str(a.shape).encode("utf-8"))
                h.update(a.tobytes())
            self._version_cache = h.hexdigest()[:16]
        return self._version_cache


class M1OpenProxy(QuoteModel):
    name = "M1_OPEN_PROXY"
    kind = "PROXY_FROM_M1_BARS"
    flags = ("QUOTE_MODEL_M1_OPEN_PROXY", "ASK_APPROX_FROM_BAR_SPREAD_FIELD", "LATENCY_QUANTISED_TO_M1_OPEN",
             "PROXY_QUOTE_ARRIVAL_ASSUMED_AT_EVENT")

    def __init__(self, m1: Bars, point: float, spread_floor_points: float):
        self.m1 = m1
        self.point = point
        self.floor = float(spread_floor_points)
        prev_spread = np.r_[m1.spread[0], m1.spread[:-1]].astype(float)
        self.open_off = np.maximum(prev_spread, self.floor) * point      # known at the open of bar i (previous completed bar)
        self.own_off = np.maximum(m1.spread.astype(float), self.floor) * point
        self.source = f"M1_PROXY:{m1.provenance.get('dataset_id')}"

    def _q(self, i):
        b = float(self.m1.o[i])
        t = float(self.m1.open_at[i])
        return Quote(t, b, b + float(self.open_off[i]), t, t, int(i), self.source)

    def first_usable(self, t):
        i = int(np.searchsorted(self.m1.open_at, t, side="left"))
        return None if i >= len(self.m1) else self._q(i)

    def first_event_at_or_after(self, t):
        return self.first_usable(t)

    def segments(self, t_from, t_to, known_by=None):
        m = self.m1
        i0 = int(np.searchsorted(m.open_at, t_from, side="left"))
        i1 = int(np.searchsorted(m.open_at, t_to, side="left"))
        for i in range(i0, i1):
            off_o, off = float(self.open_off[i]), float(self.own_off[i])
            yield {"t": float(m.open_at[i]), "seq": i, "open_bid": float(m.o[i]), "open_ask": float(m.o[i]) + off_o,
                   "bid_hi": float(m.h[i]), "bid_lo": float(m.l[i]), "ask_hi": float(m.h[i]) + off,
                   "ask_lo": float(m.l[i]) + off, "exact": False, "t_end": float(m.close_at[i])}

    def ask_high_in(self, t0, t1, bid_high, known_by=None):
        m = self.m1
        i0, i1 = int(np.searchsorted(m.open_at, t0, "left")), int(np.searchsorted(m.open_at, t1, "left"))
        if i1 <= i0:
            return None, "M1_MISSING_IN_SIGNAL_BAR"
        return float(np.max(m.h[i0:i1] + self.own_off[i0:i1])), "ASK_HIGH_APPROX_M1_HIGH_PLUS_SPREAD_FIELD"

    def version_id(self):
        # Must change with the bar payload (not only length/dataset_id), else changed M1 data reuses fill IDs.
        # Hashed once per proxy object (bytes, cached), not per candidate.
        if getattr(self, "_version_cache", None) is None:
            h = hashlib.sha256()
            h.update(hash_obj([self.name, self.source, self.floor, self.point, len(self.m1)]).encode("utf-8"))
            for arr in (self.m1.open_at, self.m1.close_at, self.m1.o, self.m1.h, self.m1.l, self.m1.spread):
                a = np.ascontiguousarray(arr)
                h.update(f"|{a.dtype}|{a.shape}|".encode("utf-8"))
                h.update(a.tobytes())
            self._version_cache = h.hexdigest()[:16]
        return self._version_cache


# ------------------------------------------------------------------ parameters
class EconomicsUnavailable(ValueError):
    """Per-symbol execution inputs are missing/invalid; keep its market context, not a fake zero-cost plan."""


def _valid_number(value, *, positive=False) -> bool:
    if value is None or isinstance(value, bool):
        return False
    try:
        n = float(value)
        return math.isfinite(n) and (n > 0 if positive else n >= 0)
    except (TypeError, ValueError):
        return False


def economics_status(symbol: str, prof: dict, cost: dict, require_spread_floor: bool = True) -> dict:
    """Unknown economics stays explicit. Cross conversion is unavailable without a same-asof observed rate."""
    reasons = []
    for key in ("trade_tick_size", "point", "contract_size"):
        if not _valid_number(prof.get(key), positive=True):
            reasons.append(f"METADATA_MISSING_OR_INVALID:{key}")
    keys = ["slippage_points_per_side"]
    if require_spread_floor:
        keys.append("spread_floor_points")
    for key in keys:
        if not _valid_number((cost.get(key) or {}).get(symbol)):
            reasons.append(f"COST_MISSING_OR_INVALID:{symbol}:{key}")
    comm = cost.get("commission_usd_per_lot_round_trip")
    if not _valid_number(comm):
        reasons.append("COMMISSION_MISSING_OR_INVALID")
    elif float(comm) != 0 and prof.get("profit_currency") != "USD" and prof.get("base_currency") != "USD":
        reasons.append("COMMISSION_CONVERSION_UNKNOWN:NO_SAME_ASOF_OBSERVED_RATE")
    return {"status": "UNKNOWN" if reasons else "ASSUMED", "reasons": reasons,
            "commission_status": cost.get("commission_status", "ASSUMED"),
            "basis": "declared scenario, not measured account costs"}


@dataclass
class ExecParams:
    latency_s: float
    slip_price: float
    commission_price_rt: float | None   # price units per 1 unit volume, round trip; None = UNKNOWN
    spread_guard: float
    drift_guard_mult: float
    tp_R: float
    max_hold_s: float
    deadline_s: float
    pre_close_s: float
    q: float
    stops_level_price: float | None
    session: dict
    latency_name: str = ""
    cost_name: str = ""
    freeze_level_price: float | None = None
    stale_quote_max_s: float = 2.0
    commission_status: str = "ASSUMED"
    commission_cash_per_lot_rt: float | None = None
    commission_cash_currency: str | None = None
    contract: dict = field(default_factory=dict)   # {contract_size, profit_currency, base_currency}
    risk: dict | None = None                       # {account_currency, risk_cash, volume_min, volume_step, volume_max}

    def version(self) -> dict:
        return {k: getattr(self, k) for k in ("latency_s", "slip_price", "commission_price_rt", "spread_guard", "drift_guard_mult", "tp_R",
                                               "max_hold_s", "deadline_s", "pre_close_s", "q", "stops_level_price", "freeze_level_price",
                                               "stale_quote_max_s", "commission_status", "commission_cash_per_lot_rt",
                                               "commission_cash_currency", "contract", "risk", "latency_name", "cost_name")}


def _blocked(base: dict, reason: str, **kw) -> dict:
    base.update({"status": "BLOCKED", "reason": reason, **kw})
    base["transitions"].append({"state": "REJECTED", "reason": reason, "event_at": kw.get("at")})
    return base


def _closed_throughout(t0: float, t1: float, sess: dict) -> bool:
    if not sess or t1 <= t0:
        return False
    from .coverage import scheduled_open
    ts = np.arange(int(t0), int(t1) + 1, 30, dtype=np.int64)
    return bool(len(ts)) and not scheduled_open(ts, sess).any()


# ------------------------------------------------------------------ simulator
def simulate(cand: dict, qm: QuoteModel, p: ExecParams) -> dict:
    side = cand["side"]
    q = p.q
    sig = cand["signal_bar"]
    sig_open, sig_close = _ts(sig["open_at"]), float(cand["signal_close_ts"])
    ready = float(cand["ready_ts"])
    t_q = ready + p.latency_s
    deadline = sig_close + p.deadline_s
    if cand.get("episode_expires_ts"):
        deadline = min(deadline, float(cand["episode_expires_ts"]))
    rec: dict[str, Any] = {"candidate_id": cand["candidate_id"], "candidate_revision": cand.get("revision_id"), "setup": cand["setup"],
                           "symbol": cand["symbol"], "side": side, "latency": p.latency_name, "cost": p.cost_name,
                           "quote_model": qm.name, "quote_kind": getattr(qm, "kind", None), "quote_model_version": qm.version_id(),
                           "execution_model_version": EXECUTION_MODEL_VERSION, "params_version": hash_obj(p.version())[:16],
                           "flags": list(qm.flags), "ready_at": iso_utc(ready), "quote_request_at": iso_utc(t_q), "deadline_at": iso_utc(deadline),
                           "transitions": [{"state": "INTENT", "event_at": iso_utc(t_q)}]}
    rec["fill_id"] = stable_id("FILL", rec["candidate_revision"] or rec["candidate_id"], rec["quote_model_version"], rec["params_version"])
    if cand.get("atr_frozen") is None:
        return _blocked(rec, "ATR_UNKNOWN")
    if t_q >= deadline:
        return _blocked(rec, "READY_AFTER_DEADLINE", at=iso_utc(t_q))
    atr_v = float(cand["atr_frozen"])
    buffer = float(cand["buffer"])
    sess_end = next_session_end(t_q, p.session)
    if sess_end is None:
        rec["flags"].append("SESSION_SCHEDULE_UNKNOWN")
    elif t_q > sess_end - p.pre_close_s:
        return _blocked(rec, "PAST_PRE_SESSION_END", at=iso_utc(t_q))
    quote = qm.first_usable(t_q)
    if quote is None:
        return _blocked(rec, "MARKET_CLOSED_NO_QUOTE" if _closed_throughout(t_q, deadline, p.session) else "NO_QUOTE_AFTER_READY")
    rec["entry_quote"] = {"t": iso_utc(quote.t), "bid": quote.bid, "ask": quote.ask, "spread": quote.ask - quote.bid, **quote.identity()}
    if quote.t >= deadline:
        reason = "MARKET_CLOSED_BEFORE_DEADLINE" if _closed_throughout(t_q, deadline, p.session) else "DEADLINE_BEFORE_FIRST_QUOTE"
        return _blocked(rec, reason, at=iso_utc(quote.t), gap_s=quote.t - t_q)
    if quote.t - quote.event_at > p.stale_quote_max_s:
        return _blocked(rec, "QUOTE_STALE", at=iso_utc(quote.t), quote_age_s=quote.t - quote.event_at)
    if sess_end is not None and quote.t > sess_end - p.pre_close_s:
        return _blocked(rec, "PAST_PRE_SESSION_END", at=iso_utc(quote.t))
    if not (math.isfinite(quote.bid) and quote.bid > 0 and math.isfinite(quote.ask) and quote.ask >= quote.bid):
        return _blocked(rec, "QUOTE_INVALID_OR_ASK_MISSING", at=iso_utc(quote.t))
    # structural SL from the signal bar, quote side correct, using only data known by the fill
    if side == LONG:
        sl = floor_to_tick(float(sig["l"]) - buffer, q)
        sl_basis = "BID_LOW_OF_SIGNAL_BAR"
    else:
        ah, basis = qm.ask_high_in(sig_open, sig_close, float(sig["h"]), known_by=quote.t)
        if ah is None:
            return _blocked(rec, basis)
        sl = ceil_to_tick(ah + buffer, q)
        sl_basis = basis
    rec.update({"sl": sl, "sl_basis": sl_basis})
    # SL touched between signal close and the entry quote (only ticks already known at fill) → never enter
    for seg in qm.segments(sig_close, quote.event_at, known_by=quote.t):
        stop_px = seg["bid_lo"] if side == LONG else seg["ask_hi"]
        if not (math.isfinite(stop_px) and stop_px > 0):
            # NaN compares False: a missing stop-side quote must not count as "SL not touched".
            return _blocked(rec, "STOP_SIDE_QUOTE_MISSING_BEFORE_ENTRY", at=iso_utc(seg["t"]))
        if (side == LONG and seg["bid_lo"] <= sl) or (side == SHORT and seg["ask_hi"] >= sl):
            return _blocked(rec, "SL_TOUCHED_BEFORE_ENTRY", at=iso_utc(seg["t"]))
    c_sig = float(sig["c"])
    drift = (quote.bid - c_sig) if side == LONG else (c_sig - quote.bid)
    rec["entry_drift_over_atr"] = drift / atr_v
    if drift > p.drift_guard_mult * atr_v:
        return _blocked(rec, "ENTRY_DRIFT_GUARD", at=iso_utc(quote.t))
    if (side == LONG and quote.bid <= sl) or (side == SHORT and quote.ask >= sl):
        return _blocked(rec, "QUOTE_BEYOND_SL", at=iso_utc(quote.t))
    entry = quote.ask + p.slip_price if side == LONG else quote.bid - p.slip_price
    R = abs(entry - sl)
    if not (R > 0):
        return _blocked(rec, "R_NONPOSITIVE")
    spread_R = (quote.ask - quote.bid) / R
    rec["spread_over_R"] = spread_R
    if spread_R > p.spread_guard:
        return _blocked(rec, "SPREAD_GUARD", at=iso_utc(quote.t))
    tp = ceil_to_tick(entry + p.tp_R * R, q) if side == LONG else floor_to_tick(entry - p.tp_R * R, q)
    trig = quote.bid if side == LONG else quote.ask                    # price the broker measures stops against
    for lvl_name, lvl in (("stops", p.stops_level_price), ("freeze", p.freeze_level_price)):
        if lvl is None:
            rec["flags"].append(f"{lvl_name.upper()}_LEVEL_UNKNOWN")
        elif min(abs(trig - sl), abs(tp - trig)) < lvl:
            return _blocked(rec, f"{lvl_name.upper()}_LEVEL_VIOLATION")
    fill_t = quote.t
    t_exit_sched = fill_t + p.max_hold_s
    if sess_end is not None:
        t_exit_sched = min(t_exit_sched, sess_end - p.pre_close_s)
    rec.update({"status": "FILLED", "fill_at": iso_utc(fill_t), "entry": entry, "tp": tp, "R_price": R,
                "tp_R_after_rounding": abs(tp - entry) / R, "time_exit_scheduled_at": iso_utc(t_exit_sched),
                "entry_leg": {"quote_side": "ASK" if side == LONG else "BID", "quote_price": quote.ask if side == LONG else quote.bid,
                              "slippage_price": p.slip_price, "price": entry}})
    rec["transitions"].append({"state": "FILLED", "event_at": iso_utc(fill_t)})
    # The quote may have an event timestamp before it became available. The
    # broker cannot trigger an exit before the actual fill/availability time.
    out = _walk(side, qm, fill_t, fill_t, t_exit_sched, entry, sl, tp, R, p)
    rec["flags"] += out.pop("flags_add", [])
    rec.update(out)
    _costs(rec, side, entry, R, p)
    rec["transitions"].append({"state": "EXITED", "event_at": out["primary"]["exit_at"], "reason": out["primary"]["exit_reason"]})
    return rec


def _costs(rec: dict, side: str, entry: float, R: float, p: ExecParams) -> None:
    sgn = 1 if side == LONG else -1
    comm = p.commission_price_rt
    leg = None if comm is None else comm / 2.0
    rec["commission"] = {"status": "UNKNOWN" if comm is None else p.commission_status, "entry_leg_price": leg, "exit_leg_price": leg,
                         "round_trip_price": comm, "note": "price units per 1 unit volume; spread is inside Bid/Ask (not charged again)"}
    if comm is None:
        rec["flags"].append("COMMISSION_UNKNOWN")
    for key in ("primary", "favorable_first"):
        o = rec.get(key)
        if o is None:
            continue
        if o.get("exit_at") is None:
            # Data ending before an exit is an unresolved outcome, not a flat
            # trade at the entry price. Keep the reason for diagnostics but do
            # not publish realised P&L or R.
            o["gross_price"] = None
            o["gross_R"] = None
            o["net_price"] = None
            o["net_R"] = None
            continue
        gross = (o["exit_price"] - entry) * sgn
        o["gross_price"] = gross
        o["gross_R"] = gross / R
        o["net_price"] = None if comm is None else gross - comm
        o["net_R"] = None if comm is None else (gross - comm) / (R + comm)
    rec["net_R"] = rec["primary"].get("net_R")
    rec["R_budget_price"] = None if comm is None else R + comm
    rec["R_cash_basis"] = "R_budget = |entry-SL| + declared round-trip commission; a gap exit can lose more than R_budget"
    if comm is not None:
        rec["cost_over_R"] = ((rec["entry_quote"]["ask"] - rec["entry_quote"]["bid"]) + 2 * p.slip_price + comm) / R
    rec["cash"] = cash_view(rec, side, entry, R, p)
    if rec["cash"].get("status") == "OK" and rec["cash"].get("planned_risk_cash"):
        # With an executable risk profile, canonical R is account-currency
        # realised P&L over the frozen cash risk budget. Price-unit fields
        # remain available for diagnostics.
        rec["net_R"] = rec["cash"]["net_cash"] / rec["cash"]["planned_risk_cash"]
        if rec.get("primary", {}).get("exit_at") is not None:
            rec["primary"]["net_R"] = rec["net_R"]


def conversion_rate(contract: dict, account_ccy: str, exit_price: float) -> tuple[float | None, str]:
    """Profit-currency → account-currency multiplier for one price unit × contract. Only defined cases; else UNKNOWN."""
    pc, bc = contract.get("profit_currency"), contract.get("base_currency")
    if not pc or not account_ccy:
        return None, "CURRENCY_METADATA_MISSING"
    if pc == account_ccy:
        return 1.0, "PROFIT_CCY_IS_ACCOUNT_CCY"
    if bc == account_ccy and exit_price > 0:
        return 1.0 / exit_price, "OWN_QUOTE_AT_EXIT (base==account)"
    return None, "CONVERSION_RATE_UNKNOWN"


def cash_view(rec: dict, side: str, entry: float, R: float, p: ExecParams) -> dict:
    """Cash P&L only with an explicit risk profile and contract/conversion metadata; otherwise UNKNOWN (never 0)."""
    if not p.risk:
        return {"status": "UNKNOWN", "reason": "NO_RISK_PROFILE (normalised R only; no executable lot)"}
    if rec.get("primary", {}).get("exit_at") is None:
        return {"status": "UNKNOWN", "reason": "EXIT_UNRESOLVED"}
    cs = p.contract.get("contract_size")
    comm = p.commission_price_rt
    if not cs or comm is None:
        return {"status": "UNKNOWN", "reason": "CONTRACT_SIZE_OR_COMMISSION_UNKNOWN"}
    conv_e, why_e = conversion_rate(p.contract, p.risk.get("account_currency"), entry)
    conv_x, why_x = conversion_rate(p.contract, p.risk.get("account_currency"), rec["primary"]["exit_price"])
    if conv_e is None or conv_x is None:
        return {"status": "UNKNOWN", "reason": why_e if conv_e is None else why_x}
    account_ccy = p.risk.get("account_currency")
    fixed_comm = p.commission_cash_per_lot_rt
    fixed_comm_ccy = p.commission_cash_currency
    if fixed_comm is not None:
        if fixed_comm_ccy and fixed_comm_ccy != account_ccy:
            return {"status": "UNKNOWN", "reason": "COMMISSION_CURRENCY_CONVERSION_UNKNOWN"}
        commission_per_lot_cash = float(fixed_comm)
    else:
        commission_per_lot_cash = float(comm) * cs * conv_e
    per_lot_risk = R * cs * conv_e + commission_per_lot_cash  # planned loss to SL incl. costs, account ccy, per lot
    vol, why = round_volume_down(p.risk["risk_cash"] / per_lot_risk, p.risk["volume_step"], p.risk["volume_min"], p.risk["volume_max"])
    if vol is None:
        return {"status": "BLOCKED", "reason": why, "volume_raw": p.risk["risk_cash"] / per_lot_risk}
    gross = rec["primary"]["gross_price"] * cs * vol * conv_x
    commission_cash = commission_per_lot_cash * vol
    return {"status": "OK", "volume": vol, "volume_rule": "risk_cash / per-lot planned loss, rounded DOWN to step",
            "planned_risk_cash": per_lot_risk * vol, "gross_cash": gross, "commission_cash": commission_cash,
            "net_cash": gross - commission_cash, "account_currency": p.risk["account_currency"],
            "conversion_entry": [conv_e, why_e], "conversion_exit": [conv_x, why_x],
            "commission_cash_per_lot": commission_per_lot_cash,
            "commission_cash_currency": fixed_comm_ccy or account_ccy,
            "status_note": "computed from declared fixture/profile values; MT5 order_calc_profit parity pending live"}


def _walk(side: str, qm: QuoteModel, fill_event: float, fill_t: float, t_exit: float, entry: float, sl: float, tp: float,
          R: float, p: ExecParams) -> dict:
    """Broker-side path after the fill, in EVENT order (stops/TP live at the broker, not in our arrival)."""
    sgn = 1 if side == LONG else -1
    mae = mfe = 0.0

    def _side_missing(t, seq):
        # Long exits/stops are measured on Bid, short on Ask. A quote without that side hides whether the stop/TP
        # traded, and NaN compares False (silently skipped). Report the exit as unresolved, never as P&L.
        return {"primary": {"exit_at": None, "exit_price": None, "exit_reason": "EXIT_UNRESOLVED_QUOTE_SIDE_MISSING",
                            "hold_s": None, "unresolved_at": iso_utc(t), "unresolved_quote_seq": None if seq is None else int(seq)},
                "ambiguous_sl_tp": False, "mae_R": mae, "mfe_R": mfe, "flags_add": ["EXIT_UNRESOLVED", "QUOTE_SIDE_MISSING_AFTER_FILL"]}

    keys = ("open_bid", "bid_lo", "bid_hi") if side == LONG else ("open_ask", "ask_lo", "ask_hi")
    for seg in qm.segments(fill_event, t_exit):           # the fill quote itself is on the correct side (checked) → harmless
        if not all(math.isfinite(seg[k]) and seg[k] > 0 for k in keys):
            return _side_missing(seg["t"], seg.get("seq"))
        ob = seg["open_bid"] if side == LONG else seg["open_ask"]
        if (side == LONG and ob <= sl) or (side == SHORT and ob >= sl):
            px = (ob - p.slip_price) if side == LONG else (ob + p.slip_price)
            return {"primary": _exit(seg["t"], px, "SL_GAP" if ob != sl else "SL", fill_t, seg.get("seq"), p.slip_price),
                    "ambiguous_sl_tp": False, "mae_R": min(mae, (px - entry) * sgn / R), "mfe_R": mfe}
        if (side == LONG and ob >= tp) or (side == SHORT and ob <= tp):
            return {"primary": _exit(seg["t"], tp, "TP" if seg["exact"] else "TP_AT_LEVEL_ON_GAP", fill_t, seg.get("seq"), 0.0),
                    "ambiguous_sl_tp": False, "mae_R": mae, "mfe_R": max(mfe, (tp - entry) * sgn / R)}
        lo, hi = (seg["bid_lo"], seg["bid_hi"]) if side == LONG else (seg["ask_lo"], seg["ask_hi"])
        adverse_px, fav_px = (lo, hi) if side == LONG else (hi, lo)
        hit_sl = adverse_px <= sl if side == LONG else adverse_px >= sl
        hit_tp = fav_px >= tp if side == LONG else fav_px <= tp
        mae = min(mae, (adverse_px - entry) * sgn / R)
        mfe = max(mfe, (fav_px - entry) * sgn / R)
        t_evt = seg.get("t_end", seg["t"])
        sl_px = (sl - p.slip_price) if side == LONG else (sl + p.slip_price)
        if hit_sl and hit_tp:
            return {"primary": _exit(t_evt, sl_px, "SL_AMBIGUOUS_ADVERSE_FIRST", fill_t, seg.get("seq"), p.slip_price),
                    "favorable_first": _exit(t_evt, tp, "TP_AMBIGUOUS_FAVORABLE_FIRST", fill_t, seg.get("seq"), 0.0),
                    "ambiguous_sl_tp": True, "mae_R": mae, "mfe_R": mfe, "flags_add": ["TICK_PATH_AMBIGUOUS"]}
        if hit_sl:
            return {"primary": _exit(t_evt, sl_px, "SL", fill_t, seg.get("seq"), p.slip_price), "ambiguous_sl_tp": False, "mae_R": mae, "mfe_R": mfe}
        if hit_tp:
            return {"primary": _exit(t_evt, tp, "TP", fill_t, seg.get("seq"), 0.0), "ambiguous_sl_tp": False, "mae_R": mae, "mfe_R": mfe}
    qx = qm.first_event_at_or_after(t_exit)
    if qx is None:
        return {"primary": {"exit_at": None, "exit_price": entry, "exit_reason": "NO_QUOTE_FOR_TIME_EXIT_DATA_END", "hold_s": None},
                "ambiguous_sl_tp": False, "mae_R": mae, "mfe_R": mfe, "flags_add": ["EXIT_UNRESOLVED"]}
    side_px = qx.bid if side == LONG else qx.ask
    if not (math.isfinite(side_px) and side_px > 0):
        return _side_missing(qx.event_at, qx.seq)
    px = (qx.bid - p.slip_price) if side == LONG else (qx.ask + p.slip_price)
    o = _exit(qx.event_at, px, "TIME_EXIT", fill_t, qx.seq, p.slip_price)
    o["overrun_s"] = qx.event_at - t_exit
    res = {"primary": o, "ambiguous_sl_tp": False, "mae_R": min(mae, (px - entry) * sgn / R), "mfe_R": mfe}
    if o["overrun_s"] > 300:
        res["flags_add"] = ["EXIT_OVERRUN_GAP"]
    return res


def _exit(t: float, px: float, reason: str, fill_t: float, seq=None, slip: float = 0.0) -> dict:
    return {"exit_at": iso_utc(t), "exit_price": px, "exit_reason": reason, "hold_s": t - fill_t,
            "exit_quote_seq": None if seq is None else int(seq), "exit_slippage_price": slip}


def _ts(iso: str) -> float:
    return dt.datetime.fromisoformat(iso.replace("Z", "+00:00")).timestamp()


def make_params(symbol: str, prof: dict, cost: dict, cost_name: str, latency_name: str, latency_s: float,
                common: dict, price_hint: float | None = None, risk: dict | None = None) -> ExecParams:
    # Existing valid profiles retain their parameter values/hashes; unknown commission remains None.
    required = economics_status(symbol, prof, cost, require_spread_floor=False)["reasons"]
    invalid = [r for r in required if r.startswith(("METADATA_", "COST_")) and not r.endswith(":contract_size")]
    if invalid:
        raise EconomicsUnavailable("ECONOMICS_UNKNOWN:" + ";".join(invalid))
    q = float(prof["trade_tick_size"])
    point = float(prof["point"])
    slip = float(cost["slippage_points_per_side"][symbol]) * point
    raw_cs = prof.get("contract_size")
    cs = raw_cs if _valid_number(raw_cs, positive=True) else None
    raw_comm = cost.get("commission_usd_per_lot_round_trip")
    comm_usd = raw_comm if _valid_number(raw_comm) else None
    comm_price = None
    if comm_usd is not None and float(comm_usd) == 0.0:
        comm_price = 0.0                                             # explicit ZERO bound, labelled by commission_status
    elif cs and comm_usd is not None:
        if prof.get("profit_currency") == "USD":
            comm_price = float(comm_usd) / float(cs)
        elif prof.get("base_currency") == "USD" and _valid_number(price_hint, positive=True):  # USDxxx own quote
            comm_price = float(comm_usd) / float(cs) * float(price_hint)
    sl_pts, fz_pts = prof.get("stops_level_points"), prof.get("freeze_level_points")
    return ExecParams(latency_s=latency_s, slip_price=slip, commission_price_rt=comm_price,
                      spread_guard=common["spread_guard_max_spread_over_R"], drift_guard_mult=common["entry_drift_guard_atr_mult"],
                      tp_R=common["tp_R_multiple"], max_hold_s=common["max_hold_minutes"] * 60,
                      deadline_s=common["entry_deadline_s_after_signal_close"], pre_close_s=common["pre_session_end_exit_s"],
                      q=q, stops_level_price=None if sl_pts is None else float(sl_pts) * point,
                      freeze_level_price=None if fz_pts is None else float(fz_pts) * point,
                      session=prof.get("session") or {}, latency_name=latency_name, cost_name=cost_name,
                      commission_status=cost.get("commission_status", "ASSUMED"),
                      commission_cash_per_lot_rt=None if comm_usd is None else float(comm_usd),
                      commission_cash_currency="USD" if comm_usd is not None else None,
                      contract={"contract_size": cs, "profit_currency": prof.get("profit_currency"), "base_currency": prof.get("base_currency")},
                      risk=risk)
