"""Read-only MT5 collector (B1 live path).

Safety contract:
* attaches ONLY to a terminal64.exe that is already running at the explicitly chosen path; never launches one
  (mt5.initialize(path) would start a terminal if none is running, so we check the process list first);
* the MetaTrader5 module is wrapped by ReadOnlyMT5, which exposes a whitelist of read calls only
  (no order_send/order_check/positions_*/history_* writes exist in this code path);
* timestamps are stored exactly as the API returns them under the registry's API_UTC_CONTRACT (documented as
  UTC, no offset applied) plus a clock probe as evidence; this path is separate from the legacy-cache hypothesis.

Storage contract (ChunkStore):
* small windows (bars: days/weeks; ticks: hours) → bounded RAM; nothing is accumulated across windows except the
  pending boundary tick group;
* each window's data is committed as an immutable chunk (atomic tmp+rename, sha256). A chunk name that already
  exists with different bytes is never overwritten: the new bytes go to `<name>.revN` and a SOURCE_CONFLICT is logged;
* `checkpoint.json` is written atomically AFTER the chunk; a crash in between is safe (the rerun finds the identical
  chunk and reuses it);
* tick cursor = `committed_through_ms` (exclusive) + persisted pending group (last, possibly incomplete ms group).
  Restart re-reads the pending second and merges by order & multiplicity (no `last_time_msc + 1`);
* coverage is per requested window: OK / EMPTY_MARKET_CLOSED / EMPTY_UNEXPLAINED / ERROR_NONE_RETURNED /
  ERROR_INVALID_BATCH / NOT_ATTEMPTED. A run is OK only if every window is OK or EMPTY_MARKET_CLOSED.
"""
from __future__ import annotations

import io
import json
import os
import subprocess
from functools import wraps
from pathlib import Path
from typing import Any, Callable

import numpy as np

from .timemap import server_to_utc, utc_to_server
from .retention import ensure_tick_generation, storage_lease
from .util import STORE_DIR, atomic_write_bytes, atomic_write_json, hash_obj, iso_utc, now_utc, parse_utc, sha256_bytes, sha256_file

READ_ONLY_CALLS = frozenset({"initialize", "shutdown", "version", "last_error", "terminal_info", "account_info", "symbol_info",
                             "symbol_info_tick", "symbols_get", "copy_rates_range", "copy_rates_from_pos", "copy_ticks_range",
                             "TIMEFRAME_M1", "TIMEFRAME_M5", "TIMEFRAME_H1", "TIMEFRAME_D1", "COPY_TICKS_ALL",
                             # pure calculators used by B3 parity (no order is sent): order_calc_profit / order_calc_margin
                             "order_calc_profit", "order_calc_margin", "ORDER_TYPE_BUY", "ORDER_TYPE_SELL"})
BAR_WINDOW_S = {"M1": 86400, "M5": 7 * 86400, "H1": 31 * 86400, "D1": 366 * 86400}
TF_S = {"M1": 60, "M5": 300, "H1": 3600, "D1": 86400}
OK_WINDOW = ("OK", "EMPTY_MARKET_CLOSED")


def _storage_leased(parameter: str, position: int | None = None):
    """Keep collection and end-of-session cleanup mutually exclusive."""
    def decorate(fn):
        @wraps(fn)
        def run(*args, **kwargs):
            path = kwargs.get(parameter)
            if path is None and position is not None and len(args) > position:
                path = args[position]
            with storage_lease(path or STORE_DIR / "raw"):
                return fn(*args, **kwargs)
        return run
    return decorate


class ReadOnlyMT5:
    def __init__(self, module):
        object.__setattr__(self, "_m", module)

    def __getattr__(self, name):
        if name not in READ_ONLY_CALLS:
            raise PermissionError(f"READ_ONLY_GUARD: '{name}' is not an allowed read call")
        return getattr(object.__getattribute__(self, "_m"), name)

    def __setattr__(self, k, v):
        raise PermissionError("READ_ONLY_GUARD")


def running_terminal_paths() -> list[str]:
    """Paths of running terminal64.exe processes (PowerShell); [] if none / not on Windows."""
    try:
        out = subprocess.run(["powershell", "-NoProfile", "-Command",
                              "Get-Process terminal64 -ErrorAction SilentlyContinue | ForEach-Object { $_.Path }"],
                             capture_output=True, text=True, timeout=30)
        return [os.path.normcase(os.path.abspath(p.strip())) for p in out.stdout.splitlines() if p.strip()]
    except (OSError, subprocess.SubprocessError):
        return []


# ------------------------------------------------------------------ tick merge (pure, testable)
def merge_tick_batch(stored: np.ndarray, pending_ms: int | None, batch: np.ndarray) -> tuple[np.ndarray, int | None, list[dict]]:
    """Merge a batch fetched from `pending_ms` (inclusive) onwards.

    stored  : ticks held so far (structured, field time_msc, sorted, source order preserved) — includes the
              pending boundary group at its tail.
    pending : ms of the last (possibly incomplete) group in `stored`, or None.
    batch   : ticks returned for [pending_ms, …], source order.
    Returns (new_stored, new_pending_ms, conflicts). The boundary group in `batch` must start with the stored group
    (same order & multiplicity) — extra records are appended; a mismatch is a SOURCE_CONFLICT and the stored version
    is kept. The new last group becomes pending."""
    conflicts: list[dict] = []
    has_known_group = pending_ms is not None and len(stored) and bool((stored["time_msc"] == pending_ms).any())
    if len(batch) == 0 and not has_known_group:
        return stored, pending_ms, conflicts
    if pending_ms is not None and len(stored):
        old_grp = stored[stored["time_msc"] == pending_ms]
        new_grp = batch[batch["time_msc"] == pending_ms] if len(batch) else batch
        rest = batch[batch["time_msc"] > pending_ms] if len(batch) else batch
        if len(new_grp) < len(old_grp) or not np.array_equal(new_grp[:len(old_grp)], old_grp):
            conflicts.append({"time_msc": int(pending_ms), "stored": int(len(old_grp)), "fetched": int(len(new_grp)),
                              "reason": "SOURCE_CONFLICT_PENDING_GROUP_MISSING_ON_REREAD" if len(new_grp) == 0 else "SOURCE_CONFLICT_BOUNDARY_GROUP"})
            extra = new_grp[:0]
        else:
            extra = new_grp[len(old_grp):]
        if (batch["time_msc"] < pending_ms).any():
            conflicts.append({"reason": "BATCH_STARTS_BEFORE_PENDING", "time_msc": int(batch["time_msc"].min())})
        merged = np.concatenate([stored, extra, rest])
    else:
        merged = np.concatenate([stored, batch]) if len(stored) else batch
    new_pending = int(merged["time_msc"][-1]) if len(merged) else None
    return merged, new_pending, conflicts


# ------------------------------------------------------------------ chunk store
def _npz_bytes(**arrays) -> bytes:
    bio = io.BytesIO()
    np.savez(bio, **arrays)
    return bio.getvalue()


def commit_chunk(dirpath: Path, name: str, key: str, array: np.ndarray) -> dict:
    """Write once. Same name + same bytes → reused; different bytes → `<name>.revN.npz` + SOURCE_CONFLICT."""
    data = _npz_bytes(**{key: array})
    sha = sha256_bytes(data)
    p = dirpath / f"{name}.npz"
    if p.exists():
        if sha256_file(p) == sha:
            return {"file": p.name, "sha256": sha, "rows": int(len(array)), "commit": "REUSED_IDENTICAL"}
        k = 2
        while (dirpath / f"{name}.rev{k}.npz").exists():
            if sha256_file(dirpath / f"{name}.rev{k}.npz") == sha:
                return {"file": f"{name}.rev{k}.npz", "sha256": sha, "rows": int(len(array)), "commit": "REUSED_IDENTICAL_REVISION",
                        "conflict": "SOURCE_CONFLICT:CHUNK_REVISION"}
            k += 1
        p2 = dirpath / f"{name}.rev{k}.npz"
        atomic_write_bytes(p2, data)
        return {"file": p2.name, "sha256": sha, "rows": int(len(array)), "commit": "NEW_REVISION",
                "conflict": "SOURCE_CONFLICT:CHUNK_REVISION", "conflicts_with": p.name}
    atomic_write_bytes(p, data)
    return {"file": p.name, "sha256": sha, "rows": int(len(array)), "commit": "NEW"}


def load_checkpoint(dirpath: Path) -> dict | None:
    p = dirpath / "checkpoint.json"
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else None


def save_checkpoint(dirpath: Path, ck: dict) -> None:
    ck["updated_at"] = iso_utc(now_utc())
    atomic_write_json(dirpath / "checkpoint.json", ck)


