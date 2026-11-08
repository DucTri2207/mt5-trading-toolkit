"""Frozen execution and FTMO-equity diagnostics; no orders or terminal login."""
import csv
import json
import math
from collections import Counter
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

import numpy as np

from gold_v301_causal_core import ROOT, RUN, COSTS
from research_gold_v301_causal import data, save, sha


def simulate(signal, bars, path, cost):
    """Independent next-open trade; events contain account-realized deltas / R0.

    Paths assign artificial times to OHLC vertices, not reconstructed tick times.
    Limit targets receive no favorable improvement; stops receive adverse slip.
    """
    spread, commission, slip = cost
    m = int(signal[0])+1; d = int(signal[3])
    if m >= len(bars):
        return None
    bid = float(bars[m, 1]); entry = bid + spread + slip if d == 1 else bid-slip
    stop = float(signal[5]); risk = d*(entry-stop)
    if risk < 2.5-1e-10 or risk > 10.+1e-10 or spread > .45+1e-10:
        return None
    qty = 1.; sl = -risk; be = False; tp1 = False
    realized = -.5*commission/risk
    events = [(float(bars[m, 0]), realized, d*((bid if d == 1 else bid+spread)-entry)/risk, 1.)]
    exit_time = None; reason = None

    def mark(t, x, delta=0.):
        events.append((float(t), float(delta), float(qty*x/risk), float(qty)))

    def close(t, x, why):
        nonlocal realized, qty, exit_time, reason
        delta = qty*(x-.5*commission)/risk
        realized += delta; qty = 0.; exit_time = float(t); reason = why
        mark(t, x, delta)

    def favorable(left, right, t0, t1):
        nonlocal realized, qty, sl, be, tp1
        levels = []
        if not be: levels.append((6., 'BE'))
        if not tp1: levels.append((1.5*risk, 'TP1'))
        levels.append((2.*risk, 'TP2'))
        for x, kind in sorted(levels):
            if left-1e-10 <= x <= right+1e-10:
                frac = 1. if not math.isfinite(left) or right == left else (x-left)/(right-left)
                t = t0+(t1-t0)*max(0., min(1., frac))
                mark(t, x)
                if kind == 'BE': be = True; sl = .1
                elif kind == 'TP1':
                    delta = .5*(x-.5*commission)/risk
                    realized += delta; qty = .5; tp1 = True; be = True; sl = .1
                    mark(t, x, delta)
                else:
                    close(t, x, 'TP2')
                    return True
        return False

    # Existing report's expiry was 288 observed M5 bars, not 24 wall-clock hours.
    end = min(len(bars), m+288)
    for j in range(m, end):
        t = float(bars[j, 0]); q = bars[j, 1:5].copy()
        if d == -1: q += spread
        xopen = d*(float(q[0])-entry)
        if xopen <= sl:
            close(t, xopen-slip, 'GAP_BE' if be else 'GAP_SL')
            break
        if favorable(-math.inf, xopen, t, t):
            break
        mark(t, xopen)
        adverse = float(q[2] if d == 1 else q[1]); beneficial = float(q[1] if d == 1 else q[2])
        extremes = [adverse, beneficial] if path == 'ADVERSE_FIRST' else [beneficial, adverse]
        before = xopen; before_t = t
        for k, price in enumerate(extremes+[float(q[3])], 1):
            now_t = t+(100. if k == 1 else (200. if k == 2 else 299.))
            x = d*(price-entry)
            if x < before and x <= sl <= before:
                cross_t = before_t+(now_t-before_t)*(before-sl)/(before-x)
                mark(cross_t, sl)
                close(cross_t, sl-slip, 'BE' if be else 'SL')
                break
            if x > before and favorable(before, x, before_t, now_t):
                break
            mark(now_t, x); before = x; before_t = now_t
        if qty == 0:
            break
    if qty:
        if end < len(bars):
            t = float(bars[end, 0]); quote = float(bars[end, 1])+(spread if d == -1 else 0.)
            x = d*(quote-entry)
            if x <= sl:
                close(t, x-slip, 'GAP_BE' if be else 'GAP_SL')
            elif not favorable(-math.inf, x, t, t):
                close(t, x-slip, 'TIME')
        else:
            # The end-of-sample position remains censored for headline results.
            t = float(bars[-1, 0])+299.
            x = d*(float(bars[-1, 4])+(spread if d == -1 else 0.)-entry)
            mark(t, x); exit_time = t; reason = 'CENSORED'
    row = dict(signal_index=int(signal[0]), signal_time=int(signal[1]), entry_time=int(bars[m, 0]),
        exit_time=exit_time, direction=d, entry=entry, initial_stop=stop, risk=risk, r=realized,
        reason=reason, tp1=tp1, zone_type=int(signal[8]), zone_id=int(signal[7]),
        year=datetime.fromtimestamp(int(signal[1]), tz=timezone.utc).year)
    assert all(events[k][0] <= events[k+1][0]+1e-7 for k in range(len(events)-1))
    assert math.isclose(math.fsum(x[1] for x in events), realized, abs_tol=1e-9)
    return row, np.asarray(events, dtype=float)


