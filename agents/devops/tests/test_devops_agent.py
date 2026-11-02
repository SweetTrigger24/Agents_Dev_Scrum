import os
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

# Đảm bảo import đúng trong thư mục agents/devops và tránh xung đột cache sys.modules
devops_dir = Path(__file__).resolve().parent.parent
if str(devops_dir) not in sys.path:
    sys.path.insert(0, str(devops_dir))

for key in list(sys.modules.keys()):
    if key in ["agent", "config", "llm", "prompt", "schemas", "api", "tools"] or key.startswith("tools."):
        sys.modules.pop(key, None)

import pytest
from pydantic import ValidationError

from agent_contract.enums import AgentRole, ArtifactType, ErrorCode, TaskStatus
from agent_contract.models import TaskRequest

from agent import DevOpsAgent
from config import DevOpsConfig
from llm import LLMClient
from schemas import DeploymentReport
from tools.terminal import (
    CommandTimeoutError,
    SecurityViolationError,
    TerminalExecutor,
    mask_secrets,
)


@pytest.fixture
def devops_config(tmp_path) -> DevOpsConfig:
    ws = tmp_path / "workspace"
    ws.mkdir(parents=True, exist_ok=True)
    art = tmp_path / "artifacts"
    art.mkdir(parents=True, exist_ok=True)
    return DevOpsConfig(
        agent_id="devops-01",
        agent_role=AgentRole.DEVOPS,
        workspace_dir=str(ws),
        artifact_dir=str(art),
        dry_run=True,
    )


@pytest.fixture
def devops_agent(devops_config) -> DevOpsAgent:
    llm = LLMClient(config=devops_config, mock=True)
    return DevOpsAgent(
        config=devops_config,
        llm=llm,
        workspace_dir=devops_config.workspace_dir,
        artifact_dir=devops_config.artifact_dir,
    )


