# Nghiên cứu chỉ số

Universe nghiên cứu: **US100/NAS100, US500/SPX500, US30 và GER40/DAX**. Tên trên là tên thường gặp, không xác nhận symbol hoặc thông số hợp đồng của broker người dùng.

## I1 — FTMO: US500, payoff lớn nhưng sát giới hạn lỗ

FTMO báo cáo **662 lệnh/32 ngày hoạt động, 38,52% thắng, average RRR 2,06**, lợi nhuận mô phỏng **27.734,16 USD** trên account 100.000 USD, chủ yếu US500 và có GER40. Ngày xấu lỗ **4.942,60 USD**, chỉ còn **57,40 USD** so với giới hạn được bài nêu. Entry rule và raw log không được công bố đầy đủ. [S28 — nguồn gốc](https://ftmo.com/en/blog/how-a-us500-trader-secured-27734-despite-heavy-drawdowns/)

**Hướng nghiên cứu:** lãi/lỗ trung bình cao không đủ đánh giá khả năng sống sót tài khoản quỹ. Không sao chép cách tăng exposure hoặc phiên overnight chỉ từ case này.

## I2 — FTMO: winrate cao nhưng payoff thấp

Case chỉ số GER40/US100/US30/US500 có **77,08% thắng** trong **10 ngày**, lợi nhuận mô phỏng **27.175,28 USD** trên account 300.000 USD. Lãi trung bình **1.333,23 USD**, lỗ trung bình **2.014,01 USD**; chia hai số cho payoff khoảng **0,662**. Không dùng con số 77% để quảng bá mô hình đạt 1,5R. Số lệnh không lấy từ phần trăm để tự suy ngược. [S29 — nguồn gốc](https://ftmo.com/en/blog/massive-77-08-win-rate-prime-trader-earns-27175-through-precise-index-scalping/)

## I3 — Unger Academy: hai hệ thống ES M15

Nguồn công bố hệ thống một có **1.132 lệnh, 50,44% thắng, average trade 220,77 USD**; hệ thống pivot long-only có **380 lệnh, 35,53% thắng, average trade 271,91 USD**. Nhánh pivot đợi quét thấp hơn ngày trước và S1, đóng lấy lại S1 rồi vào nến kế tiếp. Stop/target gốc **900/2.400 USD mỗi ES**. Đó là backtest, chưa có đầy đủ raw log/giả định phí. [S30 — nguồn gốc](https://ungeracademy.com/blog/sp-500-trading-220-average-trade)

Không thể chuyển USD/contract ES thành số point SL của US500 CFD khi chưa biết contract spec. Hệ thống đầu có nhiều long hơn short; không ép đối xứng BUY/SELL chỉ vì code đối xứng thuận tiện.

## I4 — FTMO: ORB có mô tả entry/stop/target công khai

Bài ORB nêu các cửa sổ **5/15/30 phút**; ví dụ lấy 15 phút đầu phiên, đợi **M5 đóng ngoài biên**, vào qua FVG, stop ngoài nến giữa và target dự kiến **2:1**. Không có thống kê mẫu, PF hay winrate đi kèm. Đây là tài liệu phương pháp, không phải case trader có thành tích xác minh. [S31 — nguồn gốc](https://ftmo.com/en/blog/opening-range-breakout-strategy-how-to-master-the-1530-us-session/)

Giờ trong bài dùng cách viết CET/EST đơn giản hóa. Mốc phiên cash Mỹ phải tính theo **09:30 America/New_York**, ngày nghỉ/đóng sớm theo lịch; không đóng đinh 15:30 giờ châu Âu hoặc giờ Việt Nam quanh năm. [S32 — NYSE](https://www.nyse.com/markets/hours-calendars)

## Cấu trúc đề nghị để nghiên cứu

| Playbook | Cấu trúc | Khác với chỉ đổi setting |
|---|---|---|
| Opening-range breakout/retest | Khóa range sau khi phiên mở; xác nhận đi ra; entry có thời hạn; biết mức làm mất hiệu lực | Thêm một nguồn cơ hội theo phiên, không chờ vùng H1 |
| Pullback tiếp diễn sau mở cửa | Có nhịp đẩy và pullback hợp lệ; xác nhận tiếp diễn; trail theo cấu trúc | Tách nhận diện trend khỏi entry và trailing |
| Failure/reclaim tại biên ngày trước | Mức có trước, phá rồi lấy lại; đủ room tới đích | Thêm một cơ chế trạng thái thất bại, không phải tăng số lần quét |
| Pivot reclaim kiểu ES | Nhánh tham chiếu để thí nghiệm riêng | Không mặc định kéo chiến lược long-only ES sang mọi chỉ số |

Nhánh FVG là biến thể của ORB để kiểm định riêng. Không tự gọi vùng FVG là đã có “lệnh tổ chức” hoặc chắc chắn phải quay lại fill.

## Những khác biệt bắt buộc giữ trong thiết kế

- **Cash index, ETF, futures và CFD không phải cùng sản phẩm.** CFD US500/NAS100 có phiên, spread, swap và giá theo broker; ES/NQ có kỳ hạn, roll và volume giao dịch sàn.
- Với US100/US500/US30: cùng một nhịp risk-on/risk-off có thể tạo nhiều kế hoạch liên quan; cần đo exposure gộp và tương quan thay vì cộng số lệnh cơ học.
- Với GER40: dùng phiên cơ sở và ngày nghỉ châu Âu riêng; không sao chép mốc cash Mỹ. Chưa chốt lịch Xetra trong đợt này, nên để trường phiên cần xác minh.
- Chia cash-session/overnight trước khi so sánh kết quả; không chọn một giờ đẹp sau khi nhìn P&L.
- Không so sánh SL “20 point” giữa các chỉ số như cùng một số tiền. Đơn vị rủi ro phải dựa vào spec symbol. [S33 — MetaQuotes](https://www.mql5.com/en/docs/constants/environment_state/marketinfoconstants)

## Kết luận nghiên cứu cho nhóm chỉ số

ORB và pullback sau mở cửa đáng được khảo sát vì có mức tham chiếu, thời điểm xác lập và điểm mất hiệu lực rõ. Nguồn hiện có chưa chứng minh một phiên bản chung cho US100/US500/US30/GER40 vừa có winrate cao vừa thu trung bình 1,5R. Các case payoff cao và winrate cao ở trên thuộc các tài khoản khác nhau, không được ghép thành một bộ thành tích.
