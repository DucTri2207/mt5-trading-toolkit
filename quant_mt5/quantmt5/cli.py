"""`quant` CLI — every command prints one JSON envelope {status, schema_version, request_id, snapshot_id, as_of, data, quality, errors}."""
from __future__ import annotations

import argparse
import io
import json
import sys
import traceback
from collections import Counter
from pathlib import Path

from . import ENGINE_VERSION, STRATEGY_VERSION
from .config import config_hash
from .util import PROJECT_DIR, STORE_DIR, atomic_write_json, atomic_write_text, envelope, iso_utc, now_utc, parse_utc, pretty_json, stable_id, write_immutable_json

PILOT = ["XAUUSD", "EURUSD", "USDJPY"]


def _emit(env: dict, out: str | None = None) -> int:
    txt = pretty_json(env)
    if out:
        atomic_write_text(out, txt + "\n")
    sys.stdout.write(txt + "\n")
    return 0 if env["status"] != "ERROR" else 2


# ------------------------------------------------------------------ commands
def cmd_doctor(a):
    from .doctor import doctor
    d = doctor()
    return envelope("OK" if not d["flags"] else "PARTIAL", d, quality=d["flags"], command="doctor")


def cmd_audit(a):
    from .audit import run_audit
    syms = a.symbols.split(",") if a.symbols else None
    r = run_audit(syms)
    r["generated_at"] = iso_utc(now_utc())
    p = STORE_DIR / "audit" / "AUDIT_REPORT.json"
    atomic_write_json(p, r)
    summary = {s: {"flags": v["flags"], "clock_verdict": v["clock_evidence_M5"]["verdict"],
                   "price_grid": v["price_grid_M5"]["inferred_tick_size"],
                   "rows": {tf: x.get("integrity", {}).get("rows") for tf, x in v["timeframes"].items()},
                   "real_volume": v["timeframes"]["M5"]["volume"]["real_volume_status"]} for s, v in r["symbols"].items()}
    return envelope("PARTIAL", {"report_path": str(p), "summary": summary}, quality=sorted({f for v in r["symbols"].values() for f in v["flags"]}),
                    command="audit")


def cmd_snapshot(a):
    from .snapshot import make_snapshot
    as_of = parse_utc(a.as_of) if a.as_of else now_utc()
    snap = make_snapshot(as_of, a.universe.split(","), include_scan=not a.no_scan)
    st = "OK" if not snap["errors"] else ("PARTIAL" if len(snap["errors"]) < len(snap["universe"]) else "ERROR")
    data = {"snapshot_path": str(STORE_DIR / "snapshots" / (snap["snapshot_id"] + ".json")),
            "symbols": snap["symbols"], "n_candidates": len(snap["candidates"]), "n_episodes": len(snap["episodes"])}
    q = sorted({f for v in snap["symbols"].values() for f in v.get("quality_flags", [])})
    return envelope(st, data, snapshot_id=snap["snapshot_id"], as_of=snap["as_of_utc"], quality=q, errors=snap["errors"], command="snapshot")


def cmd_scan(a):
    from .snapshot import load_snapshot, scan
    snap = load_snapshot(a.snapshot)
    r = scan(snap)
    q = sorted({f for v in snap["symbols"].values() for f in v.get("quality_flags", [])})
    return envelope(r["status"], r, snapshot_id=snap["snapshot_id"], as_of=snap["as_of_utc"], quality=q, errors=snap["errors"], command="scan")


def cmd_catalog(a):
    from .snapshot import catalog_view
    r = catalog_view(a.snapshot, a.symbol, a.from_, a.setup, a.limit)
    st = "PARTIAL" if r["catalog_meta"].get("view_flags") else ("OK" if r["candidates_total"] else "OK_EMPTY")
    return envelope(st, r, snapshot_id=a.snapshot, as_of=r["as_of"],
                    quality=r.get("quality_flags") or [], command="catalog")


def cmd_context(a):
    from .context import build_context, build_market_context
    groups = a.groups.split(",") if a.groups else []
    if a.candidate:
        r = build_context(a.snapshot, a.candidate, groups, at=a.at)
        when = r["decision_at"]
    elif a.symbol:
        r = build_market_context(a.snapshot, a.symbol, groups)
        when = r["as_of"]
    else:
        return envelope("ERROR", None, errors=[{"reason": "ARGS: give --candidate or --symbol"}], command="context")
    unk = [f["name"] for f in r["features"] if f.get("quality") != "OK"]
    return envelope("OK" if not unk else "PARTIAL", r, snapshot_id=a.snapshot, as_of=when,
                    quality=[f"UNKNOWN:{n}" for n in unk] + list(r.get("quality_flags") or []), command="context")


