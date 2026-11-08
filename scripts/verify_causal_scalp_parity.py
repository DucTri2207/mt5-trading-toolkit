"""Focused static parity gate for the deployed XAUUSD scalp preset."""

from __future__ import annotations

import json
import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MQL5 = (ROOT / "duc_tri_can_ho_tro_scalp.mq5").read_text(encoding="utf-8", errors="ignore")
PY = (ROOT / "scripts" / "backtest_causal_scalp.py").read_text(encoding="utf-8", errors="ignore")
CAND = (ROOT / "scripts" / "evaluate_causal_candidates.py").read_text(encoding="utf-8", errors="ignore")
SESSION = (ROOT / "scripts" / "evaluate_gold_scalp_session_filter.py").read_text(encoding="utf-8", errors="ignore")


def input_value(name: str) -> str | None:
    match = re.search(rf"input\s+[^;]*\b{name}\s*=\s*([^;]+);", MQL5)
    return match.group(1).strip() if match else None


checks = {
    "mql5_wick_50": input_value("WickRatioMin") == "0.50",
    "mql5_proximal": "SweepLevelMode  = SWEEP_PROXIMAL" in MQL5,
    "mql5_displacement_025": input_value("MinDisplacementATR") == "0.25",
    "mql5_h1_trend_on": input_value("UseHtfTrendFilter") == "true",
    "mql5_h1_distance_175": input_value("MaxHtfEmaDistanceATR") == "1.75",
    "mql5_h1_distance_causal": "distanceShift = iBarShift" in MQL5 and "CopyBuffer(g_htfAtrHandle" in MQL5,
    "mql5_killzone_on": input_value("FilterKillzones") == "true",
    "mql5_killzone_offset_default": input_value("KillzoneHourOffset") == "0",
    "mql5_weak_hours_filter": input_value("ExcludeWeakKzHours") == "true" and "h == 12 || h == 14" in MQL5,
    "mql5_structural_buffer_025": input_value("SlBufferATR") == "0.25",
    "mql5_max_risk_20": input_value("MaxSlPips") == "200.0",
    "mql5_min_risk_2": input_value("MinSlPips") == "20.0",
    "mql5_tp_scalp": "InpTpMode        = TP_MODE_SCALP" in MQL5,
    "mql5_tp_05": input_value("InpTp1RR") == "0.5",
    "mql5_be_off": input_value("InpUseAutoBE") == "false",
    "python_post_sweep_pivot": "def find_post_pivot" in PY,
    "python_structural_min_risk": "if risk < cfg.min_risk:" in PY,
    "candidate_wick_50": "proxy_w50_max20_tp05" in CAND,
    "candidate_max_risk_20": "maxrisk=20.0" in CAND,
    "candidate_target_05": "target=.5" in CAND,
    "candidate_nonoverlap": "last_exit" in CAND,
    "session_filter_replay": "exclude_12_14" in SESSION,
}

failed = [name for name, ok in checks.items() if not ok]
result = {"passed": len(checks) - len(failed), "failed": len(failed), "checks": checks}
out = ROOT / "reports" / "causal_scalp_parity_20261024.json"
out.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
print(json.dumps(result, ensure_ascii=False))
raise SystemExit(1 if failed else 0)
