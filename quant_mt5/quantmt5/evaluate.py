"""B3/B4: branch selection on a shared raw catalog, execution scenarios, metrics, block bootstrap, paired tests,
portfolio benchmark. Results are R-normalised; no lot sizing without a risk profile."""
from __future__ import annotations

import datetime as dt
import math
from collections import Counter, defaultdict
from typing import Any

import numpy as np

from . import ENGINE_VERSION, STRATEGY_VERSION
from .config import config_hash, cost_profiles, strategy
from .data import dataset_version, load_registry
from .detectors import SymbolData, detect_all, load_symbol
from .execution import M1OpenProxy, make_params, simulate
from .timemap import NY, UTC
from .util import engine_hash, iso_utc

BRANCHES_A = ("M0", "M1", "M2")
BRANCHES_B = ("P0", "P1", "P2")
PAIRED = (("M2", "M0"), ("M2", "M1"), ("P1", "P0"), ("P2", "P1"))
BOOT_SEED = 20261103


def session_date(ts: float) -> dt.date:
    """NY trading-session date: a session runs 17:00 NY (previous day) → 17:00 NY."""
    ny = dt.datetime.fromtimestamp(ts, UTC).astimezone(NY)
    return (ny + dt.timedelta(hours=7)).date()


def ny_bucket(ts: float) -> str:
    h = dt.datetime.fromtimestamp(ts, UTC).astimezone(NY).hour
    if 8 <= h < 12:
        return "NY_08_12"
    if 12 <= h < 17:
        return "NY_12_17"
    if 2 <= h < 8:
        return "LONDON_02_08"
    return "ASIA_17_02"


# ------------------------------------------------------------------ selection per branch
def select_branch(cands: list[dict], branch: str, run_exec) -> tuple[list[dict], Counter]:
    """Apply the branch gate in time order on the shared catalog. A: max one fill per episode; blocked candidates
    stay recorded and the next candidate of the episode may be tried. B: every passing pattern is its own plan."""
    from .util import stable_id
    stats = Counter()
    ledger = []
    done_eps: dict[str, str] = {}
    for c in sorted(cands, key=lambda x: (x["ready_ts"], x["candidate_id"])):
        g = c["gates"].get(branch, {}).get("result")
        stats[f"gate_{g}"] += 1
        base = {"candidate_id": c["candidate_id"], "candidate_revision": c.get("revision_id"), "branch": branch, "setup": c["setup"],
                "symbol": c["symbol"], "side": c["side"], "ready_at": c["ready_at"]}
        if g != "PASS":
            ledger.append(dict(base, status="NOT_ELIGIBLE", reason=f"GATE_{g}:{c['gates'].get(branch, {}).get('reason', '')}",
                               ledger_row_id=stable_id("LEDGER", c.get("revision_id") or c["candidate_id"], branch, "GATE")))
            continue
        if c["setup"] == "A" and c["episode_id"] in done_eps:
            stats["skipped_episode_already_filled"] += 1
            ledger.append(dict(base, status="SKIPPED", reason="EPISODE_ALREADY_FILLED_IN_BRANCH", filled_by=done_eps[c["episode_id"]],
                               ledger_row_id=stable_id("LEDGER", c.get("revision_id") or c["candidate_id"], branch, "SKIP")))
            continue
        r = dict(run_exec(c))
        r["branch"] = branch
        r["ledger_row_id"] = stable_id("LEDGER", r.get("fill_id"), branch)
        stats[f"exec_{r['status']}"] += 1
        if r["status"] == "BLOCKED":
            stats[f"blocked_{r['reason']}"] += 1
        ledger.append(r)
        if r["status"] == "FILLED" and c["setup"] == "A":
            done_eps[c["episode_id"]] = r["fill_id"]
    return ledger, stats


