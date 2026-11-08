# Hướng dẫn demo tối 04/11/2026 — quét theo yêu cầu (FTMO 1-Step, MT5 demo)

> Bản vận hành mới 08/11/2026: xem [NANG_CAP_CA_TOI_20261108.md](NANG_CAP_CA_TOI_20261108.md) cho main8/extended12, batch analysis, check một mã và finish dọn tick. Các ví dụ phiên `toi_nay` dưới đây là lịch sử; không sửa engine hash của phiên cũ.

Công cụ **chỉ đọc**: không đặt lệnh, không kiểm tra lệnh, không đăng nhập, không đổi tài khoản. Muốn thử lệnh demo thì bạn tự đặt trong MT5. Mỗi lần gọi chạy một lượt có giới hạn rồi kết thúc; không cần chương trình chạy nền.

Thư mục làm việc: `D:\trading thử lần cuối cuối`. Lệnh: `quant_mt5\quant.cmd` (chạy được từ bất kỳ thư mục nào).

## 0. Chuẩn bị (một lần)
1. Mở **MT5 demo** ở đúng đường dẫn sẽ khai báo (mặc định `C:\Program Files\MetaTrader 5`) và đăng nhập **tài khoản DEMO**. Công cụ đọc `trade_mode` thật của tài khoản; tài khoản live, contest hoặc không xác định đều bị từ chối.
2. Tạo phiên, chọn thư mục riêng (có dấu hoặc khoảng trắng đều được):
   ```
   quant_mt5\quant.cmd session init --root "D:\trading thử lần cuối cuối\phien_demo" --name toi_nay --terminal-path "C:\Program Files\MetaTrader 5" --symbols XAUUSD,EURUSD,USDJPY
   ```
   Lệnh này ghi lại engine, config, symbol, FTMO 1-Step / MT5 demo, kèm ghi chú: vốn, risk và chế độ luật (Best Day hay Consistency) là UNCONFIGURED/UNKNOWN; đánh giá challenge thuộc B6C2.
   - Tên native khác (ví dụ có hậu tố): `--symbols XAUUSD=XAUUSD.r,...`. Phải khai báo rõ, công cụ không đoán.
3. Kiểm tra trước: `quant_mt5\quant.cmd session preflight --root "...\phien_demo" --name toi_nay`
   - `READY_TO_ATTACH`: terminal đang chạy, có thể quét.
   - `PENDING_LIVE_SOURCE_NOT_RUNNING`: chưa mở đúng terminal. Công cụ không tự mở và không gọi initialize.

## 1. Quét trước phiên / khi rảnh (mỗi lần gọi một lệnh)
```
quant_mt5\quant.cmd session once --root "D:\trading thử lần cuối cuối\phien_demo" --name toi_nay
```
Lượt quét: xác minh nguồn demo → thu dữ liệu có giới hạn (bars 35 ngày, ticks 240 phút mặc định cho phiên mới; phiên cũ giữ cấu hình đã ghim) → snapshot → scan nhiều mã → replay → ghi journal → tạo báo cáo → thoát.

Kết quả là một JSON có `data.status` và `data.report.report_md`. Mở file `.md` đó để đọc:
- trạng thái từng mã (`FRESH` / `STALE` / `MARKET_CLOSED` / lỗi kèm lý do);
- từng ứng viên: setup, hướng, gate, trạng thái plan, entry/SL/TP tham khảo, hạn entry;
- replay kèm `evidence_grade`: `NATIVE_TICK_EXACT` / `*_PARTIAL_COVERAGE` / `PROXY_M1_OPEN_NOT_EVIDENCE`;
- context ATR / RVOL lấy cùng snapshot;
- lệnh mở card.
- **cửa sổ entry tại as-of**: `CÒN TRONG CỬA SỔ ENTRY` hoặc `ĐÃ HẾT HẠN — chỉ quan sát, KHÔNG phải tín hiệu vào lệnh`. Replay của ứng viên cũ là mô phỏng quá khứ, không phải lệnh có thể vào bây giờ;
- dòng **Clock nguồn** (ví dụ `EET_EU · ASSUMED_FROM_CURRENT_PROBE · offset 7200 s`): công cụ tự đo clock server từ tick mới nhất (MetaQuotes-Demo ≈ UTC+2) và dùng **cùng một** quy ước cho request, nến, tick, cutoff. Lần gọi đầu ghim clock vào phiên; các lần sau phải khớp, lệch thì `HALT` (`CLOCK_CONFLICT`). Lịch sử/DST vẫn chưa xác minh;
- **tuổi quote (tick)** lấy từ băng tick đã thu; **tuổi nến M5 đóng** là độ trễ nến — hai số khác nhau. Không có tick thì tuổi quote là `UNKNOWN`.

