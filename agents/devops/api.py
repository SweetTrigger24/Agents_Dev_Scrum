import sys
from datetime import datetime, timezone
from pathlib import Path

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
from agent import DevOpsAgent
from config import DevOpsConfig
from llm import LLMClient

config = DevOpsConfig()
config.verify_startup(check_port=False)

mock_mode = not bool(config.llm_api_key.strip())
llm_client = LLMClient(config=config, mock=mock_mode)
agent_instance = DevOpsAgent(config=config, llm=llm_client)

app = FastAPI(
    title="DevOps Agent API",
    version=CONTRACT_VERSION,
    description="Dịch vụ API độc lập của DevOps Agent theo Agent Contract v1.0",
)


@app.get("/health", summary="Kiểm tra trạng thái sẵn sàng của DevOps Agent")
def health() -> dict[str, str]:
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


@app.get("/agent", response_model=AgentIdentity, summary="Lấy thông tin nhận diện của DevOps")
def get_agent() -> AgentIdentity:
    return agent_instance.get_identity()


@app.get("/state", response_model=AgentState, summary="Lấy trạng thái vận hành của DevOps")
def get_state() -> AgentState:
    return agent_instance.get_state()


@app.post("/tasks", response_model=TaskResult, summary="Thực thi tác vụ DevOps")
def execute_task(request: TaskRequest) -> TaskResult:
    return agent_instance.handle(request)
