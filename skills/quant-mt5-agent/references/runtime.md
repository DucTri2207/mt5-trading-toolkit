# Runtime MT5 trên máy người dùng

Project: `D:/trading thử lần cuối cuối/quant_mt5`. CLI: `D:/trading thử lần cuối cuối/quant_mt5/quant.cmd`. Python cài sẵn: `C:/Users/ductr/AppData/Local/Programs/Python/Python313/python.exe`.

Các ví dụ dưới đây dùng PowerShell. Với tool shell, đặt workdir `D:/trading thử lần cuối cuối` hoặc đường dẫn tuyệt đối khác có chủ đích. Dùng call operator `&` với đường dẫn có dấu/khoảng trắng; không ghép chuỗi `cmd.exe /c`.

## Khảo sát nguồn, không mở terminal

```powershell
& 'D:\trading thử lần cuối cuối\quant_mt5\quant.cmd' readiness --no-attach
& 'D:\trading thử lần cuối cuối\quant_mt5\quant.cmd' session --help
```

Output là JSON envelope: `status`, `command`, `data`, `quality`, `errors`. `data.initialize_called=false` với nguồn vắng là PENDING đúng nghĩa. Đường dẫn selected_terminal trong readiness có thể là cấu hình mặc định; nó không tự chứng minh người dùng đã chọn account hay terminal đang chạy.

## Một lượt lấy nguồn và scan

Bản nâng cấp 08/11/2026: đọc `D:/trading thử lần cuối cuối/quant_mt5/NANG_CAP_CA_TOI_20261108.md` để lấy phiên vận hành đã chuẩn bị và giới hạn kiểm chứng. CLI `session init` mặc định main8: XAUUSD, EURUSD, USDJPY, GBPUSD, USDCAD, USDCHF, AUDUSD, NZDUSD. `--universe-preset extended12` thêm EURJPY, GBPJPY, EURGBP, AUDJPY. Hoặc `--symbols canonical=native,...` chính xác theo broker; không dùng đồng thời preset và symbols. Cặp mới thiếu phí chỉ context/UNKNOWN, không suy phí từ EURUSD.

`session once` trả `data.cycle.analysis` gồm market context từng mã, cards (đã chứa context), watch_zones, deferred_cards; ưu tiên dùng packet này để tránh khởi chạy CLI riêng nhiều lần. `analysis --snapshot ...` là lệnh batch dự phòng trên cùng bundle. `timings_s` và `cache_stats` là số đo phần mềm, không bao gồm suy luận của agent.

Kiểm nhanh một mã trong universe đã ghim: `session check --root <root> --name <name> --symbols EURUSD`. Thu dữ liệu mới và tạo snapshot mới, không dùng quote mới để hồi sinh candidate hết hạn. Không daemon/vòng tự lặp.

### Sau lượt cuối người dùng đã xác định

Lưu đầy đủ báo cáo/nhận định/note trước. Lấy `data.finish_token` của lượt thành công mới nhất (status REPORT_COMMITTED), rồi:

```powershell
& 'D:\trading thử lần cuối cuối\quant_mt5\quant.cmd' session finish --root '<root>' --name '<name>' --expected-cycle '<cycle_id>' --expected-generation '<generation_id>' --expected-snapshot '<snapshot_id>'
```

Không đoán token, không dùng token lượt trước sau khi có lượt mới. Finish chỉ xóa raw ticks của generation vận hành được sở hữu: accepted/pending/conflict/checkpoint. Giữ bars, snapshots, bundles, reports, derived Fabio, journal/notes; outcome còn mở ghi CENSORED không tính thắng/thua. Receipt CLOSED mới xác nhận xóa xong; REFUSED/CLEANUP_PARTIAL phải nêu rõ, retry bằng đúng token nếu chỉ lỗi dọn dở. Mở lại phiên tạo generation mới, không làm pin cũ sống lại; replay tick cũ báo TICK_DATA_PURGED_BY_RETENTION. Không nâng cấp quyền sở hữu legacy để xóa hồi tố.

Ưu tiên session on-demand đã được cấu hình đúng nguồn nếu có. Dùng action `once` để thu dữ liệu và phân tích một lượt rồi thoát; `exec` chỉ gọi CLI trong bundle của phiên đã có:

```powershell
& 'D:\trading thử lần cuối cuối\quant_mt5\quant.cmd' session once --root '<root-cua-phien>' --name '<ten-phien>'
```

Không dùng `run` hoặc `start` cho việc gọi skill. Xem file cấu hình phiên hiện có trước khi gọi; không tạo phiên đoán vốn/account/risk. Session init/preflight/once có CLI help thật và hướng dẫn trong project `HUONG_DAN_DEMO_TOI_NAY.md` khi bản bàn giao tương ứng đã có.

Đường dự phòng độc lập là bounded paper-run đã có ở B6B. Chọn terminal thực tế được người dùng mở và mapping canonical=native theo metadata broker. `--out-root` dùng một thư mục ổn định riêng cho đúng nguồn demo, chẳng hạn dưới `quant_mt5/runtime/on_demand/`; không dùng main store hoặc archive nghiên cứu. Thay các placeholder bằng giá trị thực trước khi chạy:

```powershell
& 'D:\trading thử lần cuối cuối\quant_mt5\quant.cmd' --out '<raw-output-json-cua-luot>' paper-run --terminal-path '<exe-MT5-da-chon>' --symbols 'XAUUSD,EURUSD,USDJPY' --out-root '<thu-muc-nguon-demo>' --require-trade-mode 0 --tick-minutes 240 --scan-timeout 300
```

