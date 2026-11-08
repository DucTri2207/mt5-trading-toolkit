# Kế hoạch nâng cấp và nghiệm thu harness nghiên cứu TP/SL

Ngày lập: 05/11/2026, ICT. Phiên bản kế hoạch: 1.0.

**Trạng thái: DRAFT_FOR_REVIEW — chỉ lập kế hoạch.** Tài liệu này không phải lệnh triển khai, không cho phép gửi việc sang Muse, thay engine đang dùng, chạy nền hoặc đặt/check order. Các tên module, schema, command và artifact mới bên dưới đều là thiết kế dự kiến.

## 1. Kết quả cần đạt

Chuẩn bị trên laptop một bộ nghiên cứu có thể chuyển sang Linux/Muse, để Muse thực hiện các thí nghiệm TP/SL bằng đặc tả và phép kiểm tra máy đọc được. Một người khác phải tái lập được kết quả từ cùng dữ liệu và phiên bản mã nguồn.

Mục tiêu nghiên cứu của người dùng: TP theo vùng giá đích, SL theo điểm vô hiệu hợp lý, tăng win rate trong khi giữ số cơ hội thực hiện và cải thiện hiệu quả sau chi phí. Các mục tiêu này phải được đo riêng; kết quả không đạt một mục tiêu phải ghi rõ.

Hai kết luận nghiệm thu độc lập:

- `HARNESS_ACCEPTED`: phần mềm tính đúng, tái lập được, xử lý dữ liệu thiếu đúng và đủ điều kiện giao Muse nghiên cứu.
- `POLICY_ACCEPTED_FOR_FORWARD`: một quy tắc TP/SL cụ thể đủ bằng chứng để khóa và quan sát forward. Kết luận này cần nghiên cứu thực tế sau khi harness đạt.

Kết quả âm hoặc chưa đủ bằng chứng là đầu ra hợp lệ của một harness đạt nghiệm thu. Hoàn thành harness không chứng minh chiến lược có lãi hoặc pass FTMO.

## 2. Hiện trạng đã đối chiếu với mã nguồn

Các đường dẫn trong phần này tính từ `D:/trading thử lần cuối cuối/quant_mt5/`.

| Thành phần | Hiện trạng | Hệ quả với kế hoạch |
| --- | --- | --- |
| `quantmt5/execution.py`, `simulate()` | SL ngoài nến tín hiệu + buffer; short dùng Ask high khi có dữ liệu; TP = 1,5R | Giữ đường baseline để hồi quy, thêm policy có version trong bản staged |
| `quantmt5/context.py` | Có PDH/PDL và high/low của 8 H1 đã đóng | Tái dùng định nghĩa có sẵn, nhưng cần xuất level và thời điểm được biết thành contract riêng |
| `quantmt5/evaluate.py`, `run_experiment()` | Tạo `M1OpenProxy` cho backtest; không tự chuyển sang tick chỉ vì registry có tick | Bắt buộc nối evaluator với replay tick và coverage; adapter dữ liệu riêng chưa đủ |
| `quantmt5/replay.py` | Có kiểm coverage và nhãn tick exact/partial cho nguồn hiện có | Tái dùng logic kiểm đã có, thêm nguồn lịch sử bên thứ ba đúng danh tính |
| `quantmt5/evaluate.py` | Có branch/episode selection, portfolio capacity, daily series, block bootstrap, Holm | Mở rộng cho policy TP/SL; không viết evaluator độc lập có semantics khác |
| `quantmt5/config.py`, `data.py`, `source_bundle.py` | Có bundle hash, data pins và read contract | Dùng làm nền; schema nguồn hiện thiên về collector MT5, cần adapter có acceptance riêng |
| `quantmt5/data.py`, `Bars.status()` | Bar không có `member_count` được gọi `BROKER_FINAL`; timestamp/aggregation có giả định hiện hữu | Không đưa bar từ tick Dukascopy vào rồi gắn nhãn broker bar; phải giữ provenance và định nghĩa phiên đúng |
| `quantmt5/util.py`, `engine_hash()` | Hash các file `.py` ngay dưới package | Module/harness ở thư mục con phải được đưa vào release manifest; hash hiện tại chưa đủ phủ phần mới |
| `tests/conftest.py` | Có fixture đọc archive của workspace | Gói portable cần bộ fixture tự chứa; test cần cache riêng phải được gắn nhãn integration và báo điều kiện thiếu |
| `config/exposure_ledger.json` | Nhiều mã/giai đoạn 2021–2026 đã được nghiên cứu | Tải lại qua nhà cung cấp khác không làm dữ liệu trở thành holdout sạch |
| `session.py` và phiên `toi_nay` | Tick mặc định 15 phút, forward outcome tracking chưa triển khai | Nghiên cứu lịch sử và sẵn sàng forward native là hai mốc bàn giao khác nhau |
| Môi trường mã nguồn | `git rev-parse` hiện không nhận diện đây là Git repository | P0 phải lập manifest/ảnh chụp nguồn; không phụ thuộc vào một commit hash chưa tồn tại |

B4 hiện là dữ liệu đã tiếp xúc, chủ yếu proxy và kết quả seed âm. Mọi kết quả B4 giữ nguyên nhãn; không gọi baseline đó là chiến lược đã được chứng minh.

Trạng thái FTMO staged phải đọc lại từ acceptance receipt mới nhất khi triển khai; không suy rằng một work order hoặc một file `DONE` chứng minh đã promote. Công việc mới không ghi lại CONTROL hay mở lại các lượt kiểm chính thức cũ.

## 3. Phạm vi và kiến trúc

### 3.1 Bản đầu tiên

