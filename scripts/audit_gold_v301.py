"""Forensic reproduction of v3.01, using saved data and no terminal connection."""
from collections import Counter
from contextlib import redirect_stdout
from datetime import datetime,timezone
from pathlib import Path
import ast
import csv
import hashlib
import io
import json
import math
import sys
import textwrap
import types

import numpy as np

ROOT=Path(__file__).resolve().parents[1]
RUN=ROOT/'reports/gold_v301_audit/20261101'
ENGINE=ROOT/'scripts/run_5year_backtest_v301.py'
BUILDER=ROOT/'scripts/test_m5_scanning_speed.py'
DATA=ROOT/'reports/scalp_structure_lab/20261025_pilot_v1/rates.npz'
UTC=timezone.utc


def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()


def default(value):
    if isinstance(value,np.generic):return value.item()
    if isinstance(value,datetime):return value.isoformat()
    raise TypeError(type(value).__name__)


def save(name,value):
    (RUN/name).write_text(json.dumps(value,default=default,ensure_ascii=False,indent=2,allow_nan=False)+'\n',encoding='utf-8')


def write_csv(name,rows):
    with (RUN/name).open('w',newline='',encoding='utf-8-sig') as f:
        if not rows:return
        w=csv.DictWriter(f,fieldnames=list(dict.fromkeys(k for p in rows for k in p)))
        w.writeheader();w.writerows(rows)


def metric(rows):
    if not rows:return dict(n=0,net_R=0.,mean_R=None,profit_factor=None,max_closed_R_drawdown=0.)
    rs=[float(p['r']) for p in rows]
    profit=sum(max(0,x) for x in rs);loss=-sum(min(0,x) for x in rs)
    curve=np.r_[0.,np.cumsum(rs)]
    return dict(n=len(rows),net_R=float(sum(rs)),mean_R=float(np.mean(rs)),
                profit_factor=profit/loss if loss else None,
                max_closed_R_drawdown=float(np.max(np.maximum.accumulate(curve)-curve)),
                positive_R_pct=100*sum(x>0 for x in rs)/len(rs),
                reasons=dict(Counter(p.get('reason','LEGACY') for p in rows)))


def load_offline_engine(h1,m5):
    source=ENGINE.read_text(encoding='utf-8-sig');tree=ast.parse(source)
    main=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='main')
    # Observe the selected zone without changing any branch or execution value.
    for node in ast.walk(main):
        if isinstance(node,ast.Dict) and any(isinstance(k,ast.Constant) and k.value=='entryMkt' for k in node.keys):
            node.keys.extend([ast.Constant('audit_zone'),ast.Constant('known_at')])
            node.values.extend([ast.Call(func=ast.Name(id='dict',ctx=ast.Load()),args=[ast.Name(id='z',ctx=ast.Load())],keywords=[]),
                                ast.Subscript(value=ast.Name(id='times_m5',ctx=ast.Load()),slice=ast.Name(id='m',ctx=ast.Load()),ctx=ast.Load())])
    main.body.append(ast.Return(value=ast.Call(func=ast.Name(id='locals',ctx=ast.Load()),args=[],keywords=[])))
    module=types.ModuleType('audited_v301_offline');module.__file__=str(ENGINE)
    exec(compile(ast.fix_missing_locations(tree),str(ENGINE),'exec'),module.__dict__)
    class Offline:
        TIMEFRAME_H1=1;TIMEFRAME_M5=5
        @staticmethod
        def initialize():return True
        @staticmethod
        def shutdown():pass
        @staticmethod
        def copy_rates_range(symbol,tf,start,end):
            assert symbol=='XAUUSD'
            a=h1 if tf==1 else m5
            return a[(a['time']>=int(start.timestamp()))&(a['time']<=int(end.timestamp()))]
    module.mt5=Offline
    return module


