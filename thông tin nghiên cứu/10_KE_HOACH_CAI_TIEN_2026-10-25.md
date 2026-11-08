# Kế hoạch cải tiến cấu trúc indicator — 25/10/2026

> **Tài liệu lịch sử, hướng P2 đã được thay thế.** Nhiệm vụ hiện hành là cải tiến trực tiếp lõi H1/sweep/xác nhận của scalp cũ theo [bộ bàn giao mới](ban_giao_scalp_cu_2026-10-25/README.md). Giữ phần dưới để tra lịch sử; không triển khai lại P2 theo D01/G2 của tài liệu này.

Trạng thái: **kế hoạch để review; chưa code, chưa chạy chiến lược mới, chưa triển khai**.

## 1. Kết quả muốn đạt

Xây dựng cấu trúc chỉ báo có thể tìm cơ hội có khoảng chạy hợp lý từ **1,5R ban đầu**, quản lý SL theo diễn biến giá và tạo tần suất hữu ích. Phạm vi nghiên cứu gồm vàng, cặp tiền và chỉ số; pilot đề nghị là **XAUUSD** để có đối chứng từ dự án hiện tại.

Không lấy số lần sửa setting, số chỉ báo ghép vào hoặc danh tiếng tác giả làm thước đo cải tiến. Kết quả cần được chứng minh bằng hành vi đúng thời điểm và hiệu quả sau chi phí.

## 2. Những quyết định thiết kế đề nghị

| Mã | Quyết định cho bản kế hoạch | Lý do |
|---|---|---|
| D01 | Đánh giá **P2 — pullback tiếp diễn** đầu tiên | Khảo sát khả năng vào gần điểm mất hiệu lực và giữ nhịp thuận xu hướng |
| D02 | Pilot chỉ so **E0 target 1,5R** với **E1 trailing cấu trúc** | Biết phần cải thiện đến từ entry hay exit; hạn chế số biến thể |
| D03 | Kiểm tra target/cản có trước và room tại entry | Không dựng target xa tùy ý để có RR đẹp |
| D04 | Giữ nguyên R0 theo entry fill và initial SL | Dời stop hoặc chốt bớt không được đổi mẫu số |
| D05 | Tách ứng viên thị trường khỏi kế hoạch đang active | Đo được cơ hội mất ở detector, room, fill hay giới hạn vị thế |
| D06 | Phát hiện trên nến đóng; quản lý stop/exit theo quote có thứ tự | Tránh dùng thông tin xuất hiện sau thời điểm quyết định |
| D07 | Mỗi ý tưởng có một khóa, một kết quả tổng | Không tăng tần suất bằng nhiều ticket hoặc nhận cùng sóng nhiều lần |
| D08 | P1 breakout/retest, P3 failure và ATR trail nằm sau pilot | Không tạo một hệ thống lớn trước khi biết nhánh đầu có giá trị |

Đây là hướng để chuẩn bị triển khai, chưa phải chiến lược được chọn nhờ thành tích backtest. Cơ sở phương pháp và giới hạn nguồn đã nằm trong tài liệu 01–09.

## 3. Lộ trình theo phụ thuộc

| Giai đoạn | Việc sẽ làm khi được yêu cầu code | Sản phẩm bàn giao | Điều kiện chuyển bước |
|---|---|---|---|
| G0 — Đóng băng và rà soát mô phỏng | Lưu baseline, kiểm tra phút entry, chi phí, thứ tự bar/tick, cách chọn lệnh | Đặc tả replay và log chẩn đoán | Không còn sai khác chưa giải thích có thể làm đẹp kết quả |
| G1 — Chẩn đoán khả năng 1,5R | Trên entry/SL có sẵn, đo first-hit 1/1,5/2R trước initial SL | Bảng MFE/MAE và lý do không đạt theo bối cảnh | Biết cần sửa entry, loại cơ hội hay quản lý lệnh; không yêu cầu kết quả phải đẹp |
| G2 — Lõi P2 | Levels/pivot xác nhận, bối cảnh, pullback, trigger và hủy | Detector có nhật ký từng ứng viên | Replay prefix cho cùng tín hiệu tại cùng thời điểm |
| G3 — Kế hoạch và trailing | Initial SL, room, fill, R0, vòng đời, E0/E1 | Chuỗi sự kiện entry/stop/exit có thể đối chiếu | Không nới SL, không hồi tố, không bỏ mất bar entry |
| G4 — Đối chiếu MQL5/Python | Cùng fixture và dữ liệu, so signal/stop/event | Báo cáo sai khác đến từng sự kiện | Các sai khác được xử lý hoặc ghi là giới hạn dữ liệu; không chỉ so tổng P&L |
| G5 — Đánh giá lịch sử và ngoài mẫu | Kiểm định đủ 5 năm khả dụng, walk-forward, chi phí và độ ổn định | Báo cáo đầy đủ cả trường hợp yếu | Đạt các cổng kinh tế được chốt trước khi chạy |
| G6 — Bản indicator thử nghiệm | Kết nối panel, mức SL đề xuất, log và đóng gói | Artifact riêng có version, hash, hướng dẫn | Build sạch và kế hoạch trên chart khớp log/replay |
| G7 — Shadow/forward | Thu mẫu đúng version và broker | Báo cáo theo thời gian và cỡ mẫu | Không suy kết quả live từ backtest; quản lý mẫu theo version |
| G8 — Mở rộng | P1/P3, rồi cặp tiền/chỉ số, rồi danh mục | Báo cáo lợi ích tăng thêm của từng phần | Mỗi phần phải tự có bằng chứng; không kế thừa số liệu vàng |

