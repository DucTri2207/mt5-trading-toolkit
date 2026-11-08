# Kế hoạch triển khai — 25/10/2026

> **Tài liệu lịch sử của pilot P2.** Chỉ dẫn hiện hành nằm trong [bộ bàn giao cải tiến scalp cũ](ban_giao_scalp_cu_2026-10-25/README.md), đặc biệt phần package và gate của tài liệu03. Không dùng file này để triển khai lại P2 hay ghi đè indicator chính.

Trạng thái hiện tại: **chỉ lập kế hoạch**. Không có thao tác biên dịch, copy vào MT5, gắn chart hoặc khởi động monitor mới trong đợt này.

## 1. Triển khai theo từng tầng

| Tầng | Việc dự kiến | Bằng chứng phải có |
|---|---|---|
| T0 — Workspace lab | Tạo phiên bản thử nghiệm riêng khi bắt đầu code | Spec version, baseline và diff rõ |
| T1 — Replay offline | Chạy detector/management trên dữ liệu và fixture | Event parity, coverage và lỗi đã xử lý |
| T2 — Build riêng | Biên dịch wrapper và các dependency đã khai báo | Compile log, binary mới, hash, 0 errors/0 warnings |
| T3 — MT5 chart thử | Gắn artifact riêng trên chart thử nghiệm | Entry/SL/trailing hiển thị khớp event log; không cần khả năng gửi lệnh |
| T4 — Shadow/forward | Thu tín hiệu mới theo version cố định | Quote lúc phát hiện, độ trễ, trạng thái và kết quả đúng phiên bản |
| T5 — Quyết định bản dùng chính | Review kỹ thuật, kinh tế và vận hành | Kết quả đủ điều kiện đã chốt; biết cách rollback |

Khi có chỉ dẫn triển khai trong tương lai, tiếp tục trong phạm vi đã được cho phép; không tạo các vòng xin xác nhận lặp lại cho bước đã được ủy quyền. Việc lập kế hoạch hôm nay không kích hoạt T0.

## 2. Đóng gói và tên artifact

Tên đề nghị cho lab: `duc_tri_scalp_structure_lab`. Version lab và `spec_version` nằm trong log/manifest. Không gắn nhãn release chính hoặc đổi version indicator đang dùng chỉ vì build thành công.

Package dự kiến gồm wrapper source/EX5, đúng các `.mqh` cần thiết, thông số thí nghiệm, log compile và manifest SHA-256. Dependency hệ thống như Canvas dùng bản MetaTrader có sẵn; không cài thư viện mới nếu chưa cần.

Đường dẫn dự kiến trong workspace: `D:/trading thử lần cuối cuối/reports/scalp_structure_lab/<run-id>/`. `<run-id>` sẽ gồm thời gian chạy và spec version, tránh ghi đè báo cáo 24/10.

Thư mục đích MT5 lab dự kiến: dưới **data directory thực tế** của terminal được chọn, trong `MQL5/Indicators/DucTriLab/<version>/`. Giữ layout các include cục bộ khớp package; không copy đè thư mục Include dùng chung.

Trước copy phải xác minh data directory hiện tại, đường dẫn cuối và dependency closure. Không dùng đường dẫn terminal cũ hardcode làm bằng chứng đang trỏ đúng MT5.

## 3. Build tách khỏi đồng bộ bản dùng chính

Script [compile_sync_scalp_distance.py](<D:/trading thử lần cuối cuối/scripts/compile_sync_scalp_distance.py>) hiện copy source vào tên indicator chính trước khi compile và ghi lại EX5. Vì vậy không chạy nguyên script đó cho lab.

Thiết kế công cụ build tương lai cần nhận source/output/log cụ thể, build ở staging riêng, xác minh binary được sinh từ lần compile mới, rồi mới copy package đúng tên lab. Nếu compile lỗi thì giữ log và source để sửa; không xóa hoặc thay binary bản chính.

Không dùng duy nhất exit code của MetaEditor để kết luận. Phải đọc log, kiểm tra timestamp/output và so hash source/dependency/package.

## 4. Checklist chart thử

