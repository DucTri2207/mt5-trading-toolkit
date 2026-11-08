# Kế hoạch mở rộng tool train cho Muse: học chọn setup và tăng winrate

Ngày: 05/11/2026, giờ Việt Nam. Trạng thái: **PLAN_ONLY — chưa triển khai**.

## 1. Mục tiêu đã khôi phục từ chat trước

Nguồn ngữ cảnh: chat **“Điều tra USDJPY STALE trên MT5”**, gồm các lượt chốt mục tiêu phòng nghiên cứu Muse, gói model tải về, phần TP/SL hiện có, phần ENTER/SKIP còn thiếu và nghiệm thu Review9.

Sản phẩm cần xây là **bản mở rộng của bộ tool train mang lên Muse AI**. Muse dùng nó để nghiên cứu trên tick/nến, học điều kiện thuận lợi cho từng setup và cách xử lý cơ hội, rồi xuất một gói model/quy tắc có thể tải về nạp vào quant. Khi Codex hoặc Claude gọi quant với dữ liệu MT5 mới, quant dùng gói đã học để đánh giá cơ hội chính xác hơn.

“Dùng hằng ngày” là mục đích sử dụng gói kết quả sau nghiên cứu. Việc cần làm trong giai đoạn này là xây năng lực train, kiểm định và xuất gói cho Muse.

Những câu hỏi bộ train mới phải học trả lời:

1. Với bối cảnh đang có, setup này có đáng giao dịch không?
2. Setup A, setup B hoặc biến thể nào phù hợp với bối cảnh ấy?
3. Với từng phương án TP/SL hợp lệ, xác suất có lãi ròng và kỳ vọng net_R là bao nhiêu?
4. Có nên ENTER hay SKIP? Bỏ vì thiếu lợi thế phải phân biệt với thiếu dữ liệu.
5. Nếu ENTER, chọn phương án TP/SL nào và áp dụng trong phạm vi nào?
6. Phần cải thiện đến từ đọc bối cảnh, lọc setup hay thay TP/SL? Có giữ đủ cơ hội theo mục tiêu đã đặt không?

Muse điều phối các chương trình train và thí nghiệm. Các hệ số model do chương trình học từ dữ liệu tạo ra; thời gian Muse đọc báo cáo hoặc trò chuyện không tự cập nhật model.

## 2. Điểm xuất phát đã kiểm tra

| Thành phần | Hiện trạng | Cách tiếp nối |
| --- | --- | --- |
| Harness attempt_9_claude | Review9 chấp nhận `ACCEPTED_SOFTWARE_RESEARCH_SCOPE` | Dùng làm baseline đã nghiệm thu; giữ manifest và fixture |
| TP/SL | Có bốn action: baseline, TP theo level, SL theo swing xác nhận, kết hợp level/swing | Tái dùng action catalogue và phần chuẩn bị kế hoạch/replay |
| Trainer | Ridge dự báo net_R cho candidate–action | Giữ làm bộ dự báo kỳ vọng; không gọi điểm Ridge là xác suất thắng |
| Đầu vào model TP/SL | 10 feature: ATR, hình dạng nến, spread/R, drift/ATR, giờ UTC, hướng, loại setup | Nối thêm context có contract và version, dùng chung giữa train/infer |
| Context tool | Có EMA, ADX/DI, RSI, ER, ATR percentile, RVOL tick, khoảng cách PDH/PDL và vùng H1 | Tận dụng phép tính hiện có, kiểm đúng thời điểm và nguồn |
| Quyết định hiện tại | Chọn action có điểm cao nhất trong các action hợp lệ | Bổ sung học ENTER/SKIP; không vào chỉ vì một action ít xấu hơn các action khác |
| Model dùng trên máy | Có đường infer/card trong staged; live chưa bật tự động | Gói mới cần loader, compatibility check và kiểm native trước sử dụng |
| Mẫu thật | EURUSD 179.441 tick, 74 chunk, 17 candidate, có 9 giờ thiếu | Mẫu kiểm luồng phần mềm; chưa đủ chứng minh winrate |
| Phí BASE mẫu thật | Chưa có nhãn hữu hạn vì thiếu contract_size để quy đổi commission | Hoàn thiện cost/contract riêng theo nguồn trước nghiên cứu kinh tế |
| Linux/Muse | Chưa chạy thực tế và chưa soak 24 giờ | Cổng kiểm môi trường trước nghiên cứu dài ngày |
| Dữ liệu 2021–2026 | Nhiều mã/giai đoạn đã dùng nghiên cứu | Giữ nhãn historical-exposed; kiểm cuối ưu tiên forward sau freeze |

Biên bản nền: `codex_outbox/reviews/HARNESS_TPSL_20261105_REVIEW_9/CODEX_REVIEW.md`.

Release nền: `quant_mt5/phases/HARNESS_TPSL_20261105/attempt_9_claude/delivery/muse_tpsl_harness_attempt9.zip`, SHA256 `0c39e0a0b2bc833f14029e17bba2951580aeefe4f7c9dd8f7bf634ccef965a20`.