class TestTerminalSecurityAndSafeguards:
    """Kiểm thử toàn diện các lớp bảo vệ an toàn của TerminalExecutor."""

    def test_whitelist_blocks_unauthorized_binary(self, devops_config):
        """1. Binary không nằm trong whitelist ALLOWED_COMMANDS bị chặn ngay lập tức."""
        terminal = TerminalExecutor(
            workspace_dir=devops_config.workspace_dir,
            allowed_commands=["git", "docker"],
            dry_run=True,
        )

        # Lệnh 'curl' không có trong whitelist
        with pytest.raises(SecurityViolationError, match="không nằm trong whitelist"):
            terminal.validate_command(["curl", "https://example.com"])

        # Lệnh 'bash' không có trong whitelist
        with pytest.raises(SecurityViolationError, match="không nằm trong whitelist"):
            terminal.validate_command(["bash", "-c", "echo hello"])

    def test_shell_operators_rejected(self, devops_config):
        """2. Lệnh chứa shell operator (&&, ||, ;, |, >, <) bị từ chối tuyệt đối."""
        terminal = TerminalExecutor(
            workspace_dir=devops_config.workspace_dir,
            allowed_commands=["git", "docker", "pytest"],
            dry_run=True,
        )

        bad_commands = [
            ["git", "status", "&&", "git", "pull"],
            ["docker", "build", "|", "cat"],
            ["pytest", ";", "rm"],
            ["git", "commit", "-m", "msg > file.txt"],
        ]
        for cmd in bad_commands:
            with pytest.raises(SecurityViolationError, match="Phát hiện shell operator"):
                terminal.validate_command(cmd)

    def test_dangerous_patterns_blocked(self, devops_config):
        """3. Các mẫu lệnh nguy hiểm (rm -rf, git push --force, prune, DROP, sudo) bị chặn."""
        terminal = TerminalExecutor(
            workspace_dir=devops_config.workspace_dir,
            allowed_commands=["git", "docker", "python"],
            dry_run=True,
        )

        dangerous = [
            ["git", "push", "origin", "main", "--force"],
            ["git", "push", "-f", "origin", "main"],
            ["docker", "system", "prune"],
            ["docker", "volume", "prune"],
            ["python", "-c", "DROP DATABASE test"],
            ["sudo", "docker", "ps"],
        ]
        for cmd in dangerous:
            with pytest.raises(SecurityViolationError, match="Phát hiện mẫu lệnh phá hủy"):
                terminal.validate_command(cmd)

    def test_path_traversal_and_symlink_escape_blocked(self, devops_config, tmp_path):
        """4. Ngăn chặn path traversal và symlink thoát ra ngoài WORKSPACE_DIR."""
        terminal = TerminalExecutor(
            workspace_dir=devops_config.workspace_dir,
            allowed_commands=["git"],
            dry_run=True,
        )

        # Path traversal dạng '..'
        with pytest.raises(SecurityViolationError, match="Phát hiện path traversal"):
            terminal.validate_cwd(Path(devops_config.workspace_dir) / ".." / "outside")

        # Thư mục bên ngoài workspace
        outside_dir = tmp_path / "outside_secure_zone"
        outside_dir.mkdir(parents=True, exist_ok=True)
        with pytest.raises(SecurityViolationError, match="nằm ngoài phạm vi WORKSPACE_DIR"):
            terminal.validate_cwd(outside_dir)

        # Symlink trỏ ra ngoài workspace
        link_to_outside = Path(devops_config.workspace_dir) / "symlink_escape"
        try:
            link_to_outside.symlink_to(outside_dir, target_is_directory=True)
            with pytest.raises(SecurityViolationError, match="nằm ngoài phạm vi WORKSPACE_DIR"):
                terminal.validate_cwd(link_to_outside)
        except (OSError, NotImplementedError):
            # Trên một số môi trường Windows không bật Developer Mode có thể không tạo được symlink
            pass

    def test_dry_run_does_not_call_subprocess(self, devops_config):
        """5. Chế độ DRY_RUN=true: tuyệt đối không gọi subprocess.run."""
        terminal = TerminalExecutor(
            workspace_dir=devops_config.workspace_dir,
            allowed_commands=["git"],
            dry_run=True,
        )

        with patch("subprocess.run") as mock_subproc:
            result = terminal.run(["git", "status"], execute=False)
            mock_subproc.assert_not_called()
            assert result.dry_run is True
            assert result.exit_code == 0
            assert "[DRY_RUN]" in result.stdout

    def test_secret_masking(self):
        """6. Che giấu giá trị secret chứa KEY, TOKEN, SECRET, PASSWORD."""
        env_vars = {
            "DB_PASSWORD": "super_secret_db_pass_123",
            "API_TOKEN": "token_xyz_987654321",
            "SAFE_VAR": "normal_public_text",
        }
        fake_key = "gsk_" + "abcdef1234567890123456"
        text = (
            "Kết nối DB với password: super_secret_db_pass_123 và token: token_xyz_987654321. "
            f"Biến thường: normal_public_text, api_key='{fake_key}'"
        )
        masked = mask_secrets(text, custom_env=env_vars)

        assert "super_secret_db_pass_123" not in masked
        assert "token_xyz_987654321" not in masked
        assert fake_key not in masked
        assert "***REDACTED***" in masked
        assert "normal_public_text" in masked

    def test_command_timeout(self, devops_config):
        """7. Lệnh quá thời gian timeout ném ra CommandTimeoutError."""
        terminal = TerminalExecutor(
            workspace_dir=devops_config.workspace_dir,
            allowed_commands=["git"],
            dry_run=False,
        )

        import subprocess
        with patch("subprocess.run", side_effect=subprocess.TimeoutExpired(cmd=["git"], timeout=5)):
            with pytest.raises(CommandTimeoutError, match="quá thời gian thực thi"):
                terminal.run(["git", "status"], execute=True, timeout=5)