def read_tick_chunks(dirpath: Path, t0_ms: int | None = None, t1_ms: int | None = None, verify: bool = True) -> np.ndarray:
    """Lazily read only committed tick chunks overlapping [t0_ms, t1_ms]; sha-verified. Pending group excluded."""
    ck = load_checkpoint(dirpath)
    if ck is None:
        raise FileNotFoundError(f"NO_CHECKPOINT:{dirpath}")
    out = []
    for ch in ck["chunks"]:
        if t0_ms is not None and ch["last_ms"] < t0_ms or t1_ms is not None and ch["first_ms"] > t1_ms:
            continue
        p = dirpath / ch["file"]
        if verify and sha256_file(p) != ch["sha256"]:
            from .data import ChunkCorrupt
            raise ChunkCorrupt(f"CHUNK_CORRUPT:{p}")
        with np.load(p, allow_pickle=False) as z:
            a = z["ticks"]
        if t0_ms is not None or t1_ms is not None:
            m = np.ones(len(a), bool)
            if t0_ms is not None:
                m &= a["time_msc"] >= t0_ms
            if t1_ms is not None:
                m &= a["time_msc"] <= t1_ms
            a = a[m]
        out.append(a)
    return np.concatenate(out) if out else np.zeros(0)


def verify_store(dirpath: Path) -> dict:
    ck = load_checkpoint(dirpath)
    if ck is None:
        return {"status": "NO_CHECKPOINT"}
    bad = [ch["file"] for ch in ck["chunks"] if not (dirpath / ch["file"]).exists() or sha256_file(dirpath / ch["file"]) != ch["sha256"]]
    win = ck.get("windows", {})
    incomplete = [k for k, w in win.items() if w.get("status") not in OK_WINDOW]
    return {"status": "OK" if not bad and not incomplete else "INCOMPLETE_OR_CORRUPT", "corrupt_or_missing_chunks": bad,
            "windows_total": len(win), "windows_not_ok": incomplete, "orphan_tmp_files": sorted(p.name for p in dirpath.glob("*.tmp"))}


# ------------------------------------------------------------------ schedule (for EMPTY classification only)
# ------------------------------------------------------------------ source clock policy (B6C 043 F2)
CLOCK_POLICY_VERSION = "source-clock-policy-v1"
CLOCK_CANDIDATES = ("RAW_IS_UTC", "EET_EU", "NY_PLUS_7")        # preference order when several match the current offset


def raw_of(utc_ts: float, clock: str) -> int:
    """UTC epoch second -> the source's numeric (raw) time under `clock` (API request bounds only)."""
    return int(utc_ts) if clock == "RAW_IS_UTC" else int(utc_to_server(int(utc_ts), clock))


def utc_of(raw, clock: str) -> np.ndarray:
    raw = np.asarray(raw, dtype=np.int64)
    return raw if clock == "RAW_IS_UTC" else server_to_utc(raw, clock)


def _profile_offset_now(profile: str, now: float) -> int:
    return raw_of(now, profile) - int(now)


def resolve_source_clock(probes: dict, explicit: str | None = None, now: float | None = None) -> dict:
    """One clock profile for the whole source (all symbols, bars AND ticks). Evidence = the current fresh-tick probes only:
    * fresh probes disagree, or an explicit/pinned profile contradicts a fresh probe -> CLOCK_CONFLICT (nothing collected)
    * fresh offset 0 -> RAW_IS_UTC; 7200/10800 -> first matching candidate (EET_EU before NY_PLUS_7), others recorded
    * no fresh probe -> explicit/pinned profile if given, else RAW_IS_UTC labelled UNRESOLVED (flag CLOCK_UNRESOLVED)
    Never VERIFIED: one current probe says nothing about historical DST or the PC clock accuracy."""
    now = now_utc() if now is None else now
    fresh = {s: int(p["nearest_whole_offset_s"]) for s, p in probes.items()
             if str(p.get("assessment", "")).startswith("FRESH_TICK_CONSISTENT")}
    offs = sorted(set(fresh.values()))
    base = {"policy": CLOCK_POLICY_VERSION, "resolved_at": iso_utc(now), "fresh_offsets_s": offs, "explicit": explicit,
            "probes": {s: {k: p.get(k) for k in ("assessment", "nearest_whole_offset_s", "residual_s", "delta_tick_minus_local_s")}
                       for s, p in sorted(probes.items())},
            "caveat": "current-probe assumption only; historical DST, legacy data and the PC clock are NOT verified"}
    if explicit is not None and explicit not in CLOCK_CANDIDATES:
        return {**base, "status": "CLOCK_CONFLICT", "reason": f"UNKNOWN_CLOCK_PROFILE:{explicit}"}
    if len(offs) > 1:
        return {**base, "status": "CLOCK_CONFLICT", "reason": "FRESH_PROBES_DISAGREE", "by_symbol": fresh}
    matching = [c for c in CLOCK_CANDIDATES if offs and _profile_offset_now(c, now) == offs[0]]
    if explicit is not None:
        if offs and explicit not in matching:
            return {**base, "status": "CLOCK_CONFLICT", "reason": f"PINNED_{explicit}_CONTRADICTS_FRESH_OFFSET_{offs[0]}_S"}
        # The interpretation label stays the PIN's (only probe-resolved profiles are pinned): a per-call recheck outcome must not
        # change candidate revisions (gate time_basis) or the journal would record the same signal again. Recheck kept apart.
        off = _profile_offset_now(explicit, now)
        return {**base, "status": "RESOLVED", "profile": explicit, "offset_now_s": off,
                "clock_profile_status": "ASSUMED_FROM_CURRENT_PROBE", "pinned_by_session": True,
                "recheck": "CONSISTENT_WITH_CURRENT_PROBE" if offs else "NOT_RECHECKED_NO_FRESH_PROBE",
                "alternatives": [c for c in CLOCK_CANDIDATES if c != explicit and _profile_offset_now(c, now) == off],
                "flags": [] if offs else ["CLOCK_NOT_RECHECKED_NO_FRESH_PROBE"]}
    if not offs:
        return {**base, "status": "RESOLVED", "profile": "RAW_IS_UTC", "offset_now_s": 0,
                "clock_profile_status": "UNRESOLVED_NO_FRESH_PROBE_API_DOC_DEFAULT",
                "alternatives": [c for c in CLOCK_CANDIDATES if c != "RAW_IS_UTC"], "flags": ["CLOCK_UNRESOLVED"]}
    if not matching:
        return {**base, "status": "CLOCK_CONFLICT", "reason": f"UNSUPPORTED_OFFSET_{offs[0]}_S"}
    return {**base, "status": "RESOLVED", "profile": matching[0], "offset_now_s": offs[0],
            "clock_profile_status": "ASSUMED_FROM_CURRENT_PROBE", "alternatives": matching[1:], "flags": []}


def window_fully_closed(w0: float, w1: float, session: dict | None) -> bool:
    """True if [w0, w1) lies entirely inside a scheduled closure (weekend / daily break) of the symbol profile."""
    if not session:
        return False
    from .coverage import scheduled_open
    ts = np.arange(int(w0), int(w1), 60, dtype=np.int64)
    return bool(len(ts)) and not scheduled_open(ts, session).any()


# ------------------------------------------------------------------ bars
def _bar_window_bounds(key: str, rec: dict) -> tuple[int, int]:
    """Actual queried open-time bounds, including legacy forming-tail cuts."""
    if rec.get("requested_from") and rec.get("requested_to_inclusive"):
        return int(parse_utc(rec["requested_from"])), int(parse_utc(rec["requested_to_inclusive"])) + 1
    a, b = key.split("_")
    return int(a), int(b)


def _incremental_requests(ck: dict, start: int, stop: int, window_s: int, request_end: int):
    """Retry incomplete windows unchanged; fetch only uncovered open-time ranges.

    Completed immutable windows remain reusable when a rolling lookback moves.
    New ranges are split into bounded immutable fragments.
    The final window ends at the closed-bar bound, so its forming tail is never
    mistaken for complete coverage on the next scan.
    """
    requests, covered, expected = [], [], []
    for key, rec in ck["windows"].items():
        a, b = _bar_window_bounds(key, rec)
        if a >= stop or b <= start:
            continue
        expected.append(key)
        covered.append((max(a, start), min(b, stop)))
        if rec.get("status") not in OK_WINDOW:
            requests.append((key, a, min(b, stop)))
    cursor = start
    missing = []
    for a, b in sorted(covered):
        if a > cursor:
            missing.append((cursor, a))
        cursor = max(cursor, b)
    if cursor < stop:
        missing.append((cursor, stop))
    for a, b in missing:
        while a < b:
            edge = min(b, a + window_s)
            # Preserve the legacy window label; only its *actual* queried open
            # interval above is reusable, never an unqueried forming tail.
            key = f"{a}_{request_end if edge == stop else edge}"
            requests.append((key, a, edge))
            expected.append(key)
            a = edge
    return sorted(requests, key=lambda x: (x[1], x[2], x[0])), list(dict.fromkeys(expected))


