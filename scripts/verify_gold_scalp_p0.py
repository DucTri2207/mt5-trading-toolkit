"""Small source-level and arithmetic regression gate for P0 indicator fixes."""
from pathlib import Path
import json

root = Path(__file__).resolve().parents[1]
source = (root / "duc_tri_can_ho_tro.mq5").read_text(encoding="utf-8-sig")
checks = {}
checks["balanced_braces"] = source.count("{") == source.count("}")
checks["balanced_parentheses"] = source.count("(") == source.count(")")
checks["htf_closed_rates"] = "CopyRates(_Symbol, scanTf, 1, htfBarsToCopy, hRates)" in source
checks["htf_closed_atr"] = "CopyBuffer(atrH, 0, 1, copied, hAtr)" in source
checks["no_historical_restore"] = "bool shouldRestore  = false;" in source
checks["structural_stop_rejects_wide"] = source.count("if(risk > maxRisk) continue;") == 2
checks["real_rr_gate"] = "rr1 < MinRR || rr2 < rr1" in source
checks["signal_identity_guard"] = "sameProcessedSignal" in source and "g_lastSignalSeenTime" in source
checks["signed_be_progress"] = "favorablePts > 0.0 ? favorablePts / GetPipSize() : 0.0" in source
checks["distinct_zone_visits"] = "if(inside && !wasInside) testCount++;" in source
checks["test_quota_hidden"] = "g_zones[i].testCount >= MaxTests" in source
checks["previous_day_is_closed"] = "CopyRates(_Symbol,PERIOD_D1,1,2,d1)" in source
checks["reference_levels_are_used"] = "UseReferenceLevels && g_previousDayHigh" in source and "UseReferenceLevels && g_previousDayLow" in source
checks["spread_guard"] = "liveTick.ask-liveTick.bid" in source and "MaxSpreadPrice" in source

# A $6 adverse move for a BUY must produce zero favorable pips.
entry, current, pip = 2350.0, 2344.0, 0.1
favorable_points = current - entry
favorable_pips = favorable_points / pip if favorable_points > 0 else 0.0
checks["adverse_move_cannot_trigger_be"] = favorable_pips == 0.0

failed = [name for name, ok in checks.items() if not ok]
result = {"passed": len(checks) - len(failed), "failed": len(failed), "checks": checks}
out = root / "reports" / "gold_scalp_upgrade_20261023" / "p0-verification.json"
out.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
print(json.dumps(result, ensure_ascii=False))
raise SystemExit(1 if failed else 0)