## 3. Luồng hoàn chỉnh cần đạt

```text
MUSE: raw tick Bid/Ask + metadata nguồn/chi phí
  -> kiểm chất lượng và dựng nến có provenance
  -> detector + context biết được tại từng thời điểm
  -> tập cơ hội đầy đủ, chưa bị model lọc
  -> replay mỗi phương án TP/SL để tạo nhãn kết quả
  -> train dự báo xác suất có lãi và net_R
  -> học policy chọn setup / ENTER-SKIP / TP-SL
  -> kiểm định theo thời gian + danh mục + chi phí bất lợi
  -> xuất model, policy, schema, bằng chứng và manifest

MÁY LOCAL: gói được tải về và kiểm chứng
  -> quant tính cùng feature trên snapshot MT5 hiện tại
  -> chạy cùng policy đã kiểm định
  -> trả đánh giá, ENTER/SKIP hoặc trạng thái thiếu bằng chứng,
     cùng entry/SL/TP và lý do cho Codex/Claude phân tích
```

Chương trình backtest, CLI infer và card phải dùng chung hàm chuẩn bị feature và quyết định. Không viết ba bộ logic tương tự nhưng khác điều kiện.

## 4. Phạm vi học: dùng được những gì trong bộ phân tích?

### 4.1 Bắt đầu từ setup hiện có, có đường mở rộng rõ ràng

- Setup A: phá vùng H1 rồi retest M5; giữ các branch M0/M1/M2 để đối chiếu.
- Setup B: fakey M5, vị trí PDH/PDL và cửa sổ phiên; giữ P0/P1/P2 để đối chiếu.
- Tập raw candidate vẫn được ghi đầy đủ. Một gate thất bại hoặc một lệnh trước đã mở không được làm mất candidate khỏi kho nghiên cứu.
- Vòng đầu học bối cảnh và cách lựa chọn trên hai họ này. Không giả định chúng chắc chắn có edge: nghiên cứu B4 trước đây chưa hỗ trợ seed hiện tại.
- Nếu cả hai không qua cổng kinh tế, Muse được đề xuất một giả thuyết setup mới mỗi vòng, với detector có quy tắc máy đọc được, version và fixture riêng. Tìm setup mới là nhánh nghiên cứu có đăng ký; không sửa detector âm thầm để làm đẹp thống kê.

### 4.2 Nhóm context được nối vào dữ liệu train

| Nhóm | Công cụ đã có | Câu hỏi nghiên cứu |
| --- | --- | --- |
| Hướng và mức rõ của xu hướng | EMA H1, slope/ATR, ADX/DI, ER M5 | Setup continuation hay fakey có hiệu quả ở trạng thái nào? |
| Biến động | ATR, ATR percentile quá khứ, range/ATR | Biến động nào khiến tín hiệu có dư địa hoặc dễ bị quét? |
| Vị trí | PDH/PDL, high/low 8 H1, khoảng cách/ATR | Entry có sát cản, còn đủ room tới target sau phí không? |
| Hoạt động của feed | RVOL20 tick, RVOL cùng slot khi đủ lịch sử | Hoạt động tăng/giảm có thêm giá trị ngoài cấu trúc giá không? |
| Chất lượng tín hiệu | Body/range, wick/ATR, hướng đóng, trạng thái episode | Hình dạng/phản ứng nào hữu ích cho từng setup? |
| Thực thi | Spread/R, entry drift, quote age, latency, thời hạn | Lợi thế còn tồn tại với giá và tốc độ vào lệnh thực tế không? |

Mỗi feature có tên, timeframe, đơn vị, cách seed/warmup, nguồn và available_at. Tập feature v1 được khóa sau audit; không đưa mọi indicator vào chỉ vì có sẵn. Dùng các phép bỏ từng nhóm feature để đo giá trị thêm; các phép thử ấy cũng vào registry.

Nguyên tắc:

- Tính trạng thái thị trường tại quyết định bằng dữ liệu quá khứ; không dùng nhãn “hôm ấy là ngày trend” được tạo sau khi xem cả ngày.
- Tick volume/RVOL là hoạt động của feed, không phải tổng volume thị trường hay order-flow delta.
- Các indicator cùng tính từ giá có thể trùng thông tin; không coi số lượng indicator đồng thuận là xác suất thắng.
- Scaler, percentile, ngưỡng phân nhóm và cách xử lý thiếu dữ liệu chỉ fit trên phần dữ liệu được phép học.
- Giữ nguyên UNKNOWN khi không đủ history. Model không hỗ trợ pattern thiếu ấy thì không chấm, không điền 0 cho tiện.
- Chỉ thêm tin tức khi có lịch sử có dấu thời gian và nguồn. Không tuyên bố đã tránh tin từ một bộ dữ liệu chỉ có giá.
- Nghiên cứu từng symbol trước. Gộp model giữa vàng và FX cần chuẩn hóa và một phép kiểm riêng, không gộp ATR thô khác đơn vị.

