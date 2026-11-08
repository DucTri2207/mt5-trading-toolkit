"""Mechanical port of the frozen MQL5 source; contains no Python detector."""
from pathlib import Path
import hashlib
import re

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'can_ho_tro_v4'
INC = OUT / 'MQL5/Include/CanHoTroV4'


def function(text, signature):
    start = text.index(signature + '\n{')
    pos = text.index('{', start)
    depth = 1
    end = pos + 1
    while depth:
        depth += (text[end] == '{') - (text[end] == '}')
        end += 1
    return text[start:end]


def write(name, content):
    path = INC / name
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        raise FileExistsError(path)
    path.write_text(content + '\n', encoding='utf-8')


def main():
    original = ROOT / 'duc_tri_can_ho_tro.mq5'
    assert hashlib.sha256(original.read_bytes()).hexdigest() == '5a244553a7e659fb50c78481294531e38b9e60d1d1c0b11adbc26db7c7226405'
    src = original.read_text(encoding='utf-8-sig')
    types = src[src.index('enum ENUM_LANG'):src.index('//+------------------------------------------------------------------+\n//| Input Parameters')]
    structs = src[src.index('struct SZone'):src.index('//+------------------------------------------------------------------+\n//| Biến toàn cục')]
    structs = structs.replace('int               id;', 'long              id;')
    structs = structs.replace('int               zoneId;', 'long              zoneId;')
    structs = structs.replace('   datetime          timeStart;', '   datetime          timeFormed;\n   datetime          timeKnown;\n   datetime          timeInvalid;\n   datetime          timeStart;')
    structs = structs.replace('struct SConfirmSignal\n{', '''struct SConfirmSignal
{
   string            signal_id;
   long              source_zone_id;
   datetime          confirm_bar_open;
   datetime          signal_known_time;
   datetime          publish_time;
   datetime          order_place_time;
   datetime          fill_time;
   datetime          exit_time;
   datetime          sweep_time;
   datetime          zone_known_time;
   double            source_distal;
   double            source_proximal;
   double            choch_level;
   double            arrow_anchor;''')
    write('Types.mqh', '#ifndef CHT_V4_TYPES\n#define CHT_V4_TYPES\n' + types + structs + '\n#endif')
    inputs = src[src.index('input group'):src.index('//+------------------------------------------------------------------+\n//| Cấu trúc dữ liệu')]
    lines = []
    for line in inputs.splitlines():
        if line.startswith('input group'):
            lines.extend(['#ifndef CHT_V4_NATIVE_FIXTURE', line, '#endif'])
        else:
            lines.append(re.sub(r'^input\s+', 'V4_INPUT ', line))
    write('Inputs.mqh', '''#ifndef CHT_V4_INPUTS
#define CHT_V4_INPUTS
#ifdef CHT_V4_NATIVE_FIXTURE
#define V4_INPUT
#else
#define V4_INPUT input
#endif
''' + '\n'.join(lines) + '''
V4_INPUT bool InpCompatV301 = false; // true: literal v3.01 core comparison; causal guards disabled
V4_INPUT string InpV4LedgerFolder = "CanHoTroV4";
#undef V4_INPUT
#endif''')

    zones = function(src, 'void ScanHtfMacroZones()')
    zones = zones.replace('void ScanHtfMacroZones()', 'void CZoneEngine::Scan()')
    zones = zones.replace('         SZone zone;', '''         SZone zone;
         ZeroMemory(zone);
         zone.timeFormed = hRates[baseEnd + DepartBars].time;
         zone.timeKnown = zone.timeFormed + PeriodSeconds(scanTf);
         zone.timeInvalid = isBroken ? hRates[brokenBar].time + PeriodSeconds(scanTf) : 0;''')
    zones = zones.replace('zone.id = ArraySize(g_zones) + 1;', 'zone.id = InpCompatV301 ? ArraySize(g_zones) + 1 : V4ZoneId(hRates[baseStart].time,isSupply,zDistal,zProximal);')
    zones = zones.replace('            if(!fBroken)', '            if(!fBroken || !InpCompatV301)')
    zones = zones.replace('               SZone flipZ;', '''               SZone flipZ;
               ZeroMemory(flipZ);
               flipZ.timeFormed = hRates[brokenBar].time;
               flipZ.timeKnown = flipZ.timeFormed + PeriodSeconds(scanTf);
               // Invalidity is known only after the invalidating H1 closes.
               if(fBroken || fTests >= MaxTests || copied - 1 >= brokenBar + FlipLifeBars)
                  flipZ.timeInvalid = fTimeEnd + PeriodSeconds(scanTf);''')
    zones = zones.replace('flipZ.id = ArraySize(g_zones) + 1;', 'flipZ.id = InpCompatV301 ? ArraySize(g_zones) + 1 : V4ZoneId(hRates[brokenBar].time,flipSupply,fDistal,fProximal);')
    zones = zones.replace('flipZ.isBroken = false;', 'flipZ.isBroken = !InpCompatV301 && flipZ.timeInvalid > 0 && flipZ.timeInvalid <= g_v4Now;')
    zones = zones.replace('   RefreshReferenceLevels();\n   DrawReferenceLevels();', '   RefreshReferenceLevels();\n   DrawReferenceLevels();')
    write('Zones.mqh', '''#ifndef CHT_V4_ZONES
#define CHT_V4_ZONES
class CZoneEngine { public: static void Scan(); };
''' + zones + '\n#endif')

    signal = function(src, 'void DetectLtfConfirmation(bool isFirstRun = false)')
    signal = signal.replace('void DetectLtfConfirmation(bool isFirstRun = false)', 'void CSignalEngine::Detect(bool isFirstRun)')
    signal = signal.replace('   double ltfAtr =', '''   if(!InpCompatV301 && ltfRates[1].time <= g_v4LastEvaluated) return;
   if(!InpCompatV301) g_v4LastEvaluated = ltfRates[1].time;
   double ltfAtr =''')
    signal = signal.replace('      double zMin =', '''      if(!InpCompatV301 && (g_zones[z].timeKnown > g_v4Now ||
         (g_zones[z].timeInvalid > 0 && g_zones[z].timeInvalid <= g_v4Now))) continue;
      double zMin =''', 1)
    signal = signal.replace('         double fullRng =', '''         if(!InpCompatV301 && ltfRates[s].time < g_zones[z].timeKnown) continue;
         double fullRng =''')
    signal = signal.replace('                rr1 < MinRR || rr2 < rr1)', '''                (InpCompatV301 ? rr1 < MinRR : rr1 + V4_RR_EPSILON < MinRR) ||
                (InpCompatV301 ? rr2 < rr1 : rr2 + V4_RR_EPSILON < rr1))''')
    gate_start = signal.index('             bool sameProcessedSignal =')
    assignment_start = signal.index('             g_lastSignal.active', gate_start)
    assignment_end = signal.index('             g_lastSignalSeenTime', assignment_start)
    assignment = signal[assignment_start:assignment_end].replace('g_lastSignal.', 'candidate.')
    publication_end = signal.index('             double arrowAnchor', assignment_end)
    new = '''             SConfirmSignal candidate;
             ZeroMemory(candidate);
''' + assignment + '''
             candidate.confirm_bar_open = ltfRates[cBar].time;
             candidate.signal_known_time = ltfRates[cBar].time + PeriodSeconds(ltf);
             candidate.publish_time = g_v4Now;
             candidate.source_zone_id = g_zones[z].id;
             candidate.zone_known_time = g_zones[z].timeKnown;
             candidate.source_distal = g_zones[z].distal;
             candidate.source_proximal = g_zones[z].proximal;
             candidate.sweep_time = ltfRates[sweepBar].time;
             candidate.choch_level = chochLevel;
             candidate.arrow_anchor = isBuySignal ? ltfRates[cBar].low : ltfRates[cBar].high;
             candidate.signal_id = V4SignalId(candidate);
             bool sameProcessedSignal = (g_lastSignalSeenTime == candidate.time &&
                                         g_lastSignalSeenZone == candidate.zoneId &&
                                         g_lastSignalSeenBuy == candidate.isBuy);
             bool blocked = sameProcessedSignal || g_lastSignal.active;
             // The detector always exposes candidates; the plan controls publication separately.
             V4Candidate(candidate, blocked ? (sameProcessedSignal ? "DUPLICATE" : "ACTIVE_PLAN") : "PUBLISHED");
             if(blocked) continue;
             if(!V4PersistPublished(candidate)) { g_v4IoFailed = true; return; }
             g_lastSignal = candidate;
             g_lastSignalSeenTime = candidate.time;
             g_lastSignalSeenZone = candidate.zoneId;
             g_lastSignalSeenBuy = candidate.isBuy;
'''
    signal = signal[:gate_start] + new + signal[publication_end:]
    # Continue examining all remaining source zones for the candidate ledger. The first
    # publication activates the display plan, so later eligible zones are explicitly blocked.
    signal = signal.replace('            break;\n         }\n         else if(confirmBar', '            if(InpCompatV301) break;\n         }\n         else if(confirmBar')
    write('Signals.mqh', '''#ifndef CHT_V4_SIGNALS
#define CHT_V4_SIGNALS
class CSignalEngine { public: static void Detect(bool isFirstRun=false); };
''' + signal + '\n#endif')

    # Preserve the UI and native callbacks; only the shared core bodies/types/inputs move.
    indicator = src
    indicator = indicator.replace(src[src.index('enum ENUM_LANG'):src.index('CCanvas              g_canvas;')],
                                   '#include <CanHoTroV4/Types.mqh>\n#include <CanHoTroV4/Inputs.mqh>\n\n')
    indicator = indicator.replace('int                  g_lastSignalSeenZone', 'long                 g_lastSignalSeenZone')
    indicator = indicator.replace(function(src, 'void ScanHtfMacroZones()'), '#include <CanHoTroV4/Zones.mqh>\nvoid ScanHtfMacroZones(){ CZoneEngine::Scan(); }')
    indicator = indicator.replace(function(src, 'void DetectLtfConfirmation(bool isFirstRun = false)'), '#include <CanHoTroV4/Signals.mqh>\nvoid DetectLtfConfirmation(bool isFirstRun){ CSignalEngine::Detect(isFirstRun); }')
    indicator = indicator.replace('int OnInit()\n{', '''#include <CanHoTroV4/Identity.mqh>
#include <CanHoTroV4/Logger.mqh>

int OnInit()
{''')
    indicator = indicator.replace('   // Nạp hoặc lưu cấu hình Telegram Bot', '''   if(!V4OpenLedger()) return INIT_FAILED;
   V4RestoreArrows();
   // Nạp hoặc lưu cấu hình Telegram Bot''')
    indicator = indicator.replace('void OnDeinit(const int reason)\n{', 'void OnDeinit(const int reason)\n{\n   V4CloseLedger();')
    indicator = indicator.replace('   if(rates_total < AtrLen', '''   MqlTick v4Tick;
   if(!SymbolInfoTick(_Symbol,v4Tick) || v4Tick.time<=0) return prev_calculated;
   g_v4Now=v4Tick.time;
   if(g_v4IoFailed) return prev_calculated;
   if(rates_total < AtrLen''')
    indicator = indicator.replace('"DucTri_CV"', '"DucTri_V4_CV"').replace('"DucTri_"', '"DucTri_V4_"')
    indicator = indicator.replace('"%sZ_%d"', '"%sZ_%I64d"')
    indicator = indicator.replace('"%s %d pts | Râu: %.*f", g_lastSignal.zoneType, g_lastSignal.zoneScore, _Digits, g_lastSignal.sweepPrice',
                                   '"%s #%I64d %.2f–%.2f", g_lastSignal.zoneType, g_lastSignal.source_zone_id, g_lastSignal.source_distal, g_lastSignal.source_proximal')
    indicator = indicator.replace('#property version     "3.01"', '#property version     "4.00"')
    indicator = indicator.replace('v3.01', 'v4.00 M1 LAB')
    target = OUT / 'MQL5/Indicators/duc_tri_can_ho_tro_v4.mq5'
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists(): raise FileExistsError(target)
    target.write_text(indicator, encoding='utf-8')
    print('MQL5 port written; compile and runtime verification still required')


if __name__ == '__main__':
    main()