- Universe thí điểm: XAUUSD, EURUSD, USDJPY, với mapping và khả dụng nguồn được kiểm riêng.
- Giữ detector và sáu branch M0/M1/M2/P0/P1/P2 của seed làm tập đối chiếu; không chọn branch sau khi nhìn P&L.
- Hai exit policy ở vòng đầu: baseline 1,5R và TP theo level gần nhất hợp lệ; cùng SL baseline, entry, thời hạn và cost/latency đã khóa.
- Cả phép so sánh trên cùng opportunity ledger và mô phỏng danh mục có capacity đều bắt buộc.
- Harness chạy offline trên Windows và Linux, không cần MT5 để nghiên cứu lịch sử.
- Dữ liệu thực đi từ mẫu nhỏ đã kiểm sang mở rộng; chưa tải toàn bộ 10 năm trước khi adapter đạt.

Trailing, chốt từng phần, breakeven, chọn target bằng ML và tự sinh setup mới nằm ngoài bản đầu. SL theo cấu trúc là vòng nghiên cứu tiếp theo trên cùng harness.

### 3.2 Luồng dữ liệu dự kiến

```text
Raw nguồn + source metadata + checksum
    -> adapter + data-quality report + read contract
    -> bundle bất biến + snapshot/data pins
    -> opportunity ledger + level catalog biết được tại quyết định
    -> exit policy -> replay có quote/coverage/cost contract
    -> ledger toàn bộ ứng viên + portfolio timeline
    -> thống kê theo đặc tả đã đăng ký
    -> máy kiểm chứng + báo cáo tiếng Việt + quyết định review
```

Vùng triển khai dự kiến: một staging tree riêng dưới `quant_mt5/phases/HARNESS_TPSL_20261105/`, mỗi gói có attempt và manifest riêng. Engine đang dùng là nguồn đối chiếu. Khi chuẩn bị Git, chỉ đưa bản đã làm sạch vào repo; thay đổi Git/private repo/token thuộc bước triển khai sau.

Ưu tiên tái dùng `execution`, `replay`, `evaluate`, `data`, `config`, `features` và các helper hash/atomic write/lock hiện có. Module mới tối thiểu dự kiến: `research_contracts`, `historical_source`, `exit_policy`, `research_runner`, `research_verify`. Bố trí cuối cùng theo dependency thực, không tạo framework plugin tổng quát.

### 3.3 Danh tính và thời gian

Mỗi kết quả phải gắn đủ: code manifest hash, environment lock hash, data manifest hash, read-contract hash, config/bundle hash, experiment/spec hash, exit-policy hash, cost/latency hash và seed.

- `experiment_id`: danh tính của câu hỏi và đặc tả bất biến.
- `run_id`: một lần thực thi, có thể có retry kỹ thuật.
- `trial_id`: một phép thử khoa học được đăng ký; thêm rule/grid/filter sau khi xem kết quả tạo trial mới.
- `decision_at`: thời điểm dữ liệu dùng cho quyết định thực sự khả dụng trong mô hình.
- `event_at`, `available_at`, `ingested_at`: ba khái niệm riêng. Historical arrival không đo được phải ghi `ASSUMED`, không dùng ngày tải file làm thời điểm thị trường biết dữ liệu.

ID của plan/fill/ledger mới phải phân biệt được policy, pool level đã chọn và read contract. Không cache theo `candidate_id` đơn lẻ khi nhiều policy/cost/latency cùng chạy. Clock/path/volume semantics thay đổi phải đổi version và làm mất hiệu lực cache tương ứng.

Run hash bao gồm provenance đầy đủ. Semantic fingerprint phục vụ parity loại riêng timestamp chạy, log và vị trí file theo danh sách trường đã khóa; không được bỏ data/policy identity hay trường quyết định. Giá so sánh theo tick-grid; tolerance cho P&L/float phải công bố trước, kèm sai số tối đa và kiểm nó không làm đổi verdict. Không buộc byte của log Windows và Linux giống nhau.

## 4. Các gói triển khai trên laptop và cổng nghiệm thu

Mỗi gói chỉ bắt đầu khi prerequisite đạt; người triển khai nộp evidence, người nghiệm thu kiểm lại độc lập. Nếu Claude Code triển khai thì Codex nghiệm thu. Chưa gửi lệnh cho Claude Code hoặc Muse trong lượt lập kế hoạch này.

| Gói | Công việc và đầu ra | Điều kiện đạt |
| --- | --- | --- |
| H0 — Khóa nền | Kiểm trạng thái nguồn hiện hành; lập source/config/test manifest; chọn regression suite; lập dependency map, exposure map và baseline fixtures | Nguồn đối chiếu xác định được; không trộn FTMO staged chưa được nhận; fixture baseline có expected result độc lập |
| H1 — Contract và runner | Schema chặt cho data/experiment/policy/run; isolated config/store/output; dependency lock theo nền tảng; register/run/resume/verify | Thiếu trường bắt buộc, unknown enum hoặc bundle lỗi bị từ chối; import đúng staged tree; fresh process dùng đúng env trước import |
| H2 — Adapter và chất lượng dữ liệu | Raw bất biến, decoder/normalizer Dukascopy, mapping đơn vị, coverage ledger, bar aggregation, kiểm chéo export độc lập | Mẫu có giá/time/side/order đúng; source ngoài không bị gọi native/synthetic; các lỗi checksum/time/gap có kết quả đúng |
| H3 — Level và exit policy | Xuất level causally; baseline và nearest-valid-level TP; output plan có lineage và reason code | Baseline hồi quy đạt; thêm/sửa dữ liệu tương lai không đổi plan cũ; TP/SL đúng side/grid; thiếu level được ghi rõ |
| H4 — Replay tick và portfolio | Nối batch evaluator vào replay đã có; thêm policy vào mọi version/cache; giữ selection/capacity; unresolved handling | Cùng một input replay đơn lẻ và batch cho cùng kết quả; không tự rơi về proxy; portfolio đếm đủ nhận/loại/đang mở |
| H5 — Thống kê và quyết định | Paired daily series, frequency/win-rate/cost/hold metrics, test-family contract, bootstrap và report builder | Tổng ledger khớp daily/portfolio; CI/p-value kiểm bằng oracle nhỏ; UNKNOWN/unresolved không bị đổi thành 0 hoặc bị bỏ lén |
| H6 — Nghiệm thu độc lập và portable | Kiểm adversarial, regression, chạy clean Windows/Linux, relocate bundle, restart/resume, tài nguyên | Tất cả case bắt buộc đạt; cùng input sinh semantic output hash như nhau; artifact thiếu/tamper không được PASS |
| H7 — Đóng gói giao Muse | Gói sanitized, dependency lock, fixtures, runbook, task template, result schema và acceptance receipt | Người chưa biết project chạy lại được ca mẫu; máy verify xác nhận gói và kết quả; review xác nhận `MUSE_HISTORICAL_RESEARCH_READY` |

