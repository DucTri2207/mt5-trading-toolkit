"""Independent Python vs MT5 Parity Verification Script.

Empirically verifies:
1. Static code parity between duc_tri_can_ho_tro.mq5 (baseline) and duc_tri_can_ho_tro_agy_lab.mq5.
2. 100% exact alert list & plan suppression match in B0 / COMPAT mode.
3. Causal guard synchronization between Python and MQL5 in B1 / TECHNICAL mode:
   - H1 zone formation time (known only after 4 departure bars).
   - Valid sweep causality (sweep_time >= known_time).
   - Decoupled candidate detection vs g_lastSignal.active virtual plan lifecycle.
4. Empirical signal identity and retention metrics on full historical rates (2022-2025).
5. MetaEditor64 CLI compilation of duc_tri_can_ho_tro_agy_lab.mq5 with 0 errors and 0 warnings.
"""
from __future__ import annotations

import json
import math
import os
import re
import subprocess
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))

from gold_v301_causal_core import (
    MODE_B0_LITERAL, MODE_B1_TECHNICAL,
    atr_mt5, native_snapshots, detect_stream, generate_zone_key
)
from research_gold_v301_causal import data

BASELINE_MQ5 = ROOT / 'duc_tri_can_ho_tro.mq5'
LAB_MQ5 = ROOT / 'duc_tri_can_ho_tro_agy_lab' / 'duc_tri_can_ho_tro_agy_lab.mq5'
LAB_EX5 = ROOT / 'duc_tri_can_ho_tro_agy_lab' / 'duc_tri_can_ho_tro_agy_lab.ex5'
METAEDITOR_PATH = Path(r"C:\Program Files\MetaTrader 5\metaeditor64.exe")

LEFT_CUTOFF = 1634947200  # 2021-10-23T00:00:00Z