def reproduce(h1,m5):
    identity=dict(engine_sha256=sha(ENGINE),builder_sha256=sha(BUILDER),data_sha256=sha(DATA))
    cache=RUN/'REPRODUCTION.json';signal_path=RUN/'legacy_signals.json'
    if cache.exists() and signal_path.exists():
        existing=json.loads(cache.read_text(encoding='utf-8'))
        if existing['identity']==identity:return existing,json.loads(signal_path.read_text(encoding='utf-8'))
    module=load_offline_engine(h1,m5);out=io.StringIO()
    with redirect_stdout(out):state=module.main()
    (RUN/'legacy_engine_stdout.log').write_text(out.getvalue(),encoding='utf-8')
    assert isinstance(state,dict)
    signals=state['signals'];calc=state['calc_metrics']
    statistics={}
    for key in ['r_old','r_mkt_hybrid','r_mkt_rr','r_lmt_hybrid']:
        statistics[key]=dict(all=calc(signals,key),killzones=calc([p for p in signals if p['kz']],key))
    actual=statistics['r_mkt_rr']
    matches=(len(signals)==2601 and actual['all']['total_trades']==1818 and
             math.isclose(actual['all']['total_r'],122.) and actual['killzones']['total_trades']==881 and
             math.isclose(actual['killzones']['total_r'],67.75))
    result=dict(identity=identity,data_rows=dict(h1=len(state['rates_h1']),m5=len(state['rates_m5'])),
        zones=len(state['zones']),raw_signals=len(signals),metrics=statistics,
        headline_counts_and_PnL_match_report=matches,
        original_raw_snapshot_preserved=False,
        current_snapshot_is_later=True,
        claimed_original_rows=dict(m5=352252,h1=31480),
        years={str(y):calc([p for p in signals if p['year']==y and p['kz']],'r_mkt_rr') for y in range(2021,2027)},
        no_terminal_connection=True,ex5_executed=False)
    save('REPRODUCTION.json',result);save('legacy_signals.json',signals)
    return result,json.loads(signal_path.read_text(encoding='utf-8'))


def prefix_audit(h1):
    sys.path.insert(0,str(ROOT))
    from scripts.test_m5_scanning_speed import build_h1_zones,compute_wilder_atr
    t=h1['time'];o=h1['open'];h=h1['high'];l=h1['low'];c=h1['close']
    a=compute_wilder_atr(h,l,c,14)
    full=build_h1_zones(t,o,h,l,c,a)
    def key(z):return (int(z['timeActive']),bool(z['isSupply']),float(z['distal']),float(z['proximal']),bool(z['isFlip']))
    keys={key(z) for z in full};checks=[]
    for year in [2023,2024,2025]:
        cutoff=int(datetime(year,1,1,tzinfo=UTC).timestamp());n=int(np.searchsorted(t,cutoff))
        prefix=build_h1_zones(t[:n],o[:n],h[:n],l[:n],c[:n],a[:n])
        gone=[z for z in prefix if z['timeActive']+3600<=t[n-1] and key(z) not in keys]
        checks.append(dict(cutoff=year,prefix_bars=n,previously_known_zones_missing_after_future_extension=len(gone),
                           missing_flip_zones=sum(z['isFlip'] for z in gone),examples=gone[:3]))
    # A direct fixture isolates the future-dependent flip predicate even when
    # the three historical cut dates contain no surviving flip witness.
    ft=np.arange(34,dtype=np.int64)*3600
    fo=np.full(34,100.);fc=fo.copy();fh=fo+.5;fl=fo-.5;fa=np.ones(34)
    fo[20]=fc[20]=100.;fh[20]=100.2;fl[20]=99.8
    for i,values in {21:(100.,100.1,98.4,98.5),22:(98.5,98.6,97.9,98.),
                     23:(98.,98.1,97.7,97.8),24:(97.8,98.1,97.7,98.),
                     25:(98.,101.2,97.9,101.)}.items():fo[i],fh[i],fl[i],fc[i]=values
    fo[26:]=fc[26:]=101.;fh[26:]=101.5;fl[26:]=100.5
    fo[31]=101.;fh[31]=101.5;fl[31]=98.5;fc[31]=99.
    prefix=build_h1_zones(ft[:30],fo[:30],fh[:30],fl[:30],fc[:30],fa[:30])
    extended=build_h1_zones(ft,fo,fh,fl,fc,fa)
    before=[z for z in prefix if z['isFlip'] and z['timeActive']==ft[25]]
    after=[z for z in extended if z['isFlip'] and z['timeActive']==ft[25]]
    assert len(before)==1 and not after
    fixture=dict(prefix_bars=30,extended_bars=34,flip_start=int(ft[25]),
                 flip_visible_on_prefix=True,flip_visible_after_future_break=False,
                 future_break_bar=31,zone=before[0])
    rejected=[]
    function=next(n for n in ast.parse(BUILDER.read_text(encoding='utf-8-sig')).body
                  if isinstance(n,ast.FunctionDef) and n.name=='build_h1_zones')
    for node in ast.walk(function):
        if isinstance(node,ast.If) and isinstance(node.test,ast.UnaryOp) and isinstance(node.test.op,ast.Not) and isinstance(node.test.operand,ast.Name) and node.test.operand.id=='fBroken':
            node.orelse=ast.parse("audit_rejected.append(dict(start_idx=brokenBar,failure_idx=k,isSupply=flipSupply,distal=fDistal,proximal=fProximal))").body
    context=dict(audit_rejected=rejected)
    exec(compile(ast.fix_missing_locations(ast.Module(body=[function],type_ignores=[])),str(BUILDER),'exec'),context)
    observed=context['build_h1_zones'](t,o,h,l,c,a)
    assert {key(z) for z in observed}==keys
    historical_witness=[]
    for item in rejected[:20]:
        n=item['start_idx']+1
        prefix=build_h1_zones(t[:n],o[:n],h[:n],l[:n],c[:n],a[:n])
        target=(int(t[item['start_idx']]),bool(item['isSupply']),float(item['distal']),float(item['proximal']),True)
        match=[z for z in prefix if key(z)==target]
        if match and target not in keys:
            historical_witness.append(dict(prefix_bars=n,known_after=int(t[n-1])+3600,
                future_failure_known_after=int(t[item['failure_idx']])+3600,
                zone=match[0],present_on_prefix=True,present_on_full_history=False))
        if len(historical_witness)>=3:break
    result=dict(status='FAIL_SYNTHETIC_PREFIX_INVARIANCE',
                checks=checks,interpretation='A full-history zone set can differ from the zone set available in real time; no PnL impact is inferred solely from this count.')
    result['synthetic_witness']=fixture
    result['full_history_future_rejected_flip_count']=len(rejected)
    result['targeted_historical_witnesses']=historical_witness
    save('PREFIX_AUDIT.json',result)
    return result


