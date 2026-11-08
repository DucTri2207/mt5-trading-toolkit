# Mục tiêu người dùng — hỗ trợ đánh giá FTMO

Ngày 04/11/2026, trong chat `01a1a504-cbf2-7643-a19d-e87baf268dac`, người dùng nhắc lại mục tiêu ban đầu là **pass quỹ** và trả lời tên quỹ là **FTMO**. Đây là mục tiêu chi phối phần bàn giao tiếp theo, không thay bằng mục tiêu bán phần mềm hoặc chỉ có framework chạy được.

## Trạng thái và phạm vi đã được ủy quyền

- Công cụ dùng chung dữ liệu MT5, hai setup seed hiện tại, snapshot/context/card, replay, analysis_note và paper journal là hạ tầng để hỗ trợ quyết định theo mục tiêu đó.
- B3/B4 evaluator/B5 và B6A đã đạt phạm vi kỹ thuật offline được ghi trong CONTROL/reviews. Nghiên cứu B4 hiện có kết quả âm/không hỗ trợ seed v0.1 trên dữ liệu đã tiếp xúc và M1 proxy. Không nâng kết quả đó thành lợi thế dương hoặc khả năng pass FTMO.
- FTMO được người dùng chọn; **chưa chốt 1-Step hay 2-Step**, loại tài khoản, ngày order và hồ sơ challenge thực tế. Không tự chọn mức vốn hay rủi ro tiền thật. Có thể hoàn thiện evaluator/harness cho các hồ sơ tách biệt trước, giữ selection=UNCONFIGURED tới khi có lựa chọn cụ thể.
- Chỉ read-only/paper. Không mua challenge, đăng nhập/đổi tài khoản, gửi/check order, bật Algo Trading hoặc tự đóng vị thế. Mọi rule/risk gate hiện ở mức cảnh báo, đánh giá và từ chối đề xuất trong công cụ.

## Tiêu chí phải bổ sung trong B6C sau khi B6B đạt

1. **Hồ sơ luật FTMO có version và nguồn chính thức.** Phân biệt program, phase và chế độ luật theo ngày áp dụng. Thiếu lựa chọn hoặc rule input cần thiết → UNCONFIGURED/UNKNOWN, không PASS mặc định.
2. **Đánh giá challenge từ equity timeline thực sự.** Gồm balance, floating P/L, fees/swap, giới hạn lỗ trong ngày và toàn kỳ, reset theo múi giờ/DST của luật, target ở trạng thái đã đóng vị thế và ngày giao dịch đủ điều kiện. Chỉ có closed PnL/R hoặc thiếu marks không đủ kết luận không vi phạm intraday.
3. **Data/source fidelity.** Nguồn demo tham chiếu, dữ liệu synthetic, phí giả định, clock chưa xác minh hoặc quote proxy phải được phân loại đúng. Snapshot generic MT5 không tự là hồ sơ thực thi FTMO được xác minh. Không thay nguồn/account để cứu kết quả.
4. **Luồng paper dùng được và protocol triển vọng.** Freeze engine/config/source/rules/risk assumptions, ghi quyết định baseline và AI trước kết quả, giữ cả bỏ qua/no-signal/missing data, đánh giá lợi nhuận/rủi ro/frequency và mục tiêu challenge theo mốc thật. Không liên tục đổi seed hoặc tự tìm tham số lịch sử đẹp.
5. **Vận hành và bàn giao.** Durable collector/paper, crash/restart/dedup/health/stop, lệnh chạy được, logs và gói tái lập. Nghiệm thu phần mềm, điều kiện sẵn sàng chạy nguồn thật, kết quả paper theo luật và kết quả challenge thực tế là các kết luận riêng, có bằng chứng riêng.

Khi thiếu terminal đúng nguồn hoặc cấu hình challenge, hoàn tất software/fake/doc/packaging độc lập; ghi rõ bước cần người dùng và mốc theo dõi. Không gọi mục tiêu pass quỹ đã hoàn thành chỉ vì B6C phần mềm đạt hoặc đã freeze. Cũng không hứa công cụ sẽ làm seed có lãi; kết quả cần được đo.

## Nguồn chính thức đã kiểm ngày 04/11/2026

- [FTMO Trading Objectives](https://ftmo.com/en/trading-objectives/): loss rules xét equity gồm floating P/L và chi phí; reset ngày theo 00:00 CE(S)T; 1-Step có daily amount 3% initial capital và EOD trailing maximum-loss amount 10%. Đây là thông tin cho evaluator, không phải khuyến nghị chọn chương trình.
- [FTMO 2-Step](https://ftmo.com/en/2-step-challenge/): target Challenge/Verification 10%/5%, daily loss 5%, maximum loss 10%, minimum 4 trading days. Cần đọc định nghĩa chi tiết trước khi mã hóa semantics, không chỉ lấy bảng marketing.
- [FTMO 1-Step](https://ftmo.com/en/1-step-challenge/): single evaluation, target 10%. Trang giới thiệu vẫn có nhãn Best Day; phải xử lý cùng thông báo có ngày dưới đây.
- [FTMO Trading Update, 08/10/2026](https://ftmo.com/en/blog/trading-updates/trading-update-8-oct-2026/): từ order 1-Step tạo lúc 09:00 ngày 12/10/2026 theo platform time GMT+3, Consistency thay Best Day; order cũ giữ chế độ cũ. Consistency dùng total profit (gồm ngày âm), Best Day cũ dùng tổng ngày dương. Vượt tỷ trọng là chưa đủ điều kiện, không tự là breach. Không áp một denominator cho mọi hồ sơ hoặc âm thầm bỏ ngày âm.

Lưu ý nguồn: trang tổng quát/marketing có thể chậm cập nhật so với thông báo có ngày; phải lưu provenance và effective regime. Worker cần xác minh lại nguồn chính thức khi khóa hồ sơ triển khai và ghi các chỗ chưa rõ là UNKNOWN, không đoán luật.
