# HƯỚNG DẪN CẤU HÌNH & PHÁT TRIỂN AGENT ĐỘC LẬP TRÊN NHIỀU MÁY (MULTI-MACHINE SETUP CONFIG)
*Phiên bản chuẩn hóa: 1.0.0 | Áp dụng cho: 10 AI Agent trên 5 máy phát triển*

Tài liệu này cung cấp **toàn bộ cấu hình kỹ thuật, bảng phân bổ, biến môi trường, danh mục thư viện và checklist tương thích** để bất kỳ thành viên nào trong nhóm (5 kỹ sư) khi clone repo về máy mới đều có thể tạo và chạy Agent của mình tương thích 100% với hệ sinh thái chung mà không bị xung đột.

---

## 1. BẢNG MA TRẬN PHÂN BỔ 10 AGENT TRÊN 5 MÁY

Hệ thống được chia đều cho 5 máy. Mỗi máy đảm nhiệm 2 Agent độc lập, chạy trên 2 cổng mạng (Port) riêng biệt:

| Máy | Agent ID | Role | Port | Host | Capabilities bắt buộc | Action chính | File Artifact chính | Allowed Commands |
|---|---|---|---|---|---|---|---|---|
| **Máy 1** | `pm-01` | `PM` | `8001` | `0.0.0.0` | `project_planning`, `task_decomposition`, `task_assignment`, `progress_tracking` | `analyze_requirement`, `create_plan`, `decompose_tasks`, `report_status` | `plan.md`, `tasks.json`, `status-report.md` | `python,pytest` |
| **Máy 1** | `devops-01` | `DEVOPS` | `8002` | `0.0.0.0` | `git`, `docker`, `ci_cd`, `deployment`, `monitoring`, `health_check` | `git_operation`, `build_image`, `generate_ci_config`, `run_tests`, `deploy`, `health_check` | `ci.yml`, `deployment-report.md` | `git,docker,pytest,python,curl` |
| **Máy 2** | `ba-01` | `BA` | `8003` | `0.0.0.0` | `requirement_analysis`, `user_story`, `use_case`, `acceptance_criteria` | `analyze_requirement`, `write_user_stories`, `define_use_cases`, `create_acceptance_criteria` | `requirements.md`, `user-stories.json` | `python,pytest` |
| **Máy 2** | `sa-01` | `SA` | `8004` | `0.0.0.0` | `system_architecture`, `api_design`, `technology_selection` | `design_architecture`, `design_api`, `select_tech_stack`, `review_architecture` | `architecture.md`, `api-spec.yaml` | `python,pytest` |
| **Máy 3** | `po-01` | `PO` | `8005` | `0.0.0.0` | `product_vision`, `feature_prioritization`, `backlog_management`, `acceptance` | `define_vision`, `prioritize_features`, `manage_backlog`, `accept_deliverable` | `product-vision.md`, `backlog.json` | `python,pytest` |
| **Máy 3** | `dev-01` | `DEV` | `8006` | `0.0.0.0` | `coding`, `refactoring`, `bug_fixing`, `code_review` | `write_code`, `refactor_code`, `fix_bug`, `review_code` | `code-diff.patch`, `review.md` | `git,python,pytest,npm,mvn` |
| **Máy 4** | `tester-01` | `TESTER` | `8007` | `0.0.0.0` | `test_planning`, `test_case_generation`, `automated_testing`, `bug_reporting` | `create_test_plan`, `generate_test_cases`, `run_tests`, `report_bug` | `test-plan.md`, `test-cases.json` | `python,pytest,curl` |
| **Máy 4** | `dba-01` | `DBA` | `8008` | `0.0.0.0` | `database_design`, `schema_design`, `sql`, `query_optimization` | `design_database`, `generate_schema`, `write_migration`, `optimize_query` | `schema.sql`, `db-design.md` | `python,pytest` |
| **Máy 5** | `scrum_master-01` | `SCRUM_MASTER` | `8009` | `0.0.0.0` | `sprint_management`, `scrum_management`, `blocker_tracking`, `retrospective` | `plan_sprint`, `track_blockers`, `facilitate_standup`, `run_retrospective` | `sprint-summary.md`, `blockers.json` | `python,pytest` |
| **Máy 5** | `security-01` | `SECURITY` | `8010` | `0.0.0.0` | `security_analysis`, `vulnerability_scan`, `dependency_scan`, `security_review` | `analyze_security`, `scan_vulnerabilities`, `audit_dependencies`, `review_security` | `security-report.md`, `audit.json` | `git,python,pytest,bandit,pip-audit` |

