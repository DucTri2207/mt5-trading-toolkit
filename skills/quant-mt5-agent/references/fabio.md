# Fabio cho FTMO — chỉ lấy dữ liệu từ MT5

Đọc khi cần F1/F2, CVD, LVN/POC, failed breakout hoặc brainstorm setup theo Fabio Valentini. Đây là operationalization nghiên cứu của dự án; giữ nguyên hai setup baseline A/B. Không có winrate đã hiệu chuẩn.

## Một lượt dùng thực tế

Người dùng mở đúng MT5 đã đăng nhập; agent kiểm nguồn rồi gọi `session once` hoặc `paper-run` hữu hạn theo [runtime.md](runtime.md). Nến, tick, Bid/Ask, spread, metadata đều từ nguồn MT5 đã chọn. Không cần indicator trả phí, ứng dụng/feed ngoài, hay file export thủ công. Phần mềm tính trực tiếp CVD/Profile từ dữ liệu thu qua MT5.

Lượt mới tự tạo bundle + snapshot, baseline scan/context, phân tích Fabio từng symbol và báo cáo. Với snapshot đã có, dùng cùng bundle/config/store:

```powershell
& 'D:\trading thử lần cuối cuối\quant_mt5\quant.cmd' fabio --snapshot '<snapshot_id>' --symbol XAUUSD --report '<out>\fabio_XAUUSD.md'
& 'D:\trading thử lần cuối cuối\quant_mt5\quant.cmd' journal add --kind observation --snapshot '<snapshot_id>' --text 'FABIO <analysis_id> <decision> XAUUSD'
```

Không truyền `--flow`/`--exec` trong vận hành này: chúng chỉ giữ cho chẩn đoán offline/kiểm thử contract cũ, output có nhãn `EXPLICIT_OFFLINE_INPUT`. Mặc định `MT5_SNAPSHOT_AUTO` đọc đúng các tick chunk được snapshot ghim, kiểm SHA và ánh xạ clock một lần. Thay đổi chunk đã ghim là lỗi toàn vẹn dữ liệu, không được âm thầm dùng nguồn khác.

## CVD được tính như thế nào

- **Có trade volume và cờ BUY/SELL hợp lệ:** cộng volume buy, trừ volume sell của chính broker/symbol MT5. Chỉ là dữ liệu khớp lệnh của nguồn đó; không suy thành tổng thị trường.
- **Chỉ có quote Bid/Ask:** `TICK_DIRECTION_PROXY`. So midpoint `(Bid+Ask)/2` của tick liên tiếp: tăng +1, giảm −1, không đổi 0. Đây là chênh lệch tick tăng/giảm, không phải khối lượng mua/bán thực và không phải bằng chứng độc lập với giá.
- Không tính delta bằng cách gán toàn bộ tick volume của nến xanh cho buy hoặc nến đỏ cho sell. Không thay dữ liệu thiếu bằng 0.
- Aggregate theo M5 đã đóng, reset theo ngày UTC; gap hoặc thiếu coverage bắt đầu đoạn mới. So swing/slope trong cùng đoạn reset. Dữ liệu thu mới mặc định 240 phút tick hữu hạn; CVD có thể bắt đầu giữa ngày, nên đọc mốc đoạn thực tế trong output, không coi là tổng từ đầu phiên.
- Thiếu tick/coverage, stale, future-known hoặc side/volume chưa đủ → lý do cụ thể. Vẫn trả bối cảnh giá khi có đủ nến; không tự kéo feed ngoài.

Nguồn kỹ thuật: [MetaQuotes về tick/flags và giới hạn Forex](https://www.mql5.com/en/book/applications/timeseries/timeseries_ticks_mqltick). Công cụ thị trường có cùng lựa chọn tick-direction để đối chiếu là [Cumulative Volume Delta CVD Indicator](https://www.mql5.com/en/market/product/154294); bản nâng cấp tính trực tiếp, chưa kiểm định hay cài indicator đó.

## Profile và setup

Profile ưu tiên tick tại mức giá của chart nếu đủ coverage cho toàn cửa sổ. Với chart Bid, profile dùng Bid. Nếu thiếu tick, dùng tick volume của nến phân bổ theo range và ghi `MT5_BAR_TICK_VOLUME_UNIFORM_PROXY`; LVN/POC khi đó là xấp xỉ hoạt động giá.

1. **State:** tìm balance M5 đã ổn định; không đủ → UNKNOWN.
2. **F1:** chấp nhận thoát value → impulse → pullback về LVN → price response.
3. **F2:** breakout thất bại → close reclaim value → pullback/test ở nến sau reclaim → trigger hướng về POC. Reclaim không đồng thời là trigger của lần pullback sau.
4. **Phản chứng:** quay lại balance (F1), xuyên cấu trúc, breakout tiếp diễn (F2), target ở sai phía, trigger hết hạn.
5. **Execution:** Bid/Ask tự lấy từ MT5; commission và slippage thiếu giữ UNKNOWN. Không dùng phí cấu hình giả định rồi nói đã tính đủ phí FTMO.

Spec `FABIO_FTMO_V1` version `1.1.0`, hash và mọi tham số trong output. Ngưỡng/định nghĩa máy là lựa chọn dự án; không bê số hợp đồng NQ sang lot CFD.

## Đọc kết quả

- `WAIT / SKIP / DATA_UNAVAILABLE / ENTER_CANDIDATE` là quyết định nghiên cứu, không phải order. Dữ liệu market không FRESH chặn cả family lẫn mọi variant.
- `FRESH` được đo so với as-of của snapshot. Snapshot lịch sử vẫn là dữ liệu lịch sử; nhãn này không xác nhận đang quan sát thị trường live hay clock broker đã được xác minh.
- `price_response`, `price_plus_cvd`, `price_plus_bar_delta` so trên cùng cơ hội; CVD/bar delta ghi rõ basis thực/proxy. `price_plus_local_aggression` giữ DATA_UNAVAILABLE vì phiên bản này chưa triển khai trades/footprint tại mức giá cho gate đó.
- Proxy chỉ mô tả hoạt động tick cùng phản ứng giá. Không diễn đạt `aggression/absorption đã xác nhận`, không đếm nó là phiếu độc lập với giá.
- Luôn trình bày supporting/contradicting evidence, mức vô hiệu, expiry, target và phí/room khi có. Thiếu phí → tối đa WAIT nếu price setup đã đủ.
- `win_probability=null`, `broker_order=false`; account/stage/rules/equity chưa được đọc thì chưa qua gate FTMO. Bối cảnh cũ demo/1-Step không xác minh tài khoản hiện tại.
- Artifact riêng `store/fabio/<snapshot_id>/...`; không tạo candidate baseline giả. Chỉ `note add` với candidate baseline có thật; Fabio riêng dùng artifact + journal observation.
