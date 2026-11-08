# -*- coding: utf-8 -*-
"""Summarize observed M3b only; does not optimize or launch tests."""
from pathlib import Path
import csv,json,hashlib,shutil,re
from datetime import datetime,timezone,timedelta
ROOT=Path(__file__).resolve().parents[1];RUN=ROOT/'reports/can_ho_tro_v4/20261102_m3b_v2';REL=ROOT/'can_ho_tro_v4'
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def dump(p,x):p.write_text(json.dumps(x,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
def rows(p):
    with p.open(encoding='utf-8-sig') as f:return list(csv.DictReader(f))
ind=RUN/'indicator_parity/Agent-127.0.0.1-3000'
ea=RUN/'tp1r_final/Agent-127.0.0.1-3000/Tester'
a=rows(ea/'signals_XAUUSD.csv');b=rows(ind/'signals_XAUUSD.csv')
diag=dict(x.split('=',1) for x in (ind/'indicator_diagnostics.txt').read_text().split())
assert diag['io_failed']=='0' and len(a)==len(b)==0
assert int(diag['confirm'])==341 and int(diag['risk_rejected'])==260 and int(diag['rr_rejected'])==81
parity=dict(ea_signals=len(a),indicator_signals=len(b),missing_in_ea=[],extra_in_ea=[],equal=True,positive_events_validated=False,adapter='Actual indicator OnInit/OnCalculate/OnTimer/OnDeinit through tester EA adapter; not visual tester; Telegram config helpers stubbed, UI/notifications disabled only',indicator_diagnostics=diag)
dump(RUN/'BROKER_INDICATOR_PARITY.json',parity)
result=json.loads((RUN/'M3B_RESULTS.json').read_text());result['indicator_parity']=parity
result['hist_comparison']=json.loads((RUN/'HIST_M2_SLICE_SUMMARY.json').read_text());result['hist_comparison']['common_interval_server']=['2026.07.01 00:00','2026.10.23 23:00'];result['hist_comparison']['common_interval_ea_signals']=0
result['hist_comparison']['frozen_last_m5_open']=1792796100
result['hist_comparison']['mode_identification']='M2 signal_id final suffix _0 EXIT_1R / _1 TRAIL, not row order.'
dump(RUN/'M3B_RESULTS.json',result)
# Refresh working source manifest; accepted M3a ZIP stays immutable.
dump(REL/'MANIFEST.json',dict(version='4.0',scope='M3b diagnostics working files; accepted M3a ZIP unchanged',files=[dict(path=p.relative_to(REL).as_posix(),bytes=p.stat().st_size,sha256=sha(p)) for p in sorted(REL.rglob('*')) if p.is_file() and p.name!='MANIFEST.json']))
patch=RUN/'patch';shutil.copytree(REL,patch)
for kind,p in [('EA',patch/'MQL5/Experts/CanHoTroV4_TesterEA.ex5'),('Indicator',patch/'MQL5/Indicators/duc_tri_can_ho_tro_v4.ex5')]:
    build=json.loads((RUN/('BUILD_final.json' if kind=='EA' else 'BUILD_Indicator_final.json')).read_text());assert sha(p)==build['binary_sha256']
oldzip=ROOT/'reports/can_ho_tro_v4/20261102_m3a_v1/CanHoTro_v4.0_M3a.zip'
assert sha(oldzip)=='f515b8565e8b63cb64c27b8b12dea6e4457ec0d4190dd9fa330d17e6c32cdbf6'
report="""# M3b — Đã chạy; CHƯA ĐẠT kiểm chứng khớp lệnh B0v4

Hai rule mặc định chạy xong trên tick thật nhưng 0 candidate/0 signal/0 trade. Không có bằng chứng lỗi adapter làm mất tín hiệu: toàn bộ xác nhận bị loại đúng điều kiện SL/TP/RR đã khóa. Không thay preset để tạo lệnh. M3b chưa xác minh được execution/commission/slippage/exit ledger có giao dịch hoặc parity sự kiện dương. Không làm M4/M5.

## Nguyên nhân, chứng cứ
- MQL5 data/ATR ready: cả bốn bộ đếm H1/M5 rates/ATR not-ready =0, không FAIL_CLOSED, không SKIPPED, không REJECTED order; file events chỉ header vì chưa đến bước submit.
- 67.077 lượt observe; replay spread chặn43.896; 443.039 zone eligible,18.426 POI,13.131 sweep,341 xác nhận theo vùng (không nhất thiết341 bar độc lập).
- 260/341 bị risk_price>10 (100pips ×0.1). Risk thực của nhóm10.074357…107.409786.
- 81/341 còn lại risk_price4.356357…9.971286. TP1 HYBRID60pips=6; MinRR1.5 cần risk<=4. Toàn bộ81 có RR1<1.5, không thành candidate. REJECTION_ANALYSIS.json + rejected_confirmations.csv có từng trường hợp; assert điều kiện từng dòng PASS.
- Lượt riêng MaxSpreadPrice1.2, giữ mọi input khác: 0 spread blocked,343 xác nhận,260 risk reject+83 RR reject, vẫn0 candidate. Đây là chẩn đoán theo claude_009, không phải baseline hay đề xuất preset, không sửa ea_default.set.
- M3a native profile dùng TP RR, market confirm và reference=false, nên1.393 tín hiệu fixture không dự báo số mặc định HYBRID trên broker. Không thay native số liệu cũ.

## Chạy thật
Terminal portable được chỉ định, người dùng đã đăng nhập; Codex không đọc/sửa/copy config account hoặc đăng nhập. Server MetaQuotes-Demo, terminal file version5.0.0.6296; XAUUSD M5, Model4, nonvisual, 2026.07.01 00:00 tới2026.10.31 00:00 (end exclusive), tick cuối2026.10.30 22:59:58. Deposit100.000USD, leverage100, risk0.5%. Các report cuối đều100% real ticks và44.373.721 ticks, bao phủ4 tháng, đạt tối thiểu3 tháng. Dùng kỳ .ini claude_009 để tái lập lỗi; không kéo thêm kỳ nhằm tìm lệnh.
Commission: giữ thiết lập broker/tester hiện có; không đọc cấu hình tài khoản. InpCommissionPerLot7 là mô hình ảo, không override fee tester. Vì0 deal, commission thực và việc đặt đúng phí chưa được xác minh; không giả định fee bằng0. Spread thực mỗi OnTick hợp lệ: min0, mean0.32810150, max148.91;5.639.679/44.373.721 tick spread>0.45. Replay spread min0/max1.12/mean0.43532806 tính trên các lần detector quan sát có lặp bar; không phải phân phối spread tick thực. Không nới ngưỡng theo outlier148.91.

| B0v4 mặc định | EXIT_1R | TRAIL |
|---|---:|---:|
| Signal / closed trades |0 /0|0 /0|
| Win%, mean gross/net R, PF_R |N/A|N/A|
| Net USD |0|0|
| Equity DD maximal |0 (0%)|0 (0%)|
| Exit reasons |{}|{}|

PF0 của report tester là placeholder khi không có lệnh; không coi là PF đo được. DD0 không chứng minh chiến lược an toàn. Ledger31 cột có đủ header; chưa kiểm dữ liệu lệnh thực vì0 lệnh. Report HTML và CSV gốc nằm trong tp1r_final/ và trail_final/; mỗi lượt có inputs.set/tester.ini/RUN.json/log đã lọc. Model4 đã chạy thật; không thay bằng native mô phỏng.

## Indicator parity trên cùng kỳ
Adapter CanHoTroV4_IndicatorParity.mq5 là bản sao indicator sản xuất, đổi tên callback và bỏ property indicator để driver EA gọi OnInit/OnCalculate/OnTimer/OnDeinit. Nạp dữ liệu thật trong tester; không gọi CTrade. Tắt UI/notification và thay Load/Save Telegram config bằng no-op trong adapter, không sửa detector. Không phải visual tester hoặc attach indicator gốc vào visual chart. Danh sách EA0 và indicator0 khớp tập rỗng, missing/extra0; indicator cũng341 xác nhận/260 risk/81 RR reject, io_failed0. Không tuyên bố100% parity sự kiện dương với mẫu0; visual parity vẫn chưa thực hiện theo yêu cầu nonvisual.

## So với HIST M2, cắt ngày
M2 fixture M5 dừng23/10/2026 22:55, nến đóng23:00; không có24–30/10. So sánh chung theo timestamp server danh nghĩa01/07–23/10 23:00: EA0, HIST M2 mỗi rule65 signals/65 closed. Không dùng toàn kỳ1.393 để so. File HIST_M2_SLICE_0/1.csv và JSON kèm theo. Hai nguồn/profile khác (M2 TP RR/reference=false, spread/cost mô hình); chưa đồng bộ offset server lịch sử giữa export cũ và broker hiện tại, nên không dùng65↔0 làm phép đo missing EA.

| HIST M2, khoảng chung | EXIT_1R | TRAIL |
|---|---:|---:|
| Win net % |41.538462|41.538462|
| Mean gross R |−0.099640963|−0.092467319|
| Mean net R |−0.150677732|−0.143504089|
| PF_R |0.752226976|0.764023247|
| Reasons |SL37,TP_1R25,TIMEOUT_GAP3|SL61,TIMEOUT_GAP4|

Không có kết luận cải thiện hiệu quả từ0 lệnh của tester. HIST vẫn âm.

## Sửa và bàn giao
Sửa khả năng chẩn đoán EA: Identity/Observation/Zones/Signals thêm counters và witness, EA tổng hợp khi OnDeinit; thống kê spread tick tách replay. Không tìm thấy lỗi logic/adapter cần đổi quy tắc giao dịch trong kỳ này. Tất cả gates và default giữ nguyên; không tự sửa SL/TP/RR để đáp ứng kỳ vọng có lệnh. EA final, indicator final và indicator adapter final compile0 errors/0 warnings. Source snapshot source_final/, patch/ chứa mã/binary/docs hiện tại. MANIFEST.json M3b hash mọi file bằng chứng, MANIFEST_VERIFICATION.json kiểm hash. Source M3a ZIP đã nghiệm thu f515b856… giữ nguyên, không đóng đè. Chưa xác minh CTrade với giao dịch dương, phí broker, partial-fill, MFE/MAE exit thực. Không coi M3b đã nghiệm thu đầy đủ.

## Tái lập và điểm dừng
python scripts/v4_m3b.py build --label <mới>; run --label <mới> --rule0 hoặc1; runner lấy preset mặc định, chỉ đổi folder output và exit rule, INI tester từ mẫu được chỉ định. Lượt spread dùng --spread1.2 là riêng biệt. Indicator adapter được lưu tại indicator_adapter/ và snapshot build; chạy --expert CanHoTroV4_IndicatorParity.ex5. Chọn tên output mới; không ghi đè run cũ. Không dùng optimizer. Trạng thái account do người dùng quản lý, không đưa vào runner.
Dừng chờ Claude nghiệm thu chẩn đoán và quyết định riêng về preset nếu cần nghiên cứu thêm. Không tự mở M4/M5, không bật lại heartbeat.
"""
(RUN/'REPORT.md').write_text(report,encoding='utf-8')
manifest=[dict(path=p.relative_to(RUN).as_posix(),bytes=p.stat().st_size,sha256=sha(p)) for p in sorted(RUN.rglob('*')) if p.is_file() and p not in [RUN/'MANIFEST.json',RUN/'MANIFEST_VERIFICATION.json']]
dump(RUN/'MANIFEST.json',dict(scope='M3b',files=manifest))
errors=[x['path'] for x in manifest if sha(RUN/x['path'])!=x['sha256']];assert not errors
dump(RUN/'MANIFEST_VERIFICATION.json',dict(files=len(manifest),mismatches=errors,passed=True,m3a_zip_unchanged=True))
proof='\n'.join('- `'+(RUN/n).relative_to(ROOT).as_posix()+'` — `'+sha(RUN/n)+'`' for n in ['REPORT.md','M3B_RESULTS.json','BROKER_INDICATOR_PARITY.json','REJECTION_ANALYSIS.json','MANIFEST.json','MANIFEST_VERIFICATION.json'])
out=f"""# codex_006 — M3b — CHƯA ĐẠT kiểm chứng khớp lệnh (đã chạy và chẩn đoán xong)
Đã đọc: README_QUY_UOC, claude_003,007,008,009; giữ claude_005/006 đã đọc. Không đọc chat cũ.
Thời điểm: {datetime.now(timezone(timedelta(hours=7))).isoformat()}

## Đã làm
- Thêm chẩn đoán không đổi logic/preset: counters data/ATR/spread/zone/POI/sweep/confirm/candidate; CSV witness risk/TP/RR; spread tick thực tách replay. Biên dịch EA+indicator+adapter cuối0/0. Đây là sửa thiếu quan sát lỗi, không có bằng chứng bug adapter làm mất tín hiệu trên kỳ này.
- Chạy lại Model4, XAUUSD M5,01/07–31/10/2026, nonvisual, mặc định risk0.5%, deposit100000USD: EXIT_1R và TRAIL, mỗi lượt44.373.721 tick, report100% real ticks, cả hai0 lệnh. Build6296, MetaQuotes-Demo. Không đọc/sửa account, không login, không chạm MT5 thật.
- Root cause: data/ATR ready;341 xác nhận theo vùng bị loại260 risk>10 và81 risk4.356…9.971 nên TP1 distance6 /risk <MinRR1.5. Chưa có candidate để submit. Spread0.45 chỉ là chặn bổ sung. Lượt chẩn đoán riêng spread1.2 vẫn0 (260 risk+83 RR). Không nới default/SL/TP/RR để cứu kết quả.
- Indicator qua adapter callback sản xuất cùng data/tick/kỳ cũng0 signal và cùng341/260/81, io_failed0; tập rỗng khớp nhưng không có parity event dương, không visual tester. Chi tiết phương pháp/giới hạn trong REPORT.md.
- R gộp/ròng, win%,PF_R: N/A vì mẫu0; equityDD0, netUSD0; exit reasons rỗng. Report PF0 không phải PF thực nghiệm. Spread tick mean0.3281015/max148.91; replay stats mẫu khác. Fee broker chưa xác minh do0 deal; input7/lot không phải override commission tester.
- HIST M2 cắt khoảng chung01/07–23/10 23:00 (fixture dừng):65 lệnh mỗi rule, win41.538462%, mean gross/net EXIT−.099640963/−.150677732R, TRAIL−.092467319/−.143504089R, PF_R.752226976/.764023247. M2 profile/data khác nên không gán65 là EA missing. CSV/JSON giao đủ, không dùng số toàn kỳ1.393 để so.

## Bằng chứng (đường dẫn + SHA-256)
{proof}

Output thật cuối:
```text
V4_DIAGNOSTICS ticks=44373721 observations=67077 zone_rates_not_ready=0 zone_atr_not_ready=0 ltf_rates_not_ready=0 ltf_atr_not_ready=0 spread_n=67077 spread_blocked=43896 spread_min=0.00000000 spread_max=1.12000000 spread_mean=0.43532806 candidates=0 published=0 last_evaluated=1793400600 eligible=443039 poi=18426 sweep=13131 confirm=341 risk_rejected=260 rr_rejected=81 tick_spread_n=44373721 tick_spread_blocked=5639679 tick_spread_min=0.00000000 tick_spread_max=148.91000000 tick_spread_mean=0.32810150
```
Compile nguyên văn xem COMPILE_EA_final.log,COMPILE_Indicator_final.log,COMPILE_IndicatorParity_final.log (được hash trong manifest); actual report HTML/ledger/ini/set/log tại tp1r_final/,trail_final/,indicator_parity/. patch/ gồm mã và EX5 hiện tại, docs đã bổ sung M3b. Manifest kiểm lại0 mismatch; ZIP M3a không đổi hash f515b8565e8b63cb64c27b8b12dea6e4457ec0d4190dd9fa330d17e6c32cdbf6.

## Lệch so với kế hoạch và lý do
Không ép tạo lệnh hay tối ưu khi preset không có candidate. Kỳ4 tháng .ini được giữ để tái lập claude_009, đạt tối thiểu3 tháng; không kéo kỳ để tìm lệnh. Real ticks nay đầy đủ từ01/07, khác lượt Claude trước từ06/08; report cuối100% real ticks. Không khẳng định đã xác minh commission/CTrade/trades ledger bằng lệnh thật. Parity nonvisual qua callback adapter, không visual; mẫu0 không chứng minh parity sự kiện dương. HIST cắt đúng khoảng chung nhưng thiếu24–30/10 và khác profile/server offset chưa đồng bộ; ghi rõ thay vì bịa dữ liệu.

## Việc chưa xong / rủi ro đã biết
Cổng khớp/thoát lệnh thực B0v4, commission/slippage, partial-fill, ledger trade có dữ liệu và visual parity vẫn chưa đạt do0 tín hiệu/lệnh. Không có blocker account. Không có cơ sở đổi preset trong phạm vi được giao; dừng ở chẩn đoán đã chứng minh. M3a release ZIP giữ nguyên; thay đổi source/binary là patch chẩn đoán chờ Claude nghiệm thu, chưa thay ZIP phát hành.

## Câu hỏi cho Claude/người dùng
Không cần câu trả lời để hoàn tất phạm vi lần này. Claude kiểm witness/manifest và quyết định riêng nếu cần nghiên cứu preset khác; Codex không tự thay rule.

## Bước tiếp theo đề xuất
DỪNG theo yêu cầu. Không M4/M5, không tự chạy tiếp, không bật heartbeat.
"""
p=ROOT/'codex_outbox/codex_006_M3b.md';assert not p.exists();p.write_text(out,encoding='utf-8')
print(json.dumps(dict(report=str(p.relative_to(ROOT)),manifest_files=len(manifest),mismatches=0,parity_equal=True,positive_trade_validation=False)))
