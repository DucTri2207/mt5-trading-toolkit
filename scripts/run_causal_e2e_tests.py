#!/usr/bin/env python3
"""Master Test Orchestrator & E2E Test Runner for Cản Hỗ Trợ Simulation Overhaul.

Usage:
    python scripts/run_causal_e2e_tests.py [--all] [--tier 1|2|3|4] [--verbose] [--audit-core] [--json]

Options:
    --all           Run all 4 tiers of E2E causal tests (default).
    --tier N        Run only tests belonging to Tier N (1, 2, 3, or 4).
    --verbose, -v   Show detailed test execution log.
    --audit-core    Probe live scripts/gold_v301_causal_core.py against the 4 audited defects.
    --json          Output structured JSON test execution report.
"""
import argparse
import io
import json
import os
import sys
import time
import unittest
from pathlib import Path

# Safe stdout encoding on Windows
if hasattr(sys.stdout, 'reconfigure'):
    try:
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    except Exception:
        pass

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'scripts'))
sys.path.insert(0, str(ROOT / 'tests'))

from test_causal_e2e_v2 import (
    TestTier1FeatureCoverage,
    TestTier2BoundariesAndCornerCases,
    TestTier3CrossFeatureCombinations,
    TestTier4RealWorldWitnessReplay,
)


TIER_MAP = {
    1: ('Tier 1: Feature Coverage', TestTier1FeatureCoverage),
    2: ('Tier 2: Boundary & Corner Cases', TestTier2BoundariesAndCornerCases),
    3: ('Tier 3: Cross-Feature Combinations', TestTier3CrossFeatureCombinations),
    4: ('Tier 4: Real-World Application & Witness Replay', TestTier4RealWorldWitnessReplay),
}


def run_tier(tier_num, test_case_class, verbose=False):
    """Execute all tests in a specific test class and collect metrics."""
    suite = unittest.defaultTestLoader.loadTestsFromTestCase(test_case_class)
    stream = io.StringIO()
    runner = unittest.TextTestRunner(stream=stream, verbosity=2 if verbose else 1)
    
    start_time = time.perf_counter()
    result = runner.run(suite)
    elapsed = time.perf_counter() - start_time
    
    return {
        'tier': tier_num,
        'name': TIER_MAP[tier_num][0],
        'total': result.testsRun,
        'passed': result.testsRun - len(result.failures) - len(result.errors),
        'failed': len(result.failures),
        'errored': len(result.errors),
        'elapsed_seconds': round(elapsed, 4),
        'failures': [str(f[0]) for f in result.failures],
        'errors': [str(e[0]) for e in result.errors],
        'raw_output': stream.getvalue()
    }


def audit_live_core():
    """Probe live scripts/gold_v301_causal_core.py directly against the 4 audited defects."""
    import numpy as np
    try:
        import gold_v301_causal_core as core
    except Exception as exc:
        return {'status': 'ERROR', 'error': str(exc), 'probes': []}
    
    probes = []
    
    # Probe 1: BUG-01 Lookahead bias in simulate_h2_entry
    # Check if entry_time is taken from confirm_bar_open or signal_known_time
    candidate_1 = {
        'signal_id': '1', 'time_m5': 1635325800, 'confirm_bar_open': 1635325800,
        'signal_known_time': 1635326100, 'direction': 1, 'sl_price': 1785.2776,
        'choch_level': 1787.97, 'entry_market': 1788.0, 'risk': 2.7224
    }
    m1_pre = np.array([[1635325800.0, 1786.84, 1786.99, 1786.79, 1786.94]])
    try:
        res1 = core.simulate_h2_entry(candidate_1, m1_pre, spread=0.30)
        # Old bug: res1['filled'] is True or checks m1_pre at 1635325800
        # If filled is False because of no touch, but let's check if it accepts pre-known bars:
        probe1_fixed = not res1.get('filled', False) and res1.get('cancel_reason') != "SL_HIT_BEFORE_FILL"
    except Exception as e:
        probe1_fixed = False
    probes.append({
        'defect': 'BUG-01: Lookahead Bias t0',
        'description': 'H2 filled before signal_known_time (1635326100 vs 1635325800)',
        'fixed': probe1_fixed,
        'recommendation': 'Enforce signal_known_time = confirm_bar_open + 300s; reject pre-known quotes.'
    })

    # Probe 2: BUG-02 Erased filled loss (simulate_h2_entry)
    candidate_2 = {
        'time_m5': 1500000, 'confirm_bar_open': 1500000, 'signal_known_time': 1500000,
        'direction': 1, 'sl_price': 1996.0, 'choch_level': 2000.0,
        'entry_market': 2002.0, 'risk': 6.0
    }
    m1_ohlc = np.array([[1500000.0, 2001.0, 2002.0, 1995.0, 1997.0]])
    try:
        res2 = core.simulate_h2_entry(candidate_2, m1_ohlc, spread=0.30)
        # Buggy code returns cancelled=True, cancel_reason='SL_HIT_BEFORE_FILL'
        probe2_fixed = res2.get('filled', False) and res2.get('entry_type') == 'LIMIT'
    except Exception:
        probe2_fixed = False
    probes.append({
        'defect': 'BUG-02: Erased Filled Loss',
        'description': 'Price touch of Limit before SL erroneously cancelled as SL_HIT_BEFORE_FILL',
        'fixed': probe2_fixed,
        'recommendation': 'Evaluate limit fill before SL when bar open is above limit on descent.'
    })

    # Probe 3: BUG-04 Short false TP (simulate_1r_trade)
    m5_bars = np.array([[1500300, 1998.0, 1998.5, 1995.9, 1997.0]])
    try:
        res3 = core.simulate_1r_trade(
            entry_price=2000.0, sl_price=2004.0, direction=-1,
            fill_time=1500300, t0=1500300, m5_bars=m5_bars, m5_start_idx=0
        )
        # Buggy code checks b_low <= tp_price -> exit_reason='TP'
        probe3_fixed = res3.get('exit_reason') != 'TP'
    except Exception:
        probe3_fixed = False
    probes.append({
        'defect': 'BUG-04: Short False TP',
        'description': 'SELL TP triggered on Bid (1995.90) while Ask (1996.20) remained above TP (1996.00)',
        'fixed': probe3_fixed,
        'recommendation': 'Verify SELL TP condition on Ask side (low + spread <= TP).'
    })

    # Probe 4: BUG-05 Fee double deduction (simulate_1r_trade)
    try:
        res4 = core.simulate_1r_trade(
            entry_price=2000.31, sl_price=1995.0, direction=1,
            fill_time=1500300, t0=1500300, m5_bars=m5_bars, m5_start_idx=0, schedule='BASE'
        )
        gross = res4.get('gross_pnl_usd', 0)
        net = res4.get('net_pnl_usd', 0)
        comm = res4.get('commission_usd', 0.07)
        probe4_fixed = abs(net - (gross - comm)) < 1e-4
    except Exception:
        probe4_fixed = False
    probes.append({
        'defect': 'BUG-05: Double Fee Deduction',
        'description': 'Deducting spread and slip twice when execution prices already include costs',
        'fixed': probe4_fixed,
        'recommendation': 'Compute Net P&L = Gross P&L - Commission.'
    })

    return {'status': 'OK', 'probes': probes}


