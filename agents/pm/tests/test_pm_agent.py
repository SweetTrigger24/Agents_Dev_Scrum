import json
import sys
from pathlib import Path

# Đảm bảo import đúng trong thư mục agents/pm và tránh xung đột cache sys.modules
pm_dir = Path(__file__).resolve().parent.parent
if str(pm_dir) not in sys.path:
    sys.path.insert(0, str(pm_dir))

for key in list(sys.modules.keys()):
    if key in ["agent", "config", "llm", "prompt", "schemas", "api", "tools"] or key.startswith("tools."):
        sys.modules.pop(key, None)

import pytest
from fastapi.testclient import TestClient

from agent_contract.enums import AgentRole, ArtifactType, ErrorCode, TaskStatus
from agent_contract.models import TaskRequest, TaskResult

from agent import PMAgent
from api import app
from config import PMConfig
from llm import LLMClient
from schemas import (
    AnalyzeRequirementOutput,
    AssignTasksOutput,
    CreatePlanOutput,
    DecomposeTasksOutput,
    ReportStatusOutput,
    TrackProgressOutput,
)
from tools.task import TaskToolError, assign_task, create_task, load_tasks


@pytest.fixture
def pm_config(tmp_path) -> PMConfig:
    return PMConfig(
        base_dir=tmp_path,
        port=8001,
        agent_id="pm-01",
        agent_role=AgentRole.PM,
        artifact_dir=str(tmp_path / "artifacts"),
    )


@pytest.fixture
def pm_agent(pm_config) -> PMAgent:
    llm = LLMClient(config=pm_config, mock=True)
    return PMAgent(config=pm_config, llm=llm, artifact_dir=pm_config.artifact_dir)


class TestPMAgentActions:
    """Kiểm thử đầy đủ 6 Action của PM Agent với LLM giả lập."""

    def test_action_analyze_requirement(self, pm_agent):
        """Action 1: analyze_requirement tạo requirements-summary.md và gợi ý BA."""
        req = TaskRequest(
            task_id="TASK-T1",
            project_id="PROJ-001",
            agent_id="pm-01",
            role=AgentRole.PM,
            action="analyze_requirement",
            instruction="Phân tích yêu cầu xây dựng sàn giao dịch thương mại điện tử B2B",
            context={"scale": "enterprise"},
        )
        res = pm_agent.handle(req)

        assert res.status == TaskStatus.COMPLETED
        assert res.error is None
        assert len(res.outputs) == 1
        data = res.outputs[0]
        assert "functional_requirements" in data
        assert "non_functional_requirements" in data
        assert len(res.artifacts) == 1
        assert res.artifacts[0].name == "requirements-summary.md"
        assert res.artifacts[0].type == ArtifactType.REQUIREMENT
        assert any(na.suggested_role == AgentRole.BA for na in res.next_actions)

    def test_action_create_plan(self, pm_agent):
        """Action 2: create_plan tạo plan.md và gợi ý decompose_tasks."""
        req = TaskRequest(
            task_id="TASK-T2",
            project_id="PROJ-001",
            agent_id="pm-01",
            role=AgentRole.PM,
            action="create_plan",
            instruction="Lập kế hoạch 4 sprint xây dựng ứng dụng web bán hàng",
            context={"project_name": "Web Shop"},
        )
        res = pm_agent.handle(req)

        assert res.status == TaskStatus.COMPLETED
        assert res.error is None
        assert len(res.artifacts) == 1
        assert res.artifacts[0].name == "plan.md"
        assert res.artifacts[0].type == ArtifactType.PLAN
        assert any(na.action == "decompose_tasks" for na in res.next_actions)

    def test_action_decompose_tasks(self, pm_agent):
        """Action 3: decompose_tasks tạo tasks.json backlog với các TaskItem đầy đủ."""
        req = TaskRequest(
            task_id="TASK-T3",
            project_id="PROJ-001",
            agent_id="pm-01",
            role=AgentRole.PM,
            action="decompose_tasks",
            instruction="Phân rã kế hoạch thành danh sách task kỹ thuật cho sprint 1",
        )
        res = pm_agent.handle(req)

        assert res.status == TaskStatus.COMPLETED
        assert res.error is None
        assert len(res.artifacts) == 1
        assert res.artifacts[0].name == "tasks.json"
        assert res.artifacts[0].type == ArtifactType.BACKLOG
        tasks = res.outputs[0]["tasks"]
        assert len(tasks) > 0
        # Kiểm tra task đầu tiên có đủ trường theo quy tắc
        t0 = tasks[0]
        assert "task_id" in t0 and "title" in t0 and "assignee_role" in t0 and "acceptance_criteria" in t0

    def test_action_assign_tasks(self, pm_agent):
        """Action 4: assign_tasks cập nhật vai trò phân công cho các task trong backlog."""
        req = TaskRequest(
            task_id="TASK-T4",
            project_id="PROJ-001",
            agent_id="pm-01",
            role=AgentRole.PM,
            action="assign_tasks",
            instruction="Phân công task cho DEV, TESTER, DEVOPS theo đúng vai trò",
            context={"assignments": {"TASK-001": "DEV", "TASK-002": "TESTER"}},
        )
        res = pm_agent.handle(req)

        assert res.status == TaskStatus.COMPLETED
        assert res.error is None
        assert len(res.artifacts) == 1
        assert res.artifacts[0].name == "tasks.json"
        assert any(na.suggested_role == AgentRole.DEV for na in res.next_actions)

    def test_action_track_progress(self, pm_agent):
        """Action 5: track_progress tính toán tỷ lệ phần trăm hoàn thành."""
        req = TaskRequest(
            task_id="TASK-T5",
            project_id="PROJ-001",
            agent_id="pm-01",
            role=AgentRole.PM,
            action="track_progress",
            instruction="Theo dõi tiến độ backlog hiện tại",
        )
        res = pm_agent.handle(req)

        assert res.status == TaskStatus.COMPLETED
        assert res.error is None
        data = res.outputs[0]
        assert "progress_percent" in data
        assert "total_tasks" in data
        assert any(na.action == "report_status" for na in res.next_actions)

    def test_action_report_status(self, pm_agent):
        """Action 6: report_status xuất status-report.md đủ 4 phần chuẩn."""
        req = TaskRequest(
            task_id="TASK-T6",
            project_id="PROJ-001",
            agent_id="pm-01",
            role=AgentRole.PM,
            action="report_status",
            instruction="Xuất báo cáo trạng thái định kỳ 4 phần",
        )
        res = pm_agent.handle(req)

        assert res.status == TaskStatus.COMPLETED
        assert res.error is None
        assert len(res.artifacts) == 1
        assert res.artifacts[0].name == "status-report.md"
        assert res.artifacts[0].type == ArtifactType.DOCUMENTATION
        report = res.outputs[0]["report"]
        assert len(report["completed"]) > 0
        assert len(report["in_progress"]) > 0
        assert len(report["blocked"]) > 0
        assert len(report["next"]) > 0


