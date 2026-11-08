"""Build/package a separate research indicator. No chart attachment or orders."""
from __future__ import annotations
import argparse
import hashlib
import json
import re
import shutil
import subprocess
import time
from datetime import datetime,timezone
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
RUN=ROOT/'reports/scalp_structure_lab/20261025_pilot_v1'
NAME='duc_tri_scalp_structure_lab'
EDITOR=Path('C:/Program Files/MetaTrader 5/MetaEditor64.exe')
FILES=[Path(NAME+'.mq5'),Path(NAME+'.ex5')]+[Path('Include')/name for name in ['ScalpStructureTypes.mqh','ScalpStructureSetup.mqh','ScalpStructurePlan.mqh']]

def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()
def build():
    results=[]
    for source,label in [(ROOT/(NAME+'.mq5'),'indicator'),(ROOT/'tests/mql5/TestScalpStructureReplay.mq5','runner')]:
        log=RUN/f'compile_{label}.log'
        if log.exists():log.unlink()
        started=time.time();startup=subprocess.STARTUPINFO();startup.dwFlags|=subprocess.STARTF_USESHOWWINDOW;startup.wShowWindow=0
        # MetaEditor parses quotes after the colon, unlike normal argv parsers.
        command=f'"{EDITOR}" /compile:"{source}" /log:"{log}"'
        proc=subprocess.run(command,startupinfo=startup)
        raw=log.read_bytes();text=raw.decode('utf-16') if raw.startswith(b'\xff\xfe') else raw.decode('utf-8-sig')
        binary=source.with_suffix('.ex5')
        match=re.search(r'Result:\s*0 errors,\s*0 warnings',text)
        if not match or not binary.exists() or binary.stat().st_mtime<started-2:
            raise RuntimeError(f'Build failed or stale output: {source}\n{text}')
        results.append({'source':str(source),'ex5':str(binary),'source_sha256':sha(source),
                        'ex5_sha256':sha(binary),'log':str(log),'metaeditor_exit_code':proc.returncode,
                        'diagnostics':'0 errors, 0 warnings'})
    package=RUN/'package';package.mkdir(exist_ok=True)
    for rel in FILES:
        dest=package/rel;dest.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(ROOT/rel,dest)
    shutil.copy2(RUN/'SPEC_LOCK.json',package/'SPEC_LOCK.json')
    (package/'README.md').write_text('''# Duc Tri structure lab p2_structure_0.1

Research artifact. The historical P2 pilot failed the profitability gate.
Default InpPaperEnabled=false. No order API, alerts, LLM or EA integration.
E0 uses a minimum 1.5R target rounded outward to the tick grid; E1 uses confirmed structure trailing.
Initial risk R0 never changes. Stop only tightens. One idea per policy.
Paper sessions, if manually enabled for development, reset on reload; no durable forward state is implemented.
Do not merge such sessions with the v3.12 monitor. Full forward deployment is gated off.
The five-year reports use synthetic spreads on Bid M1 OHLC, not recorded Bid/Ask ticks.

To inspect, copy this folder under MQL5/Indicators/DucTriLab/p2_structure_0_1.
Keep Include/ beside the MQ5 file. Build with MetaEditor and retain compile logs and hashes.
Do not overwrite duc_tri_can_ho_tro_scalp.
''',encoding='utf-8')
    protected=json.loads((ROOT/'thông tin nghiên cứu/baseline_lap_ke_hoach_20261025.json').read_text(encoding='utf-8-sig'))
    changed=[r['path'] for r in protected['files'] if not Path(r['path']).exists() or sha(Path(r['path'])).lower()!=r['sha256'].lower()]
    manifest={'created_utc':datetime.now(timezone.utc).isoformat(),'spec_version':'p2_structure_0.1',
              'builds':results,'protected_existing_files_checked':len(protected['files']),
              'protected_existing_files_changed':changed,
              'package':str(package),'files':[{'relative_path':str(r),'sha256':sha(package/r),'bytes':(package/r).stat().st_size} for r in FILES],
              'forward_deployment':'withheld after failed historical gate','paper_enabled_default':False}
    (RUN/'build_manifest.json').write_text(json.dumps(manifest,indent=2),encoding='utf-8')
    if changed:raise RuntimeError('An existing protected file changed: '+str(changed))
    print(json.dumps(manifest,indent=2))

def install_review_copy():
    import MetaTrader5 as mt5
    if not mt5.initialize(timeout=30000):raise RuntimeError(str(mt5.last_error()))
    try:data_path=Path(mt5.terminal_info().data_path)
    finally:mt5.shutdown()
    destination=data_path/'MQL5/Indicators/DucTriLab/p2_structure_0_1'
    expected=(data_path/'MQL5/Indicators/DucTriLab').resolve()
    if destination.resolve().parent!=expected:raise RuntimeError('Destination outside lab root')
    package=RUN/'package';verified=[]
    for rel in FILES+[Path('SPEC_LOCK.json'),Path('README.md')]:
        target=destination/rel;target.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(package/rel,target)
        same=sha(package/rel)==sha(target);verified.append({'path':str(target),'sha256':sha(target),'matches':same})
        if not same:raise RuntimeError('Install hash mismatch')
    (RUN/'review_install_manifest.json').write_text(json.dumps({'destination':str(destination),'files':verified,'attached_to_chart':False,'purpose':'Review copy only; forward blocked by failed research gate'},indent=2),encoding='utf-8')
    print('REVIEW_COPY',destination)

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--install-review-copy',action='store_true');a=p.parse_args();build()
    if a.install_review_copy:install_review_copy()
