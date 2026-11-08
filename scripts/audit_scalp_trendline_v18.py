"""Independent pivot/ray reconstruction, raw-prefix and execution accounting checks."""
import json
import math
from collections import Counter

import numpy as np

from can_ho_tro_scalp_core import bars_matrix,metaquotes_atr
from can_ho_tro_scalp_plan import round_tick
from prepare_can_ho_tro_scalp import sha,write_json
import research_scalp_trendline_v18 as s


def reference_structure(bars,seconds):
    p = np.arange(2,len(bars)-2)
    lo = p[(bars[p,3]<bars[p-1,3])&(bars[p,3]<bars[p-2,3])&
           (bars[p,3]<=bars[p+1,3])&(bars[p,3]<=bars[p+2,3])]
    hi = p[(bars[p,2]>bars[p-1,2])&(bars[p,2]>bars[p-2,2])&
           (bars[p,2]>=bars[p+1,2])&(bars[p,2]>=bars[p+2,2])]
    known = bars[:,0]+seconds;out = np.zeros((len(bars),14));out[:,0] = known
    for pivots,column,price in ((lo,2,3),(hi,8,2)):
        available = bars[pivots+2,0]+seconds
        n = np.searchsorted(available,known,side='right')
        for offset,dest in ((2,column),(1,column+3)):
            have = n>=offset;ix = n[have]-offset
            out[have,dest:dest+3] = np.c_[bars[pivots[ix],0],bars[pivots[ix],price],available[ix]]
    ready = (out[:,2]>0)&(out[:,8]>0)
    up = ready&(out[:,6]>out[:,3])&(out[:,12]>out[:,9])&(bars[:,4]>out[:,6])
    down = ready&(out[:,6]<out[:,3])&(out[:,12]<out[:,9])&(bars[:,4]<out[:,12])
    out[up,1] = 1;out[down,1] = -1
    return out,dict(low_pivots=len(lo),high_pivots=len(hi))


def asof(at,states,age):
    j = np.searchsorted(states[:,0],at,side='right')-1
    if j<0:
        return 0.,0.
    return (states[j,1] if at-states[j,0]<=age else 0.),states[j,0]


