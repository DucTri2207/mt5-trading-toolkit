"""Locked v4.0.1 validation, no account files or optimizer."""
import argparse,json,shutil,subprocess,re,sys,time
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
import v4_m3b as broker
from v4_build_m1 import compile_source
from v4_native_m1 import prepare
from v4_port_m1 import function
ROOT=Path(__file__).resolve().parents[1];RUN=ROOT/'reports/can_ho_tro_v4/20261102_v401_v1'
PORT=broker.PORT;broker.RUN=RUN

def dump(p,x):p.write_text(json.dumps(x,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
def build():
    broker.build('v401')
    result=compile_source(PORT,PORT/'MQL5/Indicators/duc_tri_can_ho_tro_v4.mq5',RUN/'COMPILE_indicator.log');dump(RUN/'BUILD_indicator.json',result);assert result['passed']
    shutil.copy2(PORT/'MQL5/Indicators/duc_tri_can_ho_tro_v4.ex5',ROOT/'can_ho_tro_v4/MQL5/Indicators/duc_tri_can_ho_tro_v4.ex5')
    s=(ROOT/'can_ho_tro_v4/MQL5/Indicators/duc_tri_can_ho_tro_v4.mq5').read_text(encoding='utf-8-sig');s=re.sub(r'^#property indicator_.*\n','',s,flags=re.M)
    for sig in ['void SaveTelegramConfig(string token, string chatId)','void LoadTelegramConfig(string &token, string &chatId)']:s=s.replace(function(s,sig),sig+' {}')
    for name in ['OnInit','OnDeinit','OnTimer','OnCalculate','OnChartEvent']:s=re.sub(r'\b'+name+r'\b','U_'+name,s)
    old=(ROOT/'reports/can_ho_tro_v4/20261102_m3b_v2/indicator_adapter/CanHoTroV4_IndicatorParity.mq5').read_text(encoding='utf-8-sig')
    wrapper=old[old.index('// Tester adapter for actual indicator callbacks'):]
    p=PORT/'MQL5/Experts/CanHoTroV4_IndicatorParity401.mq5';p.write_text(s+'\n'+wrapper,encoding='utf-8-sig');shutil.copy2(p,RUN/p.name)
    r=compile_source(PORT,p,RUN/'COMPILE_indicator_adapter.log');dump(RUN/'BUILD_indicator_adapter.json',r);assert r['passed']
    print('V401: EA, indicator, callback adapter compiled 0/0',flush=True)

def native_run(port,source,label):
    ini=port.parent/(label+'.ini');ini.write_text('[Common]\nLogin=0\nServer=MetaQuotes-Demo\nNewsEnable=0\n[Experts]\nEnabled=1\nAllowLiveTrading=0\nAllowDllImport=0\n[StartUp]\nScript=V4\\'+source+'\nSymbol=_CHT_M5_20261025\nPeriod=M1\nShutdownTerminal=1\n',encoding='ascii')
    si=subprocess.STARTUPINFO();si.dwFlags|=subprocess.STARTF_USESHOWWINDOW;si.wShowWindow=0
    p=subprocess.Popen(f'"{port/"terminal64.exe"}" /portable /config:"{ini}"',cwd=port,startupinfo=si);code=p.wait();return code

def setup_native(run):
    port=run/'portable_terminal';port.mkdir(parents=True,exist_ok=False)
    for name in ['terminal64.exe','MetaEditor64.exe']:shutil.copy2(PORT/name,port/name)
    shutil.copytree(PORT/'MQL5/Include',port/'MQL5/Include')
    tests=port/'MQL5/Scripts/V4'
    shutil.copytree(ROOT/'reports/can_ho_tro_v4/20261102_m3a_v1/build_inputs_r3/tests',tests)
    shutil.copytree(ROOT/'tests/v4',tests,dirs_exist_ok=True)
    files=port/'MQL5/Files/v4_fixture';files.mkdir(parents=True)
    frozen=ROOT/'reports/can_ho_tro_v4/20261101_m2_v1/portable_terminal/MQL5/Files/v4_fixture'
    for name in ['h1.csv','m5.csv']:shutil.copy2(frozen/name,files/name)
    seed=ROOT/'reports/scalp_structure_lab/20261025_pilot_v1/fixture_terminal'
    (port/'bases').mkdir();shutil.copy2(seed/'bases/symbols.custom.dat',port/'bases/symbols.custom.dat')
    rel=Path('bases/Custom/history/_CHT_M5_20261025');shutil.copytree(seed/rel,port/rel)
    return port,tests

def worker(index):
    run=RUN/f'prefix_r2_worker_{index}';port,tests=setup_native(run)
    # Prefix tests retain the accepted M1 profile and literal display-plan baseline.
    p=tests/'PlanStateV301.mqh';s=p.read_text(encoding='utf-8');s=s.replace('favorablePips >= InpBeTriggerPips','favorablePips >= V4Distance(InpBeTriggerPips)');p.write_text(s,encoding='utf-8')
    src=(ROOT/'tests/v4/TestV4Acceptance.mq5').read_text(encoding='utf-8-sig')
    src='#define _Symbol "XAUUSD_FIXTURE"\n'+src
    src=src.replace('   ulong began=', '   InpPriceScaleMode=MODE;\n   ulong began=')
    files=port/'MQL5/Files/v4_fixture';(files/'prefix_partition.csv').write_text(f'{index*50},50\n')
    results={}
    for mode in [0,1]:
        body=src.replace('InpPriceScaleMode=MODE','InpPriceScaleMode='+str(mode));p=tests/f'TestV401Prefix{mode}.mq5';p.write_text(body,encoding='utf-8-sig')
        r=compile_source(port,p,run/f'COMPILE_mode{mode}.log');assert r['passed'];dump(run/f'BUILD_mode{mode}.json',r)
        code=native_run(port,p.stem,'mode'+str(mode))
        out=run/f'mode{mode}';out.mkdir()
        for name in ['prefix_result.json','prefix_200.csv','unit_checks.csv']:shutil.copy2(files/name,out/name)
        results[str(mode)]=json.loads((out/'prefix_result.json').read_text())
        assert results[str(mode)]['prefix_passed']==50
        print('PREFIX_PART_DONE',index,mode,flush=True)
    dump(run/'RESULTS.json',results);return results

def hist():
    run=RUN/'native_hist';port,tests=setup_native(run)
    files=port/'MQL5/Files/v4_fixture';shutil.copy2(ROOT/'reports/can_ho_tro_v4/20261101_m2_v1/portable_terminal/MQL5/Files/v4_fixture/m1.csv',files/'m1.csv')
    fixture=(ROOT/'tests/v4/FixtureData.mqh').read_text(encoding='utf-8-sig')
    market=fixture[fixture.index('MqlRates fixtureH'):fixture.index('SZone g_zones')]+fixture[fixture.index('bool FixtureTick'):fixture.index('void ResetFixtureState')]+fixture[fixture.index('#define CopyRates'):]
    market=market.replace('#define CopyRates','int FixtureRates(const string symbol,const ENUM_TIMEFRAMES tf,const datetime from,const datetime to,MqlRates &out[]){return -1;}\n#define CopyRates')
    (tests/'Market401.mqh').write_text(market,encoding='utf-8-sig')
    body=(ROOT/'can_ho_tro_v4/MQL5/Indicators/duc_tri_can_ho_tro_v4.mq5').read_text(encoding='utf-8-sig');body=re.sub(r'^#property indicator_.*\n','',body,flags=re.M)
    for name in ['OnInit','OnDeinit','OnTimer','OnCalculate','OnChartEvent']:body=re.sub(r'\b'+name+r'\b','U_'+name,body)
    (tests/'Indicator401.mqh').write_text(body,encoding='utf-8-sig')
    wrapper=(ROOT/'tests/v4/TestV401Hist.mq5').read_text(encoding='utf-8-sig');p=tests/'TestV401Hist.mq5';p.write_text(wrapper,encoding='utf-8-sig')
    r=compile_source(port,p,run/'COMPILE.log');dump(run/'BUILD.json',r);assert r['passed']
    native_run(port,p.stem,'hist')
    out=run/'outputs';out.mkdir()
    for name in ['hist_signals.csv','hist_trades.csv','hist_result.json','scale_checks.csv']:shutil.copy2(files/name,out/name)
    print((out/'hist_result.json').read_text(),flush=True)

def prefix():
    with ThreadPoolExecutor(max_workers=4) as pool:results=list(pool.map(worker,range(4)))
    totals={str(m):sum(x[str(m)]['prefix_passed'] for x in results) for m in [0,1]};dump(RUN/'PREFIX_401_SUMMARY.json',dict(totals=totals,partitions=results));print(json.dumps(totals))

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('action');p.add_argument('--label');p.add_argument('--rule',type=int,default=0);p.add_argument('--expert');a=p.parse_args()
    if a.action=='build':build()
    elif a.action=='prefix':prefix()
    elif a.action=='hist':hist()
    else:broker.launch(a.label,a.rule,None,expert=a.expert)
