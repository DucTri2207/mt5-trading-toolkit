"""Check cached-broker real-tick tester access in an isolated account-free portable."""
import hashlib
import json
import shutil
import subprocess
import time
from pathlib import Path

from v4_build_m1 import compile_source

ROOT=Path(__file__).resolve().parents[1]
RUN=ROOT/'reports/can_ho_tro_v4/20261102_m3_v1'
SOURCE=Path('C:/Users/ductr/AppData/Roaming/MetaQuotes/Terminal/D0E8209F77C8CF37AD8BF550E51FF075')
SEED=ROOT/'reports/can_ho_tro_v4/20261101_m2_v1/portable_terminal'


def sha(path):
    h=hashlib.sha256()
    with path.open('rb') as f:
        for block in iter(lambda:f.read(1024*1024),b''): h.update(block)
    return h.hexdigest()


def save(name,value):
    (RUN/name).write_text(json.dumps(value,indent=2,ensure_ascii=False)+'\n',encoding='utf-8')


def main():
    RUN.mkdir(parents=True,exist_ok=False)
    portable=RUN/'portable_terminal'; portable.mkdir()
    copied=[]
    for name in ['terminal64.exe','MetaEditor64.exe','metatester64.exe']:
        shutil.copy2(SEED/name,portable/name)
    # Market catalogs, H1/M1 history and real tick caches only; no account DB, trade DB, configuration or credentials.
    for server in ['MetaQuotes-Demo','Default']:
        for role,source,target,names in [
            ('market symbol catalog',SOURCE/'bases/MetaQuotes-Demo/symbols',portable/'bases'/server/'symbols',None),
            ('bar cache',SOURCE/'bases/MetaQuotes-Demo/history/XAUUSD',portable/'bases'/server/'history/XAUUSD',['2025.hcc','2026.hcc']),
            ('real tick cache',SOURCE/'bases/MetaQuotes-Demo/ticks/XAUUSD',portable/'bases'/server/'ticks/XAUUSD',['202610.tkc','ticks.dat'])]:
            target.mkdir(parents=True,exist_ok=True)
            for p in source.iterdir():
                if not p.is_file() or (names is not None and p.name not in names): continue
                dest=target/p.name
                if role=='market symbol catalog' and server=='Default' and p.name.startswith('symbols-'):
                    dest=target/'symbols-0.dat'
                shutil.copy2(p,dest)
                digest=sha(p); assert sha(dest)==digest
                copied.append(dict(role=role,source=str(p),target=str(dest.relative_to(RUN)),bytes=p.stat().st_size,sha256=digest))
    save('PREFLIGHT_DATA_MANIFEST.json',dict(copies=copied,account_or_credentials_copied=False,source_server='MetaQuotes-Demo'))
    testdir=portable/'MQL5/Experts/V4'; testdir.mkdir(parents=True)
    source=ROOT/'tests/v4/TestV4M3Preflight.mq5'; target=testdir/source.name; shutil.copy2(source,target)
    result=compile_source(portable,target,RUN/'COMPILE_PREFLIGHT.log'); save('BUILD_PREFLIGHT.json',result)
    assert result['passed']
    ini=RUN/'tester_preflight.ini'
    ini.write_text('[Common]\nLogin=0\nServer=MetaQuotes-Demo\nKeepPrivate=0\nNewsEnable=0\n'
       '[Experts]\nEnabled=1\nAllowLiveTrading=0\nAllowDllImport=0\n'
       '[Tester]\nExpert=V4\\TestV4M3Preflight.ex5\nSymbol=XAUUSD\nPeriod=M5\nModel=4\n'
       'Optimization=0\nExecutionMode=0\nFromDate=2026.10.01\nToDate=2026.10.03\nForwardMode=0\n'
       'Deposit=100000\nCurrency=USD\nLeverage=100\nUseLocal=1\nUseRemote=0\nUseCloud=0\n'
       'Visual=0\nReport=M3_PREFLIGHT\nReplaceReport=1\nShutdownTerminal=1\n',encoding='ascii')
    save('PREFLIGHT_PROTOCOL.json',dict(symbol='XAUUSD',server_market_cache='MetaQuotes-Demo',model=4,
       purpose='Infrastructure only; stop after 1000 ticks; no orders or strategy P&L.',
       login=0,no_authentication=True,period=['2026-10-01','2026-10-03'],real_account_terminal_modified=False))
    startup=subprocess.STARTUPINFO(); startup.dwFlags|=subprocess.STARTF_USESHOWWINDOW; startup.wShowWindow=0
    started=time.time(); proc=subprocess.Popen(f'"{portable/"terminal64.exe"}" /portable /config:"{ini}"',cwd=portable,startupinfo=startup)
    print('M3_PREFLIGHT_STARTED',proc.pid,flush=True)
    save('PREFLIGHT_PROCESS.json',dict(pid=proc.pid,path=str(portable/'terminal64.exe'),started=started))
    timed_out=False
    try: code=proc.wait(timeout=60)
    except subprocess.TimeoutExpired:
        timed_out=True; proc.terminate(); code=proc.wait(timeout=10)
    common=Path('C:/Users/ductr/AppData/Roaming/MetaQuotes/Terminal/Common/Files/CanHoTroV4_M3_20261102')
    outputs=[]
    if common.exists():
        for p in common.glob('*.json'):
            if p.stat().st_mtime>=started-2:
                shutil.copy2(p,RUN/p.name); outputs.append(p.name)
    save('PREFLIGHT_RESULT.json',dict(exit_code=code,timed_out=timed_out,outputs=outputs,elapsed_seconds=time.time()-started))
    print(json.dumps(dict(exit_code=code,timed_out=timed_out,outputs=outputs)),flush=True)


if __name__=='__main__': main()