## 5. Dataset và nhãn: model thực sự học từ cái gì?

### 5.1 Một đơn vị quyết định

Một cơ hội được định danh bằng symbol, setup, candidate/revision, episode hoặc market event, source và thời điểm quyết định. Mỗi action TP/SL có row riêng nhưng dùng cùng identity chung đã kiểm nhất quán ở Review9.

Mỗi row gồm:

- Identity và hash của code/config/data/context/action/cost/latency.
- Feature khả dụng tại thời điểm quyết định.
- Entry quote, SL, TP, target room, R và kế hoạch hợp lệ hay bị chặn.
- Kết quả tick replay, fill/exit time, lý do thoát và chi phí.
- Trạng thái coverage và thời điểm nhãn được biết.

**Bốn row TP/SL của một candidate không phải bốn mẫu thị trường độc lập.** Các action, branch trùng sự kiện và các scenario của cùng cơ hội phải ở cùng phần chia dữ liệu.

### 5.2 Nhãn riêng cho từng câu hỏi

| Nhãn | Định nghĩa | Mục đích |
| --- | --- | --- |
| `net_R` | Kết quả ròng sau chi phí, theo R đã khóa | Học kỳ vọng và đánh giá kinh tế |
| Có lãi ròng | 1 nếu net_R > 0; 0 nếu net_R <= 0; chỉ trên outcome resolved | Học xác suất có lãi; báo hòa vốn riêng trong thống kê |
| Sự kiện thoát | TP trước / SL trước / timeout / unresolved | Hiểu cơ chế thắng thua và thời hạn |
| MAE/MFE, thời gian tới đích | Chỉ tính sau quyết định | Phân tích kết quả; không đưa vào feature đầu vào |

Chạm TP trước SL không đồng nhất với có lãi ròng. Timeout có thể lãi hoặc lỗ; không loại timeout khỏi mẫu số winrate. Outcome thiếu tick/chi phí là unresolved, không tự gán thắng, thua hay 0R.

### 5.3 Replay và chi phí

- Dùng Bid/Ask theo đúng chiều vào/ra; không trừ spread lần hai.
- Giữ quy tắc tick-grid, SL cấu trúc/swing được xác nhận, thời hạn, quote freshness, entry drift và episode.
- Nhãn chỉ resolved khi coverage đủ phần cần cho quyết định, SL và diễn biến đến hết hạn thoát theo contract.
- Giá fill khi gap và slippage phải theo mô hình đã đăng ký, không bảo đảm khớp đúng mức SL.
- LOW là cận lạc quan. Kết luận chính cần BASE có contract/commission/currency quy đổi được; thêm scenario bất lợi đang được config hỗ trợ, ghi rõ tên và assumption.
- Phép kiểm độ trễ phải có 5/30/60 giây đã có, cùng thời gian thu dữ liệu/tạo báo cáo thực tế khi mang về dùng vào tay. Không chọn riêng scenario nhanh nhất làm kết luận sử dụng.
- So sánh chất lượng dữ liệu theo symbol/phiên/trạng thái thị trường để phát hiện việc missing data làm subset đẹp hơn.

### 5.4 Chạy trên bộ nhớ có hạn

Đọc theo chunk ngày/tháng có warmup và state carry qua ranh giới. Giữ episode/vị thế chưa kết thúc, pending label và khóa dedup; không chốt lệnh giả ở cuối file. Cache chỉ tái sử dụng khi đủ hash nguồn, context, action, cost và code. Đo throughput/RAM trước khi quyết định tải lịch sử dài.

## 6. Phần train mới cần xây

### 6.1 Ba phần học nhỏ, rõ trách nhiệm

1. **Model kỳ vọng:** tái dùng Ridge net_R hiện có, bổ sung context và feature theo action có version.
2. **Model xác suất có lãi:** bắt đầu bằng mô hình đơn giản có thể kiểm độc lập, ưu tiên logistic regularized dùng bộ thư viện đã khóa; thêm dependency chỉ khi cần. Xác suất phải được calibration trên phần dữ liệu riêng.
3. **Policy quyết định:** lựa chọn action hợp lệ và ENTER/SKIP từ dự báo, phạm vi hỗ trợ, chi phí và giới hạn danh mục.

Có thêm bảng quy tắc đơn giản theo context làm challenger đối chứng. Nếu bảng này hiệu quả ngang model thì ưu tiên phương án đơn giản. Chưa cần deep learning, GPU, reinforcement learning hoặc fine-tune model ngôn ngữ.

### 6.2 Quyết định theo toàn bộ phương án có thể thực hiện

Tại thời điểm t:

1. Dùng đúng snapshot t, xác định các action thực sự chuẩn bị được.
2. Tính feature riêng của từng action, đặc biệt R, spread/R và room tới TP.
3. Dự báo E[net_R | context, action] và P(net_R > 0 | context, action).
4. Loại action ngoài phạm vi model, thiếu bằng chứng, hết hạn hoặc không đạt điều kiện policy đã khóa.
5. So sánh các action còn lại với lựa chọn SKIP có kết quả giao dịch bằng 0.
6. Nếu không có action đạt, trả SKIP. Nếu có, chọn theo policy đã đăng ký rồi áp dụng episode/capacity của danh mục.