def select_trades(potential, start=0., end=math.inf):
    selected = []; available = start
    for row, events in potential:
        at = row['entry_time']
        if at < available or at < start or at >= end:
            continue
        selected.append((row, events)); available = row['exit_time']
    return selected


def metric(selected):
    rows = [r for r, _ in selected if r['reason'] != 'CENSORED']
    if not rows:
        return dict(n=0, net_R=0., profit_factor=None, max_closed_R_DD=0.)
    rs = np.array([r['r'] for r in rows]); curve = np.r_[0., np.cumsum(rs)]
    loss = -sum(min(x, 0.) for x in rs)
    return dict(n=len(rows), net_R=float(sum(rs)), mean_R=float(np.mean(rs)),
        profit_factor=float(sum(max(x, 0.) for x in rs)/loss) if loss else None,
        positive_net_pct=float(100*np.mean(rs>0)),
        max_closed_R_DD=float(np.max(np.maximum.accumulate(curve)-curve)),
        reasons=dict(Counter(r['reason'] for r in rows)),
        censored=sum(r['reason'] == 'CENSORED' for r, _ in selected))


def account(selected, fraction, feed_offset=0):
    """Fixed initial-capital risk. Intrabar equity and CE(S)T reset diagnostic."""
    initial = 100000.; money = initial*fraction
    balance = initial; peak = initial; maxdd = 0.; max_daily = 0.
    daily_balance = initial; day = None; total_breach = []; daily_breach = set()
    first10 = None; entry_days = set(); prague = ZoneInfo('Europe/Prague')
    curve = []
    for row, events in selected:
        entry_day = datetime.fromtimestamp(row['entry_time']-feed_offset*3600, tz=timezone.utc).astimezone(prague).date()
        entry_days.add(entry_day)
        for t, delta, floating, qty in events:
            dt = datetime.fromtimestamp(t-feed_offset*3600, tz=timezone.utc).astimezone(prague)
            if dt.date() != day:
                day = dt.date(); daily_balance = balance
            balance += delta*money
            equity = balance+floating*money
            peak = max(peak, equity); maxdd = max(maxdd, peak-equity)
            loss_today = daily_balance-equity; max_daily = max(max_daily, loss_today)
            if equity < initial*.9:
                total_breach.append(float(t))
            if equity < daily_balance-initial*.05:
                daily_breach.add(str(day))
            if qty == 0 and balance >= initial+initial*.1 and len(entry_days) >= 4 and first10 is None:
                first10 = float(t)
            curve.append([t, balance, equity])
    return dict(final_balance=balance, return_pct=(balance/initial-1)*100,
        max_equity_peak_drawdown_pct=maxdd/initial*100, max_daily_equity_loss_pct=max_daily/initial*100,
        total_floor_breached=bool(total_breach), daily_breach_days=sorted(daily_breach),
        first_total_breach=total_breach[0] if total_breach else None,
        first_closed_10pct_target=first10, entry_days=len(entry_days)), np.asarray(curve)


