"""Run the frozen order-flow hypotheses on a normalized, provenance-tagged event tape."""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
from dataclasses import asdict, replace
from pathlib import Path

from fabio_orderflow_core import Config, Event, export_signals_csv, generate_signals, predeclared_configs
from replay_fabio_orderflow import ExecutionConfig, run_replay, run_two_step

ROOT = Path(__file__).resolve().parents[1]
EVENT_FIELDS = ['ts_ns', 'sequence', 'contract', 'price', 'size', 'aggressor', 'bid', 'ask', 'kind']


def sha(path):
    digest = hashlib.sha256()
    with Path(path).open('rb') as source:
        for block in iter(lambda: source.read(1024*1024), b''):
            digest.update(block)
    return digest.hexdigest()


def read_events(path):
    with Path(path).open(encoding='utf-8-sig', newline='') as source:
        rows = csv.DictReader(source)
        if rows.fieldnames not in (EVENT_FIELDS, EVENT_FIELDS + ['quote_usable']):
            raise ValueError('Normalized tape requires the registered event header, optionally followed by quote_usable')
        events = []
        for row in rows:
            usable = row.get('quote_usable', '1')
            if usable not in ('0', '1'):
                raise ValueError('quote_usable must be 0 or 1 in the tape')
            events.append(Event(ts_ns=int(row['ts_ns']), sequence=int(row['sequence']),
                                contract=row['contract'], price=float(row['price']), size=int(row['size']),
                                aggressor=int(row['aggressor']), bid=float(row['bid']), ask=float(row['ask']),
                                kind=row['kind'], quote_usable=usable == '1'))
    if not events:
        raise ValueError('Empty tape cannot establish either performance or feed validity')
    return events


def write_json(path, value):
    Path(path).write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False)+'\n', encoding='utf-8')


