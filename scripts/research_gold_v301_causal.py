"""Create the frozen signal replay and inspect the original MQ5 in native MQL5."""
import argparse
import hashlib
import json
import re
import shutil
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

from gold_v301_causal_core import (ROOT, RUN, DATA, COSTS, matrix, atr_mt5, atr_wilder,
    native_snapshots, native_zones, detect_one, detect_stream, repaired_report_zones, report_snapshots)


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def save(name, value):
    (RUN/name).write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False,
        default=lambda v: v.item() if isinstance(v, np.generic) else str(v))+'\n', encoding='utf-8')


def data():
    archive = np.load(DATA)
    end = int(datetime(2026, 10, 23, 23, 59, 59, tzinfo=timezone.utc).timestamp())
    # Warm-up history already present before the report's evaluation start.
    return {key: matrix(archive[key][archive[key]['time'] <= end]) for key in ['h1', 'm5', 'm1']}


def plan():
    RUN.mkdir(parents=True, exist_ok=True)
    path = RUN/'FROZEN_PLAN.json'
    if path.exists():
        return
    sources = ['duc_tri_can_ho_tro.mq5', 'duc_tri_can_ho_tro.ex5',
               'scripts/run_5year_backtest_v301.py', 'scripts/test_m5_scanning_speed.py']
    save('FROZEN_PLAN.json', dict(created_utc=datetime.now(timezone.utc).isoformat(),
        sources={s: sha(ROOT/s) for s in sources}, data_sha256=sha(DATA),
        evaluation_start='2021-10-23T00:00:00Z', evaluation_end='2026-10-23T23:59:59Z',
        warmup='Use all earlier bars in the saved snapshot; no future bars.',
        strategies=['REPORT_REPAIRED: original report detector with causal H1 lifetimes',
                    'MQ5_PREFIX: original MQ5 rules evaluated on closed H1 prefixes, idle candidate stream'],
        parameters=dict(tp1_R=1.5, tp2_R=2., tp1_fraction=.5, be_trigger_price=6., be_offset_price=.1,
                        stop_min_price=2.5, stop_max_price=10., buffer_ATR=.3, wick_min=.35),
        sessions='Original filter: signal-bar feed-clock hours 08:00 through 17:59 inclusive; not claimed DST-aligned London/NY.',
        execution='Next available M5 opening quote; bid OHLC with fixed hypothetical Ask spread; two explicit paths; one position; 288 observed M5-bar expiry from old report.',
        costs={k: dict(spread_price=v[0], roundtrip_commission_price=v[1], adverse_slippage_per_fill_price=v[2]) for k, v in COSTS.items()},
        risk_fraction_initial_balance=[.0025, .005], account_initial_USD=100000,
        ftmo_benchmark='CFD 2-Step; equity daily floor=start-of-day balance minus 5% initial; static 90% floor; target10% then5%; >=4 entry days per phase.',
        limitations=['Saved non-FTMO bars, no synchronized historical Bid/Ask ticks.',
                     'No actual FTMO swap/lot/margin specs; reported account metrics are scenario diagnostics.',
                     'Original candle-feed timezone is unverified; FTMO reset tested under explicit UTC interpretations.',
                     'No parameter search, optimization, or genuine post-selection holdout in this investigation.']))


