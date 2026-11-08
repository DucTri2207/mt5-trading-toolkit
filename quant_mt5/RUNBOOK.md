# RUNBOOK: Quy trình quét cơ hội và Brainstorm buổi tối (Quant MT5 v0.2)

Tài liệu hướng dẫn quy trình vận hành buổi tối chuẩn hóa cho Agent và chuyên viên định lượng.
*Lưu ý quan trọng*: Dữ liệu hiện tại là lịch sử đã tiếp xúc (`HISTORICAL_EXPOSED`), B6 đã có đường thu MT5 **chỉ đọc** (B6A readiness/collect/parity, B6B bundle→snapshot→paper journal, B6C1 phiên quét theo yêu cầu); việc chạy trên nguồn MT5 demo thật vẫn chờ người dùng mở đúng terminal. Mọi kết quả phục vụ kiểm chứng mô hình, không diễn giải lãi lỗ thực tế.

---

## 1. Chuỗi lệnh vận hành từng bước

### Bước 1: Kiểm tra tính sẵn sàng của hệ thống (Doctor)
- **Lệnh**:
  `quant.cmd doctor`
- **Giải thích**: Kiểm tra tính toàn vẹn của registry dữ liệu, config và môi trường runtime.
- **Trường cần đọc trong output**: `status` (`OK`), `quality` (rỗng hoặc danh sách cảnh báo), `data.checks`.

### Bước 2: Tạo Snapshot bất biến tại thời điểm đánh giá
- **Lệnh**:
  `quant.cmd snapshot --as-of "2026-10-22T16:00:00Z" --universe XAUUSD,EURUSD,USDJPY`
- **Giải thích**: Cố định dữ liệu thị trường và chạy bộ dò tìm setup tính đến thời điểm as_of, sinh `snapshot_id`.
- **Trường cần đọc trong output**: `status`, `snapshot_id`, `data.n_candidates`, `data.snapshot_path`.

### Bước 3: Quét danh sách cơ hội (Scan)
- **Lệnh**:
  `quant.cmd scan --snapshot <snapshot_id>`
- **Giải thích**: Tổng hợp các ứng viên đủ điều kiện hoặc bị chặn theo từng symbol trong snapshot.
- **Trường cần đọc trong output**: `status` (`OK` hoặc `OK_EMPTY`), `rows` (danh sách candidate_id, setup, plan_state).

### Bước 4: Xuất thẻ cơ hội (Card)
- **Lệnh**:
  `quant.cmd card --snapshot <snapshot_id> --candidate <candidate_id>`
- **Giải thích**: Ghép toàn bộ dữ liệu định danh, điều kiện kích hoạt, baseline plan, features và evidence của ứng viên.
- **Trường cần đọc trong output**: `data.identity`, `data.why`, `data.baseline`, `data.context`, `data.evidence`, `data.notes_revision`.
- **Tái dựng thẻ cũ** (chỉ các note đã ghi tới thời điểm đó): `quant.cmd card --snapshot <snapshot_id> --candidate <candidate_id> --notes-as-of "<UTC>"`. Phần lõi (identity/why/baseline/context/evidence) không đổi theo note; chỉ `brainstorm_notes` + `notes_revision` đổi.

### Bước 5: Truy vấn ngữ cảnh chi tiết bổ sung (Context - tùy chọn)
- **Lệnh**:
  `quant.cmd context --snapshot <snapshot_id> --candidate <candidate_id> --groups ema,adx,rsi,er,atr_pct`
- **Giải thích**: Trích xuất bổ sung các nhóm chỉ báo kỹ thuật tùy chọn tính tại thời điểm ra quyết định.
- **Trường cần đọc trong output**: `data.features` (các cặp name, value, quality, available_at).

### Bước 6: Viết Analysis Note JSON và nạp vào hệ thống
- **Lệnh**:
  `quant.cmd note add --file analysis_note.json`
- **Giải thích**: Thẩm định và ghi nhận phân tích định tính của agent vào nhật ký append-only.
- **Trường cần đọc trong output**: `status` (`OK`), `data.note_id`, `data.differs_from_baseline`, `data.features_verified`.

### Bước 7: Ghi nhật ký vận hành (Journal)
- **Lệnh**:
  `quant.cmd journal add --kind observation --text "Hoan tat brainstorm phien toi" --candidate <candidate_id> --snapshot <snapshot_id>`
- **Giải thích**: Ghi nhận một dòng quan sát/nhật ký vận hành độc lập (không gửi lệnh thị trường).
- **Trường cần đọc trong output**: `status` (`OK`), `data.journal_id`, `data.note`.

### Bước 8: Đóng băng phiên bản hệ thống (Freeze)
- **Lệnh**:
  `quant.cmd freeze --label "evening_scan_freeze"`
