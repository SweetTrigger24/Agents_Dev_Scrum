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
| PM | `project_planning`, `task_decomposition`, `task_assignment`, `progress_tracking`, `task_dispatch`, `workflow_orchestration` (hai capability cuối thêm ở v1.1.0) |
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
HOST=0.0.0.0
PORT=8001                    # bắt buộc, mỗi agent một cổng riêng (pm 8001, devops 8002...)
CONTRACT_MIN_VERSION=1.0.0   # agent từ chối khởi động nếu agent_contract cũ hơn
LLM_PROVIDER=groq            # groq | gemini | openrouter | ollama | openai | custom
LLM_MODEL=llama-3.3-70b-versatile
LLM_API_KEY=
LLM_BASE_URL=                # để trống thì lấy theo preset của provider
LLM_TEMPERATURE=0.2
LLM_TIMEOUT_SECONDS=60
LLM_MAX_RETRIES=2
ARTIFACT_DIR=./artifacts     # đường dẫn tương đối, tính theo thư mục của agent
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
5. Chỉ **PM** được giao task cho agent khác (mục 7b, Prompt 8); 9 agent còn lại **không gọi agent khác**, chỉ gợi ý qua `next_actions`.
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

## 7. Prompt giao cho Antigravity

**Cách dùng**: tạo workspace `ai-team/`, lưu mục 2 vào `docs/CONTRACT.md` và mục 3 vào `docs/STRUCTURE.md`. Dán **Prompt 0** vào file rules của workspace (hoặc đầu mỗi cuộc giao việc), rồi giao lần lượt Prompt 1 → 9. Chỉ giao prompt tiếp theo sau khi bạn đã chạy test và duyệt kết quả của prompt trước.

### Prompt 0 — Bối cảnh và quy tắc (dán một lần)

```
Bạn là kỹ sư Python senior trong dự án "ai-team": 10 AI agent (PM, SA, BA, PO, DEV, TESTER, DEVOPS, DBA, SCRUM_MASTER, SECURITY) do 5 người phát triển độc lập trên 5 máy. Giai đoạn này CHỈ làm Agent độc lập và protocol chung. KHÔNG làm Orchestrator, Dashboard, LangGraph, hay giao tiếp agent-với-agent.

Tài liệu bắt buộc đọc trước khi làm: docs/CONTRACT.md và docs/STRUCTURE.md. Đây là nguồn sự thật duy nhất; nếu thấy mâu thuẫn hoặc thiếu, DỪNG và hỏi tôi, không tự quyết.

Quy tắc:
- Python 3.11+, Pydantic v2, type hint đầy đủ, pytest. LLM qua API chuẩn OpenAI (đổi base_url/model bằng .env).
- Không hard-code API key, provider hay model. Không commit .env.
- Mọi I/O dùng model của gói agent_contract. Không định nghĩa lại model hay enum đã có.
- Agent không ném exception ra ngoài handle(); mọi lỗi trả TaskResult với AgentError.
- Test phải chạy offline bằng LLM giả (mock), không gọi mạng.
- Làm đúng phạm vi của prompt, không thêm tính năng ngoài danh sách. Code ngắn gọn, có docstring tiếng Việt cho hàm công khai.
- Cuối mỗi nhiệm vụ: liệt kê file đã tạo, lệnh để chạy test, và những điểm bạn không chắc chắn.
```

### Prompt 1 — Gói Contract (Phase 1)

```
Đọc docs/CONTRACT.md. Tạo gói contract/ (pyproject.toml, cài được bằng pip install -e ./contract) với module agent_contract gồm enums.py, models.py, registry.py, validators.py.

Yêu cầu:
1. Cài đặt đầy đủ các enum và model ở mục 2.1 và 2.2, gồm CONTRACT_VERSION = "1.0.0".
2. registry.py: CAPABILITY_REGISTRY (role -> danh sách capability) và ACTION_MAP (role -> {action: capability}) theo mục 2.3. Với 8 role chưa có bảng action, để ACTION_MAP rỗng cho role đó và đánh dấu TODO rõ ràng.
3. Các ràng buộc validate ở cuối mục 2.2 (COMPLETED <-> error None, FAILED/BLOCKED phải có error, capabilities là tập con của registry, uri tương đối không chứa "..", agent_id đúng regex).
4. Hàm tiện ích: make_error(code, message, retryable, **details) -> AgentError; failed_result(request, error) và blocked_result(request, error) -> TaskResult.
5. Script xuất JSON Schema của mọi model ra contract/schemas/*.json.
6. Test trong contract/tests/: validate 3 ví dụ JSON ở mục 2.4; test từng ràng buộc (cả trường hợp đúng và sai); test registry không có capability trùng role khác.

Tiêu chí xong: pytest contract chạy xanh; python -m agent_contract.export_schemas sinh file schema.
```

### Prompt 2 — Agent Template (Phase 2)

````
Đọc docs/CONTRACT.md và docs/STRUCTURE.md. Tạo agent-template/ theo đúng cấu trúc ở mục 3, dùng gói agent_contract đã có.

