"""Render and independently check the v3.01 forensic audit artifacts."""
import csv
import hashlib
import json
import math
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
RUN=ROOT/'reports/gold_v301_audit/20261101'


def read(name):return json.loads((RUN/name).read_text(encoding='utf-8'))


def link(relative,pattern):
    path=ROOT/relative
    n=next(i for i,line in enumerate(path.read_text(encoding='utf-8-sig').splitlines(),1) if pattern in line)
    return f'[{path.name}:{n}](<{path.as_posix()}:{n}>)'


def main():
    r=read('REPRODUCTION.json');a=read('COHORT_ACCOUNTING.json');e=read('EXECUTION_AUDIT.json');p=read('PREFIX_AUDIT.json');m=read('SOURCE_MANIFEST.json')
    checks={}
    for key in ['M5_ADVERSE_FIRST','M5_FAVORABLE_FIRST','M1_ADVERSE_FIRST','M1_FAVORABLE_FIRST']:
        with (RUN/f'trades_{key}.csv').open(encoding='utf-8-sig') as f:rows=list(csv.DictReader(f))
        closed=[x for x in rows if x['status']=='CLOSED'];values=[float(x['r']) for x in closed]
        assert len(closed)==e[key]['all']['n']
        assert math.isclose(math.fsum(values),e[key]['all']['net_R'],abs_tol=1e-8)
        kz=[x for x in closed if x['kz']=='True']
        assert len(kz)==e[key]['killzones']['n']
        assert math.isclose(math.fsum(float(x['r']) for x in kz),e[key]['killzones']['net_R'],abs_tol=1e-8)
        for cost in [.2,.5,1.]:
            net=math.fsum(float(x['r'])-cost/float(x['risk']) for x in kz)
            assert math.isclose(net,e[key]['costs'][str(cost)]['killzones']['net_R'],abs_tol=1e-8)
        assert all(float(x['entry_time'])<float(x['exit_time']) and float(x['risk'])>0 for x in closed)
        checks[key]=dict(rows=len(closed),status='passed')
    for name in ['engine','builder','data','indicator','binary']:
        assert hashlib.sha256(Path(m[name]['path']).read_bytes()).hexdigest()==m[name]['sha256']
    assert hashlib.sha256((ROOT/'scripts/audit_gold_v301.py').read_bytes()).hexdigest()==m['audit_script_sha256']
    assert r['headline_counts_and_PnL_match_report']
    assert a['ALL']['limit_unfilled_count']==a['ALL']['limit_zero_R_count']==421
    v=dict(status='passed',ledger_checks=checks,source_hashes_match=True,headline_reproduction=True,
           synthetic_execution_checks=len(read('EXECUTION_COUNTEREXAMPLES.json')),
           synthetic_future_flip_rejection_reproduced=p['synthetic_witness']['flip_visible_on_prefix'] and not p['synthetic_witness']['flip_visible_after_future_break'],
           targeted_historical_prefix_witnesses=len(p['targeted_historical_witnesses']),
           limitations=['Same historically selected signal cohort, H1 timing/future-selection defects not corrected in the execution diagnostics.',
                        'No real tick, broker Bid/Ask, native signal parity, full causal replay or FTMO portfolio test.'])
    (RUN/'VERIFICATION.json').write_text(json.dumps(v,indent=2)+'\n',encoding='utf-8')
    lines=['# Kiểm tra lại báo cáo XAUUSD M5 v3.01','',
           '**Đã tái lập đúng các số lợi nhuận gộp +122R / +67,75R bằng engine Python gốc. Đây là một ứng viên nghiên cứu có kết quả dương gộp; báo cáo hiện chưa xác nhận được lợi nhuận có thể giao dịch hoặc khả năng pass FTMO.**','',
           '## 1. Những gì tái lập được','',
           f"Ba bản engine trong dự án có cùng hash; lượt kiểm tra chạy bản scripts/run_5year_backtest_v301.py với snapshot MT5 lưu ngày 25/10/2026, cắt về 23/10/2021–23/10/2026. Lượt tái lập có {r['data_rows']['m5']:,} nến M5, {r['data_rows']['h1']:,} nến H1, {r['zones']:,} vùng. Báo cáo cũ ghi 352.252 M5 / 31.480 H1 / 3.219 vùng; snapshot dữ liệu gốc của lần đó không được giữ trong thư mục báo cáo. Vì vậy dữ liệu không giống từng byte, nhưng toàn bộ số tín hiệu và kết quả bốn model dưới đây khớp.",
           '', '| Model | Lệnh toàn phiên | R toàn phiên | Lệnh trong giờ lọc | R trong giờ lọc |',
           '|---|---:|---:|---:|---:|']
    for name,key in [('Distal cũ','r_old'),('Market Hybrid','r_mkt_hybrid'),('Market Pure R:R','r_mkt_rr'),('Limit 50% Hybrid','r_lmt_hybrid')]:
        row=r['metrics'][key];lines.append(f"| {name} | {row['all']['total_trades']} | {row['all']['total_r']:+.2f} | {row['killzones']['total_trades']} | {row['killzones']['total_r']:+.2f} |")
    lines+=['',
            'File duc_tri_can_ho_tro.ex5 hiện có đúng 119.190 bytes. Engine tạo báo cáo là một mô phỏng Python, không chạy file EX5 và không chứng minh tín hiệu Python trùng indicator native. Biên dịch thành công kiểm tra cú pháp/build; cần kiểm chứng hành vi riêng.',
            '', '## 2. Lợi nhuận gộp chịu được bao nhiêu chi phí?','',
            f"Market Pure R:R trong giờ lọc: 881 lệnh, +67,75R, PF 1,1543; bình quân **{a['KILLZONES']['mean_R']:.5f}R/lệnh**. Khoảng SL trung bình thực sự {a['KILLZONES']['mean_stop_distance']:.3f} USD giá Vàng, thay vì khoảng 7 USD như diễn giải cũ. Toàn phiên: 1.818 lệnh, +122R, bình quân {a['ALL']['mean_R']:.5f}R/lệnh.",
            '', '| Tổng chi phí quy đổi sang chênh lệch giá Vàng mỗi lệnh | R toàn phiên | R trong giờ lọc |',
            '|---|---:|---:|']
    for cost in ['0.0','0.2','0.5','1.0']:
        lines.append(f"| {cost} USD giá | {a['ALL']['cost_sensitivity'][cost]:+.2f} | {a['KILLZONES']['cost_sensitivity'][cost]:+.2f} |")
    lines+=['',
            f"Đây là phép trừ kế toán trên cùng bảng lệnh: R sau phí = R gốc − chi phí / khoảng SL ban đầu. Ngưỡng xóa hết lợi nhuận gộp là khoảng **{a['KILLZONES']['flat_cost_per_unit_position_erasing_legacy_profit']:.3f} USD giá** trong giờ lọc, và **{a['ALL']['flat_cost_per_unit_position_erasing_legacy_profit']:.3f} USD giá** toàn phiên. Không nhầm với USD tiền phí cho một lot: cần quy đổi theo contract size/khối lượng. Đây không phải báo giá spread hoặc commission FTMO đã xác minh. Phép trừ này chưa mô hình hóa việc phí làm đổi entry, TP/SL, số lệnh, gap hoặc swap.",
            '', '## 3. Kiểm tra execution: không quy toàn bộ lãi cho lỗi intrabar','',
            'Trên đúng 1.818 tín hiệu được engine cũ chọn, chuyển entry sang open M5 kế tiếp; giữ SL cấu trúc; tính lại TP1=1,5R và TP2=2R theo khoảng entry–SL thực tế. Đóng 50/50, BE tại +6 giá hoặc khi TP1 khớp, stop BE tại entry ±0,1. Gap SL dùng open thực có thể lỗ hơn −1R. Hết thời hạn định giá phần vị thế còn lại.',
            '', '| Phương án trên cùng 881 tín hiệu giờ lọc | R trước phí | R sau trừ 0,2 giá | R sau trừ 0,5 giá | DD cộng dồn R đã đóng |',
            '|---|---:|---:|---:|---:|',
            f"| Engine gốc | +67.75 | {a['KILLZONES']['cost_sensitivity']['0.2']:+.2f} | {a['KILLZONES']['cost_sensitivity']['0.5']:+.2f} | 16.50 |"]
    for name,label in [('M5_ADVERSE_FIRST','M5: O → cực trị bất lợi → cực trị thuận → C'),('M5_FAVORABLE_FIRST','M5: O → cực trị thuận → cực trị bất lợi → C')]:
        x=e[name];lines.append(f"| {label} | {x['killzones']['net_R']:+.2f} | {x['costs']['0.2']['killzones']['net_R']:+.2f} | {x['costs']['0.5']['killzones']['net_R']:+.2f} | {x['killzones']['max_closed_R_drawdown']:.2f} |")
    lines+=['',
            '**Phần lãi trước phí vẫn dương trong cả hai đường OHLC đã thử.** Hai đường này là các giả định cụ thể, không phải cận tốt/xấu tuyệt đối và không phải thứ tự tick lịch sử. BE có thể khiến đi tới cực trị thuận trước lại thoát sớm hơn, nên kết quả hai đường không luôn xếp theo tên gọi.',
            'Các bảng này vẫn dùng tập tín hiệu H1 cũ có vấn đề thông tin tương lai; chúng chỉ tách ảnh hưởng execution, không xác nhận lợi thế của chiến lược sau khi sửa toàn bộ lỗi. Số dương nhỏ do BE +0,1 được tính là R dương, khác nhãn BE=0 của engine cũ; không so win rate hai cách định nghĩa như cùng một thước đo.',
            '', '### Đối chiếu M1 bổ sung','',
            f"Theo điều kiện đủ năm nến M1 bên trong từng nến M5 của toàn bộ 288-bar execution window, chỉ {e['M1_ADVERSE_FIRST']['all']['n']} / 1.818 tín hiệu đủ dữ liệu; trong giờ lọc có {e['M1_ADVERSE_FIRST']['killzones']['n']} / 881. Loại {e['M1_coverage']['excluded_signals']} trường hợp có phút thiếu và giữ danh sách. Khoảng trống giữa các nến M5 được giữ nguyên, không nội suy.",
            f"Cùng 181 tín hiệu giờ lọc: M5 hai đường đều +{e['M5_ADVERSE_FIRST']['paired_with_M1_killzones']['net_R']:.2f}R; M1 hai đường lần lượt +{e['M1_ADVERSE_FIRST']['killzones']['net_R']:.2f}R và +{e['M1_FAVORABLE_FIRST']['killzones']['net_R']:.2f}R trước phí. Không so 181 tín hiệu này trực tiếp với toàn bộ 881 hoặc coi mẫu đủ phút là đại diện cho toàn kỳ. M1 vẫn là OHLC Bid, chưa phải tick Bid/Ask lịch sử.",
            '', '## 4. Các lỗi hoặc giới hạn đã có bằng chứng','',
            '### 4.1. Vùng H1 dùng thông tin chưa có tại thời điểm quyết định','',
            f"Builder lấy đủ OHLC của nến departure H1 cuối nhưng timeActive đặt tại **giờ mở** của chính nến đó: {link('scripts/test_m5_scanning_speed.py','timeActive = times_h1')}. Có {a['ALL']['premature_h1_activation_signals']} / 1.818 tín hiệu được nhận trong giờ xác nhận H1 chưa đóng, gồm {a['KILLZONES']['premature_h1_activation_signals']} / 881 tín hiệu giờ lọc. Điều này chưa chứng minh tất cả các tín hiệu ấy sẽ biến mất khi sửa; cần tái phát sinh tín hiệu theo dòng thời gian.",
            f"Vùng FLIP chỉ được thêm nếu không bị phá trong phần tương lai mà vòng lặp đã xem: {link('scripts/test_m5_scanning_speed.py','if not fBroken:')}. Fixture đã tái hiện việc một flip xuất hiện khi có 30 nến nhưng biến mất khỏi quá khứ khi nối thêm bốn nến có lần phá ở nến 31. Ba mốc lịch sử đầu năm 2023/2024/2025 ban đầu không tìm được nhân chứng; kiểm tra nhắm vào nhánh bị loại trong dữ liệu thật tìm được {len(p['targeted_historical_witnesses'])} ví dụ. Tất cả được giữ trong PREFIX_AUDIT.json.",
            f"Trong tập cũ, FLIP đóng góp {a['KILLZONES']['zone_groups']['FLIP']['gross_R']:+.2f}R từ {a['KILLZONES']['zone_groups']['FLIP']['n']} lệnh giờ lọc; vùng thường đóng góp {a['KILLZONES']['zone_groups']['REGULAR']['gross_R']:+.2f}R từ {a['KILLZONES']['zone_groups']['REGULAR']['n']} lệnh. Không được suy ra rằng bỏ FLIP hoặc giữ vùng thường sẽ tái tạo cùng tập lệnh trong một detector đã sửa.",
            '', '### 4.2. Thứ tự TP/BE/SL và hết hạn','',
            f"Pure RR kiểm tra high/low thuận chiều để kích BE/TP trước nhánh SL: {link('scripts/run_5year_backtest_v301.py','# Market Pure RR (')}. Ví dụ BUY entry 100, SL 95, TP1 107,5, TP2 110; nến H=111/L=94 được engine ghi +1,75R. Nếu giá đi xuống 94 trước, kết quả là −1R. Nến chạm +6 rồi chạm SL cũ được tính BE trong engine dù thứ tự chưa biết.",
            'Khi hết 288 nến mà không chạm SL/BE/TP, engine vẫn gán −1R. Fixture entry 100, SL 95, kết thúc ở 100,5 đáng ra +0,1R trước phí lại được ghi −1R. Một số lỗi có thể làm xấu kết quả, nên không mặc định mọi khác biệt đều thổi phồng lợi nhuận. Ngoài ra, 288 quan sát M5 có thể kéo dài qua cuối tuần/khoảng thiếu, không luôn bằng 24 giờ đồng hồ.',
            '', '### 4.3. Entry và giá giao dịch','',
            f"Engine dùng close nến xác nhận làm entry: {link('scripts/run_5year_backtest_v301.py','entryMkt = closes_m5[cIdx]')}. Trong {a['KILLZONES']['non_next_open_price_entries']} / 881 tín hiệu giờ lọc, open nến kế tiếp khác giá close ấy. Chưa có spread Bid/Ask, slippage, commission và swap trong kết quả gốc. Khoản BE đệm 0,1 giá không đủ để khẳng định bù mọi chi phí.",
            'MetaTrader phân biệt tick thật, tick sinh từ M1 và giao dịch theo Bid/Ask; nến OHLC không tự cung cấp thứ tự chạm các mức. [Tài liệu chính thức MetaTrader](https://www.metatrader5.com/en/terminal/help/algotrading/tick_generation).',
            '', '### 4.4. Lệnh chưa khớp bị ghi hòa vốn','',
            f"Toàn bộ {a['ALL']['limit_zero_R_count']} trường hợp 0R của Limit là **chưa khớp**, tương tự {a['KILLZONES']['limit_zero_R_count']} trong giờ lọc. Thực tế chỉ {a['ALL']['limit_filled_count']} / 1.818 và {a['KILLZONES']['limit_filled_count']} / 881 trường hợp khớp Limit. Không thể dùng 421 hoặc 213 để mô tả số vị thế đã được BE cứu.",
            '', '### 4.5. Những nhận xét vượt quá kết quả đã đo','',
            '- Năm 2026 Pure RR giờ lọc −1,50R; 2021 chỉ có từ cuối tháng 10. Bốn năm lịch đầy đủ 2022–2025 dương gộp theo engine cũ. Câu “dương tất cả các năm” không đúng.',
            '- Giảm 24,5R xuống 16,5R tương đương giảm khoảng 32,65% mức DD cũ; đây không phải tài khoản drawdown 33%. DD R theo tín hiệu cũng chưa là equity DD tài khoản.',
            '- Baseline cũ có 2.601 tín hiệu và SL khác; model mới có 1.818 tín hiệu. Chưa có đối chứng cùng entry/SL với BE bật/tắt để quy toàn bộ phần giảm DD cho BE hoặc khẳng định 193 BE đều sẽ mất 1R nếu giữ lệnh.',
            '- Engine quét OHLC, không đo khối lượng giao dịch tổ chức hay order flow. Những giải thích “dòng tiền tổ chức đẩy đi thẳng” và “Limit âm do fakeout” là giả thuyết giải thích, chưa được phép kiểm tra này chứng minh.',
            '- Hàm giờ lọc nhận các giờ 8–12 và 13–17, tương đương 08:00–17:59 theo nhãn thời gian feed. Chưa kiểm chứng ánh xạ server/UTC và DST London/New York.',
            '- Chọn model tốt nhất sau khi xem cùng năm năm dữ liệu là lựa chọn trong mẫu. Chưa có kết quả giao dịch mới độc lập cho cấu hình được chọn.',
            '', '## 5. Ý nghĩa đối với mục tiêu FTMO','',
            'Tỷ lệ TP 37,8% không tự loại chiến lược khi payout lớn hơn rủi ro. Điều cần xác nhận là kỳ vọng sau toàn bộ phí và đường equity có thể triển khai. Báo cáo cộng R của từng tín hiệu độc lập, có thể chồng vị thế; chưa đặt risk/lot, giới hạn rủi ro tổng, margin hoặc tính equity cùng các vị thế mở.',
            'Benchmark [FTMO CFD 2-Step](https://ftmo.com/en/trading-objectives/) cần +10% rồi +5%, giới hạn lỗ equity ngày 5%, tổng 10% và ít nhất bốn ngày mỗi phase. Các số +67,75R và DD 16,5R chưa đủ để tính xác suất hoặc khẳng định pass.',
            '', '## 6. Đề xuất tiếp theo cho chính ứng viên này','',
            'Giữ nguyên định nghĩa setup S/D–sweep–CHoCH và các mức RR/BE đã chọn, sửa detector H1 để chỉ dùng dữ liệu đã đóng và giữ được lịch sử vùng có thể biết lúc đó. Kiểm tra detector khi nối thêm dữ liệu phải giữ nguyên các tín hiệu cũ. Sau đó đối chiếu tín hiệu với native indicator, replay trên Bid/Ask có nguồn rõ ràng, và tính một đường equity theo risk/tổng vị thế đã khóa. Chưa thêm bộ lọc, footprint hoặc tối ưu tham số để cứu kết quả.',
            'Nếu phần lãi còn lại sống được qua các bước này và dữ liệu mới, đây là nền tảng cụ thể để tiếp tục. Hiện tại kết luận phù hợp là **lợi nhuận gộp tái lập được, lợi nhuận giao dịch thực và khả năng pass quỹ còn chưa xác nhận**.',
            '', '## Tệp và tái lập','',
            '- REPRODUCTION.json, legacy_engine_stdout.log, legacy_signals.json: engine gốc và bảng tín hiệu.',
            '- COHORT_ACCOUNTING.json: chi phí hòa vốn, lệnh chưa khớp, nhóm vùng và điểm entry.',
            '- PREFIX_AUDIT.json, EXECUTION_COUNTEREXAMPLES.json: lỗi có ví dụ tái hiện.',
            '- EXECUTION_AUDIT.json, trades_M5_*.csv, trades_M1_*.csv, m1_excluded_signals.csv: tất cả giả định execution và mẫu thiếu.',
            '- SOURCE_MANIFEST.json và VERIFICATION.json: hash nguồn/dữ liệu và kiểm tra đối soát.',
            '- Chạy: python scripts/audit_gold_v301.py, sau đó python scripts/report_gold_v301_audit.py. Bản nguồn/EX5 gốc không bị sửa.','']
    (RUN/'REPORT.md').write_text('\n'.join(lines),encoding='utf-8')
    print(json.dumps(dict(report=str(RUN/'REPORT.md'),verification=v),ensure_ascii=True))


if __name__=='__main__':main()
