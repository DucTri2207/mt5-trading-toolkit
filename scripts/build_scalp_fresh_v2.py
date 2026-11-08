"""Build a separate, locked fresh-zone indicator and a native replay check."""
from pathlib import Path
import shutil
import subprocess
import json

import build_can_ho_tro_scalp as build
from generate_can_ho_tro_oracle import function
from prepare_can_ho_tro_scalp import write_json, sha
from research_scalp_v2 import ROOT, RUN


def main():
    indicator=ROOT/'duc_tri_can_ho_tro_scalp_v2_fresh.mq5'
    source=(ROOT/'duc_tri_can_ho_tro_scalp_lab.mq5').read_text(encoding='utf-8-sig')
    source=source.replace('LAB 0.1','LAB 0.2 FRESH').replace('Lab 0.1','Lab 0.2 FRESH')
    source=source.replace('"4.00"','"4.10"')
    source=source.replace('Scalp lab 0.1: existing H1 sweep core; virtual only; no broker orders',
                          'Fresh-zone research: H1 sweep + M5; <=1 prior test; TP0.5R; EDGE NOT CONFIRMED')
    source=source.replace('input CHTPolicy InpLabPolicy=CHT_TS;','input CHTPolicy InpLabPolicy=CHT_T05;')
    source=source.replace('CanHoTroScalpNative.mqh','CanHoTroScalpNativeV2Fresh.mqh')
    source=source.replace('(!InpLabRoom || InpLabPolicy==CHT_T05 || InpLabPolicy==CHT_T15);',
                          '(!InpLabRoom || InpLabPolicy==CHT_T05 || InpLabPolicy==CHT_T15) &&\n          InpLabPolicy==CHT_T05 && !InpLabRoom && !InpLabBody50;')
    indicator.write_text(source,encoding='utf-8-sig')
    native=(ROOT/'Include/CanHoTroScalpNative.mqh').read_text(encoding='utf-8-sig')
    native=native.replace('#define CAN_HO_TRO_SCALP_NATIVE','#define CAN_HO_TRO_SCALP_NATIVE\n#include "CanHoTroScalpFresh.mqh"')
    native=native.replace('CHTPlannedGate(raw[i]','CHTFreshGate(raw[i]')
    native=native.replace('CHT_v01_','CHT_fresh_v02_').replace('CHT_VERSION,_Symbol','"fresh_v02_fixed_T05",_Symbol')
    native=native.replace('SCALP LAB 0.1 | ','FRESH LAB 0.2 | ').replace(' | INDICATOR ONLY',' | GROSS BEFORE FEES | EDGE UNCONFIRMED')
    (ROOT/'Include/CanHoTroScalpNativeV2Fresh.mqh').write_text(native,encoding='utf-8-sig')
    original=(ROOT/'tests/mql5/TestCanHoTroScalpReplay.mq5').read_text(encoding='utf-8-sig')
    signatures={
        'ReadRates':'bool ReadRates(const string name,MqlRates &out[])',
        'IdeaKey':'string IdeaKey(const CHTCandidate &c)',
        'ExportStopEvent':'void ExportStopEvent(const int f,const int index,const CHTPlan &p,const long before)',
        'ReplayMarket':'void ReplayMarket(const string name,const CHTPolicy policy,const double spread,const double slip,const string cost,const bool room,const bool serial,const bool retest=false,const bool highFirst=false)',
    }
    code='''#property strict
#include "../../Include/CanHoTroScalpDetector.mqh"
#include "../../Include/CanHoTroScalpPlan.mqh"
#include "../../Include/CanHoTroScalpFresh.mqh"
const string CHT_FOLDER="can_ho_tro_scalp_v1\\\\";
MqlRates allH1[],allM5[],allM1[];
CHTCandidate allCandidates[];
CHTPivot allHighs[],allLows[];double atrM5[];
void Progress(const string state,const int count){Print(state," ",count);}
'''
    for name,signature in signatures.items():
        body=function(original,name)
        if name=='ReplayMarket':body=body.replace('CHTPlannedGate(c,','CHTFreshGate(c,')
        code+=signature+'\n{'+body+'}\n'
    code+='''
void OnStart()
{
   int checks=0,failures=0;
   CHTCandidate c;ZeroMemory(c);c.v[2]=1;c.v[19]=98;c.v[21]=100;
   c.v[9]=0;checks++;if(CHTFreshGate(c,.01,false,false)!=CHT_NONE)failures++;
   c.v[9]=1;checks++;if(CHTFreshGate(c,.01,false,false)!=CHT_NONE)failures++;
   c.v[9]=2;checks++;if(CHTFreshGate(c,.01,false,false)!=1001)failures++;
   c.v[9]=1;c.v[27]=3;checks++;if(CHTFreshGate(c,.01,false,false)!=103)failures++;
   bool loaded=ReadRates("m1",allM1);checks++;if(!loaded)failures++;
   int f=FileOpen(CHT_FOLDER+"candidates_c0_mql.csv",FILE_READ|FILE_CSV|FILE_ANSI,',');
   checks++;if(f==INVALID_HANDLE)failures++;
   if(f!=INVALID_HANDLE)
   {
      while(!FileIsEnding(f))
      {
         string stamp=FileReadString(f);if(stamp=="")break;
         CHTCandidate row;row.v[0]=StringToDouble(stamp);
         for(int j=1;j<36;j++)row.v[j]=FileReadNumber(f);
         int n=ArraySize(allCandidates);ArrayResize(allCandidates,n+1,4096);allCandidates[n]=row;
      }
      FileClose(f);
   }
   if(loaded && failures==0)
   {
      ReplayMarket("FRESH_V2",CHT_T05,.20,0.,"LOW",false,true);
      ReplayMarket("FRESH_V2",CHT_T05,.30,.01,"BASE",false,true);
      ReplayMarket("FRESH_V2",CHT_T05,.45,.05,"STRESS",false,true);
   }
   f=FileOpen(CHT_FOLDER+"fresh_v2_result.json",FILE_WRITE|FILE_TXT|FILE_ANSI);
   FileWriteString(f,StringFormat("{\\"checks\\":%d,\\"failures\\":%d,\\"candidate_rows\\":%d}",checks,failures,ArraySize(allCandidates)));FileClose(f);
}
'''
    oracle=ROOT/'tests/mql5/TestScalpFreshV2.mq5';oracle.write_text(code,encoding='utf-8-sig')
    build.RUN=RUN
    manifests=[build.compile_one(indicator,'fresh_v2_indicator'),build.compile_one(oracle,'fresh_v2_oracle')]
    write_json(RUN/'NATIVE_BUILD.json',dict(builds=manifests))
    shutil.copy2(oracle.with_suffix('.ex5'),build.FIXTURE/'MQL5/Scripts'/oracle.with_suffix('.ex5').name)
    ini=RUN/'fresh_v2_fixture.ini'
    ini.write_text('''[Common]
Login=0
Server=MetaQuotes-Demo
[Experts]
Enabled=0
AllowLiveTrading=0
AllowDllImport=0
[StartUp]
Script=TestScalpFreshV2
Symbol=XAUUSD
Period=M5
ShutdownTerminal=1
''',encoding='ascii')
    proc=build.launch_ini(ini,'fresh_v2_process.json')
    try:print('FIXTURE_EXIT',proc.wait(timeout=45),flush=True)
    except subprocess.TimeoutExpired:print('FIXTURE_RUNNING',proc.pid,flush=True)


if __name__=='__main__':main()
