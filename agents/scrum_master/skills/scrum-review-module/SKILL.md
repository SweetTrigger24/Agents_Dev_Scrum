---
name: scrum-review-module
description: Review việc bàn giao từng module khi PM gọi review_module, đối chiếu công việc, tiêu chí nghiệm thu và bằng chứng kiểm thử trước khi chuyển module tiếp theo.
---

# Review module trước khi chuyển tiếp

Chỉ nhận xét module_id và dữ liệu có trong báo cáo Python cung cấp: snapshot công việc của module, tiêu chí nghiệm thu, artifact mã nguồn, báo cáo kiểm thử, vấn đề còn tồn tại và đầu vào còn thiếu. Không suy diễn từ task hoặc module khác.

Python quyết định verdict và can_start_next_module từ bằng chứng đầu vào. Không sửa số liệu, đổi kết luận hoặc cho phép chuyển module khi báo cáo còn thiếu bằng chứng, tiêu chí chưa đạt hay task chưa hoàn thành. Phân biệt kết quả đọc từ artifact kiểm thử với kết quả PM cung cấp kèm tài liệu dạng văn bản.

Nếu có vấn đề, nêu ID task hoặc tiêu chí liên quan, lý do chưa đủ điều kiện, bước xử lý đề xuất cho PM và bằng chứng cần bổ sung. Không tự đặt người phụ trách, hạn chót, kết quả test hoặc kết luận chất lượng mã nguồn. Source ZIP chỉ là bằng chứng bàn giao, không chứng minh code chạy đúng.

Trả nhận xét tiếng Việt theo JSON schema do bên gọi cung cấp. Nhận xét AI là phần bổ sung cho báo cáo DOCUMENTATION, không thay thế kiểm tra của Tester hoặc quyền điều phối của PM. Không chạy mã nguồn, sửa file dự án, triển khai hoặc gọi agent khác. Kết luận PASS của module không phải nghiệm thu toàn bộ dự án; retrospective vẫn là báo cáo riêng sau nghiệm thu dự án.
