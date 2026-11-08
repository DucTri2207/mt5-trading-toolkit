"""Small shared helpers: hashing, stable IDs, atomic writes, time formatting, response envelopes."""
from __future__ import annotations

import contextlib
import datetime as _dt
import hashlib
import json
import math
import os
import tempfile
import time
import uuid
from decimal import Decimal, ROUND_CEILING, ROUND_FLOOR
from pathlib import Path
from typing import Any, Iterable

from . import SCHEMA_VERSION

PKG_DIR = Path(__file__).resolve().parent
PROJECT_DIR = PKG_DIR.parent            # .../quant_mt5
WORKSPACE_DIR = PROJECT_DIR.parent      # .../trading thử lần cuối cuối; QUANTMT5_WORKSPACE overrides (relative dataset paths resolve here; staged/extracted copies)
WORKSPACE_DIR = Path(os.environ.get("QUANTMT5_WORKSPACE") or PROJECT_DIR.parent)
# Config/source bundle for this process: QUANTMT5_CONFIG_DIR (absolute, set before import) selects an isolated,
# immutable bundle (see quantmt5.source_bundle); default = the repository config (legacy historical cache).
_CFG_ENV = os.environ.get("QUANTMT5_CONFIG_DIR")
if _CFG_ENV and not Path(_CFG_ENV).is_absolute():
    raise ValueError(f"QUANTMT5_CONFIG_DIR must be absolute: {_CFG_ENV!r}")
CONFIG_DIR = Path(_CFG_ENV) if _CFG_ENV else PROJECT_DIR / "config"
CONFIG_IS_BUNDLE = bool(_CFG_ENV)
STORE_DIR = Path(os.environ.get("QUANTMT5_STORE", PROJECT_DIR / "store"))

UTC = _dt.timezone.utc


# ---------------------------------------------------------------- hashing / ids
def sha256_bytes(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def sha256_file(path: os.PathLike | str, chunk: int = 1 << 20) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while True:
            buf = f.read(chunk)
            if not buf:
                break
            h.update(buf)
    return h.hexdigest()


def _json_default(o: Any):
    import numpy as np
    if isinstance(o, (np.integer,)):
        return int(o)
    if isinstance(o, (np.floating,)):
        f = float(o)
        return None if not math.isfinite(f) else f
    if isinstance(o, np.bool_):
        return bool(o)
    if isinstance(o, np.ndarray):
        return o.tolist()
    if isinstance(o, Path):
        return str(o)
    if isinstance(o, (_dt.datetime, _dt.date)):
        return o.isoformat()
    raise TypeError(f"not JSON serialisable: {type(o)}")


def _clean_nan(o: Any):
    if isinstance(o, float):
        return o if math.isfinite(o) else None
    if isinstance(o, dict):
        return {k: _clean_nan(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)):
        return [_clean_nan(v) for v in o]
    return o


def canonical_json(obj: Any) -> str:
    return json.dumps(_clean_nan(obj), sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=_json_default)


def pretty_json(obj: Any) -> str:
    return json.dumps(_clean_nan(obj), sort_keys=False, indent=2, ensure_ascii=False, default=_json_default)


def hash_obj(obj: Any) -> str:
    return sha256_bytes(canonical_json(obj).encode("utf-8"))


def stable_id(prefix: str, *parts: Any, n: int = 20) -> str:
    """Deterministic ID from the event's defining inputs (never from wall clock or run order)."""
    return f"{prefix}_{hash_obj(list(parts))[:n]}"


def engine_hash() -> str:
    """Hash of every .py file in the package (sorted) — identifies the engine build."""
    h = hashlib.sha256()
    for p in sorted(PKG_DIR.glob("*.py")):
        h.update(p.name.encode())
        h.update(p.read_bytes())
    return h.hexdigest()


# ---------------------------------------------------------------- atomic writes
def atomic_write_bytes(path: os.PathLike | str, data: bytes) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=path.name + ".", suffix=".tmp", dir=str(path.parent))
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise
    return path


