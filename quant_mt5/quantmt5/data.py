"""Dataset registry + bar loading.

Zero-copy design: the shared store references immutable source archives by path + SHA-256 (verified on load);
derived bars (e.g. FX H1/D1 from M5) are rebuilt deterministically and labelled ``DERIVED_FROM_M5``.

Time lineage: the source's numeric timestamp is kept untouched as ``open_raw``. ``open_at``/``close_at`` are the
result of applying ONE clock profile chosen by the dataset's time contract (config/datasets.json):
* ``API_UTC_CONTRACT`` (data collected through the MT5 Python API by quantmt5.collector): RAW_IS_UTC — no offset.
  Any other profile is rejected unless an override_reason is recorded (prevents a double offset).
* ``LEGACY_CACHE_HYPOTHESIS`` (old research archives): the applied profile is a research hypothesis
  (clock_profile_status ASSUMED) and the recorded source basis + conflict are carried verbatim in provenance.
Neither path upgrades time to VERIFIED.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np

from .analysis_cache import cached
from .timemap import server_to_utc
from .util import CONFIG_DIR, WORKSPACE_DIR, sha256_file

TF_SECONDS = {"M1": 60, "M5": 300, "H1": 3600, "D1": 86400}
ASSUMED_ARRIVAL_DELAY_S = 1  # setup-specs 1.1: historical available_at = close_at + 1s (ASSUMPTION, not observed)


@dataclass
class Bars:
    symbol: str
    tf: str
    open_raw: np.ndarray      # source numeric timestamp exactly as stored (basis: provenance.source_time_basis_recorded)
    open_at: np.ndarray       # UTC epoch seconds (clock profile)
    close_at: np.ndarray
    available_at: np.ndarray
    o: np.ndarray
    h: np.ndarray
    l: np.ndarray
    c: np.ndarray
    tick_volume: np.ndarray
    real_volume: np.ndarray
    spread: np.ndarray        # MqlRates.spread field, points; semantics audited separately
    provenance: dict = field(default_factory=dict)
    member_count: np.ndarray | None = None   # derived bars only: number of base bars aggregated
    expected_members: int | None = None      # derived bars only: tf / base tf (nominal, ignores scheduled breaks)

    def __len__(self) -> int:
        return len(self.c)

    @property
    def tf_s(self) -> int:
        return TF_SECONDS[self.tf]

    def slice(self, start: int, stop: int) -> "Bars":
        kw = {k: getattr(self, k)[start:stop] for k in ("open_raw", "open_at", "close_at", "available_at", "o", "h", "l",
                                                          "c", "tick_volume", "real_volume", "spread")}
        mc = None if self.member_count is None else self.member_count[start:stop]
        return Bars(self.symbol, self.tf, provenance=self.provenance, member_count=mc, expected_members=self.expected_members, **kw)

    def status(self, i: int, as_of: float | None = None) -> str:
        """COMPLETE / FINAL_FEWER_MEMBERS (derived, bucket closed with fewer base bars — scheduled break, quiet market
        or missing data; not decided here) / BROKER_FINAL (native) / PROVISIONAL (bucket not closed at as_of)."""
        if as_of is not None and self.close_at[i] > as_of:
            return "PROVISIONAL"
        if self.member_count is None:
            return "BROKER_FINAL"
        return "COMPLETE" if int(self.member_count[i]) >= int(self.expected_members or 0) else "FINAL_FEWER_MEMBERS"

    def prefix_available(self) -> np.ndarray:
        """pav[i] = max(available_at[0..i]) — the moment the whole event-ordered prefix through bar i is known."""
        return np.maximum.accumulate(self.available_at) if len(self) else self.available_at

    def upto_available(self, t: float) -> "Bars":
        """As-of view at t (arrival contract): the LONGEST EVENT-ORDERED PREFIX whose every bar has available_at <= t.
        Never contains a bar that arrived after t (no reliance on available_at being sorted). Bars that already
        arrived but lie after a not-yet-arrived bar are WITHHELD (not used, not compressed over) until the hole
        fills; the count is recorded in provenance so the view is never presented as fully scanned."""
        pav = self.prefix_available()
        n = int(np.searchsorted(pav, t, side="right"))     # pav is non-decreasing by construction
        out = self.slice(0, n)
        arrived = int((self.available_at <= t).sum())
        withheld = arrived - n
        if withheld:
            out.provenance = dict(self.provenance, asof_withheld_rows=withheld,
                                  asof_first_hole_open_at=_iso(int(self.open_at[n])), asof_first_hole_available_at=_iso(int(self.available_at[n])),
                                  data_quality_flags=list(self.provenance.get("data_quality_flags", [])) + ["ARRIVAL_HOLE_BARS_WITHHELD"])
        return out


def load_registry(path: Path | None = None) -> dict:
    if path is None:
        from .config import verified_config_bytes
        return json.loads(verified_config_bytes("datasets.json"))   # exact verified bytes of the pinned bundle
    return json.loads(Path(path).read_text(encoding="utf-8"))


def resolve(p: str) -> Path:
    pp = Path(p)
    return pp if pp.is_absolute() else (WORKSPACE_DIR / pp)


def _verified_npz(path_str: str, sha256: str):
    path = Path(path_str)
    if not path.exists():
        raise FileNotFoundError(f"SOURCE_MISSING: {path}")
    actual = sha256_file(path)
    if actual != sha256:
        raise ValueError(f"SOURCE_HASH_MISMATCH: {path} expected {sha256} got {actual}")
    def decode():
        with np.load(path, allow_pickle=False) as z:
            return {k: z[k] for k in z.files}
    return cached("archive", (str(path.resolve()), sha256), decode)


def _from_rates(symbol: str, tf: str, rates: np.ndarray, clock: str, prov: dict) -> Bars:
    if rates.dtype.names is None or "time" not in rates.dtype.names:
        raise ValueError("RATES_SCHEMA_INVALID")
    open_raw = rates["time"].astype(np.int64)
    open_at = server_to_utc(open_raw, clock)
    tfs = TF_SECONDS[tf]
    close_at = open_at + tfs
    return Bars(symbol, tf, open_raw=open_raw, open_at=open_at, close_at=close_at,
                available_at=close_at + ASSUMED_ARRIVAL_DELAY_S,
                o=rates["open"].astype(float), h=rates["high"].astype(float), l=rates["low"].astype(float),
                c=rates["close"].astype(float), tick_volume=rates["tick_volume"].astype(np.int64),
                real_volume=rates["real_volume"].astype(np.int64), spread=rates["spread"].astype(np.int64),
                provenance=prov)


def aggregate(m: Bars, tf: str) -> Bars:
    """Deterministic server-clock bucket aggregation (H1 by server hour, D1 by server date)."""
    tfs = TF_SECONDS[tf]
    bucket = m.open_raw // tfs
    starts = np.flatnonzero(np.r_[True, bucket[1:] != bucket[:-1]])
    ends = np.r_[starts[1:], len(bucket)]
    open_raw = bucket[starts] * tfs
    if "clock_profile" not in m.provenance:
        raise ValueError("TIME_PROFILE_MISSING_IN_PROVENANCE")
    open_at = server_to_utc(open_raw, m.provenance["clock_profile"])
    close_at = open_at + tfs
    prov = dict(m.provenance)
    prov.update({"kind": "DERIVED_FROM_" + m.tf, "aggregation": f"server-clock {tf} buckets; spread=min of members",
                 "member_counts_min": int((ends - starts).min()) if len(starts) else 0,
                 "boundary": f"server-clock bucket = floor(open_raw / {tfs}) (broker {tf} boundary under the stored numeric time)",
                 "bar_status_rule": "COMPLETE if members == expected else FINAL_FEWER_MEMBERS once closed; PROVISIONAL before close"})
    if len(m) == 0:
        e = np.zeros(0)
        ei = np.zeros(0, np.int64)
        return Bars(m.symbol, tf, ei, ei, ei, ei, e, e, e, e, ei, ei, ei, provenance=prov, member_count=ei,
                    expected_members=tfs // m.tf_s)
    # a derived bar is known only when it has closed AND every member bar has arrived
    member_avail = np.maximum.reduceat(m.available_at, starts)
    return Bars(m.symbol, tf, open_raw=open_raw, open_at=open_at, close_at=close_at,
                available_at=np.maximum(close_at + ASSUMED_ARRIVAL_DELAY_S, member_avail),
                o=m.o[starts], h=np.maximum.reduceat(m.h, starts), l=np.minimum.reduceat(m.l, starts),
                c=m.c[ends - 1], tick_volume=np.add.reduceat(m.tick_volume, starts),
                real_volume=np.add.reduceat(m.real_volume, starts), spread=np.minimum.reduceat(m.spread, starts),
                provenance=prov, member_count=(ends - starts).astype(np.int64), expected_members=tfs // m.tf_s)


def provisional_bar(base: Bars, tf: str, as_of: float) -> dict | None:
    """The still-running `tf` bar at as_of, built only from base bars available at as_of. None if the latest bucket
    is already closed. Always labelled PROVISIONAL with elapsed time; never a substitute for a closed bar."""
    known = base.upto_available(as_of)
    if len(known) == 0:
        return None
    tfs = TF_SECONDS[tf]
    bucket_raw = int(known.open_raw[-1] // tfs * tfs)
    b_open = int(server_to_utc(bucket_raw, base.provenance["clock_profile"])[0])
    b_close = b_open + tfs
    if as_of >= b_close:
        return None
    sel = known.open_raw // tfs * tfs == bucket_raw
    idx = np.flatnonzero(sel)
    # (upto_available already returns only the fully-arrived event-ordered prefix)
    return {"tf": tf, "status": "PROVISIONAL", "built_from": base.tf, "open_at": _iso(b_open), "nominal_close_at": _iso(b_close),
            "as_of": _iso(as_of), "elapsed_s": float(as_of - b_open), "elapsed_fraction": float((as_of - b_open) / tfs),
            "members": int(len(idx)), "expected_members_nominal": tfs // base.tf_s,
            "last_member_close_at": _iso(int(known.close_at[idx[-1]])),
            "o": float(known.o[idx[0]]), "h": float(known.h[idx].max()), "l": float(known.l[idx].min()), "c": float(known.c[idx[-1]]),
            "tick_volume_so_far": int(known.tick_volume[idx].sum()), "volume_basis": "tick",
            "comparability": "NOT comparable with closed-bar volume/RVOL (partial interval); detectors never use it"}


def _iso(t: float) -> str:
    import datetime as _dt
    return _dt.datetime.fromtimestamp(float(t), _dt.timezone.utc).isoformat().replace("+00:00", "Z")


TIME_QUALITY_FLAGS = ("TIME_UNVERIFIED",)


def time_lineage(reg: dict, symbol: str, clock_override: str | None = None, override_reason: str | None = None) -> dict:
    """Resolve the clock profile for a dataset from its time contract and return the provenance fields to carry."""
    ds = reg["symbols"][symbol]
    tb = ds.get("time_basis")
    if not tb:
        raise ValueError(f"TIME_BASIS_MISSING:{symbol}")
    contract = tb["contract"]
    cdef = reg.get("time_contracts", {}).get(contract)
    if cdef is None:
        raise ValueError(f"TIME_CONTRACT_UNKNOWN:{contract}")
    if contract == "API_UTC_CONTRACT":
        default = cdef["clock_profile"]
        if tb.get("clock_profile_applied", default) != default and not tb.get("override_reason"):
            raise ValueError(f"TIME_DOUBLE_OFFSET_GUARD:{symbol}: API_UTC_CONTRACT data must not be shifted without override_reason")
    else:
        default = tb["clock_profile_applied"]
    profile = clock_override or tb.get("clock_profile_applied", default)
    if contract == "API_UTC_CONTRACT" and profile != cdef["clock_profile"] and not (override_reason or tb.get("override_reason")):
        raise ValueError(f"TIME_DOUBLE_OFFSET_GUARD:{symbol}: refusing clock override {profile} on API_UTC_CONTRACT data without override_reason")
    flags = list(TIME_QUALITY_FLAGS)
    status = tb.get("time_basis_status") or cdef.get("status")
    if status and "CONFLICT" in status:
        flags.append("SOURCE_CONFLICT:TIME_BASIS")
    return {"time_contract": contract,
            "source_time_basis_recorded": tb.get("source_time_basis_recorded"),
            "source_time_basis_ref": tb.get("source_time_basis_ref"),
            "source_time_basis_ref_sha256": tb.get("source_time_basis_ref_sha256"),
            "clock_profile": profile,
            "clock_profile_status": "OVERRIDE_FOR_SENSITIVITY" if clock_override else (tb.get("clock_profile_status") or cdef.get("status")),
            "clock_override_reason": override_reason if clock_override else None,
            "time_basis_status": status,
            "time_conflict_reason": tb.get("conflict_reason"),
            "time_alternative_profiles": tb.get("alternative_profiles", []),
            "time_quality_flags": flags}


class DataVersionMismatch(ValueError):
    """The data a snapshot consumed can no longer be reproduced exactly (fail closed, never silently re-read)."""


OK_WINDOW_STATES = ("OK", "EMPTY_MARKET_CLOSED")


AGGREGATION_RULE = "server-clock bucket floor(open_raw/tf); O=first H=max L=min C=last; volumes summed; spread=min (v1)"


def read_contract(reg: dict, symbol: str, tf: str) -> dict:
    """Everything that decides how stored numbers are interpreted when read: time contract + applied clock
    lineage, timeframe definition (native key / derived-from + aggregation rule) and the available_at assumption.
    Pinned beside the raw bytes so an old snapshot can never be read under a newer interpretation."""
    ds = reg["symbols"][symbol]
    tb = ds.get("time_basis") or {}
    contract = tb.get("contract")
    cdef = (reg.get("time_contracts") or {}).get(contract) or {}
    spec = ds["timeframes"].get(tf) or {}
    rc = {"time_contract": contract,
          "clock_profile": tb.get("clock_profile_applied") or cdef.get("clock_profile"),
          "contract_clock_profile": cdef.get("clock_profile"),
          "source_time_basis_recorded": tb.get("source_time_basis_recorded"),
          "clock_profile_status": tb.get("clock_profile_status"), "time_basis_status": tb.get("time_basis_status"),
          "override_reason": tb.get("override_reason"),
          "available_at_assumption_s": ASSUMED_ARRIVAL_DELAY_S,
          "tf_definition": ({"derive_from": spec["derive_from"], "aggregation": AGGREGATION_RULE} if spec.get("derive_from")
                            else {"format": spec.get("format", "archive_npz"), "key": spec.get("key")})}
    return rc


def dataset_version(reg: dict, symbol: str, tf: str) -> dict:
    """Content identity (raw bytes) + read-contract identity of what a load of (symbol, tf) consumes now."""
    ds = reg["symbols"][symbol]
    spec = ds["timeframes"].get(tf)
    if spec is None:
        return {"status": "UNAVAILABLE"}
    rc = read_contract(reg, symbol, tf)
    if spec.get("derive_from"):
        base = dataset_version(reg, symbol, spec["derive_from"])
        return {"derived_from": spec["derive_from"], "base": base, "content_hash": base.get("content_hash"),
                "read_contract": rc, "read_contract_hash": _hash_obj([rc, base.get("read_contract_hash")])}
    if spec.get("format") == "collector_bars_v1":
        ck = json.loads((resolve(spec["chunk_dir"]) / "checkpoint.json").read_text(encoding="utf-8"))
        chunks = [{"file": c["file"], "sha256": c["sha256"]} for c in ck["chunks"]]
        windows = {k: w.get("status") for k, w in sorted(ck.get("windows", {}).items())}
        v = {"format": "collector_bars_v1", "chunk_dir": spec["chunk_dir"], "chunks": chunks, "window_states": windows}
        v["content_hash"] = collected_content_hash(chunks, windows)
    else:
        v = {"format": "archive_npz", "path": spec["path"], "key": spec["key"], "sha256": spec["sha256"]}
        v["content_hash"] = _hash_obj(v)
    v.update({"read_contract": rc, "read_contract_hash": _hash_obj(rc)})
    return v


def check_read_contract(reg: dict, symbol: str, tf: str, pin: dict | None) -> None:
    """Fail closed if the registry would now interpret the pinned data differently (clock, contract, TF definition)."""
    if pin is None:
        return
    if not pin.get("read_contract_hash"):
        raise DataVersionMismatch(f"READ_CONTRACT_NOT_PINNED:{symbol}:{tf}: snapshot predates read-contract pinning; re-snapshot")
    cur = dataset_version(reg, symbol, tf)
    if cur.get("read_contract_hash") != pin["read_contract_hash"]:
        old, new = pin.get("read_contract") or {}, cur.get("read_contract") or {}
        diff = sorted(k for k in set(old) | set(new) if old.get(k) != new.get(k))
        raise DataVersionMismatch(f"READ_CONTRACT_MISMATCH:{symbol}:{tf}: changed fields {diff or ['base']} since the snapshot")


def _hash_obj(o) -> str:
    from .util import hash_obj
    return hash_obj(o)


def collected_content_hash(chunks: list[dict], windows: dict) -> str:
    """Location-independent identity of a collected chunk set + its coverage states."""
    return _hash_obj({"format": "collector_bars_v1", "chunks": chunks, "window_states": windows})


def load_bars(symbol: str, tf: str, registry: dict | None = None, clock: str | None = None,
              override_reason: str | None = None, pins: dict | None = None) -> Bars | None:
    """Return Bars or None when the timeframe is unavailable for that symbol (caller reports HISTORY_INSUFFICIENT).
    `clock` overrides the contract's profile for sensitivity analysis only (recorded in provenance).
    `pins` = {tf: dataset_version(...)} recorded in a snapshot: the load reads exactly that content or raises
    DataVersionMismatch (fail closed)."""
    reg = registry or load_registry()
    ds = reg["symbols"].get(symbol)
    if ds is None:
        raise KeyError(f"SYMBOL_NOT_IN_REGISTRY: {symbol}")
    spec = ds["timeframes"].get(tf)
    if spec is None:
        return None
    pin = (pins or {}).get(tf)
    if pins is not None:
        if pin is None:
            raise DataVersionMismatch(f"READ_CONTRACT_NOT_PINNED:{symbol}:{tf}: timeframe not in the snapshot pins")
        check_read_contract(reg, symbol, tf, pin)
    if spec.get("derive_from"):
        base = load_bars(symbol, spec["derive_from"], reg, clock, override_reason, pins)
        if base is None:
            return None
        def derived():
            out = aggregate(base, tf)
            if pin is not None:
                out.provenance = dict(out.provenance, read_contract_hash=pin["read_contract_hash"])
            return out
        key = _hash_obj([symbol, tf, clock, override_reason, spec, base.provenance, pin])
        return cached("bars", key, derived)
    tl = time_lineage(reg, symbol, clock, override_reason)
    if spec.get("format") == "collector_bars_v1":
        rates, cprov = load_collected_bars(resolve(spec["chunk_dir"]), pin)
        prov = {"source_id": ds.get("source_id", reg["source_id"]), "dataset_id": ds["dataset_id"], "kind": "BROKER_NATIVE",
                **tl, **cprov, "exposure": ds.get("exposure"), "read_contract_hash": dataset_version(reg, symbol, tf)["read_contract_hash"],
                "available_at_basis": "ASSUMED close_at+1s (bars fetched after the fact; collected_at recorded per chunk)"}
        key = _hash_obj([symbol, tf, tl, prov])
        return cached("bars", key, lambda: _from_rates(symbol, tf, rates, tl["clock_profile"], prov))
    cur = dataset_version(reg, symbol, tf)
    if pin is not None and pin.get("content_hash") != cur["content_hash"]:
        raise DataVersionMismatch(f"DATA_VERSION_MISMATCH:{symbol}:{tf}: pinned {pin.get('sha256')} vs registry {spec['sha256']}")
    arrays = _verified_npz(str(resolve(spec["path"])), spec["sha256"])
    rates = arrays[spec["key"]]
    prov = {"source_id": reg["source_id"], "dataset_id": ds["dataset_id"], "path": spec["path"],
            "sha256": spec["sha256"], "key": spec["key"], "kind": "BROKER_NATIVE", **tl,
            "data_version": cur["content_hash"], "data_version_pinned": pin is not None, "read_contract_hash": cur["read_contract_hash"],
            "coverage_complete": None, "coverage_basis": "archive: per-window collector coverage not recorded; see `quant coverage` (schedule-based)",
            "data_quality_flags": [],
            "exposure": ds.get("exposure"), "imported_at": ds.get("imported_at") or reg.get("source_identity", {}).get("retrieved_utc", {}).get(symbol),
            "available_at_basis": "ASSUMED close_at+1s (historical import, no arrival timestamps)"}
    key = _hash_obj([symbol, tf, tl, prov])
    return cached("bars", key, lambda: _from_rates(symbol, tf, rates, tl["clock_profile"], prov))


class ChunkCorrupt(ValueError):
    pass


def load_collected_bars(chunk_dir: Path, pin: dict | None = None) -> tuple[np.ndarray, dict]:
    """Concatenate accepted collector chunks (sha256-verified). With `pin`, read exactly the pinned chunk set
    (old immutable chunks stay on disk) or raise DataVersionMismatch. Overlapping bars must be identical, else
    SOURCE_CONFLICT. Returns (rates, provenance additions incl. coverage state and data_version)."""
    chunk_dir = Path(chunk_dir)
    ck = json.loads((chunk_dir / "checkpoint.json").read_text(encoding="utf-8"))
    if pin is not None:
        chunks, windows, version = pin["chunks"], pin.get("window_states", {}), pin["content_hash"]
    else:
        chunks = [{"file": c["file"], "sha256": c["sha256"]} for c in ck["chunks"]]
        windows = {k: w.get("status") for k, w in sorted(ck.get("windows", {}).items())}
        version = collected_content_hash(chunks, windows)
    shas = []
    for ch in chunks:
        p = chunk_dir / ch["file"]
        if not p.exists():
            raise DataVersionMismatch(f"DATA_VERSION_MISMATCH:CHUNK_MISSING:{p}")
        if sha256_file(p) != ch["sha256"]:
            raise (DataVersionMismatch if pin is not None else ChunkCorrupt)(f"CHUNK_CORRUPT_OR_CHANGED:{p}")
        shas.append(ch["sha256"])
    if not chunks:
        raise ValueError(f"NO_COMMITTED_CHUNKS:{chunk_dir}")
    def decode():
        parts = []
        for ch in chunks:
            with np.load(chunk_dir / ch["file"], allow_pickle=False) as z:
                parts.append(z["rates"])
        a = np.concatenate(parts)
        a = a[np.argsort(a["time"], kind="stable")]
        dup = np.flatnonzero(np.diff(a["time"]) == 0)
        if len(dup):
            if any(a[i].tobytes() != a[i + 1].tobytes() for i in dup):
                raise ValueError(f"SOURCE_CONFLICT:DUPLICATE_BAR_DIFFERENT_VALUES:{chunk_dir}")
            a = np.delete(a, dup + 1)
        return a
    # Integrity above is checked even on a hit; metadata below is never cached.
    a = cached("collected_bars", (str(chunk_dir.resolve()), _hash_obj(chunks)), decode)
    not_ok = {k: s for k, s in windows.items() if s not in OK_WINDOW_STATES}
    flags = sorted({f"COVERAGE_{s}" for s in not_ok.values()})
    gaps = [g for k in not_ok for g in (ck.get("windows", {}).get(k, {}).get("missing_open_ranges") or [])]
    return a, {"chunk_dir": str(chunk_dir), "chunk_sha256": shas, "collected_identity": ck.get("identity"),
               "data_version": version, "data_version_pinned": pin is not None,
               "coverage_complete": not not_ok, "coverage_not_ok_windows": not_ok, "coverage_missing_open_ranges": gaps[:50],
               "data_quality_flags": (["COVERAGE_INCOMPLETE"] + flags) if not_ok else [],
               "imported_at": ck.get("updated_at")}


def dataset_manifest(registry: dict | None = None) -> dict[str, Any]:
    reg = registry or load_registry()
    return {"source_id": reg["source_id"], "time_contracts": reg.get("time_contracts"),
            "symbols": {s: {"time_basis": d.get("time_basis"),
                            "timeframes": {tf: {k: v for k, v in spec.items()} for tf, spec in d["timeframes"].items()},
                            "data_versions": {tf: {k: v for k, v in dataset_version(reg, s, tf).items() if k in ("content_hash", "read_contract_hash")}
                                              for tf in d["timeframes"]}}
                        for s, d in reg["symbols"].items()}}


@dataclass
class Ticks:
    symbol: str
    time_msc: np.ndarray   # UTC epoch milliseconds
    bid: np.ndarray
    ask: np.ndarray
    flags: np.ndarray
    provenance: dict = field(default_factory=dict)

    def __len__(self) -> int:
        return len(self.bid)


def load_ticks_npz(path: Path, symbol: str, clock: str | None = None) -> Ticks:
    z = np.load(path, allow_pickle=False)
    key = z.files[0]
    a = z[key]
    names = a.dtype.names or ()
    tm = a["time_msc"].astype(np.int64)
    if clock and clock != "RAW_IS_UTC":
        tm = server_to_utc(tm // 1000, clock) * 1000 + tm % 1000
    return Ticks(symbol, tm, a["bid"].astype(float), a["ask"].astype(float),
                 a["flags"].astype(np.int64) if "flags" in names else np.zeros(len(a), np.int64),
                 {"path": str(path), "clock_profile": clock})