### H0 — Khóa nền và oracle

1. Lưu hash nguồn/config đã được chấp nhận; xác minh riêng trạng thái FTMO 046 từ bằng chứng gần nhất.
2. Đóng băng các fixture LONG/SHORT, TP/SL/time exit, pre-entry SL touched, spread guard, Ask thiếu, quote chậm, episode/capacity và unresolved.
3. Expected value dùng tick tape rất ngắn tính tay được. Chạy engine cũ và engine staged trên cùng fixture để kiểm hồi quy; lấy output engine cũ làm một control, không coi nó là oracle duy nhất.
4. Lập danh sách test hiện có phải giữ nguyên assertion. Không sửa fixture/expected cũ để làm bản mới xanh.
5. Bản thí điểm không gọi lại native smoke 23:00 hoặc bất kỳ official run đã dùng hết quyền chạy. Native readiness sẽ có runbook/gate riêng khi được yêu cầu.

### H1 — Schema và vận hành

- Đặc tả dùng JSON chặt, từ chối NaN/Infinity, số âm không hợp lệ, bool thay numeric, đường dẫn thoát output root và trường không được hỗ trợ.
- Tái dùng atomic write và file lock. State dự kiến: `REGISTERED -> RUNNING -> COMPLETED` hoặc `FAILED/INTERRUPTED`; chỉ `COMPLETED` qua verify mới đủ để in verdict.
- Retry cùng spec/data/code không nhân đôi kết quả hoặc biến thành một trial khoa học mới. Mọi retry vẫn có event và attempt receipt.
- Khóa phiên bản Python, numpy, pytest, timezone database và decoder đã chọn; tách dependency thu native Windows khỏi môi trường historical Linux.
- Bundle di chuyển được bằng root mapping trong manifest; identity dữ liệu dựa trên nội dung. Đổi thư mục không làm đổi semantic result, đổi nội dung/read contract phải đổi identity.
- Audit runtime/source import path trước run. Thiếu dữ liệu không fallback sang registry/store mặc định của laptop.
- Khóa đường research trong chế độ offline; không gọi collector/MetaTrader5 để bù dữ liệu giữa một thí nghiệm.

### H2 — Hợp đồng nguồn và chất lượng

Mẫu pilot: khoảng 20 ngày giao dịch cho mỗi mã, kèm cửa sổ EU/US đổi DST, giao tháng/năm, cuối tuần, thiếu file và mất kết nối được tiêm có kiểm soát. Pilot chứng minh phần mềm, không phải bộ mẫu chứng minh lợi thế.

Các trường bắt buộc:

- Provider, instrument mapping, data vintage, original URL/object identity, checksum, byte count, fetched time và decoder version.
- Tick: raw timestamp, UTC timestamp, thứ tự record nguồn, Bid, Ask; volume và đơn vị giữ riêng nếu có. Nhiều tick cùng millisecond phải giữ thứ tự nguồn. Không gộp tick chỉ vì cùng timestamp hoặc cùng giá.
- Coverage của từng request/window: thành công đầy đủ theo contract nguồn, rỗng có bằng chứng thị trường đóng, chưa tải, lỗi mạng, parse lỗi, thiếu không giải thích được, hoặc xung đột. HTTP lỗi/404 không tự là market closed.
- Checksum, độ dài record, endian, price scale và timestamp-unit kiểm bằng export mẫu độc lập. Nếu dùng object path theo giờ/tháng, convention phải có test giao tháng/năm; không suy từ tên file.
- Giá hữu hạn, dương, Ask >= Bid; thứ tự time hợp lệ; off-grid/conflicting records được quarantine và báo số lượng. Không âm thầm sửa giá hoặc sort lại thứ tự mơ hồ rồi gọi là dữ liệu gốc.
- Một khoảng yên lặng không đủ kết luận mất tick; khoảng request thành công cũng không chứng minh toàn bộ thị trường. Coverage certificate chỉ áp dụng băng nguồn và những giả định đã ghi.

Bar contract:

- V1 dùng Bid OHLC từ tick, giữ Ask riêng cho execution; chart basis ghi rõ.
- M1/M5/H1/D1 phải có định nghĩa bucket, close time, completeness và `available_at` rõ.
- D1 broker, D1 UTC và ngày giao dịch New York là các định nghĩa khác nhau. Chọn đúng policy đã đăng ký; thay boundary là trial/read contract mới.
- Nếu v1 chọn UTC D1 cho Dukascopy, ghi `PDH/PDL_UTC`; không so rồi gọi tương đương PDH broker. Muốn parity broker cần cấu hình rollover và test lịch tương ứng.
- Không dựng nến không có quote bằng forward fill. Không dùng H1/D1 còn chạy làm dữ liệu đã đóng. Tick count tái dựng phải được gọi theo nguồn; không giả bằng MT5 tick_volume.
- Volume ở best Bid/Ask là quote size của nguồn; không đổi thành tổng giao dịch thị trường hoặc aggressor delta. Real volume không có giữ UNKNOWN.
- Profile instrument/contract/cost phải riêng theo nguồn và vintage. Metadata MT5 quan sát hiện tại không tự thành metadata lịch sử Dukascopy.

