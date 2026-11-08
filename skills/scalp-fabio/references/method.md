# Phương pháp và giới hạn diễn giải

## Nguồn và quy tắc máy

Nguồn nghiên cứu có sẵn: `D:/trading thử lần cuối cuối/reports/20261108_video_strategy/BAO_CAO_NGHIEN_CUU_FABIO_FTMO_20261108.md`. Báo cáo ghi mốc video Fabio gốc, bản dịch STrade và phần chưa xác minh. Các đề xuất feed trả phí trong báo cáo cũ đã được thay bằng phạm vi **MT5-only** của kế hoạch hiện tại. Không dùng khuyến nghị cũ để yêu cầu mua data hoặc mở FTMO.

| Nguyên tắc nguồn đã đối chiếu | Quy tắc triển khai của dự án | Dữ liệu/điểm khác nguồn và cách kiểm |
|---|---|---|
| State trước model; Fabio 05:24–08:53, 37:49–38:51 | Balance M5 gồm 24 bars, range tối đa 3,5 ATR; hai closes cuối nằm trong value area | Các số là lựa chọn máy. Kiểm warmup, OHLC, as-of và balance thực sự có trước breakout. |
| Profile impulse, LVN rồi chờ quay lại; 39:06–40:42 | Acceptance hai closes; khóa impulse ở pullback đầu đủ 0,5 ATR; chỉ touch xảy ra sau khi profile biết mới được tính | Profile dùng tick theo chart basis khi đủ coverage, hoặc tick-volume nến rải đều có nhãn approximation. Kiểm anchor_end khác known_at, không hồi tố vùng. |
| Hướng tới balance/POC đã xác định; 40:42–41:15 | F1 chọn POC của balance hoàn tất trước balance hiện tại trong tuổi tham chiếu hữu hạn; thiếu đích phía có lợi thì UNKNOWN | Thuật toán chọn reference là adaptation, không công thức được Fabio công bố. Đích được khóa trước entry, không dùng D1 fallback của legacy. |
| Failed breakout trở lại balance, chờ nhịp sau; 41:29–42:44 | F2: breakout range → reclaim value trong cửa sổ failure → profile reclaim → later pullback/trigger; đích POC balance đã khóa | Reclaim không đồng thời là later-pullback/trigger. Kiểm trình tự thời điểm và breakout tiếp diễn bác bỏ reclaim. |
| Đọc aggression cùng phản ứng; 1:04:13–1:06:36 | `price_response` là bản thích nghi chính; CVD và bar-delta là các biến thể bổ sung trên cùng cơ hội | Quote proxy không xác nhận giao dịch chủ động. Gate aggression tại mức giá vẫn thiếu khi không có executed trades theo giá. |
| CVD hỗ trợ; 27:45–28:58 | CVD reset ngày UTC/gap, slope và divergence theo các pivot đã xác nhận | CVD tổng hợp không thay bubble; không nối qua reset/gap hoặc backdate pivot. |
| Thường đọc M5 và thực thi M1; 59:48–1:03:38 | Phiên bản này dùng M5 cho state và trigger | Chưa triển khai entry M1. Không áp ngưỡng 20–30 hợp đồng NQ thành lot CFD. |
| Ví dụ quản trị theo cấu trúc/điều kiện thị trường | SL cấu trúc có buffer, entry deadline/max-hold cố định trong spec; replay có chi phí/latency khai báo | Đây là quy tắc nghiên cứu của dự án; không lấy ví dụ video thành risk cá nhân hoặc mức stop đảm bảo. |

## Hai family

**F1:** cân bằng đã biết → chấp nhận rời value → impulse → pullback xác nhận giúp khóa profile → later touch LVN → nến phản ứng theo hướng tiếp diễn. Long/short đọc đối xứng. Cực trị mới sau khi khóa profile phải tạo trạng thái phù hợp theo engine; không âm thầm kéo vùng rồi giữ nhận định cũ. Quay vào balance, phá cấu trúc, hết hạn hoặc thiếu dữ liệu phải hiện rõ.

**F2:** balance đã biết → breakout range không duy trì → close reclaim vào value → đợi nhịp test sau reclaim tại LVN profile phù hợp → trigger hướng POC balance. Nếu giá tiếp tục breakout vượt cực trị thất bại, luận điểm bị bác bỏ. POC đã phía sau giá hoặc thiếu room không được đổi thành mục tiêu khác để giữ lệnh sống.

Các tham số nền dùng để tái lập, chưa tối ưu: min history 120 M5; balance 24 bars/3,5 ATR, lookback 150; VA 70%; bin 0,125 ATR; acceptance hai closes; failure tối đa sáu bars; pullback 0,5 ATR; LVN ≤ 0,5 median bins dương, tối thiểu bốn bins hợp lệ; tolerance 0,25 ATR; response window ba bars; buffer SL 0,1 ATR; room ròng tối thiểu 1,5R.

Policy mới dùng reference POC trong tối đa **150 M5 trước start balance** hiện tại, episode tối đa **150 M5** kể từ exit đầu, hạn entry từ **close của trigger đầu + 600 giây**, max-hold nghiên cứu mặc định **1.800 giây**. Balance mới có đủ 24 bars settled nằm hoàn toàn sau breakout trước có thể mở episode mới trước TTL; không tái kích hoạt cùng cơ hội cũ bằng một trigger mới. Đối chiếu `SCALP_SPEC`, replay spec và plan với version/hash của artifact; mismatch phải được báo thay vì đổi nhãn. Hạn entry không reset khi quét lại. Replay muốn thử max-hold khác phải khai báo riêng trước đọc kết quả; không gọi đó là quy tắc nguồn.

