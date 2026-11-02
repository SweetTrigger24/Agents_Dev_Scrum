# Kế hoạch xây dựng 10 Agent độc lập + Agent Contract v1.0

*Tài liệu giao việc cho Antigravity. Phạm vi: chỉ làm Agent và Protocol, chưa làm Orchestrator, Dashboard, LangGraph. Cập nhật: 02/11/2026.*

## 1. Mục tiêu và phạm vi

**Làm trong giai đoạn này**

- Một gói **Contract dùng chung** (Pydantic) mà cả 10 agent import, không ai tự định nghĩa lại.
- Một **Agent Template** để 5 người clone, mỗi người chỉ viết phần riêng của agent mình (prompt, capability, tool, output schema).
- **PM Agent** và **DevOps Agent** hoàn chỉnh (phần của bạn).
- Bộ kiểm tra **Contract Validation** để rà agent của 4 người còn lại.

**Chưa làm**: Orchestrator, Agent Registry, Dashboard, LangGraph, giao tiếp agent-với-agent.

**Điểm điều chỉnh so với kế hoạch tham khảo**

| Vấn đề | Kế hoạch tham khảo | Đề xuất ở đây | Lý do |
| --- | --- | --- | --- |
| Nơi đặt `schemas.py` | Mỗi agent có một file riêng | Một gói `agent_contract` dùng chung, mỗi agent chỉ thêm schema *đầu ra riêng* | Mỗi người tự copy schema sẽ lệch nhau sau 1 tuần |
| Trường lỗi | Có cả `errors: []` và `error: {}` | Chỉ một `error` (đối tượng hoặc null) | Tránh hai cách trả lỗi |
| Hai loại status | Trộn Task status và Agent status | Tách `TaskStatus` và `AgentStatus` | Dashboard sau này đọc hai thứ khác nhau |
| Chạy lệnh của DevOps | Whitelist lệnh | Whitelist + không dùng shell + `dry_run` mặc định | An toàn hơn khi dùng LLM miễn phí khó đoán |
| LLM miễn phí không đảm bảo JSON | Chưa nói | Parse + validate + tự retry kèm thông báo lỗi | Model miễn phí hay trả JSON hỏng |
| Cấu trúc repo | Mỗi agent một thư mục riêng | Monorepo: `contract/` + `agent-template/` + `agents/<role>/` | Một repo để 5 máy cùng `git pull` |

## 2. Agent Contract v1.0

> Đây là phần cần thống nhất với 4 người còn lại trước tiên. Sau khi **freeze** (Phase 7) chỉ được sửa bằng cách tăng version.

### 2.1 Enum thống nhất

| Enum | Giá trị |
| --- | --- |
| `AgentRole` | `PM`, `SA`, `BA`, `PO`, `DEV`, `TESTER`, `DEVOPS`, `DBA`, `SCRUM_MASTER`, `SECURITY` |
| `AgentStatus` | `OFFLINE`, `IDLE`, `RUNNING`, `WAITING`, `COMPLETED`, `FAILED`, `BLOCKED` |
| `TaskStatus` | `PENDING`, `RUNNING`, `COMPLETED`, `FAILED`, `BLOCKED`, `CANCELLED` |
| `Priority` | `LOW`, `MEDIUM`, `HIGH`, `CRITICAL` |
| `ArtifactType` | `REQUIREMENT`, `USER_STORY`, `ARCHITECTURE`, `DATABASE_SCHEMA`, `SOURCE_CODE`, `TEST_CASE`, `TEST_REPORT`, `SECURITY_REPORT`, `DEPLOYMENT`, `DOCUMENTATION`, `PLAN`, `BACKLOG`, `OTHER` |
| `ErrorCode` | `INVALID_INPUT`, `MISSING_CONTEXT`, `LLM_ERROR`, `TOOL_ERROR`, `TIMEOUT`, `PERMISSION_DENIED`, `ARTIFACT_ERROR`, `VALIDATION_ERROR`, `UNKNOWN_ERROR` |

Ghi chú: `PLAN`, `BACKLOG`, `OTHER` là phần bổ sung so với danh sách gốc, vì PM và PO cần xuất kế hoạch và backlog.

### 2.2 Các model (rút gọn, Antigravity sẽ viết bản đầy đủ)