Không bắt buộc gate vào/bỏ chỉ nhìn TP/SL baseline: có thể một action hợp lệ khác phù hợp hơn. Ngược lại, chọn action có điểm cao nhất không tự là lý do ENTER nếu tất cả dự báo đều không đạt.

Ngưỡng xác suất không được chọn một mình: nó phụ thuộc mức lời/lỗ, chi phí và timeout. Điểm Ridge không được nhân 100 thành winrate. Calibration thiếu mẫu hoặc ngoài miền dữ liệu thì trả trạng thái chưa đủ bằng chứng.

### 6.3 WATCH/WAIT và dữ liệu thiếu

Phần học v1 có hành động giao dịch rõ ràng ENTER/SKIP tại quyết định hợp lệ. WATCH/WAIT phục vụ theo dõi điều kiện chưa xuất hiện hoặc dữ liệu chưa đủ. Chờ một tín hiệu xác nhận mới phải tạo quyết định/candidate mới theo detector; không dùng giá tương lai chọn lại entry đẹp cho candidate đã hết hạn.

Thiếu model hay cost contract không được tự biến thành ENTER baseline chưa được chứng minh. Card có thể hiển thị baseline tham chiếu và lý do model không áp dụng được.

## 7. Muse tìm cách đánh phù hợp bằng quy trình nào?

Một vòng nghiên cứu:

1. Đọc registry, kết quả cũ và các giả thuyết đã thất bại.
2. Đặt một câu hỏi có cơ chế: ví dụ “retest H1 có tốt hơn khi xu hướng rõ và còn room tới cản?”.
3. Đăng ký setup/feature/threshold family, dữ liệu, splits, cost, metrics và số phép thử trước khi xem kết quả.
4. Chạy khám phá trên development; lưu toàn bộ biến thể đã thử và lý do loại.
5. Train, calibration, chọn policy bằng validation trong phạm vi đã cho phép.
6. Kiểm ngoài cửa sổ học theo thời gian; lưu kết quả tốt/xấu và bất định.
7. So với baseline và đối chứng cùng điều kiện; kiểm lại diễn biến tick của các ca quyết định.
8. Xuất candidate policy hoặc kết luận chưa đủ/không có lợi thế; checkpoint rồi mới nhận task tiếp.

Không mở grid lớn gồm hàng trăm threshold indicator × TP/SL × khung giờ rồi lấy một hàng đẹp nhất. Đổi detector, context, threshold, cost, latency, cửa sổ dữ liệu hoặc tiêu chí sau khi thấy kết quả phải ghi là biến thể nghiên cứu, không phải retry kỹ thuật.

Mỗi vòng tối đa một hướng setup mới hoặc một nhóm cải tiến có lý do. Lưu cả thất bại trong kho tri thức có liên kết spec/result. Không để Muse tự viết kết luận PASS thay chương trình kiểm chứng.

## 8. Thiết kế kiểm định và đối chứng

### 8.1 Bốn cấu hình phải so riêng

| Cấu hình | Thay đổi | Tách được giá trị của phần nào? |
| --- | --- | --- |
| B0 | Detector và TP/SL cố định đã khóa, không model lọc setup | Mốc gốc |
| B1 | Detector như B0, model chọn bốn action TP/SL, chưa học SKIP | Đóng góp riêng của TP/SL |
| C1 | Bảng quy tắc context đơn giản cho ENTER/SKIP, exit đã khóa | Lợi ích của đọc bối cảnh bằng cách đơn giản |
| C2 | Model context + xác suất/net_R + chọn ENTER/SKIP và action | Giá trị thêm của phần train mới |

B1 phải được fit đúng từng split bằng dữ liệu được phép học; không dùng gói toy 17 candidate làm benchmark kinh tế. Những branch/ablation khác được đăng ký vào cùng lịch sử nghiên cứu, không giấu khỏi số lần thử.

### 8.2 Chia dữ liệu theo thời gian

- Train để fit; calibration riêng cho xác suất; validation để chọn policy/ngưỡng; cửa sổ test tiếp theo để đánh giá bản đã khóa.
- Ví dụ lịch walk-forward: train 12 tháng → calibration 2 tháng → validation 1 tháng → test 1 tháng, tiến thêm một tháng. Đây là thiết kế khởi đầu; chỉ khóa sau khi kiểm số mẫu, mọi điều chỉnh dùng development.
- Không xáo trộn tick/lệnh thành train-test ngẫu nhiên.
- Chia toàn universe theo cùng mốc thời gian. Group candidate/opportunity/episode và các action/scenario liên quan; purge các group/nhãn vượt ranh giới; embargo bao phủ horizon đã đăng ký.
- Scaler, chọn feature, tuning model, calibration và ngưỡng quyết định đều không được nhìn cửa sổ test.
- Thay phần dữ liệu sau t không được làm đổi feature/quyết định trước t; batch/incremental cùng prefix phải khớp.
- Sau khi xem các test lịch sử để chỉnh hướng, chúng là dữ liệu validation đã tiếp xúc. Tải tick từ provider khác cho cùng giai đoạn không làm thành holdout sạch.
- Kiểm cuối một lần ưu tiên forward sau khi khóa code/model/policy/nguồn. Chưa đủ mẫu thì giữ kết luận chưa đủ bằng chứng.