Data-quality gate ghi toàn bộ cửa sổ dự kiến, cửa sổ dùng được và lý do loại. Vùng giao dịch được đưa vào kiểm định phải có quote coverage đủ entry/exit; nếu thiếu thì outcome unresolved, kết luận tổng thể chưa đủ bằng chứng. Báo thống kê subset có nhãn, không cấp verdict dương trên subset được chọn sau khi nhìn lợi nhuận.

### H3 — Level catalog và TP/SL

**Vòng TP đầu tiên có đúng hai policy:**

- `BASELINE_FIXED_R_V1`: tái hiện TP 1,5R + SL hiện tại.
- `NEAREST_VALID_LEVEL_V1`: TP là mức gần nhất hợp lệ theo hướng có lợi trong pool PDH/PDL và high/low 8 H1 đóng; SL như baseline.

Đây là nhãn policy dự kiến, chưa có trong runtime. Không thêm lưới RR, lookback hay chấm điểm level ở vòng đầu.

Hợp đồng level:

- `level_id`, loại, giá gốc, chart basis, timeframe, source/data/read-contract hash, bar/window nguồn, `formed_at`, `available_at`, validity và lý do vô hiệu.
- Pool level được đóng băng ở candidate `ready_at`, chỉ dùng dữ liệu `available_at <= ready_at`. Entry quote đầu tiên dùng được cung cấp giá để kiểm khoảng cách và chọn target; không mở rộng pool bằng bar xuất hiện sau ready.
- Record plan ghi thêm `decision_at`, quote event/arrival, mức được xét, mức được chọn, loại trừ và giá sau rounding. Selection chỉ xem dữ liệu biết tại quyết định.
- Mức đã vượt, nằm sai phía entry, bằng entry sau rounding hoặc vi phạm điều kiện stops/freeze được loại theo quy tắc cố định. Tie-break: khoảng cách sau rounding, loại theo thứ tự đã khóa, rồi `level_id`.
- Không có mức hợp lệ: `BLOCKED_NO_VALID_TARGET`. Không fallback 1,5R ẩn. Một policy fallback nếu được nghiên cứu sau là trial riêng.
- Level có nguồn Bid vẫn giữ nhãn Bid. LONG thoát theo Bid, SHORT theo Ask; v1 coi TP là giá tuyệt đối và short yêu cầu Ask chạm giá đó. Không dùng spread tương lai để biến một Bid level thành Ask level, không diễn giải short TP thành cùng sự kiện Bid chạm level.
- Phiên bản rounding và convention về chạm biên phải rõ và được kiểm bằng giá đúng tick; baseline giữ rounding hiện tại, policy level phải bảo đảm giá hợp lệ sau rounding.

**Vòng SL tiếp theo:** chỉ bắt đầu sau khi harness và vòng TP được review. Một challenger đầu tiên có thể dùng swing đã xác nhận tại ready hoặc điểm vô hiệu của cấu trúc setup; đặc tả phải chốt cách xác nhận, timeframe, buffer, expiry và quote-side support trước khi chạy. Swing cần nến bên phải chỉ được dùng sau khi các nến xác nhận đã khả dụng.

Giữ TP cố định khi so sánh SL; xác định lại quantity/cost trên cùng risk convention. So sánh R/trade khi mỗi policy tự đổi độ rộng SL là chưa đủ: phải có hiệu quả/ngày và danh mục trên cùng ngân sách rủi ro mô phỏng. Tiền vốn/risk thực không được tự chọn.

### H4 — Tick replay và hai lớp so sánh

1. **Opportunity comparison:** tạo catalog chung trước exit selection. Mọi candidate có một disposition cho mỗi policy: gate fail, episode skip, entry blocked, no target, fill, outcome unresolved... So sánh cùng tập candidate; không chỉ giữ giao của các lệnh thắng hoặc đã fill.
2. **Portfolio comparison:** chạy từng policy theo timeline, giữ quy tắc một vị thế/symbol và risk budget hiện hữu. TP khác làm thời gian giữ khác, ảnh hưởng số lệnh được nhận và opportunity bị bỏ. Thay portfolio/episode rule là thí nghiệm khác.

Batch evaluator cần có quote-model resolver dùng chung với replay. V1 research yêu cầu tick; thiếu thì `NOT_EVALUABLE/UNRESOLVED` có reason. Proxy chỉ được chạy ở chế độ diagnostic đã đăng ký, headline riêng và không tính vào evidence tick.

Nguồn Dukascopy phải có provider/evidence grade riêng; `_grade()` và `load_pinned_ticks()` hiện có nhánh native-versus-synthetic nên phải mở rộng nhất quán toàn luồng. `EXACT_QUOTE_PATH` chỉ nói độ trung thực khi replay băng quote đã lưu, không chứng minh fill của broker, latency thực hay toàn thị trường.

Kiểm coverage từ đoạn dữ liệu cần dựng SL tới entry và hết horizon. SHORT cần Ask cho toàn cửa sổ dựng SL. Không lấy min/max từ băng không đầy đủ. Entry deadline + max hold + quote slack phải theo config/hash, không cố định ngầm 60 phút trong một helper mới.

Outcome/censoring ở mép dữ liệu: vẫn ghi candidate/fill; chưa có tương lai để thoát thì `PENDING/UNRESOLVED`. Giữa train/validation/final phải purge các outcome chồng biên. Warmup chỉ dùng lịch sử trước fold; phần warmup không tính P&L. Calendar có ngày 0 lệnh và giữ ngày phát sinh exit theo contract.

### H5 — Metric và suy luận

