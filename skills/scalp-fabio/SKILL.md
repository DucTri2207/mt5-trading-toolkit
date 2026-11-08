---
name: scalp-fabio
description: "Phân tích scalping theo khung Fabio Valentini F1/F2 bằng dữ liệu MT5: balance, LVN/POC, phản ứng giá và CVD có nhãn nguồn. Dùng khi người dùng gọi scalp Fabio hoặc phương pháp của video scalper 169%; hoạt động độc lập với skill trade-toi và setup A phá H1."
---

# Scalp Fabio — MT5

Dùng công cụ tại `D:/trading thử lần cuối cuối/quant_mt5` để phân tích hai family F1/F2 ở M5. Đây là bản thích nghi của dự án theo khung Fabio; các ngưỡng máy và kết quả phải có bằng chứng riêng. Người dùng chưa dùng tài khoản FTMO; nguồn đã thử trước đây là MetaQuotes-Demo, tài khoản hiện tại phải được nguồn xác minh.

Đọc [phương pháp và cách diễn giải](references/method.md) khi nhận định F1/F2. Đọc [runtime](references/runtime.md) khi chạy CLI, đọc phiên hoặc replay. Chỉ dùng runtime đã cài, không chạy detector trong `staged`, bản backup hay ZIP.

## Chọn đúng công việc

- **Đọc report/snapshot được cung cấp:** chỉ đọc artifacts và giữ nhãn HISTORICAL/SYNTHETIC. Không readiness, attach, collect, once, enrich hoặc finish. Artifact legacy được đọc đúng spec legacy; thiếu trường mới không được tự bổ sung bằng suy đoán.
- **Phân tích bằng dữ liệu mới:** một lượt hữu hạn từ terminal/session/universe người dùng chọn. Tái dùng snapshot vừa có trong cùng yêu cầu nếu phù hợp; Fabio mới phải chọn tường minh `--policy scalp_mt5_v1` và kiểm policy/spec/hash trả về. Batch hiện có có thể vẫn là legacy. Không quét lại chỉ để đổi policy.
- **Xây hoặc sửa hệ thống:** làm công việc phát triển theo yêu cầu, không phát sinh một lượt thị trường từ việc skill được nhắc tên.
- **“Trade tối theo Fabio”:** dùng chung snapshot với quy trình `trade-toi`; trình bày cơ hội A và Fabio bằng ID/phương pháp riêng. Fabio WAIT hoặc CVD trái chiều không được giấu hay phủ quyết A.

## Đọc và kết luận

1. Kiểm snapshot/as-of, source, symbol mapping, policy/spec/hash, market state, coverage và basis profile/flow. Dữ liệu lỗi integrity/source/cutoff phải hiện rõ và không dùng làm bằng chứng usable.
2. Trả đủ các mã và cả F1/F2, kể cả NO_STRUCTURE, WAIT, INVALIDATED, EXPIRED hoặc lỗi dữ liệu. `max_cards` chỉ giới hạn phần giải thích sâu. Không có A vẫn phân tích Fabio được.
3. Phân biệt `setup_stage` với `execution_readiness`: đã có trigger nhưng thiếu phí vẫn là cơ hội nghiên cứu. Giữ nguyên `decision`, hạn entry và mức vô hiệu của máy; quét lại không gia hạn tín hiệu.
4. Giải thích theo chuỗi state → location → trigger → phản ứng giá → phản chứng → khả năng thực thi. Nêu kịch bản ưu tiên, diễn biến cần chờ và điều kiện bác bỏ rõ; dùng vùng/mốc đã biết tại quyết định. Vùng chờ thiếu trigger/target không được biến thành entry/SL/TP hoàn chỉnh.
5. Đọc quote, cost và mức plan từ cùng artifact. `READY_FOR_REVIEW` hoặc `ENTER_CANDIDATE` không chứng nhận giá còn vào được sau lúc viết báo cáo; không đặt/check/sửa lệnh hay chọn lot.
6. Lưu báo cáo/observation với snapshot, analysis/opportunity/revision/trigger IDs đã có. Một cơ hội xuất hiện nhiều lần không thành nhiều mẫu; không cấp candidate A giả để note hoặc replay Fabio.

Khi tiếp tục cùng nguồn/mã, tìm artifact scalp hợp lệ của lần trước trong report/ledger và truyền `--previous-analysis` để giữ balance, bins profile và target qua các snapshot. Kiểm `profile_lifecycle.mode=FROZEN_PREVIOUS_ANALYSIS_CHAIN`, source/spec và lịch sử giá khớp. Nếu chưa có artifact trước, snapshot độc lập là tái dựng; coverage/basis khác có thể tạo `profile_revision_id` khác. Giữ plan gốc làm bằng chứng replay, không đếm revision dữ liệu thành lệnh mới; không tự bỏ lỗi nối lịch sử để dựng lại tín hiệu đẹp hơn.

## Dữ liệu và giới hạn

Chỉ dùng dữ liệu MT5 đã ghim: nến, tick Bid/Ask, metadata và trade events nếu broker thực sự cung cấp. Không cần mua footprint/feed/indicator. Quote-direction CVD là **proxy hoạt động tick**, không đo tiền ròng hay xác nhận aggression/absorption thực; profile từ tick-volume nến phải ghi **xấp xỉ** ngay cạnh vùng. Với dữ liệu trade hợp lệ vẫn giữ phạm vi nguồn broker, không gọi là tape toàn thị trường.

Tin tức: `USER_MANAGED`. Giữ UNKNOWN khi thiếu commission/slippage, target, clock hoặc coverage; kịch bản phí replay ASSUMED không trở thành phí đã xác minh. Không suy xác suất thắng, ý định cá mập, lợi nhuận 169% hoặc lợi thế giao dịch từ số gate/test phần mềm.

## Kết quả tiếng Việt

Nêu giờ Việt Nam của snapshot và nguồn; bảng đầy đủ theo mã/F1/F2 gồm hướng, giai đoạn, vùng, trigger/thời hạn, readiness và lý do chờ/bỏ. Viết sâu cho các cơ hội đáng chú ý với dữ kiện ủng hộ, phản chứng và điều kiện đổi nhận định. Gắn nhãn proxy/approximation/UNKNOWN sát nội dung liên quan, kèm link report và ID để kiểm lại.

Kết thúc lượt sau khi lưu kết quả. Chỉ dùng `session finish` khi người dùng xác định đây là lượt cuối, sau khi lưu đủ report và lấy token cuối hợp lệ theo runtime. Không tự theo dõi nền, tạo lịch, train model hoặc thu thêm để làm đẹp kết quả.
