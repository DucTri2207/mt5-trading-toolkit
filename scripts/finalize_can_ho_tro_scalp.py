"""Verify completed research artifacts and produce the review handoff."""
import hashlib
import json
from pathlib import Path
import shutil
import zipfile

ROOT = Path(__file__).resolve().parents[1]
RUN = ROOT / 'reports/can_ho_tro_scalp/20261025_v1'

def read(path):
    return json.loads(path.read_text(encoding='utf-8'))

def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()

def write(name, value):
    (RUN / name).write_text(json.dumps(value, indent=2, ensure_ascii=False), encoding='utf-8')

checks = {}
for name in ['DETECTOR_PARITY', 'MARKET_PLAN_PARITY', 'PREFIX_PARITY']:
    obj = read(RUN / (name + '.json'))
    assert obj['passed'], name
    checks[name] = len(obj['checks'])
assert read(RUN / 'DATA_AUDIT.json')['passed_ohlc']
assert 'Ran 35 tests' in (RUN / 'python_tests.log').read_text()
assert '\nOK' in (RUN / 'python_tests.log').read_text()
checks['python_tests'] = 35
baseline = read(next((ROOT / 'thông tin nghiên cứu').rglob('BASELINE_TRUOC_LAP_KE_HOACH.json')))
for item in baseline['files']:
    assert sha(ROOT / item['relative_path']) == item['sha256'], item['relative_path']
checks['protected_files_unchanged'] = len(baseline['files'])
for name in ['indicator_build_manifest.json', 'oracle_build_manifest.json', 'native_chart_build_manifest.json']:
    obj = read(RUN / name)
    obj = obj.get('build', obj)
    for field in ['source', 'ex5']:
        assert sha(Path(obj[field])) == obj[field + '_sha256'], name + field
    assert obj['diagnostics'] == '0 errors, 0 warnings'
fixture = ROOT / 'reports/scalp_structure_lab/20261025_pilot_v1/fixture_terminal/MQL5/Files/can_ho_tro_scalp_v1'
native = read(fixture / 'native_chart_result.json')
assert native['failures'] == 0 and native['same_candidate_keys']
for name in ['native_chart_result.json', 'native_m5.png', 'native_h1.png', 'state_roundtrip.json']:
    shutil.copy2(fixture / name, RUN / 'qa' / name)
checks['native_chart'] = native
rows = read(RUN / 'summary_all.json')['rows']
assert len(rows) == 48
serial = [r for r in rows if r['mode'] == 'serial']
assert len(serial) == 24
for row in read(RUN / 'STABILITY_DIAGNOSTICS.json')['rows']:
    match = next(r for r in serial if all(r[k] == row[k] for k in ['name', 'cost', 'path']))
    assert match['metrics'] == row['metrics']
table = ['| Cấu hình | Chi phí | Đường giá | Lệnh | Thắng | PF | Tổng R |', '|---|---|---|---:|---:|---:|---:|']
for row in serial:
    m = row['metrics']
    table.append(f"| {row['name']} | {row['cost']} | {row['path']} | {m['n']} | {m['win_rate']:.1f}% | {m['pf']:.3f} | {m['total_r']:+.2f} |")
