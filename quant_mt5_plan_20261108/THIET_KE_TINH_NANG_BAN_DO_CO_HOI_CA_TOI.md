# Thiết kế tính năng: Bản đồ cơ hội giao dịch ca tối

Ngày: 08/11/2026, giờ Việt Nam.
Revision 2: MT5-only; A phá vùng H1/retest M5; lớp bối cảnh không thêm bộ lọc làm giảm cơ hội A.
Trạng thái: ĐÃ NGHIÊN CỨU CODE VÀ BẰNG CHỨNG CŨ; ĐỀ XUẤT THIẾT KẾ, CHƯA TRIỂN KHAI.

Bàn giao chi tiết mới hơn: [Bắt đầu và prompt giao việc](<D:/trading thử lần cuối cuối/quant_mt5_plan_20261108/ban_giao_A_MT5_only/00_BAT_DAU_VA_PROMPT_GIAO_VIEC.md>). Bộ 00–03 chốt 10 work packages, hợp đồng dữ liệu, giao thức hai call hữu hạn và 70 ca nghiệm thu. Người dùng sau đó đã giao triển khai và tạo skill **trade tối**; trạng thái triển khai thực tế theo checkpoint/báo cáo nghiệm thu, không suy từ bản thiết kế này.

Kết quả triển khai V1: [NGHIEM_THU.md](<D:/trading thử lần cuối cuối/quant_mt5/phases/EVENING_CONTEXT_A_MT5_20261108/attempt_1_codex/NGHIEM_THU.md>) — runtime/skill đã tích hợp, OFFLINE_ACCEPTED / LIVE_PENDING. Bản thiết kế bên dưới giữ nguyên bối cảnh nghiên cứu ban đầu.

## 1. Đúng bài toán người dùng

Đây là nghiên cứu tính năng hệ thống, KHÔNG phải quét hoặc đưa nhận định thị trường tối nay. Lượt này không attach MT5, không lấy dữ liệu live, không sửa runtime, không gửi lệnh, không tạo lịch tự động và không xóa tick.

Xây một lớp phân tích kỹ thuật đa tài sản để mỗi khi người dùng gọi trong các phiên tối, hệ thống trả lời được:

1. Có những tín hiệu A nào, mã nào cần xem trước, và bối cảnh thuận/nghịch của từng mã là gì?
2. Thị trường đang có xu hướng, cân bằng hay chưa rõ trạng thái?
3. Những vùng giá nào đáng chờ; giá có thể hướng tới vùng nào theo từng kịch bản?
4. Hành động giá và dữ liệu flow thực sự hỗ trợ hoặc phản bác hướng đó ra sao?
5. Cần diễn biến nào mới có cơ hội vào; khi nào hủy nhận định?

Không yêu cầu người dùng nhớ tên setup. Giao diện nói bằng hướng, vùng chờ, trigger, mục tiêu, điều kiện hủy. ID setup/branch giữ trong bằng chứng máy để kiểm toán. Nhánh A phá vùng H1/retest M5 là lõi sinh tín hiệu; lớp mới bổ sung thông tin, KHÔNG là bộ lọc bắt A vượt thêm điều kiện. Không tự thay chiến lược hoặc portfolio đang khai báo.

Nguồn vận hành duy nhất: dữ liệu do MT5/broker hiện có cung cấp qua bộ nối đã cài. Loại footprint, local-aggression/imbalance theo mức giá, DOM/heatmap và feed ngoài/trả phí khỏi lộ trình tính năng này; không để lại như hạng mục phải mua sau hoặc điều kiện đang thiếu cần vượt qua. Không yêu cầu tải indicator hay xuất file thủ công. Không xóa code/artifact nghiên cứu cũ trong lượt sửa kế hoạch.

Tin tức ngoài phạm vi: người dùng tự kiểm. Không scrape lịch tin, không chấm điểm tin, không đặt điều kiện phải lấy lịch tin mới được trả phân tích kỹ thuật. Báo cáo ghi `news_handling=USER_MANAGED`, `news_checked_by_system=false`; không tuyên bố đã tránh rủi ro tin tức.

## 2. Tách khỏi phần nâng cấp đang làm ở chat khác

Chat “Tối ưu setup quét thị trường” đang triển khai từ `KE_HOACH_NANG_CAP_QUET_CA_TOI.md`: tốc độ, bộ mã, capabilities/chi phí, vùng chờ, kiểm một mã và dọn tick.

