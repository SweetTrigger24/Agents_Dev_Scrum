import json
import sys
from pathlib import Path

# Đảm bảo import được các module trong agent-template và tránh xung đột cache sys.modules
agent_template_dir = Path(__file__).resolve().parent.parent
if str(agent_template_dir) not in sys.path:
    sys.path.insert(0, str(agent_template_dir))

for key in list(sys.modules.keys()):
    if key in ["agent", "config", "llm", "prompt", "schemas", "api", "tools"] or key.startswith("tools."):
        sys.modules.pop(key, None)

import pytest
from fastapi.testclient import TestClient

from agent_contract.enums import AgentRole, AgentStatus, ArtifactType, ErrorCode, TaskStatus
from agent_contract.models import AgentIdentity, TaskRequest, TaskResult
from agent_contract.registry import CAPABILITY_REGISTRY

from agent import BaseAgent, action
from api import app
from config import AgentConfig
from llm import LLMClient, LLMError
from schemas import EchoOutput
from tools.artifact import ArtifactError, list_artifacts, read_artifact, save_artifact


@pytest.fixture
def sample_config(tmp_path) -> AgentConfig:
    return AgentConfig(
        base_dir=tmp_path,
        port=8000,
        agent_id="pm-01",
        agent_role=AgentRole.PM,
        llm_provider="groq",
        llm_model="llama-3.3-70b-versatile",
        llm_max_retries=2,
        dry_run=True,
    )


@pytest.fixture
def sample_identity() -> AgentIdentity:
    return AgentIdentity(
        agent_id="pm-01",
        role=AgentRole.PM,
        name="PM Test Agent",
        version="1.0.0",
        capabilities=CAPABILITY_REGISTRY[AgentRole.PM],
        status=AgentStatus.IDLE,
    )


@pytest.fixture
def sample_task_request() -> TaskRequest:
    return TaskRequest(
        task_id="TASK-TEST-001",
        project_id="PROJ-001",
        agent_id="pm-01",
        role=AgentRole.PM,
        action="echo",
        instruction="Kiểm thử xử lý tác vụ",
        context={"env": "testing"},
    )


class TestAgentLifecycleAndExecution:
    """Kiểm tra vòng đời thực thi thành công và kiểm soát quyền hạn của Agent."""

    def test_handle_success(self, sample_identity, sample_config, sample_task_request):
        """1. Kiểm tra thực thi action echo thành công với mock LLM."""
        llm = LLMClient(config=sample_config, mock=True)
        agent = BaseAgent(identity=sample_identity, config=sample_config, llm=llm)

        result = agent.handle(sample_task_request)

        assert result.status == TaskStatus.COMPLETED
        assert result.error is None
        assert result.task_id == sample_task_request.task_id
        assert result.agent_id == sample_task_request.agent_id
        assert len(result.outputs) == 1
        assert result.outputs[0]["received_instruction"] == "Kiểm thử xử lý tác vụ"
        assert result.outputs[0]["received_action"] == "echo"
        assert "duration_ms" in result.metadata
        assert result.metadata["provider"] == "groq"
        assert result.metadata["dry_run"] is True

        # Kiểm tra get_identity và get_state
        assert agent.get_identity().agent_id == "pm-01"
        assert agent.get_state().status == AgentStatus.IDLE
        assert agent.get_state().current_task is None

    def test_wrong_action_permission_denied(self, sample_identity, sample_config):
        """2. Kiểm tra action sai / không thuộc đăng ký -> PERMISSION_DENIED, retryable=False."""
        agent = BaseAgent(identity=sample_identity, config=sample_config)
        bad_request = TaskRequest(
            task_id="TASK-TEST-002",
            project_id="PROJ-001",
            agent_id="pm-01",
            role=AgentRole.PM,
            action="unregistered_dangerous_action",
            instruction="Lệnh không được phép",
        )

        result = agent.handle(bad_request)

        assert result.status == TaskStatus.FAILED
        assert result.error is not None
        assert result.error.code == ErrorCode.PERMISSION_DENIED
        assert result.error.retryable is False

    def test_role_mismatch_permission_denied(self, sample_identity, sample_config):
        """Kiểm tra sai role giữa TaskRequest và Agent -> PERMISSION_DENIED."""
        agent = BaseAgent(identity=sample_identity, config=sample_config)
        mismatch_request = TaskRequest(
            task_id="TASK-TEST-003",
            project_id="PROJ-001",
            agent_id="pm-01",
            role=AgentRole.DEVOPS,  # Agent là PM nhưng gửi role DEVOPS
            action="echo",
            instruction="Sai role",
        )

        result = agent.handle(mismatch_request)

        assert result.status == TaskStatus.FAILED
        assert result.error is not None
        assert result.error.code == ErrorCode.PERMISSION_DENIED
        assert result.error.retryable is False

    def test_agent_id_mismatch_permission_denied(self, sample_identity, sample_config):
        """Kiểm tra sai agent_id -> PERMISSION_DENIED."""
        agent = BaseAgent(identity=sample_identity, config=sample_config)
        mismatch_request = TaskRequest(
            task_id="TASK-TEST-004",
            project_id="PROJ-001",
            agent_id="pm-02",  # Agent là pm-01 nhưng gửi tới pm-02
            role=AgentRole.PM,
            action="echo",
            instruction="Sai agent_id",
        )

        result = agent.handle(mismatch_request)

        assert result.status == TaskStatus.FAILED
        assert result.error is not None
        assert result.error.code == ErrorCode.PERMISSION_DENIED
        assert result.error.retryable is False


