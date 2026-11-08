# Kế hoạch nâng cấp quét và phân tích ca tối

Ngày nghiên cứu: 08/11/2026, giờ Việt Nam. Trạng thái: NGHIÊN CỨU XONG, SẴN SÀNG TRIỂN KHAI; chưa sửa engine/config vận hành, chưa xóa tick.

## 1. Mục tiêu và phạm vi

Yêu cầu: quét theo lần người dùng gọi, thường cách nhau 20 phút trong buổi tối; mở rộng nhiều cặp tiền; bỏ dầu; phản hồi nhanh hơn và cho biết sớm vùng cần theo dõi; xóa tick sau lượt quét cuối ngày.

Ba kết quả cần đạt riêng biệt:

1. Tốc độ: giảm đọc/thu/tính lặp, đo toàn bộ thời gian tới báo cáo máy và thời gian tới nhận định của agent.
2. Khả năng sử dụng: thấy vùng chờ trước trigger, biết điều kiện còn thiếu và kiểm lại một mã sát lúc quyết định.
3. Hiệu quả giao dịch: đo trên các phiên mới, sau phí, theo cơ hội độc lập. Tăng tốc/mở rộng mã không tự chứng minh tỷ lệ thắng tăng.

Tuần 02–08/11: A/M0 có 8 thắng/10 lệnh đóng, tổng +0,430R; A/M1 có 8 thắng/9 lệnh, +5,430R. Đây là các nhánh chồng lặp trên mẫu rất nhỏ, phí giả định; không cộng thành hai tập độc lập, không chọn M1 làm chuẩn mới chỉ vì tuần này đẹp. Giữ quy tắc A/B và các nhãn Fabio; bổ sung báo cáo và tối ưu triển khai trước.

Ca tối mặc định là các lượt người dùng gọi từ khoảng 18h trở đi. Đo riêng 18–19h, 19–20h, 20–21h và ngoài khung đó; không tự đóng phiên lúc 20h/21h. Ngày kết phiên xác định bằng Asia/Ho_Chi_Minh và yêu cầu “lượt cuối hôm nay”.

## 2. Bằng chứng từ hệ thống đang chạy

Runtime thực tế: D:/trading thử lần cuối cuối/quant_mt5/quantmt5. Các thư mục Muse/staged/phases là bản nghiên cứu riêng, không coi là chức năng runtime đã có.

| Phát hiện | Bằng chứng trong runtime | Hệ quả |
|---|---|---|
| Chỉ có ba mã trong profile/cost | config/symbol_profiles.json; config/cost_profiles.json | Thêm tên mã chưa đủ để vận hành |
| Missing cost có thể làm hỏng cả snapshot | snapshot.py:191 lấy spread_floor_points[sym]; execution.py:544 lấy slippage_points_per_side[symbol] | GBPUSD mới có thể gây KeyError dù không có candidate |
| Cửa sổ lấy nến dịch theo thời gian gọi | paper.py:195; collector.py:260–267 | Cache theo w0/w1 chính xác có thể tải chồng lịch sử |
| Replay trước khi kiểm trùng journal | paper.py:140–163; replay.py:138–150 | Cùng symbol/candidate bị load/detect/tick-verify nhiều lần |
| Mỗi thẻ mở hai process riêng | session.py:566–567; context.py:443 đã gọi build_context trong card | Tối đa 8 thẻ tạo 16 process, tính context lặp |
| Tick flow đọc NPZ hai lần | mt5_flow.py:66–80; mask theo bar tại :204 | Tốn I/O, decode và RAM khi tape dài |
| Báo cáo ưu tiên candidate mới nhất trong 24h | session.py:556 | Vùng đang chờ và tín hiệu còn hạn chưa được ưu tiên đúng |
| Đã có dữ liệu vùng chờ để tái dùng | snapshot.py:286; detectors.py:241; context.py:250–263 | Không cần tạo một engine chiến lược mới |
| Cửa sổ entry chỉ 90 giây | config/strategy_v0_1.json: common.entry_deadline_s_after_signal_close | Quét mỗi 20 phút vẫn bỏ lỡ dù chạy nhanh |
| Chưa có theo dõi outcome forward hoàn chỉnh | session.py:115 | Không thể coi journal hiện tại là sổ hiệu quả forward đầy đủ |
| Chưa có kết ngày và dọn tick | session CLI, session.py:459, :632 | once/stop không đồng nghĩa lượt cuối ngày |