Quote age trong phân tích nền là 120 giây; đây là ngưỡng máy hiện có, chưa chứng nhận độ nhanh đủ cho scalp. Replay có luật quote/latency riêng được ghim. Đo độ trễ prospective trước khi kết luận tính thực thi.

## State, identity và kế hoạch

- `setup_stage` mô tả cấu trúc đang tới đâu; `execution_readiness` mô tả phần thực thi đã đủ hay còn thiếu, ví dụ COST_UNKNOWN hoặc QUOTE_STALE. Đọc cả hai cùng `decision`/`reason`, không suy readiness từ trigger.
- `analysis_id` là lần phân tích; `opportunity_id` là cơ hội; `revision_id` và `trigger_id` phân biệt diễn biến/trigger. Giữ source/spec và timestamps của artifact, không dùng chỉ số bar hoặc snapshot mới để tự tạo ID.
- `profile_lifecycle.mode=FROZEN_PREVIOUS_ANALYSIS_CHAIN`: nối artifact trước giữ balance, bins profile, đích đã chọn (kể cả TARGET_UNKNOWN) và trigger/thời hạn trong cùng episode. Source/spec và OHLC/volume/time của phần lịch sử dùng lại phải khớp; mismatch thì báo lỗi. Chuỗi này được ghim bằng hash artifact trước. `RECONSTRUCTED_FROM_PINNED_INPUTS` là lần đầu/đọc độc lập; khi coverage/basis khác, so `profile_revision_id`, giữ observations cũ và không thay plan quyết định bằng plan dựng lại sau khi đã thấy outcome.
- `known_at` là thời điểm thông tin khả dụng; mốc đỉnh/đáy có thể sớm hơn. Một touch trước known_at không phải entry có thể thực hiện. Không suy thứ tự trong một nến nếu tick không chứng minh được.
- Chỉ đọc `research_plan` thực sự được engine xuất khi đủ cấu trúc và đúng schema mà adapter replay của cùng version nhận. Vùng chờ thiếu target không có quyền tự sinh TP. Phân tích cũ có thể thiếu các trường mới; đọc đúng spec đã tạo nó, không đổi tên field hoặc sửa hash để ép replay.
- Giữ mọi WAIT/SKIP/EXPIRED/no-fill/missing và phiên không có cơ hội. Không cộng F1/F2, các biến thể flow hoặc các mã có exposure liên quan thành các giao dịch độc lập.

## Flow và profile

| Basis được artifact xác nhận | Được diễn giải | Tránh suy ra |
|---|---|---|
| Quote-direction CVD | Tick cùng/ngược hướng giá; mức tham gia của feed; bất đồng cần quan sát thêm | Dòng tiền ròng, khối lượng mua/bán thực, absorption thực, danh tính tổ chức |
| Executed trades hợp lệ của broker | Delta theo phương pháp side/volume đã kiểm, trong phạm vi feed đó | Tape toàn thị trường hoặc dữ liệu độc lập từ nơi khác |
| Profile tick tại giá, đủ coverage | POC/VA/LVN theo basis và cửa sổ đã khóa | Khối lượng thực nếu trọng số chỉ là tick activity |
| Profile từ tick_volume nến | Phân phối xấp xỉ phục vụ vị trí nghiên cứu | Footprint, lệnh limit tồn tại hay profile executed chính xác |

Các chỉ số cùng tính từ giá không phải nhiều bằng chứng độc lập. Price response được giữ khi thiếu/trái proxy CVD; đây là cách tránh thêm bộ lọc chưa kiểm định. Điều đó không bảo đảm cùng tần suất hay hiệu quả với video.

## Replay và mức nghiệm thu

Replay chỉ đánh giá plan đã khóa từ artifact trên đường tick được ghim. Entry dùng Ask cho long/Bid cho short; exit và mức stop/target dùng phía đối diện. Spread đã nằm trong Bid/Ask, không trừ thêm lần hai. Short level từ chart Bid chuyển sang phía Ask bằng giả định được replay công bố; không gọi đó là Ask high đã quan sát nếu không có bằng chứng.

Policy scalp chỉ cho readiness thực thi khi chart basis là BID. LAST/UNKNOWN vẫn đọc được cấu trúc nhưng giữ DATA_MISSING và không sinh plan thực thi. Chi phí khai báo dùng cùng công thức room ở phân tích và replay: giá entry đã cộng trượt giá bất lợi, SL/target làm tròn tick; room trừ commission round trip và thêm dự phòng một market leg. Đây là kịch bản ASSUMED.

Thiếu tick entry → UNRESOLVED; thiếu đường exit → CENSORED/UNRESOLVED theo output, không điền hòa vốn. Stop gap có thể lỗ quá 1R. Commission/slippage giả định phải mang ASSUMED; phí thật chưa biết giữ UNKNOWN, không công bố net đã xác minh từ giả định 0.

Nghiệm thu phần mềm/nghiên cứu không xác nhận edge, winrate hoặc đủ điều kiện giao dịch live. Pilot demo, kiểm định prospective và entry M1 là những công việc tiếp theo khi được yêu cầu; không tự chạy trong một lượt đọc báo cáo.
