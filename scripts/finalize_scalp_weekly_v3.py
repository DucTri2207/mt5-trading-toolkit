# -*- coding: utf-8 -*-
"""Publish an honest checkpoint of all v3 attempts, including failed ones."""
import csv
import json
from pathlib import Path
import zipfile

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np

from prepare_can_ho_tro_scalp import sha, write_json
import research_scalp_weekly_v3 as w
import research_scalp_microzones_v3 as m


def read(path):return json.loads(path.read_text(encoding='utf-8'))


def fmt(value,digits=2):return '—' if value is None else f'{value:.{digits}f}'


def main():
    all_rows=[]
    for family,run in [('WEEKLY',w.RUN),('MICROZONES',m.RUN)]:
        verification=read(run/'VERIFICATION.json')
        assert all(verification['fresh_unchanged'].values())
        assert read(run/'PREFIX_CHECKS.json')['passed']
        for row in read(run/'summary.json')['rows']:
            all_rows.append(dict(family=family,run=run,**row))
    assert len(all_rows)==78
    flat=[]
    for row in all_rows:
        metric=row['metrics'];f=metric['frequency']
        flat.append(dict(family=row['family'],name=row['name'],cost=row['cost'],n=metric['n'],
                         win_rate=metric['win_rate'],pf=metric['pf'],net_r=metric['total_r'],
                         expectancy=metric['expectancy'],trades_per_week=f['mean'],median_week=f['median'],
                         min_week=f['min'],max_week=f['max'],empty_weeks=len(f['empty_weeks']),
                         weeks_5_to_10=f['weeks_with_5_to_10'],weeks=f['weeks'],
                         adjusted_lower=metric['expectancy_month_bootstrap_lower_family95'],
                         frequency_pass=metric['frequency_pass'],economic_screen_pass=metric['economic_screen_pass']))
    with (w.RUN/'ALL_V3_EXPERIMENTS.csv').open('w',newline='',encoding='utf-8-sig') as handle:
        writer=csv.DictWriter(handle,fieldnames=list(flat[0]));writer.writeheader();writer.writerows(flat)
    with (w.RUN/'ALL_V3_WEEKS.csv').open('w',newline='',encoding='utf-8-sig') as handle:
        fields=['family','name','cost','week_start','market_days','n','closed','wins','r']
        writer=csv.DictWriter(handle,fieldnames=fields);writer.writeheader()
        for row in all_rows:
            for week in row['metrics']['frequency']['weekly']:
                writer.writerow(dict(family=row['family'],name=row['name'],cost=row['cost'],**week))
    registry=dict(previous=dict(hypotheses=32,scenarios=108,path='reports/can_ho_tro_scalp/20261101_v2/EXPERIMENT_REGISTRY.json',
                                sha256=sha(w.ROOT/'reports/can_ho_tro_scalp/20261101_v2/EXPERIMENT_REGISTRY.json')),
                  new=dict(hypotheses=26,scenarios=78,weekly_hypotheses=18,microzone_hypotheses=8),
                  cumulative=dict(hypotheses=58,scenarios=186),
                  diagnostic_scenarios=dict(zero_friction=1,last_week=3),
                  note='Earlier pre-v2 choices are additional uncorrected search. Cost/path scenarios are not independent hypotheses.',
                  new_locks={str(run.relative_to(w.ROOT)):sha(run/'EXPERIMENT_LOCK.json') for run in (w.RUN,m.RUN)},
                  tests=dict(passed=73,command="python -m unittest discover -s tests -p 'test*scalp*.py' -v"),
                  qualified=[],goal_status='active; no qualified edge; Fresh preserved')
    write_json(w.RUN/'CUMULATIVE_REGISTRY.json',registry)
    def metric(name,cost='BASE'):return next(row['metrics'] for row in all_rows if row['name']==name and row['cost']==cost)
    fresh_trades=read(w.ROOT/'reports/can_ho_tro_scalp/20261101_v2/FRESH_T05_BASE_ADVERSE_FIRST_trades.json')
    data=np.load(w.BASE/'rates.npz');market=w.bars_matrix(data['m1'])
    fresh=w.metrics(fresh_trades);fresh['frequency']=w.weekly(fresh_trades,market)
    comparison=[('Fresh v0.2',fresh),('COMBO R0.8',metric('COMBO_R80')),
                ('Micro R0.8',metric('MICRO_COMBO_R80')),('Day R1.0',metric('DAY_FAILURE_R100'))]
    plt.rcParams.update({'font.family':'DejaVu Sans','font.size':10})
    fig,axes=plt.subplots(1,3,figsize=(13,4.4),gridspec_kw={'wspace':.48})
    labels=[name for name,_ in comparison];ys=np.arange(len(labels))
    specs=[('Mean entries / market-data week',[x['frequency']['mean'] for _,x in comparison],(5,10),None),
           ('Net winning trades (%)',[x['win_rate'] for _,x in comparison],(55,60),None),
           ('Profit factor after BASE costs',[x['pf'] for _,x in comparison],None,1.)]
    colors=['#0B7285','#D9480F','#C92A2A','#9775FA']
    for ax,(title,values,band,line) in zip(axes,specs):
        if band:ax.axvspan(*band,color='#D3F9D8',zorder=0)
        if line:ax.axvline(line,color='#222222',linestyle='--',linewidth=1)
        ax.barh(ys,values,color=colors,height=.55,zorder=2)
        ax.set_yticks(ys,labels);ax.invert_yaxis();ax.set_title(title,fontsize=10,pad=12)
        ax.spines[['top','right']].set_visible(False);ax.grid(axis='x',alpha=.15,zorder=0)
        upper=max(max(values)*1.2,band[1]*1.1 if band else 1.8)
        ax.set_xlim(0,upper)
        for y,value in zip(ys,values):ax.text(value+upper*.02,y,f'{value:.2f}',va='center',fontsize=9,
                                             bbox=dict(facecolor='white',edgecolor='none',pad=.3))
    fig.suptitle('XAUUSD: frequency and economic quality must both pass',fontsize=13,y=1.01)
    fig.text(.5,-.03,'2021-10-25 to 2026-10-25 | Retrospective M1 replay | Assumed BASE costs | No verified edge',ha='center',fontsize=9)
    fig.savefig(w.RUN/'WEEKLY_RESEARCH_OVERVIEW.png',dpi=180,bbox_inches='tight');plt.close(fig)
    last=read(w.RUN/'LAST_WEEK.json')
    week_base=next(row for row in last['rows'] if row['cost']=='BASE')['metrics']
    combo=metric('COMBO_R80');micro=metric('MICRO_COMBO_R80');freq=combo['frequency']
    md=f'''# Kết quả nghiên cứu bản scalp 5–10 lệnh/tuần

## Trạng thái

**Chưa tìm được bản vừa đủ tần suất, vừa đạt win rate và edge dương sau phí.** Mục tiêu nghiên cứu còn đang mở. Fresh v0.2, binary và hai include được giữ nguyên theo SHA256.

Người dùng chọn 5–10 lệnh/tuần, kỳ vọng win rate khoảng 55–60% và tuần nào cũng có lệnh. Bản kết hợp đã có lệnh trong mọi tuần lịch sử, nhưng lỗ nên bị loại. Không dùng tần suất hoặc win rate riêng lẻ để tuyên bố thành công.

## Tuần trước: 26–30/10/2026

| Bản | Lệnh | Thắng / thua | P&L sau phí |
|---|---:|---:|---:|
| Fresh v0.2 | 0 | 0 / 0 | 0R |
| COMBO_R80 thử tăng tần suất | {week_base['n']} | {week_base['wins']} / {week_base['losses']} | {week_base['total_r']:+.2f}R |

Bản thử mới **thua trong tuần này**. Đây là backtest M1 trên tuần đã được xem, không phải giao dịch thật hay một kiểm định ngoài mẫu còn nguyên vẹn. 1R là khoảng rủi ro giá lúc khớp từng lệnh; không chuyển thành USD khi chưa có vốn/khối lượng.

## Backtest 5 năm

Từ 25/10/2021 đến trước 25/10/2026; có {freq['weeks']} tuần có dữ liệu. Chi phí BASE: spread 0,30 giá; slippage 0,01 mỗi khớp bất lợi; commission khứ hồi tương đương 0,07 giá. STRESS: 0,45 / 0,05 / 0,10. Các mức này là giả định nghiên cứu.

| Bản | Lệnh | Win rate | PF sau phí | Tổng R | TB lệnh/tuần | Tuần 0 lệnh |
|---|---:|---:|---:|---:|---:|---:|
'''
    for name,x in comparison:
        f=x['frequency'];md+=f"| {name} | {x['n']} | {x['win_rate']:.2f}% | {x['pf']:.3f} | {x['total_r']:+.2f} | {f['mean']:.2f} | {len(f['empty_weeks'])} |\n"
    md+=f'''
Fresh vẫn có mẫu nhỏ và lịch sử lựa chọn tham số; kết quả dương hồi cứu của nó chưa đủ xác nhận edge.

### Tần suất của COMBO_R80

- Trung bình {freq['mean']:.2f}; trung vị {freq['median']:.0f}; ít nhất {freq['min']}, nhiều nhất {freq['max']} lệnh/tuần.
- {freq['weeks_with_5_to_10']}/{freq['weeks']} tuần có 5–10 lệnh; {freq['weeks_below_5']} tuần dưới 5 lệnh; không có tuần 0 lệnh.
- Việc trung bình đạt mục tiêu **không đồng nghĩa mọi tuần đều có 5–10 lệnh**. Giới hạn tối đa 2 lệnh/ngày và 10 lệnh/tuần không ép mở lệnh khi thiếu setup.
- Stress: {metric('COMBO_R80','STRESS')['total_r']:+.2f}R, PF {metric('COMBO_R80','STRESS')['pf']:.3f}; không vượt kiểm tra kinh tế.

### Kết quả từng năm của COMBO_R80 (BASE)

| Năm | Lệnh | Win rate | Tổng R |
|---|---:|---:|---:|
'''
    for year,x in combo['by_year'].items():md+=f"| {year}{' (không trọn năm)' if year in ('2021','2026') else ''} | {x['n']} | {fmt(x['win_rate'])}% | {x['total_r']:+.2f} |\n"
    md+=f'''
## Những gì đã thử trong lượt này

1. **18 cấu hình / 54 kịch bản chi phí:** failure test tại pivot M15 xác nhận sau hai nến phải hoặc đỉnh/đáy ngày hoàn tất; pullback EMA20/ADX14 M5/M15; ba TP 0,8R/1R/1,2R; hai cách kết hợp với Fresh. Tất cả giữ quy tắc nhân quả và có giới hạn vị thế.
2. **8 cấu hình / 24 kịch bản chi phí:** chuyển vùng impulse/base của Fresh sang M15/M5, trigger M5/M1; giữ freshness ≤1 lần test, mốc phải có trước sweep, H1 EMA50, CHoCH và thứ tự ưu tiên gốc; TP 0,8R/1R.
3. Giữ **toàn bộ thất bại**. Cộng nghiên cứu trước: ít nhất **58 cấu hình / 186 kịch bản chính**, thêm 1 chẩn đoán bỏ phí và 3 kịch bản tuần trước. Các lượt tìm kiếm cũ hơn vẫn tạo thêm thiên lệch chọn mẫu.

Kiểm tra bỏ toàn bộ phí của COMBO_R80 vẫn cho PF {read(w.RUN/'ZERO_FRICTION_CONTROL.json')['metrics']['pf']:.3f}, {read(w.RUN/'ZERO_FRICTION_CONTROL.json')['metrics']['total_r']:+.2f}R. Vì vậy không có bằng chứng chỉ cần giảm phí là cứu được bộ quy tắc này.

Mẫu đỉnh/đáy ngày có một số P&L dương hồi cứu nhưng chỉ 31 lệnh trong 5 năm, 234 tuần trống; không được chọn như một edge đáp ứng yêu cầu. Bản chuyển timeframe của Fresh vẫn âm và thiếu tần suất.

## Kiểm chứng

- 73 kiểm tra Python qua, gồm 9 kiểm tra mới về tiền, phí, mốc biết trước, census tuần và giới hạn số lệnh.
- Detector cũ sau khi thêm tham số timeframe mặc định vẫn khớp **chính xác 5.882 dòng C0** với dữ liệu đã kiểm định.
- 3 prefix thật cho bộ weekly và 6 prefix thật cho bộ microzone khớp hoàn toàn; bổ sung dữ liệu tương lai không sửa tín hiệu trước mốc cắt.
- Hash của Fresh source/binary/includes không đổi. Không đặt lệnh, đổi tài khoản, gửi Telegram hoặc cài bản mới vào terminal chính.
- Không có cấu hình mới vượt đủ các tiêu chí. Bộ chọn theo năm trước không có ứng viên đủ điều kiện; trạng thái CASH ở bài kiểm tra đó cũng không đáp ứng mục tiêu tuần nào có lệnh.

## Giới hạn và bước tiếp tục

Dữ liệu 2021–2026 và tuần 26–30/10 đã được xem. Prefix checks chứng minh không dùng tương lai trong việc tạo tín hiệu; chúng không biến lịch sử này thành ngoài mẫu chưa sử dụng. Bootstrap điều chỉnh không loại bỏ toàn bộ thiên lệch từ các nghiên cứu trước. M1 OHLC không tái hiện tick, spread động, độ trễ hoặc slippage theo tin.

Chưa có native MQL cho các timeframe mới vì không có ứng viên kinh tế đạt chuẩn để chuyển giao. Chưa xác minh đúng phí broker, clock/DST, lịch tin, khối lượng và gói FTMO/The5ers. Không tuyên bố lợi nhuận tương lai hoặc khả năng qua quỹ.

Lượt tiếp theo phải có giả thuyết có lý do mới, khóa độc lập và cộng số phép thử; tránh tối ưu tiếp các ngưỡng vừa thất bại để làm đẹp lịch sử. Ưu tiên kiểm tra cơ chế vào lệnh/chi phí và cấu trúc thị trường có thể giải thích được, rồi mới tăng số biến. Khi có ứng viên đáng tin, cần dữ liệu xác nhận mới và parity native trước khi sử dụng.

## Nguồn tạo giả thuyết

- [Adam Grimes — Fundamental Trading Patterns](https://www.adamhgrimes.com/fundamental-trading-patterns/): mô tả pullback và failure test. Các quy tắc số trong thí nghiệm là cách chuyển thể của nghiên cứu này.
- [Phỏng vấn Linda Raschke, Active Trader tháng 3/2004](https://lindaraschke.net/wp-content/uploads/2026/03/raschke_pt2_0304.pdf): EMA20 và ADX14 cho pullback có động lượng. Đây không phải bộ thông số XAUUSD được tác giả chứng nhận.

## File bàn giao

- `ALL_V3_EXPERIMENTS.csv`: 78 kết quả cấu hình/chi phí.
- `ALL_V3_WEEKS.csv`: mọi tuần có dữ liệu của cả 78 kịch bản, gồm tuần trống và ngày nghỉ/tuần ngắn qua số ngày có dữ liệu; không tự điền nến thiếu.
- `LAST_WEEK.json`: từng lệnh của tuần 26–30/10 ở ba mức phí.
- `CUMULATIVE_REGISTRY.json`: số phép thử cộng dồn.
- Lock, detector, từng lệnh, prefix và verification ở hai thư mục weekly_v3/microzones_v3.
- Các script `research_scalp_weekly_v3.py`, `research_scalp_microzones_v3.py`, `audit_scalp_weekly_v3.py`, `finalize_scalp_weekly_v3.py` cho phép tái tạo nghiên cứu; dữ liệu nguồn giữ ở thư mục v1.

Gói ZIP gồm mã và kết quả, không kèm các file rates.npz lịch sử lớn. Chạy lại backtest dùng dữ liệu gốc trong workspace; chạy toàn bộ 73 tests còn dùng fixture ở `reports/scalp_structure_lab/20261025_pilot_v1`.
'''
    (w.RUN/'RESEARCH_CHECKPOINT.md').write_text(md,encoding='utf-8')
    continuation=(w.RUN/'CONTINUATION.md').read_text(encoding='utf-8')
    start=continuation.index('## Trạng thái')
    stop=continuation.index('## Khi tiếp tục')
    continuation=continuation[:start]+f'''## Trạng thái đã hoàn tất lượt thử

Đọc `RESEARCH_CHECKPOINT.md`, `CUMULATIVE_REGISTRY.json` và `../20261101_microzones_v3/summary.json`. Đã chạy 26 cấu hình mới / 78 kịch bản; tổng ít nhất 58 / 186. Mục tiêu **chưa đạt**, giữ trạng thái active.

- COMBO_R80: 1.717 lệnh, 47,47% thắng, PF 0,676, −290,44R BASE; 6,58 lệnh/tuần, 0 tuần trống; {freq['weeks_with_5_to_10']}/{freq['weeks']} tuần có 5–10 lệnh.
- MICRO_COMBO_R80: 919 lệnh, PF 0,769, −101,64R; 3,52 lệnh/tuần, 13 tuần trống.
- Tuần 26–30/10: Fresh 0 lệnh; COMBO_R80 có 7 lệnh, 2 thắng / 5 thua, −3,53R BASE. Tuần đã xem, không gọi là holdout nguyên vẹn.
- 73 tests, 3+6 prefix thật và 5.882 dòng parity cũ qua. Fresh giữ nguyên hash. Không có native mới để cài.
- Bỏ toàn bộ phí, COMBO_R80 vẫn âm −54,04R / PF 0,929; không chỉ là vấn đề commission.

''' + continuation[stop:]
    (w.RUN/'CONTINUATION.md').write_text(continuation,encoding='utf-8')
    write_json(w.RUN/'CHECKPOINT_MANIFEST.json',dict(scripts={p:sha(w.ROOT/p) for p in
        ['scripts/research_scalp_weekly_v3.py','scripts/research_scalp_microzones_v3.py',
         'scripts/audit_scalp_weekly_v3.py','scripts/finalize_scalp_weekly_v3.py',
         'scripts/can_ho_tro_scalp_core.py','scripts/can_ho_tro_scalp_plan.py']},
         input_data_sha256=sha(w.BASE/'rates.npz'),
         old_detector_sha256=sha(w.BASE/'detector_python.npz'),
         cumulative_registry_sha256=sha(w.RUN/'CUMULATIVE_REGISTRY.json')))
    bundle=w.RUN/'scalp_weekly_v3_checkpoint.zip'
    with zipfile.ZipFile(bundle,'w',zipfile.ZIP_DEFLATED,compresslevel=6) as archive:
        for run in (w.RUN,m.RUN):
            for path in sorted(run.rglob('*')):
                if path.is_file() and path!=bundle:archive.write(path,path.relative_to(w.ROOT))
        for p in ['scripts/research_scalp_weekly_v3.py','scripts/research_scalp_microzones_v3.py',
                  'scripts/audit_scalp_weekly_v3.py','scripts/finalize_scalp_weekly_v3.py',
                  'scripts/can_ho_tro_scalp_core.py','scripts/can_ho_tro_scalp_plan.py',
                  'scripts/research_scalp_v2.py','scripts/replay_can_ho_tro_scalp.py',
                  'scripts/prepare_can_ho_tro_scalp.py','scripts/replay_scalp_structure_lab.py',
                  'tests/test_research_scalp_weekly_v3.py','tests/test_can_ho_tro_scalp.py',
                  'tests/test_research_scalp_v2.py','tests/test_scalp_structure_lab.py']+w.FRESH_PATHS:
            archive.write(w.ROOT/p,p)
    print('CHECKPOINT',len(flat),'rows; qualified0; zip_bytes',bundle.stat().st_size,flush=True)
    print('COMBO_FREQUENCY',freq['mean'],freq['median'],freq['min'],freq['max'],freq['weeks_with_5_to_10'],freq['weeks'],flush=True)


if __name__=='__main__':main()
