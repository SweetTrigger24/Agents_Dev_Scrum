# Review module trước khi chuyển sang module tiếp theo

Action `review_module` thuộc capability `scrum_management`, dùng Agent API `/tasks` và Contract 1.3.0. Agent tự nạp skill tiếng Việt `agents/scrum_master/skills/scrum-review-module/SKILL.md`. Các action theo dõi blocker và retrospective vẫn dùng riêng.

## PM gửi gì?

1. `context.module_id`: ID module đang review.
2. `context.tasks`: snapshot không rỗng, chỉ gồm công việc của module đó. Mỗi task có ID ổn định và status; có thể thêm module_id và blocked_reason. Nếu có module_id khác module đang review, agent từ chối dữ liệu.
3. `context.acceptance_criteria`: danh sách không rỗng, mỗi mục có id duy nhất, description, status PASS/FAIL/UNVERIFIED và evidence. PM gửi toàn bộ tiêu chí cần nghiệm thu; Scrum không tự suy ra tiêu chí bị PM bỏ sót.
4. Đúng một artifact SOURCE_CODE ZIP hiện tại và đúng một TEST_REPORT của module. PM relay file vào inbox của Scrum trước khi gọi `/tasks`, kèm ArtifactRef thực tế và checksum nếu có.

Ví dụ TaskRequest tại `agents/scrum_master/examples/review_module.json`. Thay các ArtifactRef minh họa bằng metadata thật do DEV và Tester trả về; file ví dụ không tự tạo hoặc gửi source/test report. Các tệp đầu vào nằm trong `artifacts/inbox/<created_by>/` của Scrum.

TEST_REPORT dạng JSON cần chứa verdict và có thể chứa findings:

```json
{"verdict": "PASS", "findings": []}
```

Nếu báo cáo là Markdown hoặc văn bản, PM gửi thêm `context.test_result` gắn đúng artifact_id của TEST_REPORT, kèm bằng chứng:

```json
{
  "artifact_id": "ART-TEST-001",
  "verdict": "PASS",
  "evidence": "Báo cáo test-report.md: hai trường hợp đăng nhập hợp lệ và mật khẩu sai đều đạt"
}
```

Agent ghi rõ đây là kết quả do PM cung cấp. Với TEST_REPORT JSON có verdict hợp lệ, verdict trong file được ưu tiên; context không được ghi đè. Finding HIGH/CRITICAL trong file cũng chặn chuyển tiếp, kể cả verdict là PASS.

## Scrum trả gì?

- Artifact DOCUMENTATION: `artifacts/scrum_module_review_<task_id>.md`.
- `outputs[0].review_type = module_review` và module_id để phân biệt với retrospective.
- `outputs[0].verdict`: PASS nếu đủ bằng chứng và đạt; FAIL nếu có công việc/tiêu chí/test chưa đạt; BLOCKED nếu thiếu dữ liệu và chưa ghi nhận điều kiện FAIL.
- `outputs[0].can_start_next_module`: chỉ true khi PASS.
- missing_inputs, reasons, acceptance_criteria, test_result, blockers và input_evidence để PM biết cần xử lý gì.

PASS trả TaskStatus COMPLETED. FAIL hoặc BLOCKED đều trả TaskStatus BLOCKED kèm AgentError không tự retry và báo cáo review. Dữ liệu sai định dạng trả FAILED/INVALID_INPUT. Artifact được khai báo nhưng chưa relay hoặc sai checksum bị kiểm tra đầu vào của BaseAgent chặn trước handler, nên trường hợp đó có thể chưa có báo cáo review.

Ở backend rules, báo cáo vẫn đầy đủ kết luận dựa trên quy tắc. Antigravity chỉ thêm nhận xét nếu đã đủ đầu vào; khi AI lỗi, giữ nguyên kết luận và ghi metadata.ai_status=fallback. Thiếu dữ liệu thiết yếu thì bỏ qua lượt gọi AI. Scrum đối chiếu bằng chứng PM cung cấp, không chạy source hoặc thay thế kiểm thử kỹ thuật.

## Thứ tự gọi bên PM

Sau khi DEV bàn giao source và Tester có báo cáo cho module, PM gọi `review_module`. Chỉ giao module kế tiếp khi nhận COMPLETED, đúng module_id, artifact DOCUMENTATION tồn tại và can_start_next_module=true. Nếu chưa đạt, PM giao sửa lỗi hoặc bổ sung bằng chứng rồi review lại với task_id mới. Kết quả API được cache theo task_id.

PM có thể gọi trực tiếp Scrum hoặc dùng `dispatch_task` với target_role=SCRUM_MASTER, target_action=review_module, target_context chứa dữ liệu trên và input_artifacts chứa source/test report. Dispatcher hiện có sẽ relay artifact và giữ output/metadata của Scrum. Cập nhật contract/registry trên máy PM để nhận action mới.

Conductor trong bản này chặn ngay bước review_module nếu kết quả không đủ COMPLETED + verdict PASS + can_start_next_module=true + module_id khớp + ArtifactRef DOCUMENTATION. Báo cáo của kết quả bị chặn vẫn được lưu trong project state. PM không tự tạo bằng chứng nghiệm thu còn thiếu từ brief hoặc tự retry review này. Dispatcher gọi thủ công chỉ chuyển tiếp kết quả; luồng điều phối bên gọi cần kiểm tra điều kiện tương tự.

Workflow mặc định hiện không chia module, nên không tự thêm vòng lặp hoặc gọi review_module giữa các module. Bên PM cần đặt lời gọi này tại ranh giới module của workflow riêng. Nếu dùng YAML của Conductor, context.tasks của review_module được giữ nguyên để PM cung cấp đúng phạm vi; không bị thay bằng snapshot toàn dự án. Không áp dụng kết luận PASS của một module cho việc nghiệm thu toàn bộ dự án.
