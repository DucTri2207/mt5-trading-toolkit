"""Block-based validation of a frozen Fabio replay, without inventing pass odds.

Evidence JSON references are hashed and inspected, not inferred from metadata booleans.
See implementation/VALIDATION_EVIDENCE.md for the prospective evidence contract.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
from collections import Counter
from datetime import date, datetime, timedelta, timezone
from numbers import Integral
from pathlib import Path
from zoneinfo import ZoneInfo

import numpy as np

SEED = 20261101
RESAMPLES = 20000
FAMILY_SIZE = 24


def sha256(path):
    digest = hashlib.sha256()
    with Path(path).open('rb') as source:
        for block in iter(lambda: source.read(1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()


def bootstrap_mean_net_R(blocks, *, resamples=RESAMPLES, seed=SEED, family_size=FAMILY_SIZE):
    """Paired block bootstrap of sum(net R)/closed-trade count.

    A block with zero trades is retained. A resample containing no trades has
    unidentified expectancy and contributes -infinity to a conservative lower
    interval, instead of being dropped. JSON represents an unbounded lower as None.
    """
    if (isinstance(resamples, bool) or not isinstance(resamples, Integral) or resamples < 1
            or isinstance(family_size, bool) or not isinstance(family_size, Integral)
            or family_size < FAMILY_SIZE):
        raise ValueError('Positive integer resamples and family_size >=24 required')
    sums, counts = [], []
    for total, count in blocks:
        if (not math.isfinite(total) or isinstance(count, bool) or not isinstance(count, Integral)
                or count < 0 or (count == 0 and total != 0)):
            raise ValueError('Each block requires finite net R and a nonnegative integer trade count')
        sums.append(float(total))
        counts.append(int(count))
    if not sums:
        return {'status': 'NO_BLOCKS', 'blocks': 0, 'mean_net_R': None,
                'lower95': None, 'family_adjusted_lower95': None}
    sums, counts = np.asarray(sums), np.asarray(counts)
    if counts.sum() == 0:
        return {'status': 'NO_CLOSED_TRADES', 'blocks': len(sums), 'zero_trade_blocks': len(sums),
                'closed_trades': 0, 'mean_net_R': None, 'lower95': None,
                'family_adjusted_lower95': None, 'mean_R_per_block': 0.}
    rng = np.random.default_rng(seed)
    ratios = np.empty(resamples)
    block_means = np.empty(resamples)
    no_trade_resamples = 0
    for start in range(0, resamples, 256):
        n = min(256, resamples - start)
        picked = rng.integers(0, len(sums), size=(n, len(sums)))
        selected_sum = sums[picked].sum(axis=1)
        selected_count = counts[picked].sum(axis=1)
        no_trade_resamples += int(np.count_nonzero(selected_count == 0))
        ratios[start:start + n] = np.divide(selected_sum, selected_count,
                                          out=np.full(n, -np.inf), where=selected_count > 0)
        block_means[start:start + n] = selected_sum / len(sums)

    def lower(values, probability):
        # Use order statistics rather than interpolation between infinity and finite values.
        selected = np.sort(values)[int(math.floor(probability * (len(values) - 1)))]
        return float(selected) if math.isfinite(selected) else None

    def upper(values, probability):
        selected = np.sort(values)[int(math.ceil(probability * (len(values) - 1)))]
        return float(selected) if math.isfinite(selected) else None

    return {'status': 'ESTIMATED', 'blocks': len(sums), 'zero_trade_blocks': int(np.count_nonzero(counts == 0)),
            'closed_trades': int(counts.sum()), 'mean_net_R': float(sums.sum() / counts.sum()),
            'lower95': lower(ratios, .025), 'upper95': upper(ratios, .975),
            'family_adjusted_lower95': lower(ratios, .025 / family_size),
            'family_adjusted_upper95': upper(ratios, 1 - .025 / family_size),
            'mean_R_per_block': float(sums.mean()),
            'mean_R_per_block_lower95': lower(block_means, .025),
            'mean_R_per_block_family_adjusted_lower95': lower(block_means, .025 / family_size),
            'zero_trade_resamples': no_trade_resamples, 'resamples': int(resamples),
            'seed': int(seed), 'family_size': int(family_size),
            'interval': 'two-sided95%, Bonferroni family correction on both tails',
            'zero_trade_resample_policy': 'unidentified per-trade expectancy; conservative negative-infinite lower tail'}


def _artifact(reference):
    if not isinstance(reference, dict) or not reference.get('path') or not reference.get('sha256'):
        return None, 'missing hashed artifact reference'
    path = Path(reference['path'])
    if not path.is_file():
        return None, 'artifact file missing: ' + str(path)
    if sha256(path) != reference['sha256']:
        return None, 'artifact hash mismatch: ' + str(path)
    try:
        value = json.loads(path.read_text(encoding='utf-8'))
    except (ValueError, UnicodeError):
        return None, 'artifact is not valid UTF-8 JSON'
    if not isinstance(value, dict):
        return None, 'artifact JSON must be an object'
    return value, None


def _files_verified(references):
    if not isinstance(references, list) or not references:
        return False
    for item in references:
        if not isinstance(item, dict) or not item.get('path') or not item.get('sha256'):
            return False
        path = Path(item['path'])
        if not path.is_file() or sha256(path) != item['sha256']:
            return False
    return True


def registration_payload_sha256(registration):
    # Receipt reference is excluded to avoid a circular hash between registration and receipt.
    payload = {key: value for key, value in registration.items() if key != 'timestamp_receipt'}
    canonical = json.dumps(payload, sort_keys=True, separators=(',', ':'), ensure_ascii=False).encode('utf-8')
    return hashlib.sha256(canonical).hexdigest()


def _evidence_gates(metadata, source_coverage, replay):
    references = metadata.get('validation_evidence', {})
    dataset = metadata.get('dataset_id')
    expected_hypotheses = {'BASE20', 'FILTER30', 'PROFILE_ONLY_CONTROL'}
    gates = {}
    registration, error = _artifact(references.get('registration'))
    valid_registration = False
    if registration:
        integers = [registration.get(k) for k in ('registered_at_ns', 'confirmation_start_ns', 'confirmation_end_ns')]
        timestamps_valid = all(isinstance(v, Integral) and not isinstance(v, bool) and v >= 0 for v in integers)
        first, last = source_coverage.get('first_event_ns'), source_coverage.get('last_event_ns')
        source_times_valid = all(isinstance(v, Integral) and not isinstance(v, bool) and v >= 0 for v in (first, last))
        receipt, receipt_error = _artifact(registration.get('timestamp_receipt'))
        receipt_valid = bool(receipt and receipt.get('kind') == 'registration_timestamp_receipt'
                             and receipt.get('registration_payload_sha256') == registration_payload_sha256(registration)
                             and receipt.get('registered_at_ns') == registration.get('registered_at_ns')
                             and receipt.get('registry_record_id') and receipt.get('registry_source'))
        valid_registration = bool(timestamps_valid and source_times_valid
                                  and registration.get('kind') == 'prospective_confirmation_registration'
                                  and registration.get('dataset_id') == dataset
                                  and registration.get('data_use_policy') == 'prospective_after_registration'
                                  and set(registration.get('hypotheses', [])) == expected_hypotheses
                                  and integers[0] <= integers[1] <= first <= last <= integers[2]
                                  and _files_verified(registration.get('code_files')) and receipt_valid)
        if not valid_registration:
            error = receipt_error or 'registration chronology, code, dates, hypotheses or receipt not verified'
    gates['prospective_registered_unseen'] = {'passed': valid_registration,
                                             'reason': error or 'inspected dated registration, code hashes and timestamp receipt',
                                             'limit': 'A receipt must come from the stated trusted registry; local files cannot establish absence of any external prior viewing.'}

    coverage, error = _artifact(references.get('coverage'))
    event_files = coverage.get('event_files', []) if coverage else []
    coverage_times = [source_coverage.get('first_event_ns'), source_coverage.get('last_event_ns')]
    valid_coverage_times = all(isinstance(v, Integral) and not isinstance(v, bool) and v >= 0 for v in coverage_times)
    valid_coverage = bool(coverage and coverage.get('kind') == 'source_quote_coverage_audit'
                          and coverage.get('dataset_id') == dataset
                          and metadata.get('source_kind') == 'EXCHANGE_TRADES_BBO'
                          and source_coverage.get('full_quote_updates') is True
                          and coverage.get('full_quote_updates') is True
                          and coverage.get('continuous_registered_sessions') is True
                          and coverage.get('unresolved_market_session_gaps') == []
                          and valid_coverage_times and coverage_times[0] <= coverage_times[1]
                          and coverage.get('first_event_ns') == source_coverage.get('first_event_ns')
                          and coverage.get('last_event_ns') == source_coverage.get('last_event_ns')
                          and metadata.get('events_sha256')
                          and coverage.get('events_sha256') == metadata.get('events_sha256')
                          and any(item.get('sha256') == metadata.get('events_sha256') for item in event_files if isinstance(item, dict))
                          and _files_verified(coverage.get('source_files'))
                          and _files_verified(event_files)
                          and _files_verified(coverage.get('session_calendar_files')))
    gates['source_quote_coverage_inspected'] = {'passed': valid_coverage,
                                               'reason': error or ('inspected coverage audit and hashed source/event/calendar files' if valid_coverage else 'continuous registered-session quote audit incomplete')}

    rules, error = _artifact(references.get('account_rules'))
    cfg = replay.get('config', {})
    keys = ('prop_day_zone', 'prop_daily_fraction', 'prop_total_fraction')
    valid_rules = bool(rules and rules.get('kind') == 'account_rule_execution_verification'
                       and rules.get('dataset_id') == dataset and rules.get('account_profile')
                       and all(rules.get('parameters', {}).get(k) == cfg.get(k) for k in keys)
                       and all(k in cfg for k in keys)
                       and rules.get('source_and_account_execution_equivalent') is True
                       and rules.get('news_and_session_restrictions_checked') is True
                       and _files_verified(rules.get('official_rule_files'))
                       and _files_verified(rules.get('execution_audit_files')))
    gates['account_rules_and_execution_inspected'] = {'passed': valid_rules,
                                                     'reason': error or ('inspected account rules and execution audit' if valid_rules else 'account-specific rules or execution evidence incomplete')}
    return gates


def analyze_replay(replay, market_days=None, metadata=None, source_coverage=None, *,
                   resamples=RESAMPLES, seed=SEED, family_size=FAMILY_SIZE):
    metadata, source_coverage = metadata or {}, source_coverage or {}
    for key in ('config', 'trades', 'daily_equity', 'open_position', 'prop_breaches'):
        if key not in replay:
            raise ValueError('Missing replay evidence field: ' + key)
    supplied = {date.fromisoformat(str(day)).isoformat() for day in (market_days or [])}
    observed = {date.fromisoformat(str(day)).isoformat() for day in replay.get('daily_equity', {})}
    days = sorted(supplied | observed)
    day_sum, day_count = Counter(), Counter()
    trades = replay.get('trades', [])
    zone = ZoneInfo(replay.get('config', {}).get('prop_day_zone', 'Europe/Prague'))
    missing_exit_days = set()
    for trade in trades:
        value = trade['net_R']
        if not math.isfinite(value):
            raise ValueError('Closed trade net_R must be finite')
        exited = trade['exit_ns']
        if isinstance(exited, bool) or not isinstance(exited, Integral) or exited < 0:
            raise ValueError('Closed trade exit_ns must be a nonnegative integer')
        day = datetime.fromtimestamp(exited / 1e9, timezone.utc).astimezone(zone).date().isoformat()
        if day not in days:
            missing_exit_days.add(day)
        day_sum[day] += value
        day_count[day] += 1
    days = sorted(set(days) | missing_exit_days)
    week_rows = []
    if days:
        first, last = date.fromisoformat(days[0]), date.fromisoformat(days[-1])
        monday = first - timedelta(days=first.weekday())
        while monday <= last:
            included = [day for day in days if monday <= date.fromisoformat(day) < monday + timedelta(days=7)]
            week_rows.append({'week_start': monday.isoformat(), 'observed_market_days': len(included),
                              'net_R': sum(day_sum[d] for d in included),
                              'closed_trades': sum(day_count[d] for d in included)})
            monday += timedelta(days=7)
        elapsed_weeks = (last - first).days / 7
    else:
        elapsed_weeks = 0.
    daily = bootstrap_mean_net_R([(day_sum[d], day_count[d]) for d in days],
                                 resamples=resamples, seed=seed, family_size=family_size)
    weekly = bootstrap_mean_net_R([(w['net_R'], w['closed_trades']) for w in week_rows],
                                  resamples=resamples, seed=seed + 1, family_size=family_size)
    count = len(trades)
    frequency = count / len(week_rows) if week_rows else None
    empty_weeks = sum(row['closed_trades'] == 0 for row in week_rows)
    win_rate = sum(t['net_R'] > 0 for t in trades) / count if count else None
    gates = {
        'minimum_sample': {'passed': elapsed_weeks >= 26 and count >= 200,
                           'closed_trades': count, 'required_trades': 200,
                           'elapsed_calendar_weeks': elapsed_weeks, 'required_elapsed_weeks': 26},
        'positive_selection_adjusted_daily_and_weekly': {
            'passed': all(b.get('family_adjusted_lower95') is not None and b['family_adjusted_lower95'] > 0
                          for b in (daily, weekly)),
            'family_size': family_size},
        'frequency_and_win_targets': {'passed': bool(frequency is not None and 5 <= frequency <= 10
                                                    and empty_weeks == 0 and win_rate is not None and win_rate >= .55),
                                     'trades_per_calendar_week': frequency, 'empty_calendar_weeks': empty_weeks,
                                     'win_rate': win_rate, 'win_rate_target_min': .55,
                                     'weekly_frequency_target': [5, 10]},
        'complete_closed_positions_and_no_observed_prop_breach': {
            'passed': replay.get('open_position') is None and not replay.get('prop_breaches', [])},
        'market_day_evidence_consistent': {'passed': not missing_exit_days and (not supplied or observed <= supplied),
                                          'closed_trade_days_missing_from_input': sorted(missing_exit_days),
                                          'observed_days_missing_from_supplied_days': sorted(observed - supplied) if supplied else []}
    }
    gates.update(_evidence_gates(metadata, source_coverage, replay))
    return {'analysis_version': 'fabio_validation_v1', 'dataset_id': metadata.get('dataset_id'),
            'confirmed': all(item['passed'] for item in gates.values()), 'gates': gates,
            'closed_trades': count, 'observed_market_days': len(days),
            'first_observed_day': days[0] if days else None, 'last_observed_day': days[-1] if days else None,
            'calendar_weeks_spanned': len(week_rows), 'elapsed_calendar_weeks': elapsed_weeks,
            'weeks_without_observed_days': sum(w['observed_market_days'] == 0 for w in week_rows),
            'weekly_blocks': week_rows, 'daily_bootstrap': daily, 'weekly_bootstrap': weekly,
            'max_observed_equity_dd_cash': replay.get('max_observed_equity_dd_cash'),
            'daily_observed_equity': replay.get('daily_equity', {}),
            'pass_probability': None,
            'limits': ['Block bootstrap is a conditional resampling description, not a guarantee of future profitability.',
                       'Family correction covers current ES and GC tests (2 markets x3 configurations x2 costs x2 risks =24); the prior131 tracked hypotheses and older searches are not fully corrected.',
                       'These empirical samples remain discovery data; selection adjustment alone does not make them pristine confirmation data.',
                       'Observed equity drawdown misses unobserved source gaps unless full quote coverage is independently audited.',
                       'Confirmation requires the stated hashed evidence; metadata booleans alone are insufficient.',
                       'A positive edge does not determine a prop challenge pass probability.']}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--execution', type=Path, required=True)
    parser.add_argument('--metadata', type=Path, required=True)
    parser.add_argument('--coverage', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    read = lambda p: json.loads(p.read_text(encoding='utf-8'))
    replay, meta, coverage = read(args.execution), read(args.metadata), read(args.coverage)
    result = analyze_replay(replay, None, meta, coverage)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False) + '\n', encoding='utf-8')
    print(json.dumps({'confirmed': result['confirmed'], 'closed_trades': result['closed_trades'],
                      'elapsed_calendar_weeks': result['elapsed_calendar_weeks']}, ensure_ascii=True))


if __name__ == '__main__':
    main()