```python
CONTRACT_VERSION = "1.0.0"

class AgentIdentity(BaseModel):          # Agent tự khai báo
    contract_version: str = CONTRACT_VERSION
    agent_id: str                         # dạng pm-01, devops-01 (regex ^[a-z_]+-\d{2}$)
    role: AgentRole
    name: str
    version: str                          # version của agent
    capabilities: list[str]               # phải nằm trong CAPABILITY_REGISTRY[role]
    status: AgentStatus = AgentStatus.IDLE

class AgentState(BaseModel):             # Dashboard sau này đọc cái này
    agent_id: str
    role: AgentRole
    status: AgentStatus
    current_task: str | None = None
    updated_at: datetime

class ArtifactRef(BaseModel):
    artifact_id: str                      # ART-001
    name: str
    type: ArtifactType
    version: str = "1.0"
    uri: str                              # đường dẫn tương đối, ví dụ artifacts/requirements.md
    created_by: str                       # agent_id
    created_at: datetime
    checksum: str | None = None           # sha256, để phát hiện file bị sửa

class Constraints(BaseModel):
    deadline: datetime | None = None
    priority: Priority = Priority.MEDIUM
    timeout_seconds: int = 300

class TaskRequest(BaseModel):
    contract_version: str = CONTRACT_VERSION
    task_id: str                          # TASK-001
    project_id: str
    agent_id: str
    role: AgentRole
    action: str                           # phải nằm trong danh sách action của role
    instruction: str
    context: dict = {}
    input_artifacts: list[ArtifactRef] = []
    constraints: Constraints = Constraints()

class AgentError(BaseModel):
    code: ErrorCode
    message: str
    retryable: bool
    details: dict = {}

class NextAction(BaseModel):              # gợi ý, KHÔNG phải lệnh gọi agent khác
    suggested_role: AgentRole
    action: str
    reason: str

class TaskResult(BaseModel):
    contract_version: str = CONTRACT_VERSION
    task_id: str
    agent_id: str
    status: TaskStatus                    # kết thúc: COMPLETED | FAILED | BLOCKED | CANCELLED
    summary: str
    outputs: list[dict] = []              # dữ liệu có cấu trúc, schema riêng từng action
    artifacts: list[ArtifactRef] = []
    next_actions: list[NextAction] = []
    error: AgentError | None = None       # bắt buộc có khi FAILED/BLOCKED, null khi COMPLETED
    metadata: dict = {}                   # model, provider, token, duration_ms, dry_run...
```

**Ràng buộc validate (viết bằng `model_validator`)**

- `status == COMPLETED` thì `error` phải là `None`; `FAILED`/`BLOCKED` thì `error` bắt buộc có.
- `TaskRequest.role` phải khớp role của agent nhận.
- `AgentIdentity.capabilities` phải là tập con của `CAPABILITY_REGISTRY[role]`.
- `ArtifactRef.uri` phải là đường dẫn tương đối và không chứa `..`.

### 2.3 Capability Registry và Action Map

Mỗi `action` ánh xạ về đúng một `capability`. Agent nhận action không thuộc capability của mình thì trả `FAILED` + `PERMISSION_DENIED`, `retryable=false`.

| Role | Capabilities |
| --- | --- |
| PM | `project_planning`, `task_decomposition`, `task_assignment`, `progress_tracking` |
| BA | `requirement_analysis`, `user_story`, `use_case`, `acceptance_criteria` |
| SA | `system_architecture`, `api_design`, `technology_selection` |
| DBA | `database_design`, `schema_design`, `sql`, `query_optimization` |
| DEV | `coding`, `refactoring`, `bug_fixing`, `code_review` |
| TESTER | `test_planning`, `test_case_generation`, `automated_testing`, `bug_reporting` |
| DEVOPS | `git`, `docker`, `ci_cd`, `deployment`, `monitoring`, `health_check` |
| SECURITY | `security_analysis`, `vulnerability_scan`, `dependency_scan`, `security_review` |
| PO | `product_vision`, `feature_prioritization`, `backlog_management`, `acceptance` |
| SCRUM\_MASTER | `sprint_management`, `scrum_management`, `blocker_tracking`, `retrospective` |

**Action của PM**

| Action | Capability |
| --- | --- |
| `analyze_requirement` | `project_planning` |
| `create_plan` | `project_planning` |
| `decompose_tasks` | `task_decomposition` |
| `assign_tasks` | `task_assignment` |
| `track_progress` | `progress_tracking` |
| `report_status` | `progress_tracking` |

**Action của DevOps**

| Action | Capability |
| --- | --- |
| `git_operation` | `git` |
| `build_image` | `docker` |
| `generate_ci_config` | `ci_cd` |
| `run_tests` | `ci_cd` |
| `deploy` | `deployment` |
| `health_check` | `health_check` |
| `setup_monitoring` | `monitoring` |

