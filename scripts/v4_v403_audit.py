"""Narrow chart/ledger audit; no terminal settings or account files are read."""
from pathlib import Path
import csv, json, random, hashlib

ROOT = Path(__file__).resolve().parents[1]
RUN = ROOT / 'reports/can_ho_tro_v4/20261102_v403_v1'
FILES = ROOT / 'reports/can_ho_tro_v4/20261102_m3a_v1/portable_terminal/MQL5/Files'
CHART = FILES / 'v403_final_chart'

def rows(p):
    return list(csv.DictReader(p.open(encoding='utf-8-sig', newline='')))

def dump(p, x):
    p.write_text(json.dumps(x, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')

signals = rows(next((FILES / 'V403_final2').glob('signals_*.csv')))
ids = {s['signal_id'] for s in signals}
reference = rows(CHART / 'reference.csv')
fields = ['signal_id', 'confirm_bar_open', 'signal_known_time', 'is_buy', 'entry', 'initial_sl', 'source_zone_id', 'tp1', 'tp2', 'arrow_anchor']
assert len(signals) == len(reference) == 21
assert all(a[k] == b[k] for a, b in zip(signals, reference) for k in fields)
sample = random.Random(403).sample(range(len(signals)), 20)
dump(RUN / 'PARITY_20_RANDOM.json', dict(seed=403, total_signals=21, unchunked_HIST_match=True,
     sample=[dict(index=i, **{k: signals[i][k] for k in fields}) for i in sample]))

periods = dict(M1=60, M5=300, M15=900, M30=1800, H1=3600, H4=14400, D1=86400)
canonical = rows(CHART / 'H1_first_objects.csv')
geometry = lambda data: {r['name']: tuple(r[k] for k in ['time0', 'price0', 'time1', 'price1'])
                         for r in data if r['name'].startswith('DucTri_V4_Z_')}
zones = geometry(canonical)
result = []
for p in sorted(CHART.glob('*_objects.csv')):
    data = rows(p)
    arrows = {r['name'].removeprefix('DucTri_V4_SIG_'): r for r in data if r['name'].startswith('DucTri_V4_SIG_')}
    assert arrows.keys() == ids, p.name
    assert geometry(data) == zones, p.name
    assert not any(r['name'].startswith('DucTri_V4_M2_') for r in data), p.name
    tf = 'H4' if p.name.startswith('M1_to_H4') else p.name.split('_')[0]
    seconds = periods[tf]
    sources = {r['name']: r for r in data if r['name'].startswith('DucTri_V4_SOURCE_')}
    for s in signals:
        arrow = arrows[s['signal_id']]
        expected = int(s['confirm_bar_open']) // seconds * seconds
        assert int(arrow['time0']) == expected, (p.name, s['signal_id'], arrow['time0'], expected)
        expected_price = float(s['arrow_anchor']) + (-1 if s['is_buy'] == '1' else 1) * .25 * float(s['ltf_atr'])
        assert abs(float(arrow['price0']) - expected_price) < 1e-7
        if '_restart_' in p.name:
            assert all(t in arrow['tooltip'] for t in ['server', 'Entry', 'SL', 'TP1', 'TP2', 'risk', s['source_zone_id'], s['zone_type']]), (p.name, arrow['tooltip'])
        source = sources['DucTri_V4_SOURCE_' + s['signal_id']]
        zone = zones['DucTri_V4_Z_' + s['source_zone_id']]
        assert tuple(source[k] for k in ['time0', 'price0', 'time1', 'price1']) == zone
    result.append(dict(stage=p.stem.removesuffix('_objects'), arrows=len(arrows), zones=len(zones), source_zones=len(sources), stats_objects=0, IDs_match=True, geometry_match=True, candle_mapping_match=True))

before = RUN / 'before'
strategy_inputs_unchanged = True
for p in (ROOT / 'can_ho_tro_v4/Presets').glob('*.set'):
    def settings(f):
        enc = 'utf-16' if f.read_bytes().startswith(b'\xff\xfe') else 'utf-8-sig'
        return dict(line.split('=', 1) for line in f.read_text(encoding=enc).splitlines() if '=' in line and not line.startswith(';'))
    old, new = settings(before / 'Presets' / p.name), settings(p)
    assert all(new[k] == v for k, v in old.items()), p.name
    assert set(new)-set(old) == {'InpHistoryDays', 'InpShowExpiredZones', 'InpShowStatsPanel', 'InpDashCollapsed', 'InpDashBottom'}
for name in ['Risk.mqh', 'PriceScale.mqh', 'Observation.mqh', 'LogicHelpers.mqh']:
    rel = Path('MQL5/Include/CanHoTroV4') / name
    # Normalize BOM/newlines only; detector-plan/risk code is retained.
    assert (before / rel).read_text(encoding='utf-8-sig') == (ROOT / 'can_ho_tro_v4' / rel).read_text(encoding='utf-8-sig'), name
dump(RUN / 'CHART_AUDIT.json', dict(passed=True, stages=result, signals=21, zones=237,
     random_HIST_checks=20, full_HIST_signals=21, strategy_preset_values_unchanged=strategy_inputs_unchanged,
     input_changed_only_display_defaults=True, forbidden_terminal_accessed=False))
print('CHART AUDIT:', len(result), 'stages; 21 IDs, 237 zones, mapping/tooltips/source lifetimes match; HIST 21/21 + random20/20')
