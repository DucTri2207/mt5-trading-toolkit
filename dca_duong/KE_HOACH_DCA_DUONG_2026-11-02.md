# Kế hoạch bot DCA dương XAUUSD + Claude/Codex điều phối (02/11/2026)

Doc đầy đủ (có sơ đồ): https://claude.ai/artifact/4yANSDwdn6tMyDdZoJcmmj
Trạng thái: KẾ HOẠCH — chưa code. Chờ Triển: (1) copy file .ex5 bot cũ vào `D:\trading thử lần cuối cuối`, (2) trả lời câu hỏi mục 8.

## 1. Tóm tắt
- Đổi hướng khỏi indicator scalp (v4: không có bằng chứng lợi thế). Làm bot DCA dương (pyramiding — nhồi lệnh khi giá đi đúng hướng) cho XAUUSD.
- EA MQL5 thuần quy tắc giữ quyền đặt lệnh. Claude/Codex chỉ "gác cổng" mỗi H1: ghi `policy.json` (cho hướng nào, hệ số rủi ro ≤ 1, có hạn dùng 90'). Lỗi/hết hạn/hai LLM khác ý → không mở rổ mới.
- Lợi thế phải đến từ EA quy tắc (backtest tick thật). LLM chỉ được chấm bằng forward/shadow vì LLM đã "thuộc" giá vàng quá khứ.

## 2. Bot cũ (.ex5)
- Tên file: "166.6 giá vàng. 91 lệnh. 7.46 lot cent = 0.074lot" → nếu cách đều & cùng lot: bước ≈ 1,85 giá, ≈ 0,08 lot cent/lệnh (chưa xác nhận).
- .ex5 không dịch ngược được → chạy hộp đen trong Strategy Tester portable (`reports\can_ho_tro_v4\20261102_m3a_v1\portable_terminal`), 3 đoạn (trend, đi ngang, tuần tin lớn); đọc mục Inputs + danh sách deal → `BOT_CU_SPEC.md`.
- Claude chưa đọc được Downloads (bị từ chối quyền) → cần Triển copy file.

## 3. Toán rủi ro
- N lệnh cùng lot, quãng D: giá vốn TB cách đỉnh D/2. Lãi tại đỉnh = L × D/2 (L = USD mỗi 1 giá của cả rổ). Hồi D/2 là về 0.
- Ví dụ bot cũ: 7,46 USD/giá × 83,3 ≈ 621 USD (≈ 62.100 USC) tại đỉnh; hồi 166,6 → lỗ ≈ 621 USD.
- Luật cốt lõi "nhồi bằng tiền lãi": R_rổ = Σ v_i (P_i − S) ≤ R_max (1% vốn) sau mỗi lần nhồi; không đủ chỗ thì không nhồi.
- Turtle: +1 đơn vị mỗi 0,5 ATR, tối đa 4, SL chung 2 ATR từ lệnh mới nhất.
- Vàng 2026 biên độ H1 lớn (blog MQL5: trung vị ~26 USD vs ~5 USD 2022–24; chưa kiểm chứng) → bước nhồi theo ATR.

## 4. EA v1 (mặc định đề xuất)
| Thành phần | Mặc định | Biến thể |
|---|---|---|
| Lệnh đầu | Phá đỉnh/đáy 20 nến H1 + cùng phía EMA200 H1 | Mũi tên Cản Hỗ Trợ v4; Triển tự bấm |
| Bước nhồi | 0,5 × ATR(H1,14), ≥ 8 × spread | 0,25 / 1,0 ATR; cố định như bot cũ |
| Khối lượng | Lệnh đầu 1% vốn; nhồi giảm ×0,7/bậc | Lot đều |
| Cửa nhồi | R_rổ sau khi thêm ≤ 1% vốn | 1,5% |
| SL rổ | 2 ATR sau lệnh đầu, kéo lên mỗi lần nhồi, ghi SL thật lên server | SL ảo + SL thảm hoạ |
| Thoát | Lãi rổ rơi 40% từ đỉnh lãi (sau ≥ 1R) hoặc phá 10 nến H1 ngược | 30%/50%; TP theo R |
| Trần | 30 lệnh/rổ, 1 rổ/chiều, trần tổng lot | 50 / 91 |
| Tin, spread | Không mở/nhồi ±30' tin đỏ USD; spread cao thì chờ | Bỏ lọc |
| Cầu chì | Lỗ ngày ≥ 3% nghỉ; sụt vốn ≥ 15% khoá EA | Luật quỹ |
Kỹ thuật: tài khoản hedging, magic riêng, OrderCalcMargin, khôi phục rổ khi restart, journal CSV.

## 5. Kiến trúc
Claude (điều phối) + Codex (ý kiến thứ hai) ⇄ Cầu Python (MetaTrader5: snapshot D1/H4/H1, ATR, lịch tin, rổ; kiểm schema, kẹp trần, ghi policy.json) → EA DCA dương (giữ quyền đặt lệnh, trần cứng) → server sàn (SL thật). EA ⇄ Telegram (nhịp tim, tắt khẩn).
- policy.json: valid_until, regime, allow_buy, allow_sell, risk_mult (0–1), max_layers, step_atr, close_all, confidence, reason.
- Gọi: Task Scheduler mỗi H1 → `claude -p --bare --output-format json --json-schema policy.schema.json` (cần API key) + `codex exec --output-schema policy.schema.json`.
- MCP MT5 chỉ để hỏi tay, không cho đường tự động (không xác thực, mật khẩu trong cấu hình).
- Lý do: Alpha Arena S1 (18/10–3/11/2025) 4/6 LLM lỗ, Claude Sonnet 4.5 10.000 → 5.799 USD; FINSABER: LLM quá thận trọng khi tăng, quá liều khi giảm.
- Khâu phát triển: Claude đặc tả + nghiệm thu; Codex code + chạy tester; kênh codex_inbox/outbox (tiếp theo: claude_017).

## 6. Lộ trình + cổng
| Giai đoạn | Việc | Cổng |
|---|---|---|
| P0 (1–2 ngày) | Khôi phục bot cũ bằng tester | Đặc tả giải thích ≥ 90% lệnh |
| P1 (3–5 ngày) | Đặc tả + code EA v1 | Compile 0/0; chart demo 1 ngày không lỗi; restart giữa rổ khôi phục đúng |
| P2 (3–5 ngày) | Backtest tick thật, kiểm 12 tháng gần nhất, stress spread ×1,5 | **PF ≥ 1,3 ngoài mẫu sau phí, ≥ 100 rổ, DD ≤ 10%, ±20% tham số vẫn lãi. Không đạt → dừng** |
| P3 (2–3 ngày) | Bộ lọc chế độ quy tắc | DD giảm ≥ 25%, giữ ≥ 70% lợi nhuận |
| P4 (4 tuần) | LLM chạy bóng trên demo | ≥ 30 rổ; LLM tránh thua tốt hơn quy tắc, không bỏ rổ thắng lớn; không đạt → LLM chỉ cố vấn |
| P5 (4 tuần) | Demo có LLM gác cổng, 0,5%/rổ | Trong dải backtest; trượt giá ≤ 1,5× giả định; 0 sự cố |
| P6 | Cent thật, 0,25%/rổ tăng dần | Dừng nếu DD > 1,5× backtest |

## 7. Rủi ro chính
Đi ngang (nhiều rổ thua nhỏ) · gap/đảo chiều khi rổ to · phí trên nhiều lệnh nhỏ · backtest ảo (bài học v3.01/AGY) · LLM sai/chậm/hết quota · LLM backtest bị look-ahead · prompt injection từ web · máy tắt · tâm lý chuỗi thua dài.

## 8. Câu hỏi cho Triển
1. Tài khoản đích: cent (sàn nào?) hay thi quỹ?
2. Bot cũ vào lệnh đầu theo gì, đóng rổ thế nào, có khoá tài khoản?
3. Lệnh đầu bot mới: phá đỉnh/đáy H1, mũi tên v4, hay tự bấm?
4. Quyền của LLM: chỉ bật/tắt hướng + giảm rủi ro, hay chỉnh bước/lớp trong giới hạn?
5. Chạy máy nhà 24/5 hay VPS Windows?
6. Claude dùng gói đăng ký hay API key; Codex làm ý kiến thứ hai khi live?
7. Rủi ro 1%/rổ, 3%/ngày, 15% tổng — đồng ý?
8. Lot nhồi: đều (như bot cũ) hay giảm dần ×0,7?

## Nguồn
- https://www.mql5.com/en/articles/23448 (Turtle rules MQL5)
- https://www.mql5.com/en/blogs/post/774661 (biên độ vàng 2026 — bài quảng cáo)
- https://forklog.com/en/four-out-of-six-ai-models-suffer-losses-in-trading-tournament/
- https://arxiv.org/html/2505.07078v3 (FINSABER)
- https://www.mql5.com/en/docs/python_metatrader5
- https://docsearch.algolia.com/mcp/docs/repo/ariadng/metatrader-mcp-server
- https://code.claude.com/docs/en/headless
- https://learn.chatgpt.com/docs/non-interactive-mode
