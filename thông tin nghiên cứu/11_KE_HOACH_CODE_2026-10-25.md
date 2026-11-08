# Kế hoạch cách code — 25/10/2026

> **Tài liệu lịch sử, không còn là đặc tả code hiện hành.** Dùng [đặc tả cải tiến lõi scalp cũ](ban_giao_scalp_cu_2026-10-25/02_DAC_TA_HANH_VI.md) và [backlog/nghiệm thu mới](ban_giao_scalp_cu_2026-10-25/03_CONG_VIEC_VA_NGHIEM_THU.md). Nhánh P2 bên dưới là thí nghiệm đã chạy và không đạt; không thay detector scalp cũ bằng nhánh đó.

**Chỉ là thiết kế kỹ thuật. Các tên file/hàm mới dưới đây là dự kiến, chưa được tạo.** Ưu tiên một nhánh nhỏ có thể replay trước, tránh xây framework nhiều chiến lược ngay từ đầu.

## 1. Mã hiện tại cần biết trước khi triển khai

| Thành phần đang có | Cách dùng trong kế hoạch |
|---|---|
| [Indicator scalp v3.12](<D:/trading thử lần cuối cuối/duc_tri_can_ho_tro_scalp.mq5>) | Đối chứng hành vi; không thay mặc định trong bước lab |
| [GoldScalpCore.mqh](<D:/trading thử lần cuối cuối/Include/GoldScalpCore.mqh>) | Xem xét tái dùng round tick/signed movement/stop helpers sau kiểm tra định nghĩa |
| [GoldScalpContext.mqh](<D:/trading thử lần cuối cuối/Include/GoldScalpContext.mqh>) | Có context/session helpers; một số chỗ gắn M5/300 giây, không coi là đa khung/đa tài sản sẵn |
| [GoldScalpEngine.mqh](<D:/trading thử lần cuối cuối/Include/GoldScalpEngine.mqh>) | Có tích hợp và phụ thuộc biến global; không nhập nguyên khối vào lõi thuần |
| [Harness causal](<D:/trading thử lần cuối cuối/scripts/backtest_causal_scalp.py>) | Nguồn đối chiếu baseline và định nghĩa tín hiệu cũ; không mặc định được tái dùng cho P2 |
| [M1 replay helper](<D:/trading thử lần cuối cuối/scripts/evaluate_gold_scalp_m1_stability.py>) | Cần audit thứ tự xử lý, phút entry và chọn lệnh trước khi dùng làm bằng chứng |
| [Static parity](<D:/trading thử lần cuối cuối/scripts/verify_causal_scalp_parity.py>) | Chủ yếu dò text/default; không thay thế so hành vi MQL5/Python |

Indicator scalp đang dùng phần lớn logic inline và chỉ include Canvas; sự tồn tại của các Include khác không chứng minh chúng đã được gọi trong đường chạy scalp. Không sửa helper dùng chung trước khi biết những file nào phụ thuộc nó.

## 2. Hai vấn đề cần xác minh ở G0

1. `fast_m1_trade` lấy entry ở open của bar M1 đầu nhưng vòng kiểm tra SL/TP bắt đầu từ `bars[1:]`. Phải đối chiếu xem diễn biến ngay phút entry có đang bị bỏ qua. Chuẩn bị fixture chỉ chạm stop/target trong phút đầu để chứng minh hành vi trước khi sửa.
2. Các script hiện có chọn chuỗi non-overlap từ kết quả M5 rồi mới tính một số kết quả M1. Khi exit khác nhau, chuỗi entry tiếp theo có thể khác. Replay mới phải chọn tuần tự theo đúng clock/exit đang đánh giá.

Đây là các điểm quan sát khi đọc mã, chưa lượng hóa ảnh hưởng bằng test trong ngày lập kế hoạch. Số liệu cũ giữ nhãn lịch sử, không tự nâng thành chuẩn hành vi mới.

## 3. Tổ chức mã tối thiểu cho pilot

Các đường dẫn sau nằm dưới `D:/trading thử lần cuối cuối/` và **chỉ là dự kiến**:

