# -*- coding: utf-8 -*-
"""Make an auditable handoff; never promote an unsuccessful economic test."""
import csv
import json
import zipfile
from datetime import datetime, timezone
from pathlib import Path

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np

import research_scalp_v2 as r
from prepare_can_ho_tro_scalp import sha, write_json


def read(p):return json.loads(p.read_text(encoding='utf-8'))


def main():
    folders=[('H1_M5',r.RUN),('H1_M1',r.RUN.parent/'20261101_m1_v2'),
             ('DIRECT_RECLAIM',r.RUN.parent/'20261101_reclaim_v2'),
             ('BREAKOUT_PULLBACK',r.RUN.parent/'20261101_breakout_v2')]
    all_rows=[];registry=[]
    for family,folder in folders:
        summary=read(folder/'summary.json');lock=read(folder/'EXPERIMENT_LOCK.json')
        registry.append(dict(family=family,folder=str(folder.relative_to(r.ROOT)),
                             hypothesis_count=len(lock['hypotheses']),scenario_count=len(summary['rows']),
                             lock_sha256=sha(folder/'EXPERIMENT_LOCK.json')))
        for row in summary['rows']:all_rows.append(dict(family=family,folder=folder,**row))
    assert sum(x['hypothesis_count'] for x in registry)==32
    assert len(all_rows)==108
    primary=[]
    for family,folder in folders:
        source=[x for x in all_rows if x['family']==family and x['cost']=='BASE']
        for name in sorted(set(x['name'] for x in source)):
            # Use the worse declared intraminute path for pending models.
            primary.append(min((x for x in source if x['name']==name),key=lambda x:x['metrics']['total_r']))
    assert len(primary)==32
    csv_path=r.RUN/'ALL_EXPERIMENTS.csv'
    with csv_path.open('w',encoding='utf-8-sig',newline='') as f:
        writer=csv.writer(f);writer.writerow(['family','config','cost','path','trades','win_pct','pf','net_r','expectancy_r','family32_lower_expectancy','screen_pass'])
        for x in all_rows:
            rows=read(x['folder']/(x['label']+'_trades.json'))
            lock=read(x['folder']/'EXPERIMENT_LOCK.json');lock['family_size']=32
            m=r.summarize(rows,lock)
            x['final_metrics']=m
            writer.writerow([x['family'],x['name'],x['cost'],x.get('path','ADVERSE_FIRST'),m['n'],m['win_rate'],m['pf'],m['total_r'],m['expectancy'],m['expectancy_month_bootstrap_lower_family95'],m['pf_screen_pass']])
    # primary shares references with all_rows, so all final metrics now cover family32.
    assert not any(x['final_metrics']['pf_screen_pass'] for x in primary)
    selected=next(x for x in primary if x['family']=='H1_M5' and x['name']=='FRESH_T05')
    m=selected['final_metrics'];base=next(x['final_metrics'] for x in primary if x['family']=='H1_M5' and x['name']=='BASE_T05')
    costs=[next(x for x in all_rows if x['family']=='H1_M5' and x['name']=='FRESH_T05' and x['cost']==c)['final_metrics'] for c in ['LOW','BASE','STRESS']]
    trades=read(r.RUN/'FRESH_T05_BASE_ADVERSE_FIRST_trades.json')
    ordered=sorted(trades,key=lambda t:t['entry_time'])
    gaps=[(b['entry_time']-a['exit_time'])/86400 for a,b in zip(ordered,ordered[1:])]
    monthly=np.array([x['r'] for x in m['monthly']]);baseline_monthly=np.array([x['r'] for x in base['monthly']])
    rng=np.random.default_rng(20261101);draws=rng.integers(len(monthly),size=(20000,len(monthly)))
    delta=(monthly[draws]-baseline_monthly[draws]).mean(axis=1)
    stats=dict(family_size_new=32,earlier_searches='unknown total; NOT corrected by current family adjustment',
               selected=m,baseline=base,delta_r_per_calendar_month_ci95=np.quantile(delta,[.025,.975]).tolist(),
               longest_flat_gap_days=max(gaps),flat_gaps_over30days=sum(x>30 for x in gaps),
               zero_trade_calendar_months=sum(x['n']==0 for x in m['monthly']),
               no_gap_trades_diagnostic=r.metrics([x for x in trades if x['data_gaps']==0]))
    write_json(r.RUN/'STATISTICAL_AUDIT.json',stats)
    write_json(r.RUN/'EXPERIMENT_REGISTRY.json',dict(families=registry,total_hypotheses=32,total_scenarios=108,
               primary_path_rule='worst total-R declared intraminute path',economic_gate_passed=False))
    equity=read(r.RUN/'FRESH_EQUITY.json')['rows']
    eq=np.load(r.RUN/'fresh_equity_BASE.npz')['equity']
    props=dict(status='NOT_SUITABLE_AS_A_STANDALONE_PROP_STRATEGY',
               assumed_profiles=['FTMO CFD 2-Step','The5ers High Stakes'],verified_on_user_date='2026-11-01',
               exact_purchased_program='not specified',
               the5ers_inactivity_rule_days=30,observed_longest_flat_gap_days=max(gaps),
               intervals_with_no_position_or_entry_for_more_than30days=sum(x>30 for x in gaps),
               assumed_fixed_initial_risk_percent=[dict(risk_percent=risk,modeled_five_year_return_percent=m['total_r']*risk,
                    maximum_marked_return_percent=float(eq[:,1].max())*risk,
                    modeled_equity_dd_percent=next(x for x in equity if x['cost']=='BASE')['equity_dd_r']*risk)
                    for risk in [.25,.5,1.]],
               limitations=['illustrative fixed-initial-risk scaling only; not a challenge-pass simulation',
                            'broker lot step, margin, fees, news exclusions and day-clock alignment unverified',
                            'native indicator virtual R is GROSS before fees; historical report deducts assumed commission'])
    write_json(r.RUN/'PROP_REVIEW.json',props)
    sources=[
        dict(title='The Probability of Backtest Overfitting',url='https://www.davidhbailey.com/dhbpapers/backtest-prob.pdf',use='multiple-search bias; no profitable-strategy promise'),
        dict(title='Adam H. Grimes: Fundamental Trading Patterns',url='https://www.adamhgrimes.com/fundamental-trading-patterns/',use='pattern taxonomy only; rules and results here are our own hypotheses'),
        dict(title='FTMO Trading Objectives',url='https://ftmo.com/en/trading-objectives/',use='2-Step: 5% daily, 10% static total, targets 10%/5%, four trading days; other plans differ'),
        dict(title='The5ers High Stakes',url='https://www.the5ers.com/high-stakes/',use='30-day inactivity, profitable-day definition, news restriction'),
        dict(title='The5ers drawdown rule for High Stakes',url='https://the5ers.com/faqs/what-is-the-drawdown-rule-for-high-stakes/',use='daily 5% from greater closing balance/equity; 10% absolute loss; server midnight'),
    ]
    write_json(r.RUN/'SOURCES.json',dict(checked_user_date='2026-11-01',sources=sources))
    tests=(r.RUN/'tests.log').read_text(encoding='utf-8-sig')
    assert 'Ran 64 tests' in tests and '\nOK' in tests
    assert read(r.RUN/'NATIVE_PARITY.json')['passed']
    assert read(r.RUN/'PREFIX_CHECKS.json')['passed']
    assert read(r.RUN/'BASELINE_PARITY.json')['passed']
    for item in read(r.BASE/'ORIGINAL_SOURCE_MANIFEST.json')['files']:
        assert sha(Path(item['path']))==item['sha256']
    builds=read(r.RUN/'NATIVE_BUILD.json')['builds']
    for b in builds:
        assert b['diagnostics']=='0 errors, 0 warnings'
        assert sha(b['source'])==b['source_sha256'] and sha(b['ex5'])==b['ex5_sha256']
    checks=dict(python_tests=64,native_fixture_checks=6,native_trade_parity_rows=251,
                causal_prefix_checks=4,original_indicator_unchanged=True,
                baseline_replay_rows=read(r.RUN/'BASELINE_PARITY.json')['rows'],
                economic_gate_passed=False,prop_suitability_passed=False,
                user_goal_confirmed_positive_edge_achieved=False)
    write_json(r.RUN/'FINAL_VERIFICATION.json',dict(research_batch_complete=True,checks=checks,
               unsatisfied=['statistically defensible edge after search bias','useful opportunity frequency','prop-program operational requirements'],
               new_week=read(r.RUN/'FORWARD_WEEK.json')))
    # Static scientific plot, with the weak-sample result visible in its title.
    plt.rcParams.update({'font.family':'DejaVu Sans','font.size':10,'axes.spines.top':False,'axes.spines.right':False})
    fig,ax=plt.subplots(2,2,figsize=(14,8.8),layout='constrained')
    for cost,color in [('BASE','#2269c4'),('STRESS','#e08726')]:
        e=np.load(r.RUN/('fresh_equity_'+cost+'.npz'))['equity']
        dates=[datetime.fromtimestamp(t,timezone.utc) for t in e[:,0]]
        ax[0,0].plot(dates,e[:,1],label=cost,color=color,lw=1.3)
    ax[0,0].set(title='Fresh v0.2: marked equity after assumed fees',ylabel='Initial risk units (R)');ax[0,0].legend();ax[0,0].grid(alpha=.15)
    years=list(m['by_year']);profits=[m['by_year'][y]['total_r'] for y in years]
    ax[0,1].bar(years,profits,color=['#27876e' if v>=0 else '#c54b49' for v in profits])
    for i,y in enumerate(years):ax[0,1].text(i,profits[i]+(.13 if profits[i]>=0 else -.3),str(m['by_year'][y]['n'])+' trades',ha='center',fontsize=9)
    ax[0,1].axhline(0,color='#777',lw=.6);ax[0,1].set(title='Fresh: annual net R (2021 and 2026 are partial)',ylabel='R')
    ax[0,1].set_ylim(min(profits)-.8,max(profits)+.8)
    colors=['#2269c4','#9273b2','#e08726','#27876e']
    for (family,_),color in zip(folders,colors):
        group=[x for x in primary if x['family']==family]
        ax[1,0].scatter([x['final_metrics']['n'] for x in group],[x['final_metrics']['pf'] for x in group],label=family,s=28,alpha=.8,color=color)
    ax[1,0].axhline(1,color='#999',ls=':');ax[1,0].axhline(1.5,color='#c54b49',ls='--',label='PF 1.5 screen')
    ax[1,0].set(title='All 32 hypotheses, BASE fees',xlabel='Trades / five years',ylabel='Profit factor');ax[1,0].legend(fontsize=8)
    ax[1,0].set_ylim(.45,1.6)
    lower=m['expectancy_month_bootstrap_lower_family95'];ci=m['expectancy_month_bootstrap_95']
    ax[1,1].axvline(0,color='#c54b49',ls='--');ax[1,1].plot(ci,[1,1],color='#2269c4',lw=7,alpha=.45)
    ax[1,1].plot([lower,ci[1]],[0,0],color='#e08726',lw=7,alpha=.45)
    ax[1,1].scatter([m['expectancy']]*2,[1,0],color='#333',s=30)
    ax[1,1].set(yticks=[0,1],yticklabels=['Family32 lower bound*','Unadjusted 95% interval'],xlabel='Expected R per trade',title='Selection-adjusted lower bound crosses zero')
    ax[1,1].set_ylim(-.5,1.5)
    ax[1,1].text(.02,.04,'*One-sided corrected lower bound; upper end is descriptive.\nEarlier searches and real tick costs remain uncorrected.',transform=ax[1,1].transAxes,fontsize=8)
    fig.suptitle('XAUUSD 2021-10-25 to 2026-10-24 | Fresh v0.2 | EDGE NOT CONFIRMED',fontsize=16,weight='bold')
    fig.savefig(r.RUN/'RESEARCH_OVERVIEW.png',dpi=140);plt.close(fig)
    table=['| Nhánh | Lệnh | Win rate | PF | Tổng R |','|---|---:|---:|---:|---:|']
    for name in ['BASE_T05','BASE_T3','SLOPE_T05','NO_CHASE_T05','RISK6_T3','FRESH_T05','FRESH_T3']:
        a=next(x['final_metrics'] for x in primary if x['family']=='H1_M5' and x['name']==name)
        table.append(f"| {name} | {a['n']} | {a['win_rate']:.1f}% | {a['pf']:.3f} | {a['total_r']:+.2f} |")
    cost_table=['| Chi phí | Spread | Trượt giá mỗi lần khớp | Commission/lot khứ hồi giả định | Lệnh | Win | PF | R |','|---|---:|---:|---:|---:|---:|---:|---:|']
    for cost,a in zip(r.COSTS,costs):
        cost_table.append(f"| {cost['id']} | {cost['spread']:.2f} | {cost['slip']:.2f} | ${cost['commission_price']*100:.0f} | {a['n']} | {a['win_rate']:.1f}% | {a['pf']:.3f} | {a['total_r']:+.2f} |")
    annual=['| Năm | Lệnh | Win | R |','|---|---:|---:|---:|']
    for year,a in m['by_year'].items():annual.append(f"| {year}{' (một phần)' if year in ['2021','2026'] else ''} | {a['n']} | {a['win_rate']:.1f}% | {a['total_r']:+.2f} |")
    report=f'''# Nghiên cứu scalp XAUUSD — 01/11/2026

## Kết luận

Đã lấy lại lịch sử, tạo bản indicator nghiên cứu **Fresh v0.2**, chạy **32 cấu hình / 108 kịch bản chi phí và đường giá** trên cửa sổ 5 năm. **Chưa đạt mục tiêu edge dương đáng tin cậy và phù hợp thi quỹ.**

Nhánh tốt nhất cần theo dõi: **H1 → sweep/reclaim → M5 CHoCH, chỉ nhận vùng có test_count ≤1, TP0,5R**. Sau chi phí BASE: **84 lệnh, 63 thắng /21 thua, win75%, PF1,503, +10,03R**. Chi phí STRESS còn +8,99R/PF1,445. Đây là kết quả hồi cứu có lời theo mô hình, chưa chứng minh lợi thế tương lai.

![Kết quả nghiên cứu](RESEARCH_OVERVIEW.png)

## Lịch sử và yêu cầu đã khôi phục

Đã đọc chat **“Hoàn thành task nghiên cứu”** (`01a1731c-c947-7a93-824f-da6ac05f7dfc`) và phần liên quan của **“Phân tích indicator scalp vàng”** (`01a169d6-0832-74e3-a6b3-77fd845cfa69`). Yêu cầu gần nhất: ưu tiên vàng, tăng chất lượng entry/win rate, thử chốt 3 giá, tạm bỏ footprint, hướng tới FTMO và The5ers. Phần EA/LLM tự giao dịch là mục tiêu sau.

Baseline lần trước: T05 có 438 lệnh, win67,1%, PF1,071 trước commission ở spread0,20. Bản TS có PF1,160; tăng chi phí còn gần hòa vốn. Lần này dùng cùng detector đã có parity native, tính thêm commission giả định. Vì khác mô hình phí, không so trực tiếp PF1,503 mới với PF1,071 cũ như một phép thử chỉ thay bộ lọc.

## Dữ liệu và quy tắc thực thi

- Cửa sổ **25/10/2021 đến trước25/10/2026**, quote cuối23/10/2026. Dữ liệu gốc 2.043.723 M1, 409.219 M5, 34.214 H1, có 4.783 H1 warmup. Hash ở EXPERIMENT_LOCK và data_manifest của bản trước.
- Replay OHLC M1. Market BUY tại Ask+slippage, SELL tại Bid−slippage; thoát đúng Bid/Ask; kiểm tra cả phút entry. Nếu SL và TP cùng phút: SL trước. Gap stop không ép về−1R.
- SL theo cấu trúc, khoảng cách 2–20 giá, giữ tối đa6 giờ, một vị thế tại một thời điểm, giữ nguyên R ban đầu. Không dùng martingale hay tăng SL để làm đẹp win rate.
- Retest so riêng OLHC và OHLC; bảng chọn đường giá xấu hơn. M1 chạy detector độc lập với dữ liệu đã đóng, không dùng xác nhận M5 tương lai để chọn entry.
- Commission giả định $7/lot khứ hồi ở LOW/BASE, $10 ở STRESS; 100oz/lot, tương đương0,07/0,10 giá. Đây chưa phải bảng phí được xác minh của tài khoản mua. Swap chưa tính; Fresh không có lệnh vượt ngày feed trong mẫu này.
- Cửa sổ cũ đã được nghiên cứu nhiều lần. Kết quả và các đoạn kiểm định theo thời gian đều là **hồi cứu**, không gọi là tập ngoài mẫu nguyên vẹn.

## Kết quả chính ở chi phí BASE

{chr(10).join(table)}

Các nhóm mở rộng đều thất bại ở định nghĩa đã khóa: H1+M1 tăng số cơ hội nhưng BASE_T05 chỉ PF0,765; entry trực tiếp reclaim BASE_T05 PF0,708; breakout–pullback T05 PF0,673. Không suy rộng rằng mọi chiến lược thuộc các họ này đều vô hiệu.

TP cố định3 giá đã được backtest thực sự; không lấy win rate TP0,5R gán cho TP3. Fresh TP3 chỉ PF1,357; BASE TP3 gần hòa vốn PF1,008.

## Fresh v0.2: chi phí và độ ổn định

{chr(10).join(cost_table)}

{chr(10).join(annual)}

- Tần suất **1,4 lệnh/tháng**; có **20 tháng lịch không có lệnh**; giữ trung bình84 phút. Vẫn ít và lâu so với mong muốn một hệ scalp nhiều cơ hội.
- Win rate75% có Wilson95% khoảng **64,8–83,0%**, chỉ mang tính mô tả vì lệnh có thể phụ thuộc.
- Expectancy BASE +{m['expectancy']:.3f}R/lệnh. Bootstrap theo61 tháng lịch, gồm cả tháng0, khoảng95% không điều chỉnh: [{m['expectancy_month_bootstrap_95'][0]:.4f}, {m['expectancy_month_bootstrap_95'][1]:.4f}]. Sau điều chỉnh32 giả thuyết mới, cận dưới là **{m['expectancy_month_bootstrap_lower_family95']:.4f}R**, dưới0. Các lần tối ưu cũ chưa được điều chỉnh đầy đủ.
- Chênh lệch R/tháng so với baseline cùng phí có khoảng95% **[{stats['delta_r_per_calendar_month_ci95'][0]:.3f}, {stats['delta_r_per_calendar_month_ci95'][1]:.3f}]**; không đủ cơ sở khẳng định cải tiến chắc chắn.
- Equity drawdown theo mô hình BASE **3,73R**, STRESS **3,88R**; khác closed-trade DD3,04R. R không phải phần trăm tài khoản.
- Một lệnh có2 khoảng thiếu phút; không phân biệt được thiếu giá với phút không cập nhật chỉ từ rates. Kết quả loại lệnh có gap được lưu riêng, không dùng thay kết quả chính.

Ngưỡng screening của lượt này là PF≥1,5, kỳ vọng dương dưới stress, ≥200 lệnh, các năm đầy đủ dương và cận dưới bootstrap có điều chỉnh>0. Đây là tiêu chí nghiên cứu công bố trước, chưa phải cấu hình rủi ro người dùng chấp thuận. **Không cấu hình nào đạt đủ.**

## Kiểm tra theo thời gian và dữ liệu mới

Chọn cấu hình từng năm chỉ từ các năm trước, purge6 giờ; giữ tiền mặt khi không có cấu hình train dương đủ60 lệnh; thực thi lịch chọn liên tục một vị thế. Với nhóm H1–M5, giai đoạn2023–2026: BASE **122 lệnh, PF0,994, −0,32R**; STRESS **115 lệnh, PF0,855, −7,86R**. Chọn phương án tốt ở quá khứ chưa tạo được hiệu quả ổn định ở đoạn tiếp theo.

Đã lấy mới tuần26–30/10/2026 từ MT5 và khóa lựa chọn Fresh trước khi đánh giá P&L. Có10 ứng viên raw, **0 lệnh Fresh đủ điều kiện** ở cả3 mức phí. Không có thêm bằng chứng về win rate hay expectancy. Ghép tuần mới không làm thay đổi bất cứ ứng viên cũ nào.

## FTMO / The5ers

Chưa xác định gói cụ thể đã mua. Hồ sơ tham chiếu là FTMO CFD2-Step và The5ers High Stakes; không áp quy định này cho mọi chương trình.

[FTMO](https://ftmo.com/en/trading-objectives/) công bố cho2-Step: daily loss5%, total loss10% cố định, mục tiêu10%/5%, tối thiểu4 ngày giao dịch; reset ngày theo CE(S)T. [The5ers drawdown](https://the5ers.com/faqs/what-is-the-drawdown-rule-for-high-stakes/) dùng daily5% theo giá trị lớn hơn balance/equity lúc reset server và maxloss10% tuyệt đối.

[High Stakes](https://www.the5ers.com/high-stakes/) còn yêu cầu hoạt động trong30 ngày, định nghĩa ngày lời tối thiểu0,5% và hạn chế thực hiện giao dịch trong khoảng2 phút quanh tin quan trọng. Fresh có **{sum(x>30 for x in gaps)} khoảng trống hơn30 ngày**, dài nhất **{max(gaps):.1f} ngày** khi không có vị thế. Hệ này dùng riêng sẽ không đáp ứng yêu cầu hoạt động đó. Chưa có bộ lọc tin lịch sử đã được xác minh.

Minh họa cố định0,5% vốn ban đầu cho1R: +10,03R tương đương khoảng **+5,02% trong cả5 năm**, đỉnh marked khoảng+6,09%, chưa tới mục tiêu10% bước1. Đây là phép quy đổi để thấy tốc độ, không phải đề xuất tăng risk. Chưa mô phỏng đầy đủ thi quỹ do chưa xác minh giờ feed, lot step, phí, margin và lịch tin.

## Bản cải tiến đã tạo

- `duc_tri_can_ho_tro_scalp_v2_fresh.mq5/.ex5`: bản riêng, default TP0,5R, chỉ vùng có≤1 lần test; dùng gate trước bước chọn ưu tiên để không bỏ qua vùng hợp lệ đứng sau.
- Có namespace persistence riêng; mặc định quan sát; không có broker order. Virtual R hiển thị **gross trước phí**, không đồng nhất với bảng net phía trên.
- Hai binary indicator và native oracle:0 errors/0 warnings. 64 kiểm thử Python đạt;6 native fixture checks;251 dòng replay native/Python khớp giá, thời gian, SL, gross và netR ở3 mức phí;4 kiểm tra prefix đạt. Baseline439 dòng khớp bản trước. Indicator gốc và binary gốc giữ nguyên checksum.
- Chưa chạy QA canvas tương tác mới cho Fresh; chart live dùng adapter cũ đã kiểm chứng với thay đổi gate/namespace/banner. Đây là giới hạn UI, không thay cho bằng chứng kinh tế.

## Phần còn lại để đạt mục tiêu thật

Lượt này hoàn thành triển khai và thí nghiệm; **mục tiêu xác nhận edge chưa đạt**. Khóa Fresh để theo dõi dữ liệu mới; cần dữ liệu quote/tick đủ coverage và chi phí tài khoản thật. Dùng một nguồn level/setup khác có giả thuyết rõ ràng để bổ sung cơ hội, rồi khóa quy tắc trước phần dữ liệu xác nhận mới. Các kết quả thất bại được giữ để lần sau không thử lại vô thức cùng tham số.

Không coi việc tiếp tục chỉnh trên cùng5 năm là cách bảo đảm tìm ra edge. Nghiên cứu về [backtest overfitting](https://www.davidhbailey.com/dhbpapers/backtest-prob.pdf) là căn cứ cho việc công bố cả họ giả thuyết và đánh dấu dữ liệu đã xem. Nhánh breakout/reclaim là giả thuyết tự định nghĩa, tham khảo phân loại pattern của [Adam Grimes](https://www.adamhgrimes.com/fundamental-trading-patterns/), không gán thành tích của tác giả cho kết quả này.

## Tái lập và file

Trong workspace hiện tại, dùng Python3.9 với NumPy/Numba/Matplotlib đã cài:

```powershell
python scripts/research_scalp_v2.py
python scripts/research_scalp_m1_v2.py
python scripts/research_scalp_reclaim_v2.py
python scripts/research_scalp_breakout_v2.py
python -m unittest discover -s tests -p "test*scalp*.py" -v
python scripts/build_scalp_fresh_v2.py
python scripts/audit_scalp_v2.py
python scripts/finalize_scalp_v2.py
```

Không chạy lại bước tải dữ liệu vào snapshot cũ. `rates.npz` gốc không đóng trong ZIP vì kích thước lớn; giữ tại `../20261025_v1/rates.npz`, hash được ghi trong lock. File tuần mới đã lưu riêng. Các report/test chỉ đọc thị trường, không đặt lệnh.

`ALL_EXPERIMENTS.csv` chứa mọi kết quả; `EXPERIMENT_REGISTRY.json` dẫn đến4 lock; `STATISTICAL_AUDIT.json`, `NATIVE_PARITY.json`, `PREFIX_CHECKS.json`, `PROP_REVIEW.json`, `FINAL_VERIFICATION.json` giữ bằng chứng. Gói `scalp_research_v2_20261101.zip` chứa code và các kết quả mới, có CHECKSUMS; không phải gói đã được phê duyệt để thi quỹ.
'''
    automation_file=r.RUN/'CONTINUING_RESEARCH.json'
    if automation_file.exists():
        automation=read(automation_file)
        report+='\n## Nghiên cứu tiếp nối đã bật\n\nHeartbeat **'+automation['name']+'** chạy trong chat này mỗi **2 giờ**; chỉ báo khi có tiến triển đáng kể, đạt đủ tiêu chí hoặc cần người dùng. Tiếp tục từ nhật ký, giữ các kết quả thất bại và khóa giả thuyết mới trước khi backtest. Không có cam kết rằng tối ưu sẽ tạo được edge. Cần máy tính bật và Codex đang chạy để truy cập thư mục local, theo [tài liệu chính thức](https://learn.chatgpt.com/docs/automations?surface=app).\n'
    (r.RUN/'FINAL_RESEARCH_REPORT.md').write_text(report,encoding='utf-8')
    history='''# Điểm tiếp tục sau nghiên cứu 01/11/2026

Đã khôi phục chat “Hoàn thành task nghiên cứu” và “Phân tích indicator scalp vàng”. Người dùng hiện cho phép tự nghiên cứu, code bản cải tiến và backtest5 năm; ưu tiên XAUUSD, chất lượng entry/win rate, từng hỏi TP3 giá, bỏ footprint, nhắm FTMO/The5ers. Không đặt lệnh hoặc gửi tin nhắn ngoài.

Đã thử32 cấu hình/108 scenario; giữ toàn bộ thất bại. Best retrospective: FRESH_T05 có84 lệnh/75%/PF1.503/+10.03R ở spread.30/slip.01/$7commission. Stress+8.99R/PF1.445. Mẫu ít, family32 bootstrap lower<0, năm2026 âm. Không đạt edge đủ chắc hoặc đủ tần suất; không gọi thành công.

Fresh indicator riêng đã build0errors/0warnings, native/Python251row parity,64tests,4prefixchecks. NewweekOct26–30:10rawcandidate,0freshtrade. Tuần này đã xem, không được gọi chưa từng sử dụng ở lần sau.

The5ers HighStakes có30-day inactivity; Fresh có20gap>30day,max124.7day. Không phù hợp dùng riêng. Chưa xác minh clock/fees/news/lot constraints của gói người dùng.

Đọc FINAL_RESEARCH_REPORT.md và EXPERIMENT_REGISTRY.json trước khi tiếp tục. Không tự mở rộng TP3 thành mục tiêu bắt buộc duy nhất hoặc bỏ mục tiêu win rate để lấy R. Không chạy lại tối ưu M1/reclaim/breakout đã thất bại mà không có giả thuyết mới và dữ liệu xác nhận mới.
'''
    if automation_file.exists():
        history+='\n## Nghiên cứu tiếp nối\n\nHeartbeat đang ACTIVE trong chat này mỗi 2 giờ, id '+automation['automation_id']+'. Chỉ báo khi có tiến triển đáng kể hoặc cần người dùng; cần máy và Codex đang chạy. Đọc lại tổng số phép thử và không gọi tuần đã xem là dữ liệu ngoài mẫu mới.\n'
    (r.RUN/'CONTINUATION.md').write_text(history,encoding='utf-8')
    overview=r.ROOT/'thông tin nghiên cứu/README.md';text=overview.read_text(encoding='utf-8')
    marker='## Cập nhật 01/11/2026 — nghiên cứu v0.2'
    if marker not in text:
        first,rest=text.split('\n',1)
        update=f'''\n\n{marker}

Đã triển khai Fresh v0.2 và kiểm định32 cấu hình/108 kịch bản trên5 năm. Fresh có84 lệnh,75% thắng,PF1,503 sau phí giả định; bằng chứng thống kê và tần suất chưa đạt, không phù hợp dùng riêng cho High Stakes30-day inactivity. Mục tiêu edge đủ chắc vẫn chưa hoàn thành.

[Báo cáo mới](<../reports/can_ho_tro_scalp/20261101_v2/FINAL_RESEARCH_REPORT.md>) · [Điểm tiếp tục](<../reports/can_ho_tro_scalp/20261101_v2/CONTINUATION.md>)

Phần dưới là hồ sơ lịch sử25/10; trạng thái triển khai hiện hành nằm trong báo cáo mới.
'''
        overview.write_text(first+update+rest,encoding='utf-8')
    included=[]
    for _,folder in folders:
        included.extend(p for p in folder.iterdir() if p.is_file() and p.suffix.lower() not in {'.zip'} and p.name!='PACKAGE_MANIFEST.json')
    new_scripts=['research_scalp_v2','research_scalp_m1_v2','research_scalp_reclaim_v2','research_scalp_breakout_v2','audit_scalp_v2','build_scalp_fresh_v2','finalize_scalp_v2']
    dependencies=['can_ho_tro_scalp_core','can_ho_tro_scalp_plan','prepare_can_ho_tro_scalp','replay_can_ho_tro_scalp','build_can_ho_tro_scalp','generate_can_ho_tro_oracle']
    included.extend(r.ROOT/'scripts'/(name+'.py') for name in new_scripts+dependencies)
    included.extend((r.ROOT/'Include').glob('CanHoTroScalp*.mqh'))
    included.extend([r.ROOT/'tests/test_research_scalp_v2.py',r.ROOT/'tests/test_can_ho_tro_scalp.py',r.ROOT/'tests/mql5/TestScalpFreshV2.mq5',r.ROOT/'tests/mql5/TestScalpFreshV2.ex5'])
    included.extend([r.ROOT/'duc_tri_can_ho_tro_scalp_v2_fresh.mq5',r.ROOT/'duc_tri_can_ho_tro_scalp_v2_fresh.ex5',r.ROOT/'duc_tri_can_ho_tro_scalp_lab.mq5',r.ROOT/'tests/mql5/TestCanHoTroScalpReplay.mq5'])
    archive=r.RUN/'scalp_research_v2_20261101.zip'
    with zipfile.ZipFile(archive,'w',zipfile.ZIP_DEFLATED) as z:
        for p in sorted(set(included)):z.write(p,p.relative_to(r.ROOT).as_posix())
        z.writestr('CHECKSUMS.json',json.dumps({p.relative_to(r.ROOT).as_posix():sha(p) for p in sorted(set(included))},indent=2))
    with zipfile.ZipFile(archive) as z:assert z.testzip() is None
    write_json(r.RUN/'PACKAGE_MANIFEST.json',dict(path=str(archive),sha256=sha(archive),files=len(set(included)),zip_integrity_passed=True,
               full_data_snapshot_included=False,economic_gate_passed=False))
    print(json.dumps(dict(hypotheses=32,scenarios=108,tests=64,economic_gate_passed=False,archive_bytes=archive.stat().st_size,report=str(r.RUN/'FINAL_RESEARCH_REPORT.md')),ensure_ascii=True))


if __name__=='__main__':main()
