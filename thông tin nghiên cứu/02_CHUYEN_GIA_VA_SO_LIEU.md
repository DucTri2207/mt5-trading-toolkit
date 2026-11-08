# Chuyên gia, case study và số liệu công khai

Ngày nghiên cứu: 25/10/2026. Các nhận xét “hướng áp dụng” dưới đây là suy luận của dự án.

Tài liệu này tập trung các chuyên gia và case vàng ban đầu. Các case bổ sung cho tiền tệ và chỉ số được trình bày riêng ở tài liệu 07/08; không ghép chúng thành một track record chung.

## 1. Andrea Unger — thành tích có nguồn tổ chức, phương pháp vàng có nguồn tác giả

Ban tổ chức World Cup ghi nhận Andrea Unger đứng đầu sự kiện năm 2008 với mức tăng **671,90%**. Kevin Davey đứng đầu năm 2006 với **106,70%**. Đây là kết quả tài khoản dự thi; không phải số liệu winrate, drawdown hay R của một setup vàng. [S01 — ban tổ chức](https://www.worldcupchampionships.com/world-cup-trading-championship-historical-standings)

Unger Academy công bố hai hệ thống GC có kết quả năm 2026 tới tháng 10: intraday breakout **16.450 USD**, theo xu hướng **50.090 USD**; tổng **66.540 USD**, chưa tính commission/slippage. Tác giả nói giai đoạn ngoài mẫu bắt đầu từ 2018. Một mô hình dùng M15 và điều kiện co hẹp biến động, mô hình còn lại dùng M5 và phá kênh giá. Chưa có raw trades hoặc đầy đủ bộ lọc để tái tạo. [S02 — bài gốc](https://ungeracademy.com/blog/gold-trading-trend-following-strategies-2)

**Hướng áp dụng:** xây dựng loại setup phù hợp trạng thái thị trường; không dùng kết quả thi đấu để bảo chứng các hệ thống được giới thiệu sau này. Chưa thể xác nhận chúng đạt 1,5R/lệnh thắng.

## 2. Hệ thống học viên Andrea — breakout biên Á trên GC

Unger Academy công bố backtest: **2.859 lệnh, 49,98% thắng, PF 1,33, P&L 423.460 USD, max drawdown 35.070 USD, trung bình 148,11 USD/lệnh**. Khung tham chiếu là **20:00–00:00 ET**, mua khi phá đỉnh và bán khi phá đáy khoảng này. Năm 2026 là một phần năm. Bài gọi người phát triển là học viên Andrea; không xác nhận đó là Andrea Unger. [S03 — bài gốc](https://ungeracademy.com/blog/september-2026-gold-futures-trading-system)

**Giới hạn:** đây là backtest nhà cung cấp công bố; chưa rõ đầy đủ giả định phí, fill, SL và danh sách lệnh. Không có mẫu số rủi ro ban đầu để đổi average trade sang R. Mã đầy đủ nằm trong dịch vụ thành viên.

**Hướng áp dụng:** một playbook breakout phiên có thể mở thêm loại cơ hội. Tần suất và hiệu quả phải đo lại trên XAUUSD; không chuyển nguyên kết quả futures sang CFD.

## 3. Kevin Davey — nghiên cứu exits và kỷ luật phát triển

Nghiên cứu công khai của Davey so sánh **567.000 backtest, 40 thị trường, 5 cỡ nến, 15 kiểu exit**; gồm GC. Cỡ nến là **60, 120, 360, 720 phút và daily**, không phải M1/M5. Tác giả có đưa giả định commission/slippage và xét dữ liệu bên trong bar khi cần. Kết luận xếp hạng exit là của bộ thí nghiệm này, không chứng minh trailing luôn tốt hơn trên vàng scalp. [S05 — bài gốc](https://kjtradingsystems.com/algo-trading-exits.html)

Ông mô tả quy trình ngoài mẫu, walk-forward và incubation trong phương pháp phát triển hệ thống. [S06 — website tác giả](https://kjtradingsystems.com/)

**Hướng áp dụng:** so sánh exit độc lập với entry trên cùng tập cơ hội; sau đó mới so sánh cả hệ thống tuần tự. Không mặc định tự đảo chiều hoặc bỏ hard stop chỉ vì một kiểu exit đứng đầu nghiên cứu.

## 4. FTMO — case XAUUSD 249 lệnh

FTMO công bố giai đoạn **12 ngày giao dịch, 249 lệnh, 37,35% thắng**, tỷ lệ lãi trung bình/lỗ trung bình **2,80**, lợi nhuận **24.553,92 USD** trên account mô phỏng 100.000 USD. Lãi trung bình **659,28 USD**, lỗ trung bình **235,64 USD**. Phần mô tả SL ban đầu trong ví dụ là suy đoán của người viết. [S07 — bài gốc](https://ftmo.com/en/blog/the-machine-like-scalper-a-24-5-return-in-12-days-on-gold/)

**Giới hạn:** trader ẩn danh; không có quy tắc entry/SL đầy đủ, raw log hoặc xác nhận 2,80R theo SL ban đầu. Không thể coi số lot gần cố định là bằng chứng một thuật toán máy móc.

**Hướng áp dụng:** đọc số liệu như ví dụ payoff cao; nghiên cứu giữ phần lãi và cắt setup mất hiệu lực. Không lấy 20 ticket/ngày làm chỉ tiêu bắt buộc.

## 5. FTMO — case XAUUSD 85 lệnh

FTMO nêu **85 lệnh, winrate 40%, average RRR 2,59**, lợi nhuận **25.198,17 USD** trên account mô phỏng 100.000 USD. Bài mô tả lệnh lỗ thường ngắn hơn các lệnh lời tốt, nhưng tự xác nhận không thể xác định chính xác chiến lược từ chart. Khoảng thời gian đầy đủ chưa được xác lập từ phần văn bản đã đọc. [S08 — bài gốc](https://ftmo.com/en/blog/scalping-gold-to-a-25198-profit-mastering-one-instrument-in-both-directions/)

**Hướng áp dụng:** không ép mọi scalp đóng sau cùng số phút. Tuy nhiên “để lệnh thắng chạy” vẫn cần quy tắc có thể replay, không phải lý do giữ mọi lệnh đang lỗ.

## 6. Choon Chiat — trader đánh vàng có tên và quy tắc mô tả

FTMO mô tả tỷ lệ thắng khoảng **70%**, thường không quá **3 lệnh/ngày**, đọc **M30 rồi M5**, tìm vùng đi ngang và phản ứng tại hỗ trợ/kháng cự, dùng Bollinger Bands/RSI xác nhận; R:R dự kiến **1:1**. Bài không công bố chu kỳ BB/RSI và nói trader không đặt SL/TP trực tiếp. [S09 — bài gốc](https://ftmo.com/en/blog/top-ftmo-trader-choon-chiat-scalping-strategy-with-very-high-win-rate/)

**Hướng áp dụng:** có thể học cách phân biệt range, nhưng cơ chế không đặt hard SL không phù hợp bản thiết kế đề xuất. Không gán BB(20,2), RSI(14), ngưỡng 30/70 hay R=1,5 cho tác giả.

## 7. FTMO — 572 lệnh là phản ví dụ cần đọc

Case này có **572 lệnh trong 10 ngày hoạt động, 50% thắng, average RRR 1,60**, lợi nhuận mô phỏng **50.333,81 USD** trên account 200.000 USD. Ngày tệ nhất lỗ **9.937,07 USD**, chỉ cách giới hạn ngày **62,93 USD**. Một ví dụ gồm bốn ticket cùng giá, và không đặt SL trên ticket được minh họa. [S10 — bài gốc](https://ftmo.com/en/blog/how-a-gold-scalper-secured-50333-in-2-weeks/)

**Hướng áp dụng:** gộp ticket theo ý tưởng và tính tổng exposure. Đây không phải mẫu quản trị rủi ro để sao chép chỉ vì lợi nhuận hoặc tần suất cao.

## 8. Những người/đơn vị có phương pháp công khai nhưng chưa có thống kê phù hợp

| Người / đơn vị | Nội dung thực sự dùng | Thiếu dữ liệu gì để đánh giá hiệu quả? |
|---|---|---|
| Linda Raschke | Holy Grail: động lượng trước, pullback sau; tài liệu phỏng vấn gốc | Không có mẫu XAUUSD M5 với entry/exit và R ban đầu |
| Adam Grimes | Phân loại pullback, failure test, breakout | Không có winrate/PF cho cách chuyển thành thuật toán của dự án |
| Al Brooks | Trend/range và dời stop theo pullback | Phương pháp tùy nghi; không có hiệu quả xác minh cho bản cơ giới hóa này |
| Brian Shannon | AVWAP như tham chiếu bối cảnh | Không có bằng chứng dùng tick volume CFD tạo cùng kết quả |
| SMB Training | Playbook cổ phiếu với điều kiện và exit rõ hơn | Số thống kê tự nêu thiếu cỡ mẫu, kỳ đo, phí và raw trades |

Nguồn của từng phương pháp và thông số nằm trong tài liệu 03 và danh mục 01. Không phong các trường hợp này thành “top thế giới đã được kiểm toán”.

## Các kết luận được phép rút ra

- Có case công khai cho thấy tỷ lệ lãi/lỗ trung bình cao đi kèm winrate vừa phải. Chưa có nguồn trong đợt này chứng minh **cùng lúc** 80% thắng, lệnh thắng trung bình 1,5R ban đầu và tần suất cao bền vững trên XAUUSD.
- Chưa tìm được bộ chiến lược của trader quỹ nổi tiếng vừa có full rules, vừa có full log dài hạn và đầy đủ thay đổi SL. Khoảng trống này được giữ nguyên trong đánh giá.
- Phần có thể chuẩn bị chắc hơn là **cách định nghĩa, ghi nhận và kiểm định các cấu trúc**. Hiệu quả của cấu trúc mới vẫn cần được đo sau khi người dùng cho triển khai.
