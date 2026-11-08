---
name: quant-mt5-agent
description: Quét và phân tích thị trường MT5 theo yêu cầu trước phiên hoặc khi người dùng rảnh. Lấy dữ liệu đa tài sản/cặp tiền, tính context và chỉ số quant, đọc setup, brainstorm kịch bản và lưu báo cáo/nhật ký từ cùng snapshot. Có thêm khung Fabio/CVD cho FTMO (state→location→trigger→phản ứng giá→phản chứng→execution; F1 trend/LVN, F2 failed breakout). Dùng khi người dùng nhờ phân tích MT5, vàng, FX, chỉ số, order flow/CVD/LVN hoặc brainstorm setup; giữ đúng các symbol và tính năng công cụ thực sự hỗ trợ.
---

# Quant MT5 — phân tích khi được gọi

Đây là skill vận hành công cụ hiện có tại `D:/trading thử lần cuối cuối/quant_mt5`. Thực hiện một lượt hữu hạn theo yêu cầu rồi kết thúc. Giữ đầy đủ phạm vi tài sản/chỉ số/context/setup đã triển khai; không thay yêu cầu phân tích bằng một dự án lập trình hoặc đòi đợi nghiên cứu dài hạn.

Ví dụ: “Dùng $quant-mt5-agent phân tích trước phiên tối nay”, “Quét XAUUSD, EURUSD và USDJPY, lấy ATR/volume/EMA/ADX/RSI rồi cùng mình chọn cơ hội”, “Cập nhật lại phân tích bằng dữ liệu mới”.

## Lấy dữ liệu và chạy công cụ

Đọc [các lệnh và đường dẫn thực tế](references/runtime.md) lần đầu dùng hoặc khi CLI thay đổi. Chạy command bằng đường dẫn tuyệt đối; các tool call shell dùng workdir tuyệt đối. Kiểm tra help/schema thật khi cần, không bịa tên command hoặc giả định bản nháp nghiên cứu là executable.

1. Dùng symbol/universe và terminal/session người dùng đã chọn. Bối cảnh đã lưu là **MT5 demo, mục tiêu FTMO 1-Step** (không xác minh account/stage/risk hiện tại). Khi chưa chỉ định symbol, dùng universe đã lưu trong phiên. Bản nâng cấp 08/11 có preset main8 và extended12; đọc runtime để chọn phiên mới đúng engine, không sửa hash phiên cũ. Tạm loại dầu cả tên canonical lẫn alias. Mã thiếu metadata/cost vẫn phải có trạng thái riêng; economics UNKNOWN chỉ được báo context, không giả phí hay kế hoạch đã đủ điều kiện.
2. Kiểm tra nguồn qua `readiness --no-attach`: terminal đang chạy, đường dẫn, trạng thái nguồn. Nếu không có terminal thì báo bước mở MT5 đã đăng nhập demo và dừng ở trạng thái PENDING; không mở/đăng nhập/đổi account. Nếu có nhiều nguồn mơ hồ, hỏi chọn nguồn một lần. Một terminal được người dùng mở cho phiên này có thể được dùng sau khi preflight xác nhận đúng tài khoản demo; lưu fingerprint để những lần gọi sau không đổi nguồn âm thầm.
3. Chạy **một lượt** `session once` khi phiên on-demand đã cấu hình, hoặc `paper-run` hữu hạn theo runtime reference. Preflight phải xác minh account trade_mode demo; không suy từ tên server có chữ “Demo”. Không dùng session start/run, daemon, scheduler hay vòng gọi LLM cho yêu cầu phân tích thông thường. Tái dùng raw/chunks theo đúng namespace và giữ đầu ra tách khỏi kho nghiên cứu mặc định.
4. Lấy snapshot_id, config bundle và store từ output chính lượt chạy đó. Mọi scan/context/card/replay/note tiếp theo dùng **cùng config bundle + store + snapshot**. Không để lệnh tiếp theo rơi về registry lịch sử mặc định. Không diễn giải timestamp trong archive hoặc warmup backfill thành quan sát trực tiếp hiện tại.

