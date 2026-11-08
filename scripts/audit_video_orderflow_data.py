"""Audit frozen bar data for the Fabio video study; never connects to a broker."""
from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DATA = ROOT / 'reports/can_ho_tro_scalp/20261025_v1/rates.npz'
DEFAULT_OUTPUT = ROOT / 'reports/2026-11-01_video_tvERE-Beu2U/DATA_FEASIBILITY.json'


def audit_bars(bars):
    names = set(bars.dtype.names or ())
    if not {'time', 'open', 'high', 'low', 'close'} <= names or len(bars) == 0:
        raise ValueError('Expected nonempty structured OHLC bars with epoch timestamps')
    if np.any(np.diff(bars['time']) <= 0):
        raise ValueError('Bar times must be strictly increasing')
    result = {'bars': len(bars), 'fields': list(bars.dtype.names),
              'first_epoch': int(bars['time'][0]), 'last_epoch': int(bars['time'][-1])}
    for name in ('tick_volume', 'real_volume'):
        result[name] = ({'nonzero_bars': int(np.count_nonzero(bars[name])),
                         'min': int(bars[name].min()), 'max': int(bars[name].max())}
                        if name in names else None)
    # Even positive bar volume cannot recover the sequence or volume at each price.
    result.update(executed_volume_at_price_available=False,
                  aggressor_side_available=False, event_sequence_available=False,
                  faithful_video_execution_replay_possible=False)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--data', type=Path, default=DEFAULT_DATA)
    parser.add_argument('--output', type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    digest = hashlib.sha256()
    with args.data.open('rb') as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b''):
            digest.update(chunk)
    with np.load(args.data, allow_pickle=False) as arrays:
        timeframes = {name: audit_bars(arrays[name]) for name in arrays.files}
    result = {
        'study': 'tvERE-Beu2U', 'user_date': '2026-11-01',
        'audit_utc': datetime.now(timezone.utc).isoformat(),
        'source_path': str(args.data.resolve()), 'source_sha256': digest.hexdigest(),
        'timeframes': timeframes,
        'feed_to_New_York_clock_verified': False,
        'historical_data_previously_examined': True,
        'strategy_backtest_run': False, 'new_trading_hypotheses_tested': 0,
        'reason': 'OHLC bars lack executed volume at price, aggressor side and event sequence.',
        'required_minimum': ['contract_id', 'exchange_timestamp', 'event_sequence',
                             'trade_price', 'trade_quantity', 'aggressor_side_or_documented_classification',
                             'best_bid', 'best_ask', 'contract_tick_size', 'contract_tick_value',
                             'session_calendar_and_roll_policy', 'execution_fees_and_latency_model'],
        'optional_for_extended_models': ['depth_updates', 'order_id', 'queue_position'],
        'notes': ['MBO is needed for order/queue claims, not automatically for a basic trade-print/CVD model.',
                  'A quote price increase is not proof of an executed aggressive buy.',
                  'Bar real_volume alone would still be insufficient even if nonzero.',
                  'A CFD adaptation is a new hypothesis, not a replication of the video.'],
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({'output': str(args.output.resolve()), 'source_sha256': digest.hexdigest(),
                      'bars': {name: item['bars'] for name, item in timeframes.items()},
                      'strategy_backtest_run': False}, ensure_ascii=True))


if __name__ == '__main__':
    main()
