import csv,json,hashlib,re,math
from pathlib import Path
from collections import Counter
ROOT=Path(__file__).resolve().parents[1];RUN=ROOT/'reports/can_ho_tro_v4/20261102_v401_final_v1';OLD=ROOT/'reports/can_ho_tro_v4/20261102_v401_v1'
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def dump(p,x):p.write_text(json.dumps(x,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
def rows(p):
    with p.open(encoding='utf-8-sig') as f:return list(csv.DictReader(f))
def one(p,pattern):return next(p.glob(pattern))
def metric(s,label):
    m=re.search(re.escape(label)+r':</td>\s*<td[^>]*><b>(.*?)</b>',s,re.S);assert m,label
    return re.sub('<[^>]*>','',m.group(1)).strip()
def main():
    results={};proof=[]
    for label in ['final401_tp1r','final401_trail']:
        r=RUN/label;t=one(r,'Agent-*/Tester');tr=rows(t/'trades_XAUUSD.csv');audit=rows(t/'risk_audit.csv');events=rows(t/'execution_events_XAUUSD.csv');sig=rows(t/'signals_XAUUSD.csv')
        diag=dict(x.split('=',1) for x in (t/'diagnostics.txt').read_text().split())
        html=one(r,'report.*').read_text(encoding='utf-16')
        assert len(tr)==len(audit)==len(sig)==29 and all(x['status']=='CLOSED' for x in tr)
        assert not any(x['action']=='FAIL_CLOSED' for x in events)
        assert int(diag['ticks'])==44373721 and metric(html,'History Quality')=='100% real ticks'
        assert int(diag['last_evaluated'])==1793400600
        maxstep=0;maxcash=0;risks=[]
        for x,a in zip(tr,audit):
            assert x['signal_id']==a['signal_id']
            cash=float(x['risk_price'])*float(x['volume'])*100
            assert abs(cash-float(x['risk_USD']))<1e-6
            err=abs(float(a['actual_sl_cash'])-float(a['target_cash']))/float(a['one_step_cash']);assert err<=1+1e-7;maxstep=max(maxstep,err)
            assert abs(float(a['actual_sl_cash'])-float(x['risk_USD']))<1e-7
            assert abs(float(a['actual_sl_cash'])/float(a['tick_formula_cash'])-10)<1e-6
            side=1 if x['direction']=='BUY' else -1
            predicted=(float(x['exit_price'])-float(x['entry']))*side*float(x['volume'])*100
            e=abs(predicted-float(x['gross_USD']));maxcash=max(maxcash,e);assert e<.011
            assert abs(float(x['net_R'])-float(x['net_USD'])/cash)<1e-8
            risks.append(float(a['actual_sl_cash'])/float(a['equity'])*100)
            proof.append(dict(run=label,signal_id=x['signal_id'],risk_cash=cash,target_cash=float(a['target_cash']),error_steps=err,gross_cash_error=e))
        rs=[float(x['net_R']) for x in tr];gross=[float(x['gross_USD'])/float(x['risk_USD']) for x in tr]
        results[label]=dict(signals=len(sig),closed=len(tr),ticks=int(diag['ticks']),quality=metric(html,'History Quality'),win_net_percent=100*sum(x>0 for x in rs)/len(rs),mean_gross_R=sum(gross)/len(gross),mean_net_R=sum(rs)/len(rs),sum_net_R=sum(rs),PF_R=sum(x for x in rs if x>0)/-sum(x for x in rs if x<0),net_USD=sum(float(x['net_USD']) for x in tr),commission_USD=sum(float(x['commission_USD']) for x in tr),fee_USD=sum(float(x['fee_USD']) for x in tr),swap_USD=sum(float(x['swap_USD']) for x in tr),equity_DD_maximal=metric(html,'Equity Drawdown Maximal'),equity_DD_relative=metric(html,'Equity Drawdown Relative'),exit_reasons=dict(Counter(x['exit_reason'] for x in tr)),execution_events=dict(Counter(x['action'] for x in events)),max_risk_error_steps=maxstep,actual_SL_risk_percent_min=min(risks),actual_SL_risk_percent_max=max(risks),max_gross_cash_reconciliation_error=maxcash,diagnostics=diag)
    # Compare the fresh EA list directly against accepted broker indicator list.
    a=rows(one(RUN/'final401_tp1r','Agent-*/Tester/signals_XAUUSD.csv'));b=rows(one(OLD/'v401_indicator','Agent-*/signals_XAUUSD.csv'))
    assert a==b and len(a)==29
    dump(RUN/'POSITIVE_PARITY.json',dict(ea=29,accepted_indicator=29,matched=29,columns=len(a[0]),mismatches=[],reuse_reason='Detector, scale, RR, inputs and presets unchanged; fresh EA rows equal accepted indicator rows. No new visual test.'))
    before=RUN/'before/MQL5';current=ROOT/'can_ho_tro_v4/MQL5';changed=[]
    for p in current.rglob('*'):
        if p.is_file() and p.suffix!='.ex5' and (not (before/p.relative_to(current)).exists() or sha(p)!=sha(before/p.relative_to(current))):changed.append(p.relative_to(current).as_posix())
    allowed={'Experts/CanHoTroV4_TesterEA.mq5'}|{'Include/CanHoTroV4/'+x for x in ['Risk.mqh','Execution.mqh','Journal.mqh','M2Panel.mqh','StopRules.mqh']}
    assert set(changed)<=allowed,changed
    presets=ROOT/'can_ho_tro_v4/Presets';assert all(sha(p)==sha(RUN/'before/Presets'/p.name) for p in presets.iterdir() if p.is_file())
    dump(RUN/'SCOPE_DIFF.json',dict(changed_source=changed,detector_scale_RR_unchanged=True,presets_unchanged=True,accepted_prefix_modes={'0':200,'1':200}))
    dump(RUN/'RISK_EXECUTION_AUDIT.json',dict(checks=len(proof),passed=True,orders=proof))
    dump(RUN/'RESULTS_FINAL.json',results)
    # Keep only risk warning lines from the exact final run wall-clock intervals.
    warning=[]
    for label in results:
        filtered=one(RUN/label,'*.filtered.txt').read_text(encoding='utf-8').splitlines()
        times=[x.split('\t')[2] for x in filtered if len(x.split('\t'))>2];lo,hi=min(times),max(times)
        for p in (ROOT/'reports/can_ho_tro_v4/20261102_m3a_v1/portable_terminal/Tester').glob('Agent-*/logs/*.log'):
            raw=p.read_bytes();txt=raw.decode('utf-16' if raw.startswith(b'\xff\xfe') else 'utf-8-sig',errors='replace')
            for line in txt.splitlines():
                fields=line.split('\t')
                if len(fields)>2 and lo<=fields[2]<=hi and ('V4_RISK_WARNING' in line or 'V4_RISK_FAIL_CLOSED' in line or 'V4 tester failed' in line):warning.append(label+' '+line)
    (RUN/'RISK_WARNINGS.filtered.txt').write_text('\n'.join(warning)+'\n',encoding='utf-8')
    assert len(warning)==2 and all('V4_RISK_WARNING' in x for x in warning)
    print(json.dumps(results,ensure_ascii=True,indent=2))
if __name__=='__main__':main()