**Headline mặc định đề xuất:** chênh lệch daily net return theo đơn vị risk đã khóa, challenger trừ baseline, sau phí/spread/slippage; báo cả mức tuyệt đối của challenger. Hai phép so sánh phải cùng data/calendar/cost/risk convention.

Các chỉ tiêu bắt buộc:

- Net expectancy/trade, net return/day, tổng net return và chênh lệch paired daily.
- Win rate = tỷ lệ outcome net > 0; net = 0 báo riêng; có CI phù hợp phụ thuộc theo ngày.
- Raw signals, eligible plans, fills, resolved/unresolved, lệnh/tuần, tuần 0 lệnh và toàn bộ lý do bỏ.
- Tỷ lệ fills challenger/baseline ở cả opportunity và portfolio. Baseline không có fill thì tỷ lệ UNKNOWN.
- Hold time, time-to-TP/SL, MAE/MFE sau entry, spread/cost trên risk, phía LONG/SHORT.
- Drawdown closed-P&L riêng với intraday marked equity. Thiếu marks không cấp chứng nhận drawdown equity/luật quỹ.
- Theo symbol, năm/fold, session và cost scenario; subgroup là chẩn đoán trừ khi đã đăng ký thành claim kiểm định.
- Concentration theo ngày/mã, độ nhạy khi bỏ ngày cực đoan được đăng ký trước; không âm thầm loại outlier để cải thiện headline.

Mục tiêu giữ số lệnh: dùng tỷ lệ quan sát tối thiểu 1,00 cho chính sách được xem là đáp ứng yêu cầu hiện tại; không âm thầm đổi sang 0,95. Báo CI của thay đổi tần suất. Tỷ lệ mẫu >= 1 không chứng minh tần suất ngoài mẫu không giảm. Nếu cần biên non-inferiority khác phải chốt trước khi đọc validation.

Nhóm đối chứng:

- Baseline exit trên cùng candidate là control chính cho TP/SL.
- Một empirical null cho directional edge là thí nghiệm phụ đã đăng ký: giữ entry time/market state, side-specific execution, khoảng cách stop/target, horizon và cost; cơ chế randomization phải mô tả chính xác và sinh đủ đối chứng. Không coi đảo chiều giữ nguyên giá SL/TP là control tương đương.
- `SL/(SL+TP)` chỉ là ví dụ lý tưởng, không dùng làm ngưỡng nghiệm thu thực nghiệm.

Thống kê:

- Tái dùng moving-block bootstrap theo trading day; giữ vector tất cả symbol, baseline và challenger cùng block để bảo toàn phụ thuộc. Kiểm lại trường hợp lệnh chồng ngày hoặc horizon dài hơn block.
- Block length, số resample, seed, primary statistic và null-centering khóa trước run. Kế thừa giá trị cũ cần ghi lý do, không tuyên bố block 5 ngày luôn đủ.
- Vòng đầu có sáu so sánh policy-vs-baseline theo branch. Các claim absolute edge/win rate nếu dùng để chọn/promote phải nằm trong test family đầy đủ đã đăng ký.
- Holm chỉ hiệu chỉnh family đã khai báo; không coi Holm của từng lượt là kiểm soát toàn bộ việc tìm kiếm nhiều tuần. Mỗi campaign hữu hạn có tổng trial budget và alpha budget đã chốt; hết budget thì output là báo cáo và review, không tự reset bằng campaign mới.
- Validation lặp ghi mọi lần xem và mọi trial, giữ nhãn validation/exploratory. Lần kiểm cuối dùng một candidate đã khóa trên dữ liệu tương lai, một checkpoint đã định trước. Theo dõi sức khỏe được phép; không chọn ngày dừng dựa trên P&L.
- Chọn chiều dài forward bằng precision/power analysis từ development và hiệu ứng tối thiểu có ý nghĩa được khóa. Không lấy sàn 30 fills/60 days hiện có làm bằng chứng đủ lực thống kê. Thiếu mẫu tại checkpoint trả `INCONCLUSIVE`; kéo dài/chỉnh rule tạo đặc tả đánh giá mới và giữ audit của lần cũ.

Điều kiện candidate được chọn cho forward: không unresolved ảnh hưởng claim, cost/coverage chấp nhận được, expectancy tuyệt đối đạt ngưỡng đã khóa, cải thiện so baseline có độ bất định được báo, win rate/frequency đạt yêu cầu đã đăng ký và kết quả không lệ thuộc một subgroup được chọn sau khi xem dữ liệu. Những ngưỡng như hiệu ứng tối thiểu hoặc drawdown budget phải chốt tại đăng ký nghiên cứu; trước đó verdict chỉ là mô tả, không tự đặt ngưỡng để PASS.

## 5. Thang dữ liệu và quy trình nghiên cứu

### Ba tầng dữ liệu

1. **Development:** dữ liệu đã dùng/nhìn ở mọi dạng, kể cả nguồn khác của cùng mã/giai đoạn. Dùng xây đặc tả, debug và ước lượng chi phí/power. Ghi exposure, không gọi fresh OOS.
2. **Validation:** cửa sổ khóa trước mỗi wave, được dùng so sánh có ghi sổ; mọi điều chỉnh sau khi xem kết quả được nhận diện. Có walk-forward và purge, nhưng không xóa lịch sử đã tiếp xúc.
3. **Final prospective:** dữ liệu sau thời điểm freeze toàn bộ candidate/spec. Giữ tách khỏi quá trình chọn tham số; kiểm một lần theo checkpoint đã đăng ký. Dữ liệu cũ chỉ có thể thay thế khi chứng minh được chưa từng tiếp xúc, kể cả nghiên cứu liên quan; mặc định dùng forward.