class TestEdgeCasesAndValidation:
    """Kiểm thử trường hợp biên: thiếu context và phân công vai trò không hợp lệ."""

    def test_missing_context_blocked(self, pm_agent):
        """Yêu cầu thiếu thông tin cốt lõi -> trả BLOCKED + MISSING_CONTEXT với tối đa 3 câu hỏi."""
        vague_request = TaskRequest(
            task_id="TASK-VAGUE",
            project_id="PROJ-001",
            agent_id="pm-01",
            role=AgentRole.PM,
            action="create_plan",
            instruction="làm đi",  # Chỉ dẫn quá ngắn, mơ hồ
            context={"simulate_missing_context": True},
        )
        res = pm_agent.handle(vague_request)

        assert res.status == TaskStatus.BLOCKED
        assert res.error is not None
        assert res.error.code == ErrorCode.MISSING_CONTEXT
        assert res.error.retryable is False
        assert "questions" in res.error.details
        questions = res.error.details["questions"]
        assert isinstance(questions, list)
        assert 1 <= len(questions) <= 3

    def test_invalid_assignee_role_fails(self, pm_config):
        """assign_task với role không hợp lệ hoặc capability không khớp phải ném lỗi."""
        # 1. Tạo trước 1 task hợp lệ
        create_task(
            task_id="TASK-ASSIGN-01",
            title="Lập trình backend",
            description="Mô tả",
            assignee_role=AgentRole.DEV,
            acceptance_criteria=["Tiêu chí 1"],
            artifact_dir=pm_config.artifact_dir,
        )

        # 2. Gán với role không hợp lệ
        with pytest.raises(TaskToolError, match="không phải là AgentRole hợp lệ"):
            assign_task("TASK-ASSIGN-01", "NON_EXISTENT_ROLE", artifact_dir=pm_config.artifact_dir)  # type: ignore

        # 3. Gán với role thiếu capability yêu cầu
        # Ví dụ yêu cầu capability "coding" nhưng lại gán cho PM
        with pytest.raises(TaskToolError, match="không sở hữu capability 'coding'"):
            assign_task(
                "TASK-ASSIGN-01",
                AgentRole.PM,
                required_capability="coding",
                artifact_dir=pm_config.artifact_dir,
            )


class TestPMAgentAPI:
    """Kiểm thử FastAPI endpoints của PM Agent."""

    def test_api_endpoints(self):
        client = TestClient(app)

        res_health = client.get("/health")
        assert res_health.status_code == 200
        assert res_health.json()["role"] == "PM"

        res_agent = client.get("/agent")
        assert res_agent.status_code == 200
        assert res_agent.json()["agent_id"] == "pm-01"

        res_state = client.get("/state")
        assert res_state.status_code == 200
        assert res_state.json()["status"] == "IDLE"

        task_payload = {
            "contract_version": "1.0.0",
            "task_id": "TASK-API-PM",
            "project_id": "PROJ-001",
            "agent_id": "pm-01",
            "role": "PM",
            "action": "report_status",
            "instruction": "Tạo báo cáo trạng thái",
            "context": {},
            "input_artifacts": [],
            "constraints": {"deadline": None, "priority": "MEDIUM", "timeout_seconds": 60},
        }
        res_task = client.post("/tasks", json=task_payload)
        assert res_task.status_code == 200
        assert res_task.json()["status"] == "COMPLETED"