# ------------------------------------------------------------------ metrics
def _block_bootstrap_means(x: np.ndarray, block: int, B: int, rng: np.random.Generator) -> np.ndarray:
    n = len(x)
    if n == 0:
        return np.array([])
    nb = int(math.ceil(n / block))
    starts = rng.integers(0, max(1, n - block + 1), size=(B, nb))
    idx = (starts[:, :, None] + np.arange(block)[None, None, :]).reshape(B, -1)[:, :n]
    return x[idx].mean(axis=1)


INFERENCE_METHOD = {
    "statistic": "mean of the daily net-R series (all calendar days, zero days included)",
    "resampling": "moving-block bootstrap over consecutive calendar days (a day = sum over symbols, so same-day symbols stay together)",
    "ci95": "percentile of the uncentred block-bootstrap means",
    "null": "H0: mean daily R = 0; null distribution = block-bootstrap means of the series centred at its sample mean",
    "alternative": "two-sided",
    "p_value": "(1 + #{|T*_null| >= |T_obs|}) / (B + 1)  (Monte Carlo corrected)",
    "multiplicity": "Holm over the declared family (4 primary paired comparisons per scenario); a missing p counts as 1 in the family",
}


def bootstrap_ci(x: np.ndarray, block: int = 5, B: int = 2000, seed: int = BOOT_SEED) -> dict:
    """Mean, percentile CI and a NULL-CENTRED block-bootstrap p-value (see INFERENCE_METHOD).

    Resampling the centred series x - mean(x) with the same block indices gives exactly bm - mean(x), so the
    null statistics are computed from the same draws."""
    x = np.asarray(x, dtype=float)
    rng = np.random.default_rng(seed)
    bm = _block_bootstrap_means(x, block, B, rng)
    if len(bm) == 0:
        return {"mean": None, "ci95": [None, None], "p_two_sided_bootstrap": None, "block_days": block, "resamples": B, "seed": seed,
                "method": "null-centred moving-block bootstrap"}
    m = float(x.mean())
    null = bm - m
    tol = 1e-12 * max(1.0, abs(m))
    p = (1 + int(np.sum(np.abs(null) >= abs(m) - tol))) / (B + 1)
    return {"mean": m, "ci95": [float(np.quantile(bm, 0.025)), float(np.quantile(bm, 0.975))],
            "p_two_sided_bootstrap": float(min(1.0, p)), "block_days": block, "resamples": B, "seed": seed,
            "method": "null-centred moving-block bootstrap; percentile CI; MC-corrected two-sided p"}


def holm(pvals: dict[str, float | None]) -> dict[str, float | None]:
    """Holm step-down over the WHOLE declared family: a comparison without a valid p (e.g. unresolved outcomes)
    still counts in the family size as p = 1; its adjusted p is reported as None."""
    items = sorted((1.0 if v is None else v, k) for k, v in pvals.items())
    m = len(items)
    out, running = {}, 0.0
    for r, (v, k) in enumerate(items):
        adj = min(1.0, (m - r) * v)
        running = max(running, adj)
        out[k] = None if pvals[k] is None else running
    return out


def trading_days(start: dt.date, end: dt.date) -> list[dt.date]:
    d, out = start, []
    while d <= end:
        if d.weekday() < 5:
            out.append(d)
        d += dt.timedelta(days=1)
    return out


class CalendarError(ValueError):
    pass


def daily_series(fills: list[dict], days: list[dt.date], key: str = "net_R") -> np.ndarray:
    """Resolved P&L by exit session date on a FIXED calendar. A resolved exit outside the calendar is rejected
    (OUTSIDE_CALENDAR) — never silently dropped. Unresolved rows carry no P&L and are counted elsewhere."""
    pos = {d: i for i, d in enumerate(days)}
    s = np.zeros(len(days))
    for f in fills:
        t = _ts(f["primary"]["exit_at"]) if f["primary"].get("exit_at") else None
        v = f.get(key) if key != "fav" else f.get("favorable_first", f["primary"]).get("net_R")
        if t is None or v is None:
            continue
        d = session_date(t)
        if d not in pos:
            raise CalendarError(f"OUTSIDE_CALENDAR: resolved exit of {f.get('candidate_id')} on session {d} is outside the "
                                f"evaluation calendar {days[0] if days else None}..{days[-1] if days else None}")
        s[pos[d]] += v
    return s


