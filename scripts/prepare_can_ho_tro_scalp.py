"""Freeze and read XAUUSD research inputs from an existing MT5 session. No orders."""
from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
RUN = ROOT / 'reports/can_ho_tro_scalp/20261025_v1'
VERSION = 'can_ho_tro_scalp_0.1'


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def write_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + '\n', encoding='utf-8')


def freeze():
    RUN.mkdir(parents=True, exist_ok=True)
    lock = {
        'version': VERSION, 'created_utc': datetime.now(timezone.utc).isoformat(),
        'period_start': '2021-10-25T00:00:00+00:00',
        'period_end_exclusive': '2026-10-25T00:00:00+00:00',
        'warmup_requested_start': '2021-01-01T00:00:00+00:00',
        'data_timestamp_basis': 'MT5 Python UTC API; retain original feed epoch and D1 boundaries',
        'clock_mapping_to_London_NewYork': 'UNVERIFIED; source hour filter is retained in feed timestamp hours',
        'configs': ['C0_NATIVE', 'T05', 'T15', 'TS', 'T05_RG1', 'T15_RG1', 'BODY50_T15_RG1'],
        'costs': [{'id': 'C_A', 'spread': .2, 'slippage_ticks': 0},
                  {'id': 'C_B', 'spread': .3, 'slippage_ticks': 1},
                  {'id': 'C_C', 'spread': .45, 'slippage_ticks': 5}],
        'commission_cash': 0, 'swap_cash': 0,
        'fee_status': 'ZERO_ASSUMPTION_NOT_VERIFIED_BROKER_FEES',
        'tick_size': .01, 'max_spread': .45, 'min_risk': 2., 'max_risk': 20.,
        'market_quote_max_delay_seconds': 60, 'holding_seconds': 21600,
        'pending_seconds': 900, 'room_r': 1.5, 'room_buffer_atr': .10,
        'trail_left': 2, 'trail_right': 2, 'trail_buffer_atr': .25,
        'source_hours': [8, 9, 10, 11, 13, 15, 16, 17],
        'historical_label': 'fixed-spec retrospective chronological blocks; previously inspected data',
        'bootstrap_seed': 20261025, 'bootstrap_resamples': 10000,
        'no_broker_trade_operations': True,
    }
    target = RUN / 'EXPERIMENT_LOCK.json'
    if target.exists():
        existing = json.loads(target.read_text(encoding='utf-8'))
        comparable = {k: v for k, v in existing.items() if k != 'created_utc'}
        assert comparable == {k: v for k, v in lock.items() if k != 'created_utc'}, 'Do not overwrite a changed experiment lock'
    else:
        write_json(target, lock)
    paths = [ROOT / 'duc_tri_can_ho_tro_scalp.mq5', ROOT / 'duc_tri_can_ho_tro_scalp.ex5']
    write_json(RUN / 'ORIGINAL_SOURCE_MANIFEST.json', {
        'purpose': 'Immutable pre-implementation originals; lab uses separate names',
        'files': [{'path': str(p), 'sha256': sha(p), 'bytes': p.stat().st_size} for p in paths],
        'spec_sha256': sha(target),
    })
    print('FROZEN', target, flush=True)


def fetch():
    import MetaTrader5 as mt5
    cfg = json.loads((RUN / 'EXPERIMENT_LOCK.json').read_text(encoding='utf-8'))
    if not mt5.initialize(path=r'C:\Program Files\MetaTrader 5\terminal64.exe', timeout=10000):
        raise RuntimeError(str(mt5.last_error()))
    try:
        terminal, symbol = mt5.terminal_info(), mt5.symbol_info('XAUUSD')
        if not terminal.connected or symbol is None:
            raise RuntimeError('Existing terminal is not connected to XAUUSD history')
        meta = {'retrieved_utc': datetime.now(timezone.utc).isoformat(),
                'terminal_path': terminal.path, 'data_path': terminal.data_path,
                'symbol': symbol.name, 'point': symbol.point, 'tick_size': symbol.trade_tick_size,
                'digits': symbol.digits, 'chart_mode': symbol.chart_mode,
                'contract_size': symbol.trade_contract_size,
                'current_stops_level_points': symbol.trade_stops_level,
                'current_freeze_level_points': symbol.trade_freeze_level,
                'historical_broker_constraints': 'UNKNOWN; research requires correct-side >=1 tick',
                'timestamp_basis': cfg['data_timestamp_basis'],
                'clock_mapping_to_London_NewYork': cfg['clock_mapping_to_London_NewYork']}
        arrays = {}
        start = datetime.fromisoformat(cfg['warmup_requested_start'])
        end = datetime.fromisoformat(cfg['period_end_exclusive'])
        for name, tf in [('m1', mt5.TIMEFRAME_M1), ('m5', mt5.TIMEFRAME_M5), ('h1', mt5.TIMEFRAME_H1), ('d1', mt5.TIMEFRAME_D1)]:
            pieces = []
            for year in range(start.year, end.year + 1):
                left = max(start, datetime(year, 1, 1, tzinfo=timezone.utc))
                right = min(end, datetime(year + 1, 1, 1, tzinfo=timezone.utc))
                if left >= right:
                    continue
                rates = mt5.copy_rates_range('XAUUSD', tf, left, right)
                if rates is not None and len(rates):
                    pieces.append(rates)
                print('FETCH', name, year, 0 if rates is None else len(rates), flush=True)
            if not pieces:
                raise RuntimeError(f'No {name} history: {mt5.last_error()}')
            rates = np.concatenate(pieces)
            rates = rates[np.argsort(rates['time'], kind='stable')]
            _, keep = np.unique(rates['time'], return_index=True)
            rates = rates[np.sort(keep)]
            rates = rates[rates['time'] < int(end.timestamp())]
            arrays[name] = rates
            meta[name] = {'n': len(rates), 'first_epoch': int(rates['time'][0]), 'last_epoch': int(rates['time'][-1])}
        np.savez_compressed(RUN / 'rates.npz', **arrays)
        meta['sha256'] = sha(RUN / 'rates.npz')
        begin = int(datetime.fromisoformat(cfg['period_start']).timestamp())
        meta['h1_warmup_bars'] = int(np.sum(arrays['h1']['time'] + 3600 <= begin))
        meta['full_2000_h1_warmup'] = meta['h1_warmup_bars'] >= 2000
        write_json(RUN / 'data_manifest.json', meta)
        print(json.dumps(meta, ensure_ascii=True), flush=True)
    finally:
        mt5.shutdown()


if __name__ == '__main__':
    import sys
    sys.stdout.reconfigure(encoding='utf-8')
    parser = argparse.ArgumentParser()
    parser.add_argument('command', choices=['freeze', 'fetch'])
    {'freeze': freeze, 'fetch': fetch}[parser.parse_args().command]()
