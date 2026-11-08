"""Run all 200 independent native prefix cases in four isolated terminals."""
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
import subprocess,shutil,os,json,argparse
ROOT=Path(__file__).resolve().parents[1]
RUN=ROOT/"reports/can_ho_tro_v4/20261101_m1_v2"
def worker(index):
    run=RUN/f"prefix_worker_{index}";portable=run/"portable_terminal"
    portable.mkdir(parents=True,exist_ok=False)
    source=RUN/"portable_terminal"
    for name in ("terminal64.exe","MetaEditor64.exe"):shutil.copy2(source/name,portable/name)
    shutil.copytree(source/"MQL5/Include",portable/"MQL5/Include")
    files=portable/"MQL5/Files/v4_fixture";files.mkdir(parents=True)
    (files/"prefix_partition.csv").write_text(f"{index*50},50\n")
    env=dict(os.environ,PYTHONIOENCODING="utf-8")
    with (run/"console.txt").open("w",encoding="utf-8") as log:
        code=subprocess.call([os.sys.executable,str(ROOT/"scripts/v4_native_m1.py"),"--run",str(run),"--name","TestV4Acceptance","--label","final_200"],stdout=log,stderr=subprocess.STDOUT,env=env,cwd=ROOT)
    return dict(worker=index,returncode=code)
if __name__=="__main__":
    parser=argparse.ArgumentParser();parser.add_argument("--run",default=str(RUN));args=parser.parse_args()
    RUN=Path(args.run).resolve()
    with ThreadPoolExecutor(max_workers=4) as pool:results=list(pool.map(worker,range(4)))
    (RUN/"PREFIX_PARTITION_RUNNER.json").write_text(json.dumps(results,indent=2))
    print(json.dumps(results))
