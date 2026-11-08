# Mục tiêu 1,5R và cơ chế dời SL

Nội dung thiết kế của dự án, ngày 25/10/2026. Những con số minh họa không phải kết quả giao dịch hoặc thông số đã được chọn.

## Bốn ý nghĩa khác nhau của “1,5R”

| Thước đo | Định nghĩa | Có tự kéo theo thước đo khác không? |
|---|---|---|
| Target dự kiến 1,5R | Giá đích cách entry 1,5 lần khoảng stop ban đầu | Không chứng minh giá chạm đích |
| MFE từ 1,5R | Giá từng chạy thuận tương đương 1,5 lần rủi ro ban đầu | Không chứng minh đã chốt được 1,5R |
| Lệnh thắng thu trung bình 1,5R | Trung bình R ròng của các trade idea kết thúc dương | Không đồng nghĩa mọi lệnh thắng đều đạt 1,5R |
| Payoff ratio 1,5 | Lãi tiền trung bình chia độ lớn lỗ tiền trung bình | Không đồng nghĩa 1,5R theo SL ban đầu |

Mục tiêu làm việc cần báo cáo cả **room dự kiến**, **hit-rate 1,5R**, **R thực thu của lệnh thắng** và **R trung bình mọi lệnh**. Không đánh tráo một số tốt thay cho cả bốn.

## R được khóa lúc bắt đầu trade idea

- `D0 = |entry_fill − initial_stop|` là rủi ro theo đơn vị giá.
- `R0_cash` là mức lỗ tiền tương ứng D0 và khối lượng ban đầu theo thông số hợp đồng.
- `R_net = (tổng P&L đã thực hiện − phí chưa tính trong P&L) / R0_cash`.
- R0 không thay đổi khi SL được nâng, lot được chốt bớt hoặc chart co giãn.
- Dùng Bid/Ask đúng phía; không trừ spread lần nữa nếu đã nằm trong giá fill.
- Mọi ticket của một ý tưởng được gộp. Mở bốn ticket không biến một ý tưởng thành bốn cơ hội độc lập.

Nếu sau này cho thêm vị thế, phải định nghĩa ngân sách rủi ro bổ sung trước khi thêm. Báo cáo riêng các lần add-on và tổng rủi ro; không đổi mẫu số về sau để làm đẹp R.

## Điều kiện trước khi vào: room thực sự đủ

Xác định cản/đích gần nhất có ý nghĩa **từ thông tin đã biết lúc đó**. Khoảng entry tới đích, trừ đệm thoát/chi phí cần thiết, phải tạo được room nghiên cứu từ 1,5R. Nếu đích trước mặt chỉ cách 0,8R, không giải quyết bằng cách vẽ một đường 1,5R xuyên cản.

Có ba khả năng phải đo: đợi entry tốt hơn có thể không được fill; stop ngoài cấu trúc có thể làm R rộng; hoặc setup phải bị bỏ. Bộ lọc room thường làm mất một phần tín hiệu, nên việc tăng tần suất phải đến từ loại cơ hội mới có chất lượng, không từ việc đếm lại cùng một sóng.

## Ba exit để đưa ra so sánh sau này

### E0 — Đối chứng: target cố định 1,5R

Giữ nguyên initial stop, đặt đích 1,5R. Chỉ là nhánh đối chứng để biết trailing có thực sự giúp hay không. Không suy ra hiệu quả bằng cách đổi InpTp1RR hiện tại.

### E1 — Dời theo cấu trúc pullback đã xác nhận

