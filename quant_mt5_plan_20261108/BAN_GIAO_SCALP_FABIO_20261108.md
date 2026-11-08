# Bàn giao Scalp Fabio MT5 — 08/11/2026

Đã triển khai P0–P5 và cài skill **`scalp-fabio`** tại `C:/Users/ductr/.codex/skills/scalp-fabio/`. Cấp nghiệm thu: **SOFTWARE / RESEARCH**. Chưa chạy pilot MT5 trực tiếp, gửi lệnh, kiểm định lợi thế giao dịch hoặc entry M1 trong đợt này.

## Dùng ngay

Gọi: **“Dùng $scalp-fabio đọc snapshot/báo cáo này”** để phân tích artifact sẵn có. Khi muốn dữ liệu mới: **“Dùng $scalp-fabio phân tích các mã trong phiên MT5 demo của tôi”**. Skill dùng collector/snapshot hiện có, một lượt hữu hạn, rồi chọn policy Fabio mới tường minh trên cùng snapshot.

Đọc [skill đã cài](C:/Users/ductr/.codex/skills/scalp-fabio/SKILL.md) và [runbook](C:/Users/ductr/.codex/skills/scalp-fabio/references/runtime.md). `trade-toi` vẫn có vai trò quét ca tối; Fabio là phương pháp riêng và dùng được trên cùng snapshot. Không cần mua footprint/feed hoặc mở tài khoản FTMO để dùng phần phân tích MT5 này.

## Những gì đã thêm

| Phần | Hành vi đã triển khai |
|---|---|
| Policy riêng | `scalp_mt5_v1`, spec `SCALP_FABIO_MT5_V1` v1.0.0; CLI/batch cũ mặc định vẫn Fabio legacy v1.1.0 |
| F1 | Balance trước breakout → acceptance → khóa profile khi pullback được xác nhận → touch sau thời điểm biết vùng → trigger giá; đích là POC balance đã hoàn tất trước đó, tối đa 150 M5 trước start balance hiện tại |
| F2 | Breakout range → reclaim value → pullback/test sau reclaim → trigger hướng POC balance; không dùng nến reclaim làm luôn trigger sau hồi |
| Tính nhân quả | Chỉ dùng nến đóng/đã khả dụng; thời điểm biết tính theo cả prefix, tránh backdate khi nến lịch sử đến trễ |
| Nối các lần quét | `--previous-analysis` giữ balance, bins profile, lựa chọn target (kể cả UNKNOWN), pending balance và hạn trigger qua các snapshot; kiểm source/spec/metadata, hash trạng thái và prefix OHLC/volume/time |
| Định danh và trạng thái | `analysis_id`, `episode_key`, `opportunity_id`, `profile_revision_id`, `revision_id`, `trigger_id`, `plan_id`; tách giai đoạn cấu trúc khỏi khả năng kiểm thực thi |
| Replay riêng | `fabio-replay` nhận plan Fabio và tick đã ghim; dùng lại TickQuotes và bộ đi qua đường quote; giữ SL/target cấu trúc, đúng Bid/Ask, gap có thể lỗ quá 1R |
| Thiếu dữ liệu/phí | Tick thiếu → UNRESOLVED/CENSORED; chi phí thiếu → net UNKNOWN; giá trị phí khai báo là ASSUMED; lưu cả no-fill/expired/skipped |
| Báo cáo/ledger | Artifact bất biến và ledger Fabio riêng; report nêu basis profile/CVD, readiness, ID và nguồn dữ liệu |

F1/F2 là bản M5 thích nghi theo khung nguồn. Mốc 169% không được dùng làm xác suất hay cam kết lợi nhuận của hệ. Các con số balance/LVN/expiry/max-hold là lựa chọn nghiên cứu của dự án, chưa được tối ưu hay kiểm định prospective.

## Cách nối snapshot và replay

Các mẫu dưới dùng CLI thật; thay placeholders bằng ID/path từ output. Với phiên có source bundle, dùng `session exec --root ... --name ... --` như runbook để đọc đúng bundle/store của snapshot.

```powershell
# Lần đầu trên snapshot đã có
& 'D:/trading thử lần cuối cuối/quant_mt5/quant.cmd' fabio --snapshot '<snapshot_id>' --symbol '<symbol>' --policy scalp_mt5_v1

# Lần sau cùng nguồn/mã: truyền artifact quyết định trước
& 'D:/trading thử lần cuối cuối/quant_mt5/quant.cmd' fabio --snapshot '<new_snapshot_id>' --symbol '<symbol>' --policy scalp_mt5_v1 --previous-analysis '<previous_analysis.json>'

# Replay bằng snapshot outcome đã có; commission/slippage vẫn UNKNOWN nếu bỏ hai option phí
& 'D:/trading thử lần cuối cuối/quant_mt5/quant.cmd' fabio-replay --analysis '<analysis.json>' --family F1 --snapshot '<outcome_snapshot_id>' --latency-s 2 --max-hold-s 1800
```

