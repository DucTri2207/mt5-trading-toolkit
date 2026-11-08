"""Declared evening universes; broker symbols are exact mappings, never suffix guesses."""
from __future__ import annotations

import re
from collections.abc import Iterable, Mapping

MAIN8 = ("XAUUSD", "EURUSD", "USDJPY", "GBPUSD", "USDCAD", "USDCHF", "AUDUSD", "NZDUSD")
EXTENDED12 = MAIN8 + ("EURJPY", "GBPJPY", "EURGBP", "AUDJPY")
OIL_ALIASES = ("USOIL", "UKOIL", "XTIUSD", "XBRUSD", "WTI", "BRENT")


def validate_map(mapping: Mapping[str, str] | Iterable[tuple[str, str]]) -> dict[str, str]:
    """Validate before collection. A pair iterable also catches duplicate canonical names before dict conversion."""
    pairs = mapping.items() if isinstance(mapping, Mapping) else mapping
    out, natives = {}, set()
    for canonical, native in pairs:
        if not isinstance(canonical, str) or not isinstance(native, str):
            raise ValueError("SYMBOL_MAP_MUST_CONTAIN_STRINGS")
        canonical, native = canonical.strip().upper(), native.strip()
        if not canonical or not native or not re.fullmatch(r"[A-Z][A-Z0-9_]*", canonical):
            raise ValueError("SYMBOL_MAP_INVALID_NAME")
        if any(char.isspace() or char in "/\\:=,*?" for char in native) or native in (".", ".."):
            raise ValueError(f"SYMBOL_MAP_NATIVE_MUST_BE_EXACT:{native}")
        if any(name.startswith(alias) for name in (canonical, native.upper()) for alias in OIL_ALIASES):
            raise ValueError(f"OIL_EXCLUDED:{canonical}:{native}")
        if canonical in out:
            raise ValueError(f"DUPLICATE_CANONICAL_SYMBOL:{canonical}")
        if native.casefold() in natives:
            raise ValueError(f"DUPLICATE_NATIVE_SYMBOL:{native}")
        out[canonical] = native
        natives.add(native.casefold())
    if not out:
        raise ValueError("SYMBOL_MAP_EMPTY")
    return out
