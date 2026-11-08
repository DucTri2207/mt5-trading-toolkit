# -*- coding: utf-8 -*-
"""Checkpoint both v4 investigations without promoting a losing strategy."""
import csv
import json
import zipfile

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np

from prepare_can_ho_tro_scalp import sha,write_json
import research_scalp_limit_v4 as limit
import research_scalp_range_v4 as range_lab


def read(path):return json.loads(path.read_text(encoding='utf-8'))


def main():
    root=limit.w.ROOT;run=limit.RUN;old=read(limit.w.RUN/'CUMULATIVE_REGISTRY.json')
    assert old['cumulative']==dict(hypotheses=58,scenarios=186)
    rows=[]
    for family,folder in [('LIMIT',limit.RUN),('RANGE',range_lab.RUN)]:
        assert read(folder/'PREFIX_CHECKS.json')['passed']
        verification=read(folder/'VERIFICATION.json')
        assert not verification['qualified'] and all(verification['fresh_unchanged'].values())
        rows.extend(dict(family=family,folder=folder,**row) for row in read(folder/'summary.json')['rows'])
    assert len(rows)==108
    flat=[]
    for row in rows:
        m=row['metrics'];f=m['frequency']
        flat.append(dict(family=row['family'],name=row['name'],cost=row['cost'],path=row.get('path','ADVERSE_FIRST'),
                         n=m['n'],win_rate=m['win_rate'],pf=m['pf'],net_r=m['total_r'],expectancy=m['expectancy'],
                         mean_week=f['mean'],median_week=f['median'],min_week=f['min'],max_week=f['max'],
                         empty_weeks=len(f['empty_weeks']),weeks_5_to_10=f['weeks_with_5_to_10'],
                         adjusted_lower=m['expectancy_month_bootstrap_lower_family95'],
                         frequency_pass=m['frequency_pass'],economic_screen_pass=m['economic_screen_pass']))
    with (run/'ALL_V4_EXPERIMENTS.csv').open('w',newline='',encoding='utf-8-sig') as handle:
        writer=csv.DictWriter(handle,fieldnames=list(flat[0]));writer.writeheader();writer.writerows(flat)
    with (run/'ALL_V4_WEEKS.csv').open('w',newline='',encoding='utf-8-sig') as handle:
        writer=csv.DictWriter(handle,fieldnames=['family','name','cost','path','week_start','market_days','n','closed','wins','r'])
        writer.writeheader()
        for row in rows:
            for week in row['metrics']['frequency']['weekly']:
                writer.writerow(dict(family=row['family'],name=row['name'],cost=row['cost'],path=row.get('path','ADVERSE_FIRST'),**week))
    registry=dict(previous=dict(hypotheses=58,scenarios=186,registry_sha256=sha(limit.w.RUN/'CUMULATIVE_REGISTRY.json')),
                  new=dict(limit_hypotheses=12,range_hypotheses=4,total_hypotheses=16,
                           reused_market_control_hypotheses=4,scenarios=108,
                           limit_scenarios=72,market_control_scenarios=24,range_scenarios=12),
                  cumulative=dict(hypotheses=74,scenarios=294),
                  note='At least74 tracked hypotheses;earlier research remains additional uncorrected selection. Reused controls and cost/path scenarios are not extra hypotheses.',
                  tests=dict(regression_suite=83,new_range_checks=6,total_unique=89),
                  prefix_checks=dict(new_limit_execution=12,new_range_detector=6),
                  legacy_pending_parity=read(run/'LEGACY_PENDING_PARITY.json'),
                  locks={str(folder.relative_to(root)):sha(folder/'EXPERIMENT_LOCK.json') for folder in (limit.RUN,range_lab.RUN)},
                  qualified=[],goal_status='active; no joint frequency and economic edge')
    write_json(run/'CUMULATIVE_REGISTRY.json',registry)
    def metric(name,cost='BASE',path=None):
        selected=[r['metrics'] for r in rows if r['name']==name and r['cost']==cost and (path is None or r.get('path')==path)]
        return selected
    def worst(name):return min(metric(name),key=lambda m:m['pf'] or 0)
    table_names=['WEEKLY_MARKET_R80','WEEKLY_SHALLOW_R80','WEEKLY_MIDPOINT_R80','WEEKLY_LEVEL_R80',
                 'MICRO_MARKET_R80','MICRO_MIDPOINT_R80','MICRO_LEVEL_R80',
                 'RANGE_M15','RANGE_H1','RANGE_COMBO','NO_CONTEXT']
    chart=[]
    for spec in limit.SPECS:chart.append((spec['name'],worst(spec['name']),'MARKET' if spec['mode']=='MARKET' else 'LIMIT'))
    chart.extend((s['name'],metric(s['name'])[0],'RANGE') for s in range_lab.SPECS)
    fig,ax=plt.subplots(figsize=(10,5.5));ax.axvspan(5,10,ymin=1/1.7,ymax=1,color='#D3F9D8',alpha=.7)
    colors={'LIMIT':'#D9480F','MARKET':'#495057','RANGE':'#5F3DC4'};markers={'LIMIT':'o','MARKET':'x','RANGE':'^'}
    for family in colors:
        selected=[(name,m) for name,m,f in chart if f==family]
        ax.scatter([m['frequency']['mean'] for _,m in selected],[m['pf'] for _,m in selected],
                   c=colors[family],marker=markers[family],s=55,label=family,alpha=.75,zorder=3)
    ax.scatter([84/261],[1.503],marker='*',s=150,c='#087F8C',label='Preserved Fresh v0.2',zorder=4)
    ax.annotate('Fresh: 84 trades',(.322,1.503),xytext=(1.1,1.53),arrowprops=dict(arrowstyle='-',color='#777'),fontsize=9)
    s=worst('WEEKLY_SHALLOW_R80')
    ax.annotate('Shallow pullback',(s['frequency']['mean'],s['pf']),xytext=(6.3,.85),arrowprops=dict(arrowstyle='-',color='#777'),fontsize=9)
    ax.axhline(1,color='#555',linestyle='--',linewidth=1);ax.axvline(5,color='#555',linestyle=':',linewidth=1)
    ax.set(xlim=(0,10.2),ylim=(0,1.7),xlabel='Mean entries / market-data week',ylabel='BASE profit factor',
           title='V4 research: no candidate meets frequency and economic quality')
    ax.text(6,1.4,'Frequency + PF region\nOther checks still required',fontsize=9,color='#2B8A3E')
    ax.grid(alpha=.13);ax.legend(loc='lower right');ax.spines[['top','right']].set_visible(False)
    fig.text(.5,-.01,'2021-10-25 to 2026-10-25 | Limit points use the lower-PF synthetic path | Retrospective, assumed costs',ha='center',fontsize=8)
    fig.savefig(run/'V4_RESEARCH_OVERVIEW.png',dpi=180,bbox_inches='tight');plt.close(fig)
    paired=next(x for x in read(run/'MATCHED_ENTRY_DIAGNOSTICS.json')['rows'] if x['name']=='WEEKLY_SHALLOW_R80' and x['path']=='OHLC')
    md='''# Nghiên cứu tiếp: điểm vào và bối cảnh đi ngang

## Kết luận hiện tại

**Mục tiêu còn đang mở. Chưa có bản đạt đồng thời win rate, tần suất và lợi nhuận sau phí.** Fresh source/binary/includes được giữ nguyên. Không cài bản mới vào tài khoản thật.

Lượt này thêm **16 cấu hình mới** và thử lại 4 cấu hình đối chứng ở các mô hình khớp khác, tổng **108 kịch bản**. Cộng các lượt đã ghi nhận: ít nhất **74 cấu hình / 294 kịch bản chính**. Không đếm đối chứng đã có thành giả thuyết mới; các nghiên cứu cũ hơn vẫn gây thêm thiên lệch chọn mẫu.

## Thử gì và vì sao

### 1. Điểm vào khi giá hồi

Giữ nguyên tín hiệu weekly/microzone đã khóa; chỉ thay entry bằng lệnh chờ hồi nhẹ 0,15 ATR, giữa thân nến, hoặc mốc tham chiếu. Thử TP 0,8R/1R, phí LOW/BASE/STRESS, cả hai đường giá O→L→H→C và O→H→L→C. Lệnh chờ phải thụ động, hết hạn sau 15 phút và chỉ khớp khi đúng phía Ask/Bid chạm giá. Fresh trong nhánh kết hợp vẫn vào market và TP 0,5R.

### 2. Hồi về giá trung bình trong bối cảnh đi ngang

Band EMA20 ±2,5 ATR được khóa từ M5 đã đóng trước sweep. Reclaim trong tối đa 3 nến M5; mốc TP là EMA trước excursion, không cập nhật theo tương lai. Thử bối cảnh M15/H1 có ADX14 ≤20 và độ dốc EMA nhỏ, nhánh kết hợp Fresh, và đối chứng không lọc bối cảnh. Entry chỉ được nhận nếu room thực tế đến mean ≥0,8R sau khi tính Ask/Bid và SL tối thiểu.

Giới hạn chung: một vị thế/ý tưởng chờ, tối đa 2 lệnh/ngày và 10 lệnh/tuần, không ép lệnh để đủ chỉ tiêu. Thời gian giữ mới tối đa 120 phút và không quá 21:00 giờ feed.

## Backtest 5 năm: 25/10/2021 đến trước 25/10/2026

Phí BASE: spread 0,30 giá, slippage 0,01, commission khứ hồi tương đương 0,07 giá. STRESS: 0,45 / 0,05 / 0,10. Đây là giả định nghiên cứu, chưa xác nhận phí broker. Với limit, bảng lấy kịch bản có PF thấp hơn trong hai đường giá; file CSV giữ đủ cả hai.

| Cấu hình | Lệnh | Win rate | PF | Net R | TB lệnh/tuần | Tuần 0 lệnh |
|---|---:|---:|---:|---:|---:|---:|
'''
    for name in table_names:
        m=worst(name);f=m['frequency']
        md+=f"| {name} | {m['n']} | {m['win_rate']:.2f}% | {m['pf']:.3f} | {m['total_r']:+.2f} | {f['mean']:.2f} | {len(f['empty_weeks'])} |\n"
    md+=f'''
Không có biến thể mới nào dương ở BASE, nên không có ứng viên để chuyển sang native hay dùng thật. Các mức TP 1R và mọi phí/đường giá khác nằm trong CSV và JSON; không giấu các cấu hình thua.

## Chẩn đoán đáng chú ý

- Lệnh chờ hồi nhẹ vẫn đủ tần suất trung bình, nhưng win rate chỉ khoảng 48%; dời entry chưa khắc phục được chất lượng tín hiệu.
- Trong đối chiếu WEEKLY_SHALLOW_R80/OHLC, có **{paired['market_signals_not_filled_by_limit']}** tín hiệu mà bản market khớp nhưng bản limit không khớp. Bản market thắng **{paired['missed_market_wins']}** trong số đó, tổng **{paired['missed_market_total_r']:+.2f}R**. Đây là thống kê mô tả; việc lệnh chờ chiếm thời gian và giới hạn số lệnh cũng thay đổi sự kiện được nhận, nên không coi là chứng minh nhân quả riêng của entry.
- Bộ lọc đi ngang làm số lệnh giảm mạnh; nhánh kết hợp chỉ khoảng 2,03 lệnh/tuần, 30 tuần trống và vẫn lỗ. Chưa có bằng chứng bộ lọc ADX/EMA đang dùng làm xuất hiện edge.
- Ở NO_CONTEXT/BASE, **1.248** tín hiệu bị từ chối vì sau xác nhận M5 đã không còn room 0,8R về mean; đây là cơ sở để cân nhắc kiểm tra một trigger sớm độc lập ở lượt sau, thay vì đổi thêm độ sâu limit.

## Kiểm chứng đã thực hiện

- 83 kiểm tra hồi quy qua sau thay đổi giờ cho lệnh chờ; 6 kiểm tra mới của nhánh range qua, tổng 89 kiểm tra khác nhau.
- 12 kiểm tra prefix thực thi lệnh chờ và 6 kiểm tra prefix detector range trên dữ liệu thật khớp hoàn toàn.
- Thêm trường `pending_hours` vào Plan, giữ mặc định giờ cũ. Replay pending cũ khớp chính xác **462 dòng** gồm trạng thái, thời điểm, SL, risk, R và phí.
- TP chạm trước khi limit khớp không được ghi nhận thành thắng; gap qua SL trước fill bị hủy; hết hạn trước touch không phát sinh phí. Room không đủ không tạo FILL hoặc commission.
- Hash Fresh source/binary/includes không đổi. Không có native mới hoặc thao tác tài khoản/gửi tin ngoài.

## Giới hạn

Tất cả lịch sử này đã được xem trước. Đây là nghiên cứu hồi cứu; prefix checks không biến nó thành dữ liệu ngoài mẫu nguyên vẹn. OHLC/OLHC chỉ là hai kịch bản trong nến, không phải tick thật hay biên tốt/xấu tuyệt đối. Không xác nhận hàng đợi, spread động, trượt giá theo tin, clock/DST hoặc quy định gói quỹ cụ thể. Không có cam kết lợi nhuận tương lai.

## Nguồn và file

- [Adam Grimes: Fundamental Trading Patterns](https://www.adamhgrimes.com/fundamental-trading-patterns/) là nguồn phân loại pullback/failure test; cách đặt limit ở đây là giả thuyết riêng đã khóa.
- [Linda Raschke, Active Trader tháng 3/2004](https://lindaraschke.net/wp-content/uploads/2026/03/raschke_pt2_0304.pdf) mô tả EMA20, ADX14 và Keltner ±2,5 ATR. Không gán kết quả XAUUSD của thí nghiệm này cho tác giả.
- `ALL_V4_EXPERIMENTS.csv`: 108 kịch bản. `ALL_V4_WEEKS.csv`: 28.188 dòng tuần, có cả tuần trống.
- Locks, từng lệnh, bootstrap, lựa chọn theo năm trước và audits ở `20261101_limit_v4` và `20261101_range_v4`.
- Gói ZIP có mã/kết quả; dữ liệu rates.npz và fixture cũ dùng lại trong workspace, không đóng gói các tập lịch sử lớn.
'''
    (run/'RESEARCH_CHECKPOINT.md').write_text(md,encoding='utf-8')
    continuation='''# Điểm tiếp tục nghiên cứu v4

## Mục tiêu không đổi

Giữ Fresh v0.2. Bản khác hướng tới win rate 55–60%, 5–10 lệnh/tuần, tuần nào cũng có lệnh và edge sau phí. Mục tiêu ACTIVE, chưa đạt; không đánh dấu hoàn thành hay thu hẹp còn giữ Fresh/báo cáo.

## Trạng thái

Đọc RESEARCH_CHECKPOINT.md, CUMULATIVE_REGISTRY.json và ../20261101_range_v4/summary.json. Tổng ít nhất 74 cấu hình / 294 kịch bản chính. Lượt v4 gồm 12 giả thuyết entry limit mới, 4 giả thuyết range/mean mới và 4 đối chứng market đã từng được tính trước. Tất cả BASE âm. WEEKLY_SHALLOW_R80: 1.521 lệnh, khoảng 48% thắng, PF khoảng 0,686, 5,83 lệnh/tuần, 0 tuần trống. Range combo: 529 lệnh, 46,31% thắng, PF 0,800, −57,38R, 2,03 lệnh/tuần, 30 tuần trống. Không có native mới để cài.

83 hồi quy + 6 kiểm tra range qua. 12 prefix execution limit, 6 prefix detector range qua; pending legacy 462 dòng khớp chính xác. Fresh hash không đổi. Không có process nghiên cứu đang chạy sau khi finalizer hoàn thành.

## Bằng chứng thay đổi hướng tiếp theo

1. Market v3 âm cả khi bỏ phí; chuyển sang limit vẫn âm. Không tiếp tục thử một dãy độ sâu hồi/TP chỉ để lấy số dương.
2. Limit bỏ lỡ nhiều tín hiệu market thắng: 299 sự kiện không khớp ở WEEKLY_SHALLOW_R80/OHLC, trong đó market thắng 237 và tổng +124,33R. Đây là mô tả có cả tác động occupancy/caps, không phải kết luận nhân quả thuần.
3. Mean-reversion M5 có nhiều tín hiệu hết room sau khi nến xác nhận đóng: NO_CONTEXT/BASE 1.248 trường hợp room<0,8R; chỉ 997 lệnh được nhận, vẫn âm. Nếu thử trigger M1 sớm, phải là detector độc lập dùng band M5 đã đóng và biết trước M1 sweep; TUYỆT ĐỐI không dựa vào việc M5 tương lai sẽ xác nhận. Chưa triển khai/thử giả thuyết này. Cần khóa mới trước kết quả và cộng phép thử; đừng gọi là lặp lại H1/M1 v2 đã thất bại.
4. Dữ liệu 2021–2026 và tuần 26–30/10 đều đã xem; mọi kiểm định trên đó là hồi cứu. Cần dữ liệu xác nhận mới khi có ứng viên đáng tin.
5. Không có ứng viên hiện tại để chuyển native hoặc thi quỹ. Phí broker, clock/DST, lịch tin, lot và gói FTMO/The5ers còn chưa xác minh. Không đặt lệnh broker, đổi tài khoản chính, cài đè Fresh hoặc gửi Telegram/chat khác.

## Tái chạy

- python scripts/research_scalp_limit_v4.py
- python scripts/audit_scalp_limit_v4.py
- python scripts/research_scalp_range_v4.py
- python scripts/audit_scalp_range_v4.py
- python scripts/finalize_scalp_v4.py

Kết quả đã lưu; không cần chạy lại toàn bộ khi không thay định nghĩa hoặc không có dữ liệu mới. Tham số pending_hours mặc định giữ đúng giờ cũ; default parity 462 dòng đã lưu.
'''
    (run/'CONTINUATION.md').write_text(continuation,encoding='utf-8')
    files=['scripts/research_scalp_limit_v4.py','scripts/research_scalp_range_v4.py',
           'scripts/audit_scalp_limit_v4.py','scripts/audit_scalp_range_v4.py','scripts/finalize_scalp_v4.py',
           'scripts/research_scalp_weekly_v3.py','scripts/research_scalp_microzones_v3.py',
           'scripts/can_ho_tro_scalp_core.py','scripts/can_ho_tro_scalp_plan.py','scripts/research_scalp_v2.py',
           'scripts/replay_can_ho_tro_scalp.py','scripts/replay_scalp_structure_lab.py','scripts/prepare_can_ho_tro_scalp.py',
           'tests/test_research_scalp_limit_v4.py','tests/test_research_scalp_range_v4.py',
           'tests/test_research_scalp_weekly_v3.py','tests/test_research_scalp_v2.py',
           'tests/test_can_ho_tro_scalp.py','tests/test_scalp_structure_lab.py']+limit.w.FRESH_PATHS
    write_json(run/'CHECKPOINT_MANIFEST.json',dict(files={p:sha(root/p) for p in files},
               input_data_sha256=sha(limit.w.BASE/'rates.npz'),goal_status='active',qualified=[]))
    bundle=run/'scalp_v4_checkpoint.zip'
    with zipfile.ZipFile(bundle,'w',zipfile.ZIP_DEFLATED,compresslevel=6) as archive:
        for folder in (limit.RUN,range_lab.RUN):
            for path in sorted(folder.rglob('*')):
                if path.is_file() and path!=bundle:archive.write(path,path.relative_to(root))
        for file in files:archive.write(root/file,file)
    print('V4 CHECKPOINT',len(rows),'scenarios;74 hypotheses cumulative;Fresh unchanged;qualified0;zip_bytes',bundle.stat().st_size,flush=True)


if __name__=='__main__':main()
