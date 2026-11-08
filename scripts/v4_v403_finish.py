"""Package only the scoped v403 result after real-chart evidence is complete."""
from pathlib import Path
from datetime import datetime, timezone, timedelta
import json, csv, shutil, hashlib, zipfile

ROOT = Path(__file__).resolve().parents[1]
RUN = ROOT / 'reports/can_ho_tro_v4/20261102_v403_v1'
REL = ROOT / 'can_ho_tro_v4'
PORT = ROOT / 'reports/can_ho_tro_v4/20261102_m3a_v1/portable_terminal'
def sha(p): return hashlib.sha256(p.read_bytes()).hexdigest()
def dump(p, x): p.write_text(json.dumps(x, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')

assert json.loads((RUN/'CHART_AUDIT.json').read_text(encoding='utf-8'))['passed']
chart = RUN/'chart_final'
shutil.copytree(PORT/'MQL5/Files/v403_final_chart', chart, dirs_exist_ok=True)
for name in ['M1_visible.jpg', 'M5_visible.jpg']:
    assert (RUN/name).exists(), name
    shutil.copy2(RUN/name, chart/name)
for name in ['dashboard_expanded.jpg', 'dashboard_collapsed.jpg']:
    shutil.copy2(RUN/name, chart/name)
shutil.copytree(PORT/'MQL5/Files/V403_final2', RUN/'ledger_final', dirs_exist_ok=True)
log=(PORT/'MQL5/Logs/20261102.log').read_text(encoding='utf-16', errors='replace')
(RUN/'portable_v403.filtered.log').write_text('\n'.join(l for l in log.splitlines() if any(k in l for k in ['V403_', 'V4_RISK_WARNING', 'V4_LEDGER_RECOVERED']))+'\n',encoding='utf-8')
builds={}
for name in ['indicator_shipping', 'EA_final', 'restart_final', 'capture_tooltips', 'visible']:
    b=json.loads((RUN/('BUILD_'+name+'.json')).read_text());assert b['passed'];builds[name]=b
assert sha(REL/'MQL5/Indicators/duc_tri_can_ho_tro_v4.ex5')==builds['indicator_shipping']['binary_sha256']
assert sha(REL/'MQL5/Experts/CanHoTroV4_TesterEA.ex5')==builds['EA_final']['binary_sha256']
stages=list(csv.DictReader((chart/'stages.csv').open(encoding='utf-8-sig')))
cold=[s for s in stages if s['stage'].endswith('_first')]
audit=json.loads((RUN/'CHART_AUDIT.json').read_text(encoding='utf-8'))
result=dict(version='4.0.3', scope='claude_014 including both additions', passed=True,
    native_checks=59, native_failures=0, histogram_reference_signals=21, random_checks=20,
    unique_chart_stages=len(audit['stages']), arrows=21, zones=237, source_zones=21,
    stats_objects=0, cold_initialization=cold, real_terminal_D0E8209F_accessed=False,
    M3b_HIST_performance_rerun=False, M4_M5=False, awaiting_Claude_acceptance=True)
dump(RUN/'RESULTS_V403.json',result)
val=REL/'validation/v403';val.mkdir(exist_ok=False)
for folder in ['chart_final','ledger_final']:
    shutil.copytree(RUN/folder,val/folder)
for name in ['CHART_AUDIT.json','PARITY_20_RANDOM.json','RESULTS_V403.json','portable_v403.filtered.log']:
    shutil.copy2(RUN/name,val/name)
build=val/'build';build.mkdir()
for p in RUN.glob('BUILD_*.json'):shutil.copy2(p,build/p.name)
for p in RUN.glob('COMPILE_*.log'):shutil.copy2(p,build/p.name)
units=val/'native';units.mkdir()
for name in ['TestV403StorageRisk','TestV402IndicatorRisk','TestV401RiskStops']:
    shutil.copytree(RUN/'native'/name,units/name)
    for prefix,ext in [('BUILD_','.json'),('COMPILE_','.log')]:shutil.copy2(RUN/'native'/(prefix+name+ext),units/(prefix+name+ext))
sources=val/'sources';sources.mkdir()
for name in ['TestV403Chart.mq5','TestV403Visible.mq5','TestV403StorageRisk.mq5','TestV4Core.mq5','FixtureData.mqh','TestV402IndicatorRisk.mq5','TestV401RiskStops.mq5']:
    shutil.copy2(ROOT/'tests/v4'/name,sources/name)
for p in (ROOT/'scripts').glob('v4_v403*.py'):shutil.copy2(p,sources/p.name)
for name in ['TestV403Final.mq5','TestV403Restart.mq5']:shutil.copy2(RUN/name,sources/name)

payload=[dict(path=p.relative_to(REL).as_posix(),bytes=p.stat().st_size,sha256=sha(p)) for p in sorted(REL.rglob('*')) if p.is_file() and p!=REL/'MANIFEST.json']
dump(REL/'MANIFEST.json',dict(version='4.0.3',status='scoped checks passed; awaiting Claude acceptance',files=payload))
zp=RUN/'CanHoTro_v4.0.3.zip';assert not zp.exists()
with zipfile.ZipFile(zp,'w',zipfile.ZIP_DEFLATED) as z:
    for p in sorted(REL.rglob('*')):
        if p.is_file():z.write(p,'can_ho_tro_v4/'+p.relative_to(REL).as_posix())
ex=RUN/'extracted_verification';ex.mkdir()
with zipfile.ZipFile(zp) as z:
    assert z.testzip() is None
    assert all(not Path(n).is_absolute() and '..' not in Path(n).parts for n in z.namelist())
    z.extractall(ex)
actual=ex/'can_ho_tro_v4'
assert all(sha(p)==sha(actual/p.relative_to(REL)) for p in REL.rglob('*') if p.is_file())
assert all(sha(actual/f['path'])==f['sha256'] for f in payload)
dump(RUN/'ZIP_VERIFICATION.json',dict(passed=True,CRC_passed=True,files=len(payload)+1,mismatches=[],zip_sha256=sha(zp)))
evidence=[dict(path=p.relative_to(RUN).as_posix(),sha256=sha(p)) for p in sorted(RUN.rglob('*')) if p.is_file() and not any(k in p.parts for k in ['before','portable_terminal','extracted_verification']) and p.name not in ['MANIFEST.json','MANIFEST_VERIFICATION.json']]
dump(RUN/'MANIFEST.json',dict(version='4.0.3',zip=dict(path=zp.name,sha256=sha(zp)),files=evidence))
assert all(sha(RUN/f['path'])==f['sha256'] for f in evidence)
dump(RUN/'MANIFEST_VERIFICATION.json',dict(passed=True,files=len(evidence),mismatches=[]))
table='\n'.join('| '+s['stage'].replace('_first','')+' | 21 | 237 | 0 | '+s['init_meta'].split('|')[1]+' |' for s in cold)
base=RUN.as_posix()
proof='\n'.join('- ['+name+'](<'+(RUN/name).as_posix()+'>) — SHA-256 `'+sha(RUN/name)+'`' for name in ['CanHoTro_v4.0.3.zip','RESULTS_V403.json','CHART_AUDIT.json','PARITY_20_RANDOM.json','MANIFEST.json','ZIP_VERIFICATION.json','MANIFEST_VERIFICATION.json'])
photos='\n'.join('- ['+tf+'](<'+(chart/(tf+'_visible.jpg' if tf in ['M1','M5'] else tf+'_restart.png')).as_posix()+'>)' for tf in ['M1','M5','M15','M30','H1','H4','D1'])
report='''# codex_010 — Hiển thị v4.0.3 — ĐẠT kiểm tra phạm vi; chờ Claude nghiệm thu
Đã đọc README_QUY_UOC,claude_003,claude_014 gồm cả hai phần bổ sung cuối. Không đọc chat cũ.
Thời điểm: '''+datetime.now(timezone(timedelta(hours=7))).isoformat()+'''

## Đã làm

- Detector cố định H1/M5, ATR đúng hai khung, fingerprint bỏ khung hiển thị. Một writer giữ khóa file; các chart đọc chung ledger/checkpoint/zone snapshot/score, tiếp quản khi writer đóng. Không dùng ledger CHART của v402 để seed.
- Replay nhân quả toàn bộ M5 khả dụng trong 90 ngày, qua OnTimer tối đa32 observations/lượt với ngân sách khoảng50ms. Quét H1 khi closed H1 thay đổi; cache cùng prefix không đổi detector. Dòng tiến độ trên chart; replay im lặng cả BE lịch sử. Signal_id giữ nguyên công thức.
- Lưu vùng H1 lịch sử, active luôn vẽ; expired trong cửa sổ màu mờ. Vùng nguồn từ base start đến actual invalidation; active kéo tới H1 hiện tại+ExtendBars H1. Tooltip đầy đủ giờ server/hướng/entry/SL/TP1/TP2/ID+loại vùng/risk. Arrow đặt tại nến chart chứa confirm_bar_open M5; tooltip còn ghi signal_known_time.
- InpShowStatsPanel=false xóa M2_BG và toàn bộ M2_* cũ, CSV vẫn tự ghi. Nút CSV nhỏ ở chân dashboard; warning một dòng phía dưới. Dashboard mặc định thu gọn, nút+/− đã bấm bằng UI thật; chọn góc qua DashRight/InpDashBottom.
- Sửa nhánh reload: luôn vẽ cache kể cả không có M5 mới. Gỡ/gắn, đổi M1→H4→M1 và nhiều lần restart portable đều giữ21 signal_id.

## Kiểm indicator thật trên portable

Chỉ terminal reports/can_ho_tro_v4/20261102_m3a_v1/portable_terminal, tài khoản demo người dùng đã đăng nhập; không chọn hoặc thao tác terminal D0E8209F. Không gửi lệnh, không Strategy Tester/M4/M5.

Indicator EX5 sản xuất gắn trên7 chart đồng thời bằng template của lần gắn UI thật v402, loại toàn bộ drawings lưu sẵn, thêm input display mới; không dùng iCustom/callback adapter để giả chart. Controller chỉ điều khiển chart/thu objects. Trên cùng terminal, lượt HIST native riêng dùng source detector thật quét lại H1 mỗi M5, không chia chunk, không dùng cache, không ghi lệnh.

| Khung | Mũi tên | Vùng Z | M2 objects | Init lịch sử ms |
|---|---:|---:|---:|---:|
'''+table+'''

237 vùng là tập render từ zone-history ledger (active + expired trong cửa sổ),21 khung source riêng; không cộng source hai lần vào số vùng.17 stage CSV độc nhất cùng IDs, hình học vùng (giá/start/end), mapping nến và source lifetimes.31 dòng stage có thêm các lượt restart lặp. Trong lúc replay, giao diện cập nhật và chuyển chart được; không đo p99/max callback hoặc benchmark máy khác.

HIST độc lập cùng cửa sổ khớp21/21 signal theo thời gian/hướng/entry/SL/TP/source/anchor; mẫu ngẫu nhiên seed403 gồm20/20 khớp. Không dùng29 signal seed cũ của v402.59 native checks (storage23,risk indicator11 với oracle_calls0,risk/trail EA25) không lỗi; risk/scale/plan code và mọi giá trị preset chiến lược cũ giữ nguyên. Chỉ thêm5 input display/history.

### Ảnh từng khung

'''+photos+'''

Ảnh M1/M5 bổ sung lấy trực tiếp màn hình cửa sổ portable sau khi điều hướng tới tín hiệu28/10. ChartScreenShot offscreen1400×900 trước đó lấy sai viewport về cuối chart, nên không dùng hai PNG đó làm bằng chứng thấy arrow. M15–D1 dùng PNG chart thật có arrow/vùng. dashboard_expanded.jpg và dashboard_collapsed.jpg ghi thao tác nút thật.

## Bằng chứng và hash

'''+proof+'''

Compiler indicator shipping/EA/controller/native: `Result: 0 errors, 0 warnings`. Native: `{"checks":23,"failures":0}`, `{"checks":11,"failures":0,"oracle_calls":0}`, `{"checks":25,"failures":0}`. CHART_AUDIT passed; ZIP CRC và mọi hash sau giải nén đạt. Binary đóng gói khớp BUILD_indicator_shipping/BUILD_EA_final.

## Lệch và giới hạn

Chọn phát hành4.0.3 để giữ ZIP4.0.2 đã bàn giao. Các lượt phát triển đầu: template CRCRLF không load; ảnh chụp quá sớm khi replay còn chạy; reload không có bar mới bỏ vẽ; CSV tooltip xuống dòng không được FileWrite quote. Đã sửa và chạy gate cuối; bằng chứng thử đầu được giữ riêng, không tính là pass.

Không chạy lại M3b/full HIST lợi nhuận, forward/DST/Telegram, stress mất điện hoặc transaction nguyên tử giữa mọi file. Full dashboard cần chart đủ cao/giảm DashScale; mặc định thu gọn. Vùng/tín hiệu phụ thuộc lịch sử broker khả dụng. Source/display cache không phải xác nhận lợi thế giao dịch. Không có blocker phạm vi còn mở.

## Điểm dừng

Source/binary/preset/docs/validation ở can_ho_tro_v4; ZIP4.0.3, manifest và hash đã kiểm. Đã đóng portable sau kiểm. DỪNG, chờ Claude nghiệm thu; không M4/M5.
'''
(ROOT/'codex_outbox/codex_010_hien_thi.md').write_text(report,encoding='utf-8')
print('v4.0.3 ZIP',sha(zp),'files',len(payload)+1)
print('outbox codex_010_hien_thi.md written; stop')