Các số dòng là vị trí tại lúc kiểm tra; khi code thay đổi cần tìm lại đúng hàm.

### Đo và quan sát hiện có

- Máy: Intel Core i5-12450H, 8 core/12 logical processor; RAM 7,63 GiB; ổ D 150 GiB, còn khoảng 51,46 GiB tại thời điểm kiểm tra.
- Timing cũ trong cycles.jsonl: 9,30 / 15,11 / 24,14 giây ở toi_nay; 11,53 giây ở hom_nay_20261105. duration_s kết thúc trước build_report, chưa gồm card/context và thời gian agent.
- Probe offline một lần trên EURUSD của snapshot SNAP_f05620cbbcb761935e5c: load_symbol 0,455s; detect_all 0,072s; read_snapshot_mt5 2,560s; 35.916 nến M1, 7.187 nến M5, 1.441 tick chunks. Snapshot cuối tuần trả NO_USABLE_BARS nhưng vẫn đọc tape. OS cache chưa kiểm soát; đây không phải p95 hay benchmark live.
- Phiên toi_nay sau ba lượt có EURUSD M1 90 chunks/107.475 dòng cộng theo chunks, M5 15 chunks/21.522 dòng. Không gọi các tổng này là số nến duy nhất. Có lỗi SOURCE_CONFLICT:DUPLICATE_BAR_DIFFERENT_VALUES; phải xác định revision, không bỏ kiểm conflict để chạy nhanh.

## 3. Mở rộng danh sách mã

Triển khai hai đợt, cùng một hệ thống preflight và báo cáo trạng thái:

| Đợt | Danh sách đề xuất | Tổng |
|---|---|---:|
| 1 | XAUUSD, EURUSD, USDJPY, GBPUSD, USDCAD, USDCHF, AUDUSD, NZDUSD | 8 |
| 2 | Thêm EURJPY, GBPJPY, EURGBP, AUDJPY | 12 |

XAUUSD/EURUSD/USDJPY đã có runtime. GBPUSD/USDCAD/USDCHF có dấu vết lịch sử trong reports/can_ho_tro_scalp/20261101_intermarket_v9/FX_DATA_MANIFEST.json; vẫn phải kiểm lại broker hiện tại. AUDUSD/NZDUSD và các cross là danh sách đề xuất, chưa được xác nhận trong lượt nghiên cứu này.

Dầu bị loại khỏi allowlist: WTI/Brent và alias broker như USOIL, UKOIL, XTIUSD, XBRUSD khi mapping tương ứng. Không suy USDCAD là dầu; đó vẫn là cặp FX. Chỉ số và mã khác chưa có trong đợt nâng cấp này.

Preflight từng mã phải trả đủ:

- canonical/native mapping; trạng thái broker có mã hay không; không tự chọn một suffix mơ hồ.
- chart basis, tick size, point, digits, contract size, currency, volume limits, stops/freeze và calc mode từ nguồn đã chọn.
- lịch phiên/coverage và time basis, ghi OBSERVED/ASSUMED/UNKNOWN rõ ràng.
- capabilities: đọc giá/context; xác định setup; dữ liệu tick flow; tính phí/room; không gộp tất cả thành một nhãn supported.
- requested/available/context-only/blocked/missing/excluded để đủ số lượng mã người dùng yêu cầu. Một mã hỏng không làm mất kết quả các mã còn lại.

Thiếu cost phải giữ context/zone nếu đủ dữ liệu; execution ở WAIT/ECONOMICS_UNKNOWN, không thay thiếu bằng 0. Nhánh nghiên cứu dùng cost giả định phải giữ nhãn ASSUMED, không chuyển thành chi phí đã đo.

