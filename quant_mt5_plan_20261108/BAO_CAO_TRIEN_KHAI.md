# Bàn giao nâng cấp quét ca tối — 08/11/2026

Đã triển khai vào runtime `D:/trading thử lần cuối cuối/quant_mt5`. Chức năng phần mềm được kiểm thử bằng fixture và dữ liệu lịch sử; chưa nghiệm thu độ trễ live, p95 hoặc RAM toàn process tree. Không đặt/check lệnh, không mở MT5, không đổi tài khoản, không chạy nền.

## 1. Phiên dùng từ lượt tới

- Root: `D:/trading thử lần cuối cuối/quant_mt5/runtime/on_demand/evening_v2`.
- Tên: **ca_toi_8_v2**; engine hash `53a47917fc3f26661d1e542977a9e4e848a1be38dad06f9a340a142ea14bb5a8`.
- Config hash: `50aae0079de1dfe9c80c7044ac17b1455e76eaf98a3a376159ec3b03c37f94aa`; strategy/cost JSON không đổi so với backup.
- 8 mã: XAUUSD, EURUSD, USDJPY, GBPUSD, USDCAD, USDCHF, AUDUSD, NZDUSD. Preset extended12 thêm EURJPY, GBPJPY, EURGBP, AUDJPY; chưa ghim 12 mã vào phiên mặc định.
- Terminal đã chọn trước đây: `C:/Program Files/MetaTrader 5/terminal64.exe`. Trade mode bắt buộc DEMO khi thực sự attach. Tên native hiện là mapping tường minh cùng tên, chưa chứng minh broker có đủ 8/12 mã.
- Preflight: engine/config khớp, Python 3.13.11, numpy 2.4.3, MetaTrader5 5.0.6180; **PENDING_LIVE_SOURCE_NOT_RUNNING**, initialize=false. Không có terminal đang chạy khi kiểm.
- Phiên bootstrap `ca_toi_8` được giữ nguyên, chưa thu dữ liệu, đã bị thay thế bởi `ca_toi_8_v2` sau sửa nhãn replay cuối. Các phiên cũ khác không bị sửa hash.

Hướng dẫn lệnh: [NANG_CAP_CA_TOI_20261108.md](../quant_mt5/NANG_CAP_CA_TOI_20261108.md).

## 2. Đã thay đổi

### Hiệu năng

- Collector tái dùng khoảng thời gian thực sự đã hoàn tất; lookback trượt không tải lại toàn bộ 35 ngày. Vẫn retry phần thiếu/pending và giữ các chunk cũ bất biến.
- Sửa khoảng đuôi H1/D1 không có nến đóng đủ điều kiện: không tạo cảnh báo thiếu giả; thiếu nến thực vẫn PARTIAL.
- Cache chỉ sống trong một lượt, theo content/pin/cutoff/config. Mỗi lần dùng lại vẫn kiểm SHA; chunk sửa/xóa và generation đã purge không được cache che lỗi.
- Tick tape cache tối đa 12 tape và 256 MiB; có eviction counter. Đây không phải giới hạn RAM toàn tiến trình. Tối ưu index tick theo thời gian M5, vẫn giữ same-ms multiplicity, arrival time, reset/gap và nhãn proxy.
- Card/context thị trường được tạo theo batch trong process scan; báo cáo dùng packet đã có, không mở hai subprocess cho mỗi ứng viên.
- Journal đọc index một lần; bỏ replay lặp của outcome tick-exact đã đóng. Outcome chưa đóng được append bản cập nhật, không ghi đè signal; censor không được hồi sinh sau dọn.

### Universe và vùng vào

