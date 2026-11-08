---
name: trade-toi
description: "Phân tích cơ hội giao dịch ca tối từ MT5: trả đủ tín hiệu A phá vùng H1/retest M5 trước, rồi giải thích hướng giá, vùng chờ và hoạt động tick. Dùng khi người dùng gọi trade tối, quét ca tối hoặc kiểm một mã; không tự đặt lệnh hay theo dõi nền."
---

# trade tối

Đây là skill vận hành bộ công cụ tại `D:/trading thử lần cuối cuối/quant_mt5`, không phải đề nghị nghiên cứu lại chiến lược. Trả kết quả bằng tiếng Việt, nói bằng hướng/vùng/điều kiện chờ; giữ ID và bằng chứng máy để kiểm toán.

Đọc [runtime](references/runtime.md) khi bắt đầu hoặc CLI thay đổi. Đọc [cách diễn giải](references/analysis.md) khi viết nhận định. Dùng CLI/runtime đã triển khai, không dùng bản staged, baseline backup hoặc các lệnh chỉ có trong kế hoạch.

Nếu người dùng chỉ nhờ đọc report/snapshot đã cung cấp, đọc đúng artifacts đó, giữ nhãn SYNTHETIC/HISTORICAL và không readiness/collect/once/enrich/finish. Quy trình dưới đây chỉ dành cho yêu cầu lấy dữ liệu MT5 mới.

## Một lượt hữu hạn

1. Dùng terminal/session/universe người dùng đã chọn; nếu thiếu, đọc hướng dẫn phiên mới nhất trong dự án. Chỉ dùng MT5 người dùng đã mở và đăng nhập demo. Kiểm readiness không attach và session preflight (packages/process/pins); thiếu nguồn thì PENDING và hướng dẫn mở MT5, không tự mở/đổi tài khoản. READY_TO_ATTACH chưa xác minh account: collector của call baseline mới kiểm identity/trade_mode demo trước đọc dữ liệu, giữ nguyên guard này.
2. Gọi `session once --analysis-mode baseline` (hoặc `session check --symbols ... --analysis-mode baseline` khi chỉ kiểm mã đã ghim). Dùng một JSON output, lấy cycle/snapshot/bundle/generation từ chính lượt đó.
3. **Đọc và trình bày bảng A ngay sau call baseline**, trước khi gọi enrich. Mọi A đều phải được nhắc bằng ID/mã/hướng/trạng thái/thời hạn; nếu nhiều thì bảng compact và link đầy đủ, không chỉ nói “còn vài tín hiệu”. `max_cards` chỉ giới hạn thẻ sâu. Snapshot còn hạn không có nghĩa đã được phép giao dịch ngay.
4. Gọi một `session enrich` với đúng continuation vừa nhận; không collect lại, không thay bằng snapshot latest khác, không thêm context/card process cho dữ liệu đã có. Dùng báo cáo cuối và packet cùng snapshot để giải thích.
5. Optional thiếu/timeout: vẫn trả đủ A với hạn chế rõ. Integrity/source mismatch: không diễn giải dữ liệu lỗi thành usable hoặc gọi finish. Không kéo dài deadline để bù thời gian phân tích.
6. Lưu bằng chứng qua report/journal/note hiện có. `note add` chỉ cho candidate thật đã phân tích; quan sát không candidate dùng observation. Nếu người dùng chưa yêu cầu lượt cuối thì giữ tick và kết thúc lượt, không chạy nền.

## A là lõi, context không phủ quyết

A dùng vùng 8 H1 đã hoàn tất được đóng băng → M5 phá biên → M5 retest sau đó. M0/M1/M2, gate, plan, expiry và mọi execution/portfolio guard giữ theo engine. Không đồng nhất với Fabio F1/F2; không chọn lại branch vì winrate cũ đẹp.

Thiếu/trái CVD, profile, ADX/RSI, strength hoặc Fabio WAIT chỉ là thông tin bối cảnh, không được giấu A hay tạo gate mới. Context thuận cũng không biến expired/stale/thiếu phí thành lệnh có thể vào. Giữ `actionable_now=false` và yêu cầu quote/tài khoản mới như engine.

Chỉ MT5: không footprint, DOM/heatmap, feed ngoài, indicator trả phí hoặc file export bắt buộc. Tick-direction/CVD proxy là hoạt động tick của feed, không tổng tiền vào/ra, không bằng chứng độc lập với giá hay ý định cá mập. Tin tức: `USER_MANAGED`, hệ thống không kiểm; không gọi lịch tin và không nói đã tránh tin.

## Kết quả người dùng cần

- Giờ Việt Nam của snapshot, nguồn/mã đã quét, hạn chế thực sự ảnh hưởng nhận định.
- Bảng đủ A: hướng, vùng/plan gốc, trạng thái branch và cửa sổ entry, context đang chờ/thuận/nghịch/thiếu tách biệt.
- Bức tranh mọi mã kể cả no-signal: H1/M5, vùng đóng băng và vùng tham chiếu phân biệt; bằng chứng ủng hộ, phản bác, diễn biến cần chờ và điều kiện hủy.
- Thẻ sâu theo giới hạn đã chọn: không bịa entry/SL/TP cho watch-only; mục tiêu tham chiếu không thay TP. Không thêm xác suất thắng hoặc tự giảm tần suất bằng lọc chỉ báo.
- Link report cuối, snapshot ID và phần chưa xác minh; không gọi replay paper là fill broker hay chứng nhận FTMO.

Chỉ khi người dùng nói lượt cuối/kết phiên: hoàn tất phân tích/lưu note, lấy token của **báo cáo cuối** rồi `session finish` đúng IDs. Baseline PENDING không có quyền dọn. Xác nhận receipt CLOSED và số file/byte; raw tick đã xóa không còn replay exact, bars/report/journal vẫn giữ.

Không đặt/check lệnh, chọn lot/risk tiền thật, tự tạo lịch, train model hoặc tự quét lặp. Người dùng yêu cầu xây/chỉnh hệ thống thì xử lý như công việc phát triển riêng, không chạy lượt thị trường vì skill này được nhắc tên.
