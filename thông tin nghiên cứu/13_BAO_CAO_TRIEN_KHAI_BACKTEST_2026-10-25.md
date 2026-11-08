# Triển khai pilot cấu trúc và backtest vàng 5 năm — 25/10/2026

**Kết luận: pilot P2 p2_structure_0.1 chưa đạt yêu cầu sử dụng.** Đã code nhánh lab, biên dịch và đối chiếu thực thi MQL5/Python; cả E0 và E1 đều âm ở ba mức spread. Giữ artifact để nghiên cứu, không nâng thành bản dùng chính, không triển khai forward từ kết quả này.

## 1. Phạm vi và phiên bản

Mục tiêu triển khai đang mở: “triển khai theo kế hoạch xong thì back test 5 năm”. Giai đoạn trước đã hoàn tất yêu cầu chỉ lập kế hoạch. Lượt này triển khai pilot vàng P2 theo tài liệu 10–12; P1/P3, forex và chỉ số còn phụ thuộc kết quả pilot.

Bản lab riêng: `duc_tri_scalp_structure_lab.mq5/.ex5`, spec `p2_structure_0.1`. Bộ thông số tại `SPEC_LOCK.json` được ghi trước kết quả đầu tiên. Không chạy tìm kiếm setting hoặc chọn lại giờ đẹp sau khi xem kết quả.

Định nghĩa pilot: M5, pivot 2 trái/2 phải; ATR Wilder 14; xác nhận HH/HL hoặc LL/LH; pullback tối đa 12 bar; anchor bị phá thì mất hiệu lực; trigger đóng vượt high/low bar trước. SL ngoài anchor +0,25 ATR, làm tròn tick ra ngoài. Cản gần nhất đã biết từ swing M5/H1 và D1 hoàn tất; cần room ít nhất 1,5R theo giá fill. Không có bộ lọc giờ hoặc auto BE.

E0 có target danh nghĩa 1,5R, làm tròn tick theo hướng đích và kiểm tra lại cản. E1 không có TP cố định: chỉ siết SL theo pivot sau entry đã xác nhận và tiếp diễn vượt swing trước. R0 là khoảng cách entry–SL ban đầu, luôn bất biến. Giữ tối đa 6 giờ đồng hồ; thoát tại quote tiếp theo nếu thị trường đóng. Mỗi policy một idea tại một thời điểm.

## 2. Dữ liệu và mô hình khớp

Cửa sổ đánh giá chính: **25/10/2021 00:00 UTC đến trước 25/10/2026 00:00 UTC**; warm-up từ 25/09/2021. Dữ liệu có quote từ 27/09/2021 đến hết phiên 23/10/2026; cuối cửa sổ là cuối tuần.

| Dữ liệu broker trả về, gồm warm-up | Số nến |
|---|---:|
| M1 | 1.786.617 |
| M5 | 357.782 |
| H1 | 29.891 |
| D1 | 1.311 |

M1 ghép lại khớp toàn bộ open/high/low/close của 357.782 nến M5. Có 1.384 nhóm M5 với dưới 5 nến M1; chưa phân biệt chắc chắn phút không có quote và dữ liệu thiếu. Ở spread 0,2, có 35 lệnh E0 và 33 lệnh E1 đi qua khoảng thời gian thiếu phút quan sát. Kết quả phụ thuộc lịch sử broker và quy tắc gap được mô tả.

Giả định OHLC là Bid; Ask tổng hợp = Bid + spread 0,2 / 0,5 / 1,0 giá. BUY vào Ask, thoát Bid; SELL vào Bid, thoát Ask. Kiểm tra cả phút entry. Chạm SL và TP cùng phút dùng thứ tự bất lợi. Stop cũ được xét trước stop mới; gap thoát theo open khả dụng có thể lỗ hơn −1R. Không kẹp lỗ gap về −1R.

Đây là **M1 OHLC replay, không phải tick Bid/Ask lịch sử**. Chưa đo commission và slippage đầy đủ; commission thêm đang giả định 0 có nhãn chưa xác minh. Một số lần chạy có 1 lệnh chưa phân giải ở cuối dữ liệu, được đếm riêng và không chuyển thành BE. Drawdown dưới đây là drawdown của R đã đóng, chưa phải equity drawdown trong ngày của tài khoản quỹ.

## 3. Kết quả P2 — chuỗi lệnh thực theo từng policy