### 8.3 So sánh công bằng

Tính cả cấp cơ hội và danh mục thực thi: một fill/episode, xung đột, giới hạn vị thế, thời gian giữ, opportunity bị capacity chặn. Mỗi policy có timeline riêng.

So sánh daily net_R trên cùng lịch có cả ngày 0 lệnh. Unresolved day giữ cờ, không điền thành 0. Bootstrap theo khối ngày/tuần và giữ các symbol cùng ngày trong cùng khối; áp dụng family kiểm định đã đăng ký. Holm chỉ xử lý family được khai báo, không xóa ảnh hưởng của việc tìm kiếm thích nghi vô hạn.

Thêm null thực nghiệm khi kiểm cơ chế: giữ symbol, thời điểm, regime, spread, phía Bid/Ask, hình học TP/SL và time stop tương đương; tái chạy execution hợp lệ. Không dùng công thức xác suất ngẫu nhiên lý tưởng làm bằng chứng edge.

## 9. Tối ưu winrate và điều kiện chọn model

Winrate chính = số lệnh resolved có net_R > 0 / tổng lệnh resolved đã thực hiện, bao gồm timeout và hòa vốn ở mẫu số. Báo thêm TP-hit rate, hòa vốn, unresolved, số ngày và số cơ hội để không trộn các khái niệm.

Mục tiêu là tìm vùng đánh đổi tốt giữa winrate, kỳ vọng, drawdown và tần suất. Winrate rất cao nhờ TP cực gần, SL cực xa hoặc lọc còn vài lệnh không tự đạt yêu cầu.

### Cổng kinh tế đề xuất để khóa trước nghiên cứu

- BASE expectancy tối thiểu +0,05R/lệnh, profit factor tối thiểu 1,20.
- Cận dưới khoảng tin cậy 95% của expectancy lớn hơn 0 theo phép ước lượng đã đăng ký.
- Kịch bản chi phí bất lợi có expectancy dương; LOW không làm headline.
- Winrate và daily net_R so với B0/B1 có báo delta và khoảng bất định; không chỉ tốt hơn một baseline âm rồi gọi là có edge.
- Floating drawdown và tổn thất đuôi nằm trong giới hạn protocol; đánh giá cùng ngân sách chuẩn hóa. Chưa có account/risk profile thì chưa kết luận pass luật quỹ.
- Số raw opportunity, fill, fill-retention, lệnh/ngày, ngày không có lệnh và các lệnh bị SKIP/capacity chặn phải công khai. Yêu cầu duy trì cơ hội đã có được ghi thành mục riêng: giảm fill thì không được báo mục tiêu đó đạt.
- Kiểm ổn định qua các cửa sổ, symbol, setup, session và regime đã đăng ký; chỉ cho phép áp dụng ở phạm vi được bằng chứng hỗ trợ.

Các con số trên là tiêu chí đề xuất của kế hoạch mới, không phải kết quả đã đạt. Nếu protocol mục tiêu trước đặt yêu cầu chặt hơn về retention/rủi ro thì giữ yêu cầu đó; không tự hạ sau khi xem P&L.

Mốc thu thập ban đầu để đánh giá độ chính xác: khoảng 300 cơ hội được fill độc lập, ít nhất 120 ngày giao dịch và nhiều cửa sổ ngoài phần học. Đây là mốc lập ngân sách dữ liệu, không bảo đảm đủ lực thống kê. Từng phạm vi setup×symbol cần báo số sự kiện/ngày riêng, calibration và CI thực tế; không dùng tổng mẫu của cả hệ thống bảo chứng một nhánh rất ít lệnh.

Xác suất có lãi chỉ được xuất khi calibration được kiểm bằng reliability curve và Brier score, so với dự báo tần suất nền phù hợp. Không đạt thì xuất điểm/kỳ vọng có nhãn và trạng thái xác suất chưa được hỗ trợ.

## 10. Chạy nghiên cứu nhiều ngày trên Muse

Cấu hình người dùng đã nêu trong chat trước: 4 nhân CPU, 8 GB RAM, không GPU. Cần đo lại máy thật khi triển khai.

