# -*- coding: utf-8 -*-
"""Preserve the independent early-entry test, including every failed scenario."""
import csv
import json
import zipfile

from prepare_can_ho_tro_scalp import sha, write_json
import research_scalp_early_mean_v5 as e


def read(path):
    return json.loads(path.read_text(encoding='utf-8'))


def main():
    run = e.RUN
    old_path = e.w.ROOT / 'reports/can_ho_tro_scalp/20261101_limit_v4/CUMULATIVE_REGISTRY.json'
    assert read(old_path)['cumulative'] == dict(hypotheses=74, scenarios=294)
    verification = read(run / 'VERIFICATION.json')
    assert all(verification['fresh_unchanged'].values()) and not verification['qualified']
    assert read(run / 'PREFIX_CHECKS.json')['passed']
    rows = read(run / 'summary.json')['rows']
    assert len(rows) == 12
    flat = []
    for row in rows:
        m = row['metrics']; f = m['frequency']
        flat.append(dict(name=row['name'], cost=row['cost'], n=m['n'], win_rate=m['win_rate'],
                         pf=m['pf'], net_r=m['total_r'], expectancy=m['expectancy'],
                         mean_week=f['mean'], median_week=f['median'], min_week=f['min'], max_week=f['max'],
                         empty_weeks=len(f['empty_weeks']), weeks_5_to_10=f['weeks_with_5_to_10'],
                         adjusted_lower=m['expectancy_month_bootstrap_lower_family95'],
                         frequency_pass=m['frequency_pass'], economic_screen_pass=m['economic_screen_pass']))
    with (run / 'ALL_V5_EXPERIMENTS.csv').open('w', newline='', encoding='utf-8-sig') as handle:
        writer = csv.DictWriter(handle, fieldnames=list(flat[0])); writer.writeheader(); writer.writerows(flat)
    with (run / 'ALL_V5_WEEKS.csv').open('w', newline='', encoding='utf-8-sig') as handle:
        writer = csv.DictWriter(handle, fieldnames=['name', 'cost', 'week_start', 'market_days', 'n', 'closed', 'wins', 'r'])
        writer.writeheader()
        for row in rows:
            for week in row['metrics']['frequency']['weekly']:
                writer.writerow(dict(name=row['name'], cost=row['cost'], **week))
    registry = dict(previous=dict(hypotheses=74, scenarios=294, registry_sha256=sha(old_path)),
                    new=dict(hypotheses=4, scenarios=12), cumulative=dict(hypotheses=78, scenarios=306),
                    tests=dict(previous_unique=89, early_detector=8, total_unique=97), real_prefix_checks=6,
                    qualified=[], goal_status='active; no joint frequency, win rate and economic edge',
                    experiment_lock_sha256=sha(run / 'EXPERIMENT_LOCK.json'),
                    note='At least78 tracked hypotheses plus earlier untracked research; all data previously inspected.')
    write_json(run / 'CUMULATIVE_REGISTRY.json', registry)
    md = '''# Xác nhận M1 sớm: backtest 5 năm v5

**Mục tiêu còn mở. Chưa có ứng viên đạt 55–60% thắng, 5–10 lệnh/tuần, không tuần trống và edge sau phí.**

Fresh v0.2 giữ nguyên hash source/binary/includes. Bản thử nghiệm này chỉ nằm trong lab.

## Giả thuyết đã khóa trước kết quả

Ở v4, nhiều tín hiệu M5 đóng quá muộn để còn room về EMA. V5 tạo detector M1 độc lập: band EMA20 ±2,5 ATR14 của nến M5 đã đóng trước sweep, giữ band/mean/ATR5 cố định. M1 reclaim trong tối đa 3 nến; không cần M5 hiện tại xác nhận trong tương lai. Bộ lọc range M15/H1 giống v4; thêm đối chứng không lọc và kết hợp Fresh.

Entry market theo Bid/Ask, spread/slippage/commission, SL ngoài cực trị excursion, tối thiểu 2 và tối đa 20 giá. TP về mean đã khóa, room từ giá khớp thật ≥0,8R. M1 chạm cả TP/SL tính SL trước. Một vị thế, tối đa 2 lệnh/ngày và 10/tuần; không ép số lệnh. Tín hiệu 08:00–trước 19:00 giờ feed, giữ tối đa 120 phút và không quá 21:00 feed. Chưa gọi các giờ này là London/New York.

## Kết quả BASE, 25/10/2021 đến trước 25/10/2026

Phí BASE giả định: spread 0,30 giá, slippage 0,01, commission khứ hồi 0,07 giá. STRESS: 0,45 / 0,05 / 0,10. R là lãi/lỗ theo rủi ro SL ban đầu, đã trừ phí; chưa quy đổi thành % tài khoản.

| Bản | Lệnh | Thắng | PF | Net R | TB lệnh/tuần | Tuần 0 lệnh | Tuần có 5–10 lệnh |
|---|---:|---:|---:|---:|---:|---:|---:|
'''
    for row in rows:
        if row['cost'] != 'BASE':
            continue
        m = row['metrics']; f = m['frequency']
        md += f"| {row['name']} | {m['n']} | {m['win_rate']:.2f}% | {m['pf']:.3f} | {m['total_r']:+.2f} | {f['mean']:.2f} | {len(f['empty_weeks'])} | {f['weeks_with_5_to_10']}/{f['weeks']} |\n"
    md += '''
Cả 4 cấu hình đều âm ở cả LOW, BASE và STRESS. Đối chứng không lọc đủ tần suất trung bình nhưng không đạt tỷ lệ thắng/lợi nhuận. Việc vào sớm giảm số lần bị từ chối vì hết room (510 ở NO_CONTEXT/BASE, so với 1.248 của v4); các tập tín hiệu, thời gian chiếm vị thế và caps khác nhau, nên không quy chênh lệch P&L riêng cho một yếu tố.

Median target/risk của EARLY_NO_CONTEXT/BASE khoảng 1,405R nhưng thắng 36%; 1.075/1.714 lệnh thoát STOP hoặc STOP_GAP. Đây là cơ sở kiểm tra thất bại của nỗ lực hồi, không phải bằng chứng cứ đảo chiều mọi lệnh thua là có edge.

## Kiểm chứng

97 kiểm tra hồi quy đều qua, gồm 8 kiểm tra mới về đóng nến, đối xứng BUY/SELL, band/mean/ATR khóa, dedup/rearm, hết hạn và gap. Sáu prefix trên dữ liệu thật (3 nguồn × 2 mốc 01/01/2022, 01/01/2025) khớp chính xác. Fresh hash không đổi. Cộng dồn ít nhất **78 giả thuyết / 306 kịch bản chính**, không tính phép chọn theo năm và các audits là giả thuyết độc lập mới.

Tất cả lịch sử đã được xem. Đây là hồi cứu; không có native mới, dữ liệu ngoài mẫu nguyên vẹn hay chứng nhận phù hợp FTMO/The5ers. Phí thực, clock/DST, spread động và trượt giá theo tin còn chưa kiểm chứng.

## Nguồn

Mô hình mean/band là giả thuyết chuyển thể từ [phỏng vấn Linda Raschke, tháng 3/2004](https://lindaraschke.net/wp-content/uploads/2026/03/raschke_pt2_0304.pdf). Nguồn không công bố preset XAUUSD của v5. [MetaTrader 5: copy_rates_from_pos](https://www.mql5.com/en/docs/python_metatrader5/mt5copyratesfrompos_py) phân biệt nến hiện tại ở vị trí 0 với nến đã đóng.

Các file ALL_V5_EXPERIMENTS.csv, ALL_V5_WEEKS.csv, summary.json, ENTRY_DIAGNOSTICS.json và từng lệnh giữ đủ mọi kết quả. Không chạy lại tuần 26–30/10 để tìm bản đẹp vì tuần đó đã được xem và mọi ứng viên v5 đã thất bại trên 5 năm.
'''
    (run / 'RESEARCH_CHECKPOINT.md').write_text(md, encoding='utf-8')
    continuation = '''# Điểm tiếp tục v5

Mục tiêu ACTIVE: giữ Fresh v0.2; bản riêng 55–60% thắng, 5–10 lệnh/tuần, tuần nào cũng có lệnh, edge sau phí. Chưa đạt. Đọc RESEARCH_CHECKPOINT.md, CUMULATIVE_REGISTRY.json, ENTRY_DIAGNOSTICS.json và summary.json tại đây. V5 hoàn tất 4 giả thuyết /12 kịch bản, tổng ít nhất78/306. 97 tests và6 prefix mới qua. Không có process đang chạy sau finalizer.

EARLY_NO_CONTEXT/BASE:1714 lệnh,36% thắng,PF.777,-248.94R,6.57 lệnh/tuần,0 tuần trống. Mean room rejections510; STOP/STOP_GAP1075. Vào sớm không tạo edge. Bộ lọc range M15/H1 làm mất tần suất và vẫn âm. Không lặp scan band/TP/threshold trên cùng lịch sử để lấy số dương.

Có cơ sở nghiên cứu tiếp sự thất bại của nỗ lực hồi: chỉ tạo tín hiệu mới SAU khi M1 thực sự đóng phá extreme đã biết của một reclaim thất bại; không đảo nhãn lệnh thua, không dùng kết quả TP/SL làm điều kiện. Chưa triển khai ở thời điểm finalizer v5. Phải khóa định nghĩa và cộng số phép thử trước khi đánh giá. Kiểm tra trend M15/H1 và no-context có thể là ablation; điều kiện xác nhận, expiry, mean invalidation, gap và stop phải nêu rõ.

Toàn bộ2021–2026/tuần26–30/10 đã xem. Fresh và tài khoản/broker/Telegram không đổi. Không đặt lệnh hay gửi chat khác. Prop package/phí/clock/news/lot chưa xác minh. Chỉ làm native riêng sau khi có ứng viên đủ chuẩn và dữ liệu xác nhận mới; không hứa edge dương.

Tái chạy khi cần: python scripts/research_scalp_early_mean_v5.py; python scripts/audit_scalp_early_mean_v5.py; python scripts/finalize_scalp_early_mean_v5.py. Kết quả đã cache, không cần chạy lại nếu định nghĩa/dữ liệu không đổi.
'''
    (run / 'CONTINUATION.md').write_text(continuation, encoding='utf-8')
    files = ['scripts/research_scalp_early_mean_v5.py', 'scripts/audit_scalp_early_mean_v5.py',
             'scripts/finalize_scalp_early_mean_v5.py', 'tests/test_research_scalp_early_mean_v5.py',
             'scripts/research_scalp_range_v4.py', 'scripts/research_scalp_weekly_v3.py',
             'scripts/can_ho_tro_scalp_core.py', 'scripts/can_ho_tro_scalp_plan.py',
             'scripts/replay_can_ho_tro_scalp.py', 'scripts/prepare_can_ho_tro_scalp.py'] + e.w.FRESH_PATHS
    write_json(run / 'CHECKPOINT_MANIFEST.json', dict(files={p: sha(e.w.ROOT/p) for p in files},
               input_data_sha256=sha(e.w.BASE/'rates.npz'), goal_status='active', qualified=[]))
    bundle = run / 'scalp_v5_checkpoint.zip'
    with zipfile.ZipFile(bundle, 'w', zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
        for path in sorted(run.iterdir()):
            if path.is_file() and path != bundle:
                archive.write(path, path.relative_to(e.w.ROOT))
        for file in files:
            archive.write(e.w.ROOT/file, file)
    with zipfile.ZipFile(bundle) as archive:
        assert archive.testzip() is None
    print('V5 CHECKPOINT:78 hypotheses/306 scenarios; qualified0; Fresh unchanged; ZIP verified', flush=True)


if __name__ == '__main__':
    main()
