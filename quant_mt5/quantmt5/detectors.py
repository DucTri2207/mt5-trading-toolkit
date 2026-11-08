"""Setup A (H1 range breakout → M5 retest, branches M0/M1/M2) and Setup B (3-bar fakey, branches P0/P1/P2).

Implements setup-specs.md v0.1 §1–3, §5.1. The raw catalog is independent of branch gates, positions and outcomes.
Every record cites its source bars (open/close/available UTC), frozen levels, decision/ready time, gate reasons,
quality flags and a stable logical ID plus a revision ID (logical ID + the input values it was computed from).

Causality rules enforced here (beyond "use closed bars"):
* an anchor is usable only from `activated_at` (its 8 H1 + ATR bar available); a breakout bar that became available
  before activation is NOT turned into a retroactive episode;
* gates needing the H1 that closes at the same instant as the M5 candidate wait at most `sync_timeout_s`; if that H1
  is not available by then the gate is UNKNOWN (H1_SYNC_TIMEOUT), never filled from later data;
* P1 uses only the D1 of the broker trading day immediately preceding the mother's broker day (schedule-aware);
  if that day's D1 is missing / not yet available → UNKNOWN, never an older day.
"""
from __future__ import annotations

import datetime as dt
import math
from copy import deepcopy
from dataclasses import dataclass, field
from typing import Any

import numpy as np

from . import STRATEGY_VERSION
from .analysis_cache import cached
from .config import MetadataError, config_hash, profile, strategy, tick_size
from .data import Bars, load_bars, load_registry
from .features import SeriesCache
from .timemap import NY, UTC, server_to_utc
from .util import ceil_to_tick, hash_obj, iso_utc, stable_id

M5 = 300


def prefix_available(b: Bars) -> np.ndarray:
    """prefix_available[i] = max(available_at[0..i]): a recursive feature (ATR/EMA) at i is known only from then."""
    return np.maximum.accumulate(b.available_at) if len(b) else b.available_at


def causal_atr(atr5: np.ndarray, pav: np.ndarray, last_idx: int, freeze_t: float, warmup: int) -> dict:
    """ATR state usable at freeze_t: the latest index k' <= last_idx whose WHOLE prefix (seed history included)
    was available by freeze_t. Returns {ok, index, reason, stale_bars}."""
    if last_idx < 0:
        return {"ok": False, "reason": "ATR_WARMUP"}
    k = int(np.searchsorted(pav[:last_idx + 1], freeze_t, side="right")) - 1
    if k < warmup - 1:
        return {"ok": False, "reason": "ATR_WARMUP" if last_idx < warmup - 1 else "ATR_SOURCE_NOT_AVAILABLE_AT_FREEZE",
                "latest_fully_available_index": k}
    if not (math.isfinite(atr5[k]) and atr5[k] > 0):
        return {"ok": False, "reason": "ATR_NONFINITE"}
    return {"ok": True, "index": k, "stale_bars": int(last_idx - k)}


@dataclass
class SymbolData:
    symbol: str
    m5: Bars
    h1: Bars
    d1: Bars
    m1: Bars | None
    q: float
    prof: dict
    source_id: str
    cache_m5: SeriesCache = field(init=False)
    cache_h1: SeriesCache = field(init=False)

    def __post_init__(self):
        self.cache_m5 = SeriesCache(self.m5)
        self.cache_h1 = SeriesCache(self.h1)


def load_symbol(symbol: str, registry: dict | None = None, cut_available_at: float | None = None,
                pins: dict | None = None) -> SymbolData:
    """Load bars; optional cut keeps only bars available at/before the cut (prefix replay / snapshot).
    `pins` (from a snapshot's data_versions) forces the exact consumed content or raises DataVersionMismatch."""
    reg = registry or load_registry()
    prof = profile(symbol)
    q = tick_size(symbol, prof)  # raises MetadataError (never defaults)
    tfs = {tf: load_bars(symbol, tf, reg, pins=pins) for tf in ("M5", "H1", "D1", "M1")}
    for tf in ("M5", "H1", "D1"):
        if tfs[tf] is None:
            raise MetadataError(f"HISTORY_INSUFFICIENT:{symbol}:{tf}")
    key = hash_obj([symbol, cut_available_at, prof, q, reg["source_id"], pins,
                    {k: None if v is None else v.provenance for k, v in tfs.items()}])
    def build():
        view = {k: (v.upto_available(cut_available_at) if v is not None and cut_available_at is not None else v)
                for k, v in tfs.items()}
        return SymbolData(symbol, view["M5"], view["H1"], view["D1"], view["M1"], q, prof, reg["source_id"])
    return cached("symbol", key, build)