Yêu cầu:
1. config.py: dùng pydantic-settings đọc các biến ở mục 2.6; tạo .env.example đúng nội dung đó.
2. llm.py: class LLMClient dùng openai SDK với base_url/api_key/model từ config. Preset base_url theo provider (groq, gemini, openrouter, ollama, openai); LLM_BASE_URL nếu có thì ghi đè. Hàm complete_json(messages, output_model) phải: gọi LLM yêu cầu CHỈ trả JSON; trích JSON ngay cả khi bị bọc ```json; validate bằng output_model; nếu hỏng thì retry tối đa LLM_MAX_RETRIES lần, mỗi lần gửi kèm thông báo lỗi validate để model tự sửa; hết lượt thì raise LLMError nội bộ. Có timeout.
3. agent.py: class BaseAgent(identity, config, llm) với:
   - handle(request: TaskRequest) -> TaskResult: kiểm tra role/agent_id khớp, action thuộc ACTION_MAP và capability đã khai báo (sai thì PERMISSION_DENIED, retryable=false); đặt status RUNNING rồi về IDLE/COMPLETED/FAILED; bắt MỌI exception và đổi sang AgentError đúng mã; điền metadata (provider, model, duration_ms, dry_run).
   - get_identity() -> AgentIdentity, get_state() -> AgentState.
   - cơ chế đăng ký action: decorator @action("ten_action", output_model=...) để agent con chỉ cần viết hàm xử lý.
4. tools/artifact.py: save_artifact(name, type, content, created_by) ghi file vào ARTIFACT_DIR, cập nhật artifacts/index.json, tăng ART-xxx, tính sha256, chặn path traversal; read_artifact(ref); list_artifacts().
5. prompt.py: hàm build_messages(system_prompt, request) ghép system prompt + instruction + context + nội dung input_artifacts; system prompt luôn yêu cầu trả đúng JSON theo schema.
6. cli.py: python -m cli run examples/task.json in TaskResult JSON; python -m cli identity in AgentIdentity.
7. api.py (FastAPI): GET /health, GET /agent, GET /state, POST /tasks (nhận TaskRequest, trả TaskResult).
8. Một action mẫu "echo" để chứng minh luồng chạy, kèm examples/task.json.
9. tests/test_agent.py với LLM giả: thành công; action sai -> PERMISSION_DENIED; JSON LLM hỏng rồi sửa được sau retry; JSON hỏng mãi -> FAILED/LLM_ERROR; exception trong tool -> FAILED/TOOL_ERROR; path traversal bị chặn.
10. README.md: cách copy template thành agent mới trong 5 bước.

Tiêu chí xong: pytest xanh; python -m cli run examples/task.json trả TaskResult hợp lệ với LLM giả (có cờ --mock); uvicorn api:app chạy được.
````

### Prompt 3 — PM Agent (Phase 3)

```
Copy agent-template/ thành agents/pm/ (agent_id pm-01, role PM). Đọc mục 5 trong docs/STRUCTURE.md và mục 2.3 của docs/CONTRACT.md.

Yêu cầu:
1. Khai báo identity với 4 capability của PM; đăng ký 6 action: analyze_requirement, create_plan, decompose_tasks, assign_tasks, track_progress, report_status, đúng ACTION_MAP.
2. schemas.py: ProjectPlan (milestones, sprints, risks), TaskItem (task_id, title, description, assignee_role: AgentRole, acceptance_criteria, due, depends_on, status: TaskStatus), StatusReport (completed, in_progress, blocked, next). Mỗi action có output model riêng.
3. tools/task.py: create_task, update_task, assign_task, get_task_status lưu trong artifacts/tasks.json; assign_task chỉ nhận AgentRole hợp lệ và kiểm tra capability phù hợp. tools/plan.py: create_plan, create_milestone. Dùng artifact tool cho read/create_artifact. KHÔNG có terminal, docker, deploy.
4. prompt.py: system prompt tiếng Việt cho PM theo quy tắc: không viết code hay thiết kế kỹ thuật; mỗi task có đủ tên, mô tả, vai trò, tiêu chí hoàn thành, hạn; thiếu thông tin quan trọng thì trả BLOCKED + MISSING_CONTEXT với tối đa 3 câu hỏi trong error.details.questions.
5. Mỗi action COMPLETED phải sinh artifact (plan.md type PLAN, tasks.json type BACKLOG, status-report.md type DOCUMENTATION) và next_actions gợi ý role tiếp theo (không gọi agent khác).
6. Test với LLM giả cho cả 6 action, thêm trường hợp thiếu context và assignee không hợp lệ.
7. examples/: một task.json cho mỗi action; demo.py chạy chuỗi create_plan -> decompose_tasks -> assign_tasks -> report_status và in từng TaskResult.
8. README.md ngắn: cách chạy, cách đổi LLM provider, danh sách action.

Tiêu chí xong: pytest xanh; demo.py chạy được với --mock và với LLM thật khi có key; mọi TaskResult qua validate của agent_contract.
```

### Prompt 4 — DevOps Agent (Phase 4)

```
Copy agent-template/ thành agents/devops/ (agent_id devops-01, role DEVOPS). Đọc mục 6 trong docs/STRUCTURE.md và mục 2.3 của docs/CONTRACT.md.

Yêu cầu:
1. Khai báo identity với 6 capability; đăng ký 7 action: git_operation, build_image, generate_ci_config, run_tests, deploy, health_check, setup_monitoring.
2. tools/terminal.py (lớp thực thi DUY NHẤT, mọi tool khác đi qua đây): chỉ chạy lệnh có binary nằm trong ALLOWED_COMMANDS; nhận lệnh dạng list, subprocess.run(shell=False, timeout, capture_output); cwd bắt buộc nằm trong WORKSPACE_DIR (resolve path, chặn ".." và symlink thoát ra ngoài); chặn mẫu nguy hiểm (rm -rf, git push --force/-f, docker system prune, DROP, curl|sh, sudo); giới hạn kích thước output; che giá trị secret trong stdout/stderr (biến có tên chứa KEY, TOKEN, SECRET, PASSWORD).
3. DRY_RUN=true mặc định: terminal chỉ trả về lệnh sẽ chạy, không chạy. Chạy thật chỉ khi DRY_RUN=false VÀ request.context.execute == true. Deploy lên môi trường prod hoặc lệnh phá hủy luôn trả BLOCKED + PERMISSION_DENIED, retryable=false.
4. tools/git.py (clone, pull, checkout, commit, push), tools/docker.py (build, run, compose, stop), tools/testing.py (run_tests), tools/deployment.py (deploy, health_check qua httpx với timeout). Tất cả gọi qua terminal.py.
5. Luồng LLM: LLM chỉ sinh KẾ HOẠCH (danh sách lệnh dạng list + giải thích + rollback) theo output model; code kiểm tra qua terminal.py rồi mới thực thi. Với generate_ci_config, LLM sinh nội dung file (GitHub Actions/Dockerfile/docker-compose) và agent ghi vào artifact, không chạy gì.
6. schemas.py: CommandPlan, BuildReport, TestRunReport, DeploymentReport, HealthCheckReport. Deploy phải có rollback_plan, thiếu thì validation lỗi.
7. Lệnh lỗi (exit code khác 0) trả FAILED + TOOL_ERROR, retryable tùy loại lỗi; quá thời gian trả TIMEOUT. Artifact DEPLOYMENT cho báo cáo deploy.
8. Test: whitelist (lệnh ngoài danh sách bị chặn), path traversal, symlink thoát workspace, mẫu nguy hiểm, dry-run không chạy gì (mock subprocess và assert không được gọi), che secret, timeout, LLM trả lệnh có shell operator như && hoặc | bị từ chối.
9. demo.py: chạy generate_ci_config -> build_image (dry-run) -> run_tests (dry-run) -> deploy (dry-run, môi trường staging) -> health_check, in từng TaskResult.
10. README.md: nhóm lệnh được phép, cách bật chạy thật an toàn, danh sách action.

