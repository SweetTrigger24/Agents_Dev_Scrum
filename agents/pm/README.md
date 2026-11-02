# Project Manager (PM) Agent (`pm-01`)

Agent chịu trách nhiệm quản lý dự án, phân tích yêu cầu sơ bộ, lập kế hoạch Sprint/Milestone, phân rã và phân công công việc, theo dõi tiến độ và báo cáo trạng thái.

---

## 1. Danh sách 6 Action hỗ trợ

| Action | Capability tương ứng | Artifact đầu ra | Next Actions gợi ý |
|---|---|---|---|
| `analyze_requirement` | `project_planning` | `requirements-summary.md` (`REQUIREMENT`) | BA (`requirement_analysis`), PM (`create_plan`) |
| `create_plan` | `project_planning` | `plan.md` (`PLAN`) | BA (`analyze_requirement`), PM (`decompose_tasks`) |
| `decompose_tasks` | `task_decomposition` | `tasks.json` (`BACKLOG`) | PM (`assign_tasks`) |
| `assign_tasks` | `task_assignment` | `tasks.json` (`BACKLOG`) | DEV (`coding`), TESTER (`test_planning`) |
| `track_progress` | `progress_tracking` | Cập nhật `tasks.json` | PM (`report_status`) |
| `report_status` | `progress_tracking` | `status-report.md` (`DOCUMENTATION`) | SCRUM_MASTER (`sprint_management`), PO (`feature_prioritization`) |

---

## 2. Cách chạy nhanh

### Chạy chuỗi Demo (khuyến nghị)
```bash
# Chạy chuỗi create_plan -> decompose_tasks -> assign_tasks -> report_status
python demo.py --mock
```

### Chạy qua CLI
```bash
# Xem identity
python -m cli identity

# Chạy một action cụ thể từ file mẫu
python -m cli run examples/task_create_plan.json --mock
```

### Chạy API Service (FastAPI)
```bash
uvicorn api:app --reload --port 8001
```
Các endpoint có sẵn:
- `GET /health`
- `GET /agent`
- `GET /state`
- `POST /tasks` (nhận `TaskRequest`, trả `TaskResult`)

---

## 3. Cách đổi LLM Provider

Chỉnh sửa file `.env` (copy từ `.env.example`):
```ini
AGENT_ID=pm-01
AGENT_ROLE=PM

# Chọn provider: groq | gemini | openrouter | ollama | openai
LLM_PROVIDER=groq
LLM_MODEL=llama-3.3-70b-versatile
LLM_API_KEY=gsk_your_api_key_here

# Hoặc dùng Gemini miễn phí:
# LLM_PROVIDER=gemini
# LLM_MODEL=gemini-2.5-flash
# LLM_API_KEY=AIzaSy...

# Hoặc dùng Ollama local:
# LLM_PROVIDER=ollama
# LLM_MODEL=llama3:8b
# LLM_BASE_URL=http://localhost:11434/v1
```

---

## 4. Chạy Unit Test
```bash
python -m pytest tests/ -v
```