Tính năng này nhận đầu ra của các phần đó, không viết một collector, cache, bộ vùng chờ hoặc cơ chế retention thứ hai. Tài liệu này không sửa kế hoạch hoặc code của chat kia. Yêu cầu mới về tin tức áp dụng cho tính năng này; mục lấy lịch tin trong kế hoạch trước không được mang sang làm gate.

Ranh giới sở hữu:

| Phần nền đang nâng cấp | Phần phân tích bổ sung tại đây |
|---|---|
| Thu dữ liệu, clock/coverage, nguồn demo, snapshot/config pins | Tổng hợp bối cảnh từng mã từ cùng snapshot |
| Mở rộng symbol, metadata, chi phí, mapping broker | So sánh mã; giải thích thuận/nghịch, không loại tín hiệu A |
| Watch zones và kiểm candidate còn hạn | Bản đồ vùng tham chiếu, kịch bản chính/ngược, thay đổi bias |
| Tăng tốc, tái dùng dữ liệu, ghi nhật ký, dọn tick | Lưu toàn bộ tín hiệu A và nhãn bối cảnh trước khi biết kết quả |

Trước lúc code phải đọc lại phiên bản runtime mới và điều chỉnh điểm nối; số dòng trong nghiên cứu chỉ là mốc tại thời điểm đọc. Không sửa đồng thời các file shared trong khi chat kia đang thay đổi chúng. Không tự nhắn hoặc điều khiển chat kia.

## 3. Chốt đúng nhánh A và hợp đồng không làm giảm cơ hội

Đã đọc lại chat “Tối ưu setup quét thị trường” và đối chiếu `quant_mt5_plan_20261103/quant-mt5-agent/references/setup-specs.md`, mục 2, cùng hàm `detect_A` trong `quant_mt5/quantmt5/detectors.py`.

Định danh chính xác: **Setup A — MTF breakout/retest continuation**. Vùng được neo từ high/low của 8 nến H1 hoàn tất và đóng băng. Nến M5 đóng phá biên tạo episode; một nến M5 sau đó hồi kiểm tra vùng và có phản ứng đóng nến hợp lệ mới tạo candidate. H1 là khung tạo vùng, không có nghĩa mọi biến thể phải đợi một nến H1 mới xác nhận phá vỡ.

- M0: không có gate xác nhận H1 bổ sung.
- M1: thêm hướng close H1 so với EMA50, không thêm slope.
- M2: cần H1 hoàn tất có mốc đóng từ mốc đóng nến breakout trở đi và close ngoài chính biên vùng đã neo; không hồi tố candidate M5 trước đó.

Ba biến thể giữ nguyên; không nhầm với Fabio F1/F2 hay một chiến lược phá đỉnh của một nến H1 đơn lẻ. Khi tích hợp, ghim comparator theo branch/config vận hành đã chọn, kiểm riêng M0/M1/M2; không tự đổi `portfolio.declared_pair` A/M2+B/P1 sang M1 hoặc M0. M0 bên dưới là mốc của báo cáo tuần, không phải quyết định đổi branch giao dịch.

Nguồn: `quant_mt5/runtime/on_demand/weekly_fabio_20261102_08/WEEKLY_TRIAL_REPORT.md`, `TRAILING_TRIAL_REPORT.md` và replay gốc.

- A/M0: 10 lệnh đóng, 8 thắng/2 thua, tổng +0,429705R; trung bình khoảng +0,043R/lệnh. Có một lần SL_GAP khoảng -5R.
- A/M1: 9 lệnh đóng, 8 thắng/1 thua, +5,429705R. Là 9 fill trùng của M0 sau khi loại một loss, không phải tập độc lập mới; không tự chọn nó chỉ vì đẹp hơn.
- Dữ liệu cả tuần, không phải riêng ca tối; chi phí/latency giả định, clock chưa xác minh, coverage PARTIAL. Không suy rộng sang chỉ số hoặc mã mới.
- Kết quả A là lý do đáng tiếp tục nghiên cứu. M0/M1/M2 được giữ nguyên nhãn, không chọn biến thể bằng kết quả đẹp của chính tuần này. Fabio F1/F2 là lớp khác, không được thừa hưởng winrate của A.

Mục tiêu revision này là giữ cơ hội A, giúp hiểu bối cảnh và chuẩn bị trước vùng retest. Không sửa luật A, SL/TP, TTL, deadline, risk hoặc giới hạn vị thế. Nếu giữ nguyên mọi lệnh, giá thực thi và cách thoát thì P&L/winrate cũng phải giữ nguyên; không hứa tăng winrate chỉ nhờ thêm diễn giải. Các cải thiện về bỏ lỡ tín hiệu/thời gian phản ứng phải đo riêng.