`--require-trade-mode 0` là account trade mode demo của luồng này, không phải enum symbol trade mode. Khi đã pin identity, `--expect-identity` nhận **JSON text**, không phải đường dẫn file. Pin của collector gồm executable, data_path, server, account_fingerprint, account_currency và provider_kind; readiness.identity chưa gồm executable/provider_kind nên không truyền nguyên nó rồi tưởng đủ. Các trường thêm phải được suy từ đúng executable/module native đã thực sự attach, không tự tạo identity giả. Dùng subprocess argv hoặc truyền nội dung file JSON đã đọc đúng cách để tránh quote lỗi. Mặc định paper-run thu 35 ngày warmup bar và 240 phút tick hữu hạn, không phải chạy nền. Lần gọi sau tái dùng đúng nguồn/cursor; thiếu lịch sử được báo rõ. Nếu flags/schema của bản cài đổi, đọc `paper-run --help` và project runbook thay vì bỏ mất yêu cầu demo.

## Tiếp tục trên đúng bundle và snapshot

Với paper-run, đường config ở `data.bundle.config_dir`, store ở `data.scan_process.env.QUANTMT5_STORE`, snapshot ID thường ở `data.scan.data.snapshot_id`. Session once có thể trả các đường này qua `analysis`/artifacts/report của nó; đọc JSON thực thay vì giả định cùng nesting.

Mỗi lần gọi CLI là một process mới. Đặt hai env dưới đây trong **chính tool call shell có các lệnh tiếp theo**, từ các đường output thật; không kỳ vọng biến môi trường ở tool call trước còn hiệu lực:

```powershell
$env:QUANTMT5_CONFIG_DIR = '<config_dir-cua-bundle>'
$env:QUANTMT5_STORE = '<store-cua-phien>'
& 'D:\trading thử lần cuối cuối\quant_mt5\quant.cmd' scan --snapshot '<snapshot_id>'
& 'D:\trading thử lần cuối cuối\quant_mt5\quant.cmd' context --snapshot '<snapshot_id>' --symbol XAUUSD --at as_of --groups ema,adx,rsi,er,atr_pct
& 'D:\trading thử lần cuối cuối\quant_mt5\quant.cmd' card --snapshot '<snapshot_id>' --candidate '<candidate_id>'
& 'D:\trading thử lần cuối cuối\quant_mt5\quant.cmd' context --snapshot '<snapshot_id>' --candidate '<candidate_id>' --at decision --groups ema,adx,rsi,er,atr_pct
& 'D:\trading thử lần cuối cuối\quant_mt5\quant.cmd' replay --snapshot '<snapshot_id>' --candidate '<candidate_id>'
& 'D:\trading thử lần cuối cuối\quant_mt5\quant.cmd' note add --file '<analysis_note.json>'
```

`context --at as_of` là bối cảnh hiện tại của snapshot; `--at decision` là bối cảnh lúc ra quyết định. Chỉ truyền candidate ID được scan/card trả về trong cùng snapshot. Khi symbol có nhiều candidate, lấy chi tiết theo câu hỏi thay vì mặc định quét lại toàn bộ lịch sử.

Schema analysis_note và ví dụ đã có trong `D:/trading thử lần cuối cuối/quant_mt5/RUNBOOK.md`; đọc phần note khi thực sự ghi note. Không copy các snapshot/candidate/time ví dụ làm dữ liệu của lượt thật. Output replay là mô phỏng có nhãn, không phải order hay fill broker.

Thiếu nguồn thật: dừng ở hướng dẫn khôi phục nguồn; không đổi sang kho lịch sử/synthetic rồi gọi đó là phân tích hiện tại. Nếu người dùng yêu cầu test thao tác bằng fixture/historical, cho phép riêng và dán nhãn rõ trên báo cáo. Việc kiểm luật FTMO/equity và đủ bằng chứng hiệu quả chiến lược được tiến hành riêng, không biến thành điều kiện phải đợi mới dùng skill đọc/phân tích.

## Phân tích Fabio/CVD (lệnh `fabio`)

Cùng env `QUANTMT5_CONFIG_DIR`/`QUANTMT5_STORE` và snapshot như trên. Kiểm `quant.cmd fabio --help` khi nghi ngờ CLI đã đổi.

```powershell
& 'D:\trading thử lần cuối cuối\quant_mt5\quant.cmd' fabio --snapshot '<snapshot_id>' --symbol XAUUSD --report '<thu-muc-output>\fabio_XAUUSD.md'
```

Chi tiết output, basis CVD và cách đọc dữ liệu thiếu: [fabio.md](fabio.md). Khi chạy bản staged/giải nén ở nơi khác thư mục workspace, đặt `QUANTMT5_WORKSPACE` là thư mục chứa các đường dẫn dataset tương đối (mặc định là cha của `quant_mt5`).

Bản Fabio 1.1.0 tự đọc tick từ cùng bundle/snapshot khi không truyền input offline. `paper-run`/phiên khởi tạo mới lấy 240 phút tick mặc định; phiên cũ giữ giá trị đã pin, nên coverage CVD có thể thiếu. Engine hash đổi: khởi tạo phiên mới, không sửa hash của phiên cũ. Không dùng nguồn ngoài MT5 để lấp dữ liệu.