Cross không có USD cần tỷ giá quy đổi phí cùng snapshot và đúng thời điểm biết. execution.make_params hiện chỉ xử lý profit_currency=USD hoặc base_currency=USD với price_hint. Chưa đủ quy đổi thì chỉ phân tích vùng, chưa kết luận room ròng/lot hợp lệ. Không đọc commission từ symbol_info như thể trường đó tồn tại.

## 4. Nâng tốc độ theo thứ tự ít thay đổi nhất

### P0 — Đo đúng và xác nhận dữ liệu

- Thêm telemetry cho preflight, collect bars/ticks, verify/decode, detect, replay, Fabio, context, report, tổng lượt; số request/chunk/byte, cache hit, peak RAM.
- Lưu snapshot_as_of, computed_at, report_ready_at, analysis_completed_at và quote_age riêng. Không gọi thời gian process con là thời gian trả lời hoàn chỉnh.
- Kiểm clock trên nguồn đang mở ở lần triển khai: raw tick time, thời gian máy UTC, request bounds, bar boundary. Tài liệu MetaQuotes nói API dùng UTC, trong khi archive hiện có profile EET_EU giả định từ probe. Cần giải quyết bằng bằng chứng nguồn; không chuyển offset hai lần hoặc sửa timestamp archive cũ.
- Kiểm các lỗ coverage đã có. Warmup phải đủ ATR/EMA; không cắt history tùy tiện để lấy tốc độ.

### P1 — Thu tăng dần, tái dùng dữ liệu trong một lượt

- Cố định cửa sổ thu theo mốc và clock đã ghim. Lượt sau chỉ lấy phần mới, phần thiếu cần retry và tail chưa final.
- Bars final không thay âm thầm; revision nguồn có lineage riêng. Raw payload/snapshot cũ giữ nguyên. Tại as-of cũ vẫn chỉ thấy revision đã biết khi đó.
- Một process phân tích trong đúng bundle; load dữ liệu và detector catalog theo symbol một lần rồi dùng cho snapshot, replay, context và báo cáo.
- Cache cục bộ có key gồm source identity, symbol, content pins, clock/time contract, config/engine, cutoff và nhóm feature. Context decision và as-of không dùng chung kết quả sai thời điểm.
- Batch card/context một lần; không gọi hai CLI cho từng thẻ. Giữ CLI card/context riêng để tra cứu khi cần.
- Chỉ tính lại replay mới/chưa kết thúc hoặc có dữ liệu mới ảnh hưởng outcome. Kiểm trùng bản ghi trước công việc nặng; outcome sau phải là record cập nhật riêng, không bị dedup candidate nuốt mất.

### P2 — Tối ưu tick flow và phạm vi tính sâu

- Hash/decode mỗi chunk cần dùng một lần trong một worker; source-order validation thực hiện trên thứ tự gốc, trước khi sort để replay.
- Dùng chỉ mục thời gian/searchsorted và lát cắt cho từng bar, vẫn giữ điều kiện available_at, multiplicity tick cùng mili giây, gap và reset CVD.
- Có thể trả early NO_USABLE_BARS trước decode nếu chứng minh được từ metadata/closed bars; phải khai báo integrity NOT_CHECKED ở đường đó. Không báo dữ liệu tick đã xác minh khi chưa đọc/kiểm.
- Mọi mã đã yêu cầu vẫn được quét cấu trúc giá và có trạng thái. Phân tích tick/profile sâu ưu tiên tất cả candidate còn hạn và một số vùng chờ gần nhất; phần chưa chạy phải ghi DEFERRED, không đổi thành NO_SIGNAL.
- Phạm vi Fabio/coverage phải hiện rõ khi chia hai tầng. Không âm thầm giảm số mã phân tích rồi gọi đó là cùng một full scan nhanh hơn.
- Bắt đầu thu MT5 tuần tự. Nếu benchmark còn cần, thử tối đa hai worker CPU trên dữ liệu đã ghim; giới hạn RAM quan trọng hơn số logical CPU trên máy khoảng 8 GiB. Không tự giả định API MT5 an toàn khi gọi song song.
- Chưa thêm daemon, Redis, database hay model học mới. Tái dùng NumPy, snapshot và journal đang có.

### Chỉ tiêu đề xuất, chưa đạt/chưa đo

