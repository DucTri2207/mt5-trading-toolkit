# -*- coding: utf-8 -*-
"""Publish v5/v6 results and a cost ledger with corrected inherited metadata."""
import csv
import json
import math
import zipfile

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

from prepare_can_ho_tro_scalp import sha, write_json
import research_scalp_failed_reclaim_v6 as f


def read(path):
    return json.loads(path.read_text(encoding='utf-8'))


def csv_file(path, rows):
    with path.open('w', newline='', encoding='utf-8-sig') as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader(); writer.writerows(rows)


def main():
    run = f.RUN; root = f.w.ROOT
    previous = read(f.early.RUN/'CUMULATIVE_REGISTRY.json')
    assert previous['cumulative'] == dict(hypotheses=78, scenarios=306)
    rows = []
    for version, folder in [('V5', f.early.RUN), ('V6', f.RUN)]:
        verification = read(folder/'VERIFICATION.json')
        assert not verification['qualified'] and all(verification['fresh_unchanged'].values())
        assert read(folder/'PREFIX_CHECKS.json')['passed']
        rows.extend(dict(version=version, folder=folder, **row) for row in read(folder/'summary.json')['rows'])
    assert len(rows) == 24
    flat = []; weeks = []; years = []; ledger = []; fee_checks = []; misleading = 0
    for row in rows:
        m = row['metrics']; frequency = m['frequency']
        flat.append(dict(version=row['version'], name=row['name'], cost=row['cost'], n=m['n'], win_rate=m['win_rate'],
                         pf=m['pf'], net_r=m['total_r'], expectancy=m['expectancy'],
                         mean_week=frequency['mean'], median_week=frequency['median'],
                         min_week=frequency['min'], max_week=frequency['max'], empty_weeks=len(frequency['empty_weeks']),
                         weeks_5_to_10=frequency['weeks_with_5_to_10'],
                         adjusted_lower=m['expectancy_month_bootstrap_lower_family95'],
                         frequency_pass=m['frequency_pass'], economic_screen_pass=m['economic_screen_pass']))
        for week in frequency['weekly']:
            weeks.append(dict(version=row['version'], name=row['name'], cost=row['cost'], **week))
        for year, metric in m['by_year'].items():
            years.append(dict(version=row['version'], name=row['name'], cost=row['cost'], year=year,
                              coverage='PARTIAL' if year in ('2021', '2026') else 'FULL',
                              n=metric['n'], wins=metric['wins'], win_rate=metric['win_rate'],
                              pf=metric['pf'], net_r=metric['total_r']))
        trades = read(row['folder']/(row['name']+'_'+row['cost']+'_trades.json'))['trades']
        cost = next(c for c in f.w.COSTS if c['id'] == row['cost'])
        corrected = []
        for trade in trades:
            filled = bool(trade['entry_time']); fee = cost['commission_price']/trade['risk'] if filled else 0.
            assert math.isclose(trade['commission_r'], fee, rel_tol=1e-10, abs_tol=1e-10)
            if trade['r'] is not None:
                assert math.isclose(trade['r'], trade['gross_r']-fee, rel_tol=1e-10, abs_tol=1e-10)
            if filled and 'ZERO_ASSUMPTION' in trade.get('fees_status', ''):
                misleading += 1
            normalized = dict(trade)
            normalized.update(commission=cost['commission_price']*100 if filled else 0.,
                              fees_status='ASSUMED_ROUND_TRIP_COMMISSION; SPREAD_SLIP_IN_PRICES; SWAP_UNMODELED',
                              commission_cash_unit='100oz-lot assumption,not actual account charge',
                              assumed_spread=cost['spread'], assumed_slippage=cost['slip'],
                              assumed_commission_price=cost['commission_price'])
            corrected.append(normalized)
            ledger.append(dict(version=row['version'], name=row['name'], cost=row['cost'],
                               candidate_index=trade['candidate_index'], state=trade['state'], reason=trade['reason'],
                               buy=trade['buy'], source=trade['source'], signal_time=trade['signal_time'],
                               entry_time=trade['entry_time'], exit_time=trade['exit_time'], entry=trade['entry'],
                               initial_sl=trade['initial_sl'], risk=trade['risk'], gross_r=trade['gross_r'],
                               commission_r=fee, net_r=trade['r'], assumed_spread=cost['spread'],
                               assumed_slippage=cost['slip'], assumed_commission_price=cost['commission_price'],
                               assumed_commission_cash_100oz=normalized['commission'],
                               fee_status=normalized['fees_status']))
        clean = run/'NORMALIZED_TRADES'; clean.mkdir(exist_ok=True)
        write_json(clean/(row['name']+'_'+row['cost']+'.json'), dict(trades=corrected,
                   original_sha256=sha(row['folder']/(row['name']+'_'+row['cost']+'_trades.json')),
                   metadata_only=True, economic_results_unchanged=True))
        fee_checks.append(dict(name=row['name'], cost=row['cost'], rows=len(trades),
                               commission_r_verified=True, net_equals_gross_minus_fee=True))
    csv_file(run/'ALL_V5_V6_EXPERIMENTS.csv', flat)
    csv_file(run/'ALL_V5_V6_WEEKS.csv', weeks)
    csv_file(run/'ALL_V5_V6_YEARS.csv', years)
    csv_file(run/'ALL_V5_V6_TRADES.csv', ledger)
    write_json(run/'FEE_METADATA_ERRATUM.json', dict(
        issue='Inherited as_result label/cash commission fields said ZERO/0 while wrapper correctly deducted commission_r from gross_r.',
        original_logs_retained=True, normalized_folder='NORMALIZED_TRADES', mislabeled_filled_rows=misleading,
        corrected_fields=['fees_status', 'commission'],
        unchanged=['entry', 'exit_price', 'risk', 'gross_r', 'commission_r', 'r', 'state', 'reason'],
        economic_results_unchanged=True, all_scenarios_verified=fee_checks,
        future_work='New research adapters must set assumed fee metadata explicitly;do not interpret old fees_status/commission fields as zero-cost execution.'))
    registry = dict(previous=dict(hypotheses=78, scenarios=306, registry_sha256=sha(f.early.RUN/'CUMULATIVE_REGISTRY.json')),
                    new=dict(hypotheses=4, scenarios=12), this_continuation=dict(hypotheses=8, scenarios=24),
                    cumulative=dict(hypotheses=82, scenarios=318),
                    tests=dict(total_unique=106, new_v5=8, new_v6=9),
                    this_continuation_prefix_checks=dict(detector=12, execution=8),
                    qualified=[], goal_status='active; no joint win-rate,frequency and after-cost edge',
                    locks={str(folder.relative_to(root)): sha(folder/'EXPERIMENT_LOCK.json') for folder in (f.early.RUN, f.RUN)},
                    note='At least82 tracked hypotheses plus earlier untracked research;cost scenarios/audits/walkforward choices are not extra hypotheses.')
    write_json(run/'CUMULATIVE_REGISTRY.json', registry)
    base_rows = [row for row in rows if row['cost'] == 'BASE']
    fig, axes = plt.subplots(1, 2, figsize=(11, 4.5), layout='constrained')
    for version, marker, color in [('V5', 'o', '#1971C2'), ('V6', '^', '#D9480F')]:
        selected = [row for row in base_rows if row['version'] == version]
        x = [r['metrics']['frequency']['mean'] for r in selected]
        axes[0].scatter(x, [r['metrics']['win_rate'] for r in selected], marker=marker, c=color, s=60, label=version)
        axes[1].scatter(x, [r['metrics']['pf'] for r in selected], marker=marker, c=color, s=60, label=version)
    axes[0].fill_between([5, 10], 55, 60, color='#B2F2BB', alpha=.7)
    axes[1].fill_between([5, 10], 1, 1.6, color='#B2F2BB', alpha=.7)
    axes[0].scatter([84/261], [75], marker='*', c='#087F8C', s=120, label='Preserved Fresh')
    axes[1].scatter([84/261], [1.503], marker='*', c='#087F8C', s=120, label='Preserved Fresh')
    axes[0].set(ylim=(25, 80), ylabel='Win rate after fees (%)', title='Win rate and frequency')
    axes[1].set(ylim=(.4, 1.6), ylabel='Profit factor after fees', title='Economic quality and frequency')
    axes[1].axhline(1, c='#555', linestyle='--', linewidth=1)
    for ax in axes:
        ax.set(xlim=(0, 10.2), xlabel='Mean entries / market-data week')
        ax.axvline(5, c='#555', linestyle=':', linewidth=1); ax.grid(alpha=.15)
        ax.spines[['top', 'right']].set_visible(False); ax.legend(loc='upper right', fontsize=8)
    fig.suptitle('Five-year BASE results: none of the 8 new hypotheses meets the objective', fontsize=12)
    fig.savefig(run/'V5_V6_RESEARCH_OVERVIEW.png', dpi=180); plt.close(fig)
    md = '''# Nghiên cứu scalp: M1 sớm và tiếp diễn sau hồi thất bại

**Chưa có bản đủ chuẩn. Mục tiêu vẫn ACTIVE: 55–60% thắng, 5–10 lệnh/tuần, tuần nào cũng có lệnh và lợi nhuận sau phí.**

Giữ nguyên Fresh v0.2. Lượt tiếp tục này thêm 8 giả thuyết /24 kịch bản phí; cộng dồn ít nhất **82 giả thuyết /318 kịch bản chính**. Không có bản mới để cài hoặc giao dịch thật.

## Hai hướng đã kiểm tra

**V5 – M1 hồi về mean:** xác nhận M1 độc lập với band M5 đã đóng trước sweep; khóa mean/ATR/band. Thử range M15, range H1, kết hợp Fresh và đối chứng không lọc. Vào sớm giúp còn room nhưng chưa tạo edge.

**V6 – tiếp diễn sau nỗ lực hồi thất bại:** chỉ dùng raw reclaim đã đóng, không dùng nhãn lời/lỗ. Trong 15 nến M1 tiếp theo, chờ close phá extreme đã biết theo hướng ngược lại ít nhất 0,1 ATR5; yêu cầu thân, range và vị trí close. Hủy khi giá chạm mean trước hoặc trong nến xác nhận, hoặc có gap. SL ngoài toàn bộ nỗ lực hồi; TP 0,8R. Thử trend M15/H1, kết hợp Fresh và đối chứng không lọc. Đây là tín hiệu mới ở thời điểm sau, không phải đảo dấu lợi nhuận lệnh cũ.

Nguồn ý tưởng tiếp diễn sau đảo chiều thất bại: [Al Brooks, bài trình bày ngày 17/10/2017](https://www.brookstradingcourse.com/wp-content/uploads/2017/10/171017-Futures.io-Presentation-Opening-Reversals-Al-Brooks.pdf). Ngưỡng XAUUSD là giả thuyết riêng, không phải preset hoặc hiệu suất của tác giả. Cơ sở band/mean: [Linda Raschke, phỏng vấn tháng 3/2004](https://lindaraschke.net/wp-content/uploads/2026/03/raschke_pt2_0304.pdf).

## Backtest 5 năm: 25/10/2021 đến trước 25/10/2026

BASE: spread 0,30 giá, slippage 0,01, commission khứ hồi 0,07 giá. LOW: 0,20 /0 /0,07. STRESS: 0,45 /0,05 /0,10. Đây là phí giả định. R đã trừ phí và tính theo SL ban đầu; không phải % tài khoản.

| Bản | Lệnh | Thắng | PF | Net R | TB lệnh/tuần | Tuần 0 lệnh | Tuần 5–10 lệnh |
|---|---:|---:|---:|---:|---:|---:|---:|
'''
    for row in base_rows:
        m = row['metrics']; freq = m['frequency']
        md += f"| {row['name']} | {m['n']} | {m['win_rate']:.2f}% | {m['pf']:.3f} | {m['total_r']:+.2f} | {freq['mean']:.2f} | {len(freq['empty_weeks'])} | {freq['weeks_with_5_to_10']}/{freq['weeks']} |\n"
    md += '''
Cả 8 cấu hình mới đều âm ở cả 3 mức phí. EARLY_NO_CONTEXT đủ tần suất trung bình và không tuần trống, nhưng thắng chỉ 36%. V6 thắng khoảng 44–49% ở BASE, dưới mục tiêu và chưa đủ bù mức TP 0,8R cùng chi phí; tần suất cũng không đủ. Bộ chọn theo năm trước chọn CASH cho mọi năm 2023–2026 vì không có ứng viên qua ngưỡng đào tạo. CASH không được coi là đạt yêu cầu.

## Tuần 26–30/10/2026 đã kiểm tra trước đó

Fresh v0.2: **0 lệnh, 0R**. Bản thử nghiệm v3 COMBO_R80: **7 lệnh, 2 thắng/5 thua, −3,53R BASE**. Đây là hai phiên bản khác nhau. Kết quả lấy lại từ FORWARD_WEEK.json và LAST_WEEK.json đã lưu; không chạy tuần này cho mọi biến thể v5/v6 đã thất bại để chọn bản đẹp. Tuần này và lịch sử 5 năm đều đã được xem.

## Kiểm chứng và sửa nhãn báo cáo

- 106 kiểm tra hồi quy qua, gồm 8 kiểm tra v5 và 9 kiểm tra v6 mới. Detector đóng nến, frozen levels, đối xứng, expiry, gap và trạng thái được kiểm tra.
- 12 prefix detector mới (v5/v6) và 8 prefix thực thi v6 khớp chính xác trên hai mốc 01/01/2022 và 01/01/2025. Prefix không chứng minh lợi nhuận ngoài mẫu.
- Mô hình dùng Bid/Ask, commission đúng một lần, gap và SL trước TP trong M1 mơ hồ. Một vị thế, tối đa 2 fills/ngày và 10/tuần. Bảng tuần tính đủ 261 tuần có dữ liệu, có cả tuần trống; trung bình 5–10 không có nghĩa mọi tuần đều 5–10.
- Phát hiện trường `fees_status`/`commission` kế thừa từ log lõi còn ghi ZERO/0 trong khi wrapper đã trừ đúng `commission_r`. Đã đối chiếu từng dòng: net R = gross R − commission R và commission R = phí giá /risk thực. `NORMALIZED_TRADES` và `ALL_V5_V6_TRADES.csv` có nhãn phí/commission sửa đúng. `FEE_METADATA_ERRATUM.json` ghi nguồn gốc; log gốc và mọi giá, R, trạng thái, thời điểm giữ nguyên. Không có thay đổi P&L do sửa nhãn.
- Fresh source/binary/includes giữ đúng hash. Không đặt lệnh, đổi tài khoản, cài đè hoặc gửi tin ngoài.

## Giới hạn và hướng tiếp tục

Toàn bộ lịch sử đã được xem: mọi kết quả là hồi cứu, có thiên lệch từ ít nhất 82 giả thuyết và cả nghiên cứu cũ chưa đếm. Bootstrap theo tháng có hiệu chỉnh số giả thuyết; không có ứng viên dương để đi tiếp. M1 OHLC không xác nhận tick thật, spread động, fill hoặc trượt giá theo tin. Phí broker, clock/DST, news, lot và gói FTMO/The5ers còn chưa xác minh.

Hai hướng v5/v6 đã được trả lời âm. Lượt sau cần nguồn tín hiệu/bối cảnh có cơ sở mới, không tiếp tục quét TP, band, độ sâu hoặc timeframe để ép kết quả dương. Báo cáo gốc 23/10 có hướng AVWAP của Brian Shannon chưa triển khai trong các lab này; cần kiểm tra chất lượng tick_volume/real_volume và định nghĩa điểm neo biết trước trước khi quyết định một thí nghiệm riêng. Tick volume chỉ là proxy; không được gọi là footprint/volume toàn thị trường. Đây mới là hướng cân nhắc, chưa có kết quả hoặc giả thuyết mới được đếm.

Chưa có cơ sở bảo đảm lợi nhuận tương lai hoặc dùng thật. Khi có ứng viên qua đủ cổng, mới tạo native riêng, kiểm tra parity và dữ liệu xác nhận chưa dùng chọn tham số.

## File

`ALL_V5_V6_EXPERIMENTS.csv`:24 kịch bản; `ALL_V5_V6_WEEKS.csv`:6.264 dòng tuần; `ALL_V5_V6_YEARS.csv`:năm đầy đủ và phần năm; `ALL_V5_V6_TRADES.csv` và `NORMALIZED_TRADES`:sổ lệnh với phí đúng nhãn. ZIP chứa source/locks/kết quả, dùng lại rates.npz trong workspace.
'''
    (run/'RESEARCH_CHECKPOINT.md').write_text(md, encoding='utf-8')
    continuation = '''# Điểm tiếp tục sau v6

## Mục tiêu

ACTIVE, chưa đạt. Giữ Fresh v0.2; bản mới55–60% thắng,5–10 lệnh/tuần,tuần nào cũng có lệnh,edge sau phí. Không thu hẹp thành giữ Fresh hoặc viết báo cáo. Không đánh dấu hoàn thành/blocked chỉ vì khó hoặc kết quả âm.

## Đã xong

Đọc RESEARCH_CHECKPOINT.md,CUMULATIVE_REGISTRY.json,FEE_METADATA_ERRATUM.json và summary.json tại đây, kèm ../20261101_early_mean_v5/summary.json. V5:4 giả thuyết/12 phí;V6:4/12. Cộng ít nhất82/318. V5 EARLY_NO_CONTEXT/BASE1714 lệnh,36% thắng,PF.777,-248.94R,6.57/tuần,0 tuần trống. V6 FAILED_COMBO727 lệnh,48.97%,PF.687,-116.11R,2.79/tuần,13 tuần trống;FAILED_NO_CONTEXT949,47.21%,PF.678,-162.60R,3.64/tuần,5 tuần trống. Cả8 mới âm ở LOW/BASE/STRESS;selector2023–2026 đềuCASH.

106 tests qua. V5/V6 thêm12 prefix detector;V6 thêm8 prefix execution đều exact. Fresh hash không đổi. Không có process nghiên cứu đang chạy sau finalizer; không có native mới hoặc lịch sử chưa dùng để chọn tham số. Goal turn này là PROGRESS:2 hướng độc lập triển khai/thử/audit xong, đã loại bỏ hướng mới và sửa nhãn phí; chưa lặp impasse qua3 goal turns.

## Lỗi metadata phí

as_result kế thừa fees_status=ZERO và commission=0 dù wrapper đã trừ commission_r. P&L chính xác; tất cả24 kịch bản đã audit net=gross-fee vàfee=commission_price/risk. Log gốc/frozen sources giữ nguyên, bản sửa nhãn ở NORMALIZED_TRADES vàALL_V5_V6_TRADES.csv. FEE_METADATA_ERRATUM ghi rõ. Ở lab tương lai, đặt fees_status vàcommission cash đúng giả định trong adapter từ đầu; không coi log cũ là zero-cost. Chưa sửa engine đã khóa vì đây là metadata, không phải thay đổi kinh tế.

## Hướng kế tiếp

Không lặp M1 band-reclaim hoặc thất bại-reclaim với một dãyTP/threshold. Trước khi thêm cấu hình mới, đọc reports/GOLD_SCALP_RESEARCH_2026-10-23.md mụcBrian Shannon/AVWAP và nguồn gốc alphatrends.net; xác minh dữ liệu tick_volume vsreal_volume, điểm neo biết trước và cách tính VWAP proxy. Hướng AVWAP chưa có lab ở các lượt này; chỉ cân nhắc nếu cơ sở và data quality đủ. Không tạo footprint giả, không giả volume broker là giao dịch tập trung. Nếu không tìm được giả thuyết mới có cơ sở, ghi nhận nhu cầu dữ liệu xác nhận hoặc bằng chứng ngoài mẫu thay vì tối ưu vô hạn. Chưa khóa/thử/đếm bất kỳ cấu hình AVWAP nào.

Mỗi giả thuyết mới khóa trước kết quả, cộng số phép thử, backtest5năm với Bid/Ask/phí/gap/SL adverse-first; kiểm tra tuần0lệnh và số tuần5–10. Native/parity/dữ liệu xác nhận mới chỉ sau khi có ứng viên đủ chuẩn. Tất cả2021–2026 vàtuần26–30/10 đã xem, chỉ gọi hồi cứu.

Không đặt broker orders, đổi tài khoản chính, cài đè Fresh, Telegram/chat khác. Footprint chưa dùng,EA/LLM là giai đoạn sau. Gói quỹ/phí/clock/news/lot chưa xác minh. Giữ lịch heartbeat2giờ của cùng chat; không tạo trùng. Chỉ thông báo cải thiện đáng kể/lỗi quan trọng/yêu cầu input; không lặp báo cáo không thay đổi.

Tái chạy khi có lý do: python scripts/research_scalp_failed_reclaim_v6.py; python scripts/audit_scalp_failed_reclaim_v6.py; python scripts/finalize_scalp_failed_reclaim_v6.py. Cached results đã đầy đủ.
'''
    (run/'CONTINUATION.md').write_text(continuation, encoding='utf-8')
    files = [
        'scripts/research_scalp_failed_reclaim_v6.py', 'scripts/audit_scalp_failed_reclaim_v6.py',
        'scripts/finalize_scalp_failed_reclaim_v6.py', 'tests/test_research_scalp_failed_reclaim_v6.py',
        'scripts/research_scalp_early_mean_v5.py', 'scripts/audit_scalp_early_mean_v5.py',
        'scripts/finalize_scalp_early_mean_v5.py', 'tests/test_research_scalp_early_mean_v5.py',
        'scripts/research_scalp_range_v4.py', 'scripts/research_scalp_weekly_v3.py',
        'scripts/can_ho_tro_scalp_core.py', 'scripts/can_ho_tro_scalp_plan.py',
        'scripts/replay_can_ho_tro_scalp.py', 'scripts/prepare_can_ho_tro_scalp.py',
        'scripts/research_scalp_v2.py', 'scripts/replay_scalp_structure_lab.py',
        'tests/test_can_ho_tro_scalp.py', 'tests/test_research_scalp_weekly_v3.py',
        'tests/test_research_scalp_range_v4.py', 'tests/test_research_scalp_v2.py',
        'tests/test_scalp_structure_lab.py'] + f.w.FRESH_PATHS
    write_json(run/'CHECKPOINT_MANIFEST.json', dict(files={p: sha(root/p) for p in files},
               input_data_sha256=sha(f.w.BASE/'rates.npz'), goal_status='active', qualified=[],
               audit_counts=dict(tests=106, new_detector_prefixes=12, new_execution_prefixes=8,
                                 fee_scenarios=len(fee_checks), ledger_rows=len(ledger))))
    write_json(run/'CONTINUING_RESEARCH.json', dict(goal_status='active', qualified=[],
               automation_id='nghi-n-c-u-ti-p-edge-scalp-xauusd', same_thread=True,
               heartbeat_cadence='every2hours', process_running=False,
               next_direction='Review unimplemented AVWAP/tick-volume hypothesis with original sources and causal anchors before any new lock.'))
    bundle = run/'scalp_v6_checkpoint.zip'
    with zipfile.ZipFile(bundle, 'w', zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
        for folder in (f.early.RUN, run):
            for path in sorted(folder.rglob('*')):
                if path.is_file() and path.suffix != '.zip':
                    archive.write(path, path.relative_to(root))
        for file in files:
            archive.write(root/file, file)
    with zipfile.ZipFile(bundle) as archive:
        assert archive.testzip() is None
    print('V6 CHECKPOINT:82 hypotheses/318 scenarios;qualified0;106 tests;fee rows', len(ledger),
          'metadata-corrected fills', misleading, ';ZIP verified', bundle.stat().st_size, flush=True)


if __name__ == '__main__':
    main()