def _bar(b: Bars, i: int) -> dict:
    return {"index": int(i), "open_raw": int(b.open_raw[i]), "open_at": iso_utc(b.open_at[i]),
            "close_at": iso_utc(b.close_at[i]), "available_at": iso_utc(b.available_at[i]),
            "o": float(b.o[i]), "h": float(b.h[i]), "l": float(b.l[i]), "c": float(b.c[i]),
            "tick_volume": int(b.tick_volume[i]), "spread_field_points": int(b.spread[i])}


def _levels(q: float, atr_v: float, cfg: dict) -> tuple[float, float]:
    delta = ceil_to_tick(max(cfg["delta_min_ticks"] * q, cfg["delta_atr_mult"] * atr_v), q)
    buffer = ceil_to_tick(max(cfg["buffer_min_ticks"] * q, cfg["buffer_atr_mult"] * atr_v), q)
    return delta, buffer


VIEW_ONLY_FLAGS = ("ARRIVAL_HOLE_BARS_WITHHELD",)   # property of an as-of view, not of a decision's (fully arrived) inputs


def _quality(sd: SymbolData) -> list[str]:
    fl: set[str] = set()
    for b in (sd.m5, sd.h1, sd.d1):
        p = b.provenance
        fl.update(p.get("time_quality_flags", []))
        fl.update(f"{f}:{b.tf}" for f in p.get("data_quality_flags", []) if f not in VIEW_ONLY_FLAGS)
    return sorted(fl)


def _view_flags(sd: SymbolData) -> list[str]:
    out = []
    for b in (sd.m5, sd.h1, sd.d1):
        p = b.provenance
        if p.get("asof_withheld_rows"):
            out.append(f"ARRIVAL_HOLE_BARS_WITHHELD:{b.tf}:{p['asof_withheld_rows']} (first hole {p.get('asof_first_hole_open_at')})")
    return out


def _strategy_hash(cfg: dict) -> str:
    return hash_obj(cfg)[:16]


def _finish(rec: dict, inputs: Any, cfg: dict, quality: list[str], deadline_s: int) -> dict:
    """Common candidate fields: revision id, eligibility per branch, lifecycle, deadline, quality."""
    rec["revision_id"] = stable_id("REV", rec["candidate_id"], inputs, _strategy_hash(cfg))
    rec["eligibility"] = {g: {"PASS": "ELIGIBLE", "FAIL": "BLOCKED_BY_GATE", "UNKNOWN": "UNKNOWN"}[v["result"]] for g, v in rec["gates"].items()}
    deadline = rec["signal_close_ts"] + deadline_s
    if rec.get("episode_expires_ts"):
        deadline = min(deadline, rec["episode_expires_ts"])
    rec["entry_deadline_ts"] = int(deadline)
    rec["entry_deadline_at"] = iso_utc(deadline)
    known = rec.get("inputs_available_at", {}).get("prefix_known") or rec.get("detected_known_at") or rec["signal_bar"]["available_at"]
    rec["lifecycle"] = [{"state": "DETECTED", "event_at": iso_utc(rec["signal_close_ts"]), "available_at": known,
                         "reason": "SIGNAL_BAR_CLOSED; all pattern inputs known"},
                        {"state": "GATES_EVALUATED", "event_at": rec["ready_at"], "available_at": rec["ready_at"],
                         "reason": ",".join(f"{g}={v['result']}" for g, v in rec["gates"].items())}]
    rec["quality_flags"] = quality
    rec["execution_status"] = "NOT_EVALUATED_IN_B2 (quote-side fill/SL Ask/costs are B3)"
    return rec