| Luồng | Mục tiêu nghiệm thu ban đầu |
|---|---|
| Warm scan 8 mã, đủ structured report | p95 <=30s |
| Warm scan 12 mã, đủ structured report | p95 <=45s |
| Kiểm nhanh một mã gần entry | p95 <=5s, không tính thời gian LLM |
| So cùng workload trước/sau | Giảm >=50% thời gian xử lý nội bộ khi không bị mạng/MT5 chi phối |
| Bộ nhớ tăng thêm của toàn cây process | Mục tiêu <=1 GiB; ghi peak thực tế |

Cold bootstrap, mạng/terminal đang đồng bộ, và full deep-analysis mọi mã phải báo riêng. Không gọi target là cam kết. Đo >=20 lượt warm có phân bố ca không tín hiệu/nhiều candidate/lỗi một mã; p50/p95/max, bytes, request, peak RAM và chất lượng đầu ra. Không dùng 20 lần cùng một file nóng làm bằng chứng live.

## 5. Phân tích vùng vào cho ca tối

Tái dùng episode WATCHING_RETEST của A và state/location của Fabio khi output đủ bằng chứng. Setup B hiện chỉ phát candidate sau khi mẫu mother/inside/fakey hoàn tất, episode_id=None; bản đầu hiển thị candidate B đã xác nhận và context vùng liên quan. WATCH trước trigger cho B cần một đặc tả precursor/expiry/điều kiện hủy riêng, chưa coi là khả năng sẵn có. Không thay vùng anchor đã đóng băng của Setup A bằng rolling H1 range dùng để mô tả thị trường.

Luồng mỗi lần gọi:

    Quét toàn bộ danh sách → xác định vùng đang chờ/tín hiệu còn hạn
    → phân tích sâu cơ hội ưu tiên → lưu phản chứng và điều kiện hủy
    → kiểm lại một mã khi người dùng gọi sát trigger → kết luận theo dữ liệu mới.

Báo cáo ngắn mỗi mã gồm:

- Trạng thái: WATCH, CANDIDATE, EXPIRED, BLOCKED hoặc DATA_UNAVAILABLE; CANDIDATE không có nghĩa đã qua gate tài khoản hay đã gửi lệnh.
- Zone low/high, nguồn vùng/episode, thời điểm biết, khoảng cách giá tới vùng tính bằng ticks và ATR, hướng tiếp cận.
- Điều đã có, trigger còn thiếu, mốc vô hiệu, expiry. Chưa có trigger thì không bịa candidate hoặc entry/SL/TP.
- Với candidate hợp lệ: entry/SL/TP theo đúng card, Bid/Ask hiện tại, spread, phí và room có nhãn nguồn, thời gian còn lại tới deadline.
- Kịch bản chính và bằng chứng bác bỏ mạnh nhất. CVD quote-direction vẫn là proxy, không thêm một phiếu order-flow độc lập.
- Mốc dữ liệu, lúc tính xong, tuổi quote, snapshot ID; trình bày UTC+7 cho người dùng.

Ưu tiên hiển thị: candidate còn hiệu lực và đủ dữ liệu → vùng chờ gần giá → blocked/expired. Xếp hạng theo trạng thái và khoảng cách có giải thích, không gán xác suất thắng hay điểm AI thành phần trăm.

Khi cần xác nhận trước entry, lấy snapshot mới cho mã được kiểm, liên kết snapshot/episode cũ. Kiểm lại cấu trúc và expiry bằng dữ liệu mới; không kéo dài deadline để cứu tín hiệu đã hết hạn. Trước khi agent đưa kết luận vào/chờ, kiểm thời gian thực đã trôi qua; quá hạn phải đổi sang EXPIRED/WAIT.

20 phút là nhịp quan sát rộng. Ví dụ tuần vừa rồi EURUSD/A lúc 18:15 và 18:30 hết hạn ở 18:16:30 và 18:31:30; nhịp 18:00/18:20/18:40 không bắt được. Chế độ người dùng gọi kiểm sát nến M5 phải được phân biệt với kết quả quét 20 phút. Chưa bật theo dõi nền hoặc báo tự động giữa hai lần gọi.

