# Playbook cấu trúc đề nghị nghiên cứu

Trạng thái: thiết kế giả thuyết ngày 25/10/2026. Chưa có module nào được triển khai hoặc backtest trong đợt này.

Đây là phần thiết kế trên vàng. Chuyển sang các cặp tiền và chỉ số phải dùng hồ sơ thị trường trong tài liệu 07/08/09, không sao chép nguyên điều kiện phiên hoặc đơn vị rủi ro.

## Từ phương pháp gốc sang giả thuyết của dự án

Đề nghị giữ **ba nhánh độc lập**, có điều kiện thị trường và cơ chế hủy khác nhau. Một tín hiệu không phải thỏa đồng thời cả ba nhánh. Những điều kiện chung chỉ gồm dữ liệu hợp lệ, rủi ro có giới hạn, chi phí và khoảng đích khả thi.

### P1 — Breakout sau tích lũy, có xác nhận hoặc retest

**Nguồn ý tưởng:** mô hình breakout co hẹp và range phiên của Unger Academy [S02](https://ungeracademy.com/blog/gold-trading-trend-following-strategies-2), [S03](https://ungeracademy.com/blog/september-2026-gold-futures-trading-system).

**Cấu trúc đề nghị:**

1. Xác lập biên trên/dưới của vùng tích lũy hoặc phiên đã hoàn tất. Lưu thời điểm cả hai biên trở thành thông tin có sẵn.
2. Phân biệt giá phá biên rồi giữ được bên ngoài với việc chỉ chọc râu và quay vào.
3. Có hai biến thể entry để nghiên cứu riêng: vào sau breakout được xác nhận, hoặc đợi retest thành công. Không chọn biến thể sau khi đã biết kết quả lệnh.
4. SL ban đầu đặt ngoài mức làm setup mất hiệu lực, không bóp SL để đạt tỷ lệ R mong muốn.
5. Xác định vùng đích trước khi vào; hủy nếu retest thất bại, giá chạy quá xa hoặc cơ hội đã hết hạn.

**Lý do có thể hữu ích:** tạo loại cơ hội tiếp diễn không bắt buộc phải quay về một vùng H1 cũ. Giả thuyết này cần được đo, chưa chứng minh tần suất tăng.

**Rủi ro kiểm định:** breakout khi spread giãn, retest dùng low/high chưa biết, hoặc backtest limit luôn được khớp ở giá đẹp.

### P2 — Pullback tiếp diễn sau một nhịp đẩy

**Nguồn ý tưởng:** Holy Grail của Raschke và cấu trúc pullback của Grimes [S11](https://lindaraschke.net/wp-content/uploads/2026/03/raschke_pt2_0304.pdf), [S12](https://www.adamhgrimes.com/fundamental-trading-patterns/).

**Cấu trúc đề nghị:**

1. Nhận diện một nhịp đẩy có hướng và cấu trúc đã xác nhận; lưu đỉnh/đáy và thời điểm phát hiện.
2. Nhịp hồi chưa phá điểm mất hiệu lực của xu hướng. Phân biệt pullback nông, pullback phức tạp và đảo chiều.
3. Chờ giá tái khẳng định hướng cũ bằng nến đóng hoặc phá cấu trúc vi mô đã biết. M1 chỉ là biến thể timing riêng, không được dùng kết quả đóng M5 trước khi M5 đóng.
4. Stop nằm ngoài đáy/đỉnh pullback có ý nghĩa; nếu entry quá muộn làm room dưới 1,5R thì ghi rõ và bỏ.
5. Quản lý tiếp diễn theo các pullback mới; hủy khi cấu trúc bị phá hoặc động lượng không tiếp diễn theo quy tắc được khai báo trước.

**Lý do có thể hữu ích:** tách cơ hội thuận xu hướng khỏi mô hình quét mép vùng H1. Không lấy EMA chạm giá làm tín hiệu hoàn chỉnh.

### P3 — Phá vỡ thất bại tại mức đã có trước

**Nguồn ý tưởng:** failure test của Grimes; breakout và mean reversion được tách riêng trong tài liệu Unger [S12](https://www.adamhgrimes.com/fundamental-trading-patterns/), [S04](https://ungeracademy.com/blog/strategies-on-gold-that-balance-each-other-diversify-your-trading-portfolio).

**Cấu trúc đề nghị:**

1. Mức tham chiếu phải tồn tại trước sự kiện: đỉnh/đáy phiên hoàn tất, ngày trước hoặc swing đã xác nhận.
2. Giá giao dịch vượt mức rồi đóng trở lại phía trong. Một râu dài ở bất kỳ chỗ nào không đủ định nghĩa failure test.
3. Chờ phản ứng ngược hướng và kiểm tra đường đi tới đích; không mua giữa range chỉ vì RSI thấp.
4. Stop nằm ngoài cực trị thất bại cộng đệm hợp lý. Đích là mức tham chiếu đối diện đủ room, không dựng một target giả cách entry đúng 1,5R.
5. Hủy khi giá lấy lại hướng breakout và chấp nhận giao dịch ngoài biên theo định nghĩa đã khóa.

**Lý do có thể hữu ích:** dùng mức giá có trước làm nền cho mô hình sweep hiện tại và nhận diện lúc nào nên đảo chiều thay vì đuổi breakout.

## Router bối cảnh — thay đổi cấu trúc, không thêm một chuỗi AND dài hơn

| Bối cảnh đề nghị | Nhánh được xét | Điều cần tránh |
|---|---|---|
| Tích lũy đã xác lập, xuất hiện mở rộng biên | P1 | Mặc định fade mọi breakout |
| Xu hướng có nhịp hồi còn hợp lệ | P2 | Đòi mọi pullback quay về H1 supply/demand |
| Kiểm tra biên rồi bị từ chối | P3 | Dùng râu nến đơn lẻ hoặc pivot tương lai |
| Dữ liệu thiếu, quote cũ, sự kiện chưa rõ | Chưa phát kế hoạch | Gán nhãn chắc chắn cho dữ liệu không đủ |

M15/M5 là cặp khung thời gian để thiết kế thí nghiệm; M1 timing là nhánh thử riêng. Chưa chốt thuật toán regime hoặc ngưỡng ADX/EMA cho vàng. H1 vẫn có thể cung cấp bối cảnh và cản, nhưng không mặc định làm cửa bắt buộc cho mọi playbook.

## Thông số thực sự có trong tài liệu gốc

| Nguồn | Thông số hoặc quy tắc được công bố | Vai trò và giới hạn |
|---|---|---|
| Raschke, S11 | EMA **20 bar**, ADX **14 bar**, ví dụ ADX vượt **30** trên SPX **30 phút** | Mô hình momentum rồi pullback; chưa phải preset XAUUSD M5 |
| Unger, S02 | Mô hình **M15** breakout, mô hình **M5** phá kênh N kỳ | N, bộ lọc đầy đủ và các stop chưa được công bố trong bài |
| Học viên Andrea, S03 | Biên **20:00–00:00 ET** | Mốc gốc của case; phải xử lý America/New_York và DST, không cố định UTC quanh năm |
| Unger, S04 | Một mô hình **M5** phá đỉnh/đáy ngày trước; nhánh đảo chiều có xác nhận **M15** | Hai logic khác nhau, không ghép điều kiện đối nghịch thành một entry |
| Choon Chiat, S09 | **M30 → M5**, mô tả R:R **1:1** | Không công bố period BB/RSI; không phải mô hình 1,5R |
| SMB, S14 | **EMA9/VWAP**, stop bằng **1/3** nhịp đo, target một nhịp đo | Playbook cổ phiếu; không suy ra cùng winrate trên vàng |
| StockCharts, S15 | Chandelier mặc định **22 kỳ**, **3×ATR(22)**, minh họa daily | Công thức tham khảo, không tự chuyển 22 ngày thành 22 nến M1/M5 |
| Brooks, S13 | Trail theo đáy pullback đã hoàn thành sau một đỉnh mới; SELL đối xứng | Không có hằng số ATR hoặc winrate XAUUSD trong bài |

Nguồn bổ sung: [S09 — Choon](https://ftmo.com/en/blog/top-ftmo-trader-choon-chiat-scalping-strategy-with-very-high-win-rate/), [S14 — SMB PDF](https://www.smbtraining.com/blog/wp-content/uploads/2024/04/The-Fashionably-Late-Scalp-Cheat-Sheet.pdf), [S15 — Chandelier](https://chartschool.stockcharts.com/table-of-contents/technical-indicators-and-overlays/technical-overlays/chandelier-exit), [S13 — Brooks](https://www.brookstradingcourse.com/futures-market/trade-trend-channels/).

SMB tự nêu 60% thắng và 3:1 trong cheat sheet nhưng thiếu cỡ mẫu/kỳ đo/phí; không coi là số liệu đã kiểm chứng. Dòng giờ “Mid-Day” có cách ghi AM không nhất quán, nên không dùng làm luật phiên.

## Vai trò bổ trợ của AVWAP

Brian Shannon mô tả AVWAP như tham chiếu giá, volume và thời gian từ một điểm neo [S16](https://alphatrends.net/anchored-vwap/). Với dự án này, chỉ xem đây là **bối cảnh tùy chọn**, không thêm mặc định vào ba entry. Trên CFD, nếu chỉ có tick volume thì phải ghi rõ VWAP proxy; chưa có feed xác minh thì không triển khai footprint, delta hay hấp thụ lệnh “tổ chức”.

## Ưu tiên nghiên cứu tiếp theo

P1 và P2 phù hợp nhất để khảo sát khả năng đi xa hơn 0,5R; P3 giúp mô hình phản ứng tại biên có định nghĩa rõ hơn. Mỗi nhánh phải được đánh giá riêng trước khi kết hợp. Chưa có cơ sở chọn một nhánh làm preset thắng cuộc.