def collect_bars(mt5, sym: str, tf: str, start: float, end: float, dirpath: Path, identity: dict,
                 session: dict | None = None, window_s: int | None = None, clock: str = "RAW_IS_UTC") -> dict:
    """Windows/keys/coverage/forming-bar cut are in UTC; the API request bounds are the raw (source-clock) equivalents
    under `clock`; stored rows keep the raw numeric time exactly as returned."""
    dirpath.mkdir(parents=True, exist_ok=True)
    ck = load_checkpoint(dirpath) or {"kind": "bars", "symbol": sym, "tf": tf, "format": "collector_bars_v1",
                                      "time_contract": "API_UTC_CONTRACT" if clock == "RAW_IS_UTC" else "API_SERVER_CLOCK_PROBED",
                                      "clock_profile": clock, "identity": identity, "chunks": [], "windows": {}}
    window_s = window_s or BAR_WINDOW_S[tf]
    # Include an open time only if its entire candle has closed by `end`.
    stop = int(end) - TF_S[tf] + 1
    requests, expected = _incremental_requests(ck, int(start), stop, window_s, int(end))
    status = "OK"
    for key, w0, w1 in requests:
        # Only bars CLOSED by `end` are committed: MT5 also returns the forming bar (partial values); committing it would
        # later conflict with its final version or leak a running candle into closed-bar features (B6B).
        w1c = w1
        if w1c <= w0:
            break
        r0, r1c = raw_of(w0, clock), raw_of(w1c, clock)
        rec: dict[str, Any] = {"requested_from": iso_utc(w0), "requested_to_inclusive": iso_utc(w1c - 1), "attempted_at": iso_utc(now_utc()),
                               "clock_profile": clock, "requested_raw_from": r0, "requested_raw_to_inclusive": r1c - 1}
        no_slots = (TF_S[tf] < 86400 and -(-r0 // TF_S[tf]) * TF_S[tf] >= r1c)
        if tf == "D1" and (session or {}).get("d1_boundary"):
            slots = d1_coverage(np.zeros(0, dtype=np.int64), w0, w1c, session)
            no_slots = slots.get("expected_open_days") == 0
        if no_slots:
            # Rolling minute scans can advance the open-time bound without
            # crossing any H1/D1 opening. There is no bar to fetch or lose;
            # this is not an unexplained empty market-data response.
            rec.update({"status": "EMPTY_MARKET_CLOSED" if window_fully_closed(w0, w1c, session) else "OK",
                        "rows": 0, "slot_status": "OK", "slot_check": "NO_ELIGIBLE_CLOSED_BAR_OPEN_IN_INTERVAL"})
            ck["windows"][key] = rec
            save_checkpoint(dirpath, ck)
            continue
        rates = mt5.copy_rates_range(sym, getattr(mt5, f"TIMEFRAME_{tf}"), r0, r1c - 1)   # one attempt per window per run
        if rates is None:
            rec.update({"status": "ERROR_NONE_RETURNED", "last_error": str(mt5.last_error())})
            ck["windows"][key] = rec
            save_checkpoint(dirpath, ck)
            status = "PARTIAL"
            break
        a = np.asarray(rates)
        n_forming = int(np.sum(utc_of(a["time"], clock) + TF_S[tf] > end)) if len(a) else 0
        if n_forming:
            a = a[utc_of(a["time"], clock) + TF_S[tf] <= end]
            rec["forming_bars_excluded"] = n_forming
        reasons = validate_bars(a, r0, r1c, tf)
        if reasons:
            q = quarantine(dirpath, key, "rates", a, reasons)
            rec.update({"status": "ERROR_INVALID_BATCH", "rows": int(len(a)), "reasons": reasons, "quarantine": q})
            ck.setdefault("quarantine", []).append({"window": key, **q})
            ck["windows"][key] = rec
            save_checkpoint(dirpath, ck)
            status = "PARTIAL"
            break
        if len(a) == 0:
            rec.update({"status": "EMPTY_MARKET_CLOSED" if window_fully_closed(w0, w1c, session) else "EMPTY_UNEXPLAINED", "rows": 0})
        else:
            gaps = slot_gaps(utc_of(a["time"], clock), w0, w1c, tf, session)
            prev_chunk = next((c for c in ck["chunks"] if c.get("window") == key), None)
            info, accept, conflict = _commit_window_bars(dirpath, key, a, prev_chunk)
            if accept:
                if prev_chunk is not None:
                    ck["chunks"].remove(prev_chunk)
                    ck.setdefault("superseded", []).append({**prev_chunk, "superseded_by": info["file"]})
                ck["chunks"].append({**info, "window": key, "first": int(a["time"][0]), "last": int(a["time"][-1])})
            rec.update({"rows": int(len(a)), "first_raw": int(a["time"][0]), "last_raw": int(a["time"][-1]), "file": info["file"],
                        "commit": info["commit"], **gaps})
            if conflict:
                rec.update({"status": "CONFLICT_UNRESOLVED", "conflict": conflict})
                ck.setdefault("conflicts", []).append({"window": key, **info, "reason": conflict})
            else:
                rec["status"] = gaps["slot_status"]
        ck["windows"][key] = rec
        save_checkpoint(dirpath, ck)
        if rec["status"] not in OK_WINDOW:
            status = "PARTIAL"
    return _summary(ck, status, start, end, window_s, expected=expected)


def validate_bars(a: np.ndarray, w0: int, w1: int, tf: str) -> list[dict]:
    """Structured reasons why a bar batch must not be accepted (empty list = valid)."""
    if len(a) == 0:
        return []
    out = []
    names = a.dtype.names or ()
    for f in ("time", "open", "high", "low", "close"):
        if f not in names:
            return [{"reason": "SCHEMA_FIELD_MISSING", "field": f}]

    def rows(mask):
        return [int(i) for i in np.flatnonzero(mask)[:20]]

    t = a["time"].astype(np.int64)
    o, h, l, c = (a[f].astype(float) for f in ("open", "high", "low", "close"))
    nonfinite = ~(np.isfinite(o) & np.isfinite(h) & np.isfinite(l) & np.isfinite(c))
    checks = [("NON_FINITE_OHLC", nonfinite),
              ("NON_POSITIVE_PRICE", ~nonfinite & ~((o > 0) & (h > 0) & (l > 0) & (c > 0))),
              ("HIGH_BELOW_LOW", ~nonfinite & (h < l)),
              ("HIGH_BELOW_OPEN_OR_CLOSE", ~nonfinite & (h < np.maximum(o, c))),
              ("LOW_ABOVE_OPEN_OR_CLOSE", ~nonfinite & (l > np.minimum(o, c))),
              ("TIME_OUTSIDE_WINDOW", (t < w0) | (t > w1 - 1)),
              ("TIME_NOT_STRICTLY_INCREASING", np.r_[False, np.diff(t) <= 0])]
    if TF_S[tf] < 86400:
        checks.append(("TIME_NOT_ALIGNED_TO_TF", t % TF_S[tf] != 0))
    if "tick_volume" in names:
        checks.append(("NEGATIVE_TICK_VOLUME", a["tick_volume"].astype(np.float64) < 0))
    if "spread" in names:
        checks.append(("NEGATIVE_SPREAD", a["spread"].astype(np.int64) < 0))
    for reason, mask in checks:
        if mask.any():
            out.append({"reason": reason, "rows": rows(mask), "count": int(mask.sum())})
    return out


def validate_ticks(b: np.ndarray) -> list[dict]:
    if len(b) == 0:
        return []
    out = []
    bid, ask = b["bid"].astype(float), b["ask"].astype(float)
    for reason, mask in (("NON_FINITE_BID", ~np.isfinite(bid)), ("NON_POSITIVE_BID", np.isfinite(bid) & (bid <= 0)),
                         ("NON_FINITE_ASK", ~np.isfinite(ask)), ("NEGATIVE_ASK", np.isfinite(ask) & (ask < 0)),
                         ("TICKS_NOT_SORTED", np.r_[False, np.diff(b["time_msc"]) < 0])):
        if mask.any():
            out.append({"reason": reason, "rows": [int(i) for i in np.flatnonzero(mask)[:20]], "count": int(mask.sum())})
    return out


def quarantine(dirpath: Path, key: str, field: str, a: np.ndarray, reasons: list[dict]) -> dict:
    """Keep the rejected raw batch as evidence, outside the accepted chunk set."""
    qd = dirpath / "quarantine"
    qd.mkdir(parents=True, exist_ok=True)
    n = len(list(qd.glob(f"{key}_*.npz"))) + 1
    data = _npz_bytes(**{field: a})
    p = qd / f"{key}_{n}.npz"
    atomic_write_bytes(p, data)
    return {"file": f"quarantine/{p.name}", "sha256": sha256_bytes(data), "rows": int(len(a)), "reasons": [r["reason"] for r in reasons]}


def slot_gaps(times: np.ndarray, w0: int, w1: int, tf: str, session: dict | None) -> dict:
    """Received bars vs scheduled-open slots of [w0, w1). Missing open slots → PARTIAL_GAPS (retried)."""
    tfs = TF_S[tf]
    if tfs >= 86400:
        return d1_coverage(times, w0, w1, session)
    slots = np.arange(-(-w0 // tfs) * tfs, w1, tfs, dtype=np.int64)
    present = np.isin(slots, times.astype(np.int64))
    if session:
        from .coverage import scheduled_open
        open_ = scheduled_open(slots, session)
        basis = "SESSION_SCHEDULE"
    else:
        open_ = np.ones(len(slots), bool)
        basis = "NO_SCHEDULE_ALL_SLOTS_EXPECTED"
    miss = open_ & ~present
    edges = np.flatnonzero(np.diff(np.r_[0, miss.astype(np.int8), 0]))
    ranges = [{"from": iso_utc(int(slots[e0])), "to_exclusive": iso_utc(int(slots[e1 - 1]) + tfs), "bars": int(e1 - e0)}
              for e0, e1 in zip(edges[::2], edges[1::2])]
    st = "OK" if not miss.any() else ("PARTIAL_GAPS" if session else "COVERAGE_UNKNOWN_NO_SCHEDULE")
    return {"slot_status": st, "slot_basis": basis, "expected_open_slots": int(open_.sum()), "present_open_slots": int((open_ & present).sum()),
            "missing_open_slots": int(miss.sum()), "missing_open_ranges": ranges[:50],
            "present_outside_schedule": int((present & ~open_).sum()),
            "note": "missing open slots are UNEXPLAINED (holiday, no-price interval or lost data — not decided); window will be retried"}


def d1_coverage(times: np.ndarray, w0: int, w1: int, session: dict | None) -> dict:
    """D1 coverage without inventing a broker day boundary.
    * With a declared boundary (session["d1_boundary"] = {"tz": IANA|"UTC", "day_start": "HH:MM"}): every broker day in the
      window that has scheduled-open time must have a bar opening at its start → OK / PARTIAL_GAPS (missing days listed).
    * Without it: only a boundary-free lower bound is checked — k UTC days fully inside the window with ≥20h scheduled
      open each must be touched by at least ceil(k/2) broker days. Fewer bars → PARTIAL_GAPS; otherwise
      COVERAGE_UNVERIFIED_D1_BOUNDARY (never claimed complete)."""
    import datetime as _dt
    import math
    from zoneinfo import ZoneInfo
    from .coverage import scheduled_open
    t = np.asarray(times, dtype=np.int64)
    if not session:
        return {"slot_status": "COVERAGE_UNKNOWN_NO_SCHEDULE", "slot_check": "D1_NO_SCHEDULE", "rows": int(len(t))}
    bnd = session.get("d1_boundary")
    if bnd:
        tz = _dt.timezone.utc if bnd.get("tz", "UTC") == "UTC" else ZoneInfo(bnd["tz"])
        hh, mm = map(int, bnd.get("day_start", "00:00").split(":"))
        d = _dt.datetime.fromtimestamp(w0, _dt.timezone.utc).astimezone(tz).date() - _dt.timedelta(days=1)
        expected, missing = [], []
        while True:
            ds = int(_dt.datetime(d.year, d.month, d.day, hh, mm, tzinfo=tz).timestamp())
            nd = d + _dt.timedelta(days=1)
            de = int(_dt.datetime(nd.year, nd.month, nd.day, hh, mm, tzinfo=tz).timestamp())
            if ds >= w1:
                break
            if ds >= w0:
                mins = np.arange(ds, min(de, w1), 60, dtype=np.int64)
                if len(mins) and scheduled_open(mins, session).any():
                    expected.append(ds)
                    if ds not in set(t.tolist()):
                        missing.append(iso_utc(ds))
            d = nd
        return {"slot_status": "OK" if not missing else "PARTIAL_GAPS", "slot_check": "D1_DECLARED_BOUNDARY",
                "slot_basis": f"declared broker day start {bnd.get('day_start', '00:00')} {bnd.get('tz', 'UTC')} ({bnd.get('status', 'status not given')})",
                "expected_open_days": len(expected), "present_open_days": len(expected) - len(missing), "missing_open_days": missing[:50],
                "present_outside_expected": int(len(set(t.tolist()) - set(expected)))}
    k = 0
    day = -(-w0 // 86400) * 86400
    while day + 86400 <= w1:
        mins = np.arange(day, day + 86400, 60, dtype=np.int64)
        if int(scheduled_open(mins, session).sum()) >= 20 * 60:
            k += 1
        day += 86400
    lower = math.ceil(k / 2)
    st = "PARTIAL_GAPS" if len(t) < lower else "COVERAGE_UNVERIFIED_D1_BOUNDARY"
    return {"slot_status": st, "slot_check": "D1_BOUNDARY_UNKNOWN_LOWER_BOUND_ONLY", "rows": int(len(t)),
            "utc_days_with_20h_open": k, "min_bars_boundary_free": lower,
            "note": "broker D1 boundary not declared: completeness cannot be verified (UTC-midnight grid not assumed); "
                    "fewer bars than the boundary-free lower bound → gaps; window retried"}


def _commit_window_bars(dirpath: Path, key: str, a: np.ndarray, prev_chunk: dict | None) -> tuple[dict, bool, str | None]:
    """Commit a window's bars. A refetch of a PARTIAL window that keeps every previously accepted bar identical
    supersedes it (completion, not a conflict). A refetch that changes an accepted bar is a SOURCE_CONFLICT:
    the new bytes are stored as evidence and the previously accepted chunk stays accepted."""
    if prev_chunk is None:
        return commit_chunk(dirpath, key, "rates", a), True, None
    with np.load(dirpath / prev_chunk["file"], allow_pickle=False) as z:
        old = z["rates"]
    if old.tobytes() == a.tobytes() and old.dtype == a.dtype:
        return {**prev_chunk, "commit": "REUSED_IDENTICAL"}, False, None
    idx = np.searchsorted(a["time"], old["time"])
    same = (idx < len(a)) & (a["time"][np.minimum(idx, len(a) - 1)] == old["time"])
    kept = same.all() and all(a[i].tobytes() == r.tobytes() for i, r in zip(idx, old))
    k = 2
    while (dirpath / f"{key}.v{k}.npz").exists():
        k += 1
    info = commit_chunk(dirpath, f"{key}.v{k}", "rates", a)
    if kept:
        return {**info, "commit": "SUPERSEDES_PARTIAL", "supersedes": prev_chunk["file"]}, True, None
    return {**info, "commit": "CONFLICT_EVIDENCE_NOT_ACCEPTED"}, False, "SOURCE_CONFLICT:ACCEPTED_BARS_CHANGED"


def _summary(ck: dict, status: str, start: float, end: float, window_s: int, expected: list | None = None) -> dict:
    if expected is None:
        expected = []
        w0 = int(start)
        while w0 < end:
            w1 = int(min(end, w0 + window_s))
            if w1 <= w0:                      # guard: never loop on a sub-second remainder
                break
            expected.append(f"{w0}_{w1}")
            w0 = w1
    states = {k: ck["windows"].get(k, {}).get("status", "NOT_ATTEMPTED") for k in expected}
    complete = all(v in OK_WINDOW for v in states.values())
    return {"status": "OK" if complete else "PARTIAL", "coverage_complete": complete, "windows": len(expected),
            "window_status_counts": {s: list(states.values()).count(s) for s in sorted(set(states.values()))},
            "rows_committed": int(sum(c["rows"] for c in ck["chunks"])), "chunks": len(ck["chunks"]),
            "conflicts": ck.get("conflicts", []), "pending_boundary_ms": ck.get("pending_ms")}


# ------------------------------------------------------------------ ticks
def _conflict_evidence(dirpath: Path, tag: str, stored: np.ndarray, fetched: np.ndarray) -> dict:
    """Both source versions of a conflicting segment, immutable, outside the accepted chunk set."""
    cd = dirpath / "conflicts"
    cd.mkdir(parents=True, exist_ok=True)
    data = _npz_bytes(stored=stored, fetched=fetched)
    sha = sha256_bytes(data)
    p = cd / f"{tag}_{sha[:12]}.npz"
    if not p.exists():
        atomic_write_bytes(p, data)
    return {"file": f"conflicts/{p.name}", "sha256": sha, "stored_rows": int(len(stored)), "fetched_rows": int(len(fetched))}


@_storage_leased("dirpath", 4)
def collect_ticks(mt5, sym: str, start: float, end: float, dirpath: Path, identity: dict, session: dict | None = None,
                  window_s: int = 3600, finalize_tail: bool | None = None, save_ck=None, resync_conflicts: bool = False,
                  clock: str = "RAW_IS_UTC") -> dict:
    """Backfill ticks window by window with a durable cursor. `finalize_tail` commits the last ms group when `end`
    is safely in the past (historical backfill); live runs keep it pending. A boundary conflict is never committed:
    the window stays CONFLICT_UNRESOLVED and the cursor does not pass it unless `resync_conflicts` adopts the
    source version explicitly (recorded with both versions as evidence)."""
    save_ck = save_ck or save_checkpoint
    dirpath.mkdir(parents=True, exist_ok=True)
    generation = ensure_tick_generation(dirpath, identity=identity)
    ck = load_checkpoint(dirpath) or {"kind": "ticks", "symbol": sym, "format": "collector_ticks_v1",
                                      "time_contract": "API_UTC_CONTRACT" if clock == "RAW_IS_UTC" else "API_SERVER_CLOCK_PROBED",
                                      "clock_profile": clock, "identity": identity, "chunks": [], "windows": {}, "committed_through_ms": None,
                                      "pending_ms": None, "pending_file": None, "pending_sha256": None}
    ck.update(generation)
    if finalize_tail is None:
        finalize_tail = end < now_utc() - 120
    pending = _load_pending(dirpath, ck)
    status = "OK"
    requests, expected = _incremental_requests(ck, int(start), int(end), window_s, int(end))
    for key, w0, w1 in requests:
        r0, r1 = raw_of(w0, clock), raw_of(w1, clock)            # raw (source-clock) bounds; time_msc stays raw
        frm_s = (ck["pending_ms"] // 1000) if ck["pending_ms"] is not None else r0
        rec: dict[str, Any] = {"requested_from": iso_utc(w0), "requested_to_inclusive": iso_utc(w1 - 1), "fetched_from_raw": int(frm_s),
                               "clock_profile": clock, "requested_raw_from": r0, "requested_raw_to_inclusive": r1 - 1,
                               "attempted_at": iso_utc(now_utc())}
        batch = mt5.copy_ticks_range(sym, frm_s, r1 - 1, mt5.COPY_TICKS_ALL)
        if batch is None:
            rec.update({"status": "ERROR_NONE_RETURNED", "last_error": str(mt5.last_error())})
            ck["windows"][key] = rec
            save_ck(dirpath, ck)
            status = "PARTIAL"
            break
        b = np.asarray(batch)
        reasons = validate_ticks(b)
        if reasons:
            q = quarantine(dirpath, key, "ticks", b, reasons)
            rec.update({"status": "ERROR_INVALID_BATCH", "reason": reasons[0]["reason"], "reasons": reasons, "rows": int(len(b)), "quarantine": q})
            ck.setdefault("quarantine", []).append({"window": key, **q})
            ck["windows"][key] = rec
            save_ck(dirpath, ck)
            status = "PARTIAL"
            break
        pms = ck["pending_ms"]
        conflicts: list[dict] = []
        if pms is not None:
            # same-second ticks before the pending ms were committed earlier: they must match exactly
            tail_from = int(frm_s) * 1000
            fetched_tail = b[(b["time_msc"] >= tail_from) & (b["time_msc"] < pms)]
            committed_tail = read_tick_chunks(dirpath, tail_from, pms - 1) if ck["chunks"] else b[:0]
            same = len(committed_tail) == len(fetched_tail) and (
                len(fetched_tail) == 0 or (committed_tail.dtype == fetched_tail.dtype and np.array_equal(committed_tail, fetched_tail)))
            if not same:
                conflicts.append({"reason": "SOURCE_CONFLICT_COMMITTED_TAIL", "time_msc_from": tail_from, "time_msc_to": pms - 1,
                                  "stored": int(len(committed_tail)), "fetched": int(len(fetched_tail)),
                                  "evidence": _conflict_evidence(dirpath, f"tail_{pms}", committed_tail, fetched_tail)})
            b = b[b["time_msc"] >= pms]
        b = b[b["time_msc"] < r1 * 1000]
        held = pending if pending is not None else None
        if held is None:
            merged = b
        else:
            merged, _, grp_conf = merge_tick_batch(held, pms, b)
            if grp_conf:
                new_grp = b[b["time_msc"] == pms]
                if resync_conflicts and not conflicts:
                    # explicit resolution: adopt the source's current version of the uncommitted boundary group
                    ev = _conflict_evidence(dirpath, f"group_{pms}", held, new_grp)
                    merged = np.concatenate([new_grp, b[b["time_msc"] > pms]])
                    ck.setdefault("resolutions", []).append({"window": key, "time_msc": pms, "resolution": "RESYNCED_TO_SOURCE_VERSION",
                                                             "stored_rows": int(len(held)), "source_rows": int(len(new_grp)), "evidence": ev,
                                                             "resolved_at": iso_utc(now_utc())})
                    rec["resolved_conflict"] = "RESYNCED_TO_SOURCE_VERSION"
                else:
                    conflicts += [{**c, "evidence": _conflict_evidence(dirpath, f"group_{pms}", held, new_grp)} for c in grp_conf]
        if conflicts:
            # unresolved: nothing committed, cursor and pending group unchanged; the window stays retryable
            rec.update({"status": "CONFLICT_UNRESOLVED", "conflicts": conflicts,
                        "recovery": "rerun (source may settle) or rerun with resync_conflicts=True to adopt the source version of the uncommitted group"})
            ck.setdefault("conflicts", []).extend({**c, "window": key} for c in conflicts)
            ck["windows"][key] = rec
            save_ck(dirpath, ck)
            status = "PARTIAL"
            break
        own = merged[merged["time_msc"] >= r0 * 1000] if len(merged) else merged   # this window's own data, without the overlap
        rec["received_rows_new"] = int(len(own))
        rec["overlap_group_confirmed_rows"] = 0 if pending is None else int(len(pending))
        if len(own) == 0:
            # nothing new in this window: the held/confirmed overlap group is NOT evidence that the window was loaded,
            # and it is not finalized here (stays pending; cursor unchanged)
            rec.update({"status": "EMPTY_MARKET_CLOSED" if window_fully_closed(w0, w1, session) else "EMPTY_UNEXPLAINED"})
            if rec["status"] == "EMPTY_MARKET_CLOSED" and pending is not None and w1 >= end and finalize_tail:
                # historical backfill ending in a closure: the group was re-read identically above → confirmed, commit it
                info = commit_chunk(dirpath, f"{key}_{int(pending['time_msc'][0])}_confirmed_tail", "ticks", pending)
                ck["chunks"].append({**info, "window": key, "first_ms": int(pending["time_msc"][0]), "last_ms": int(pending["time_msc"][-1])})
                old_pf = ck.get("pending_file")
                ck.update({"pending_ms": None, "pending_file": None, "pending_sha256": None, "pending_rows": 0,
                           "committed_through_ms": int(pending["time_msc"][-1]) + 1})
                rec["confirmed_tail_committed_rows"] = int(len(pending))
                pending = None
                ck["windows"][key] = rec
                save_ck(dirpath, ck)
                if old_pf:
                    try:
                        (dirpath / old_pf).unlink()
                    except OSError:
                        pass
                w0 = w1
                continue
            ck["windows"][key] = rec
            save_ck(dirpath, ck)
            if rec["status"] == "EMPTY_UNEXPLAINED":
                status = "PARTIAL"
            w0 = w1
            continue
        last_ms = int(merged["time_msc"][-1])
        is_last_window = w1 >= end
        commit_all = is_last_window and finalize_tail
        to_commit = merged if commit_all else merged[merged["time_msc"] < last_ms]
        new_pending = None if commit_all else merged[merged["time_msc"] == last_ms]
        if len(to_commit):
            info = commit_chunk(dirpath, f"{key}_{int(to_commit['time_msc'][0])}", "ticks", to_commit)
            ck["chunks"].append({**info, "window": key, "first_ms": int(to_commit["time_msc"][0]), "last_ms": int(to_commit["time_msc"][-1])})
            if info.get("conflict"):
                ck.setdefault("conflicts", []).append({"window": key, **info})
            ask_missing = int(np.sum(~(to_commit["ask"] > 0)))
            gaps = np.diff(to_commit["time_msc"]) / 1000.0
            rec.update({"committed_rows": int(len(to_commit)), "file": info["file"], "commit": info["commit"],
                        "ask_missing_rows": ask_missing, "max_gap_s": float(gaps.max()) if len(gaps) else 0.0,
                        "same_ms_duplicate_rows": int(np.sum(np.diff(to_commit["time_msc"]) == 0))})
            if ask_missing:
                rec["flags"] = ["ASK_MISSING"]
        old_pending_file = ck.get("pending_file")
        if new_pending is not None and len(new_pending):
            pb = _npz_bytes(ticks=new_pending)
            pf = dirpath / f"pending_{last_ms}_{len(new_pending)}.npz"   # new name: the old pending stays valid until the checkpoint commits
            atomic_write_bytes(pf, pb)
            ck.update({"pending_ms": last_ms, "pending_file": pf.name, "pending_sha256": sha256_bytes(pb), "pending_rows": int(len(new_pending))})
            ck["committed_through_ms"] = last_ms  # exclusive
        else:
            ck.update({"pending_ms": None, "pending_file": None, "pending_sha256": None, "pending_rows": 0})
            ck["committed_through_ms"] = last_ms + 1
        pending = new_pending
        rec["status"] = "OK"
        ck["windows"][key] = rec
        save_ck(dirpath, ck)
        if old_pending_file and old_pending_file != ck.get("pending_file"):
            try:
                (dirpath / old_pending_file).unlink()
            except OSError:
                pass
        w0 = w1
    s = _summary(ck, status, start, end, window_s, expected=expected)
    s["rows_committed"] = int(sum(c["rows"] for c in ck["chunks"]))
    s["pending_rows_not_committed"] = int(ck.get("pending_rows", 0) or 0)
    if s["pending_rows_not_committed"]:
        s["tail_status"] = "PENDING_BOUNDARY_GROUP_NOT_COMMITTED (re-read on next run)"
    return s


def _load_pending(dirpath: Path, ck: dict):
    if not ck.get("pending_file"):
        return None
    p = dirpath / ck["pending_file"]
    if not p.exists() or sha256_file(p) != ck["pending_sha256"]:
        from .data import ChunkCorrupt
        raise ChunkCorrupt(f"PENDING_GROUP_CORRUPT:{p}")
    with np.load(p, allow_pickle=False) as z:
        return z["ticks"]


# ------------------------------------------------------------------ clock probe
def clock_probe(mt5, sym: str, session: dict | None = None, max_fresh_s: float = 30.0, now_fn=None) -> dict:
    """Evidence only: compare the latest tick's numeric time with local UTC at collection. Never changes status and
    never VERIFIES a clock: a stale tick / closed market cannot be told apart from a UTC offset, and the local PC clock
    accuracy is not measured. `assessment` says what the single observation can and cannot support."""
    local = (now_fn or now_utc)()
    t = mt5.symbol_info_tick(sym)
    if t is None:
        return {"status": "NO_TICK", "local_utc": iso_utc(local), "assessment": "UNKNOWN_NO_TICK"}
    td = t._asdict() if hasattr(t, "_asdict") else dict(t)
    raw_time, raw_msc = td.get("time"), td.get("time_msc")
    tick_s = (raw_msc or 0) / 1000.0 or float(raw_time or 0)
    if not tick_s:
        return {"status": "NO_TICK", "local_utc": iso_utc(local), "assessment": "UNKNOWN_TICK_TIME_MISSING",
                "raw": {"time": raw_time, "time_msc": raw_msc}}
    delta = tick_s - local
    near = min((0, 7200, 10800, -14400, -18000), key=lambda x: abs(delta - x))
    residual = delta - near
    sched_open = None
    if session and session.get("tz") == "America/New_York":
        from .coverage import scheduled_open
        sched_open = bool(scheduled_open(np.array([int(local)]), session)[0])
    if sched_open is False:
        assessment = "UNKNOWN_MARKET_CLOSED_BY_SCHEDULE"
    elif -max_fresh_s <= residual <= 5:
        assessment = f"FRESH_TICK_CONSISTENT_WITH_OFFSET_{near}_S_NOT_VERIFIED" + ("" if sched_open else "_SESSION_UNKNOWN")
    else:
        assessment = "UNKNOWN_STALE_TICK_OR_OFFSET"
    return {"status": "PROBE_RECORDED_NOT_VERIFIED", "local_utc": iso_utc(local), "tick_time_numeric": tick_s,
            "raw": {"time": raw_time, "time_msc": raw_msc}, "received_local_utc": iso_utc(local),
            "delta_tick_minus_local_s": round(delta, 3), "nearest_whole_offset_s": near, "residual_s": round(residual, 3),
            "max_fresh_s": max_fresh_s, "scheduled_open_at_probe": sched_open, "assessment": assessment,
            "local_clock_basis": "PC system clock via OS (UTC); accuracy NOT measured",
            "caveat": "delta mixes clock basis and tick age (closed market / stale tick); one current probe never verifies the legacy-cache clock/DST",
            "reading": {0: "consistent with UTC numeric time", 7200: "consistent with UTC+2 wall clock", 10800: "consistent with UTC+3 wall clock"}.get(near, "other")}


PROFILE_POSITIVE = ("point", "trade_tick_size", "trade_tick_value", "trade_contract_size", "volume_min", "volume_max", "volume_step")
PROFILE_NONNEG_INT = ("digits", "trade_stops_level", "trade_freeze_level")
PROFILE_STR = ("name", "currency_base", "currency_profit", "currency_margin")
# MT5 ENUM_SYMBOL_CALC_MODE / ENUM_SYMBOL_TRADE_MODE as exported by the MetaTrader5 Python package 5.0.6180
# (read from the module constants, no terminal attach). Code 35 is NOT exported by this runtime.
# Static so that offline/fake runs work without the package; `runtime_enum_contract()` re-checks it when available.
ENUM_CONTRACT_VERSION = "MetaTrader5-python-5.0.6180"
CALC_MODES = {0: "FOREX", 1: "FUTURES", 2: "CFD", 3: "CFDINDEX", 4: "CFDLEVERAGE", 5: "FOREX_NO_LEVERAGE", 32: "EXCH_STOCKS",
              33: "EXCH_FUTURES", 34: "EXCH_OPTIONS", 36: "EXCH_OPTIONS_MARGIN", 37: "EXCH_BONDS", 38: "EXCH_STOCKS_MOEX",
              39: "EXCH_BONDS_MOEX", 64: "SERV_COLLATERAL"}
TRADE_MODES = {0: "DISABLED", 1: "LONGONLY", 2: "SHORTONLY", 3: "CLOSEONLY", 4: "FULL"}


def runtime_enum_contract(module=None) -> dict:
    """Package version + SYMBOL_CALC_MODE_* / SYMBOL_TRADE_MODE_* constants of the installed MetaTrader5 module (import
    only; never initialize). Package absent → UNKNOWN (the static table is then unverified for this machine)."""
    if module is None:
        try:
            import MetaTrader5 as module  # noqa: N813
        except ImportError:
            return {"status": "UNKNOWN_PACKAGE_ABSENT", "static_contract": ENUM_CONTRACT_VERSION, "package_version": None}
    calc = {getattr(module, n): n.removeprefix("SYMBOL_CALC_MODE_") for n in dir(module) if n.startswith("SYMBOL_CALC_MODE_")}
    trade = {getattr(module, n): n.removeprefix("SYMBOL_TRADE_MODE_") for n in dir(module) if n.startswith("SYMBOL_TRADE_MODE_")}
    ver = getattr(module, "__version__", None)
    match = calc == CALC_MODES and trade == TRADE_MODES
    return {"status": "MATCHES_STATIC_CONTRACT" if match else "MISMATCH_WITH_STATIC_CONTRACT", "package_version": ver,
            "static_contract": ENUM_CONTRACT_VERSION, "calc_modes_runtime": {str(k): v for k, v in sorted(calc.items())},
            "trade_modes_runtime": {str(k): v for k, v in sorted(trade.items())},
            "note": "package constants only; a terminal/broker may still report other codes (kept raw, reason-coded, never COMPLETE)"}


LINEAR_PROFIT_CALC_MODES = (0, 2, 4, 5)   # profit = price diff x contract size x lots (then currency conversion)


def _is_int(v) -> bool:
    import numbers
    return isinstance(v, numbers.Integral) and not isinstance(v, bool)


def _is_num(v) -> bool:
    import numbers
    return isinstance(v, numbers.Real) and not isinstance(v, bool) and bool(np.isfinite(v))


def validate_profile(prof: dict) -> dict:
    """Value domains, never defaults: positive finite sizes; non-negative integer digits/stops/freeze (0 kept);
    non-empty string names/currencies; documented calc/trade mode enums; volume_min <= volume_max and >= step.
    `profit_formula_capability` says whether our linear independent arithmetic applies — metadata presence alone
    does not prove every calculation mode is supported."""
    bad = []
    for k in PROFILE_POSITIVE:
        v = prof.get(k)
        if not _is_num(v) or v <= 0:
            bad.append({"field": k, "value": v, "reason": "MISSING_NAN_OR_NONPOSITIVE"})
    for k in PROFILE_NONNEG_INT:
        v = prof.get(k)
        if not _is_int(v) or v < 0:
            bad.append({"field": k, "value": v, "reason": "NOT_NONNEGATIVE_INTEGER"})
    for k in PROFILE_STR:
        v = prof.get(k)
        if not isinstance(v, str) or not v.strip():
            bad.append({"field": k, "value": v, "reason": "MISSING_OR_EMPTY_STRING"})
    cm, tm = prof.get("trade_calc_mode"), prof.get("trade_mode")
    if not _is_int(cm) or cm not in CALC_MODES:
        bad.append({"field": "trade_calc_mode", "value": cm, "reason": "MISSING_OR_UNKNOWN_CALC_MODE"})
    if not _is_int(tm) or tm not in TRADE_MODES:
        bad.append({"field": "trade_mode", "value": tm, "reason": "MISSING_OR_UNKNOWN_TRADE_MODE"})
    fields_bad = {x["field"] for x in bad}
    if not fields_bad & {"volume_min", "volume_max", "volume_step"}:
        if prof["volume_min"] > prof["volume_max"]:
            bad.append({"field": "volume_min", "value": [prof["volume_min"], prof["volume_max"]], "reason": "VOLUME_MIN_GT_MAX"})
        if prof["volume_min"] < prof["volume_step"] - 1e-12:
            bad.append({"field": "volume_min", "value": prof["volume_min"], "reason": "BELOW_VOLUME_STEP"})
    if _is_int(cm) and cm in LINEAR_PROFIT_CALC_MODES:
        cap = f"LINEAR_{CALC_MODES[cm]}"
    else:
        cap = "UNKNOWN_CAPABILITY" + (f":{CALC_MODES[cm]}" if _is_int(cm) and cm in CALC_MODES else "")
    return {"status": "COMPLETE" if not bad else "INCOMPLETE", "invalid": bad, "profit_formula_capability": cap,
            "enum_contract": ENUM_CONTRACT_VERSION, "calc_mode_raw": cm, "calc_mode_name": CALC_MODES.get(cm) if _is_int(cm) else None,
            "note": "current-only profile (effective at profile_observed_at); does not prove historical contract/fees"}


def verify_attached_identity(mt5, exe: str) -> tuple[dict | None, str | None]:
    """After attach: the terminal must be the selected path, connected, with a real account/server. Anything missing is
    a reason code, never a fingerprint built from None."""
    try:
        ti, ai = mt5.terminal_info(), mt5.account_info()
    except (PermissionError, AttributeError) as e:
        return None, f"IDENTITY_UNAVAILABLE:{type(e).__name__}"
    if ti is None:
        return None, "TERMINAL_INFO_NONE"
    ti_d = ti._asdict() if hasattr(ti, "_asdict") else dict(ti)
    if os.path.normcase(os.path.abspath(ti_d.get("path") or "")) != os.path.dirname(exe):
        return None, "ATTACHED_TERMINAL_PATH_MISMATCH"
    if not ti_d.get("connected"):
        return None, "TERMINAL_DISCONNECTED"
    if ai is None:
        return None, "ACCOUNT_INFO_NONE"
    ai_d = ai._asdict() if hasattr(ai, "_asdict") else dict(ai)
    if ai_d.get("login") in (None, 0, "") or not ai_d.get("server"):
        return None, "ACCOUNT_IDENTITY_MISSING"
    return {"terminal_path": ti_d.get("path"), "data_path": ti_d.get("data_path"), "build": ti_d.get("build"),
            "company": ti_d.get("company"), "connected": ti_d.get("connected"), "server": ai_d.get("server"),
            "account_fingerprint": hash_obj([ai_d.get("login"), ai_d.get("server")])[:16],
            "trade_mode": ai_d.get("trade_mode"), "account_currency": ai_d.get("currency"), "collected_at": iso_utc(now_utc())}, None


# ------------------------------------------------------------------ orchestration
@_storage_leased("out_root")
def collect(terminal_path: str, symbols: list[str], start_utc: float, end_utc: float, *, out_root: Path | None = None,
            mt5_module=None, process_lister: Callable[[], list[str]] = running_terminal_paths,
            timeframes=("M1", "M5", "H1", "D1"), with_ticks: bool = True, tick_window_s: int = 3600,
            sessions: dict | None = None, tick_start_utc: float | None = None, require_trade_mode: int | None = None,
            expect_identity: dict | None = None, clock_profile: str | None = None) -> dict:
    exe = os.path.normcase(os.path.abspath(terminal_path if terminal_path.lower().endswith(".exe")
                                           else os.path.join(terminal_path, "terminal64.exe")))
    # whole seconds: a fractional `end` (wall clock) made the window loops of _summary never advance (w1 == w0)
    start_utc, end_utc = int(start_utc), int(end_utc)
    if tick_start_utc is not None:
        tick_start_utc = int(tick_start_utc)
    running = process_lister()
    if exe not in running:
        return {"status": "ERROR", "reason": "TERMINAL_NOT_RUNNING_AT_SELECTED_PATH", "selected": exe, "running": running,
                "recovery": "Start that terminal yourself (logged into the intended account) and rerun; this tool never launches terminals."}
    # Provider kind follows the REAL source: only the MetaTrader5 package imported here is NATIVE; an injected module is
    # SYNTHETIC whatever it claims (no caller argument can upgrade it).
    if mt5_module is None:
        import MetaTrader5 as mt5_module  # noqa: N813
        provider_kind = "NATIVE_TERMINAL"
    else:
        provider_kind = "SYNTHETIC_INJECTED_MODULE"
    mt5 = ReadOnlyMT5(mt5_module)
    if not mt5.initialize(path=exe):
        return {"status": "ERROR", "reason": "INITIALIZE_FAILED", "last_error": str(mt5.last_error())}
    try:
        identity, why = verify_attached_identity(mt5, exe)
        if identity is None:
            return {"status": "ERROR", "reason": why, "selected": exe,
                    "recovery": "attach only to the selected, connected, logged-in terminal; this tool never logs in or switches accounts"}
        identity = dict(identity, executable=exe, provider_kind=provider_kind)
        # B6C: account-kind and session-pin guards BEFORE any data read/write
        if require_trade_mode is not None and identity.get("trade_mode") != require_trade_mode:
            return {"status": "ERROR", "reason": "ACCOUNT_TRADE_MODE_NOT_ALLOWED", "trade_mode": identity.get("trade_mode"),
                    "required_trade_mode": require_trade_mode, "provider_kind": provider_kind,
                    "recovery": "demo sessions require ACCOUNT_TRADE_MODE_DEMO (0) from account_info; live/contest/unknown refused"}
        if expect_identity:
            diff = [k for k in IDENTITY_PIN_KEYS if expect_identity.get(k) != identity.get(k)]
            if diff:
                return {"status": "ERROR", "reason": "SOURCE_IDENTITY_NOT_SESSION_PINNED", "changed": diff, "provider_kind": provider_kind}
        source_id = source_namespace(identity)
        root = (out_root or STORE_DIR / "raw") / source_id
        clash = _namespace_clash(root, identity)
        if clash:
            return {"status": "ERROR", "reason": "SOURCE_NAMESPACE_IDENTITY_CLASH", "detail": clash, "root": str(root),
                    "recovery": "existing chunks/cursors belong to another identity; nothing was written or migrated"}
        # F2: probe every symbol FIRST, resolve one clock for the whole source, refuse on conflict before any write
        pre: dict[str, dict] = {}
        for sym in symbols:
            try:
                si = mt5.symbol_info(sym)
                if si is None:
                    pre[sym] = {"status": "ERROR", "reason": "SYMBOL_NOT_FOUND"}
                    continue
                sd = si._asdict() if hasattr(si, "_asdict") else dict(si)
                prof = {k: sd.get(k) for k in ("name", "path", "digits", "point", "trade_tick_size", "trade_tick_value", "trade_contract_size",
                                               "currency_base", "currency_profit", "currency_margin", "volume_min", "volume_max", "volume_step",
                                               "trade_stops_level", "trade_freeze_level", "trade_calc_mode", "trade_mode", "chart_mode")}
                pre[sym] = {"profile": prof, "profile_observed_at": iso_utc(now_utc()), "profile_check": validate_profile(prof),
                            "clock_probe": clock_probe(mt5, sym, (sessions or {}).get(sym))}
            except Exception as e:                                   # noqa: BLE001 - isolate one symbol's failure
                pre[sym] = {"status": "ERROR", "reason": f"SYMBOL_PROBE_FAILED:{type(e).__name__}:{e}"[:300]}
        clock = resolve_source_clock({s: r["clock_probe"] for s, r in pre.items() if "clock_probe" in r}, explicit=clock_profile)
        if clock["status"] != "RESOLVED":
            return {"status": "ERROR", "reason": "CLOCK_CONFLICT", "clock": clock, "provider_kind": provider_kind, "identity": identity,
                    "recovery": "nothing was collected; the source clock evidence is inconsistent (re-probe when the market is open, "
                                "or start a new session if the source/clock really changed)"}
        cp = clock["profile"]
        stale = _clock_clash(root, cp)
        if stale:
            return {"status": "ERROR", "reason": "CLOCK_PROFILE_CHANGED_FOR_STORE", "clock": clock, "detail": stale, "provider_kind": provider_kind,
                    "identity": identity, "recovery": "existing windows were requested under another clock mapping; use a new session/store "
                                                      "(old data kept untouched)"}
        pre_batch = {p: p.read_bytes() for p in _checkpoint_files(root)}      # restored if the source changes mid-batch
        manifest: dict[str, Any] = {"source_id": source_id, "identity": identity, "provider_kind": provider_kind,
                                    "request": {"start": iso_utc(start_utc), "end": iso_utc(end_utc)}, "collected_at": iso_utc(now_utc()),
                                    "symbols": {}, "clock": clock, **time_basis_for(clock)}
        overall = "OK"
        for sym in symbols:
            rec = dict(pre[sym])
            if rec.get("status") == "ERROR":
                manifest["symbols"][sym] = rec
                overall = "PARTIAL"
                continue
            sess = (sessions or {}).get(sym)
            rec.update({"bars": {}, "ticks": None})
            try:
                for tf in timeframes:
                    rec["bars"][tf] = collect_bars(mt5, sym, tf, start_utc, end_utc, root / sym / "bars" / tf, identity, sess, clock=cp)
                    if rec["bars"][tf]["status"] != "OK":
                        overall = "PARTIAL"
                if with_ticks:
                    t0 = start_utc if tick_start_utc is None else max(start_utc, tick_start_utc)
                    rec["ticks"] = collect_ticks(mt5, sym, t0, end_utc, root / sym / "ticks", identity, sess, tick_window_s, clock=cp)
                    rec["ticks"]["requested_tick_window"] = {"start": iso_utc(t0), "end": iso_utc(end_utc)}
                    if rec["ticks"]["status"] != "OK":
                        overall = "PARTIAL"
            except Exception as e:                                   # noqa: BLE001 - F1: one symbol never aborts the others
                rec.update({"status": "ERROR", "reason": f"SYMBOL_COLLECT_FAILED:{type(e).__name__}:{e}"[:300], "published": False,
                            "note": "committed windows stay on disk for a later retry; this symbol is not published in this batch"})
                overall = "PARTIAL"
            manifest["symbols"][sym] = rec
        manifest["profiles_complete"] = all((v.get("profile_check") or {}).get("status") == "COMPLETE" for v in manifest["symbols"].values())
        after, why_after = verify_attached_identity(mt5, exe)
        changed = [k for k in IDENTITY_STABLE_KEYS if after is None or after.get(k) != identity.get(k)]
        mp = root / "manifests" / f"collect_{int(now_utc() * 1000)}.json"
        if after is None or changed:
            # Source changed during the batch: keep the raw evidence, publish NOTHING usable, and roll every checkpoint back
            # to its pre-batch bytes so no later run (same process or restart) can reuse the tainted cursors/chunk lists.
            tag = f"QUARANTINED_{int(now_utc() * 1000)}"
            manifest.update({"status": "QUARANTINED_SOURCE_CHANGED", "identity_after": after, "changed": changed or [why_after],
                             "checkpoints_rolled_back": _rollback_checkpoints(root, pre_batch, tag)})
            atomic_write_json(mp.with_name(mp.stem + "_QUARANTINED.json"), manifest)
            return {"status": "ERROR", "reason": "SOURCE_CHANGED_DURING_BATCH", "changed": changed or [why_after],
                    "manifest_path": str(mp.with_name(mp.stem + "_QUARANTINED.json")), "registry_fragment": None}
        manifest["identity_rechecked_after_batch"] = True
        manifest["status"] = overall
        atomic_write_json(mp, manifest)
        return {"status": overall, "manifest_path": str(mp), "manifest": manifest, "root": str(root), "provider_kind": provider_kind,
                "clock": clock,
                "registry_fragment": registry_fragment(root, source_id, [s for s, r in manifest["symbols"].items() if r.get("status") != "ERROR"],
                                                       timeframes, provider_kind, identity, clock)}
    finally:
        mt5.shutdown()


IDENTITY_PIN_KEYS = ("executable", "data_path", "server", "account_fingerprint", "account_currency", "provider_kind")
IDENTITY_STABLE_KEYS = ("terminal_path", "data_path", "server", "account_fingerprint", "account_currency", "connected")


def source_namespace(identity: dict) -> str:
    """Namespace of a collected source: executable, data_path, server, account fingerprint, account currency and
    provider kind. Missing parts are never hashed as a valid identity (verify_attached_identity rejects them first)."""
    parts = [identity.get(k) for k in ("executable", "data_path", "server", "account_fingerprint", "account_currency", "provider_kind")]
    if any(p in (None, "") for p in parts):
        raise ValueError(f"SOURCE_NAMESPACE_INCOMPLETE:{parts}")
    return "mt5_" + hash_obj(parts)[:16]


def _checkpoint_files(root: Path) -> list[Path]:
    if not root.exists():
        return []
    return sorted(list(root.glob("*/bars/*/checkpoint.json")) + list(root.glob("*/ticks/checkpoint.json")))


def _rollback_checkpoints(root: Path, pre_batch: dict, tag: str) -> list[dict]:
    """Tainted checkpoint → kept as checkpoint.<tag>.json; checkpoint restored to its pre-batch bytes (or removed from
    use if it did not exist before). Chunk/pending files are left on disk untouched (raw evidence; unreferenced)."""
    out = []
    for ckp in _checkpoint_files(root):
        cur = ckp.read_bytes()
        old = pre_batch.get(ckp)
        if old == cur:
            continue
        saved = ckp.with_name(f"checkpoint.{tag}.json")
        saved.write_bytes(cur)
        if old is None:
            ckp.unlink()
        else:
            atomic_write_bytes(ckp, old)
        out.append({"checkpoint": str(ckp.relative_to(root)), "tainted_saved_as": saved.name,
                    "restored": "PRE_BATCH_BYTES" if old is not None else "REMOVED_NO_PRIOR_STATE"})
    return out


def _namespace_clash(root: Path, identity: dict) -> list[str]:
    """Existing checkpoints under this namespace must carry the SAME full identity (restart safety); a checkpoint
    without a complete identity is never reused as verified."""
    out = []
    for ckp in _checkpoint_files(root):
        old = (json.loads(ckp.read_text(encoding="utf-8")).get("identity") or {})
        bad = [k for k in IDENTITY_STABLE_KEYS + ("provider_kind", "executable") if old.get(k) != identity.get(k)]
        if bad:
            out.append(f"{ckp.relative_to(root)}:{','.join(bad)}")
    return out


def _clock_clash(root: Path, clock: str) -> list[str]:
    """Existing checkpoints must have been requested under the same clock mapping (legacy checkpoints = RAW_IS_UTC)."""
    out = []
    for ckp in _checkpoint_files(root):
        old = json.loads(ckp.read_text(encoding="utf-8")).get("clock_profile", "RAW_IS_UTC")
        if old != clock:
            out.append(f"{ckp.relative_to(root)}:{old}!={clock}")
    return out


def time_basis_for(clock: dict | None) -> dict:
    """Manifest time basis matching the clock used for the request bounds (one convention end to end)."""
    if not clock or clock.get("profile", "RAW_IS_UTC") == "RAW_IS_UTC":
        st = (clock or {}).get("clock_profile_status")
        return {"time_contract": "API_UTC_CONTRACT", "clock_profile_applied": "RAW_IS_UTC",
                "source_time_basis_recorded": "MT5 Python API values stored exactly as returned (docs: UTC); no offset applied"
                                              + (f"; current probe: {st}" if st else ""),
                "time_basis_status": "DOC_CONTRACT_TIME_UNVERIFIED", "clock_profile_status": st or "DOC_CONTRACT"}
    return {"time_contract": "API_SERVER_CLOCK_PROBED", "clock_profile_applied": clock["profile"],
            "source_time_basis_recorded": (f"MT5 Python API values stored exactly as returned; current fresh-tick probe offset "
                                           f"{clock.get('offset_now_s')} s vs local UTC -> interpreted as {clock['profile']}"),
            "time_basis_status": "PROBE_ASSUMED_NOT_VERIFIED", "clock_profile_status": clock["clock_profile_status"],
            "alternative_profiles": clock.get("alternatives", []),
            "conflict_reason": "API documentation describes UTC; the current source shows a server-clock offset"}


def _tb_entry(clock: dict | None, root: Path) -> dict:
    tb = time_basis_for(clock)
    out = {"contract": tb["time_contract"], "source_time_basis_recorded": tb["source_time_basis_recorded"],
           "source_time_basis_ref": str(root / "manifests"), "time_basis_status": tb["time_basis_status"],
           "clock_profile_status": tb["clock_profile_status"]}
    if tb["time_contract"] != "API_UTC_CONTRACT":
        out.update({"clock_profile_applied": tb["clock_profile_applied"], "alternative_profiles": tb.get("alternative_profiles", []),
                    "conflict_reason": tb["conflict_reason"]})
    if clock:
        out["clock_policy"] = {k: clock.get(k) for k in ("policy", "fresh_offsets_s", "explicit", "flags")}   # no wall clock: content-stable
    return out


def registry_fragment(root: Path, source_id: str, symbols: list[str], timeframes, provider_kind: str = "UNKNOWN",
                      identity: dict | None = None, clock: dict | None = None) -> dict:
    """Dataset entries for collected data (API_UTC_CONTRACT, chunked bars/ticks). Exposure label follows the provider:
    SYNTHETIC data is a software fixture, never live evidence; NATIVE_COLLECTED only names the source (clock/edge unproven)."""
    exposure = ("SYNTHETIC_FIXTURE: software test data, not market evidence" if provider_kind != "NATIVE_TERMINAL"
                else "NATIVE_COLLECTED: unseen by research until registered in exposure_ledger; historical recollection is not forward evidence")
    return {s: {"dataset_id": f"ds_{source_id}_{s.lower()}", "source_id": source_id, "provider_kind": provider_kind,
                "exposure": exposure,
                "time_basis": _tb_entry(clock, root),
                "timeframes": {tf: {"format": "collector_bars_v1", "chunk_dir": str(root / s / "bars" / tf)} for tf in timeframes},
                "ticks": {"format": "collector_ticks_v1", "chunk_dir": str(root / s / "ticks")}}
            for s in symbols}
