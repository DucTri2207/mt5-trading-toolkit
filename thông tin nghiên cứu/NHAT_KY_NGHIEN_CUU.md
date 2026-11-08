# Nhật ký nghiên cứu — 25/10/2026

## Yêu cầu đã xử lý

Người dùng muốn nghiên cứu thay đổi cấu trúc indicator hướng tới lệnh khoảng 1,5R và SL dời theo giá; chưa yêu cầu sửa mã. Trong lúc làm, người dùng mở rộng sang vàng, các cặp tiền và chỉ số. Hồ sơ đã cập nhật theo cả hai yêu cầu.

## Công việc đã thực hiện

- Tạo thư mục nghiên cứu và chụp SHA-256 của 52 file source/binary/settings/script hiện có vào baseline trước khi lập tài liệu.
- Đọc báo cáo cũ và những đoạn mã cần thiết để xác định chỗ nào là setting, chỗ nào là giới hạn cấu trúc. Không dùng hướng dẫn trong tài liệu cũ thay cho yêu cầu hiện tại.
- Tra cứu nguồn sơ cấp và đối chiếu 33 tài liệu/bài/trang chính thức. Danh mục gồm nhiều loại bằng chứng, không phải 33 chiến lược có lợi nhuận đã xác minh.
- Xác nhận thành tích thi đấu của Unger/Davey bằng trang tổ chức; giữ riêng với phương pháp họ công bố.
- Ghi case vàng/forex/chỉ số có số liệu; phân biệt payoff ratio với R theo SL ban đầu, futures với CFD và ticket với idea.
- Lập ba playbook nghiên cứu, đặc tả trailing/room, bản đồ module và kế hoạch kiểm định tương lai; chưa chạy chiến lược mới.
- Lưu rõ các thông số không công khai và các symbol chưa có case đủ số liệu; không điền giá trị phổ biến để làm đủ bảng.

## Những nguồn/chi tiết không được đưa thành bằng chứng

- Link World Cup “standings-version-2” lỗi truy cập; dùng trang historical standings chính thức còn hoạt động.
- URL FAQ news CFD FTMO thử truy cập trả 404; không dùng nó để khẳng định luật news hiện tại. Chưa chốt bảo vệ news cho bất kỳ gói quỹ nào.
- Kho lưu học thuật eScholarship trả 429 khi mở; chuyển sang bản PDF của chính tác giả cho nguồn S23.
- Bài FTMO về ba cặp USD được search index tìm thấy nhưng khi mở chuyển về trang blog; không đưa vào 33 nguồn đã chốt hoặc lấy số liệu làm kết luận.
- Nguồn S27 mở lại có timeout; chỉ dùng mô tả phỏng vấn và phần phương pháp được tìm thấy trên domain chính thức, không dùng số lợi nhuận để xác nhận hiệu quả.
- Ngày tương đối của search engine và của bài có thể lệch nhau; dùng ngày truy cập, không tự đặt ngày xuất bản chính xác. PDF Raschke là nội dung tháng 3/2004 dù đường dẫn upload năm 2026.
- Các bài marketing có diễn giải về tâm lý, tổ chức hoặc thuật toán không tự trở thành dữ kiện. Không suy từ lot cố định rằng rủi ro cố định hoặc hệ thống hoàn toàn tự động.
- Chưa lấy mã trong dịch vụ trả phí, không đăng ký, mua dữ liệu, tải robot hay cài thư viện/skill.

## Câu hỏi còn mở cho buổi thảo luận

1. “1,5R” muốn là target tối thiểu, mức khóa lãi hay lãi trung bình của lệnh thắng? Hồ sơ tạm đo các đại lượng riêng.
2. Tần suất mong muốn tính trên một symbol hay cả danh mục, theo ngày hay tháng?
3. Chấp nhận mức giveback/MFE và drawdown bao nhiêu để giữ được sóng?
4. Ưu tiên setup pilot và nguồn dữ liệu nào? Symbol/contract thực tế của broker ra sao?
5. Tài khoản quỹ thuộc đơn vị, loại gói và ngày hiệu lực nào? Không mặc định mọi account 100k cùng quy tắc.

Những câu hỏi này không cản việc hoàn thành hồ sơ hiện tại và không được coi là sự cho phép triển khai.

## Kết quả của đợt nghiên cứu

Đã có bản tổng hợp để review và chọn hướng thử nghiệm. Chưa có tuyên bố một chiến lược mới đạt 1,5R, winrate mục tiêu, tần suất mục tiêu hoặc đạt điều kiện tài khoản quỹ. Bản ghi kiểm tra phạm vi cuối cùng nằm ở `kiem_tra_pham_vi_20261025.json`.