def reference_events(gold,h1,s1,s4,sd):
    """Enumerate each ray once, then find its first touch/confirmation in vector paths."""
    a5 = metaquotes_atr(gold);a1 = metaquotes_atr(h1);at = gold[:,0];known = at+300
    j = np.searchsorted(s1[:,0],at,side='right')-1;safe = np.maximum(j,0)
    direction = s1[safe,1];anchor = np.where(direction>0,s1[safe,5],s1[safe,11])
    contiguous = np.r_[False,np.diff(at)==300]
    eligible = ((np.arange(len(gold))>=15)&(known<s.w.END)&contiguous&(j>=0)&
                (at-s1[safe,0]<=7200)&(np.r_[0.,a5[:-1]]>0)&(direction!=0))
    seen = set();rows = [];rays = 0;valid_rays = 0;touches = 0
    for first in np.flatnonzero(eligible):
        d = direction[first];key = (int(d),int(anchor[first]))
        if key in seen or key[1]<=0:
            continue
        seen.add(key);rays += 1;column = 2 if d>0 else 8;state = s1[j[first]]
        t1,y1,t2,y2 = state[column],state[column+1],state[column+3],state[column+4]
        ray_atr = a1[j[first]];born = state[0]
        if not 0<t2-t1<=48*3600 or ray_atr<=0:
            continue
        slope = (y2-y1)/(t2-t1);q = np.arange(np.searchsorted(h1[:,0],t1),j[first]+1)
        extreme = h1[q,3 if d>0 else 2];levels = y1+slope*(h1[q,0]-t1)
        if np.any(d*(extreme-levels)<-.1*ray_atr):
            continue
        valid_rays += 1
        ix = np.arange(first,np.searchsorted(known,born+12*3600,side='right'))
        line_open = y1+slope*(at[ix]-t1);line_close = y1+slope*(known[ix]-t1)
        invalid = ~eligible[ix]|(direction[ix]!=d)|(anchor[ix]!=t2)|\
                  (d*(gold[ix,4]-line_close)<-.25*a5[ix-1])
        failures = np.flatnonzero(invalid)
        if len(failures):
            stop = failures[0];ix = ix[:stop];line_open = line_open[:stop];line_close = line_close[:stop]
        if not len(ix):
            continue
        initially_away = d*(gold[first-1,4]-line_open[0])>=a5[first-1]
        away = d*(gold[ix,4]-line_close)>=a5[ix]
        observed_away = np.r_[initially_away,initially_away|np.maximum.accumulate(away[:-1])]
        contacts = ((gold[ix,3]<=line_open+.25*a5[ix-1]) if d>0 else
                    (gold[ix,2]>=line_open-.25*a5[ix-1]))&observed_away
        hits = np.flatnonzero(contacts)
        if not len(hits):
            continue
        touches += 1;t = hits[0];touch = ix[t];fa = a5[touch-1]
        window = ix[t:t+3];rng = gold[window,2]-gold[window,3]
        outer = np.divide(gold[window,4]-gold[window,3] if d>0 else gold[window,2]-gold[window,4],
                          rng,out=np.zeros(len(window)),where=rng>0)
        quality = (d*(gold[window,4]-gold[window,1])>=.1*fa)&(rng>=.5*fa)&(outer>=.65)&\
                  (d*(gold[window,4]-line_close[t:t+3])>=.1*fa)
        confirms = np.flatnonzero(quality)
        if not len(confirms):
            continue
        c = t+confirms[0];i = ix[c]
        if not s.w.START<=known[i] or not 2*3600<=known[i]%86400<18*3600:
            continue
        touch4,_ = asof(at[touch],s4,28800);touchd,_ = asof(at[touch],sd,345600)
        now4,k4 = asof(at[i],s4,28800);nowd,kd = asof(at[i],sd,345600)
        rows.append([known[i],float(d>0),born,t1,y1,t2,y2,ray_atr,at[touch],fa,line_open[t],
                     line_close[c],touch4,now4,touchd,nowd,s1[j[i],0],k4,kd,i])
    result = np.asarray(rows,float).reshape((-1,20))
    if len(result):
        result = result[np.argsort(result[:,0],kind='stable')]
    return result,dict(first_seen_ray_identities=rays,geometry_valid_rays=valid_rays,first_touches=touches)


