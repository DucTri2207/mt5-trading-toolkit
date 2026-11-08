"""Backtest the frozen v1 setup on audited cached Nasdaq CFD history. No tuning."""
from collections import Counter,defaultdict
from dataclasses import asdict
from datetime import date,datetime,timedelta,timezone
from pathlib import Path
import csv
import json

import numpy as np

from collect_us100_ny import ROOT,sha,write_json
from prepare_us100_cached_data import broker_to_utc
from us100_ny_core import (COSTS,detect,m1_eligible_days,simulate_day,summary,
                           session_bounds,session_time,ny_day,prop_attempt,RISK)

RUN=ROOT/'reports/us100_ny_scalp/20261101_backtest_v2'
OLD=ROOT/'reports/us100_ny_scalp/20261101_v1'
UTC=timezone.utc
YEARS=range(2022,2027)
LOCK='e8b674356b7e0a9cff96da9ed0be6446b9978548793cb0af2f7027dfcd9463b3'


def dates(first=date(2022,1,1),last=date(2026,10,30)):
    d=first
    while d<=last:
        if d.weekday()<5:yield d
        d+=timedelta(days=1)


def week(d):return d-timedelta(days=d.weekday())


def block_interval(trades,days,reps=10000,seed=20261101):
    weeks=sorted({week(d) for d in days})
    sums=np.zeros(len(weeks));counts=np.zeros(len(weeks),dtype=int)
    index={w:i for i,w in enumerate(weeks)}
    for p in trades:
        i=index[week(date.fromisoformat(p['date']))]
        sums[i]+=p['r_net'];counts[i]+=1
    result=dict(method='nonoverlapping calendar-week cluster percentile bootstrap of mean trade net R',
                replicates=reps,seed=seed,weeks=len(weeks),trades=len(trades),
                sample_gate_met=len(weeks)>=26 and len(trades)>=200)
    if not trades or not weeks:return dict(**result,mean_R_95pct=None,zero_trade_replicates=reps)
    draw=np.random.default_rng(seed).integers(0,len(weeks),size=(reps,len(weeks)))
    denominator=counts[draw].sum(axis=1);valid=denominator>0
    estimates=sums[draw].sum(axis=1)[valid]/denominator[valid]
    return dict(**result,mean_R_95pct=np.quantile(estimates,[.025,.975]).tolist(),
                zero_trade_replicates=int(np.sum(~valid)))


def write_csv(path,rows):
    if not rows:
        path.write_text('',encoding='utf-8');return
    keys=list(dict.fromkeys(k for p in rows for k in p))
    with path.open('w',newline='',encoding='utf-8-sig') as f:
        writer=csv.DictWriter(f,fieldnames=keys);writer.writeheader();writer.writerows(rows)


