# Skill cho DEV và Scrum Master

Skill nằm trong repo để mỗi máy chạy agent nhận được cùng hướng dẫn. Không cần cài vào thư mục skill cá nhân của Codex. Loader `tools/skills.py` của từng agent chọn skill theo `TaskRequest.action`, không theo đường dẫn do PM gửi.

## Nơi chỉnh prompt, skill và tool

- DEV: `agents/dev/prompt.py` chứa `DEV_SYSTEM_PROMPT` và `build_dev_prompt()` để ghép quy tắc chung, skill đã chọn, schema bàn giao và dữ liệu PM. `agent.py` gọi hàm này trước khi chạy Codex.
- Scrum Master: `agents/scrum_master/prompt.py` chứa `SCRUM_SYSTEM_PROMPT` và `build_scrum_review_prompt()` để ghép quy tắc chung, skill và báo cáo Python. `tools/ai_review.py` gọi hàm này rồi thực hiện kết nối Antigravity và kiểm tra phản hồi.
- Chỉnh quy trình riêng của từng action trong `skills/<tên-skill>/SKILL.md`. Các hàm trong `tools/` vẫn đọc/lưu file, xác minh dữ liệu và xử lý các thao tác cụ thể; `agent.py` điều khiển luồng thực hiện.
- `build_messages()` trong hai file prompt.py vẫn phục vụ action mẫu echo. Prompt chính không được ghép trực tiếp trong agent.py hoặc tools/ai_review.py nữa. Phần điều phối giữa các agent vẫn thuộc PM.

| Agent | Action PM gọi | Skill trong thư mục agent |
| --- | --- | --- |
| DEV | `implement_project` | `skills/dev-implement/SKILL.md` |
| DEV | `fix_bugs` | `skills/dev-fix-bugs/SKILL.md` |
| DEV | `review_code` | `skills/dev-review-code/SKILL.md` |
| DEV | `refactor_code` | `skills/dev-refactor-code/SKILL.md` |
| SCRUM_MASTER | `track_blockers` | `skills/scrum-track-blockers/SKILL.md` |
| SCRUM_MASTER | `run_retrospective` | `skills/scrum-retrospective/SKILL.md` |
| SCRUM_MASTER | `review_module` | `skills/scrum-review-module/SKILL.md` |

Review module được bổ sung từ Contract 1.3.0; xem [SCRUM_MODULE_REVIEW.md](SCRUM_MODULE_REVIEW.md) cho dữ liệu PM cần gửi và điều kiện chuyển module.

## Cách PM sử dụng

PM tiếp tục gửi TaskRequest tới `POST /tasks` kèm Bearer token. Agent tự đọc skill trước khi gọi AI; không cần trường `skill`. Contract 1.2.0 bổ sung hai action DEV vào registry, giữ nguyên cấu trúc TaskRequest/TaskResult và nhận được request 1.1.0. DEV đưa toàn bộ skill và JSON Schema bàn giao vào prompt Codex. Scrum Master đưa skill vào prompt nhận xét Antigravity, còn Python vẫn tính số liệu.

DEV cần `DEV_BACKEND=codex`, `DRY_RUN=false` và CLI đã đăng nhập để AI áp dụng skill. `sample` chỉ hỗ trợ thử đóng gói source cho implement_project; `dry_run` không sinh source. Source PM gửi được ưu tiên. Nếu PM không gửi source, DEV có thể khôi phục bản bàn giao thành công gần nhất của cùng project_id cho cả tạo module tiếp theo, sửa lỗi, review và refactor. Mỗi lần chạy vẫn dùng workspace mới để tránh ảnh hưởng bản lưu. Xem [DEV_LOCAL_SOURCE.md](DEV_LOCAL_SOURCE.md).

Scrum Master cần `SM_BACKEND=antigravity`, `DRY_RUN=false` và CLI `agy` đã đăng nhập để AI áp dụng skill. `rules` vẫn tạo báo cáo Python, không gọi AI. Nếu AI lỗi, báo cáo dùng dữ liệu gốc và metadata phản ánh fallback.

Ví dụ task PM gửi đến Scrum Master:

```json
{
  "contract_version": "1.2.0",
  "task_id": "SM-SKILL-001",
  "project_id": "PROJECT-001",
  "agent_id": "scrum_master-01",
  "role": "SCRUM_MASTER",
  "action": "track_blockers",
  "instruction": "Phân tích blocker và đề xuất bước xử lý cho PM",
  "context": {
    "tasks": [
      {"id": "DEV-01", "status": "COMPLETED"},
      {"id": "TEST-01", "status": "BLOCKED", "blocked_reason": "Chờ source ZIP"}
    ]
  },
  "constraints": {"timeout_seconds": 180}
}
```

`metadata.skill` cho biết skill được chọn. `metadata.skill_applied=true` nghĩa backend AI đã trả kết quả thành công sau khi nhận hướng dẫn; không chứng minh AI tuân thủ mọi hướng dẫn hoặc sản phẩm đã qua kiểm thử. Với `rules`, `sample` hoặc AI fallback, trường này là false. Task bị chặn trước khi gọi AI có thể chưa có metadata skill.

