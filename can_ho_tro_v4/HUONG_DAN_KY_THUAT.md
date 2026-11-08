# Cản Hỗ Trợ v4.0.3 — Hướng dẫn kỹ thuật

Bản v4.0.3 ngày 02/11/2026, chờ Claude nghiệm thu claude_014. Cùng vùng H1/tín hiệu M5 trên M1–D1, replay 90 ngày, dashboard thu gọn và mặc định xóa khung thống kê. Giữ sửa risk/state của v4.0.2. Indicator quan sát/ghi journal; TesterEA chỉ dùng Strategy Tester. ZIP v4.0 M3a không được phát hành vì lỗi lot ×10.

## Cài thủ công

1. Giải nén vào thư mục mới. Kiểm SHA-256 ZIP bằng MANIFEST.json bên cạnh; MANIFEST.json bên trong liệt kê hash từng file payload.
2. Trong MT5 của người dùng, File → Open Data Folder. Tự chép các nhánh MQL5/Include, MQL5/Indicators, MQL5/Experts vào nhánh tương ứng. Không ghi đè v3.01; v4 có tên riêng.
3. Refresh Navigator, mở duc_tri_can_ho_tro_v4 và Load Presets/indicator_default.set. EA dùng Presets/ea_default.set trong Strategy Tester. Không gắn EA lên chart giao dịch.
4. Indicator yêu cầu detector H1/M5 (PERIOD_CURRENT được giải về H1/M5), bất kể khung chart. CSV/checkpoint theo symbol + fingerprint detector/plan đã resolve; **không chứa khung chart**. ATR detector dùng đúng H1/M5. CSV score thêm hash chi phí/account. Một chart giữ khóa writer; chart khác đọc cùng ledger, zone snapshot, checkpoint và score; chart còn lại tiếp quản khi writer đóng.

Bộ v4.0.2 có CHART trong fingerprint được giữ nguyên, không tự nhập/ghép. Corrupt signals/state/candidates/guard/score và zone snapshot của bộ riêng được archive rồi replay lại; lỗi khóa tạm thời không coi là corrupt. Không xóa/ghép archive thủ công để ép phục hồi.

## Lịch sử và hiển thị v4.0.3

- InpHistoryDays=90: namespace mới replay mọi M5 broker khả dụng trong số ngày lịch. OnTimer chia tối đa 32 observations/lượt, ngân sách khoảng 50ms (một lần quét H1 có thể vượt ngân sách), có ngày đang xử lý trên chart. LtfBarsScan=300 vẫn là lookback của mỗi quyết định. Đổi HistoryDays tạo namespace mới nếu giá trị khác 90.
- Quét đầy đủ khi closed H1 thay đổi; M5 trong cùng prefix H1 dùng cùng vùng. Không đưa forming H1/D1 vào detector. HIST độc lập quét lại mỗi M5 để đối chiếu.
- InpShowExpiredZones=true: vùng hết hiệu lực trong cửa sổ lịch sử có màu mờ. Vùng active luôn hiện, không bị quota MaxZones/giá hiện tại che mất; các bộ lọc detector/xếp hạng giữ như trước. Vùng nguồn có khung riêng, từ base start đến invalid H1 đóng. Vùng active kéo tới mở H1 hiện tại + ExtendBars H1 trên mọi chart.
- Arrow dùng signal_id làm tên riêng, vào nến chart chứa **confirm_bar_open M5**, giống arrow M5 gốc. Tooltip ghi signal_known_time giờ server, hướng, entry/initial SL/TP1/TP2, ID/loại vùng, khoảng risk và % equity. Nhiều tín hiệu chung nến H4/D1 vẫn là các object riêng.
- InpShowStatsPanel=false: xóa toàn bộ M2_* cũ, kể cả M2_BG/nút cũ; CSV vẫn ghi. Nút CSV nhỏ ở chân dashboard chính. Cảnh báo quan trọng một dòng phía dưới; trong replay ưu tiên dòng tiến độ.
- InpDashCollapsed=true: mặc định thanh nhỏ; nút +/− mở/thu. ShowDash tắt bảng chính; tiến độ/cảnh báo vẫn hiện. DashRight chọn trái/phải, InpDashBottom chọn trên/dưới. Dashboard mở đầy đủ cần chart đủ cao hoặc giảm DashScale.
- Khôi phục và vẽ ngay cả khi chưa có M5 mới. Snapshot nhị phân là cache hiển thị; ledger CSV là bằng chứng tín hiệu. File owner_<key>.lock chỉ dùng giữ khóa; không xóa khi terminal đang chạy.


