"""Scoped claude_014 real-chart check. Only the designated portable, never the real terminal."""
from pathlib import Path
import sys,shutil,json,re,subprocess
from v4_build_m1 import compile_source
ROOT=Path(__file__).resolve().parents[1]
RUN=ROOT/'reports/can_ho_tro_v4/20261102_v403_v1'
PORT=ROOT/'reports/can_ho_tro_v4/20261102_m3a_v1/portable_terminal'
def build():
    shutil.copytree(ROOT/'can_ho_tro_v4/MQL5',PORT/'MQL5',dirs_exist_ok=True)
    for label,rel in [('indicator_final','Indicators/duc_tri_can_ho_tro_v4.mq5'),('EA_final','Experts/CanHoTroV4_TesterEA.mq5')]:
        p=PORT/'MQL5'/rel;r=compile_source(PORT,p,RUN/('COMPILE_'+label+'.log'))
        (RUN/('BUILD_'+label+'.json')).write_text(json.dumps(r,indent=2));print(label,r['passed'],flush=True);assert r['passed']
        shutil.copy2(p.with_suffix('.ex5'),(ROOT/'can_ho_tro_v4/MQL5'/rel).with_suffix('.ex5'))
    previous=(RUN/'TestV403ReferenceChart.mq5').read_text(encoding='utf-8-sig')
    wrapper=previous[previous.index('\nvoid ReferenceReplay()'):].replace('g_prefix="V403_REFERENCE_";','g_v4QuietPlan=true;g_prefix="V403_REFERENCE_";')
    body=(ROOT/'can_ho_tro_v4/MQL5/Indicators/duc_tri_can_ho_tro_v4.mq5').read_text(encoding='utf-8-sig')
    body=re.sub(r'^#property indicator_.*\n','',body,flags=re.M)
    for name in ['OnInit','OnDeinit','OnTimer','OnCalculate','OnChartEvent']:body=re.sub(r'\b'+name+r'\b','ReferenceUnused_'+name,body)
    controller=(ROOT/'tests/v4/TestV403Chart.mq5').read_text(encoding='utf-8-sig').replace('void OnStart()','void RunChartChecks()')
    generated=(body+'\n'+controller+'\n'+wrapper).replace('V403_final\\\\zones_','V403_final2\\\\zones_').replace('v403_chart','v403_final_chart')
    p=PORT/'MQL5/Scripts/V4/TestV403Final.mq5';p.write_text(generated,encoding='utf-8-sig');shutil.copy2(p,RUN/p.name)
    r=compile_source(PORT,p,RUN/'COMPILE_chart_final.log');(RUN/'BUILD_chart_final.json').write_text(json.dumps(r,indent=2));print('chart/reference',r['passed'],flush=True);assert r['passed']
    template=PORT/'MQL5/Profiles/Templates/v403.tpl';s=template.read_text(encoding='utf-16').replace('InpV4LedgerFolder=V403_final','InpV4LedgerFolder=V403_final2');template.write_bytes(s.replace('\n','\r\n').encode('utf-16'))
def launch():
    ini=RUN/'chart_v403_final.ini';ini.write_text('[Experts]\nEnabled=1\nAllowLiveTrading=0\nAllowDllImport=0\n[StartUp]\nScript=V4\\TestV403Final\nSymbol=XAUUSD\nPeriod=M5\nShutdownTerminal=0\n',encoding='ascii')
    si=subprocess.STARTUPINFO();si.dwFlags|=subprocess.STARTF_USESHOWWINDOW;si.wShowWindow=0
    p=subprocess.Popen(f'"{PORT/"terminal64.exe"}" /portable /config:"{ini}"',cwd=PORT,startupinfo=si);print('portable',p.pid)
if __name__=='__main__':
    if 'build' in sys.argv:build()
    if 'launch' in sys.argv:launch()