Winrate là tỷ lệ lệnh kết thúc dương, bao gồm thoát hết hạn có lãi; không phải tỷ lệ tất cả lệnh đạt TP 1,5R. Tần suất tính trên đúng 60 tháng, không đếm candidate bị loại thành lệnh.

| Spread, đơn vị giá | Policy | Lệnh đóng | Lệnh/tháng | Winrate | PF | Tổng R | DD đóng |
|---:|---|---:|---:|---:|---:|---:|---:|
| 0.2 | E0: TP 1,5R | 416 | 6.93 | 35.8% | 0.66 | -101.50R | 103.88R |
| 0.2 | E1: trailing cấu trúc | 413 | 6.88 | 25.4% | 0.67 | -98.12R | 100.57R |
| 0.5 | E0: TP 1,5R | 382 | 6.37 | 31.4% | 0.62 | -95.94R | 97.73R |
| 0.5 | E1: trailing cấu trúc | 381 | 6.35 | 23.6% | 0.60 | -99.01R | 99.01R |
| 1.0 | E0: TP 1,5R | 332 | 5.53 | 25.3% | 0.42 | -140.22R | 143.68R |
| 1.0 | E1: trailing cấu trúc | 333 | 5.55 | 18.0% | 0.36 | -150.65R | 150.65R |

Ở spread 0,2: E0 có 121/416 lệnh thực nhận ít nhất 1,5R; E1 có 36/413. Lãi trung bình của lệnh thắng E1 là 1.89R, nhưng winrate 25.4% khiến expectancy vẫn -0.238R/lệnh. Có lệnh lớn hơn 1,5R chưa đủ tạo hệ thống tốt.

### Theo năm ở spread 0,2

| Năm | E0 lệnh | E0 R | E0 PF | E1 lệnh | E1 R | E1 PF |
|---|---:|---:|---:|---:|---:|---:|
| 2021 | 16 | +0.38R | 1.04 | 16 | -6.04R | 0.36 |
| 2022 | 87 | -20.76R | 0.65 | 86 | -35.07R | 0.43 |
| 2023 | 98 | -26.09R | 0.58 | 97 | -20.81R | 0.65 |
| 2024 | 82 | +9.70R | 1.24 | 80 | +26.42R | 1.68 |
| 2025 | 78 | -58.64R | 0.36 | 78 | -59.55R | 0.33 |
| 2026 | 55 | -6.10R | 0.83 | 56 | -3.08R | 0.92 |

2021 và 2026 là phần năm trong cửa sổ, không phải năm trọn. Năm 2024 dương không bù được sự suy yếu các năm khác, đặc biệt 2025. Có báo cáo cửa sổ 12 tháng, BUY/SELL và các block tiếp bước 2023–2026, purge 6 giờ. Vì spec cố định, không có bước fit/chọn tham số trong các block; đây là đánh giá hồi cứu theo thời gian, không phải OOS nguyên vẹn chưa từng được nhìn.

Đối chiếu cùng cohort 416 entry E0: E1 đạt -99.25R so với E0 -101.50R, chênh +2.25R. Cohort này cho E1 giữ độc lập và có thể chồng lệnh, nên chỉ chẩn đoán exit; số liệu triển khai một idea dùng bảng chính. Trailing chưa tạo cải thiện đủ ý nghĩa để cứu chất lượng entry.

## 4. Audit baseline v3.12 và khả năng đi 1,5R

Tái lập mẫu legacy 156 lệnh: 82,05% thắng, PF 2,65, +39,41R theo quy ước replay M1 cũ. Sửa riêng vòng lặp bỏ qua phút entry trên đúng cohort ấy làm đổi **0 lệnh**. Lỗi có tồn tại trong code nhưng chưa làm đổi kết quả mẫu đã khóa này; không quy mọi khác biệt hiệu suất cho lỗi đó.

Sau khi dùng Bid/Ask tổng hợp, rounding tick, gap fill và chọn chuỗi theo exit M1 thực, các đối chứng với **entry baseline cũ** cho kết quả:

| TP đối chứng | Lệnh đóng | Lệnh/tháng | Winrate dương | PF | Tổng R | DD đóng |
|---:|---:|---:|---:|---:|---:|---:|
| 0.5R | 171 | 2.85 | 77.8% | 2.06 | +33.73R | 3.18R |
| 1R | 139 | 2.32 | 64.7% | 2.11 | +42.05R | 4.65R |
| 1.5R | 130 | 2.17 | 57.7% | 1.94 | +40.47R | 4.79R |
| 2R | 126 | 2.10 | 54.0% | 1.94 | +42.87R | 5.93R |

