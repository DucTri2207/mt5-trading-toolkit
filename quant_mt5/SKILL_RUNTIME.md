# Quant MT5 Agent Runtime Skill

Tài liệu định hướng thực thi cho Agent khi tham gia quy trình quét và brainstorm cơ hội giao dịch (B5).

Bản 08/11: ưu tiên [NANG_CAP_CA_TOI_20261108.md](NANG_CAP_CA_TOI_20261108.md). Dùng phiên main8 mới, đọc batch analysis trong kết quả once; `session check` tạo snapshot mới cho một mã; chỉ `session finish` sau lượt cuối đã xác định và lưu nhận định mới dọn tick bằng token chính lượt đó. Không dọn research/legacy. Tick xóa rồi không replay exact, outcome chưa đóng là CENSORED.

## Hướng dẫn vận hành chính
Xem chi tiết quy trình từng bước và chuỗi lệnh thật tại [RUNBOOK.md](file:///D:/trading%20thử%20lần%20cuối%20cuối/quant_mt5/RUNBOOK.md).

## Các lệnh cốt lõi
- Khảo sát hệ thống: `quant.cmd doctor`
- Tạo snapshot đóng băng thời điểm: `quant.cmd snapshot --as-of <UTC> --universe <SYMBOLS>`
- Quét tìm cơ hội: `quant.cmd scan --snapshot <SNAP_ID>`
- Trích xuất thẻ cơ hội: `quant.cmd card --snapshot <SNAP_ID> --candidate <CAND_ID>`
- Lấy bối cảnh chi tiết: `quant.cmd context --snapshot <SNAP_ID> --candidate <CAND_ID> --groups <GROUPS>`
- Phân tích Fabio/CVD (nghiên cứu, hữu hạn): `quant.cmd fabio --snapshot <SNAP_ID> --symbol <SYM> [--flow F] [--exec F] [--report MD]` (xem RUNBOOK mục 9)
- Ghi nhận phân tích: `quant.cmd note add --file <NOTE.json>`
- Ghi nhật ký vận hành: `quant.cmd journal add --kind observation --text <TEXT>`
- Đóng băng phiên bản: `quant.cmd freeze --label <LABEL>`

## Bất biến bắt buộc
1. **Không tự chế số**: Mọi giá trị features và thông số kỹ thuật phải trích xuất chính xác từ `quant card` hoặc `quant context`.
2. **Dùng cùng snapshot**: Phân tích, lấy context và nạp note phải sử dụng đúng `snapshot_id` chứa ứng viên đó.
3. **Bắt buộc ghi deviation_reason khi khác baseline**: Nếu `agent_action` khác `baseline_eligibility`, bắt buộc phải giải trình rõ ràng.
4. **Không ngầm định gửi lệnh**: B5 chỉ phục vụ quan sát định tính và ghi nhận dữ liệu; tuyệt đối không ngầm định phát sinh lệnh ra broker.