def cmd_coverage(a):
    from .config import profile
    from .coverage import bar_coverage
    from .data import load_bars
    b = load_bars(a.symbol, a.tf)
    if b is None:
        return envelope("ERROR", None, errors=[{"reason": f"HISTORY_INSUFFICIENT:{a.symbol}:{a.tf}"}], command="coverage")
    start = parse_utc(a.start) if a.start else float(b.open_at[0])
    end = parse_utc(a.end) if a.end else float(b.close_at[-1])
    r = bar_coverage(b, start, end, profile(a.symbol).get("session"))
    st = "OK" if r.get("classes", {}).get("MISSING_UNEXPLAINED", 0) == 0 else "PARTIAL"
    return envelope(st, r, quality=list(b.provenance.get("time_quality_flags", [])), command="coverage")


def cmd_explain(a):
    from .context import explain
    r = explain(a.snapshot, a.candidate)
    return envelope("OK", r, snapshot_id=a.snapshot, quality=r.get("quality_flags"), command="explain")


def cmd_replay(a):
    from .replay import replay
    r = replay(a.candidate, a.symbol, a.latency, a.cost, snapshot_id=a.snapshot, ticks_path=a.ticks)
    return envelope("OK" if r.get("found") else "ERROR", r, quality=r.get("flags", []),
                    errors=[] if r.get("found") else [{"reason": "CANDIDATE_NOT_FOUND"}], command="replay")


def default_experiment() -> dict:
    from .config import cost_profiles, strategy
    return {
        "name": "B4_six_configs_seed_v0_1",
        "question": "Do H1 event confirmation (M2) and known-level location (P1) / NY window (P2) add net value over their controls, after quote-side costs and latency?",
        "strategy_version": STRATEGY_VERSION, "engine_version": ENGINE_VERSION,
        "universe": PILOT, "branches": ["M0", "M1", "M2", "P0", "P1", "P2"],
        "primary_comparisons": ["M2-M0", "M2-M1", "P1-P0", "P2-P1"],
        "multiple_testing": "Holm over the 4 primary comparisons per scenario; 9 scenarios reported, none chosen as headline after the fact (headline = BASE latency / BASE cost declared here)",
        "evaluation": {"start": "2021-02-01", "end": "2026-10-23", "calendar": "NY session days Mon-Fri incl. zero days",
                       "warmup_note": "ATR M5 200 bars, EMA50 H1 250 bars complete before 2021-02-01"},
        "latency_scenarios": ["BASE", "MANUAL", "SLOW"], "cost_scenarios": ["LOW", "BASE", "ADVERSE"],
        "headline": {"latency": "BASE", "cost": "BASE"},
        "execution": "M1_OPEN_PROXY where M1 exists (XAUUSD); FX not evaluable (no M1/ticks/contract) — catalog statistics only",
        "metrics": ["net R per trade & per day (block bootstrap 5-day blocks, 2000 resamples, seed 20261103)", "drawdown", "frequency",
                    "cost/R", "MAE/MFE", "by year/side/NY bucket", "ambiguity sensitivity", "paired daily differences"],
        "portfolio": {"declared_pair": strategy()["portfolio"]["declared_pair"], "status": strategy()["portfolio"]["pair_status"]},
        "exposure": "HISTORICAL_EXPOSED for all symbols/years (see config/datasets.json). Results are NOT final OOS.",
        "label_if_results_seen_before_registration": "EXPLORATORY",
        "cost_profile_version": cost_profiles()["cost_profile_version"],
    }


def cmd_register(a):
    exp = default_experiment()
    if a.file:
        exp = json.loads(Path(a.file).read_text(encoding="utf-8"))
    eid = stable_id("EXP", exp)
    exp = dict(exp, experiment_id=eid)
    p = STORE_DIR / "experiments" / f"{eid}.json"
    if p.exists():
        rec = json.loads(p.read_text(encoding="utf-8"))
        return envelope("OK", {"experiment_id": eid, "path": str(p), "registered_at": rec["registered_at"], "already_registered": True}, command="register")
    rec = dict(exp, registered_at=iso_utc(now_utc()), results_seen_before_registration=bool(a.exploratory))
    write_immutable_json(p, rec)
    return envelope("OK", {"experiment_id": eid, "path": str(p), "registered_at": rec["registered_at"]}, command="register")


def cmd_evaluate(a):
    from .evaluate import run_experiment
    from .report import write_run
    p = STORE_DIR / "experiments" / f"{a.experiment}.json"
    if not p.exists():
        return envelope("ERROR", None, errors=[{"reason": "EXPERIMENT_NOT_REGISTERED", "hint": "run `quant register` first"}], command="evaluate")
    exp = json.loads(p.read_text(encoding="utf-8"))
    log = []
    res = run_experiment(exp, progress=lambda s: (log.append(s), print(s, file=sys.stderr)))
    run_dir = write_run(exp, res, log)
    return envelope("OK", {"run_dir": str(run_dir), "headline": res["results"]["BASE/BASE"] and
                           {br: {k: res["results"]["BASE/BASE"][br][k] for k in ("n_fills", "net_R_total", "expectancy_R_per_trade", "verdict")}
                            for br in ("M0", "M1", "M2", "P0", "P1", "P2")}},
                    quality=["HISTORICAL_EXPOSED", "QUOTE_MODEL_M1_OPEN_PROXY", "COSTS_ASSUMED", "TIME_UNVERIFIED"], command="evaluate")