- **Giải thích**: Lưu trữ bản ghi băm bất biến của engine, config, strategy và dataset manifest.
- **Trường cần đọc trong output**: `status` (`OK`), `data.freeze_id`, `data.already_frozen`.

---

## 2. Ví dụ Analysis Note JSON hợp lệ (`analysis_note.json`)

File JSON phải thỏa mãn tất cả các trường REQUIRED trong `quantmt5.notes`. `snapshot_id`/`candidate_id` dưới đây chỉ là ví dụ: snapshot ID phụ thuộc engine/config/data hash, nên luôn lấy ID thật từ output `snapshot`/`scan`. Quy tắc thời gian: `as_of` ≤ as_of của snapshot và ≥ ready của candidate; `created_at` (nếu ghi) phải ≥ `as_of` và không ở tương lai; hệ thống tự ghi `recorded_at`. `baseline_eligibility` được engine tính tại `as_of` của note (gate, ready, entry deadline; block chỉ tính khi đã quyết định trước `as_of`): tín hiệu đã hết hạn là `NOT_ELIGIBLE_EXPIRED`, nên WAIT/SKIP sau deadline không phải là lệch baseline. `supersedes` chỉ được trỏ tới note trước đó của cùng snapshot/candidate/branch. Gửi lại đúng file có `created_at` sẽ bị chặn `NOTE_ALREADY_RECORDED` (idempotent); file không có `created_at` thì mỗi lần gửi là một note mới.

```json
{
  "author": "agent-brainstorm",
  "snapshot_id": "SNAP_8ff609fda5451ccb3fa1",
  "candidate_id": "CB_bb2c82afc505a1c96f2f",
  "branch": "P0",
  "as_of": "2026-10-22T05:01:00Z",
  "features_used": [
    {
      "name": "atr14_wilder",
      "tf": "M5",
      "value": 2.0700000000001637
    },
    {
      "name": "rvol20_tick",
      "tf": "M5",
      "value": 1.25
    }
  ],
  "observations": "Nến tín hiệu F đóng cửa ngược chiều mẹ tạo setup inside bar breakout thất bại rõ nét.",
  "preferred_scenario": "Giá tiếp tục quán tính giảm theo hướng phá vỡ biên dưới.",
  "alternative_scenario": "Giá đảo chiều hồi phục vượt qua đỉnh nến F.",
  "change_mind_conditions": [
    "Giá đóng cửa vượt mức Stop Loss",
    "Khối lượng tick đột biến ngược chiều"
  ],
  "missing_data": [],
  "agent_action": "CONSIDER_ENTRY",
  "next_check": "Đóng nến M5 tiếp theo",
  "deviation_reason": "",
  "created_at": "2026-11-03T16:00:00Z"
}
```


---

## 3. B6A — Kiểm nguồn MT5 chỉ đọc (readiness / collect / parity)

Không lệnh nào dưới đây mở terminal, đăng nhập, đổi tài khoản, bật Algo Trading hay gửi lệnh. Nếu terminal được chọn trong `config/datasets.json` (`source_identity.terminal_executable`) **chưa chạy**, công cụ không gọi `initialize` và trả `PENDING_LIVE_SOURCE_NOT_RUNNING`.

1. Người dùng tự mở đúng terminal, đã đăng nhập tài khoản dự định.
2. `quant.cmd readiness` → đọc `data.status`:
   - `LIVE_IDENTITY_OK_PROFILES_COMPLETE`: đọc được path/connected/account (chỉ lưu fingerprint) và profile đầy đủ.
   - `..._PROFILES_INCOMPLETE`: xem `symbols.<SYM>.profile_check.invalid`.
   - `ERROR` + reason (`ATTACHED_TERMINAL_PATH_MISMATCH`, `TERMINAL_DISCONNECTED`, `ACCOUNT_INFO_NONE`, ...): dừng.

   `clock_probe.assessment` không bao giờ là VERIFIED. Một probe hiện tại không xác minh được clock/DST của cache 2021–2026; cache đó vẫn là EET_EU ASSUMED.
3. Thu mẫu có giới hạn (store riêng, không đụng registry/main store): `quant.cmd collect --terminal-path "<dir>" --symbols XAUUSD,EURUSD,USDJPY --start <now-35d> --end <now> --tick-start <now-15m>`.
4. `quant.cmd parity --rows <B3 cash ledger JSONL> [--observe-margin]`:
   - `OK` chỉ khi mọi dòng đều được so sánh và khớp.
   - `PARTIAL_MATCH`: có dòng bỏ qua.
   - `INCONCLUSIVE_*`: không có ca so sánh được, hoặc calculator trả None.
   - `MISMATCH`: có dòng lệch.
   - Phép so này chỉ kiểm gross P&L; commission/swap/slippage chưa được xác minh; margin chỉ là quan sát.
   - Chỉ so khi tiền tệ tài khoản native (đã định danh) trùng `cash.account_currency` của dòng; thiếu hoặc khác đơn vị → SKIPPED có reason, không tự quy đổi. Nếu identity/account/currency đổi giữa batch → `INVALIDATED_SOURCE_CHANGED`. Profile chỉ COMPLETE khi đúng miền giá trị; `profit_formula_capability` cho biết công thức tuyến tính có áp dụng được không.


