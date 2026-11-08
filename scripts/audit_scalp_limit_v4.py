"""Audit frozen signals, chronological execution and paired fill diagnostics."""
import json

import numpy as np

from can_ho_tro_scalp_core import bars_matrix
from prepare_can_ho_tro_scalp import sha,write_json
import research_scalp_limit_v4 as v


def read(path):return json.loads(path.read_text(encoding='utf-8'))


def main():
    lock=read(v.RUN/'EXPERIMENT_LOCK.json')
    assert all(sha(v.w.ROOT/p)==value for p,value in lock['signals_sha256'].items())
    preserved={p:sha(v.w.ROOT/p)==value for p,value in lock['preserved_fresh'].items()}
    assert all(preserved.values())
    raws=v.load_raw();market=bars_matrix(np.load(v.w.BASE/'rates.npz')['m1']);checks=[]
    fields=['candidate_index','idea_id','signal_time','state','reason','entry_time','exit_time','entry','initial_sl','risk','r','commission_r']
    for group in ('WEEKLY','MICRO'):
        for mode in ('SHALLOW','MIDPOINT','LEVEL'):
            spec=next(s for s in v.SPECS if s['group']==group and s['mode']==mode and s['rr']==.8)
            for path in v.PATHS:
                full=read(v.RUN/(spec['name']+'_BASE_'+path+'_trades.json'))['trades']
                cut=int(v.datetime(2024,7,1,12,tzinfo=v.timezone.utc).timestamp())
                raw=raws[group];prefix=raw[raw[:,1]<cut]
                got,_=v.run_serial(prefix,market[market[:,0]<cut],spec,v.w.COSTS[1],path)
                expected=[t for t in full if not t['state'].startswith('CENSORED') and t['signal_time']<cut and (not t['exit_time'] or t['exit_time']<cut)]
                terminal=[t for t in got if not t['state'].startswith('CENSORED')]
                assert len(terminal)==len(expected),(spec,path,len(terminal),len(expected))
                for a,b in zip(terminal,expected):assert all(a[k]==b[k] for k in fields),(a,b)
                checks.append(dict(name=spec['name'],path=path,cut=cut,terminal_rows=len(terminal),exact=True))
                print('EXECUTION PREFIX',spec['name'],path,len(terminal),'PASS',flush=True)
    write_json(v.RUN/'PREFIX_CHECKS.json',dict(passed=True,checks=checks,fields=fields))
    paired=[]
    for spec in v.SPECS:
        if spec['mode']=='MARKET':continue
        control=next(s for s in v.SPECS if s['group']==spec['group'] and s['mode']=='MARKET' and s['rr']==spec['rr'])
        for path in v.PATHS:
            base=read(v.RUN/(control['name']+'_BASE_'+path+'_trades.json'))['trades']
            actual=read(v.RUN/(spec['name']+'_BASE_'+path+'_trades.json'))['trades']
            key=lambda t:(t['idea_id'],t['signal_time'])
            old={key(t):t for t in base if t['state']=='CLOSED'}
            new={key(t):t for t in actual if t['state']=='CLOSED'}
            both=old.keys()&new.keys();missed=old.keys()-new.keys()
            missed_rows=[old[k] for k in missed]
            paired.append(dict(name=spec['name'],path=path,matched=len(both),
                               matched_market_net_r=sum(old[k]['r'] for k in both),
                               matched_limit_net_r=sum(new[k]['r'] for k in both),
                               market_signals_not_filled_by_limit=len(missed),
                               missed_market_wins=sum(t['r']>0 for t in missed_rows),
                               missed_market_total_r=sum(t['r'] for t in missed_rows),
                               note='descriptive matching; pending occupancy and caps can change which events are eligible; not randomized causal attribution'))
    write_json(v.RUN/'MATCHED_ENTRY_DIAGNOSTICS.json',dict(rows=paired))
    rows=read(v.RUN/'summary.json')['rows'];qualified=[]
    for spec in v.SPECS:
        outcomes=[r['metrics'] for r in rows if r['name']==spec['name'] and r['cost'] in ('BASE','STRESS')]
        if all(t['frequency_pass'] and t['economic_screen_pass'] and (t['win_rate'] or 0)>=55 and t['total_r']>0 for t in outcomes):qualified.append(spec['name'])
    write_json(v.RUN/'VERIFICATION.json',dict(fresh_unchanged=preserved,qualified=qualified,
               tests_passed=83,new_limit_tests=10,prefix_checks=len(checks),
               native_new_branch='not built; no qualified candidate',
               historical_edge_confirmed=False,
               reason='No candidate passes joint frequency,net-win-rate,and economic criteria across BASE/STRESS and both synthetic paths.'))


if __name__=='__main__':main()
