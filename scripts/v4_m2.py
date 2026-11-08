"""Prepare/build native M2; Python only serializes fixtures and compares exported results.

The unchanged legacy edge_probe.py is run solely as the separately labelled legacy oracle.
"""
import argparse
import csv
import hashlib
import json
import shutil
import subprocess
from collections import Counter
from datetime import datetime, timezone, timedelta
from pathlib import Path

import numpy as np
from v4_native_m1 import prepare
from v4_build_m1 import compile_source

ROOT = Path(__file__).resolve().parents[1]
RUN = ROOT / 'reports/can_ho_tro_v4/20261101_m2_v1'
M1 = ROOT / 'reports/can_ho_tro_v4/20261101_m1_v2'


def sha(p):
    return hashlib.sha256(p.read_bytes()).hexdigest()


def read(p):
    with p.open(encoding='utf-8-sig', newline='') as f:
        return list(csv.DictReader(f))


def save(name, value):
    (RUN / name).write_text(json.dumps(value, indent=2, ensure_ascii=False, allow_nan=False)+'\n', encoding='utf-8')


def table(path, rows, fields=None):
    with path.open('w', encoding='utf-8-sig', newline='') as f:
        w = csv.DictWriter(f, fieldnames=fields or list(rows[0]))
        w.writeheader(); w.writerows(rows)


def reconcile():
    probe = read(ROOT / 'reports/gold_v301_causal/20261101/signals_MQ5_PREFIX.csv')
    native = read(M1 / 'portable_terminal/MQL5/Files/v4_fixture/compat_idle.csv')
    # Match immutable confirm-bar, side and prices, keeping observed time separate from known time.
    key = lambda t, d, e, s: (int(t), int(d), round(float(e), 8), round(float(s), 8))
    lookup = {key(x['signal_time'], x['direction'], x['entry_close'], x['stop']): x for x in probe}
    extras, time_diff, matched = [], [], 0
    for n in native:
        p = lookup.get(key(n['confirm_bar_open'], n['direction'], n['entry'], n['sl']))
        if p is None:
            extras.append(n)
        else:
            matched += 1
            if n['signal_known_time'] != p['known_at']:
                time_diff.append(dict(confirm_bar_open=n['confirm_bar_open'], native_known=n['signal_known_time'],
                                      native_observed=n['publish_time'], probe_known=p['known_at'],
                                      reason='PROBE_LABELS_NEXT_OBSERVED_M5_OPEN_AS_KNOWN_ACROSS_GAP'))
    table(RUN / 'IDLE_60_EXTRA.csv', extras)
    table(RUN / 'IDLE_TIME_DIFFERENCES.csv', time_diff)
    result = dict(native=len(native), probe=len(probe), matching_confirm_side_prices=matched, extras=len(extras),
                  extra_min=min(int(x['signal_known_time']) for x in extras),
                  extra_max=max(int(x['signal_known_time']) for x in extras),
                  evaluation_start=1634947200, all_extras_before_start=all(int(x['confirm_bar_open']) < 1634947200 for x in extras),
                  timestamp_semantic_differences=len(time_diff),
                  all_probe_known_equal_native_observed=all(x['probe_known']==x['native_observed'] for x in time_diff),
                  cause='Probe filters confirm_bar_open >= 2021-10-23; M1 fixture evaluates all saved bars. Not pre-2021-10-01 warmup.')
    save('IDLE_RECONCILIATION.json', result)
    assert matched == len(probe) and len(extras) == 60 and result['all_extras_before_start']
    return probe