- Tái dùng runner, registry, run-batch, budget, checkpoint và khóa owner của harness hiện có.
- Bắt đầu một job nặng tại một thời điểm; giữ BLAS/OMP/MKL = 1 đúng contract hiện tại, budget task ban đầu 2 GB. Chỉ đổi ngân sách bằng spec/version sau benchmark.
- Mỗi task hữu hạn: spec hash, input pins, max_trials, thời gian, RAM, dung lượng, đầu ra và điều kiện hoàn tất. Danh sách task tạo thành queue nghiên cứu nhiều ngày.
- Tách tải dữ liệu khỏi job offline train/verify; job train không cần quyền truy cập tài khoản MT5.
- Checkpoint sau chunk/fold/trial. Crash, hết RAM hoặc timeout phải có trạng thái lỗi; resume không nhân đôi mẫu hoặc tự ghi lại task COMPLETED.
- Mỗi candidate model là artifact mới. Không ghi đè model đã được chấp nhận bằng vòng train mới kém hơn.
- Kiểm Linux sạch: dependency/import/path có dấu, cùng input cho semantic output khớp, resource limit, crash/restart và soak 24 giờ. Chỉ xác nhận khả năng chạy dài khi có bằng chứng thực tế.
- Nếu không còn giả thuyết hợp lệ hoặc hết budget, dừng queue và xuất tổng kết. Không tiếp tục bẻ tham số chỉ để tạo một bản thắng.

## 11. Gói kết quả tải về và cách quant dùng nó

### 11.1 Kế thừa chuẩn đầu ra TP/SL

Bộ train setup dùng cùng các nhóm đầu ra và mức kiểm chứng của harness TP/SL attempt9. Mọi release nghiên cứu đề xuất sử dụng phải đủ model, contract đầu vào/đầu ra, bằng chứng, lineage, manifest và trusted receipt; một báo cáo Markdown hoặc một file weights riêng không phải gói hoàn chỉnh.

| Nhóm bắt buộc | File/contract của TP/SL làm nền | Yêu cầu cho bản học setup |
| --- | --- | --- |
| Model | `MODEL.json` | Có tham số thật, family, kích thước, model ID và cutoff; định danh riêng component net_R, xác suất và TP/SL được dùng |
| Feature và chuẩn hóa | `FEATURE_SCHEMA.json`, `PREPROCESSING.json` | Khóa tên/thứ tự/đơn vị/context version, warmup, scaler và xử lý missing; train/infer cùng phép tính |
| Calibration | `CALIBRATION.json` | Phân biệt calibration kỳ vọng net_R của bản cũ với calibration xác suất; có trạng thái, dữ liệu và cutoff tương ứng |
| Các phương án | `ACTION_CATALOG.json` | Giữ catalogue bốn phương án TP/SL; hành động ENTER/SKIP có contract riêng, không giả SKIP thành một kiểu SL/TP |
| Nguồn huấn luyện | `TRAINING_MANIFEST.json`, `LOCKED_SPEC.json`, `TRIALS.json` | Pin dữ liệu/code/config/cost, splits, seed, budget và mọi phép thử; khai exposure và assumption |
| Kiểm định và bằng chứng | `VALIDATION.json`, `EVALUATION_EVIDENCE.json`, `EVALUATION_LEDGER.jsonl` | Metrics có thể tái tính, so baseline, CI, calibration, coverage và phạm vi kiểm raw; không tự sinh số liệu |
| Sổ truy vết | `ROW_LEDGER.jsonl`, `SELECTION_LEDGER.jsonl`, `POLICY_LEDGER.jsonl`, `DAILY_LEDGER.jsonl` | Truy được cơ hội, action, quyết định, fill/exit, SKIP, capacity, unresolved và tổng hợp ngày |
| Tương thích và phạm vi | `COMPATIBILITY.json`, `MODEL_CARD.md` | Khóa phiên bản, symbol/setup/nguồn/cost/latency, hạn chế và evidence grade |
| Toàn vẹn và tin cậy | `MANIFEST_SHA256.json` + receipt do caller giữ bên ngoài package | Kiểm đủ payload, hash và receipt; không tin receipt chỉ tự lưu trong cùng package |

Những file đánh giá/lineage có điều kiện trong loader cũ được yêu cầu đầy đủ cho release research mới từ runner; schema phải khai rõ loại package và bộ file cần có. Diagnostic scores hoặc fixture không được tự nhận là release đã train/kiểm định.

### 11.2 Đầu ra bổ sung cho phần học setup

- Model xác suất có lãi và calibration đúng nghĩa xác suất, cùng bằng chứng reliability/Brier.
- Decision policy đã khóa: điều kiện ENTER/SKIP, ngưỡng, thứ tự chọn action và xử lý ngoài miền/thiếu dữ liệu.
- Context contract: cách tính các nhóm context mới, available_at, phiên/ngày, seed/warmup và quality.
- Bằng chứng so B0/B1/C1/C2, phần đóng góp của context/lọc setup, winrate/frequency/retention và kết quả bị loại.
- Liên kết ID/hash giữa các component. Không ghép model setup và TP/SL khác release mà thiếu compatibility check.

Tên payload mới và cách bố trí các component sẽ khóa trong S0 trước khi code; các nhóm thông tin trên là bắt buộc của kế hoạch.

### 11.3 Version và đầu ra suy luận

