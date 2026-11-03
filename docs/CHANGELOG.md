# CHANGELOG

Tất cả các thay đổi về Agent Contract sẽ được ghi lại tại tài liệu này.

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
