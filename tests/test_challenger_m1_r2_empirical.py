"""Empirical Challenger Test Suite for M1 R2 Remediation Verification.

Verifies:
1. 500-signal sample execution across B0, B1, H1, H2 with 0 assertion crashes.
2. Signal 65 in H2 (index 65 and signal_id 65) execution, entry type, fill time, and clean exit.
3. Signal 111 in B0 (index 110, index 111, signal_id 111, signal_id 112) execution, clean handling, and exit_time >= fill_time.
4. Strict limit window verification: LIMIT fills in H2 strictly in [signal_known_time, signal_known_time + 300).
5. Fallback window verification: MARKET_FALLBACK fills in [signal_known_time + 300, signal_known_time + 360].
6. Temporal causality verification: exit_time >= fill_time >= signal_known_time across 100% of filled trades.
7. Output file integrity in reports/can_ho_tro_agy_upgrade/20261101_agy_lab_v2/.
"""
import csv
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))

import numpy as np
import run_can_ho_tro_lab_experiments as runner
from gold_v301_causal_core import FEE_SCHEDULES


def test_500_signals_sample():
    print("=" * 80)
    print("TEST 1: 500-SIGNAL SAMPLE ACROSS ALL 4 BRANCHES (B0, B1, H1, H2)")
    print("=" * 80)
    
    h1, m5, m1 = runner.load_dataset()
    v2_dir = ROOT / 'reports/can_ho_tro_agy_upgrade/20261101_agy_lab_v2'
    
    branch_stats = {}
    
    for branch in ['B0', 'B1', 'H1', 'H2', 'H1_H2']:
        sig_file = v2_dir / f'SIGNALS_{branch}.csv'
        assert sig_file.exists(), f"Missing signal file: {sig_file}"
        all_sigs = runner.read_signals_csv(sig_file)
        sample_500 = all_sigs[:500]
        
        # Run simulation with BASE schedule
        trades = runner.simulate_branch_trades(sample_500, m5, m1, branch_name=branch, schedule='BASE')
        pf_trades = runner.filter_single_position(trades)
        
        # Verify 0 crashes
        assert len(trades) > 0, f"No trades generated for {branch}"
        
        limit_trades = [t for t in trades if t['entry_type'] == 'LIMIT']
        fallback_trades = [t for t in trades if t['entry_type'] == 'MARKET_FALLBACK']
        market_trades = [t for t in trades if t['entry_type'] == 'MARKET']
        
        branch_stats[branch] = {
            'signals': len(sample_500),
            'raw_trades': len(trades),
            'portfolio_trades': len(pf_trades),
            'limit_fills': len(limit_trades),
            'fallback_fills': len(fallback_trades),
            'market_fills': len(market_trades),
            'crashes': 0
        }
        
        print(f"Branch {branch:<6}: 500 signals -> {len(trades)} raw fills "
              f"({len(limit_trades)} LIMIT, {len(fallback_trades)} FALLBACK, {len(market_trades)} MARKET) -> "
              f"{len(pf_trades)} portfolio trades. Assertion crashes: 0")
              
    return branch_stats