Đây là chẩn đoán E0, không phải bản indicator mới đã được chứng minh. Đối chứng 1,5R có 75 lệnh dương/130 nhưng chỉ **47/130 lệnh thực nhận ≥1,5R**; lãi trung bình một lệnh thắng khoảng 1,11R do có thoát hết hạn. Không được mô tả 57,7% là tỷ lệ đạt đủ 1,5R.

Khi cố định 171 entry của đối chứng 0,5R rồi theo dõi tiếp đến SL/2R/hết hạn, số entry chạm 1R / 1,5R / 2R theo mô hình bất lợi là **82 / 58 / 44**. Không có lệnh chưa phân giải ở diagnostic này. Chuỗi entry của các target riêng khác nhau vì thời gian giữ khác nhau; không đánh đồng hai phép so sánh.

Baseline trong audit giữ quy tắc clamp risk tối thiểu 2 giá của replay cũ chỉ để so sánh. P2 dùng stop cấu trúc thực, không áp clamp đó. Các khác biệt quy ước khớp khác cũng được ghi trong `baseline_audit.json`.

## 5. Kiểm chứng kỹ thuật và các sửa trong audit

- Python: **20/20** kiểm tra hành vi đạt, gồm entry minute, Ask SELL, gap, R0, không nới stop, causal prefix trên mẫu lịch sử, anchor mất hiệu lực, serial exit, tick grid và sai số số thực ở first-passage.
- MQL5: **14/14** fixture chạy thực trong terminal fixture riêng, không chỉ compile.
- Parity động: **14/14** nhóm đối chiếu đạt; 15,442 candidate, 32,649 đề xuất trailing, 2,257 lệnh đóng của 6 kịch bản và 990 lần dời stop khớp Python/MQL5. Timestamp, phía lệnh, trạng thái khớp chính xác; sai số số thực tối đa khoảng 5×10⁻¹¹.
- Wrapper và runner biên dịch **0 errors, 0 warnings**; có binary mới, log và SHA-256. MetaEditor trả mã tiến trình 1 trong môi trường này; kết luận dựa trên log, file mới và hash, không chỉ exit code.
- Cả **64 file source/include/script/settings/binary cũ** trong baseline được kiểm tra, không có file đổi hash. Source/EX5 v3.12 workspace và MT5 vẫn khớp nhau.

Các sửa trước khi chốt: loại stop nằm sai phía quote thoát; vô hiệu anchor đã bị phá; xét tick của target và room; không tính MFE sau TP; dùng tolerance cho first-passage khi R có sai số máy. Các lần chạy sơ bộ trước sửa không phải kết quả cuối. Không đổi bộ seed để tìm kết quả đẹp.

Thực tế harness/P2 được bắt đầu code trước khi audit baseline hoàn tất; chỉ chốt đánh giá sau khi G0/G1 và parity đã có bằng chứng. Parity chứng minh hai implementation thực hiện cùng quy tắc trên dữ liệu này, không chứng minh bản thân quy tắc có lợi thế.

## 6. Trạng thái triển khai và quyết định gate

| Gate | Trạng thái cuối lượt |
|---|---|
| G0 audit replay | Hoàn tất cho phạm vi mô hình M1 mô tả ở trên |
| G1 first-passage baseline | Hoàn tất; giữ riêng diagnostic và chuỗi serial |
| G2/G3 detector/plan/trailing | Đã triển khai pilot P2 |
| G4 parity động | Đạt trên fixture và lịch sử dùng chung |
| G5 backtest 5 năm/chi phí/ổn định | Đã chạy; **pilot không đạt hiệu quả kinh tế** |
| G6 artifact riêng | Đã build/package và copy bản review riêng; không gắn lab lên chart chính |
| G7 forward/monitor lab | **Chưa triển khai do G5 không đạt** |
| G8 P1/P3/forex/chỉ số/EA | Còn điều kiện; chưa code trong pilot này |

Package: `reports/scalp_structure_lab/20261025_pilot_v1/package`. Bản review nằm tại `C:/Users/ductr/AppData/Roaming/MetaQuotes/Terminal/D0E8209F77C8CF37AD8BF550E51FF075/MQL5/Indicators/DucTriLab/p2_structure_0_1`. Default `InpPaperEnabled=false`; không có API gửi lệnh. Nếu bật paper thủ công để phát triển, phiên hiện tại reset khi reload, chưa có state forward bền vững; không dùng làm monitor đánh giá forward chính thức.

