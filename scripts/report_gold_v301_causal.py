"""Summarize the frozen causal replay without selecting parameters from its P&L."""
import ast
import json
from collections import Counter
from datetime import datetime, timezone

import numpy as np
from numba import njit

from gold_v301_causal_core import ROOT, RUN, detect_stream
from research_gold_v301_causal import data, save, sha


def read(name):
    return json.loads((RUN/name).read_text(encoding='utf-8'))


def reference(name, text):
    path = ROOT/name
    line = next(i for i, s in enumerate(path.read_text(encoding='utf-8-sig').splitlines(),1) if text in s)
    return f'[{path.name}:{line}](<{path.as_posix()}:{line}>)'


def main():
    r = read('RESULTS.json'); n = read('NATIVE_PARITY.json'); v = read('VERIFICATION.json')
    windows = read('CHALLENGE_WINDOWS.json'); signal_counts = read('SIGNAL_SUMMARY.json')
    saved = np.load(RUN/'signals.npz')
    old = json.loads((ROOT/'reports/gold_v301_audit/20261101/legacy_signals.json').read_text(encoding='utf-8'))
    legacy = [s for s in old if s['kz'] and s['pass_struct']]
    keys = {(int(s['known_at']),1 if s['isBuy'] else -1) for s in legacy}
    overlaps = {name: len(keys & {(int(s[2]),int(s[3])) for s in saved[key]})
                for name,key in [('MQ5_PREFIX','native'),('REPORT_REPAIRED','repaired')]}
    # Diagnose the floating-point MinRR gate. No result from this diagnostic is
    # used to select or replace the frozen strategy's performance statistics.
    source = (ROOT/'scripts/gold_v301_causal_core.py').read_text(encoding='utf-8')
    tree = ast.parse(source)
    function = next(x for x in tree.body if isinstance(x,ast.FunctionDef) and x.name=='detect_one')
    function.decorator_list = []; function.name = 'detect_one'
    for node in ast.walk(function):
        if isinstance(node,ast.Compare) and isinstance(node.left,ast.Name) and node.left.id=='rr1':
            node.comparators[0] = ast.Constant(1.5-1e-9)
    context = dict(np=np)
    exec(compile(ast.fix_missing_locations(ast.Module(body=[function],type_ignores=[])), 'numeric_diagnostic','exec'), context)
    # Compile the existing stream with the diagnostic detector in its globals.
    stream = next(x for x in tree.body if isinstance(x,ast.FunctionDef) and x.name=='detect_stream')
    stream.decorator_list=[]
    context['detect_one']=njit(context['detect_one'])
    exec(compile(ast.fix_missing_locations(ast.Module(body=[stream],type_ignores=[])), 'numeric_diagnostic','exec'), context)
    d=data()
    tolerance_stream = njit(context['detect_stream'])(d['h1'],d['m5'],saved['m5_atr'],saved['h1_ptr'],saved['native_zones'],True)
    left = int(datetime(2021,10,23,tzinfo=timezone.utc).timestamp())
    tolerance_stream = tolerance_stream[tolerance_stream[:,1]>=left]
    numeric = dict(original_candidate_count=len(saved['native']), tolerance_diagnostic_count=len(tolerance_stream),
        gate='rr1 < MinRR with TP1 constructed exactly as entry+/-1.5*risk',
        interpretation='Binary rounding can reject the nominal 1.5R target. Diagnostic only; no P&L reported or parameter selected from this extra stream.')
    save('NUMERIC_GATE_DIAGNOSTIC.json',numeric)
    summary=[]
    for strategy in ['REPORT_REPAIRED','MQ5_PREFIX']:
        for cost in ['ZERO','BASE']:
            for risk in [.0025,.005]:
                for path in ['ADVERSE_FIRST','FAVORABLE_FIRST']:
                    group=[w for w in windows if w['strategy']==strategy and w['cost']==cost and w['risk']==risk and w['path']==path]
                    summary.append(dict(strategy=strategy,cost=cost,risk=risk,path=path,windows=len(group),
                        statuses=dict(Counter(w['status'] for w in group)),
                        reached_verification=sum(w.get('phase',0)==2 or w['status']=='BOTH_PHASES_MET' for w in group)))
    save('CHALLENGE_SUMMARY.json',summary)
    lines=['# Kiểm định tiếp XAUUSD M5 v3.01: đối chiếu native, sửa H1, chi phí và quỹ','',
        '**Kết luận: cấu hình đang được kiểm định không đạt. Sau khi tạo lại tín hiệu theo thông tin H1 đã biết và mô phỏng một vị thế, cả bản sửa engine báo cáo lẫn bản bám quy tắc MQ5 đều âm trước phí. Chưa có cơ sở dùng báo cáo +67,75R để mua challenge FTMO.**','',
        '## 1. Phạm vi và dữ liệu','',
        'Khóa TP1=1,5R / TP2=2R, đóng 50/50, BE tại +6 giá hoặc TP1, đệm BE +0,1; SL cấu trúc +0,3ATR, khoảng rủi ro 2,5–10 giá. Không tối ưu tham số theo kết quả lần này. Khung giờ giữ đúng bộ lọc cũ: giờ mở nến tín hiệu 08:00–17:59 theo timestamp feed. Chưa xác minh đây là London/NY theo DST.',
        '', 'Dữ liệu là snapshot MT5 đã lưu, đánh giá 23/10/2021–23/10/2026. Có 352.302 M5 và 29.431 H1 trong khoảng đánh giá; nhánh MQ5 có thêm warm-up từ 27/09/2021. Nhánh sửa báo cáo giữ thời điểm bắt đầu/seed ATR của báo cáo để đối chiếu. 2021 và 2026 đều không phải năm trọn vẹn. Không phải lịch sử giá FTMO.',
        '', '## 2. Đã đối chiếu được phần nào của indicator?','',
        f"Biên dịch và chạy trực tiếp **nguyên thân hàm** ScanHtfMacroZones / DetectLtfConfirmation của MQ5 bằng MetaTrader trong terminal kiểm thử riêng. Python khớp **{n['cases']:,} mốc lịch sử**, **{n['zone_rows_checked']:,} dòng vùng**, và **{n['positive_signal_cases_checked']:,} trường hợp có tín hiệu**. Giá trị entry/SL/TP/zone cũng khớp, sai số kiểm tra 1e-7. Thêm {n['actual_builtin_iATR_rows_checked']} dòng đối chiếu iATR thật: xác nhận dùng trung bình trượt True Range; engine báo cáo dùng Wilder.",
        '', 'Các hàm dữ liệu được cấp các nến/ATR lịch sử đóng; UI, Telegram và thông báo được stub. Mỗi mốc bắt đầu trong trạng thái chưa có lệnh để kiểm tra điều kiện tín hiệu. Đây là parity của logic nguồn native; không phải chứng nhận toàn bộ vòng đời chart/reload của file EX5 cũ. Không kết nối tài khoản và không gửi lệnh.',
        '', '### Vì sao báo cáo cũ không đại diện chính xác cho MQ5 hiện có?','',
        '| Quy tắc | Engine tạo báo cáo | MQ5 hiện có |', '|---|---|---|',
        '| ATR | Wilder | iATR: trung bình trượt TR |',
        '| Bước dịch base H1 | i += baseLen | i += baseLen, rồi vòng for cộng thêm 1 |',
        '| Đếm test vùng thường | Mỗi nến chạm proximal | Chỉ tăng khi chuyển từ ngoài vào toàn vùng |',
        '| MaxTests vùng thường | Ngừng vùng sau 4 test | Vẫn quét, chỉ break cấu trúc làm vùng broken |',
        '| Điểm MTF | Tự cộng 10 | 0 khi chưa chứng minh overlap |',
        '| Swing SL | Có thể lấy thêm nến cũ hơn | lookback max(5, sweep shift) |',
        '| Lệnh cùng lúc | Các tín hiệu độc lập, có thể chồng nhau | Chặn tín hiệu mới khi plan active |',
        '', f"Trong 881 quyết định Killzones cũ, chỉ {overlaps['MQ5_PREFIX']} có cùng thời điểm + hướng với nhánh MQ5. Điều này chưa có nghĩa entry/SL/zone giống nhau. Nhánh sửa báo cáo có {overlaps['REPORT_REPAIRED']} thời điểm + hướng trùng; tổng {signal_counts['repaired_kz']} tín hiệu Killzones đủ điều kiện cấu trúc, còn nhánh MQ5 có {signal_counts['native_kz']}.",
        '', f"Còn một lỗi số học: kiểm tra rr1 < 1,5 có thể loại TP được dựng đúng danh nghĩa 1,5R vì làm tròn nhị phân. Đổi riêng so sánh sang dung sai 1e-9 cho {numeric['tolerance_diagnostic_count']:,} tín hiệu thay vì {numeric['original_candidate_count']:,}. Đây là chẩn đoán lỗi; toàn bộ bảng hiệu suất bên dưới giữ phép so sánh gốc, không dùng luồng mới để chọn kết quả đẹp hơn.",
        '', '## 3. H1 đã được sửa và kiểm tra như thế nào?','',
        '**REPORT_REPAIRED:** vùng bắt đầu tại thời điểm đóng nến departure H1 cuối, thay vì mở nến đó. Break/quota chỉ kết thúc vùng khi nến H1 tương ứng đóng. Mọi FLIP tồn tại từ thời điểm biết break đến thời điểm biết invalidation/expiry; việc FLIP bị phá sau này không xóa sự tồn tại trước đó. Điểm tại lúc sinh vùng không đọc số test tương lai.',
        '', '**MQ5_PREFIX:** mỗi quyết định M5 chỉ nhận vùng tính từ tối đa 2.000 H1 đã đóng tại thời điểm đó, với đúng các quy tắc nguồn MQ5. Giữ cả các khác biệt vừa liệt kê; không đổi chúng âm thầm để ép hai engine trùng nhau. Trong giao dịch live, việc MQ5 tái quét các H1 đã đóng vốn đã tránh đọc H1 chưa đóng; lỗi dùng lịch sử tương lai nằm ở cách engine báo cáo dựng cả tập vùng rồi chọn tín hiệu.',
        '', 'Kiểm tra prefix: 25 mốc lịch sử cho nhánh MQ5, 9 mốc cho nhánh sửa báo cáo; bổ sung dữ liệu tương lai không làm đổi tập vùng đang biết tại mốc kiểm tra. Kiểm tra timestamp tín hiệu, biên SL và chỉ số nến cũng đạt.',
        '', '## 4. Kết quả chính trong khung giờ lọc','',
        'Vào ở open M5 kế tiếp, BUY khớp Ask và đóng Bid; SELL khớp Bid và đóng Ask. Giữ SL cấu trúc; từ giá khớp tính lại TP theo 1,5R/2R. Loại khi khoảng SL thực ngoài 2,5–10; một vị thế tại một thời điểm. Gap SL dùng giá mở thực và có thể lỗ hơn 1R. Hết 288 **nến M5 quan sát được** thì đóng phần còn lại; thời gian này không luôn bằng 24 giờ đồng hồ. Đây là quy tắc expiry của mô phỏng cũ, indicator gốc không tự đặt lệnh/đóng lệnh theo expiry.',
        '', 'Hai đường OHLC giả định: cực trị bất lợi trước hoặc cực trị thuận lợi trước. Với BE, đây không phải cận tốt nhất/xấu nhất. Giá đỉnh/đáy trong nến không cho biết thứ tự thật.',
        '', '| Nhánh | Chi phí | Lệnh (bất lợi trước / thuận lợi trước) | Tổng R | PF |',
        '|---|---|---:|---:|---:|', '| Báo cáo cũ | 0 | 881 | +67,75 | 1,15 |']
    for strategy,label in [('REPORT_REPAIRED','Sửa engine báo cáo'),('MQ5_PREFIX','Quy tắc MQ5, H1 prefix')]:
        for cost in ['ZERO','LOW','BASE','STRESS']:
            aa=r[f'{strategy}_KZ_{cost}_ADVERSE_FIRST']['metrics']; ff=r[f'{strategy}_KZ_{cost}_FAVORABLE_FIRST']['metrics']
            lines.append(f"| {label} | {cost} | {aa['n']} / {ff['n']} | {aa['net_R']:+.2f} / {ff['net_R']:+.2f} | {aa['profit_factor']:.3f} / {ff['profit_factor']:.3f} |")
    lines+=['', 'Chi phí là giả định cố định theo **đơn vị giá Vàng**, không phải USD phí/lot FTMO thực đo:','',
        '| Kịch bản | Spread Ask−Bid | Commission khứ hồi quy đổi | Trượt giá bất lợi mỗi fill market/stop |',
        '|---|---:|---:|---:|','| ZERO | 0 | 0 | 0 |','| LOW | 0,20 | 0,06 | 0,02 |',
        '| BASE | 0,40 | 0,06 | 0,05 |','| STRESS | 0,45 | 0,10 | 0,10 |',
        '', 'Commission chia ở entry/exit theo khối lượng, kể cả chốt từng phần. TP limit không bị trượt bất lợi trong mô hình này. Chưa tính swap. Spread trong các kịch bản tuân cap 0,45 của indicator. Chi phí thay đổi giá khớp, risk, TP/SL và thời gian đóng nên có thể thay đổi cả tập lệnh sau cổng một vị thế; không chỉ trừ R kế toán. Các tên LOW/BASE/STRESS không khẳng định phản ánh phân phối spread FTMO.',
        '', '### Tách tác động của cổng một vị thế','',
        '| Nhánh ZERO | Tín hiệu có fill hợp lệ | R cộng độc lập | Số lệnh sau chặn chồng | R sau chặn chồng |',
        '|---|---:|---:|---:|---:|']
    for strategy in ['REPORT_REPAIRED','MQ5_PREFIX']:
        for path in ['ADVERSE_FIRST','FAVORABLE_FIRST']:
            a=r[f'{strategy}_KZ_ZERO_{path}']
            lines.append(f"| {strategy}, {path} | {a['valid_fill_candidates']} | {a['independent_candidate_metrics']['net_R']:+.2f} | {a['metrics']['n']} | {a['metrics']['net_R']:+.2f} |")
    lines+=['', 'Tổng R cộng độc lập có thể bao gồm vị thế đồng thời và không phải đường vốn. Không quy toàn bộ chênh lệch giữa báo cáo cũ và bảng mới cho một lỗi duy nhất: tập vùng/tín hiệu, thực thi và cổng vị thế đều đã thay đổi; bảng này tách riêng phần chặn chồng.',
        '', '## 5. Kết quả từng năm — cổng một vị thế','',
        '| Năm | Báo cáo sửa H1 ZERO: lệnh / R | Báo cáo sửa H1 BASE: lệnh / R | MQ5 prefix ZERO: lệnh / R | MQ5 prefix BASE: lệnh / R |',
        '|---|---:|---:|---:|---:|']
    for y in range(2021,2027):
        cells=[]
        for strategy,cost in [('REPORT_REPAIRED','ZERO'),('REPORT_REPAIRED','BASE'),('MQ5_PREFIX','ZERO'),('MQ5_PREFIX','BASE')]:
            a=r[f'{strategy}_KZ_{cost}_ADVERSE_FIRST']['years'][str(y)]
            cells.append(f"{a['n']} / {a['net_R']:+.2f}")
        lines.append(f"| {y}{' (không trọn năm)' if y in (2021,2026) else ''} | "+' | '.join(cells)+' |')
    lines+=['', 'Cột năm dùng đường cực trị bất lợi trước; đường còn lại và toàn phiên nằm trong RESULTS.json.',
        '', '## 6. Đường vốn và điều kiện FTMO','',
        'Benchmark là [FTMO CFD 2-Step](https://ftmo.com/en/2-step-challenge/): mục tiêu 10% rồi 5%; tối thiểu 4 ngày mở lệnh mỗi phase. [Quy tắc equity](https://ftmo.com/en/trading-objectives/) dùng floor tổng 90% vốn đầu và floor ngày bằng balance đầu ngày trừ 5% vốn đầu; reset 00:00 CE(S)T. Kiểm tra nguồn ngày 01/11/2026.',
        '', 'Mô phỏng 100.000 USD, rủi ro cố định theo vốn ban đầu, một vị thế. Tính equity đang mở và chốt từng phần tại các điểm của đường OHLC giả định. Nhãn thời gian cực trị trong nến là thời gian mô phỏng, không phải timestamp tick thật. Đường vốn liên tục 5 năm bên dưới vẫn tính sau lần vi phạm để chẩn đoán; tài khoản quỹ thực sẽ không tiếp tục qua cổng vi phạm.',
        '', '| Nhánh, BASE, bất lợi trước | Rủi ro/lệnh | Lợi nhuận 5 năm (% vốn đầu) | DD equity đỉnh–đáy (% vốn đầu) | Mất nhiều nhất trong ngày | Vi phạm floor tổng? |',
        '|---|---:|---:|---:|---:|---|']
    for strategy in ['REPORT_REPAIRED','MQ5_PREFIX']:
        for fraction in [.0025,.005]:
            a=r[f'{strategy}_KZ_BASE_ADVERSE_FIRST']['accounts'][str(fraction)]
            lines.append(f"| {strategy} | {fraction*100:.2f}% | {a['return_pct']:+.2f}% | {a['max_equity_peak_drawdown_pct']:.2f}% | {a['max_daily_equity_loss_pct']:.2f}% | {'Có' if a['total_floor_breached'] else 'Không'} |")
    lines+=['', '### Cửa sổ khởi đầu challenge theo lịch sử','',
        'Khởi đầu phẳng vào ngày 1 mỗi tháng từ 01/2022 đến 10/2025: 46 mốc, mỗi mốc quan sát 365 ngày, reset tài khoản khi đạt phase 1 rồi mô phỏng phase 2 tiếp theo. 365 ngày chỉ là thời hạn quan sát của báo cáo; FTMO 2-Step không đặt deadline đó. Không đạt trong cửa sổ được ghi **chưa hoàn tất**, không coi là vi phạm. Các cửa sổ chồng lấn, không độc lập và **không phải xác suất pass**.',
        '', '| Nhánh | Chi phí | Risk | Đường giá | Đủ cả hai phase / 46 | Vi phạm / 46 | Chưa hoàn tất / 46 |',
        '|---|---|---:|---|---:|---:|---:|']
    for a in summary:
        ss=a['statuses']
        lines.append(f"| {a['strategy']} | {a['cost']} | {a['risk']*100:.2f}% | {a['path']} | {ss.get('BOTH_PHASES_MET',0)} | {ss.get('FAILED',0)} | {ss.get('UNRESOLVED',0)} |")
    lines+=['', 'Chưa biết timezone thực của feed nên bảng chính giả định timestamp là UTC; kiểm tra reset với giả định feed UTC+2 và UTC+3 cũng lưu trong RESULTS.json. Các mốc tối đa/lỗi trong ngày vẫn là ước lượng M5, chưa có Bid/Ask ticks, lịch sử swap, quy cách lot/margin hoặc clock FTMO đã xác minh. Không gọi các lượt “đủ hai phase” trong mô hình là tài khoản FTMO thật đã pass.',
        '', '## 7. Quyết định sau kiểm định','',
        '**Không dùng cấu hình này làm căn cứ trả phí challenge.** Cả hai nhánh kiểm định đều thiếu lợi nhuận gộp trong mô hình một vị thế; đưa chi phí vào làm kết quả xấu thêm. Bản sửa báo cáo không còn giữ được kết quả +67,75R, còn code MQ5 đang có cũng không tạo đúng luồng giao dịch của báo cáo cũ.',
        '', 'Chưa thực hiện một nghiên cứu lợi thế mới hoặc tối ưu thêm bộ lọc. Sửa so sánh RR nhạy làm tròn và vòng đời vùng theo đúng input có thể là công việc phần mềm tiếp theo, nhưng hiệu quả của một bản thay đổi như vậy chưa được chứng minh ở đây. Không phát hành bản indicator “đã có lợi nhuận” từ kết quả này.',
        '', 'Indicator gốc MQ5 và EX5 được giữ nguyên, hash khớp trước/sau. Phần sửa H1 nằm trong engine nghiên cứu riêng; chưa đồng bộ bản nghiên cứu sang terminal giao dịch. File EX5 119.190 bytes vẫn là bản cũ.',
        '', '## 8. Tái chạy và bằng chứng','',
        'Chạy từ thư mục dự án bằng Python hiện có (NumPy, Numba và MetaEditor/MetaTrader đã cài):','',
        '```powershell','python scripts/research_gold_v301_causal.py signals',
        'python scripts/research_gold_v301_causal.py prepare-native',
        'python scripts/research_gold_v301_causal.py run-native',
        'python scripts/verify_gold_v301_causal.py',
        'python scripts/backtest_gold_v301_causal.py',
        'python scripts/verify_gold_v301_causal.py ledger',
        'python scripts/report_gold_v301_causal.py','```','',
        '- FROZEN_PLAN.json / EXECUTION_PLAN.json: quy tắc và giả định trước khi xem P&L.',
        '- NATIVE_PARITY.json / NATIVE_EXTRACT.json / NATIVE_BUILD.json: thân hàm nguồn, build và parity.',
        '- PREFIX_VERIFICATION.json: kiểm tra dữ liệu tương lai không thay đổi snapshot lịch sử.',
        '- signals_*.csv / trades_*.csv: tín hiệu và từng giao dịch có timestamp, giá, SL, risk, R, lý do đóng.',
        '- RESULTS.json: cả hai đường OHLC, toàn phiên/giờ lọc, từng năm, equity và reset clock.',
        '- CHALLENGE_WINDOWS.json / challenge_windows.csv: từng cửa sổ 365 ngày.',
        '- SOURCE_MANIFEST.json / VERIFICATION.json: hash và đối soát ledger.',
        '', f"Kiểm tra hoàn tất: **{v['kz_ledger_rows_checked']:,} dòng lệnh Killzones** đối soát tổng R, từng năm và không chồng thời gian. Các fixture kiểm tra BUY/SELL, thứ tự SL/TP, BE, chi phí và vi phạm equity trong nến đều đạt.",
        '', 'Mốc mã nguồn:', '',
        '- '+reference('duc_tri_can_ho_tro.mq5','int htfBarsToCopy = MathMin(MaxHistory, 2000);'),
        '- '+reference('duc_tri_can_ho_tro.mq5','int lookback = MathMin(copied - 1, MathMax(cBar + 4, sweepBar));'),
        '- '+reference('duc_tri_can_ho_tro.mq5','rr1 < MinRR || rr2 < rr1)'),
        '- '+reference('scripts/test_m5_scanning_speed.py','timeActive = times_h1'),
        '- '+reference('scripts/test_m5_scanning_speed.py','if not fBroken:'),
        '', '**Giới hạn còn lại:** không phải backtest tick thật của FTMO, không có holdout độc lập sau quá trình chọn model cũ, không chứng nhận hành vi EX5 đầy đủ. Kết luận áp dụng cho đúng các quy tắc và giả định đã ghi, không kết luận mọi phương pháp SMC/Supply–Demand đều không hiệu quả.','']
    (RUN/'REPORT.md').write_text('\n'.join(lines),encoding='utf-8')
    print(json.dumps(dict(report=str(RUN/'REPORT.md'),challenge_summary=summary)),flush=True)


if __name__=='__main__':
    main()