Các giai đoạn chưa bắt đầu. Không ấn ngày hoàn thành code hoặc ngày pass quỹ khi chưa có dữ liệu và chưa bắt đầu triển khai.

## 4. Các chỉ số phải đo cùng nhau

| Mục tiêu | Cách đo | Trạng thái ngưỡng |
|---|---|---|
| Khoảng đích từ 1,5R | Room tại entry tới mức có nguồn gốc, tính đệm/chi phí đúng quy ước | Mục tiêu thiết kế ban đầu |
| Thu được khoảng 1,5R | Mean/median R ròng của lệnh thắng; tỷ lệ lệnh thực thu ≥1,5R | Mục tiêu cần kiểm định, không đồng nhất với MFE |
| Winrate cao | Win/loss/BE tách riêng, kèm cỡ mẫu và khoảng tin cậy | Chưa chốt con số; không âm thầm bỏ mục tiêu |
| Tần suất đủ dùng | Unique ideas và filled trades/tháng, theo asset và cả danh mục | Người dùng chưa chốt con số; không đặt quota phát lệnh |
| Hiệu quả kinh tế | Net expectancy, PF, net R/tháng và độ ổn định theo giai đoạn | Đề nghị thảo luận PF >1,5 và expectancy dương; chưa là cổng đã phê duyệt |
| Rủi ro | Equity DD, worst day, chuỗi lỗ, exposure gộp | Phụ thuộc kế hoạch rủi ro và gói quỹ chưa chọn |

Một điều kiện đúng về kỹ thuật không chứng minh hiệu quả kinh tế. Thêm mục tiêu xa hơn có thể giảm winrate; dời stop sớm có thể làm mất runner. Cần trình bày rõ các đánh đổi.

## 5. Phạm vi sau pilot vàng

- **Vàng:** P2 trước; P1/P3 đo riêng khi có lý do bổ sung.
- **Forex:** EURUSD trước để đối chiếu nguồn; GBPUSD/USDJPY/AUDUSD kiểm tra riêng đơn vị, phiên, spread và exposure tiền tệ.
- **Chỉ số:** chọn một symbol có dữ liệu/spec rõ để pilot ORB hoặc pullback, sau đó mới xem US100/US500/US30/GER40 khác nhau thế nào.
- Danh mục chỉ được đánh giá sau khi có dòng sự kiện đồng bộ. Tăng tổng số tín hiệu không tự chứng minh đa dạng hóa.

## 6. Các điểm chưa chốt nhưng không cản việc lập kế hoạch

Tần suất mong muốn; định nghĩa mục tiêu 1,5R cuối cùng; drawdown có thể chịu; gói quỹ; mức giveback; thời hạn giữ lệnh và nguồn lịch tin. Tài liệu 11 ghi các giả định kỹ thuật dự thảo. Các phần này cần khóa trước khi dùng kết quả test làm quyết định, không cần người dùng trả lời để hoàn thành bộ tài liệu hôm nay.

## 7. Cách quyết định sau mỗi giai đoạn

Nếu có sai lệch mô phỏng: xử lý tính đúng trước, ghi ảnh hưởng rồi mới đánh giá lại. Nếu code đúng nhưng hiệu quả yếu: phân tích đúng nhóm nguyên nhân, không mở grid lớn để tìm một cấu hình đẹp. Nếu một nhánh tốt: giữ version của nó làm đối chứng cho nhánh tiếp theo.

Không có bước nào trong kế hoạch được gọi là “đảm bảo 10/10” hay “chắc chắn pass quỹ”. Kế hoạch đánh giá xác suất thành công và thất bại theo giả định, thay vì cam kết kết quả chưa có bằng chứng.
