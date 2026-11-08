"""Write an evaluate run: RESULTS.json (all scenarios), headline ledgers (JSONL), REPORT.md (human view)."""
from __future__ import annotations

from pathlib import Path

from .util import STORE_DIR, atomic_write_json, atomic_write_text, canonical_json, iso_utc, now_utc, sha256_file, stable_id

BR = ("M0", "M1", "M2", "P0", "P1", "P2")


def _f(x, nd=3):
    if x is None:
        return "—"
    if isinstance(x, float):
        return f"{x:+.{nd}f}" if abs(x) < 1e6 else f"{x:.3g}"
    return str(x)


def write_run(exp: dict, res: dict, log: list[str]) -> Path:
    # Data versions are part of the run identity: new/changed data must never reuse (and overwrite) an older run.
    run_id = stable_id("RUN", exp["experiment_id"], res["engine_hash"], res["config_hash"], res.get("data_versions"))
    d = STORE_DIR / "runs" / run_id
    d.mkdir(parents=True, exist_ok=True)
    ledgers = res.pop("_ledgers", {})
    res["run_id"] = run_id
    res["generated_at"] = iso_utc(now_utc())
    res["experiment_registered_at"] = exp["registered_at"]
    atomic_write_json(d / "RESULTS.json", res)
    head = f"{exp['headline']['latency']}/{exp['headline']['cost']}"
    files = {"RESULTS.json": None}
    for scen in (head, "MANUAL/BASE"):
        if scen in ledgers:
            name = f"ledger_{scen.replace('/', '_')}.jsonl"
            lines = []
            for br, led in ledgers[scen].items():
                for r in led:
                    lines.append(canonical_json(dict(r, branch=br)))
            atomic_write_text(d / name, "\n".join(lines) + "\n")
            files[name] = None
    atomic_write_text(d / "run.log", "\n".join(log) + "\n")
    md = _markdown(exp, res, head)
    atomic_write_text(d / "REPORT.md", md)
    files.update({"run.log": None, "REPORT.md": None})
    atomic_write_json(d / "MANIFEST.json", {"run_id": run_id, "experiment_id": exp["experiment_id"],
                                            "files": {k: sha256_file(d / k) for k in files}})
    return d


