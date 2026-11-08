# v4.0.3 — 02/11/2026 — claude_014

- Cùng vùng H1 và signal_id M5 trên M1/M5/M15/M30/H1/H4/D1; ATR và fingerprint không phụ thuộc chart.
- Replay nhân quả 90 ngày qua OnTimer, có tiến độ; một writer, các chart đọc chung cache và tiếp quản khi writer đóng.
- Vùng active luôn vẽ; expired mờ; source zone kéo tới invalidation; tooltip arrow đầy đủ.
- InpShowStatsPanel=false xóa M2_* cũ; CSV tự ghi, nút CSV nhỏ ở dashboard. Dashboard mặc định thu gọn, chọn góc bằng DashRight/InpDashBottom.
- Khôi phục khi đổi khung/gỡ gắn/restart trước M5 mới; replay không phát BE notification lịch sử.
- Không đổi ngưỡng, scale, RR, risk/trail; không M4/M5. Bằng chứng v402/v401 là baseline, không kết quả mới v403.

# CHANGELOG v4.0.2 — 02/11/2026

Chờ Claude nghiệm thu. **v4.0 M3a KHÔNG được phát hành vì lỗi lot ×10**; ZIP cũ chỉ giữ làm bằng chứng.

## v4.0.2 — hai lỗi indicator chạy thật

- Ledger/state/score dùng fingerprint cấu hình đã resolve HTF/LTF, kèm khung chart thực (ATR chart). ID rỗng của state chưa có signal được chuẩn hóa khi so sánh, tránh cách ly nhầm. Chỉ đọc bộ đúng fingerprint; legacy symbol-only để nguyên.
- Bộ ledger/state không khớp:archive signals/state/candidates/guard/score thành *_corrupt_<time>,reset rồi tạo lại;cảnh báo đỏ nhìn thấy trên chart/panel. Lock/I/O không coi là corruption. Không tự nhập archive vào runtime mới.
- Indicator dùng contract size × adverse price distance × lot,quy đổi profit→account currency bằng symbol direct/inverse hoặc USD bridge; thiếu metadata/quote thì Lot N/A rõ lý do. Không gọi OrderCalcProfit. Tick value lệch>1% vẫn cảnh báo. EA tiếp tục OrderCalcProfit;detector/scale/RR/preset không đổi.
- Indicator thật qua menu chart portable H1→M5→M15→M5→gỡ/gắn:29 mũi tên broker đã lưu giữ nguyên tên/time/price. Panel lot0.060 với equity10000USD,target50USD,risk43.212USD,một bước7.202USD. Chủ ý corrupt checkpoint của bộ test:archive,khởi tạo lại,cảnh báo hiện rõ.
- Storage/risk23/23,indicator risk11/11 (oracle calls0),EA risk/stop regression25/25;tất cả compile0/0. Không M3b/HIST/P&L mới;baseline v4.0.1 dưới đây được tái sử dụng có ghi rõ. Chỉ portable20261102_m3a_v1,không chạm D0E8209F.
- Gói4.0.2 gồm source/binary,preset không đổi,docs,validation/v402,manifest+ZIP và hash sau giải nén. Chờ Claude nghiệm thu,không M4/M5.

## v4.0.1

