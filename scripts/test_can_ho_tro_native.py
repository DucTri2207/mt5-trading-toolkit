"""Stage a native chart integration test in the WORKSPACE fixture terminal only."""
from __future__ import annotations

import json
import re
import shutil
import argparse
import subprocess

import numpy as np

from prepare_can_ho_tro_scalp import ROOT, RUN, write_json
from build_can_ho_tro_scalp import FIXTURE, FILES, compile_one, launch_ini
from can_ho_tro_scalp_plan import planned_gate


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--run',action='store_true');args=parser.parse_args()
    raw=np.load(RUN/'detector_python.npz')['c0_raw']
    eligible=[r for r in raw if planned_gate(r)=='PASS']
    chosen=eligible[-1];at=int(chosen[1]);before=at-300
    data=np.load(RUN/'rates.npz');rates=data['m1'];times=rates['time']
    initial=rates[times<before]
    extra=rates[(times>=before)&(times<at)]
    entry=int(np.searchsorted(times,at));bid=float(rates[entry]['open'])
    for name,values in [('native_initial',initial),('native_extra',extra)]:
        matrix=np.column_stack([values[k] for k in ['time','open','high','low','close']])
        np.savetxt(FILES/(name+'.csv'),matrix,delimiter=',',fmt=['%d','%.10f','%.10f','%.10f','%.10f'])
    lab=ROOT/'duc_tri_can_ho_tro_scalp_lab.mq5'
    source=lab.read_text(encoding='utf-8');enums={}
    original=(ROOT/'duc_tri_can_ho_tro_scalp.mq5').read_text(encoding='utf-8-sig')
    enum_source=original+'\n'+(ROOT/'Include/CanHoTroScalpPlan.mqh').read_text(encoding='utf-8')
    for body in re.findall(r'enum\s+\w+\s*\{(.*?)\}',enum_source,re.S):
        body=re.sub(r'//[^\n]*','',body);value=-1
        for field in body.split(','):
            field=field.strip()
            if not field:continue
            parts=field.split('=');value=int(parts[1].strip()) if len(parts)>1 else value+1
            enums[parts[0].strip()]=str(value)
    # The five lab controls come first; all inherited UI/detector inputs retain defaults.
    native=(ROOT/'Include/CanHoTroScalpNative.mqh').read_text(encoding='utf-8')
    params=re.findall(r'input\s+(\w+)\s+(\w+)\s*=\s*([^;]+);',native)
    setup=['ArrayResize(parameters,%d);'%(len(params)+1),
           'parameters[0].type=TYPE_STRING;parameters[0].string_value="DucTriLab\\\\can_ho_tro_v01\\\\duc_tri_can_ho_tro_scalp_lab";']
    for i,(kind,name,value) in enumerate(params,1):
        value=value.strip()
        if name=='InpLabVirtualPlans':value='true'
        if kind=='string':typ,member='TYPE_STRING','string_value'
        elif kind=='double':typ,member='TYPE_DOUBLE','double_value'
        else:
            typ,member=('TYPE_BOOL' if kind=='bool' else 'TYPE_INT'),'integer_value'
            value=enums.get(value,value)
        setup.append(f'parameters[{i}].type={typ};parameters[{i}].{member}={value};')
    template=(ROOT/'tests/mql5/TestCanHoTroScalpNative.mq5.in').read_text(encoding='utf-8')
    code=template.replace('@@PARAMETERS@@','\n   '.join(setup)).replace('@@BEFORE@@',str(before)).replace('@@AT@@',str(at)).replace('@@BID@@',repr(bid))
    target=ROOT/'tests/mql5/TestCanHoTroScalpNative.mq5';target.write_text(code,encoding='utf-8')
    result=compile_one(target,'native_chart')
    directory=FIXTURE/'MQL5/Indicators/DucTriLab/can_ho_tro_v01';directory.mkdir(parents=True,exist_ok=True)
    shutil.copy2(ROOT/'duc_tri_can_ho_tro_scalp_lab.ex5',directory/'duc_tri_can_ho_tro_scalp_lab.ex5')
    shutil.copy2(target.with_suffix('.ex5'),FIXTURE/'MQL5/Scripts/TestCanHoTroScalpNative.ex5')
    shutil.copy2(ROOT/'tests/mql5/CanHoTroScalpNative.tpl',FIXTURE/'MQL5/Profiles/Templates/CHT_native_v01.tpl')
    ini=RUN/'fixture_native.ini'
    ini.write_text('''[Common]
Login=0
Server=MetaQuotes-Demo
[Experts]
Enabled=0
AllowLiveTrading=0
AllowDllImport=0
[StartUp]
Script=TestCanHoTroScalpNative
Symbol=XAUUSD
Period=M5
ShutdownTerminal=1
''',encoding='ascii')
    write_json(RUN/'native_chart_build_manifest.json',{'build':result,'expected_signal':chosen.tolist(),
                'quote_at':at,'bid':bid,'fixture_path':str(FIXTURE),'ini':str(ini),'main_terminal_affected':False})
    print(json.dumps({'native_test_staged':True,'expected_known_at':at,'input_count':len(params)},ensure_ascii=True))
    if args.run:
        target=FILES/'native_chart_result.json'
        if target.exists():target.unlink()
        proc=launch_ini(ini,'native_chart_process.json')
        try:print('NATIVE_CHART_EXIT',proc.wait(timeout=50),flush=True)
        except subprocess.TimeoutExpired:print('NATIVE_CHART_STILL_RUNNING',proc.pid,flush=True)


if __name__=='__main__':main()