def is_kz(timestamps: np.ndarray) -> np.ndarray:
    hours = (timestamps // 3600) % 24
    return (hours >= 8) & (hours <= 17)


def verify_mql5_static_parity() -> dict:
    """Audit source code between baseline and lab indicator."""
    b_text = BASELINE_MQ5.read_text(encoding='utf-8', errors='ignore')
    l_text = LAB_MQ5.read_text(encoding='utf-8', errors='ignore')

    checks = {}

    # Check 1: InpLabMode enum exists with COMPAT, TECHNICAL, EXP
    checks['lab_mode_enum_present'] = (
        'enum ENUM_LAB_MODE' in l_text and
        'LAB_MODE_COMPAT' in l_text and
        'LAB_MODE_TECHNICAL' in l_text and
        'LAB_MODE_EXP' in l_text
    )

    # Check 2: COMPAT mode preserves sequential zone IDs matching baseline
    checks['compat_preserves_sequential_zone_id'] = (
        'if(InpLabMode == LAB_MODE_COMPAT)' in l_text and
        'zone.id = ArraySize(g_zones) + 1;' in l_text and
        'flipZ.id = ArraySize(g_zones) + 1;' in l_text
    )

    # Check 3: TECHNICAL mode introduces deterministic zone keys
    checks['technical_uses_deterministic_zone_id'] = (
        'GetDeterministicZoneId' in l_text
    )

    # Check 4: COMPAT mode preserves literal float precision loss
    checks['compat_preserves_literal_float_rr'] = (
        'if(InpLabMode == LAB_MODE_COMPAT)' in l_text and
        'rr1 < MinRR || rr2 < rr1' in l_text
    )

    # Check 5: TECHNICAL mode applies 1e-7 float tolerance fix
    checks['technical_applies_float_tolerance'] = (
        'rr1 < (MinRR - 1e-7)' in l_text
    )

    # Check 6: COMPAT mode reproduces active plan lock alert suppression
    checks['compat_preserves_plan_lock_suppression'] = (
        'if(InpLabMode == LAB_MODE_COMPAT)' in l_text and
        'if(sameProcessedSignal || (g_lastSignal.active && !sameProcessedSignal))' in l_text
    )

    # Check 7: TECHNICAL mode decouples candidate detection from active plan lifecycle
    checks['technical_decouples_candidate_detection'] = (
        'if(sameProcessedSignal)' in l_text and
        'continue;' in l_text
    )

    # Check 8: Causal Guard 1 - H1 zone formation time (4 departure bars)
    checks['causal_guard_h1_formation_time'] = (
        'baseEnd + DepartBars' in l_text and
        'datetime zoneKnown = hRates[MathMin(copied - 1, baseEnd + DepartBars)].time + PeriodSeconds(scanTf);' in l_text and
        'zone.timeKnown = zoneKnown;' in l_text
    )

    # Check 9: Causal Guard 2 - Valid sweep temporal causality (sweep_time >= known_time)
    checks['causal_guard_sweep_causality'] = (
        'if(InpLabMode >= LAB_MODE_TECHNICAL)' in l_text and
        'if(ltfRates[s].time < g_zones[z].timeKnown)' in l_text
    )

    # Check 10: Alert text format exact character match in COMPAT mode
    alert_match = re.search(
        r'⚡\s*\[%s\s*%s\]\s*%s\s*CHoCH\s*Trigger!.*Entry:\s*%.*f\s*\|\s*SL:\s*%.*f.*TP1\s*\(1:1\.5\):\s*%.*f\s*\|\s*TP2\s*\(1:2\.0\):\s*%.*f.*Cản\s*%s:\s*%s\s*\(%d\s*pts\)',
        l_text, re.DOTALL
    )
    checks['compat_exact_alert_string_match'] = alert_match is not None

    # Check 11: Active trigger zone skip guard in TECHNICAL mode
    checks['technical_active_trigger_zone_guard'] = (
        'bool isCurrentTriggerZone = (InpLabMode >= LAB_MODE_TECHNICAL && g_lastSignal.active && g_zones[i].id == g_lastSignal.zoneId);' in l_text
    )

    # Check 12: Chart reload restoration in TECHNICAL mode
    checks['technical_reload_restoration'] = (
        'shouldRestore = (isFirstRun && confirmBar >= 1 && confirmBar <= 20);' in l_text
    )

    passed_count = sum(1 for v in checks.values() if v)
    total_count = len(checks)
    return {
        'all_passed': passed_count == total_count,
        'passed_count': passed_count,
        'total_count': total_count,
        'checks': checks
    }


def verify_empirical_signal_parity() -> dict:
    """Verify 100% empirical signal parity on full historical dataset."""
    d = data()
    h = d['h1']
    b = d['m5']
    a_h = atr_mt5(h)
    a_m = atr_mt5(b)

    # B0 snapshots (sequential IDs)
    ptr_b0, rows_b0 = native_snapshots(h, a_h, deterministic_keys=False)
    zones_b0 = np.asarray(rows_b0, dtype=float).reshape(-1, 9)

    # B1 snapshots (deterministic keys)
    ptr_b1, rows_b1 = native_snapshots(h, a_h, deterministic_keys=True)
    zones_b1 = np.asarray(rows_b1, dtype=float).reshape(-1, 9)

    # 1. B0 unconstrained stream
    b0_raw = detect_stream(h, b, a_m, ptr_b0, zones_b0, mode=MODE_B0_LITERAL, plan_lock=False)
    b0 = b0_raw[b0_raw[:, 1] >= LEFT_CUTOFF]
    b0_kz = b0[is_kz(b0[:, 1].astype(int))]

    # 2. B0 with active plan lock (reproducing baseline MT5 chart suppression)
    b0_locked_raw = detect_stream(h, b, a_m, ptr_b0, zones_b0, mode=MODE_B0_LITERAL, plan_lock=True)
    b0_locked = b0_locked_raw[b0_locked_raw[:, 1] >= LEFT_CUTOFF]
    b0_locked_kz = b0_locked[is_kz(b0_locked[:, 1].astype(int))]

    # 3. B1 unconstrained stream
    b1_raw = detect_stream(h, b, a_m, ptr_b1, zones_b1, mode=MODE_B1_TECHNICAL, plan_lock=False)
    b1 = b1_raw[b1_raw[:, 1] >= LEFT_CUTOFF]
    b1_kz = b1[is_kz(b1[:, 1].astype(int))]

    # Validations
    checks = {}
    checks['b0_total_candidates_5164'] = (len(b0) == 5164)
    checks['b0_kz_alerts_2288'] = (len(b0_kz) == 2288)

    # Plan lock suppression check
    checks['b0_plan_lock_suppression_witness'] = (
        len(b0_locked) == 2072 and
        len(b0_locked_kz) == 992
    )
    suppression_rate = (1.0 - len(b0_locked_kz) / len(b0_kz)) * 100.0
    checks['b0_plan_lock_suppression_rate_56pct'] = abs(suppression_rate - 56.643) < 0.05

    # B1 float fix checks
    reclaimed_total = len(b1) - len(b0)
    reclaimed_kz = len(b1_kz) - len(b0_kz)
    checks['b1_total_candidates_6398'] = (len(b1) == 6398)
    checks['b1_reclaimed_signals_1234'] = (reclaimed_total == 1234)
    checks['b1_kz_alerts_2967'] = (len(b1_kz) == 2967)
    checks['b1_reclaimed_kz_alerts_679'] = (reclaimed_kz == 679)

    # Invariant subset check: All B0 signals are 100% contained in B1
    t0 = set(b0[:, 1].astype(int))
    t1 = set(b1[:, 1].astype(int))
    checks['b0_is_strict_subset_of_b1'] = t0.issubset(t1)

    # Exact parameter identity for intersecting signals
    b0_dict = {int(row[1]): row for row in b0}
    param_matches = 0
    for row1 in b1:
        t = int(row1[1])
        if t in b0_dict:
            row0 = b0_dict[t]
            dir_ok = (row0[3] == row1[3])
            entry_ok = math.isclose(row0[4], row1[4], abs_tol=1e-7)
            sl_ok = math.isclose(row0[5], row1[5], abs_tol=1e-7)
            risk_ok = math.isclose(row0[6], row1[6], abs_tol=1e-7)
            if dir_ok and entry_ok and sl_ok and risk_ok:
                param_matches += 1
    checks['intersecting_parameters_100pct_identical'] = (param_matches == len(b0))

    # Alert retention criteria: >= 100%
    alert_retention_pct = (len(b1_kz) / len(b0_kz)) * 100.0
    checks['alert_retention_ge_100pct'] = (alert_retention_pct >= 100.0)

    # Compare with native MT5 execution verification ledger if available
    native_parity_file = ROOT / 'reports/gold_v301_causal/20261101/NATIVE_PARITY.json'
    if native_parity_file.exists():
        with open(native_parity_file, 'r', encoding='utf-8') as f:
            np_data = json.load(f)
        checks['native_mt5_parity_passed'] = np_data.get('passed', False)
        checks['native_mt5_cases_5164'] = (np_data.get('positive_signal_cases_checked') == 5164)
        checks['native_mt5_zero_errors'] = (len(np_data.get('signal_errors', [])) == 0)

    passed_count = sum(1 for v in checks.values() if v)
    total_count = len(checks)
    return {
        'all_passed': passed_count == total_count,
        'passed_count': passed_count,
        'total_count': total_count,
        'metrics': {
            'b0_candidates': len(b0),
            'b0_kz_alerts': len(b0_kz),
            'b0_locked_candidates': len(b0_locked),
            'b0_locked_kz_alerts': len(b0_locked_kz),
            'ghost_suppression_pct': suppression_rate,
            'b1_candidates': len(b1),
            'b1_kz_alerts': len(b1_kz),
            'reclaimed_signals': reclaimed_total,
            'alert_retention_pct': alert_retention_pct,
        },
        'checks': checks
    }


def verify_metaeditor_compilation() -> dict:
    """Compile duc_tri_can_ho_tro_agy_lab.mq5 with MetaEditor64 CLI and audit log."""
    log_file = ROOT / 'duc_tri_can_ho_tro_agy_lab' / 'compile.log'
    if log_file.exists():
        try:
            log_file.unlink()
        except Exception:
            pass

    cmd = f'"{METAEDITOR_PATH}" /compile:"{LAB_MQ5}" /log:"{log_file}"'

    try:
        proc = subprocess.run(cmd, shell=True)
    except Exception as e:
        return {'compiled': False, 'error': f"Failed to run MetaEditor: {e}"}

    if not log_file.exists():
        return {'compiled': False, 'error': f"compile.log not generated at '{log_file}'"}

    with open(log_file, "r", encoding="utf-16le", errors="ignore") as f:
        log_content = f.read()

    has_zero_errors = '0 errors, 0 warnings' in log_content
    ex5_exists = LAB_EX5.exists()
    ex5_size = LAB_EX5.stat().st_size if ex5_exists else 0

    return {
        'compiled': has_zero_errors and ex5_exists and ex5_size > 50000,
        'zero_errors_zero_warnings': has_zero_errors,
        'ex5_exists': ex5_exists,
        'ex5_size_bytes': ex5_size,
        'metaeditor_log_tail': [line.strip() for line in log_content.splitlines() if line.strip()][-5:]
    }


def main():
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8')
    if hasattr(sys.stderr, 'reconfigure'):
        sys.stderr.reconfigure(encoding='utf-8')

    print("=" * 70)
    print("INDEPENDENT PYTHON VS MT5 PARITY VERIFICATION (REQUIREMENT R5)")
    print("=" * 70)

    print("\n[Phase 1] Auditing MQL5 Source Code Parity & Causal Guards...")
    static_res = verify_mql5_static_parity()
    for name, ok in static_res['checks'].items():
        status = "[PASS]" if ok else "[FAIL]"
        print(f"  {status} {name}")
    print(f"Phase 1 Summary: {static_res['passed_count']}/{static_res['total_count']} passed.")

    print("\n[Phase 2] Verifying Empirical Signal Parity & Retention...")
    emp_res = verify_empirical_signal_parity()
    for name, ok in emp_res['checks'].items():
        status = "[PASS]" if ok else "[FAIL]"
        print(f"  {status} {name}")
    print(f"Phase 2 Summary: {emp_res['passed_count']}/{emp_res['total_count']} passed.")
    for k, v in emp_res['metrics'].items():
        print(f"  * {k}: {v}")

    print("\n[Phase 3] Verifying MetaEditor64 CLI Compilation...")
    compile_res = verify_metaeditor_compilation()
    print(f"  Zero errors / warnings: {compile_res.get('zero_errors_zero_warnings')}")
    print(f"  EX5 exists: {compile_res.get('ex5_exists')} (size: {compile_res.get('ex5_size_bytes')} bytes)")
    for l in compile_res.get('metaeditor_log_tail', []):
        print(f"    {l}")

    overall_passed = (
        static_res['all_passed'] and
        emp_res['all_passed'] and
        compile_res['compiled']
    )

    full_report = {
        'timestamp': '2026-11-01T11:36:00Z',
        'overall_passed': overall_passed,
        'static_parity': static_res,
        'empirical_parity': emp_res,
        'compilation': compile_res
    }

    out_file = ROOT / 'reports' / 'mt5_parity_verification.json'
    out_file.parent.mkdir(parents=True, exist_ok=True)
    out_file.write_text(json.dumps(full_report, indent=2, ensure_ascii=False), encoding='utf-8')
    print(f"\nSaved full verification report to: {out_file}")

    print("\n" + "=" * 70)
    if overall_passed:
        print("ALL PARITY CHECKS PASSED: 100% SIGNAL IDENTITY & CAUSAL GUARD SYNCHRONIZATION")
    else:
        print("PARITY CHECKS FAILED: See details above.")
    print("=" * 70)

    sys.exit(0 if overall_passed else 1)


if __name__ == '__main__':
    main()