BUY: sau khi một pullback hoàn thành và giá tiếp tục tạo đỉnh mới, xem xét nâng SL dưới đáy pullback cộng đệm. SELL làm đối xứng. Ý tưởng quản lý theo pullback có nguồn phương pháp ở [Brooks — S13](https://www.brookstradingcourse.com/futures-market/trade-trend-channels/); cách cơ giới hóa dưới đây là đề xuất của dự án.

- Pivot chỉ có hiệu lực tại thời điểm được xác nhận, không phải hồi tố ở nến tạo đáy/đỉnh.
- BUY dùng `SL_mới = max(SL_cũ, mức_stop_cấu_trúc_hợp_lệ)`; SELL dùng phép min.
- Nếu chưa có cấu trúc mới thì giữ stop trước đó; không tự kéo về entry vì vừa chạm một mức R.
- Đệm phải phản ánh spread, tick size và biến động, nhưng công thức/độ lớn chưa chốt.
- Kiểm tra stop nằm đúng phía giá hiện hành và giới hạn broker.
- Mức stop mới chỉ có hiệu lực sau lúc tính xong và độ trễ sửa lệnh giả định; không áp ngược cho phần giá đã chạy trong cùng bar.

### E2 — Dời theo biến động, có khóa một chiều

Dùng khoảng cách ATR từ cực trị thuận lợi để tạo stop ứng viên. [Chandelier theo StockCharts — S15](https://chartschool.stockcharts.com/table-of-contents/technical-indicators-and-overlays/technical-overlays/chandelier-exit) là công thức tham khảo. Đường Chandelier thô có thể lùi khi ATR/rolling extreme đổi; stop giao dịch đề nghị phải khóa một chiều như E1.

Phải phân biệt cực trị trong N bar với cực trị kể từ entry; đó là hai định nghĩa khác nhau. Chưa chọn N, hệ số ATR hoặc mức kích hoạt. Không gọi một công thức lai mới là quy tắc gốc của Le Beau.

## Breakeven và chốt từng phần

Breakeven là một policy riêng để so sánh, không phải mặc định “an toàn hơn”. Kéo SL quá sớm có thể làm mất các lệnh tốt từng hồi qua entry. Stop ở entry vẫn có thể lỗ ròng do phí hoặc gap. Trailing tích hợp của MT5 chạy tại terminal; mức SL đã đặt mới là mức tồn tại khi terminal ngừng chạy. [S21 — cơ chế nền tảng](https://www.metatrader5.com/en/terminal/help/trading/general_concept)

Ví dụ trước phí, cùng tổng khối lượng ban đầu:

| Cách chốt | R thực thu nếu các phần đều đạt đích |
|---|---:|
| 50% ở 0,5R và 50% ở 2R | 1,25R |
| 50% ở 1R và 50% ở 2R | 1,50R |
| 70% ở 0,5R và 30% ở 2R | 0,95R |

Do đó “có một phần chạm 2R” không đủ chứng minh cả lệnh thu 1,5R. Không đưa chốt từng phần vào vòng thử đầu nếu chưa chứng minh lợi ích so với giữ toàn bộ vị thế.

## Toán kỳ vọng và tần suất

Minh họa: mọi lệnh thắng +1,5R, mọi lệnh thua −1R, không hòa vốn, chưa tính phí:

| Winrate | Kỳ vọng R/lệnh |
|---:|---:|
| 40% | 0,00R |
| 50% | +0,25R |
| 60% | +0,50R |
| 70% | +0,75R |
| 80% | +1,00R |

Đây là phép tính, không phải dự báo winrate. Khi có trailing, mức thắng/thua thay đổi, phải tính trực tiếp từ phân phối R thực tế.

Tần suất chưa được người dùng chốt bằng số. Có thể trình bày kịch bản 10/20/40 ý tưởng mỗi tháng để thảo luận, nhưng không ép indicator phát quota. Cần báo cáo cả tháng không có lệnh và các cửa sổ 3/6/12 tháng.

Với mức lịch sử khoảng 2,6 lệnh/tháng, 100 tín hiệu forward cần khoảng **38 tháng**, 200 cần khoảng **77 tháng** nếu tần suất giữ nguyên. Vì vậy chờ 100–200 lệnh của preset cũ không thể là toàn bộ kế hoạch cải tiến; cần nghiên cứu cấu trúc cơ hội ngay, đồng thời phân biệt mẫu lịch sử với mẫu forward.

## Chỉ số phải có để đánh giá trailing

MFE/MAE theo R0; xác suất chạm 1,0/1,5/2,0R trước initial SL; phần MFE đã giữ lại; lãi trả lại từ đỉnh; median/mean R của lệnh thắng; loss/BE/win riêng; R ròng/tháng; max drawdown theo equity; chuỗi lỗ; thời gian giữ và độ nhạy spread/slippage. Không giữ yêu cầu 80% như cách duy nhất để chọn mô hình, cũng không tự cho rằng người dùng đã bỏ mục tiêu winrate cao.
