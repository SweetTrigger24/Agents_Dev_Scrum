# Agent Template (Agent Contract v1.0)

Template chuẩn hóa cho việc phát triển 10 AI Agent độc lập trong dự án **ai-team**.
Mỗi kỹ sư clone thư mục này và chỉ cần tập trung viết logic nghiệp vụ riêng (prompt, capability, tool, output schema).

---

## 5 Bước tạo Agent mới từ Template

### Bước 1: Sao chép thư mục template sang thư mục role tương ứng
Copy toàn bộ thư mục `agent-template/` sang thư mục con trong `agents/<role>/`:
```bash
# Ví dụ tạo PM Agent:
cp -r agent-template agents/pm
cd agents/pm
```

### Bước 2: Cấu hình biến môi trường `.env`
Sao chép `.env.example` thành `.env` và cập nhật thông tin vai trò:
```bash
cp .env.example .env
```
Chỉnh sửa trong `.env`:
```ini
AGENT_ID=pm-01
AGENT_ROLE=PM
LLM_PROVIDER=groq
LLM_MODEL=llama-3.3-70b-versatile
LLM_API_KEY=gsk_your_api_key_here
```

### Bước 3: Định nghĩa Schema đầu ra riêng trong `schemas.py`
Xác định cấu trúc dữ liệu Pydantic mà các action của agent sẽ trả về:
```python
# agents/pm/schemas.py
from pydantic import BaseModel

class ProjectPlanOutput(BaseModel):
    milestones: int
    sprints: int
    details: list[str]
```

### Bước 4: Khai báo năng lực và viết các Action Handler trong `agent.py`
Khai báo capabilities (phải nằm trong `CAPABILITY_REGISTRY[role]`) và sử dụng decorator `@action`:
```python
# agents/pm/agent.py
from agent_template.agent import BaseAgent, action
from schemas import ProjectPlanOutput

class PMAgent(BaseAgent):
    @action("create_plan", output_model=ProjectPlanOutput)
    def handle_create_plan(self, request: TaskRequest) -> ProjectPlanOutput:
        # Xây dựng prompt và gọi LLM
        messages = build_messages(
            system_prompt="Bạn là PM...",
            request=request,
            output_schema=ProjectPlanOutput.model_json_schema(),
        )
        return self.llm.complete_json(messages, ProjectPlanOutput)
```

### Bước 5: Viết Unit Test và kiểm tra
Tạo các test case trong `tests/test_agent.py` và chạy:
```bash
# Chạy unit test offline
python -m pytest tests/ -v

# Chạy thử nghiệm CLI với task mẫu
python -m cli run examples/task.json --mock

# Khởi chạy API
uvicorn api:app --reload --port 8000
```

---

## Cấu trúc thư mục Template
```
agent-template/
├── agent.py                 # Lớp BaseAgent xử lý vòng đời, ngoại lệ và metadata
├── config.py                # Đọc .env bằng pydantic-settings
├── llm.py                   # Client OpenAI tương thích nhiều provider + retry JSON
├── prompt.py                # Ghép messages chuẩn kèm schema
├── schemas.py               # Schema đầu ra riêng của agent
├── tools/
│   └── artifact.py          # Quản lý đọc/ghi artifact an toàn (chặn path traversal)
├── api.py                   # FastAPI service (/health, /agent, /state, /tasks)
├── cli.py                   # CLI thực thi tác vụ nhanh
├── examples/
│   └── task.json            # Task mẫu thử nghiệm
├── tests/
│   └── test_agent.py        # Bộ unit test độc lập với Mock LLM
├── .env.example
├── requirements.txt
└── README.md
```