# =========================================================================== Setup A
def detect_A(sd: SymbolData, cfg: dict | None = None) -> tuple[list[dict], list[dict]]:
    cfg = cfg or strategy()
    cc, ca = cfg["common"], cfg["setup_A"]
    m5, h1 = sd.m5, sd.h1
    q = sd.q
    eps = cc["epsilon_ticks"] * q
    atr5 = sd.cache_m5.get("atr14")
    ema50 = sd.cache_h1.get("ema50")
    pav5, pavh = prefix_available(m5), prefix_available(h1)
    n = len(m5)
    lookback = ca["h1_lookback_bars"]
    ttl = ca["episode_ttl_s_after_breakout_close"]
    quality = _quality(sd)
    episodes: list[dict] = []
    cands: list[dict] = []
    anchor_cache: dict[int, dict | None] = {}
    used: set[int] = set()
    active: dict | None = None
    diag = {"breakouts_before_anchor_activation": 0}

    def anchor(hh: int) -> dict | None:
        if hh in anchor_cache:
            return anchor_cache[hh]
        res = None
        j1 = int(np.searchsorted(h1.close_at, hh, side="right")) - 1
        if j1 >= lookback - 1 and int(h1.close_at[j1]) == hh:
            U = float(np.max(h1.h[j1 - lookback + 1:j1 + 1]))
            D = float(np.min(h1.l[j1 - lookback + 1:j1 + 1]))
            k5 = int(np.searchsorted(m5.close_at, hh, side="right")) - 1
            if U > D and k5 >= cc["warmup_m5_bars"] - 1 and math.isfinite(atr5[k5]) and atr5[k5] > 0:
                delta, buffer = _levels(q, float(atr5[k5]), cc)
                # anchor usable only when the event-ordered H1 prefix through its 8 bars AND the whole ATR seed prefix
                # up to k5 have arrived (same knowledge rule as the as-of view)
                act = float(max(pavh[j1], pav5[k5]))
                res = {"anchor_at": iso_utc(hh), "anchor_ts": hh, "U": U, "D": D,
                       "h1_bars": [{"open_at": iso_utc(h1.open_at[i]), "close_at": iso_utc(h1.close_at[i]), "available_at": iso_utc(h1.available_at[i]),
                                    "h": float(h1.h[i]), "l": float(h1.l[i]), "status": h1.status(i)} for i in range(j1 - lookback + 1, j1 + 1)],
                       "h1_first_open_at": iso_utc(h1.open_at[j1 - lookback + 1]), "h1_last_close_at": iso_utc(h1.close_at[j1]),
                       "h1_last_index": j1, "atr_frozen": float(atr5[k5]), "atr_bar_close_at": iso_utc(m5.close_at[k5]),
                       "delta": delta, "buffer": buffer, "activated_ts": act, "activated_at": iso_utc(act)}
        anchor_cache[hh] = res
        return res

    def close_episode(ep: dict, state: str, event_ts: float, avail_ts: float, reason: str):
        ep["state"] = state
        ep["transitions"].append({"state": state, "event_at": iso_utc(event_ts), "available_at": iso_utc(avail_ts), "reason": reason})

    for k in range(1, n):
        if active is not None:
            ep = active
            side = ep["side"]
            if m5.close_at[k] >= ep["expires_ts"]:
                close_episode(ep, "EXPIRED", ep["expires_ts"], ep["expires_ts"], "TTL_90M_AFTER_BREAKOUT_CLOSE")
                active = None
            elif m5.open_at[k] - m5.open_at[k - 1] != M5:
                close_episode(ep, "DATA_BLOCKED", m5.open_at[k], pav5[k], "M5_GAP_STATE_UNKNOWN")
                active = None
            else:
                U, D, delta = ep["U"], ep["D"], ep["delta"]
                o, h, l, c = m5.o[k], m5.h[k], m5.l[k], m5.c[k]
                if (side == "LONG" and c < U - delta) or (side == "SHORT" and c > D + delta):
                    close_episode(ep, "INVALIDATED", m5.close_at[k], pav5[k], "CLOSE_BACK_THROUGH_ZONE")
                    active = None
                else:
                    if side == "LONG":
                        ok = (U - delta <= l <= U + delta) and (c >= U + eps) and (c > o) and (h > l) and (2 * (c - l) >= h - l)
                    else:
                        ok = (D - delta <= h <= D + delta) and (c <= D - eps) and (c < o) and (h > l) and (2 * (h - c) >= h - l)
                    if ok:
                        cands.append(_candidate_A(sd, ep, k, ema50, eps, cc, cfg, quality, pavh, pav5))
        if active is None:
            hh = int(m5.open_at[k] // 3600 * 3600)
            if hh in used:
                continue
            a = anchor(hh)
            if a is None or m5.open_at[k] - m5.open_at[k - 1] != M5:
                continue
            c, cp = m5.c[k], m5.c[k - 1]
            side = None
            if c >= a["U"] + eps and cp < a["U"] + eps:
                side = "LONG"
            elif c <= a["D"] - eps and cp > a["D"] - eps:
                side = "SHORT"
            if side is None:
                continue
            known = float(pav5[k])           # the cross needs bar k-1's close too: known when the prefix through k arrived
            if known < a["activated_ts"]:
                diag["breakouts_before_anchor_activation"] += 1   # no retroactive episode from a late anchor
                continue
            used.add(hh)
            ep = {kk: v for kk, v in a.items()}
            ep.update({"episode_id": stable_id("EPA", sd.source_id, sd.symbol, STRATEGY_VERSION, hh, side),
                       "setup": "A", "symbol": sd.symbol, "side": side, "strategy_version": STRATEGY_VERSION,
                       "breakout_bar": _bar(m5, k), "breakout_close_at": iso_utc(m5.close_at[k]),
                       "breakout_close_ts": int(m5.close_at[k]), "breakout_available_at": iso_utc(known),
                       "breakout_known_ts": known, "predecessor_bar": _bar(m5, k - 1),
                       "expires_ts": int(m5.close_at[k] + ttl), "expires_at": iso_utc(m5.close_at[k] + ttl),
                       "quality_flags": quality,
                       "state": "WATCHING_RETEST", "transitions": [{"state": "WATCHING_RETEST", "event_at": iso_utc(m5.close_at[k]),
                                                                     "available_at": iso_utc(known), "reason": "BREAKOUT_CLOSE"}]})
            if known >= ep["expires_ts"]:
                # the cross only became knowable after the TTL: recorded, but it never offers an entry
                ep["state"] = "EXPIRED"
                ep["transitions"].append({"state": "EXPIRED", "event_at": ep["expires_at"], "available_at": iso_utc(known),
                                          "reason": "BREAKOUT_KNOWN_ONLY_AFTER_TTL"})
                ep["revision_id"] = stable_id("REV", ep["episode_id"], [a["U"], a["D"], a["atr_frozen"], ep["breakout_bar"], ep["predecessor_bar"], known],
                                              _strategy_hash(cfg))
                episodes.append(ep)
                continue
            ep["revision_id"] = stable_id("REV", ep["episode_id"], [a["U"], a["D"], a["atr_frozen"], ep["breakout_bar"], ep["predecessor_bar"], known],
                                          _strategy_hash(cfg))
            episodes.append(ep)
            active = ep
    if active is not None:
        active["state_note"] = "OPEN_AT_DATA_END"
    sd.diagnostics = diag            # run-level (depends on data length) — kept out of per-event records
    return episodes, cands


def _h1_for_candidate(h1: Bars, pavh: np.ndarray, k_close: float, k_known: float, timeout: float) -> tuple[int | None, float, str | None]:
    """H1 to use for a candidate closing at k_close whose M5 inputs are known at k_known. Returns (index|None, ready_ts,
    reason). H1 j counts as known when its event-ordered prefix has arrived (pavh[j]); the same-instant H1 (hour
    boundary) must be known within `timeout` after the M5; otherwise UNKNOWN."""
    j = int(np.searchsorted(h1.close_at, k_close, side="right")) - 1
    boundary = int(k_close) % 3600 == 0
    if boundary:
        if j >= 0 and int(h1.close_at[j]) == int(k_close):
            if pavh[j] <= k_known + timeout:
                return j, float(max(k_known, pavh[j])), None
            return None, float(k_known + timeout), "H1_SYNC_TIMEOUT"
        return None, float(k_known + timeout), "H1_SYNC_TIMEOUT_OR_MISSING"
    if j < 0:
        return None, float(k_known), "NO_H1"
    if pavh[j] > k_known:
        return None, float(k_known + timeout), "H1_LATE_ARRIVAL"
    return j, float(k_known), None


def _candidate_A(sd: SymbolData, ep: dict, k: int, ema50: np.ndarray, eps: float, cc: dict, cfg: dict, quality: list[str],
                 pavh: np.ndarray, pav5: np.ndarray) -> dict:
    m5, h1 = sd.m5, sd.h1
    side = ep["side"]
    k_known = float(pav5[k])     # retest + every earlier M5 (incl. breakout and its predecessor) have arrived
    j, ready, why = _h1_for_candidate(h1, pavh, float(m5.close_at[k]), k_known, cc["sync_timeout_s"])
    gates: dict[str, dict] = {"M0": {"result": "PASS", "rule": "no H1 gate", "evaluated_at": iso_utc(k_known)}}
    if j is None:
        gates["M1"] = {"result": "UNKNOWN", "reason": why, "evaluated_at": iso_utc(ready)}
        gates["M2"] = {"result": "UNKNOWN", "reason": why, "evaluated_at": iso_utc(ready)}
    else:
        h1c = float(h1.c[j])
        h1info = {"h1_open_at": iso_utc(h1.open_at[j]), "h1_close_at": iso_utc(h1.close_at[j]),
                  "h1_available_at": iso_utc(pavh[j]), "h1_close": h1c, "h1_status": h1.status(j), "evaluated_at": iso_utc(ready)}
        e = ema50[j]
        if j < cc["warmup_h1_bars_for_ema"] - 1 or not math.isfinite(e):
            gates["M1"] = {"result": "UNKNOWN", "reason": "EMA50_WARMUP", "h1_bars_available": j + 1, **h1info}
        elif pavh[j] > ready:
            gates["M1"] = {"result": "UNKNOWN", "reason": "EMA_SOURCE_NOT_AVAILABLE_AT_DECISION",
                           "ema_prefix_available_at": iso_utc(pavh[j]), **h1info}
        else:
            pas = h1c > e if side == "LONG" else h1c < e
            gates["M1"] = {"result": "PASS" if pas else "FAIL", "ema50": float(e), **h1info}
        fresh = int(h1.close_at[j]) >= ep["breakout_close_ts"]
        beyond = (h1c >= ep["U"] + eps) if side == "LONG" else (h1c <= ep["D"] - eps)
        gates["M2"] = {"result": "PASS" if (fresh and beyond) else "FAIL", "edge": "U" if side == "LONG" else "D",
                       "h1_closed_after_breakout": fresh, "h1_close_beyond_edge": beyond, **h1info}
    level = ep["U"] if side == "LONG" else ep["D"]
    rec = {"candidate_id": stable_id("CA", sd.source_id, sd.symbol, STRATEGY_VERSION, ep["episode_id"], int(m5.open_at[k])),
           "setup": "A", "symbol": sd.symbol, "side": side, "strategy_version": STRATEGY_VERSION,
           "episode_id": ep["episode_id"], "anchor_at": ep["anchor_at"], "signal_bar": _bar(m5, k), "signal_index": k,
           "signal_close_ts": int(m5.close_at[k]), "ready_ts": int(math.ceil(ready)), "ready_at": iso_utc(math.ceil(ready)),
           "level": level, "zone": {"U": ep["U"], "D": ep["D"]}, "delta": ep["delta"], "buffer": ep["buffer"],
           "atr_frozen": ep["atr_frozen"], "atr_bar_close_at": ep["atr_bar_close_at"], "epsilon": eps,
           "episode_expires_ts": ep["expires_ts"], "breakout_close_at": ep["breakout_close_at"], "gates": gates,
           "detected_known_at": iso_utc(k_known), "episode_known_at": ep["breakout_available_at"],
           "retest_depth_over_atr": ((ep["U"] - m5.l[k]) if side == "LONG" else (m5.h[k] - ep["D"])) / ep["atr_frozen"]}
    # every semantic dependency of this decision (episode revision = anchor zone/ATR/breakout bar; expiry; gate records)
    inputs = {"signal_bar": rec["signal_bar"], "episode_revision": ep["revision_id"], "breakout_close_ts": ep["breakout_close_ts"],
              "expires_ts": ep["expires_ts"], "zone": rec["zone"], "atr_frozen": rec["atr_frozen"], "delta": rec["delta"],
              "buffer": rec["buffer"], "gates": gates, "ready_ts": rec["ready_ts"]}
    return _finish(rec, inputs, cfg, quality, cc["entry_deadline_s_after_signal_close"])


# =========================================================================== Setup B
class _PrevDay:
    """Broker day immediately preceding the mother's broker day.

    Broker day boundary:
    * declared `session["d1_boundary"] = {"tz", "day_start"}` → days start at that local time; D1 bars are matched by
      open_at (UTC) == day start;
    * otherwise the stored D1 convention: server-date buckets of the raw timestamp (open_raw // 86400) interpreted with
      the dataset clock profile (legacy: ASSUMED). D1 bars are matched by open_raw.
    A broker day is skipped only if the schedule says it is closed for the WHOLE day (zero open minutes). Short sessions
    (e.g. a 2-hour Sunday) are trading days. No schedule → only the previous calendar day is acceptable. The expected
    day without a D1 bar → UNKNOWN (never an older day)."""

    def __init__(self, sd: SymbolData):
        self.sd = sd
        self.sess = sd.prof.get("session") or {}
        self.bnd = self.sess.get("d1_boundary")
        self.clock = sd.m5.provenance.get("clock_profile", "RAW_IS_UTC")
        self.clock_status = sd.m5.provenance.get("clock_profile_status")
        d1 = sd.d1
        self.by_key = ({int(t): i for i, t in enumerate(d1.open_at)} if self.bnd else {int(t): i for i, t in enumerate(d1.open_raw)})
        self._cache: dict[int, tuple] = {}

    def basis(self) -> str:
        if self.bnd:
            return f"DECLARED_BOUNDARY {self.bnd.get('day_start', '00:00')} {self.bnd.get('tz', 'UTC')} ({self.bnd.get('status', 'status not given')})"
        return f"RAW_DAY_BUCKET (clock {self.clock}, {self.clock_status})"

    def _day_bounds(self, key: int) -> tuple[int, int]:
        """UTC [start, end) of a broker day identified by key (declared: local midnight-ish UTC start; raw: raw day start)."""
        if self.bnd:
            from zoneinfo import ZoneInfo
            tz = dt.timezone.utc if self.bnd.get("tz", "UTC") == "UTC" else ZoneInfo(self.bnd["tz"])
            hh, mm = map(int, self.bnd.get("day_start", "00:00").split(":"))
            d = dt.datetime.fromtimestamp(key, dt.timezone.utc).astimezone(tz).date()
            nd = d + dt.timedelta(days=1)
            return key, int(dt.datetime(nd.year, nd.month, nd.day, hh, mm, tzinfo=tz).timestamp())
        return int(server_to_utc(key, self.clock)[0]), int(server_to_utc(key + 86400, self.clock)[0])

    def day_key_of(self, m5_index: int) -> int:
        m5 = self.sd.m5
        if not self.bnd:
            return int(m5.open_raw[m5_index] // 86400 * 86400)
        from zoneinfo import ZoneInfo
        tz = dt.timezone.utc if self.bnd.get("tz", "UTC") == "UTC" else ZoneInfo(self.bnd["tz"])
        hh, mm = map(int, self.bnd.get("day_start", "00:00").split(":"))
        loc = dt.datetime.fromtimestamp(int(m5.open_at[m5_index]), dt.timezone.utc).astimezone(tz)
        d = loc.date() if (loc.hour, loc.minute) >= (hh, mm) else loc.date() - dt.timedelta(days=1)
        return int(dt.datetime(d.year, d.month, d.day, hh, mm, tzinfo=tz).timestamp())

    def _prev_key(self, key: int) -> int:
        if not self.bnd:
            return key - 86400
        a, _ = self._day_bounds(key)
        from zoneinfo import ZoneInfo
        tz = dt.timezone.utc if self.bnd.get("tz", "UTC") == "UTC" else ZoneInfo(self.bnd["tz"])
        hh, mm = map(int, self.bnd.get("day_start", "00:00").split(":"))
        d = dt.datetime.fromtimestamp(a, dt.timezone.utc).astimezone(tz).date() - dt.timedelta(days=1)
        return int(dt.datetime(d.year, d.month, d.day, hh, mm, tzinfo=tz).timestamp())

    def _open_minutes(self, key: int) -> int:
        from .coverage import scheduled_open
        a, b = self._day_bounds(key)
        return int(scheduled_open(np.arange(a, b, 60, dtype=np.int64), self.sess).sum())

    def expected(self, key: int) -> tuple[int | None, str, list[str]]:
        """(expected previous day key | None, rule, skipped closed days)."""
        if key in self._cache:
            return self._cache[key]
        if not self.sess or self.sess.get("tz") != "America/New_York":
            res = (self._prev_key(key), "NO_SCHEDULE_PREVIOUS_CALENDAR_DAY; " + self.basis(), [])
        else:
            res, skipped, d = (None, "NO_SCHEDULED_TRADING_DAY_WITHIN_7_DAYS; " + self.basis(), []), [], key
            for _ in range(7):
                d = self._prev_key(d)
                if self._open_minutes(d) > 0:
                    res = (d, "SCHEDULE (skip only fully-closed days); " + self.basis(), skipped)
                    break
                skipped.append(self.label(d))
        self._cache[key] = res
        return res

    def label(self, key: int) -> str:
        a, _ = self._day_bounds(key)
        if self.bnd:
            from zoneinfo import ZoneInfo
            tz = dt.timezone.utc if self.bnd.get("tz", "UTC") == "UTC" else ZoneInfo(self.bnd["tz"])
            return dt.datetime.fromtimestamp(a, dt.timezone.utc).astimezone(tz).strftime("%Y-%m-%d")
        return _day(key)


def detect_B(sd: SymbolData, cfg: dict | None = None) -> list[dict]:
    cfg = cfg or strategy()
    cc, cb = cfg["common"], cfg["setup_B"]
    m5, d1 = sd.m5, sd.d1
    q = sd.q
    eps = cc["epsilon_ticks"] * q
    atr5 = sd.cache_m5.get("atr14")
    o, h, l, c = m5.o, m5.h, m5.l, m5.c
    w0, w1 = (int(x[:2]) * 60 + int(x[3:]) for x in cb["p2_window_ny"])
    quality = _quality(sd)
    prev_day = _PrevDay(sd)
    d1_index = prev_day.by_key
    pav5, pavd = prefix_available(m5), prefix_available(d1)
    tb = f"clock_profile={m5.provenance.get('clock_profile')} ({m5.provenance.get('clock_profile_status')}); {m5.provenance.get('time_basis_status')}; TIME_UNVERIFIED"
    out: list[dict] = []
    n = len(m5)
    for k in range(2, n):
        im, ii, f = k - 2, k - 1, k
        if m5.open_at[ii] - m5.open_at[im] != M5 or m5.open_at[f] - m5.open_at[ii] != M5:
            continue
        HM, LM = h[im], l[im]
        if not (h[ii] <= HM - eps and l[ii] >= LM + eps):
            continue
        side = None
        if LM <= o[f] <= HM and l[f] <= LM - eps and h[f] <= HM and LM + eps <= c[f] <= HM - eps and c[f] > o[f]:
            side = "LONG"
        elif LM <= o[f] <= HM and h[f] >= HM + eps and l[f] >= LM and LM + eps <= c[f] <= HM - eps and c[f] < o[f]:
            side = "SHORT"
        if side is None:
            continue
        # ATR frozen before mother open: latest prefix whose every bar (seed history included) was available by then
        ka_close = int(np.searchsorted(m5.close_at[:im], m5.open_at[im], side="right")) - 1
        st = causal_atr(atr5, pav5, ka_close, float(m5.open_at[im]), cc["warmup_m5_bars"])
        atr_ok = st["ok"]
        ka = st.get("index", -1)
        rec: dict[str, Any] = {
            "candidate_id": stable_id("CB", sd.source_id, sd.symbol, STRATEGY_VERSION, int(m5.open_at[im]), side),
            "setup": "B", "symbol": sd.symbol, "side": side, "strategy_version": STRATEGY_VERSION,
            "mother_bar": _bar(m5, im), "inside_bar": _bar(m5, ii), "signal_bar": _bar(m5, f), "signal_index": f,
            # decided only when mother, inside, fakey AND every earlier M5 (ATR seed) have arrived: prefix-known time of F
            "signal_close_ts": int(m5.close_at[f]), "ready_ts": int(math.ceil(pav5[f])), "ready_at": iso_utc(math.ceil(pav5[f])),
            "inputs_available_at": {"mother": iso_utc(m5.available_at[im]), "inside": iso_utc(m5.available_at[ii]),
                                    "fakey": iso_utc(m5.available_at[f]), "prefix_known": iso_utc(pav5[f])},
            "epsilon": eps, "episode_id": None, "episode_expires_ts": None}
        ev = iso_utc(math.ceil(pav5[f]))
        gates: dict[str, dict] = {"P0": {"result": "PASS", "rule": "3-bar fakey geometry only (needs epsilon, not ATR)", "evaluated_at": ev}}
        if not atr_ok:
            rec.update({"atr_frozen": None, "delta": None, "buffer": None, "atr_source": st})
            gates["P1"] = {"result": "UNKNOWN", "reason": st["reason"], "evaluated_at": ev}
            gates["P2"] = {"result": "UNKNOWN", "reason": "P1_UNKNOWN", "evaluated_at": ev}
        else:
            delta, buffer = _levels(q, float(atr5[ka]), cc)
            rec.update({"atr_frozen": float(atr5[ka]), "atr_bar_close_at": iso_utc(m5.close_at[ka]), "delta": delta, "buffer": buffer,
                        "atr_source": {"basis": "LATEST_FULLY_AVAILABLE_PREFIX_BEFORE_MOTHER_OPEN", "index": ka,
                                       "bar_close_at": iso_utc(m5.close_at[ka]), "bar_available_at": iso_utc(m5.available_at[ka]),
                                       "prefix_available_at": iso_utc(pav5[ka]), "freeze_at": iso_utc(m5.open_at[im]),
                                       "stale_bars": st["stale_bars"]},
                        "overshoot_over_atr": ((LM - l[f]) if side == "LONG" else (h[f] - HM)) / float(atr5[ka]),
                        "reclaim_over_atr": ((c[f] - LM) if side == "LONG" else (HM - c[f])) / float(atr5[ka])})
            day_key = prev_day.day_key_of(im)
            exp_key, basis, skipped = prev_day.expected(day_key)
            p1: dict[str, Any] = {"mother_broker_day": prev_day.label(day_key), "prev_day_rule": basis, "skipped_closed_days": skipped,
                                  "evaluated_at": ev}
            if exp_key is None:
                p1.update({"result": "UNKNOWN", "reason": "PREV_TRADING_DAY_NOT_DETERMINED"})
            elif exp_key not in d1_index:
                p1.update({"result": "UNKNOWN", "reason": "PREV_D1_MISSING", "prev_day_expected": prev_day.label(exp_key)})
            else:
                pd_i = d1_index[exp_key]
                if pavd[pd_i] > m5.open_at[im]:
                    p1.update({"result": "UNKNOWN", "reason": "PREV_D1_NOT_AVAILABLE_BEFORE_MOTHER", "prev_day_id": prev_day.label(exp_key),
                               "prev_day_available_at": iso_utc(pavd[pd_i])})
                else:
                    PDH, PDL = float(d1.h[pd_i]), float(d1.l[pd_i])
                    if side == "LONG":
                        pas = abs(LM - PDL) <= delta and l[f] <= PDL - eps and c[f] >= PDL + eps
                    else:
                        pas = abs(HM - PDH) <= delta and h[f] >= PDH + eps and c[f] <= PDH - eps
                    p1.update({"result": "PASS" if pas else "FAIL", "prev_day_id": prev_day.label(exp_key), "PDH": PDH, "PDL": PDL,
                               "prev_day_available_at": iso_utc(pavd[pd_i]), "d1_kind": d1.provenance.get("kind"),
                               "d1_status": d1.status(pd_i), "level_used": PDL if side == "LONG" else PDH})
            gates["P1"] = p1
            ny = dt.datetime.fromtimestamp(int(m5.close_at[f]), UTC).astimezone(NY)
            mins = ny.hour * 60 + ny.minute
            in_win = w0 <= mins < w1
            p2 = ({"result": "UNKNOWN", "reason": "P1_UNKNOWN"} if p1["result"] == "UNKNOWN"
                  else {"result": "PASS" if (p1["result"] == "PASS" and in_win) else "FAIL"})
            p2.update({"signal_close_ny": ny.strftime("%Y-%m-%d %H:%M %Z"), "in_window": in_win, "window_ny": cb["p2_window_ny"],
                       "time_basis": tb, "evaluated_at": ev})
            gates["P2"] = p2
        rec["gates"] = gates
        inputs = {"mother": rec["mother_bar"], "inside": rec["inside_bar"], "fakey": rec["signal_bar"], "atr_frozen": rec.get("atr_frozen"),
                  "atr_source": rec.get("atr_source"), "delta": rec.get("delta"), "buffer": rec.get("buffer"), "gates": gates,
                  "ready_ts": rec["ready_ts"]}
        out.append(_finish(rec, inputs, cfg, quality, cc["entry_deadline_s_after_signal_close"]))
    return out


def _day(raw: int) -> str:
    return dt.datetime.fromtimestamp(int(raw), UTC).strftime("%Y-%m-%d")


def detect_all(sd: SymbolData, cfg: dict | None = None) -> dict:
    cfg = cfg or strategy()
    # Hold the SymbolData alongside its result, preventing object-id reuse while
    # the catalog is cached. Copies isolate report/replay caller annotations.
    entry = cached("catalog", (id(sd), _strategy_hash(cfg)), lambda: (sd, _detect_all(sd, cfg)))
    return deepcopy(entry[1])


def _detect_all(sd: SymbolData, cfg: dict) -> dict:
    eps_, ca = detect_A(sd, cfg)
    cb = detect_B(sd, cfg)
    return {"episodes": eps_, "candidates": ca + cb,
            "catalog_meta": {"strategy_version": STRATEGY_VERSION, "strategy_hash": _strategy_hash(cfg or strategy()),
                             "symbol": sd.symbol, "source_id": sd.source_id,
                             "bars": {"M5": len(sd.m5), "H1": len(sd.h1), "D1": len(sd.d1)},
                             "data_through": iso_utc(sd.m5.close_at[-1]) if len(sd.m5) else None,
                             "quality_flags": _quality(sd), "view_flags": _view_flags(sd),
                             "diagnostics": getattr(sd, "diagnostics", {})}}
