"""Bounded, single-analysis reuse. Nothing survives the outer scan's scope.

Loaders must validate their source/pin *before* consulting this cache. Cache keys
are content/read-contract identities, never merely a symbol or a pathname.
"""
from __future__ import annotations

from collections import OrderedDict
from contextlib import contextmanager
from contextvars import ContextVar


_ACTIVE = ContextVar("quantmt5_analysis_cache", default=None)
_MISSING = object()
_LIMITS = {"tick_tape": 12, "archive": 8, "collected_bars": 64,
           "bars": 128, "symbol": 32, "catalog": 32}
_TICK_BYTE_LIMIT = 256 * 1024 * 1024


@contextmanager
def analysis_scope():
    """Yield serializable counters; nested scopes share their outer scan cache."""
    state = _ACTIVE.get()
    if state is not None:
        yield state[1]
        return
    stats = {"hits": 0, "misses": 0, "evictions": 0, "by_kind": {}, "entries": 0, "tick_cache_bytes": 0}
    token = _ACTIVE.set(({}, stats))
    try:
        yield stats
    finally:
        _ACTIVE.reset(token)


def cached(kind, key, build):
    """Memoize a validated value inside the current analysis only."""
    state = _ACTIVE.get()
    if state is None:
        return build()
    caches, stats = state
    cache = caches.setdefault(kind, OrderedDict())
    counters = stats["by_kind"].setdefault(kind, {"hits": 0, "misses": 0, "evictions": 0})
    value = cache.pop(key, _MISSING)
    outcome = "hits" if value is not _MISSING else "misses"
    stats[outcome] += 1
    counters[outcome] += 1
    if value is _MISSING:
        value = build()
    cache[key] = value
    tape_bytes = sum(v[0].nbytes for v in cache.values()) if kind == "tick_tape" else 0
    while len(cache) > _LIMITS.get(kind, 4) or (kind == "tick_tape" and tape_bytes > _TICK_BYTE_LIMIT):
        _, evicted = cache.popitem(last=False)
        if kind == "tick_tape":
            tape_bytes -= evicted[0].nbytes
        counters["evictions"] += 1
        stats["evictions"] += 1
    if kind == "tick_tape":
        stats["tick_cache_bytes"] = tape_bytes
    stats["entries"] = sum(len(c) for c in caches.values())
    return value