def _markdown(exp: dict, res: dict, head: str) -> str:
    L = [f"# Run {res['run_id']} — {exp['name']}", "",
         f"- Experiment `{exp['experiment_id']}` registered {exp['registered_at']}; run generated {res['generated_at']}.",
         f"- Engine {res['engine_version']} hash `{res['engine_hash'][:16]}…`, config hash `{res['config_hash'][:16]}…`, strategy {res['strategy_version']}.",
         f"- Window {res['evaluation_days']['start']} → {res['evaluation_days']['end']} ({res['evaluation_days']['n']} NY session days, zero days included).",
         f"- Calendar: {(res.get('calendar') or {}).get('policy', 'window weekdays')}; horizon extension days: {(res.get('calendar') or {}).get('extension_days', [])}.",
         "- Verdicts: INCONCLUSIVE_UNRESOLVED_OUTCOMES whenever any filled trade has no known outcome (never imputed as 0R); INCONCLUSIVE_THIN_SAMPLE below the provisional floor (not a sample-size certification).",
         "- **Exposure: HISTORICAL_EXPOSED** — every symbol-year was used by earlier research; this is not final OOS.",
         "- **Quote model: M1_OPEN_PROXY** (no tick tape). Costs ASSUMED (config/cost_profiles.json). Clock: legacy-cache hypothesis EET_EU applied (ASSUMED; SOURCE_CONFLICT:TIME_BASIS with recorded source basis; TIME_UNVERIFIED) — session-dependent rows are conditional.", "",
         "## Catalog", "", "| Symbol | raw candidates | episodes A | execution |", "|---|---:|---:|---|"]
    for s, v in res["symbols"].items():
        L.append(f"| {s} | {v['raw_candidates']} | {v['episodes']} | {v['execution_model']}{' — ' + v['execution_block_reason'] if v['execution_block_reason'] else ''} |")
    L += ["", "Gate outcomes per branch on the shared catalog:", ""]
    for s, v in res["symbols"].items():
        L.append(f"- {s}: " + "; ".join(f"{br} {v['gate_counts'][br]}" for br in BR))
    if "data_versions" in res:
        L += ["", "## Data versions", ""]
        for s, tfs in sorted(res["data_versions"].items()):
            if isinstance(tfs, dict) and "error" in tfs:
                L.append(f"- {s}: error: {tfs['error']}")
            elif isinstance(tfs, dict):
                items = []
                for tf, v in sorted(tfs.items()):
                    h = (v.get("content_hash") or v.get("sha256") or v.get("read_contract_hash")) if isinstance(v, dict) else None
                    if h:
                        short = f"`{h[:16]}…`" if len(h) > 16 else f"`{h}`"
                        items.append(f"{tf} {short}")
                    elif isinstance(v, dict) and "error" in v:
                        items.append(f"{tf} error: {v['error']}")
                    else:
                        items.append(f"{tf} {v}")
                L.append(f"- {s}: " + (", ".join(items) if items else "none"))
            else:
                L.append(f"- {s}: {tfs}")
    for scen, r in res["results"].items():
        L += ["", f"## Scenario {scen}" + (" (headline, declared before running)" if scen == head else ""), "",
              "| Branch | fills | unres. | fills/wk | net R | exp R/trade | win | mean daily R [95% CI] | maxDD R | worst day | amb. | verdict |",
              "|---|---:|---:|---:|---:|---:|---|---:|---:|---:|---|---|"]
        for br in BR:
            m = r[br]
            ci = m["mean_daily_R"]
            win = "—" if m["win_rate"] is None else f"{m['win_rate']:.2f}"
            L.append(f"| {br} | {m['n_fills']} | {m.get('n_fills_unresolved', 0)} | {m['fills_per_week']:.2f} | {_f(m['net_R_total'], 1)} | {_f(m['expectancy_R_per_trade'])} | "
                     f"{win} | "
                     f"{_f(ci['mean'], 4)} [{_f(ci['ci95'][0], 4)}, {_f(ci['ci95'][1], 4)}] | {_f(m['max_drawdown_R_closed'], 1)} | "
                     f"{_f(m['worst_day_R'], 1)} | {m['ambiguous_sl_tp']['n']} | {m['verdict']} |")
        L += ["", "Paired daily differences (null-centred moving-block bootstrap, MC-corrected two-sided p, Holm over the 4 declared comparisons; a comparison with unresolved outcomes has no p and counts as p=1 in the family):", ""]
        for k, v in r["paired_daily_differences"].items():
            L.append(f"- {k}: mean {_f(v['mean'], 4)} R/day, 95% CI [{_f(v['ci95'][0], 4)}, {_f(v['ci95'][1], 4)}], p_boot {_f(v.get('p_two_sided_bootstrap'))}, p_holm {_f(v.get('p_holm'))}"
                     f" — {v.get('status', '')} ({v.get('scope', '')})")
        pf = r["portfolio"]
        pm = pf["metrics"]
        L += ["", f"Portfolio {pf['pair']} (EXPLORATORY): accepted {pf['counts']['accepted']} of {pf['counts']['pool']}, "
                  f"rejected {pf['counts']['rejected']}, dropped {pf['counts']['dropped']}; net R {_f(pm['net_R_total'], 1)}, "
                  f"mean daily R {_f(pm['mean_daily_R']['mean'], 4)} [{_f(pm['mean_daily_R']['ci95'][0], 4)}, {_f(pm['mean_daily_R']['ci95'][1], 4)}], "
                  f"maxDD {_f(pm['max_drawdown_R_closed'], 1)} R, verdict {pm['verdict']}."]
    hb = res["results"][head]
    L += ["", "## Headline detail", ""]
    for br in BR:
        m = hb[br]
        L.append(f"- **{br}** blocked/exec: {m['exec_counts']}; exits {m['exit_reasons']}; cost/R {_f(m['cost_over_R_mean'])}; "
                 f"MAE {_f(m['mae_R_mean'])} MFE {_f(m['mfe_R_mean'])}; hold {_f(m['hold_minutes_mean'], 1)} min; "
                 f"ambiguity: adverse-first {_f(m['ambiguous_sl_tp']['net_R_total_adverse_first'], 1)} vs favourable-first {_f(m['ambiguous_sl_tp']['net_R_total_favorable_first'], 1)} R; "
                 f"top-5-day share {_f(m['top5_days_share_of_positive_R'])}")
        L.append(f"  - by year: " + ", ".join(f"{y}: n={v['n']} {v['net_R']:+.1f}R" for y, v in sorted(m["by_year"].items())))
        L.append(f"  - by side: " + ", ".join(f"{y}: n={v['n']} {v['net_R']:+.1f}R" for y, v in sorted(m["by_side"].items())))
        L.append(f"  - by NY bucket: " + ", ".join(f"{y}: n={v['n']} {v['net_R']:+.1f}R" for y, v in sorted(m["by_ny_bucket"].items())))
    L += ["", "## Reading rules", "",
          "- Verdicts are per strategy+config+symbol+cost/latency profile. `POSITIVE_CI_ON_EXPOSED_HISTORY` is at most HISTORICAL_PROMISING; nothing here is FORWARD_SUPPORTED.",
          "- BASE and MANUAL latency collapse to the same M1 open under the proxy; SLOW (60 s) cannot meet the 90 s deadline with minute-open quotes, so SLOW = data limitation, not a strategy result.",
          "- Ambiguous SL/TP minutes use adverse-first in the headline; favourable-first is sensitivity only."]
    return "\n".join(L) + "\n"