def unresolved_day_mask(fills: list[dict], days: list[dt.date]) -> np.ndarray:
    """Days whose outcome set is incomplete: from the fill session of an unresolved trade to the calendar end
    (its exit day is unknown, so every later day may carry the missing P&L)."""
    pos = {d: i for i, d in enumerate(days)}
    mask = np.zeros(len(days), dtype=bool)
    for f in fills:
        if f.get("status") == "FILLED" and f.get("net_R") is None:
            d = session_date(_ts(f["fill_at"])) if f.get("fill_at") else None
            i = pos.get(d)
            if i is None:
                raise CalendarError(f"OUTSIDE_CALENDAR: unresolved fill of {f.get('candidate_id')} on session {d}")
            mask[i:] = True
    return mask


def calendar_with_horizon(start: dt.date, end: dt.date, ledgers: list[list[dict]]) -> tuple[list[dt.date], list[dt.date]]:
    """Shared calendar for every branch/scenario/portfolio of one run: weekdays start..end plus the valid exit
    horizon (weekdays up to the last resolved exit session, and any non-weekday exit session date)."""
    exit_days = set()
    for led in ledgers:
        for r in led:
            if r.get("status") == "FILLED" and r.get("net_R") is not None and r["primary"].get("exit_at"):
                exit_days.add(session_date(_ts(r["primary"]["exit_at"])))
            elif r.get("status") == "FILLED" and r.get("fill_at"):
                exit_days.add(session_date(_ts(r["fill_at"])))          # unresolved: its fill day must be on the calendar
    last = max([end] + list(exit_days))
    days = sorted(set(trading_days(start, last)) | {d for d in exit_days if d >= start})
    return days, [d for d in days if d > end or d.weekday() >= 5]