### 3.1 Ba trạng thái tách biệt, không thêm quyền phủ quyết A

| Trạng thái | Quyền hạn |
|---|---|
| `baseline_status` | Giữ nguyên candidate, gate, eligibility và lý do của đúng branch A |
| `execution_safety_status` | Giữ nguyên kiểm dữ liệu/quote, deadline, spread, cost, integrity và policy nền; không vô hiệu guard để tăng số lệnh |
| `context_status` | ỦNG_HỘ / MÂU_THUẪN / TRUNG_TÍNH / CHƯA_CÓ; chỉ bổ trợ, không ghi đè hai trạng thái trên |

Không yêu cầu A đồng thời qua CVD, RVOL, RSI, ADX, POC/LVN, sức mạnh tương đối và đồng thuận đa khung. Thiếu/trái chiều một feature bổ sung chỉ tạo chú thích. `WAIT/SKIP` của Fabio không phải quyền chặn A; economics của Fabio không ghi đè economics của A. Chi phí ASSUMED vẫn là ASSUMED, UNKNOWN không thành 0/KNOWN; kết quả mô phỏng không được nâng thành lệnh live đã an toàn.

Ngay cả nhãn “bối cảnh bất lợi” cũng không biến A thành “bỏ lệnh”. Nếu người dùng tự bỏ theo nhận định thì ghi đó là quyết định thủ công, đo riêng, không tính như baseline hoặc âm thầm áp thành rule mới. Mọi thay đổi gate/entry/exit về sau nằm ngoài MVP này.

“Không giảm tần suất” nghĩa là không làm mất cơ hội do lớp mới trên cùng đầu vào/lịch gọi; không hứa ngày nào thị trường cũng sinh cùng số lệnh, không hứa mọi candidate đều khớp hoặc phải được người dùng giao dịch.

## 4. Tài nguyên có sẵn và khoảng trống thật

Các đường dẫn bên dưới tính từ `D:/trading thử lần cuối cuối/quant_mt5/`.

| Năng lực | Trạng thái lúc khảo sát | Điểm dùng lại |
|---|---|---|
| Context không cần candidate; ATR, RVOL, hình học nến | Đã có | `quantmt5/context.py:213`, `build_market_context` |
| Đỉnh/đáy D1 hoàn tất, biên 8 H1, khoảng cách ATR | Đã có, kèm giới hạn clock | `context.py:249`; biên H1 mô tả không phải anchor A |
| EMA/slope, ADX/DI, RSI, ER, ATR percentile | Đã có theo nhóm tùy chọn | `context.py`, `features.py`; không cộng thành phiếu độc lập |
| Balance, value area, POC/LVN, phản ứng giá, phản chứng | Đã có trong lớp Fabio | `fabio.py:112`, `:422`, `:581` |
| Tick pinned, CVD, profile, Bid/Ask | Đã có với nhãn nguồn và coverage | `mt5_flow.py`, `fabio.py:715` |
| Rule/card A, identity, expiry, journal | Đã có | `detectors.py`, `context.py:395`, `paper.py` |
| Context toàn universe, watch zones, cards/deferred và cache theo lượt | Đã xuất hiện trong bản nâng cấp đang làm | `reporting.py:62`, `analysis_cache.py`; cần đọc lại khi nền chốt |
| Bảng A đầy đủ + nhãn bối cảnh không lọc + diễn giải liên thị trường | Chưa đáp ứng trọn hợp đồng revision 2 | Mở rộng packet/renderer hiện có, không làm collector thứ hai |
| Biên phiên, swing xác nhận, thay đổi kịch bản qua các lượt | Chưa có thành một bản đồ thống nhất | Bổ sung theo từng mốc, không trùng watch-zone engine |
| Sức mạnh tương đối và nhóm exposure | Chưa có trong runtime được đọc | Đợt sau; chỉ số dẫn xuất từ giá, không phải dòng tiền thực |
| Nhật ký outcome và đo tác động của lớp bối cảnh | Nền đang bổ sung; chưa nghiệm thu toàn luồng | Tái dùng outcome, bổ sung delivered/nhãn/context trước outcome |

Khung có sẵn là M1/M5/H1/D1; MVP dùng H1 để đọc bối cảnh, M5 để đọc phản ứng, D1 hoàn tất để tham chiếu. Chưa thêm H4/M15 nếu khung hiện có đủ. Tận dụng nến, tick/quote, spread, hoạt động tick, RVOL, ATR và metadata/lịch phiên có chất lượng rõ; không cố dùng mọi chỉ báo chỉ vì tính được.