report = '''# Kết quả triển khai và backtest scalp lab 0.1

Đã hoàn thành bản lab và backtest 5 năm. Chưa cấu hình nào đạt ngưỡng PF 1.5 trong kế hoạch; chưa đủ cơ sở khuyến nghị giao dịch thực tế. Trailing stop có tổng R cao hơn ở chi phí thấp, nhưng lợi thế giảm gần hết khi tăng chi phí. Bộ lọc room và entry retest không cải thiện trong định nghĩa đã khóa.

## Phạm vi triển khai

Giữ chuỗi vùng H1 → sweep/reclaim → xác nhận M5 từ source cũ. Lab dùng tín hiệu nến đã đóng, kiểm tra mức giá đã tồn tại trước sweep, tách candidate khỏi plan đang quản lý và khử trùng lặp theo identity. Giá khớp và thoát dùng đúng Bid/Ask; R0 giữ nguyên; SL trailing chỉ dời một chiều sau pivot xác nhận và có hiệu lực từ quote kế tiếp. Có quản lý pending BODY50, expiry, room thực tế, persistence và kiểm tra reload M5/H1.

Source và binary gốc cùng các file bảo vệ đã được kiểm tra checksum. Lab dùng tên riêng `duc_tri_can_ho_tro_scalp_lab`; virtual plans mặc định tắt. Đây là indicator nghiên cứu, không có lệnh đặt giao dịch broker. Chưa cài thay bản chính trên MT5.

## Dữ liệu và giả định

XAUUSD, cửa sổ 2021-10-25 đến trước 2026-10-25; quote cuối 2026-10-23. Có 4,783 nến H1 warmup trước cửa sổ. Dữ liệu: 2,043,723 M1; 409,219 M5; 34,214 H1. Tổng hợp M1 khớp OHLC M5/H1 hoàn toàn.

Replay dùng OHLC M1 và chi phí giả lập, không phải real tick backtest. C_A: spread 0.20, slippage 0; C_B: spread 0.30, slippage 1 tick; C_C: spread 0.45, slippage 5 ticks. Tick 0.01; commission và swap giả định 0. T05/T15 là TP 0.5R/1.5R, đóng sau tối đa 6 giờ; TS là trailing theo cấu trúc với giới hạn thời gian. R là đơn vị rủi ro ban đầu, không phải phần trăm tài khoản. Serial chỉ quản lý một plan tại một thời điểm; paired diagnostic chỉ dùng so sánh cùng candidate.

## Kết quả serial

'''
report += '\n'.join(table)
report += '''

## Kiểm chứng và giới hạn

35 kiểm thử Python đạt; 23 kiểm tra runtime MQL không lỗi; 7 nhóm detector parity và 96 nhóm trade/stop parity đạt. Bốn mốc prefix kiểm tra tính nhất quán khi cắt dữ liệu đạt. Native chart M5/H1 có 36 kiểm tra không lỗi, cùng candidate và reload giữ trạng thái.

Đã đối chiếu iATR native: dùng rolling mean TR thay vì Wilder. Đã tách ảnh hưởng bar 0 trong detector cũ khỏi C0 closed-only; không coi các con số baseline nghiên cứu cũ là P&L literal của MQL. Báo cáo raw và planned-price parity được lưu riêng.

TS ở C_A có modeled equity drawdown khoảng 13.61R; lợi thế expectancy so với T05 có khoảng tin cậy bootstrap 95% chứa 0. Khi chuyển C_C, TS còn +0.42R, PF 1.002 trước commission/swap. Không có bằng chứng đủ chắc cho nâng cấp lợi nhuận.

Cửa sổ đã được xem trong nghiên cứu nên là đánh giá hồi cứu, không phải tập OOS nguyên vẹn. Các phút thưa không thể phân biệt chắc giữa không có cập nhật giá và thiếu history. Ánh xạ giờ feed sang London/New York và ràng buộc broker lịch sử chưa xác minh. Chi phí được mô hình hóa theo các kịch bản cố định.

## Bàn giao

Code, binary, include, scripts, tests, log, kết quả từng trade, parity và QA được đóng trong `can_ho_tro_scalp_lab_0_1.zip`. Dữ liệu lớn `rates.npz` và `equity_curves.npz` giữ trong thư mục run; checksum dữ liệu nằm trong `data_manifest.json`. Tham số và seed ở `EXPERIMENT_LOCK.json`; thống kê tháng/năm và bootstrap ở `STABILITY_DIAGNOSTICS.json`. Kết luận kinh tế: chưa đạt; giữ lab để nghiên cứu, chưa chuyển sang EA giao dịch.
'''
(RUN / 'FINAL_RESEARCH_REPORT.md').write_text(report, encoding='utf-8')
write('FINAL_VERIFICATION.json', {'implementation_complete': True, 'five_year_backtest_complete': True, 'economic_gate_passed': False, 'checks': checks, 'result_rows': len(rows)})
files = [ROOT / 'duc_tri_can_ho_tro_scalp_lab.mq5', ROOT / 'duc_tri_can_ho_tro_scalp_lab.ex5']
files += list((ROOT / 'Include').glob('CanHoTroScalp*.mqh'))
files += [p for p in (ROOT / 'scripts').iterdir() if p.is_file() and 'can_ho_tro' in p.name]
files += [p for p in (ROOT / 'tests').rglob('*') if p.is_file() and 'canhotro' in p.name.lower()]
files += [ROOT / 'tests/test_can_ho_tro_scalp.py']
files += [p for p in RUN.iterdir() if p.is_file() and p.suffix in ['.json', '.md', '.log', '.csv']]
files += [p for p in (RUN / 'qa').iterdir() if p.is_file()]
files = sorted(set(files))
archive = RUN / 'can_ho_tro_scalp_lab_0_1.zip'
with zipfile.ZipFile(archive, 'w', zipfile.ZIP_DEFLATED) as z:
    for p in files:
        z.write(p, p.relative_to(ROOT).as_posix())
    z.writestr('CHECKSUMS.json', json.dumps({p.relative_to(ROOT).as_posix(): sha(p) for p in files}, indent=2))
with zipfile.ZipFile(archive) as z:
    assert z.testzip() is None
write('PACKAGE_MANIFEST.json', {'archive': archive.name, 'sha256': sha(archive), 'files': len(files), 'zip_integrity_passed': True})
print(json.dumps({'complete': True, 'economic_gate_passed': False, 'files': len(files), 'zip_bytes': archive.stat().st_size}))