*4 người còn lại tự định nghĩa action cho role của mình theo cùng dạng bảng này, rồi gửi để bạn duyệt và gộp vào registry.*

### 2.4 Ví dụ JSON chuẩn

**TaskRequest**

```json
{
  "contract_version": "1.0.0",
  "task_id": "TASK-001",
  "project_id": "PROJECT-001",
  "agent_id": "pm-01",
  "role": "PM",
  "action": "create_plan",
  "instruction": "Lập kế hoạch 6 sprint cho web bán hàng, 5 người, 3 tháng",
  "context": {"team_size": 5, "duration_weeks": 12},
  "input_artifacts": [],
  "constraints": {"deadline": null, "priority": "HIGH", "timeout_seconds": 300}
}
```

**TaskResult (thành công)**

```json
{
  "contract_version": "1.0.0",
  "task_id": "TASK-001",
  "agent_id": "pm-01",
  "status": "COMPLETED",
  "summary": "Đã tạo kế hoạch 6 sprint gồm 4 milestone",
  "outputs": [{"milestones": 4, "sprints": 6}],
  "artifacts": [{"artifact_id": "ART-001", "name": "plan.md", "type": "PLAN", "version": "1.0", "uri": "artifacts/plan.md", "created_by": "pm-01", "created_at": "2026-11-02T09:00:00Z", "checksum": null}],
  "next_actions": [{"suggested_role": "BA", "action": "analyze_requirement", "reason": "Cần chi tiết hóa yêu cầu cho sprint 1"}],
  "error": null,
  "metadata": {"provider": "groq", "model": "llama-3.3-70b-versatile", "duration_ms": 4200}
}
```

**TaskResult (lỗi)**

```json
{
  "contract_version": "1.0.0",
  "task_id": "TASK-002",
  "agent_id": "devops-01",
  "status": "FAILED",
  "summary": "Build Docker image thất bại",
  "outputs": [], "artifacts": [], "next_actions": [],
  "error": {"code": "TOOL_ERROR", "message": "docker build exit code 1", "retryable": true, "details": {"stderr_tail": "..."}},
  "metadata": {}
}
```

**Quy tắc retry cho Orchestrator sau này**: `FAILED` + `retryable=true` → thử lại; `retryable=false` → `BLOCKED` → chuyển cho người.

### 2.5 Quy ước Artifact

- Ghi file vào thư mục `artifacts/` của agent; mỗi file có một `ArtifactRef` ghi trong `artifacts/index.json`.
- Tên `artifact_id` tăng dần theo từng agent (`ART-001`...); khi ghép hệ thống sẽ thêm tiền tố project.
- Sửa nội dung thì tạo version mới (`1.1`), không ghi đè version cũ.
- Luồng artifact dự kiến: BA `requirements.md` → SA `architecture.md` → DBA `database.sql` → DEV source code → TESTER `test-report.md` → SECURITY `security-report.md` → DEVOPS `deployment-report.md`.

### 2.6 Cấu hình LLM chung (`.env.example`)

```
AGENT_ID=pm-01
AGENT_ROLE=PM
LLM_PROVIDER=groq            # groq | gemini | openrouter | ollama | openai | custom
LLM_MODEL=llama-3.3-70b-versatile
LLM_API_KEY=
LLM_BASE_URL=                # để trống thì lấy theo preset của provider
LLM_TEMPERATURE=0.2
LLM_TIMEOUT_SECONDS=60
LLM_MAX_RETRIES=2
ARTIFACT_DIR=./artifacts
WORKSPACE_DIR=./workspace    # thư mục làm việc giới hạn cho DevOps
ALLOWED_COMMANDS=git,docker,pytest,npm,mvn,python
DRY_RUN=true
```

Preset `base_url` nằm trong code (`llm.py` của template): Groq `https://api.groq.com/openai/v1`, Gemini `https://generativelanguage.googleapis.com/v1beta/openai/`, OpenRouter `https://openrouter.ai/api/v1`, Ollama `http://localhost:11434/v1`. Tên model và hạn mức miễn phí đổi thường xuyên, nên chỉ để trong `.env`, không hard-code.

### 2.7 Quy tắc cho cả nhóm

