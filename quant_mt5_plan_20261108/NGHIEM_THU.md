# Nghiệm thu nâng cấp quét ca tối

Ngày: 08/11/2026. Đây là checklist chuẩn bị triển khai; các mục chưa chạy không được đánh PASS.

## A. Đo baseline và benchmark

- [ ] Lưu engine/config/content hashes của baseline và máy/terminal/package version.
- [ ] Benchmark cũ/mới cùng dữ liệu, symbol, candidate và phạm vi Fabio; cold/warm riêng.
- [ ] Đo collect, verify/decode, detect, replay, flow, context, report và tổng wall time; riêng thời gian agent.
- [ ] Ít nhất 20 lượt warm có ca no-signal, nhiều candidate và lỗi một mã; báo p50/p95/max/peak RAM/request/bytes.
- [ ] Warm 8 mã mục tiêu p95 <=30s; 12 mã <=45s; check một mã <=5s. Không gọi là đạt nếu giảm coverage hoặc thiếu analysis mà không báo.
- [ ] So workload tương đương: mục tiêu giảm >=50% xử lý nội bộ; nguồn mạng/MT5 phải được phân rã riêng.
- [ ] Peak RAM tăng thêm toàn process tree mục tiêu <=1 GiB; thu MT5 tuần tự, chỉ tăng CPU worker nếu số đo hỗ trợ.

## B. Cache và dữ liệu nhân quả

- [ ] Lượt sau 20 phút không tải lại 35 ngày hoàn chỉnh; chỉ delta + tail/retry được giải thích.
- [ ] Cửa sổ chưa hoàn tất không bị đánh OK toàn bộ rồi bỏ mất nến mới.
- [ ] Sửa/revision nguồn giữ lineage, snapshot cũ không thấy dữ liệu biết sau đó.
- [ ] Candidate IDs, gate, zone, SL/TP, expiry, nhãn chất lượng và replay khớp baseline trên cùng pin; float tolerance chỉ dùng khi hợp đồng tính toán cho phép và không đổi quyết định.
- [ ] ATR/EMA không đổi seed do tự cắt history; decision cutoff khác as-of cutoff được kiểm riêng.
- [ ] Mỗi chunk cần thiết verify/decode tối đa một lần mỗi worker/lượt; sửa chunk làm cache miss/lỗi toàn vẹn.
- [ ] Không sort trước rồi bỏ qua raw tick order; giữ ticks cùng mili giây, gap, CVD reset và available_at.
- [ ] Early return không đọc tick báo rõ integrity NOT_CHECKED; không tạo FRESH/VERIFIED giả.
- [ ] Đổi source/account, time basis, config/engine hoặc tick generation không tái dùng cache cũ.
- [ ] Probe UTC/raw source/DST không apply offset hai lần; archive cũ không bị rewrite.

## C. Mở rộng mã ngoài dầu

- [ ] Danh sách đợt 1 có 8 mã, đợt 2 có 12 mã như kế hoạch; broker chưa có mã được ghi rõ.
- [ ] Một mã thiếu dữ liệu không làm abort toàn lượt; requested count luôn đối chiếu được với statuses.
- [ ] GBPUSD chưa có cost vẫn có price/context nếu đủ dữ liệu; economics UNKNOWN, không KeyError/zero fee giả.
- [ ] Symbol suffix mơ hồ/duplicate native mapping bị chặn trước collect; native metadata không sao chép từ EURUSD tùy ý.
- [ ] Cross thiếu tỷ giá quy đổi không được xuất net room/lot hợp lệ.
- [ ] Lịch phiên và D1 boundary thiếu vẫn UNKNOWN; không mặc định mọi mã có cùng giờ nghỉ.
- [ ] Oil canonical/alias bị loại trước collect; USDCAD vẫn là FX hợp lệ.

## D. Vùng chờ và cửa sổ vào lệnh

