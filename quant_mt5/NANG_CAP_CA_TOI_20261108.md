# Nâng cấp quét ca tối — 08/11/2026

Chỉ đọc MT5 demo; không đặt/check lệnh, không tự mở terminal hoặc đổi account, không chạy nền.

## Phạm vi

- `main8`: XAUUSD, EURUSD, USDJPY, GBPUSD, USDCAD, USDCHF, AUDUSD, NZDUSD.
- `extended12`: thêm EURJPY, GBPJPY, EURGBP, AUDJPY. Đây là hỗ trợ phần mềm; mã native và dữ liệu thực tế phải được kiểm trên broker.
- Dầu và alias USOIL/UKOIL/XTIUSD/XBRUSD/WTI/BRENT bị từ chối trước thu dữ liệu.
- Cặp chưa đủ phí/slippage/conversion: vẫn phân tích giá nếu đủ nến, economics UNKNOWN; không giả kế hoạch thực thi hay tỷ lệ thắng.

## Gọi từng lượt

Phiên mới phải ghim bản engine hiện tại. Phiên cũ giữ nguyên, không sửa hash để ép chạy.

```powershell
& 'D:\trading thử lần cuối cuối\quant_mt5\quant.cmd' session init --root 'D:\trading thử lần cuối cuối\quant_mt5\runtime\on_demand\evening_v2' --name ca_toi_8_v2 --terminal-path 'C:\Program Files\MetaTrader 5\terminal64.exe' --universe-preset main8
& 'D:\trading thử lần cuối cuối\quant_mt5\quant.cmd' session preflight --root 'D:\trading thử lần cuối cuối\quant_mt5\runtime\on_demand\evening_v2' --name ca_toi_8_v2
& 'D:\trading thử lần cuối cuối\quant_mt5\quant.cmd' session once --root 'D:\trading thử lần cuối cuối\quant_mt5\runtime\on_demand\evening_v2' --name ca_toi_8_v2
```

`once` thu 35 ngày warmup nến, 240 phút tick hữu hạn. Lượt sau tái dùng nến đã xác nhận và chỉ lấy phần mới/thiếu/pending. Dữ liệu đọc theo snapshot/pin, cache chỉ tồn tại trong một lượt; chunk bị sửa/xóa vẫn lỗi toàn vẹn.

Kiểm riêng một mã đã ghim:

```powershell
& 'D:\trading thử lần cuối cuối\quant_mt5\quant.cmd' session check --root 'D:\trading thử lần cuối cuối\quant_mt5\runtime\on_demand\evening_v2' --name ca_toi_8_v2 --symbols EURUSD
```

Đây là lượt hữu hạn mới, không theo dõi nền. Nhịp 20 phút có thể bỏ lỡ cửa sổ entry 90 giây; check không gia hạn tín hiệu cũ.

## Đọc kết quả

`data.report.report_md` là báo cáo; `data.cycle.analysis` chứa market context, cards, watch_zones và deferred_cards. Card đã có context tại decision. `analysis` CLI là batch dự phòng; không cần chạy card rồi context lặp lại cho mỗi candidate.

Vùng A lấy từ episode WATCHING_RETEST/anchor cố định thật, không lấy rolling H1 làm anchor. Fabio giữ state/location/invalidation/expiry và nhãn proxy CVD. B chỉ có candidate đã xác nhận, chưa có precursor. Còn hạn tại as-of không đồng nghĩa còn hạn khi đọc; mọi entry vẫn cần quote mới và kiểm tài khoản. News UNKNOWN nếu chưa có lịch có nguồn/thời điểm. Nhóm chung đồng tiền chỉ cảnh báo phơi nhiễm, không phải hệ số tương quan.

## Lượt cuối và dọn tick

Chỉ khi người dùng xác định lượt cuối/kết phiên: chạy once → lưu báo cáo/phân tích/note → lấy `data.finish_token` → finish:

```powershell
& 'D:\trading thử lần cuối cuối\quant_mt5\quant.cmd' session finish --root 'D:\trading thử lần cuối cuối\quant_mt5\runtime\on_demand\evening_v2' --name ca_toi_8_v2 --expected-cycle '<cycle_id>' --expected-generation '<generation_id>' --expected-snapshot '<snapshot_id>'
```

Token phải từ báo cáo thành công mới nhất. Có lượt mới hoặc collection mới thì token cũ bị chặn. Không tự gọi finish theo giờ/im lặng. Không dùng `stop` để dọn tick.

Finish chỉ xóa ticks được sở hữu của generation vận hành; giữ nến, báo cáo, snapshot, config, journal và kho nghiên cứu. Outcome chưa đóng thành CENSORED, không tính thắng/thua. Receipt CLOSED xác nhận file/byte đã xóa; CLEANUP_PARTIAL cần retry đúng token. Raw đã xóa không replay exact được; lệnh cũ báo `TICK_DATA_PURGED_BY_RETENTION`, không âm thầm đổi proxy. Lượt sau tạo generation mới và lấy lại tick warmup.

## Kiểm chứng

Kết quả test và số đo nằm ở `D:/trading thử lần cuối cuối/quant_mt5_plan_20261108/BAO_CAO_TRIEN_KHAI.md`. Không coi kiểm thử synthetic hoặc một tuần thắng nhiều là chứng minh hiệu quả giao dịch. Mốc tốc độ live 8/12 mã và check một mã chỉ được công nhận sau benchmark native khi thị trường mở.
