# Runtime của trade tối

CLI: `D:/trading thử lần cuối cuối/quant_mt5/quant.cmd`.
Python: `C:/Users/ductr/AppData/Local/Programs/Python/Python313/python.exe`.
Runbook mới: `D:/trading thử lần cuối cuối/quant_mt5/TRADE_TOI.md`. Đọc runbook để lấy phiên/phạm vi và giới hạn nghiệm thu, không quay về baseline/staged khi live thiếu nguồn.

## Chọn nguồn và phiên

```powershell
& 'D:/trading thử lần cuối cuối/quant_mt5/quant.cmd' readiness --no-attach
& 'D:/trading thử lần cuối cuối/quant_mt5/quant.cmd' session once --help
& 'D:/trading thử lần cuối cuối/quant_mt5/quant.cmd' session enrich --help
```

Không có terminal: báo PENDING và yêu cầu người dùng mở MT5 đã đăng nhập demo. Nhiều terminal mơ hồ: hỏi chọn nguồn một lần. Không tự mở/đăng nhập/đổi account. Session preflight chỉ kiểm packages/process/pins; READY_TO_ATTACH chưa phải account verified. Collector trong once/check mới xác minh identity và account trade_mode demo trước khi đọc dữ liệu, không dựa chữ Demo trong tên server. Giữ source fingerprint trong session.

Tái dùng session nếu engine/config/source khớp. Phiên engine cũ không được sửa hash để ép chạy. Khi người dùng thực sự yêu cầu phân tích và cần phiên mới, giữ terminal/mapping đã chọn; tạo session mới theo runbook. Không init session/snapshot/live scan chỉ vì người dùng đang yêu cầu lập kế hoạch hoặc sửa phần mềm.

Với yêu cầu đọc artifacts synthetic/historical đã có, bỏ toàn bộ bước lấy nguồn mới: chỉ đọc files, kiểm identity/cutoff và nhãn nguồn, không gọi once/enrich hoặc finish. Không diễn giải artifact cũ thành thị trường tối nay.

`main8`: XAUUSD, EURUSD, USDJPY, GBPUSD, USDCAD, USDCHF, AUDUSD, NZDUSD. `extended12` thêm EURJPY, GBPJPY, EURGBP, AUDJPY. Native symbol phải đúng mapping broker; không đoán suffix. Indices chỉ khi metadata và mapping đã được kiểm, không mặc định US100/US500/GER40 đều có. Dầu ngoài phạm vi. Thiếu data/cost có status riêng, không bịa commission/slippage=0.

## Hai call trên cùng snapshot

`<...>` dưới đây là placeholder; thay bằng path/tên/ID thật. Chạy shell với workdir tuyệt đối. Không dùng `start/run`, scheduler hoặc vòng gọi lại tự động.

```powershell
& 'D:/trading thử lần cuối cuối/quant_mt5/quant.cmd' session once --root '<root>' --name '<name>' --analysis-mode baseline --max-cards 3
```

Output có một JSON envelope. Đọc `data.context_state`, `data.report`, `data.cycle`, `data.continuation`. Baseline thành công có `PENDING` và `finish_token=null`. Đọc JSON/Markdown report, trình bày toàn bộ A ngay trong lời đáp tiến độ rồi mới làm tiếp; không chờ context mới báo.

```powershell
& 'D:/trading thử lần cuối cuối/quant_mt5/quant.cmd' session enrich --root '<root>' --name '<name>' --expected-cycle '<continuation.cycle_id>' --expected-generation '<continuation.generation_id>' --expected-snapshot '<continuation.snapshot_id>' --context-timeout 30 --max-cards 3
```

Enrich không collect/replay. Bản cuối nằm ở `data.report.report_json/report_md`; `data.analysis` và `data.cycle.analysis` chứa packet cuối nếu thành công. Dùng bản cuối, không lấy baseline `cycle.analysis` giữ trong biến của call1 rồi tưởng đã cập nhật.

- `COMPLETE`: phân tích đã kết thúc; có thể vẫn UNKNOWN/UNSUPPORTED do dữ liệu thiếu.
- `PARTIAL_FAILED`: optional timeout/error đã kết thúc; A vẫn giữ, đọc optional_errors. Có token chỉ khi core được kiểm và report đã commit.
- `REFUSED`/integrity mismatch: không tự đổi expected IDs hoặc ghép dữ liệu mới. Báo nguyên nhân; giữ tick. Nếu muốn cập nhật thị trường phải gọi lượt mới có yêu cầu phù hợp, không tự hồi sinh tín hiệu cũ.
- Gọi lại cùng cycle/end tái dùng kết quả; full gặp PENDING có thể trả CONTEXT_PENDING và cần enrich, không tạo thị trường mới.

Kiểm một mã đã ghim dùng `session check --root ... --name ... --symbols EURUSD --analysis-mode baseline --max-cards 3`, sau đó enrich continuation mới. Đây là snapshot mới; deadline cũ không gia hạn. Nhịp gọi 20 phút có thể bỏ lỡ entry90s; không giải quyết bằng tự chạy nền.

## Lưu nhận định và lượt cuối

Report máy tự lưu. Nếu cần ghi nhận định, đọc schema note tại `D:/trading thử lần cuối cuối/quant_mt5/RUNBOOK.md`; chỉ note cho candidate đã có trong cùng snapshot. Observation/no-signal dùng journal, không cấp ID A giả.

`session exec` dùng bundle/snapshot trong phiên, ví dụ truy hồi card:

```powershell
& 'D:/trading thử lần cuối cuối/quant_mt5/quant.cmd' session exec --root '<root>' --name '<name>' -- card --snapshot '<snapshot_id>' --candidate '<candidate_id>'
```

Không gọi card/context lặp nếu packet đã chứa dữ kiện cần dùng. Trong session exec, luôn truyền snapshot khi command hỗ trợ; không rơi về store nghiên cứu mặc định.

Chỉ khi người dùng xác định lượt cuối/kết phiên, hoàn tất report/nhận định trước rồi dùng `data.finish_token` cuối cùng:

```powershell
& 'D:/trading thử lần cuối cuối/quant_mt5/quant.cmd' session finish --root '<root>' --name '<name>' --expected-cycle '<token.cycle_id>' --expected-generation '<token.generation_id>' --expected-snapshot '<token.snapshot_id>'
```

Không đoán token, không dùng token call1 hoặc token trước một lượt mới. CLOSED/receipt mới xác nhận dọn; report/bar/snapshot/bundle/journal giữ, raw tick đã xóa không replay exact. CLEANUP_PARTIAL chỉ retry đúng token, không tự xóa bằng shell. PENDING hoặc REFUSED không được “fix” bằng bỏ guard.

Skill này dùng workflow local, không gọi OpenAI API riêng hay cần API key. Cấu trúc skill theo [hướng dẫn chính thức về skills](https://developers.openai.com/plugins/build/skills); xác minh vận hành dựa CLI/help/test của dự án, không dựa trang web để đoán dữ liệu MT5.
