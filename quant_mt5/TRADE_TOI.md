# trade tối — bản đồ cơ hội A + MT5-only

Nâng cấp 08/11/2026, tiếp nối bản quét ca tối v2. Skill gọi bằng `$trade-toi`, tên hiển thị **trade tối**. Kế hoạch/hợp đồng: `D:/trading thử lần cuối cuối/quant_mt5_plan_20261108/ban_giao_A_MT5_only/`.

## Chức năng

- Trả toàn bộ tín hiệu A/B trước phần phân tích bổ sung; `max_cards` chỉ giới hạn thẻ sâu, không cắt bảng tín hiệu.
- A vẫn là frozen range8H1 → M5 breakout → M5 retest. Không đổi M0/M1/M2, entry/SL/TP, deadline, sizing hay execution.
- Phân tích hướng H1, giá M5 đóng, vùng đóng băng/PDH/PDL/value, hoạt động tick ducó nhãn proxy, kịch bản và phản chứng; mục tiêu tham chiếu không thay TP.
- Reference windows Asia/London/New York có timezone/DST và coverage; relative movement1h/4h chuẩn hóa ATR, FX strength/exposure theo metadata. Thiếu dữ liệu giữ UNKNOWN.
- Không footprint, feed ngoài/trả phí, indicator bắt buộc hay news gate. Tin tức người dùng tự kiểm. Không xác suất thắng hoặc khẳng định ý định cá mập.

## Phiên cho engine mới

Không sửa engine hash của phiên `ca_toi_8_v2` cũ. Tính năng đã đổi source nên lần phân tích mới cần phiên ghim engine hiện tại. Trong lượt nâng cấp không tự tạo/thu dữ liệu phiên native mới.

Khi người dùng yêu cầu phân tích mới, dùng terminal/mapping họ đã chọn. Terminal trước đây: `C:/Program Files/MetaTrader 5/terminal64.exe`; đây không phải bằng chứng terminal đang chạy hoặc đúng account hiện tại. Kiểm readiness trước; thiếu nguồn thì người dùng tự mở MT5 demo. Nếu người dùng đã chọn terminal khác, dùng đường đó, không quay về mặc định.

Root/tên gợi ý cho lần dùng đầu sau nâng cấp: `D:/trading thử lần cuối cuối/quant_mt5/runtime/on_demand/trade_toi_v1`, `trade_toi_8_v1`. Nếu tên này đã thuộc engine khác, dùng tên mới, không đè phiên. Các lệnh dưới đây là hướng dẫn vận hành, không có nghĩa đã chạy native trong nghiệm thu.

```powershell
& 'D:/trading thử lần cuối cuối/quant_mt5/quant.cmd' readiness --no-attach
& 'D:/trading thử lần cuối cuối/quant_mt5/quant.cmd' session init --root 'D:/trading thử lần cuối cuối/quant_mt5/runtime/on_demand/trade_toi_v1' --name trade_toi_8_v1 --terminal-path 'C:/Program Files/MetaTrader 5/terminal64.exe' --universe-preset main8
& 'D:/trading thử lần cuối cuối/quant_mt5/quant.cmd' session preflight --root 'D:/trading thử lần cuối cuối/quant_mt5/runtime/on_demand/trade_toi_v1' --name trade_toi_8_v1
```

Preflight chỉ kiểm packages/process/engine/config pins; READY_TO_ATTACH chưa xác minh account. Collector trong cycle kiểm fingerprint và trade_mode demo trước đọc dữ liệu. Không tự mở/đăng nhập/đổi tài khoản; không đặt/check lệnh.

main8: XAUUSD, EURUSD, USDJPY, GBPUSD, USDCAD, USDCHF, AUDUSD, NZDUSD. extended12 thêm EURJPY, GBPJPY, EURGBP, AUDJPY. Broker native mapping phải xác minh, không đoán suffix; index chỉ khi có metadata/mapping thực, chưa tuyên bố US100/US500/GER40 live-supported. Dầu ngoài scope.

## Một lượt: baseline rồi enrichment

```powershell
& 'D:/trading thử lần cuối cuối/quant_mt5/quant.cmd' session once --root 'D:/trading thử lần cuối cuối/quant_mt5/runtime/on_demand/trade_toi_v1' --name trade_toi_8_v1 --analysis-mode baseline --max-cards 3
```