## 5. Phương pháp phân tích sẽ được sản phẩm hóa

### 5.1 Trạng thái trước, vùng sau, trigger cuối

- Trạng thái: mô tả cấu trúc H1/M5 và balance/acceptance đã có; giữ UNKNOWN hoặc MIXED khi không đủ bằng chứng. Slope/ER/ADX phục vụ câu hỏi cụ thể, không bắt mọi chỉ báo đồng thuận.
- Vị trí: giá đang trong hay ngoài vùng cân bằng, gần biên nào, đã đi quá xa hay còn đường tới vùng đối diện? Khoảng cách dùng ATR/ticks, không so raw pips của vàng với chỉ số.
- Hành động giá: phá và giữ ngoài vùng; hồi kiểm tra; thất bại và đóng trở lại; nến xác nhận và phản ứng sau khi chạm. Một râu nến không tự chứng minh quét stop hoặc đảo chiều.
- Trigger: dùng đúng candidate/điều kiện của engine đã kiểm. Nếu mới là vùng chờ thì entry/SL/TP chưa có được để null, không vẽ một lệnh hoàn chỉnh cho đẹp báo cáo.

### 5.2 Bản đồ vùng và giả thuyết thanh khoản

MVP dùng vùng/episode A đã đóng băng, đỉnh đáy D1 đã hoàn tất, biên H1 mô tả, balance/POC/value area/LVN có nguồn. Giữ riêng loại vùng, nguồn, thời điểm biết, khoảng thời gian tạo vùng và chất lượng.

Đợt tiếp theo thêm biên các phiên trước/đang diễn ra và swing đã xác nhận. Mỗi mốc phải có định nghĩa thời gian rõ; vùng đang phát triển khác vùng đã hoàn tất. Session theo timezone IANA và lịch broker đã kiểm, không hardcode một giờ New York chung cho mọi ngày. Thiếu clock/coverage thì ghi thiếu, không gọi cực trị của phần dữ liệu bị khuyết là cực trị cả phiên.

Vùng đỉnh/đáy chỉ là nơi đặt giả thuyết có thanh khoản; không phải quan sát trực tiếp stop hay lệnh tổ chức. Mục tiêu đường giá là kịch bản có điều kiện, không nói thị trường chắc chắn phải đến đó. Không đổi anchor A thành rolling H1 high/low.

### 5.3 Order flow: hiển thị đúng độ sâu dữ liệu

- Có flags buy/sell và traded volume hợp lệ: đọc chênh lệch khớp lệnh của đúng feed, không gọi là tổng thị trường.
- Chỉ có Bid/Ask: CVD tick-direction là proxy số tick tăng/giảm, không phải tiền vào/ra; không được đếm thêm như xác nhận độc lập với giá.
- Profile tick ở giá là phân bố hoạt động của feed; profile phân bổ volume nến theo range còn là xấp xỉ mạnh hơn. Nhãn basis đặt cạnh POC/LVN, không giấu trong phụ lục.
- CVD so trong cùng đoạn reset và coverage. Phân kỳ chỉ dùng swing tương ứng đã xác nhận, không nối qua gap. Không triển khai xác nhận aggression/absorption tại mức giá; không giữ nó thành gate chờ bổ sung dữ liệu ngoài.
- Thiếu flow vẫn trả phân tích giá và giữ nguyên tín hiệu A. Không hạ thiếu thành 0; không loại hoặc hạ eligibility của mã vì thiếu dữ liệu flow tùy chọn.

Phần người dùng gọi “cá mập sẽ làm gì” được thể hiện thành: vùng đáng theo dõi → hai đường giá có thể xảy ra → bằng chứng chọn đường nào → mức bác bỏ. Không gắn người mua/bán cho tổ chức cụ thể hoặc tuyên bố biết ý đồ. Đây là kỷ luật bằng chứng, không phải chứng nhận phương pháp của “trader top thế giới”.

### 5.4 Sức mạnh tương đối và tránh trùng ý tưởng

Sau MVP, thêm bảng biến động chuẩn hóa trên những cửa sổ đã chốt trước, cùng cutoff và đủ history. Ví dụ nghiên cứu ban đầu: biến động 1 giờ/4 giờ chia ATR H1 của mốc đầu cửa sổ; kiểm mẫu số dương, thời điểm biết và số bar trước khi dùng. Chỉ số này đo chuyển động tương đối, không đo vốn dịch chuyển.

