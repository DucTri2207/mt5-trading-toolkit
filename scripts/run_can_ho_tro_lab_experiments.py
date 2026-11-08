"""Master Experiment Runner for C\u1ea3n H\u1ed7 Tr\u1ee3 Lab Upgrade (Milestone 2 & 3).

Executes controlled experiments across 5 branches:
- B0: Literal Baseline (reproducing exact baseline quirks, float precision loss, coupled plan lock)
- B1: Technical Bugfix (float precision 1e-7 tolerance, decoupled candidate detection, stable zone keys)
- H1: Highest Room Net R (multi-zone candidate ranking with structural stop guardrail)
- H2: 5-minute Retest Virtual Limit with Market Fallback (chronological M1 quote replay)
- H1_H2: Combined Branch (H1 zone selection + H2 limit entry with fallback)

Evaluates:
- Primary Payoff: 1R (TP = entry +/- D_actual, strict 120m timeout, NO auto-BE/partial close)
- Pre-registered Fee Schedules: LOW (0.27 USD), BASE (0.39 USD), STRESS (0.65 USD)
- Portfolio Gate: Strictly 1 open position forward in time
- Trade retention gates: N_alert >= 100%, N_fill >= 100% full window & annual (2022-2025)
- Standardized ledgers: 24-col SIGNALS, 19-col TRADES, annual breakdown, summary table
"""
import csv
import json
import math
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))

from gold_v301_causal_core import (
    DATA, matrix, atr_mt5, native_snapshots,
    MODE_B0_LITERAL, MODE_B1_TECHNICAL,
    FEE_SCHEDULES,
    calculate_opposing_room,
    detect_all_candidates,
    select_h1_candidate,
    simulate_h2_entry,
    simulate_market_entry,
    simulate_1r_trade,
    filter_single_position
)

OUTPUT_DIR = ROOT / 'reports/can_ho_tro_agy_upgrade/20261101_agy_lab_v2'


def load_dataset():
    """Load cached gold market data snapshot."""
    archive = np.load(DATA)
    h1 = matrix(archive['h1'])
    m5 = matrix(archive['m5'])
    m1 = matrix(archive['m1'])
    return h1, m5, m1


def compute_signals_all_branches(h1, m5, m1, ptr, zones, a_h, a_m, eval_start, eval_end):
    """Generate candidate signal streams for B0, B1, H1, H2, and H1_H2."""
    print("Extracting candidate signals across full timeline...", flush=True)
    t_start = time.time()
    
    b0_signals = []
    b1_signals = []
    h1_signals = []
    
    h_idx = -1
    total_m5 = len(m5)
    
    for m in range(30, total_m5):
        # Align H1 closed bar pointer
        while h_idx + 1 < len(h1) and h1[h_idx + 1, 0] + 3600 <= m5[m, 0]:
            h_idx += 1
        if h_idx < 0:
            continue
            
        bar_t0 = int(m5[m - 1, 0])
        if bar_t0 < eval_start or bar_t0 > eval_end:
            continue
            
        z_slice = zones[ptr[h_idx]:ptr[h_idx + 1]]
        
        # 1. B0 Literal candidate extraction (literal float comparison)
        b0_cands = detect_all_candidates(m5, a_m, m, z_slice, mode=MODE_B0_LITERAL, roundtrip_cost=0.37)
        if b0_cands:
            b0_signals.append(b0_cands[0])  # B0 takes first matching zone in iteration order
            
        # 2. B1 Technical candidate extraction (tolerance 1e-7 fix)
        b1_cands = detect_all_candidates(m5, a_m, m, z_slice, mode=MODE_B1_TECHNICAL, roundtrip_cost=0.37)
        if b1_cands:
            b1_signals.append(b1_cands[0])  # B1 takes first matching zone
            
            # 3. H1 Highest Room Net R candidate ranking
            h1_cand = select_h1_candidate(b1_cands, roundtrip_cost=0.37)
            if h1_cand:
                h1_signals.append(h1_cand)
                
    elapsed = time.time() - t_start
    print(f"Signal extraction complete in {elapsed:.2f}s: B0={len(b0_signals)}, B1={len(b1_signals)}, H1={len(h1_signals)}")
    return b0_signals, b1_signals, h1_signals


