# Diễn giải cùng snapshot, không thêm gate

Ưu tiên packet `analysis.evening_context`, `market`, `cards`, `watch_zones`, `currency_strength` của báo cáo mới. Chỉ đọc sâu thêm khi người dùng hỏi dữ kiện chưa có; giữ cùng bundle/store/snapshot.

## Phân biệt thời điểm và nguồn

`SNAPSHOT_AS_OF` là bối cảnh tại snapshot; card `CANDIDATE_DECISION` là những gì đã biết khi candidate xuất hiện. Không lấy CVD/profile sau decision để kể như tín hiệu lúc vào. Chỉ nến hoàn tất và available trước cutoff được dùng cho nhãn; provisional nằm riêng.

`price_reference` dùng closed M5, không phải Ask/Bid dùng thực thi. Dùng lại current_window/quote age/expiry/economics từ engine; không tự khẳng định ready. Còn hạn tại as-of có thể đã hết khi người dùng đọc. Historial FRESH vẫn là dữ liệu lịch sử.

## Hướng, vùng, kịch bản

Nhãn H1 dùng vị trí close so EMA50 và slope EMA50 chuẩn hóa ATR, không phải xác suất. `context_status` so hướng đó với **từng** A LONG/SHORT; không lấy một side đại diện cho mọi candidate của mã.

Vùng A từ frozen anchor; rolling H1, PDH/PDL broker và balance/value/LVN là mức tham chiếu khác, có nguồn/thời điểm biết. Không thay anchor A bằng vùng rolling mới. Reference session windows là lựa chọn nghiên cứu của dự án, không phải lịch giao dịch broker; developing chỉ được gọi observed high/low. TIME_UNVERIFIED vẫn phải ghi rõ.

Một kịch bản hữu ích gồm: dữ kiện đang thấy → vùng cần quan sát → trigger nguyên bản → bằng chứng bác bỏ mạnh nhất → hạn chế. Với watch-only, candidate_id/plan là null; chờ retest không phải lệnh chờ đã gửi. Kịch bản ngược là điều kiện làm nhận định sai, không tự sinh trade đảo chiều. Không thay SL/TP/deadline bằng dự đoán quét thanh khoản.

Không có evidence chống thì nói chưa có evidence chống được đo, không tự bịa. Thiếu dữ liệu khác với dữ liệu phản bác. Không đổi nhãn sau khi biết outcome rồi nói đã dự đoán đúng.

## Flow và so sánh mã

CVD quote-direction là chênh lệch tick tăng/giảm; `is_proxy`, `volume_basis`, coverage và reset/segment phải đi cùng nhận định. Không nói absorption/aggression xác nhận hoặc dòng tiền tổ chức. Executed mode nếu có chỉ phản ánh broker/symbol cung cấp flags/volume, không toàn thị trường. Không nối phân kỳ qua gap/reset hoặc pivot chưa được xác nhận.

Currency strength chỉ là ATR-normalized relative movement 1h/4h trên rổ FX có coverage rõ. Partial/UNKNOWN không xếp hạng như đầy đủ; gold/index không thành tiền tệ do cắt tên symbol. Nhóm exposure chung USD không phải hệ số tương quan và không tự đổi sizing/cap.

Không khẳng định “cá mập sẽ làm X”. Cách nói phù hợp: “Giá đang tiếp cận vùng X; nếu M5 đóng giữ phía Y theo trigger gốc thì kịch bản tiếp diễn còn hợp lệ. Đóng xuyên Z sẽ bác bỏ. Hoạt động tick là proxy và hiện thuận/ngược/chưa đủ dữ liệu.”

Lifecycle `PENDING/COMPLETE/PARTIAL_FAILED` là trạng thái phân tích, không phải signal PASS/FAIL. `UNKNOWN/UNSUPPORTED` có thể là kết quả hoàn chỉnh hợp lệ. Tin tức luôn do người dùng kiểm; không xem việc thiếu lịch tin là lỗi hoặc gate A.