Tiêu chí xong: pytest xanh (không chạy lệnh thật nào trong test); demo.py chạy dry-run thành công; không có chỗ nào gọi subprocess ngoài terminal.py.
```

### Prompt 5 — Công cụ kiểm tra Contract (Phase 6)

```
Tạo tools/validate_agent.py. Với mỗi thư mục trong agents/, kiểm tra và in bảng PASS/FAIL cùng lý do:
1. Có đủ file bắt buộc: agent.py, config.py, prompt.py, schemas.py, tools/, tests/, artifacts/, .env.example, requirements.txt, README.md.
2. .env.example có đủ các khóa ở mục 2.6; không có API key thật trong repo (quét mẫu key phổ biến).
3. Import được agent, get_identity() trả AgentIdentity hợp lệ; capabilities là tập con của registry; role khớp thư mục.
4. Chạy examples/task.json ở chế độ mock: kết quả là TaskResult hợp lệ, status thuộc TaskStatus, error đúng ràng buộc.
5. Gửi action không hợp lệ: phải nhận FAILED + PERMISSION_DENIED. Gửi input hỏng: phải nhận FAILED + INVALID_INPUT, không ném exception.
6. Không thấy agent import agent khác hoặc gọi HTTP tới agent khác.
7. Mỗi agent có ít nhất một test và pytest của agent đó xanh.
Xuất thêm báo cáo Markdown ra docs/validation-report.md và trả exit code khác 0 nếu có agent FAIL.
```

### Prompt 6 — Chạy độc lập trên mọi máy (giao sau Prompt 2, hoặc sau Prompt 4 nếu PM và DevOps đã xong)

Prompt này bảo đảm 2 agent chạy chung 1 máy hay 10 agent chạy trên 5 máy đều giống nhau: chỉ khác `.env` và địa chỉ. Nó thêm `HOST`, `PORT`, `CONTRACT_MIN_VERSION` vào cấu hình, nên sau khi Antigravity làm xong, mục 2.6 trong `docs/CONTRACT.md` sẽ được cập nhật theo.

```
Đọc docs/CONTRACT.md và docs/STRUCTURE.md. Mục tiêu: mọi agent phải chạy giống hệt nhau dù 2 agent chạy chung 1 máy hay 10 agent chạy trên 5 máy. Agent không được giả định gì về máy đang chạy nó. Làm đúng phạm vi dưới đây, không thêm tính năng khác.

A. Cập nhật docs/CONTRACT.md (mục 2.6) và docs/CHANGELOG.md
- Thêm vào .env: HOST=0.0.0.0, PORT (bắt buộc, không có giá trị mặc định chung), CONTRACT_MIN_VERSION=1.0.0.
- Ghi vào CHANGELOG: "thêm HOST, PORT, CONTRACT_MIN_VERSION; không đổi schema nên không tăng CONTRACT_VERSION".

B. Sửa agent-template/ (và đồng bộ sang agents/pm, agents/devops)
1. config.py: đọc HOST, PORT, CONTRACT_MIN_VERSION. Thiếu PORT thì dừng với thông báo rõ. Mọi đường dẫn (ARTIFACT_DIR, WORKSPACE_DIR) dùng pathlib, chấp nhận đường dẫn tương đối, tính theo thư mục của agent chứ KHÔNG theo thư mục đang đứng khi chạy lệnh. Từ chối đường dẫn trỏ ra ngoài thư mục agent.
2. Khi khởi động: kiểm tra phiên bản agent_contract đang cài >= CONTRACT_MIN_VERSION, sai thì thoát với lỗi rõ ràng. Kiểm tra PORT chưa bị chiếm, bị chiếm thì báo lỗi và gợi ý cổng khác.
3. api.py: GET /health trả {status, agent_id, role, contract_version, agent_version}. Mọi thời gian dùng datetime có timezone UTC (timezone-aware), serialize ISO 8601 có hậu tố Z. Không dùng datetime.now() không tham số hay utcnow().
4. tools/artifact.py: uri luôn là đường dẫn tương đối dùng dấu "/" (as_posix), không bao giờ chứa ổ đĩa, "~" hay đường dẫn tuyệt đối. Agent chỉ đọc artifact trong ARTIFACT_DIR của chính nó; artifact đầu vào từ agent khác phải được copy vào thư mục artifacts/inbox/ của agent này trước, agent không đọc thẳng thư mục của agent khác.
5. Cô lập: mỗi agent có artifacts/, workspace/, data/ riêng. Thêm .gitignore cho workspace/, data/, .env, __pycache__.
6. requirements.txt: ghim phiên bản (==) cho mọi thư viện, và ghim agent_contract theo version cụ thể.