| File dự kiến | Trách nhiệm |
|---|---|
| `Include/ScalpStructureTypes.mqh` | Context/level/candidate/plan/event; enums và đơn vị dữ liệu |
| `Include/ScalpStructureSetup.mqh` | Nhận diện swing xác nhận, cấu trúc xu hướng và P2 pullback |
| `Include/ScalpStructurePlan.mqh` | Initial stop, room, fill, R0, vòng đời và E0/E1 |
| `duc_tri_scalp_structure_lab.mq5` | Adapter MT5: lấy dữ liệu, gọi lõi, vẽ kế hoạch và xuất log |
| `scripts/replay_scalp_structure_lab.py` | Replay tuần tự tương ứng, fixture và xuất chỉ số cần thiết |
| `tests/mql5/TestScalpStructureReplay.mq5` | Runner fixture; không có gửi lệnh |

Không tạo plugin system, backend, cơ sở dữ liệu hoặc hàng chục lớp cho pilot. Các hàm nhận dữ liệu đầu vào rõ ràng, trả kết quả và lý do; tránh đọc chart, account hoặc quote ẩn trong hàm xác định setup.

Tái dùng helper hiện có chỉ khi hợp đồng đúng. Ví dụ `GSNetRR` đang có quy ước risk cộng friction; không được gọi kết quả đó là cùng R0 nếu đặc tả mới dùng initial price risk cố định rồi trừ phí ở P&L.

## 4. Hợp đồng dữ liệu

| Bản ghi | Những trường tối thiểu |
|---|---|
| Context | symbol, timeframe, bar open/close, as-of time, dữ liệu đủ/thiếu, trend state |
| Level | ID, loại, giá, observed-at, confirmed-at, hết hạn, nguồn phiên/swing |
| Candidate | ID, playbook=P2, hướng, trigger, mức dùng, stop anchor, thời hạn, lý do hủy |
| Plan | Candidate ID, planned entry, fill, initial SL, current SL, R0 price/cash, target/room, volume, trạng thái |
| Event | ID, thời điểm quyết định/hiệu lực, quote/bar nguồn, stop cũ/mới, lý do, phí và exit |

Định danh phải dựa trên symbol, playbook, hướng, mức tham chiếu và thời điểm xác nhận. Không dùng index mảng trượt làm danh tính lâu dài.

## 5. Đặc tả thuật toán P2 dự thảo

1. Dùng M5 đã đóng làm clock detector ban đầu. M15/H1 cung cấp bối cảnh và cản, không tự thành một chuỗi EMA gate bắt buộc cho mọi entry.
2. Nhận diện swing với số nến trái/phải được khai báo. Một pivot chỉ dùng được sau khi các nến xác nhận phía phải đã đóng. Seed kỹ thuật để thảo luận là 2 trái/2 phải; không phải thông số vàng đã được chứng minh hoặc khuyến nghị của chuyên gia.
3. Cấu trúc tăng đòi hỏi các swing hợp lệ thể hiện đỉnh/đáy đi lên; giảm đối xứng. Trạng thái lẫn lộn ghi UNKNOWN/RANGE thay vì ép hướng.
4. Theo dõi nhịp đẩy, sau đó pullback chưa phá mức bảo vệ xu hướng. Mỗi pullback có định danh và cửa sổ còn hiệu lực.
5. Trigger dự thảo: nến đóng phá micro-level theo hướng tiếp diễn, micro-level phải được xác lập trước nến phá. Lưu lúc trigger thực sự biết được; không ghi entry về nến tạo đáy.
6. Stop ngoài pullback anchor cộng đệm hợp lệ, round tick ra ngoài. Nếu stop không hợp lệ hoặc quá xa theo chính sách rủi ro thì loại, không kéo vào trong cấu trúc.
7. Kiểm tra cản có nguồn và khoảng đích nghiên cứu từ 1,5R, tính đúng chi phí. Mức dự phòng entry ±N×R không được coi là cản quan sát.
8. Entry pilot là quote khả dụng kế tiếp sau xác nhận; retest/limit và M1 timing để các biến thể sau. Không mặc định khớp đúng giá close của nến vừa xác nhận.

Hết hạn trigger, thời hạn giữ, cách chọn protected swing và buffer phải được ghi trong cấu hình thí nghiệm trước lần chạy đầu. Các seed nhằm làm quy tắc xác định được, không phải kết quả tối ưu setting.

## 6. Lõi management và thứ tự sự kiện

Các hàm dự kiến: đọc candidate, lập plan, xử lý fill, xử lý quote, đề xuất stop khi có bar đóng, ghi exit. Tên cụ thể có thể đổi; trách nhiệm và thứ tự không đổi.

Một chu kỳ phải:

1. Xử lý giá/thời gian mới đối với **stop đang có hiệu lực** và các pending order đã tồn tại.
2. Nếu trade đã kết thúc, khóa kết quả. Không sử dụng đoạn giá sau đó để cập nhật lãi/MFE cho trade ấy.
3. Sau khi bar đóng, cập nhật context/level và đề xuất stop mới.
4. Kiểm tra stop mới có siết đúng hướng, đúng tick, đúng phía quote; gắn thời điểm hiệu lực sau quyết định và độ trễ giả định.
5. Xét candidate mới theo chính sách vị thế và ngân sách đã khai báo.

**E0:** initial stop và target 1,5R để làm đối chứng. **E1:** BUY nâng stop dưới đáy pullback mới đã xác nhận sau khi tiếp diễn tạo đỉnh mới; SELL làm ngược lại. Khi chưa có cấu trúc mới thì giữ stop cũ. Không kèm chốt từng phần/BE mặc định trong vòng so sánh đầu.

Initial stop/R0 bất biến; stop BUY không giảm và stop SELL không tăng. Gap được fill theo quote khả dụng có thể bất lợi hơn mức stop, không clamp mọi lỗ về −1R.

Nếu chỉ có OHLC không biết thứ tự, ghi ambiguous hoặc chạy kịch bản bất lợi; không để high cuối bar kích hoạt trailing rồi dùng low trước đó như thể xảy ra sau khi stop được nâng.

## 7. Adapter và nhật ký

`OnInit` chuẩn bị handles và nhận hồ sơ symbol. `OnCalculate` xử lý bar đóng theo thứ tự tăng thời gian, còn management nhận quote phù hợp. Khi terminal nạp lại lịch sử, không phát cảnh báo cho toàn bộ tín hiệu cũ hoặc thay trạng thái đã hoàn tất bằng hiện tại.

Log dự kiến là JSONL có schema version, ID, decision-at/effective-at, dữ liệu đầu vào, lý do và các mức giá. Các nhãn chart chỉ lấy từ plan đã được lõi chấp nhận. Chưa cần thay toàn bộ dashboard cũ; pilot hiển thị đủ entry, SL ban đầu/hiện tại, room, trạng thái và nguyên nhân.

Không đưa API key, Telegram token hoặc thông tin định danh tài khoản vào fixture/report. Không tích hợp LLM/EA tự giao dịch trong pilot chỉ báo.

## 8. Kiểm chứng hành vi sẽ viết khi triển khai

| Fixture | Chứng minh điều gì? |
|---|---|
| Thay các nến tương lai, giữ prefix | Tín hiệu và stop quá khứ không đổi |
| Pivot còn thiếu bar xác nhận | Không có tín hiệu dựa trên pivot ấy |
| Chạm SL hoặc TP ngay phút entry | Không bỏ qua diễn biến entry bar |
| Giá đi ngược ngay sau fill | Không kích hoạt BE/trailing vì trị tuyệt đối |
| BUY/SELL đối xứng | Cùng quy tắc dấu, rounding và quote |
| ATR giãn/pivot thấp hơn | Stop đang khóa không bị nới |
| Cùng một tick chạm stop cũ, sau đó bật lại | Không hồi sinh trade hoặc áp stop mới ngược thời gian |
| Dữ liệu/quote thiếu | Không tính thành BE hoặc một trade hoàn chỉnh |
| Exit M1 sớm/muộn hơn M5 | Chuỗi entry tiếp theo chọn lại theo exit thật |
| Nhiều ticket hoặc nhiều playbook cùng nhịp | Không tăng số idea giả tạo |

MQL5 và Python dùng cùng fixture để so thứ tự sự kiện, level, entry, initial/current SL, exit và R. Time/state/ID phải khớp; tolerance giá theo tick size đã khai báo; không chỉ so một tổng winrate.

Đây là danh sách kiểm chứng tương lai. Hôm nay chỉ kiểm tra tài liệu và bảo toàn source; không thêm hoặc chạy các fixture trên.

## 9. Các đợt thay đổi sau khi được yêu cầu code

Tách thành: audit replay → chuẩn dữ liệu/fixtures → detector P2 → plan/room → trailing → parity động → adapter chart → build/package. Mỗi đợt có diff nhỏ, nhật ký, bằng chứng và điểm quay lại. Chỉ mở rộng ATR/P1/P3 khi có kết luận từ pilot, không làm sẵn cơ chế chưa dùng.
