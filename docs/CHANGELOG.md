# CHANGELOG

Tất cả các thay đổi về Agent Contract sẽ được ghi lại tại tài liệu này.

## [DEV local source] - 2026-11-05
- DEV lưu source bàn giao thành công theo project_id và tự khôi phục khi PM không gửi source, giữ nguyên Contract 1.3.0.
- Ưu tiên source PM gửi; không bỏ qua checksum, không lấy bản của dự án khác và không dùng task lỗi/partial/sample làm bản lưu mới.
- Dispatcher cho DEV tự xác minh bản tại máy khi lỗi chuyển SOURCE_CODE; giữ kiểm tra lỗi checksum và các artifact khác.

## [1.3.0] - 2026-11-05
- Đăng ký SCRUM_MASTER review_module vào capability scrum_management, giữ nguyên cấu trúc TaskRequest/TaskResult và các action cũ.
- Báo cáo DOCUMENTATION riêng cho mỗi lần review module; đối chiếu snapshot task, tiêu chí nghiệm thu, SOURCE_CODE và TEST_REPORT. Chỉ trả COMPLETED/can_start_next_module=true khi đủ điều kiện; thiếu dữ liệu hoặc chưa đạt trả BLOCKED.
- Bổ sung skill tiếng Việt scrum-review-module, ví dụ TaskRequest và hướng dẫn tích hợp bên PM. AI chỉ nhận xét, không thay đổi kết luận Python.
- Conductor giữ context.tasks riêng cho review_module, không đưa task của các module khác vào snapshot này.
- Conductor kiểm tra kết luận PASS, module_id, can_start_next_module và artifact DOCUMENTATION trước khi cho bước review module hoàn tất; không tự điền bằng chứng còn thiếu từ brief.

## [1.2.0] - 2026-11-05
- Bổ sung DEV review_code/code_review và refactor_code/refactoring, tương thích các action cũ; giữ nguyên cấu trúc TaskRequest/TaskResult.
- DEV nạp skill theo action, yêu cầu báo cáo JSON có acceptance/checks/findings, kiểm tra đầu ra và giữ verified=false cho bằng chứng AI tự báo cáo.
- Scrum lưu lịch sử quan sát blocker theo project; không xem task vắng mặt là đã gỡ blocker.
- PM dispatch relay input_artifacts, giữ metadata skill và áp timeout của request; Conductor gửi ID bước ổn định trong snapshot Scrum.
- Đồng bộ version package và schema mặc định thành 1.2.0. Request phiên bản cũ vẫn dùng được.

## [1.1.0] - 2026-11-03
### Nâng cấp Contract v1.1.0 (Prompt 8 - PM Conductor)
- Nâng `CONTRACT_VERSION` từ `"1.0.0"` lên `"1.1.0"`. `CONTRACT_MIN_VERSION` của các agent giữ nguyên `"1.0.0"`.
- Bổ sung capabilities cho PM: `task_dispatch`, `workflow_orchestration`.
- Bổ sung actions cho PM: `start_project`, `resume_project`, `get_project_state` (workflow_orchestration) và `dispatch_task` (task_dispatch).
- Đăng ký toàn bộ pipeline actions ở Bảng 2.9 vào `ACTION_MAP` và `CAPABILITY_REGISTRY` cho toàn bộ 10 Agent roles.
- Bổ sung mục 2.9 "Pipeline actions" vào `docs/CONTRACT.md`:
  - Quy ước verdict: `outputs[0]` của TESTER, SECURITY và PO có cấu trúc `{"verdict": "PASS" | "FAIL", "findings": [...]}`.
  - Quy ước `SOURCE_CODE`: chuyển giao qua file nén `.zip`.
- Tăng giới hạn `MAX_UPLOAD_MB` mặc định lên 50MB.
- Ngoại lệ điều phối: Cho phép duy nhất PM import module `conductor` và gọi HTTP tới các agent khác. Các agent khác vẫn bị nghiêm cấm giao tiếp ngang hàng.

## [1.0.0] - 2026-11-03
### Bổ sung Agent API v1 (Prompt 7)
- Thêm mục 2.8 "Agent API v1" vào `docs/CONTRACT.md`:
  - Chuẩn hóa các endpoint HTTP: `/health`, `/agent`, `/state`, `/tasks`, `/tasks/{task_id}`, `/artifacts`, `/artifacts/{id}/content`, `/artifacts/inbox`.
  - Cơ chế xác thực Bearer Token qua header `Authorization: Bearer <AGENT_API_KEY>` (ngoại trừ `/health`).
  - Thêm `AGENT_API_KEY`, `MAX_UPLOAD_MB` vào cấu hình `.env.example`.
  - Không đổi schema Pydantic nên không tăng `CONTRACT_VERSION` (vẫn giữ 1.0.0).

## [1.0.0] - 2026-11-02
### Cập nhật cấu hình môi trường
- thêm HOST, PORT, CONTRACT_MIN_VERSION; không đổi schema nên không tăng CONTRACT_VERSION.

### Khởi tạo ban đầu
- Định nghĩa các Enum: `AgentRole`, `AgentStatus`, `TaskStatus`, `Priority`, `ArtifactType`, `ErrorCode`.
- Định nghĩa các Model chuẩn (Pydantic v2): `AgentIdentity`, `AgentState`, `ArtifactRef`, `Constraints`, `TaskRequest`, `AgentError`, `NextAction`, `TaskResult`.
- Thiết lập `CAPABILITY_REGISTRY` cho 10 roles và `ACTION_MAP` cho PM & DevOps (8 roles còn lại để trống chờ bổ sung).
- Ràng buộc validator:
  - `status == COMPLETED` -> `error` bắt buộc là `None`.
  - `status in (FAILED, BLOCKED)` -> `error` bắt buộc phải có.
  - `status == CANCELLED` -> `error` tùy chọn (`None` hoặc `AgentError`).
  - `uri` artifact là tương đối và không chứa `..`.
  - `agent_id` regex `^[a-z_]+-\d{2}$`.
  - `capabilities` là tập con của `CAPABILITY_REGISTRY[role]`.
- Cung cấp các hàm tiện ích: `make_error`, `failed_result`, `blocked_result`.
- Hỗ trợ công cụ xuất schema `python -m agent_contract.export_schemas`.