- main8/extended12, mapping chính xác, chặn trùng canonical/native và các alias dầu được khai báo. Không đoán hậu tố broker.
- Giữ trạng thái mọi mã yêu cầu, kể cả không có metadata/dữ liệu. Thiếu phí/slippage/conversion giữ economics UNKNOWN và context-only; không tự bịa phí hay tỷ giá cross.
- Giữ nguyên detector/gate A/B và thời hạn entry. A hiển thị vùng WATCHING_RETEST từ anchor cố định thật; H1 rolling chỉ là mô tả. B chưa có precursor.
- Fabio đầy đủ từng mã, giữ giá/state/location/invalidation/expiry/economics và nhãn CVD proxy. Không biến tick-direction thành aggression độc lập.
- Ưu tiên cửa sổ entry còn hợp lệ tại as-of; tính lại tuổi/deadline ở lúc analysis/report sẵn sàng. Không tự xác nhận lệnh có thể vào ngay. Thẻ vượt giới hạn có nhãn DEFERRED_DEEP_ANALYSIS.
- `session check --symbols <mã>`: lượt hữu hạn cho mã đã ghim, lấy dữ liệu mới/snapshot mới, không gia hạn tín hiệu cũ. Nhóm chung currency là cảnh báo phơi nhiễm, không phải tương quan/xác suất thắng. News vẫn UNKNOWN.

### Dọn tick sau lượt cuối

- Chỉ khi người dùng xác định lượt cuối: once → lưu nhận định/note → finish với cycle/generation/snapshot của báo cáo thành công mới nhất.
- Khóa storage và đối chiếu revision chặn token cũ, cleanup khi còn reader/writer, đường dẫn ngoài phạm vi/reparse và consumer ngoài phiên. Không nhận quyền sở hữu kho legacy để dọn hồi tố.
- Xóa accepted/pending/conflict tick payload và checkpoint của generation vận hành; giữ bars, reports, bundles, snapshots, journal/notes và research.
- Outcome chưa đóng thành CENSORED_AT_SESSION_END, net_R=null, không thắng/thua. Receipt xác minh byte/file; lỗi dọn dở có thể retry đúng token.
- G1 bị xóa rồi G2 thu dữ liệu giống hệt vẫn là generation khác. Replay G1 trả TICK_DATA_PURGED_BY_RETENTION, không fallback proxy rồi gọi là exact.
- Chỉ tick synthetic do kiểm thử tạo ra đã được xóa trong turn này. Tick vận hành cũ và kho nghiên cứu của người dùng chưa bị xóa.

## 3. Số đo đã có — không phải SLA live

| Phép đo | Trước | Sau | Giới hạn |
|---|---:|---:|---|
| EURUSD cùng pin, hai lượt đọc detector/flow mỗi chu kỳ; median lặp lần đo đầu | 5,657s | 2,140s | Giảm 62,2%; một mã offline, không full scan |
| Cùng workload, lần đo lại có JSON | 7,181s | 2,065s | Giảm 71,2%; máy có tải đồng thời, không chọn số tốt nhất làm SLA |
| main8 warm cùng as-of | — | 4,773s | 7 ngày bars/240 phút ticks synthetic, không lấy thêm mạng |
| extended12 warm cùng as-of | — | 6,376s | Như trên; đủ 12 context/Fabio; thẻ sâu có giới hạn riêng |
| Phiên 8 → check GBPUSD sau +20 phút | — | 5,149s | Toàn session wall; paper_run 3,604s, scan 2,479s; hơi vượt mục tiêu 5s |

So EURUSD: 7.078 M5 bars, 1.441 tick chunks, 94 candidates, 133 episodes, 287 flow bars usable. Hash toàn catalog và toàn flow/profile/quote khớp trước/sau. Cold ở đây là process-cold, OS cache không được flush.

Warm8/12 sau chỉnh cache: đúng 32/48 collected-bar decodes (4 TF/mã), 8/12 tape decodes, zero evictions và zero request nguồn khi as-of không đổi. Không suy thành zero request cho lần quét mới 20 phút sau. Workload synthetic dùng cùng một tape biến đổi theo mã, không phải đa thị trường độc lập.

Artifacts: [benchmark chi tiết](KET_QUA_HIEU_NANG_20261108.md), [baseline JSON](benchmark_baseline.json), [upgraded JSON](benchmark_upgraded.json), [warm8/12](universe_smoke_absolute_20261108/summary_warm_after_cache_update.json), [focused +20 phút](focused_session_smoke_20261108/summary.json).

Xác nhận trên source cuối sau sửa nhãn replay: [benchmark_upgraded_final.json](benchmark_upgraded_final.json) giữ nguyên parity, median lặp 2,043s. Lượt đầu có outlier **30,294s** khi test dữ liệu lớn khác đang chạy đồng thời; giữ nguyên số này trong báo cáo, không dùng các lần nhanh để cam kết độ trễ.

