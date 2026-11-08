"""B6B: immutable, versioned config/source bundle built from a verified collect result.

A bundle is a directory `CFGB_<id>/` holding exactly the files the engine reads (strategy, cost profiles, exposure
ledger copied unchanged from the base config; symbol profiles mapped from the NATIVE profile observed by the
collector; a datasets registry that points ONLY at the collected chunks of one source namespace) plus
BUNDLE_MANIFEST.json (sha256 of every file). A process selects it with QUANTMT5_CONFIG_DIR=<bundle dir> before
import; quantmt5.config.bundle_identity() re-verifies every file and fails closed on tampering. The legacy
registry/config are never edited."""
from __future__ import annotations

import json
from contextlib import ExitStack
from pathlib import Path

from .util import PROJECT_DIR, atomic_write_text, hash_obj, iso_utc, now_utc, sha256_bytes

CHART_BASIS = {0: "BID", 1: "LAST"}
PROFILE_MAP = {  # engine field <- native symbol_info field
    "trade_tick_size": "trade_tick_size", "point": "point", "digits": "digits", "contract_size": "trade_contract_size",
    "profit_currency": "currency_profit", "base_currency": "currency_base", "margin_currency": "currency_margin",
    "volume_min": "volume_min", "volume_max": "volume_max", "volume_step": "volume_step",
    "stops_level_points": "trade_stops_level", "freeze_level_points": "trade_freeze_level"}
COPIED = ("strategy_v0_1.json", "cost_profiles.json", "exposure_ledger.json")
GENERATION_FIELDS = ("tick_generation_id", "retention_root", "retention_session_id")


class BundleError(ValueError):
    pass


def _dump(obj) -> bytes:
    return (json.dumps(obj, ensure_ascii=False, indent=1, sort_keys=True) + "\n").encode("utf-8")


def map_profile(native: str, rec: dict, provider_kind: str, legacy: dict | None) -> dict:
    """Engine profile from the observed native profile. Invalid native fields are set to None (engine fails closed)
    instead of being filled from the legacy profile; session is inherited and labelled ASSUMED."""
    raw, chk = rec.get("profile") or {}, rec.get("profile_check") or {}
    invalid = {x["field"] for x in chk.get("invalid", [])}
    out = {k: (None if src in invalid else raw.get(src)) for k, src in PROFILE_MAP.items()}
    cm = raw.get("chart_mode")
    out.update({"native_symbol": native, "chart_basis": CHART_BASIS.get(cm, "UNKNOWN") if "chart_mode" not in invalid else "UNKNOWN",
                "calc_mode": chk.get("calc_mode_name"), "profit_formula_capability": chk.get("profit_formula_capability"),
                "metadata_status": f"OBSERVED_CURRENT_ONLY via {provider_kind} (observed_at in BUNDLE_MANIFEST.profile_observed_at); profile_check={chk.get('status', 'UNKNOWN')}" if raw else "UNKNOWN_NATIVE_PROFILE_MISSING",
                "metadata_invalid": chk.get("invalid", []),
                "raw_native_profile": raw, "enum_contract": chk.get("enum_contract")})
    sess = (legacy or {}).get("session")
    out["session"] = (dict(sess, status="ASSUMED_INHERITED_FROM_LEGACY_PROFILE (not observed from this source; DST/clock unverified)")
                      if sess else None)
    out["session_status"] = "ASSUMED_INHERITED" if sess else "UNKNOWN_NOT_OBSERVED"
    return out


def _chunkset_hash(chunk_dir: Path) -> str | None:
    ckp = chunk_dir / "checkpoint.json"
    if not ckp.exists():
        return None
    ck = json.loads(ckp.read_text(encoding="utf-8"))
    identity = {"chunks": [[c["file"], c["sha256"]] for c in ck["chunks"]],
                "windows": {k: w.get("status") for k, w in sorted(ck.get("windows", {}).items())}}
    if ck.get("tick_generation_id"):
        identity["tick_generation_id"] = ck["tick_generation_id"]
    return hash_obj(identity)


def tick_version(reg: dict, symbol: str) -> dict | None:
    """Pinnable identity of a symbol's collected tick chunks (chunk files + sha + window states)."""
    spec = (reg["symbols"].get(symbol) or {}).get("ticks")
    if not spec:
        return None
    from .retention import storage_lease
    with storage_lease(spec["chunk_dir"]):
        return _tick_version(spec)