---

## 4. B6B — Nguồn thu thập → bundle → snapshot/scan/card/replay → paper journal (one-shot, không daemon)

Mỗi nguồn thu thập được đóng thành một **bundle config/source bất biến** `CFGB_<id>/`:
- strategy, cost và exposure sao nguyên;
- profile map từ `symbol_info` native (có `raw_native_profile`; session kế thừa được ghi `ASSUMED_INHERITED`);
- `datasets.json` chỉ trỏ tới chunk của nguồn đó;
- `BUNDLE_MANIFEST.json` lưu sha của từng file.

Một process chọn bundle bằng `QUANTMT5_CONFIG_DIR=<đường dẫn tuyệt đối tới bundle>`, đặt trước khi chạy. Sửa bất kỳ file nào → `CONFIG_BUNDLE_TAMPERED`. Snapshot ghim bundle và tập tick chunk; đọc snapshot bằng config khác → `CONFIG_BUNDLE_MISMATCH`. Registry lịch sử và main store không bị sửa.

1. **Native one-shot** (chỉ khi người dùng đã tự mở đúng terminal và đăng nhập; nếu không → `PENDING_LIVE_SOURCE_NOT_RUNNING`, không initialize):
   `quant.cmd paper-run --terminal-path "C:\Program Files\MetaTrader 5" --symbols XAUUSD,EURUSD,USDJPY --out-root "<thư mục riêng>"`
   (`--symbols CANON=NATIVE` khi broker dùng hậu tố; mapping phải khai báo rõ, không đoán). Mặc định: bars 35 ngày, ticks 15 phút.
2. Output trong `<out-root>`:
   - `raw/<source_id>/` chứa chunk; namespace gắn với exe/data_path/server/account fingerprint/currency/provider;
   - `bundles/CFGB_*/`;
   - `store/snapshots/`;
   - `store/journal/paper_<source_id>.jsonl` gồm `paper_signal` (dedup theo nguồn + candidate revision) và `observation` cho mỗi lượt, kể cả lượt không có tín hiệu, dữ liệu stale hay lỗi.
3. Xem lại trong process của bundle (đặt `QUANTMT5_CONFIG_DIR` và `QUANTMT5_STORE=<out-root>\store`):
   - `quant.cmd scan --snapshot <id>`
   - `quant.cmd card ...`
   - `quant.cmd context ...`
   - `quant.cmd replay --candidate <id> --snapshot <id>`: `quote_basis` cho biết đang dùng `COLLECTED_*_TICKS` hay `M1_OPEN_PROXY` (kèm `tick_note`)
   - `quant.cmd paper-scan --as-of <UTC>`: chạy lại không ghi trùng
4. Analysis note: `quant.cmd note add --file <note.json>` trong cùng process bundle. Hệ thống không tự gọi LLM.
5. **Demo tổng hợp** (máy sạch, không cần MT5): `python -X utf8 quant_mt5/phases/B6B_INTEGRATION_20261104/attempt_1/scripts/b6b_demo.py`, sau đó đọc `DEMO_RESULT.json`. Dữ liệu demo là **SYNTHETIC**, không phải bằng chứng thị trường.

Nhãn provider: chỉ module MetaTrader5 thật được import bên trong collector mới là `NATIVE_TERMINAL`; module inject luôn là `SYNTHETIC_INJECTED_MODULE`. `NATIVE_COLLECTED` chỉ nói nguồn thu, không chứng minh clock hay edge. Dữ liệu thu lại từ quá khứ không phải bằng chứng forward.


---

## 5. B6C1 — Phiên quét theo yêu cầu (on-demand, không daemon)

Hướng dẫn ngắn bằng tiếng Việt cho buổi tối: `quant_mt5/HUONG_DAN_DEMO_TOI_NAY.md`.