## Tín hiệu, panel và export

confirm_bar_open là mở nến xác nhận; signal_known_time là lúc đóng; publish_time là lúc công bố. Không fill trước known/order_place_time. source_zone_id ổn định theo hình học/start/side/point. Candidate chịu gate một display plan; ACTIVE_PLAN không phải lệnh khớp. MaxTests/MaxAgeBars giữ hành vi hiện có, không thêm bộ lọc.

HIST hồi cứu OHLC, khi SL/TP cùng nến dùng SL trước và ghi ambiguous. LIVE mô phỏng theo quote quan sát từ khởi động; gián đoạn ghi LIVE_GAP và loại P&L. Timeout theo đồng hồ, không kéo dài bằng số bar. InpScoreExit chọn EXIT_1R hoặc TRAIL; TP1/TP2 của plan hiển thị không đồng nghĩa TP broker.

n/closed/pending-excl lần lượt là tổng tín hiệu/đã đóng/chờ hoặc loại. Gross/net R là trung bình R của lệnh đóng; win% theo net R; PF_R = tổng net R dương / trị tuyệt đối tổng net R âm. fee/R là median cost/R. Nút Xuất CSV ghi score/journal và .groups.csv theo source, giờ server, tuần server; không trộn LIVE/HIST/TESTER.

## Quy đổi ngưỡng giá theo D1

InpPriceScaleMode=1 mặc định cho XAUUSD: k = close D1 đã đóng gần nhất / 2000. Dùng D1 broker thật tại thời điểm quyết định; không dùng close ngày đang chạy/tương lai. Thiếu D1 thì chờ hoặc loại, không tự fallback. Mode0 giữ khoảng cách cũ. Dùng thư mục ledger mới khi đổi mode.

Chín input khoảng cách nhân k: MaxSlPips, MinSlPips, InpTp1Pips, InpTp2Pips, InpBeTriggerPips, InpBeOffsetPips, MaxSpreadPrice, InpHistSpreadPrice, InpSlippagePoints. Giá trị input base/preset giữ nguyên. ATR, RR, số bar, score, phần trăm risk và commission tiền không nhân. Quote spread/deal fees thật không nhân. BE offset lưu theo thời điểm signal; trigger theo observation; spread/slip mô hình HIST theo thời điểm fill/exit. Các nhãn input base không thay cho giá SL/TP/BE thực của signal.

## Lot, rủi ro và chi phí

**Indicator:** risk tiền = contract size × adverse entry–SL distance × lot × tỷ giá profit currency→account currency. XAUUSD/USD trên MetaQuotes-Demo dùng contract100. Không gọi OrderCalcProfit vì API không dùng được trong indicator. Cùng tiền thì rate1; khác tiền tìm symbol direct/inverse theo currency metadata (hỗ trợ suffix), có thể nối qua USD. Dùng ask trực tiếp hoặc1/bid đảo chiều cho tiền lỗ; quote phải dương, không crossed. Thiếu contract/currency/tỷ giá thì Lot N/A với cặp tiền rõ trên panel/log, không fallback tick value.

**EA:** tiếp tục OrderCalcProfit(hướng,symbol,1lot,entry,initialSL). Input risk0.5%,step/min/max không đổi. Lot làm tròn xuống; ép min có thể vượt mục tiêu, đọc Risk thực. Cả hai nguồn đối chiếu tick value LOSS/tick size; lệch>1% hiện/log “broker khai báo tick value không khớp”, vẫn dùng nguồn chính tương ứng. Oracle EA lỗi thì fail closed. Detector/scale/RR/preset input không đổi.

