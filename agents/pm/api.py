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
from agent import PMAgent
from config import PMConfig
from llm import LLMClient

config = PMConfig()
mock_mode = not bool(config.llm_api_key.strip())
llm_client = LLMClient(config=config, mock=mock_mode)
agent_instance = PMAgent(config=config, llm=llm_client)

app = FastAPI(
    title="Project Manager (PM) Agent API",
    version=CONTRACT_VERSION,
    description="Dịch vụ API độc lập của PM Agent theo Agent Contract v1.0",
)


@app.get("/health", summary="Kiểm tra trạng thái sẵn sàng của PM Agent")
def health() -> dict[str, str]:
    return {
        "status": "ok",
        "agent_id": agent_instance.identity.agent_id,
        "role": agent_instance.identity.role.value,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


@app.get("/agent", response_model=AgentIdentity, summary="Lấy thông tin nhận diện của PM")
def get_agent() -> AgentIdentity:
    return agent_instance.get_identity()


@app.get("/state", response_model=AgentState, summary="Lấy trạng thái vận hành của PM")
def get_state() -> AgentState:
    return agent_instance.get_state()


@app.post("/tasks", response_model=TaskResult, summary="Thực thi tác vụ của PM")
def execute_task(request: TaskRequest) -> TaskResult:
    return agent_instance.handle(request)