def simulate_branch_trades(signals, m5, m1, branch_name='B1', schedule='BASE'):
    """Simulate order execution and 1R trade payoff for a branch."""
    trades = []
    m5_times = m5[:, 0]
    m1_times = m1[:, 0]
    spread, comm, slip = FEE_SCHEDULES[schedule]
    
    for sig_idx, sig in enumerate(signals):
        t0 = sig['time_m5']
        signal_known_time = sig.get('signal_known_time', sig.get('exec_time', t0 + 300))
        d = sig['direction']
        sl = sig['sl_price']
        
        # Determine entry execution based on branch
        if branch_name in ('B0', 'B1', 'H1'):
            m5_idx = np.searchsorted(m5_times, signal_known_time)
            if m5_idx >= len(m5):
                continue
            next_m5_quote = m5[m5_idx]
            
            entry_info = simulate_market_entry(sig, next_m5_quote, spread=spread, slip=slip, max_delay=60)
        elif branch_name in ('H2', 'H1_H2'):
            # 5-minute virtual limit order retest with market fallback
            # Limit window is strictly [signal_known_time, signal_known_time + 300)
            m1_start_idx = int(np.searchsorted(m1_times, signal_known_time))
            # Slice M1 bars covering the 5-minute limit window plus fallback delay window (+360s)
            m1_end_idx = int(np.searchsorted(m1_times, signal_known_time + 360))
            m1_sub = m1[m1_start_idx:max(m1_start_idx + 6, m1_end_idx)]
            
            # Fallback M5 quote at or after deadline (signal_known_time + 300)
            limit_deadline = signal_known_time + 300
            fallback_m5_idx = int(np.searchsorted(m5_times, limit_deadline))
            fallback_m5_quote = m5[fallback_m5_idx] if fallback_m5_idx < len(m5) else None
            
            entry_info = simulate_h2_entry(sig, m1_sub, fallback_m5_quote, spread=spread, slip=slip)
            
        if not entry_info['filled']:
            continue
            
        # Locate M5 bar containing fill_time for payoff replay
        fill_time = entry_info['fill_time']
        m5_fill_idx = int(np.searchsorted(m5_times, fill_time, side='right')) - 1
        m5_fill_idx = max(0, m5_fill_idx)
        if m5_fill_idx >= len(m5):
            continue
            
        # Simulate Primary 1R Payoff forward in time
        trade = simulate_1r_trade(
            entry_price=entry_info['entry_price'],
            sl_price=entry_info['sl_price'],
            direction=d,
            fill_time=fill_time,
            t0=t0,
            m5_bars=m5,
            m5_start_idx=m5_fill_idx,
            schedule=schedule,
            is_limit=(entry_info['entry_type'] == 'LIMIT'),
            signal_known_time=signal_known_time,
            entry_type=entry_info['entry_type'],
            ambiguous_intrabar=entry_info.get('ambiguous_intrabar', False)
        )
        trade['trade_id'] = sig_idx + 1
        trade['signal_id'] = sig_idx + 1
        trade['branch'] = branch_name
        trade['schedule'] = schedule
        trade['year'] = datetime.fromtimestamp(t0, tz=timezone.utc).year
        trades.append(trade)
        
    return trades


