"""Read-only MT5 parity for B3 ledgers: compare our cash P&L with MT5's own calculator.

Uses only `order_calc_profit` / `order_calc_margin` (pure calculations; no order is sent) through the ReadOnlyMT5
whitelist, and only on a terminal already running at the selected path whose identity (path / connected / account)
is verified right after attach. Without a running terminal the result is PENDING_LIVE — never reported as verified.

Status semantics (B6A): OK only when at least one case was compared, every requested case was compared and all
matched. Zero comparable cases → INCONCLUSIVE_NO_COMPARABLE_CASES; skipped cases → PARTIAL_MATCH with coverage;
a calculator returning None → INCONCLUSIVE_CALC_UNAVAILABLE; any mismatch → MISMATCH. order_calc_profit checks
gross P&L only (no commission / swap / slippage); order_calc_margin output is an observation, not margin parity."""
from __future__ import annotations

import math
import os
from typing import Callable

from .collector import ReadOnlyMT5, running_terminal_paths, runtime_enum_contract, verify_attached_identity

CALC_CALLS = ("order_calc_profit", "order_calc_margin", "ORDER_TYPE_BUY", "ORDER_TYPE_SELL")
SUPPORTED_CALC = ("PROFIT_CCY_IS_ACCOUNT_CCY", "BASE_CCY_IS_ACCOUNT_CCY")


def independent_gross(side: str, entry: float, exit_price: float, volume: float, contract_size: float | None,
                      profit_ccy: str | None, base_ccy: str | None, account_ccy: str | None) -> tuple[float | None, str]:
    """Plain arithmetic for the two linear (FX/CFD 'Forex'-style) cases only; anything else is UNKNOWN."""
    if not contract_size or contract_size <= 0 or not profit_ccy or not account_ccy:
        return None, "UNKNOWN_METADATA"
    sgn = 1.0 if side == "LONG" else -1.0
    gross_profit_ccy = (exit_price - entry) * sgn * contract_size * volume
    if profit_ccy == account_ccy:
        return gross_profit_ccy, "PROFIT_CCY_IS_ACCOUNT_CCY"
    if base_ccy == account_ccy and exit_price > 0:
        return gross_profit_ccy / exit_price, "BASE_CCY_IS_ACCOUNT_CCY"
    return None, "UNKNOWN_CONVERSION"


def summarize(out: list[dict]) -> dict:
    n = len(out)
    match = sum(o["status"] == "MATCH" for o in out)
    mism = sum(o["status"] == "MISMATCH" for o in out)
    none = sum(o["status"] == "CALC_NONE" for o in out)
    skipped = sum(o["status"] == "SKIPPED" for o in out)
    checked = match + mism + none
    if n == 0:
        st = "INCONCLUSIVE_NO_ROWS"
    elif checked == 0:
        st = "INCONCLUSIVE_NO_COMPARABLE_CASES"
    elif mism:
        st = "MISMATCH"
    elif none:
        st = "INCONCLUSIVE_CALC_UNAVAILABLE"
    elif skipped:
        st = "PARTIAL_MATCH"
    else:
        st = "OK"
    return {"status": st, "requested": n, "checked": checked, "matched": match, "mismatched": mism, "calc_none": none,
            "skipped": skipped, "coverage": (match / n) if n else 0.0}


def _ccy(v) -> str | None:
    return v.strip().upper() if isinstance(v, str) and v.strip() else None


def compare_rows(rows: list[dict], calc, buy, sell, tol_cash: float, margin_calc=None, account_ccy: str | None = None) -> list[dict]:
    """Rows are compared only in the SAME currency unit: native account currency (identified) == row cash currency.
    Missing / different units are SKIPPED with a reason (no historical conversion is invented here)."""
    out = []
    acc = _ccy(account_ccy)
    for r in rows:
        cash = r.get("cash") or {}
        if r.get("status") != "FILLED":
            out.append({"fill_id": r.get("fill_id"), "status": "SKIPPED", "reason": "NOT_FILLED"})
            continue
        if cash.get("status") != "OK" or r.get("primary", {}).get("exit_price") is None:
            out.append({"fill_id": r.get("fill_id"), "status": "SKIPPED", "reason": "NO_CASH_ROW:" + str(cash.get("reason") or cash.get("status"))})
            continue
        row_ccy = _ccy(cash.get("account_currency"))
        if acc is None:
            out.append({"fill_id": r.get("fill_id"), "status": "SKIPPED", "reason": "NATIVE_ACCOUNT_CURRENCY_UNKNOWN"})
            continue
        if row_ccy is None:
            out.append({"fill_id": r.get("fill_id"), "status": "SKIPPED", "reason": "ROW_CURRENCY_UNKNOWN"})
            continue
        if row_ccy != acc:
            out.append({"fill_id": r.get("fill_id"), "status": "SKIPPED", "reason": f"CURRENCY_MISMATCH:{row_ccy}!={acc}"})
            continue
        otype = buy if r["side"] == "LONG" else sell
        native = calc(otype, r["symbol"], cash["volume"], r["entry"], r["primary"]["exit_price"])
        ours = cash["gross_cash"]
        rec = {"fill_id": r.get("fill_id"), "symbol": r["symbol"], "side": r["side"], "volume": cash["volume"],
               "entry": r["entry"], "exit": r["primary"]["exit_price"], "ours_gross_cash": ours, "native_gross_profit": native,
               "account_currency": cash.get("account_currency")}
        if native is None or (isinstance(native, float) and not math.isfinite(native)):
            rec["status"] = "CALC_NONE"
        else:
            rec["abs_diff"] = abs(native - ours)
            rec["status"] = "MATCH" if rec["abs_diff"] <= tol_cash else "MISMATCH"
        if margin_calc is not None:
            try:
                rec["margin_observation"] = margin_calc(otype, r["symbol"], cash["volume"], r["entry"])
            except Exception as e:  # observation only
                rec["margin_observation"] = f"ERROR:{type(e).__name__}"
        out.append(rec)
    return out


