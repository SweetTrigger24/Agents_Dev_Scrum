---
name: dev-fix-bugs
description: Sửa mã nguồn hiện có khi PM gọi fix_bugs, dựa trên các phát hiện từ kiểm thử hoặc báo cáo bảo mật được chuyển đến.
---

# Sửa lỗi theo nhiệm vụ PM giao

Mã nguồn đầu vào có thể do PM chuyển đến hoặc được hệ thống khôi phục từ bản bàn giao thành công gần nhất của cùng project_id. Chỉ sử dụng source đã được chuẩn bị trong workspace; không tự tìm hoặc sửa bản lưu của dự án khác.

Kiểm tra mã nguồn hiện có đã được giải nén vào workspace và các báo cáo kiểm thử hoặc bảo mật trong references/. Mỗi thay đổi phải gắn với một phát hiện trong báo cáo hoặc chỉ dẫn của PM. Giữ nguyên hành vi không liên quan và bộ công nghệ đang dùng; không thay ứng dụng bằng một bản mẫu mới.

Tái hiện lỗi được báo cáo khi môi trường cho phép. Thực hiện thay đổi sửa lỗi nhỏ nhất nhưng đầy đủ, bổ sung kiểm thử hồi quy khi có ích và chạy các bài kiểm thử liên quan có sẵn. Ghi vào README hoặc báo cáo sửa lỗi những phát hiện đã xử lý, những vấn đề còn tồn tại, các lệnh thực sự đã chạy và giới hạn của môi trường.

Không khẳng định lỗ hổng đã được xử lý hoặc kiểm thử đã đạt khi chưa có bằng chứng. Nếu thiếu mã nguồn hoặc báo cáo chưa đủ thông tin, xác định đó là thiếu ngữ cảnh; không tự tạo nội dung thay thế. Bàn giao mã nguồn và báo cáo sửa lỗi cho PM để xác minh độc lập. Không triển khai hoặc gọi agent khác; chỉ làm việc trong workspace của nhiệm vụ và không truy cập thông tin bí mật.

Tạo delivery_report.json theo schema do bên gọi cung cấp. Liên kết từng thay đổi với ID phát hiện trong báo cáo đầu vào nếu có. Với mỗi yêu cầu sửa lỗi, ghi một mục nghiệm thu kèm bằng chứng; liệt kê rõ các phát hiện chưa xử lý. Ghi lại những kiểm thử hồi quy không đạt hoặc bị bỏ qua, không loại chúng khỏi báo cáo. Đặt scope_status là PARTIAL hoặc NEEDS_CONTEXT khi việc sửa lỗi chưa hoàn tất; không mô tả một thay đổi chưa được xác minh là lỗi đã được xác nhận xử lý xong.