def calculate_performance_metrics(trades, n_raw, n_alert, baseline_counts=None):
    """Calculate standard performance metrics matching PROJECT.md and ORIGINAL_REQUEST.md."""
    # Filter closed trades (exclude end-of-sample censored)
    closed = [t for t in trades if t['exit_reason'] != 'CENSORED']
    n_fill = len(trades)
    n_closed = len(closed)
    
    if n_closed == 0:
        return {
            'n_raw': n_raw, 'n_alert': n_alert, 'n_fill': n_fill, 'n_closed': 0,
            'retention_alert_pct': 0.0, 'retention_fill_pct': 0.0,
            'tp_pct': 0.0, 'win_pct': 0.0, 'profit_factor': 0.0,
            'net_r': 0.0, 'expectancy': 0.0, 'max_dd_r': 0.0,
            'years': {}
        }
        
    # Retention vs baseline
    base_n_alert = baseline_counts['n_alert'] if baseline_counts else n_alert
    base_n_fill = baseline_counts['n_fill'] if baseline_counts else n_fill
    retention_alert_pct = (n_alert / base_n_alert * 100.0) if base_n_alert > 0 else 100.0
    retention_fill_pct = (n_fill / base_n_fill * 100.0) if base_n_fill > 0 else 100.0
    
    # Win rate and TP rate
    tp_hits = sum(1 for t in closed if t['exit_reason'] == 'TP')
    tp_pct = (tp_hits / n_closed) * 100.0
    
    wins = [t for t in closed if t['net_pnl_usd'] > 0]
    losses = [t for t in closed if t['net_pnl_usd'] < 0]
    win_pct = (len(wins) / n_closed) * 100.0
    
    # Financial metrics
    gross_gains = sum(t['net_pnl_usd'] for t in wins)
    gross_losses = abs(sum(t['net_pnl_usd'] for t in losses))
    pf = (gross_gains / gross_losses) if gross_losses > 0 else float('inf')
    
    r_multiples = [t['net_r'] for t in closed]
    net_r = sum(r_multiples)
    expectancy = net_r / n_closed if n_closed > 0 else 0.0
    
    # Max Closed R Drawdown
    cum_r = np.cumsum(r_multiples)
    peak_r = np.maximum.accumulate(cum_r)
    dd_r = peak_r - cum_r
    max_dd_r = float(np.max(dd_r)) if len(dd_r) > 0 else 0.0
    
    # Annual breakdown
    years = {}
    for y in [2022, 2023, 2024, 2025]:
        y_closed = [t for t in closed if t['year'] == y]
        y_trades = [t for t in trades if t['year'] == y]
        y_r = [t['net_r'] for t in y_closed]
        years[y] = {
            'n_fill': len(y_trades),
            'n_closed': len(y_closed),
            'net_r': float(sum(y_r)),
            'expectancy': float(np.mean(y_r)) if y_closed else 0.0,
            'tp_pct': float(sum(1 for t in y_closed if t['exit_reason'] == 'TP') / len(y_closed) * 100.0) if y_closed else 0.0
        }
        
    return {
        'n_raw': n_raw,
        'n_alert': n_alert,
        'n_fill': n_fill,
        'n_closed': n_closed,
        'retention_alert_pct': retention_alert_pct,
        'retention_fill_pct': retention_fill_pct,
        'tp_pct': tp_pct,
        'win_pct': win_pct,
        'profit_factor': pf,
        'net_r': net_r,
        'expectancy': expectancy,
        'max_dd_r': max_dd_r,
        'years': years
    }


