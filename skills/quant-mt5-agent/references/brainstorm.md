# Brainstorm có phản chứng (dùng với `fabio` hoặc setup baseline)

Mục tiêu: một kịch bản ưu tiên, một kịch bản ngược, và **bằng chứng bác bỏ mạnh nhất** — không phải gom mọi chỉ báo cùng ủng hộ bias đã chọn.

## Mẫu cho mỗi cơ hội
1. **Kịch bản ưu tiên**: state → location → trigger (từ output máy; ghi family, spec_hash, snapshot).
2. **Kịch bản ngược**: điều kiện cụ thể (mức giá/sự kiện) làm luận điểm sai; lấy từ `invalidation`, `contradicting_evidence`, `missing`.
3. **Bằng chứng bác bỏ mạnh nhất**: một mục, nêu rõ nguồn (price bar / flow ngoài / thiếu dữ liệu).
4. **Hành động**: cân nhắc vào / chờ điều kiện X trước `expires_at` / bỏ. Không nâng WAIT thành vào vì "cảm giác".
5. **Hạn chế dữ liệu**: route đang dùng, flow có/không, economics KNOWN/UNKNOWN, news UNKNOWN.

## Quy tắc đọc flow / CVD
- Giá giữ vùng nhưng CVD giảm: **có thể** là hấp thụ lực bán (nếu delta là executed thật và đúng reset/basis). Không tự thành lý do short; cần giá thực sự phá/giữ dưới vùng. Tool gọi tình huống này `OPPOSING_AGGRESSION_ABSORBED` — vẫn chỉ là suy luận, không phải quan sát lệnh thụ động.
- Aggression cùng hướng mà giá không tiến (`POSSIBLE_ABSORPTION_AGAINST`) là lý do chất vấn hướng đó.
- Phân kỳ chỉ so **các swing tương ứng** (fractal pivot đã xác nhận, thời điểm biết = sau n nến), cùng reset/basis, không nối qua khoảng trống. Là bối cảnh, không phải trigger. Nến giá đỏ + nến CVD xanh trong một khoảng không đủ gọi phân kỳ swing.
- CVD ước lượng từ giá/tick-volume không phải nguồn flow độc lập; không đếm thêm như một "xác nhận" thứ hai.
- Với CVD `TICK_DIRECTION_PROXY`, chỉ nói tick tăng/giảm và giá tiến/không tiến. Không gọi là aggression/absorption thực; không coi xác nhận từ biến động giá là bằng chứng độc lập. Thiếu tick thì ghi missing đúng output; mọi dữ liệu vận hành lấy từ MT5.

## So sánh lựa chọn (ghi log, không kết luận)
Với cùng cơ hội ghi `price_response`, `price_plus_cvd`, `price_plus_bar_delta` (có trong `variants`). `price_plus_local_aggression` giữ `DATA_UNAVAILABLE` khi chưa có executed trades theo mức giá. Delta của cả nến chỉ là bằng chứng trên cửa sổ phản ứng, không chứng minh aggression ngay tại LVN. Khi dữ liệu thị trường cũ, không dùng bất kỳ variant nào để vào. Về sau đánh giá bằng expectancy ròng sau chi phí, coverage, số cơ hội độc lập (nhiều biến thể trên một cơ hội không tăng số mẫu). Chưa tuyên bố tối ưu winrate. "Thắng" = P&L ròng > 0 sau phí, không phải chạm TP trên nến.

## Cấm
Xác suất thắng/độ tin cậy từ số phiếu AI hay số gate qua; ép toàn bộ chỉ báo đồng thuận; dùng MFE/MAE sau entry hoặc POC tương lai làm feature; lấy giá futures làm entry/SL/TP CFD; nói đã qua gate tài khoản khi chưa đọc equity/rule thực.