class TestLLMJSONHandlingAndRetry:
    """Kiểm tra cơ chế retry tự sửa JSON hỏng và xử lý khi LLM hỏng hoàn toàn."""

    def test_json_repaired_after_retry(self, sample_identity, sample_config, sample_task_request):
        """3. JSON LLM hỏng lần 1, nhưng sửa được sau retry -> thành công COMPLETED."""
        call_count = 0

        def flaky_mock_responder(messages: list[dict[str, str]]) -> str:
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                # Lần 1: Trả về JSON lỗi (thiếu dấu ngoặc nhọn kết thúc)
                return '{"received_instruction": "Kiểm thử", "reply": '
            # Lần 2: Trả về JSON chuẩn tuân thủ EchoOutput
            return json.dumps({
                "received_instruction": "Kiểm thử",
                "received_action": "echo",
                "received_context": {},
                "reply": "Đã sửa lỗi JSON thành công",
            })

        llm = LLMClient(config=sample_config, mock=True, mock_responder=flaky_mock_responder)
        agent = BaseAgent(identity=sample_identity, config=sample_config, llm=llm)

        result = agent.handle(sample_task_request)

        assert result.status == TaskStatus.COMPLETED
        assert result.error is None
        assert call_count == 2
        assert result.outputs[0]["reply"] == "Đã sửa lỗi JSON thành công"

    def test_json_fails_permanently_returns_llm_error(self, sample_identity, sample_config, sample_task_request):
        """4. JSON hỏng mãi quá số lần retry -> FAILED kèm ErrorCode.LLM_ERROR."""
        def permanently_broken_responder(messages: list[dict[str, str]]) -> str:
            return "Xin lỗi tôi không thể trả về JSON!"

        llm = LLMClient(config=sample_config, mock=True, mock_responder=permanently_broken_responder)
        agent = BaseAgent(identity=sample_identity, config=sample_config, llm=llm)

        result = agent.handle(sample_task_request)

        assert result.status == TaskStatus.FAILED
        assert result.error is not None
        assert result.error.code == ErrorCode.LLM_ERROR
        assert result.error.retryable is True


