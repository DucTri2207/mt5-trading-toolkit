"""Compile the separate Fabio bridge and run parser fixtures in an isolated portable terminal."""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RUN = ROOT / 'reports/2026-11-01_video_tvERE-Beu2U/implementation/indicator'
EDITOR = Path('C:/Program Files/MetaTrader 5/MetaEditor64.exe')
SEED_FIXTURE = ROOT / 'reports/scalp_structure_lab/20261025_pilot_v1/fixture_terminal'
TERMINAL = SEED_FIXTURE / 'terminal64.exe'


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def hidden():
    startup = subprocess.STARTUPINFO()
    startup.dwFlags |= subprocess.STARTF_USESHOWWINDOW
    startup.wShowWindow = 0
    return startup


def compile_one(source, label):
    log = RUN / f'compile_{label}.log'
    if log.exists():
        log.unlink()
    started = time.time()
    result = subprocess.run(f'"{EDITOR}" /compile:"{source}" /log:"{log}"', startupinfo=hidden(), timeout=90)
    raw = log.read_bytes()
    text = raw.decode('utf-16') if raw.startswith(b'\xff\xfe') else raw.decode('utf-8-sig')
    binary = source.with_suffix('.ex5')
    if not re.search(r'Result:\s*0 errors,\s*0 warnings', text) or not binary.exists() or binary.stat().st_mtime < started - 2:
        raise RuntimeError(text)
    return {'source': str(source), 'source_sha256': sha(source), 'binary': str(binary),
            'binary_sha256': sha(binary), 'compiler_exit_code': result.returncode,
            'diagnostics': '0 errors, 0 warnings', 'log': str(log)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--compile-only', action='store_true')
    args = parser.parse_args()
    RUN.mkdir(parents=True, exist_ok=True)
    indicator = ROOT / 'duc_tri_fabio_orderflow_lab.mq5'
    native = ROOT / 'tests/mql5/TestFabioOrderflowBridge.mq5'
    visual = ROOT / 'tests/mql5/TestFabioOrderflowIndicator.mq5'
    builds = [compile_one(indicator, 'indicator'), compile_one(native, 'parser_fixture'), compile_one(visual, 'indicator_fixture')]
    record = {'created_utc': datetime.now(timezone.utc).isoformat(), 'builds': builds,
              'native_fixture': None, 'installed_in_user_terminal': False, 'live_chart_attached': False}
    if not args.compile_only:
        fixture = RUN / 'fixture_terminal'
        (fixture / 'MQL5/Scripts').mkdir(parents=True, exist_ok=True)
        (fixture / 'MQL5/Indicators').mkdir(parents=True, exist_ok=True)
        exe = fixture / 'terminal64.exe'
        if not exe.exists() or sha(exe) != sha(TERMINAL):
            shutil.copy2(TERMINAL, exe)
        (fixture / 'bases').mkdir(exist_ok=True)
        shutil.copy2(SEED_FIXTURE / 'bases/symbols.custom.dat', fixture / 'bases/symbols.custom.dat')
        seed_history = Path('bases/Custom/history/_CHT_M5_20261025')
        shutil.copytree(SEED_FIXTURE / seed_history, fixture / seed_history, dirs_exist_ok=True)
        shutil.copy2(native.with_suffix('.ex5'), fixture / 'MQL5/Scripts/TestFabioOrderflowBridge.ex5')
        shutil.copy2(visual.with_suffix('.ex5'), fixture / 'MQL5/Scripts/TestFabioOrderflowIndicator.ex5')
        shutil.copy2(indicator.with_suffix('.ex5'), fixture / 'MQL5/Indicators/duc_tri_fabio_orderflow_lab.ex5')
        ini = RUN / 'fixture.ini'
        ini.write_text('[Common]\nLogin=0\nServer=MetaQuotes-Demo\n[Experts]\nEnabled=0\nAllowLiveTrading=0\nAllowDllImport=0\n[StartUp]\nScript=TestFabioOrderflowBridge\nSymbol=_CHT_M5_20261025\nPeriod=M1\nShutdownTerminal=1\n', encoding='ascii')
        output = fixture / 'MQL5/Files/fabio_orderflow_fixture/result.json'
        if output.exists():
            output.unlink()
        proc = subprocess.Popen(f'"{exe}" /portable /config:"{ini}"', cwd=str(fixture), startupinfo=hidden())
        (RUN / 'fixture_process.json').write_text(json.dumps({'pid': proc.pid, 'path': str(exe), 'ini': str(ini)}, indent=2), encoding='utf-8')
        try:
            exit_code = proc.wait(timeout=50)
        except subprocess.TimeoutExpired:
            record['native_fixture'] = {'status': 'running', 'pid': proc.pid}
        else:
            if not output.exists():
                raise RuntimeError(f'Isolated terminal ended without fixture output, exit={exit_code}')
            result = json.loads(output.read_text(encoding='utf-8-sig'))
            if result['failures'] != 0:
                raise RuntimeError(str(result))
            record['native_fixture'] = {'status': 'passed', 'terminal_exit_code': exit_code, **result}
            shutil.copy2(output, RUN / 'NATIVE_FIXTURE.json')
            visual_ini = RUN / 'indicator_fixture.ini'
            visual_ini.write_text(ini.read_text(encoding='ascii').replace('Script=TestFabioOrderflowBridge', 'Script=TestFabioOrderflowIndicator'), encoding='ascii')
            visual_output = output.with_name('indicator_result.json')
            if visual_output.exists():
                visual_output.unlink()
            visual_proc = subprocess.Popen(f'"{exe}" /portable /config:"{visual_ini}"', cwd=str(fixture), startupinfo=hidden())
            (RUN / 'indicator_fixture_process.json').write_text(json.dumps({'pid': visual_proc.pid, 'path': str(exe), 'ini': str(visual_ini)}, indent=2), encoding='utf-8')
            try:
                visual_exit = visual_proc.wait(timeout=35)
            except subprocess.TimeoutExpired:
                record['indicator_fixture'] = {'status': 'running', 'pid': visual_proc.pid}
            else:
                if not visual_output.exists():
                    raise RuntimeError(f'Isolated indicator fixture ended without output, exit={visual_exit}')
                visual_result = json.loads(visual_output.read_text(encoding='utf-8-sig'))
                if visual_result['failures'] != 0:
                    raise RuntimeError(str(visual_result))
                record['indicator_fixture'] = {'status': 'passed', 'terminal_exit_code': visual_exit, **visual_result}
                shutil.copy2(visual_output, RUN / 'INDICATOR_FIXTURE.json')
                shutil.copy2(output.with_name('indicator_fixture.png'), RUN / 'INDICATOR_FIXTURE.png')
    (RUN / 'BUILD.json').write_text(json.dumps(record, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(record, ensure_ascii=True))


if __name__ == '__main__':
    main()