## 4. Kiểm thử

- Các nhóm mới: mapping/cost/missing data, cache và integrity/cutoff, vùng chờ/deadline/batch, retention và E2E thật qua CLI.
- Trên source cuối: `test_upgrade_reporting`, `test_upgrade_performance`, `test_upgrade_retention`, `test_upgrade_retention_e2e`, `test_upgrade_universe`, `test_runtime_fabio_integration`: **66 passed trong 23,73s**; compileall package thành công. Preflight cuối vẫn engine/config khớp và PENDING vì MT5 chưa chạy.
- Regression replay B3 từng thiếu nhãn ASK_MISSING khi economics UNKNOWN đã được sửa để giữ cả hai lý do; lượt chạy lại bao gồm ca đó + cache + flow: **29 passed**. Không thay logic vào/thoát lệnh để sửa nhãn.
- Bộ regression rộng root: **200 passed, 1 failed**. Ca fail `test_core.py::test_collect_attaches_only_to_running_selected_terminal` do fixture cũ thiếu account_currency; đã chạy lại trên bản backup trước nâng cấp và lỗi y hệt. Không bỏ guard account để làm test xanh.
- Snapshot/context/Fabio + universe/retention: **63 passed** ở lượt kiểm trước. Các suite có giao nhau, không cộng số để báo tổng độc lập.
- E2E session once/repeat/+5 phút: **2 passed** sau sửa micro-tail H1/D1.
- Retention E2E: init → once → committed report → finish → old replay PURGED → idempotent finish → lần sau generation mới → stale finish bị từ chối. Xác minh bytes/files đã xóa và hash bars/report/bundle/snapshot không đổi.
- Focused E2E: nguồn không đổi, snapshot mới; token lượt 8 mã cũ bị từ chối, token check mới CLOSED. Chỉ dữ liệu synthetic trong vùng thử.
- Có thêm lỗi baseline D1 lower-bound và fixture B1 thiếu currency đã được xác nhận tồn tại trước nâng cấp; chi tiết trong báo cáo hiệu năng. Không tuyên bố toàn bộ test repository xanh.
- Skill vận hành đã cập nhật batch/check/finish và kiểm bằng quick_validate; hướng dẫn dự án cập nhật tick warmup 240 phút.

## 5. Chưa nghiệm thu / rủi ro còn lại

1. Chưa có lượt native demo mới: MT5 chưa mở; ngày kiểm là Chủ nhật. Cần xác minh mã broker, freshness, clock và economics thực tế khi có nguồn. Không tự mở/đăng nhập MT5.
2. Chưa có ≥20 lượt native warm để tính p50/p95/max, workload35 ngày toàn8/12 và peak RSS toàn process tree. Mục tiêu 30s/45s/5s chưa được chứng nhận; focused synthetic5,149s không được đánh PASS ≤5s.
3. Cặp mới chưa có chi phí đầy đủ chỉ context/UNKNOWN. Lịch phiên/D1 chưa biết giữ nhãn UNKNOWN; không sao chép lịch EURUSD tùy ý.
4. Nhịp 20 phút có thể bỏ lỡ entry 90 giây. Không đổi gate để làm đẹp winrate hoặc kéo dài tín hiệu.
5. Dọn raw ticks đánh đổi khả năng replay exact ngày cũ. Báo cáo/derived evidence còn giữ không thay thế nguyên tape. Outcome chỉ theo candidate được các snapshot quan sát; chưa là hệ thống đối soát fill broker/ledger hoàn chỉnh.
6. Nâng cấp phần mềm không chứng minh tỷ lệ thắng tăng. Một tuần 8/10 và các biến thể chồng lặp chưa xác lập edge; vẫn cần mẫu forward độc lập và lợi nhuận ròng sau phí.

Bản sao trước nâng cấp: `baseline_before_upgrade/` (package/config/tests/CLI và hướng dẫn cũ). Không sửa/xóa archive nghiên cứu, không đổi threshold strategy/cost JSON. Không có repository Git hợp lệ để tạo commit; `.git` cũ rỗng được giữ nguyên.
