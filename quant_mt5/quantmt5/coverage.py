"""Coverage: requested window vs received bars, against the declared session schedule.

Classification of every expected bar slot (open time) in [start, end):
* PRESENT                    bar exists and the schedule says the market is open
* SCHEDULED_CLOSED           no bar, schedule says closed (weekend / daily break) — not a data gap
* MISSING_UNEXPLAINED        no bar while the schedule says open (holiday, no-price minute, or lost data — not decided)
* PRESENT_OUTSIDE_SCHEDULE   bar exists while the schedule says closed (schedule or clock-hypothesis mismatch)
The schedule is expressed in America/New_York time, so the result is CONDITIONAL on the dataset's clock profile.
"""
from __future__ import annotations

import datetime as dt
from typing import Any

import numpy as np

from .data import TF_SECONDS, Bars
from .timemap import NY, UTC

DOW = {"Mon": 0, "Tue": 1, "Wed": 2, "Thu": 3, "Fri": 4, "Sat": 5, "Sun": 6}


def _ny_local(ts: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """(weekday, minute_of_day) in America/New_York for UTC epoch seconds (vectorised per hour)."""
    ts = np.asarray(ts, dtype=np.int64)
    hrs = ts // 3600
    uniq, inv = np.unique(hrs, return_inverse=True)
    offs = np.array([int(dt.datetime.fromtimestamp(int(h) * 3600, UTC).astimezone(NY).utcoffset().total_seconds()) for h in uniq], np.int64)
    loc = ts + offs[inv]
    days = loc // 86400
    wd = (days + 3) % 7  # 1970-01-01 was a Thursday
    return wd, (loc % 86400) // 60


def scheduled_open(ts_utc: np.ndarray, session: dict) -> np.ndarray:
    """Boolean per timestamp: is the market scheduled open? Unknown schedule → all True (nothing classified closed)."""
    if not session or session.get("tz") != "America/New_York":
        return np.ones(len(ts_utc), bool)
    wd, mod = _ny_local(ts_utc)
    wc_day, wc_t = session.get("weekly_close", "Fri 17:00").split()
    wc = int(wc_t[:2]) * 60 + int(wc_t[3:])
    kind = session.get("kind")
    reopen_s = session.get("daily_reopen") if kind == "DAILY_BREAK" else (session.get("rollover") or "17:00")
    ro = int(reopen_s[:2]) * 60 + int(reopen_s[3:])
    closed = (wd == 5) | ((wd == DOW[wc_day]) & (mod >= wc)) | ((wd == 6) & (mod < ro))
    if kind == "DAILY_BREAK" and session.get("daily_close"):
        dc = int(session["daily_close"][:2]) * 60 + int(session["daily_close"][3:])
        closed |= (wd <= 3) & (mod >= dc) & (mod < ro)
    return ~closed


def bar_coverage(b: Bars, start: float, end: float, session: dict | None, top: int = 10) -> dict[str, Any]:
    tfs = TF_SECONDS[b.tf]
    if tfs >= 86400:
        return {"status": "NOT_APPLICABLE_FOR_D1", "rows": int(((b.open_at >= start) & (b.open_at < end)).sum())}
    slots = np.arange(int(start) // tfs * tfs, int(end), tfs, dtype=np.int64)
    present = np.isin(slots, b.open_at)
    open_ = scheduled_open(slots, session or {})
    cls = {"PRESENT": int((present & open_).sum()), "SCHEDULED_CLOSED": int((~present & ~open_).sum()),
           "MISSING_UNEXPLAINED": int((~present & open_).sum()), "PRESENT_OUTSIDE_SCHEDULE": int((present & ~open_).sum())}
    miss = (~present & open_).astype(np.int8)
    edges = np.flatnonzero(np.diff(np.r_[0, miss, 0]))
    runs = sorted(((int(e1 - e0), int(slots[e0])) for e0, e1 in zip(edges[::2], edges[1::2])), reverse=True)[:top]
    expected_open = cls["PRESENT"] + cls["MISSING_UNEXPLAINED"]
    by_year: dict[str, dict] = {}
    yrs = np.array([dt.datetime.fromtimestamp(int(s), UTC).year for s in slots[:: max(1, 86400 // tfs)]])
    for y in np.unique(yrs):
        y0 = dt.datetime(int(y), 1, 1, tzinfo=UTC).timestamp()
        y1 = dt.datetime(int(y) + 1, 1, 1, tzinfo=UTC).timestamp()
        m = (slots >= y0) & (slots < y1)
        eo = int((open_ & m).sum())
        by_year[str(int(y))] = {"expected_open_slots": eo, "present_open": int((present & open_ & m).sum()),
                                "coverage_of_open": (int((present & open_ & m).sum()) / eo) if eo else None}
    return {"tf": b.tf, "requested": {"start": _iso(start), "end": _iso(end)}, "slots": int(len(slots)), "classes": cls,
            "coverage_of_scheduled_open": (cls["PRESENT"] / expected_open) if expected_open else None,
            "longest_unexplained_runs": [{"bars": n, "from": _iso(t), "minutes": n * tfs / 60} for n, t in runs],
            "by_year": by_year, "schedule": session, "clock_profile": b.provenance.get("clock_profile"),
            "conditional_on": "session schedule (NY time) and the dataset clock profile "
                              f"({b.provenance.get('clock_profile')}, {b.provenance.get('clock_profile_status')}); no holiday calendar"}


def _iso(t) -> str:
    return dt.datetime.fromtimestamp(int(t), UTC).isoformat().replace("+00:00", "Z")
