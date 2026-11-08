# Kế hoạch kiểm định sau nghiên cứu

Đây là kế hoạch cho lần triển khai được yêu cầu sau này. **Chưa chạy các thí nghiệm này trong đợt nghiên cứu.**

## Điều cần chứng minh

Một cấu trúc đáng triển khai phải có hiệu quả sau chi phí, cơ hội phù hợp tần suất người dùng cần, khả năng giữ lợi nhuận theo R0 và drawdown phù hợp. Không đổi mục tiêu thành thắng nhiều lệnh nhỏ, hoặc tăng số ticket để đạt tần suất.

Người dùng chưa chốt số lệnh/tháng và mức drawdown chấp nhận được. Tạm trình bày các kịch bản tần suất trong tài liệu 04; chúng chưa là cổng pass/fail được phê duyệt. Mục tiêu 1,5R phải đo theo định nghĩa đã thống nhất, không chỉ theo vị trí đường TP.

## Thiết kế thí nghiệm tối thiểu

| Mã | Câu hỏi | Cách so sánh |
|---|---|---|
| R01 | Tín hiệu hiện tại có đủ khả năng đi xa? | Từ cùng entry và initial SL, đo first passage tới 1/1,5/2R trước initial SL, MFE/MAE và thời gian; chưa áp trailing |
| R02 | Trailing có giữ thêm lãi hay cắt mất sóng? | Trên cùng cơ hội hợp lệ, so target 1,5R, structure trail và ATR trail |
| R03 | Entry mới có giá trị tăng thêm? | P1/P2/P3 riêng, cùng mô hình chi phí và một exit đối chứng |
| R04 | Room gate có dự báo khả năng đạt đích? | So có/không gate trên candidate log, tính cả số cơ hội bị mất |
| R05 | M1 timing có cải thiện thật? | So timing M5 với M1 đã đóng; ghi các limit không fill và trường hợp trượt giá |
| R06 | Kết hợp setup có tăng tần suất hữu ích? | Gộp theo thời gian, khử cùng ý tưởng, xét overlap, rủi ro và thứ tự exit thực |
| R07 | Kết hợp symbol có thêm nguồn độc lập? | So từng asset với danh mục đồng bộ; đo exposure và DD gộp |

R01 là chẩn đoán quan trọng: nếu phần lớn entry mất hiệu lực trước khi đi được 1,5R, sửa exit một mình không đủ. Cần xem lại loại cơ hội, điểm vào hoặc điểm mất hiệu lực có ý nghĩa.

## Hai cấp replay phải tách biệt

1. **So exit trên cùng tập cơ hội:** giúp biết khác biệt xuất phát từ quản lý lệnh, không từ việc mỗi exit chọn một tập entry khác.
2. **Replay tuần tự cả hệ thống:** một exit thay đổi thời gian giữ và cơ hội tiếp theo, vì vậy phải chọn lại các lệnh theo chính exit đó trên dòng thời gian.

Không chọn chuỗi lệnh bằng exit M5 rồi gọi kết quả quản lý M1/tick là replay tuần tự đầy đủ nếu thời điểm thoát khác nhau. Phải kiểm tra sự khác biệt này trong harness tương lai trước khi công bố số tổng.

## Dữ liệu và tính khả dụng theo thời điểm

- Cùng symbol/broker đích, nến và Bid/Ask lịch sử khi có. Lưu phần tick thiếu, không tự coi cửa sổ có vài tick là phủ đầy đủ cả trade.
- Tín hiệu từ nến đóng; level/pivot chỉ dùng sau thời điểm xác nhận. Kiểm tra dữ liệu prefix cho cùng kết quả tại cùng thời điểm.
- Dùng đúng thời gian đặt limit, stop mới và fill. Không cho stop tạo từ high/low cả bar có hiệu lực từ đầu bar.
- Khi OHLC không biết thứ tự chạm, dùng kịch bản bất lợi hoặc ghi không xác định. Tick chỉ giúp khi coverage được xác minh.
- Tách chart Bid/Last khỏi Ask; lệnh BUY mở/đóng đúng phía quote và SELL đối xứng. Commission/swap/slippage phải được tính đúng một lần.
- Bổ sung lịch news/phiên có dữ liệu lúc đó; thiếu lịch ghi UNKNOWN. Không giả có bảo vệ tin trong kỳ kiểm định.
- Với futures: lưu quy tắc roll và khác biệt hợp đồng liên tục. Với CFD: kiểm tra gap phiên, swap và spec broker riêng.