def replay(signal,bars,terminal,path,step):
    """Two explicit OHLC paths; each fill follows chronological price crossings."""
    d=1 if signal['isBuy'] else -1
    entry=float(bars['open'][0]);risk=d*(entry-float(signal['sl_new']))
    if risk<=0:return dict(status='INVALID_ENTRY_STOP',idx=signal['idx'])
    sl=-risk;be=False;tp1=False;qty=1.;realized=0.
    def finish(x,reason,t):
        return dict(status='CLOSED',r=(realized+qty*x)/risk,reason=reason,entry=entry,risk=risk,
                    entry_time=int(bars['time'][0]),exit_time=int(t),idx=signal['idx'],kz=signal['kz'],year=signal['year'],
                    tp1_hit=tp1,legacy_r=signal['r_mkt_rr'],risk_outside_legacy_gate=not 2.5<=risk<=10.)
    def favorable(left,right):
        nonlocal sl,be,tp1,qty,realized
        events=[]
        if not be:events.append((6.,'BE'))
        if not tp1:events.append((1.5*risk,'TP1'))
        events.append((2.*risk,'TP2'))
        for x,kind in sorted(events):
            if left-1e-10<=x<=right+1e-10:
                if kind=='BE':be=True;sl=.1
                elif kind=='TP1':
                    realized+=.5*x;qty=.5;tp1=True;be=True;sl=.1
                else:
                    return x
        return None
    for b in bars:
        opening=d*(float(b['open'])-entry);t=int(b['time'])
        if opening<=sl:return finish(opening,'GAP_BE' if be else 'GAP_SL',t)
        hit=favorable(-math.inf,opening)
        if hit is not None:return finish(hit,'TP2',t)
        hi,lo=float(b['high']),float(b['low'])
        adverse=lo if d==1 else hi;beneficial=hi if d==1 else lo
        sequence=[adverse,beneficial] if path=='ADVERSE_FIRST' else [beneficial,adverse]
        prior=opening
        for price in sequence+[float(b['close'])]:
            x=d*(price-entry)
            if x<prior and x<=sl<=prior:return finish(sl,'BE' if be else 'SL',t+step)
            if x>prior:
                hit=favorable(prior,x)
                if hit is not None:return finish(hit,'TP2',t+step)
            prior=x
    if terminal is None:return dict(status='CENSORED',idx=signal['idx'])
    x=d*(float(terminal['open'])-entry);t=int(terminal['time'])
    if x<=sl:return finish(x,'GAP_BE' if be else 'GAP_SL',t)
    hit=favorable(-math.inf,x)
    if hit is not None:return finish(hit,'TP2',t)
    return finish(x,'TIME',t)


