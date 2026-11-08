"""Independent H1-zone/M1 detector, never conditional on a future M5 signal."""
from datetime import datetime, timezone
import json
import numpy as np

import research_scalp_v2 as research
from can_ho_tro_scalp_core import bars_matrix, detect_all, metaquotes_atr
from prepare_can_ho_tro_scalp import sha, write_json


def main():
    run=research.ROOT/'reports/can_ho_tro_scalp/20261101_m1_v2'
    run.mkdir(parents=True,exist_ok=True)
    names=['BASE_T05','BASE_T3','FRESH_T05','FRESH_T3','SLOPE_T05','NO_CHASE_T05','RISK6_T3']
    specs=[s for s in research.SPECS if s['name'] in names]
    lock=dict(version='scalp_m1_v2',user_date='2026-11-01',
              source_data_sha256=sha(research.BASE/'rates.npz'),
              spec_sha256=sha(research.RUN/'EXPERIMENT_LOCK.json'),
              bar_seconds=60,lookback='20 CLOSED M1 bars; original 20-bar pattern transplanted to M1',
              definitions='same causal source-zone rules; no future M5 candidate used for eligibility',
              hypotheses=specs,costs=research.COSTS,family_size=22,
              bootstrap_seed=20261101,bootstrap_resamples=20000,
              limitations='retrospective previously inspected history; M1 detector has no new native MQL parity yet',
              screening='same PF>=1.5, min200, positive complete years and family-adjusted bootstrap criteria as v2')
    dest=run/'EXPERIMENT_LOCK.json'
    if dest.exists():assert json.loads(dest.read_text(encoding='utf-8'))==lock
    else:write_json(dest,lock)
    original=np.load(research.BASE/'rates.npz');arrays={k:bars_matrix(original[k]) for k in original.files}
    numerical=np.load(research.BASE/'detector_python.npz')
    start=int(datetime(2021,10,25,tzinfo=timezone.utc).timestamp())
    stop=int(datetime(2026,10,25,tzinfo=timezone.utc).timestamp())
    cache=run/'detector_m1.npz'
    if cache.exists():raw=np.load(cache)['raw']
    else:
        print('DETECT independent M1; scanning full five years',flush=True)
        atr=metaquotes_atr(arrays['m1'])
        raw,snap=detect_all(arrays['h1'],arrays['m1'],arrays['d1'],numerical['atr1'],atr,numerical['ma1'],start,stop,True,60)
        np.savez_compressed(cache,raw=raw,snapshots=snap)
    print('M1_RAW',len(raw),'source_pass',int(((raw[:,27]==0)&(raw[:,28]==0)).sum()),flush=True)
    features=[research.feature(c,arrays['h1'],numerical['ma1']) for c in raw]
    write_json(run/'candidate_features.json',features)
    rows=[];all_trades={}
    for spec in specs:
        for cost in research.COSTS:
            label=spec['name']+'_'+cost['id']
            trades,rejects=research.run_serial(raw,features,arrays,spec,cost)
            write_json(run/(label+'_trades.json'),trades)
            m=research.summarize(trades,lock)
            rows.append(dict(name=spec['name'],cost=cost['id'],label=label,metrics=m,rejections=rejects))
            all_trades[label]=trades
            print(label,'n',m['n'],'win',round(m['win_rate'] or 0,2),'PF',round(m['pf'] or 0,3),'R',round(m['total_r'],2),flush=True)
    wf=research.evaluate_walkforward({s['name']:all_trades[s['name']+'_BASE'] for s in specs},raw,features,arrays,specs,research.COSTS[1])
    write_json(run/'summary.json',dict(rows=rows,walkforward=wf,lock_sha256=sha(dest)))
    print('M1 DONE',flush=True)


if __name__=='__main__':main()
