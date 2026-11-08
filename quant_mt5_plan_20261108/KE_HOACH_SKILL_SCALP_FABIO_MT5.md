# Kế hoạch skill Scalp Fabio — tái dùng bộ công cụ MT5 hiện có

Ngày lập: 08/11/2026, Asia/Saigon. Trạng thái: **KẾ HOẠCH, CHƯA TRIỂN KHAI SKILL MỚI**.

## 1. Chốt đúng yêu cầu

- Skill đề xuất: `scalp-fabio`, tên hiển thị **Scalp Fabio — MT5**.
- Đây là skill phương pháp scalping theo khung Fabio Valentini, không phải tên khác của `trade-toi` và không phải setup A phá H1.
- `trade-toi` phục vụ quy trình quét ca tối hiện có. `scalp-fabio` phục vụ phương pháp, dùng khi người dùng gọi ở bất kỳ phiên phù hợp nào.
- Tái dùng công cụ dự án; không dựng collector, indicator, database, nền tảng giao dịch hay hệ AI mới.
- Nguồn vận hành chỉ từ MT5 người dùng đã mở. Nguồn đã kiểm trước đây là **MetaQuotes-Demo**. Người dùng xác nhận **chưa từng dùng tài khoản FTMO**; không giả định account, chương trình hoặc luật FTMO hiện tại.
- Không footprint, bubble/tape trả phí, DOM/heatmap, feed ngoài hoặc indicator cần mua. Tin tức do người dùng tự kiểm: `USER_MANAGED`.
- Không tự đặt/check/sửa lệnh, chọn lot, chạy nền, tạo lịch, hoặc train Muse. Mỗi yêu cầu phân tích mới là một lượt hữu hạn.
- Không hứa lợi nhuận 169%, một tỷ lệ thắng, hoặc giữ nguyên số lệnh của một phương pháp khác.

### Giới hạn phải nói ngay

