"""Read market history copies with an offline native script; no account/login/order access."""
from pathlib import Path
import json
import shutil
import subprocess

import build_fabio_orderflow_indicator as build
from collect_us100_ny import ROOT, sha, write_json

RUN=ROOT/'reports/us100_ny_scalp/20261101_backtest_v2'
SOURCE=Path(r'C:\Users\ductr\AppData\Roaming\MetaQuotes\Terminal\D0E8209F77C8CF37AD8BF550E51FF075')


def main():
    assert (RUN/'DATA_PLAN.json').exists()
    build.RUN=RUN
    script=ROOT/'tests/mql5/ExportCachedNasdaq.mq5'
    manifest=build.compile_one(script,'cached_export')
    write_json(RUN/'EXPORT_BUILD.json',manifest)
    fixture=RUN/'offline_terminal'
    (fixture/'MQL5/Scripts').mkdir(parents=True,exist_ok=True)
    shutil.copy2(build.TERMINAL,fixture/'terminal64.exe')
    (fixture/'bases').mkdir(exist_ok=True)
    shutil.copy2(build.SEED_FIXTURE/'bases/symbols.custom.dat',fixture/'bases/symbols.custom.dat')
    seed=Path('bases/Custom/history/_CHT_M5_20261025')
    shutil.copytree(build.SEED_FIXTURE/seed,fixture/seed,dirs_exist_ok=True)
    copies=[]
    for source_folder,target_folder,role in [
        (SOURCE/'bases/Default/Symbols',fixture/'bases/Default/Symbols','default symbol catalog'),
        (SOURCE/'bases/MetaQuotes-Demo/symbols',fixture/'bases/MetaQuotes-Demo/symbols','broker symbol catalog'),
        (SOURCE/'bases/MetaQuotes-Demo/history/USTEC',fixture/'bases/MetaQuotes-Demo/history/USTEC','broker M1 history'),
        (SOURCE/'bases/MetaQuotes-Demo/history/USTEC',fixture/'bases/Default/History/USTEC','offline default context M1 copy')]:
        target_folder.mkdir(parents=True,exist_ok=True)
        for p in source_folder.glob('*'):
            if not p.is_file():continue
            before=sha(p);dest=target_folder/p.name;shutil.copy2(p,dest)
            assert sha(dest)==before
            copies.append(dict(role=role,source_name=p.name,bytes=p.stat().st_size,source_sha256=before,target=str(dest)))
    write_json(RUN/'CACHE_COPY_MANIFEST.json',dict(copies=copies,accounts_or_credentials_copied=False))
    # Login=0 uses the default catalog. Use the cached broker market catalog in that offline context.
    catalogs=list((SOURCE/'bases/MetaQuotes-Demo/symbols').glob('symbols-*.dat'))
    assert len(catalogs)==1
    shutil.copy2(catalogs[0],fixture/'bases/Default/Symbols/symbols-0.dat')
    write_json(RUN/'OFFLINE_CATALOG_CONTEXT.json',dict(source_role='cached broker market symbol catalog',
        sha256=sha(catalogs[0]),target_role='offline default symbol catalog',no_accounts_or_credentials=True))
    shutil.copy2(script.with_suffix('.ex5'),fixture/'MQL5/Scripts'/script.with_suffix('.ex5').name)
    ini=RUN/'offline_export.ini'
    ini.write_text('[Common]\nLogin=0\nServer=MetaQuotes-Demo\nMaxBars=5000000\n[Charts]\nMaxBars=5000000\n[Experts]\nEnabled=0\nAllowLiveTrading=0\nAllowDllImport=0\n[StartUp]\nScript=ExportCachedNasdaq\nSymbol=_CHT_M5_20261025\nPeriod=M1\nShutdownTerminal=1\n',encoding='ascii')
    p=subprocess.Popen(f'"{fixture/"terminal64.exe"}" /portable /config:"{ini}"',cwd=str(fixture),startupinfo=build.hidden())
    write_json(RUN/'EXPORT_PROCESS.json',dict(pid=p.pid,path=str(fixture/'terminal64.exe')))
    try:code=p.wait(timeout=50)
    except subprocess.TimeoutExpired:
        p.terminate();p.wait(timeout=10);code='OWN_EXPORT_TERMINATED_AFTER_TIMEOUT'
    out=fixture/'MQL5/Files/nasdaq_cache_export'
    records={p.name:json.loads(p.read_text(encoding='utf-8-sig')) for p in out.glob('*.json')}
    write_json(RUN/'EXPORT_RESULT.json',dict(exit_code=code,records=records,files=[dict(name=p.name,bytes=p.stat().st_size) for p in out.glob('*.csv')]))
    print(json.dumps(dict(exit_code=code,records=records),ensure_ascii=True),flush=True)


if __name__=='__main__':main()