- [ ] WATCH của A xuất hiện từ episode hợp lệ; Fabio dùng state/location có bằng chứng. B bản đầu chỉ hiển thị candidate đã xác nhận, không bịa precursor/episode/entry.
- [ ] Phân biệt frozen anchor A với rolling H1 range mô tả; mọi level có nguồn/thời điểm biết.
- [ ] Candidate còn hạn không bị danh sách expired mới nhất đẩy khỏi báo cáo.
- [ ] Quote/Bid/Ask/age, spread, deadline và report time đều được ghi; nhãn còn entry không sống quá deadline thực.
- [ ] Tín hiệu 18:15:01 hết hạn 18:16:30 phải EXPIRED ở lượt 18:20, không hồi sinh bằng quote mới.
- [ ] Focused check tạo snapshot mới và liên kết episode; các thay đổi cấu trúc từ lượt trước được xét.
- [ ] Tất cả symbol được quét cơ bản; phần sâu DEFERRED có nhãn, không âm thầm biến thành NO_SIGNAL.
- [ ] News UNKNOWN nếu chưa có lịch có nguồn/timestamp; proxy CVD không đổi thành xác nhận aggression.
- [ ] Exposure cùng currency và cơ hội trùng qua các lượt có thể nhận diện, không đếm thành bằng chứng độc lập.

## E. Nhật ký outcome và dọn tick

- [ ] once bình thường không xóa tick. “Lượt cuối” chạy once → lưu phân tích/note → finish; stop không thay finish.
- [ ] finish đối chiếu expected_generation_id và latest completed cycle/report trong khóa storage; once A → once B → finish A phải STALE_FINALIZATION_REQUEST. Report write failure hoặc scan failure không purge.
- [ ] Source/session/date đúng Asia/Ho_Chi_Minh; kết phiên qua nửa đêm và mở lại cùng ngày có generation mới rõ ràng.
- [ ] Active reader/writer chặn cleanup; bao phủ session exec, direct paper-run và replay, không deadlock khóa lồng.
- [ ] Path traversal, junction/symlink/reparse point ngoài session bị từ chối; không dùng mtime để chọn tick.
- [ ] Xóa đúng accepted chunks, pending/conflict tick payload và live checkpoint; không giữ bản sao tape đầy đủ trong cache khác.
- [ ] Bars, báo cáo, journal, config/identity, research archive và phiên khác giữ nguyên nội dung.
- [ ] Consumer nghiên cứu ngoài phiên trỏ vào tick session khiến finish trả SHARED_TICK_REFERENCE_OUTSIDE_SESSION; ownership legacy không xác định không được purge tự động.
- [ ] G1 bị xóa rồi G2 cùng ngày tải dữ liệu giống hệt: ID generation khác; replay G1 vẫn PURGED, G2 đọc được, cache/tombstone không lẫn.
- [ ] Snapshot/bundle cũ không bị sửa hash; availability registry ghi dữ liệu đã retire.
- [ ] Replay cũ trả TICK_DATA_PURGED_BY_RETENTION; report cũ vẫn đọc; không fallback proxy rồi báo exact.
- [ ] Lỗi giữa purge trả CLEANUP_PARTIAL; retry idempotent; không xóa file mới/đổi ngoài manifest.
- [ ] Receipt byte/file trước-sau khớp filesystem; chỉ CLOSED khi verification hoàn tất.
- [ ] Lượt kế tiếp thu tick warmup 240 phút theo generation mới, reuse bars và giữ kiểm account/clock.
- [ ] Outcome đã đóng có record riêng; candidate dedup không nuốt mất cập nhật outcome sau.
- [ ] Outcome còn mở là PENDING/CENSORED, không tính vào winrate đã đóng; coverage mẫu bị thiếu được báo.
- [ ] Không tuyên bố replay hoàn chỉnh cho ngày đã xóa raw ticks.

## F. Bàn giao

- [ ] Chạy bộ test collector/source pin, detector/replay, Fabio và session liên quan; thêm test có ý nghĩa cho feature mới/cleanup, không nhân bản test chỉ để tăng số lượng.
- [ ] Phiên mới ghim engine/config/universe; không ép hash phiên cũ để qua preflight.
- [ ] Cập nhật hướng dẫn vận hành và skill runtime: tick 240 phút, vùng chờ, focused check, finish và giới hạn replay.
- [ ] Báo cáo rõ functionality đã chạy, chỉ tiêu đạt/chưa đạt, phần cần xác minh khi thị trường mở.
- [ ] Bản production chỉ được gọi hoàn tất khi đợt 1, vùng chờ/kiểm nhanh và cleanup bắt buộc đều đã kiểm. Đợt 2 phải ghi trạng thái từng cross.

Không dùng thắng 8/10 của một tuần làm tiêu chí PASS chất lượng giao dịch. Nghiệm thu phần mềm chứng minh hệ thống chạy đúng/nhanh hơn; lợi thế giao dịch cần dữ liệu mới và phí có bằng chứng.