Không thay nguồn/EX5 v3.12, không trộn cohort vào paper monitor 24/10, không tạo heartbeat mới. Chưa kiểm định giao diện lab trên chart và chưa đánh giá forward; không gọi copy artifact là release sử dụng.

Trong kiểm tra GUI, profile có bị chuyển tạm, sau đó đã chọn lại **Market Overview**, thấy các tab XAUUSD M30/Daily/H1 như ban đầu. MT5 tự tắt Algo Trading khi đổi profile; không thực hiện thao tác bật lại. Algo Trading đang tắt theo terminal_info.trade_allowed=false.

## 7. Hướng nghiên cứu tiếp theo, chưa triển khai

1. Giữ P2 này như một giả thuyết đã kiểm định không đạt, không mở grid EMA/giờ/ATR để che kết quả.
2. Dùng các case baseline đi được 1,5R để phân tích trước entry: chất lượng nhịp đẩy, vị trí pullback so với cấu trúc H1, liquidity sweep và cản thực. Tách đặc điểm đo được trước entry khỏi đặc điểm chỉ thấy sau khi thắng.
3. Viết spec cấu trúc mới: protected swing/impulse và pullback có invalidation rõ, trigger/retest có thời điểm biết được; chỉ nâng stop sau khi continuation thực sự được xác nhận. Đây là giả thuyết nghiên cứu, chưa phải cam kết hiệu quả.
4. Khóa mẫu kiểm định theo thời gian và chi phí trước khi thử. Dữ liệu 2021–2026 đã được xem, nên kết quả sau khi thiết kế lại trên cùng tập không thể gọi pristine OOS. Cần mẫu tương lai/nguồn độc lập cho xác nhận.
5. Chỉ mở rộng playbook hoặc asset khi có luận cứ và hồ sơ symbol riêng. Chưa chọn gói quỹ, nên chưa mô phỏng tỷ lệ pass và chưa xác lập mức risk tài khoản 100k.

**Mục tiêu một chỉ báo mạnh, lệnh khoảng 1,5R và phù hợp quỹ vẫn chưa đạt. Lượt code pilot và backtest đã cho một kết luận có thể kiểm tra: định nghĩa P2 hiện tại không nên được đưa vào sử dụng.**

## 8. Hồ sơ và cách chạy lại

Các script: `scripts/replay_scalp_structure_lab.py`, `scripts/audit_scalp_structure_lab.py`, `scripts/build_scalp_structure_lab.py`; wrapper và 3 Include `ScalpStructure*`; fixture tại `tests/test_scalp_structure_lab.py` và `tests/mql5/TestScalpStructureReplay.mq5`.

```powershell
python scripts/replay_scalp_structure_lab.py fetch
python scripts/replay_scalp_structure_lab.py run
python -m unittest discover -s tests -p test_scalp_structure_lab.py -v
python scripts/audit_scalp_structure_lab.py baseline
python scripts/audit_scalp_structure_lab.py diagnostics
python scripts/build_scalp_structure_lab.py
```

`--skip-csv` chỉ dùng khi input CSV được giữ nguyên và muốn replay lại nhanh. Parity cần chạy EX5 fixture mới trên bốn CSV đầu vào trong Common/Files/scalp_structure_lab_v1, sau đó `python scripts/audit_scalp_structure_lab.py parity`; không chỉ tái đọc output MQL cũ sau khi đổi lõi. Lần này có terminal fixture riêng, log thực thi và manifest binary để đối chiếu.

Cơ chế `/portable`, `/config` và script StartUp dựa trên [tài liệu MetaTrader 5 chính thức](https://www.metatrader5.com/en/terminal/help/start_advanced/start). Runtime fixture không có tài khoản được sao chép vào và tự đóng sau script; dữ liệu được đọc từ CSV dùng chung.

Bằng chứng: `SPEC_LOCK.json`, `data_manifest.json`, `data_audit.json`, `baseline_audit.json`, `backtest_summary.json`, `stability_diagnostics.json`, `dynamic_parity.json`, `build_manifest.json`, `review_install_manifest.json`, log Python/MetaEditor và CSV MQL trong thư mục run.
