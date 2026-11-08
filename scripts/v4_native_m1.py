"""Prepare/run native V4 fixtures; Python never evaluates a trading detector."""
from pathlib import Path
import argparse
import csv
import hashlib
import json
import shutil
import subprocess
import time

from v4_port_m1 import function
from v4_build_m1 import compile_source

ROOT = Path(__file__).resolve().parents[1]


def prepare(run):
    portable = run / 'portable_terminal'
    files = portable / 'MQL5/Files/v4_fixture'
    files.mkdir(parents=True, exist_ok=True)
    frozen = ROOT / 'reports/gold_v301_causal/20261101/native_terminal/MQL5/Files/gold_v301'
    for name in ['h1.csv', 'm5.csv']:
        shutil.copy2(frozen / name, files / name)
    testdir = portable / 'MQL5/Scripts/V4'
    shutil.copytree(ROOT / 'tests/v4', testdir, dirs_exist_ok=True)
    original = (ROOT / 'duc_tri_can_ho_tro.mq5').read_text(encoding='utf-8-sig')
    (testdir / 'PlanStateV301.mqh').write_text(function(original, 'void ManageActiveSignal(double curPrice)'), encoding='utf-8')
    definition = original[original.index('enum ENUM_LANG'):original.index('CCanvas              g_canvas;')]
    import re
    definition = re.sub(r'^input group .*$', '', definition, flags=re.M)
    definition = re.sub(r'^input\s+', '', definition, flags=re.M)
    (testdir / 'OracleV301.mqh').write_text(definition, encoding='utf-8')
    funcs = '\n\n'.join(function(original, sig) for sig in [
        'void ScanHtfMacroZones()', 'bool IsInKillzone(datetime barTime)',
        'void DetectLtfConfirmation(bool isFirstRun = false)'])
    (testdir / 'OracleFunctions.mqh').write_text(funcs, encoding='utf-8')
    shutil.copytree(ROOT / 'can_ho_tro_v4/MQL5/Include/CanHoTroV4',
                    portable / 'MQL5/Include/CanHoTroV4', dirs_exist_ok=True)
    # IsInKillzone remains exactly the original function for both implementations.
    (testdir / 'KillzoneV301.mqh').write_text(function(original, 'bool IsInKillzone(datetime barTime)'), encoding='utf-8')
    # Native-only observability copy: unchanged detector branch plus RR rejection logging.
    shared = (ROOT / 'can_ho_tro_v4/MQL5/Include/CanHoTroV4/Signals.mqh').read_text(encoding='utf-8')
    marker = '                continue;\n            double rrMacro'
    observed = ('             {\n'
                '                if(g_v4RrTraceFile!=INVALID_HANDLE && InpCompatV301)\n'
                '                   FileWrite(g_v4RrTraceFile,(long)ltfRates[cBar].time,isBuySignal?1:-1,\n'
                '                      V4ZoneId(g_zones[z].timeStart,g_zones[z].isSupply,g_zones[z].distal,g_zones[z].proximal),\n'
                '                      DoubleToString(rr1,16),DoubleToString(rr2,16),DoubleToString(MinRR,16),V4RrAllowed(rr1,rr2));\n'
                '                continue;\n             }\n            double rrMacro')
    assert shared.count(marker)==1
    traced = shared.replace(marker,observed)
    selected = ('      if(g_v4SweepTraceFile!=INVALID_HANDLE && InpCompatV301 && g_v4SelectedFrame)\n'
                '         FileWrite(g_v4SweepTraceFile,(long)g_v4Now,\n'
                '            V4ZoneId(g_zones[z].timeStart,g_zones[z].isSupply,g_zones[z].distal,g_zones[z].proximal),\n'
                '            (long)g_zones[z].timeKnown,(long)ltfRates[sweepBar].time,confirmBar,\n'
                '            ltfRates[sweepBar].time<g_zones[z].timeKnown);\n')
    traced = traced.replace('      if(confirmBar >= 1)', selected+'      if(confirmBar >= 1)')
    (testdir / 'TraceSignals.mqh').write_text(traced,encoding='utf-8')
    core = (ROOT / 'tests/v4/TestV4Core.mq5').read_text(encoding='utf-8')
    (testdir / 'TestV4TraceCore.mqh').write_text(core.replace('<CanHoTroV4/Signals.mqh>','"TraceSignals.mqh"'),encoding='utf-8')
    # Only a custom offline symbol is seeded. No broker accounts/config are copied.
    seed = ROOT / 'reports/scalp_structure_lab/20261025_pilot_v1/fixture_terminal'
    (portable / 'bases').mkdir(exist_ok=True)
    if not (portable / 'bases/symbols.custom.dat').exists():
        shutil.copy2(seed / 'bases/symbols.custom.dat', portable / 'bases/symbols.custom.dat')
    rel = Path('bases/Custom/history/_CHT_M5_20261025')
    if not (portable / rel).exists():
        shutil.copytree(seed / rel, portable / rel)
    return testdir


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--run', required=True)
    p.add_argument('--name', default='TestV4Core')
    p.add_argument('--label', required=True)
    p.add_argument('--expert', action='store_true')
    p.add_argument('--period', default='M1')
    a = p.parse_args()
    run = ROOT / a.run
    testdir = prepare(run)
    portable = run / 'portable_terminal'
    if a.expert:
        target = portable / 'MQL5/Experts/V4'
        shutil.copytree(testdir, target, dirs_exist_ok=True)
        testdir = target
    snapshot = run / 'build_inputs' / (a.name + '_' + a.label)
    shutil.copytree(ROOT / 'can_ho_tro_v4/MQL5/Include/CanHoTroV4', snapshot / 'CanHoTroV4')
    shutil.copytree(testdir, snapshot / 'tests', ignore=shutil.ignore_patterns('*.ex5'))
    inputs = {str(f.relative_to(snapshot)): hashlib.sha256(f.read_bytes()).hexdigest()
              for f in snapshot.rglob('*') if f.is_file()}
    (snapshot / 'SHA256.json').write_text(json.dumps(inputs, indent=2), encoding='utf-8')
    build = compile_source(portable, testdir / (a.name + '.mq5'), run / f'COMPILE_{a.name}_{a.label}.log')
    (run / f'BUILD_{a.name}_{a.label}.json').write_text(json.dumps(build, indent=2)+'\n', encoding='utf-8')
    if not build['passed']:
        raise SystemExit(1)
    ini = run / f'{a.name}_{a.label}.ini'
    ini.write_text('[Common]\nLogin=0\nServer=MetaQuotes-Demo\nNewsEnable=0\n'
                   '[Experts]\nEnabled=1\nAllowLiveTrading=0\nAllowDllImport=0\n'
                   '[StartUp]\n'+('Expert' if a.expert else 'Script')+'=V4\\'+a.name+'\nSymbol=_CHT_M5_20261025\n'
                   'Period='+a.period+'\nShutdownTerminal=1\n', encoding='ascii')
    startup = subprocess.STARTUPINFO()
    startup.dwFlags |= subprocess.STARTF_USESHOWWINDOW
    startup.wShowWindow = 0
    command = f'"{portable / "terminal64.exe"}" /portable /config:"{ini}"'
    proc = subprocess.Popen(command, cwd=portable, startupinfo=startup)
    (run / f'PROCESS_{a.name}_{a.label}.json').write_text(json.dumps(
        dict(pid=proc.pid, command=command, started=time.time(), user_terminal_touched=False), indent=2), encoding='utf-8')
    print('NATIVE_STARTED', proc.pid, a.name, flush=True)
    # Keep command sessions pollable; no unrelated terminal process is stopped.
    code = proc.wait()
    print('NATIVE_ENDED', code, flush=True)
    (run / f'EXIT_{a.name}_{a.label}.json').write_text(json.dumps(dict(exit_code=code)), encoding='utf-8')


if __name__ == '__main__':
    main()