def main():
    read = lambda p:json.loads(p.read_text(encoding='utf-8'))
    w = s.w;v = s.v;lock = read(s.RUN/'EXPERIMENT_LOCK.json')
    source = np.load(w.BASE/'rates.npz');gold = bars_matrix(source['m5']);market = bars_matrix(source['m1'])
    h1 = bars_matrix(source['h1']);d1 = bars_matrix(source['d1']);h4 = bars_matrix(np.load(s.RUN/'h4_rates.npz')['rates'])
    stored = np.load(s.RUN/'structure_inputs.npz');states = {};pivot_audit = {}
    for name,bars,seconds in (('h1',h1,3600),('h4',h4,14400),('d1',d1,86400)):
        states[name],counts = reference_structure(bars,seconds)
        np.testing.assert_array_equal(states[name],stored[name]);pivot_audit[name] = dict(rows=len(bars),**counts)
    h4_checks = 0
    for bar in h4[(h4[:,0]>=w.START)&(h4[:,0]<w.END)]:
        left,right = np.searchsorted(gold[:,0],[bar[0],bar[0]+14400]);part = gold[left:right]
        assert len(part) and np.array_equal(bar[1:5],[part[0,1],part[:,2].max(),part[:,3].min(),part[-1,4]])
        h4_checks += 1
    np.testing.assert_array_equal(np.unique(gold[(gold[:,0]>=w.START)&(gold[:,0]<w.END),0]//14400)*14400,
                                  h4[(h4[:,0]>=w.START)&(h4[:,0]<w.END),0])
    expected,ray_counts = reference_events(gold,h1,states['h1'],states['h4'],states['d1'])
    detected = np.load(s.RUN/'events.npy');raw = np.load(s.RUN/'raw_candidates.npy')
    np.testing.assert_allclose(expected,detected,rtol=0,atol=1e-10)
    np.testing.assert_array_equal(s.candidates(gold,detected),raw)
    assert np.all(raw[:,12]<=raw[:,0]) and np.all(raw[:,39]<=raw[:,0])
    assert np.all(raw[:,1]==raw[:,37]+60)
    for event in detected:
        birth = event[2];touch = event[8];d = 1 if event[1] else -1;column = 2 if d>0 else 8
        j = np.searchsorted(states['h1'][:,0],birth,side='right')-1
        assert states['h1'][j,column+2]<=birth<=touch and states['h1'][j,column+5]<=birth
        assert event[16]<=event[0]-300 and event[17]<=event[0]-300 and event[18]<=event[0]-300
        actual = raw[(raw[:,37]==event[0])&(raw[:,3]==event[5]),36].astype(int).tolist()
        families = [49]
        if event[12]==d and event[13]==d:
            families.append(47)
            if event[14]==d and event[15]==d:
                families.append(48)
        assert actual==sorted(families)
    prefixes = [];executions = [];w.FAMILIES.update(s.NAMES)
    for year in (2022,2025):
        cut = int(w.datetime(year,1,1,tzinfo=w.timezone.utc).timestamp())
        gm = gold[gold[:,0]+300<=cut];frames = [h1[h1[:,0]+3600<=cut],h4[h4[:,0]+14400<=cut],d1[d1[:,0]+86400<=cut]]
        snapshots = [s.structure(b,sec) for b,sec in zip(frames,(3600,14400,86400))]
        for frame,name,snap in zip(frames,('h1','h4','d1'),snapshots):
            np.testing.assert_array_equal(snap,states[name][:len(frame)])
        prefix = s.events(gm,frames[0],*snapshots,end=cut)
        np.testing.assert_array_equal(prefix,detected[detected[:,0]<cut])
        candidates = s.candidates(gm,prefix);np.testing.assert_array_equal(candidates,raw[raw[:,37]<cut])
        prefixes.append(dict(cut=cut,raw_M5_H1_H4_D1_structures_rays_events_candidates_exact=True,events=len(prefix)))
        pm = market[market[:,0]+60<=cut]
        for spec in s.SPECS:
            full = read(s.RUN/(spec['name']+'_BASE_trades.json'))['trades']
            rows,_ = v.execution.run_serial(candidates,pm,spec,w.COSTS[1])
            fields = ('state','reason','entry_time','exit_time','entry','initial_sl','risk','r','commission_r','target')
            closed = lambda rr:[{k:r[k] for k in fields} for r in rr if r['state']=='CLOSED' and r['exit_time']<cut]
            assert closed(rows)==closed(full),(year,spec['name'])
            executions.append(dict(name=spec['name'],cut=cut,closed=len(closed(rows)),exact=True))
    labels = np.load(v.RUN/'barrier_labels.npz');fees = 0;matched = 0;money = 0;qualified = [];summary = read(s.RUN/'summary.json')
    for spec in s.SPECS:
        base = next(r['metrics'] for r in summary['rows'] if r['name']==spec['name'] and r['cost']=='BASE')
        stress = next(r['metrics'] for r in summary['rows'] if r['name']==spec['name'] and r['cost']=='STRESS')
        if base['frequency_pass'] and base['economic_screen_pass'] and (base['win_rate'] or 0)>=55 and stress['economic_screen_pass']:
            qualified.append(spec['name'])
        for cost in w.COSTS:
            rows = read(s.RUN/(spec['name']+'_'+cost['id']+'_trades.json'))['trades'];filled = [r for r in rows if r['entry_time']]
            assert max(Counter(r['entry_time']//86400 for r in filled).values(),default=0)<=2
            assert max(Counter(w.week_key(r['entry_time']) for r in filled).values(),default=0)<=10
            assert all(b['entry_time']>=a['exit_time'] for a,b in zip(filled,filled[1:]))
            for r in rows:
                fees += 1;d = 1 if r['buy'] else -1
                if r['entry_time']:
                    assert 2.-1e-9<=r['risk']<=20.+1e-9
                    assert math.isclose(r['risk'],d*(r['entry']-r['initial_sl']),abs_tol=1e-10)
                    assert math.isclose(r['commission_r'],cost['commission_price']/r['risk'],abs_tol=1e-10)
                    assert r['target']==round_tick(r['entry']+d*.8*r['risk'],.01,d)
                    assert r['deadline']==min(r['entry_time']+7200,r['entry_time']//86400*86400+21*3600)
                if r['r'] is not None:
                    assert math.isclose(r['gross_r'],d*(r['exit_price']-r['entry'])/r['risk'],abs_tol=1e-10)
                    assert math.isclose(r['r'],r['gross_r']-r['commission_r'],abs_tol=1e-10);money += 1
                assert 'ASSUMED_ROUND_TRIP_COMMISSION' in r['fees_status']
                if cost['id']=='BASE' and r['state']=='CLOSED':
                    i = np.searchsorted(labels['known'],r['source_known_at']);side = 0 if r['buy'] else 1
                    if i<len(labels['known']) and labels['known'][i]==r['source_known_at']:
                        assert labels['payoff'][i,side]==r['r'] and labels['risk'][i,side]==r['risk'];matched += 1
    fresh = {p:sha(w.ROOT/p)==h for p,h in lock['preserved_fresh'].items()};assert all(fresh.values())
    implementation = {p:sha(w.ROOT/p)==h for p,h in lock['implementation_sha256'].items()};assert all(implementation.values())
    assert sha(w.BASE/'rates.npz')==lock['gold_sha256'] and sha(v.RUN/'barrier_labels.npz')==lock['labels_sha256']
    assert sha(s.RUN/'h4_rates.npz')==lock['h4_sha256'] and sha(s.RUN/'H4_DATA_MANIFEST.json')==lock['h4_manifest_sha256']
    write_json(s.RUN/'VERIFICATION.json',dict(passed=True,independent_structure=pivot_audit,independent_ray_reconstruction=ray_counts,
        native_H4_M5_exact_OHLC_checks=h4_checks,independent_first_touch_confirmation_events=len(detected),
        raw_feature_detector_prefixes=prefixes,execution_prefixes=executions,fee_rows_audited=fees,
        exact_exit_risk_target_deadline_money_rows=money,common_half_hour_BASE_R_risk_label_matches=matched,
        fresh_unchanged=fresh,implementation_unchanged=implementation,qualified=qualified,
        historical_edge_confirmed=False,FTMO_rules_deferred_per_user=True))
    write_json(s.RUN/'CUMULATIVE_REGISTRY.json',dict(previous=dict(hypotheses=126,scenarios=464),
        new=dict(hypotheses=3,cost_scenarios=9),cumulative=dict(hypotheses=129,scenarios=473),
        tests=dict(previous_unique=164,new=6,total_unique=170),prefixes=dict(raw_feature_detector=2,execution=6),
        qualified=qualified,goal_status='active;researchongoing'))
    write_json(s.RUN/'SOURCE_MANIFEST.json',dict(fresh_unchanged=True,
        files={p:sha(w.ROOT/p) for p in lock['implementation_sha256']},audit_sha256=sha(w.ROOT/'scripts/audit_scalp_trendline_v18.py')))
    print('PASS',sum(x['rows'] for x in pivot_audit.values()),'independent structure rows;',len(detected),
          'independent ray events;',h4_checks,'H4 OHLC;',len(prefixes),'raw+',len(executions),
          'execution prefixes;',fees,'fee rows,',money,'money rows,',matched,'common BASE labels;qualified',qualified,flush=True)


if __name__=='__main__':
    main()
