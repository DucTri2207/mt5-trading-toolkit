# Source các skill trading

Ba thư mục này được sao từ bản skill đã cài và kiểm chứng ngày 2026-11-08. Không sửa bản skill đang cài trên máy chỉ vì đóng gói repo.

Để cài trên máy khác:

1. Clone repo và cài Python theo README gốc; chạy bộ test offline.
2. Copy thư mục skill muốn dùng vào `$CODEX_HOME/skills` (mặc định `~/.codex/skills`). Giữ cả `agents/` và `references/`.
3. Trong bản copy vừa cài, thay prefix `D:/trading thử lần cuối cuối` và biến thể dấu `\` bằng đường dẫn checkout thật. Rà cả `SKILL.md`, `references/` và `agents/`.
4. Các đường dẫn session/bundle lịch sử trong tài liệu chỉ minh họa cho máy gốc. Tạo/chọn phiên mới theo runtime trên máy đích; không sửa manifest của phiên cũ để đổi đường dẫn.

Skill `scalp-fabio` là phương pháp riêng; `trade-toi` giữ tín hiệu A độc lập. Chỉ đọc/thu dữ liệu theo yêu cầu; không tự đặt lệnh hoặc theo dõi nền.
