# CHANGELOG

Tất cả các thay đổi về Agent Contract sẽ được ghi lại tại tài liệu này.

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