---

## 2. BIẾN MÔI TRƯỜNG BẮT BUỘC (`.env.example`)

Mỗi agent **BẮT BUỘC** phải có đủ 16 biến môi trường sau trong file `.env.example` và `.env` (thiếu bất kỳ biến nào sẽ bị `tools/validate_agent.py` đánh trượt):

```properties
# 1. Cấu hình mạng (BẮT BUỘC: HOST=0.0.0.0, PORT không được để trống và không được trùng)
HOST=0.0.0.0
PORT=8003
CONTRACT_MIN_VERSION=1.0.0

# 2. Định danh Agent (Khớp với bảng phân bổ ở Mục 1)
AGENT_ID=ba-01
AGENT_ROLE=BA

# 3. Cấu hình LLM kết nối (Dùng Google Gemini Flash hoặc Groq/OpenAI)
LLM_PROVIDER=gemini
LLM_MODEL=gemini-3.6-flash
LLM_API_KEY=
LLM_BASE_URL=https://generativelanguage.googleapis.com/v1beta/openai/
LLM_TEMPERATURE=0.2
LLM_TIMEOUT_SECONDS=60
LLM_MAX_RETRIES=2

# 4. Cấu hình thư mục cô lập cục bộ (Dùng đường dẫn tương đối, không thoát ra ngoài)
ARTIFACT_DIR=./artifacts
WORKSPACE_DIR=./workspace
ALLOWED_COMMANDS=python,pytest
DRY_RUN=true
```

> [!IMPORTANT]
> **Tuyệt đối không commit API Key thật vào Git!** File `.env` đã được cấu hình trong `.gitignore`. Thành viên chỉ điền API Key vào `.env` trên máy cá nhân của mình.

---

## 3. DANH MỤC PHIÊN BẢN THƯ VIỆN GHIM CỨNG (`requirements.txt`)

Để loại bỏ hoàn toàn lỗi `"chạy trên máy tôi được nhưng máy bạn lỗi"`, toàn bộ 10 Agent sử dụng chung file `requirements.txt` với phiên bản được ghim cứng (`==`):

```text
agent-contract==1.0.0
fastapi==0.162.0
uvicorn==0.54.0
pydantic==2.14.2
pydantic-settings==2.16.2
python-dotenv==1.2.4
openai==3.42.1
httpx==0.28.1
pytest==9.1.1
pyyaml==6.0.3
```

---

## 4. QUY TRÌNH 4 BƯỚC THIẾT LẬP MÁY MỚI TỪ ĐẦU (ZERO TO HERO)

### Bước 1: Clone repo và tạo môi trường ảo Python (Python 3.11+)
```powershell
git clone <URL_REPO_CUA_NHOM> ai-team
cd ai-team

# Tạo venv và kích hoạt
python -m venv venv
.\venv\Scripts\Activate.ps1
```

### Bước 2: Cài đặt gói lõi `agent_contract` ở chế độ Editable
Đây là bước bắt buộc để mọi Agent trên máy import được các model Pydantic và registry:
```powershell
pip install -e ./contract
pip install -r agent-template/requirements.txt
```

### Bước 3: Tạo Agent tự động bằng công cụ Scaffold (Khuyên dùng)
Thay vì copy thư mục thủ công và sửa tay dễ bị sót, chỉ cần chạy lệnh:
```powershell
# Ví dụ tạo BA Agent cho Máy 2:
python tools/scaffold_agent.py --role BA

# Hoặc tạo SA Agent:
python tools/scaffold_agent.py --role SA
```
Công cụ này sẽ:
- Tự động sinh `agents/<role>/` với cấu trúc chuẩn.
- Tự động điền đúng `AGENT_ID`, `PORT`, `AGENT_ROLE`, `CAPABILITIES`.
- Tự tạo `.env.example`, `.env`, `README.md`, `schemas.py`, `prompt.py`, `tests/`.

### Bước 4: Kiểm tra tính tương thích ngay lập tức
```powershell
# 1. Chạy bài kiểm tra toàn bộ 13 tiêu chí Contract:
python tools/validate_agent.py

# 2. Chạy unit test của Agent vừa tạo:
python -m pytest agents/ba/tests/ -q
```
Nếu màn hình báo **`PASS`**, Agent của bạn đã tương thích 100% với hệ thống của cả nhóm!

