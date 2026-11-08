"""Environment / source health. Never launches or attaches to a terminal."""
from __future__ import annotations

import importlib
import os
import platform
import shutil
import sys

from . import ENGINE_VERSION, SCHEMA_VERSION
from .collector import running_terminal_paths
from .data import load_registry, resolve
from .util import STORE_DIR, engine_hash, iso_utc, now_utc


def doctor() -> dict:
    reg = load_registry()
    pk = {}
    for m in ("numpy", "pandas", "MetaTrader5", "tzdata", "pytest"):
        try:
            mod = importlib.import_module(m)
            pk[m] = getattr(mod, "__version__", "present")
        except ImportError:
            pk[m] = None
    sel = reg["source_identity"]["terminal_executable"]
    running = running_terminal_paths()
    sources = {}
    for sym, d in reg["symbols"].items():
        for tf, spec in d["timeframes"].items():
            if "path" in spec:
                sources[f"{sym}/{tf}"] = os.path.exists(resolve(spec["path"]))
    STORE_DIR.mkdir(parents=True, exist_ok=True)
    free = shutil.disk_usage(STORE_DIR).free
    sel_running = os.path.normcase(os.path.abspath(sel)) in running
    flags = []
    if not sel_running:
        flags.append("LIVE_SOURCE_NOT_RUNNING")
    if not all(sources.values()):
        flags.append("CACHE_SOURCE_MISSING")
    return {"engine_version": ENGINE_VERSION, "schema_version": SCHEMA_VERSION, "engine_hash": engine_hash(),
            "python": sys.version.split()[0], "platform": platform.platform(), "packages": pk,
            "selected_terminal": sel, "running_terminals": running, "selected_terminal_running": sel_running,
            "live_attach_performed": False, "cache_sources_present": sources, "store_dir": str(STORE_DIR),
            "store_free_gb": round(free / 1e9, 1), "checked_at": iso_utc(now_utc()), "flags": flags,
            "time_basis": {s: {k: d["time_basis"].get(k) for k in ("contract", "clock_profile_applied", "clock_profile_status", "time_basis_status")}
                           for s, d in reg["symbols"].items()}}