Xếp FX theo chiều base/quote, hiển thị thành phần và coverage; chưa gọi thành chỉ số sức mạnh tiền tệ toàn thị trường nếu rổ không đủ. So vàng/chỉ số trong nhóm hợp lý, không cộng bừa vào strength của FX. Các quan hệ liên thị trường là bằng chứng bổ trợ có thể thay đổi, không giả định vàng luôn ngược USD hay các chỉ số luôn đi cùng nhau.

MVP nhóm exposure từ metadata base/quote và loại tài sản, không cắt ký tự tên mã để coi US100/GER40 là tiền tệ. Correlation thực nghiệm chỉ thêm nếu có cùng history đủ sạch. Nhiều lệnh cùng bán USD không được coi là nhiều xác nhận độc lập. Nhóm exposure chỉ cảnh báo tập trung rủi ro; không tự chọn một mã rồi giấu các mã còn lại, không thay luật portfolio/lot.

## 6. Universe mục tiêu, có cả chỉ số

- Kế thừa đợt nền: XAUUSD và EURUSD, USDJPY, GBPUSD, USDCAD, USDCHF, AUDUSD, NZDUSD; mở cross theo danh sách nền khi đủ mapping/cost.
- Bổ sung phạm vi khảo sát của tính năng: US100, US500, GER40 (tên canonical đề xuất; alias thực tế do broker quyết định). Đây chưa phải danh sách đã xác nhận hỗ trợ. Không bỏ phần chỉ số khỏi lộ trình chỉ vì bảng config hiện mới có ba mã.
- Dầu tiếp tục ngoài phạm vi theo yêu cầu đã có. Không thêm crypto. Feed ngoài/trả phí và công cụ phụ thuộc chúng bị loại khỏi kế hoạch này.

Mỗi mã trả riêng khả năng đọc context, có setup, có flow, có execution economics. Mã chưa đủ metadata/history/cost có thể chỉ xem bối cảnh, hoặc báo thiếu; không dùng cost, contract size hay lịch FX cho CFD chỉ số. Không lấy giá futures để làm entry/SL/TP cho CFD. Không được suy A có lợi thế trên chỉ số trước kiểm định riêng.

## 7. Đầu ra người dùng: đầy đủ tín hiệu, gọn phần diễn giải

Hai phần tách biệt:

1. Bảng ngắn TOÀN BỘ tín hiệu A trong phạm vi báo cáo: ID, mã, branch, hướng, eligibility, giờ biết, deadline, trạng thái thực thi và nhãn context. Có đủ số lượng/ID đối chiếu; không bị `top-K`, `max_cards` hay giới hạn ba mã cắt mất. Tín hiệu cũ/blocked nằm ở nhóm riêng với lý do, không trình bày như còn vào được.
2. Bản đồ vùng chờ và phần diễn giải sâu, có thể giới hạn ba mã mỗi lượt để đọc nhanh. Các mã chưa viết sâu giữ nhãn `CONTEXT_PENDING/DEFERRED`, không bị kết luận kém hơn hoặc không có tín hiệu. Mọi tín hiệu A còn hạn vẫn hiện ở phần 1 dù context chưa xong.

Mỗi dòng tổng quan thị trường: mã → trạng thái → hướng có điều kiện → vùng chờ → bằng chứng thuận/nghịch → trạng thái dữ liệu/flow. Không dùng phần trăm thắng, điểm tối thiểu để được hiện, hoặc “độ tin cậy AI”.

Mỗi thẻ chi tiết:

1. Quan sát thực tế và nguồn: giá, vùng, thời điểm, cơ sở volume/flow.
2. Kịch bản ưu tiên và điều phải xuất hiện tiếp theo.
3. Kịch bản ngược; bằng chứng bác bỏ mạnh nhất và mốc đổi bias.
4. Nhãn quan sát: THEO_DÕI_SÁT, CHỜ_VỀ_VÙNG, BỐI_CẢNH_BẤT_LỢI hoặc CHƯA_ĐỦ_CONTEXT; không dùng BỎ_QUA làm phủ quyết A.
5. Readiness riêng từ policy nền: trigger, quote mới, deadline, entry drift, economics/room, trạng thái tài khoản chưa kiểm. “Mã đáng theo dõi” không đồng nghĩa “được vào ngay”; tín hiệu A còn eligibility không đồng nghĩa đã qua kiểm thực thi.
6. Entry/SL/TP chỉ khi trace được về card/analysis gốc còn hợp lệ; vùng mục tiêu tham chiếu phải phân biệt với TP của plan.