Tin tức: hiện context.news_calendar=UNKNOWN. Mỗi phiên cần một snapshot lịch tin có nguồn, thời điểm lấy, timezone và những currency bị ảnh hưởng; có thể thu qua bước nghiên cứu của agent, không bắt CLI tự scrape nhiều nguồn. Không có nguồn thì giữ UNKNOWN. Đo riêng tình huống trước/sau tin, không chọn một khoảng tránh tin tối ưu từ đúng tuần cũ.

Nhiều mã cùng USD/JPY phải hiển thị nhóm exposure cùng hướng. Đây là mô tả tập trung rủi ro; không coi 5 tín hiệu liên quan là 5 bằng chứng độc lập, cũng chưa thêm ngưỡng correlation tùy ý.

## 6. Xóa tick sau lượt cuối ngày

### Hợp đồng vận hành

Người dùng nói “quét lần cuối hôm nay” hoặc “kết phiên”. Agent chạy lượt quét hữu hạn, hoàn thành context/card/phân tích và lưu nhật ký trước, sau đó gọi thao tác kết ngày. Không suy lượt cuối từ việc người dùng im lặng hoặc từ đồng hồ 20h.

Giao diện dự kiến: thêm action session finish vào CLI hiện có, nhận root/name và cycle/snapshot cần kết thúc. Đây là ĐỀ XUẤT, CLI hiện tại chưa có. Không dùng session stop thay thế; stop chỉ dừng runner.

Để tránh xóa trước khi agent đọc/ghi note, finish là bước riêng sau once và phân tích. Tất cả file cần cho báo cáo cuối phải được commit xong trước bước này. Trong cùng khóa storage, finish đối chiếu ID phiên, expected_generation_id, cycle/report cuối đã hoàn tất và ngày Việt Nam. Nếu có lượt mới hơn thì trả STALE_FINALIZATION_REQUEST; không áp báo cáo cũ cho generation/lượt mới dù cùng phiên/ngày.

### Xóa và giữ gì

Xóa toàn bộ dữ liệu tick thô thuộc generation vận hành của phiên đã kết: accepted NPZ, pending payload, tick conflict/quarantine và checkpoint đang hoạt động. Bao gồm tick warmup của generation đó, không chỉ file có mtime trong hôm nay. Không giữ lén raw tick windows dưới tên cache khác.

Giữ nến M1/M5/H1/D1, báo cáo Markdown/JSON, card/context/zone summary, các quote entry/exit đã quan sát, feature/CVD/profile dẫn xuất, journal, outcome đã biết, config, identity, clock và metadata/hash của dữ liệu đã xóa. Các quote rời/summary không thay thế băng tick đầy đủ.

Phạm vi duy nhất: thư mục raw tick của phiên vận hành được chọn, mọi đường dẫn được resolve và kiểm nằm trong namespace ấy. Không xóa kho tuần weekly_fabio_20261102_08, store nghiên cứu/training, phiên khác hay dữ liệu MT5 trong AppData. Generation mới phải có ownership riêng và đăng ký consumer từ bundle/snapshot được quản lý; nếu có consumer được bảo vệ ngoài phiên trỏ vào chunk thì trả SHARED_TICK_REFERENCE_OUTSIDE_SESSION. Ownership/tham chiếu legacy chưa xác định thì không purge tự động. Nếu xuất nghiên cứu từ phiên mới, tạo bản dữ liệu nghiên cứu độc lập trước khi đăng ký export hoàn tất; không để archive tham chiếu raw sắp xóa. Việc dọn kho nghiên cứu cũ là hành động riêng ngoài yêu cầu dọn cuối ngày.

### Trình tự an toàn và phục hồi

    OPEN → REPORT_COMMITTED → PURGE_PLANNED → PURGING → CLOSED