def run(events_path, metadata_path, output):
    events_path, metadata_path, output = Path(events_path), Path(metadata_path), Path(output)
    meta = json.loads(metadata_path.read_text(encoding='utf-8'))
    for key in ('dataset_id', 'source_kind', 'contract', 'tick_size', 'tick_value', 'source_url',
                'events_sha256', 'full_quote_updates', 'complete_sessions'):
        if key not in meta:
            raise ValueError('Missing source metadata: '+key)
    if meta['source_kind'] not in ('EXCHANGE_TRADES_BBO', 'SYNTHETIC_FIXTURE'):
        raise ValueError('Unsupported data source; OHLC/tick-count proxies are not order flow')
    if sha(events_path) != meta['events_sha256']:
        raise ValueError('Event tape hash differs from provenance')
    if type(meta['full_quote_updates']) is not bool or type(meta['complete_sessions']) is not int or meta['complete_sessions'] < 0:
        raise ValueError('Coverage declarations must have explicit bool/integer types')
    inferred_side = meta.get('aggressor_method') == 'QUOTE_RULE_STRICT_PRIOR_1S'
    if meta.get('aggressor_method') not in (None, 'DIRECT_EXCHANGE_SIDE',
                                         'EXCHANGE_REPORTED_DATABENTO_SIDE', 'QUOTE_RULE_STRICT_PRIOR_1S'):
        raise ValueError('Unregistered trade-side classification')
    core = Config(tick_size=float(meta['tick_size']), tick_value=float(meta['tick_value']),
                  expected_contract=meta['contract'], allow_unknown_side_profile_only=inferred_side)
    execution = ExecutionConfig(tick_size=core.tick_size, tick_value=core.tick_value)
    hypotheses = predeclared_configs(core)
    scenarios = [('BASE', execution), ('STRESS', replace(execution, commission_per_side=3.5,
                                                       slippage_ticks=2, latency_ns=500000000))]
    lock = {'version': 'fabio_orderflow_study_v1', 'dataset': meta, 'event_sha256': sha(events_path),
            'metadata_sha256': sha(metadata_path),
            'signal_hypotheses': {name: asdict(cfg) for name, cfg in hypotheses.items()},
            'execution_scenarios': {name: asdict(cfg) for name, cfg in scenarios},
            'risk_fractions': [.0025, .005], 'code_sha256': {name: sha(ROOT/'scripts'/name) for name in
            ('fabio_orderflow_core.py', 'replay_fabio_orderflow.py', 'run_fabio_orderflow_study.py')},
            'fees_are_assumptions': True, 'backtest_selection': 'All three declared variants; no winner selected',
            'prop_profile': 'FTMO CFD 2-Step reference money rules only; source-market fills may differ',
            'inference': 'No pass guarantee; synthetic or partial samples cannot establish an edge'}
    output.mkdir(parents=True, exist_ok=True)
    lock_path = output/'EXPERIMENT_LOCK.json'
    if lock_path.exists():
        if json.loads(lock_path.read_text(encoding='utf-8')) != lock:
            raise ValueError('Frozen study differs; use a new version/output folder')
    else:
        write_json(lock_path, lock)
    # Rules, costs, source identity and code are frozen before observing any trading P&L.
    events = read_events(events_path)
    rows, diagnostics = [], {}
    for name, cfg in hypotheses.items():
        signals, diag = generate_signals(events, cfg)
        diagnostics[name] = diag
        write_json(output/(name+'_signals.json'), [asdict(s) for s in signals])
        export_signals_csv(output/(name+'_signals.csv'), signals, meta['dataset_id'],
                           meta['source_kind'], events[-1].ts_ns, contract=meta['contract'])
        for cost_name, cost in scenarios:
            for risk in (.0025, .005):
                config = replace(cost, risk_fraction=risk)
                results = run_replay(events, signals, config)
                benchmark = run_two_step(events, signals, config)
                stem = f'{name}_{cost_name}_risk{risk:.4f}'
                write_json(output/(stem+'_execution.json'), results)
                write_json(output/(stem+'_two_step.json'), benchmark)
                rows.append({'model': name, 'cost': cost_name, 'risk_fraction': risk,
                             'signals': len(signals), 'closed_trades': len(results['trades']),
                             'open_at_end': results['open_position'] is not None,
                             'win_rate': results['win_rate'], 'PF': results['PF'],
                             'mean_net_R': results['mean_net_R'], 'net_closed_cash': results['net_closed_cash'],
                             'max_observed_equity_dd_cash': results['max_observed_equity_dd_cash'],
                             'two_step_status': benchmark['status'], 'edge_confirmed': False,
                             'pass_probability': None})
    result = {'dataset': meta, 'events': len(events), 'first_event_ns': events[0].ts_ns,
              'last_event_ns': events[-1].ts_ns, 'diagnostics': diagnostics, 'rows': rows,
              'signal_hypotheses_tested_on_this_tape': len(hypotheses), 'cost_risk_scenarios': len(rows),
              'technical_integration_only': meta['source_kind'] != 'EXCHANGE_TRADES_BBO' or not meta['full_quote_updates'] or meta['complete_sessions'] < 20,
              'historical_edge_confirmed': False, 'guaranteed_prop_pass': False,
              'pass_probability': None,
              'next_gate': 'Full consecutive development sample, then locked unseen confirmation >=26 weeks and >=200 trades',
              'source_market_and_fund_account_execution_equivalent': False}
    result['trade_side_inferred_not_direct'] = inferred_side
    result['credible_prop_pass_evidence'] = False
    result['coverage_gate_for_performance_inference'] = bool(meta['source_kind'] == 'EXCHANGE_TRADES_BBO'
                                                           and meta['full_quote_updates']
                                                           and meta['complete_sessions'] >= 20)
    write_json(output/'SUMMARY.json', result)
    with (output/'RESULTS.csv').open('w', encoding='utf-8', newline='') as dest:
        writer = csv.DictWriter(dest, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--events', required=True, type=Path)
    parser.add_argument('--metadata', required=True, type=Path)
    parser.add_argument('--out', required=True, type=Path)
    args = parser.parse_args()
    result = run(args.events, args.metadata, args.out)
    print(json.dumps({'output': str(args.out.resolve()), 'events': result['events'],
                      'scenarios': result['cost_risk_scenarios'],
                      'technical_integration_only': result['technical_integration_only'],
                      'historical_edge_confirmed': False}, ensure_ascii=True))


if __name__ == '__main__':
    main()
