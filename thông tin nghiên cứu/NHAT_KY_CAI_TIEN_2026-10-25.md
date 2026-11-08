# Nhật ký cải tiến ngày 25/10/2026

## Giai đoạn 3 — hoàn thiện kế hoạch bàn giao sau lượt bị ngắt

Ngày25/10/2026, tiếp tục yêu cầu ở chat “Phân tích indicator scalp vàng”: lập lại kế hoạch đủ rõ để model thấp hơn thực hiện code. Đã hoàn thành [bộ bàn giao](ban_giao_scalp_cu_2026-10-25/README.md), gồm audit source, đặc tả hành vi, backlog/nghiệm thu, nguồn và prompt giao việc. Bộ này thay chỉ dẫn P2 của tài liệu10–12; giữ nguyên báo cáo13 và lịch sử dưới đây.

Đã rà trực tiếp source v3.12 và replay, kiểm lại nguồn Grimes/Brooks/Davey/MQL5, thực hiện hai lượt rà độc lập về lõi và kiểm định. Các phát hiện quan trọng: detector Python chưa tương đương MQL, source có hai nơi kết thúc plan, entry đề xuất chưa phải fill, timeout6h chỉ có trong nghiên cứu, và dữ liệu2025–2026 đã được xem. Đã khóa thứ tự chốt baseline→so exit→room→retest, kèm35 fixture, cost scenarios và quy tắc R0/thời điểm stop.

Phạm vi lượt hoàn thiện: chỉ tài liệu trong thư mục nghiên cứu. Không sửa source/include/script/setting/EX5, không build, chạy backtest mới, đồng bộ MT5, thay monitor/automation hay đặt lệnh. Đối chiếu80 file với `BASELINE_TRUOC_LAP_KE_HOACH.json`; kết quả cuối lưu tại `ban_giao_scalp_cu_2026-10-25/KIEM_TRA_BAN_GIAO.json`. Kết quả đạt trong lượt này là **kế hoạch bàn giao hoàn chỉnh**, không phải indicator đã nâng cấp hoặc hiệu quả giao dịch mới.

---

Múi giờ: Asia/Saigon. Nhật ký ghi theo thứ tự công việc, không gán giờ chính xác cho các hoạt động không có log thời gian. **Phần đầu ghi giai đoạn chỉ lập kế hoạch. Giai đoạn 2 ở cuối nhật ký ghi phần triển khai pilot và backtest sau khi mục tiêu được chuyển sang triển khai.**

## Mục tiêu và chỉ dẫn của giai đoạn lập kế hoạch

- Hướng tới scalp có tần suất hữu ích, cơ hội khoảng 1,5R và SL dời theo giá.
- Cải tiến cấu trúc thay vì chỉ tối ưu bộ setting hiện tại.
- Nghiên cứu cả vàng, cặp tiền và chỉ số; ưu tiên chuẩn bị pilot vàng có đối chứng.
- Lần này lập kế hoạch cách code, cách triển khai và ghi nhật ký. Chưa code.
- Không sử dụng trading-foundation.

## Các công việc đã hoàn thành trong ngày

| Mã | Nội dung | Trạng thái và bằng chứng |
|---|---|---|
| J01 | Tổng hợp nguồn công khai cho ba nhóm thị trường | Đã có 33 nguồn được phân loại trong tài liệu 01 và sources.json; không đồng nghĩa 33 chiến lược đã được kiểm toán |
| J02 | Phân biệt R0, payoff, MFE và target; làm rõ trailing | Đã ghi tài liệu 04; chưa xác nhận cấu trúc mới đạt 1,5R |
| J03 | Phác thảo P1/P2/P3 và luồng indicator | Đã có tài liệu 03/05; đây là thiết kế, chưa là mã |
| J04 | Đọc source, Include, harness, test runner và build script hiện có | Đã xác định điểm tái dùng và các giới hạn, không chạy chúng |
| J05 | Chọn thứ tự đề nghị cho pilot | P2 trước, so E0/E1; P1/P3/ATR trail sau; ghi D01–D08 tại tài liệu 10 |
| J06 | Lập kế hoạch cải tiến | Đã viết tài liệu 10 với G0–G8, đầu ra, phụ thuộc và tiêu chí chuyển bước |
| J07 | Lập kế hoạch cách code | Đã viết tài liệu 11: file dự kiến, hợp đồng dữ liệu, thuật toán dự thảo, sự kiện và kiểm chứng tương lai |
| J08 | Lập kế hoạch triển khai | Đã viết tài liệu 12: staging/build, package lab, chart thử, shadow, quỹ và rollback |
| J09 | Bảo toàn phạm vi | Đã chụp baseline của 64 file source/include/binary/script/settings trong workspace trước khi viết kế hoạch; đối chiếu cuối trong file kiểm tra kế hoạch |

