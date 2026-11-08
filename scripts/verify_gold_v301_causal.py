"""Verify original native core parity, causal prefixes, and financial ledgers."""
import csv
import json
import math
from datetime import datetime, timezone

import numpy as np

from gold_v301_causal_core import (ROOT, RUN, atr_mt5, atr_wilder, native_zones,
    repaired_report_zones, detect_one)
from research_gold_v301_causal import data, save, sha


def verify_native():
    d = data(); h = d['h1']; b = d['m5']; cached = np.load(RUN/'signals.npz')
    cases = np.load(RUN/'native_cases.npy'); files = RUN/'native_terminal/MQL5/Files/gold_v301'
    done = json.loads((files/'done.json').read_text())
    assert done['completed'] and done['cases'] == len(cases)
    actual = np.loadtxt(files/'actual_iatr.csv', delimiter=',')
    expected_atr = atr_mt5(actual[:,:5])
    np.testing.assert_allclose(actual[30:,5],expected_atr[30:],rtol=0,atol=1e-8)
    nz = np.loadtxt(files/'zones_native.csv', delimiter=',')
    ns = np.loadtxt(files/'signals_native.csv', delimiter=',')
    assert len(ns) == len(cases)
    zone_errors = []; signal_errors = []; zones_checked = 0; signals_checked = 0
    cursor = 0; ptr = cached['h1_ptr']; allzones = cached['native_zones']; m5_atr = cached['m5_atr']
    for ci, (m, last) in enumerate(cases):
        z = allzones[ptr[last]:ptr[last+1]]
        expected = z.copy()
        if len(z):
            source_index = np.where(z[:, 2] == 4, z[:, 7], z[:, 6]).astype(int)
            expected[:, 6] = h[source_index, 0]
            expected = expected[:, [0,1,2,3,4,5,6,8]]
        else:
            expected = np.zeros((0,8))
        end = cursor
        while end < len(nz) and int(nz[end, 0]) == ci:
            end += 1
        got = nz[cursor:end, 1:]; cursor = end
        if got.shape != expected.shape or not np.allclose(got, expected, rtol=0, atol=1e-7):
            if len(zone_errors) < 5:
                zone_errors.append(dict(case=ci, m=int(m), native_rows=len(got), python_rows=len(expected),
                    native=got[:4].tolist(), python=expected[:4].tolist()))
        zones_checked += len(got)
        p = detect_one(b, m5_atr, int(m), z, True)
        found_native = ns[ci, 3] > 0
        found_python = p[2] > 0
        ok = found_native == found_python
        if found_python and found_native:
            direction = p[3]; entry = p[4]; risk = p[6]
            want = [float(direction == 1), p[1], entry, p[5], entry+direction*1.5*risk,
                    entry+direction*2*risk, p[7], p[9]]
            ok = np.allclose(ns[ci, 2:], want, rtol=0, atol=1e-7)
            signals_checked += 1
        if not ok and len(signal_errors) < 8:
            signal_errors.append(dict(case=ci, m=int(m), native=ns[ci].tolist(), python=p.tolist()))
    result = dict(passed=not zone_errors and not signal_errors, cases=len(cases),
        actual_builtin_iATR_rows_checked=len(actual)-30,
        zone_rows_checked=zones_checked, positive_signal_cases_checked=signals_checked,
        zone_errors=zone_errors, signal_errors=signal_errors,
        scope='Verbatim original ScanHtfMacroZones/DetectLtfConfirmation compiled and run by MetaTrader; supplied bars/ATR, idle signal state, notifications/UI stubbed. Not the old EX5 full chart lifecycle.')
    save('NATIVE_PARITY.json', result)
    print(json.dumps(result), flush=True)
    assert result['passed']