- InpPriceScaleMode=1: chín ngưỡng khoảng cách XAU quy đổi bằng close D1 đã đóng /2000. Mode0 giữ khoảng cách cũ; thiếu D1 không fallback. Không đổi detector/RR/base preset.
- Sửa lot ×10: OrderCalcProfit là nguồn chính cho panel lot, cost/R, EA và risk journal. Tick formula chỉ đối chiếu; lệch>1% hiện/log “broker khai báo tick value không khớp”. Oracle lỗi thì không hiển thị/dùng lot; không fallback tick value.
- Sửa trail: bỏ modify SL/TP giống nhau sau chuẩn hóa; kiểm STOPS_LEVEL/FREEZE_LEVEL; invalid stops/frozen giữ SL cũ, ghi sự kiện, không dừng tester. Lỗi khác fail closed. Đồng bộ stop ảo với SL đã áp dụng.
- Thêm risk_audit.csv; giữ ledger trade31 cột và fee/swap từ history deals. 58/58 lệnh xác minh risk0.5% trong sai số một bước lot.
- EA/indicator/adapter compile0/0; unit risk/stop25/25; smoke prefix20/20 ×2 mode. Detector/scale/RR/preset hash không đổi so snapshot trước sửa; giữ nghiệm thu prefix200/200 ×2 và HIST1519/0.
- M3b mỗi rule44.373.721 tick/100% real,29 closed: EXIT_1R mean net−0.1699986735R, PF_R0.7466967436, net−2482.66USD, equityDD4847.79USD/4.79%; TRAIL mean net−0.0711303713R, PF_R0.8940135144, net−1113.86USD, equityDD5324.20USD/5.19%. Win37.931034% cả hai. Commission/fee0; swap−43.80/−47.12USD.
- HIST mode1/default đã nghiệm thu459 signals/closed mỗi rule: mean net EXIT_1R−0.1300616069R, TRAIL−0.1364607699R. Dữ liệu fixture27/09/2021–23/10/2026; D1 tổng hợp closed H1, không thay broker D1 thật.
- Số liệu M3b v401 trước sửa lot (DD40.06%) không đại diện risk0.5%; TRAIL trước sửa bị ngắt không phải baseline. Các run cũ bất biến. Chưa có bằng chứng lợi thế; không tối ưu/M4/M5.
- Đóng gói source/binary/preset/docs/evidence, manifest payload, ZIP và giải nén so hash. Xem HUONG_DAN_KY_THUAT.md và validation/REPORT.md về giới hạn.

## Lịch sử nền v4.0 (fixture profile cũ, không phải kết quả mặc định v4.0.1)

M1/M2/M3a thêm guard thời gian, ID vùng, epsilon RR, publication gate, nguồn vùng độc lập, checkpoint, scorecard LIVE/HIST, journal chỉ đọc và EA tester-only. Legacy parity5164/5164; synthetic journal9 deal/4 vị thế. Profile cũ TP RR/reference=false có1393 signals,1392 closed,1 expired; mean net−0.0941291330/−0.1072654621R. Không dùng số này thay HIST459 của profile mặc định HYBRID/reference=true/mode1.

## F1–F7
- F1: guard zone-known/sweep-known, không dùng sweep trước vùng đã biết. M1 51 candidate shadow bị guard loại, 12 publication COMPAT witness mất; mẫu số không trộn với ACTIVE_PLAN.
- F2: FLIP có timeFormed/timeKnown/timeInvalid. Native trace v3.01: 1.833/2.363 publication dùng FLIP đã invalid; V4 không công bố các event đó.
- F3: ID vùng hash 63 bit từ hình học/start/side/point. 2.856 vùng khớp hai cửa sổ, không collision quan sát; không bảo đảm toán học không collision.
- F4: epsilon cho roundoff RR, MinRR vẫn là floor ở HYBRID/RR/PIPS.
- F5: log candidate trước gate publication, lý do bị chặn rõ. Không bật mọi candidate thành lệnh. M1: 2.424 = 1.393 published + 1.031 ACTIVE_PLAN.
- F6: vùng nguồn tín hiệu có rectangle/ID riêng, không mất theo quota vùng gần nhất; 100 mẫu geometry/tooltip đã kiểm.
- F7: writer chờ mở có giới hạn, checkpoint/catch-up/reload ổn định; prefix 200/200. Crash giữa append và checkpoint vẫn fail closed, chưa tự phục hồi.

## Bảng thay đổi tín hiệu (fixture M1/M2 đóng băng)
| Nhóm nguyên nhân chính, loại trừ nhau | Thêm | Mất |
|---|---:|---:|
| F1 |112|12|
| F2 |0|1833|
| F4 |274|0|
| F5 |546|57|
| Tổng |932|1902|

v3.01 2.363 → V4 1.393; chung 461 ID. 14 mixed F5 được quy chính F1, 49 quy F4; không cộng thêm. DIFF_V301_V4.csv 3.295 dòng, có lý do từng dòng. Đây là số từ profile fixture, không phải mặc định mọi broker/period.
Vùng thường: 123/831 tín hiệu từ vùng testCount>=4, 0 age>1200; giữ nguyên hành vi MaxTests/MaxAgeBars theo quyết định Claude.

