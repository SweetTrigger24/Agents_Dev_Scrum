1. Hiện tại hệ thống đã có gì?

Hệ thống monorepo đã hoàn thiện toàn bộ nền tảng cốt lõi cho giai đoạn phát triển Agent độc lập:

Gói Contract dùng chung (contract/):

Cài đặt dạng module chuẩn qua pip install -e ./contract (agent_contract==1.0.0).
Định nghĩa 6 Enum thống nhất (AgentRole, AgentStatus, TaskStatus, Priority, ArtifactType, ErrorCode).
8 Data Model Pydantic v2 chuẩn: AgentIdentity, AgentState, ArtifactRef, Constraints, TaskRequest, AgentError, NextAction, TaskResult.
CAPABILITY_REGISTRY cho toàn bộ 10 vai trò và ACTION_MAP hoàn chỉnh cho PM và DevOps.
Bộ validator tự động bắt lỗi: trạng thái COMPLETED không được có lỗi, FAILED/BLOCKED bắt buộc có lỗi, URI tương đối, regex agent_id, v.v.
Đã xuất 8 file JSON Schema chuẩn tại contract/schemas/.

Agent Template chuẩn mẫu (agent-template/):

Khung kiến trúc chuẩn để 4 người còn lại clone và triển khai 8 vai trò khác.
BaseAgent với decorator @action("tên_action", output_model=...), tự động kiểm tra quyền hạn, quản lý vòng đời Task, bắt toàn bộ ngoại lệ và trả về TaskResult(error=AgentError).
LLMClient OpenAI-compatible hỗ trợ 5 providers (Groq, Gemini, OpenRouter, Ollama, OpenAI), tự động trích xuất JSON, tự sửa lỗi schema qua cơ chế retry.
tools/artifact.py: Quản lý artifact, băm SHA256, ghi index.json, chống path traversal và cô lập thư mục inbox/.
Hỗ trợ cả giao diện dòng lệnh cli.py và REST API qua FastAPI api.py.

2 Agent nghiệp vụ hoàn chỉnh:

PM Agent (agents/pm/): ID pm-01, 4 capability, 6 action (analyze_requirement, create_plan, decompose_tasks, assign_tasks, track_progress, report_status). Có công cụ quản lý task (tasks.json), sinh kế hoạch (plan.md), backlog và báo cáo tiến độ.
DevOps Agent (agents/devops/): ID devops-01, 6 capability, 7 action (git_operation, build_image, generate_ci_config, run_tests, deploy, health_check, setup_monitoring). Có lớp thực thi an toàn duy nhất TerminalExecutor (whitelist lệnh, không dùng shell, chặn rm -rf, chặn deploy prod, che giấu secret trong log, chế độ dry_run mặc định).

Hạ tầng điều phối cục bộ (scripts/run_local.py):

Quản lý khởi động nhiều agent thành các tiến trình độc lập theo cấu hình scripts/local_agents.yaml.
Kiểm tra pre-flight cổng mạng, ghi log riêng từng agent ra logs/<agent>.log, kiểm tra sức khỏe qua endpoint GET /health trong 15s.
Lệnh điều khiển trực quan: up, status, down.
Bảng phân bổ endpoint cho toàn bộ nhóm tại docs/AGENT_ENDPOINTS.md.

Bộ kiểm thử Contract tự động (tools/validate_agent.py):

Kiểm tra tự động 13 tiêu chí Contract v1.0 và tính cô lập (cấu trúc file, biến môi trường, bảo vệ secret, không hardcode path, timezone-aware datetime, AST isolation không import chéo, port duy nhất, ghim version requirements, URI tương đối, gitignore cô lập, kiểm tra mock task và error handling).
Tự động xuất báo cáo chuẩn tại docs/validation-report.md.

Chất lượng kiểm thử:

Toàn bộ 79 unit tests chạy offline (mock 100%, không tốn API key, không phụ thuộc mạng) đều xanh.
2. Hệ thống hiện tại có thể làm được gì?
Chạy cụm Agent đồng thời: Chỉ với lệnh python scripts/run_local.py up, PM Agent (port 8001) và DevOps Agent (port 8002) sẽ cùng khởi động thành 2 dịch vụ mạng độc lập, sẵn sàng nhận request.
Thực thi nghiệp vụ PM: Gửi TaskRequest dạng JSON tới PM Agent qua REST API (POST http://localhost:8001/tasks) hoặc CLI -> PM Agent sẽ phân tích yêu cầu, chia sprint, sinh kế hoạch plan.md, phân rã các task và lưu vào artifacts/tasks.json, đồng thời gợi ý bước tiếp theo cho vai trò BA/PO.
Thực thi nghiệp vụ DevOps: Gửi TaskRequest tới DevOps Agent (POST http://localhost:8002/tasks) -> DevOps Agent sinh cấu hình GitHub Actions / Dockerfile, sinh kế hoạch lệnh (kèm rollback_plan), kiểm tra an toàn theo whitelist và chạy thử ở chế độ dry-run hoặc chạy thực thi an toàn.
Tự động chấm điểm Contract cho Agent mới: Bất kỳ ai khi code xong một agent mới (ví dụ agents/ba, agents/dev) chỉ cần chạy python tools/validate_agent.py để biết ngay agent đó có đạt chuẩn hay vi phạm quy tắc chung (báo lỗi cụ thể từng dòng code).
3. Cần làm gì tiếp theo?

Theo đúng lộ trình trong kế hoạch (từ Phase 5 đến Phase 7):

Thử nghiệm với LLM thật (Phase 5):
Cung cấp API Key thật (ví dụ: Groq API Key miễn phí hoặc Gemini API Key) vào file .env của agents/pm/ và agents/devops/.
Chạy script demo thực tế (python agents/pm/demo.py và python agents/devops/demo.py) để đánh giá chất lượng phản hồi bằng tiếng Việt và khả năng tự sửa JSON của model thật.
Bàn giao cho 4 kỹ sư còn lại trong nhóm (Phase 2 & Phase 6):
Gửi gói contract/ và agent-template/ cho 4 thành viên còn lại trên 4 máy khác.
Hướng dẫn họ clone template để dựng 8 vai trò còn lại (BA, SA, PO, DEV, TESTER, DBA, SCRUM_MASTER, SECURITY).
Họ sẽ điền host/port của máy họ vào docs/AGENT_ENDPOINTS.md.
Cập nhật ACTION_MAP cho 8 Agent còn lại:
Khi các thành viên gửi danh sách action của vai trò họ, cập nhật bổ sung vào ACTION_MAP trong contract/agent_contract/registry.py và chạy script xuất lại JSON Schema.
Đóng băng Contract v1.0.0 (Phase 7 - Freeze):
Sau khi rà soát toàn bộ 10 agent bằng tools/validate_agent.py và đạt 100% PASS, thực hiện gắn tag git contract-v1.0.0 để chốt hạ giao thức trước khi bước sang giai đoạn tiếp theo (xây dựng Orchestrator và giao tiếp liên Agent).