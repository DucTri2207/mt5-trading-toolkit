"""Load versioned configuration; every run records config_hash."""
from __future__ import annotations

import json
import math
from functools import lru_cache
from pathlib import Path

from .util import CONFIG_DIR, CONFIG_IS_BUNDLE, hash_obj

BUNDLE_MANIFEST = "BUNDLE_MANIFEST.json"


class ConfigBundleError(ValueError):
    """Pinned config/source bundle missing, tampered or not a bundle (never falls back to the repository config)."""


@lru_cache(maxsize=1)
def _verified_bundle() -> tuple[dict, dict]:
    """Read every bundle file ONCE, verify its bytes against the manifest and keep those exact bytes in memory.
    All loaders parse these bytes; files are never re-read in this process (later on-disk edits cannot be served
    under the verified bundle id). Semantic identity (provider/source/account currency) is derived from the hashed
    datasets.json; unhashed manifest metadata that disagrees is rejected."""
    import hashlib
    if not CONFIG_IS_BUNDLE:
        return {"kind": "DEFAULT_REPO_CONFIG", "config_dir": str(CONFIG_DIR), "bundle_id": None}, {}
    mp = CONFIG_DIR / BUNDLE_MANIFEST
    if not mp.exists():
        raise ConfigBundleError(f"CONFIG_BUNDLE_MANIFEST_MISSING:{mp}")
    man = json.loads(mp.read_text(encoding="utf-8"))
    data = {}
    for name, sha in man["files"].items():
        p = CONFIG_DIR / name
        b = p.read_bytes() if p.exists() else None
        if b is None or hashlib.sha256(b).hexdigest() != sha:
            raise ConfigBundleError(f"CONFIG_BUNDLE_TAMPERED:{name}")
        data[name] = b
    want = hash_obj(man["files"])[:20]
    if man.get("bundle_id") != f"CFGB_{want}":
        raise ConfigBundleError("CONFIG_BUNDLE_ID_MISMATCH")
    if "datasets.json" not in data:
        raise ConfigBundleError("CONFIG_BUNDLE_WITHOUT_REGISTRY")
    reg = json.loads(data["datasets.json"])
    ident = reg.get("source_identity") or {}
    provider = ident.get("provider_kind")
    sym_prov = {s: v.get("provider_kind") for s, v in reg.get("symbols", {}).items()}
    if not provider or any(p != provider for p in sym_prov.values()):
        raise ConfigBundleError(f"BUNDLE_PROVIDER_INCONSISTENT:{provider}:{sym_prov}")
    for key, hashed in (("provider_kind", provider), ("source_id", reg.get("source_id")),
                        ("account_currency", ident.get("account_currency"))):
        if man.get(key) is not None and man.get(key) != hashed:
            raise ConfigBundleError(f"BUNDLE_MANIFEST_METADATA_CONFLICT:{key}: manifest={man.get(key)} hashed={hashed}")
    return ({"kind": "SOURCE_BUNDLE", "config_dir": str(CONFIG_DIR), "bundle_id": man["bundle_id"], "provider_kind": provider,
             "source_id": reg.get("source_id"), "account_currency": ident.get("account_currency"),
             "identity_basis": "derived from hashed datasets.json"}, data)


def bundle_identity() -> dict:
    """Identity of the config this process reads (repository config → DEFAULT_REPO_CONFIG)."""
    return _verified_bundle()[0]


def verified_config_bytes(name: str) -> bytes:
    ident, data = _verified_bundle()
    if ident["kind"] != "SOURCE_BUNDLE":
        return (CONFIG_DIR / name).read_bytes()
    if name not in data:
        raise ConfigBundleError(f"CONFIG_FILE_NOT_IN_BUNDLE:{name}")
    return data[name]


def _load(name: str) -> dict:
    return json.loads(verified_config_bytes(name))


@lru_cache(maxsize=1)
def strategy() -> dict:
    return _load("strategy_v0_1.json")


@lru_cache(maxsize=1)
def symbol_profiles() -> dict:
    return _load("symbol_profiles.json")


@lru_cache(maxsize=1)
def cost_profiles() -> dict:
    return _load("cost_profiles.json")


def config_bundle() -> dict:
    return {"strategy": strategy(), "symbol_profiles": symbol_profiles(), "cost_profiles": cost_profiles()}


def config_hash() -> str:
    return hash_obj(config_bundle())


class MetadataError(ValueError):
    """Raised with a reason code when required symbol metadata is missing/invalid (never defaulted)."""


def profile(symbol: str) -> dict:
    p = symbol_profiles()["symbols"].get(symbol)
    if p is None:
        raise MetadataError(f"METADATA_MISSING:{symbol}:profile")
    return p


def tick_size(symbol: str, prof: dict | None = None) -> float:
    p = prof if prof is not None else profile(symbol)
    q = p.get("trade_tick_size")
    if q is None or isinstance(q, bool):
        raise MetadataError(f"METADATA_MISSING:{symbol}:trade_tick_size")
    try:
        qf = float(q)
    except (TypeError, ValueError):
        raise MetadataError(f"METADATA_INVALID:{symbol}:trade_tick_size=NOT_NUMERIC")
    if not math.isfinite(qf):
        raise MetadataError(f"METADATA_INVALID:{symbol}:trade_tick_size=NON_FINITE")
    if qf <= 0:
        raise MetadataError(f"METADATA_INVALID:{symbol}:trade_tick_size=NON_POSITIVE")
    return qf
