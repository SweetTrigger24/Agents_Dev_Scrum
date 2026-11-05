# DEV làm tiếp bằng source đã lưu khi PM không gửi được file

Sau task tạo code, sửa lỗi hoặc refactor thành công bằng Codex, DEV lưu con trỏ tới artifact SOURCE_CODE vừa bàn giao, kèm project_id, task_id, agent_id và checksum SHA-256. Lưu tại `agents/dev/data/project_sources/<sha256-project-id>.json`. File ZIP vẫn nằm trong `agents/dev/artifacts/`. Khởi động lại API không làm mất liên kết này; cần giữ cả data và artifacts khi chuyển máy.

## Thứ tự chọn source

1. Dùng source hợp lệ PM cung cấp. Nếu PM gửi ArtifactRef của file source vẫn có tại máy DEV, agent đọc file tại máy mà không cần tải lại ZIP.
2. Nếu PM không gửi SOURCE_CODE, tự khôi phục bản bàn giao thành công gần nhất của đúng project_id.
3. Nếu PM có gửi ArtifactRef nhưng chuyển file thất bại, chỉ dùng bản lưu nếu checksum khớp; nếu không có checksum thì artifact_id và created_by phải khớp. Không tự thay source PM yêu cầu bằng một phiên bản khác.
4. Nếu chưa có source và action là fix_bugs, review_code hoặc refactor_code, trả BLOCKED/MISSING_CONTEXT. Với implement_project lần đầu, cho phép tạo dự án mới; đặt context.continue_project=true nếu yêu cầu bắt buộc làm tiếp trên source đã có, để tránh khởi tạo nhầm khi thiếu source.

Khi đã có bản lưu của dự án, implement_project sẽ đọc và mở rộng mã nguồn hiện tại, giữ các module đã hoàn thành rồi đóng gói source tích hợp. Project khác không được tự lấy bản lưu này. File bị mất, sai checksum hoặc bản lưu bị hỏng sẽ bị chặn thay vì tạo lại ứng dụng từ đầu.

## Ví dụ PM giao module tiếp theo mà không gửi source

```json
{
  "task_id": "DEV-PROJECT-1-MODULE-2",
  "project_id": "PROJECT-1",
  "agent_id": "dev-01",
  "role": "DEV",
  "action": "implement_project",
  "instruction": "Thêm module quản lý người dùng, giữ nguyên module đăng nhập đã làm.",
  "context": {"module_id": "USERS", "continue_project": true},
  "input_artifacts": [],
  "constraints": {"timeout_seconds": 300}
}
```

PM vẫn gửi yêu cầu, kiến trúc, user story hoặc báo cáo lỗi cần thiết qua input_artifacts/context như bình thường. Cơ chế này chỉ thay thế việc chuyển source, không bỏ qua tài liệu khác bị thiếu hoặc sai checksum. Task_id mỗi yêu cầu API cần mới vì kết quả được cache theo task_id.

## Kiểm tra nguồn đã dùng

Trong TaskResult.metadata:

- project_id: dự án hiện tại.
- source_input.origin: pm_relay, local_artifact, local_project_cache hoặc new_project.
- source_input.artifact_id và checksum: phiên bản đầu vào đã chọn, nếu có source.
- source_input.source_task_id: task tạo bản lưu khi dùng local_project_cache.
- source_checkpoint_saved=true: đã lưu source mới để làm tiếp ở lần sau.

Task thất bại, báo cáo PARTIAL/NEEDS_CONTEXT, backend sample và review_code không thay thế bản source bàn giao thành công gần nhất. Tạo source xong vẫn cần Tester xác minh; bản lưu không đồng nghĩa đã nghiệm thu hoặc triển khai thành công.

Các artifact cũ được tạo trước khi có liên kết project_id không được tự đoán thuộc dự án nào. PM có thể gửi ArtifactRef của đúng source cũ đã nằm tại DEV, không cần upload lại; sau task thành công, source mới sẽ được gắn với project_id và dùng tự động về sau.

## Khi dùng PM Conductor

Nếu lỗi tải hoặc upload SOURCE_CODE tới DEV, dispatcher vẫn gửi ArtifactRef chính xác trong TaskRequest để DEV tự xác minh bản tại máy. Nếu DEV không có bản phù hợp, task vẫn BLOCKED. Lỗi checksum khi tải artifact, lỗi chuyển tài liệu khác và lỗi chuyển source tới agent khác vẫn chặn luồng. Nếu workflow PM riêng dừng trước khi gửi TaskRequest cho DEV, cần cập nhật dispatcher hoặc tiếp tục gọi DEV với metadata tương ứng để sử dụng cơ chế này.

Thay đổi dùng nguyên Contract 1.3.0 và cấu hình hiện có. Khởi động lại API DEV và cập nhật dispatcher trên máy PM để áp dụng.
