"""M3b runner using existing portable session; never reads account configuration."""
import argparse,json,shutil,subprocess,time,re,hashlib
from pathlib import Path
from v4_build_m1 import compile_source
ROOT=Path(__file__).resolve().parents[1]
RUN=ROOT/'reports/can_ho_tro_v4/20261102_m3b_v2'
PORT=ROOT/'reports/can_ho_tro_v4/20261102_m3a_v1/portable_terminal'
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def dump(p,o):p.write_text(json.dumps(o,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
def build(label):
    RUN.mkdir(exist_ok=True)
    snapshot=RUN/f'source_{label}';shutil.copytree(ROOT/'can_ho_tro_v4/MQL5',snapshot,ignore=shutil.ignore_patterns('*.ex5'))
    shutil.copytree(ROOT/'can_ho_tro_v4/MQL5',PORT/'MQL5',dirs_exist_ok=True)
    r=compile_source(PORT,PORT/'MQL5/Experts/CanHoTroV4_TesterEA.mq5',RUN/f'COMPILE_EA_{label}.log')
    dump(RUN/f'BUILD_{label}.json',r);print(json.dumps(r));assert r['passed']
    shutil.copy2(PORT/'MQL5/Experts/CanHoTroV4_TesterEA.ex5',ROOT/'can_ho_tro_v4/MQL5/Experts/CanHoTroV4_TesterEA.ex5')
def launch(label,rule,dates,spread=None,expert=None):
    out=RUN/label;out.mkdir(exist_ok=False)
    preset=(ROOT/'can_ho_tro_v4/Presets/ea_default.set').read_text(encoding='utf-16')
    if spread is not None:preset=re.sub(r'^MaxSpreadPrice=.*$',f'MaxSpreadPrice={spread}',preset,flags=re.M)
    if expert:
        for key in ['ShowDash','AlertConfirm','AlertPopup','AlertPush','AlertSoundOn','TgEnable','AlertBeTriggered']:
            preset=re.sub(r'^'+key+r'=.*$',key+'=false',preset,flags=re.M)
    folder='M3b_v2_'+label
    preset=re.sub(r'^InpV4LedgerFolder=.*$',f'InpV4LedgerFolder={folder}',preset,flags=re.M)
    preset=re.sub(r'^InpScoreExit=.*$',f'InpScoreExit={rule}',preset,flags=re.M)
    setname='M3b_'+label+'.set';setpath=PORT/'MQL5/Profiles/Tester'/setname
    setpath.write_text(preset,encoding='utf-16');shutil.copy2(setpath,out/'inputs.set')
    ini=(PORT/'m3b_tp1r.ini').read_text()
    if expert:ini=re.sub(r'^Expert=.*$',f'Expert={expert}',ini,flags=re.M)
    ini=re.sub(r'^ExpertParameters=.*$',f'ExpertParameters={setname}',ini,flags=re.M)
    ini=re.sub(r'^Report=.*$',f'Report=m3b_{label}',ini,flags=re.M)
    if dates:
        ini=re.sub(r'^FromDate=.*$',f'FromDate={dates[0]}',ini,flags=re.M)
        ini=re.sub(r'^ToDate=.*$',f'ToDate={dates[1]}',ini,flags=re.M)
    path=out/'tester.ini';path.write_text(ini,encoding='ascii')
    offsets={str(p):p.stat().st_size for p in (PORT/'Tester').glob('Agent-*/logs/*.log')}
    start=time.time();si=subprocess.STARTUPINFO();si.dwFlags|=subprocess.STARTF_USESHOWWINDOW;si.wShowWindow=0
    proc=subprocess.Popen(f'"{PORT/"terminal64.exe"}" /portable /config:"{path}"',cwd=PORT,startupinfo=si)
    print('TESTER_STARTED',label,proc.pid,flush=True);code=proc.wait()
    # Copy only own new ledger directory; never read account files.
    for agent in (PORT/'Tester').glob('Agent-*'):
        f=agent/'MQL5/Files'/folder
        if f.exists():shutil.copytree(f,out/agent.name)
        for log in (agent/'logs').glob('*.log'):
            raw=log.read_bytes();encoding='utf-16-le' if raw.startswith(b'\xff\xfe') else 'utf-8-sig';text=raw[offsets.get(str(log),0):].decode(encoding,errors='replace')
            keep=[line for line in text.splitlines() if any(x in line for x in ['V4_DIAGNOSTICS','V4 tester failed','real ticks','ticks generated','final balance','successfully finished','test passed','XAUUSD: history','XAUUSD: ticks','account is not specified'])]
            (out/(agent.name+'_'+log.name+'.filtered.txt')).write_text('\n'.join(keep),encoding='utf-8')
    for ext in ['htm','html','xml']:
        f=PORT/f'm3b_{label}.{ext}'
        if f.exists():shutil.copy2(f,out/f'report.{ext}')
    dump(out/'RUN.json',dict(label=label,pid=proc.pid,exit_code=code,elapsed_seconds=time.time()-start,model=4,account_config_read=False))
    print('TESTER_ENDED',label,code,flush=True)
if __name__=='__main__':
    a=argparse.ArgumentParser();a.add_argument('action');a.add_argument('--label',required=True);a.add_argument('--rule',type=int,default=0);a.add_argument('--dates',nargs=2);a.add_argument('--spread',type=float);a.add_argument('--expert');x=a.parse_args()
    if x.action=='build':build(x.label)
    else:launch(x.label,x.rule,x.dates,x.spread,x.expert)
