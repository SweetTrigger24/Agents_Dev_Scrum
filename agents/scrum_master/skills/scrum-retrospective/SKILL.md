---
name: scrum-retrospective
description: Tổng kết snapshot task khi PM gọi run_retrospective và đề xuất cải tiến mà không tự suy diễn lịch sử sprint.
---

# Tổng kết trạng thái bàn giao

Chỉ dựa vào bằng chứng có trong báo cáo do Python tổng hợp. Python chịu trách nhiệm cho toàn bộ số liệu task. Task đã hoàn thành chưa phải bằng chứng rằng kiểm thử đã đạt hoặc triển khai thành công. Một snapshot đơn lẻ không đủ để xác định thời gian xử lý công việc, tốc độ hoàn thành trong sprint, xu hướng hoặc lịch sử sprint kéo dài nhiều ngày.

Mô tả kết quả đã quan sát và những vướng mắc chưa xử lý, kèm ID task nếu có. Phân biệt điều đã quan sát được với đề xuất cải tiến. Đề xuất một số ít thay đổi quy trình cụ thể và giải thích PM nên thu thập bằng chứng gì ở lần sau để đánh giá chúng.

Khi không có context.tasks, thừa nhận thiếu dữ liệu, không tự khẳng định thành công hoặc thất bại. Không tự đặt ngày tháng, con người, nguyên nhân gốc rễ hoặc các bản phát hành đã được nghiệm thu. Trả nhận xét dưới dạng JSON theo schema của bên gọi; các cải tiến được đề xuất là gợi ý cho PM, không phải lệnh để thực thi.

Nếu có lịch sử quan sát đã lưu, dùng lịch sử đó để nhận xét những vướng mắc còn tồn tại, đã được gỡ hoặc chưa có quan sát mới. Nêu rõ lịch sử này chỉ gồm một phần các quan sát, không phải nhật ký sự kiện đầy đủ. Không dùng lịch sử đó để tính tốc độ hoàn thành trong sprint, thời gian xử lý công việc hoặc suy ra quan hệ nhân quả. Task vắng mặt không phải bằng chứng rằng vướng mắc đã được xử lý.

Gắn mỗi cải tiến quy trình với một task hoặc vướng mắc đã quan sát. Nêu thay đổi được đề xuất và thông tin theo dõi có thể đo lường để PM thu thập, chẳng hạn đã xác nhận bàn giao mã nguồn trước khi giao task kiểm thử hay chưa. Đưa các vướng mắc còn tồn tại và bằng chứng còn thiếu vào thông điệp gửi PM.