1. Giữ khóa chung cho storage; chặn writer và reader đang dùng chunk, kể cả session exec/direct paper-run. Tránh khóa lồng gây deadlock ở build_report.
2. Lưu manifest kế hoạch: source/session/generation/cycle, resolved paths, kích thước, hash, snapshot/consumer bị ảnh hưởng, báo cáo đã commit và kết quả kiểm ownership/tham chiếu ngoài phiên. Từ chối path traversal và reparse point/junction ngoài phạm vi.
3. Ghi availability/tombstone riêng cho pin bị retire. Không sửa snapshot hoặc bundle gốc để che việc xóa.
4. Xóa theo đúng manifest; reset/retire cursor và pending cùng payload. Không để checkpoint OK tham chiếu file không còn.
5. Kiểm lại byte/file còn sót, invalidate cache. Chỉ CLOSED khi hoàn tất; lỗi giữa chừng thành CLEANUP_PARTIAL, lần gọi tiếp nối tiếp idempotent. File mới/đổi sau lúc lập kế hoạch phải kiểm lại, không xóa mù.
6. Receipt trả số file/byte xóa thật, đường dẫn báo cáo còn giữ và raw_tick_replay_available=false. Báo cáo cũ vẫn mở được; exact replay trả TICK_DATA_PURGED_BY_RETENTION, không fallback proxy âm thầm.
7. Lượt mới sau kết ngày tạo tick generation/checkpoint mới và thu warmup hữu hạn mặc định 240 phút; tái dùng bars, identity và clock. Cho phép người dùng quay lại quét trong cùng ngày bằng generation mới; không tái dùng tick cache đã retire.

Không đổi cấu trúc thư mục tick theo ngày ngay ở bản đầu nếu không cần; collector._checkpoint_files hiện giả định đường */ticks/checkpoint.json. Mỗi generation mới có ID riêng bất biến trong checkpoint, tick pin, cache key và tombstone; không dùng riêng content hash làm ID vì dữ liệu tải lại có thể giống hệt. Pin legacy giữ nguyên và được tra theo metadata ngoài; không sửa artifact cũ. Nếu đổi path phải sửa đồng bộ routing và kiểm clock.

### Outcome còn mở và mất replay

Chốt các outcome đã đủ bằng chứng trước cleanup. Cơ hội còn mở/thiếu đường giá được lưu PENDING/CENSORED_AT_SESSION_END, không tính là thắng/thua/hòa và không đưa vào mẫu đã đóng. Không tự theo dõi tiếp sau kết phiên.

Xóa tick là mất dữ liệu không khôi phục được từ summary. Không thể hứa backtest tick chính xác những ngày đã dọn. Số liệu forward phải dựa trên record lưu trước cleanup và nhãn bằng chứng; nếu sau này người dùng muốn kiểm chứng raw đầy đủ thì cần chọn một chính sách lưu khác rõ ràng.

### Dung lượng đã kiểm, không suy rộng toàn máy

| Phạm vi | Tick bytes | Xấp xỉ |
|---|---:|---:|
| on_demand/operations hiện có | 1.520.561 | 1,45 MiB |
| phien_demo, các phiên cũ đã kiểm | 10.884.253 | 10,38 MiB |
| Kho nghiên cứu weekly_fabio_20261102_08 | 406.730.441 | 387,89 MiB |

Khoảng 97% tick bytes ở các root đã kiểm thuộc nghiên cứu tuần. Dọn phiên hằng ngày chủ yếu ngăn tích lũy khi mở 8–12 mã; cải thiện tốc độ trước mắt phải đến từ giảm đọc/tính lặp. Xóa file không đồng nghĩa giảm peak RAM nếu luồng phân tích vẫn đọc cả tape vào nhiều bản sao.

## 7. Gói triển khai và thứ tự bàn giao

| Gói | Công việc | File chính | Điều kiện xong |
|---|---|---|---|
| 0 | Ghim baseline, telemetry, xác minh clock/coverage | session.py, paper.py, collector.py; benchmark riêng | Có baseline cùng workload và status dữ liệu trung thực |
| 1 | Thu tăng dần + batch report + cache theo pin | collector.py, source_bundle.py, data.py, replay.py, context.py, session.py | Parity trên pin cũ, không tải lại 35 ngày mỗi lượt |
| 2 | Khả năng từng symbol, economics thiếu không crash, 8 mã | cli.py, config.py, source_bundle.py, snapshot.py, execution.py; config phiên mới | Mọi mã có status, các mã đủ dữ liệu chạy được |
| 3 | Watch zones ca tối + kiểm tập trung + tick indexing | snapshot.py, context.py, mt5_flow.py, paper.py, session.py | Vùng chờ đúng nguồn, báo hết hạn đúng, đạt benchmark |
| 4 | Outcome append-only + session finish/dọn tick | session.py, collector.py, paper.py, replay.py, cli.py; helper retention nhỏ nếu cần | Cleanup an toàn, còn report, ngày sau warmup lại được |
| 5 | Cross conversion + lên 12 mã, forward demo | execution.py, config/bundle, tests | Đạt data/cost/latency gates từng mã; không chứng nhận winrate |