def setup():
    RUN.mkdir(parents=True, exist_ok=False)
    probe = reconcile()  # Required before any scorecard parity calculation.
    portable = RUN / 'portable_terminal'
    source_portable = M1 / 'portable_terminal'
    for name in ('terminal64.exe', 'MetaEditor64.exe', 'metatester64.exe'):
        portable.mkdir(exist_ok=True)
        shutil.copy2(source_portable / name, portable / name)
    shutil.copytree(source_portable / 'MQL5/Include', portable / 'MQL5/Include')
    prepare(RUN)
    shutil.copytree(ROOT / 'can_ho_tro_v4/MQL5', portable / 'MQL5', dirs_exist_ok=True)
    files = portable / 'MQL5/Files/v4_fixture'
    with (files / 'probe_signals.csv').open('w', newline='') as f:
        csv.writer(f).writerows((i, x['known_at'], x['direction'], x['stop']) for i, x in enumerate(probe))
    recovered = read(ROOT / 'reports/gold_live_review/20261101/RECOVERED_CLOSED_TRADES.csv')
    with (files / 'recovered.csv').open('w', newline='') as f:
        csv.writer(f).writerows((x['entry_ticket'], 1 if x['direction']=='buy' else -1, x['entry_epoch'], x['exit_epoch'],
                                x['entry_price'], x['exit_price'], x['entry_volume'], x['gross_profit']) for x in recovered)
    bars = np.load(ROOT / 'reports/scalp_structure_lab/20261025_pilot_v1/rates.npz')['m1']
    a = np.column_stack([bars[x] for x in ('time', 'open', 'high', 'low', 'close')] + [np.zeros(len(bars))])
    np.savetxt(files / 'm1.csv', a, delimiter=',', fmt=['%d', '%.10f', '%.10f', '%.10f', '%.10f', '%.1f'])
    lock_files = list((ROOT/'can_ho_tro_v4').rglob('*.mqh')) + list((ROOT/'can_ho_tro_v4').rglob('*.mq5'))
    lock_files += [ROOT/'tests/v4/TestV4M2.mq5', Path(__file__), files/'probe_signals.csv', files/'m1.csv', files/'recovered.csv']
    save('M2_RULES_LOCK.json', dict(created_vn=datetime.now(timezone(timedelta(hours=7))).isoformat(),
         timeout='240 wall-clock minutes since known; first executable quote at/after deadline; no later H/L',
         legacy='same frozen 5164 input signals; bid-only; 240 observed M1 bars; separate fixed 0.39/risk net cost',
         main='native V4 1393 published signals; HIST M1; spread .30, slip .01 each fill, roundtrip commission 7/lot; gold tick .01/$1',
         sources={str(p.relative_to(ROOT)):sha(p) for p in lock_files}, retrospective=True))
    print('PREPARED: reconciliation 5164 matched + 60 before evaluation start; lock saved', flush=True)


def build(label):
    portable = RUN / 'portable_terminal'
    shutil.copytree(ROOT / 'can_ho_tro_v4/MQL5', portable / 'MQL5', dirs_exist_ok=True)
    prepare(RUN)
    snapshot=RUN/f'build_inputs_{label}'
    shutil.copytree(ROOT/'can_ho_tro_v4/MQL5',snapshot/'MQL5',ignore=shutil.ignore_patterns('*.ex5'))
    shutil.copytree(portable/'MQL5/Scripts/V4',snapshot/'tests',ignore=shutil.ignore_patterns('*.ex5'))
    shutil.copy2(Path(__file__),snapshot/'v4_m2.py')
    (snapshot/'SHA256.json').write_text(json.dumps({str(p.relative_to(snapshot)):sha(p)
        for p in snapshot.rglob('*') if p.is_file()},indent=2)+'\n',encoding='utf-8')
    results = {}
    test_name='TestV4M2Final' if label.startswith('final') else 'TestV4M2'
    for name, rel in [('test', f'Scripts/V4/{test_name}.mq5'), ('indicator', 'Indicators/duc_tri_can_ho_tro_v4.mq5')]:
        results[name] = compile_source(portable, portable/'MQL5'/rel, RUN/f'COMPILE_M2_{name}_{label}.log')
    save(f'BUILD_{label}.json', results)
    if not all(x['passed'] for x in results.values()):
        raise SystemExit(1)
    shutil.copy2(portable/'MQL5/Indicators/duc_tri_can_ho_tro_v4.ex5', ROOT/'can_ho_tro_v4/MQL5/Indicators/duc_tri_can_ho_tro_v4.ex5')
    print('BUILD: test + indicator 0 errors, 0 warnings', flush=True)


def run(label):
    portable = RUN / 'portable_terminal'
    ini = RUN/f'M2_{label}.ini'
    test_name='TestV4M2Final' if label.startswith('final') else 'TestV4M2'
    ini.write_text('[Common]\nLogin=0\nServer=MetaQuotes-Demo\nNewsEnable=0\n[Experts]\nEnabled=1\nAllowLiveTrading=0\nAllowDllImport=0\n'
                   f'[StartUp]\nScript=V4\\{test_name}\nSymbol=_CHT_M5_20261025\nPeriod=M1\nShutdownTerminal=1\n', encoding='ascii')
    startup = subprocess.STARTUPINFO(); startup.dwFlags |= subprocess.STARTF_USESHOWWINDOW; startup.wShowWindow = 0
    p = subprocess.Popen(f'"{portable / "terminal64.exe"}" /portable /config:"{ini}"', cwd=portable, startupinfo=startup)
    print('NATIVE_STARTED',p.pid,flush=True)
    code = p.wait()
    save(f'EXIT_{label}.json', dict(pid=p.pid, exit_code=code, user_terminal_touched=False))
    print('NATIVE_ENDED',code,flush=True)