## Những phát hiện mới từ việc lập kế hoạch

1. `verify_causal_scalp_parity.py` phần lớn kiểm tra chuỗi/default trong source. Nhãn 22/22 cũ không chứng minh event parity giữa hai engine. Kế hoạch thêm so từng signal/stop/exit khi triển khai.
2. `fast_m1_trade` lấy entry ở bar đầu nhưng xét SL/TP từ `bars[1:]`. Cần xác minh xử lý phút entry bằng fixture; chưa chạy lại để lượng hóa ảnh hưởng.
3. Một số replay M1 đi sau bộ chọn non-overlap M5. Kế hoạch yêu cầu chọn lại chuỗi theo exit clock thực của từng phép thử.
4. Có các Include và test runner từ nhánh khác, nhưng scalp hiện tại không tự nhiên dùng những helper đó. Tái dùng cần kiểm tra dependency và đơn vị.
5. Script compile hiện có đồng bộ tên indicator chính; kế hoạch lab phải build/package riêng để tránh thay nhầm bản đang dùng.

Những mục này là quan sát code hoặc rủi ro cần kiểm chứng, không phải kết quả test mới hoặc kết luận đã sửa xong lỗi.

## Những việc chưa thực hiện ở cuối giai đoạn chỉ lập kế hoạch

Chưa tạo file code lab; chưa sửa `.mq5/.mqh/.py/.set`; chưa compile EX5; chưa chạy backtest/fixture; chưa copy MT5 hoặc gắn chart; chưa đổi monitor/automation; chưa đặt lệnh.

Các thống kê v3.12 trong báo cáo trước là kết quả lịch sử của phiên bản đó, không được ghi thành thành tích của cấu trúc mới hay công việc kiểm định hôm nay.

## Hạng mục tiếp theo khi bắt đầu triển khai

| Thứ tự | Hạng mục | Còn phụ thuộc |
|---:|---|---|
| 1 | Khóa định nghĩa thí nghiệm và audit replay G0 | Có yêu cầu bắt đầu code; ghi các lựa chọn chưa chốt |
| 2 | Chẩn đoán first passage 1,5R G1 | Replay đủ tin cậy và dữ liệu có coverage rõ |
| 3 | Detector P2 và kế hoạch E0/E1 | Spec timing/stop/room đã khóa |
| 4 | Parity động, lịch sử và chart lab | Lõi đúng hành vi và package riêng |
| 5 | Forward và mở rộng asset/playbook | Có kết luận từng bước; hồ sơ symbol/rủi ro tương ứng |

Tần suất, drawdown mục tiêu và loại tài khoản quỹ còn chưa chốt. Ghi chúng thành đầu vào phải xác định, không tự giả là người dùng đã đồng ý với một mức cụ thể.

## Tệp của nhật ký và kế hoạch hôm nay

- [Kế hoạch cải tiến](<D:/trading thử lần cuối cuối/thông tin nghiên cứu/10_KE_HOACH_CAI_TIEN_2026-10-25.md>)
- [Kế hoạch cách code](<D:/trading thử lần cuối cuối/thông tin nghiên cứu/11_KE_HOACH_CODE_2026-10-25.md>)
- [Kế hoạch triển khai](<D:/trading thử lần cuối cuối/thông tin nghiên cứu/12_KE_HOACH_TRIEN_KHAI_2026-10-25.md>)
- Bằng chứng bảo toàn: `baseline_lap_ke_hoach_20261025.json` và `kiem_tra_lap_ke_hoach_20261025.json`.

