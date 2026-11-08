"""Keep the original canvas/UI and replace ONLY the lab's detector/lifecycle adapters."""
from __future__ import annotations

import re
from prepare_can_ho_tro_scalp import ROOT, RUN, write_json, sha


def replace_body(text,name,body):
    match=re.search(r'\b'+name+r'\([^;]*?\)\s*\{',text,re.S)
    if not match:raise ValueError(name)
    start=text.index('{',match.start());end=start+1;depth=1
    while depth:
        depth+=(text[end]=='{')-(text[end]=='}');end+=1
    return text[:start]+'{\n'+body+'\n}'+text[end:]


def main():
    original=ROOT/'duc_tri_can_ho_tro_scalp.mq5'
    text=original.read_text(encoding='utf-8-sig')
    source_manifest=json_load(RUN/'ORIGINAL_SOURCE_MANIFEST.json')
    assert sha(original)==source_manifest['files'][0]['sha256'],'Original source changed'
    text=text.replace('#property version     "3.12"','#property version     "4.00"')
    text=re.sub(r'#property description .*', '#property description "Scalp lab 0.1: existing H1 sweep core; virtual only; no broker orders"',text,count=1)
    text=text.replace('v3.01','SCALP LAB 0.1')
    # IndicatorCreate has a 64-parameter limit. Put the five lab controls first
    # so a caller can override them and retain inherited defaults for the UI.
    native=(ROOT/'Include/CanHoTroScalpNative.mqh').read_text(encoding='utf-8')
    controls=native[native.index('input group'):native.index('#endif',native.index('input group'))]
    input_start=text.index('input group')
    text=text[:input_start]+'''#define CHT_EXTERNAL_CONFIG
#include "Include/CanHoTroScalpTypes.mqh"
#include "Include/CanHoTroScalpPlan.mqh"
#define CHT_INPUTS_EARLY
'''+controls+'\n'+text[input_start:]
    marker='CCanvas              g_canvas;'
    text=text.replace(marker,'''#include "Include/CanHoTroScalpDetector.mqh"
#include "Include/CanHoTroScalpPlan.mqh"
#include "Include/CanHoTroScalpState.mqh"
'''+marker,1)
    critical=['BaseMaxBars','BaseBarATR','BaseTotalATR','DepartATR','DepartBars','LegInBars','AtrLen',
              'MaxHistory','MaxTests','MaxAgeBars','UseFlip','FlipLifeBars','MinScoreShow',
              'WDepart','WBase','WFresh','WReversal','WMtf','WickRatioMin','MinDisplacementATR',
              'HtfTrendMAPeriod','MaxHtfEmaDistanceATR','SlBufferATR','FilterKillzones','KillzoneHourOffset',
              'ExcludeWeakKzHours','MaxSpreadPrice','MaxSlPips','MinSlPips','UseHtfTrendFilter','UseReferenceLevels','UseLtfConfirm','LtfBarsScan']
    terms=[]
    for name in critical:
        match=re.search(r'input\s+\w+\s+'+name+r'\s*=\s*([^;]+);',text)
        assert match,name
        terms.append(f'{name}=={match[1].strip()}')
    checker='''#include "Include/CanHoTroScalpNative.mqh"
bool CHTLockedPreset()
{
   return '''+' &&\n          '.join(terms)+''' && HtfPeriod==PERIOD_H1 && LtfPeriod==PERIOD_M5 &&
          SweepLevelMode==SWEEP_PROXIMAL && InpSlMode==SL_STRUCTURAL_SWING && !InpUseAutoBE &&
          InpEntryMode==ENTRY_MARKET_CONFIRM && InpTpMode==TP_MODE_SCALP && InpTp1RR==.5 && MinRR==.5 &&
          (InpLabSlippageTicks==0 || InpLabSlippageTicks==1 || InpLabSlippageTicks==5) &&
          (!InpLabBody50 || (InpLabPolicy==CHT_T15 && InpLabRoom)) &&
          (!InpLabRoom || InpLabPolicy==CHT_T05 || InpLabPolicy==CHT_T15);
}
'''
    text=text.replace('int OnInit()',checker+'\nint OnInit()',1)
    text=text.replace('int OnInit()\n{','''int OnInit()
{
   if(!CHTLockedPreset()){Print("Lab 0.1 requires the locked research preset; unsupported config");return INIT_PARAMETERS_INCORRECT;}
''',1)
    start=text.index('   // Nạp hoặc lưu cấu hình Telegram Bot')
    end=text.index('   return INIT_SUCCEEDED;',start)
    text=text[:start]+'''   // The lab never reads/sends Telegram credentials or sends notifications.
   CHTNativeInit();
   Print("Can ho tro scalp LAB 0.1: original canvas; H1 sweep core; indicator only");
'''+text[end:]
    text=text.replace('void OnDeinit(const int reason)\n{','void OnDeinit(const int reason)\n{\n   CHTNativeSave();',1)
    text=replace_body(text,'OnCalculate','''   static bool first=true;
   if(first){MqlTick tick;bool ready=SymbolInfoTick(_Symbol,tick);Print("Lab first calculate: bars=",rates_total," chart=",ChartID()," quote=",ready," bid=",tick.bid);first=false;}
   if(rates_total<40)return 0;
   CHTNativeCalculate();
   return rates_total;''')
    text=replace_body(text,'ScanHtfMacroZones','   MqlTick tick;if(SymbolInfoTick(_Symbol,tick))CHTNativeZones(tick.time);')
    text=replace_body(text,'DetectLtfConfirmation','   // Replaced by raw candidate adapter. It cannot mutate plan lifecycle.')
    text=replace_body(text,'ManageActiveSignal','   // CHTQuote is the sole lifecycle owner. Legacy double-close path retired.')
    text=replace_body(text,'DispatchTelegram','   return false; // no external messaging from this lab')
    text=replace_body(text,'SendSignalAlert','   return; // lab events are local only')
    text=text.replace('   // 4. Take Profit 1 Line (Xanh Mint)', '''   if(sig.tp1<=0 && sig.tp2<=0)
   {ObjectDelete(0,g_prefix+"PLAN_TP1");ObjectDelete(0,g_prefix+"PLAN_TP2");ChartRedraw(0);return;}
   // 4. Take Profit 1 Line (Xanh Mint)''',1)
    text=text.replace('(InpEntryMode == ENTRY_MARKET_CONFIRM ? "Market" : "Plan")','(g_chtPlan.state==CHT_FILLED?"Fill":"Requested")')
    text=text.replace('      g_canvas.TextOut(planValX, curPlanY, statusStr,',
                      '      statusStr=CHTNativeStatus();\n      g_canvas.TextOut(planValX, curPlanY, statusStr,',1)
    text=text.replace('"Entry (Market/Limit):" : "Vào lệnh (Mkt/Limit):"','"Fill / Requested:" : "Khớp / Dự kiến:"')
    text=text.replace('g_lastSignal.entryMarket, _Digits, g_lastSignal.entryLimit);',
                      'g_lastSignal.entry, _Digits, g_chtPlan.requested);',1)
    text=text.replace('"Stop Loss / BE:" : "Cắt lỗ / Hòa vốn BE:"','"SL current / initial:" : "SL hiện tại / ban đầu:"')
    old='string slStr = StringFormat("%.*f (%.0fp) | BE: %.*f", _Digits, g_lastSignal.sl, PriceToPips(MathAbs(g_lastSignal.entry - g_lastSignal.initialSl)), _Digits, g_lastSignal.bePrice);'
    new='string slStr = StringFormat("%.*f / %.*f | R0 %.2f", _Digits, g_lastSignal.sl, _Digits, g_lastSignal.initialSl, g_chtPlan.risk);'
    new='string slStr = StringFormat("%.*f / %.*f | ", _Digits, g_lastSignal.sl, _Digits, g_lastSignal.initialSl)+(g_chtPlan.state==CHT_PENDING?"R0 PENDING":StringFormat("R0 %.2f",g_chtPlan.risk));'
    assert old in text;text=text.replace(old,new,1)
    # Remove unconfirmed fallback trade proposals from the inherited idle panel.
    begin=text.index('      // Kế hoạch Limit dự phòng')
    end=text.index('      g_canvas.TextOut(28, curPlanY, (g_lang == LANG_EN ? "Stats',begin)
    text=text[:begin]+'''      g_canvas.TextOut(28,curPlanY,CHTNativeStatus(),ColorToARGB(C'250,204,21',255));
      curPlanY+=planPitch;
      g_canvas.TextOut(28,curPlanY,"H1 level -> sweep -> closed M5 confirmation",ColorToARGB(C'148,163,184',255));
      curPlanY+=planPitch;
'''+text[end:]
    text=text.replace("ColorToARGB(C'52,211,153', 35)","ColorToARGB(C'26,52,50', 255)")
    text=text.replace("ColorToARGB(C'248,113,113', 35)","ColorToARGB(C'53,39,45', 255)")
    old='string tpStr = StringFormat("%.*f (+%.0fp) / %.*f (%.1fR)", _Digits, g_lastSignal.tp1, PriceToPips(MathAbs(g_lastSignal.tp1 - g_lastSignal.entry)), _Digits, g_lastSignal.tp2, g_lastSignal.rr2);'
    new='string tpStr = g_chtPlan.policy==CHT_TS ? "STRUCTURE TRAIL / NO FIXED TP" : StringFormat("%.*f (%.2fR)",_Digits,g_lastSignal.tp1,g_lastSignal.rr1);'
    assert old in text;text=text.replace(old,new,1)
    # Disable defaults even though dispatch and signal alerts are removed.
    for name in ['AlertPopup','AlertPush','AlertSoundOn','AlertNewZone','AlertEnter','AlertBreak','AlertConfirm','TgEnable','AlertBeTriggered']:
        text=re.sub(r'(input\s+bool\s+'+name+r'\s*=\s*)true',r'\1false',text)
    target=ROOT/'duc_tri_can_ho_tro_scalp_lab.mq5';target.write_text(text,encoding='utf-8')
    write_json(RUN/'LAB_ADAPTER_MANIFEST.json',{'original_sha256':sha(original),'lab_sha256':sha(target),
        'retained':'Existing zone drawing, canvas/dashboard, appearance and theme code',
        'replaced':'H1 scan adapter; closed M5 candidate feed; single quote lifecycle; native persistence/watermark',
        'default_virtual_plans':False,'broker_trade_api_used':False,'network_alerts_disabled':True})
    print(str(target))


def json_load(path):
    import json
    return json.loads(path.read_text(encoding='utf-8'))


if __name__=='__main__':
    import sys
    sys.stdout.reconfigure(encoding='utf-8');main()