def atomic_write_text(path: os.PathLike | str, text: str) -> Path:
    return atomic_write_bytes(path, text.encode("utf-8"))


def atomic_write_json(path: os.PathLike | str, obj: Any) -> Path:
    return atomic_write_text(path, pretty_json(obj) + "\n")


def write_immutable_json(path: os.PathLike | str, obj: Any) -> tuple[Path, bool]:
    """Write once. If the file exists, it must have identical canonical content; never overwrite.

    Returns (path, created)."""
    path = Path(path)
    if path.exists():
        existing = json.loads(path.read_text(encoding="utf-8"))
        if canonical_json(existing) != canonical_json(obj):
            raise FileExistsError(f"IMMUTABLE_CONFLICT: {path} exists with different content")
        return path, False
    atomic_write_json(path, obj)
    return path, True


@contextlib.contextmanager
def file_lock(path: os.PathLike | str, timeout_s: float = 60.0):
    """Exclusive cross-process lock on `<path>.lock` (Windows: msvcrt byte lock; POSIX: flock). Not re-entrant.

    Needed because Windows emulates O_APPEND as seek-to-end + write: two processes appending concurrently can
    overwrite each other's lines (observed: 596 of 600 lines kept, recheck 2026-11-04)."""
    lp = Path(str(path) + ".lock")
    lp.parent.mkdir(parents=True, exist_ok=True)
    f = open(lp, "a+b")
    try:
        if os.name == "nt":
            import msvcrt
            deadline = time.monotonic() + timeout_s
            while True:
                try:
                    f.seek(0)
                    msvcrt.locking(f.fileno(), msvcrt.LK_NBLCK, 1)
                    break
                except OSError:
                    if time.monotonic() > deadline:
                        raise TimeoutError(f"FILE_LOCK_TIMEOUT:{lp}")
                    time.sleep(0.005)
            try:
                yield
            finally:
                f.seek(0)
                msvcrt.locking(f.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            import fcntl
            fcntl.flock(f.fileno(), fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(f.fileno(), fcntl.LOCK_UN)
    finally:
        f.close()


def append_jsonl(path: os.PathLike | str, record: dict, *, lock: bool = True) -> None:
    """Append-only journal line; flush+fsync. Existing lines are never rewritten.
    lock=False only when the caller already holds file_lock(path)."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    line = canonical_json(record) + "\n"
    with (file_lock(path) if lock else contextlib.nullcontext()):
        with open(path, "a", encoding="utf-8", newline="\n") as f:
            f.write(line)
            f.flush()
            os.fsync(f.fileno())


class JournalCorrupt(ValueError):
    """A complete (newline-terminated) journal line is not valid JSON: never dropped silently; the writer halts."""


def repair_jsonl_tail(path: os.PathLike | str) -> dict | None:
    """Call while holding file_lock(path). A crash can leave a final line without its newline:
    * valid JSON without newline → newline appended (record kept);
    * invalid partial bytes → moved to <path>.partial_<ms> and the file truncated to the last newline.
    Every repair is appended to <path>.audit.jsonl. Middle lines are never touched (read_jsonl raises)."""
    path = Path(path)
    if not path.exists():
        return None
    b = path.read_bytes()
    if not b or b.endswith(b"\n"):
        return None
    i = b.rfind(b"\n")
    tail = b[i + 1:]
    try:
        json.loads(tail.decode("utf-8"))
        with open(path, "ab") as f:
            f.write(b"\n")
            f.flush()
            os.fsync(f.fileno())
        rec = {"action": "NEWLINE_ADDED_TO_COMPLETE_LAST_RECORD", "bytes": len(tail)}
    except (ValueError, UnicodeDecodeError):
        saved = path.with_name(f"{path.name}.partial_{int(now_utc() * 1000)}")
        saved.write_bytes(tail)
        with open(path, "r+b") as f:
            f.truncate(i + 1)
            f.flush()
            os.fsync(f.fileno())
        rec = {"action": "PARTIAL_LAST_LINE_QUARANTINED", "bytes": len(tail), "saved_as": saved.name}
    rec["at"] = iso_utc(now_utc())
    with open(path.with_name(path.name + ".audit.jsonl"), "a", encoding="utf-8", newline="\n") as f:
        f.write(canonical_json(rec) + "\n")
    return rec


def read_jsonl(path: os.PathLike | str) -> list[dict]:
    path = Path(path)
    if not path.exists():
        return []
    out = []
    for n, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        line = line.strip()
        if line:
            try:
                out.append(json.loads(line))
            except ValueError as e:
                raise JournalCorrupt(f"JOURNAL_CORRUPT:{path.name}:line {n}: {e}") from None
    return out


# ---------------------------------------------------------------- time
def iso_utc(ts: float | int | None) -> str | None:
    if ts is None:
        return None
    try:
        if not math.isfinite(float(ts)):
            return None
    except (TypeError, ValueError):
        return None
    return _dt.datetime.fromtimestamp(float(ts), UTC).isoformat().replace("+00:00", "Z")


def parse_utc(s: str) -> float:
    s = s.strip()
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    d = _dt.datetime.fromisoformat(s)
    if d.tzinfo is None:
        raise ValueError(f"timestamp must carry a timezone (got {s!r})")
    return d.astimezone(UTC).timestamp()


def now_utc() -> float:
    return _dt.datetime.now(UTC).timestamp()


def now_iso_local() -> str:
    return _dt.datetime.now().astimezone().isoformat()


# ---------------------------------------------------------------- price grid
def _dec(x: float) -> Decimal:
    return Decimal(repr(float(x)))


GRID_SNAP_TICKS = Decimal("1e-7")   # values within 1e-7 tick of a grid point are float noise → that grid point


def _grid_units(x: float, q: float) -> Decimal:
    if not (q > 0 and math.isfinite(q)):
        raise ValueError("TICK_SIZE_INVALID")
    if not math.isfinite(x):
        raise ValueError("PRICE_NONFINITE")
    u = _dec(x) / _dec(q)
    near = u.to_integral_value()
    return near if abs(u - near) <= GRID_SNAP_TICKS else u


def ceil_to_tick(x: float, q: float) -> float:
    n = _grid_units(x, q).to_integral_value(rounding=ROUND_CEILING)
    return float(n * _dec(q))


def floor_to_tick(x: float, q: float) -> float:
    n = _grid_units(x, q).to_integral_value(rounding=ROUND_FLOOR)
    return float(n * _dec(q))


def round_volume_down(volume: float, step: float, vmin: float, vmax: float) -> tuple[float | None, str]:
    """Round a lot size DOWN to the volume step. Returns (volume or None, reason)."""
    if not (step > 0 and vmin > 0 and vmax >= vmin):
        return None, "VOLUME_METADATA_INVALID"
    if not math.isfinite(volume) or volume <= 0:
        return None, "VOLUME_NONPOSITIVE"
    v = float((_dec(volume) / _dec(step)).to_integral_value(rounding=ROUND_FLOOR) * _dec(step))
    if v < vmin:
        return None, "BELOW_MIN_VOLUME_RISK_EXCEEDED"
    return min(v, vmax), "OK"


# ---------------------------------------------------------------- envelope
def envelope(status: str, data: Any = None, *, snapshot_id: str | None = None, as_of: str | None = None,
             quality: Iterable[str] | dict | None = None, errors: list | None = None, command: str = "") -> dict:
    assert status in ("OK", "OK_EMPTY", "PARTIAL", "ERROR"), status
    return {
        "status": status,
        "schema_version": SCHEMA_VERSION,
        "command": command,
        "request_id": "req_" + uuid.uuid4().hex[:16],
        "snapshot_id": snapshot_id,
        "as_of": as_of,
        "data": data,
        "quality": (list(quality) if quality is not None and not isinstance(quality, dict) else quality) or [],
        "errors": errors or [],
    }