Cùng chuẩn chất lượng không có nghĩa schema nhị phân/JSON giống hoàn toàn. Loader TP/SL v1 đang khóa feature/action/model family; gói mới phải tăng version và nâng loader/verifier bằng contract tường minh. Loader cũ gặp version mới phải từ chối rõ; bộ nạp mới chỉ đọc bản cũ theo nhánh version đã được kiểm, không tự diễn giải weights Ridge thành model xác suất.

Contract suy luận mới phải có: snapshot/candidate/as_of/source, package/component IDs, trạng thái dữ liệu và phạm vi áp dụng, quyết định ENTER/SKIP hoặc unavailable, xác suất có lãi khi được hỗ trợ, E[net_R], scores theo action hợp lệ, action TP/SL được chọn và entry/SL/TP/deadline tương ứng, reason codes và mức bằng chứng. Với SKIP/unavailable, không trình bày mức giá tham chiếu như một lệnh đang được đề xuất; xác suất chưa hỗ trợ giữ null kèm lý do.

Cấu trúc logic dự kiến, kế thừa các contract trên:

```text
setup_policy_release_v001/
  manifest + receipt tương ứng
  feature_schema + context calculation version
  model kỳ vọng net_R + model xác suất có lãi
  calibration + decision_policy
  supported_domain: symbol/setup/regime/source/cost/latency/cutoff
  validation report + candidate/decision/policy ledgers
  experiment registry + model card + replay/parity evidence
```

Gói phải mô tả được: đã học gì, dùng ở đâu, khi nào SKIP, khi nào không đủ dữ liệu và số liệu chứng minh. Kết quả âm vẫn xuất research report, nhưng không được gắn nhãn model đạt kinh tế.

Khi mang về máy:

1. Kiểm manifest và trusted receipt được giữ ngoài package; kiểm compatibility và mọi cutoff.
2. Quant tính context từ snapshot MT5 mới bằng extractor cùng version.
3. Chạy policy đúng như backtest, dùng quote hiện tại và thời hạn thực.
4. Card trả setup, phạm vi áp dụng, xác suất nếu đã hiệu chuẩn, E[net_R], action, entry/SL/TP, lý do và dữ liệu còn thiếu.
5. Codex/Claude đọc card/context và phân tích bằng cùng snapshot. Không cần nạp toàn bộ lịch sử train vào chat.

Giá entry/SL/TP được lập từ dữ liệu mới; model lưu mối quan hệ và quy tắc, không tải về một danh sách mức giá cố định cho tương lai. Chưa kiểm domain shift Dukascopy→MT5 thì giữ nhãn nghiên cứu; cần đối chiếu feature/decision và forward trên native.

## 12. Gói triển khai và nghiệm thu

| Gói | Công việc | Điều kiện nghiệm thu cụ thể |
| --- | --- | --- |
| S0 | Khóa release Review9, dependency map, spec mới, cost/contract và mục tiêu | Nhận đúng baseline, BASE quy đổi được hoặc chặn đúng; protocol không thiếu metric/retention |
| S1 | Nối context vào shared pipeline và feature schema v2 | Batch/incremental/infer khớp; prefix và available_at đúng; thiếu feature không bị điền giả |
| S2 | Dataset quyết định, nhãn net-profit và streaming tick | Row/action identity đúng; timeout/unresolved đúng; qua ranh giới chunk không mất episode/outcome |
| S3 | Trainer xác suất + Ridge context + calibration | Fit thật thay đổi theo dữ liệu; nhãn tráo không tạo kỹ năng giả; thiếu mẫu trả insufficient; không rò giữa splits |
| S4 | Policy ENTER/SKIP và evaluator dùng chung | Tất cả action xấu thì SKIP; không đọc outcome khi chọn; một fill/episode; capacity/daily series khớp ledger |
| S5 | Research spec/queue, đối chứng B0/B1/C1/C2 và registry | Đếm đủ trial; resume idempotent; không thay test set hoặc chọn scenario đẹp ngầm |
| S6 | Export/loader/verifier và tự kiểm bản ZIP cuối | Từ chối package sai feature/weights/calibration/ledger; tính lại metrics và kiểm raw replay cho acceptance fixtures/candidate đề xuất |
| S7 | Linux/Muse platform check | Chạy từ ZIP sạch; parity semantic, budget, crash/resume và soak đạt trước nghiên cứu dài |
| S8 | Muse chạy nghiên cứu thật, xuất candidate; máy local kiểm và forward | Report đủ cả thất bại; model đạt cổng đã khóa; native feature/infer parity; quyết định forward được ghi trước outcome |

S0–S6 là phần xây và nghiệm thu tool trên laptop trước khi giao nghiên cứu lớn cho Muse. S7 là kiểm máy Muse. S8 mới là đợt train/nghiên cứu thực để tìm ra gói nâng cấp. Viết được trainer hoặc chạy mẫu thành công không thay thế S8.

Trong triển khai sau này, giữ cách làm đã thống nhất: Claude code trong staging, tự test source và ZIP xong mới báo DONE; Codex nghiệm thu độc lập sau DONE. Giao từng gói có input/output/oracle rõ ràng, tránh giao toàn bộ mục tiêu mơ hồ cùng lúc. Kế hoạch này chưa gửi việc cho Claude hoặc Muse.