def metrics(ledger: list[dict], days: list[dt.date], stats: Counter) -> dict[str, Any]:
    fills = [r for r in ledger if r["status"] == "FILLED" and r.get("net_R") is not None]
    unresolved = [r for r in ledger if r["status"] == "FILLED" and r.get("net_R") is None]
    unresolved_reasons: dict[str, int] = {}
    for r in unresolved:
        flags = r.get("flags", []) or []
        if "EXIT_UNRESOLVED" in flags:
            reason = "EXIT_UNRESOLVED"
        elif "COMMISSION_UNKNOWN" in flags:
            reason = "COMMISSION_UNKNOWN"
        else:
            reason = "NET_R_NONE_OTHER"
        unresolved_reasons[reason] = unresolved_reasons.get(reason, 0) + 1
    nR = np.array([r["net_R"] for r in fills])
    daily = daily_series(fills, days)
    cum = np.cumsum(daily)
    peak = np.maximum.accumulate(np.r_[0.0, cum])[1:]
    dd = cum - peak
    # recovery: longest stretch under water (days)
    under, longest = 0, 0
    for v in dd:
        under = under + 1 if v < 0 else 0
        longest = max(longest, under)
    streak, worst_streak = 0, 0
    for v in nR:
        streak = streak + 1 if v < 0 else 0
        worst_streak = max(worst_streak, streak)
    amb = [r for r in fills if r.get("ambiguous_sl_tp")]
    fav_total = float(sum((r.get("favorable_first") or r["primary"]).get("net_R", r["net_R"]) for r in fills)) if fills else 0.0
    by = lambda keyf: {k: {"n": len(v), "net_R": float(sum(v)), "expectancy_R": float(np.mean(v))}
                       for k, v in _group(fills, keyf).items()}
    pos_days = np.sort(daily[daily > 0])[::-1]
    weeks = max(1e-9, len(days) / 5)
    res = {
        "n_trading_days": len(days), "catalog_gate_counts": {k: v for k, v in stats.items() if k.startswith("gate_")},
        "exec_counts": {k: v for k, v in stats.items() if k.startswith(("exec_", "blocked_", "skipped_"))},
        "n_fills": len(fills), "fills_per_week": len(fills) / weeks,
        "n_fills_unresolved": len(unresolved), "unresolved_reasons": unresolved_reasons,
        "net_R_total": float(nR.sum()) if len(nR) else 0.0,
        "expectancy_R_per_trade": float(nR.mean()) if len(nR) else None,
        "win_rate": float((nR > 0).mean()) if len(nR) else None,
        "avg_win_R": float(nR[nR > 0].mean()) if (nR > 0).any() else None,
        "avg_loss_R": float(nR[nR <= 0].mean()) if (nR <= 0).any() else None,
        "mean_daily_R": bootstrap_ci(daily),
        "max_drawdown_R_closed": float(dd.min()) if len(dd) else 0.0,
        "longest_underwater_days": longest, "worst_day_R": float(daily.min()) if len(daily) else 0.0,
        "longest_losing_streak": worst_streak,
        "mae_R_mean": float(np.mean([r["mae_R"] for r in fills])) if fills else None,
        "mfe_R_mean": float(np.mean([r["mfe_R"] for r in fills])) if fills else None,
        "hold_minutes_mean": float(np.mean([r["primary"]["hold_s"] for r in fills if r["primary"].get("hold_s") is not None]) / 60) if fills else None,
        "cost_over_R_mean": float(np.mean([r["cost_over_R"] for r in fills if "cost_over_R" in r])) if fills else None,
        "spread_over_R_mean": float(np.mean([r["spread_over_R"] for r in fills])) if fills else None,
        "entry_drift_over_atr_mean": float(np.mean([r["entry_drift_over_atr"] for r in fills])) if fills else None,
        "exit_reasons": dict(Counter(r["primary"]["exit_reason"] for r in fills)),
        "ambiguous_sl_tp": {"n": len(amb), "net_R_total_adverse_first": float(nR.sum()) if len(nR) else 0.0,
                            "net_R_total_favorable_first": fav_total,
                            "note": "headline uses adverse-first; favourable-first shown only as sensitivity"},
        "top5_days_share_of_positive_R": float(pos_days[:5].sum() / pos_days.sum()) if pos_days.sum() > 0 else None,
        "by_year": by(lambda r: r["fill_at"][:4]), "by_side": by(lambda r: r["side"]),
        "by_ny_bucket": by(lambda r: ny_bucket(_ts(r["fill_at"]))),
        "by_symbol": by(lambda r: r["symbol"]),
    }
    res["mean_daily_R"]["scope"] = "RESOLVED_OUTCOMES_ONLY" if unresolved else "ALL_FILLS_RESOLVED"
    res["daily_sum_equals_ledger_net_R"] = bool(abs(float(daily.sum()) - res["net_R_total"]) <= 1e-9 * max(1.0, abs(res["net_R_total"])))
    res["verdict_min_sample"] = dict(VERDICT_SAMPLE_POLICY)
    res["verdict"] = verdict(res)
    if unresolved:
        # Unknown outcomes are NOT imputed (never 0R). The resolved-subset reading is descriptive and conditional.
        res["resolved_subset"] = {"verdict": verdict(dict(res, n_fills_unresolved=0)),
                                  "label": "CONDITIONAL_ON_RESOLVED_OUTCOMES — descriptive only; unresolved outcomes could change the sign"}
    return res


# Software guard, not a strategy gate: below these sizes a bootstrap CI over a few days is not a basis for any
# decisive verdict (recheck 2026-11-04: 2 fills / 5 days produced REJECTED_NEGATIVE_CI). Declared before any
# full B4 research run; Codex may revise them in the B4 registration, never after seeing P&L.
MIN_FILLS_FOR_VERDICT = 30
MIN_DAYS_FOR_VERDICT = 60
VERDICT_SAMPLE_POLICY = {
    "fills": MIN_FILLS_FOR_VERDICT, "trading_days": MIN_DAYS_FOR_VERDICT,
    "policy": "PROVISIONAL software floor below which no decisive verdict is printed. It is NOT a sample-size or power "
              "certification: passing it does not mean the sample is sufficient or that any edge is established. "
              "To be locked (or replaced) in the B4 registration before outcomes are seen.",
}


