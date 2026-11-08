# MT5 Trading Toolkit

Bộ công cụ nghiên cứu và phân tích kỹ thuật MT5, gồm Quant MT5, trade tối theo setup A và scalping theo khung Fabio. CLI Python dùng để đọc dữ liệu, phân tích, replay và ghi nhật ký; không gửi lệnh giao dịch.

## Bắt đầu trên Windows

Dùng Python 3.13. Tại thư mục gốc repo, chạy PowerShell:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
if (!(Test-Path quant_mt5/config/datasets.json)) {
    Copy-Item quant_mt5/config/datasets.example.json quant_mt5/config/datasets.json
}
.\quant_mt5\quant.cmd --help
.\.venv\Scripts\python.exe -m pytest -c pytest-offline.ini -q
```

Launcher ưu tiên `QUANTMT5_PYTHON` nếu đã đặt, tiếp đến `.venv`, rồi `python` trong PATH. Không cần MT5 hoặc dữ liệu cá nhân để chạy bộ test offline. Các phiên bản trong requirements là phiên bản đã kiểm chứng lúc bàn giao.

`datasets.example.json` mô tả cache lịch sử dùng trong nghiên cứu; dữ liệu tương ứng **không nằm trên GitHub**. Sao chép file này chỉ tạo cấu hình, không tạo dữ liệu thị trường. Lệnh đọc cache sẽ báo thiếu dữ liệu cho đến khi khôi phục đúng file/SHA, hoặc thu nguồn MT5 mới theo [hướng dẫn vận hành](quant_mt5/RUNBOOK.md). Khi cần dữ liệu mới, tự mở và đăng nhập đúng terminal MT5 trước. Không tự động đăng nhập bằng mật khẩu trong repo.

## Các phần chính

| Đường dẫn | Nội dung |
|---|---|
| `quant_mt5/quantmt5/` | Runtime phân tích, setup A/B, flow, Fabio, replay, session và báo cáo |
| `quant_mt5/config/` | Strategy, profile, exposure và mẫu registry dữ liệu |
| `quant_mt5/tests/` | Kiểm thử runtime; `fixtures/` chứa nguồn giả lập độc lập |
| `skills/` | Source của `trade-toi`, `scalp-fabio`, `quant-mt5-agent` và hướng dẫn cài |
| `Include/`, các file `.mq5` ở root | Indicator và thành phần MQL5 hiện hữu |
| `can_ho_tro_v4/`, `claude_build_v404/MQL5/` | Hai nhánh source V4/V4.04; giữ riêng để tránh trộn phiên bản |
| `scripts/`, `tests/` | Công cụ nghiên cứu và bộ kiểm thử MQL5/Python cũ |
| `quant_mt5_plan_20261108/`, `docs/` | Kế hoạch, bàn giao và hướng dẫn cấu trúc dự án |
| `quant_mt5_plan_20261103/`, `dca_duong/`, `thông tin nghiên cứu/` | Kế hoạch ban đầu và tài liệu nghiên cứu nền |

Các đường dẫn source MQL5 và runtime hiện hữu được giữ để tương thích script và manifest. Script build/sync cũ có đường dẫn máy cá nhân và có thể copy file sang MT5: đọc và cấu hình trước khi chạy. Dependencies của các nghiên cứu cũ nằm ngoài requirements runtime; cài theo import của script cần dùng.

## Dùng các kỹ năng

- [Trade tối](skills/trade-toi/SKILL.md): trả đủ tín hiệu A phá vùng H1/retest M5, rồi phân tích context và vùng chờ. [Hướng dẫn](quant_mt5/TRADE_TOI.md).
- [Scalp Fabio](skills/scalp-fabio/SKILL.md): F1/F2 độc lập với A. Policy mới chọn tường minh bằng `--policy scalp_mt5_v1`; mặc định legacy được giữ. [Bàn giao](quant_mt5_plan_20261108/BAN_GIAO_SCALP_FABIO_20261108.md).
- [Quant MT5](skills/quant-mt5-agent/SKILL.md): công cụ dùng chung cho snapshot, scan, card, context và replay.

Xem [cài skill](skills/README.md) và [runtime](quant_mt5/SKILL_RUNTIME.md). Quote-direction CVD là proxy hoạt động tick; profile từ volume nến là xấp xỉ. Không diễn giải chúng thành tiền ròng toàn thị trường hay bằng chứng về ý định cá mập. Kiểm thử phần mềm không chứng minh lợi nhuận hoặc tỷ lệ thắng.

## Kiểm thử và dữ liệu local

`python -m pytest -c pytest-offline.ini -q` là cổng kiểm thử cho checkout mới. `python -m pytest` thu cả hai thư mục test chính; một số test đầy đủ cần cache lịch sử, báo cáo đã bàn giao hoặc MetaEditor, nên chỉ chạy khi đã chuẩn bị các điều kiện đó. Không quét test trong vendor, bản giải nén, phases hay backup.

Dữ liệu thô, session/bundle, nhật ký, binary, ZIP, vendor và báo cáo dung lượng lớn được giữ local, không push. Không chuyển hoặc sửa cache/session đã ghim đường dẫn và SHA. `QUANTMT5_CONFIG_DIR` chỉ dùng với source bundle hợp lệ có manifest; không trỏ nó vào một thư mục cấu hình tùy ý.

Chi tiết dọn dẹp và kiểm chứng tại [docs/PROJECT_LAYOUT.md](docs/PROJECT_LAYOUT.md) và [docs/CLEANUP_20261108.md](docs/CLEANUP_20261108.md).
