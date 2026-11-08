# Nghiên cứu các cặp tiền

Phạm vi bổ sung theo yêu cầu ngày 25/10/2026. Universe đề nghị khảo sát: **EURUSD, GBPUSD, USDJPY, AUDUSD**. Đây là danh sách nghiên cứu, chưa phải các symbol đã có edge hoặc đã được kiểm tra trên broker hiện tại.

## Các nguồn có số liệu cụ thể

### F1 — FTMO: account chủ yếu EURUSD

FTMO công bố account mô phỏng 80.000 EUR có **45 lệnh, 53,33% thắng, average RRR 2,40, PF 2,75**, lợi nhuận **25.655,24 EUR**; trung bình **1,76 lệnh/ngày** trong giai đoạn báo cáo. Account có giao dịch thêm US100/ETH nên đây không phải thống kê tách riêng EURUSD. Lệnh ví dụ giữ 2 giờ 39 phút. Quy tắc entry và lịch sử thay đổi SL chưa đầy đủ. [S24 — nguồn gốc](https://ftmo.com/en/blog/under-two-trades-a-day-delivered-a-32-return-on-eurusd/)

**Hướng nghiên cứu:** entry có cấu trúc và giữ nhịp intraday có thể phù hợp mục tiêu payoff cao hơn. Không suy ra 45 ý tưởng độc lập hoặc R ban đầu từ số ticket và average RRR.

### F2 — Unger Academy: Euro FX futures breakout

Tác giả nêu hệ thống phát triển tháng 4/2021, breakout đỉnh/đáy ngày trước có lọc giờ/biến động và time exit sau **5 ngày**. Giai đoạn 2008–01/04/2021: khoảng **450 lệnh**, P&L **90.600 USD**, average trade khoảng **200 USD**, winrate khoảng **50%**, lãi/lỗ trung bình khoảng **1.400/960 USD**; drawdown xấu nhất hơn **15.000 USD**. [S25 — nguồn gốc](https://ungeracademy.com/blog/euro-fx-strategy-analysis-does-it-work-in-and-out-of-sample)

**Giới hạn:** các số này là backtest tác giả nêu, không phải báo cáo broker; nhiều bộ lọc chưa công khai. Khoảng ba lệnh/tháng và khả năng giữ nhiều ngày khiến nó không phải đáp án trực tiếp cho scalp tần suất cao. Dữ liệu là futures, không phải spot EURUSD.

### F3 — Unger Academy: mean reversion trên British Pound và Euro FX

Bài giới thiệu hai hệ thống đảo chiều dùng Bollinger Bands trên currency futures; hệ thống Pound có đóng cuối phiên và có SL/TP. Tham số BB, trigger hoàn chỉnh và thống kê đủ để tái tạo chưa được nêu rõ trong phần văn bản. Không gán BB(20,2) cho hai hệ thống này. [S26 — nguồn gốc](https://ungeracademy.com/blog/bollinger-bands-on-british-pound-and-eurofx-structure-real-performance)

**Hướng nghiên cứu:** kiểm tra nhánh quay về trong range tách biệt với breakout; không mặc định mọi cặp tiền mean revert ở mọi phiên.

### F4 — Pepijn, trader có tên trong phỏng vấn FTMO

FTMO mô tả top-down D1/W1, entry ở M1/M5/M15, price action với Fibonacci/liquidity, chờ khoảng **15 phút sau mở phiên London**. Đây là mô tả phương pháp của trader; chưa có full journal dài hạn, winrate hoặc R ban đầu để tái lập thành hệ thống. [S27 — bài/phỏng vấn FTMO](https://ftmo.com/en/blog/top-ftmo-trader-pepijn-better-be-safe-than-sorry/)

**Hướng nghiên cứu:** chuẩn bị bối cảnh trước, timing sau và phân biệt entry với management. Không lấy lợi nhuận được nhắc trong phỏng vấn làm bằng chứng một tổ hợp Fibonacci tự động.

## Những cấu trúc nên đối chiếu

| Cặp tiền | Nhánh nên khảo sát đầu tiên | Bằng chứng riêng hiện có | Phần cần đo trên feed đích |
|---|---|---|---|
| EURUSD | Breakout/retest; pullback; failure tại biên phiên | Case FTMO F1; hệ thống Euro FX F2/F3 chỉ tham khảo | Hiệu quả từng phiên, fill limit, spread/risk, room 1,5R |
| GBPUSD | Pullback/breakout; failure khi bị từ chối biên | F3 là Pound futures, chưa phải GBPUSD CFD | Slippage, biến động tin GBP/USD, phiên London/NY |
| AUDUSD | Biên phiên và pullback theo bối cảnh | Chưa có bộ case đủ số liệu được chốt trong hồ sơ này | Kiểm định riêng; không suy ra từ EURUSD |
| USDJPY | Breakout/pullback và failure có xác nhận | Chưa có bộ case đủ số liệu được chốt trong hồ sơ này | Đơn vị JPY, spread, sự kiện Nhật/Mỹ và khác biệt các phiên |

Các nhánh trên là đề xuất của dự án, không phải khuyến nghị vào lệnh. Không tự nhận đã có nghiên cứu thành tích riêng cho AUDUSD/USDJPY chỉ vì quy tắc tổng quát áp dụng được về mặt toán học.

## Ràng buộc khi mở rộng indicator

- Giao dịch OTC không có một tiếng chuông “London open” duy nhất như phiên cash của chỉ số Mỹ. Phải khai báo cách chia phiên và múi giờ/DST.
- EURUSD và GBPUSD có USD ở vế sau; USDJPY có USD ở vế trước. Nguồn futures JPY có quy ước báo giá khác spot USDJPY; phải kiểm tra chiều mapping trước khi dùng làm dữ liệu phụ.
- Không chuyển bộ SL 2–20 giá của vàng sang cặp tiền. Rủi ro phải tính từ cấu trúc, tick size, tick value, tiền tài khoản và quy tắc broker.
- Khi có nhiều cặp, phải quản lý rủi ro theo exposure tiền tệ. Một đợt bán USD có thể tạo nhiều tín hiệu liên quan; không coi đó là nhiều thí nghiệm độc lập.
- Không mặc định quan hệ tương quan luôn có cùng dấu hoặc cùng độ lớn. Cần cửa sổ dữ liệu đồng bộ và scenario stress.

Nguồn đơn vị symbol: [S33 — MetaQuotes](https://www.mql5.com/en/docs/constants/environment_state/marketinfoconstants). Phần mapping/portfolio ở đây là yêu cầu thiết kế của dự án, chưa được triển khai.

## Kết luận nghiên cứu cho nhóm tiền tệ

EURUSD có case account chứa số liệu đáng đọc nhất trong các nguồn đã chốt. Hệ thống có thông số chi tiết hơn lại có thời gian giữ nhiều ngày; hai loại bằng chứng không thể ghép thành một tuyên bố “scalp 1,5R đã được chứng minh”. Cần kiểm định phương pháp trên từng cặp và thống nhất tần suất mong muốn trước khi chọn thiết kế cuối.