IDENTITY_KEYS = ("terminal_path", "data_path", "server", "account_fingerprint", "account_currency", "connected")


def profit_parity(rows: list[dict], terminal_path: str, mt5_module=None, process_lister: Callable[[], list[str]] = running_terminal_paths,
                  tol_cash: float = 0.01, evidence_kind: str | None = None, observe_margin: bool = False) -> dict:
    """evidence_kind: NATIVE_TERMINAL only when the real MetaTrader5 module is imported here; an injected module is
    SYNTHETIC unless the caller labels it explicitly. Identity is verified after attach AND again after the batch;
    any change (or failure) invalidates the batch instead of attributing it to the first identity."""
    exe = os.path.normcase(os.path.abspath(terminal_path if terminal_path.lower().endswith(".exe") else os.path.join(terminal_path, "terminal64.exe")))
    runtime = runtime_enum_contract() if mt5_module is None else {"status": "NOT_EVALUATED_INJECTED_MODULE_SYNTHETIC"}
    if exe not in process_lister():
        return {"status": "PENDING_LIVE", "reason": "TERMINAL_NOT_RUNNING_AT_SELECTED_PATH", "checked": 0, "initialize_called": False,
                "runtime_contract": runtime,
                "procedure": "start the selected terminal yourself (logged in), then rerun; this tool never launches or logs in"}
    if mt5_module is None:
        import MetaTrader5 as mt5_module  # noqa: N813
        evidence_kind = evidence_kind or "NATIVE_TERMINAL"
    else:
        # An injected module can never be labelled native, whatever the caller passes.
        if evidence_kind and not evidence_kind.startswith("SYNTHETIC"):
            evidence_kind = f"SYNTHETIC_INJECTED_MODULE(rejected_label={evidence_kind})"
        evidence_kind = evidence_kind or "SYNTHETIC_INJECTED_MODULE"
    mt5 = ReadOnlyMT5(mt5_module)
    if not mt5.initialize(path=exe):
        return {"status": "ERROR", "reason": "INITIALIZE_FAILED", "checked": 0, "evidence_kind": evidence_kind}
    try:
        identity, why = verify_attached_identity(mt5, exe)
        if identity is None:
            return {"status": "ERROR", "reason": why, "checked": 0, "evidence_kind": evidence_kind}
        out = compare_rows(rows, mt5.order_calc_profit, mt5.ORDER_TYPE_BUY, mt5.ORDER_TYPE_SELL, tol_cash,
                           mt5.order_calc_margin if observe_margin else None, account_ccy=identity.get("account_currency"))
        res = summarize(out)
        after, why_after = verify_attached_identity(mt5, exe)
        changed = [k for k in IDENTITY_KEYS if after is None or after.get(k) != identity.get(k)]
        if after is None or changed:
            res.update({"status": "INVALIDATED_SOURCE_CHANGED", "matched": 0, "coverage": 0.0,
                        "reason": why_after or ("IDENTITY_CHANGED:" + ",".join(changed)), "identity_before": identity, "identity_after": after,
                        "rows": out, "evidence_kind": evidence_kind})
            return res
        res.update({"rows": out, "evidence_kind": evidence_kind, "identity": identity, "identity_rechecked_after_batch": True,
                    "runtime_contract": runtime,
                    "unit": identity.get("account_currency"),
                    "note": "gross P&L parity in the identified account currency only; commission/swap/slippage are NOT verified "
                            "by order_calc_profit; margin values are observations"})
        return res
    finally:
        mt5.shutdown()
