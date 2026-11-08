"""Generate MQL numerical oracle from the immutable v3.12 source bodies.

Only I/O adapters, trace fields and pure helper outputs are added. The original
zone and sweep/pivot/first-confirm loops are copied, not reconstructed in Python.
"""
from __future__ import annotations

import re
from prepare_can_ho_tro_scalp import ROOT, RUN, write_json, sha


def function(source, name):
    at = source.index(name+'(')
    # Forward declarations exist; select the occurrence followed by a body.
    for match in re.finditer(r'\b'+name+r'\([^;]*?\)\s*\{', source, re.S):
        at = match.start()
        brace = source.index('{', at)
        depth = 1
        end = brace+1
        while depth:
            depth += (source[end] == '{')-(source[end] == '}')
            end += 1
        return source[brace+1:end-1]
    raise ValueError(name)


def main():
    original = ROOT/'duc_tri_can_ho_tro_scalp.mq5'
    source = original.read_text(encoding='utf-8-sig')
    wanted = ['BaseMaxBars','BaseBarATR','BaseTotalATR','DepartATR','DepartBars','LegInBars',
              'AtrLen','MaxHistory','MaxTests','MaxAgeBars','UseFlip','FlipLifeBars','MinScoreShow',
              'WDepart','WBase','WFresh','WReversal','WMtf','WickRatioMin','MinDisplacementATR',
              'HtfTrendMAPeriod','MaxHtfEmaDistanceATR','SlBufferATR','FilterKillzones',
              'KillzoneHourOffset','ExcludeWeakKzHours']
    constants = []
    for name in wanted:
        m = re.search(r'input\s+(int|double|bool)\s+'+name+r'\s*=\s*([^;]+);', source)
        if not m:
            raise ValueError('Missing default '+name)
        constants.append(f'const {m[1]} {name}={m[2].strip()};')
    enum = source[source.index('enum ENUM_ZONE_TYPE'):source.index('enum ENUM_CONFIRM_STATE')]
    zone = source[source.index('struct SZone'):source.index('struct SEventLog')]
    zone = zone.replace('SZone','CHTZone').replace('};','   datetime baseTime,flipOrigin,availableAt;\n};',1)
    types = '''// Generated from v3.12; run scripts/generate_can_ho_tro_oracle.py.
#ifndef CAN_HO_TRO_SCALP_TYPES
#define CAN_HO_TRO_SCALP_TYPES
'''+'''#ifndef CHT_EXTERNAL_CONFIG
'''+enum+'\n'.join(constants)+'''
const int SweepLevelMode=0; // original default SWEEP_PROXIMAL
const int SWEEP_DISTAL=1;
#endif
'''+zone+'''
struct CHTCandidate { double v[36]; };
struct CHTContext
{
   double trendClose,trendMa,trendAtr,dayHigh,dayLow;
   datetime trendTime,dayTime;
   int m5Index,h1Count;
};
#define CHT_VERSION "can_ho_tro_scalp_0.1"
#endif
'''
    (ROOT/'Include/CanHoTroScalpTypes.mqh').write_text(types,encoding='utf-8')
    zone_body = function(source,'ScanHtfMacroZones')
    zone_body = zone_body[zone_body.index('   int startIdx'):]
    zone_body = zone_body.replace('SZone','CHTZone')
    zone_body = zone_body.replace('CHTZone zone;', '''CHTZone zone;
          zone.baseTime=hRates[baseStart].time;zone.flipOrigin=0;
          zone.availableAt=hRates[baseEnd+DepartBars].time+3600;''')
    zone_body = zone_body.replace('CHTZone flipZ;', '''CHTZone flipZ;
                flipZ.baseTime=hRates[baseStart].time;
                flipZ.flipOrigin=hRates[brokenBar].time;flipZ.availableAt=flipZ.flipOrigin+3600;''')
    detect_body = function(source,'DetectLtfConfirmation')
    detect_body = detect_body[detect_body.index('   for(int z = 0;'):detect_body.index('      // Nếu tìm thấy nến xác nhận')]
    detect_body = detect_body.replace('g_zones','zones')
    detect_body = detect_body.replace('if(sw > 0 && sw < copied - 1)', 'if(sw > (closedOnly?1:0) && sw < copied - 1)')
    header = '''// Numerical loops copied from immutable v3.12, with trace-only adapters.
#ifndef CAN_HO_TRO_SCALP_DETECTOR
#define CAN_HO_TRO_SCALP_DETECTOR
#include "CanHoTroScalpTypes.mqh"
void CHTScanZones(const MqlRates &hRates[],const double &hAtr[],CHTZone &g_zones[])
{
   int copied=ArraySize(hRates);ArrayResize(g_zones,0);
   if(copied<39)return;
   int g_statCreated=0,g_statDemand=0,g_statSupply=0,g_statBroken=0,g_statFlipped=0;
   int scanTf=PERIOD_H1;
'''+zone_body+'''
}
bool CHTInKillzone(datetime barTime)
{'''+function(source,'IsInKillzone')+'''
}
double CHTObstacle(const CHTZone &zones[],const bool buy,const double entry,
                   const CHTContext &ctx,datetime &origin)
{
   double best=0;origin=0;
   double day=buy?ctx.dayHigh:ctx.dayLow;
   if((buy && day>entry)||(!buy && day>0 && day<entry)){best=day;origin=ctx.dayTime;}
   for(int j=0;j<ArraySize(zones);j++)
   {
      if(zones[j].isBroken || zones[j].isSupply==(!buy))continue;
      double lo=MathMin(zones[j].distal,zones[j].proximal),hi=MathMax(zones[j].distal,zones[j].proximal);
      if(lo<=entry && entry<=hi){origin=zones[j].baseTime;return entry;}
      double level=zones[j].proximal;
      if((buy && level>entry)||(!buy && level<entry))
         if(best==0 || MathAbs(level-entry)<MathAbs(best-entry)){best=level;origin=zones[j].baseTime;}
   }
   return best;
}
void CHTFindRaw(const MqlRates &ltfRates[],const double ltfAtr,const CHTZone &zones[],
                const CHTContext &ctx,CHTCandidate &out[],const bool closedOnly=false)
{
   ArrayResize(out,0);int copied=ArraySize(ltfRates);
   if(copied<30 || ltfAtr<=0)return;
   bool inPoiGlobal=false,sweepFoundGlobal=false;
'''+detect_body+'''
      if(confirmBar!=1)continue;
      bool buy=!isSupply;int gate=0;
      if(MathAbs(ltfRates[1].close-ltfRates[1].open)<MinDisplacementATR*ltfAtr)gate=1;
      if(gate==0 && !CHTInKillzone(ltfRates[1].time))gate=2;
      if(gate==0 && ((buy && ctx.trendClose<=ctx.trendMa)||(!buy && ctx.trendClose>=ctx.trendMa)))gate=3;
      if(gate==0 && (ctx.trendAtr<=0 || MathAbs(ctx.trendClose-ctx.trendMa)/ctx.trendAtr>MaxHtfEmaDistanceATR))gate=4;
      int lookback=MathMin(copied-1,MathMax(5,sweepBar));
      double anchor=buy?ltfRates[1].low:ltfRates[1].high;
      for(int b=1;b<=lookback;b++)anchor=buy?MathMin(anchor,ltfRates[b].low):MathMax(anchor,ltfRates[b].high);
      double stop=anchor+(buy?-SlBufferATR:SlBufferATR)*ltfAtr;
      double mid=(ltfRates[1].open+ltfRates[1].close)/2.;
      datetime omt,olt;
      double om=CHTObstacle(zones,buy,ltfRates[1].close,ctx,omt);
      double ol=CHTObstacle(zones,buy,mid,ctx,olt);
      int count=ArraySize(out);ArrayResize(out,count+1);CHTCandidate r;
      r.v[0]=(double)ltfRates[1].time;r.v[1]=r.v[0]+300;r.v[2]=(double)buy;
      r.v[3]=(double)zones[z].baseTime;r.v[4]=zones[z].baseBars;r.v[5]=(double)zones[z].isFlip;
      r.v[6]=(double)zones[z].flipOrigin;r.v[7]=zones[z].id;r.v[8]=zones[z].score;r.v[9]=zones[z].testCount;
      r.v[10]=zones[z].distal;r.v[11]=zones[z].proximal;r.v[12]=(double)zones[z].availableAt;
      r.v[13]=(double)ltfRates[sweepBar].time;r.v[14]=sweepPrice;
      r.v[15]=(double)ltfRates[pivotBar].time;r.v[16]=chochLevel;
      r.v[17]=(double)ltfRates[pivotBar-1].time+300;r.v[18]=ltfAtr;r.v[19]=stop;r.v[20]=anchor;
      r.v[21]=ltfRates[1].close;r.v[22]=mid;r.v[23]=(double)ctx.trendTime;
      r.v[24]=ctx.trendClose;r.v[25]=ctx.trendMa;r.v[26]=ctx.trendAtr;r.v[27]=gate;
      r.v[28]=zones[z].availableAt>ltfRates[sweepBar].time?5:0;
      r.v[29]=om;r.v[30]=ol;r.v[31]=(double)omt;r.v[32]=(double)olt;
      r.v[33]=z;r.v[34]=ctx.m5Index;r.v[35]=ctx.h1Count;out[count]=r;
   }
}
void CHTATR(const MqlRates &rates[],double &out[])
{
   int n=ArraySize(rates);ArrayResize(out,n);ArrayInitialize(out,0.0);if(n<=14)return;
   double tr[];ArrayResize(tr,n);tr[0]=0;double sum=0;
   for(int i=1;i<n;i++)tr[i]=MathMax(rates[i].high,rates[i-1].close)-MathMin(rates[i].low,rates[i-1].close);
   for(int i=1;i<=14;i++)sum+=tr[i];out[14]=sum/14.;
   for(int i=15;i<n;i++)out[i]=out[i-1]+(tr[i]-tr[i-14])/14.;
}
void CHTEMA(const MqlRates &rates[],double &out[])
{
   int n=ArraySize(rates);ArrayResize(out,n);if(n==0)return;out[0]=rates[0].close;
   for(int i=1;i<n;i++)out[i]=rates[i].close*(2./51.)+out[i-1]*(49./51.);
}
int CHTLower(const MqlRates &rates[],datetime at)
{
   int l=0,r=ArraySize(rates);while(l<r){int m=(l+r)/2;if(rates[m].time<at)l=m+1;else r=m;}return l;
}
#endif
'''
    path=ROOT/'Include/CanHoTroScalpDetector.mqh'
    for old,new in [('g_zones','scanZones'),('g_statCreated','scanStatCreated'),('g_statDemand','scanStatDemand'),
                    ('g_statSupply','scanStatSupply'),('g_statBroken','scanStatBroken'),('g_statFlipped','scanStatFlipped')]:
        header=header.replace(old,new)
    path.write_text(header,encoding='utf-8')
    write_json(RUN/'ORACLE_EXTRACTION.json', {
        'source':str(original),'source_sha256':sha(original),
        'generated':str(path),'generated_sha256':sha(path),
        'unchanged_numerical_sections':['ScanHtfMacroZones inner body','DetectLtfConfirmation touch/sweep/pivot/fallback/first-break loops','IsInKillzone'],
        'adapters':['supplied closed H1/M5 arrays and context instead of terminal CopyRates/CopyBuffer',
                    'trace-only base/flip/availability fields','emit all raw confirmations before gates/plan selection',
                    'ATR and EMA calculations separately verified against native handles'],
        'original_file_modified':False,
    })
    print('Generated',path)


if __name__=='__main__':
    import sys
    sys.stdout.reconfigure(encoding='utf-8')
    main()