Gói 4 là yêu cầu bắt buộc trước khi bàn giao bản vận hành mới; không hoãn dọn tick sang một nâng cấp không xác định. Các gói trên là thứ tự kỹ thuật trong cùng kế hoạch, không phải xin phép riêng từng bước.

Phiên mới cần tên/root riêng vì session ghim engine/config/universe; không sửa hash phiên cũ. Bộ mã cũ giữ để đối chiếu. Cập nhật HUONG_DAN_DEMO_TOI_NAY.md và SKILL_RUNTIME.md cho runtime thực tế; tài liệu cũ nói ticks 15 phút trong khi code mới mặc định 240 phút.

## 8. Đánh giá hiệu quả sau nâng cấp

- Replay theo lịch người dùng thực sự gọi, cộng độ trễ xử lý/trả lời; không coi mọi trigger M5 lịch sử là cơ hội đã nhìn thấy.
- Giữ journal tất cả cơ hội, nhóm agent chọn/bỏ và lý do ghi trước outcome. A/Fabio dùng episode/trigger identity hiện có; B chưa có episode nên dùng candidate gắn symbol/setup/side/thời điểm tín hiệu, không gộp mọi episode_id=None thành một. Một cơ hội qua nhiều lượt vẫn chỉ tính một lần; M0/M1/M2 là biến thể, không tăng sample độc lập.
- Báo riêng symbol/setup/giờ/regime và phiên bản luật; winrate, net expectancy, payoff, tail loss, drawdown nếu có portfolio chronology, missed-entry và tỷ lệ UNKNOWN.
- Không suy max drawdown portfolio từ tổng R candidate. Không coi outcome thiếu là lệnh thua hoặc tự loại khỏi báo cáo coverage.
- Giữ rule ổn định qua các phiên/tuần mới trước khi chọn lọc hiệu quả. Không có cam kết tỷ lệ thắng hoặc số lệnh mỗi tối.

## 9. Nguồn chính và giới hạn nghiên cứu

- MetaQuotes: [symbols_get](https://www.mql5.com/en/docs/python_metatrader5/mt5symbolsget_py) cho phép đọc danh sách symbol/metadata theo nhóm trong một call; mapping phải dùng dữ liệu broker thực.
- MetaQuotes: [symbol_info](https://www.mql5.com/en/docs/python_metatrader5/mt5symbolinfo_py) cung cấp thông số symbol, tick size, contract và volume limits; không thay thế bảng commission đã xác nhận.
- MetaQuotes: [copy_ticks_range](https://www.mql5.com/en/docs/python_metatrader5/mt5copyticksrange_py) mô tả ticks/flags và hợp đồng thời gian UTC; cần đối chiếu source-clock hiện có trước migration.
- MetaQuotes: [copy_rates_range](https://www.mql5.com/en/docs/python_metatrader5/mt5copyratesrange_py) lưu ý history có sẵn/Max bars in chart; requested window không tự chứng minh dữ liệu đủ.
- Báo cáo gốc: quant_mt5/runtime/on_demand/weekly_fabio_20261102_08/WEEKLY_TRIAL_REPORT.md và TRAILING_TRIAL_REPORT.md.

Lượt này kiểm code/config/help, artifact cũ, thông số máy, dung lượng và một probe offline nhỏ. Chưa attach MT5, chưa xác minh broker support hiện tại, chưa có benchmark đa mã/native p95, chưa triển khai production, chưa xóa dữ liệu. Chi tiết kiểm thử bắt buộc ở NGHIEM_THU.md.
