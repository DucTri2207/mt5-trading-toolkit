# ⚡ HƯỚNG DẪN CÀI ĐẶT TELEGRAM BOT BÁO KÈO SMC (1 PHÚT)

Hệ thống cảnh báo **Đức Trí SMC Multi-Timeframe v3.1** được thiết kế 100% Pure MQL5 (hoàn toàn không dùng DLL ngoài), hỗ trợ bắn kèo tự động M5 CHoCH sau khi quét cản H1 về Telegram Bot và App MT5 trên điện thoại.

---

## BƯỚC 1: TẠO BOT & LẤY TOKEN (30 GIÂY)
1. Mở ứng dụng Telegram, tìm kiếm bot chính thức: `@BotFather` (có dấu tích xanh).
2. Gửi lệnh: `/newbot`
3. Nhập tên hiển thị cho bot (Ví dụ: `Duc Tri SMC Bot`).
4. Nhập username cho bot (phải kết thúc bằng chữ `bot`, ví dụ: `ductri_smc_keo_bot`).
5. **BotFather** sẽ gửi lại đoạn mã **HTTP API Token** có dạng:
   `<TELEGRAM_BOT_TOKEN>`
   👉 *Hãy sao chép (copy) đoạn mã Token này.*

---

## BƯỚC 2: LẤY CHAT ID & KÍCH HOẠT BOT (15 GIÂY)
1. Tìm kiếm bot: `@userinfobot` trên Telegram.
2. Bấm **START**. Bot sẽ phản hồi thông tin cá nhân của bạn:
   - Dòng `Id:` chính là Chat ID của bạn (Ví dụ: `123456789`).
   👉 *Hãy sao chép dãy số Chat ID này.*
3. **CỰC KỲ QUAN TRỌNG:**
   Tìm lại con bot bạn vừa tạo ở Bước 1, bấm **START** (hoặc gửi `/start`) để mở quyền cho bot gửi tin nhắn tới bạn! *(Nếu không bấm /start, máy chủ Telegram sẽ chặn tin nhắn).*

---

## BƯỚC 3: CẤP QUYỀN WEBREQUEST TRONG MT5 (15 GIÂY)
*(Do quy định bảo mật của MetaQuotes, mọi kết nối internet từ MT5 đều cần cấp phép danh sách URL trắng)*

1. Trên menu MT5, chọn **Tools** -> **Options** (hoặc nhấn phím tắt `Ctrl + O`).
2. Chuyển sang thẻ **Expert Advisors**.
3. Tích chọn vào ô: `Allow WebRequest for listed URL:`
4. Nhấn đúp chuột vào dòng có dấu `+` màu xanh (Add new URL) và điền chính xác:
   `https://api.telegram.org`
5. Bấm **OK** để lưu lại.

---

## BƯỚC 4: KÍCH HOẠT HỆ THỐNG TRÊN CHART MT5

### Cách 1: Sử dụng Telegram Bot (Khuyên dùng)
1. Mở cửa sổ **Navigator** (`Ctrl + N`) trong MT5:
   - Vào mục **Expert Advisors** -> Kéo `duc_tri_telegram_bridge` thả vào bất kỳ chart nào (có thể mở 1 chart trắng riêng hoặc thả chung chart với chỉ báo).
   - Trong tab **Inputs**: Dán `InpTgToken` và `InpTgChatID` đã lấy ở Bước 1 & 2.
   - Bấm **OK**.
2. **Đồng bộ tự động thông minh**:
   - Bạn chỉ cần dán Token & Chat ID **1 lần duy nhất** vào EA `duc_tri_telegram_bridge` (hoặc vào Chỉ Báo). Hệ thống sẽ tự động lưu và đồng bộ sang tất cả các chart khác qua bộ nhớ chung UTF-8!
3. Trên góc trên bên phải màn hình chart, bạn sẽ thấy nút bấm:
   👉 **[ ⚡ GỬI TEST TELEGRAM ]**
   Nhấp chuột vào nút này (hoặc nút `[TELEGRAM]` trên Dashboard Canvas của chỉ báo). Điện thoại bạn sẽ ngay lập tức "ting ting" tin nhắn kiểm tra kết nối từ Bot!
4. Giờ chỉ cần kéo Chỉ Báo `duc_tri_can_ho_tro` vào các cặp tiền bạn muốn đánh (ví dụ XAUUSD M5, EURUSD M5).
   - Mỗi khi xuất hiện mũi tên M5 BUY/SELL CHoCH sau khi quét cản H1, hệ thống sẽ tự động gửi thông báo chi tiết:
     ```html
     ⚡ SMT / SMC M5 CHoCH TRIGGER ⚡
     ━━━━━━━━━━━━━━━━━━━
     💎 Cặp tiền / Tài sản: XAUUSD (M5)
     🧭 Hướng: 🟢 BUY CHoCH
     🏛 Cản H1 kích hoạt: DEMAND DBR (Điểm: 85/100)
     ━━━━━━━━━━━━━━━━━━━
     📍 Giá Entry: 2650.50
     🛡 Stop Loss: 2647.20 (kê chóp râu nến M5, 33.0 pips)
     🎁 Take Profit 1 (1:1.5): 2655.45 (+49.5 pips)
     🚀 Take Profit 2 (1:2.0): 2657.10 (+66.0 pips)
     🎯 Target Cản H1 đối diện: 2665.00 (+145.0 pips | R:R 1:4.4)
     ━━━━━━━━━━━━━━━━━━━
     ⏰ Khung giờ: 2026.10.18 14:35
     💡 Gợi ý: Chốt 50-70% volume tại TP1 (1:1.5), dời SL về Hòa Vốn (BE), gồng runner đến TP2 (1:2.0) & Cản H1!
     ```

### Cách 2: Nhận thông báo trực tiếp qua App MT5 trên điện thoại (0-Setup)
Hệ thống đã bật sẵn `AlertPush = true` mặc định:
1. Cài app **MetaTrader 5** trên điện thoại iPhone/Android.
2. Mở app MT5 trên điện thoại -> Cài đặt (Settings) -> Chat & Tin nhắn (Messages) -> xem mã **MetaQuotes ID** (gồm 8 chữ số/ký tự).
3. Trên máy tính, mở MT5 -> Tools -> Options -> Notifications -> tích chọn `Enable Push Notifications` và dán mã MetaQuotes ID vào.
4. Bấm **Test**. Kèo M5 CHoCH sẽ hiển thị dạng Banner thông báo nổ chuông ngay trên màn hình khóa điện thoại của bạn hoàn toàn miễn phí!