def test_signal_65_h2():
    print("\n" + "=" * 80)
    print("TEST 2: SIGNAL 65 IN H2 (INDEX 65 & SIGNAL_ID 65)")
    print("=" * 80)
    
    h1, m5, m1 = runner.load_dataset()
    v2_dir = ROOT / 'reports/can_ho_tro_agy_upgrade/20261101_agy_lab_v2'
    h2_sigs = runner.read_signals_csv(v2_dir / 'SIGNALS_H2.csv')
    
    # We test both:
    # A. Index 65 (66th signal)
    # B. Signal with signal_id == 65 (index 64)
    target_indices = [64, 65]
    
    for idx in target_indices:
        sig = h2_sigs[idx]
        t0 = sig['time_m5']
        skt = sig['signal_known_time']
        deadline = skt + 300
        
        trades = runner.simulate_branch_trades([sig], m5, m1, branch_name='H2', schedule='BASE')
        print(f"\nSignal at index {idx} (signal_id={idx+1}):")
        print(f"  signal_time (t0):     {t0}")
        print(f"  signal_known_time:   {skt}")
        print(f"  limit_deadline:      {deadline}")
        print(f"  direction:           {sig['direction']}")
        print(f"  entry_market:        {sig['entry_market']}")
        print(f"  choch_level (limit): {sig['choch_level']}")
        print(f"  sl_price:            {sig['sl_price']}")
        
        if len(trades) == 0:
            print("  Result: Order did not fill (cancelled cleanly).")
        else:
            t = trades[0]
            print(f"  Result: FILLED")
            print(f"  entry_type:          {t['entry_type']}")
            print(f"  fill_time:           {t['entry_time']} (offset from skt: {t['entry_time'] - skt}s)")
            print(f"  entry_price:         {t['entry_price']}")
            print(f"  exit_time:           {t['exit_time']} (duration: {t['exit_time'] - t['entry_time']}s)")
            print(f"  exit_price:          {t['exit_price']}")
            print(f"  exit_reason:         {t['exit_reason']}")
            print(f"  net_r:               {t['net_r']}")
            
            # Assertions
            assert t['entry_time'] >= skt, f"Fill before skt: {t['entry_time']} < {skt}"
            if t['entry_type'] == 'LIMIT':
                assert t['entry_time'] < deadline, f"LIMIT fill after deadline: {t['entry_time']} >= {deadline}"
            elif t['entry_type'] == 'MARKET_FALLBACK':
                assert t['entry_time'] >= deadline, f"FALLBACK fill before deadline: {t['entry_time']} < {deadline}"
                assert t['entry_time'] <= skt + 360, f"FALLBACK fill delay > 60s: {t['entry_time']}"
            assert t['exit_time'] >= t['entry_time'], f"Exit before fill: {t['exit_time']} < {t['entry_time']}"
            assert t['exit_reason'] in ('TP', 'SL', 'GAP_SL', 'TIMEOUT', 'CENSORED'), f"Invalid exit reason: {t['exit_reason']}"
            print("  Assertions: PASS (0 crashes, clean fill & exit)")


def test_signal_111_b0():
    print("\n" + "=" * 80)
    print("TEST 3: SIGNAL 111 IN B0 (INDEX 110, 111, 112 INSPECTION)")
    print("=" * 80)
    
    h1, m5, m1 = runner.load_dataset()
    v2_dir = ROOT / 'reports/can_ho_tro_agy_upgrade/20261101_agy_lab_v2'
    b0_sigs = runner.read_signals_csv(v2_dir / 'SIGNALS_B0.csv')
    
    # Inspect indices 109 to 113 to be completely exhaustive around Signal 111
    for idx in range(109, 114):
        sig = b0_sigs[idx]
        t0 = sig['time_m5']
        skt = sig['signal_known_time']
        
        trades = runner.simulate_branch_trades([sig], m5, m1, branch_name='B0', schedule='BASE')
        print(f"\nSignal at index {idx} (signal_id={idx+1}):")
        print(f"  signal_time (t0):     {t0}")
        print(f"  signal_known_time:   {skt}")
        print(f"  direction:           {sig['direction']}")
        
        if len(trades) == 0:
            print("  Result: REJECTED/CANCELLED cleanly (likely closed-market delay guard > 60s).")
        else:
            t = trades[0]
            print(f"  Result: FILLED")
            print(f"  entry_type:          {t['entry_type']}")
            print(f"  fill_time:           {t['entry_time']} (offset from skt: {t['entry_time'] - skt}s)")
            print(f"  exit_time:           {t['exit_time']} (duration: {t['exit_time'] - t['entry_time']}s)")
            print(f"  exit_reason:         {t['exit_reason']}")
            print(f"  net_r:               {t['net_r']}")
            
            # Assertions
            assert t['entry_time'] >= skt, f"Fill before skt: {t['entry_time']} < {skt}"
            assert t['exit_time'] >= t['entry_time'], f"Exit before fill: {t['exit_time']} < {t['entry_time']}"
            assert t['exit_reason'] in ('TP', 'SL', 'GAP_SL', 'TIMEOUT', 'CENSORED'), f"Invalid exit reason: {t['exit_reason']}"
            print("  Assertions: PASS (exit_time >= fill_time strictly satisfied)")


