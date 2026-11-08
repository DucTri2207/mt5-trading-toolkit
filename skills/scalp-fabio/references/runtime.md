# Runtime Scalp Fabio

CLI đã cài: `D:/trading thử lần cuối cuối/quant_mt5/quant.cmd`.
Python của CLI: `C:/Users/ductr/AppData/Local/Programs/Python/Python313/python.exe`.
Code thực: `D:/trading thử lần cuối cuối/quant_mt5/quantmt5/fabio.py` và `fabio_replay.py`.

Dùng đường dẫn/workdir tuyệt đối. Đọc `fabio --help`, `fabio-replay --help` hoặc `session --help` nếu CLI thay đổi. Các chuỗi `<...>` trong mẫu phải được thay bằng output/path thật, không chạy nguyên mẫu.

## Đọc artifact có sẵn

Đọc JSON/Markdown người dùng chỉ định. JSON CLI có thể bọc analysis trong `data`; artifact lưu có thể là analysis trực tiếp. Kiểm `schema`, `snapshot_id`, `symbol`, `as_of`, `policy`, `spec_id`, `spec_version`, `spec_hash`, `inputs`, source và nhãn provider. Giữ giờ quan sát lịch sử, không gọi là hiện tại.

Policy mới yêu cầu `policy=scalp_mt5_v1`, `spec_id=SCALP_FABIO_MT5_V1` và hash đúng spec của engine đã tạo artifact. Hash không khớp phiên bản mong muốn thì báo mismatch; không diễn giải artifact thành bản mới chỉ vì có F1/F2. Legacy `FABIO_FTMO_V1` v1.1.0 vẫn đọc được nhưng có F1 D1-target và vòng đời cũ, phải ghi rõ khi so sánh. Khi chỉ đọc report không chạy lại detector hoặc bất kỳ thao tác lấy nguồn nào.

Đọc tất cả families. Nhãn flow/profile nằm ngay trong output các gates và `flow`/`mt5_inputs`; thiếu các trường không có nghĩa giá trị 0. Kiểm `opportunity_id`, `revision_id`, `trigger_id` và plan nếu hiện diện. Chỉ thêm suy xét bằng lời, không sửa artifact immutable để đủ schema.

Đọc `profile_lifecycle` và so `episode_key`/`profile_revision_id` với observation trước nếu có. Chuỗi `FROZEN_PREVIOUS_ANALYSIS_CHAIN` giữ bins/target từ artifact trước; snapshot độc lập với coverage/basis khác là revision tái dựng. Artifact quyết định cũ giữ nguyên để replay. Không mặc định trigger mất đi trong bản tái dựng nghĩa là trigger cũ chưa từng tồn tại.

## Một lượt dữ liệu mới

Chỉ áp dụng khi người dùng yêu cầu phân tích/cập nhật thị trường. Nếu lượt hiện tại đã có snapshot hợp lệ, chuyển thẳng sang gọi Fabio trên snapshot đó.

1. Lấy root/name/terminal/symbol mapping người dùng đã chọn từ phiên/runbook `D:/trading thử lần cuối cuối/quant_mt5/TRADE_TOI.md`. Chạy readiness không attach và preflight của phiên. READY_TO_ATTACH chỉ xác nhận packages/process/pins; collector trong once mới kiểm source identity và trade_mode demo trước đọc. Thiếu terminal thì PENDING để người dùng mở MT5 demo. Không tự mở/đổi account.

```powershell
& 'D:/trading thử lần cuối cuối/quant_mt5/quant.cmd' readiness --no-attach
& 'D:/trading thử lần cuối cuối/quant_mt5/quant.cmd' session preflight --root '<root>' --name '<name>'
```

2. `ENGINE_OR_CONFIG_CHANGED`: tạo tên phiên mới ghim engine hiện tại khi đang thực hiện yêu cầu lấy dữ liệu mới; giữ terminal/mapping đã chọn. Không chỉnh hash phiên cũ. Mẫu tạo phiên dùng mapping thật, `--symbols` nhận `canonical=native` phân cách dấu phẩy, ví dụ `XAUUSD,EURUSD=EURUSD.r`; tên native phải được xác minh. Có thể dùng preset main8/extended12 chỉ khi mapping đó đúng nguồn. Index chưa được map/đủ metadata phải báo riêng. Dầu ngoài phạm vi hiện tại.

