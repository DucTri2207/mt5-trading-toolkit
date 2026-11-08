from pathlib import Path
import re

REL = Path(__file__).resolve().parents[1] / 'can_ho_tro_v4'
p = REL / 'HUONG_DAN_KY_THUAT.md'
s = p.read_text(encoding='utf-8-sig')
s = s.replace('# Cản Hỗ Trợ v4.0.2', '# Cản Hỗ Trợ v4.0.3', 1)
a, b = s.index('Bản v4.0.2'), s.index('\n\n## Cài thủ công')
s = s[:a] + '''Bản v4.0.3 ngày 02/11/2026, chờ Claude nghiệm thu claude_014. Cùng vùng H1/tín hiệu M5 trên M1–D1, replay 90 ngày, dashboard thu gọn và mặc định xóa khung thống kê. Giữ sửa risk/state của v4.0.2. Indicator quan sát/ghi journal; TesterEA chỉ dùng Strategy Tester. ZIP v4.0 M3a không được phát hành vì lỗi lot ×10.''' + s[b:]
a, b = s.index('4. CSV/checkpoint'), s.index('\n## Tín hiệu')
s = s[:a] + '''4. Indicator yêu cầu detector H1/M5 (PERIOD_CURRENT được giải về H1/M5), bất kể khung chart. CSV/checkpoint theo symbol + fingerprint detector/plan đã resolve; **không chứa khung chart**. ATR detector dùng đúng H1/M5. CSV score thêm hash chi phí/account. Một chart giữ khóa writer; chart khác đọc cùng ledger, zone snapshot, checkpoint và score; chart còn lại tiếp quản khi writer đóng.

Bộ v4.0.2 có CHART trong fingerprint được giữ nguyên, không tự nhập/ghép. Corrupt signals/state/candidates/guard/score và zone snapshot của bộ riêng được archive rồi replay lại; lỗi khóa tạm thời không coi là corrupt. Không xóa/ghép archive thủ công để ép phục hồi.

## Lịch sử và hiển thị v4.0.3

- InpHistoryDays=90: namespace mới replay mọi M5 broker khả dụng trong số ngày lịch. OnTimer chia tối đa 32 observations/lượt, ngân sách khoảng 50ms (một lần quét H1 có thể vượt ngân sách), có ngày đang xử lý trên chart. LtfBarsScan=300 vẫn là lookback của mỗi quyết định. Đổi HistoryDays tạo namespace mới nếu giá trị khác 90.
- Quét đầy đủ khi closed H1 thay đổi; M5 trong cùng prefix H1 dùng cùng vùng. Không đưa forming H1/D1 vào detector. HIST độc lập quét lại mỗi M5 để đối chiếu.
- InpShowExpiredZones=true: vùng hết hiệu lực trong cửa sổ lịch sử có màu mờ. Vùng active luôn hiện, không bị quota MaxZones/giá hiện tại che mất; các bộ lọc detector/xếp hạng giữ như trước. Vùng nguồn có khung riêng, từ base start đến invalid H1 đóng. Vùng active kéo tới mở H1 hiện tại + ExtendBars H1 trên mọi chart.
- Arrow dùng signal_id làm tên riêng, vào nến chart chứa **confirm_bar_open M5**, giống arrow M5 gốc. Tooltip ghi signal_known_time giờ server, hướng, entry/initial SL/TP1/TP2, ID/loại vùng, khoảng risk và % equity. Nhiều tín hiệu chung nến H4/D1 vẫn là các object riêng.
- InpShowStatsPanel=false: xóa toàn bộ M2_* cũ, kể cả M2_BG/nút cũ; CSV vẫn ghi. Nút CSV nhỏ ở chân dashboard chính. Cảnh báo quan trọng một dòng phía dưới; trong replay ưu tiên dòng tiến độ.
- InpDashCollapsed=true: mặc định thanh nhỏ; nút +/− mở/thu. ShowDash tắt bảng chính; tiến độ/cảnh báo vẫn hiện. DashRight chọn trái/phải, InpDashBottom chọn trên/dưới. Dashboard mở đầy đủ cần chart đủ cao hoặc giảm DashScale.
- Khôi phục và vẽ ngay cả khi chưa có M5 mới. Snapshot nhị phân là cache hiển thị; ledger CSV là bằng chứng tín hiệu. File owner_<key>.lock chỉ dùng giữ khóa; không xóa khi terminal đang chạy.

''' + s[b:]
p.write_text(s, encoding='utf-8-sig')
p = REL / 'CHANGELOG_V4.md'
s = p.read_text(encoding='utf-8-sig')
p.write_text('''# v4.0.3 — 02/11/2026 — claude_014

- Cùng vùng H1 và signal_id M5 trên M1/M5/M15/M30/H1/H4/D1; ATR và fingerprint không phụ thuộc chart.
- Replay nhân quả 90 ngày qua OnTimer, có tiến độ; một writer, các chart đọc chung cache và tiếp quản khi writer đóng.
- Vùng active luôn vẽ; expired mờ; source zone kéo tới invalidation; tooltip arrow đầy đủ.
- InpShowStatsPanel=false xóa M2_* cũ; CSV tự ghi, nút CSV nhỏ ở dashboard. Dashboard mặc định thu gọn, chọn góc bằng DashRight/InpDashBottom.
- Khôi phục khi đổi khung/gỡ gắn/restart trước M5 mới; replay không phát BE notification lịch sử.
- Không đổi ngưỡng, scale, RR, risk/trail; không M4/M5. Bằng chứng v402/v401 là baseline, không kết quả mới v403.

''' + s, encoding='utf-8-sig')
for p in (REL / 'Presets').glob('*.set'):
    enc = 'utf-16' if p.read_bytes().startswith(b'\xff\xfe') else 'utf-8-sig'
    s = p.read_text(encoding=enc)
    for k, v in dict(InpHistoryDays='90', InpShowExpiredZones='true', InpShowStatsPanel='false', InpDashCollapsed='true', InpDashBottom='false').items():
        s = re.sub(r'^'+k+'=.*$', k+'='+v, s, flags=re.M) if re.search(r'^'+k+'=', s, re.M) else s+'\n'+k+'='+v
    p.write_text(s, encoding=enc)
print('v403 docs and display defaults updated')