def _tick_version(spec: dict) -> dict:
    from .retention import assert_tick_available
    assert_tick_available(spec)
    ckp = Path(spec["chunk_dir"]) / "checkpoint.json"
    if not ckp.exists():
        return {"format": spec.get("format"), "chunk_dir": spec["chunk_dir"], "status": "NO_TICKS_COLLECTED",
                **{k: spec[k] for k in GENERATION_FIELDS if k in spec}}
    ck = json.loads(ckp.read_text(encoding="utf-8"))
    if spec.get("tick_generation_id") and spec["tick_generation_id"] != ck.get("tick_generation_id"):
        raise BundleError("TICK_GENERATION_CHANGED_AFTER_BUNDLE")
    chunks = [{"file": c["file"], "sha256": c["sha256"], "first_ms": c.get("first_ms"), "last_ms": c.get("last_ms")} for c in ck["chunks"]]
    windows = {k: w.get("status") for k, w in sorted(ck.get("windows", {}).items())}
    v = {"format": spec.get("format"), "chunk_dir": spec["chunk_dir"], "chunks": chunks, "window_states": windows,
         "pending_rows_not_committed": ck.get("pending_rows") if ck.get("pending_ms") is not None else 0,
         **{k: ck[k] for k in GENERATION_FIELDS if k in ck}}
    identity = {"chunks": chunks, "windows": windows}
    if v.get("tick_generation_id"):
        identity["tick_generation_id"] = v["tick_generation_id"]
    clock = ck.get("clock_profile", "RAW_IS_UTC")
    if clock != "RAW_IS_UTC":
        # 043 F2: stored time_msc is the raw source clock; window keys are UTC. The pin says how to read the tape.
        v["clock_profile"] = clock
        identity["clock_profile"] = clock
    v["content_hash"] = hash_obj(identity)
    return v


PROBED_CONTRACT = {
    "clock_profile": None,
    "applies_to": "datasets collected by quantmt5.collector whose current fresh-tick probe showed a server-clock offset",
    "basis": "values stored exactly as returned; the per-dataset clock_profile_applied (source-clock-policy-v1) converts them to UTC once; "
             "API request bounds used the same profile",
    "status": "PROBE_ASSUMED_NOT_VERIFIED",
    "verification_path": "one current probe never verifies historical DST, legacy data or the PC clock; review required before any upgrade"}


def _time_contracts(legacy_reg: dict, symbols: dict) -> dict:
    out = {"API_UTC_CONTRACT": legacy_reg["time_contracts"]["API_UTC_CONTRACT"]}
    if any((e.get("time_basis") or {}).get("contract") == "API_SERVER_CLOCK_PROBED" for e in symbols.values()):
        out["API_SERVER_CLOCK_PROBED"] = PROBED_CONTRACT
    return out


def build_source_bundle(collect_res: dict, out_root: Path, symbol_map: dict[str, str], base_config_dir: Path | None = None) -> dict:
    """symbol_map: canonical -> native (declared, never guessed). Returns {bundle_id, config_dir, created|already_exists}."""
    from .retention import storage_lease
    from .universe import validate_map
    symbol_map = validate_map(symbol_map)
    paths = sorted({entry["ticks"]["chunk_dir"] for entry in (collect_res.get("registry_fragment") or {}).values() if entry.get("ticks")})
    with ExitStack() as stack:
        for path in paths:
            stack.enter_context(storage_lease(path))
        return _build_source_bundle(collect_res, out_root, symbol_map, base_config_dir)


