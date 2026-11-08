"""Compile and run ONLY the workspace portable fixture terminal; no main-terminal sync."""
from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import time
from pathlib import Path

import numpy as np

from prepare_can_ho_tro_scalp import ROOT, RUN, sha, write_json

FIXTURE = ROOT/'reports/scalp_structure_lab/20261025_pilot_v1/fixture_terminal'
FILES = FIXTURE/'MQL5/Files/can_ho_tro_scalp_v1'
EDITOR = Path('C:/Program Files/MetaTrader 5/MetaEditor64.exe')
SOURCE = ROOT/'tests/mql5/TestCanHoTroScalpReplay.mq5'


def compile_one(source, label):
    log = RUN/f'compile_{label}.log'
    if log.exists():
        log.unlink()
    started = time.time()
    startup = subprocess.STARTUPINFO()
    startup.dwFlags |= subprocess.STARTF_USESHOWWINDOW
    startup.wShowWindow = 0
    command = f'"{EDITOR}" /compile:"{source}" /log:"{log}"'
    result = subprocess.run(command, startupinfo=startup)
    raw = log.read_bytes()
    text = raw.decode('utf-16') if raw.startswith(b'\xff\xfe') else raw.decode('utf-8-sig')
    binary = source.with_suffix('.ex5')
    if not re.search(r'Result:\s*0 errors,\s*0 warnings', text) or not binary.exists() or binary.stat().st_mtime < started-2:
        raise RuntimeError(text)
    return {'source': str(source), 'source_sha256': sha(source), 'ex5': str(binary),
            'ex5_sha256': sha(binary), 'log': str(log), 'compiler_return_code': result.returncode,
            'diagnostics': '0 errors, 0 warnings'}


def stage():
    FILES.mkdir(parents=True,exist_ok=True)
    data = np.load(RUN/'rates.npz')
    for key in ['h1','m5','d1','m1']:
        matrix=np.column_stack([data[key][n] for n in ['time','open','high','low','close']])
        np.savetxt(FILES/(key+'.csv'),matrix,delimiter=',',fmt=['%d','%.10f','%.10f','%.10f','%.10f'])
    shutil.copy2(SOURCE.with_suffix('.ex5'),FIXTURE/'MQL5/Scripts'/SOURCE.with_suffix('.ex5').name)
    ini=RUN/'fixture_oracle.ini'
    ini.write_text('''[Common]
Login=0
Server=MetaQuotes-Demo
[Experts]
Enabled=0
AllowLiveTrading=0
AllowDllImport=0
[StartUp]
Script=TestCanHoTroScalpReplay
Symbol=XAUUSD
Period=M5
ShutdownTerminal=1
''',encoding='ascii')
    return ini


def launch():
    ini=stage()
    for name in ['mql_result.json','progress.json']:
        target=FILES/name
        if target.exists():target.unlink()
    return launch_ini(ini)


def launch_ini(ini,record_name='fixture_process.json'):
    startup = subprocess.STARTUPINFO();startup.dwFlags|=subprocess.STARTF_USESHOWWINDOW;startup.wShowWindow=0
    # MetaTrader parses the quotes after the colon, as MetaEditor does.
    command=f'"{FIXTURE / "terminal64.exe"}" /portable /config:"{ini}"'
    proc=subprocess.Popen(command,cwd=str(FIXTURE),startupinfo=startup)
    write_json(RUN/record_name,{'pid':proc.pid,'path':str(FIXTURE/'terminal64.exe'),
                                         'ini':str(ini),'purpose':'workspace oracle only; main account untouched'})
    print('FIXTURE_PID',proc.pid,flush=True)
    return proc


def main():
    parser=argparse.ArgumentParser();parser.add_argument('command',choices=['compile','run','status'])
    command=parser.parse_args().command
    if command=='compile':
        result=compile_one(SOURCE,'oracle')
        write_json(RUN/'oracle_build_manifest.json',result)
        print(json.dumps(result,ensure_ascii=True),flush=True)
    elif command=='run':
        proc=launch()
        try:
            code=proc.wait(timeout=50)
            print('FIXTURE_EXIT',code,flush=True)
        except subprocess.TimeoutExpired:
            print('FIXTURE_RUNNING',proc.pid,flush=True)
    else:
        for name in ['progress.json','mql_result.json']:
            p=FILES/name
            print(name,p.read_text() if p.exists() else 'NOT_CREATED')


if __name__=='__main__':
    main()
