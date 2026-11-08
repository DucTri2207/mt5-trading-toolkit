"""Compile and exercise the separate US100 indicator in a dedicated offline terminal."""
import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path

import numpy as np

import build_fabio_orderflow_indicator as compiler
from collect_us100_ny import ROOT, RUN, sha, write_json
from us100_ny_core import detect, features, make_plan, COSTS, session_time


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--compile-only', action='store_true')
    args = parser.parse_args()
    out = RUN / 'indicator'; out.mkdir(parents=True, exist_ok=True)
    compiler.RUN = out
    source = ROOT / 'duc_tri_us100_ny_pullback_lab.mq5'
    test = ROOT / 'tests/mql5/TestUs100NyPullback.mq5'
    builds = [compiler.compile_one(source, 'indicator'), compiler.compile_one(test, 'native_checks')]
    write_json(out / 'BUILD.json', dict(builds=builds, user_terminal_install=False))
    if args.compile_only:
        print('COMPILED', json.dumps(builds), flush=True); return
    sys.path.insert(0, str(ROOT / 'tests'))
    from test_us100_ny import fixture
    b = fixture(); f, s, a, w = features(b)
    signals = detect(b); assert len(signals) == 2
    native = out / 'fixture_terminal'
    files = native / 'MQL5/Files/us100_ny_fixture'; files.mkdir(parents=True, exist_ok=True)
    (native / 'MQL5/Scripts').mkdir(exist_ok=True); (native / 'MQL5/Indicators').mkdir(exist_ok=True)
    shutil.copy2(compiler.TERMINAL, native / 'terminal64.exe')
    (native / 'bases').mkdir(exist_ok=True)
    shutil.copy2(compiler.SEED_FIXTURE / 'bases/symbols.custom.dat', native / 'bases/symbols.custom.dat')
    seed = Path('bases/Custom/history/_CHT_M5_20261025')
    shutil.copytree(compiler.SEED_FIXTURE / seed, native / seed, dirs_exist_ok=True)
    shutil.copy2(source.with_suffix('.ex5'), native / 'MQL5/Indicators' / source.with_suffix('.ex5').name)
    shutil.copy2(test.with_suffix('.ex5'), native / 'MQL5/Scripts' / test.with_suffix('.ex5').name)
    np.savetxt(files / 'bars.csv', b, delimiter=',', fmt=['%d']+['%.9f']*4)
    plans = []
    for signal in signals:
        i = np.searchsorted(b[:, 0], signal.known_at)
        if i < len(b) and b[i, 0] == signal.known_at and session_time(signal.known_at):
            p = make_plan(signal, b[i, 1], b[i, 1]+2., COSTS[1])
            assert p is not None
            plans.append([signal.known_at, signal.direction, p['entry'], p['stop'], p['target']])
    np.savetxt(files / 'expected_plans.csv', plans, delimiter=',', fmt=['%d','%d','%.9f','%.9f','%.9f'])
    ini = out / 'fixture.ini'
    ini.write_text('[Common]\nLogin=0\nServer=MetaQuotes-Demo\n[Experts]\nEnabled=0\nAllowLiveTrading=0\nAllowDllImport=0\n[StartUp]\nScript=TestUs100NyPullback\nSymbol=_CHT_M5_20261025\nPeriod=M1\nShutdownTerminal=1\n', encoding='ascii')
    result_path = files / 'result.json'
    if result_path.exists():
        result_path.unlink()
    proc = subprocess.Popen(f'"{native / "terminal64.exe"}" /portable /config:"{ini}"',
                            cwd=str(native), startupinfo=compiler.hidden())
    write_json(out / 'FIXTURE_PROCESS.json', dict(pid=proc.pid, path=str(native / 'terminal64.exe')))
    try:
        exit_code = proc.wait(timeout=45)
    except subprocess.TimeoutExpired:
        proc.terminate(); proc.wait(timeout=10)
        raise RuntimeError('Dedicated fixture timed out; terminated only its own process')
    if not result_path.exists():
        raise RuntimeError(f'Native fixture produced no result; exit {exit_code}')
    result = json.loads(result_path.read_text(encoding='utf-8-sig'))
    native_rows = np.loadtxt(files / 'core_native.csv', delimiter=',')
    expected = np.column_stack((b[:, 0], f, s, a, w))
    np.testing.assert_allclose(native_rows[:, :5], expected, atol=1e-8, rtol=0)
    got_signals = native_rows[native_rows[:, 5] != 0, 5:]
    np.testing.assert_allclose(got_signals, [[z.direction, z.known_at, z.extreme] for z in signals], atol=1e-8, rtol=0)
    result['python_native_feature_and_signal_parity_rows'] = len(b)
    write_json(out / 'NATIVE_CHECKS.json', result)
    if result['failures']:
        raise AssertionError(str(result))
    shutil.copy2(files / 'INDICATOR_FIXTURE.png', out / 'INDICATOR_FIXTURE.png')
    print('NATIVE_PASSED', json.dumps(result), flush=True)


if __name__ == '__main__':
    main()