1. Mọi agent tuân theo Contract v1.0, I/O dùng Pydantic từ gói `agent_contract`.
2. Không tự sửa protocol; muốn đổi phải tạo issue và tăng version.
3. Không hard-code API key hay LLM provider; không commit `.env`.
4. Agent chỉ làm action thuộc capability đã khai báo.
5. Agent **không gọi agent khác**; chỉ gợi ý qua `next_actions`.
6. Mọi lỗi trả về `AgentError`; agent không được ném exception ra ngoài `handle()`.
7. Mỗi agent có unit test, README, `.env.example`, demo script.

## 3. Cấu trúc repo

```
ai-team/
├── README.md                    # quy tắc nhóm + link tài liệu tham khảo
├── docs/
│   ├── CONTRACT.md              # copy mục 2 của tài liệu này
│   └── CHANGELOG.md             # ghi mọi thay đổi contract
├── contract/                    # gói pip dùng chung (pip install -e ./contract)
│   ├── pyproject.toml
│   ├── agent_contract/
│   │   ├── __init__.py
│   │   ├── enums.py
│   │   ├── models.py
│   │   ├── registry.py          # CAPABILITY_REGISTRY, ACTION_MAP
│   │   └── validators.py
│   ├── schemas/                 # JSON Schema xuất ra từ Pydantic
│   └── tests/
├── agent-template/
│   ├── agent.py                 # lớp BaseAgent: handle(TaskRequest) -> TaskResult
│   ├── config.py                # đọc .env bằng pydantic-settings
│   ├── llm.py                   # client OpenAI-compatible + parse JSON + retry
│   ├── prompt.py                # system prompt + ghép prompt cho từng action
│   ├── schemas.py               # chỉ schema đầu ra RIÊNG của agent
│   ├── tools/
│   │   └── artifact.py          # ghi/đọc artifact + index.json
│   ├── api.py                   # FastAPI mỏng: /health, /agent, /state, /tasks
│   ├── cli.py                   # python -m cli run examples/task.json
│   ├── examples/                # task.json mẫu
│   ├── tests/test_agent.py
│   ├── artifacts/
│   ├── .env.example
│   ├── requirements.txt
│   └── README.md
├── agents/
│   ├── pm/    devops/    sa/    dba/    ba/    po/
│   └── dev/   tester/    scrum_master/    security/
└── tools/
    └── validate_agent.py        # kiểm tra contract cho mọi agent (Phase 6)
```

**Tech stack**: Python 3.11+, Pydantic v2, pydantic-settings, python-dotenv, openai SDK (trỏ `base_url`) hoặc httpx, FastAPI + uvicorn, pytest, Docker, Git.

## 4. Kế hoạch theo phase

| Phase | Ngày | Việc | Sản phẩm | Điều kiện xong |
| --- | --- | --- | --- | --- |
| 1 | 1 | Viết Contract: enum, model, registry, validator, JSON Schema, `CONTRACT.md` | Gói `agent_contract` | `pytest contract` xanh; ví dụ JSON ở mục 2.4 validate được |
| 2 | 1–2 | Agent Template: config, llm, BaseAgent, artifact tool, CLI, API, test mẫu | `agent-template/` | Chạy được agent "echo" với LLM giả; có test |
| 3 | 2–4 | PM Agent | `agents/pm/` | Đủ 6 action, test xanh, demo ra `plan.md` + task list |
| 4 | 4–7 | DevOps Agent | `agents/devops/` | Đủ 7 action, whitelist hoạt động, dry-run chạy được |
| 5 | 7–8 | Test độc lập PM và DevOps với LLM thật | Báo cáo test | Cả hai trả JSON hợp lệ qua CLI và API |
| 6 | 8–9 | Contract Validation cho 8 agent còn lại | `tools/validate_agent.py` + báo cáo | Danh sách lệch/chưa lệch từng agent |
| 7 | 10 | Freeze | Tag `contract-v1.0.0` | Không còn issue mở về schema |

**Đồng bộ với 4 người còn lại**: gửi họ Phase 1 và 2 ngay khi xong (ngày 2), để họ bắt đầu từ template thay vì tự dựng. Từ ngày 2 đến 9 họ làm agent của mình, bạn làm PM và DevOps.

## 5. Thiết kế PM Agent