def cmd_fabio(a):
    """Research-only F1/F2 analysis from one snapshot (+ optional external flow / FTMO quote files). Writes a store/fabio artifact."""
    from .fabio import render_report, run_for_snapshot
    from .util import sha256_file
    flow = json.loads(Path(a.flow).read_text(encoding="utf-8")) if a.flow else None
    ex = json.loads(Path(a.exec).read_text(encoding="utf-8")) if a.exec else None
    previous = json.loads(Path(a.previous_analysis).read_text(encoding="utf-8")) if a.previous_analysis else None
    if previous is not None and "data" in previous:
        previous = previous["data"]
    r = run_for_snapshot(a.snapshot, a.symbol, flow, ex, sha256_file(a.flow) if a.flow else None, sha256_file(a.exec) if a.exec else None,
                         store=not a.no_store, policy=a.policy, **({"previous_analysis": previous} if previous is not None else {}))
    if a.report:
        atomic_write_text(a.report, render_report(r))
        r["report_path"] = a.report
    q = [f"FLOW:{r['flow']['status']}"] if r.get("flow") else ["FLOW:NOT_PROVIDED"]
    st = "OK" if r["decision"] != "DATA_UNAVAILABLE" else "PARTIAL"
    return envelope(st, r, snapshot_id=a.snapshot, as_of=r["as_of"], quality=q + list(r.get("quality_flags") or []), command="fabio")


def cmd_fabio_replay(a):
    from .fabio_replay import replay_artifact
    analysis = json.loads(Path(a.analysis).read_text(encoding="utf-8"))
    if "data" in analysis:
        analysis = analysis["data"]
    r = replay_artifact(analysis, a.family, a.snapshot, latency_s=a.latency_s,
                        commission_price_rt=a.commission_price_rt, slippage_price=a.slippage_price,
                        max_hold_s=a.max_hold_s, store=not a.no_store)
    return envelope("PARTIAL" if r["status"] in ("UNRESOLVED", "CENSORED") else "OK", r,
                    snapshot_id=a.snapshot, command="fabio-replay")


def cmd_note(a):
    from .notes import add_note, list_notes
    if a.action == "add":
        note = json.loads(Path(a.file).read_text(encoding="utf-8"))
        rec = add_note(note)
        return envelope("OK", rec, snapshot_id=rec["snapshot_id"], as_of=rec["as_of"], command="note add")
    rows = list_notes(a.candidate)
    return envelope("OK" if rows else "OK_EMPTY", rows, command="note list")


def cmd_journal(a):
    from .notes import JOURNAL_PATH, add_journal
    from .util import read_jsonl
    if a.action == "add":
        rec = add_journal(a.kind, a.text, candidate_id=a.candidate, snapshot_id=a.snapshot, author=a.author, event_at=a.event_at)
        return envelope("OK", rec, command="journal add")
    rows = [r for r in read_jsonl(JOURNAL_PATH) if not a.candidate or r.get("candidate_id") == a.candidate]
    return envelope("OK" if rows else "OK_EMPTY", rows, command="journal list")


def cmd_collect(a):
    from .collector import collect
    from .config import symbol_profiles
    syms = a.symbols.split(",")
    sess = {s: (symbol_profiles()["symbols"].get(s) or {}).get("session") for s in syms}
    r = collect(a.terminal_path, syms, parse_utc(a.start), parse_utc(a.end), with_ticks=not a.no_ticks, sessions=sess,
                tick_start_utc=parse_utc(a.tick_start) if a.tick_start else None)
    return envelope(r["status"] if r["status"] in ("OK", "ERROR") else "PARTIAL", r,
                    errors=[] if r["status"] == "OK" else [{"reason": r.get("reason"), "recovery": r.get("recovery")}], command="collect")


def cmd_readiness(a):
    from .config import symbol_profiles
    from .readiness import source_readiness
    from .universe import MAIN8 as RP
    syms = a.symbols.split(",") if a.symbols else list(RP)
    sess = {s: (symbol_profiles()["symbols"].get(s) or {}).get("session") for s in syms}
    r = source_readiness(symbols=syms, sessions=sess, attach=not a.no_attach)
    st = "OK" if r["status"].startswith("LIVE_IDENTITY_OK_PROFILES_COMPLETE") else ("ERROR" if r["status"] == "ERROR" else "PARTIAL")
    return envelope(st, r, quality=[r["status"]], errors=[] if st != "ERROR" else [{"reason": r.get("reason")}], command="readiness")