---

## 5. CHECKLIST 13 QUY TẮC BẮT BUỘC CỦA CONTRACT VALIDATION

Khi phát triển code trong `agents/<tên_role>/`, bạn phải tuân thủ nghiêm ngặt 13 điều sau:

1. **Đủ 7 file & 3 thư mục bắt buộc:** `agent.py`, `config.py`, `prompt.py`, `schemas.py`, `.env.example`, `requirements.txt`, `README.md`, `tools/`, `tests/`, `artifacts/`.
2. **Không rò rỉ Secret:** `.env.example` không được chứa API key thật. Không hard-code API key trong code.
3. **Identity & Capabilities:** `get_identity()` phải trả về `AgentIdentity` hợp lệ, capabilities phải là tập con trong `CAPABILITY_REGISTRY`. Role phải viết hoa và khớp tên thư mục.
4. **Mock Task Execution:** Xử lý `TaskRequest` ở chế độ mock phải trả về `TaskResult` hợp lệ, status thuộc `TaskStatus`.
5. **Xử lý lỗi an toàn:** Gửi action không hợp lệ phải trả về `status=FAILED, error.code=PERMISSION_DENIED`. Dữ liệu đầu vào hỏng phải trả `INVALID_INPUT`, **tuyệt đối không để crash / ném ngoại lệ ra ngoài `handle()`**.
6. **Cô lập tuyệt đối (Isolation):** Không được import chéo agent khác (`from agents.pm import ...` là phạm luật). Không gọi HTTP sang agent khác. Giao tiếp chỉ thông qua `next_actions`.
7. **Unit Test đầy đủ:** Mỗi agent phải có ít nhất 1 test trong `tests/` và pytest phải xanh (chạy offline bằng mock, không gọi mạng).
8. **Không dùng đường dẫn tuyệt đối cứng:** Tuyệt đối không dùng `C:\`, `/home/`, `/Users/` trong mã nguồn. Dùng `Path(__file__).resolve().parent` và đường dẫn tương đối.
9. **Thời gian có Timezone (UTC):** Tuyệt đối không dùng `datetime.now()` không đối số hoặc `datetime.utcnow()`. Bắt buộc dùng `datetime.now(timezone.utc)` và định dạng ISO 8601 kết thúc bằng `Z`.
10. **Không trùng cổng Port:** Port trong `.env.example` phải là duy nhất và khớp với bảng ở Mục 1.
11. **Ghim phiên bản:** Mọi thư viện trong `requirements.txt` phải có `==`. Phiên bản `agent-contract` phải là `1.0.0` ở tất cả các agent.
12. **URI Artifact tương đối:** Trường `uri` trong `artifacts/index.json` bắt buộc là đường dẫn tương đối dạng posix (`artifacts/...`), không chứa ổ đĩa hay ký tự `~`.
13. **File `.gitignore` riêng:** Mỗi agent phải có `.gitignore` chứa `.env`, `workspace/`, `data/`, `__pycache__`.

---

## 6. LỆNH CHẠY THỬ NGHIỆM TRÊN MÁY CÁ NHÂN

### Chạy trực tiếp qua dòng lệnh (Prompt CLI):
```powershell
cd agents/ba
python cli.py prompt "Phân tích yêu cầu và viết 3 User Stories cho tính năng Giỏ hàng"
```

### Chạy chế độ Chat tương tác:
```powershell
cd agents/ba
python cli.py chat
```

### Chạy Server FastAPI và mở Swagger UI:
```powershell
cd agents/ba
python -m uvicorn api:app --port 8003
```
Truy cập trình duyệt: `http://localhost:8003/docs` để kiểm tra các endpoint:
- `GET /health`: Trả về trạng thái `healthy`, `agent_id`, `role`, `contract_version`, `agent_version`.
- `GET /agent`: Trả về `AgentIdentity`.
- `POST /tasks`: Nhận `TaskRequest` và thực thi trả về `TaskResult`.

### Chạy đồng thời 2 Agent trên cùng 1 máy bằng Runner script:
Cập nhật file `scripts/local_agents.yaml` theo 2 agent trên máy của bạn, sau đó chạy:
```powershell
# Khởi động cả 2 agent cùng lúc trong nền:
python scripts/run_local.py up

# Kiểm tra trạng thái sức khỏe:
python scripts/run_local.py status

# Dừng cả 2 agent:
python scripts/run_local.py down
```
