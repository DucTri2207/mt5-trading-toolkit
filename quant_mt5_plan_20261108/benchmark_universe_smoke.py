"""Synthetic 8/12-symbol end-to-end smoke. Not a production/live latency benchmark."""
from __future__ import annotations

import argparse
import importlib.util
import json
import os
import sys
import time
from pathlib import Path


def _fixtures():
    workspace = Path(__file__).resolve().parents[1]
    fixture = workspace / "quant_mt5/phases/B6B_INTEGRATION_20261104/attempt_3/codex_cases/b6b_fake_source.py"
    spec = importlib.util.spec_from_file_location("evening_benchmark_source", fixture)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    class MultiSource(module.FakeSource):
        @staticmethod
        def parameters(symbol):
            return (1.0, 2, .01) if symbol == "XAUUSD" else ((.075, 3, .001) if symbol.endswith("JPY") else (.0005, 5, .00001))

        def symbol_info(self, symbol):
            scale, digits, point = self.parameters(symbol)
            return dict(module.PROFILE, name=symbol, path="SYNTHETIC/" + symbol, digits=digits, point=point,
                        trade_tick_size=point, trade_contract_size=100 if symbol == "XAUUSD" else 100000,
                        currency_base=symbol[:3], currency_profit=symbol[3:], currency_margin=symbol[:3],
                        trade_calc_mode=2 if symbol == "XAUUSD" else 0)

        def copy_rates_range(self, symbol, tf, start, end):
            data = super().copy_rates_range(symbol, tf, start, end).copy()
            scale, digits, point = self.parameters(symbol)
            for field in ("open", "high", "low", "close"):
                data[field] = (data[field] * scale).round(digits)
            data["spread"] = round(module.SPREAD_PTS * .01 * scale / point)
            return data

        def copy_ticks_range(self, symbol, start, end, flags):
            data = super().copy_ticks_range(symbol, start, end, flags).copy()
            scale, digits, _ = self.parameters(symbol)
            for field in ("bid", "ask"):
                data[field] = (data[field] * scale).round(digits)
            return data

        def symbol_info_tick(self, symbol):
            tick = super().symbol_info_tick(symbol)
            if tick:
                scale, digits, _ = self.parameters(symbol)
                tick.update({field: round(tick[field] * scale, digits) for field in ("bid", "ask")})
            return tick

    return module, MultiSource


def make(exe, end_utc):
    """CLI synthetic-fixture entry for isolated session integration checks."""
    from quantmt5.universe import EXTENDED12
    module, source_type = _fixtures()
    source = source_type(exe, end=int(end_utc), tick_window=(int(end_utc) - 240 * 60, int(end_utc)))
    return source, lambda: [exe], {s: module.FIXTURE_SESSION for s in EXTENDED12}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--out-root", type=Path, required=True)
    parser.add_argument("--days", type=float, default=7)
    parser.add_argument("--warm-only", action="store_true")
    args = parser.parse_args()
    args.out_root = args.out_root.resolve()
    workspace = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(workspace / "quant_mt5"))
    os.environ["QUANTMT5_STORE"] = str(args.out_root / "driver_store")
    from quantmt5.paper import paper_run
    from quantmt5.universe import MAIN8, EXTENDED12
    from quantmt5.util import atomic_write_json
    module, MultiSource = _fixtures()

    exe = os.path.normcase(os.path.abspath(str(args.out_root / "synthetic_terminal64.exe")))
    records = []
    for label, universe in (("main8", MAIN8), ("extended12", EXTENDED12)):
        for stage in (("warm_after_cache_update",) if args.warm_only else ("cold", "warm_same_asof")):
            source = MultiSource(exe, end=module.END, tick_window=(module.END - 240 * 60, module.END))
            began = time.perf_counter()
            result = paper_run(exe, dict(zip(universe, universe)), out_root=args.out_root / label,
                               end_utc=module.END, lookback_days=args.days, tick_minutes=240,
                               mt5_module=source, process_lister=lambda: [exe],
                               sessions={s: module.FIXTURE_SESSION for s in universe},
                               clock_profile="RAW_IS_UTC", scan_timeout_s=240)
            scan = (result.get("scan") or {}).get("data") or {}
            record = {"universe": label, "stage": stage, "status": result["status"],
                      "wall_s": round(time.perf_counter() - began, 4), "timings_s": result.get("timings_s"),
                      "bar_requests": source.calls.count("copy_rates_range"), "tick_requests": source.calls.count("copy_ticks_range"),
                      "symbols": len(scan.get("symbols") or {}), "fabio_symbols": len(scan.get("fabio") or {}),
                      "market_context_symbols": len((scan.get("analysis") or {}).get("market") or {}),
                      "cards": len((scan.get("analysis") or {}).get("cards") or {}),
                      "analysis_errors": (scan.get("analysis") or {}).get("errors"), "cache_stats": scan.get("cache_stats"),
                      "snapshot_id": scan.get("snapshot_id"), "reason": result.get("reason")}
            records.append(record)
            atomic_write_json(args.out_root / f"{label}_{stage}.json", result)
            print(json.dumps(record), flush=True)
    atomic_write_json(args.out_root / ("summary_warm_after_cache_update.json" if args.warm_only else "summary.json"), {
        "qualification": "SYNTHETIC SMOKE ONLY: one shared tape transformed to 8/12 symbols; two runs, not p95; no live MT5 or orders",
        "history_days": args.days, "tick_minutes": 240, "records": records})


if __name__ == "__main__":
    main()