C. Script chạy cục bộ: scripts/run_local.py ở gốc repo
- Đọc scripts/local_agents.yaml, ví dụ danh sách {name: pm, path: agents/pm, port: 8001}, {name: devops, path: agents/devops, port: 8002}.
- Khởi động từng agent thành tiến trình riêng bằng subprocess (shell=False), mỗi agent dùng .env của chính nó, ghi log vào logs/<name>.log. Truyền PORT qua biến môi trường, không sửa file .env.
- Kiểm tra trước khi chạy: không trùng port trong YAML, mỗi agent có .env, mỗi agent trả /health thành công trong 15 giây, nếu không thì dừng tất cả và báo agent nào lỗi.
- Lệnh: python scripts/run_local.py up | status | down. "status" in bảng agent_id, port, trạng thái từ /health. Ctrl+C hoặc "down" dừng sạch mọi tiến trình con.
- Tạo docs/AGENT_ENDPOINTS.md dạng bảng: agent_id | role | máy | host | port | ghi chú, điền sẵn pm-01 và devops-01, các dòng còn lại để trống cho 4 người kia điền.

D. Mở rộng tools/validate_agent.py thêm các kiểm tra (PASS/FAIL kèm lý do)
1. Không có đường dẫn tuyệt đối cứng (mẫu "C:\", "/home/", "/Users/") trong mã nguồn agent.
2. Không có datetime.now() hoặc utcnow() không có timezone trong mã nguồn.
3. Không có agent nào import hoặc đọc file thuộc agents/<tên khác>/.
4. PORT trong .env.example của các agent và trong scripts/local_agents.yaml không trùng nhau (đối chiếu docs/AGENT_ENDPOINTS.md nếu cùng host).
5. requirements.txt ghim version, và version agent_contract của mọi agent giống nhau.
6. uri trong artifacts/index.json là đường dẫn tương đối.
7. .gitignore có .env, workspace/, data/.

E. Test
- config: đường dẫn tương đối tính đúng từ thư mục khác; từ chối đường dẫn thoát ra ngoài; thiếu PORT thì lỗi.
- khởi động: version contract thấp hơn thì thoát; port bị chiếm thì báo lỗi.
- run_local.py: dùng 2 agent giả (mock, không gọi LLM), kiểm tra up/status/down, trùng port bị từ chối, agent không lên /health thì dừng tất cả.
- validate_agent.py: mỗi kiểm tra mới có một ca PASS và một ca FAIL.
Test chạy offline, không gọi LLM thật, không mở port cố định (dùng port ngẫu nhiên).

Tiêu chí xong: pytest xanh; python scripts/run_local.py up chạy được pm và devops cùng lúc trên 2 port khác nhau; python tools/validate_agent.py báo PASS cho cả hai và FAIL đúng chỗ khi tôi cố tình đưa vào đường dẫn tuyệt đối hoặc port trùng.
```

**Sau khi xong**: gửi 4 người còn lại bản template mới cùng `validate_agent.py` để họ tự chạy trước khi nộp. `/health`, `PORT` và `AGENT_ENDPOINTS.md` cũng là thứ Orchestrator sẽ cần ở System Phase.

### Prompt 7 — Kết nối LAN giữa các máy (giao sau Prompt 6, trước Phase 6)

**Mô hình triển khai thực tế**: mỗi máy chỉ chạy 2 agent của mình, các máy nói chuyện với nhau qua mạng LAN bằng HTTP. Monorepo chỉ là cách chia sẻ *mã nguồn*; lúc chạy, máy nào chỉ khởi động agent của máy đó. Điều này thay thế ý tưởng chuyển artifact qua Git: artifact đi qua API của agent.

Prompt này **không đổi schema**, chỉ thêm một lớp *Agent API v1* (HTTP) mà Orchestrator sau này sẽ gọi. Nội dung API được ghi thành mục 2.8 trong `docs/CONTRACT.md`.

**Agent API v1**

| Endpoint | Xác thực | Mô tả |
| --- | --- | --- |
| `GET /health` | Không | `status`, `agent_id`, `role`, `contract_version`, `agent_version` |
| `GET /agent` | Có | `AgentIdentity` |
| `GET /state` | Có | `AgentState` |
| `POST /tasks` | Có | Nhận `TaskRequest`, trả `TaskResult` (đồng bộ, theo `timeout_seconds`) |
| `GET /tasks/{task_id}` | Có | Trả `TaskResult` đã lưu, giúp thử lại khi mạng rớt |
| `GET /artifacts` | Có | Danh sách `ArtifactRef` của agent |
| `GET /artifacts/{artifact_id}/content` | Có | Tải nội dung file |
| `POST /artifacts/inbox` | Có | Nhận artifact từ máy khác (metadata + file) |

Xác thực: header `Authorization: Bearer <AGENT_API_KEY>`. Thêm vào `.env`: `AGENT_API_KEY`, `MAX_UPLOAD_MB=10`.

```
Đọc docs/CONTRACT.md, docs/STRUCTURE.md và docs/AGENT_ENDPOINTS.md. Bối cảnh: mỗi agent chạy trên một MÁY RIÊNG, các máy gọi nhau qua LAN bằng HTTP. Không có thư mục chung giữa các máy. Làm đúng phạm vi dưới đây, KHÔNG đổi schema trong agent_contract, KHÔNG làm Orchestrator, KHÔNG để agent gọi agent khác.

A. Thêm mục 2.8 "Agent API v1" vào docs/CONTRACT.md và ghi vào CHANGELOG (không tăng CONTRACT_VERSION). Nội dung là bảng endpoint sau:
- GET /health (không xác thực): status, agent_id, role, contract_version, agent_version.
- GET /agent -> AgentIdentity; GET /state -> AgentState (có xác thực).
- POST /tasks nhận TaskRequest, trả TaskResult. GET /tasks/{task_id} trả TaskResult đã lưu hoặc 404.
- GET /artifacts -> list[ArtifactRef]; GET /artifacts/{artifact_id}/content -> nội dung file.
- POST /artifacts/inbox: multipart gồm field "metadata" (JSON ArtifactRef) và file; ghi vào artifacts/inbox/.
- Mọi endpoint trừ /health yêu cầu header Authorization: Bearer <AGENT_API_KEY>.

B. Cập nhật agent-template/ và đồng bộ sang agents/pm, agents/devops
1. config.py: thêm AGENT_API_KEY, MAX_UPLOAD_MB (mặc định 10). Nếu HOST khác 127.0.0.1 mà thiếu AGENT_API_KEY thì từ chối khởi động với thông báo rõ. Cập nhật .env.example.
2. Xác thực: dependency FastAPI kiểm tra Bearer token bằng hmac.compare_digest. Sai hoặc thiếu token trả 401 và KHÔNG ghi token vào log. /health là endpoint duy nhất không cần token.
3. POST /tasks: validate bằng TaskRequest (lỗi trả 422 kèm TaskResult FAILED/INVALID_INPUT). Idempotent theo task_id: task_id đã xử lý thì trả lại kết quả cũ từ data/results/<task_id>.json, không chạy lại. Lưu mọi TaskResult vào data/results/. Áp timeout theo constraints.timeout_seconds, quá hạn trả TaskResult FAILED/TIMEOUT, retryable=true. Chỉ chạy một task tại một thời điểm; task thứ hai đến khi đang bận trả 409 và AgentState.status giữ RUNNING.
4. Artifact qua mạng:
   - GET /artifacts/{id}/content chỉ phục vụ file có trong artifacts/index.json, kèm header X-Checksum-SHA256, chặn path traversal.
   - POST /artifacts/inbox: kiểm tra kích thước <= MAX_UPLOAD_MB, tên file được làm sạch (bỏ đường dẫn, ký tự lạ), tính sha256 và so với checksum trong metadata (lệch thì 422 và ARTIFACT_ERROR), ghi vào artifacts/inbox/<origin_agent_id>/ và thêm vào index.json với uri tương đối.
   - Trước khi xử lý TaskRequest có input_artifacts, agent kiểm tra từng artifact đã có trong inbox/ và khớp checksum; thiếu thì trả BLOCKED + MISSING_CONTEXT, details.missing_artifacts liệt kê artifact_id. Agent KHÔNG tự đi tải từ máy khác.
5. Log truy cập: mỗi request ghi method, path, status, thời gian, IP nguồn, task_id nếu có. Che secret và token.

C. scripts/lan_client.py (client thử nghiệm, không phải Orchestrator)
- Đọc scripts/endpoints.yaml (agent_id -> base_url), có endpoints.example.yaml được commit, còn endpoints.yaml thật nằm trong .gitignore. Token đọc từ biến môi trường AGENT_API_KEY_<AGENT_ID> hoặc .env.lan (cũng gitignore).
- Lệnh dùng httpx, timeout rõ ràng:
  - python scripts/lan_client.py health [agent_id|all]
  - python scripts/lan_client.py task <agent_id> <task.json>
  - python scripts/lan_client.py push-artifact <agent_id> <file> --type REQUIREMENT --created-by ba-01
  - python scripts/lan_client.py pull-artifact <agent_id> <artifact_id> --out <thư mục>
- Sau khi tải artifact phải kiểm tra sha256 so với X-Checksum-SHA256.

D. scripts/lan_check.py
- Với mỗi agent trong endpoints.yaml: gọi /health, báo PASS/FAIL, độ trễ (ms), contract_version có bằng nhau giữa các máy không, agent_id trả về có khớp khóa trong YAML không, và thử gọi một endpoint cần token mà không có token để xác nhận nhận 401.
- Gợi ý lỗi thường gặp khi FAIL (firewall chưa mở cổng, sai IP, sai cổng, agent bind 127.0.0.1).
- Xuất bảng và docs/lan-check-report.md; exit code khác 0 nếu có agent FAIL.

E. docs/LAN_SETUP.md (ngắn, có thể làm theo từng bước)
- Đặt IP tĩnh hoặc DHCP reservation cho từng máy (hoặc dùng Tailscale nếu khác mạng); điền docs/AGENT_ENDPOINTS.md.
- Mở cổng agent trên firewall Windows/Linux/macOS, chỉ cho dải IP LAN. Ví dụ lệnh cho từng hệ điều hành.
- Sinh AGENT_API_KEY bằng python -c "import secrets; print(secrets.token_urlsafe(32))", mỗi agent một token riêng, gửi cho nhóm qua kênh riêng, không commit.
- Cách chạy agent bind 0.0.0.0, kiểm tra từ máy khác bằng lan_client.py health.
- Lưu ý: HTTP thường không mã hóa, chỉ dùng trong LAN tin cậy; nếu đi qua mạng khác phải dùng VPN như Tailscale.

F. Test (offline, dùng port ngẫu nhiên, LLM giả)
- Xác thực: không token, sai token, đúng token; /health không cần token; thiếu AGENT_API_KEY khi HOST khác 127.0.0.1 thì không khởi động.
- POST /tasks: gọi hai lần cùng task_id chỉ chạy một lần; task thứ hai khi đang bận trả 409; quá hạn trả TIMEOUT.
- Artifact: tải về đúng checksum; upload quá MAX_UPLOAD_MB bị từ chối; checksum lệch bị từ chối; tên file có ".." hoặc đường dẫn tuyệt đối bị làm sạch; input_artifacts thiếu trong inbox trả BLOCKED/MISSING_CONTEXT.
- Giả lập hai agent trên hai port khác nhau trong cùng test, dùng lan_client để đẩy artifact từ agent A sang inbox của agent B rồi gọi task ở B dùng artifact đó.
- validate_agent.py thêm kiểm tra: có đủ endpoint Agent API v1, endpoint ngoài /health yêu cầu token, .gitignore chứa endpoints.yaml và .env.lan.

Tiêu chí xong: pytest xanh; chạy 2 agent trên 2 máy thật trong cùng LAN, python scripts/lan_check.py báo PASS cho cả hai; đẩy một file từ máy này sang inbox của máy kia, giao task dùng file đó từ lan_client.py và nhận TaskResult hợp lệ.
```

**Kiểm tra nghiệm thu bằng tay (ít nhất 2 máy thật)**: chạy `lan_check.py` từ máy của bạn tới 4 máy còn lại; tắt firewall của một máy để xem báo lỗi có dễ hiểu không; thử gọi `/agent` không có token và phải nhận 401.

## 7b. Chế độ tự động: chỉ nói chuyện với PM, các agent tự phối hợp

**Thay đổi thiết kế có chủ ý.** Ở các phần trước, quy tắc là *agent không gọi agent khác*. Với mục tiêu "chỉ giao việc cho PM, các agent tự chạy ra sản phẩm", PM trở thành **người điều phối duy nhất** (mô hình hình sao):

- Chỉ PM được giao task cho agent khác. 9 agent còn lại vẫn **không** được gọi ai, chỉ trả `TaskResult`.
- Điều phối nằm trong module `agents/pm/conductor/`, tách khỏi logic của PM. Sau này muốn tách thành Orchestrator riêng chỉ cần chuyển module này đi.
- **Luồng do mã tất định điều khiển (file YAML), LLM chỉ viết nội dung.** Model miễn phí hay sai, nên thứ tự bước, retry, vòng sửa lỗi và cổng duyệt không được giao cho LLM quyết định.

```
Bạn → PM: "Làm website bán hàng ..."
PM → PO (backlog) → BA (yêu cầu, user story) → [CỔNG: duyệt phạm vi]
   → SA (kiến trúc) → DBA (schema) → TESTER (test case) → DEV (code)
   → TESTER (chạy test) ⟲ DEV (sửa lỗi), tối đa 3 vòng
   → SECURITY (review) ⟲ DEV (sửa lỗi)
   → DEVOPS (CI, build, deploy dry-run) → [CỔNG: duyệt deploy]
   → PO (nghiệm thu) → SCRUM_MASTER (retrospective) → PM đóng gói RELEASE
```

**Điều cần biết trước khi làm**

- Prompt cho PM là chưa đủ: 8 agent còn lại phải có sẵn các action của pipeline (bảng 2.9 bên dưới), nên có thêm Prompt 9 dùng chung cho 4 người kia.
- "Sản phẩm hoàn chỉnh" với model miễn phí thực tế là ứng dụng nhỏ đến vừa. Chất lượng code phụ thuộc vào model, vì vậy vòng test và sửa lỗi là phần quan trọng nhất.
- Mã nguồn đi giữa các máy dưới dạng một file `.zip` (artifact `SOURCE_CODE`), vì không có thư mục chung.
- PM giữ token của cả 10 agent, nên máy của PM cần được bảo vệ cẩn thận hơn máy khác.
- Hai cổng duyệt (phạm vi, deploy) mặc định bật. Bạn có thể bật `PM_AUTO_APPROVE=true` để chạy hoàn toàn tự động khi thử nghiệm, nhưng deploy thật vẫn bị khóa.

### Bảng 2.9 — Pipeline actions (Contract v1.1.0)

| Role | Action | Capability | Tạo artifact | Đầu vào |
| --- | --- | --- | --- | --- |
| PO | `define_backlog` | `backlog_management` | `BACKLOG` | brief |
| PO | `accept_release` | `acceptance` | `DOCUMENTATION` (verdict) | `TEST_REPORT`, `DEPLOYMENT` |
| BA | `write_requirements` | `requirement_analysis` | `REQUIREMENT` | `BACKLOG`, brief |
| BA | `write_user_stories` | `user_story` | `USER_STORY` | `REQUIREMENT` |
| SA | `design_architecture` | `system_architecture` | `ARCHITECTURE` | `REQUIREMENT`, `USER_STORY` |
| DBA | `design_schema` | `schema_design` | `DATABASE_SCHEMA` | `ARCHITECTURE`, `REQUIREMENT` |
| DEV | `implement_project` | `coding` | `SOURCE_CODE` (.zip) | `ARCHITECTURE`, `DATABASE_SCHEMA`, `USER_STORY` |
| DEV | `fix_bugs` | `bug_fixing` | `SOURCE_CODE` (.zip) | `SOURCE_CODE`, `TEST_REPORT` hoặc `SECURITY_REPORT` |
| TESTER | `create_test_cases` | `test_case_generation` | `TEST_CASE` | `USER_STORY` |
| TESTER | `run_test_suite` | `automated_testing` | `TEST_REPORT` (verdict) | `SOURCE_CODE`, `TEST_CASE` |
| SECURITY | `security_review` | `security_review` | `SECURITY_REPORT` (verdict) | `SOURCE_CODE`, `ARCHITECTURE` |
| DEVOPS | `generate_ci_config`, `build_image`, `deploy`, `health_check` | như mục 2.3 | `DEPLOYMENT` | `SOURCE_CODE` |
| SCRUM\_MASTER | `track_blockers` | `blocker_tracking` | `DOCUMENTATION` | nhật ký sự kiện dự án |
| SCRUM\_MASTER | `run_retrospective` | `retrospective` | `DOCUMENTATION` | nhật ký sự kiện dự án |

**Quy ước verdict**: `outputs[0]` của TESTER, SECURITY và PO (nghiệm thu) có dạng `{"verdict": "PASS" | "FAIL", "findings": [{"severity": "LOW|MEDIUM|HIGH|CRITICAL", "title": "...", "detail": "..."}]}`. PM chỉ đọc `verdict` và `severity`, không đọc văn bản tự do.

### Prompt 8 — PM Conductor (giao sau Prompt 7)

```
Đọc docs/CONTRACT.md, docs/STRUCTURE.md và docs/AGENT_ENDPOINTS.md. Bối cảnh: 10 agent chạy trên 5 máy trong LAN, mỗi agent đã có Agent API v1 (Prompt 7). Prompt này cho phép DUY NHẤT PM gọi các agent khác, ghi đè quy tắc "agent không gọi agent khác" cho riêng PM. Làm đúng phạm vi dưới đây, không sửa các model có sẵn trong agent_contract.

Nguyên tắc: thứ tự bước, retry, vòng sửa lỗi và cổng duyệt do mã tất định điều khiển từ file YAML. LLM chỉ dùng để viết nội dung (tóm tắt, trả lời MISSING_CONTEXT, RELEASE.md), không quyết định luồng.

A. Contract v1.1.0 (chỉ thay đổi cộng thêm)
1. CONTRACT_VERSION = "1.1.0", cập nhật CHANGELOG. CONTRACT_MIN_VERSION của các agent giữ 1.0.0.
2. Thêm capability cho PM: task_dispatch, workflow_orchestration. Thêm action cho PM: start_project, resume_project, get_project_state (capability workflow_orchestration) và dispatch_task (capability task_dispatch).
3. Đăng ký toàn bộ pipeline actions ở bảng 2.9 trong ACTION_MAP và CAPABILITY_REGISTRY, ghi mục 2.9 vào docs/CONTRACT.md (kèm quy ước verdict và quy ước SOURCE_CODE là file .zip).
4. Tăng MAX_UPLOAD_MB mặc định lên 50.
5. Cập nhật tools/validate_agent.py: chỉ agents/pm được import module conductor hoặc gọi HTTP tới agent khác; mọi agent khác vẫn bị cấm. Test cho cả hai trường hợp.

B. agents/pm/conductor/ gồm:
1. workflows/software_delivery.yaml mô tả từng bước: id, role, action, depends_on, instruction_template (có {brief}, {summary_trước_đó}), input_artifact_types, expected_artifact_types, max_retries, timeout_seconds, và gate nếu có. Luồng mặc định: po.define_backlog -> ba.write_requirements -> ba.write_user_stories -> GATE approve_scope -> sa.design_architecture -> dba.design_schema -> tester.create_test_cases -> dev.implement_project -> tester.run_test_suite -> (FAIL thì dev.fix_bugs rồi chạy lại tester.run_test_suite) -> security.security_review -> (FAIL mức HIGH/CRITICAL thì dev.fix_bugs, tester.run_test_suite, security.security_review) -> devops.generate_ci_config -> devops.build_image -> devops.deploy (staging, dry-run) -> GATE approve_deploy -> devops.health_check -> po.accept_release -> scrum_master.run_retrospective -> đóng gói RELEASE.
2. dispatcher.py: nhận một bước, tạo TaskRequest hợp lệ (task_id dạng TASK-<project_id>-<số thứ tự>, agent_id lấy từ scripts/endpoints.yaml theo role). Với mỗi input_artifact: tải từ agent tạo ra nó (GET /artifacts/{id}/content), kiểm tra sha256, rồi đẩy vào inbox của agent đích (POST /artifacts/inbox). PM đóng vai trung chuyển, không agent nào tự đi lấy. Gọi POST /tasks bằng httpx với timeout theo bước, Bearer token đọc từ .env.lan hoặc biến môi trường AGENT_API_KEY_<AGENT_ID>.
3. policy.py: xử lý kết quả. COMPLETED thì ghi nhận artifact và đi tiếp. FAILED + retryable thì thử lại tối đa max_retries với backoff, giữ nguyên task_id (agent có idempotency). FAILED không retryable, hoặc hết retry thì project chuyển BLOCKED và dừng, ghi lý do. BLOCKED + MISSING_CONTEXT thì PM dùng LLM trả lời MỘT lần từ brief và bổ sung vào context rồi giao lại; vẫn thiếu thì dừng để hỏi người dùng, kèm danh sách câu hỏi. Agent không truy cập được (mất mạng, tắt máy) thì chờ và thử lại, quá hạn thì BLOCKED. Không bao giờ chạy lại bước đã COMPLETED trừ khi nằm trong vòng sửa lỗi.
4. Vòng sửa lỗi: đọc verdict trong outputs[0] của TESTER và SECURITY. Giới hạn MAX_FIX_LOOPS=3 chung cho cả dự án; vượt thì BLOCKED. Khi gọi dev.fix_bugs phải gửi kèm TEST_REPORT hoặc SECURITY_REPORT tương ứng và SOURCE_CODE mới nhất.
5. gates.py: cổng approve_scope và approve_deploy. Khi tới cổng, project chuyển WAITING_APPROVAL và dừng. Nếu PM_AUTO_APPROVE=true thì tự qua cổng, ghi vào nhật ký. Deploy thật chỉ được bật khi PM_ALLOW_REAL_DEPLOY=true VÀ cổng approve_deploy đã được duyệt; ngoài ra luôn gửi context.execute=false cho devops.
6. state.py: lưu trạng thái sau MỖI bước vào data/projects/<project_id>/state.json (ghi nguyên tử: ghi file tạm rồi đổi tên) và nhật ký sự kiện data/projects/<project_id>/events.jsonl. Pydantic model ProjectState: project_id, brief, status (CREATED, RUNNING, WAITING_APPROVAL, BLOCKED, COMPLETED, FAILED, ABORTED), steps với trạng thái từng bước, artifacts đã tạo (ArtifactRef + agent nguồn), fix_loops_used, tasks_used. Mất điện hoặc tắt PM giữa chừng thì resume chạy tiếp đúng bước dở.
7. Giới hạn bảo vệ: MAX_TASKS_PER_PROJECT=60, MAX_FIX_LOOPS=3, PROJECT_TIMEOUT_MINUTES=240, mặc định lấy từ .env. Vượt thì BLOCKED, không bao giờ chạy vô hạn.
8. release.py: khi xong, tạo thư mục data/projects/<project_id>/release/ gồm tất cả artifact cuối (tải về từ các agent), RELEASE.md do LLM viết từ dữ liệu có cấu trúc (yêu cầu, kiến trúc, kết quả test, kết quả security, trạng thái deploy, cách chạy sản phẩm, vấn đề còn tồn đọng) và manifest.json liệt kê artifact kèm checksum. Đăng ký thư mục này thành artifact DOCUMENTATION của PM.

C. Giao diện
1. cli.py của PM thêm: python -m cli project start --brief "..." (hoặc --brief-file brief.md) [--auto-approve], project status <id>, project approve <id> <gate>, project resume <id>, project abort <id>, project list. Lệnh start chạy nền và in project_id ngay.
2. api.py của PM thêm (có xác thực Bearer): POST /projects, GET /projects/{id}, POST /projects/{id}/approve, POST /projects/{id}/resume, POST /projects/{id}/abort. Action start_project, resume_project, get_project_state qua POST /tasks trả TaskResult ngay (start_project trả project_id trong outputs, công việc chạy nền).
3. project status in bảng bước: trạng thái, agent, thời gian, số lần thử, artifact tạo ra; hiển thị rõ cổng nào đang chờ duyệt hoặc lý do BLOCKED.

D. AgentState của PM phản ánh đúng: RUNNING khi có project đang chạy, WAITING khi chờ duyệt, BLOCKED khi dừng vì lỗi, IDLE khi rảnh.

E. Test (offline, không LLM thật, port ngẫu nhiên). Viết fake_agents.py dựng 9 FastAPI giả theo Agent API v1 trả TaskResult và artifact có sẵn theo từng action. Các kịch bản:
1. Đường chính chạy hết, RELEASE được tạo, manifest khớp checksum.
2. TESTER FAIL hai lần rồi PASS: có đúng hai lần dev.fix_bugs.
3. TESTER FAIL liên tục: dừng ở vòng thứ 3 với BLOCKED.
4. Lỗi retryable một lần rồi thành công: task_id không đổi.
5. Lỗi không retryable: BLOCKED, các bước sau không chạy.
6. Agent tắt máy giữa chừng: chờ rồi BLOCKED đúng hạn.
7. Dừng ở cổng approve_scope, approve rồi chạy tiếp; chế độ auto-approve.
8. Kill tiến trình PM giữa chừng rồi resume: không chạy lại bước đã xong.
9. Checksum artifact lệch khi trung chuyển: bước bị từ chối.
10. MISSING_CONTEXT được trả lời một lần; lần hai thì dừng.
11. Vượt MAX_TASKS_PER_PROJECT thì BLOCKED.
12. Không bao giờ gửi execute=true tới devops khi thiếu PM_ALLOW_REAL_DEPLOY hoặc chưa duyệt approve_deploy.
13. Agent không phải PM không thể import conductor (validate_agent báo FAIL).

F. Tài liệu: agents/pm/README.md thêm phần "Chế độ tự động" gồm cách khởi động, cách duyệt cổng, cách resume, cách đọc project status, và danh sách biến .env mới (PM_AUTO_APPROVE, PM_ALLOW_REAL_DEPLOY, MAX_FIX_LOOPS, MAX_TASKS_PER_PROJECT, PROJECT_TIMEOUT_MINUTES).

Tiêu chí xong: pytest xanh; với 9 agent giả, python -m cli project start --brief-file examples/brief.md --auto-approve chạy hết pipeline và ra thư mục release/; kill giữa chừng rồi resume vẫn ra kết quả; scripts/lan_check.py vẫn PASS.
```

### Prompt 9 — Thêm pipeline actions cho từng agent (4 người còn lại dùng chung, thay `[ROLE]`)

```
Đọc docs/CONTRACT.md (đặc biệt mục 2.8 và 2.9) và docs/STRUCTURE.md. Trong agents/[ROLE_LOWER]/ (đã tạo từ agent-template), cài đặt đúng các pipeline action của role [ROLE] trong bảng 2.9, không làm thêm action nào khác. PM sẽ là bên gọi các action này qua POST /tasks; agent này không gọi agent nào.

Yêu cầu cho MỖI action:
1. Đăng ký bằng decorator @action với output model Pydantic riêng trong schemas.py. Output model phải có các trường nội dung có cấu trúc, không chỉ một chuỗi văn bản.
2. Đọc artifact đầu vào từ artifacts/inbox/ theo input_artifacts của TaskRequest; thiếu hoặc lệch checksum thì trả BLOCKED + MISSING_CONTEXT.
3. Sinh artifact đầu ra đúng ArtifactType trong bảng, qua tools/artifact.py, kèm summary ngắn và next_actions gợi ý (chỉ gợi ý, không gọi agent khác).
4. Prompt tiếng Việt cho từng action: nêu rõ đầu vào, định dạng đầu ra, tiêu chí chất lượng; yêu cầu LLM trả JSON đúng schema.
5. Với TESTER, SECURITY, PO(accept_release): outputs[0] phải có verdict PASS hoặc FAIL và danh sách findings có severity theo mục 2.9; verdict quyết định bằng quy tắc rõ ràng trong code (ví dụ có finding HIGH hoặc CRITICAL thì FAIL), không để LLM tự quyết một mình.
6. Với DEV: LLM trả danh sách file {path, content}; code kiểm tra path nằm trong workspace (không "..", không tuyệt đối), ghi file, rồi đóng gói thành một file .zip artifact SOURCE_CODE. fix_bugs nhận .zip cũ, giải nén vào workspace, áp dụng sửa đổi theo báo cáo lỗi, đóng gói .zip mới với version tăng.
7. Với TESTER.run_test_suite và SECURITY: giải nén SOURCE_CODE vào workspace riêng, chạy lệnh qua tools/terminal.py (sao chép từ agents/devops, giữ nguyên whitelist, timeout, không shell, chặn mẫu nguy hiểm). Kết quả test lấy từ mã thoát và log thật của lệnh, không phải LLM tự khẳng định.
8. Bảo đảm mọi lỗi trả AgentError đúng mã, không ném exception.
9. Viết test offline (LLM giả) cho từng action: thành công, thiếu artifact đầu vào, JSON LLM hỏng, và với TESTER/SECURITY kiểm tra verdict PASS và FAIL. Cập nhật README và examples/ (một task.json cho mỗi action).
10. Chạy python tools/validate_agent.py và python scripts/lan_check.py, đảm bảo PASS.

Tiêu chí xong: pytest xanh; mỗi action chạy được qua lan_client.py từ máy khác và trả TaskResult hợp lệ.
```

**Nghiệm thu chế độ tự động**: bắt đầu với brief nhỏ (ví dụ ứng dụng todo một trang), chạy với `--auto-approve`, mở `RELEASE.md` kiểm tra có chạy được sản phẩm theo hướng dẫn hay không. Chỉ tăng độ phức tạp của brief sau khi chạy ổn định ba lần liên tiếp.

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
