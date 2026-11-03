# Cấu trúc Repository "ai-team"

Tài liệu mô tả cấu trúc monorepo cho 10 AI Agent độc lập tuân thủ Agent Contract v1.0.

```
ai-team/
├── README.md                    # quy tắc nhóm + link tài liệu tham khảo
├── docs/
│   ├── CONTRACT.md              # đặc tả Agent Contract v1.0 và Agent API v1
│   ├── STRUCTURE.md             # cấu trúc repository monorepo
│   ├── CHANGELOG.md             # ghi mọi thay đổi contract
│   ├── AGENT_ENDPOINTS.md       # bảng phân bổ máy, host, port
│   ├── AGENTS_SETUP_CONFIG.md   # cấu hình chi tiết cho 10 agent
│   └── LAN_SETUP.md             # hướng dẫn thiết lập mạng LAN
├── config/
│   └── agents_registry.json     # metadata 10 agent máy đọc
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
│   ├── api.py                   # FastAPI: Agent API v1
│   ├── cli.py                   # CLI: identity, run, prompt, chat
│   ├── examples/                # task.json mẫu
│   ├── tests/test_agent.py
│   ├── artifacts/
│   ├── .env.example
│   ├── requirements.txt
│   └── README.md
├── agents/
│   ├── pm/    devops/    sa/    dba/    ba/    po/
│   └── dev/   tester/    scrum_master/    security/
├── scripts/
│   ├── run_local.py             # runner quản lý các agent chạy cục bộ
│   ├── local_agents.yaml        # cấu hình port các agent cục bộ
│   ├── lan_client.py            # client gọi agent qua mạng LAN
│   ├── lan_check.py             # script kiểm tra kết nối LAN
│   └── endpoints.example.yaml   # mẫu danh sách endpoint LAN
└── tools/
    ├── validate_agent.py        # kiểm tra contract cho mọi agent
    └── scaffold_agent.py        # công cụ tự động tạo khung agent mới
```