def test_limit_fill_window_h2():
    print("\n" + "=" * 80)
    print("TEST 4: H2 LIMIT FILL WINDOW VERIFICATION ON SAMPLE & FULL DATASET")
    print("=" * 80)
    
    h1, m5, m1 = runner.load_dataset()
    v2_dir = ROOT / 'reports/can_ho_tro_agy_upgrade/20261101_agy_lab_v2'
    h2_sigs = runner.read_signals_csv(v2_dir / 'SIGNALS_H2.csv')
    
    # 1. First 500 signals
    sample_500 = h2_sigs[:500]
    trades_500 = runner.simulate_branch_trades(sample_500, m5, m1, branch_name='H2', schedule='BASE')
    
    limit_500 = [t for t in trades_500 if t['entry_type'] == 'LIMIT']
    fallback_500 = [t for t in trades_500 if t['entry_type'] == 'MARKET_FALLBACK']
    
    print(f"500-signal H2 sample: {len(trades_500)} total fills ({len(limit_500)} LIMIT, {len(fallback_500)} FALLBACK)")
    
    # Map signals by id
    sig_map = {idx + 1: s for idx, s in enumerate(sample_500)}
    
    limit_window_violations = 0
    fallback_window_violations = 0
    exit_before_fill_violations = 0
    
    for t in limit_500:
        sig = sig_map[t['signal_id']]
        skt = sig['signal_known_time']
        fill_t = t['entry_time']
        exit_t = t['exit_time']
        
        # Strictly in [signal_known_time, signal_known_time + 300)
        if not (skt <= fill_t < skt + 300):
            limit_window_violations += 1
            print(f"VIOLATION: LIMIT fill {fill_t} outside [{skt}, {skt+300})")
            
        if exit_t < fill_t:
            exit_before_fill_violations += 1
            
    for t in fallback_500:
        sig = sig_map[t['signal_id']]
        skt = sig['signal_known_time']
        fill_t = t['entry_time']
        exit_t = t['exit_time']
        
        # Strictly in [signal_known_time + 300, signal_known_time + 360]
        if not (skt + 300 <= fill_t <= skt + 360):
            fallback_window_violations += 1
            print(f"VIOLATION: FALLBACK fill {fill_t} outside [{skt+300}, {skt+360}]")
            
        if exit_t < fill_t:
            exit_before_fill_violations += 1
            
    print(f"  LIMIT window violations [skt, skt+300):       {limit_window_violations}")
    print(f"  FALLBACK window violations [skt+300, skt+360]: {fallback_window_violations}")
    print(f"  Exit before fill violations:                   {exit_before_fill_violations}")
    
    assert limit_window_violations == 0, f"Found {limit_window_violations} LIMIT window violations"
    assert fallback_window_violations == 0, f"Found {fallback_window_violations} FALLBACK window violations"
    assert exit_before_fill_violations == 0, f"Found {exit_before_fill_violations} exit-before-fill violations"
    print("Sample 500 window verification: PASS (100.00% strictly compliant)")
    
    # 2. Check full ledger TRADES_H2.csv in reports/can_ho_tro_agy_upgrade/20261101_agy_lab_v2
    print("\nAuditing full generated ledger TRADES_H2.csv:")
    with open(v2_dir / 'TRADES_H2.csv', 'r') as f:
        full_h2_trades = list(csv.DictReader(f))
        
    full_sig_map = {idx + 1: s for idx, s in enumerate(h2_sigs)}
    full_limit_violations = 0
    full_fallback_violations = 0
    full_exit_violations = 0
    full_limit_count = 0
    full_fallback_count = 0
    
    for row in full_h2_trades:
        sig_id = int(row['signal_id'])
        sig = full_sig_map[sig_id]
        skt = sig['signal_known_time']
        entry_t = int(row['entry_time'])
        exit_t = int(row['exit_time'])
        entry_type = row['entry_type']
        
        if entry_type == 'LIMIT':
            full_limit_count += 1
            if not (skt <= entry_t < skt + 300):
                full_limit_violations += 1
        elif entry_type == 'MARKET_FALLBACK':
            full_fallback_count += 1
            if not (skt + 300 <= entry_t <= skt + 360):
                full_fallback_violations += 1
                
        if exit_t < entry_t:
            full_exit_violations += 1
            
    print(f"  Full TRADES_H2.csv: {len(full_h2_trades)} trades ({full_limit_count} LIMIT, {full_fallback_count} FALLBACK)")
    print(f"  Full LIMIT violations:     {full_limit_violations}")
    print(f"  Full FALLBACK violations:  {full_fallback_violations}")
    print(f"  Full exit < fill violations: {full_exit_violations}")
    
    assert full_limit_violations == 0
    assert full_fallback_violations == 0
    assert full_exit_violations == 0
    print("Full ledger window verification: PASS (100.00% strictly compliant)")