- Symbol và timeframe đúng spec; đủ warm-up; nhận diện được nến đóng và quote stale.
- Panel phân biệt entry dự kiến, fill giả lập và SL đề xuất. Không tuyên bố đã sửa SL broker.
- P2/E0/E1 hiện đúng version; một ý tưởng không phát lại khi tick mới hoặc refresh chart.
- Stop cũ và stop mới chuyển trạng thái đúng thời điểm; TP/SL/expiry/invalidated khớp event log.
- Reload/reconnect không phát cảnh báo lịch sử như tín hiệu forward mới.
- Tần suất được tách thành candidates/accepted/filled; không đếm nhiều ticket thành nhiều idea.

Chỉ đánh giá những chức năng thực sự nằm trong pilot. Telegram/LLM/EA không được thêm vào để làm pilot có vẻ hoàn chỉnh hơn.

## 5. Thu mẫu shadow

Mẫu lab dùng file/state/log riêng gắn `spec_version`, không nhập vào `paper_shadow_trades_20261024.json` của preset v3.12. Lịch sử nạp làm context và tín hiệu bắt kịp sau downtime phải có nhãn riêng; không coi quote hiện tại là giá fill live của một tín hiệu đã cũ.

Mỗi poll thành công và lỗi đều có trạng thái sức khỏe, timestamp và nguyên nhân. Process còn sống nhưng không poll thành công cần được phát hiện. Không chỉ dựa vào sự tồn tại của state file hoặc PID cũ.

Entry/exit paper theo Bid/Ask và phí quan sát/giả định có nhãn; slippage không biết thì ghi chưa đo, không điền 0 để gọi là thực tế. Mẫu forward phải phản ánh đúng bản đã khóa.

Mốc review đề nghị 25/50 tín hiệu kết hợp review theo thời gian. Số mẫu đánh giá cuối phụ thuộc độ bất định và kết quả, không tự động pass ở 100/200. Không thay tham số giữa một cohort; đổi spec thì mở cohort mới.

Các thay đổi heartbeat/monitor chỉ thực hiện nếu là phần công việc được yêu cầu lúc triển khai; không tạo automation mới trong bước lập kế hoạch.

## 6. Cách đo khả năng đáp ứng quỹ

Chỉ mô phỏng khi có hồ sơ quy tắc đúng đơn vị/gói/ngày hiệu lực: mục tiêu từng vòng, giới hạn equity ngày/tổng, thời điểm reset, trailing drawdown nếu có, consistency, tin tức và hạn giữ lệnh.

Trên dòng giá/lệnh theo thời gian, ghi lúc chạm target, lúc vi phạm, số phiên tới mỗi kết quả và exposure. Lãi/lỗ mở và chi phí phải tham gia kiểm tra giới hạn, không chỉ balance cuối ngày.

Bootstrap/Monte Carlo chỉ bổ trợ và phải nêu giả định về cụm giao dịch, phiên và chi phí. Tỷ lệ pass của mô phỏng không được quảng bá là xác suất pass thật hoặc bảo đảm tương lai.

Chưa chọn gói quỹ trong hồ sơ này, nên bước này chưa đủ đầu vào để ra một con số pass đáng tin cậy.

## 7. Rollback

Package lab được lưu riêng. Khi lỗi: dừng đường chạy lab liên quan, giữ log/candidate/outcome để chẩn đoán, bỏ bản lab khỏi chart thử nếu cần và quay về artifact đã xác minh. Không xóa log hoặc nạp preset khác để che mất lỗi.

Nếu sau này thay bản dùng chính theo chỉ dẫn lúc đó: sao lưu đúng artifact/settings/chart liên quan trước, lưu manifest source/EX5/dependency, thực hiện thay có giới hạn và có đường phục hồi. Không dùng thao tác xóa/move đệ quy trên đường dẫn terminal tính động.

## 8. Khi nào có thể gọi là đã triển khai?

Cần phân biệt: đã code, đã compile, đã kiểm định hành vi, đã gắn chart thử, đã có mẫu forward, và đã được chọn làm bản chính. Mỗi trạng thái phải có bằng chứng tương ứng. Không coi việc tạo file `.mq5` hoặc có EX5 là đã hoàn thành mục tiêu scalp/1,5R/pass quỹ.