Cost/R mô hình gồm spread + trượt giá hai chiều quy đổi bằng nguồn tiền risk tương ứng ở trên, cộng InpCommissionPerLot tiền/lot roundtrip rồi chia risk tiền. Không nhân commission theo mức giá. Báo PHÍ CAO theo InpMaxCostRPercent. EA hạch toán net từ deal broker (profit + commission + swap + fee), không trừ commission mô hình thêm lần nữa. cost_R EA dùng spread quote tại entry và commission/fee; swap tách riêng. Gross deal đã phản ánh fill/spread.

InpInitialCapital=0 nghĩa chưa biết vốn gốc; giới hạn ngày/tổng N/A. Reset theo InpResetMinuteServer, equity gồm floating. Đây không phải bảo đảm chặn lỗ. Risk tại SL là mức tính trước phí và gap; lỗ thực có thể vượt SL do gap/trượt/chi phí. Tỷ giá indicator và OrderCalcProfit EA dùng điều kiện hiện tại/quote có sẵn, không tái dựng tỷ giá lịch sử nhiều tiền tệ. Contract-price model chưa QA mọi instrument phi tuyến.

## Trail và TesterEA

SL/TP mong muốn và hiện tại được chuẩn hóa tick size/digits; nếu giống thì bỏ PositionModify và ghi MODIFY_NO_CHANGE. Kiểm STOPS_LEVEL/FREEZE_LEVEL trước gửi. Nếu vướng mức stop/freeze hoặc broker trả INVALID_STOPS/FROZEN thì ghi MODIFY_DEFERRED, giữ SL broker cũ và thử lại theo tick sau; không TesterStop vì trường hợp này. Stop ảo đồng bộ với stop thực đang được bảo vệ. Các lỗi khác tiếp tục fail closed.

EA dùng CTrade market, SL ban đầu, TP 1R theo fill hoặc TRAIL engine chung. Mặc định một vị thế; InpAllowMultiplePositions chỉ cho hedging, giới hạn InpMaxTesterPositions. Không khôi phục lệnh qua restart. Partial market fill chưa được kiểm chứng, dừng bảo thủ. SlippagePoints là deviation tolerance, không phải bảo đảm trượt đúng số đó. MFE/MAE có thể bỏ cực trị khi broker đóng trước callback. OPEN_NOT_PNL không được coi lệnh đã đóng.

Tester xuất signals/trades/execution_events/diagnostics và risk_audit.csv. Audit lưu equity trước send, target cash, oracle risk/lot, volume/step, risk thực tại SL, tiền một bước lot, tick reference, fill và SL. Ledger trade giữ 31 cột; net_R lấy net deal chia risk tiền thực ban đầu.

## Journal

Chỉ đọc giao dịch lịch sử, gộp theo position identifier, hỗ trợ partial/reversal. Risk lấy SL opening order; thiếu SL/spec/oracle thì R UNKNOWN. THEO_TIN_HIEU/NGUOC_TIN_HIEU/TU_VAO là ghép hướng/thời gian, không chứng minh ý định người giao dịch. Fixture M3a journal là tổng hợp 9 deal/4 vị thế; chưa QA journal qua broker thật hoặc quy đổi tiền lịch sử. Không gửi lệnh từ indicator.

## Xác minh v4.0.2 trên indicator thật

Portable20261102_m3a_v1, MetaQuotes-Demo/XAUUSD, indicator sản xuất4.02 gắn trực tiếp qua menu chart H1. Controller không thay callback/detector; đổi H1→M5→M15→M5, gỡ/gắn bằng template chỉ giữ indicator/input (bỏ object vẽ cũ).29 signal broker từ run v4.0.1 được nạp vào namespace M5 mới để kiểm persistence không rỗng; không phải29 tín hiệu mới phát hiện trong phiên live. Ba lần M5 có cùng29 tên/time/price mũi tên. H1/M15 rỗng không đọc state M5. Chủ ý corrupt checkpoint M5:archive bộ riêng,chạy tiếp,cảnh báo rõ. Không coi mismatch chủ ý là lỗi còn mở.

