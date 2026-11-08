"""Clock profiles: how a stored numeric timestamp is interpreted as UTC.

This module makes NO general claim about what MT5 returns. The MetaTrader5 Python API documentation describes
copy_rates_* / copy_ticks_* timestamps as UTC; data collected through that API follows the registry's
``API_UTC_CONTRACT`` (profile RAW_IS_UTC, no offset). Old research archives follow ``LEGACY_CACHE_HYPOTHESIS``:
their recorded basis is kept verbatim and the profile below is an explicitly ASSUMED research hypothesis.

* ``RAW_IS_UTC`` stored value is UTC (API documentation contract; also the falsification baseline for caches)
* ``EET_EU``     stored value is EET/EEST wall clock with EU DST rules (UTC+2 / UTC+3) — hypothesis for the
                 legacy caches, most consistent with their session boundaries (audit.clock_evidence)
* ``NY_PLUS_7``  stored value is America/New_York wall + 7h (UTC+2 / UTC+3 on US DST rules) — alternative hypothesis

A profile is applied exactly once (data.time_lineage). Nothing here upgrades time to VERIFIED; that needs an
observed clock comparison reviewed outside the engine.
"""
from __future__ import annotations

import datetime as dt
from functools import lru_cache
from zoneinfo import ZoneInfo

import numpy as np

NY = ZoneInfo("America/New_York")
ATHENS = ZoneInfo("Europe/Athens")
UTC = dt.timezone.utc

PROFILES = ("NY_PLUS_7", "EET_EU", "RAW_IS_UTC")


@lru_cache(maxsize=None)
def _offset_for_server_date(profile: str, ordinal: int) -> int:
    """Offset (seconds) such that utc = server_raw - offset, decided per *server calendar date*.

    DST switches happen on Sunday ~02:00 local (NY) or 03:00/04:00 (EU), when FX/metal CFD markets are closed
    (server Sunday morning), so a per-date offset is exact for all tradable bars."""
    d = dt.date.fromordinal(ordinal)
    if profile == "RAW_IS_UTC":
        return 0
    if profile == "NY_PLUS_7":
        # midday NY on that date (server date ~ NY date when NY time is 17:00 the previous day; use noon NY)
        off = dt.datetime(d.year, d.month, d.day, 12, tzinfo=NY).utcoffset()
        return int(off.total_seconds()) + 7 * 3600  # -4h+7h = +3h (DST) ; -5h+7h = +2h (std)
    if profile == "EET_EU":
        off = dt.datetime(d.year, d.month, d.day, 12, tzinfo=ATHENS).utcoffset()
        return int(off.total_seconds())
    raise ValueError(f"unknown clock profile {profile}")


def server_to_utc(raw: np.ndarray | int, profile: str) -> np.ndarray:
    raw_arr = np.atleast_1d(np.asarray(raw, dtype=np.int64))
    days = raw_arr // 86400  # server calendar day number (epoch days)
    uniq, inv = np.unique(days, return_inverse=True)
    epoch_ord = dt.date(1970, 1, 1).toordinal()
    offs = np.array([_offset_for_server_date(profile, int(u) + epoch_ord) for u in uniq], dtype=np.int64)
    out = raw_arr - offs[inv]
    return out


def utc_to_server(utc_ts: int, profile: str) -> int:
    """Inverse for a single timestamp (used for as-of / window bounds)."""
    # try both candidate offsets and keep the self-consistent one
    for guess in (2 * 3600, 3 * 3600, 0):
        raw = int(utc_ts) + guess
        if int(server_to_utc(raw, profile)[0]) == int(utc_ts):
            return raw
    return int(utc_ts) + _offset_for_server_date(profile, dt.datetime.fromtimestamp(utc_ts, UTC).date().toordinal())


def ny_local(utc_ts: np.ndarray) -> list[dt.datetime]:
    return [dt.datetime.fromtimestamp(int(t), UTC).astimezone(NY) for t in np.atleast_1d(utc_ts)]


def ny_minutes_of_day(utc_ts: np.ndarray) -> np.ndarray:
    """Minute-of-day in America/New_York (IANA rules, DST-aware), vectorised by caching per UTC day."""
    ts = np.atleast_1d(np.asarray(utc_ts, dtype=np.int64))
    hours = ts // 3600
    uniq, inv = np.unique(hours, return_inverse=True)
    offs = np.array([int(dt.datetime.fromtimestamp(int(h) * 3600, UTC).astimezone(NY).utcoffset().total_seconds())
                     for h in uniq], dtype=np.int64)
    local = ts + offs[inv]
    return (local % 86400) // 60


def us_dst_active(utc_ts: int) -> bool:
    return bool(dt.datetime.fromtimestamp(int(utc_ts), UTC).astimezone(NY).dst())


def eu_dst_active(utc_ts: int) -> bool:
    return bool(dt.datetime.fromtimestamp(int(utc_ts), UTC).astimezone(ATHENS).dst())