Khung nguồn gồm **trạng thái thị trường → vị trí trên profile → xác nhận dòng lệnh và phản ứng giá**; có mô hình tiếp diễn và mô hình phá vỡ thất bại. [Playbook của bên phát hành](https://www.chartfanatics.com/strategies/auction-market-strategy).

Với nguồn quote-only đang có, sản phẩm triển khai sẽ là **bản thích nghi MT5 của khung Fabio**, không phải bản sao đầy đủ hệ order flow trong video. Khi MT5 không có giao dịch/volume/side hợp lệ, skill vẫn đọc cấu trúc giá và vùng nhưng phải ghi rõ thiếu xác nhận flow thực. Không đổi tên tick-direction thành khối lượng mua/bán thực để lấp khoảng trống.

## 2. Phân biệt ba lớp để không lẫn chiến lược

| Lớp | Vai trò | Quan hệ với skill mới |
|---|---|---|
| Công cụ chung `quant_mt5` | Thu MT5, snapshot, kiểm dữ liệu, chỉ số, phân tích, lưu báo cáo | Tái dùng |
| `trade-toi` + baseline A/B | Quy trình ca tối và các chiến lược baseline hiện có | Giữ nguyên hành vi; không bị Fabio phủ quyết |
| `scalp-fabio` | Nhận diện/giải thích F1, F2 theo bằng chứng hiện có | Skill riêng, sổ cơ hội riêng, không phụ thuộc có tín hiệu A |

Nếu sau này người dùng gọi “trade tối theo Fabio”, dùng chung một snapshot và trình bày rõ từng phương pháp. Không tự đổi A thành F1, không nhân đôi lượt thu dữ liệu và không cộng một ý tưởng thành nhiều lệnh.

## 3. Những gì đã có và cách tái dùng

Các đường dẫn dưới đây tính từ `D:/trading thử lần cuối cuối/`.

| Thành phần đã kiểm | Tái dùng như thế nào | Không được suy rộng |
|---|---|---|
| `quant_mt5/quant.cmd` | CLI đang cài, dùng Python 3.13 sẵn có | Không cần runtime/ngôn ngữ mới |
| `quantmt5/collector.py`, `source_bundle.py`, `snapshot.py`, `data.py` trong `quant_mt5/` | Thu nến/tick, định danh nguồn, ghim dữ liệu, đọc đúng as-of | Không mở account mới hoặc trộn nguồn |
| `quantmt5/session.py`, `paper.py` | Một lượt thu và phân tích; Fabio đã chạy khi A không có candidate | Không cần viết scheduler/collector riêng |
| `quantmt5/mt5_flow.py` | CVD từ trade flags/volume nếu đủ; nếu không thì midpoint +1/−1/0; quote và dữ liệu profile | Chưa có local aggression theo mức giá; không tự có phí thực |
| `quantmt5/fabio.py` | F1/F2, balance, value area, LVN/POC, phản ứng giá, economics, report | Đây là số hóa của dự án, chưa phải chiến lược đã chứng minh |
| `quantmt5/features.py`, `context.py`, `analysis_cache.py` | ATR, context và cache hiện có | Không chồng EMA/RSI/ADX thành bộ lọc bắt buộc mới |
| `quantmt5/replay.py`, `execution.py` | Bộ đọc tick đã ghim, mô hình quote, làm tròn tick và các phần xử lý khớp/thoát có thể tái dùng | `quant replay` hiện chỉ nhận candidate A/B; chưa replay Fabio trực tiếp |
| `quantmt5/notes.py`, report/journal hiện tại | Lưu quan sát và báo cáo; Fabio dùng observation | Không giả candidate A để ghi note/replay Fabio |
| `runtime/on_demand/weekly_fabio_20261102_08/weekly_trial.py` | Tham khảo cách chạy theo từng prefix M5 | Script hiện đếm trigger Fabio, không tạo P&L Fabio |
| Sáu nhóm test Fabio hiện có | Mở rộng test theo đúng module, không tạo test framework mới | Test phần mềm không xác nhận lợi nhuận |
| `scripts/fabio_orderflow_core.py`, `replay_fabio_orderflow.py`, indicator lab cũ | Tham khảo định nghĩa, fixture và bài học kiểm định | Không nối thẳng vào quote-only: chúng có giả định futures, size/side và ngưỡng hợp đồng |

Không sửa kho `staged`, bản nghiệm thu cũ hoặc ZIP để biến chúng thành runtime. Không đưa Muse vào phiên bản đầu: harness nghiên cứu có contract riêng, không phải adapter Fabio đã cài.

## 4. Khoảng cách giữa code hiện tại và skill mong muốn

1. **Thiếu skill chuyên biệt:** Fabio đang nằm trong skill MT5 tổng quát; cần một lối gọi và cách trả kết quả riêng.
2. **Kết luận WAIT quá gộp:** có thể đã xuất hiện cấu trúc/trigger nhưng thiếu chi phí. Cần trình bày hai trạng thái, không giấu cơ hội cũng không nâng thành lệnh hợp lệ.
3. **Định danh:** `analysis_id` hiện gắn snapshot, chưa phải ID một cơ hội xuyên nhiều lượt quét.
4. **Vòng đời vùng:** mỗi snapshot chọn balance/nhịp giá tại as-of. Điều này chưa tự chứng minh repaint, nhưng chưa đủ hợp đồng để theo dõi một cơ hội có vùng đã đóng băng. Phải kiểm tính nhân quả theo chuỗi.
5. **Mục tiêu F1:** hiện dùng high/low D1 hoàn tất trước đó nếu ở phía có lợi. Đây là lựa chọn dự án, không được trình bày như đã tái tạo mục tiêu profile của nguồn.
6. **Entry M1:** code hiện dùng M5; phần timing M1 trong video chưa triển khai.
7. **Replay F1/F2:** chưa có adapter phù hợp SL cấu trúc/target profile. Simulator A/B hiện có giả định entry/SL/TP riêng.
8. **Chi phí:** adapter tự động đang để commission/slippage là UNKNOWN. Chưa có số đo thì không coi 0 là chi phí thật.

## 5. Khóa phương pháp trước khi sửa code

### 5.1. Bộ quy tắc nguồn và bộ quy tắc máy phải tách biệt

Nguồn được đối chiếu trong `reports/20261108_video_strategy/BAO_CAO_NGHIEN_CUU_FABIO_FTMO_20261108.md`, gồm mốc video, bản dịch và các chỗ chưa xác minh. Không cần nghiên cứu lại từ đầu.

Người triển khai lập bảng `source principle → rule máy → dữ liệu cần → điểm khác nguồn → test`. Không gắn ngưỡng tự chọn với tên Fabio.

Các tham số đang có trong spec 1.1.0 cần lưu thành mốc đối chiếu:

| Nhóm | Giá trị hiện có — KHÔNG phải ngưỡng đã tối ưu |
|---|---|
| Khung/history | M5; ít nhất 120 bars |
| Balance | 24 M5, range tối đa 3,5 ATR; tìm trong 150 bars |
| Profile | Value area 70%; bin 0,125 ATR |
| Acceptance/failure | 2 closes; cửa sổ failure 6 bars |
| Pullback/LVN | Pullback ít nhất 0,5 ATR; LVN ≤ 0,5 median bin dương; ít nhất 4 bin hợp lệ |
| Vị trí/trigger | Tolerance 0,25 ATR; freshness 2 M5; response window 3 bars |
| SL/room | Buffer 0,1 ATR; min net room 1,5R |
| CVD/coverage | Slope 6 bars; coverage 0,9 trên 24 bars; reset ngày UTC và gap |
| Quote | Max age 120 giây; max deviation 1 ATR |

Giữ chúng cho mốc nghiên cứu ban đầu, không tinh chỉnh đồng thời để tìm kết quả đẹp. Quote age 120 giây là giá trị code hiện tại, **không phải chứng nhận đủ nhanh cho scalp**; đo độ trễ và đăng ký ngưỡng phù hợp trước thử prospective.

### 5.2. F1 — tiếp diễn sau khi rời cân bằng

Diễn giải khung: rời balance → nhịp đẩy → hồi về LVN của nhịp → xác nhận. F1 và F2 xuất phát từ [playbook nguồn](https://www.chartfanatics.com/strategies/auction-market-strategy); phần cơ giới hóa bên dưới là thiết kế dự án.

Thứ tự máy cần kiểm:

1. Chọn balance chỉ bằng dữ liệu đã có trước sự kiện breakout; lưu biên, POC/VAH/VAL, ATR và timestamps.
2. Kiểm acceptance theo spec hiện tại; wick đơn lẻ không được tự nâng thành acceptance.
3. Theo dõi impulse và xác định thời điểm kết thúc nhịp **có thể biết được**, không tìm đỉnh cuối cùng bằng dữ liệu tương lai.
4. Tạo profile nhịp bằng module có sẵn; ghi rõ tick-activity hay executed-volume, vùng đủ coverage hay bar fallback.
5. Chờ touch vùng và trigger giá đủ điều kiện; hướng SELL là đối xứng BUY, không viết hai quy trình lệch nhau.
6. Đọc CVD/proxy làm thông tin bổ sung; bản thích nghi price-response không bắt buộc proxy đồng thuận.
7. Kiểm vô hiệu, expiry, mục tiêu đã biết, quote và phí. Chỉ có vùng chờ thì không bịa entry/SL/TP hoàn chỉnh.

**Mục tiêu cần sửa có phiên bản:** giữ D1-target cũ làm `legacy` đối chiếu. Bản profile-target chọn vùng/POC đã biết và nằm phía có lợi trước entry. Phải chốt thuật toán chọn reference profile, độ cũ tối đa và thứ tự chọn trước xem outcome. Nếu nguồn không đủ để chốt một quy tắc duy nhất, ghi lựa chọn là adaptation; thiếu target thì giữ UNKNOWN, không lấy POC hình thành sau lệnh hoặc âm thầm fallback sang D1.

### 5.3. F2 — phá vỡ thất bại, quay lại balance

Thứ tự cần kiểm: balance đã biết → thử breakout → close reclaim → nhịp hồi/test **sau reclaim** → trigger; target là POC của balance đã khóa và phải nằm phía có lợi.

- Không dùng ngay nến reclaim làm cả reclaim, later-pullback và trigger.
- Profile nhịp reclaim không được mở rộng ngược bằng những nến xuất hiện sau quyết định.
- Nếu breakout tiếp diễn và bác bỏ reclaim, ghi INVALIDATED; không đổi luận điểm để giữ cùng cơ hội sống.
- Không giả định cứ chạm lần hai là tốt. Điều kiện test và phản ứng phải thể hiện được bằng dữ liệu.

### 5.4. Tính nhân quả và vùng đóng băng

Đề xuất cơ chế cần chốt/kiểm ở giai đoạn P2:

- Balance được khóa khi episode breakout được nhận diện, từ cửa sổ đã tồn tại trước breakout.
- F1: dùng lần pullback đủ ngưỡng đã xác nhận làm thời điểm khóa nhịp impulse; `anchor_end` có thể ở trước, nhưng `known_at` không được lùi về đỉnh.
- F2: xác định nhịp reclaim bằng chuỗi sự kiện đã khóa; profile phải biết trước trigger later-pullback.
- Touch xảy ra trước khi vùng thật sự được biết không được tính như một entry có thể thực hiện. Trường hợp cùng nến chỉ dùng được nếu thứ tự tick chứng minh; nếu không thì chờ sự kiện kế tiếp.
- Có cực trị mới sau khi khóa: chuyển trạng thái hoặc tạo revision có thời điểm rõ; không ghi đè vùng/nhận định cũ.
- Nếu quy tắc khóa thay đổi detector so với 1.1.0, tăng spec version và ghi rõ đây là thay đổi phương pháp. Không gọi mọi khác biệt là “sửa lỗi”.

### 5.5. Hai lớp trạng thái

| Lớp đề xuất | Ví dụ | Ý nghĩa |
|---|---|---|
| `setup_stage` | NO_STRUCTURE, WAIT_LOCATION, WAIT_TRIGGER, TRIGGER_OBSERVED, INVALIDATED, EXPIRED | Cấu trúc giá đang tới đâu |
| `execution_readiness` | DATA_MISSING, COST_UNKNOWN, QUOTE_STALE, READY_FOR_REVIEW | Khả năng kiểm kế hoạch thực thi |

Tên/schema mới là **đề xuất**, chưa có trong CLI. Phải giữ trường decision cũ tương thích; missing cost vẫn không được ENTER. Ví dụ báo người dùng: “F2 đã có trigger; phí chưa xác minh; chỉ là cơ hội nghiên cứu”.

`READY_FOR_REVIEW` không phải lệnh broker, không chứng nhận tài khoản, không phải cam kết giá còn vào được sau khi AI viết xong. Mọi thời hạn tính từ sự kiện gốc; quét lại không gia hạn.

## 6. Dữ liệu: dùng gì, kiểm gì

### Dữ liệu chính

- M5 cho state/trigger phiên bản đầu; H1/D1 chỉ context/reference đúng contract; M1 dành cho nghiên cứu timing sau.
- Tick Bid/Ask, event time, available time, flags, last/volume nếu broker có.
- Metadata từng symbol: chart basis, digits/tick size, contract/tick value nếu cần quy đổi, lịch/clock đã xác minh, mapping canonical/native.
- Mỗi output giữ snapshot, bundle, source fingerprint, spec hash, coverage và known_at. Không lộ login đầy đủ trong báo cáo.

### Kiểm chất lượng trên từng mã

1. Đúng nguồn/terminal demo được người dùng chọn; không gọi FTMO chỉ vì biến legacy có tiền tố FTMO.
2. Nến đóng, OHLC hợp lệ, đủ warmup và không dùng bar tương lai.
3. Tick có Bid > 0, Ask ≥ Bid, timestamp có thứ tự/clock rõ; kiểm gap/duplicate bằng chính sách sẵn có, không xóa nhầm tick cùng millisecond.
4. Kiểm integrity và coverage toàn cửa sổ profile/trigger, không lấy coverage CVD thay coverage profile.
5. Chỉ phân loại executed khi trade events có price/volume/side hợp lệ; bất định thì proxy/unavailable đúng adapter.
6. Profile fallback có nhãn ngay cạnh vùng LVN/POC, không giấu trong phụ lục.
7. CVD không nối qua reset/gap; swing divergence chỉ dùng swing đã xác nhận trước quyết định.

MT5 có các trường trade nhưng không bảo đảm mọi symbol có chúng; Forex thường thiếu last/volume/side. [MetaQuotes](https://www.mql5.com/en/book/applications/timeseries/timeseries_ticks_mqltick). Không cần mua indicator để kiểm khả năng nguồn.

### Chi phí: không biến việc chưa trade thành điều kiện phải mua tài khoản

- Spread lấy từ Bid/Ask hiện có. Không trừ spread lần hai khi đã dùng giá khớp hai phía.
- Commission/slippage chưa biết: phân tích cấu trúc vẫn chạy; readiness/cost giữ UNKNOWN.
- Nếu sau này có lịch sử giao dịch đúng nguồn và người dùng yêu cầu đánh giá phí: có thể đọc `history_deals_get`, ghép entry/exit, commission/fee/swap, partial fills và đơn vị quy đổi. Đây là lịch sử của tài khoản, **không phải tape toàn thị trường**. [API MetaQuotes](https://www.mql5.com/en/docs/python_metatrader5/mt5historydealsget_py).
- Không có lịch sử thì không tự đặt lệnh để đo. Trượt giá cần giá tham chiếu/giá yêu cầu và fill tương ứng; không suy từ spread hoặc chỉ một giá deal.
- Replay có thể dùng kịch bản phí giả định được khai báo trước, gắn `ASSUMED`. Không chuyển kịch bản đó thành `KNOWN` cho vận hành, không bê phí demo sang broker khác.
- Chi phí thực chưa đủ thì báo diễn biến giá/gross hoặc sensitivity riêng; kết quả net xác minh vẫn UNKNOWN.

## 7. Hợp đồng cơ hội và replay — chỉ bổ sung phần còn thiếu

### Định danh

`opportunity_id` đề xuất dựa trên source fingerprint + symbol + spec + family + side + balance/leg event timestamps cố định. Không đưa snapshot mới nhất hoặc chỉ số vị trí mảng vào key.

Tách `analysis_id`, `opportunity_id`, `revision_id`, `trigger_id`. Một cơ hội được thấy 5 lần không thành 5 mẫu. Nếu F1/F2 hoặc hai mã có exposure liên quan thì không tự cộng thành portfolio độc lập.

Tận dụng immutable JSON, stable_id, journal và store đã có; thêm ledger Fabio tối thiểu. Không xây database/event bus mới. Event mới nối tiếp, không sửa artifact cũ.

### Replay đề xuất

1. Đầu vào là plan Fabio có trigger known_at, entry window, SL cấu trúc, target cố định, expiry, phiên/spec/source và giả định phí/latency rõ.
2. Tái dùng pinned tick loader và QuoteModel. Không gọi `quant replay` với ID Fabio vì command hiện chưa hỗ trợ.
3. Viết adapter nhỏ cho plan Fabio; dùng lại phần đi qua quote/stop/exit phù hợp. Nếu phải tách helper chung, giữ wrapper A/B nguyên semantics và kiểm parity.
4. Không gọi simulator baseline rồi để nó tự thay SL bằng signal-bar low/high hoặc thay POC bằng TP cố định 1,5R.
5. Fill ở quote đầu tiên hợp lệ sau known_at + latency; không chọn quote đẹp, không cho variant chờ CVD nhận entry sớm của đối chứng.
6. BUY/SELL và phía giá kiểm SL/TP phải đúng; gap qua stop có thể lỗ hơn 1R. Không bỏ lệnh gap sau khi thấy kết quả.
7. Hạn entry dùng event Fabio, không vô tình lấy 90 giây của A; quy tắc max hold/exit chưa có phải được chốt trước kiểm định, không tự coi 60 phút baseline là quy tắc Fabio.
8. Tick thiếu đoạn entry hoặc exit: UNRESOLVED/CENSORED; không tự cho thắng, không dùng nội suy M1 rồi gọi tick-exact.
9. Lưu cả no-fill, expired, skipped, missing và zero-trade sessions. Ledger Fabio riêng, không sửa catalogue A/B.

## 8. Các giai đoạn triển khai, đầu ra và điều kiện qua bước

### P0 — Kiểm kê, sao lưu và khóa đối chứng

**Làm:** đọc AGENTS nếu có; kiểm thay đổi người dùng; ghi hash các file sẽ chạm, config, skill cũ và bộ artifact nhỏ đại diện. Workspace hiện không được nhận diện là Git repository nên không dựa vào git reset/checkout để phục hồi. Sao lưu đúng file vào thư mục attempt riêng, không copy cả kho tick.

**Dùng:** CLI help, file/hash utility, fixture và report hiện có. Kiểm phiên đang pin engine nào; không sửa hash phiên cũ.

**Đầu ra:** inventory, source manifest, danh sách test/failure nền và bảng source-vs-code. **Qua bước:** biết rõ runtime dùng thật; chỉ test offline, không cần mở MT5.

**Chốt đường chọn phiên bản ngay tại P0:** caller/phiên hiện có mặc định giữ policy legacy 1.1.0. Skill mới sau P3 phải chọn policy mới tường minh bằng một trường cấu hình phiên đã ghim hoặc option CLI tối thiểu được triển khai và kiểm help. Chọn một cách phù hợp code hiện tại, không xây plugin registry mới. Artifact phải trả spec/version/hash khớp policy yêu cầu; không đúng thì báo mismatch, không diễn giải legacy như bản mới.

### P1 — Skill nghiên cứu riêng, chạy được trên artifact hiện có

**Làm:** tạo bản staged `scalp-fabio`; đọc kết quả `fabio`/batch hiện có, không viết detector mới. Nội dung nêu rõ M5 adaptation, chưa có M1 và target legacy khi dùng output 1.1.0.

**Cấu trúc tối thiểu đề xuất:**

```text
scalp-fabio/
  SKILL.md                 mục đích, routing, workflow, giới hạn
  agents/openai.yaml       tên hiển thị và prompt gọi
  references/method.md     F1/F2, khác biệt nguồn và dữ liệu
  references/runtime.md    lệnh thực tế, IDs, đọc/lưu kết quả
```

Không thêm scripts nếu CLI đã làm được. Chọn metadata đủ phân biệt với `trade-toi`; cho phép khám phá tự nhiên, không cấu hình explicit-only nếu người dùng không yêu cầu. [OpenAI Docs về skills](https://developers.openai.com/plugins/concepts/skills).

**Output:** báo cáo F1/F2 độc lập dù A không có lệnh; giữ hết mã và cơ hội, giới hạn chỉ phần diễn giải sâu. **Qua bước:** validation schema và bài test hành vi artifact-only đạt; chưa gọi là đã có edge hay tái tạo đủ video.

### P2 — Bổ sung trạng thái, identity và vòng đời vùng

**Làm:** mở rộng `fabio.py` và phần summary/render thực sự dùng nó; bổ sung setup_stage/readiness, stable ID, event/revision/known_at. Tái dùng journal/util; chỉ tách module lifecycle nếu kích thước thực tế cần.

Nối lựa chọn policy đã chốt ở P0 qua config/bundle → caller batch hoặc CLI → `run_for_snapshot` → phân tích → artifact. Cache key/identity có spec hash; không dùng cache legacy cho policy mới. Phiên mới pin engine/config mới; phiên cũ không được sửa hash để tiếp tục giả tương thích.

**Test trước:** cùng snapshot lặp; snapshot nối tiếp cùng episode; thêm dữ liệu tương lai nhưng cutoff T; balance/target không sửa lịch sử; expiry không reset.

**Qua bước:** cơ hội được nhận diện một lần, lịch sử quyết định bất biến, không tự đổi A/B hoặc phiên cũ. Nếu sửa định nghĩa vùng, phải tăng spec version.

### P3 — Hoàn thiện bản M5 theo khung nguồn

**Làm:** xử lý khác biệt F1 target; kiểm F2 later-pullback; rà SL, quote-side, room và giá trị target đã biết. Chốt thuật toán target/expiry/max-hold trong spec trước chạy outcome. Không bê mức risk/20–30 hợp đồng từ video sang CFD.

**Qua bước:** long/short F1/F2 có fixture độc lập; no-target vẫn thấy cấu trúc; proxy chỉ advisory ở bản giá. Không đồng thời tối ưu CVD, SL, exit và khung giờ.

### P4 — Adapter replay Fabio tái dùng hạ tầng

**Làm:** thêm module dự kiến `quantmt5/fabio_replay.py` hoặc adapter nhỏ theo cấu trúc dự án; chỉ thêm CLI nếu cần cho chạy lặp hữu hạn/kiểm nghiệm. Đây là module/CLI **chưa tồn tại**, không ghi vào skill như lệnh đã chạy được trước khi có help và test.

**Qua bước:** oracle nhỏ tính tay đúng Bid/Ask, costs, stop/target, gap, late fill và missing; replay kết quả lặp ổn định; A/B parity không đổi.

### P5 — Nghiệm thu phần mềm và cài skill

**Làm:** chạy nhóm test hiện có + tests mới; kiểm output qua CLI, không chỉ gọi hàm; test routing với agent độc lập. Chỉ cài `C:/Users/ductr/.codex/skills/scalp-fabio/` sau khi bản staged đạt. Nếu file/skill đã tồn tại, đọc và cập nhật có backup, không đè mù.

**Tương thích:** artifact/schema cũ còn đọc được. Nếu đổi engine/spec ảnh hưởng caller cũ, phải giữ đường legacy hoặc policy opt-in cho skill mới; không thay ngầm nhãn quyết định trong trade-toi. Sửa tối thiểu tài liệu/routing liên quan chỉ khi có xung đột đã chứng minh.

**Qua bước:** người dùng có thể gọi skill đọc snapshot hoặc yêu cầu phân tích mới; không cần FTMO. Ghi rõ cấp nghiệm thu là SOFTWARE/RESEARCH, không LIVE_TRADING_APPROVED.

### P6 — Pilot MT5 demo, khi người dùng yêu cầu chạy

**Làm:** readiness/preflight; thử một mã đã có mapping, rồi 3 mã đã kiểm XAUUSD/EURUSD/USDJPY; sau đó dùng main8 nếu metadata/coverage phù hợp. Không mặc định chỉ số chứng khoán đã hỗ trợ vì broker có tên symbol.

**Cách gọi:** một lượt mới theo yêu cầu, phân tích cùng snapshot. Khung giờ chỉ là metadata phân tích; không hard gate buổi tối hoặc ép quy tắc London/NY của futures lên FX.

**Đo:** thời gian cold/warm, quote age, coverage, số lần fail, số cơ hội bị lỡ do nhịp gọi, tính nhất quán báo cáo. 20 phiên là mốc pilot đề xuất, không bảo đảm đủ mẫu lợi nhuận.

**Qua bước:** vận hành tái lập, nhận diện nguồn đúng, không bịa flow/chi phí. Lịch sử thiếu thì báo thiếu, không tải nguồn ngoài.

### P7 — Kiểm định và entry M1

Chỉ sau khi P2–P4 đạt, mở thử nghiệm M1 riêng: giữ state/location/target M5 đã đóng băng, tìm trigger trên M1 hoàn tất, entry sau known_at thực. Không giả lập một M1 đã xảy ra trước khi vùng M5 được biết.

So M5 và M1 trên cùng tập cơ hội; SL/exit protocol và cost giữ thống nhất để cô lập tác dụng timing. Nếu dùng SL M1 khác, đó là thí nghiệm khác, không gộp lợi ích vào timing.

Sau timing mới cân nhắc một biến thể bảo vệ/thoát sớm. Không dời SL chỉ vì proxy CVD, không nới SL, không chọn trailing sau khi xem vài lệnh thắng. Chưa đủ bằng chứng thì giữ M5 và ghi M1 thử nghiệm.

## 9. Cách vận hành dự kiến của skill

### Người dùng đưa report/snapshot sẵn

Chỉ đọc artifact đúng nguồn/as-of; không readiness, collect, quét lại hoặc dọn tick. Ghi HISTORICAL/SYNTHETIC nếu có. Không dùng dữ liệu hiện tại để giải thích lại một quyết định quá khứ.

### Người dùng yêu cầu phân tích mới

1. Dùng đúng terminal/demo đã mở và universe họ chọn; thiếu nguồn thì báo PENDING, không tự mở/đăng nhập.
2. Ưu tiên một `session once` full của phiên ghim engine và policy Fabio phù hợp; Fabio đã có trong batch. P1 dùng legacy có nhãn; sau P3 skill yêu cầu đúng policy mới và kiểm spec/hash trả về. Nếu đang tiếp tục cycle baseline-PENDING, dùng `session enrich` đúng continuation thay vì thu lại.
3. Đọc Fabio artifact mỗi symbol từ cùng bundle/store/snapshot. Chỉ gọi `fabio` riêng nếu chưa có artifact, không tính lại vô ích.
4. Báo ngay vùng/cơ hội và trạng thái; không đợi mọi chỉ báo tùy chọn đồng thuận.
5. Lưu observation/báo cáo. Không tự theo dõi hay xử lý lệnh sau khi kết thúc lượt.

Lệnh có thật đã kiểm help ngày lập kế hoạch:

```powershell
# Chỉ là mẫu vận hành tương lai. Thay placeholders bằng output thật cùng lượt.
$env:QUANTMT5_CONFIG_DIR = '<bundle-config-dir>'
$env:QUANTMT5_STORE = '<store-cua-phien>'
& 'D:/trading thử lần cuối cuối/quant_mt5/quant.cmd' fabio --snapshot '<snapshot-id>' --symbol XAUUSD --report '<bao-cao.md>'
```

Không truyền `--flow`/`--exec` như cách bù dữ liệu live; hai option đó là chẩn đoán offline. Không bịa `replay --fabio` hoặc lệnh M1.

Mẫu lệnh trên là CLI **hiện tại**, chưa có option chọn policy mới. Sau P2/P3, người triển khai phải cập nhật runbook bằng cú pháp thực sự đã thêm/kiểm help hoặc cấu hình bundle mới; không bỏ qua bước chọn policy chỉ vì lệnh legacy vẫn chạy được.

### Mẫu trả kết quả

```text
Nguồn/as-of: ... | M5 hay M1 nghiên cứu | profile/CVD basis: ...
Mã | F1/F2 | Hướng | Giai đoạn cấu trúc | Vùng chờ | Readiness | Hết hạn

Với từng cơ hội:
- Dữ kiện đã quan sát và vùng neo đã biết.
- Điều cần xảy ra tiếp; không có trigger thì chỉ là watch zone.
- Bằng chứng phản đối mạnh nhất và điều kiện hủy.
- Entry/SL/target từ engine nếu có; phần thiếu ghi rõ, không AI tự đặt giá.
- CVD đang đo gì; nếu proxy không gọi đó là cá mập/hấp thụ xác nhận.
- ID và link bằng chứng; tin tức do người dùng tự kiểm.
```

## 10. Ma trận kiểm thử giao model triển khai

| ID | Ca kiểm | Điều kiện đạt |
|---|---|---|
| D01 | Quote-only | Proxy đúng nhãn, không volume/side giả |
| D02 | Trade flags/volume hợp lệ | Delta đúng trên fixture; chỉ đại diện nguồn đó |
| D03 | Thiếu side, zero/âm/NaN volume | Không lén chuyển thành executed flow |
| D04 | Out-of-order, same-ms ticks | Xử lý đúng contract, không mất event hợp lệ |
| D05 | Gap, reset ngày, coverage thiếu | Không nối CVD qua gap; profile basis riêng |
| D06 | Hash mismatch hoặc pin đã purge | Refuse/unavailable; không đổi sang latest khác |
| P01 | Profile tick đủ coverage | POC/VA/LVN khớp oracle nhỏ, đúng basis Bid/Last |
| P02 | Profile bar fallback | Nhãn approximation rõ, tổng trọng số bảo toàn |
| P03 | Profile sparse/zero/ít bins/tie | Deterministic; UNKNOWN thay vì sinh vùng vô nghĩa |
| F01 | F1 long/short hợp lệ | Chuỗi sự kiện đúng và đối xứng |
| F02 | Wick breakout/chưa acceptance | Chưa nâng thành F1 trigger |
| F03 | Chạm LVN nhưng chưa response | WAIT_TRIGGER, không entry |
| F04 | F1 quay lại balance/bị vô hiệu | Không tiếp tục giữ cơ hội bằng sửa vùng |
| F05 | F2 reclaim và test sau đó | Reclaim bar không đóng hai vai |
| F06 | F2 breakout tiếp diễn | Invalidation có lý do, không giữ bias cũ |
| F07 | POC/target sai phía hoặc chưa biết | Không tạo plan giả/TP phía thua |
| T01 | Prefix T vs dữ liệu dài cutoff T | Cùng output tại T; future không đổi quyết định |
| T02 | Swing xác nhận muộn | known_at đúng; không backdate divergence |
| T03 | Profile/target revisions | Artifact cũ bất biến; chỉ revision mới đổi |
| I01 | Lặp snapshot và nhiều lượt cùng episode | Không tăng số cơ hội/lệnh |
| I02 | Expired rồi quét lại | Không reset hạn entry |
| E01 | Commission/slippage UNKNOWN | Vẫn thấy structure; không READY/ENTER |
| E02 | Long Ask/short Bid và stop-side | Khớp oracle, rounding đúng tick |
| E03 | Spread và commission | Không trừ spread hai lần, đúng đơn vị phí |
| E04 | Late quote, stale, adverse drift | Không vào ở quote sớm/đẹp hơn thực tế |
| E05 | Gap qua SL/SL chạm trước entry | Ghi tail loss hoặc bỏ entry đúng thứ tự |
| E06 | Tape thiếu entry/exit | UNRESOLVED/CENSORED, không tính thắng |
| E07 | Replay Fabio target POC | Không bị simulator A thay thành TP 1,5R |
| C01 | Cùng baseline A/B trước/sau | ID, side, plan, SL/TP, expiry, decision, replay P&L không đổi |
| C02 | Fabio/optional context lỗi | Không giấu A, không collect trùng |
| C03 | Fabio có cấu trúc nhưng không có A | Skill vẫn trả Fabio, không tạo A giả |
| C04 | Legacy caller và caller skill mới | Mỗi đường nhận đúng spec/hash; trade-toi không bị đổi thuật toán ngầm; cache không lẫn policy |
| S01 | Gọi trực tiếp và gọi tự nhiên Fabio | Chọn đúng skill và đúng artifact/CLI |
| S02 | Chỉ gọi trade tối | Không thay chiến lược bằng Fabio |
| S03 | Chỉ hỏi kế hoạch/đọc report | Không gọi MT5 hoặc triển khai ngoài yêu cầu |
| S04 | Dữ liệu proxy/missing/no-signal | Không bịa whales/entry/win probability |
| S05 | Tài khoản chưa phải FTMO | Không giả FTMO account hoặc chặn phân tích vì thiếu nó |
| S06 | Chưa nói lượt cuối | Không finish/purge tick |
| R01 | Cold/warm, 1/3/8 mã cùng workload | Output parity; đo latency/memory, không hứa tốc độ trước đo |

Mở rộng `test_fabio.py`, `test_fabio_flow_contract.py`, `test_fabio_decision_contract.py`, `test_fabio_economics_contract.py`, `test_fabio_mt5_profile.py`, `test_runtime_fabio_integration.py`. Bổ sung lifecycle/replay tests chỉ khi module mới thật sự cần.

Lệnh kiểm nhóm hiện có, chạy sau sửa và trong môi trường offline fixture:

```powershell
Set-Location -LiteralPath 'D:/trading thử lần cuối cuối/quant_mt5'
& 'C:/Users/ductr/AppData/Local/Programs/Python/Python313/python.exe' -m pytest tests/test_fabio.py tests/test_fabio_flow_contract.py tests/test_fabio_decision_contract.py tests/test_fabio_economics_contract.py tests/test_fabio_mt5_profile.py tests/test_runtime_fabio_integration.py -q
& 'C:/Users/ductr/AppData/Local/Programs/Python/Python313/python.exe' 'C:/Users/ductr/.codex/skills/.system/skill-creator/scripts/quick_validate.py' '<staged-scalp-fabio-folder>'
```

Sau test hẹp mới chạy regression runtime/evening/full thích hợp. So failure với baseline tại thời điểm triển khai; không lấy số test cũ làm chứng nhận bản mới. Test cần kiểm hành vi và giá trị, không chỉ tìm chữ trong report.

Agent độc lập nhận skill staged + artifact tối thiểu, không nhận đáp án mong muốn. Kiểm direct invocation, implicit invocation và yêu cầu gần nghĩa không nên kích hoạt. [OpenAI Docs về skill evals](https://developers.openai.com/blog/eval-skills).

## 11. Kiểm hiệu quả và tần suất

### Thử nghiệm ban đầu hữu hạn

- V0: F1/F2 thích nghi MT5 + phản ứng giá; proxy chỉ giải thích.
- V1: cùng cơ hội/exit, thêm điều kiện CVD proxy đã đăng ký; đây là thử nghiệm, không tự bật làm gate vận hành.
- Không chạy nhánh local-aggression khi dữ liệu không có. Có executed CVD từ MT5 thì báo thành nhóm dữ liệu riêng, không trộn với proxy.
- M1 và trailing chưa vào vòng này; mỗi lần thêm là một thí nghiệm versioned, có ngân sách so sánh.

### Dữ liệu và cách tính

1. Tuần 02–08/11 đã được xem kết quả nên là development/exposed, không phải holdout mới.
2. Khóa spec, split thời gian, universe, chi phí, latency và cách xử lý overlap trước xem validation/test.
3. Nhóm theo opportunity; purge/embargo các nhãn có horizon chồng qua ranh giới. Không chia ngẫu nhiên từng tick/variant.
4. Nếu sửa sau xem test, đánh dấu test đã exposed và dùng giai đoạn mới cho xác nhận.
5. Funnel bắt buộc: episode → vùng → trigger → đủ dữ liệu thực thi → fill → outcome. Báo số bị loại, hết hạn, bỏ lỡ và phiên không có lệnh.
6. Báo winrate ròng, payoff, expectancy/trade và/opportunity, PF, drawdown/tail loss, coverage, mức giữ cơ hội và bất định theo block ngày/tuần.
7. Thiếu phí thì tách gross/sensitivity; không chứng nhận net edge. Không gộp các R riêng lẻ thành P&L tài khoản khi chưa mô phỏng portfolio/risk.
8. Không có một số lệnh “thần kỳ” bảo đảm lợi thế. Mốc 20 phiên pilot là quản lý công việc; cần xem cả độ phụ thuộc và độ bất định, không chỉ số dòng.

**Tần suất:** baseline A phải giữ nguyên tuyệt đối trong regression. Fabio là phương pháp riêng nên không thể hứa số lệnh bằng A. Để tránh bóp tần suất không cần thiết, giữ toàn bộ cơ hội cấu trúc và chỉ dùng proxy/indicator làm advisory mặc định; không bỏ điều kiện cốt lõi của F1/F2 để ép có lệnh. Nếu V1 lọc nhiều hơn thì phải báo rõ phần lợi/hại, không chỉ winrate tăng.

## 12. Lưu dữ liệu và bàn giao

- Tái dùng policy giữ báo cáo/nến/journal; không tự xóa raw tick khi chưa có yêu cầu lượt cuối.
- Nếu người dùng yêu cầu dọn cuối ngày, dùng `session finish` hợp lệ sau lưu đầy đủ. Tick đã xóa không thể replay exact; kết quả chưa có đủ đường giá tương lai phải CENSORED.
- Nghiên cứu dài hơn cần dung lượng/retention được chốt riêng. Không lén sao chép tick vào nơi khác để né yêu cầu dọn, không đụng kho nghiên cứu cũ.
- Mỗi giai đoạn bàn giao: file đổi, hash/spec, test đã chạy, test chưa chạy, nguồn dữ liệu, sample report, giới hạn và cách rollback file có chọn lọc.
- Cấp kết luận tách biệt: **skill cài được → phần mềm đúng contract → vận hành demo đã kiểm → bằng chứng chiến lược**. Không bỏ qua các cấp.

## 13. Prompt giao model triển khai

> Đọc kế hoạch này và các skill/AGENTS có liên quan. Thực hiện P0–P5 theo từng checkpoint; không tự chạy native MT5, pilot P6, giao dịch hoặc train nếu chưa có yêu cầu tiếp theo. Tận dụng collector, snapshot, mt5_flow, Fabio, quote/replay primitives, journal và tests hiện có. Tạo skill riêng scalp-fabio, không đổi trade-toi thành Fabio và không sửa baseline A/B. Phân biệt source principle với quy tắc dự án; ghi rõ proxy/UNKNOWN. Bắt đầu bằng skill đọc artifact, sau đó bổ sung identity/causal lifecycle và adapter replay tối thiểu. Mọi thay đổi chiến lược tăng spec version, giữ legacy output tương thích; không giả candidate A để replay Fabio. Chạy test hẹp rồi regression, đánh giá skill độc lập và chỉ cài sau nghiệm thu. Dừng để báo khi dữ liệu/thuật toán nguồn chưa cho phép kết luận; không dùng dữ liệu giả để tuyên bố khả năng thật. Khi bàn giao, nói chính xác phần đã làm, phần chưa kiểm và cấp nghiệm thu.

## 14. Nguồn đối chiếu

- `reports/20261108_video_strategy/BAO_CAO_NGHIEN_CUU_FABIO_FTMO_20261108.md`: nghiên cứu video, mốc nội dung và điểm khác bản diễn giải.
- `reports/20261108_video_strategy/AI_BRAINSTORM_SETUP_PLAYBOOK.md`: kế hoạch nghiên cứu trước; các phần feed ngoài/FTMO chỉ là lịch sử, không áp vào scope mới.
- `quant_mt5/phases/FABIO_FTMO_SKILL_UPDATE_20261108/attempt_2_codex/REPORT.md`: bản Fabio đã cài và giới hạn.
- `quant_mt5/runtime/on_demand/weekly_fabio_20261102_08/WEEKLY_TRIAL_REPORT.md`: nguồn MetaQuotes Demo, trigger khác lệnh fill; chưa có P&L Fabio.
- `quant_mt5/TRADE_TOI.md` và installed `trade-toi/SKILL.md`: ranh giới giữ nguyên A và quy trình buổi tối.
- Code/CLI đang dùng được kiểm đọc ngày lập kế hoạch; chưa chạy lại test hoặc MT5 trong lượt lập kế hoạch.

**Đề nghị thứ tự:** P0–P1 để có skill nghiên cứu riêng dùng công cụ sẵn có; P2–P5 để hoàn thiện tính nhân quả/kiểm định; P6 demo khi được gọi; P7 M1 sau đó. Không chờ mua data hoặc mở FTMO mới bắt đầu được phần phân tích.
