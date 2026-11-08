"""Supplemental cached quote export in the existing isolated, login-free terminal."""
import json
import shutil
import subprocess

import build_fabio_orderflow_indicator as build
from export_cached_nasdaq import RUN,SOURCE
from collect_us100_ny import ROOT,sha,write_json


def main():
    assert (RUN/'EXECUTION_CLOCK_AMENDMENT.md').exists()
    fixture=RUN/'offline_terminal'
    build.RUN=RUN
    source=ROOT/'tests/mql5/ExportCachedNasdaqTicks.mq5'
    write_json(RUN/'TICK_EXPORT_BUILD.json',build.compile_one(source,'cached_ticks'))
    records=[]
    for base in ['MetaQuotes-Demo','Default']:
        target=fixture/'bases'/base/'ticks/USTEC';target.mkdir(parents=True,exist_ok=True)
        for p in (SOURCE/'bases/MetaQuotes-Demo/ticks/USTEC').glob('*'):
            if p.is_file():
                dest=target/p.name;shutil.copy2(p,dest)
                records.append(dict(name=p.name,bytes=dest.stat().st_size,sha256=sha(dest),base=base))
    write_json(RUN/'TICK_CACHE_MANIFEST.json',dict(market_data=records,no_credentials=True))
    shutil.copy2(source.with_suffix('.ex5'),fixture/'MQL5/Scripts'/source.with_suffix('.ex5').name)
    ini=RUN/'offline_tick_export.ini'
    ini.write_text((RUN/'offline_export.ini').read_text(encoding='ascii').replace('Script=ExportCachedNasdaq','Script=ExportCachedNasdaqTicks'),encoding='ascii')
    p=subprocess.Popen(f'"{fixture/"terminal64.exe"}" /portable /config:"{ini}"',cwd=str(fixture),startupinfo=build.hidden())
    write_json(RUN/'TICK_EXPORT_PROCESS.json',dict(pid=p.pid,path=str(fixture/'terminal64.exe')))
    try:code=p.wait(timeout=85)
    except subprocess.TimeoutExpired:
        p.terminate();p.wait(timeout=10);code='OWN_EXPORT_TERMINATED_AFTER_TIMEOUT'
    status=fixture/'MQL5/Files/nasdaq_cache_export/ticks.status.json'
    result=dict(exit_code=code,status=json.loads(status.read_text(encoding='utf-8-sig')) if status.exists() else None)
    write_json(RUN/'TICK_EXPORT_RESULT.json',result)
    print(json.dumps(result),flush=True)


if __name__=='__main__':main()