class TestToolExceptionHandling:
    """Kiểm tra xử lý ngoại lệ trong tool và bảo mật chống path traversal."""

    def test_tool_exception_returns_tool_error(self, sample_identity, sample_config):
        """5. Ngoại lệ trong tool -> FAILED kèm ErrorCode.TOOL_ERROR."""
        agent = BaseAgent(identity=sample_identity, config=sample_config)

        # Định nghĩa một action cố tình ném lỗi ArtifactError
        @action("fail_tool_action", capability="project_planning")
        def broken_action_handler(req: TaskRequest):
            raise ArtifactError("Ổ đĩa đầy, không thể ghi artifact")

        agent.register_action("fail_tool_action", broken_action_handler, capability="project_planning")

        req = TaskRequest(
            task_id="TASK-TEST-005",
            project_id="PROJ-001",
            agent_id="pm-01",
            role=AgentRole.PM,
            action="fail_tool_action",
            instruction="Thao tác gây lỗi tool",
        )

        result = agent.handle(req)

        assert result.status == TaskStatus.FAILED
        assert result.error is not None
        assert result.error.code == ErrorCode.TOOL_ERROR
        assert "Ổ đĩa đầy" in result.error.message

    def test_artifact_path_traversal_blocked(self, tmp_path):
        """6. Kiểm tra các trường hợp path traversal trong artifact tool đều bị chặn triệt để."""
        # 1. Ghi file với tên chứa '..'
        with pytest.raises(ArtifactError, match="Phát hiện path traversal"):
            save_artifact("../evil.sh", ArtifactType.OTHER, "malicious", "pm-01", artifact_dir=tmp_path)

        with pytest.raises(ArtifactError, match="Phát hiện path traversal"):
            save_artifact("sub/../../evil.sh", ArtifactType.OTHER, "malicious", "pm-01", artifact_dir=tmp_path)

        # 2. Ghi file với đường dẫn tuyệt đối
        with pytest.raises(ArtifactError, match="không được là đường dẫn tuyệt đối"):
            save_artifact("/etc/shadow", ArtifactType.OTHER, "malicious", "pm-01", artifact_dir=tmp_path)

        # 3. Đọc file path traversal
        with pytest.raises(ArtifactError, match="Phát hiện path traversal"):
            read_artifact("../../etc/passwd", artifact_dir=tmp_path)

    def test_artifact_save_and_read_success(self, tmp_path):
        """Kiểm tra lưu và đọc artifact hợp lệ, tính checksum và tăng ID tự động."""
        ref1 = save_artifact("plan.md", ArtifactType.PLAN, "# Kế hoạch sprint 1", "pm-01", artifact_dir=tmp_path)
        assert ref1.artifact_id == "ART-001"
        assert ref1.name == "plan.md"
        assert ref1.checksum is not None

        content = read_artifact(ref1, artifact_dir=tmp_path)
        assert content == "# Kế hoạch sprint 1"

        # Lưu file thứ 2 -> ID phải tăng lên ART-002
        ref2 = save_artifact("tasks.json", ArtifactType.BACKLOG, "[]", "pm-01", artifact_dir=tmp_path)
        assert ref2.artifact_id == "ART-002"

        # Kiểm tra danh sách
        all_arts = list_artifacts(artifact_dir=tmp_path)
        assert len(all_arts) == 2
        assert all_arts[0].artifact_id == "ART-001"
        assert all_arts[1].artifact_id == "ART-002"


class TestFastAPIEndpoints:
    """Kiểm tra các endpoint của FastAPI service theo Agent API v1."""

    def test_api_endpoints(self, sample_task_request):
        api_config = app.state.config
        client = TestClient(app)
        auth_headers = {"Authorization": f"Bearer {api_config.agent_api_key}"}

        # GET /health (không cần token)
        res_health = client.get("/health")
        assert res_health.status_code == 200
        health_data = res_health.json()
        assert health_data["status"] in ["ok", "healthy"]
        assert "agent_id" in health_data
        assert "role" in health_data
        assert "contract_version" in health_data
        assert "agent_version" in health_data
        assert "timestamp" in res_health.json()

        # Thiếu token trả 401
        res_unauth = client.get("/agent")
        assert res_unauth.status_code == 401

        res_bad_token = client.get("/agent", headers={"Authorization": "Bearer sai-token"})
        assert res_bad_token.status_code == 401

        # GET /agent (có token)
        res_agent = client.get("/agent", headers=auth_headers)
        assert res_agent.status_code == 200
        agent_data = res_agent.json()
        assert agent_data["agent_id"] == "pm-01"
        assert agent_data["role"] == "PM"

        # GET /state (có token)
        res_state = client.get("/state", headers=auth_headers)
        assert res_state.status_code == 200
        state_data = res_state.json()
        assert state_data["agent_id"] == "pm-01"
        assert state_data["status"] == "IDLE"

        # POST /tasks (có token)
        res_task = client.post("/tasks", json=sample_task_request.model_dump(mode="json"), headers=auth_headers)
        assert res_task.status_code == 200
        task_res = res_task.json()
        assert task_res["status"] == "COMPLETED"
        assert task_res["task_id"] == "TASK-TEST-001"
        assert task_res["error"] is None

        # GET /tasks/{task_id}
        res_get_task = client.get(f"/tasks/{sample_task_request.task_id}", headers=auth_headers)
        assert res_get_task.status_code == 200
        assert res_get_task.json()["task_id"] == sample_task_request.task_id

        # GET /artifacts
        res_artifacts = client.get("/artifacts", headers=auth_headers)
        assert res_artifacts.status_code == 200
        assert isinstance(res_artifacts.json(), list)