- `quant.cmd session init --root <dir> --name <tên> --terminal-path <thư mục MT5> --symbols XAUUSD,EURUSD,USDJPY`: cố định engine/config/FTMO 1-Step + MT5 demo; vốn/risk/luật để UNCONFIGURED/UNKNOWN.
- `quant.cmd session preflight ...`: kiểm runtime và nguồn. Terminal không chạy → `PENDING_LIVE_SOURCE_NOT_RUNNING`, không gọi initialize.
- `quant.cmd session once ...`: một lượt có giới hạn (child process có timeout) → báo cáo `reports/*.md|json`. Có khóa một writer; identity được ghim từ lượt thành công đầu tiên; tài khoản phải là `trade_mode` DEMO; chạy lại không ghi trùng.
- `quant.cmd session exec ... -- <lệnh quant>`: chạy card/context/replay/note trong đúng bundle đã ghim.
- `quant.cmd session status|summary ...`.
- Runner nền (`session run|start|stop`) chỉ là **tùy chọn**, không cần cho luồng theo yêu cầu.

### 5.1 Bản sửa 043 (native first-use)
- **Clock nguồn** (`source-clock-policy-v1`): trước khi thu dữ liệu, collector probe tick mới nhất của mọi mã và chọn **một** profile cho cả nguồn (offset 0 → `RAW_IS_UTC`; +7200/+10800 → `EET_EU`, ghi `NY_PLUS_7` là phương án khác). Các probe tươi mâu thuẫn nhau, hoặc mâu thuẫn với clock đã ghim → `CLOCK_CONFLICT`, không ghi gì. Không có probe tươi → `RAW_IS_UTC` gắn nhãn `CLOCK_UNRESOLVED` (hoặc dùng clock đã ghim). Request MT5 gửi theo giờ server (raw); window, coverage, cắt nến đang chạy, cutoff/as-of và tuổi quote đều tính theo UTC qua cùng profile; raw timestamp lưu nguyên. Registry dùng contract `API_SERVER_CLOCK_PROBED` với `clock_profile_applied`; tick pin mang `clock_profile`. Trạng thái luôn là `PROBE_ASSUMED_NOT_VERIFIED`.
- Store đã thu theo clock khác → `CLOCK_PROFILE_CHANGED_FOR_STORE` (dữ liệu cũ giữ nguyên; tạo phiên mới). `paper-run --clock-profile` chỉ do session truyền từ pin.
- **Lỗi một mã** (MemoryError, None, ngoại lệ giữa chừng) không làm hỏng các mã khác; mã đó không được publish trong batch, các window đã commit được giữ để lượt sau tiếp tục. None → window `ERROR_NONE_RETURNED` kèm `last_error`, mỗi lượt một lần gọi.
- `context --at as_of`: market state lấy tại as-of, feature của nến tín hiệu giữ nguyên nến của ứng viên; `feature_time_basis` cho biết mỗi nhóm lấy ở đâu. `--at decision` không đổi.
- `quote_age_s` chỉ từ băng tick đã pin (không có → `UNKNOWN`); độ trễ nến là `bar_watermark_age_s`.

## 9. Fabio và CVD tự lấy dữ liệu MT5

`quant.cmd fabio --snapshot <SNAP_ID> --symbol <SYM> --report <out.md>` dùng cùng config/store/snapshot với lượt quét. Không cần file export; tick đã ghim từ MT5 được kiểm SHA, chuyển clock một lần, lọc as-of để tính CVD và quote.

- F1: accepted exit → impulse/LVN → pullback → phản ứng giá. F2: failed breakout → reclaim → pullback ở nến sau → trigger về POC.
- Khi broker cung cấp trade flags + volume hợp lệ: CVD từ dữ liệu khớp lệnh của broker. Nếu chỉ Bid/Ask: CVD tick-direction proxy (+1/-1/0 theo midpoint), ghi rõ không phải executed volume.
- Profile theo tick tại giá khi đủ coverage; nếu thiếu thì tick volume phân bổ trong range nến, ghi xấp xỉ. Không đếm proxy như bằng chứng độc lập với giá.
- Giá stale chặn mọi family/variant. Commission/slippage thiếu giữ UNKNOWN; không ngầm định 0. Quyết định không phải order; xác suất thắng luôn null.
- `paper-run` và phiên mới mặc định 240 phút tick hữu hạn; phiên cũ giữ horizon đã pin. Engine thay đổi cần phiên mới, không sửa session cũ để vượt pin.
- `--flow`/`--exec` chỉ dành cho chẩn đoán offline contract cũ, nhãn `EXPLICIT_OFFLINE_INPUT`; skill vận hành MT5 không dùng các tham số này.
- Output riêng trong `store/fabio`. Không ép vào card/note baseline; lưu journal observation nếu chưa có candidate baseline hợp lệ.

Spec FABIO_FTMO_V1 v1.1.0, hash/params trong output; đây là operationalization nghiên cứu, chưa xác minh cải thiện winrate. Xem skill reference `references/fabio.md` để đọc coverage/reset/basis.