Thứ tự bảng A trước hết là deadline/cửa sổ và quy tắc ổn định; không sắp lại quyền vào lệnh của portfolio bằng điểm context. Vùng chờ có thể xếp theo khoảng cách ATR và thời gian còn lại, giữ đầy đủ nguồn/giới hạn. Room, cost và nhóm exposure được trình bày nhưng không thành gate mới. Không trộn UNKNOWN với giá trị đã biết thành điểm tổng; không nâng thiếu phí thành thực thi an toàn. Kịch bản bất lợi là thông tin cần xem, không tự xóa/giấu candidate.

Nhận định tự do của agent lưu riêng khỏi feature máy. Mỗi nhận định phải trỏ tới feature/level ID cùng snapshot, nêu rõ suy luận và dữ kiện chống lại. Lớp trình bày không được ghi đè gate, kéo dài expiry hoặc bịa con số.

## 8. Cách vận hành được thiết kế, không phải lịch chạy đã bật

Đầu phiên người dùng gọi: bảng A đầy đủ trước, tổng quan toàn rổ và vùng chờ sau. Những lần gọi sau, thường cách 20 phút: cập nhật thay đổi, giữ/hủy/thay kịch bản bối cảnh có lý do; không thay lifecycle A ngoài rule gốc. Liên kết snapshot cũ/mới, không trộn số liệu hai lần quét trong một nhận định.

Khi người dùng yêu cầu kiểm một mã sát vùng: lấy snapshot mới qua luồng nền, kiểm trigger/quote/deadline trước kết luận. Baseline hiện có cửa sổ entry 90 giây; quét 20 phút không bảo đảm bắt được. Không kéo dài deadline và không tự bật giám sát nền để che hạn chế này. Thời gian trả lời cũng phải tính vào tuổi tín hiệu.

Không có lời hứa mỗi tối đều có lệnh. Không tự vào lệnh, không chọn risk tiền thật, không khẳng định qua gate FTMO khi chưa có bằng chứng tài khoản.

## 9. Thiết kế phần mềm nhỏ nhất

Tái dùng `reporting.analyze_snapshot`, `analysis_cache` và renderer báo cáo mới; bổ sung các trường context/nhãn và bảng A đầy đủ. Sau kiểm tra đường child JSON, bộ bàn giao 00–03 đã chốt mở rộng CLI tối thiểu: `--analysis-mode baseline` và `session enrich` hữu hạn, để baseline thật sự trả trước optional analysis; không dựng orchestration service riêng. Tách hàm thuần nhỏ chỉ khi phần so sánh/kịch bản không còn phù hợp trong module hiện có. Nhận snapshot, market-context, watch zones, baseline cards và Fabio artifacts cùng nguồn đã tính.

- Thu context cho mọi mã kể cả không có candidate; tái dùng dữ liệu loaded/cache của phiên mới. Không chạy Fabio lần hai nếu cùng snapshot đã có artifact.
- Dữ kiện tối thiểu: snapshot/source/config/engine/branch IDs, as-of, baseline-ready/published và context-ready timestamps; symbol status; feature/zone refs; flow basis/coverage/reset; scenario/invalidation; candidate/analysis/episode refs; ba trạng thái ở mục 3.1; deadline/economics; lý do thứ tự; news user-managed.
- Lưu JSON + Markdown trong output phiên, nối journal hiện có, không tạo database, scheduler, model train hoặc hệ thống log thứ hai.
- Dẫn chứng/nhãn toàn bộ A và quyết định thủ công nếu có cần commit trước session finish. Tick có thể bị xóa theo chính sách nền; báo cáo dẫn xuất không cho phép tái dựng exact tick replay. Outcome chưa biết giữ censored/pending, không tự tính thắng/thua.

Điểm nối cần xử lý sau khi nền chốt: `session.py` hiện render candidate bị giới hạn `max_cards`; giới hạn này chỉ được áp cho phân tích sâu, không cho bảng A. `paper.py` hiện chờ Fabio rồi mới hoàn tất batch/report; lỗi hoặc thời gian xử lý optional không được giữ lại báo A.

Thiết kế hai bước hữu hạn trên cùng snapshot: trả/lưu bảng A đã qua các kiểm nền trước; sau đó bổ sung context trong time budget đo được. Nếu optional lỗi/chậm thì context pending/unavailable, không hạ baseline thành lỗi chung hoặc ép chờ. Không chỉ ghi file sớm mà vẫn giữ lời đáp đến hết phân tích: phải đo thời điểm người dùng thực sự nhận được bảng A. Giữ lỗi integrity/nguồn cần cho chính A là lỗi nền; không đổi nhãn để bỏ qua kiểm an toàn. Không thêm daemon/scheduler; bài kiểm phải chứng minh enrichment không làm một A còn hạn trở thành đến muộn.