Không tự gán 2025–2026 thành holdout. Exposure ledger hợp nhất phải bổ sung cả nghiên cứu cũ ngoài `quant_mt5` và các lần đọc kết quả từ chat/report. Nhà cung cấp khác là kiểm tra robustness nguồn, không khôi phục tính độc lập theo thời gian.

### Các wave sau khi phần mềm đạt

| Wave | Thay đổi được phép | Cần giữ cố định | Quyết định sau wave |
| --- | --- | --- | --- |
| W1 — TP level | Một policy nearest-valid-level so baseline | Detector/branch/entry/SL/horizon/cost/risk | Reject, inconclusive hoặc chọn candidate cho bước tiếp |
| W2 — SL cấu trúc | Một rule SL đã định nghĩa causally | TP/reference, entry và các rule còn lại được khóa | Chỉ mở khi W1 được review và đăng ký mới |
| W3 — Cấu hình kết hợp | Một tổ hợp được chọn từ development | Spec đầy đủ, portfolio và test family | Xác nhận trên validation phù hợp, tránh dùng lại dữ liệu lựa chọn như kiểm cuối |
| F — Forward | Quan sát policy đã freeze cùng baseline | Mã/config/data source/assumption và rule kết luận | Đạt, âm hoặc chưa đủ bằng chứng; mọi sửa rule trở thành version mới |

Không triển khai ML trước khi có nhãn causal, rule baseline và outcome pipeline đáng tin. Nếu về sau cần ML, thêm fold-specific preprocessing/train/validation và model artifact hash; retrain chỉ dùng dữ liệu được phép trong fold, không tự cập nhật champion khi một job kết thúc.

## 6. Ma trận nghiệm thu bắt buộc

Các mã dưới đây là test/kiểm tra sẽ xây khi triển khai. Chưa test nào trong bảng được chạy bởi việc lập kế hoạch này.

| ID | Ca kiểm | Kết quả bắt buộc |
| --- | --- | --- |
| A01 | Replay baseline trên LONG/SHORT oracle tính tay và fixture cũ | Status, entry/SL/TP, exit, chi phí và net P&L khớp contract; mọi drift được điều tra |
| A02 | Thêm/sửa các bar và tick sau decision | Level pool, target, SL và plan decision cũ không đổi; outcome được phép đổi khi tương lai đổi |
| A03 | Swing có nến xác nhận chưa khả dụng | Swing không được chọn; sau thời điểm xác nhận mới hợp lệ |
| A04 | H1/D1 đang chạy hoặc đến muộn | Không bị dùng như closed/available bar |
| A05 | LONG/SHORT, Ask missing, Ask high dựng SL không đầy đủ | Đúng quote side; thiếu dữ liệu trả blocked/unknown đúng lý do |
| A06 | Hai level bằng nhau, rounding sát tick, level sai phía, không có target | Tie-break tất định; TP/SL hợp lệ; no-target giữ trong ledger |
| A07 | Tick gap ở signal/entry/exit, hoặc hết tape trước horizon | Không cấp exact/outcome hoàn chỉnh sai; không tự chuyển headline sang M1 |
| A08 | HTTP timeout/404, file rỗng, weekend và scheduled break | Trạng thái coverage phân biệt đúng; lỗi nguồn không bị gọi market closed |
| A09 | Nhiều record cùng ms hoặc cùng Bid/Ask | Không xóa tick hợp lệ; thứ tự nguồn hoặc nhãn ambiguity được bảo toàn |
| A10 | Chỉnh 1 byte tick/config/read contract sau freeze | Verify từ chối; cache/ID cũ không được phục vụ nội dung mới |
| A11 | Chạy đơn lẻ và batch cùng candidate/policy/scenario | Plan và execution bằng nhau; không cache chéo policy |
| A12 | TP xa giữ vị thế khiến bỏ tín hiệu kế tiếp | Opportunity giữ cả hai; portfolio ghi rõ capacity rejection; frequency phản ánh giảm nếu có |
| A13 | Lỗi nguồn chỉ ở một symbol/ngày | Giữ reason và denominator; không biến missing thành 0 hoặc âm thầm bỏ khỏi headline |
| A14 | Lệnh chồng fold/checkpoint, warmup, cuối tuần | Purge/calendar/exit-horizon đúng; không rò outcome qua biên |
| A15 | Timezone/DST, EU và US đổi ngày khác nhau, double offset | UTC/phiên đúng expected; giả định chưa xác minh vẫn mang nhãn |
| A16 | Dukascopy/provider lạ đi qua replay và report | Grade đúng nguồn; không xuất `NATIVE_TICK_EXACT` cho nguồn ngoài MT5 |
| A17 | P&L LONG/SHORT, commission, spread, slip, rounding quantity | Oracle tính tay đạt; không đếm spread hai lần; thiếu input cash được UNKNOWN |
| A18 | Ledger/daily/portfolio, ngày 0 lệnh, unresolved | Tổng khớp trong tolerance đã ghi; chưa resolved chặn kết luận cần toàn bộ outcome |
| A19 | Bootstrap/Holm với vector nhỏ, p thiếu và family bị sửa | Oracle số học đạt; không bỏ test thất bại khỏi mẫu số; spec sửa tạo identity mới |
| A20 | Lấy trial đẹp nhất, xóa trial fail, đọc validation rồi đổi rule | Registry/verify phát hiện hoặc ghi rõ exploratory; không cấp nhãn final sạch |
| A21 | Crash giữa ghi artifact/manifest và retry | Không có completed giả; resume không nhân fill/trial; hash output ngữ nghĩa khớp chạy sạch |
| A22 | Hai worker claim cùng task hoặc cùng output | Chỉ một owner hợp lệ; attempt/lock rõ; không ghi chồng hoặc hỏng registry |
| A23 | Output giả, thiếu ledger, JSON tự ghi PASS | Verifier kiểm lại từ artifact/hash và bác bỏ PASS không đủ bằng chứng |
| A24 | Chạy từ thư mục có dấu/khoảng trắng, đổi root, Windows sang Linux | Import/env đúng; không phụ thuộc đường dẫn cá nhân; semantic output tái lập |
| A25 | Test portable không có cache/MT5/network | Bộ hermetic chạy được; integration thiếu dependency báo đúng, không giả bộ đã test |
| A26 | Benchmark RSS, số worker, restart, ổ đĩa đầy | Hủy an toàn/có reason; không vượt budget; không sinh report hoàn tất khi lỗi |
| A27 | Research import/call graph tới API đặt/check lệnh, credential trong gói | Dependency boundary/guard test từ chối; package scan loại credential, live state và đường dẫn nhạy cảm |
| A28 | Baseline âm, challenger âm, mẫu mỏng hoặc CI chưa kết luận | Đúng verdict; không ép xuất policy thắng để hoàn thành task |