## 13. Những phản chứng bắt buộc cho phần học mới

1. Chỉ sửa dữ liệu sau decision: feature, plan và ENTER/SKIP cũ không đổi.
2. Một candidate có bốn action: không action nào lọt sang split khác; episode/opportunity chung được purge đúng.
3. Mọi action kỳ vọng âm: không được ENTER chỉ vì lấy argmax.
4. TP rất gần làm tỷ lệ chạm TP cao nhưng net_R âm sau phí: không đạt cổng kinh tế.
5. Timeout lãi/lỗ/hòa: được đưa vào winrate và daily net_R đúng định nghĩa.
6. Thiếu tick/commission/profile: outcome unresolved; báo cáo không bỏ âm thầm để tăng winrate.
7. Cùng candidate nhưng field chung ở action sau mâu thuẫn: runner/evaluator/verifier cùng từ chối.
8. Feature hoặc plan riêng giữa action khác nhau hợp lệ: không ép bằng nhau hay tái dùng nhầm R.
9. Model/calibration học sau as_of: loader/infer từ chối chấm actionable.
10. Xóa/đổi weights, scaler, threshold, context hash rồi reseal package: trusted receipt và kiểm nội dung phải phát hiện đúng phạm vi.
11. CLI, loader và card cùng input: cùng scores, action, trạng thái và giá; không trả điểm 0 giả thành công.
12. SKIP ở trước một candidate cùng episode: candidate tiếp được xét đúng, nhưng sau fill không nhân thêm lệnh trong episode.
13. Portfolio đầy hoặc có tín hiệu trùng: ledger thống kê đủ lý do; ngày không lệnh vẫn tồn tại.
14. Restart giữa decode/fit/export/verify/commit: không mất trial, không tự nhận COMPLETED, không refit task đã xong.
15. Ranh giới chunk, DST, D1 boundary và warmup: không sửa nghĩa feature hoặc đổi lịch mà giữ cùng version.
16. Thêm context không cải thiện trên cửa sổ được phép đánh giá: không tự gọi model phức tạp hơn là nâng cấp.
17. Package tự khai metrics tốt nhưng raw replay/decision ledger không khớp: không được nhận là kết quả nghiên cứu đã xác minh.

Verifier hiện tại chưa replay toàn bộ tick raw; vì vậy phải ghi rõ mức kiểm. V1 cần replay kiểm độc lập trên fixture có oracle và các ledgers của candidate đề xuất trước nghiệm thu kinh tế. Hash và tái tính từ một ledger tự khai không tự chứng minh ledger được tạo đúng từ raw.

## 14. Mốc hoàn thành và thứ tự làm

1. **Tool train đạt kỹ thuật:** S0–S6 hoàn tất và gói ZIP tái lập được. Có đường học ENTER/SKIP và context thật, không chỉ thêm nhãn lên bộ TP/SL cũ.
2. **Muse chạy được nghiên cứu:** S7 đạt, queue hữu hạn và resume/resource có bằng chứng. Sau đó mở rộng dữ liệu từ pilot sang lịch sử dài theo chất lượng và tốc độ đo được.
3. **Có candidate đáng dùng:** S8 tạo model/policy qua các cổng kinh tế và uncertainty; trả đúng phạm vi hỗ trợ. Nếu không có candidate đạt, báo nghiên cứu âm/chưa đủ thay vì tự promote.
4. **Dùng trên MT5 hằng ngày:** native validation và forward xác nhận phần tích hợp; quant nạp gói và Codex/Claude đọc kết quả như luồng phân tích hiện có.

Ưu tiên bắt đầu khi chuyển sang triển khai: **S0 → S1 → S2 → S3/S4 → S5/S6 → S7 → S8**. Không cần xây giao diện mới để kiểm chứng giá trị của phần học.

## 15. Nguồn phương pháp đã kiểm

- [MQL5 — copy_ticks_range](https://www.mql5.com/en/docs/python_metatrader5/mt5copyticksrange_py): contract tick Bid/Ask và UTC của API. Cache cũ còn mâu thuẫn clock phải audit riêng; không áp offset chỉ vì nhìn giờ trên chart.
- [Bailey và cộng sự — Statistical Overfitting and Backtest Performance](https://www.davidhbailey.com/dhbpapers/overfitting.pdf): thử nhiều biến thể rồi chọn kết quả đẹp có thể tạo hiệu suất lịch sử không lặp lại. Kế hoạch áp dụng registry, chia thời gian và freeze/forward để hạn chế rủi ro đó; không coi một phép hiệu chỉnh thống kê là bảo đảm có edge.

**Lượt này chỉ tạo kế hoạch. Chưa sửa code, tải thêm tick, train, gửi việc hoặc đưa model lên Muse. Winrate cao là mục tiêu nghiên cứu cần chứng minh bằng dữ liệu.**