## Cách chia dữ liệu và tránh tối ưu quá mức

Dữ liệu 2021–2026 hiện tại đã được xem nhiều lần; không gọi lại 2025–2026 là holdout nguyên vẹn cho cấu trúc mới. Vẫn dùng được làm dữ liệu phát triển và đánh giá hồi cứu với nhãn rõ.

Trước khi chạy cần đăng ký danh sách giả thuyết, policy và giới hạn số biến thể. Chọn tham số chỉ từ train của từng fold, purge theo độ dài nhãn/holding horizon và tránh ranh giới lệnh. Báo cáo cả thất bại và số lần đã thử.

Nguồn hướng dẫn quy trình: [Davey — S06](https://kjtradingsystems.com/). Nghiên cứu của [Bailey và cộng sự — S23](https://www.davidhbailey.com/dhbpapers/backtest-prob.pdf) giải thích rủi ro chọn chiến lược từ nhiều backtest. Không tuyên bố đã tính PBO/CSCV cho dự án; muốn tính cần lưu ma trận kết quả của toàn bộ biến thể.

Dữ liệu broker khác có thể giúp kiểm tra độ nhạy feed, nhưng không tạo thêm năm thị trường độc lập. Forward sau ngày khóa cấu trúc mới là nguồn dữ liệu mới theo thời gian. Mẫu của preset cũ không tự xác nhận cấu trúc mới; phải gắn version và đánh giá riêng.

## Bảng kết quả bắt buộc khi được triển khai

| Nhóm | Chỉ số |
|---|---|
| Cơ hội | Raw candidates, unique ideas, accepted, filled, rejected theo lý do |
| Tần suất | Theo symbol/tháng/phiên; tháng 0 lệnh; rolling 3/6/12 tháng |
| 1,5R | Room tại entry, xác suất first-hit 1,5R, R thắng trung bình/median sau phí |
| Kỳ vọng | Net R/trade, Net R/tháng, PF, payoff tiền và R0 tách riêng |
| Quản lý | MFE/MAE, capture, giveback, BE, time exit, stop sửa quá trễ/bị từ chối |
| Rủi ro | Equity DD, chuỗi lỗ, thời gian hồi phục, worst day và exposure gộp |
| Độ chắc chắn | Khoảng tin cậy phù hợp; bootstrap theo block thời gian; kết quả từng fold |
| Coverage | Ngày dữ liệu, warm-up, khoảng trống tick, số phiên thiếu và nguồn phí |

Mỗi dòng tổng phải đi kèm số mẫu, giai đoạn và mức chi phí. Không thay các số liệu thiếu bằng 0 để biến thiếu dữ liệu thành kết quả tốt.

## Thứ tự tiến hành để thảo luận

1. Chốt định nghĩa 1,5R, tần suất và drawdown với người dùng.
2. Khóa bản đặc tả cho một playbook/exit pilot, nguồn dữ liệu và phép so sánh.
3. Khi có yêu cầu triển khai: xây detector và logger có thể replay, kiểm tra tính đúng thời điểm trước khi nghiên cứu hiệu quả.
4. Chạy lịch sử đủ phạm vi; phân tích phần không đạt; chỉ mở rộng khi có một lý do cấu trúc rõ.
5. Thu forward đúng version và review theo thời gian lẫn số mẫu. Không coi 100 hay 200 lệnh là tự động đủ chứng minh một winrate cố định.

Hoàn thành tài liệu nghiên cứu không đồng nghĩa một chiến lược đã vượt các cổng này.