def _build_source_bundle(collect_res: dict, out_root: Path, symbol_map: dict[str, str], base_config_dir: Path | None) -> dict:
    if collect_res.get("status") == "ERROR" or not collect_res.get("registry_fragment"):
        raise BundleError(f"COLLECT_NOT_PUBLISHABLE:{collect_res.get('reason')}")
    man, frag = collect_res["manifest"], collect_res["registry_fragment"]
    if not man.get("identity_rechecked_after_batch"):
        raise BundleError("IDENTITY_NOT_RECHECKED")
    base = Path(base_config_dir or PROJECT_DIR / "config")
    legacy_reg = json.loads((base / "datasets.json").read_text(encoding="utf-8"))
    legacy_prof = json.loads((base / "symbol_profiles.json").read_text(encoding="utf-8"))["symbols"]
    provider = man["provider_kind"]
    ident = {k: v for k, v in man["identity"].items() if k != "collected_at"}
    symbols, profiles, issues = {}, {}, []
    for canon, native in sorted(symbol_map.items()):
        rec = man["symbols"].get(native)
        if not rec or rec.get("status") == "ERROR" or native not in frag:
            issues.append({"symbol": canon, "native": native, "reason": (rec or {}).get("reason", "NOT_COLLECTED")})
            continue
        if not rec.get("profile"):
            issues.append({"symbol": canon, "native": native, "reason": "METADATA_MISSING_NATIVE_PROFILE"})
        missing_tf = [tf for tf, spec in frag[native]["timeframes"].items() if not (Path(spec["chunk_dir"]) / "checkpoint.json").exists()]
        if missing_tf:
            issues.append({"symbol": canon, "native": native, "reason": "TIMEFRAMES_NOT_COLLECTED", "timeframes": missing_tf})
        frag_n = dict(frag[native], timeframes={tf: v for tf, v in frag[native]["timeframes"].items() if tf not in missing_tf})
        entry = dict(frag_n, native_symbol=native,
                     collected_coverage={tf: b.get("status") for tf, b in (rec.get("bars") or {}).items()},
                     ticks_status=(rec.get("ticks") or {}).get("status"))
        if entry.get("ticks"):
            spec = dict(entry["ticks"])
            checkpoint = Path(spec["chunk_dir"]) / "checkpoint.json"
            ck = json.loads(checkpoint.read_text(encoding="utf-8")) if checkpoint.exists() else {}
            if not checkpoint.exists() and not spec.get("tick_generation_id"):
                entry["ticks"] = None
                entry["ticks_status"] = "NOT_COLLECTED"
                issues.append({"symbol": canon, "native": native, "reason": "TICKS_NOT_COLLECTED"})
            else:
                spec.update({k: ck[k] for k in GENERATION_FIELDS if k in ck})
                entry["ticks"] = spec
                from .retention import assert_tick_available
                assert_tick_available(spec)
        # bundle identity follows the DATA content at build time (same data → same bundle; more chunks → new version)
        entry["content_at_build"] = {tf: _chunkset_hash(Path(spec["chunk_dir"])) for tf, spec in entry["timeframes"].items()}
        entry["content_at_build"]["ticks"] = _chunkset_hash(Path(entry["ticks"]["chunk_dir"])) if entry.get("ticks") else None
        symbols[canon] = entry
        profiles[canon] = map_profile(native, rec, provider, legacy_prof.get(canon))
    if not symbols:
        raise BundleError(f"NO_PUBLISHABLE_SYMBOLS:{issues}")
    datasets = {"registry_version": "datasets-bundle-v1", "source_id": man["source_id"],
                "source_identity": dict(ident, terminal_executable=ident.get("executable")),
                "time_contracts": _time_contracts(legacy_reg, symbols),
                "requested_symbols": sorted(symbol_map), "symbol_map": symbol_map,
                "symbol_issues": {s: [i for i in issues if i["symbol"] == s] for s in symbol_map if any(i["symbol"] == s for i in issues)},
                "symbols": symbols}
    prof_doc = {"profile_version": f"native-{man['source_id']}", "note": f"mapped from {provider} symbol_info; see raw_native_profile",
                "symbols": profiles}
    files = {name: (base / name).read_bytes() for name in COPIED}
    files["datasets.json"] = _dump(datasets)
    files["symbol_profiles.json"] = _dump(prof_doc)
    shas = {k: sha256_bytes(v) for k, v in sorted(files.items())}
    bundle_id = f"CFGB_{hash_obj(shas)[:20]}"
    d = Path(out_root) / bundle_id
    if (d / "BUNDLE_MANIFEST.json").exists():
        old = json.loads((d / "BUNDLE_MANIFEST.json").read_text(encoding="utf-8"))
        if old["files"] != shas:
            raise BundleError(f"BUNDLE_DIR_CONFLICT:{d}")
        _register_bundle_consumers(symbols, d)
        return {"bundle_id": bundle_id, "config_dir": str(d), "already_exists": True, "issues": issues,
                "this_run_profile_observed_at": {c: (man["symbols"].get(n) or {}).get("profile_observed_at") for c, n in symbol_map.items()}}
    d.mkdir(parents=True, exist_ok=True)
    for name, data in files.items():
        (d / name).write_bytes(data)
    from .collector import runtime_enum_contract
    from .util import engine_hash
    manifest = {"bundle_id": bundle_id, "files": shas, "source_id": man["source_id"], "provider_kind": provider,
                "account_currency": ident.get("account_currency"), "collect_manifest": collect_res["manifest_path"],
                "base_config_dir": str(base), "created_at": iso_utc(now_utc()), "engine_hash_at_build": engine_hash(),
                "runtime_contract": runtime_enum_contract() if provider == "NATIVE_TERMINAL" else {"status": "NOT_EVALUATED_SYNTHETIC"},
                "cost_note": "cost_profiles copied unchanged: ASSUMED; commission is USD-denominated; no conversion to the account "
                             "currency is invented (cash views stay UNKNOWN when currencies differ)",
                "session_note": "sessions inherited from the legacy profile and labelled ASSUMED", "issues": issues,
                "profile_observed_at": {c: (man["symbols"].get(n) or {}).get("profile_observed_at") for c, n in symbol_map.items()}}
    atomic_write_text(d / "BUNDLE_MANIFEST.json", json.dumps(manifest, ensure_ascii=False, indent=1) + "\n")
    _register_bundle_consumers(symbols, d)
    return {"bundle_id": bundle_id, "config_dir": str(d), "already_exists": False, "issues": issues}


def _register_bundle_consumers(symbols: dict, bundle_dir: Path) -> None:
    from .retention import register_consumer
    for entry in symbols.values():
        if entry.get("ticks"):
            register_consumer(entry["ticks"], bundle_dir, kind="bundle")