Điều kiện nghiệm thu kỹ thuật: tất cả case áp dụng đạt; case bắt buộc chưa chạy không được tính PASS. Case native/FTMO thuộc gate sau có thể `DEFERRED` kèm lý do và không được nâng nhãn sẵn sàng.

A03 áp dụng khi mở gói swing/SL ở W2; bản TP v1 phải ghi `NOT_APPLICABLE_NO_SWING_POLICY` thay vì báo đã test swing. Mọi ngoại lệ phạm vi phải được người nghiệm thu chốt trong acceptance matrix trước run, không để Muse tự đánh dấu skip khi test đỏ.

## 7. Artifact, report và gói bàn giao

Mỗi run hoàn tất cần ít nhất:

- `SPEC.json`, receipt đăng ký và exposure/split manifest.
- `ENVIRONMENT.json`, `CODE_MANIFEST.json`, `DATA_MANIFEST.json`, `READ_CONTRACT.json`.
- `QUALITY_REPORT.json`, `OPPORTUNITIES.jsonl`, `PLANS.jsonl`, `OUTCOMES.jsonl`, `PORTFOLIO.jsonl`, `DAILY_SERIES.json`.
- `METRICS.json`, `TRIAL_EVENTS.jsonl`, `COMMANDS.json`, exit codes và stdout/stderr đã làm sạch.
- `REPORT.md`, `VERIFY.json`, `MANIFEST_SHA256.json` và receipt review độc lập khi có.

Tên và cách chia file có thể rút gọn nếu vẫn truy lại được đầy đủ; ledger lớn phải stream/chunk. Tránh tạo nhiều bản sao cùng dữ liệu chỉ để đủ danh sách.

Report tiếng Việt phải trả lời: đã chạy gì; data/source/clock/cost grade; số candidate/fill/missing; kết quả tuyệt đối và so baseline; frequency/win rate; CI và hạn chế; verdict; lệnh tái lập; artifact/hash. Kết luận do LLM viết không được thay verdict máy kiểm.

Task/spec đăng ký và release hash gốc được lưu thêm trên laptop trong receipt mà Muse không sửa được. Verifier đối chiếu bộ task được giao với toàn bộ artifact trả về, tính lại counts/metric từ ledger và kiểm replay trên oracle/pilot; acceptance độc lập phải chạy bằng release đã khóa. Chỉ so checksum do cùng một agent tự tạo lại không chứng minh báo cáo trung thực. Khi nghi ngờ kết quả, laptop phải tái chạy thí nghiệm từ bundle đã kiểm trước khi dùng kết quả đó để promote.

Gói portable bao gồm source đã nhận, fixtures nhỏ tự chứa, dependency lock, schemas/spec examples, manifest, runbook và acceptance cases. Loại credential, account fingerprint, terminal data path, `phien_demo`, live store/logs, CONTROL/dispatch nội bộ và skill cá nhân. Dữ liệu thị trường lớn giữ trong data store có manifest, theo quyền sử dụng của nguồn; không mặc định đưa vào Git.

## 8. Cách giao việc để Muse ít phải suy diễn

Muse chỉ được bắt đầu sau H7. Một task chỉ có một spec đã đăng ký và một output root. LLM đọc spec, gọi công cụ và tóm tắt kết quả; số liệu/metric/đạt-trượt được engine và verifier tính.

Task template bắt buộc:

```text
Task ID / prerequisite acceptance IDs:
Mục tiêu và claim cần kiểm:
Release manifest / environment lock hash:
Data manifest, split, exposure và source policy:
Experiment ID / spec hash / policy hash:
Lệnh cho phép đã kiểm trong runbook:
Output root / thời hạn / memory / worker / retry budget:
Artifact bắt buộc và lệnh verify:
Mã lỗi có thể retry; mã lỗi phải dừng:
Điều kiện hoàn tất và điều kiện trả INCONCLUSIVE:
Những thay đổi cần đề xuất bằng task mới:
```

Quy tắc vận hành:

- Không sửa source đã khóa, spec, expected test, split hoặc ngưỡng kết luận trong lúc task chạy.
- Unknown field, hash mismatch, invalid prices, data gap ảnh hưởng claim, source thay hoặc metric bất thường -> ghi artifact và dừng task tương ứng. Không tự vá kết quả.
- Retry chỉ dành cho lỗi kỹ thuật đã phân loại, cùng danh tính thí nghiệm. Thử lại với tham số khác là trial mới và cần đăng ký trước.
- Báo task thất bại/không có edge đầy đủ như task thành công. Không được loại run xấu khỏi registry.
- Không tiếp cận final-forward evaluation ngoài lịch checkpoint; dashboard sức khỏe chỉ hiển thị coverage/process/storage, không tự chọn champion theo P&L đang chạy.
- Code improvement của Muse nếu về sau được giao thì nằm ở nhánh/repo nghiên cứu riêng và cần review. Runner dùng release bất biến đã nhận.