def analyze():
    files = RUN/'portable_terminal/MQL5/Files/v4_fixture'
    # Original legacy execution oracle, unchanged, explicitly separate from production MQL5.
    if not (RUN/'LEGACY_ORACLE.json').exists():
        with (RUN/'LEGACY_ORACLE.log').open('w') as log:
            subprocess.run(['python', str(ROOT/'reports/claude_signal_edge_probe/20261101/edge_probe.py'),
                            str(ROOT), str(RUN/'LEGACY_ORACLE.json')], stdout=log, stderr=subprocess.STDOUT, check=True)
    oracle = json.loads((RUN/'LEGACY_ORACLE.json').read_text())
    oracle = [x for x in oracle if x['kind']=='SIG']
    native = [x for x in read(files/'legacy_native.csv') if x['valid']=='1']
    # Both retain source order; invalid stops and entry gaps are excluded identically.
    assert len(oracle)==len(native)
    rows=[]
    for a,b in zip(oracle,native):
        rows.append(dict(id=b['id'], known=b['known'], risk_delta=float(b['risk'])-a['risk'],
                         tp1_delta=float(b['tp1_R'])-a['tp1.0'], trail_delta=float(b['trail_R'])-a['trail'],
                         time_equal=int(b['known'])==a['t'], side_equal=int(b['side'])==a['dirn']))
    table(RUN/'LEGACY_PARITY.csv', rows)
    save('LEGACY_PARITY.json',dict(rows=len(rows), tolerance_R=1e-8,
         max_tp1_delta=max(abs(x['tp1_delta']) for x in rows), max_trail_delta=max(abs(x['trail_delta']) for x in rows),
         failures=sum(abs(x['tp1_delta'])>1e-8 or abs(x['trail_delta'])>1e-8 or not x['time_equal'] or not x['side_equal'] for x in rows)))
    exposures=read(files/'normal_zone_exposure.csv')
    flagged=[x for x in exposures if x['over_tests']=='1' or x['over_age']=='1']
    save('NORMAL_ZONE_EXPOSURE.json',dict(normal_signals=len(exposures),over_tests=sum(x['over_tests']=='1' for x in exposures),
         over_age=sum(x['over_age']=='1' for x in exposures),union=len(flagged),examples=flagged[:5],default_behavior_unchanged=True))
    diff=read(M1/'DIFF_V301_V4.csv'); count=Counter((x['reason'], x['compat_present'], x['v4_present']) for x in diff)
    table(RUN/'SIGNAL_CHANGE_BY_REASON.csv',[dict(reason=k[0],compat=k[1],v4=k[2],count=v,
          delta=v*((k[2]=='True')-(k[1]=='True'))) for k,v in sorted(count.items())])
    assert sum(v*((k[2]=='True')-(k[1]=='True')) for k,v in count.items())==1393-2363
    score=read(files/'scorecard_hist.csv')
    summary={}
    for rule in ('0','1'):
        subset=[x for x in score if x['signal_id'].endswith('_'+rule)]
        closed=[x for x in subset if x['filled']=='1' and x['closed']=='1']
        net=[float(x['net_R']) for x in closed]; gross=[float(x['gross_R']) for x in closed]
        profit=sum(x for x in net if x>0); loss=-sum(x for x in net if x<0)
        summary[rule]=dict(signals=len(subset), closed=len(closed), win_percent=100*sum(x>0 for x in net)/len(net),
             mean_gross_R=float(np.mean(gross)),mean_net_R=float(np.mean(net)),PF_R=profit/loss if loss else None,
             median_cost_R=float(np.median([float(x['cost_R']) for x in closed])),reasons=dict(Counter(x['reason'] for x in subset)))
    save('SCORECARD_HIST_SUMMARY.json',summary)
    recovered=read(files/'journal_recovered.csv')
    save('JOURNAL_ACCEPTANCE.json',dict(recovered_rows=len(recovered), max_fixture_accounting_error=max(abs(float(x['error'])) for x in recovered),
         real_demo_gold_deals=0, actual_history_22_trades_verified=False,
         reason='gold_live_review COLLECTION has only balance deposit; recovered rows are chart-derived gross values, no initial SL/commission/swap provenance.',
         note='Native fixture calculates gross from recovered prices/volume under an assumed $100 per price-unit per lot; actual fees and SL unavailable. Not broker-deal verification.'))
    print(json.dumps(dict(native=json.loads((files/'m2_result.json').read_text()),
                          parity=json.loads((RUN/'LEGACY_PARITY.json').read_text()),summary=summary),ensure_ascii=True))


if __name__=='__main__':
    p=argparse.ArgumentParser(); p.add_argument('action',choices=['prepare','build','run','analyze']); p.add_argument('--label',default='r1')
    a=p.parse_args()
    {'prepare':setup,'build':lambda:build(a.label),'run':lambda:run(a.label),'analyze':analyze}[a.action]()
