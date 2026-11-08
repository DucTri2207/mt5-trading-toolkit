# Sơ đồ source và dữ liệu local

Repo GitHub chứa source, test thực, cấu hình kỹ thuật, skill và tài liệu dùng để tiếp tục phát triển. `.gitignore` chọn phạm vi source tường minh và chặn output, binary, secret, cache.

Các thư mục lớn có thể vẫn hiện trên máy gốc nhưng không có trên GitHub:

| Local | Lý do giữ |
|---|---|
| `reports/` | Cache thị trường, kết quả nghiên cứu, baseline và bằng chứng kiểm định |
| `quant_mt5/phases/` | Gói bàn giao và snapshot nguồn đã ghim SHA |
| `quant_mt5/runtime/`, `quant_mt5/store/`, `phien_demo/` | Phiên, bundle, nhật ký; có thể chứa thông tin tài khoản |
| `codex_outbox/`, `codex_inbox/`, `.agents/` | Handoff và trạng thái làm việc local |
| `quant_mt5_plan_20261108/` các thư mục con | Baseline và output benchmark lịch sử |
| `local/archive/` | Log/handoff cũ, file xuất ZIP được gom lại khi dọn |
| `local/cleanup-20261108/` | Manifest thao tác dọn và kết quả kiểm tra của lượt này |

Không coi GitHub là bản backup toàn bộ dữ liệu nghiên cứu. Muốn khôi phục một replay lịch sử cần sao lưu riêng dữ liệu và bundle đúng SHA, đúng đường dẫn đã ghim. Root `PROJECT.md`, `TEST_INFRA.md`, `TEST_READY.md` mô tả các đợt nghiên cứu cũ; README gốc là điểm bắt đầu cho runtime hiện tại.