Tài nguyên cho máy người dùng mô tả 4 CPU/8 GB, không GPU: khởi đầu 1 worker, BLAS thread = 1, xử lý tick theo symbol/chunk. Trước run đo RAM/disk thực sự còn trống. Memory budget đề xuất tối đa min(2 GiB, RAM available lúc bắt đầu - 1 GiB), giảm chunk khi cần; không đủ headroom thì task trả RESOURCE_PENDING. Tăng lên 2 worker chỉ sau benchmark RSS/throughput đạt, không dựa vào số vCPU đơn thuần.

Scheduler/cron cụ thể sẽ cấu hình sau nghiệm thu môi trường. Lượt lập kế hoạch này không tạo automation, daemon hoặc tiến trình nền.

## 9. Nhánh forward native và FTMO

Nhánh này không chặn bàn giao nghiên cứu lịch sử đã đạt H7, nhưng bắt buộc trước khi tuyên bố Muse là node forward đáng tin.

**F1 — Băng native và outcome tracker:** thu tick bền vững, coverage theo request/source, duplicate/restart recovery, source identity pin và quote/bar watermark tách biệt. Outcome tracker phân biệt decision snapshot và evidence bổ sung sau đó; giữ event append-only và trạng thái unresolved. Không viết lại quyết định cũ bằng dữ liệu backfill đến sau.

**F2 — Acceptance môi trường:** Wine/MT5/Windows Python/module native là spike riêng. Soak 24 giờ gồm đóng ứng dụng Muse, reconnect, restart collector, mất mạng và dừng có kiểm soát. Thời gian soak cần bao gồm phiên thị trường mở; 24 giờ cuối tuần không chứng minh tick collection khi có giao dịch. Một ngày đạt không chứng minh lịch sử DST hoặc SLA 24/7.

**F3 — Kiểm luật quỹ:** đọc acceptance gần nhất của evaluator FTMO, khóa profile/rule vintage và các giả định risk theo lựa chọn người dùng. Cần marked equity, floating P&L, fees/swap, reset/DST và prior account state phù hợp. Không dùng closed-trade bootstrap để chứng nhận không breach intraday. Monte Carlo sau đó dùng block ngày và joint exposure, phân biệt xác suất mô phỏng với pass challenge thực.

Nhãn readiness riêng:

- `MUSE_HISTORICAL_RESEARCH_READY`: H0–H7 đạt.
- `MUSE_NATIVE_FORWARD_READY`: F1–F2 và kiểm liên quan đạt, đúng source được chọn.
- `FTMO_SIMULATION_READY`: evaluator/rules/equity/risk contract đã nhận và đủ input.
- `EDGE_SUPPORTED`: kết quả nghiên cứu/forward đủ bằng chứng trong phạm vi đã đăng ký; không đồng nghĩa challenge đã pass.

## 10. Thứ tự bắt đầu sau khi kế hoạch được duyệt

1. Giao H0–H1 thành work order đầu tiên: đóng băng nền, contract, fixture và runner mẫu tự chứa. Nghiệm thu xong mới giao gói kế.
2. H2 làm adapter trên pilot nhỏ, kiểm price/time/volume/coverage rồi nghiệm thu.
3. H3–H4 bổ sung nearest-level TP và nối batch tick replay, giữ regression baseline và portfolio.
4. H5–H6 hoàn thiện phép so sánh, verifier, adversarial/portable acceptance.
5. H7 đóng gói; chỉ sau đó gửi Muse một task pilot đã khóa. Tải rộng 10 năm theo khả dụng từng mã sau khi pilot nguồn đạt.
6. Đăng ký W1 thực tế; SL nâng cao, forward native và FTMO đi theo các gate tương ứng.

Các lựa chọn cần khóa khi đăng ký nghiên cứu, chưa chặn việc thiết kế phần mềm: ngày bắt đầu/kết thúc theo nguồn thực có; D1/session convention; cost/latency/risk assumptions; trial/alpha budget; precision/effect size; checkpoint forward. Các trường chưa chốt giữ `UNCONFIGURED` và chặn verdict khoa học liên quan. Không yêu cầu người dùng đoán các số này trước khi H0/H2 cung cấp thông tin nền.

## 11. Cơ sở tham khảo

- [Dukascopy Historical Data Export](https://www.dukascopy.com/swiss/english/marketwatch/historical/): nguồn xuất dữ liệu cần kiểm pilot và tính khả dụng theo instrument/date.
- [Dukascopy ITick API](https://www.dukascopy.com/client/javadoc3/com/dukascopy/api/ITick.html): phân biệt Bid/Ask price và size tại mức giá tốt nhất; lịch sử qua API này không tự cung cấp đầy đủ depth như live.
- [Bailey và cộng sự — The Probability of Backtest Overfitting](https://www.davidhbailey.com/dhbpapers/backtest-prob.pdf): cơ sở yêu cầu ghi thử nghiệm và kiểm soát quá trình lựa chọn chiến lược từ nhiều phép thử.
- [R stats — p.adjust](https://stat.ethz.ch/R-manual/R-devel/library/stats/html/p.adjust.html): đối chiếu Holm/FWER khi nghiệm thu hàm hiệu chỉnh; family và các p-value đầu vào vẫn phải được định nghĩa trước.

Các ngưỡng tài nguyên, thứ tự wave, ID/gói/schema và cổng ở tài liệu này là đề xuất thiết kế cho project, không phải kết luận thị trường hoặc tính năng đã tồn tại.

## 12. Receipt của lượt lập kế hoạch

Đã đọc mã nguồn/config và bằng chứng nghiên cứu liên quan; đã kiểm tài liệu chính thức nguồn dữ liệu và phương pháp thống kê. Đầu ra của lượt này là tài liệu kế hoạch. Chưa triển khai code, cài dependency, chạy backtest/native smoke, tạo repo/token, gửi việc cho Claude/Muse hay bật tiến trình nền.