## 10. Lộ trình bàn giao từng bước

| Mốc | Sản phẩm | Điều kiện xong |
|---|---|---|
| 0 — lượt này | Chốt A H1/M5, MT5-only và hợp đồng không thêm bộ lọc | Đọc lại chat/spec/code; cập nhật kế hoạch, không chạy live |
| 1 — bảo toàn A trước | Ghim baseline theo branch; bảng A đầy đủ, baseline trả trước context | Không mất ID/eligibility/fill; hơn ba tín hiệu vẫn đủ; optional lỗi không chặn |
| 2 — bối cảnh có sẵn | H1/M5/D1, vùng A, ATR/RVOL, profile/CVD có nhãn, kịch bản thuận/nghịch | Tất cả chỉ bổ trợ; bật/tắt context không đổi A hoặc giá kế hoạch |
| 3 — bổ sung phần thiếu | Biên phiên, strength, exposure và chỉ số đủ dữ liệu MT5 | Causal/cùng cutoff; không thêm gate hay ngưỡng điểm; mã mới kiểm riêng |
| 4 — nghiệm thu demo | Ghép quét/kiểm mã/report/kết phiên với nâng cấp nền | Đo delivery/latency và tỷ lệ giữ tín hiệu; không mất cơ hội do context |
| 5 — nghiên cứu giá trị thông tin | Outcome theo nhãn bối cảnh đã ghi trước, quyết định thủ công tách riêng | Không tự đưa nhãn thành bộ lọc; chưa hứa tăng winrate |

Không cần đợi chứng minh lợi nhuận mới dùng bản báo cáo kỹ thuật; nhưng không gọi thêm thông tin là đã cải thiện lợi nhuận. Các mốc đầu dùng mã đã đủ nguồn; mốc 3 không chứng nhận A có lợi thế trên chỉ số. Nếu phát hiện một nhãn có ích, trước hết kiểm ngoài mẫu như giả thuyết; không tự kích hoạt gate mới trong MVP giữ tần suất này.

## 11. Kiểm thử và cách biết tính năng có ích

Kiểm thử tối thiểu cho phần code sau này:

- No-candidate vẫn có context; một mã lỗi không làm mất kết quả các mã khác; requested = reported, gồm cả missing/excluded/deferred. Trên ba A cùng lúc phải hiện đủ ID trong bảng chính; không chỉ báo số thẻ bị hoãn.
- Snapshot/config/source mismatch bị chặn; future-known/provisional không trở thành trigger. Thêm bar tương lai không làm đổi kết quả tại cutoff cũ.
- Dữ liệu/quote cốt lõi của A stale, market closed, expiry hoặc cost unknown không thể được nâng thành entry-ready; closed khác lỗi thiếu dữ liệu. Context tùy chọn thiếu, stale/trái chiều hoặc Fabio WAIT không thay eligibility/safety state của A.
- Proxy/approximation phải hiện trong JSON và Markdown; không được phát biểu đã xác nhận dòng tiền tổ chức/absorption bằng quote-direction.
- Vùng A giữ nguyên ID/anchor; entry/SL/TP baseline bất biến. Không có card baseline hoặc analysis Fabio hợp lệ chứa mức giá có nguồn thì plan null; Fabio không được giả làm candidate A/B.
- Cùng input/config/as-of cho cùng thứ tự máy; mỗi kịch bản có phản chứng; các phiên bản suy luận agent được lưu riêng.
- Bật/tắt context, inject optional exception/timeout, thiếu CVD/profile, RSI/ADX trái chiều: baseline packet vẫn đầy đủ và được trả trước; baseline safety không bị optional fail kéo thành blocked. Kiểm thời gian delivery thật, không chỉ mtime báo cáo.
- Session DST, ngày chuyển tuần, gap, vùng chưa hoàn tất và clock unverified đều có ca kiểm; strength kiểm base/quote, cutoff, mẫu số và coverage.
- Một cơ hội qua nhiều lần quét chỉ là một mẫu; biến thể A không tăng số cơ hội độc lập; có log mọi A, lần được báo và quyết định thủ công/không kịp thấy nếu biết.
- News user-managed không chặn bản phân tích kỹ thuật và không được biến thành “đã kiểm tin”.
- Report/evidence được lưu trước dọn tick; không báo outcome chính xác khi đường giá đã thiếu hoặc bị purge.

