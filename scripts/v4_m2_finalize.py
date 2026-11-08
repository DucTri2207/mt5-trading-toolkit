# -*- coding: utf-8 -*-
"""Write M2 handoff from native artifacts, then verify the delivery hashes."""
import csv
import hashlib
import json
from datetime import datetime, timezone, timedelta
from pathlib import Path

from v4_m2 import ROOT, RUN, M1, analyze, read, save, table


def sha(p):
    h=hashlib.sha256()
    with p.open('rb') as f:
        for block in iter(lambda:f.read(1024*1024),b''):
            h.update(block)
    return h.hexdigest()


def main():
    files=RUN/'portable_terminal/MQL5/Files/v4_fixture'
    native=json.loads((files/'m2_result.json').read_text())
    panel=json.loads((RUN/'final5_outputs/m2_final_result.json').read_text())
    assert native['failures']==0 and native['published']==1393 and panel['failures']==0
    build=json.loads((RUN/'BUILD_full_final.json').read_text())
    assert all(x['passed'] for x in build.values())
    analyze()
    parity=json.loads((RUN/'LEGACY_PARITY.json').read_text())
    assert parity['failures']==0
    exposure=json.loads((RUN/'NORMAL_ZONE_EXPOSURE.json').read_text())
    journal=json.loads((RUN/'JOURNAL_ACCEPTANCE.json').read_text())
    scores=json.loads((RUN/'SCORECARD_HIST_SUMMARY.json').read_text())
    disjoint={f:dict(fix=f,added=0,removed=0) for f in ['F1','F2','F4','F5']}
    for row in read(RUN/'SIGNAL_CHANGE_BY_REASON.csv'):
        if row['compat']==row['v4']: continue
        fix=row['reason'][:2]
        disjoint[fix]['added' if row['v4']=='True' else 'removed']+=int(row['count'])
    table(RUN/'SIGNAL_CHANGE_DISJOINT.csv',list(disjoint.values()))
    now=datetime.now(timezone(timedelta(hours=7))).isoformat(timespec='seconds')
    examples='\n'.join(f"| `{x['signal_id']}` | {x['known']} | {x['test_count']} | {x['age_bars']} |" for x in exposure['examples'])
    score_table='\n'.join(f"| {name} | {scores[k]['signals']} / {scores[k]['closed']} | {scores[k]['win_percent']:.3f}% | {scores[k]['mean_gross_R']:.6f} | {scores[k]['mean_net_R']:.6f} | {scores[k]['PF_R']:.6f} |" for k,name in [('0','EXIT_1R'),('1','EXIT_TRAIL_1R')])
    change_table='\n'.join(f"| {r['fix']} | +{r['added']} | -{r['removed']} | {r['added']-r['removed']:+d} |" for r in disjoint.values())
    report=f'''# M2 — Scorecard, Risk, Journal — CHƯA ĐẠT toàn bộ cổng nghiệm thu
Thời điểm: {now}. Đã đọc claude_001–claude_005. Không đọc chat cũ.

## Kết luận
Triển khai M2 và các kiểm tra kỹ thuật đã hoàn tất. Chưa thể nghiệm thu yêu cầu **22 lệnh demo qua lịch sử deal thật**: `gold_live_review/COLLECTION.json` có 1 balance deposit, 0 gold deals, 0 orders; 22 hàng trong `RECOVERED_CLOSED_TRADES.csv` là phục dựng chart/journal. Không đổi tài khoản/đăng nhập để tìm lịch sử khác. Dừng chờ Claude, không chuyển M3.

## Phạm vi đã giao
- `Risk.mqh`: lot theo tick size/value, floor volume step, clamp min/max, phí/R, daily/total equity remaining. Min-lot clamp có thể vượt ngân sách; panel luôn hiện số tiền risk thực ước tính. Input vốn ban đầu mặc định 0 = chưa biết, không đoán baseline.
- `Execution.mqh` + `Scorecard.mqh`: nhiều tín hiệu ảo độc lập, BUY Ask→Bid, SELL Bid→Ask, hai exit cố định. Không thay display-plan gate M1. HIST và LIVE lưu nguồn riêng, không cộng gộp. CSV lưu known/published/fill/exit riêng, không sửa thời gian order/fill/exit của ledger tín hiệu M1.
- `Journal.mqh`: chỉ đọc HistorySelect/deals/orders đúng symbol; nhóm POSITION_ID, partial closes, scale-in, netting reversal tách episode/cost theo volume. SL mở từ ORDER_SL rồi fallback DEAL_SL. Không có SL → R không xác định, vẫn ghi USD. Match trong cửa sổ 30 phút mặc định, không dùng tín hiệu tương lai.
- `M2Panel.mqh` + indicator: panel riêng ở góc đối diện dashboard; n, closed, win%, R gross/net, PF theo R, median cost/R; tuần/giờ hiện n và net R, toàn bộ chỉ tiêu theo nhóm có trong CSV. Nút “Xuất CSV” xuất cả scorecard/group và journal/group. Ghi chú bắt buộc hiển thị đầy đủ trên hai dòng vì MT5 build hiện tại cắt OBJ_LABEL ở 63 ký tự.

## 60 idle chênh lệch — đã giải thích trước parity
`IDLE_RECONCILIATION.json`: 5.164/5.164 khớp theo confirm bar + hướng + entry + stop; 60 extras của native đều nằm trước 23/10/2021 (epoch 1634947200), trong 01–22/10/2021. Probe có filter confirm time >= 23/10; native M1 chạy mọi saved bar. Không phải 60 warm-up trước 01/10.
23 cặp còn có khác semantics timestamp: probe `known_at` = thời điểm M5 kế tiếp quan sát được qua gap; native known = confirm open +300, publish = quan sát. Cả 23 probe known khớp native publish. Chi tiết: `IDLE_60_EXTRA.csv`, `IDLE_TIME_DIFFERENCES.csv`. Source căn cứ: `research_gold_v301_causal.py::signals`, `gold_v301_causal_core.py::detect_one`; không chạy lại Python detector.

## Parity scorecard — legacy riêng
Chạy nguyên trạng `edge_probe.py` làm oracle legacy, không sửa quy tắc. Native MQL5 nhận đúng ledger probe 5.164 dòng, cùng M1, bid-only, timeout **240 nến quan sát**, SL trước TP, trailing kiểm stop trước cập nhật MFE. Đây là ngoại lệ tái lập legacy theo claude_002/004; Python không tạo detector mới hay scorecard production.
`LEGACY_PARITY.json`: {parity['rows']} dòng; 0 failures; tolerance 1e-8 R; max |delta TP1|={parity['max_tp1_delta']:.15g}; max |delta trail|={parity['max_trail_delta']:.15g}. Legacy net chỉ là gross trừ 0.39/risk; không trộn với main.

## Scorecard chính — hồi cứu, timeout theo đồng hồ
Giữ ledger V4 {native['published']} publications và spec đã khóa: M1 Bid OHLC; spread 0.30 giá; slippage 0.01 mỗi fill; commission roundtrip 7/lot; giả lập gold tick size .01, tick value $1, point .01. Mỗi rule có 1 tín hiệu hết hạn trước khi có quote vào, nên không có fill; 1.392 tín hiệu còn lại đã đóng. Median cost/R cả hai = {scores['0']['median_cost_R']:.6f}.

| Rule | Signals / closed | Win (net>0) | Mean gross R | Mean net R | PF R |
|---|---:|---:|---:|---:|---:|
{score_table}

Main không dùng legacy timeout: hạn = known+14.400 giây. Chỉ dùng bar hoàn chỉnh có open >= known để vào HIST. Nếu quote đầu tiên đến sau hạn → EXPIRED_NO_QUOTE. Nếu đã có fill nhưng gap qua hạn → thoát quote mở đầu tiên sau hạn, không dùng high/low sau hạn; exit_time có thể vượt hạn do không có quote. Ambiguous bar tính SL trước; stop gap khớp open bất lợi hơn stop. Trail cập nhật sau kiểm stop để tái hiện bảo thủ theo M1, không phải tick path.
Gross R = net R + cost R; R dùng khoảng fill→initial SL. Net dùng fill đã chứa spread/slip rồi chỉ trừ commission; không trừ cost lần hai. `scorecard_hist.csv` có kết quả từng tín hiệu/rule; `SCORECARD_HIST_SUMMARY.json` có cả số xấu. Không sửa tham số sau kết quả âm.

## Đo vùng thường — giữ nguyên hành vi
Trong {exposure['normal_signals']} tín hiệu từ vùng thường: testCount >= MaxTests: **{exposure['over_tests']}**; ageBars > MaxAgeBars: **{exposure['over_age']}**; hợp: {exposure['union']}. Mẫu số toàn bộ V4 =1.393. Đo tại signal_known_time; 4 publications trễ được scan lại prefix H1 tại known chỉ phục vụ telemetry, rồi phục hồi trạng thái replay. Không đổi điều kiện mặc định.

| Signal ID | Known epoch | Tests (Max=4) | Age (Max=1200) |
|---|---:|---:|---:|
{examples}

## Bảng v3.01 → V4 dùng cho tài liệu kỹ thuật
2.363 → 1.393 = giữ chung 461 + thêm 932 − mất 1.902. Căn cứ nguyên `DIFF_V301_V4.csv` của M1. Bảng dưới quy attribution chính theo nhãn đầu tiên (F1/F4 đứng trước yếu tố F5), không cộng trùng:

| Fix | Thêm | Bớt | Net |
|---|---:|---:|---:|
{change_table}
F5 đồng tác động 14 additions gán chính F1, 49 additions gán chính F4. Bảng mọi nhãn kết hợp giữ nguyên ở `SIGNAL_CHANGE_BY_REASON.csv`; bảng rời ở `SIGNAL_CHANGE_DISJOINT.csv`. 461 chung có đổi stable ID/F1 sweep thay thế, không phải thêm/bớt signal.

## Journal và cổng còn thiếu
Native dùng các giá entry/exit, volume của 22 dòng phục dựng, giả định contract 100, tính gross trong MQL5 rồi feed cùng journal accumulator. Max sai số so gross phục dựng = {journal['max_fixture_accounting_error']:.15g} USD. Fixture kiểm riêng partial close, mọi khoản fee/commission/swap, missing-SL R unknown, reversal, match hướng/thời gian. Đây **không** phải tái tạo 22 P&L net từ broker deals; không biết phí/SL mở của 22 lệnh.
`JOURNAL_ACCEPTANCE.json`: actual_history_22_trades_verified=false. Native HistorySelect thật ở portable offline có 0 deals. Cần Claude cung cấp export deal+order gốc của đúng tài khoản demo hoặc điều chỉnh cổng này rõ ràng. Giữ CHƯA ĐẠT, không tự thay thế fixture thành bằng chứng live.

## Kiểm tra và hash
- Full native cuối: {json.dumps(native,ensure_ascii=False)}.
- Final panel/tick/risk/persistence/journal: {json.dumps(panel,ensure_ascii=False)}.
- `BUILD_full_final.json`: test và indicator compiler thật 0 errors/0 warnings; output log nguyên văn trong outbox. Snapshot `build_inputs_full_final/` và `build_inputs_final5/` khóa source tại compile.
- Các lần thử lỗi (từ khóa `input` ở test; nested OnStart; OBJ_LABEL cắt ghi chú) được giữ lại. Các gate chỉ dùng full_final + final5; không xóa bằng chứng fail cũ.
- Manifest khóa source/binary/data/preset/protocol/script/test và kiểm SHA-256 sau đóng terminal. Không ghi đè v3.01/run M1.

## Giới hạn kỹ thuật v4.0 và quyết định bảo thủ
- LIVE chỉ gán cho tín hiệu có known sau khi instance đã bắt đầu theo dõi; đọc tick Bid/Ask từ known, cursor riêng mỗi record (kể cả nhiều tick cùng millisecond). Fill/exit là kết quả **ảo**, có thể trước publish nếu publication trễ trong cùng instance; không phải lệnh thực. Quote trước instance/catch-up cũ dùng HIST. Chưa QA tick trực tiếp trên broker.
- Reload LIVE đang mở → LIVE_GAP, giữ nhãn LIVE và loại khỏi win/R/PF; không suy diễn path khi instance tắt. Closed giữ nguyên; HIST pending được tính lại khi M1 có thêm. CSV lưu atomic replacement, lỗi schema/I/O dừng scorecard và hiện lỗi. Không tuyên bố phục hồi crash giữa các ledger.
- Daily baseline dùng balance đầu ngày tái dựng từ balance hiện tại trừ P&L/fees/cashflows đã ghi trong ngày trên **toàn tài khoản**; equity hiện tại gồm floating. Cần lịch sử ngày đầy đủ; funding/cashflow intraday có thể cần đối soát thủ công. Daily breach latch qua GlobalVariable theo account/server/reset/capital; tự hết ngày mới. Reset input là phút trong ngày **server**, mặc định 0; người dùng phải đặt mapping CE(S)T và cập nhật DST, không đoán timezone feed.
- Initial capital mặc định 0: remaining unknown; khi bật mute và baseline unknown thì không gửi cảnh báo xác nhận. Lot min clamp có thể vượt risk%; không phải EA sizing/order execution. Tick-value live hiện tại dùng cho lot/R journal, chưa chứng minh conversion lịch sử với tài khoản/symbol khác.
- Journal export thêm hậu tố symbol (`journal_<account>_<symbol>.csv`) để các chart không ghi đè nhau. Open/partial không trộn vào thống kê closed. Thiếu deal/orphan được báo, không tạo R giả. Tiền theo currency tài khoản; fixture USD.
- Giữ giới hạn M1: crash giữa append/checkpoint fail closed, ngắt mạng chỉ giả lập, Telegram/push chưa QA thật; replay display quote giả định 0.20; tick gốc trong gap chưa có; UI fixture không chứng minh detector default; không lệnh thực/order/fill/exit thật.
- Source sửa sau lượt hồi cứu đầu chỉ để kiểm dữ liệu, cursor/persistence, latch/hiển thị; không sửa detector, rule/timeout/cost/preset để cứu P&L. M2_RULES_LOCK ban đầu giữ nguyên; final source có snapshot/manifest riêng. Không tạo M4 EXPERIMENT_LOCK hay dùng dữ liệu đã xem làm forward.

## Tái lập
`python scripts/v4_m2.py prepare` chỉ chạy khi run mới chưa tồn tại (đổi RUN cho bản tái lập mới).
`python scripts/v4_m2.py build --label <mới>` rồi `run --label <mới>` chạy full native.
Label bắt đầu bằng `final` chạy nhóm regression nhỏ `TestV4M2Final`; `full_final` là full.
`python scripts/v4_m2.py analyze`; cuối cùng `python scripts/v4_m2_finalize.py`.
Không chạy hai terminal trong cùng portable. Code terminal shutdown thực được lưu trong EXIT_*.json; không đổi exit code thành PASS. Gate đọc artifact native + compiler, không suy PASS từ mã process.

API tham chiếu: [MQL5 deal properties](https://www.mql5.com/en/docs/constants/tradingconstants/dealproperties), [MQL5 symbol constants](https://www.mql5.com/en/docs/constant_indices).

## Bước tiếp theo
Claude nghiệm thu độc lập M2 và xử lý thiếu lịch sử demo. Codex DỪNG ở đây, không làm M3.
'''
    (RUN/'REPORT_M2.md').write_text(report,encoding='utf-8')
    baseline=json.loads((M1/'MANIFEST.json').read_text(encoding='utf-8-sig'))['files']
    baseline={x['path']:x['sha256'] for x in baseline}
    for name in ['duc_tri_can_ho_tro.mq5','duc_tri_can_ho_tro.ex5']:
        assert sha(ROOT/name)==baseline[name]
    binary=ROOT/'can_ho_tro_v4/MQL5/Indicators/duc_tri_can_ho_tro_v4.ex5'
    assert sha(binary)==sha(RUN/'portable_terminal/MQL5/Indicators/duc_tri_can_ho_tro_v4.ex5')==build['indicator']['binary_sha256']
    assert sha(binary.with_suffix('.mq5'))==build['indicator']['source_sha256']
    paths=set((ROOT/'can_ho_tro_v4').rglob('*')) | set((ROOT/'tests/v4').rglob('*'))
    paths.update([ROOT/'scripts/v4_m2.py',Path(__file__)])
    paths.update(p for p in RUN.rglob('*') if 'portable_terminal' not in p.parts)
    for folder in ['MQL5/Include','MQL5/Scripts/V4','MQL5/Indicators','MQL5/Files/v4_fixture']:
        paths.update((RUN/'portable_terminal'/folder).rglob('*'))
    for p in [ROOT/'duc_tri_can_ho_tro.mq5',ROOT/'duc_tri_can_ho_tro.ex5',ROOT/'reports/scalp_structure_lab/20261025_pilot_v1/rates.npz',
              ROOT/'reports/gold_v301_causal/20261101/signals_MQ5_PREFIX.csv',ROOT/'reports/claude_signal_edge_probe/20261101/edge_probe.py',
              ROOT/'reports/gold_live_review/20261101/COLLECTION.json',ROOT/'reports/gold_live_review/20261101/deals.csv',
              ROOT/'reports/gold_live_review/20261101/orders.csv',ROOT/'reports/gold_live_review/20261101/RECOVERED_CLOSED_TRADES.csv',
              M1/'DIFF_V301_V4.csv']:
        paths.add(p)
    paths.update(M1.glob('*.set')); paths.update((ROOT/'codex_inbox').glob('*.md'))
    excluded={'MANIFEST_M2.json','MANIFEST_M2_VERIFICATION.json'}
    paths=sorted(p for p in paths if p.is_file() and p.name not in excluded and '__pycache__' not in p.parts)
    manifest={str(p.relative_to(ROOT)):sha(p) for p in paths}
    save('MANIFEST_M2.json',manifest)
    mismatches=[name for name,value in manifest.items() if sha(ROOT/name)!=value]
    save('MANIFEST_M2_VERIFICATION.json',dict(files=len(manifest),mismatches=mismatches))
    assert not mismatches
    important=[ROOT/'can_ho_tro_v4/MQL5/Indicators/duc_tri_can_ho_tro_v4.mq5',ROOT/'can_ho_tro_v4/MQL5/Indicators/duc_tri_can_ho_tro_v4.ex5',
               RUN/'REPORT_M2.md',RUN/'MANIFEST_M2.json',RUN/'MANIFEST_M2_VERIFICATION.json',RUN/'LEGACY_PARITY.json',
               RUN/'IDLE_RECONCILIATION.json',RUN/'NORMAL_ZONE_EXPOSURE.json',RUN/'SIGNAL_CHANGE_DISJOINT.csv',
               RUN/'SCORECARD_HIST_SUMMARY.json',RUN/'JOURNAL_ACCEPTANCE.json',files/'m2_result.json',RUN/'final5_outputs/m2_final_result.json']
    hashes='\n'.join(f"- `{p.relative_to(ROOT)}` — `{sha(p)}`" for p in important)
    compile_lines=[]
    for kind in ['test','indicator']:
        raw=(RUN/f'COMPILE_M2_{kind}_full_final.log').read_bytes()
        text=raw.decode('utf-16') if raw.startswith(b'\xff\xfe') else raw.decode('utf-8-sig')
        compile_lines.extend(line for line in text.splitlines() if line.startswith('Result:'))
    outbox=f'''# codex_004 — M2 — CHƯA ĐẠT
Đã đọc inbox: claude_001, claude_002, claude_003, claude_004, claude_005.
Thời điểm: {now}

## Đã làm
- Hoàn tất source Scorecard/Execution/Risk/Journal và nối panel + export vào indicator; không đổi detector/default MaxTests/MaxAgeBars.
- Đối soát idle: 5.164 match +60 trước mốc 23/10/2021; 23 dòng khác known/observed qua gap đã liệt kê.
- Legacy parity: 5.164/5.164 PASS, tolerance 1e-8 R. Main timeout theo đồng hồ; cả hai rule ròng âm, không đổi đặc tả.
- Đo vùng thường: {exposure['over_tests']}/{exposure['normal_signals']} từ vùng testCount>=4, {exposure['over_age']} age>1200; 5 ví dụ + CSV đầy đủ. Bảng attribution 2.363→1.393 đã giao.
- Full native {native['checks']} checks/{native['failures']} failures; panel/risk/tick/persistence {panel['checks']}/{panel['failures']}. Journal 22 fixture giá phục dựng khớp gross, sai số max {journal['max_fixture_accounting_error']:.15g} USD.

## Bằng chứng (đường dẫn + SHA-256; output thật)
Base: `reports/can_ho_tro_v4/20261101_m2_v1/`. Chi tiết và lệnh tái lập: `REPORT_M2.md`.
```text
{chr(10).join(compile_lines)}
```
```json
{json.dumps(native,ensure_ascii=False)}
{json.dumps(panel,ensure_ascii=False)}
```
Manifest: {len(manifest)} files, 0 mismatch. Binary giao khớp binary portable/build cuối.

{hashes}

## Lệch so với kế hoạch và lý do
- **Chưa đạt cổng Journal 22 lệnh demo:** export account có 0 gold deals/orders. 22 dòng là phục dựng chart, không phải lịch sử broker. Không tự đổi tài khoản/đăng nhập; giữ fixture và chứng cứ thiếu dữ liệu riêng.
- Ghi chú panel chia hai dòng (OBJ_LABEL cắt 63 ký tự); CSV journal thêm symbol tránh ghi đè chart khác. LIVE gián đoạn được loại LIVE_GAP thay vì bịa path.
- Snapshot cuối lưu các sửa validation/cursor/latch/UI sau lượt hồi cứu đầu; không đổi rule/cost/detector để cứu kết quả. Không tự làm M3.

## Việc chưa xong / rủi ro đã biết
- Cần deal+order gốc đúng tài khoản demo để kiểm net P&L/initial SL/R cho 22 lệnh. Fixture không thay thế được cổng này.
- LIVE tick trên broker, DST/reset thực, account conversion lịch sử, Telegram/push thật chưa QA. Giữ các giới hạn M1 và các quyết định bảo thủ ở REPORT_M2.md.

## Câu hỏi cho Claude/người dùng (nếu có)
Claude: cung cấp export deal+order demo gốc hoặc quyết định rõ cách xử lý cổng thiếu dữ liệu; xem JOURNAL_ACCEPTANCE.json. Theo claude_005, không chờ người dùng để chọn giả định dữ liệu.

## Bước tiếp theo đề xuất
Claude nghiệm thu độc lập M2. Codex **DỪNG chờ Claude**, không chuyển M3.
'''
    target=ROOT/'codex_outbox/codex_004_M2.md'
    assert not target.exists()
    target.write_text(outbox,encoding='utf-8')
    print(json.dumps(dict(report=str(target.relative_to(ROOT)),native=native,panel=panel,manifest_files=len(manifest),mismatches=0),ensure_ascii=True))


if __name__=='__main__':
    main()