def challenge(potential, start, end, fraction, feed_offset=0, calendar=None):
    """Replay each starting date flat, using the original potential signal stream.

    No IID/Monte-Carlo interpretation; 365 days is a reporting horizon only.
    """
    initial = 100000.; money = initial*fraction
    phase = 1; balance = initial; day_balance = initial; day = None
    entry_days = set(); available = start; first_pass = None; trades = 0
    prague = ZoneInfo('Europe/Prague')
    for row, events in potential:
        if row['entry_time'] < available or row['entry_time'] < start:
            continue
        if row['entry_time'] >= end:
            break
        available = row['exit_time']; trades += 1
        dates = calendar[row['entry_time']] if calendar is not None else [
            datetime.fromtimestamp(t-feed_offset*3600, tz=timezone.utc).astimezone(prague).date() for t in events[:,0]]
        entry_days.add(dates[0])
        for (t, delta, floating, qty), date in zip(events, dates):
            if t >= end:
                return dict(status='UNRESOLVED', phase=phase, trades=trades)
            if date != day:
                day = date; day_balance = balance
            balance += delta*money; equity = balance+floating*money
            if equity < initial*.9 or equity < day_balance-initial*.05:
                return dict(status='FAILED', phase=phase, trades=trades, at=t,
                    reason='TOTAL' if equity < initial*.9 else 'DAILY')
            target = initial+initial*(.1 if phase == 1 else .05)
            if qty == 0 and balance >= target and len(entry_days) >= 4:
                if phase == 2:
                    return dict(status='BOTH_PHASES_MET', trades=trades, at=t,
                        days=(t-start)/86400., phase1_at=first_pass)
                phase = 2; first_pass = t; balance = initial; day_balance = initial
                day = None; entry_days = set()
    return dict(status='UNRESOLVED', phase=phase, trades=trades)


def calendar_for(potential):
    prague = ZoneInfo('Europe/Prague')
    return {r['entry_time']: [datetime.fromtimestamp(t,tz=timezone.utc).astimezone(prague).date()
                            for t in e[:,0]] for r,e in potential}


def fixtures():
    bars = np.array([[1000., 100., 111., 94., 101.], [1300., 101., 101., 101., 101.]])
    s = np.array([-1., 700., 1000., 1., 100., 95., 5., 1., 0., 60., 3., 1.])
    a = simulate(s, bars, 'ADVERSE_FIRST', COSTS['ZERO'])
    f = simulate(s, bars, 'FAVORABLE_FIRST', COSTS['ZERO'])
    assert math.isclose(a[0]['r'], -1.) and math.isclose(f[0]['r'], 1.75)
    bars[0, 2] = 106.1
    f = simulate(s, bars, 'FAVORABLE_FIRST', COSTS['ZERO'])
    assert math.isclose(f[0]['r'], .02)
    s[3] = -1.; s[5] = 105.; bars[0] = [1000., 100., 106., 89., 99.]
    a = simulate(s, bars, 'ADVERSE_FIRST', COSTS['ZERO'])
    f = simulate(s, bars, 'FAVORABLE_FIRST', COSTS['ZERO'])
    assert math.isclose(a[0]['r'], -1.) and math.isclose(f[0]['r'], 1.75)
    # A sell stop is triggered by Ask, with slippage and commissions.
    s[3] = 1.; s[5] = 95.; bars[0] = [1000., 100., 100., 94., 95.]
    x = simulate(s, bars, 'ADVERSE_FIRST', COSTS['LOW'])
    assert math.isclose(x[0]['r'], -1.-(.02+.06)/5.22)
    # Intrabar loss must fail a challenge even if its later close recovers.
    row = dict(entry_time=1704100000, exit_time=1704100100, reason='TP2')
    ev = np.array([[1704100000., 0., -11., 1.], [1704100100., 2., 0., 0.]])
    c = challenge([(row, ev)], 1704000000, 1704200000, .005)
    assert c['status'] == 'FAILED' and c['reason'] == 'DAILY'
    # The exact +10% and +5% monetary thresholds must both count as met.
    potential=[]; start=1704100000
    for i in range(8):
        t=start+i*86400
        row=dict(entry_time=t,exit_time=t+60,reason='TP2')
        ev=np.array([[t,0.,0.,1.],[t+60,2.5 if i<4 else 1.25,0.,0.]])
        potential.append((row,ev))
    c=challenge(potential,start-1,start+10*86400,.01)
    cc=challenge(potential,start-1,start+10*86400,.01,calendar=calendar_for(potential))
    assert c==cc and c['status']=='BOTH_PHASES_MET'
    # A midnight reset can cause a daily breach without any further price loss.
    t1=datetime(2026,11,1,22,59,tzinfo=timezone.utc).timestamp(); t2=t1+60
    row=dict(entry_time=int(t1),exit_time=t2+60,reason='TIME')
    ev=np.array([[t1,4.,-11.,1.],[t2,0.,-11.,1.],[t2+60,0.,0.,0.]])
    a,_=account([(row,ev)],.005)
    assert a['daily_breach_days']==['2026-11-02']
    return dict(execution_fixtures=4,intrabar_equity_fixture=True,
                exact_two_phase_targets_fixture=True,midnight_reset_fixture=True,passed=True)


