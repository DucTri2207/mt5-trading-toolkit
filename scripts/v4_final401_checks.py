import sys,shutil,json
from pathlib import Path
import v4_v401 as v
from v4_build_m1 import compile_source
RUN=v.ROOT/'reports/can_ho_tro_v4/20261102_v401_final_v1'
def prefix():
    run=RUN/'prefix_smoke';run.mkdir()
    port,tests=v.setup_native(run)
    p=tests/'PlanStateV301.mqh';s=p.read_text(encoding='utf-8');s=s.replace('favorablePips >= InpBeTriggerPips','favorablePips >= V4Distance(InpBeTriggerPips)');p.write_text(s,encoding='utf-8')
    src=(v.ROOT/'tests/v4/TestV4Acceptance.mq5').read_text(encoding='utf-8-sig')
    src='#define _Symbol "XAUUSD_FIXTURE"\n'+src
    files=port/'MQL5/Files/v4_fixture';(files/'prefix_partition.csv').write_text('0,20\n')
    for mode in [0,1]:
        body=src.replace('   ulong began=', '   InpPriceScaleMode='+str(mode)+';\n   ulong began=')
        p=tests/f'FinalPrefix{mode}.mq5';p.write_text(body,encoding='utf-8-sig')
        r=compile_source(port,p,run/f'COMPILE_mode{mode}.log');v.dump(run/f'BUILD_mode{mode}.json',r);assert r['passed']
        v.native_run(port,p.stem,'mode'+str(mode))
        out=run/f'mode{mode}';out.mkdir()
        for name in ['prefix_result.json','prefix_200.csv','unit_checks.csv']:shutil.copy2(files/name,out/name)
        result=json.loads((out/'prefix_result.json').read_text());assert result['prefix_passed']==20
        print('PREFIX_SMOKE',mode,20,flush=True)
if __name__=='__main__':prefix()
