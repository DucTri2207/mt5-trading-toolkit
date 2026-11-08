"""Score the single frozen US100 setup on validated available data. No search."""
from datetime import date, timedelta
import json
import numpy as np

from collect_us100_ny import RUN, RAW, sha, write_json
from us100_ny_core import (detect, m1_eligible_days, simulate_day, load_ticks, COSTS,
                          summary, session_bounds)


def main():
    path = RUN / 'm1_bid_ask.npz'
    data = np.load(path); bid, ask = data['bid'], data['ask']
    assert np.array_equal(bid[:, 0], ask[:, 0])
    assert np.all(ask[:, 1:] >= bid[:, 1:]-1e-9)
    days, _ = m1_eligible_days(bid)
    # Do not count a whole static holiday session as a tradable session.
    inactive = []
    for d in list(days):
        start, end = session_bounds(d)
        k = (bid[:, 0] >= start) & (bid[:, 0] < end)
        if np.all(bid[k, 2] == bid[k, 3]):
            days.remove(d); inactive.append(d.isoformat())
    signals = detect(bid)
    all_days, day = [], date(2024, 1, 1)
    while day <= date(2026, 10, 30):
        if day.weekday() < 5:
            all_days.append(day)
        day += timedelta(days=1)
    coverage = {str(y): dict(planned_weekdays=sum(d.year == y for d in all_days),
                              eligible_m1_days=sum(d.year == y for d in days),
                              dates=[d.isoformat() for d in days if d.year == y]) for y in (2024, 2025, 2026)}
    ticks, rejected_ticks = {}, []
    for d in (d for d in days if d.year == 2026):
        try:
            ticks[d] = load_ticks(RAW, d)
        except Exception as error:
            rejected_ticks.append(dict(date=d.isoformat(), error=str(error)))
    results = {}
    for cost in COSTS:
        trades = []
        for d in days:
            rows = simulate_day(d, signals, bid, ask, cost)
            trades.extend(rows)
        write_json(RUN / f'trades_m1_{cost.name}.json', trades)
        results[cost.name] = dict(M1_available=summary(trades), by_year={})
        for year in (2024, 2025, 2026):
            subset = [p for p in trades if p['date'].startswith(str(year))]
            results[cost.name]['by_year'][str(year)] = dict(
                **summary(subset), data_available=coverage[str(year)]['eligible_m1_days'] > 0)
        tick_trades = []
        for d, quotes in ticks.items():
            tick_trades.extend(simulate_day(d, signals, bid, ask, cost, quotes))
        write_json(RUN / f'trades_tick_2026_{cost.name}.json', tick_trades)
        results[cost.name]['TICK_2026'] = dict(**summary(tick_trades), data_available=bool(ticks))
    result = dict(spec_sha256=sha(RUN / 'SPEC_LOCK.json'), data_sha256=sha(path),
                  hypothesis_count=1, cost_scenarios=3, raw_signals=len(signals), coverage=coverage,
                  inactive_sessions=inactive, eligible_tick_2026_days=len(ticks), rejected_tick_days=rejected_ticks,
                  results=results, prop_benchmark=dict(status='NOT_EVALUATED_INSUFFICIENT_CONTIGUOUS_COVERAGE',
                  rules_implemented_and_unit_tested=True, prospective_pass_probability=None),
                  gate=dict(confirmed_edge=False, evaluation_purchase_ready=False,
                            reason='Sparse development data; no validation-year or untouched-test-year M1 execution coverage. No 26-week / 200-trade confirmation sample.'),
                  limitations=['CFD public proxy, not FTMO/broker executable quotes.',
                               'M1 paired side candles are not synchronized BBO; stop-first ambiguity and side costs modeled.',
                               'Available-day sample is incomplete and may be unrepresentative.',
                               'Zero trades on an unavailable year means no test, not a zero-signal market result.',
                               'Manual reaction latency and actual broker commission/lot/margin conditions remain unverified.'])
    write_json(RUN / 'BACKTEST_SUMMARY.json', result)
    lines = ['# US100 NY Pullback LAB v1 — kết quả ban đầu', '',
             '**Đã có indicator chạy được. Chưa có bằng chứng đủ để dùng tiền mua challenge hoặc kết luận pass quỹ.**', '',
             '## Dữ liệu thực sự sử dụng', '',
             '| Giai đoạn | Phiên đủ M1/warmup | Ngày trong kế hoạch tải |', '|---|---:|---:|']
    for y, row in coverage.items():
        lines.append(f"| {y} | {row['eligible_m1_days']} | {row['planned_weekdays']} |")
    lines += ['', 'Mẫu 2024 là các phiên rời rạc; cột kế hoạch gồm cả ngày lễ, không phải số phiên Nasdaq đã mở cửa. Các năm thiếu dữ liệu được ghi là chưa kiểm định. Lượt tải đã gặp timeout/HTTP 429; xem DATA_DOWNLOAD_AMENDMENT.md và M1_PROGRESS.json.', '',
              '## Kiểm tra sau phí trên mẫu sẵn có', '',
              '| Chi phí | Số lệnh | Thắng | Tổng R ròng | PF | Lãi/lỗ mô phỏng | DD từ đỉnh balance |', '|---|---:|---:|---:|---:|---:|---:|']
    for name, row in results.items():
        v = row['M1_available']
        wr = '--' if v['win_rate_pct'] is None else f"{v['win_rate_pct']:.1f}%"
        pf = '--' if v['profit_factor'] is None else f"{v['profit_factor']:.2f}"
        lines.append(f"| {name} | {v['trades']} | {wr} | {v['net_R']:+.2f} | {pf} | {v['return_pct']:+.2f}% | {v['drawdown_vs_closed_balance_peak_pct']:.2f}% |")
    lines += ['', '- LOW: spread Bid/Ask từ nến, slippage 0.',
              '- BASE: spread ít nhất 2 điểm chỉ số, slippage bất lợi 0,5 điểm mỗi fill market/SL.',
              '- STRESS: spread ít nhất 3 điểm, slippage bất lợi 1 điểm. Cùng bộ lọc spread của chiến lược, nên số lệnh có thể giảm.',
              '- Commission giả định 0 cho phép thử CFD này; chưa xác minh commission của tài khoản người dùng. Risk 0,25% equity hiện tại, đã dự phòng stop slippage. Mô phỏng exposure USD/điểm lẻ, chưa phải lot thực tế của quỹ.',
              '- TP khớp đúng giá mục tiêu, không cộng lợi ích gap; SL gap khớp giá bất lợi. Nến chạm cả SL/TP tính SL trước. Không trailing/BE.', '',
              'DD trong bảng đo equity bất lợi so với đỉnh balance đã chốt; không đo đỉnh equity thả nổi trong từng lệnh, nên không phải toàn bộ peak-to-trough equity drawdown. STRESS không có lệnh không phải bằng chứng chịu phí tốt.', '',
              '## Đánh giá theo mục tiêu pass quỹ', '',
              'Bộ kiểm tra có logic cho FTMO CFD 2-Step: +10% rồi +5%, daily equity loss 5%, total equity loss 10%, ít nhất bốn ngày giao dịch mỗi phase, reset ngày Prague. Đã kiểm tra bằng dữ liệu giả có kết quả biết trước. **Không công bố tỷ lệ pass trên dữ liệu thị trường hiện tại vì chuỗi phiên quá thiếu.**', '',
              'Các con số ở bảng chỉ là kiểm tra sơ bộ trên mẫu phát triển. Không tối ưu thêm tham số để làm bảng đẹp. Một giả thuyết, ba mức chi phí đã được khóa trước khi xem P&L. Không sao chép được chiến lược chính xác của trader trong bài FTMO, không thừa hưởng win rate 81,82%.', '',
              '## Quy tắc v1', '',
              'Chart M1, 09:35–11:00 New York tự đổi DST; EMA20/EMA50 và độ dốc EMA50, hai nến hồi chạm EMA20, nến xác nhận đóng vượt cả hai nến hồi. Entry sớm nhất ở quote kế tiếp. SL ngoài cụm ba nến +0,1 ATR; TP 1,25R; thoát tối đa 15 phút hoặc 11:00 NY. Tối đa ba lệnh/ngày, dừng sau hai SL, nghỉ năm phút sau mỗi exit. Định nghĩa đầy đủ: SPEC_LOCK.json.', '',
              '## Nguồn', '',
              '- [Trường hợp US100 do FTMO lựa chọn](https://ftmo.com/en/blog/how-to-make-a-profit-when-minimizing-losses-is-a-priority/) — minh họa hướng nghiên cứu, không phải thuật toán được tác giả công bố.',
              '- [Trading objectives của FTMO](https://ftmo.com/en/trading-objectives/) — benchmark CFD 2-Step, không phải xác nhận hợp đồng của người dùng.',
              '- [Dukascopy range of markets](https://www.dukascopy.com/swiss/english/cfd/range-of-markets/) và [historical export](https://www.dukascopy.com/swiss/english/marketwatch/historical/) — nguồn Nasdaq CFD công khai.',
              '- [MQL5: tính lợi nhuận](https://www.mql5.com/en/book/automation/experts/experts_ordercalcprofit) — OrderCalcProfit không dùng được trực tiếp trong indicator; lot tham khảo dùng tick value loss/size của symbol theo tiền tài khoản.', '']
    (RUN / 'REPORT.md').write_text('\n'.join(lines), encoding='utf-8')
    print(json.dumps(dict(coverage=coverage, results=results, gate=result['gate']), ensure_ascii=True), flush=True)


if __name__ == '__main__':
    main()
