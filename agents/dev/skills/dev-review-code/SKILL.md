---
name: dev-review-code
description: Rà soát mã nguồn được PM chuyển đến qua review_code, báo cáo phát hiện và hướng xử lý mà không chỉnh sửa mã nguồn.
---

# Rà soát mã nguồn được bàn giao

Source có thể do PM gửi hoặc được hệ thống khôi phục từ bản bàn giao thành công gần nhất của cùng project_id. Chỉ rà soát bản đã được chuẩn bị trong workspace; không tự chọn source từ thư mục hoặc dự án khác. Việc review không thay thế bản source lưu dùng để phát triển tiếp.

Đọc mã nguồn được cung cấp và các tiêu chí nghiệm thu liên quan trong references/. Tập trung vào tính đúng đắn có thể kiểm chứng, lỗi hồi quy, xử lý đầu vào và các bước kiểm tra dữ liệu còn thiếu. Tuân theo kiến trúc PM cung cấp, không áp đặt bộ công nghệ mới. Không thay đổi mã nguồn đang rà soát hoặc tài liệu tham khảo; chỉ ghi file delivery_report.json.

Với mỗi phát hiện, cung cấp ID duy nhất, mức độ nghiêm trọng, đường dẫn file mã nguồn hiện có, số dòng, tình huống gây lỗi cụ thể và hướng sửa đề xuất. Phân biệt phát hiện đã xác nhận bằng phân tích tĩnh với những kiểm tra chưa chạy. Không suy đoán lỗ hổng hoặc chỉ nêu vấn đề về phong cách viết code, trừ khi PM yêu cầu rà soát phong cách. Không tìm thấy vấn đề chỉ có nghĩa là chưa phát hiện lỗi trong phạm vi rà soát, chưa chứng minh sản phẩm sẵn sàng phát hành.

Tuân theo JSON schema của báo cáo bàn giao do bên gọi cung cấp. Dùng action là review_code, đặt changes=[] và ghi các mục checks với trạng thái NOT_RUN khi chưa kiểm tra hành vi chạy thực tế. Thể hiện tình trạng thiếu ngữ cảnh trong scope_status và unresolved. Gửi báo cáo về PM; không sửa code, triển khai hoặc gọi agent khác.