def fixtures():
    source=ENGINE.read_text(encoding='utf-8-sig')
    block=source[source.index('        # Market Pure RR ('):source.index('        # Limit 50% Retracement Model')]
    code=compile(textwrap.dedent(block),str(ENGINE),'exec')
    dtype=[('time','i8'),('open','f8'),('high','f8'),('low','f8'),('close','f8')]
    results=[]
    for label,hi,lo,close,old_r,adverse_r,favorable_r in [
        ('same_bar_original_SL_and_TP2',111.,94.,100.,1.75,-1.,1.75),
        ('same_bar_original_SL_and_BE_trigger',106.1,94.,100.,0.,-1.,.02),
        ('expiry_without_any_SL_BE_or_TP',101.,99.,100.5,-1.,.1,.1)]:
        s=dict(entryMkt=100.,sl_new=95.,risk_new=5.,tp1_rr=107.5,tp2_rr=110.,isBuy=True,idx=0,kz=True,year=2024)
        env=dict(s=s,isBuy=True,cIdx=0,end_bar=2,highs_m5=np.array([100.,hi]),lows_m5=np.array([100.,lo]),be_price=100.1)
        exec(code,env)
        assert env['s']['r_mkt_rr']==old_r
        bars=np.array([(300,100.,hi,lo,close)],dtype=dtype)
        terminal=np.array([(600,close,close,close,close)],dtype=dtype)[0]
        a=replay(s,bars,terminal,'ADVERSE_FIRST',300);f=replay(s,bars,terminal,'FAVORABLE_FIRST',300)
        assert math.isclose(a['r'],adverse_r,abs_tol=1e-10),(label,a)
        assert math.isclose(f['r'],favorable_r,abs_tol=1e-10),(label,f)
        results.append(dict(case=label,legacy_R=old_r,adverse_first_R=a['r'],favorable_first_R=f['r']))
    save('EXECUTION_COUNTEREXAMPLES.json',results)
    return results


def cohort_checks(signals,m5):
    valid=[p for p in signals if p['pass_struct']]
    result={}
    for name,rows in [('ALL',valid),('KILLZONES',[p for p in valid if p['kz']])]:
        prices=sum(1/p['risk_new'] for p in rows)
        net=sum(p['r_mkt_rr'] for p in rows)
        result[name]=dict(n=len(rows),gross_R=net,mean_R=net/len(rows),
            flat_cost_per_unit_position_erasing_legacy_profit=net/prices,
            cost_sensitivity={str(c):net-c*prices for c in [0.,.2,.5,1.]},
            legacy_drawdown_with_initial_zero=metric([dict(r=p['r_mkt_rr']) for p in rows])['max_closed_R_drawdown'],
            premature_h1_activation_signals=sum(p['known_at']<p['audit_zone']['timeActive']+3600 for p in rows),
            non_next_open_price_entries=sum(not math.isclose(p['entryMkt'],m5['open'][p['idx']+1],abs_tol=1e-9) for p in rows))
        unfilled=[p for p in rows if not p['filled_lmt']]
        result[name]['limit_unfilled_count']=len(unfilled)
        result[name]['limit_zero_R_count']=sum(p['r_lmt_hybrid']==0 for p in rows)
        result[name]['limit_filled_count']=len(rows)-len(unfilled)
        result[name]['limit_zero_R_unfilled_count']=sum(p['r_lmt_hybrid']==0 for p in unfilled)
        result[name]['mean_stop_distance']=float(np.mean([p['risk_new'] for p in rows]))
        result[name]['median_stop_distance']=float(np.median([p['risk_new'] for p in rows]))
        result[name]['zone_groups']={kind:dict(n=len(group),gross_R=sum(p['r_mkt_rr'] for p in group))
            for kind,group in [('FLIP',[p for p in rows if p['audit_zone']['isFlip']]),
                               ('REGULAR',[p for p in rows if not p['audit_zone']['isFlip']])]}
    save('COHORT_ACCOUNTING.json',result)
    return result


