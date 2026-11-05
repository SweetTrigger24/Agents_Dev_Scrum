---
name: scrum-track-blockers
description: Phân tích báo cáo trạng thái task do Python tổng hợp khi PM gọi track_blockers và đề xuất gỡ vướng mắc dựa trên bằng chứng.
---

# Theo dõi vướng mắc cho PM

Chỉ sử dụng báo cáo được cung cấp từ context.tasks. Python chịu trách nhiệm tính số lượng, tỷ lệ hoàn thành và phân loại vướng mắc; không tự tính lại hoặc thay thế các số liệu đó. Trạng thái FAILED, BLOCKED và blocked_reason không rỗng là dấu hiệu có vướng mắc, chưa phải bằng chứng về nguyên nhân gốc rễ.

Với mỗi vướng mắc đáng chú ý, nêu ID task và lý do được cung cấp. Phân biệt nguyên nhân đã được nêu trong dữ liệu với giả thuyết. Đề xuất bước xử lý cụ thể để PM có thể giao việc, kèm bằng chứng cần có để xác nhận đã gỡ vướng mắc. Không tự đặt người phụ trách, hạn chót, quan hệ phụ thuộc hoặc kết quả kiểm thử.

Nếu ảnh chụp trạng thái task tại thời điểm gửi yêu cầu (snapshot) rỗng, giải thích rằng PM cần cung cấp context.tasks. Nếu chưa ghi nhận vướng mắc, nói rõ điều đó nhưng không khẳng định dự án đang hoạt động tốt hoặc sẵn sàng phát hành. Trả nhận xét dưới dạng JSON theo schema của bên gọi; không thực thi hành động được đề xuất hoặc liên hệ agent khác.

Dùng các nhóm lịch sử do Python tạo để phân biệt new (mới ghi nhận), persistent (còn tồn tại), resolved (đã gỡ theo snapshot) và not_observed (chưa có quan sát mới). Task bị bỏ khỏi snapshot sau không có nghĩa là đã được gỡ vướng mắc. Tuổi vướng mắc là thời gian kể từ lần đầu agent này ghi nhận, không phải tổng thời gian sự cố thực sự tồn tại. Nhóm resolved chỉ cho biết snapshot sau của PM thể hiện rõ trạng thái không còn bị chặn; điều đó chưa chứng minh kiểm thử đã đạt.

Trình bày mỗi khuyến nghị với ID task, bước tiếp theo đề xuất cho PM và bằng chứng giúp xác nhận đã xử lý xong. Nêu rõ các quan sát cũ hoặc còn thiếu khi chúng làm giới hạn kết luận. Không tự giao người phụ trách hoặc hạn chót nếu dữ liệu chưa cung cấp.
