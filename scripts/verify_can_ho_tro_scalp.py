"""Event-level MQL/Python numerical parity, including actual native ATR/EMA buffers."""
from __future__ import annotations

import json
import shutil
import numpy as np

from prepare_can_ho_tro_scalp import RUN, write_json, sha
from build_can_ho_tro_scalp import FILES
from can_ho_tro_scalp_core import CANDIDATE_COLUMNS,bars_matrix,source_zones


def load(path, width):
    return np.loadtxt(path,delimiter=',',ndmin=2) if path.stat().st_size else np.empty((0,width))


def main():
    destination=RUN/'mql';destination.mkdir(exist_ok=True)
    for p in FILES.glob('*'):
        if p.name.endswith(('_native.csv','_mql.csv')) or p.name=='mql_result.json':
            shutil.copy2(p,destination/p.name)
    numerical=np.load(RUN/'detector_python.npz')
    data=np.load(RUN/'rates.npz')
    results=[]
    def compare(label,a,b,columns,exact):
        same_shape=a.shape==b.shape
        error=float(np.max(np.abs(a-b))) if same_shape and a.size else None
        exact_ok=same_shape and all(np.array_equal(a[:,j],b[:,j]) for j in exact)
        detail={'label':label,'python_rows':len(a),'mql_rows':len(b),'shape_match':same_shape,
                'exact_fields_match':bool(exact_ok),'max_absolute_error':error,
                'passed':bool(exact_ok and (error is None or error<=1e-8))}
        if same_shape and a.size:
            bad=np.argwhere(np.abs(a-b)>1e-8)
            detail['first_mismatches']=[{'row':int(i),'column':columns[j],
                                         'python':float(a[i,j]),'mql':float(b[i,j])} for i,j in bad[:12]]
        results.append(detail)
    compare('candidate fields',numerical['raw'],load(destination/'candidates_mql.csv',36),CANDIDATE_COLUMNS,
            [0,1,2,3,4,5,6,7,8,9,12,13,15,17,23,27,28,31,32,33,34,35])
    compare('C0 closed-only candidate fields',numerical['c0_raw'],load(destination/'candidates_c0_mql.csv',36),CANDIDATE_COLUMNS,
            [0,1,2,3,4,5,6,7,8,9,12,13,15,17,23,27,28,31,32,33,34,35])
    compare('zone snapshot counts and score/test sums',numerical['snapshots'],load(destination/'snapshots_mql.csv',5),
            ['known','h1_count','zone_count','score_sum','tests_sum'],list(range(5)))
    h1=bars_matrix(data['h1']);d1=bars_matrix(data['d1']);legacy=[];chosen=-1
    for c in numerical['raw']:
        if c[27]!=0 or int(c[1])==chosen:continue
        buy=bool(c[2]);direction=1 if buy else -1;entry=float(c[21]);stop=float(c[19]);risk=direction*(entry-stop)
        if risk>20.:continue
        if risk<2.:risk=2.;stop=entry-direction*risk
        target=entry+direction*.5*risk;macro=entry+direction*4.5*risk;distance=9999999.
        di=int(np.searchsorted(d1[:,0]+86400,c[1],side='right'))
        if di:
            day=d1[di-1,2 if buy else 3]
            if (buy and day>entry) or (not buy and 0<day<entry):distance=abs(day-entry);macro=day
        zones=source_zones(h1,numerical['atr1'],int(c[35]))
        for z in zones:
            if z[8]!=0 or bool(z[2])!=buy:continue
            level=z[5]
            if ((buy and level>entry) or (not buy and level<entry)) and abs(level-entry)<distance:
                distance=abs(level-entry);macro=level
        legacy.append([c[0],c[1],c[2],c[7],entry,stop,risk,target,target,macro]);chosen=int(c[1])
    compare('L0 flat-slot planned-price proposals',np.array(legacy).reshape(-1,10),load(destination/'legacy_planned_mql.csv',10),
            ['confirm','known','buy','zone_id','planned_entry','initial_sl','risk','tp1','tp2','macro'],[0,1,2,3])
    for key,label in [('h1','_CHT_H1_20261025'),('m5','_CHT_M5_20261025')]:
        native=load(destination/(label+'_native.csv'),3)
        indexes=np.searchsorted(data[key]['time'],native[:,0].astype(np.int64))
        # Native handle seed has no ATR before bar14. Tail-M5 probe has its own
        # start, so compare rolling values only after its 14 TR observations.
        native=native[14:];indexes=indexes[14:]
        expected=numerical['atr1' if key=='h1' else 'atr5'][indexes]
        compare('native iATR '+key,expected[:,None],native[:,1:2],['ATR'],[])
        if key=='h1':
            compare('native iMA EMA50 h1',numerical['ma1'][indexes,None],native[:,2:3],['EMA'],[])
    runtime=json.loads((destination/'mql_result.json').read_text())
    result={'mql_runtime':runtime,'checks':results,'passed':runtime['failures']==0 and all(r['passed'] for r in results),
            'oracle_extraction_sha256':sha(RUN/'ORACLE_EXTRACTION.json')}
    write_json(RUN/'DETECTOR_PARITY.json',result)
    print(json.dumps(result,ensure_ascii=True),flush=True)
    if not result['passed']:
        raise SystemExit(1)
    summary=RUN/'summary_all.json'
    if summary.exists():
        market_checks=[]
        state={'READY':0,'PENDING':1,'FILLED':2,'CLOSED':3,'REJECTED':4,'EXPIRED':5,'CANCELLED':6,'CENSORED_OPEN':7}
        reason={'':0,'END_OF_DATA':0,'STOP':2,'TARGET':3,'TIME':4,'STOP_GAP':8,
                'REJECT_AT_FILL_RISK':7,'REJECT_AT_FILL_STOP':18,'REJECT_AT_FILL_ROOM':14,
                'REJECT_AT_FILL_ROOM_UNKNOWN':13,'NO_ENTRY_QUOTE':15,'SPREAD_OR_QUOTE':16,
                'EXPIRED':5,'CANCELLED':6,'LIMIT_NOT_PASSIVE':17,'REJECT_AT_FILL_SPREAD':16}
        columns=['candidate_index','signal_time','buy','entry_time','entry','initial_sl','risk','exit_time',
                 'exit_price','state','reason','r','mfe','mae','stop','ambiguous','hit1','hit15','hit2']
        for row in json.loads(summary.read_text())['rows']:
            suffix='serial' if row['mode']=='serial' else 'paired'
            label=f'{row["name"]}_{row["cost"]}_{row["path"]}_{suffix}'
            trades=json.loads((RUN/(label+'_trades.json')).read_text())
            expected=[];stop_events=[]
            for trade in trades:
                expected.append([trade['candidate_index'],trade['signal_time'],int(trade['buy']),trade['entry_time'],trade['entry'],
                                 trade['initial_sl'],trade['risk'],trade['exit_time'],trade['exit_price'],state[trade['state']],
                                 reason[trade['reason']],trade['r'] or 0.,trade['mfe_r'],trade['mae_r'],trade['stop'],
                                 trade['ambiguous_minutes'],*[trade['first_hits'].get(t,0) for t in ['1.0','1.5','2.0']]])
                prop=None;current_stop=trade['initial_sl']
                kinds={'STOP_PROPOSED':10,'STOP_APPLIED':11,'STOP_REJECTED':12}
                for event in trade['events']:
                    if event['kind'] not in kinds:continue
                    if event['kind']=='STOP_PROPOSED':prop=event
                    old=event.get('old',current_stop);new=event.get('new',event.get('proposed'))
                    stop_events.append([trade['candidate_index'],kinds[event['kind']],event['time'],event['sequence'],old,new,
                                        prop['time'],prop['p_time'],prop['h_time']])
                    if event['kind']=='STOP_APPLIED':current_stop=new
            before=len(results)
            compare(label+' trades',np.array(expected).reshape(-1,19),load(destination/(label+'_trades_mql.csv'),19),columns,
                    [0,1,2,3,7,9,10,15,16,17,18])
            compare(label+' stop events',np.array(stop_events).reshape(-1,9),load(destination/(label+'_stops_mql.csv'),9),
                    ['candidate','kind','time','sequence','old','new','known','p_time','h_time'],[0,1,2,3,6,7,8])
            market_checks.extend(results[before:])
        full={'mql_runtime':runtime,'checks':market_checks,'passed':runtime['failures']==0 and all(c['passed'] for c in market_checks),
              'coverage':'7 configs x 3 costs x paired/serial; retest both OHLC/OLHC paths; each trade and market stop event'}
        write_json(RUN/'MARKET_PLAN_PARITY.json',full)
        print('MARKET_PLAN_PARITY',json.dumps({'passed':full['passed'],'checks':len(market_checks),'failed':[c for c in market_checks if not c['passed']]},ensure_ascii=True))
        if not full['passed']:raise SystemExit(1)


if __name__=='__main__':
    main()