def cmd_parity(a):
    from .data import load_registry
    from .parity import profit_parity
    from .util import read_jsonl
    rows = read_jsonl(a.rows)
    tp = a.terminal_path or load_registry()["source_identity"]["terminal_executable"]
    r = profit_parity(rows, tp, observe_margin=a.observe_margin)
    st = "OK" if r["status"] == "OK" else ("ERROR" if r["status"] == "ERROR" else "PARTIAL")
    return envelope(st, r, quality=[r["status"]], errors=[] if st != "ERROR" else [{"reason": r.get("reason")}], command="parity")


def _symbol_map(spec: str) -> dict:
    """'XAUUSD,EURUSD=EURUSD.r' → canonical→native (native defaults to canonical; suffixes are declared, never guessed)."""
    from .universe import validate_map
    out = []
    for item in spec.split(","):
        canon, _, native = item.partition("=")
        out.append((canon.strip(), (native or canon).strip()))
    return validate_map(out)


def _requested_map(a) -> dict:
    from .universe import MAIN8, EXTENDED12
    if a.symbols and a.universe_preset:
        raise ValueError("USE_SYMBOLS_OR_UNIVERSE_PRESET_NOT_BOTH")
    symbols = EXTENDED12 if a.universe_preset == "extended12" else MAIN8
    return _symbol_map(a.symbols or ",".join(symbols))


def _load_fixture(path: str, exe: str, end_utc: float):
    """Test/demo only: a python file exposing make(exe, end_utc) -> (mt5_module, process_lister[, sessions]).
    Gated by QUANTMT5_ALLOW_SYNTHETIC_FIXTURE=1; the injected module is always labelled SYNTHETIC by the collector."""
    import importlib.util
    import os
    if os.environ.get("QUANTMT5_ALLOW_SYNTHETIC_FIXTURE") != "1":
        raise PermissionError("SYNTHETIC_FIXTURE_NOT_ALLOWED: set QUANTMT5_ALLOW_SYNTHETIC_FIXTURE=1 (tests/demo only)")
    spec = importlib.util.spec_from_file_location("quant_synthetic_fixture", path)
    mod = importlib.util.module_from_spec(spec)
    sys.path.insert(0, str(Path(path).resolve().parent))
    spec.loader.exec_module(mod)
    out = mod.make(exe, end_utc)
    return out if len(out) == 3 else (out[0], out[1], None)


def cmd_paper_run(a):
    import os
    from .paper import paper_run
    end = parse_utc(a.end) if a.end else None
    kw = {}
    if a.synthetic_fixture:
        exe = os.path.normcase(os.path.abspath(a.terminal_path if a.terminal_path.lower().endswith(".exe")
                                               else os.path.join(a.terminal_path, "terminal64.exe")))
        mod, lister, sess = _load_fixture(a.synthetic_fixture, exe, end if end is not None else now_utc())
        kw.update(mt5_module=mod, process_lister=lister)
        if sess:
            kw["sessions"] = sess
        if os.environ.get("QUANTMT5_FIXTURE_TICK_START"):
            kw["tick_start_utc"] = parse_utc(os.environ["QUANTMT5_FIXTURE_TICK_START"])
    r = paper_run(a.terminal_path, _requested_map(a), out_root=Path(a.out_root), lookback_days=a.lookback_days,
                  tick_minutes=a.tick_minutes, end_utc=end,
                  require_trade_mode=a.require_trade_mode, expect_identity=json.loads(a.expect_identity) if a.expect_identity else None,
                  scan_timeout_s=a.scan_timeout, clock_profile=a.clock_profile, max_cards=a.max_cards, analysis_mode=a.analysis_mode, **kw)
    st = {"OK": "OK", "ERROR": "ERROR"}.get(r["status"], "PARTIAL")
    return envelope(st, r, quality=[r["status"]], errors=[] if st != "ERROR" else [{"reason": r.get("reason")}], command="paper-run")