Nối tiếp test hiện có: `test_snapshot_notes.py`, `test_runtime_fabio_integration.py`, `test_fabio_decision_contract.py`, `test_fabio_mt5_profile.py`, `test_mt5_flow.py`, `test_detectors.py`. Chưa chạy các test trong lượt chỉ thiết kế này.

### 11.1 Nghiệm thu “không giảm tần suất”: so từng cơ hội, không chỉ đếm tổng

Ghim cùng source/tape, universe cũ, branch/version, cutoff, lịch gọi, cost/execution và portfolio policy. So A-only với A+context trên đầu vào giống nhau:

| Tầng | Điều kiện nghiệm thu thiết kế |
|---|---|
| Detector | Tập candidate ID bằng nhau; không thiếu và không tạo thêm A giả |
| Eligibility | Tập ID eligible, gate/reason, anchor/zone, side, entry/SL/TP và deadline bằng nhau |
| Hiển thị | Mọi A cũ đều xuất hiện; `retention_alert = intersection / baseline = 100%` khi baseline > 0 |
| Thời điểm | `late_or_missed_due_to_context = 0` trong kiểm thử ghép đôi; ghi signal/ready/publish/expiry |
| Replay | Cùng tape/policy cho cùng filled/blocked/unresolved, fill/exit time/price, reason và net R |
| Người dùng | Delivered/viewed/entered là các trạng thái khác nhau; không suy đã xem hoặc đã vào khi chưa có bằng chứng |

Baseline không có cơ hội thì retention là N/A; luôn báo số tuyệt đối và ID khác nhau. So theo từng mã cũ × ngày × khung giờ và toàn rổ; mã mới thành cohort riêng. Không dùng thêm alert GBPUSD để bù mất alert EURUSD, không dùng một loss bị lọc hậu nghiệm để chứng minh lớp mới tốt hơn. Tách miss vốn có do nhịp gọi 20 phút/cửa sổ 90 giây khỏi miss mới do enrichment. Baseline là bản nền đã chốt để không quy thay đổi từ chat nâng cấp thành tác động của context.

### 11.2 Nghiên cứu giá trị thông tin sau khi đã giữ được A

Ghi nhãn thuận/nghịch/trung tính/thiếu và lý do trước outcome, không đợi kết quả mới sửa luận điểm. Báo outcome của mọi A theo nhãn, cùng các quyết định thủ công nếu người dùng cung cấp. Báo winrate, net expectancy, lời/lỗ trung bình, tail loss, coverage, chi phí known/assumed và số cơ hội độc lập; chưa dùng khác biệt nhóm làm rule lọc production. Cùng lệnh/thực thi phải cùng kết quả; chỉ gọi cải thiện khi có khác biệt workflow được ghi và kiểm riêng. Chỉ báo drawdown portfolio khi có chronology/exposure thực, không suy từ tổng candidate R.

Tách đo 18–19h, 19–20h, 20–21h và giờ khác theo Việt Nam; không suy khung đẹp từ đúng tuần cũ. Thử từng bổ sung trên giai đoạn mới, có holdout theo thời gian và ghi số biến thể đã thử. Không chọn tham số trên cùng tập rồi báo hiệu quả như ngoài mẫu; không đặt một mốc mẫu nhỏ tùy ý làm chứng nhận edge.

## 12. Nguồn và giới hạn

- MetaQuotes, [MqlTick và flags](https://www.mql5.com/en/book/applications/timeseries/timeseries_ticks_mqltick): trường Last/volume thường trống ở Forex; cần phân biệt tick giá và giao dịch thực. Đây là cơ sở giữ nhãn proxy, không phải bằng chứng một kỹ thuật giao dịch sinh lợi.
- MetaQuotes, [Python Integration](https://www.mql5.com/en/docs/python_metatrader5): API đọc nến/tick/quote/metadata từ terminal. Chỉ sử dụng dữ liệu broker hiện cấp; không yêu cầu nguồn dữ liệu mới ngoài MT5.
- Bằng chứng nội bộ: báo cáo tuần nêu tại mục 3; `context.py`, `fabio.py`, `mt5_flow.py`, `paper.py`, `session.py`, config và tests tại mục 4/11; kế hoạch nền ở cùng thư mục với tài liệu này.

Chưa xác minh broker support hiện tại, chưa có báo cáo live, chưa đo parity/retention/delivery hoặc hiệu quả của tính năng mới. Đây là bản thiết kế để triển khai có thứ tự, không phải kết quả kiểm thử đã đạt hoặc lời khuyên vào một lệnh hiện tại. Revision này chỉ cập nhật tài liệu; các tham chiếu code phản ánh bản nền đang được chat khác sửa và phải kiểm lại trước triển khai.