Call1 trả `data.context_state=PENDING`, `data.continuation`, report baseline và `finish_token=null`. Consumer phải đọc/trình bày bảng A ngay, không đợi phần sau. Không chỉ ghi file sớm mà giữ lời đáp đến lúc enrich xong.

Call2 dưới đây: thay placeholder bằng IDs thật từ continuation call1; không đoán hoặc lấy snapshot khác.

```powershell
& 'D:/trading thử lần cuối cuối/quant_mt5/quant.cmd' session enrich --root 'D:/trading thử lần cuối cuối/quant_mt5/runtime/on_demand/trade_toi_v1' --name trade_toi_8_v1 --expected-cycle '<cycle_id>' --expected-generation '<generation_id>' --expected-snapshot '<snapshot_id>' --context-timeout 30 --max-cards 3
```

Enrich chỉ đọc cùng snapshot/bundle, không collect/replay. Kết quả trong `data.report`, `data.analysis`, `data.cycle.analysis`. COMPLETE có thể có UNKNOWN/UNSUPPORTED; PARTIAL_FAILED là optional error/timeout đã kết thúc, baseline vẫn nguyên. REFUSED/integrity mismatch giữ tick, không cấp token cleanup. Timeout child phải thực sự kết thúc, không có worker ngầm tiếp tục.

Default không flag vẫn full để tương thích caller cũ; đường skill trade tối chủ động dùng baseline/enrich. Cùng end/cycle tái dùng, không quét/replay thêm để đổi mode. Gọi full khi cycle còn PENDING trả CONTEXT_PENDING; tiếp tục enrich đúng continuation.

Kiểm nhanh một mã đã ghim: thay once bằng `session check --symbols EURUSD --analysis-mode baseline`, rồi enrich IDs mới. Check tạo dữ liệu/snapshot mới, không gia hạn tín hiệu hết hạn. Nhịp gọi thưa có thể bỏ lỡ entry; không tự đổi thành daemon hoặc kéo dài deadline.

## Đọc đúng, lưu đủ và kết phiên

Nguồn SYNTHETIC/HISTORICAL không là live. Context snapshot hiện tại và card tại decision tách riêng; không gán CVD sau tín hiệu thành dữ kiện đã biết lúc vào. `current_window`/economics/quote guards vẫn giữ. H1 thuận không cho phép entry khi stale/expired/thiếu phí. Market root context_status UNKNOWN vì không có một side A chung; đọc alignment ở từng scenario.

Máy lưu report JSON/Markdown tự động. Khi cần note cho candidate, đọc schema `RUNBOOK.md`; quan sát không có candidate dùng journal observation. Không gọi card/context lặp nếu packet đã có. Đọc report cũ theo yêu cầu thì chỉ đọc artifact, không readiness/once/enrich/finish.

Chỉ khi người dùng xác định lượt cuối: đọc/lưu phân tích xong, dùng **token report cuối**:

```powershell
& 'D:/trading thử lần cuối cuối/quant_mt5/quant.cmd' session finish --root '<root>' --name '<name>' --expected-cycle '<token.cycle_id>' --expected-generation '<token.generation_id>' --expected-snapshot '<token.snapshot_id>'
```

Baseline PENDING không finalize được. Token cũ sau cycle/generation/mutation mới bị từ chối. CLOSED receipt mới xác nhận xóa owned raw ticks; giữ bars/reports/snapshot/bundle/journal. Raw đã xóa không replay exact; không tự cleanup bằng shell hoặc suy lượt cuối từ giờ/im lặng.

## Bằng chứng và giới hạn

Xem `D:/trading thử lần cuối cuối/quant_mt5/phases/EVENING_CONTEXT_A_MT5_20261108/attempt_1_codex/NGHIEM_THU.md` để biết source hash, test thực sự chạy, baseline failures và điều kiện chưa nghiệm thu.

Offline tests không chứng minh winrate tăng; cùng lệnh/thực thi phải cùng P&L. Chưa xác minh live broker mapping/clock/cost, native p95 hay RAM toàn process tree. Không tự chọn branch theo tuần thắng nhiều, không thay portfolio policy bằng thứ hạng chỉ báo.