def write_csv(path, rows):
    if not rows:
        path.write_text('', encoding='utf-8')
        return
    with path.open('w', encoding='utf-8-sig', newline='') as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0])); w.writeheader(); w.writerows(rows)


def main():
    save('EXECUTION_FIXTURES.json', fixtures())
    frozen = json.loads((RUN/'FROZEN_PLAN.json').read_text(encoding='utf-8'))
    # Before looking at any P&L, record the spread-cap-compatible scenarios.
    amendment = RUN/'EXECUTION_PLAN.json'
    if not amendment.exists():
        save('EXECUTION_PLAN.json', dict(created_utc=datetime.now(timezone.utc).isoformat(),
            reason='The initial planned BASE/STRESS spreads exceeded the original indicator MaxSpreadPrice=.45. Revised fixed scenarios below are inside that gate. No performance had been computed.',
            costs={k: dict(spread_price=v[0], roundtrip_commission_price=v[1], slippage_per_fill=v[2]) for k, v in COSTS.items()},
            actual_fill_gate='Keep the signal structural stop; reject if actual entry-to-stop is outside [2.5,10] price.',
            challenge_starts='First of each month 2022-01 through 2025-10, 365-calendar-day observation horizon, both phases sequential; overlapping historical windows are not independent.',
            spread_cap=.45, lot_margin_swap='Continuous per-unit risk model; no lot rounding, margin liquidation, or swap. This is not certified FTMO execution.'))
    d = data(); bars = d['m5']; saved = np.load(RUN/'signals.npz')
    results = {}; challenge_rows = []
    for strategy, key in [('REPORT_REPAIRED', 'repaired'), ('MQ5_PREFIX', 'native')]:
        signals = saved[key]
        for session in ['ALL', 'KZ']:
            selected_signals = signals if session == 'ALL' else signals[((signals[:, 1]//3600)%24>=8)&((signals[:, 1]//3600)%24<=17)]
            for cost_name, cost in COSTS.items():
                for path in ['ADVERSE_FIRST', 'FAVORABLE_FIRST']:
                    potential = []
                    for signal in selected_signals:
                        item = simulate(signal, bars, path, cost)
                        if item is not None:
                            potential.append(item)
                    selected = select_trades(potential)
                    name = f'{strategy}_{session}_{cost_name}_{path}'
                    value = dict(candidate_count=len(selected_signals), valid_fill_candidates=len(potential),
                        rejected_fills=len(selected_signals)-len(potential), skipped_busy=len(potential)-len(selected),
                        metrics=metric(selected), independent_candidate_metrics=metric(potential),
                        years={str(y): metric([(r, e) for r, e in selected if r['year'] == y]) for y in range(2021, 2027)})
                    value['accounts'] = {}
                    for fraction in [.0025, .005]:
                        a, curve = account(selected, fraction)
                        value['accounts'][str(fraction)] = a
                        if session == 'KZ' and fraction == .0025 and cost_name in ['ZERO', 'BASE']:
                            np.savez_compressed(RUN/f'equity_{name}.npz', equity=curve)
                    if session == 'KZ':
                        # Feed-time uncertainty affects the daily reset, not signal selection.
                        value['feed_clock_reset_sensitivity'] = {str(offset): account(selected, .005, offset)[0] for offset in [2, 3]}
                        write_csv(RUN/f'trades_{name}.csv', [r for r, e in selected])
                    results[name] = value
                    print(name, json.dumps(value['metrics']), flush=True)
                    if session == 'KZ' and cost_name in ['ZERO', 'BASE']:
                        calendar = calendar_for(potential)
                        for fraction in [.0025, .005]:
                            for year in range(2022, 2026):
                                for month in range(1, 13):
                                    if year == 2025 and month > 10: continue
                                    start = int(datetime(year, month, 1, tzinfo=timezone.utc).timestamp())
                                    c = challenge(potential, start, start+365*86400, fraction, calendar=calendar)
                                    challenge_rows.append(dict(strategy=strategy, cost=cost_name, path=path,
                                        risk=fraction, start=f'{year}-{month:02d}-01', **c))
                    save('EXECUTION_PROGRESS.json', dict(last_completed=name))
    save('RESULTS.json', results); save('CHALLENGE_WINDOWS.json', challenge_rows)
    write_csv(RUN/'challenge_windows.csv', [dict(strategy=r['strategy'], cost=r['cost'], path=r['path'],
        risk=r['risk'], start=r['start'], status=r['status'], phase=r.get('phase',2),
        trades=r['trades'], days=r.get('days'), reason=r.get('reason')) for r in challenge_rows])
    save('SOURCE_MANIFEST.json', dict(originals_unchanged=all(sha(ROOT/s)==v for s,v in frozen['sources'].items()),
        sources={s: sha(ROOT/s) for s in frozen['sources']}, data_sha256=sha(ROOT/'reports/scalp_structure_lab/20261025_pilot_v1/rates.npz'),
        research_scripts={s: sha(ROOT/'scripts'/s) for s in ['gold_v301_causal_core.py', 'research_gold_v301_causal.py', 'backtest_gold_v301_causal.py']}))


def refresh_financial_gates():
    """Recheck the exact money target boundary after the execution replay."""
    d=data(); cached=np.load(RUN/'signals.npz'); results=json.loads((RUN/'RESULTS.json').read_text(encoding='utf-8'))
    windows=[]
    for strategy,key in [('REPORT_REPAIRED','repaired'),('MQ5_PREFIX','native')]:
        s=cached[key]; s=s[((s[:,1]//3600)%24>=8)&((s[:,1]//3600)%24<=17)]
        for cost in ['ZERO','BASE']:
            for path in ['ADVERSE_FIRST','FAVORABLE_FIRST']:
                potential=[]
                for signal in s:
                    item=simulate(signal,d['m5'],path,COSTS[cost])
                    if item is not None:potential.append(item)
                selected=select_trades(potential); name=f'{strategy}_KZ_{cost}_{path}'
                # Trade replay itself must stay identical to the earlier ledger.
                now=metric(selected)
                assert now==results[name]['metrics']
                for risk in [.0025,.005]:
                    results[name]['accounts'][str(risk)]=account(selected,risk)[0]
                calendar=calendar_for(potential)
                for risk in [.0025,.005]:
                    for year in range(2022,2026):
                        for month in range(1,13):
                            if year==2025 and month>10:continue
                            start=int(datetime(year,month,1,tzinfo=timezone.utc).timestamp())
                            c=challenge(potential,start,start+365*86400,risk,calendar=calendar)
                            windows.append(dict(strategy=strategy,cost=cost,path=path,risk=risk,start=f'{year}-{month:02d}-01',**c))
                print('FINANCIAL_GATES_RECHECKED',name,flush=True)
    save('RESULTS.json',results); save('CHALLENGE_WINDOWS.json',windows)
    write_csv(RUN/'challenge_windows.csv',[dict(strategy=r['strategy'],cost=r['cost'],path=r['path'],risk=r['risk'],start=r['start'],
        status=r['status'],phase=r.get('phase',2),trades=r['trades'],days=r.get('days'),reason=r.get('reason')) for r in windows])
    manifest=json.loads((RUN/'SOURCE_MANIFEST.json').read_text(encoding='utf-8'))
    manifest['research_scripts']['backtest_gold_v301_causal.py']=sha(ROOT/'scripts/backtest_gold_v301_causal.py')
    save('SOURCE_MANIFEST.json',manifest)


if __name__ == '__main__':
    import sys
    if '--refresh-financial-gates' in sys.argv: refresh_financial_gates()
    else: main()