def cmd_session(a):
    from . import session as S
    root = Path(a.root)
    if a.action == "init":
        if not a.terminal_path:
            return envelope("ERROR", None, errors=[{"reason": "ARGS: --terminal-path required"}], command="session init")
        sel = None
        sel_p = PROJECT_DIR.parent / "quant_mt5_plan_20261103" / "USER_DEMO_SELECTION_20261104.md"
        if sel_p.exists():
            from .util import sha256_file
            sel = {"path": str(sel_p), "sha256": sha256_file(sel_p), "program": "FTMO 1-Step", "environment": "MT5 demo"}
        r = S.init_session(root, a.name, a.terminal_path, _requested_map(a), mode=a.mode, cycle_timeout_s=a.cycle_timeout,
                           ftmo_program=a.ftmo_program, selection_ref=sel, synthetic_fixture=a.synthetic_fixture)
        return envelope("OK", r, command="session init")
    if a.action == "preflight":
        r = S.preflight(root, a.name)
        st = "OK" if r["status"].startswith("READY") else ("ERROR" if r["status"] == "ERROR" else "PARTIAL")
        return envelope(st, r, quality=[r["status"]], command="session preflight")
    if a.action in ("once", "check"):
        if a.action == "check" and not a.symbols:
            raise ValueError("CHECK_REQUIRES_SYMBOLS_FROM_SESSION")
        r = S.on_demand(root, a.name, end_utc=parse_utc(a.end) if a.end else None, max_cards=a.max_cards,
                        focused_symbols=list(_symbol_map(a.symbols)) if a.action == "check" else None, analysis_mode=a.analysis_mode)
        st = {"OK": "OK", "PARTIAL": "PARTIAL", "SKIPPED_MARKET_CLOSED": "OK", "PENDING_SOURCE": "PARTIAL"}.get(r["status"], "ERROR")
        return envelope(st, r, quality=[r["status"]], command="session once")
    if a.action == "enrich":
        if not all((a.expected_cycle, a.expected_generation, a.expected_snapshot)):
            raise ValueError("ENRICH_REQUIRES_EXPECTED_CYCLE_GENERATION_SNAPSHOT")
        r = S.enrich(root, a.name, a.expected_cycle, a.expected_generation, a.expected_snapshot,
                     context_timeout=a.context_timeout, max_cards=a.max_cards)
        return envelope("OK" if r["status"] == "OK" else "PARTIAL" if r["status"] == "PARTIAL" else "ERROR", r,
                        command="session enrich")
    if a.action == "finish":
        if not a.expected_cycle or not a.expected_generation:
            raise ValueError("FINISH_REQUIRES_EXPECTED_CYCLE_AND_GENERATION_FROM_LATEST_REPORT")
        r = S.finish(root, a.name, a.expected_cycle, a.expected_generation, a.expected_snapshot)
        return envelope("OK" if r["status"] == "CLOSED" else "PARTIAL", r, command="session finish")
    if a.action == "exec":
        rest = [x for x in (a.rest or []) if x != "--"]
        rc, out = S.exec_in_bundle(root, a.name, rest)
        if isinstance(out, dict):
            return out
        return envelope("ERROR", None, errors=[{"reason": f"EXEC_NON_JSON_EXIT_{rc}", "output": out[-500:]}], command="session exec")
    if a.action == "run":
        ends = [parse_utc(x) for x in a.simulate_ends.split(",")] if a.simulate_ends else None
        r = S.run(root, a.name, max_cycles=a.max_cycles, simulate_ends=ends, until_utc=parse_utc(a.until) if a.until else None)
        st = {"COMPLETED": "OK", "STOPPED": "OK"}.get(r["status"], "PARTIAL" if r["status"] in ("HALTED", "REFUSED") else "ERROR")
        return envelope(st, r, quality=[r["status"]], command="session run")
    if a.action == "start":
        extra = []
        if a.max_cycles:
            extra += ["--max-cycles", str(a.max_cycles)]
        if a.until:
            extra += ["--until", a.until]
        if a.simulate_ends:
            extra += ["--simulate-ends", a.simulate_ends]
        r = S.start_background(root, a.name, extra)
        return envelope("OK" if r["status"] == "STARTED" else "ERROR", r, command="session start")
    if a.action == "status":
        return envelope("OK", S.status(root, a.name), command="session status")
    if a.action == "stop":
        r = S.request_stop(root, a.name, timeout_s=a.stop_timeout, force=a.force)
        return envelope("OK" if r["result"] in ("STOPPED", "FORCE_TERMINATED", "STALE_LOCK_NO_LIVE_RUNNER") else "PARTIAL", r, command="session stop")
    return envelope("OK", S.summary(root, a.name), command="session summary")


def cmd_paper_scan(a):
    from .paper import paper_scan
    r = paper_scan(parse_utc(a.as_of) if a.as_of else now_utc(), a.universe.split(",") if a.universe else None,
                   max_cards=a.max_cards, analysis_mode=a.analysis_mode)
    st = {"OK": "OK", "ERROR": "ERROR"}.get(r["status"], "PARTIAL")
    return envelope(st, r, snapshot_id=r.get("snapshot_id"), quality=[r["status"]],
                    errors=[] if st != "ERROR" else [{"reason": r.get("reason")}], command="paper-scan")


def cmd_analysis(a):
    from .snapshot import load_snapshot
    from .reporting import analyze_snapshot
    snap = load_snapshot(a.snapshot)
    fabio = None
    if a.include_fabio:
        from .paper import _run_fabio_for_snapshot
        fabio = _run_fabio_for_snapshot(snap, snap["universe"])
    result = analyze_snapshot(snap, max_cards=a.max_cards, fabio=fabio)
    if fabio is not None:
        result["fabio"] = fabio
    return envelope("PARTIAL" if result["errors"] else "OK", result, snapshot_id=a.snapshot, command="analysis")


