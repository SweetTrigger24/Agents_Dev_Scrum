import sys
from datetime import datetime, timezone
from pathlib import Path

# Đảm bảo import đúng trong thư mục agent-template
current_dir = Path(__file__).resolve().parent
if str(current_dir) not in sys.path:
    sys.path.insert(0, str(current_dir))

from fastapi import FastAPI
from agent_contract.models import (
    CONTRACT_VERSION,
    AgentIdentity,
    AgentState,
    TaskRequest,
    TaskResult,
)
from agent_contract.registry import CAPABILITY_REGISTRY
from agent import BaseAgent
from config import AgentConfig
from llm import LLMClient

# Khởi tạo cấu hình và Agent
config = AgentConfig()
config.verify_startup(check_port=False)

identity = AgentIdentity(
    agent_id=config.agent_id,
    role=config.agent_role,
    name=f"{config.agent_role.value} Template Agent",
    version="1.0.0",
    capabilities=CAPABILITY_REGISTRY.get(config.agent_role, []),
)

# Khởi tạo LLM Client (mặc định mock=True nếu không có API key)
mock_mode = not bool(config.llm_api_key.strip())
llm_client = LLMClient(config=config, mock=mock_mode)
agent_instance = BaseAgent(identity=identity, config=config, llm=llm_client)

app = FastAPI(
    title=f"{identity.name} API",
    version=CONTRACT_VERSION,
    description="FastAPI service cho AI Agent tuân thủ Agent Contract v1.0",
)


@app.get("/health", summary="Kiểm tra trạng thái sẵn sàng của dịch vụ")
def health() -> dict[str, str]:
    """Trả về trạng thái hoạt động của Agent service theo Agent Contract v1.0."""
    role_val = (
        agent_instance.identity.role.value
        if hasattr(agent_instance.identity.role, "value")
        else str(agent_instance.identity.role)
    )
    return {
        "status": "healthy",
        "agent_id": agent_instance.identity.agent_id,
        "role": role_val,
        "contract_version": CONTRACT_VERSION,
        "agent_version": agent_instance.identity.version,
        "timestamp": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
    }


@app.get("/agent", response_model=AgentIdentity, summary="Lấy thông tin định danh và năng lực của Agent")
def get_agent() -> AgentIdentity:
    """Trả về AgentIdentity tự khai báo."""
    return agent_instance.get_identity()


@app.get("/state", response_model=AgentState, summary="Lấy trạng thái vận hành hiện thời của Agent")
def get_state() -> AgentState:
    """Trả về AgentState phục vụ Dashboard hoặc Orchestrator."""
    return agent_instance.get_state()


@app.post("/tasks", response_model=TaskResult, summary="Gửi TaskRequest để Agent thực thi")
def execute_task(request: TaskRequest) -> TaskResult:
    """Nhận TaskRequest, xử lý bằng agent.handle() và trả về TaskResult."""
    return agent_instance.handle(request)
