"""Run a frozen synthetic 8-symbol session -> focused 20-minute update -> finalization."""
from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile
import time
from pathlib import Path


def main():
    workspace = Path(__file__).resolve().parents[1]
    output = workspace / "quant_mt5_plan_20261108" / "focused_session_smoke_20261108"
    output.mkdir(exist_ok=True)
    root = Path(tempfile.mkdtemp(prefix="frozen_", dir=output))
    project = root / "engine" / "quant_mt5"
    for name in ("quantmt5", "config"):
        shutil.copytree(workspace / "quant_mt5" / name, project / name,
                        ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    shutil.copy2(workspace / "quant_mt5" / "run_quant.py", project / "run_quant.py")
    os.environ["QUANTMT5_ALLOW_SYNTHETIC_FIXTURE"] = "1"
    os.environ["QUANTMT5_STORE"] = str(root / "driver_store")
    os.environ["QUANTMT5_WORKSPACE"] = str(workspace)
    sys.path.insert(0, str(project))
    from quantmt5 import session
    from quantmt5.universe import MAIN8
    from quantmt5.util import atomic_write_json, engine_hash, parse_utc
    fixture = workspace / "quant_mt5_plan_20261108" / "benchmark_universe_smoke.py"
    session.init_session(root, "evening8", str(root / "fake_terminal64.exe"), dict(zip(MAIN8, MAIN8)),
                         mode="SYNTHETIC_FIXTURE", synthetic_fixture=str(fixture), lookback_days=7)
    start = parse_utc("2025-01-15T15:30:00Z")
    began = time.perf_counter()
    full = session.on_demand(root, "evening8", end_utc=start)
    full_wall = time.perf_counter() - began
    atomic_write_json(root / "full8.json", full)
    assert full["status"] == "OK", full
    began = time.perf_counter()
    focused = session.on_demand(root, "evening8", end_utc=start + 20 * 60, focused_symbols=["GBPUSD"])
    focused_wall = time.perf_counter() - began
    atomic_write_json(root / "focused1.json", focused)
    assert focused["status"] == "OK", focused
    assert set(full["cycle"]["symbols"]) == set(MAIN8)
    assert set(focused["cycle"]["symbols"]) == {"GBPUSD"}
    assert focused["cycle"]["source_id"] == full["cycle"]["source_id"]
    assert focused["cycle"]["snapshot_id"] != full["cycle"]["snapshot_id"]
    assert focused["cycle"]["analysis"]["market"]["GBPUSD"]["symbol"] == "GBPUSD"
    old, latest = full["finish_token"], focused["finish_token"]
    assert latest["generation_id"] == old["generation_id"]
    stale = session.finish(root, "evening8", old["cycle_id"], old["generation_id"], old["snapshot_id"])
    assert stale["status"] == "REFUSED" and stale["reason"] == "STALE_FINALIZATION_REQUEST", stale
    closed = session.finish(root, "evening8", latest["cycle_id"], latest["generation_id"], latest["snapshot_id"])
    atomic_write_json(root / "finish.json", closed)
    assert closed["status"] == "CLOSED", closed
    record = {"qualification": "SYNTHETIC SOFTWARE SMOKE ONLY; isolated frozen engine; not live latency or winrate evidence",
              "root": str(root), "engine_hash": engine_hash(), "full8_wall_s": round(full_wall, 4),
              "focused1_plus20min_wall_s": round(focused_wall, 4), "full8_status": full["status"],
              "focused1_status": focused["status"], "source_identity_unchanged": True,
              "new_snapshot": focused["cycle"]["snapshot_id"], "stale_finish": stale,
              "latest_finish_status": closed["status"], "focused_timings_s": focused["cycle"].get("timings_s")}
    atomic_write_json(output / "summary.json", record)
    print(json.dumps(record), flush=True)


if __name__ == "__main__":
    main()
