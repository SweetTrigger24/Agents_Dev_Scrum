---
name: dev-refactor-code
description: Cải tổ mã nguồn hiện có khi PM gọi refactor_code, giữ nguyên hành vi bên ngoài và báo cáo bằng chứng kiểm thử hồi quy.
---

# Cải tổ mã nguồn trong phạm vi được yêu cầu

Hệ thống có thể chuẩn bị source từ file PM gửi hoặc bản bàn giao thành công gần nhất của cùng project_id. Làm việc trên bản đã giải nén trong workspace; không tự truy cập bản lưu hoặc workspace của dự án khác.

Đọc mã nguồn đã giải nén, kiến trúc và mục tiêu cải tổ do PM đưa ra. Xác định những hành vi và giao diện công khai phải giữ ổn định. Giới hạn thay đổi theo mục tiêu đó; không thêm tính năng, đổi bộ công nghệ hoặc tự ý thay đổi quy ước API hay cơ sở dữ liệu.

Chạy các kiểm tra liên quan có sẵn trước và sau khi thay đổi nếu có thể. Bổ sung kiểm thử hồi quy tập trung khi giúp chứng minh hành vi được giữ nguyên. Nếu môi trường không cho phép xác minh, ghi rõ giới hạn đó và đặt các mục nghiệm thu bị ảnh hưởng là UNVERIFIED. Không mô tả việc sắp xếp lại cấu trúc là cải thiện hiệu năng đã được đo lường khi chưa có số liệu đo.

Tạo delivery_report.json theo schema do bên gọi cung cấp. Liệt kê đường dẫn đã thay đổi hoặc xóa cùng lý do, các lệnh kiểm tra thực sự đã chạy và kết quả. Ghi lại rủi ro chưa được xử lý. Bàn giao mã nguồn và báo cáo cho PM để kiểm thử độc lập; chỉ làm việc trong workspace của nhiệm vụ, không triển khai hoặc gọi agent khác.
