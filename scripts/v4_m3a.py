"""Native M3a only: shared production frontends, no Strategy Tester or trading calls."""
import argparse
import csv
import hashlib
import json
import re
import shutil
import subprocess
import time
from pathlib import Path

from v4_build_m1 import compile_source
from v4_native_m1 import prepare

ROOT=Path(__file__).resolve().parents[1]
RUN=ROOT/'reports/can_ho_tro_v4/20261102_m3a_v1'
SEED=ROOT/'reports/can_ho_tro_v4/20261101_m2_v1/portable_terminal'


def sha(p):
    return hashlib.sha256(p.read_bytes()).hexdigest()


def save(name,obj):
    (RUN/name).write_text(json.dumps(obj,indent=2,ensure_ascii=False)+'\n',encoding='utf-8')


def setup():
    RUN.mkdir(parents=True,exist_ok=False)
    portable=RUN/'portable_terminal'; portable.mkdir()
    for name in ['terminal64.exe','MetaEditor64.exe','metatester64.exe']:
        shutil.copy2(SEED/name,portable/name)
    shutil.copytree(SEED/'MQL5/Include',portable/'MQL5/Include')
    prepare(RUN)
    save('PROTOCOL.json',dict(scope='M3a; no Strategy Tester',fixture='frozen H1/M5/ATR 2021-2026',
      symbol_alias='XAUUSD_FIXTURE',point=.01,pip=.1,opening_spread=.20,
      controls=dict(FilterKillzones=False,InpTpMode='TP_MODE_RR',InpEntryMode='ENTRY_MARKET_CONFIRM',UseReferenceLevels=False),
      production_frontends=['indicator V4ObserveClosedBar','EA V4EAObserve'],
      trading_functions_invoked=False,account_or_credentials_copied=False))