def verdict(m: dict) -> str:
    ci = m["mean_daily_R"].get("ci95") or [None, None]
    if m.get("n_fills_unresolved"):
        return "INCONCLUSIVE_UNRESOLVED_OUTCOMES"           # overall verdict needs every outcome (or proper bounds)
    if m["n_fills"] == 0 or ci[0] is None:
        return "INCONCLUSIVE_NO_FILLS"
    if m["n_fills"] < MIN_FILLS_FOR_VERDICT or m["n_trading_days"] < MIN_DAYS_FOR_VERDICT:
        return "INCONCLUSIVE_THIN_SAMPLE"
    if ci[1] < 0:
        return "REJECTED_NEGATIVE_CI"
    if ci[0] > 0:
        return "POSITIVE_CI_ON_EXPOSED_HISTORY"
    return "INCONCLUSIVE"


def _group(fills, keyf):
    g = defaultdict(list)
    for r in fills:
        g[keyf(r)].append(r["net_R"])
    return g


def _ts(iso: str) -> float:
    return dt.datetime.fromisoformat(iso.replace("Z", "+00:00")).timestamp()


# ------------------------------------------------------------------ portfolio
def portfolio(ledgers: dict[str, list[dict]], cands_by_id: dict[str, dict], pcfg: dict) -> dict:
    """Declared pair benchmark. Same symbol & same ready time: same side → keep A, tag B; opposite → drop both.
    Then accept in (ready_at, spread/R, symbol) order subject to 1 position/symbol and 1 open risk unit total."""
    from .util import stable_id
    pool = []
    for br, led in ledgers.items():
        for r in led:
            if r["status"] == "FILLED":            # selection never depends on P&L (net may be UNKNOWN)
                c = cands_by_id[r["candidate_id"]]
                pool.append(dict(r, branch=br, ready_ts=c["ready_ts"], signal_close_ts=c["signal_close_ts"]))
    events = defaultdict(list)
    for r in pool:
        events[(r["symbol"], r["signal_close_ts"])].append(r)     # same symbol + same signal bar close = same market event
    linked, dropped = [], []
    for key, rs in sorted(events.items()):
        sides = {r["side"] for r in rs}
        if len(sides) > 1:
            dropped += [dict(r, portfolio_reason="CONFLICT_OPPOSITE_SIDES_DROP_BOTH", conflict_with=sorted(x["candidate_id"] for x in rs if x is not r))
                        for r in rs]
            continue
        rs = sorted(rs, key=lambda r: (r["setup"] != "A", r["candidate_id"]))
        linked.append(dict(rs[0], linked_tags=[x["candidate_id"] for x in rs[1:]]))
        dropped += [dict(r, portfolio_reason="SAME_EVENT_LINKED_TO_A", linked_to=rs[0]["candidate_id"]) for r in rs[1:]]
    # Capacity is consumed in actual fill-event order. Ranking by readiness
    # could let a later fill reserve the only risk slot and retroactively reject
    # an earlier fill, making an outcome at t=+60 change a decision at t=+16.
    # Fill time is part of the event ledger; remaining keys are deterministic
    # tie breakers based on values available at the decision.
    linked.sort(key=lambda r: (_ts(r["fill_at"]), r["ready_ts"], r.get("spread_over_R", 0), r["symbol"], r["candidate_id"]))
    open_pos: list[tuple[float, str]] = []
    accepted, rejected = [], []
    for r in linked:
        t_fill, t_exit = _ts(r["fill_at"]), _ts(r["primary"]["exit_at"]) if r["primary"].get("exit_at") else float("inf")
        open_pos = [(te, s) for te, s in open_pos if te > t_fill]
        if any(s == r["symbol"] for _, s in open_pos) and len([1 for _, s in open_pos if s == r["symbol"]]) >= pcfg["max_positions_per_symbol"]:
            rejected.append(dict(r, portfolio_reason="SYMBOL_POSITION_OPEN"))
            continue
        if len(open_pos) >= pcfg["max_open_risk_units_total"]:
            rejected.append(dict(r, portfolio_reason="RISK_BUDGET_FULL"))
            continue
        open_pos.append((t_exit, r["symbol"]))
        accepted.append(r)
    for r in accepted + rejected + dropped:
        r["portfolio_row_id"] = stable_id("PF", r.get("fill_id"), r.get("branch"), r.get("portfolio_reason", "ACCEPTED"))
    return {"accepted": accepted, "rejected": rejected, "dropped": dropped,
            "counts": {"pool": len(pool), "accepted": len(accepted), "rejected": dict(Counter(r["portfolio_reason"] for r in rejected)),
                       "dropped": dict(Counter(r["portfolio_reason"] for r in dropped))}}