Nếu quote mới nhưng M5 `STALE`: engine dùng tuổi nến M5 đóng (ngưỡng hiện tại 600 giây), nên tick mới không làm nến cũ thành `FRESH`. Kiểm tra snapshot → `data_versions` → chunk/checkpoint đúng bundle của lượt đó: `last_raw`, bounds đã yêu cầu và `missing_open_ranges`. `PARTIAL_GAPS` ở cuối cửa sổ nghĩa là dữ liệu nến trả về chưa đủ, không chứng minh thị trường không có tick. Collector thử mỗi cửa sổ một lần trong mỗi lượt; cửa sổ thiếu được lấy lại ở lượt tiếp theo, giữ chunk/pin cũ. Khi MT5 demo đang mở đúng nguồn, gọi lại `session once` rồi kiểm tra cả tuổi quote, tuổi M5 và coverage. Preflight `READY_TO_ATTACH` hoặc scan `OK` riêng lẻ chưa chứng minh smoke native đã đạt; cần kết quả thu native mới có M5 cập nhật và mọi khoảng thiếu còn lại được giải thích.

### Đọc trạng thái
| `data.status` | Nghĩa |
|---|---|
| `OK` / `PARTIAL` | Đã quét. `PARTIAL` = có cảnh báo coverage (xem báo cáo). |
| không có ứng viên | "Không có setup trong 24h" — đã quét, **không phải lỗi**. |
| `PENDING_SOURCE` | Terminal chưa chạy hoặc sai đường dẫn. Mở MT5 demo rồi gọi lại. |
| `HALT` | Dừng an toàn: tài khoản khác với lần đầu (identity đã ghim), tài khoản không phải demo, clock nguồn mâu thuẫn với clock đã ghim (`CLOCK_CONFLICT` / `CLOCK_PROFILE_CHANGED_FOR_STORE`), hoặc journal hỏng. Đọc `reason`; nếu muốn dùng tài khoản khác thì tạo phiên mới. |
| `TIMEOUT` / `ERROR` | Lượt quét bị cắt có giới hạn; gọi lại. Dữ liệu cũ không mất, không ghi trùng. |
| `REFUSED` | Đang có một lượt khác chạy cùng phiên (khóa một writer). Đợi xong rồi gọi lại. |

## 2. Xem chi tiết và ghi phân tích (dùng cùng snapshot)
- Card: `quant_mt5\quant.cmd session exec --root "...\phien_demo" --name toi_nay -- card --snapshot <SNAP_ID> --candidate <CAND_ID>`
- Context đầy đủ: `... session exec ... -- context --snapshot <SNAP_ID> --candidate <CAND_ID> --groups ema,adx,rsi,er,atr_pct`
- Context hiện tại (thị trường lúc as-of, tín hiệu giữ nguyên nến của nó): thêm `--at as_of` vào lệnh context ứng viên.
- Ghi note brainstorm (mẫu JSON ở RUNBOOK §2): `... session exec ... -- note add --file note.json`. Giá trị feature trong note phải là giá trị **tại thời điểm quyết định** của ứng viên (context mặc định `--at decision`); trích giá trị as_of sẽ bị từ chối `FEATURE_VALUE_MISMATCH`.
- `exec` tự chạy trong đúng bundle mà snapshot đã ghim.
- Journal paper: `...\phien_demo\sessions\toi_nay\data\store\journal\paper_<source>.jsonl`. Báo cáo: `...\sessions\toi_nay\reports\`.
- Tổng hợp mô tả: `quant_mt5\quant.cmd session summary --root ... --name toi_nay` (chỉ đếm số liệu; không phải edge, không phải PASS FTMO).

## 3. Kết thúc / phục hồi
- Mỗi lần `once` tự kết thúc, không để lại process.
- `session status` cho biết trạng thái khóa, heartbeat và lần chạy gần nhất.
- Nếu máy tắt giữa chừng: gọi lại `once`. Dòng ghi dở ở cuối journal được tách ra file `.partial_*` và có ghi vết; dòng hỏng ở giữa file làm phiên `HALT`. Khóa cũ của process đã chết được thu hồi có ghi vết; công cụ không giết process khác.
- (Tùy chọn, không cần cho tối nay) runner nền: `session start` / `session status` / `session stop [--force]`.

## Checklist tối nay
- [ ] MT5 demo đang mở đúng đường dẫn, đã đăng nhập tài khoản DEMO.
- [ ] `session preflight` → `READY_TO_ATTACH`.
- [ ] `session once` → đọc báo cáo `.md`.
- [ ] (Nếu muốn) tự đặt lệnh demo trong MT5. Công cụ không đặt lệnh.

Giới hạn: seed v0.1 âm hoặc không được hỗ trợ trong nghiên cứu lịch sử B4. Phí và session vẫn là ASSUMED. Clock: giả định từ probe hiện tại, lịch sử/DST chưa xác minh. Lịch phiên (giờ nghỉ hằng ngày) kế thừa từ profile cũ là ASSUMED: XAUUSD trên MetaQuotes-Demo nghỉ 23:00–24:00 giờ server nên báo cáo có `PARTIAL_GAPS` ở giờ đó — là nhãn coverage, không phải mất dữ liệu do lỗi. Phiên tạo trước bản sửa 043 (đã thu theo quy ước UTC cũ) sẽ bị từ chối `CLOCK_PROFILE_CHANGED_FOR_STORE`: hãy tạo phiên mới (`session init --name ...` tên khác). Báo cáo hỗ trợ quan sát và phân tích, không hứa lợi nhuận hay khả năng pass FTMO.
