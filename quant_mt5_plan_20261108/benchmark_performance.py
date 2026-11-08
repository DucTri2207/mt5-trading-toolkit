"""Read-only same-pin comparison; run separately for baseline and upgraded source.

Only stdout is written. The historical source files are read and hashed, never
collected, edited, or deleted. Timings are process-cold / same-process repeats,
not controlled OS-cold measurements or a live-terminal latency promise.
"""
from __future__ import annotations

import argparse
import contextlib
import hashlib
import json
import os
from pathlib import Path
import statistics
import sys
import time


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-root", required=True)
    parser.add_argument("--workspace-root", required=True)
    parser.add_argument("--cycles", type=int, default=3)
    args = parser.parse_args()
    workspace = Path(args.workspace_root).resolve()
    capture = workspace / "quant_mt5/runtime/on_demand/weekly_fabio_20261102_08/capture"
    bundle = capture / "bundles/CFGB_b278a22ce4b09dfd68f2"
    os.environ["QUANTMT5_CONFIG_DIR"] = str(bundle)
    os.environ["QUANTMT5_WORKSPACE"] = str(workspace)
    sys.path.insert(0, str(Path(args.source_root).resolve()))
    from quantmt5.detectors import load_symbol, detect_all
    from quantmt5.mt5_flow import read_snapshot_mt5
    from quantmt5.util import hash_obj, parse_utc
    import numpy as np
    source_hashes = {name: hashlib.sha256((Path(args.source_root) / "quantmt5" / name).read_bytes()).hexdigest()
                     for name in ("collector.py", "data.py", "detectors.py", "replay.py", "mt5_flow.py", "analysis_cache.py")
                     if (Path(args.source_root) / "quantmt5" / name).exists()}
    try:
        from quantmt5.analysis_cache import analysis_scope
    except ImportError:
        analysis_scope = contextlib.nullcontext
    snapshot = json.loads((capture / "store/snapshots/SNAP_f05620cbbcb761935e5c.json").read_text(encoding="utf-8"))
    symbol = "EURUSD"
    pins = snapshot["data_versions"][symbol]
    asof = parse_utc("2026-11-06T13:00:00Z")
    results = []
    for cycle in range(args.cycles):
        passes = []
        started = time.perf_counter()
        with analysis_scope() as stats:
            for repeat in range(2):
                t = time.perf_counter()
                sd = load_symbol(symbol, pins=pins, cut_available_at=asof)
                bars_s = time.perf_counter() - t
                t = time.perf_counter()
                catalog = detect_all(sd)
                catalog_s = time.perf_counter() - t
                t = time.perf_counter()
                flow = read_snapshot_mt5(snapshot, sd.m5, symbol, asof)
                flow_s = time.perf_counter() - t
                passes.append({"bars_s": bars_s, "catalog_s": catalog_s, "flow_s": flow_s,
                               "total_s": bars_s + catalog_s + flow_s})
        total = time.perf_counter() - started
        parity = {"candidate_hash": hash_obj(catalog), "candidate_count": len(catalog["candidates"]),
                  "episode_count": len(catalog["episodes"]), "flow_hash": hash_obj(flow),
                  "flow_status": flow["flow"]["status"], "flow_bars": flow["flow"].get("bars_used"),
                  "m5_bars": len(sd.m5), "tick_chunks": len(snapshot["tick_versions"][symbol]["chunks"])}
        results.append({"cycle": cycle, "elapsed_s": total, "passes": passes, "cache": stats, "parity": parity})
    print(json.dumps({"source_root": args.source_root, "source_sha256": source_hashes,
                      "environment": {"python": sys.version, "numpy": np.__version__, "platform": sys.platform},
                      "workload": "EURUSD same pinned Friday snapshot, 2 analysis/report reads per cycle",
                      "first_cycle_s": results[0]["elapsed_s"],
                      "repeat_cycle_median_s": statistics.median(x["elapsed_s"] for x in results[1:]) if len(results) > 1 else None,
                      "caveat": "OS cache uncontrolled; other agents may run tests concurrently; not production p95",
                      "results": results}, ensure_ascii=True, indent=2))


if __name__ == "__main__":
    main()