def audit_ticks(bid):
    path=RUN/'offline_terminal/MQL5/Files/nasdaq_cache_export/ticks.csv'
    if not path.exists():return None,dict(status='unavailable')
    raw=np.loadtxt(path,delimiter=',')
    assert raw.ndim==2 and raw.shape[1]==4 and np.isfinite(raw).all()
    assert np.all(np.diff(raw[:,0])>=0) and np.all(raw[:,1]>1000) and np.all(raw[:,2]>=raw[:,1])
    t=broker_to_utc(raw[:,0]/1000.)
    ticks=np.column_stack((t,raw[:,1:3]))
    minutes=(t//60).astype(np.int64)*60
    ends=np.r_[np.flatnonzero(np.diff(minutes)!=0),len(ticks)-1]
    public=np.column_stack((minutes[ends],ticks[ends,1]))
    comparisons=[]
    for shift in range(-4,5):
        target=public[:,0]+shift*3600;indices=np.searchsorted(bid[:,0],target)
        ok=indices<len(bid);ok[ok]&=bid[indices[ok],0]==target[ok]
        pairs=ok[1:]&ok[:-1]&(np.diff(public[:,0])==60)
        ix=np.flatnonzero(pairs)+1
        x=np.diff(public[:,1])[pairs];y=bid[indices[ix],4]-bid[indices[ix-1],4]
        corr=float(np.corrcoef(x,y)[0,1]) if len(x)>80 and np.std(x)>0 and np.std(y)>0 else None
        error=np.abs(public[ok,1]-bid[indices[ok],4])
        comparisons.append(dict(shift_hours=shift,pairs=len(x),correlation=corr,
                                median_close_error=float(np.median(error)) if len(error) else None))
    best=max(comparisons,key=lambda r:r['correlation'] if r['correlation'] is not None else -2)
    assert best['shift_hours']==0 and best['correlation']>.99 and best['median_close_error']<=.011, 'Tick clock/feed does not match M1'
    np.savez_compressed(RUN/'broker_ticks_sample.npz',ticks=ticks)
    info=dict(status='partial_cached_sample',rows=len(ticks),raw_sha256=sha(path),
              first_utc=datetime.fromtimestamp(t[0],UTC).isoformat(),last_utc=datetime.fromtimestamp(t[-1],UTC).isoformat(),
              spread_quantiles=np.quantile(raw[:,2]-raw[:,1],[0,.5,.9,.99,1]).tolist(),comparisons=comparisons,
              native_result=json.loads((RUN/'TICK_EXPORT_RESULT.json').read_text(encoding='utf-8')),
              limitation='Native CopyTicksRange returned a timeout and partial October history, not full requested coverage; no missing quotes are generated.')
    return ticks,info


def monthly_starts(trades,first_year=2024):
    results=[]
    for year in range(first_year,2027):
        for month in range(1,13):
            start=date(year,month,1)
            if start>date(2026,10,30):break
            chosen=[p for p in trades if p['date']>=start.isoformat()]
            result=prop_attempt(chosen)
            result.update(start=start.isoformat(),observed_trades=len(chosen))
            results.append(result)
    return results


def fmt(x,digits=2):return '--' if x is None else f'{x:.{digits}f}'


def main():
    assert sha(OLD/'SPEC_LOCK.json')==LOCK
    assert (RUN/'EXECUTION_CLOCK_AMENDMENT.md').exists()
    manifest=json.loads((RUN/'DATA_MANIFEST.json').read_text(encoding='utf-8'))
    assert sha(RUN/'broker_m1.npz')==manifest['data_sha256']
    data=np.load(RUN/'broker_m1.npz');bid=data['bid']
    assert np.isfinite(bid).all() and np.all(np.diff(bid[:,0])>0)
    days,rejected=m1_eligible_days(bid);days=set(days)
    observed=set(bid[:,0].astype(np.int64).tolist())
    exclusions={p['date']:p for p in rejected}
    for d in dates():
        if d not in days and d.isoformat() not in exclusions:
            start,end=session_bounds(d)
            exclusions[d.isoformat()]=dict(date=d.isoformat(),missing_required_minutes=sum(t not in observed for t in range(start-12000,end+60,60)))
    coverage={}
    for year in YEARS:
        year_days=sorted(d for d in days if d.year==year)
        coverage[str(year)]=dict(planned_weekdays=sum(d.year==year for d in dates()),eligible_days=len(year_days),
            excluded_weekdays=sum(p['date'].startswith(str(year)) for p in exclusions.values()),
            first_eligible=year_days[0].isoformat() if year_days else None,
            last_eligible=year_days[-1].isoformat() if year_days else None,
            eligible_weeks=len({week(d) for d in year_days}),
            first_bar_utc=datetime.fromtimestamp(bid[np.flatnonzero((bid[:,0]>=datetime(year,1,1,tzinfo=UTC).timestamp())&(bid[:,0]<datetime(year+1,1,1,tzinfo=UTC).timestamp()))[0],0],UTC).isoformat())
    write_csv(RUN/'excluded_days.csv',sorted(exclusions.values(),key=lambda p:p['date']))
    print(json.dumps(dict(stage='data_audit',coverage=coverage)),flush=True)
    ticks,tick_audit=audit_ticks(bid)
    write_json(RUN/'TICK_AUDIT.json',tick_audit)
    all_signals=detect(bid)
    signals=[s for s in all_signals if session_time(s.known_at)]
    grouped=defaultdict(list)
    for s in signals:grouped[ny_day(s.known_at)].append(s)
    write_csv(RUN/'signals.csv',[dict(**asdict(s),eligible_day=ny_day(s.known_at) in days,date=ny_day(s.known_at).isoformat()) for s in signals])
    tick_days={};tick_excluded=[]
    if ticks is not None:
        first=ny_day(ticks[0,0]);last=ny_day(ticks[-1,0])
        for d in sorted(day for day in days if first<=day<=last):
            start,end=session_bounds(d)
            q=ticks[(ticks[:,0]>=start-300)&(ticks[:,0]<=end+60)]
            good=len(q)>1 and q[0,0]<=start-240 and q[-1,0]>=end and np.max(np.diff(q[:,0]))<=60
            if good:tick_days[d]=q
            else:tick_excluded.append(d.isoformat())
    results={};all_trades=[]
    for cost in COSTS:
        trades=[];tick_trades=[];paired_m1=[]
        for d in sorted(days):
            start,end=session_bounds(d)
            lo,hi=np.searchsorted(bid[:,0],[start,end],side='left');b=bid[lo:hi+1]
            # Synthetic side equals Bid here; the fixed scenario floor supplies the assumed spread.
            rows=simulate_day(d,grouped[d],b,b.copy(),cost,tick=manifest['trade_tick_size'])
            trades.extend(rows)
            if d in tick_days:
                tick_trades.extend(simulate_day(d,grouped[d],b,b.copy(),cost,ticks=tick_days[d],tick=manifest['trade_tick_size']))
                paired_m1.extend(rows)
        annual={str(y):summary([p for p in trades if p['date'].startswith(str(y))]) for y in YEARS}
        for p in trades:
            assert p['entry_time']==p['known_at'] and p['entry_time']<p['exit_time']<=p['deadline']
            assert p['risk_points']>0 and np.isfinite(p['r_net']) and p['mae_r']<=min(0,p['r_net'])+1e-9
        for d in {p['date'] for p in trades}:
            today=[p for p in trades if p['date']==d]
            assert len(today)<=3 and sum(p['reason']=='SL' for p in today)<=2
        test=[p for p in trades if p['date'].startswith('2026')]
        primary=[p for p in trades if p['date']>='2024-01-01']
        starts=monthly_starts(trades)
        results[cost.name]=dict(cost=asdict(cost),all_cached=summary(trades),years=annual,
            primary_2024_onward=summary(primary),test_2026=summary(test),
            test_2026_bootstrap=block_interval(test,[d for d in days if d.year==2026]),
            prop_from_first_cached_trade=prop_attempt(trades),prop_from_2024=prop_attempt(primary),
            prop_from_2026=prop_attempt(test),monthly_starts=starts,
            monthly_start_counts=dict(Counter(p['status'] for p in starts)),
            monthly_start_counts_2026=dict(Counter(p['status'] for p in starts if p['start'].startswith('2026'))),
            supplemental_ticks=dict(eligible_days=[d.isoformat() for d in tick_days],excluded_days=tick_excluded,
                tick=summary(tick_trades),paired_fixed_spread_m1=summary(paired_m1)))
        export=[dict(cost=cost.name,entry_utc=datetime.fromtimestamp(p['entry_time'],UTC).isoformat(),
                     exit_utc=datetime.fromtimestamp(p['exit_time'],UTC).isoformat(),**p) for p in trades]
        write_csv(RUN/f'trades_{cost.name}.csv',export)
        write_csv(RUN/f'tick_trades_{cost.name}.csv',tick_trades)
        all_trades.extend(export)
        print(json.dumps(dict(stage='scenario_finished',cost=cost.name,years=annual,test_interval=results[cost.name]['test_2026_bootstrap'],prop_2026=results[cost.name]['prop_from_2026'])),flush=True)
    result=dict(strategy_spec_sha256=LOCK,data_sha256=manifest['data_sha256'],core_sha256=sha(ROOT/'scripts/us100_ny_core.py'),
        runner_sha256=sha(Path(__file__)),amendment_sha256=sha(RUN/'EXECUTION_CLOCK_AMENDMENT.md'),
        coverage=coverage,first_utc=manifest['first_utc'],last_utc=manifest['last_utc'],rows=len(bid),
        session_signals=len(signals),eligible_session_signals=sum(ny_day(s.known_at) in days for s in signals),
        risk_fraction=RISK,price_tick=manifest['trade_tick_size'],tick_audit=tick_audit,results=results)
    write_json(RUN/'BACKTEST_SUMMARY.json',result)
    write_csv(RUN/'trades_all.csv',all_trades)
    report(result)


def report(result):
    base=result['results']['BASE'];ci=base['test_2026_bootstrap'];test=base['test_2026']
    edge=ci['sample_gate_met'] and ci['mean_R_95pct'] is not None and ci['mean_R_95pct'][0]>0
    if test['mean_R'] is None:verdict='Không có lệnh đủ điều kiện trong mẫu kiểm tra 2026.'
    elif test['mean_R']<=0:verdict='Bản v1 không cho lợi thế dương sau chi phí BASE trong mẫu kiểm tra 2026. Không đạt cơ sở dùng để mua challenge FTMO.'
    elif not edge:verdict='Mẫu kiểm tra 2026 có lãi mô phỏng ở BASE, nhưng chưa đủ bằng chứng thống kê để dùng làm phương án pass FTMO.'
    else:verdict='Mẫu kiểm tra 2026 có kỳ vọng dương trong mô hình BASE; cần xác nhận trên giá/khớp lệnh FTMO trước khi áp dụng.'
    lines=['# Backtest US100 NY Pullback v1 — dữ liệu mở rộng','',f'**{verdict}**','',
           '## Phạm vi thực tế','',
           f"- {result['rows']:,} nến M1 USTEC từ cache MetaQuotes-Demo, {result['first_utc']} đến {result['last_utc']}. Dữ liệu CFD proxy, chưa phải FTMO US100.cash.",
           '- Giữ nguyên một bộ quy tắc v1; không tìm tham số, không chọn lại giờ hoặc mục tiêu theo kết quả. 2022–2023 là chẩn đoán bổ sung; 2024 phát triển, 2025 xác nhận, 2026 kiểm tra theo kế hoạch cũ.',
           '- Clock của proxy: UTC+2, DST châu Âu; đối chiếu 18 mẫu giá độc lập, có tuần lệch DST Mỹ/châu Âu. Phiên chiến lược vẫn là 09:35–11:00 New York.',
           '- Chỉ tính ngày có đủ từng nến từ 200 phút trước phiên đến 11:00 NY. Không nội suy đoạn thiếu. Danh sách excluded_days.csv gồm cả ngày lễ, không đồng nghĩa toàn bộ là lỗi feed.','',
           '| Năm | Ngày thường trong kế hoạch | Phiên đủ dữ liệu | Bị loại | Phiên đầu / cuối |',
           '|---|---:|---:|---:|---|']
    for y,r in result['coverage'].items():
        lines.append(f"| {y} | {r['planned_weekdays']} | {r['eligible_days']} | {r['excluded_weekdays']} | {r['first_eligible']} / {r['last_eligible']} |")
    lines+=['',
            'Cache demo cũng có báo giá trong 01/01/2025 (ví dụ nến quanh 15:00 UTC chỉ dao động 0,25 điểm). Có đủ nến không chứng minh thanh khoản có thể giao dịch; không áp thêm bộ lọc ngày lễ sau khi xem kết quả. Nguồn này phù hợp kiểm tra giả thuyết sơ bộ, không thay thế dữ liệu thực thi của FTMO.',
            '', '## Kết quả BASE: spread 2 điểm, slippage 0,5 điểm','',
            '| Năm | Lệnh | Thắng | Tổng R ròng | R/lệnh | PF | Lãi/lỗ mô phỏng | DD từ đỉnh balance |',
            '|---|---:|---:|---:|---:|---:|---:|---:|']
    for y,r in base['years'].items():
        lines.append(f"| {y} | {r['trades']} | {fmt(r['win_rate_pct'])}% | {r['net_R']:+.2f} | {fmt(r['mean_R'],4)} | {fmt(r['profit_factor'])} | {r['return_pct']:+.2f}% | {r['drawdown_vs_closed_balance_peak_pct']:.2f}% |")
    lines+=['','Risk 0,25% equity hiện tại cho mỗi lệnh; lãi/lỗ từng năm bắt đầu lại từ vốn 1. DD đo equity bất lợi so với đỉnh balance đã chốt, không bao gồm đỉnh equity thả nổi trong lệnh. R là lợi nhuận ròng chia ngân sách rủi ro đã dự phòng SL slippage.','',
            '## Kiểm tra 2026 theo cả ba mức phí','',
            '| Phí | Lệnh | Thắng | Tổng R | R/lệnh | PF | Lãi/lỗ | DD từ đỉnh balance |',
            '|---|---:|---:|---:|---:|---:|---:|---:|']
    for name,row in result['results'].items():
        r=row['test_2026'];lines.append(f"| {name} | {r['trades']} | {fmt(r['win_rate_pct'])}% | {r['net_R']:+.2f} | {fmt(r['mean_R'],4)} | {fmt(r['profit_factor'])} | {r['return_pct']:+.2f}% | {r['drawdown_vs_closed_balance_peak_pct']:.2f}% |")
    lines+=['',
            '- LOW: spread 0, slippage 0 — cận lạc quan không ma sát, không phải giá giao dịch thực tế.',
            '- BASE: spread cố định 2 điểm chỉ số, slippage bất lợi 0,5 điểm mỗi fill market/SL.',
            '- STRESS: spread cố định 3 điểm, slippage 1 điểm. Bộ lọc spread/ATR giữ nguyên nên số lệnh có thể giảm.',
            '- Commission giả định 0. Tick giá 0,01. Exposure USD/điểm lẻ; chưa kiểm định lot step, margin hay độ trễ thao tác trên tài khoản FTMO.',
            '- Entry ở open nến kế tiếp sau tín hiệu đóng. Ask được mô hình hóa từ Bid và spread cố định. Không dùng spread được ghi trong chính nến tương lai để vào lệnh. SL gap chịu giá bất lợi; TP không nhận lợi ích gap; chạm cả SL/TP trong M1 tính SL trước.','',
            '## Độ bất định của mẫu 2026','',
            f"BASE có {ci['trades']} lệnh trong {ci['weeks']} tuần đủ dữ liệu. Bootstrap theo cụm tuần, 10.000 lần, seed 20261101; khoảng 95% cho R/lệnh: {ci['mean_R_95pct']}. Điều kiện >=200 lệnh và >=26 tuần: {'đạt' if ci['sample_gate_met'] else 'chưa đạt'}.",
            'Khoảng tin cậy này chỉ mô tả sự bất định trong dữ liệu proxy và giả định thực thi đã dùng; không bao gồm sai lệch giá FTMO, các khoảng dữ liệu bị thiếu hay tác động chọn chiến lược qua nhiều nghiên cứu.','',
            '## Mô phỏng benchmark FTMO CFD 2-Step','',
            'Áp dụng mục tiêu +10% rồi +5%; giới hạn equity ngày 5%, tổng 10% vốn ban đầu; ít nhất bốn ngày vào lệnh mỗi phase; reset ngày Prague. Phase hai bắt đầu ngày kế tiếp, vốn reset. Không giới hạn thời gian. [Nguồn quy tắc FTMO](https://ftmo.com/en/trading-objectives/).','',
            '| Phí | Bắt đầu chuỗi 2024 | Bắt đầu chuỗi 2026 | Tháng bắt đầu 2026: đạt cả hai / fail / chưa ngã ngũ |',
            '|---|---|---|---|']
    for name,row in result['results'].items():
        c=row['monthly_start_counts_2026'];lines.append(f"| {name} | {row['prop_from_2024']['status']} | {row['prop_from_2026']['status']} | {c.get('BOTH_PHASES_REACHED',0)} / {c.get('FAIL',0)} / {c.get('CENSORED',0)} |")
    lines+=['','FAIL là vi phạm giới hạn lỗ trong mô hình. CENSORED là lịch sử kết thúc trước khi đạt cả hai mục tiêu hoặc fail; không được đổi thành thất bại hoặc thành công. Các lần bắt đầu tháng chồng lấn nhau, thời gian quan sát khác nhau; không coi số đạt/tổng là xác suất pass tương lai. Chi tiết ngày, phase và balance trong BACKTEST_SUMMARY.json.','',
            '## Đối chiếu tick bổ sung','',
            f"Xuất được {result['tick_audit'].get('rows',0):,} quote Bid/Ask; trạng thái {result['tick_audit']['status']}. Cache chỉ có một phần tháng 10/2026; yêu cầu xuất cả tháng trả timeout kèm phần dữ liệu có sẵn. TICK_AUDIT.json giữ nguyên lỗi và kiểm tra khớp giá/thời gian với M1.",
            '', '| Phí | Phiên tick đủ | Lệnh tick | R tick | Lệnh M1 cùng ngày | R M1 |','|---|---:|---:|---:|---:|---:|']
    for name,row in result['results'].items():
        s=row['supplemental_ticks'];lines.append(f"| {name} | {len(s['eligible_days'])} | {s['tick']['trades']} | {s['tick']['net_R']:+.3f} | {s['paired_fixed_spread_m1']['trades']} | {s['paired_fixed_spread_m1']['net_R']:+.3f} |")
    lines+=['','Tick dùng spread Bid/Ask thực tế cùng các floor/slippage đã khóa. Ngày tick 16/10/2026 không có lệnh ở cả M1 và tick, nên chỉ đối chiếu được giá/clock; chưa kiểm chứng được khớp SL/TP bằng giao dịch trong ngày này. Không coi đây là xác nhận thực thi cho backtest nhiều năm.','',
            '## Tệp kiểm chứng','',
            '- BACKTEST_SUMMARY.json: kết quả đủ ba phí, từng năm, các lần mô phỏng challenge và bootstrap.',
            '- trades_BASE.csv, trades_LOW.csv, trades_STRESS.csv: từng lệnh, UTC entry/exit, SL/TP, lý do thoát, R ròng, MAE.',
            '- DATA_MANIFEST.json, CLOCK_AUDIT.json, EXECUTION_CLOCK_AMENDMENT.md: nguồn, kiểm tra clock, giả định thực thi khóa trước P&L.',
            '- signals.csv và excluded_days.csv: tín hiệu và ngày thiếu dữ liệu.',
            '- broker_m1.npz, broker_ticks_sample.npz: dữ liệu đã quy đổi UTC để tái lập.',
            '- Chạy lại: python scripts/backtest_us100_cached.py. Các tệp v1 được giữ như bản ghi kết quả ban đầu.','']
    (RUN/'REPORT.md').write_text('\n'.join(lines),encoding='utf-8')
    print(json.dumps(dict(report=str(RUN/'REPORT.md'),verdict=verdict),ensure_ascii=True),flush=True)


if __name__=='__main__':main()