def main():
    parser = argparse.ArgumentParser(description="Master E2E Test Runner for Cản Hỗ Trợ Overhaul")
    parser.add_argument('--all', action='store_true', help="Run all 4 testing tiers")
    parser.add_argument('--tier', type=int, choices=[1, 2, 3, 4], help="Run specific tier (1 to 4)")
    parser.add_argument('--verbose', '-v', action='store_true', help="Verbose test runner output")
    parser.add_argument('--audit-core', action='store_true', help="Probe live gold_v301_causal_core.py")
    parser.add_argument('--json', action='store_true', help="Output summary in JSON format")
    args = parser.parse_args()

    # Determine tiers to execute
    if args.tier:
        selected_tiers = [args.tier]
    else:
        selected_tiers = [1, 2, 3, 4]

    results = []
    for t in selected_tiers:
        tier_info = TIER_MAP[t]
        res = run_tier(t, tier_info[1], verbose=args.verbose)
        results.append(res)

    total_tests = sum(r['total'] for r in results)
    total_passed = sum(r['passed'] for r in results)
    total_failed = sum(r['failed'] for r in results)
    total_errored = sum(r['errored'] for r in results)
    total_time = sum(r['elapsed_seconds'] for r in results)
    pass_rate = (total_passed / total_tests * 100) if total_tests > 0 else 0.0

    audit_report = audit_live_core() if args.audit_core else None

    if args.json:
        output_payload = {
            'timestamp': time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            'summary': {
                'total': total_tests,
                'passed': total_passed,
                'failed': total_failed,
                'errored': total_errored,
                'pass_rate_percent': round(pass_rate, 2),
                'total_elapsed_seconds': round(total_time, 4)
            },
            'tiers': results,
            'core_audit': audit_report
        }
        print(json.dumps(output_payload, indent=2))
        sys.exit(0 if (total_failed == 0 and total_errored == 0) else 1)

    # Pretty Terminal Presentation
    print("\n" + "=" * 80)
    print(" CAN HO TRO CAUSAL SIMULATION E2E TEST SUITE RUNNER (RUN 20261101_AGY_LAB_V2)")
    print("=" * 80)
    print(f"{'Tier / Test Suite':<48} | {'Total':<6} | {'Pass':<6} | {'Fail':<6} | {'Time (s)':<8}")
    print("-" * 80)
    for r in results:
        status_flag = "[PASS]" if (r['failed'] == 0 and r['errored'] == 0) else "[FAIL]"
        print(f"{status_flag} {r['name']:<41} | {r['total']:<6} | {r['passed']:<6} | {r['failed']+r['errored']:<6} | {r['elapsed_seconds']:<8.4f}")
    print("-" * 80)
    print(f"{'OVERALL TOTAL':<48} | {total_tests:<6} | {total_passed:<6} | {total_failed+total_errored:<6} | {total_time:<8.4f}")
    print(f"Pass Rate: {pass_rate:.2f}%\n")

    if args.audit_core and audit_report:
        print("=" * 80)
        print(" LIVE CAUSAL CORE (scripts/gold_v301_causal_core.py) DEFECT AUDIT")
        print("=" * 80)
        for p in audit_report['probes']:
            status_str = "[FIXED]" if p['fixed'] else "[OPEN DEFECT - ESCALATED]"
            print(f"{status_str:<26} : {p['defect']}")
            print(f"  Description    : {p['description']}")
            print(f"  Recommendation : {p['recommendation']}\n")

    # Exit code
    if total_failed > 0 or total_errored > 0:
        sys.exit(1)
    else:
        sys.exit(0)


if __name__ == '__main__':
    main()