```powershell
& 'D:/trading thử lần cuối cuối/quant_mt5/quant.cmd' session init --root '<root>' --name '<new_name>' --terminal-path '<selected_terminal64.exe>' --symbols '<verified_symbol_map>' --ftmo-program UNVERIFIED
& 'D:/trading thử lần cuối cuối/quant_mt5/quant.cmd' session preflight --root '<root>' --name '<new_name>'
```

`--ftmo-program` chỉ là nhãn bối cảnh, không xác minh tài khoản. Các trường FTMO/selection_ref kế thừa trong phiên cũ không chứng minh người dùng đã dùng FTMO.

3. Một `session once` hữu hạn để thu và dựng snapshot. Dùng `full` cho yêu cầu Fabio độc lập. Nếu đang cùng workflow `trade-toi` đã có baseline PENDING, trình bày đủ A rồi `session enrich` đúng continuation đã nhận; không collect lần nữa.

```powershell
& 'D:/trading thử lần cuối cuối/quant_mt5/quant.cmd' session once --root '<root>' --name '<name>' --analysis-mode full --max-cards 3
```

Lấy cycle/snapshot/bundle/generation/report từ JSON output chính lượt này. Đọc trạng thái lỗi từng mã. Nếu cùng cycle trả CONTEXT_PENDING, tiếp tục enrich bằng IDs continuation hiện có:

```powershell
& 'D:/trading thử lần cuối cuối/quant_mt5/quant.cmd' session enrich --root '<root>' --name '<name>' --expected-cycle '<cycle_id>' --expected-generation '<generation_id>' --expected-snapshot '<snapshot_id>' --context-timeout 30 --max-cards 3
```

4. **Chọn Fabio policy mới tường minh**, từng mã trong universe đã ghim. `session exec -- ... --snapshot` tự chọn config bundle của snapshot đó và store của phiên. `--report` là path tuyệt đối trong output phiên. Batch legacy không thay cho bước này.

```powershell
& 'D:/trading thử lần cuối cuối/quant_mt5/quant.cmd' session exec --root '<root>' --name '<name>' -- fabio --snapshot '<snapshot_id>' --symbol '<canonical_symbol>' --policy scalp_mt5_v1 --report '<absolute_output_report.md>'
```

Nếu đây là lần quét tiếp nối, lấy artifact scalp gần nhất có `as_of <= snapshot.as_of`, cùng source/spec/mã từ report hoặc `store/fabio_ledger` rồi thêm `--previous-analysis '<absolute_previous_artifact.json>'`. Tham chiếu phải tới artifact quyết định thật; không truyền snapshot muộn hơn. Engine ghim hash của artifact đó, kiểm prefix OHLC/volume/time, giữ profile/target đã biết và chỉ mở episode mới khi có balance mới hợp lệ. `FABIO_PREVIOUS_*` là lỗi cần giải thích; không bỏ option rồi âm thầm gọi lại để lấy tín hiệu khác. Lần đầu không có artifact tương thích thì ghi rõ khởi tạo tái dựng độc lập.

Không truyền `--flow`/`--exec` để bù dữ liệu vận hành: đây là override chẩn đoán offline. Mặc định Fabio tự đọc tick/quote/profile đã ghim; phí thiếu vẫn UNKNOWN. Mọi mã đều có kết quả hoặc lỗi cụ thể. Không dùng `max_cards` cắt bớt universe.

Kiểm policy/spec/hash trả về trước diễn giải. Analysis lưu tại `store/fabio/<snapshot_id>/...json`; đọc `artifact_path` thật từ output. Cơ hội có ID mới được lưu vào ledger Fabio riêng theo engine. Không dùng `quant replay --candidate` hoặc `note add` với ID Fabio.

## Lưu observation

Báo cáo máy sinh từ cùng result. Viết thêm phần suy xét bằng tiếng Việt tại output phiên và dẫn artifact. Có thể ghi observation với cùng snapshot khi cần nhật ký:

```powershell
& 'D:/trading thử lần cuối cuối/quant_mt5/quant.cmd' session exec --root '<root>' --name '<name>' -- journal add --kind observation --snapshot '<snapshot_id>' --text '<short_observation_with_Fabio_IDs>' --author codex
```