# ------------------------------------------------------------------ experiment run
def run_experiment(exp: dict, progress=print) -> dict:
    cfg = strategy()
    cc = cfg["common"]
    costs = cost_profiles()
    lat = costs["latency_scenarios_s"]
    out: dict[str, Any] = {"experiment_id": exp["experiment_id"], "engine_version": ENGINE_VERSION, "engine_hash": engine_hash(),
                           "config_hash": config_hash(), "strategy_version": STRATEGY_VERSION, "symbols": {}, "results": {}}
    out["data_versions"] = {}
    for sym in exp["universe"]:
        try:
            reg = load_registry()
            ds = reg["symbols"][sym]
            sym_vers = {}
            for tf in ds.get("timeframes", {}):
                v = dataset_version(reg, sym, tf)
                if v.get("status") != "UNAVAILABLE":
                    sym_vers[tf] = v
            out["data_versions"][sym] = sym_vers
        except Exception as e:
            out["data_versions"][sym] = {"error": type(e).__name__}
    start = dt.date.fromisoformat(exp["evaluation"]["start"])
    end = dt.date.fromisoformat(exp["evaluation"]["end"])
    in_window = lambda c: start <= session_date(c["ready_ts"]) <= end
    catalogs: dict[str, dict] = {}
    for sym in exp["universe"]:
        sd = load_symbol(sym)
        cat = detect_all(sd, cfg)
        cands = [c for c in cat["candidates"] if in_window(c)]
        catalogs[sym] = {"sd": sd, "cands": cands, "episodes": [e for e in cat["episodes"] if start <= session_date(e["breakout_close_ts"]) <= end]}
        out["symbols"][sym] = {"raw_candidates": len(cands), "episodes": len(catalogs[sym]["episodes"]),
                               "by_setup_side": dict(Counter(f"{c['setup']}_{c['side']}" for c in cands)),
                               "gate_counts": {br: dict(Counter(c["gates"].get(br, {}).get("result") for c in cands if c["setup"] == br[0].replace("M", "A").replace("P", "B")))
                                               for br in BRANCHES_A + BRANCHES_B},
                               "execution_model": "M1_OPEN_PROXY" if sd.m1 is not None else "NOT_EVALUABLE",
                               "execution_block_reason": None if sd.m1 is not None else "HISTORY_INSUFFICIENT:M1_MISSING + ASK_MISSING + TICKS_MISSING + CONTRACT_SIZE_UNKNOWN"}
        progress(f"catalog {sym}: {len(cands)} candidates, {out['symbols'][sym]['episodes']} episodes")
    exec_syms = [s for s in exp["universe"] if catalogs[s]["sd"].m1 is not None]
    pending: dict[str, tuple] = {}
    for cost_name in exp["cost_scenarios"]:
        cost = costs["scenarios"][cost_name]
        qms = {s: M1OpenProxy(catalogs[s]["sd"].m1, float(catalogs[s]["sd"].prof["point"]), cost["spread_floor_points"][s]) for s in exec_syms}
        for lat_name in exp["latency_scenarios"]:
            params = {s: make_params(s, catalogs[s]["sd"].prof, cost, cost_name, lat_name, lat[lat_name], cc) for s in exec_syms}
            cache: dict[str, dict] = {}

            def run_exec(c):
                if c["candidate_id"] not in cache:
                    cache[c["candidate_id"]] = simulate(c, qms[c["symbol"]], params[c["symbol"]])
                return cache[c["candidate_id"]]

            scen = f"{lat_name}/{cost_name}"
            ledgers, stats = {}, {}
            for br in BRANCHES_A + BRANCHES_B:
                setup = "A" if br in BRANCHES_A else "B"
                cands = [c for s in exec_syms for c in catalogs[s]["cands"] if c["setup"] == setup]
                ledgers[br], stats[br] = select_branch(cands, br, run_exec)
            pair = exp["portfolio"]["declared_pair"]
            cands_by_id = {c["candidate_id"]: c for s in exec_syms for c in catalogs[s]["cands"]}
            pf = portfolio({pair["A"]: ledgers[pair["A"]], pair["B"]: ledgers[pair["B"]]}, cands_by_id, cfg["portfolio"])
            pending[scen] = (ledgers, stats, pair, pf)
    # Pass 2: ONE shared calendar for every branch, scenario, portfolio and paired series (window weekdays incl.
    # zero days + the valid exit horizon). Resolved P&L is never dropped at the boundary; unresolved stays unresolved.
    days, ext = calendar_with_horizon(start, end, [led for (ls, _, _, _) in pending.values() for led in ls.values()])
    for scen, (ledgers, stats, pair, pf) in pending.items():
        for br in BRANCHES_A + BRANCHES_B:
            out["results"].setdefault(scen, {})[br] = metrics(ledgers[br], days, stats[br])
        filled = {br: [r for r in ledgers[br] if r["status"] == "FILLED"] for br in ledgers}
        daily = {br: daily_series(filled[br], days) for br in ledgers}
        comps = {}
        for a, b in PAIRED:
            mask = unresolved_day_mask(filled[a], days) | unresolved_day_mask(filled[b], days)
            if mask.any():
                # Missing outcomes are not imputed as 0: no inferential p; descriptive diff on fully known days only.
                c = bootstrap_ci((daily[a] - daily[b])[~mask])
                c.update({"p_two_sided_bootstrap": None, "status": "INCONCLUSIVE_UNRESOLVED_OUTCOMES",
                          "scope": f"CONDITIONAL: {int((~mask).sum())} of {len(days)} days with complete outcomes in both branches"})
            else:
                c = bootstrap_ci(daily[a] - daily[b])
                c.update({"status": "OK", "scope": f"all {len(days)} calendar days"})
            comps[f"{a}-{b}"] = c
        adj = holm({k: v.get("p_two_sided_bootstrap") for k, v in comps.items()})
        for k in comps:
            comps[k]["p_holm"] = adj.get(k)
        out["results"][scen]["paired_daily_differences"] = comps
        pm = metrics([dict(r, status="FILLED") for r in pf["accepted"]], days, Counter())
        out["results"][scen]["portfolio"] = {"pair": pair, "counts": pf["counts"], "metrics": pm}
        out.setdefault("_ledgers", {})[scen] = ledgers
        progress(f"scenario {scen}: " + ", ".join(f"{br}={out['results'][scen][br]['n_fills']}f/{out['results'][scen][br]['net_R_total']:+.1f}R" for br in BRANCHES_A + BRANCHES_B))
    out["inference_method"] = dict(INFERENCE_METHOD, block_days=5, resamples=2000, seed=BOOT_SEED)
    out["calendar"] = {"policy": "WINDOW_WEEKDAYS_PLUS_EXIT_HORIZON (shared by all branches/scenarios/portfolio; zero days included)",
                       "window": [start.isoformat(), end.isoformat()], "n_days": len(days),
                       "extension_days": [d.isoformat() for d in ext]}
    out["evaluation_days"] = {"start": start.isoformat(), "end": end.isoformat(), "n": len(days),
                              "n_window_weekdays": len(trading_days(start, end)), "n_horizon_extension": len(ext)}
    return out