def cmd_card(a):
    from .context import opportunity_card
    try:
        card = opportunity_card(a.snapshot, a.candidate, notes_as_of=getattr(a, "notes_as_of", None))
        return envelope("OK", card, snapshot_id=a.snapshot, as_of=card["identity"]["as_of"], command="card")
    except KeyError:
        return envelope("ERROR", None, errors=[{"reason": "CANDIDATE_NOT_FOUND"}], snapshot_id=a.snapshot, command="card")
    except Exception as e:
        return envelope("ERROR", None, errors=[{"reason": str(e)}], snapshot_id=a.snapshot, command="card")


def _runtime_versions() -> dict:
    import platform
    import numpy
    return {"python": platform.python_version(), "implementation": platform.python_implementation(), "numpy": numpy.__version__}


def make_freeze(label: str = "", store_dir: Path | None = None) -> dict:
    from . import ENGINE_VERSION, STRATEGY_VERSION
    from .config import cost_profiles, strategy, symbol_profiles
    import quantmt5.config as config_mod
    import quantmt5.cli as cli_mod
    from .data import dataset_manifest
    from .util import (STORE_DIR, engine_hash, hash_obj, iso_utc, now_utc,
                       stable_id, write_immutable_json)

    base_dir = Path(store_dir) if store_dir is not None else STORE_DIR
    freeze_dir = base_dir / "freeze"

    eng_ver = ENGINE_VERSION
    eng_hash = engine_hash()

    cfg_fn = getattr(cli_mod, "config_hash", getattr(config_mod, "config_hash", None))
    cfg_hash = cfg_fn() if callable(cfg_fn) else config_mod.config_hash()

    strat_ver = strategy().get("strategy_version", STRATEGY_VERSION)
    cost_ver = cost_profiles().get("cost_profile_version")
    sym_ver = symbol_profiles().get("profile_version")
    manifest_hash = hash_obj(dataset_manifest())

    core = {
        "engine_version": eng_ver,
        "engine_hash": eng_hash,
        "config_hash": cfg_hash,
        "strategy_version": strat_ver,
        "cost_profile_version": cost_ver,
        "symbol_profile_version": sym_ver,
        "dataset_manifest_hash": manifest_hash,
        # Runtime needed to reproduce numeric results; part of the identity (a different numpy = new freeze).
        "runtime": _runtime_versions(),
    }
    fid = stable_id("FREEZE", core)
    p = freeze_dir / f"{fid}.json"

    if p.exists():
        rec = json.loads(p.read_text(encoding="utf-8"))
        res = dict(rec)
        res["already_frozen"] = True
        res["path"] = str(p)
        return res

    rec = dict(core)
    rec["freeze_id"] = fid
    rec["symbol_profile"] = sym_ver
    rec["label"] = label or ""
    rec["created_at"] = iso_utc(now_utc())

    write_immutable_json(p, rec)
    res = dict(rec)
    res["already_frozen"] = False
    res["path"] = str(p)
    return res


freeze = make_freeze


