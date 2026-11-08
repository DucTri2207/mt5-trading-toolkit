# Kiểm chứng tối ưu hiệu năng — 08/11/2026

Không kết nối MT5, không đặt lệnh, không sửa/xóa dữ liệu tick lịch sử.

## Cùng dữ liệu, cùng kết quả

Chạy `benchmark_performance.py` lần lượt với mã nguồn trước nâng cấp và mã nguồn mới. Nguồn: bundle lịch sử `CFGB_b278a22ce4b09dfd68f2`, pin `SNAP_f05620cbbcb761935e5c`; EURUSD, cắt dữ liệu tại 06/11/2026 13:00 UTC. Mỗi chu kỳ gọi hai lần tải bar → detector → MT5 flow, mô phỏng phần phân tích và báo cáo tái sử dụng cùng snapshot.

- 7.078 nến M5, 1.441 tick chunks; 94 candidates, 133 episodes, 287 bar flow usable.
- Hash toàn bộ catalog giống nhau trước/sau: `e0f7511e26490be4a5d41e98751391a286d4e439387f57224416cd11c21d7e09`.
- Hash toàn bộ flow, quote và profile giống nhau: `3ef00efebc400c4efce37854efbc244059aae0998c3fa207bcd478117ce5ecda`.

| Chu kỳ | Trước nâng cấp | Sau nâng cấp |
|---|---:|---:|
| Đầu trong process | 8,533 giây | 2,021 giây |
| Lặp 1 | 7,848 giây | 2,358 giây |
| Lặp 2 | 6,514 giây | 1,772 giây |
| Trung vị hai lần lặp | 7,181 giây | 2,065 giây |

Đợt so sánh với fingerprints mã nguồn lưu trong `benchmark_baseline.json` và `benchmark_upgraded.json`: trung vị workload giảm khoảng 71,2%, tương đương 3,48 lần nhanh hơn. Lần đo trước đó trên cùng máy giảm 62,2% (5,657 → 2,140 giây), cho thấy nhiễu wall-time; không chọn một hệ số làm cam kết. Cache mới có 11 hit / 11 miss và 0 eviction mỗi chu kỳ, giữ 120.255.360 byte tick tape; hết chu kỳ cache được giải phóng. Mọi chunk vẫn được SHA-256 kiểm lại trước mỗi lần tái sử dụng; lỗi mất/sửa chunk không bị cache che khuất.

Môi trường: Windows AMD64, Python 3.13.11, NumPy 2.4.3. Hai JSON nêu trên lưu path nguồn tuyệt đối, SHA-256 từng file triển khai, từng stage timing, counters và parity hashes.

Sau bản vá cuối giữ thêm nhãn ASK/M1 missing khi economics UNKNOWN, chạy lại bản nguồn đóng băng trong `benchmark_upgraded_final.json`: 30,294 / 1,827 / 2,258 giây; trung vị hai lần lặp 2,043 giây; parity hashes vẫn giống hoàn toàn. Lần đầu 30,294 giây là outlier khi kiểm thử replay dữ liệu thật chạy đồng thời; vẫn giữ nguyên trong bằng chứng. Đây cũng là lý do không hứa SLA hoặc tốc độ cold dựa trên số trung vị. Hash cuối của `replay.py`: `f04453581491a841efbac379b548fafb6e5c7b6cf66a5261069b0de513931603`.

Đây là benchmark offline một mã, 3 chu kỳ, không phải p95 hay SLA quét live toàn universe. OS cache không được flush; máy có thể có kiểm thử khác chạy đồng thời. Lần đầu là process-cold, không phải disk-cold.

## Lệnh tái lập

Chạy PowerShell trong thư mục workspace, dùng Python cài tại `C:\Users\ductr\AppData\Local\Programs\Python\Python313\python.exe`:

```powershell
& 'C:\Users\ductr\AppData\Local\Programs\Python\Python313\python.exe' 'D:\trading thử lần cuối cuối\quant_mt5_plan_20261108\benchmark_performance.py' --source-root 'D:\trading thử lần cuối cuối\quant_mt5_plan_20261108\baseline_before_upgrade' --workspace-root 'D:\trading thử lần cuối cuối' --cycles 3
& 'C:\Users\ductr\AppData\Local\Programs\Python\Python313\python.exe' 'D:\trading thử lần cuối cuối\quant_mt5_plan_20261108\benchmark_performance.py' --source-root 'D:\trading thử lần cuối cuối\quant_mt5' --workspace-root 'D:\trading thử lần cuối cuối' --cycles 3
```

## Kiểm thử

Trong `quant_mt5`: `python -m pytest tests/test_mt5_flow.py tests/test_upgrade_performance.py tests/test_b1_fixes.py -q -k 'not truncated_D1'`: **59 passed, 1 deselected**.

Suite nâng cấp có 15 kiểm thử: rolling bars/ticks không tải lại toàn lookback; bất biến pin cũ; đóng nến và micro-tail H1/D1; giữ nguyên pending tick cùng millisecond; ranh giới scope; cache không che file bị sửa/xóa; raw-order rejection; cutoff/late-arrival; caller sửa catalog không làm nhiễm cache; strategy output parity; giới hạn byte-cache và eviction telemetry; chi phí proxy không hợp lệ phải giữ UNKNOWN.

Kiểm thử mở rộng `test_detectors.py test_b2.py test_b3.py test_snapshot_notes.py`: 70 passed, 1 failed trong 320 giây. Failure là nhãn ASK_MISSING bị mất khi cùng lúc economics UNKNOWN; đã sửa giữ cả hai lý do. Chạy lại test lỗi và suites hiệu năng/MT5 flow: `python -m pytest tests/test_b3.py::test_replay_ledger_is_reproducible_and_labelled tests/test_upgrade_performance.py tests/test_mt5_flow.py -q`: **29 passed** trong 50,38 giây. Không tuyên bố đã chạy lại toàn bộ suite lớn sau bản vá nhãn này.

Lỗi `test_R3_truncated_D1_without_boundary_is_gaps` đã tồn tại trong baseline (test chờ lower-bound=3, engine tính=2). Đã chạy cùng test trên bản sao trước nâng cấp để xác nhận; không sửa quy tắc D1 nhằm ép test xanh. Test B1 collector cũ có fixture thiếu account_currency cũng thất bại y hệt ở baseline.

## Cơ chế triển khai

- Tái dùng coverage interval đã hoàn thành bất kể start của lookback trượt; chỉ lấy phần chưa có, retry khoảng thiếu, giữ immutable chunks cũ.
- Dùng actual requested bounds, không nhầm phần nến đang chạy với phần đã hoàn tất; không phát sinh request cho khoảng H1/D1 không có thời điểm mở nến đủ điều kiện.
- Cache theo scope và content/read-contract identity; catalog trả bản sao; tape giới hạn 12 mã và 256 MiB tổng decoded tape; không giữ cache qua chu kỳ mới. Khi quá budget sẽ evict và báo counter, không hứa tuyệt đối chỉ decode một lần cho tape quá lớn. Bar/symbol/catalog đủ capacity cho universe ca tối.
- Decode tick một lần, giữ chứng cứ raw order; index từng bar bằng searchsorted khi event time tăng dần, vẫn lọc available time, giữ same-ms multiplicity/reset/gap/proxy.
- Collection/read có retention lease; tick generation bị purge phải lỗi rõ ngay cả khi tape đã nằm trong cache.

Tối ưu tốc độ và mở rộng mã không chứng minh tỷ lệ thắng tăng; quy tắc detector A/B không thay đổi.