## Phân tích từ cùng bằng chứng

- Đọc scan để phân biệt có cơ hội, đang chờ, bị chặn, hết hạn, no-signal và lỗi/stale/missing. Không có setup vẫn có thể trình bày context thị trường nếu dữ liệu đủ.
- Ưu tiên `cycle.analysis` / báo cáo batch đã sinh trong lượt quét; card đã chứa context tại decision, không gọi thêm context lặp lại nếu không cần nhóm chỉ báo khác. Đọc watch_zones: A là anchor cố định thật, rolling H1 chỉ mô tả; B chưa có precursor. DEFERRED_DEEP_ANALYSIS không có nghĩa no-signal. Khi người dùng muốn kiểm lại một mã, dùng `session check` tạo snapshot mới, không kéo dài deadline cũ.
- Lấy context theo symbol tại snapshot as-of cho bức tranh hiện tại. Với candidate, lấy card và context tại decision để hiểu đúng tín hiệu; phân biệt rõ cập nhật as-of hiện tại với thông tin đã có lúc candidate xuất hiện.
- Chọn phép đo phục vụ câu hỏi: cấu trúc giá/khung thời gian, ATR và khoảng cách chuẩn hóa, tick/real volume và RVOL, hình học nến, spread/quote age; lấy thêm EMA, ADX/DI, RSI, efficiency ratio hoặc ATR percentile khi có ích và đủ history. Công cụ trả UNKNOWN thì giữ UNKNOWN. Không tính tay một số rồi gọi là output của engine.
- Với mỗi cơ hội đáng chú ý: nêu dữ kiện ủng hộ và chống lại, kịch bản ưu tiên, kịch bản đối nghịch, mức/điều kiện làm đổi nhận định; kết luận cân nhắc vào, chờ điều kiện cụ thể hoặc bỏ qua. Giữ nguyên hai setup baseline; không thêm gate/đổi chiến lược trong lúc phân tích.
- Entry/SL/TP/deadline và giá dùng cho nhận định phải từ card/replay/tick cùng phiên. Candidate hết hạn không được giới thiệu như lệnh có thể vào ngay. Buy dùng Ask, sell dùng Bid theo mô hình của engine. Proxy, phí ASSUMED, clock/coverage chưa xác minh phải có nhãn sát nhận định liên quan.
- Tick volume mô tả hoạt động của feed, không phải tổng khối lượng thị trường, delta hay dấu vết tổ chức. Nhiều chỉ số tính từ giá không phải nhiều bằng chứng độc lập. Không tạo xác suất thắng/điểm tin cậy chưa hiệu chuẩn.
- Tin tức/lịch kinh tế chưa lấy được từ nguồn có thời điểm thì ghi UNKNOWN; không tuyên bố đã tránh tin chỉ vì công cụ giá không báo sự kiện.

## Khung Fabio/CVD (khi câu hỏi liên quan)

Khi người dùng hỏi Fabio, CVD/order flow, LVN/POC, absorption, failed breakout hoặc muốn setup tốt hơn cho FTMO, đọc [references/fabio.md](references/fabio.md) (lệnh `quant fabio`, route dữ liệu, cách đọc output) và [references/brainstorm.md](references/brainstorm.md) (kịch bản ưu tiên/ngược, bằng chứng bác bỏ mạnh nhất, quy tắc CVD). Tóm tắt bất biến:

- Chạy `fabio` trên **cùng snapshot/config/store** của lượt quét, từng symbol. Chưa có candidate baseline vẫn có context và kết quả F1/F2 nếu dữ liệu đủ; kết quả nằm ở namespace `store/fabio`, không đi vào `note add` (chỉ dùng cho candidate hợp lệ) — ghi `journal add --kind observation`.
- Nguồn vận hành chỉ là MT5 người dùng đã mở. `fabio` tự đọc tick đã ghim cùng snapshot để tính CVD/Profile và lấy Bid/Ask; không cần feed/indicator ngoài hay file export. Có trade flags/volume thì dùng dữ liệu khớp lệnh của broker; nếu chỉ có quote thì dùng CVD tick-direction với nhãn proxy.
- CVD quote-direction không độc lập với giá, không chứng minh aggression/absorption thực. Gate aggression tại mức giá giữ `DATA_UNAVAILABLE`; market data không `FRESH` chặn cả family lẫn mọi variant.
- Bid/Ask tự đọc từ tick MT5 của đúng symbol. Commission/slippage không được nguồn MT5 cung cấp thì giữ UNKNOWN; không ngầm định 0, tối đa WAIT khi thiếu phí. Xác suất thắng luôn null. `ENTER_CANDIDATE` không phải lệnh broker và không có nghĩa đã qua gate tài khoản FTMO.
- Tách dữ liệu account thực tế (chỉ khi đã đọc từ nguồn) khỏi bối cảnh đã lưu; thiếu rule/equity không chặn báo cáo context nhưng không được nói kế hoạch đã qua gate tài khoản.
- Đây vẫn là một lượt hữu hạn theo yêu cầu: không daemon, lịch chạy, train model hay backtest 18 ô trong lượt phân tích.

## Trả kết quả và lưu lại

Trả tiếng Việt, kết luận dễ đọc trước, thường gồm:

1. Thời điểm lấy dữ liệu theo giờ Việt Nam, nguồn và danh sách mã đã quét; chỉ nêu hạn chế dữ liệu ảnh hưởng kết luận.
2. Bảng ngắn theo mã: trạng thái/bối cảnh, setup nếu có, nhận định vào/chờ/bỏ và lý do chính. Thêm các con số thực sự giúp người dùng đánh giá thay vì đổ toàn bộ indicators.
3. Thẻ chi tiết cho các cơ hội đáng quan tâm: kịch bản, giá/điều kiện vào, SL/TP và mức vô hiệu/deadline đã có nguồn, điều kiện cần kiểm lại. Nếu no-signal, nói rõ và trình bày context hữu ích đang có.
4. Snapshot ID và liên kết báo cáo hoặc artifact của lượt chạy để có thể xem lại.

Lưu báo cáo Markdown của lượt này vào thư mục output phiên, kèm các đường dẫn raw JSON/snapshot/card/context đã dùng. Phần số liệu máy và phần suy xét của agent phải phân biệt được. Chỉ viết analysis_note cho candidate đã thực sự phân tích, với features_used lấy đúng giá trị/timeframe trong context/card; ghi deviation_reason khi khác baseline. Gọi `note add` thật và xác nhận kết quả, không chỉ tạo JSON rồi tuyên bố đã ghi nhật ký. Lượt không có candidate vẫn giữ observation/no-signal của công cụ.

Khi người dùng yêu cầu cập nhật, chạy lượt mới và ghi snapshot mới; giữ kết quả cũ để đối chiếu. Không tự theo dõi sau khi đã trả lời, không mua challenge hay gửi/check order, không chọn vốn/risk tiền thật. FTMO 1-Step là bối cảnh đã chọn; đánh giá luật/equity chưa sẵn sàng không chặn báo cáo phân tích, và không được tuyên bố đã pass/chứng minh lợi thế từ một lượt quét.

Người dùng đã yêu cầu dọn tick sau lượt cuối trong ngày. Chỉ khi họ xác định đây là **lượt cuối/kết phiên**, hoàn tất once → đọc và lưu phân tích/note → `session finish` theo token chính lượt đó (runtime hướng dẫn). Không suy lượt cuối từ im lặng/giờ, không dùng stop thay finish, không dọn kho legacy/research/MT5. Xác nhận receipt CLOSED và số byte; báo rõ raw tick đã xóa không thể replay exact, bars/báo cáo/journal vẫn giữ. Lỗi scan/report/finish thì giữ tick và nêu nguyên nhân.