def verify_prefixes():
    d = data(); h = d['h1']; b = d['m5']; a = atr_mt5(h)
    rng = np.random.default_rng(301)
    # Actual future changes must not change the already observed snapshots.
    cuts = [int(np.searchsorted(h[:,0], datetime(y,1,1,tzinfo=timezone.utc).timestamp())) for y in range(2022,2027)]
    cuts += rng.integers(2000, len(h)-100, size=20).tolist()
    native_checks = []
    for n in cuts:
        n = min(n,len(h)-1)
        full = native_zones(h,a,n-1)
        prefix = native_zones(h[:n],atr_mt5(h[:n]),n-1)
        np.testing.assert_allclose(full,prefix,rtol=0,atol=1e-8)
        native_checks.append(dict(closed_h1_bars=n,active_zones=len(full)))
    left = int(datetime(2021,10,23,tzinfo=timezone.utc).timestamp())
    hh = h[h[:,0]>=left]; aa = atr_wilder(hh)
    full = repaired_report_zones(hh,aa)
    def key(z):
        return (z['supply'],z['type'],z['distal'],z['proximal'],z['base'],z['flip'],z['active'],z['score'])
    report_checks = []
    for n in [400,1000,3000,6000,10000,15000,20000,25000,len(hh)-1]:
        t = hh[n-1,0]+3600
        prefix = repaired_report_zones(hh[:n],aa[:n])
        before = {key(z) for z in prefix if z['active']<=t<z['end']}
        after = {key(z) for z in full if z['active']<=t<z['end']}
        assert before == after, (n, before-after, after-before)
        report_checks.append(dict(closed_h1_bars=n,active_zones=len(before)))
    # Causal stream checks use the exact latest closed H1 at each decision.
    cached = np.load(RUN/'signals.npz')
    for keyname in ['native','repaired']:
        s = cached[keyname]
        assert np.all(s[:,2] >= s[:,1]+300) and np.all(s[:,6]>=2.5) and np.all(s[:,6]<=10.)
        assert np.all(np.diff(s[:,2])>0)
        assert np.allclose(b[s[:,0].astype(int),0],s[:,1])
    save('PREFIX_VERIFICATION.json',dict(passed=True,native_checks=native_checks,
        repaired_report_checks=report_checks,
        note='Historical snapshots are recomputed on prefixes; full-history interval end dates never veto earlier eligible flips. Signal bar 0 is excluded.'))


def verify_ledger():
    from backtest_gold_v301_causal import fixtures
    save('EXECUTION_FIXTURES.json',fixtures())
    results = json.loads((RUN/'RESULTS.json').read_text(encoding='utf-8'))
    counts = 0
    for name, value in results.items():
        if '_KZ_' not in name: continue
        with (RUN/f'trades_{name}.csv').open(encoding='utf-8-sig') as f:
            rows = list(csv.DictReader(f))
        closed = [r for r in rows if r['reason']!='CENSORED']
        assert len(closed)==value['metrics']['n']
        assert math.isclose(math.fsum(float(r['r']) for r in closed),value['metrics']['net_R'],abs_tol=1e-8)
        assert all(float(rows[i]['exit_time'])<=float(rows[i+1]['entry_time']) for i in range(len(rows)-1))
        for y, metric in value['years'].items():
            r = [x for x in closed if x['year']==y]
            assert len(r)==metric['n']
            assert math.isclose(math.fsum(float(x['r']) for x in r),metric['net_R'],abs_tol=1e-8)
        counts += len(rows)
    manifest = json.loads((RUN/'SOURCE_MANIFEST.json').read_text(encoding='utf-8'))
    assert manifest['originals_unchanged']
    for name, value in manifest['sources'].items():
        assert sha(ROOT/name)==value
    save('VERIFICATION.json',dict(passed=True,kz_ledger_rows_checked=counts,
        original_source_and_ex5_hashes_unchanged=True,
        native_parity=json.loads((RUN/'NATIVE_PARITY.json').read_text())['passed'],
        prefix_checks=json.loads((RUN/'PREFIX_VERIFICATION.json').read_text())['passed'],
        fixtures=json.loads((RUN/'EXECUTION_FIXTURES.json').read_text())))


if __name__=='__main__':
    import sys
    if sys.argv[-1]=='ledger': verify_ledger()
    else:
        verify_native(); verify_prefixes()