def signals():
    plan(); d = data(); h = d['h1']; b = d['m5']
    a_h = atr_mt5(h); a_m = atr_mt5(b)
    started = time.time()
    print('Building original-MQ5 causal H1 snapshots...', flush=True)
    ptr, rows = native_snapshots(h, a_h)
    zones = np.asarray(rows, dtype=float).reshape(-1, 9)
    native = detect_stream(h, b, a_m, ptr, zones, True)
    left = int(datetime(2021, 10, 23, tzinfo=timezone.utc).timestamp())
    native = native[native[:, 1] >= left]
    print('MQ5_PREFIX', len(native), 'seconds', round(time.time()-started, 2), flush=True)
    # The repaired-report arm starts exactly where the archived report starts,
    # preserving its ATR seed and candidate calendar for the before/after check.
    hh = h[h[:, 0] >= left]; bb = b[b[:, 0] >= left]
    print('Building repaired-report H1 lifetimes...', flush=True)
    rz = repaired_report_zones(hh, atr_wilder(hh))
    rptr, rrows = report_snapshots(hh, rz)
    repaired = detect_stream(hh, bb, atr_wilder(bb), rptr, rrows, False)
    # Convert local report indices to the common full M5 array.
    repaired[:, 0] += np.searchsorted(b[:, 0], left)
    np.savez_compressed(RUN/'signals.npz', native=native, repaired=repaired,
                        h1_ptr=ptr, native_zones=zones, h1_atr=a_h, m5_atr=a_m)
    save('REPAIRED_REPORT_ZONES.json', rz)
    names = ['signal_index', 'signal_time', 'known_at', 'direction', 'entry_close',
             'stop', 'risk_at_close', 'zone_id', 'zone_type', 'zone_score', 'sweep_shift', 'atr']
    for name, rows in [('MQ5_PREFIX', native), ('REPORT_REPAIRED', repaired)]:
        np.savetxt(RUN/f'signals_{name}.csv', rows, delimiter=',', header=','.join(names), comments='',
                   fmt=['%d']*4+['%.10f']*3+['%d']*4+['%.10f'])
    save('SIGNAL_SUMMARY.json', dict(native_candidates=len(native), repaired_report_candidates=len(repaired),
        native_kz=int(np.sum(((native[:, 1]//3600)%24 >= 8)&((native[:, 1]//3600)%24 <= 17))),
        repaired_kz=int(np.sum(((repaired[:, 1]//3600)%24 >= 8)&((repaired[:, 1]//3600)%24 <= 17))),
        elapsed_seconds=time.time()-started, native_snapshot_rows=len(zones),
        signal_scope='Independent eligibility with no active position; portfolio gate applied in execution.'))


def extract_function(source, signature):
    start = source.index(signature+'\n{')
    brace = source.index('{', start); depth = 1; j = brace+1
    while depth:
        if source[j] == '{': depth += 1
        elif source[j] == '}': depth -= 1
        j += 1
    return source[start:j]


def prepare_native():
    plan(); d = data(); cache = np.load(RUN/'signals.npz')
    source = (ROOT/'duc_tri_can_ho_tro.mq5').read_text(encoding='utf-8-sig')
    # The actual original function bodies, not a second reimplementation.
    definitions = source[source.index('enum ENUM_LANG'):source.index('CCanvas              g_canvas;')]
    definitions = re.sub(r'^input group .*$', '', definitions, flags=re.M)
    definitions = re.sub(r'^input\s+', '', definitions, flags=re.M)
    definitions = definitions[:definitions.rfind('//+------------------------------------------------------------------+')]
    funcs = {name: extract_function(source, sig) for name, sig in [
        ('ScanHtfMacroZones', 'void ScanHtfMacroZones()'),
        ('DetectLtfConfirmation', 'void DetectLtfConfirmation(bool isFirstRun = false)'),
        ('IsInKillzone', 'bool IsInKillzone(datetime barTime)')]}
    header = RUN/'OriginalV301Extract.mqh'
    header.write_text(definitions+'\n'+NATIVE_ADAPTER+'\n'+ '\n'.join(funcs.values()), encoding='utf-8')
    save('NATIVE_EXTRACT.json', dict(original_sha256=sha(ROOT/'duc_tri_can_ho_tro.mq5'),
        function_sha256={k: hashlib.sha256(v.encode()).hexdigest() for k, v in funcs.items()},
        adapter='Only market-data API calls and UI/notification side effects are replaced. Native signal and zone bodies are verbatim.',
        scope='Original MQ5 core; this is not an end-to-end run of the old EX5 chart/alert lifecycle.'))
    h = d['h1']; b = d['m5']; ah = cache['h1_atr']; am = cache['m5_atr']
    # All 881 old KZ entries, every new idle candidate, and fixed random non-signals.
    legacy = json.loads((ROOT/'reports/gold_v301_audit/20261101/legacy_signals.json').read_text(encoding='utf-8'))
    samples = [int(np.searchsorted(b[:, 0], x['known_at'])) for x in legacy if x['kz'] and x['pass_struct']]
    samples.extend(int(x[0])+1 for x in cache['native'])
    rng = np.random.default_rng(301)
    samples.extend(rng.integers(500, len(b)-2, size=240).tolist())
    samples = np.asarray(sorted(set(samples)), dtype=int)
    cases = np.column_stack((samples, np.searchsorted(h[:, 0]+3600, b[samples, 0], side='right')-1))
    fixture = RUN/'native_terminal'; files = fixture/'MQL5/Files/gold_v301'
    files.mkdir(parents=True, exist_ok=True)
    for key, values in [('h1', np.column_stack((h, ah))), ('m5', np.column_stack((b, am))), ('cases', cases)]:
        np.savetxt(files/f'{key}.csv', values, delimiter=',', fmt='%.17g' if key != 'cases' else '%d')
    script = RUN/'TestGoldV301Original.mq5'
    script.write_text('#property strict\n#include "OriginalV301Extract.mqh"\n'+NATIVE_TEST, encoding='utf-8')
    np.save(RUN/'native_cases.npy', cases)
    print('NATIVE_PREPARED', len(cases), flush=True)


def run_native():
    import build_fabio_orderflow_indicator as build
    build.RUN = RUN
    manifest = build.compile_one(RUN/'TestGoldV301Original.mq5', 'original_native_core')
    fixture = RUN/'native_terminal'; files = fixture/'MQL5/Files/gold_v301'
    (fixture/'MQL5/Scripts').mkdir(exist_ok=True)
    shutil.copy2(build.TERMINAL, fixture/'terminal64.exe')
    (fixture/'bases').mkdir(exist_ok=True)
    shutil.copy2(build.SEED_FIXTURE/'bases/symbols.custom.dat', fixture/'bases/symbols.custom.dat')
    seed = Path('bases/Custom/history/_CHT_M5_20261025')
    shutil.copytree(build.SEED_FIXTURE/seed, fixture/seed, dirs_exist_ok=True)
    shutil.copy2(RUN/'TestGoldV301Original.ex5', fixture/'MQL5/Scripts/TestGoldV301Original.ex5')
    ini = RUN/'native.ini'
    ini.write_text('[Common]\nLogin=0\nServer=MetaQuotes-Demo\n[Experts]\nEnabled=0\nAllowLiveTrading=0\nAllowDllImport=0\n[StartUp]\nScript=TestGoldV301Original\nSymbol=_CHT_M5_20261025\nPeriod=M1\nShutdownTerminal=1\n', encoding='ascii')
    proc = subprocess.Popen(f'"{fixture/"terminal64.exe"}" /portable /config:"{ini}"', cwd=str(fixture), startupinfo=build.hidden())
    save('NATIVE_PROCESS.json', dict(pid=proc.pid, executable=str(fixture/'terminal64.exe')))
    save('NATIVE_BUILD.json', manifest)
    try:
        code = proc.wait(timeout=45)
        print('NATIVE_EXIT', code, flush=True)
    except subprocess.TimeoutExpired:
        print('NATIVE_RUNNING', proc.pid, flush=True)


NATIVE_ADAPTER = r'''
SZone g_zones[]; SEventLog g_events[]; SConfirmSignal g_lastSignal;
ENUM_CONFIRM_STATE g_confirmState=STATE_IDLE;
int g_atrHandle=102,g_htfAtrHandle=100,g_ltfAtrHandle=101;
int g_statCreated=0,g_statDemand=0,g_statSupply=0,g_statBroken=0,g_statFlipped=0;
datetime g_lastAlertBar=0,g_lastSignalSeenTime=0; int g_lastSignalSeenZone=-1;
bool g_lastSignalSeenBuy=false;
double g_previousDayHigh=0,g_previousDayLow=0;
MqlRates fixtureH[],fixtureM[]; double fixtureHA[],fixtureMA[];
int fixtureHL=-1,fixtureM0=-1;
double GetPipSize(){return .1;}
void RefreshReferenceLevels(){} void DrawReferenceLevels(){}
void DrawSignalArrow(bool buy,datetime t,double p,double a){}
void DrawTradePlanLines(const SConfirmSignal &s){}
void SendSignalAlert(const SConfirmSignal &s){}
bool FixtureTick(const string symbol,MqlTick &tick)
{ ZeroMemory(tick);tick.bid=fixtureM[fixtureM0].open;tick.ask=tick.bid+.2;return true; }
double FixtureDouble(const string symbol,const ENUM_SYMBOL_INFO_DOUBLE kind)
{return fixtureM[fixtureM0].open+(kind==SYMBOL_ASK ? .2 : 0.);}
int FixtureRates(const string symbol,const ENUM_TIMEFRAMES tf,const int pos,const int requested,MqlRates &out[])
{
 bool h=(tf==PERIOD_H1);int last=h?fixtureHL:fixtureM0-pos;
 int n=MathMin(requested,last+1);bool series=ArrayGetAsSeries(out);
 ArraySetAsSeries(out,false);ArrayResize(out,n);
 for(int j=0;j<n;j++){out[j]=h?fixtureH[last-n+1+j]:fixtureM[last-n+1+j];}
 if(!h && pos==0 && n>0){out[n-1].high=out[n-1].low=out[n-1].close=out[n-1].open;}
 ArraySetAsSeries(out,series);return n;
}
int FixtureBuffer(const int handle,const int buffer,const int pos,const int requested,double &out[])
{
 bool h=(handle==100);int last=h?fixtureHL:fixtureM0-pos;
 int n=MathMin(requested,last+1);bool series=ArrayGetAsSeries(out);
 ArraySetAsSeries(out,false);ArrayResize(out,n);
 for(int j=0;j<n;j++)out[j]=h?fixtureHA[last-n+1+j]:fixtureMA[last-n+1+j];
 ArraySetAsSeries(out,series);return n;
}
#define CopyRates FixtureRates
#define CopyBuffer FixtureBuffer
#define SymbolInfoTick FixtureTick
#define SymbolInfoDouble FixtureDouble
'''

NATIVE_TEST = r'''
#undef CopyRates
#undef CopyBuffer
#undef SymbolInfoTick
#undef SymbolInfoDouble
bool ReadFixture(const string name,MqlRates &out[],double &atr[])
{
 int f=FileOpen("gold_v301\\"+name+".csv",FILE_READ|FILE_CSV|FILE_ANSI,',');if(f==INVALID_HANDLE)return false;
 int n=0;
 while(!FileIsEnding(f)){
  string stamp=FileReadString(f);if(stamp=="")break;
  ArrayResize(out,n+1,65536);ArrayResize(atr,n+1,65536);ZeroMemory(out[n]);
  out[n].time=(datetime)StringToDouble(stamp);out[n].open=FileReadNumber(f);
  out[n].high=FileReadNumber(f);out[n].low=FileReadNumber(f);out[n].close=FileReadNumber(f);
  atr[n]=FileReadNumber(f);n++;
 } FileClose(f);return n>0;
}
void OnStart()
{
 MqlRates actualBars[];double actualAtr[];int ah=iATR(_Symbol,PERIOD_M5,14);
 int an=0,bn=0;
 for(int wait=0;wait<40;wait++){
  bn=CopyRates(_Symbol,PERIOD_M5,0,1000,actualBars);
  if(bn>30)an=CopyBuffer(ah,0,0,bn,actualAtr);
  if(an==bn && bn>30)break;Sleep(100);
 }
 if(an==bn && bn>30){
  int af=FileOpen("gold_v301\\actual_iatr.csv",FILE_WRITE|FILE_CSV|FILE_ANSI,',');
  for(int j=0;j<bn;j++)FileWrite(af,(long)actualBars[j].time,DoubleToString(actualBars[j].open,10),
   DoubleToString(actualBars[j].high,10),DoubleToString(actualBars[j].low,10),DoubleToString(actualBars[j].close,10),DoubleToString(actualAtr[j],12));
  FileClose(af);
 } IndicatorRelease(ah);
 if(!ReadFixture("h1",fixtureH,fixtureHA)||!ReadFixture("m5",fixtureM,fixtureMA)){Print("READ_FAILED");return;}
 FilterKillzones=false;InpTpMode=TP_MODE_RR;InpEntryMode=ENTRY_MARKET_CONFIRM;
 AlertConfirm=false;ShowTradeLines=false;ShowArrows=false;UseReferenceLevels=false;
 int cf=FileOpen("gold_v301\\cases.csv",FILE_READ|FILE_CSV|FILE_ANSI,',');
 int zf=FileOpen("gold_v301\\zones_native.csv",FILE_WRITE|FILE_CSV|FILE_ANSI,',');
 int sf=FileOpen("gold_v301\\signals_native.csv",FILE_WRITE|FILE_CSV|FILE_ANSI,',');
 int ci=0;
 while(!FileIsEnding(cf)){
  string first=FileReadString(cf);if(first=="")break;fixtureM0=(int)StringToInteger(first);fixtureHL=(int)FileReadNumber(cf);
  ZeroMemory(g_lastSignal);g_lastSignalSeenTime=0;g_lastSignalSeenZone=-1;g_lastAlertBar=0;ArrayResize(g_events,0);
  ScanHtfMacroZones();
  for(int j=0;j<ArraySize(g_zones);j++){
   SZone z=g_zones[j];if(z.isBroken||z.score<MinScoreShow)continue;
   FileWrite(zf,ci,z.id,(int)z.isSupply,(int)z.type,DoubleToString(z.distal,10),DoubleToString(z.proximal,10),z.score,(long)z.timeStart,z.testCount);
  }
  DetectLtfConfirmation(true);
  SConfirmSignal s=g_lastSignal;
  FileWrite(sf,ci,(int)s.active,(int)s.isBuy,(long)s.time,DoubleToString(s.entry,10),DoubleToString(s.initialSl,10),
    DoubleToString(s.tp1,10),DoubleToString(s.tp2,10),s.zoneId,s.zoneScore);
  ci++;
 }
 FileClose(cf);FileClose(zf);FileClose(sf);
 int done=FileOpen("gold_v301\\done.json",FILE_WRITE|FILE_TXT|FILE_ANSI);
 FileWriteString(done,StringFormat("{\"cases\":%d,\"completed\":true}",ci));FileClose(done);
 Print("GOLD_V301_NATIVE_DONE ",ci);
}
'''


def main():
    parser = argparse.ArgumentParser(); parser.add_argument('stage', choices=['signals', 'prepare-native', 'run-native'])
    args = parser.parse_args()
    {'signals': signals, 'prepare-native': prepare_native, 'run-native': run_native}[args.stage]()


if __name__ == '__main__':
    main()
