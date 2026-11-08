# Ma trận vàng, cặp tiền và chỉ số

Đề xuất phạm vi đa tài sản cho nghiên cứu, không phải preset giao dịch. Ngày 25/10/2026.

| Nhóm | Universe khảo sát | Cấu trúc ưu tiên để đánh giá | Khác biệt cần giữ |
|---|---|---|---|
| Vàng | XAUUSD; GC/MGC chỉ là nguồn đối chiếu | Breakout tích lũy; pullback; failure tại mức phiên/ngày | CFD vs futures, nguồn volume, đệm biến động, chi phí |
| Cặp tiền | EURUSD, GBPUSD, USDJPY, AUDUSD | Breakout/retest biên phiên; pullback; reclaim tại cực trị | Đơn vị giá/JPY, tiền định giá, các phiên và exposure USD |
| Chỉ số Mỹ | US100, US500, US30 | ORB; pullback sau nhịp đẩy; failure tại biên ngày trước | Cash vs overnight, DST/ngày nghỉ Mỹ, rủi ro tương quan |
| Chỉ số Đức | GER40 | Breakout phiên cơ sở; pullback; failure | Lịch cơ sở châu Âu cần xác minh, không lấy giờ Mỹ |

Các source ID và bằng chứng tương ứng nằm ở tài liệu 01/02/07/08. Những nhánh trong ma trận là giả thuyết dự án; chưa có hiệu quả được kiểm định trên universe này.

## Phần cấu trúc có thể dùng chung

1. Đọc dữ liệu có thời điểm có sẵn, không repaint.
2. Quản lý mức tham chiếu và trạng thái context.
3. Router chọn playbook phù hợp, cơ chế định danh ý tưởng và hủy tín hiệu.
4. Kiểm tra điểm mất hiệu lực và room theo R0.
5. Vòng đời entry/fill/SL/trailing/exit, ghi log có thể replay.
6. Báo cáo R ròng và rủi ro danh mục theo cùng định nghĩa.

## Phần không thể dùng một hằng số cho mọi thị trường

| Trường dữ liệu | Vì sao phải có hồ sơ symbol |
|---|---|
| Tick size, tick value, contract size, tiền lãi/lỗ | Đổi biến động giá thành rủi ro tiền và round giá hợp lệ |
| Digits/point/pip, volume step | Đơn vị hiển thị không đồng nhất đơn vị giao dịch |
| Spread, commission, swap, slippage | Chi phí tương đối với stop khác nhau theo symbol/phiên |
| Phiên tham chiếu, múi giờ, ngày nghỉ, DST | Range chỉ hoàn tất đúng giờ khi lịch đúng |
| Quote type Bid/Last và nguồn volume | Cần biết OHLC biểu diễn giá nào; không giả delta từ tick count |
| Stops level/freeze level | Mức SL đẹp trên chart có thể không sửa được tại broker |
| Futures expiry/roll nếu dùng | Không ghép giá continuous và giá hợp đồng thật mà bỏ qua roll |
| Nhóm rủi ro liên quan | Tần suất tăng không đồng nghĩa có thêm nguồn lợi nhuận độc lập |

Nguồn kỹ thuật: [MqlRates — S19](https://www.mql5.com/en/docs/constants/structures/mqlrates), [MqlTick — S20](https://www.mql5.com/en/docs/constants/structures/mqltick), [Symbol Properties — S33](https://www.mql5.com/en/docs/constants/environment_state/marketinfoconstants). Đối chiếu thị trường vàng: [CME — S17](https://www.cmegroup.com/content/dam/cmegroup/market-regulation/files/gold-futures-and-options-fact-card.pdf), [LBMA — S18](https://www.lbma.org.uk/publications/the-otc-guide/introduction).

## Thứ tự triển khai giả định để thảo luận

Không bật đồng loạt mọi playbook trên mọi symbol. Sau khi được yêu cầu triển khai: bắt đầu bằng một cấu trúc có định nghĩa và nguồn rõ, đo riêng từng thị trường, rồi mới kết hợp các nhánh có giá trị tăng thêm. Bản indicator vàng hiện tại chỉ là đối chứng đã có lịch sử; số liệu của nó không đại diện cho cặp tiền hay chỉ số.

Đặc biệt, đổi nhãn file thành “multiasset” không chứng minh code đã chuẩn hóa đơn vị, xử lý phiên đúng hay có edge đa thị trường. Mọi claim đa tài sản cần kết quả và coverage theo từng symbol.