Conductor PM hiện gửi snapshot các bước khác trong `context.tasks` khi chạy bước SCRUM_MASTER. Workflow mặc định vẫn chỉ gọi retrospective ở cuối, không tự theo dõi liên tục. Nếu PM ở máy khác, cần cập nhật cả thay đổi `agents/pm/conductor/orchestrator.py` hoặc tự truyền snapshot tương đương.

Sau khi cập nhật source, khởi động lại API để nạp code mới. Khi gọi thử, dùng task_id mới vì `/tasks` cache kết quả theo task_id. Cấu hình `.env` và token hiện có không bị thay đổi.

## Báo cáo DEV có cấu trúc

Codex phải tạo delivery_report.json theo schema tại `agents/dev/schemas.py`. Agent kiểm tra schema, action, đường dẫn file, vị trí finding và tính nhất quán cơ bản trước khi trả kết quả. Báo cáo thiếu hoặc sai trả FAILED/VALIDATION_ERROR thay vì báo thành công.

- `outputs[0].delivery.scope_status`: COMPLETE, PARTIAL hoặc NEEDS_CONTEXT.
- `acceptance`: ID tiêu chí, trạng thái IMPLEMENTED/PARTIAL/NOT_IMPLEMENTED/UNVERIFIED và bằng chứng.
- `changes`: file thay đổi, lý do, finding_id nếu có.
- `checks`: lệnh, PASS/FAIL/NOT_RUN và bằng chứng do AI báo cáo.
- `findings`: ID, severity, đường dẫn, dòng, mô tả và hướng sửa.
- `unresolved`: công việc hoặc dữ liệu còn thiếu.

implement_project, fix_bugs và refactor_code trả SOURCE_CODE ZIP cùng DOCUMENTATION JSON. review_code chỉ trả DOCUMENTATION; Python so sánh hash trước/sau và từ chối kết quả nếu source hoặc references bị sửa. Review có thể COMPLETE dù có findings: COMPLETE nghĩa đã thực hiện việc review, không phải code đạt nghiệm thu.

PARTIAL/NEEDS_CONTEXT do AI báo cáo trả BLOCKED với artifact bàn giao để PM xem tiếp. Riêng backend sample vẫn COMPLETED cho mục đích thử luồng, nhưng có demo_only=true và scope_status=PARTIAL. Các chỉ số verified=false và evidence_source=ai_self_report nhắc PM phải để Tester/DevOps xác minh độc lập. Kiểm tra schema không chứng minh lệnh kiểm thử đã thực sự được AI chạy.

## PM gọi qua dispatch_task

Ví dụ context của một task gửi tới PM:

```json
{
  "target_agent_id": "dev-01",
  "target_role": "DEV",
  "target_action": "review_code",
  "dispatch_task_id": "DEV-REVIEW-001",
  "target_context": {
    "acceptance_criteria": [{"id": "AC-001", "description": "Todo thêm và xóa được"}]
  }
}
```

Đặt source ArtifactRef trong input_artifacts của TaskRequest gửi PM. PM relay sang DEV trước khi gửi subtask; metadata skill của DEV được giữ trong kết quả PM. Dùng refactor_code với instruction nêu rõ mục tiêu refactor nếu cần chỉnh cấu trúc code. Hai action mới dùng khi PM chủ động dispatch hoặc chỉnh workflow; workflow mặc định không tự thêm bước review/refactor.

## Lịch sử Scrum

`outputs[0].history` chứa new, persistent, resolved, not_observed và snapshot_count. Mỗi blocker có first_seen, last_seen, số lần quan sát và observed_age_seconds; resolved_at ghi lúc snapshot mới xác nhận trạng thái đã gỡ. Nếu task biến mất hoặc trạng thái UNKNOWN, agent giữ not_observed và không tự kết luận đã gỡ.

Lưu tại `agents/scrum_master/data/scrum_history/<sha256-project-id>.json`, cô lập theo project. Dùng cùng project_id và task ID ổn định qua các lần gọi, nhưng task_id của mỗi yêu cầu API phải mới. Conductor gửi ID bước workflow làm task ID ổn định. Đây là lịch sử quan sát gần nhất và các blocker, không phải toàn bộ nhật ký dự án hay bằng chứng thời gian bắt đầu lỗi thực tế. rules và AI fallback đều sử dụng được lịch sử này. Sao lưu thư mục data nếu cần giữ qua lần chuyển máy.

## Cập nhật nhiều máy

Copy source DEV, Scrum, các thư mục skills và contract sang máy tương ứng. Máy PM cũng cần registry mới và thay đổi dispatcher/orchestrator trong bản này. Từ thư mục AGENT chạy `python -m pip install -e ./contract` để metadata package khớp 1.2.0, rồi khởi động lại API. Không cần đổi token hoặc mở thêm cổng.

Nếu cài editable báo `invalid command 'bdist_wheel'`, cài `python -m pip install wheel` trong đúng môi trường Python rồi cài lại contract. Môi trường offline cần wheel từ kho gói nội bộ hoặc file wheel có sẵn. Với bản editable đã cài trước đó, code runtime vẫn đọc source mới và CONTRACT_VERSION=1.2.0 dù metadata pip có thể còn phiên bản cũ.