Equity demo10000USD,risk0.5%,entry4034.36,SL4027.158,contract100,step0.01: risk/lot720.20USD,target50USD,lot0.060,risk43.212USD (panel43.21); lệch6.788USD nhỏ hơn một bước7.202USD. Panel cảnh báo tick mismatch, không có OrderCalcProfit failure.59 checks/0 failures:storage23,indicator risk11 (oracle calls0),EA risk/trail25. EA+indicator+controller compile0/0. FX direct/inverse/missing quote/currency kiểm unit; tài khoản chart QA là USD/USD, chưa live QA tiền khác.

Không truy cập terminal D0E8209F. Không chạy lại M3b/HIST/P&L trong phạm vi hai lỗi này. validation/v402/ là bằng chứng hiện tại; số v4.0.1 dưới đây là baseline đã nghiệm thu trước.

## Baseline v4.0.1 đã nghiệm thu

M3b XAUUSD M5, MetaQuotes-Demo, terminal6296, Model4, 01/07/2026–31/10/2026 end exclusive; tick cuối 30/10 22:59:58, mỗi rule 44.373.721 tick, report 100% real ticks. Deposit100000USD, leverage100, risk0.5%, mặc định khác giữ nguyên. Commission/fee deal đều0; đây là phí broker của run, không phải đã đặt commission7.

| M3b tick thật | EXIT_1R | TRAIL |
|---|---:|---:|
| Signals / closed |29 /29|29 /29|
| Win net % |37.931034|37.931034|
| Mean gross R |−0.1669473524|−0.0678778874|
| Mean net R |−0.1699986735|−0.0711303713|
| PF_R |0.7466967436|0.8940135144|
| Net USD |−2482.66|−1113.86|
| Swap USD |−43.80|−47.12|
| Max equity DD |4847.79USD (4.79%)|5324.20USD (5.19%)|

58/58 orders: risk tiền tại SL khớp oracle và cash relation100/price/lot; lệch target0.5% không quá một bước lot. Risk thực khoảng0.49284–0.49973% equity. TRAIL chạy hết kỳ, 51.566 no-op được bỏ qua, không FAIL_CLOSED. Hai lượt này không phát sinh MODIFY_DEFERRED; nhánh mức stop/freeze được kiểm bằng unit. Gross deal khớp (exit−entry) × hướng × volume ×100 trong sai số tiền nhỏ hơn0.01USD.

HIST đã nghiệm thu: toàn fixture M1 sẵn có 27/09/2021 01:05–23/10/2026 22:59, mỗi rule459 signals/closed. EXIT_1R mean net−0.1300616069R, PF_R0.7528694157; TRAIL−0.1364607699R, PF_R0.7415213506. D1 native tổng hợp từ H1 đã đóng ngày trước; GoldSpec cố định100 tiền/price/lot, không phải oracle broker. Không bịa phần ngày/dữ liệu thiếu. Kết quả HIST được giữ từ lượt scale đã nghiệm thu; lần sửa lot/trail không chạy lại HIST toàn kỳ.

Cả HIST và tick thật đều âm, chưa có bằng chứng lợi thế. Không tối ưu/tìm hệ số sau kết quả. Prefix cũ200/200 mỗi mode và parity indicator29/29 được tái sử dụng có kiểm hash source; smoke prefix20/mode và risk/stop25 checks kiểm lại. Adapter parity nonvisual, không phải kiểm mỹ thuật.

## Giới hạn và tái lập

Chưa kiểm forward, partial fill, broker journal, DST thực, Telegram/push, crash recovery. Append CSV/checkpoint không là một transaction; crash giữa hai bước fail closed. Không làm M4/M5. Không cài vào terminal MT5 thật.

validation/v402/ chứa log build0/0, CSV/JSON/HTML, .set/.ini và nguồn test/runner để Claude kiểm độc lập. Run v4.0.2: reports/can_ho_tro_v4/20261102_v402_v1; baseline cũ: reports/can_ho_tro_v4/20261102_v401_final_v1. Runner scripts/v4_m3b.py dùng portable demo do người dùng đăng nhập; tái lập phải chọn RUN/label mới, không ghi đè chứng cứ. Build qua v4_v401.build với RUN mới; smoke qua v4_final401_checks.py; audit qua v4_final401_audit.py. Native harness cần frozen M1/M2 và standard include MT5 ở workspace phát triển; ZIP không chứa terminal, dữ liệu đăng nhập hoặc mọi market data.