def build(label):
    portable=RUN/'portable_terminal'
    prepare(RUN)
    shutil.copytree(ROOT/'can_ho_tro_v4/MQL5',portable/'MQL5',dirs_exist_ok=True)
    tests=portable/'MQL5/Scripts/V4'
    fixture=(ROOT/'tests/v4/FixtureData.mqh').read_text(encoding='utf-8-sig')
    arrays=fixture[fixture.index('MqlRates fixtureH'):fixture.index('SZone g_zones')]
    adapters=fixture[fixture.index('bool FixtureTick'):fixture.index('void ResetFixtureState')]
    macros=fixture[fixture.index('#define CopyRates'):]
    range_adapter='int FixtureRates(const string symbol,const ENUM_TIMEFRAMES tf,const datetime from,const datetime to,MqlRates &out[]){return -1;}\n'
    (tests/'MarketFixture.mqh').write_text(arrays+adapters+range_adapter+macros,encoding='utf-8-sig')
    names=re.findall(r'^V4_INPUT\s+\w+\s+(\w+)\s*=',(ROOT/'can_ho_tro_v4/MQL5/Include/CanHoTroV4/Inputs.mqh').read_text(encoding='utf-8-sig'),re.M)
    export='\n'.join('   FileWriteString(preset,"'+n+'="+(string)'+n+'+"\\r\\n");' for n in names)
    for kind,source in [('indicator',ROOT/'can_ho_tro_v4/MQL5/Indicators/duc_tri_can_ho_tro_v4.mq5'),('ea',ROOT/'can_ho_tro_v4/MQL5/Experts/CanHoTroV4_TesterEA.mq5')]:
        body=source.read_text(encoding='utf-8-sig')
        body=re.sub(r'^#property indicator_.*\n','',body,flags=re.M)
        (tests/f'{kind}_under_test.mqh').write_text(body,encoding='utf-8-sig')
        macros_events='\n'.join(f'#define {n} U_{n}' for n in ['OnInit','OnDeinit','OnCalculate','OnTimer','OnTick','OnChartEvent'])
        undef_events='\n'.join(f'#undef {n}' for n in ['OnInit','OnDeinit','OnCalculate','OnTimer','OnTick','OnChartEvent'])
        guard='   int rejected=U_OnInit(); Check(rejected==INIT_FAILED,"real_EA_OnInit_rejects_native_non_tester");' if kind=='ea' else ''
        observe='V4EAObserve(fixtureM[m].time,fixtureM[m].time)' if kind=='ea' else 'V4ObserveClosedBar(fixtureM[m].time,fixtureM[m].time,true)'
        extra='   FileWriteString(preset,"InpAllowMultiplePositions="+(string)InpAllowMultiplePositions+"\\r\\nInpMaxTesterPositions="+(string)InpMaxTesterPositions+"\\r\\nInpTesterMagic="+(string)InpTesterMagic+"\\r\\n");' if kind=='ea' else ''
        wrapper=f'''#property strict
#define CHT_V4_NATIVE_FIXTURE
#include <Trade/Trade.mqh>
#include <CanHoTroV4/Types.mqh>
#include "MarketFixture.mqh"
#define _Symbol "XAUUSD_FIXTURE"
{macros_events}
#include "{kind}_under_test.mqh"
{undef_events}
#include <CanHoTroV4/TesterLedger.mqh>
int checks=0,failures=0;
void Check(bool ok,string name){{checks++;if(!ok){{failures++;Print("FAIL ",name);}}}}
void OnStart()
{{
   int preset=FileOpen("v4_fixture\\\\{kind}_default.set",FILE_WRITE|FILE_TXT|FILE_UNICODE);
{export}
{extra}
   FileClose(preset);
{guard}
   FilterKillzones=false; InpTpMode=TP_MODE_RR; InpEntryMode=ENTRY_MARKET_CONFIRM; UseReferenceLevels=false;
   AlertConfirm=false; ShowTradeLines=false; ShowArrows=false; AlertPopup=false; AlertPush=false;
   AlertSoundOn=false; TgEnable=false; AlertBeTriggered=false; g_v4QuietPlan=true;
   g_v4Point=.01; g_v4RenderSource=false; g_atrHandle=102; g_htfAtrHandle=100; g_ltfAtrHandle=101;
   if(!ReadFixture("h1",fixtureH,fixtureHA)||!ReadFixture("m5",fixtureM,fixtureMA)){{Check(false,"fixture_read");return;}}
   fixtureVisibleM=ArraySize(fixtureM); fixtureVisibleH=ArraySize(fixtureH); fixtureHL=-1;
   g_v4Preset=V4Preset();
   g_v4SignalsFile=FileOpen("v4_fixture\\\\signals_{kind}.csv",FILE_WRITE|FILE_READ|FILE_CSV|FILE_ANSI,',',CP_UTF8);
   Check(g_v4SignalsFile!=INVALID_HANDLE && V4Header(g_v4SignalsFile),"signal_header");
   ulong started=GetTickCount64();
   for(int m=30;m<fixtureVisibleM;m++)
   {{
      fixtureM0=m;
      while(fixtureHL+1<fixtureVisibleH && fixtureH[fixtureHL+1].time+3600<=fixtureM[m].time) fixtureHL++;
      if(!{observe} && g_v4IoFailed){{Check(false,"observation_io");break;}}
   }}
   FileClose(g_v4SignalsFile); g_v4SignalsFile=INVALID_HANDLE;
   Check(g_v4Published>0,"nonempty_stream");
   int f=FileOpen("v4_fixture\\\\trade_header_{kind}.csv",FILE_WRITE|FILE_TXT|FILE_ANSI);
   FileWriteString(f,V4TradeHeader()+"\\r\\n"); FileClose(f);
   f=FileOpen("v4_fixture\\\\trade_header_{kind}.csv",FILE_READ|FILE_WRITE|FILE_CSV|FILE_ANSI,',');FileSeek(f,0,SEEK_END);
   if(ArraySize(g_v4History)==0) return;
   SV4TesterRecord r; ZeroMemory(r);r.signal=g_v4History[0];r.signal.order_place_time=r.signal.signal_known_time;
   r.signal.initialSl=95;r.virtualTrade.entry=100;r.virtualTrade.fill=r.signal.signal_known_time+1;
   r.virtualTrade.risk=5;r.virtualTrade.mfe=5;r.riskUSD=500;r.spreadUSD=30;r.volume=1;r.tp=105;r.mae=.2;
   r.fillMsc=(long)r.virtualTrade.fill*1000;
   Check(V4TesterWrite(f,r,r.virtualTrade.fill+1,r.fillMsc+1000,105,"FIXTURE_EXIT",500,-7,-1,0,"FIXTURE_ACCOUNTING_ONLY"),"trade_row_serializer");FileClose(f);
   f=FileOpen("v4_fixture\\\\parity_{kind}_result.json",FILE_WRITE|FILE_TXT|FILE_ANSI);
   FileWriteString(f,StringFormat("{{\\"checks\\":%d,\\"failures\\":%d,\\"published\\":%d,\\"elapsed_ms\\":%I64u,\\"orders_sent\\":0}}",checks,failures,(int)g_v4Published,GetTickCount64()-started));FileClose(f);
   PrintFormat("V4_M3A_{kind.upper()}_DONE published=%I64d failures=%d",g_v4Published,failures);
}}
'''
        (tests/f'NativeM3a_{kind}.mq5').write_text(wrapper,encoding='utf-8-sig')
    sources={
      'indicator':portable/'MQL5/Indicators/duc_tri_can_ho_tro_v4.mq5',
      'ea':portable/'MQL5/Experts/CanHoTroV4_TesterEA.mq5',
      'native_indicator':tests/'NativeM3a_indicator.mq5','native_ea':tests/'NativeM3a_ea.mq5',
      'journal':tests/'TestV4M3aJournal.mq5'}
    snapshot=RUN/f'build_inputs_{label}'
    shutil.copytree(ROOT/'can_ho_tro_v4',snapshot/'can_ho_tro_v4',ignore=shutil.ignore_patterns('*.ex5'))
    shutil.copytree(tests,snapshot/'tests',ignore=shutil.ignore_patterns('*.ex5'))
    shutil.copy2(Path(__file__),snapshot/'v4_m3a.py')
    results={k:compile_source(portable,p,RUN/f'COMPILE_{k}_{label}.log') for k,p in sources.items()}
    save(f'BUILD_{label}.json',results)
    if not all(x['passed'] for x in results.values()): raise SystemExit(1)
    for k in ['indicator','ea']:
        relative=sources[k].relative_to(portable)
        shutil.copy2(sources[k].with_suffix('.ex5'),(ROOT/'can_ho_tro_v4'/relative).with_suffix('.ex5'))
    print('BUILD: indicator, EA, 2 native frontends, journal 0 errors / 0 warnings',flush=True)