def read_signals_csv(filepath):
    """Read standardized 24-column signals ledger into candidate dictionaries."""
    signals = []
    with open(filepath, 'r', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        for r in reader:
            signals.append({
                'time_m5': int(r['signal_time']),
                'exec_time': int(r['exec_time']),
                'confirm_bar_open': int(r['signal_time']),
                'signal_known_time': int(r['signal_time']) + 300,
                'direction': int(r['direction']),
                'entry_market': float(r['entry_market']),
                'sl_price': float(r['sl_price']),
                'risk': float(r['risk_usd']),
                'choch_level': float(r['choch_level']),
                'zone_id': float(r['zone_id']),
                'zone_type': int(r['zone_type']),
                'zone_distal': float(r['zone_distal']),
                'zone_proximal': float(r['zone_proximal']),
                'zone_score': float(r['zone_score']),
                'sweep_shift': float(r['sweep_shift']),
                'atr': float(r['atr']),
                'dist_to_zone': float(r['dist_to_zone']),
                'dist_to_zone_atr': float(r['dist_to_zone_atr']),
                'has_opposing': bool(int(r['has_opposing'])),
                'opposing_proximal': float(r['opposing_proximal']) if r['opposing_proximal'] else None,
                'opposing_room': float(r['opposing_room']) if r['opposing_room'] else None,
                'room_net_R': float(r['room_net_R']) if r['room_net_R'] else None,
            })
    return signals


def write_signals_csv(signals, filepath):
    """Write standardized 24-column signals ledger."""
    fieldnames = [
        'signal_id', 'signal_time', 'exec_time', 'direction', 'entry_market',
        'sl_price', 'risk_usd', 'tp_1r', 'choch_level', 'zone_id',
        'zone_type', 'zone_distal', 'zone_proximal', 'zone_score', 'sweep_shift',
        'atr', 'dist_to_zone', 'dist_to_zone_atr', 'has_opposing', 'opposing_proximal',
        'opposing_room', 'room_net_R', 'spread_at_signal', 'latency_usd'
    ]
    with open(filepath, 'w', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for idx, s in enumerate(signals, 1):
            d = s['direction']
            entry = s['entry_market']
            risk = s['risk']
            row = {
                'signal_id': idx,
                'signal_time': s['time_m5'],
                'exec_time': s['exec_time'],
                'direction': d,
                'entry_market': round(entry, 4),
                'sl_price': round(s['sl_price'], 4),
                'risk_usd': round(risk, 4),
                'tp_1r': round(entry + d * risk, 4),
                'choch_level': round(s['choch_level'], 4),
                'zone_id': int(s['zone_id']),
                'zone_type': s['zone_type'],
                'zone_distal': round(s['zone_distal'], 4),
                'zone_proximal': round(s['zone_proximal'], 4),
                'zone_score': int(s['zone_score']),
                'sweep_shift': int(s['sweep_shift']),
                'atr': round(s['atr'], 4),
                'dist_to_zone': round(s['dist_to_zone'], 4),
                'dist_to_zone_atr': round(s['dist_to_zone_atr'], 4),
                'has_opposing': 1 if s['has_opposing'] else 0,
                'opposing_proximal': round(s['opposing_proximal'], 4) if s['opposing_proximal'] is not None else '',
                'opposing_room': round(s['opposing_room'], 4) if s['opposing_room'] is not None else '',
                'room_net_R': round(s['room_net_R'], 4) if s['room_net_R'] is not None else '',
                'spread_at_signal': 0.30,
                'latency_usd': 0.00
            }
            writer.writerow(row)


def write_trades_csv(trades, filepath):
    """Write standardized 19-column trades ledger."""
    fieldnames = [
        'trade_id', 'signal_id', 'direction', 'entry_time', 'entry_price',
        'entry_type', 'sl_price', 'tp_price', 'risk_usd', 'exit_time',
        'exit_price', 'exit_reason', 'gross_pnl_usd', 'commission_usd',
        'slippage_usd', 'spread_cost_usd', 'net_pnl_usd', 'net_r', 'bars_held'
    ]
    with open(filepath, 'w', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for t in trades:
            row = {
                'trade_id': t['trade_id'],
                'signal_id': t['signal_id'],
                'direction': t['direction'],
                'entry_time': t['entry_time'],
                'entry_price': round(t['entry_price'], 4),
                'entry_type': t['entry_type'],
                'sl_price': round(t['sl_price'], 4),
                'tp_price': round(t['tp_price'], 4),
                'risk_usd': round(t['risk_usd'], 4),
                'exit_time': t['exit_time'],
                'exit_price': round(t['exit_price'], 4),
                'exit_reason': t['exit_reason'],
                'gross_pnl_usd': round(t['gross_pnl_usd'], 4),
                'commission_usd': round(t['commission_usd'], 4),
                'slippage_usd': round(t['slippage_usd'], 4),
                'spread_cost_usd': round(t['spread_cost_usd'], 4),
                'net_pnl_usd': round(t['net_pnl_usd'], 4),
                'net_r': round(t['net_r'], 4),
                'bars_held': t['bars_held']
            }
            writer.writerow(row)


def main():
    print("=" * 80)
    print("CAN HO TRO LAB EXPERIMENT ENGINE - B0 / B1 / H1 / H2")
    print("=" * 80)
    
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    h1, m5, m1 = load_dataset()
    a_h = atr_mt5(h1)
    a_m = atr_mt5(m5)
    
    print("Generating H1 snapshot cache...", flush=True)
    ptr, rows = native_snapshots(h1, a_h, deterministic_keys=True)
    zones = np.asarray(rows, dtype=float).reshape(-1, 9)
    
    eval_start = int(datetime(2021, 10, 23, 0, 0, 0, tzinfo=timezone.utc).timestamp())
    eval_end = int(datetime(2026, 10, 23, 23, 59, 59, tzinfo=timezone.utc).timestamp())
    
    # 1. Extract signals for all branches (use cached CSVs if available)
    b0_csv = OUTPUT_DIR / 'SIGNALS_B0.csv'
    b1_csv = OUTPUT_DIR / 'SIGNALS_B1.csv'
    h1_csv = OUTPUT_DIR / 'SIGNALS_H1.csv'
    
    if b0_csv.exists() and b1_csv.exists() and h1_csv.exists():
        print("Loading pre-computed signals from CSVs...", flush=True)
        b0_sigs = read_signals_csv(b0_csv)
        b1_sigs = read_signals_csv(b1_csv)
        h1_sigs = read_signals_csv(h1_csv)
        print(f"Loaded signals: B0={len(b0_sigs)}, B1={len(b1_sigs)}, H1={len(h1_sigs)}")
    else:
        b0_sigs, b1_sigs, h1_sigs = compute_signals_all_branches(
            h1, m5, m1, ptr, zones, a_h, a_m, eval_start, eval_end
        )
        for b_name, sig_list in [('B0', b0_sigs), ('B1', b1_sigs), ('H1', h1_sigs)]:
            sig_path = OUTPUT_DIR / f'SIGNALS_{b_name}.csv'
            write_signals_csv(sig_list, sig_path)
            print(f"Saved {len(sig_list)} signals to {sig_path.name}")
    
    # H2 uses B1 candidate pool with virtual limit retest entry
    h2_sigs = b1_sigs
    # H1_H2 uses H1 candidate pool with virtual limit retest entry
    h1_h2_sigs = h1_sigs
    
    signals_dict = {
        'B0': b0_sigs,
        'B1': b1_sigs,
        'H1': h1_sigs,
        'H2': h2_sigs,
        'H1_H2': h1_h2_sigs
    }
    
    # Ensure all signal CSVs are saved
    for b_name in ['H2', 'H1_H2']:
        sig_path = OUTPUT_DIR / f'SIGNALS_{b_name}.csv'
        if not sig_path.exists():
            write_signals_csv(signals_dict[b_name], sig_path)
            print(f"Saved {len(signals_dict[b_name])} signals to {sig_path.name}")
        
    # 2. Simulate trades across schedules and branches
    results = {}
    baseline_base_counts = None
    
    for schedule in ['LOW', 'BASE', 'STRESS']:
        results[schedule] = {}
        for b_name in ['B0', 'B1', 'H1', 'H2', 'H1_H2']:
            raw_sigs = signals_dict[b_name]
            # Unfiltered trade candidates
            all_trades = simulate_branch_trades(raw_sigs, m5, m1, branch_name=b_name, schedule=schedule)
            # Apply single position portfolio filter
            portfolio_trades = filter_single_position(all_trades)
            
            # Save BASE trades ledger
            if schedule == 'BASE':
                trade_path = OUTPUT_DIR / f'TRADES_{b_name}.csv'
                write_trades_csv(portfolio_trades, trade_path)
                
            n_raw = len(raw_sigs)
            n_alert = len(raw_sigs)
            
            # Baseline baseline counts anchor
            if b_name == 'B0' and schedule == 'BASE':
                baseline_base_counts = {'n_alert': n_alert, 'n_fill': len(portfolio_trades)}
                
            metrics = calculate_performance_metrics(
                portfolio_trades, n_raw, n_alert, baseline_counts=baseline_base_counts
            )
            results[schedule][b_name] = metrics
            
    # Save results JSON
    results_path = OUTPUT_DIR / 'EXPERIMENT_RESULTS.json'
    with open(results_path, 'w', encoding='utf-8') as f:
        json.dump(results, f, indent=2)
    print(f"\nExperiment results saved to {results_path}")
    
    # 3. Print Mandatory Summary Table (matching ORIGINAL_REQUEST.md R6)
    print("\n" + "=" * 115)
    print("MANDATORY EXPERIMENT SUMMARY TABLE (Payoff: 1R, Timeout: 120m, Fee: BASE & STRESS)")
    print("=" * 115)
    header = (
        f"{'Nhánh':<10} | {'N_raw':<6} | {'N_alert':<7} | {'N_fill':<6} | {'N_closed':<8} | "
        f"{'Alert%':<7} | {'Fill%':<7} | {'TP%':<6} | {'Win%':<6} | {'PF':<5} | "
        f"{'Net R':<8} | {'Exp (R)':<8} | {'DD (R)':<6} | {'STRESS Exp':<10} | {'Trạng thái':<12}"
    )
    print(header)
    print("-" * 115)
    
    for b_name in ['B0', 'B1', 'H1', 'H2', 'H1_H2']:
        base_m = results['BASE'][b_name]
        stress_m = results['STRESS'][b_name]
        
        # Criteria check:
        # Retention >= 100% full window AND annually (2022-2025)
        retention_ok = (base_m['retention_alert_pct'] >= 100.0 - 1e-7) and (base_m['retention_fill_pct'] >= 100.0 - 1e-7)
        for y in [2022, 2023, 2024, 2025]:
            if b_name != 'B0':
                b0_y_fill = results['BASE']['B0']['years'][y]['n_fill']
                if base_m['years'][y]['n_fill'] < b0_y_fill:
                    retention_ok = False
                    
        # Economic criteria: TP% >= baseline + 5%, Expectancy >= +0.05R, PF >= 1.20, Stress Exp > 0
        b0_tp = results['BASE']['B0']['tp_pct']
        economic_ok = (
            base_m['tp_pct'] >= b0_tp + 5.0 and
            base_m['expectancy'] >= 0.05 and
            base_m['profit_factor'] >= 1.20 and
            stress_m['expectancy'] > 0.0
        )
        
        status = "ĐẠT" if (retention_ok and economic_ok) else "KHÔNG ĐẠT"
        
        row = (
            f"{b_name:<10} | {base_m['n_raw']:<6} | {base_m['n_alert']:<7} | {base_m['n_fill']:<6} | {base_m['n_closed']:<8} | "
            f"{base_m['retention_alert_pct']:>6.1f}% | {base_m['retention_fill_pct']:>6.1f}% | "
            f"{base_m['tp_pct']:>5.1f}% | {base_m['win_pct']:>5.1f}% | {base_m['profit_factor']:>5.2f} | "
            f"{base_m['net_r']:>8.2f} | {base_m['expectancy']:>8.4f} | {base_m['max_dd_r']:>6.2f} | "
            f"{stress_m['expectancy']:>10.4f} | {status:<12}"
        )
        print(row)
        
    print("=" * 115)


if __name__ == '__main__':
    main()