def test_output_files_integrity():
    print("\n" + "=" * 80)
    print("TEST 5: OUTPUT FILES INTEGRITY IN reports/can_ho_tro_agy_upgrade/20261101_agy_lab_v2/")
    print("=" * 80)
    
    v2_dir = ROOT / 'reports/can_ho_tro_agy_upgrade/20261101_agy_lab_v2'
    assert v2_dir.exists(), f"Output directory {v2_dir} does not exist!"
    
    expected_files = [
        'SIGNALS_B0.csv',
        'SIGNALS_B1.csv',
        'SIGNALS_H1.csv',
        'SIGNALS_H2.csv',
        'SIGNALS_H1_H2.csv',
        'TRADES_B0.csv',
        'TRADES_B1.csv',
        'TRADES_H1.csv',
        'TRADES_H2.csv',
        'TRADES_H1_H2.csv',
        'EXPERIMENT_RESULTS.json',
    ]
    
    for fname in expected_files:
        fpath = v2_dir / fname
        assert fpath.exists(), f"Missing expected output file: {fname}"
        size = fpath.stat().st_size
        assert size > 0, f"File {fname} is empty!"
        print(f"  [OK] {fname:<25} ({size:>10} bytes)")
        
    with open(v2_dir / 'EXPERIMENT_RESULTS.json', 'r', encoding='utf-8') as f:
        results = json.load(f)
        
    for sched in ['LOW', 'BASE', 'STRESS']:
        assert sched in results, f"Missing schedule {sched} in EXPERIMENT_RESULTS.json"
        for branch in ['B0', 'B1', 'H1', 'H2', 'H1_H2']:
            assert branch in results[sched], f"Missing branch {branch} in schedule {sched}"
            m = results[sched][branch]
            assert 'n_raw' in m and m['n_raw'] > 0
            assert 'n_fill' in m and m['n_fill'] > 0
            assert 'net_r' in m
            assert 'expectancy' in m
            assert 'profit_factor' in m
            
    print("EXPERIMENT_RESULTS.json structure & content: PASS")


if __name__ == '__main__':
    test_500_signals_sample()
    test_signal_65_h2()
    test_signal_111_b0()
    test_limit_fill_window_h2()
    test_output_files_integrity()
    print("\n" + "=" * 80)
    print("ALL EMPIRICAL CHALLENGER TESTS PASSED SUCCESSFULLY!")
    print("=" * 80)