Không đưa nội dung chứa shell substitution vào command nối chuỗi; dùng quoting PowerShell đúng hoặc đọc nội dung từ file theo giao diện công cụ. Không gắn `--candidate` bằng một ID Fabio. Xác nhận kết quả lệnh trước nói đã ghi journal.

## Replay hữu hạn khi được yêu cầu

Replay cần analysis có `families.F1.research_plan` hoặc `families.F2.research_plan` đã khóa, outcome snapshot có tick tương lai cùng source/config hợp lệ và kịch bản khai báo. Plan có `known_at`, `expires_at`, `sl_chart`, `target_chart`, `trigger_close`, `atr_frozen`, `tick_size`, `chart_basis`, `source_fingerprint`. Kiểm policy/spec/source cùng IDs, không đổi tên field/hash của bản khác để ép chạy. Giữ nguyên artifact quyết định; outcome snapshot chỉ cung cấp đường giá sau quyết định. Không chạy thêm lượt native để cố hoàn tất outcome trong yêu cầu đọc artifact.

Cú pháp đã kiểm bằng `fabio-replay --help`; cùng session/store có analysis snapshot và outcome snapshot. Truyền `--snapshot` tường minh để `session exec` chọn bundle đúng:

```powershell
& 'D:/trading thử lần cuối cuối/quant_mt5/quant.cmd' session exec --root '<root>' --name '<name>' -- fabio-replay --analysis '<absolute_analysis.json>' --family F1 --snapshot '<outcome_snapshot_id>' --latency-s '<declared_latency_seconds>' --max-hold-s 1800
```

Lệnh trên để commission/slippage **UNKNOWN**: chỉ dùng diễn biến/gross diagnostic, không kết luận net đã xác minh. `latency-s` là kịch bản độ trễ khai báo, không phải số đo; bỏ option này có default 0 nên không được diễn giải là đã đo đường truyền tức thời. Nếu chưa có snapshot muộn hơn, truyền analysis snapshot và giữ kết quả CENSORED/UNRESOLVED khi chưa có đủ đường giá tương lai.

Khi nghiên cứu một kịch bản phí đã khai báo trước, thêm `--commission-price-rt <price_units_round_trip>` và `--slippage-price <price_units_per_market_leg>`. Hai giá trị là đơn vị **giá**, không phải lot/USD/points; slippage tính cho từng market leg, commission cho round trip. Đủ hai giá trị vẫn mang nhãn **ASSUMED**, không thành phí account đã xác minh. Không tự dùng 0 thay cho số còn thiếu. TP và stop/time-exit có mô hình slippage được adapter công bố; không trừ spread lần hai.

Kết quả có `replay_id`, status/reason, scenario, quote/coverage/source và `artifact_path` dưới `store/fabio_replay/` khi lưu. `--no-store` chỉ dùng khi muốn tính offline không ghi artifact. Không dùng ID Fabio làm candidate A/B. Giữ cả SKIPPED/no-fill/EXPIRED/UNRESOLVED/CENSORED, không bỏ dòng thiếu outcome khỏi mẫu âm thầm. Tick bị purge hoặc lỗi checksum phải hiện lỗi, không thay bằng M1 rồi gọi tick-exact.

## Lượt cuối

Chỉ khi người dùng xác định lượt cuối/kết phiên: lưu đầy đủ analysis/nhận định, dùng `finish_token` của báo cáo cuối hợp lệ; baseline PENDING không có token dọn. Gọi finish bằng đúng cycle/generation/snapshot, không tự đoán hoặc lấy token phiên trước.

```powershell
& 'D:/trading thử lần cuối cuối/quant_mt5/quant.cmd' session finish --root '<root>' --name '<name>' --expected-cycle '<token.cycle_id>' --expected-generation '<token.generation_id>' --expected-snapshot '<token.snapshot_id>'
```

CLOSED/receipt mới xác nhận dọn tick; báo cáo, bars và journal vẫn giữ. Sau purge không replay exact lại được. REFUSED hoặc CLEANUP_PARTIAL xử lý theo receipt/guard, không xóa bằng shell hay sửa IDs để ép thành công.