Giữ `FROZEN_PREVIOUS_ANALYSIS_CHAIN` khi nối hợp lệ. Nếu không có artifact trước, output là `RECONSTRUCTED_FROM_PINNED_INPUTS`; dữ liệu/basis mới có thể tạo revision vùng khác. Không lấy bản dựng lại sau outcome để thay plan đã quyết định. Lỗi `FABIO_PREVIOUS_*` phải được xử lý, không bỏ option để tìm một tín hiệu khác. Nến mới có trigger tiếp theo không gia hạn entry của cùng cơ hội.

Entry deadline là close của trigger đầu + 600 giây, episode TTL 150 M5; balance settled 24 bars nằm hoàn toàn sau breakout trước có thể tạo episode mới. Max-hold replay mặc định 1.800 giây là lựa chọn nghiên cứu, không lấy từ phương pháp nguồn như một quy tắc đã xác minh.

## Kiểm thử và bằng chứng

- **287 tests passed, 0 failures, 0 errors**, trong lượt cuối 79,91 giây. Bao gồm Fabio legacy, flow/profile/economics, lifecycle scalp, replay, CLI thực, B3 và các nhóm evening.
- **10 kiểm thử tích hợp CLI thực**, dùng bộ dữ liệu synthetic có checksum: snapshot → Fabio → replay, chain qua coverage mới, phí UNKNOWN/ASSUMED, ngăn đọc tick tương lai và từ chối sai source/spec/checksum/history.
- **18 trường hợp Fabio legacy** khớp hoàn toàn bản sao gốc; **16 trường hợp thực thi A/B** khớp hoàn toàn. `execution.py`, `replay.py`, `paper.py` giữ nguyên SHA-256 so với P0.
- Review độc lập đã tái hiện và xác minh sửa 7 lỗi: basis chart, identity/hash plan, nến đến trễ, thống nhất cost room, pending balance khi nối, hash trạng thái frozen, invalidation không khớp family.
- Skill validator đạt trên bản staged và bản đã cài; 4 file cài có SHA-256 trùng staged. Bài đọc artifact độc lập giữ đúng nhãn lịch sử/proxy/legacy và không phát sinh collection.
- Hiệu năng synthetic 10.080 M5 (35 ngày): median 0,620 giây với bar fallback; 0,324 giây với 100.800 tick. Đây là đo phần phân tích trên máy này, không bao gồm lấy dữ liệu/viết nhận định hay chứng minh độ trễ giao dịch.

Bằng chứng tại [thư mục nghiệm thu](<D:/trading thử lần cuối cuối/quant_mt5/phases/SCALP_FABIO_MT5_20261108/attempt_1_codex/evidence>), gồm `final_pytest.xml`, `CLI_INTEGRATION.md`, `cli_integration_calls.json`, `FINAL_REVIEW.md`, `PARITY_PERFORMANCE.json` và script tái kiểm parity/hiệu năng.

## File và phiên bản

Runtime chỉnh: `quantmt5/fabio.py`, `quantmt5/cli.py`. Runtime thêm: `quantmt5/fabio_replay.py`. Test thêm: `test_scalp_fabio.py`, `test_fabio_replay.py`, `test_scalp_cli_integration.py`.

Skill gồm `SKILL.md`, `agents/openai.yaml`, `references/method.md`, `references/runtime.md`. Không thêm dependency mới. Mọi đường dẫn/hash/spec, phiên bản Python/NumPy/MetaTrader5 và kết quả cài được lưu tại [DELIVERY_MANIFEST.json](<D:/trading thử lần cuối cuối/quant_mt5/phases/SCALP_FABIO_MT5_20261108/attempt_1_codex/DELIVERY_MANIFEST.json>).

Scalp spec hash: `4e17e1f0c34462af2751c0c5ad24bf6416fa9ffd4914987433b4d3baa6e01047`.

Workspace không có Git; bản sao file trước sửa nằm trong `attempt_1_codex/backup/`. Không ghi đè/xóa các thư mục attempt cũ khác. Phiên MT5 đã ghim engine cũ sẽ báo `ENGINE_OR_CONFIG_CHANGED`; runbook hướng dẫn tạo phiên mới khi người dùng yêu cầu lấy dữ liệu tiếp, không sửa hash phiên cũ.

## Giới hạn còn lại

- Quote-direction CVD vẫn là **proxy hoạt động tick** nếu nguồn MT5 thiếu giao dịch có volume/side hợp lệ; không biến nó thành dòng tiền ròng, footprint hoặc bằng chứng ý định cá mập. News là USER_MANAGED.
- Chart basis LAST/UNKNOWN vẫn có thể đọc cấu trúc; execution readiness giữ DATA_MISSING, chưa có plan Bid/Ask cho basis đó. Short SL/target trong replay dùng offset spread tại entry đã khóa, có nhãn giả định.
- Replay chưa xác minh tài khoản, lot/cash, FTMO rules, phiên đóng cửa hoặc độ trễ thực. Phí mô phỏng không là phí account đã đo. Không tự gửi lệnh hoặc theo dõi nền.
- P6 pilot demo, P7 kiểm định và entry M1 chưa chạy. Kết quả hiện tại xác nhận phần mềm tái lập các quy tắc khai báo; chưa chứng minh winrate, lợi thế hay tần suất thực tế.