def execution_audit(signals,m5,m1):
    rows={};excluded=[]
    for resolution in ['M5','M1']:
        for path in ['ADVERSE_FIRST','FAVORABLE_FIRST']:rows[f'{resolution}_{path}']=[]
    for s in [p for p in signals if p['pass_struct']]:
        start=s['idx']+1;end=min(len(m5),s['idx']+289)
        bars=m5[start:end];terminal=m5[end] if end<len(m5) else None
        if not len(bars):continue
        for path in ['ADVERSE_FIRST','FAVORABLE_FIRST']:
            rows[f'M5_{path}'].append(replay(s,bars,terminal,path,300))
        expected=(bars['time'][:,None]+np.arange(5)[None,:]*60).reshape(-1)
        at=np.searchsorted(m1['time'],expected);good=at<len(m1)
        good[good]&=m1['time'][at[good]]==expected[good]
        if not np.all(good):
            excluded.append(dict(idx=s['idx'],time=s['time'],year=s['year'],kz=s['kz'],missing_minutes=int(np.sum(~good))))
            continue
        for path in ['ADVERSE_FIRST','FAVORABLE_FIRST']:
            rows[f'M1_{path}'].append(replay(s,m1[at],terminal,path,60))
    result={}
    for name,items in rows.items():
        closed=[p for p in items if p['status']=='CLOSED']
        result[name]=dict(statuses=dict(Counter(p['status'] for p in items)),
            all=metric(closed),killzones=metric([p for p in closed if p['kz']]),
            years={str(y):metric([p for p in closed if p['year']==y and p['kz']]) for y in range(2021,2027)},
            costs={str(cost):dict(all=metric([{**p,'r':p['r']-cost/p['risk']} for p in closed]),
                   killzones=metric([{**p,'r':p['r']-cost/p['risk']} for p in closed if p['kz']])) for cost in [0.,.2,.5,1.]},
            signal_order_is_not_portfolio_equity=True,
            risk_outside_original_gate=sum(p['risk_outside_legacy_gate'] for p in closed))
        write_csv(f'trades_{name}.csv',items)
    eligible={p['idx'] for p in rows['M1_ADVERSE_FIRST']}
    for name in ['M5_ADVERSE_FIRST','M5_FAVORABLE_FIRST']:
        paired=[p for p in rows[name] if p['idx'] in eligible and p['status']=='CLOSED']
        result[name]['paired_with_M1_all']=metric(paired)
        result[name]['paired_with_M1_killzones']=metric([p for p in paired if p['kz']])
    result['M1_coverage']=dict(excluded_signals=len(excluded),excluded_killzone_signals=sum(p['kz'] for p in excluded),
        rule='Require all five M1 bars inside each present M5 bar of the original execution span. Market closures / gaps between M5 bars are retained; gap fills use the next opening quote. Quote clock is unchanged for reproduction.',
        source_is_bid_ohlc=True,not_real_ticks=True,not_ftmo_prices=True)
    write_csv('m1_excluded_signals.csv',excluded)
    save('EXECUTION_AUDIT.json',result)
    return result


def main():
    RUN.mkdir(parents=True,exist_ok=True)
    assert (RUN/'AUDIT_PLAN.md').exists()
    checks=fixtures()
    data=np.load(DATA)
    left=int(datetime(2021,10,23,tzinfo=UTC).timestamp());right=int(datetime(2026,10,23,23,59,59,tzinfo=UTC).timestamp())
    arrays={k:data[k][(data[k]['time']>=left)&(data[k]['time']<=right)] for k in ['h1','m5','m1']}
    for a in arrays.values():
        assert np.all(np.diff(a['time'])>0) and np.all(a['high']>=np.maximum(a['open'],a['close'])) and np.all(a['low']<=np.minimum(a['open'],a['close']))
    reproduction,signals=reproduce(arrays['h1'],arrays['m5'])
    print(json.dumps(dict(stage='legacy_reproduced',data_rows=reproduction['data_rows'],zones=reproduction['zones'],raw=reproduction['raw_signals'],match=reproduction['headline_counts_and_PnL_match_report'],pure_rr=reproduction['metrics']['r_mkt_rr'])),flush=True)
    prefixes=prefix_audit(arrays['h1'])
    print(json.dumps(dict(stage='prefix_checked',status=prefixes['status'],missing=[p['missing_flip_zones'] for p in prefixes['checks']])),flush=True)
    accounting=cohort_checks(signals,arrays['m5'])
    execution=execution_audit(signals,arrays['m5'],arrays['m1'])
    save('SOURCE_MANIFEST.json',dict(engine=dict(path=str(ENGINE),sha256=sha(ENGINE)),
        builder=dict(path=str(BUILDER),sha256=sha(BUILDER)),data=dict(path=str(DATA),sha256=sha(DATA)),
        indicator=dict(path=str(ROOT/'duc_tri_can_ho_tro.mq5'),sha256=sha(ROOT/'duc_tri_can_ho_tro.mq5')),
        binary=dict(path=str(ROOT/'duc_tri_can_ho_tro.ex5'),bytes=(ROOT/'duc_tri_can_ho_tro.ex5').stat().st_size,sha256=sha(ROOT/'duc_tri_can_ho_tro.ex5')),
        audit_script_sha256=sha(Path(__file__)),original_files_modified=False))
    print(json.dumps(dict(stage='execution_complete',accounting=accounting,execution={k:{a:b for a,b in v.items() if a in ['all','killzones','statuses','excluded_signals','excluded_killzone_signals']} for k,v in execution.items()})),flush=True)


if __name__=='__main__':main()