Kết luận nhật ký: hoàn thành phần lập kế hoạch được yêu cầu trong ngày; mục tiêu hiệu quả của indicator vẫn chưa được chứng minh bằng cấu trúc mới.


## Giai đoạn 2 — triển khai pilot và backtest theo mục tiêu mới

Mục tiêu trong ứng dụng: “triển khai theo kế hoạch xong thì back test 5 năm”. Ngày 25/10/2026, cùng ngày với kế hoạch; số liệu dưới đây thay cho trạng thái “chưa code” của giai đoạn đầu, không xóa lịch sử lập kế hoạch.

| Mã | Công việc | Bằng chứng / kết luận |
|---|---|---|
| J10 | Khóa seed, lấy dữ liệu và viết replay P2 | SPEC_LOCK, rates.npz, data_manifest; cửa sổ 25/10/2021–25/10/2026 |
| J11 | Audit khớp M1/M5 và entry minute | OHLC khớp 357.782 nhóm; sửa riêng phút entry đổi 0/156 lệnh legacy |
| J12 | Viết MQL5 types/setup/plan và wrapper lab riêng | 3 Include ScalpStructure + duc_tri_scalp_structure_lab; không có API đặt lệnh |
| J13 | Sửa các lỗi đúng quy tắc trong audit | Stop placeable, anchor invalidation, tick grid, MFE/first-passage; không tối ưu seed |
| J14 | Kiểm chứng | 20/20 Python, 14/14 MQL fixture, 14/14 nhóm parity động |
| J15 | Chạy 6 kịch bản 5 năm và ổn định | E0/E1 tại spread 0,2/0,5/1,0; cả 6 đều PF<1 |
| J16 | Chẩn đoán baseline 1/1,5/2R | 1,5R: 130 lệnh, 57,7% dương, PF 1,94; chỉ 47 lệnh thực nhận ≥1,5R |
| J17 | Build/package | Wrapper/runner 0 errors/0 warnings; 64 file cũ không đổi hash; source/EX5 v3.12 workspace/MT5 khớp |
| J18 | Kết luận gate | Không triển khai forward hoặc phát triển EA từ P2 hiện tại; bản copy review riêng default paper tắt |

Ở spread 0,2: P2 E0 416 lệnh, 35.8% thắng, PF 0.66, -101.50R; E1 413 lệnh, 25.4% thắng, PF 0.67, -98.12R. Tần suất gần 7 lệnh/tháng không bù được chất lượng entry. Kết quả âm được giữ lại, không quảng bá thành cải tiến thành công.

Lưu ý vận hành: trong kiểm tra GUI có chuyển profile tạm; đã chọn lại Market Overview và thấy tab XAUUSD M30/Daily/H1. MT5 tự tắt Algo Trading khi đổi profile, không bật lại từ lượt này. Algo Trading đang tắt theo terminal_info.trade_allowed=false. Không có thao tác gửi lệnh hoặc thay vị thế từ mã lab.

G7 shadow/forward và G8 mở rộng asset/playbook còn điều kiện vì G5 không đạt. Chưa có sample forward lab, chưa kiểm định giao diện lab, chưa có hồ sơ quỹ để tính pass. Phiên paper thủ công của wrapper chưa có phục hồi state khi reload; giữ default tắt.

[Báo cáo đầy đủ](<D:/trading thử lần cuối cuối/thông tin nghiên cứu/13_BAO_CAO_TRIEN_KHAI_BACKTEST_2026-10-25.md>) ghi bảng theo năm, cost stress, cohort, giới hạn dữ liệu và hướng nghiên cứu tiếp. Hoàn thành lượt triển khai pilot/backtest; chưa đạt mục tiêu hiệu quả của chỉ báo.