- **Công cụ**: `create_task`, `update_task`, `assign_task`, `get_task_status`, `create_plan`, `create_milestone`, `read_artifact`, `create_artifact`. Lưu task vào `artifacts/tasks.json` (file đơn giản, chưa cần database).
- **Không có**: terminal, docker, deploy.
- **Đầu ra riêng** (Pydantic, đặt trong `schemas.py`): `ProjectPlan` (milestones, sprints, rủi ro), `TaskItem` (id, tên, mô tả, vai trò phụ trách, tiêu chí hoàn thành, hạn, phụ thuộc), `StatusReport` (4 mục: đã xong, đang làm, bị chặn, việc tiếp theo).
- **Quy tắc**: không viết code hay thiết kế kỹ thuật; thiếu thông tin quan trọng thì trả `BLOCKED` + `MISSING_CONTEXT` kèm danh sách câu hỏi (tối đa 3) trong `error.details.questions`; mọi task phải gán cho một `AgentRole` hợp lệ.

## 6. Thiết kế DevOps Agent

- **Công cụ**: `git` (clone, pull, checkout, commit, push), `docker` (build, run, compose, stop), `testing` (run\_tests), `deployment` (deploy, health\_check), `artifact`.
- **An toàn (bắt buộc)**:
  - LLM chỉ *đề xuất kế hoạch lệnh*; lớp tool kiểm tra rồi mới chạy.
  - Whitelist theo `ALLOWED_COMMANDS`, chạy bằng `subprocess.run([...], shell=False, timeout=...)`, không bao giờ `shell=True`.
  - Giới hạn `cwd` trong `WORKSPACE_DIR`, chặn đường dẫn chứa `..` hoặc đường dẫn tuyệt đối ngoài workspace.
  - Chặn mẫu nguy hiểm: `rm -rf`, `git push --force`, `docker system prune`, `DROP`, `curl | sh`.
  - `DRY_RUN=true` mặc định: chỉ in lệnh sẽ chạy. Chỉ chạy thật khi `context.execute=true` **và** `DRY_RUN=false`.
  - Lệnh phá hủy hoặc deploy prod: trả `BLOCKED` + `PERMISSION_DENIED` để con người duyệt.
  - Che secret trong log và `TaskResult` (che giá trị của biến có tên chứa KEY, TOKEN, SECRET, PASSWORD).
- **Đầu ra riêng**: `BuildReport`, `TestRunReport`, `DeploymentReport`, `HealthCheckReport`; kèm artifact `DEPLOYMENT`.

## 8. Checklist Definition of Done (mỗi agent)

- [ ] Identity và capability khai báo đúng registry
- [ ] System prompt (tiếng Việt, có quy tắc vai trò)
- [ ] Kết nối LLM qua `.env`, đổi provider không sửa code
- [ ] Input = `TaskRequest`; output = `TaskResult` + output model riêng cho từng action
- [ ] Tool có khai báo capability, có giới hạn quyền
- [ ] Artifact có metadata và nằm trong `index.json`
- [ ] Mọi lỗi trả `AgentError`, không ném exception
- [ ] Unit test chạy offline và xanh
- [ ] README, `.env.example`, `demo.py`
- [ ] `validate_agent.py` báo PASS

## 9. Rủi ro và cách xử lý

| Rủi ro | Cách xử lý |
| --- | --- |
| LLM miễn phí trả JSON hỏng hoặc sai schema | Retry kèm lỗi validate; giảm `temperature`; ưu tiên model có JSON mode |
| Chạm rate limit khi 5 người thử cùng lúc | Mỗi người dùng key riêng; backoff khi gặp 429, trả `LLM_ERROR` với `retryable=true` |
| 5 người định nghĩa schema lệch nhau | Gói `agent_contract` dùng chung + `validate_agent.py` chạy trước mỗi lần merge |
| Antigravity tự thêm tính năng ngoài phạm vi | Prompt 0 giới hạn phạm vi; duyệt từng prompt trước khi giao prompt kế |
| DevOps chạy lệnh nguy hiểm do LLM bịa | Whitelist, không shell, dry-run mặc định, chặn mẫu nguy hiểm, test riêng cho từng lớp |
| Contract cần đổi sau khi freeze | Tăng version (1.1.0), ghi `CHANGELOG.md`, giữ tương thích ngược khi có thể |

## 10. Tài liệu tham khảo nhóm

- **LangGraph**: state, node, edge, orchestrator-worker. Dùng ở System Phase, chưa cần bây giờ.
- **OpenHands Software Agent SDK**: Agent, Tool, Workspace, Conversation, Agent Server. Tham khảo cho DEV và DevOps.
- **MetaGPT**: mô hình role trong công ty phần mềm. Chỉ tham khảo, không phụ thuộc trực tiếp.
- **AgileCoder**: backlog, sprint, multi-agent theo Agile. Tham khảo cho PM, PO, Scrum Master.