def run(name,label):
    portable=RUN/'portable_terminal'; ini=RUN/f'NATIVE_{name}_{label}.ini'
    ini.write_text('[Common]\nLogin=0\nServer=MetaQuotes-Demo\nNewsEnable=0\n[Experts]\nEnabled=1\nAllowLiveTrading=0\nAllowDllImport=0\n'
       f'[StartUp]\nScript=V4\\{name}\nSymbol=_CHT_M5_20261025\nPeriod=M1\nShutdownTerminal=1\n',encoding='ascii')
    startup=subprocess.STARTUPINFO(); startup.dwFlags|=subprocess.STARTF_USESHOWWINDOW; startup.wShowWindow=0
    started=time.time(); p=subprocess.Popen(f'"{portable/"terminal64.exe"}" /portable /config:"{ini}"',cwd=portable,startupinfo=startup)
    print('NATIVE_STARTED',name,p.pid,flush=True)
    code=p.wait();save(f'EXIT_{name}_{label}.json',dict(pid=p.pid,exit_code=code,started=started,elapsed_seconds=time.time()-started,strategy_tester=False))
    print('NATIVE_ENDED',name,code,flush=True)


def analyze():
    f=RUN/'portable_terminal/MQL5/Files/v4_fixture'
    def rows(p):
        with p.open(encoding='utf-8-sig',newline='') as stream: return list(csv.DictReader(stream))
    a=rows(f/'signals_indicator.csv');b=rows(f/'signals_ea.csv')
    differences=[dict(index=i,signal_id=x['signal_id'],columns=[k for k in x if x[k]!=y[k]]) for i,(x,y) in enumerate(zip(a,b)) if x!=y]
    result=dict(indicator=len(a),ea=len(b),matched=sum(x==y for x,y in zip(a,b)),columns=len(a[0]),mismatches=differences,
                strategy_tester=False,visual_tester=False,orders_sent=0)
    save('NATIVE_PARITY.json',result)
    assert len(a)==len(b)>0 and not differences
    for kind in ['indicator','ea']:
        r=json.loads((f/f'parity_{kind}_result.json').read_text());assert r['failures']==0
    journal=json.loads((f/'journal_synthetic_result.json').read_text());assert journal['failures']==0
    assert (RUN/'portable_terminal/MQL5/Files/V4_TESTER_OUTSIDE_REJECTED.txt').exists()
    required={'signal_id','mode','direction','confirm_bar_open','signal_known_time','publish_time','order_place_time','fill_time','exit_time',
       'entry','initial_sl','tp','risk_USD','exit_price','exit_reason','gross_USD','commission_USD','net_USD','net_R','MFE_R','MAE_R','source_zone_id','cost_R'}
    trade_rows=rows(f/'trade_header_ea.csv');header=list(trade_rows[0]);assert required.issubset(header)
    assert float(trade_rows[0]['net_USD'])==492 and abs(float(trade_rows[0]['net_R'])-.984)<1e-9
    assert int(trade_rows[0]['exit_time_msc'])>=int(trade_rows[0]['fill_time_msc'])>=int(trade_rows[0]['signal_known_time'])*1000
    save('M3A_TEST_SUMMARY.json',dict(parity=result,journal=journal,guard_outside_tester='INIT_FAILED',trade_columns=len(header),required_columns_missing=[]))
    print(json.dumps(dict(parity={k:v for k,v in result.items() if k!='mismatches'},journal=journal,guard='PASS')))


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('action',choices=['prepare','build','run','analyze']);p.add_argument('--label',default='r1');p.add_argument('--name')
    a=p.parse_args()
    if a.action=='prepare':setup()
    elif a.action=='build':build(a.label)
    elif a.action=='run':run(a.name,a.label)
    else:analyze()