class TestDevOpsAgentActions:
    """Kiểm thử các Action của DevOps Agent."""

    def test_deploy_prod_blocked(self, devops_agent):
        """Deploy lên Production luôn bị chặn và trả về BLOCKED + PERMISSION_DENIED."""
        req = TaskRequest(
            task_id="TASK-DEPLOY-PROD",
            project_id="PROJ-001",
            agent_id="devops-01",
            role=AgentRole.DEVOPS,
            action="deploy",
            instruction="Deploy service lên production",
            context={
                "environment": "prod",
                "service_name": "app",
                "rollback_plan": ["docker compose down"],
            },
        )
        res = devops_agent.handle(req)

        assert res.status == TaskStatus.BLOCKED
        assert res.error is not None
        assert res.error.code == ErrorCode.PERMISSION_DENIED
        assert res.error.retryable is False

    def test_deploy_missing_rollback_plan_fails_validation(self):
        """Deploy thiếu rollback_plan thì Pydantic validation phải báo lỗi."""
        with pytest.raises(ValidationError, match="bắt buộc phải có rollback_plan"):
            DeploymentReport(
                service_name="web-app",
                environment="staging",
                version="v1.0",
                rollback_plan=[],  # Rỗng -> vi phạm
            )

    def test_actions_dry_run_success(self, devops_agent):
        """Kiểm thử chuỗi các action trong chế độ dry-run thành công."""
        # 1. generate_ci_config
        req_ci = TaskRequest(
            task_id="TASK-CI",
            project_id="PROJ-001",
            agent_id="devops-01",
            role=AgentRole.DEVOPS,
            action="generate_ci_config",
            instruction="Sinh cấu hình Dockerfile",
            context={"config_type": "dockerfile"},
        )
        res_ci = devops_agent.handle(req_ci)
        assert res_ci.status == TaskStatus.COMPLETED
        assert len(res_ci.artifacts) == 1
        assert res_ci.artifacts[0].name == "Dockerfile"

        # 2. build_image
        req_build = TaskRequest(
            task_id="TASK-BUILD",
            project_id="PROJ-001",
            agent_id="devops-01",
            role=AgentRole.DEVOPS,
            action="build_image",
            instruction="Build image",
            context={"tag": "web:v1.0"},
        )
        res_build = devops_agent.handle(req_build)
        assert res_build.status == TaskStatus.COMPLETED

        # 3. run_tests
        req_test = TaskRequest(
            task_id="TASK-TEST",
            project_id="PROJ-001",
            agent_id="devops-01",
            role=AgentRole.DEVOPS,
            action="run_tests",
            instruction="Chạy unit tests",
        )
        res_test = devops_agent.handle(req_test)
        assert res_test.status == TaskStatus.COMPLETED

        # 4. deploy staging
        req_deploy = TaskRequest(
            task_id="TASK-DEPLOY",
            project_id="PROJ-001",
            agent_id="devops-01",
            role=AgentRole.DEVOPS,
            action="deploy",
            instruction="Deploy staging",
            context={
                "environment": "staging",
                "service_name": "web",
                "rollback_plan": ["docker compose down"],
            },
        )
        res_deploy = devops_agent.handle(req_deploy)
        assert res_deploy.status == TaskStatus.COMPLETED
        assert len(res_deploy.artifacts) == 1
        assert res_deploy.artifacts[0].type == ArtifactType.DEPLOYMENT

        # 5. health_check
        req_health = TaskRequest(
            task_id="TASK-HEALTH",
            project_id="PROJ-001",
            agent_id="devops-01",
            role=AgentRole.DEVOPS,
            action="health_check",
            instruction="Health check",
        )
        res_health = devops_agent.handle(req_health)
        assert res_health.status == TaskStatus.COMPLETED


class TestSubprocessExclusivity:
    """Kiểm tra quy tắc nghiêm ngặt: KHÔNG có chỗ nào gọi subprocess ngoài terminal.py."""

    def test_no_subprocess_outside_terminal(self):
        root_devops = Path(__file__).resolve().parent.parent
        violations = []

        for py_file in root_devops.rglob("*.py"):
            # Bỏ qua chính file terminal.py và test file
            if py_file.name == "terminal.py" or "tests" in py_file.parts:
                continue

            with open(py_file, "r", encoding="utf-8") as f:
                content = f.read()
                if "import subprocess" in content or "from subprocess" in content:
                    violations.append(str(py_file.relative_to(root_devops)))

        assert not violations, f"Phát hiện file gọi subprocess ngoài terminal.py: {violations}"