def cmd_freeze(a):
    from .util import STORE_DIR
    if getattr(a, "show", None):
        p = STORE_DIR / "freeze" / f"{a.show}.json"
        if not p.exists():
            return envelope("ERROR", None, errors=[{"reason": "FREEZE_NOT_FOUND"}], command="freeze")
        rec = json.loads(p.read_text(encoding="utf-8"))
        return envelope("OK", rec, command="freeze")
    res = make_freeze(label=getattr(a, "label", "") or "")
    return envelope("OK", res, command="freeze")


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="quant", description="Quant MT5 v0.2 shared CLI (read/scan/paper only; no order sending)")
    p.add_argument("--out", help="also write the JSON envelope to this file")
    sp = p.add_subparsers(dest="cmd", required=True)
    sp.add_parser("doctor").set_defaults(fn=cmd_doctor)
    s = sp.add_parser("audit"); s.add_argument("--symbols"); s.set_defaults(fn=cmd_audit)
    s = sp.add_parser("snapshot"); s.add_argument("--as-of", help="ISO-8601 with timezone; default now"); s.add_argument("--universe", default=",".join(PILOT))
    s.add_argument("--no-scan", action="store_true", help="data-only snapshot (B1): watermarks, bar status, provisional bars; no detectors"); s.set_defaults(fn=cmd_snapshot)
    s = sp.add_parser("scan"); s.add_argument("--snapshot", required=True); s.set_defaults(fn=cmd_scan)
    s = sp.add_parser("catalog"); s.add_argument("--snapshot", required=True); s.add_argument("--symbol", required=True)
    s.add_argument("--from", dest="from_"); s.add_argument("--setup", choices=["A", "B"]); s.add_argument("--limit", type=int, default=50)
    s.set_defaults(fn=cmd_catalog)
    s = sp.add_parser("coverage"); s.add_argument("--symbol", required=True); s.add_argument("--tf", default="M5")
    s.add_argument("--start"); s.add_argument("--end"); s.set_defaults(fn=cmd_coverage)
    s = sp.add_parser("context"); s.add_argument("--snapshot", required=True); s.add_argument("--candidate"); s.add_argument("--symbol")
    s.add_argument("--groups", help="optional groups: ema,adx,rsi,er,atr_pct"); s.add_argument("--at", choices=["decision", "as_of"], default="decision"); s.set_defaults(fn=cmd_context)
    s = sp.add_parser("fabio", help="research-only Fabio F1/F2 analysis (state/location/trigger/response/refutation/economics); no orders")
    s.add_argument("--snapshot", required=True); s.add_argument("--symbol", required=True)
    s.add_argument("--policy", choices=["legacy", "scalp_mt5_v1"], default="legacy", help="explicit Fabio research policy; existing callers remain legacy")
    s.add_argument("--previous-analysis", help="previous scalp artifact/envelope from same source/spec; freeze balance/profile/target across snapshots")
    s.add_argument("--flow", help="offline diagnostic fabio_flow_v1 JSON; omit to automatically use pinned MT5 broker ticks")
    s.add_argument("--exec", help="offline diagnostic quote/cost JSON; omit for automatic MT5 quote (missing costs stay UNKNOWN)")
    s.add_argument("--report", help="also write the Vietnamese machine-part report (Markdown) from the same result")
    s.add_argument("--no-store", action="store_true"); s.set_defaults(fn=cmd_fabio)
    s = sp.add_parser("fabio-replay", help="offline replay of a frozen Fabio plan on outcome snapshot ticks; no broker orders")
    s.add_argument("--analysis", required=True, help="Fabio scalp analysis artifact or CLI envelope")
    s.add_argument("--family", required=True, choices=["F1", "F2"])
    s.add_argument("--snapshot", help="outcome snapshot with same source/config and pinned future tick path; default analysis snapshot")
    s.add_argument("--latency-s", type=float, default=0.0, help="declared research latency in seconds, not measured")
    s.add_argument("--commission-price-rt", type=float, help="ASSUMED round-trip commission in price units; omitted = UNKNOWN")
    s.add_argument("--slippage-price", type=float, help="ASSUMED adverse slippage per market leg in price units; omitted = UNKNOWN")
    s.add_argument("--max-hold-s", type=float, default=1800.0, help="declared research hold cap (default 1800 seconds)")
    s.add_argument("--no-store", action="store_true"); s.set_defaults(fn=cmd_fabio_replay)
    s = sp.add_parser("explain"); s.add_argument("--snapshot", required=True); s.add_argument("--candidate", required=True); s.set_defaults(fn=cmd_explain)
    s = sp.add_parser("card"); s.add_argument("--snapshot", required=True); s.add_argument("--candidate", required=True)
    s.add_argument("--notes-as-of", help="rebuild the card with only notes recorded at/before this UTC time"); s.set_defaults(fn=cmd_card)
    s = sp.add_parser("replay"); s.add_argument("--candidate", required=True); s.add_argument("--symbol")
    s.add_argument("--snapshot", help="read data through this snapshot's pins / read contract")
    s.add_argument("--ticks", help="npz with structured `ticks` (time_msc,bid,ask[,available_msc]) — exact quote path")
    s.add_argument("--latency", default="BASE", choices=["BASE", "MANUAL", "SLOW"]); s.add_argument("--cost", default="BASE", choices=["LOW", "BASE", "ADVERSE"])
    s.set_defaults(fn=cmd_replay)
    s = sp.add_parser("register"); s.add_argument("--file"); s.add_argument("--exploratory", action="store_true"); s.set_defaults(fn=cmd_register)
    s = sp.add_parser("evaluate"); s.add_argument("--experiment", required=True); s.set_defaults(fn=cmd_evaluate)
    s = sp.add_parser("freeze"); s.add_argument("--label", default=""); s.add_argument("--show"); s.set_defaults(fn=cmd_freeze)
    s = sp.add_parser("note"); s.add_argument("action", choices=["add", "list"]); s.add_argument("--file"); s.add_argument("--candidate"); s.set_defaults(fn=cmd_note)
    s = sp.add_parser("journal"); s.add_argument("action", choices=["add", "list"]); s.add_argument("--kind", default="observation")
    s.add_argument("--text", default=""); s.add_argument("--candidate"); s.add_argument("--snapshot"); s.add_argument("--author", default="unknown")
    s.add_argument("--event-at"); s.set_defaults(fn=cmd_journal)
    s = sp.add_parser("collect"); s.add_argument("--terminal-path", required=True); s.add_argument("--symbols", required=True)
    s.add_argument("--start", required=True); s.add_argument("--end", required=True); s.add_argument("--no-ticks", action="store_true")
    s.add_argument("--tick-start", help="ticks only from this UTC time (bounded smoke window)"); s.set_defaults(fn=cmd_collect)
    s = sp.add_parser("readiness"); s.add_argument("--symbols"); s.add_argument("--no-attach", action="store_true"); s.set_defaults(fn=cmd_readiness)
    s = sp.add_parser("parity"); s.add_argument("--rows", required=True, help="JSONL ledger rows with cash view")
    s.add_argument("--terminal-path"); s.add_argument("--observe-margin", action="store_true"); s.set_defaults(fn=cmd_parity)
    s = sp.add_parser("paper-run", help="bounded one-shot: read-only collect -> source bundle -> paper-scan (no daemon, no orders)")
    s.add_argument("--analysis-mode", choices=["full", "baseline"], default="full")
    s.add_argument("--terminal-path", required=True); s.add_argument("--symbols", help="CANON[=NATIVE],...")
    s.add_argument("--universe-preset", choices=["main8", "extended12"])
    s.add_argument("--max-cards", type=int, default=8)
    s.add_argument("--out-root", required=True, help="isolated output root (raw/, bundles/, store/)")
    s.add_argument("--lookback-days", type=float, default=35); s.add_argument("--tick-minutes", type=float, default=240)
    s.add_argument("--end", help="collection end / as-of (UTC); default now"); s.add_argument("--require-trade-mode", type=int)
    s.add_argument("--expect-identity", help="JSON identity pin; mismatch → refused before any read")
    s.add_argument("--synthetic-fixture", help=argparse.SUPPRESS); s.add_argument("--scan-timeout", type=float, default=300)
    s.add_argument("--clock-profile", choices=["RAW_IS_UTC", "EET_EU", "NY_PLUS_7"],
                   help="pinned source clock (session pin); a contradicting fresh probe -> CLOCK_CONFLICT, nothing collected")
    s.set_defaults(fn=cmd_paper_run)
    s = sp.add_parser("session", help="durable paper session: init/preflight/run/start/status/stop/summary (no orders)")
    s.add_argument("action", choices=["init", "preflight", "once", "check", "enrich", "finish", "exec", "run", "start", "status", "stop", "summary"])
    s.add_argument("--analysis-mode", choices=["full", "baseline"], default="full")
    s.add_argument("--context-timeout", type=float, default=30)
    s.add_argument("--root", required=True); s.add_argument("--name", required=True)
    s.add_argument("--terminal-path"); s.add_argument("--symbols")
    s.add_argument("--universe-preset", choices=["main8", "extended12"])
    s.add_argument("--expected-cycle"); s.add_argument("--expected-generation"); s.add_argument("--expected-snapshot")
    s.add_argument("--mode", default="DEMO_NATIVE", choices=["DEMO_NATIVE", "SYNTHETIC_FIXTURE"])
    s.add_argument("--synthetic-fixture", help=argparse.SUPPRESS); s.add_argument("--ftmo-program", default="1-Step")
    s.add_argument("--cycle-timeout", type=int, default=600); s.add_argument("--max-cycles", type=int)
    s.add_argument("--until", help="stop after this UTC time"); s.add_argument("--simulate-ends", help=argparse.SUPPRESS)
    s.add_argument("--stop-timeout", type=float, default=120); s.add_argument("--force", action="store_true")
    s.add_argument("--end", help="ON_DEMAND as-of (UTC); default now"); s.add_argument("--max-cards", type=int, default=8)
    s.set_defaults(fn=cmd_session)
    s = sp.add_parser("paper-scan", help="run inside a source bundle process (QUANTMT5_CONFIG_DIR): snapshot/scan/replay/journal")
    s.add_argument("--analysis-mode", choices=["full", "baseline"], default="full")
    s.add_argument("--as-of"); s.add_argument("--universe"); s.add_argument("--max-cards", type=int, default=8); s.set_defaults(fn=cmd_paper_scan)
    s = sp.add_parser("analysis", help="batch market context + candidate cards from one pinned snapshot")
    s.add_argument("--include-fabio", action="store_true")
    s.add_argument("--snapshot", required=True); s.add_argument("--max-cards", type=int, default=8); s.set_defaults(fn=cmd_analysis)
    return p


def main(argv=None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    argv = list(sys.argv[1:] if argv is None else argv)
    rest = []
    if argv[:1] == ["session"] and "--" in argv:          # session exec ... -- <quant command>
        i = argv.index("--")
        argv, rest = argv[:i], argv[i + 1:]
    a = build_parser().parse_args(argv)
    a.rest = rest
    try:
        if a.cmd in ("snapshot", "scan", "catalog", "context", "explain", "replay", "fabio", "fabio-replay", "card", "analysis", "paper-scan", "note", "journal"):
            from .retention import storage_lease
            from .analysis_cache import analysis_scope
            with storage_lease(STORE_DIR.parent), analysis_scope():
                env = a.fn(a)
        else:
            env = a.fn(a)
    except Exception as e:  # reason-coded error envelope, never an empty success
        env = envelope("ERROR", None, errors=[{"reason": type(e).__name__ + ": " + str(e), "trace": traceback.format_exc(limit=3)}], command=a.cmd)
    return _emit(env, a.out)
