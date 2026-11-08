# -*- coding: utf-8 -*-
from pathlib import Path
root=Path(__file__).resolve().parents[1]/'can_ho_tro_v4'
p=root/'HUONG_DAN_KY_THUAT.md';s=p.read_text(encoding='utf-8')
s=s.replace('# Cản Hỗ Trợ v4.0.1 —','# Cản Hỗ Trợ v4.0.2 —',1)
s=s.replace('Bản đóng gói ngày 02/11/2026, chờ Claude nghiệm thu.','Bản v4.0.2 ngày 02/11/2026, chờ Claude nghiệm thu. Hai lỗi indicator chạy thật của v4.0.1 được sửa trong bản này.',1)
a=s.index('4. Đặt InpV4LedgerFolder');b=s.index('\n\n## Tín hiệu',a)
s=s[:a]+'''4. CSV/checkpoint nằm trong MQL5/Files/<InpV4LedgerFolder>. signals/state/candidates/guard_rejects có tên <symbol>_<fingerprint>; score thêm fingerprint chi phí/account. Fingerprint dùng khung chart và HTF/LTF thực sau resolve PERIOD_CURRENT, cùng tham số detector/plan. Đổi H1/M5/M15 không đọc nhầm state. Một writer cho cùng cấu hình tại một thời điểm.

Nếu state không khớp ledger của chính cấu hình (hoặc ledger hỏng), bộ signals/state/candidates/guard/score liên quan được đổi tên *_corrupt_<time> và khởi tạo lại; cảnh báo đỏ trên panel/chart, chi tiết đường dẫn trong log. Bộ khác giữ nguyên. Lỗi mở file do writer còn giữ khóa tiếp tục chờ có giới hạn, không coi là corruption. File v4.0.1 chỉ có symbol được để nguyên, không tự nhập vào namespace mới. Không tự ghép/xóa archive để ép phục hồi.''' +s[b:]
a=s.index('**OrderCalcProfit(hướng, symbol, 1 lot, entry, initial SL)**');b=s.index('\n\nCost/R mô hình',a)
s=s[:a]+'''**Indicator:** risk tiền = contract size × adverse entry–SL distance × lot × tỷ giá profit currency→account currency. XAUUSD/USD trên MetaQuotes-Demo dùng contract100. Không gọi OrderCalcProfit vì API không dùng được trong indicator. Cùng tiền thì rate1; khác tiền tìm symbol direct/inverse theo currency metadata (hỗ trợ suffix), có thể nối qua USD. Dùng ask trực tiếp hoặc1/bid đảo chiều cho tiền lỗ; quote phải dương, không crossed. Thiếu contract/currency/tỷ giá thì Lot N/A với cặp tiền rõ trên panel/log, không fallback tick value.

**EA:** tiếp tục OrderCalcProfit(hướng,symbol,1lot,entry,initialSL). Input risk0.5%,step/min/max không đổi. Lot làm tròn xuống; ép min có thể vượt mục tiêu, đọc Risk thực. Cả hai nguồn đối chiếu tick value LOSS/tick size; lệch>1% hiện/log “broker khai báo tick value không khớp”, vẫn dùng nguồn chính tương ứng. Oracle EA lỗi thì fail closed. Detector/scale/RR/preset input không đổi.''' +s[b:]
s=s.replace('Cost/R mô hình gồm spread + trượt giá hai chiều quy đổi bằng OrderCalcProfit,','Cost/R mô hình gồm spread + trượt giá hai chiều quy đổi bằng nguồn tiền risk tương ứng ở trên,')
s=s.replace('OrderCalcProfit dùng điều kiện quy đổi tiền hiện tại của terminal; không bảo đảm quy đổi lịch sử nhiều tiền tệ.','Tỷ giá indicator và OrderCalcProfit EA dùng điều kiện hiện tại/quote có sẵn, không tái dựng tỷ giá lịch sử nhiều tiền tệ. Contract-price model chưa QA mọi instrument phi tuyến.')
s=s.replace('## Kết quả xác minh v4.0.1','''## Xác minh v4.0.2 trên indicator thật

Portable20261102_m3a_v1, MetaQuotes-Demo/XAUUSD, indicator sản xuất4.02 gắn trực tiếp qua menu chart H1. Controller không thay callback/detector; đổi H1→M5→M15→M5, gỡ/gắn bằng template chỉ giữ indicator/input (bỏ object vẽ cũ).29 signal broker từ run v4.0.1 được nạp vào namespace M5 mới để kiểm persistence không rỗng; không phải29 tín hiệu mới phát hiện trong phiên live. Ba lần M5 có cùng29 tên/time/price mũi tên. H1/M15 rỗng không đọc state M5. Chủ ý corrupt checkpoint M5:archive bộ riêng,chạy tiếp,cảnh báo rõ. Không coi mismatch chủ ý là lỗi còn mở.

Equity demo10000USD,risk0.5%,entry4034.36,SL4027.158,contract100,step0.01: risk/lot720.20USD,target50USD,lot0.060,risk43.212USD (panel43.21); lệch6.788USD nhỏ hơn một bước7.202USD. Panel cảnh báo tick mismatch, không có OrderCalcProfit failure.59 checks/0 failures:storage23,indicator risk11 (oracle calls0),EA risk/trail25. EA+indicator+controller compile0/0. FX direct/inverse/missing quote/currency kiểm unit; tài khoản chart QA là USD/USD, chưa live QA tiền khác.

Không truy cập terminal D0E8209F. Không chạy lại M3b/HIST/P&L trong phạm vi hai lỗi này. validation/v402/ là bằng chứng hiện tại; số v4.0.1 dưới đây là baseline đã nghiệm thu trước.

## Baseline v4.0.1 đã nghiệm thu''')
s=s.replace('validation/ chứa log build0/0','validation/v402/ chứa log build0/0')
s=s.replace('Run phát triển: reports/can_ho_tro_v4/20261102_v401_final_v1.','Run v4.0.2: reports/can_ho_tro_v4/20261102_v402_v1; baseline cũ: reports/can_ho_tro_v4/20261102_v401_final_v1.')
p.write_text(s,encoding='utf-8')
p=root/'CHANGELOG_V4.md';s=p.read_text(encoding='utf-8').replace('# CHANGELOG v4.0.1 —','# CHANGELOG v4.0.2 —',1)
at=s.index('## v4.0.1')
s=s[:at]+'''## v4.0.2 — hai lỗi indicator chạy thật

- Ledger/state/score dùng fingerprint cấu hình đã resolve HTF/LTF, kèm khung chart thực (ATR chart). ID rỗng của state chưa có signal được chuẩn hóa khi so sánh, tránh cách ly nhầm. Chỉ đọc bộ đúng fingerprint; legacy symbol-only để nguyên.
- Bộ ledger/state không khớp:archive signals/state/candidates/guard/score thành *_corrupt_<time>,reset rồi tạo lại;cảnh báo đỏ nhìn thấy trên chart/panel. Lock/I/O không coi là corruption. Không tự nhập archive vào runtime mới.
- Indicator dùng contract size × adverse price distance × lot,quy đổi profit→account currency bằng symbol direct/inverse hoặc USD bridge; thiếu metadata/quote thì Lot N/A rõ lý do. Không gọi OrderCalcProfit. Tick value lệch>1% vẫn cảnh báo. EA tiếp tục OrderCalcProfit;detector/scale/RR/preset không đổi.
- Indicator thật qua menu chart portable H1→M5→M15→M5→gỡ/gắn:29 mũi tên broker đã lưu giữ nguyên tên/time/price. Panel lot0.060 với equity10000USD,target50USD,risk43.212USD,một bước7.202USD. Chủ ý corrupt checkpoint của bộ test:archive,khởi tạo lại,cảnh báo hiện rõ.
- Storage/risk23/23,indicator risk11/11 (oracle calls0),EA risk/stop regression25/25;tất cả compile0/0. Không M3b/HIST/P&L mới;baseline v4.0.1 dưới đây được tái sử dụng có ghi rõ. Chỉ portable20261102_m3a_v1,không chạm D0E8209F.
- Gói4.0.2 gồm source/binary,preset không đổi,docs,validation/v402,manifest+ZIP và hash sau giải nén. Chờ Claude nghiệm thu,không M4/M5.

'''+s[at:]
p.write_text(s,encoding='utf-8')
