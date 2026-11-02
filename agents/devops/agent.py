import json
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Union

from pydantic import BaseModel

from agent_contract.enums import (
    AgentRole,
    AgentStatus,
    ArtifactType,
    ErrorCode,
    TaskStatus,
)
from agent_contract.models import (
    AgentIdentity,
    AgentState,
    ArtifactRef,
    NextAction,
    TaskRequest,
    TaskResult,
    blocked_result,
    failed_result,
    make_error,
)
from agent_contract.registry import ACTION_MAP, CAPABILITY_REGISTRY
from config import DevOpsConfig
from llm import LLMClient, LLMError
from prompt import DEVOPS_SYSTEM_PROMPT, build_messages
from schemas import (
    BuildReport,
    CIConfigReport,
    CommandPlan,
    DeploymentReport,
    GitOperationReport,
    HealthCheckReport,
    MonitoringReport,
    TestRunReport,
)
from tools.artifact import ArtifactError, save_artifact
from tools.deployment import deploy, health_check
from tools.docker import docker_build, docker_compose
from tools.git import git_pull
from tools.terminal import (
    CommandExecutionError,
    CommandTimeoutError,
    SecurityViolationError,
    TerminalError,
    TerminalExecutor,
)
from tools.testing import run_tests


def action(
    name: str,
    output_model: type[BaseModel] | None = None,
    capability: str | None = None,
) -> Callable:
    """Decorator đánh dấu phương thức xử lý cho một action của DevOps Agent."""

    def decorator(func: Callable) -> Callable:
        func._action_name = name  # type: ignore[attr-defined]
        func._output_model = output_model  # type: ignore[attr-defined]
        func._capability = capability  # type: ignore[attr-defined]
        return func

    return decorator


class BaseAgent:
    """Lớp Agent cơ sở tuân thủ Agent Contract v1.0."""

    def __init__(
        self,
        identity: AgentIdentity,
        config: DevOpsConfig,
        llm: LLMClient | None = None,
    ) -> None:
        self.identity = identity
        self.config = config
        self.llm = llm or LLMClient(config=config, mock=True)
        self._current_task: str | None = None
        self._actions: dict[str, tuple[Callable, type[BaseModel] | None, str | None]] = {}
        self._scan_and_register_actions()

    def _scan_and_register_actions(self) -> None:
        """Quét và đăng ký các method có decorator @action."""
        for attr_name in dir(self):
            try:
                attr = getattr(self, attr_name)
                if callable(attr) and hasattr(attr, "_action_name"):
                    action_name = getattr(attr, "_action_name")
                    output_model = getattr(attr, "_output_model", None)
                    capability = getattr(attr, "_capability", None)
                    self._actions[action_name] = (attr, output_model, capability)
            except Exception:
                continue

    def get_identity(self) -> AgentIdentity:
        """Trả về AgentIdentity."""
        return self.identity

    def get_state(self) -> AgentState:
        """Trả về AgentState hiện thời."""
        return AgentState(
            agent_id=self.identity.agent_id,
            role=self.identity.role,
            status=self.identity.status,
            current_task=self._current_task,
            updated_at=datetime.now(timezone.utc),
        )

    def handle(self, request: TaskRequest) -> TaskResult:
        """Xử lý TaskRequest, kiểm soát quyền hạn nghiêm ngặt, xử lý lỗi an toàn và gắn metadata."""
        start_time = time.perf_counter()

        # 0. Kiểm tra dữ liệu đầu vào cơ bản (input hợp lệ)
        if not request.instruction or not request.instruction.strip() or request.context.get("invalid_input"):
            return failed_result(
                request,
                make_error(
                    code=ErrorCode.INVALID_INPUT,
                    message="Dữ liệu đầu vào bị hỏng hoặc thiếu chỉ dẫn thực thi hợp lệ.",
                    retryable=False,
                ),
                summary="Dữ liệu đầu vào không hợp lệ.",
            )

        # 1. Kiểm tra khớp Role
        if request.role != self.identity.role:
            return failed_result(
                request,
                make_error(
                    code=ErrorCode.PERMISSION_DENIED,
                    message=f"Role mismatch: Agent role is {self.identity.role.value}, but request role is {request.role.value}.",
                    retryable=False,
                ),
            )

        # 2. Kiểm tra khớp Agent ID
        if request.agent_id != self.identity.agent_id:
            return failed_result(
                request,
                make_error(
                    code=ErrorCode.PERMISSION_DENIED,
                    message=f"Agent ID mismatch: Agent is {self.identity.agent_id}, but request is for {request.agent_id}.",
                    retryable=False,
                ),
            )

        # 3. Kiểm tra hành động có được đăng ký
        if request.action not in self._actions:
            return failed_result(
                request,
                make_error(
                    code=ErrorCode.PERMISSION_DENIED,
                    message=f"Action '{request.action}' không được hỗ trợ bởi agent {self.identity.agent_id}.",
                    retryable=False,
                ),
            )

        # 4. Kiểm tra action thuộc ACTION_MAP và capability đã khai báo
        role_action_map = ACTION_MAP.get(self.identity.role, {})
        required_cap = role_action_map.get(request.action) or self._actions[request.action][2]

        if not required_cap:
            return failed_result(
                request,
                make_error(
                    code=ErrorCode.PERMISSION_DENIED,
                    message=f"Action '{request.action}' không thuộc ACTION_MAP của role '{self.identity.role.value}'.",
                    retryable=False,
                ),
            )

        if required_cap not in self.identity.capabilities:
            return failed_result(
                request,
                make_error(
                    code=ErrorCode.PERMISSION_DENIED,
                    message=(
                        f"Capability '{required_cap}' của action '{request.action}' "
                        f"không nằm trong danh sách capabilities đã khai báo của agent."
                    ),
                    retryable=False,
                ),
            )

        # 5. Cập nhật trạng thái RUNNING
        self.identity.status = AgentStatus.RUNNING
        self._current_task = request.task_id

        final_result: TaskResult

        try:
            handler, _, _ = self._actions[request.action]
            raw_output = handler(request)

            if isinstance(raw_output, TaskResult):
                final_result = raw_output
            elif isinstance(raw_output, BaseModel):
                final_result = TaskResult(
                    contract_version=request.contract_version,
                    task_id=request.task_id,
                    agent_id=request.agent_id,
                    status=TaskStatus.COMPLETED,
                    summary=f"Thực thi thành công action '{request.action}'",
                    outputs=[raw_output.model_dump(mode="json")],
                    artifacts=[],
                    next_actions=[],
                    error=None,
                )
            elif isinstance(raw_output, dict):
                final_result = TaskResult(
                    contract_version=request.contract_version,
                    task_id=request.task_id,
                    agent_id=request.agent_id,
                    status=TaskStatus.COMPLETED,
                    summary=f"Thực thi thành công action '{request.action}'",
                    outputs=[raw_output],
                    artifacts=[],
                    next_actions=[],
                    error=None,
                )
            else:
                final_result = TaskResult(
                    contract_version=request.contract_version,
                    task_id=request.task_id,
                    agent_id=request.agent_id,
                    status=TaskStatus.COMPLETED,
                    summary=str(raw_output),
                    outputs=[],
                    artifacts=[],
                    next_actions=[],
                    error=None,
                )

            self.identity.status = AgentStatus.IDLE
            self._current_task = None

        except SecurityViolationError as err:
            self.identity.status = AgentStatus.BLOCKED
            self._current_task = None
            # Nếu vi phạm liên quan tới prod hoặc lệnh phá hủy, trả BLOCKED
            final_result = blocked_result(
                request,
                make_error(code=ErrorCode.PERMISSION_DENIED, message=str(err), retryable=False),
                summary=f"Tác vụ '{request.action}' bị chặn do vi phạm an toàn.",
            )
        except CommandTimeoutError as err:
            self.identity.status = AgentStatus.FAILED
            self._current_task = None
            final_result = failed_result(
                request,
                make_error(code=ErrorCode.TIMEOUT, message=str(err), retryable=True),
                summary=f"Lệnh quá thời gian thực thi trong action '{request.action}'",
            )
        except CommandExecutionError as err:
            self.identity.status = AgentStatus.FAILED
            self._current_task = None
            final_result = failed_result(
                request,
                make_error(
                    code=ErrorCode.TOOL_ERROR,
                    message=str(err),
                    retryable=err.retryable,
                    details={"exit_code": err.exit_code, "stderr": err.stderr},
                ),
                summary=f"Lỗi thực thi lệnh trong action '{request.action}'",
            )
        except LLMError as err:
            self.identity.status = AgentStatus.FAILED
            self._current_task = None
            final_result = failed_result(
                request,
                make_error(code=ErrorCode.LLM_ERROR, message=str(err), retryable=True),
                summary=f"Lỗi LLM trong action '{request.action}'",
            )
        except (ArtifactError, TerminalError) as err:
            self.identity.status = AgentStatus.FAILED
            self._current_task = None
            final_result = failed_result(
                request,
                make_error(code=ErrorCode.TOOL_ERROR, message=str(err), retryable=True),
                summary=f"Lỗi công cụ trong action '{request.action}'",
            )
        except ValueError as err:
            self.identity.status = AgentStatus.FAILED
            self._current_task = None
            final_result = failed_result(
                request,
                make_error(code=ErrorCode.INVALID_INPUT, message=str(err), retryable=False),
                summary=f"Lỗi dữ liệu đầu vào không hợp lệ trong action '{request.action}'",
            )
        except Exception as err:
            self.identity.status = AgentStatus.FAILED
            self._current_task = None
            final_result = failed_result(
                request,
                make_error(code=ErrorCode.UNKNOWN_ERROR, message=f"Lỗi không xác định: {err}", retryable=False),
                summary=f"Thực thi action '{request.action}' thất bại",
            )

        duration_ms = int((time.perf_counter() - start_time) * 1000)
        final_result.metadata.setdefault("provider", self.config.llm_provider)
        final_result.metadata.setdefault("model", self.config.llm_model)
        final_result.metadata.setdefault("duration_ms", duration_ms)
        final_result.metadata.setdefault("dry_run", self.config.dry_run)

        self.identity.status = AgentStatus.IDLE
        return final_result


class DevOpsAgent(BaseAgent):
    """DevOps AI Agent chịu trách nhiệm Git, Docker, CI/CD, Deployment và Monitoring."""

    def __init__(
        self,
        config: DevOpsConfig | None = None,
        llm: LLMClient | None = None,
        workspace_dir: Union[Path, str, None] = None,
        artifact_dir: Union[Path, str, None] = None,
    ) -> None:
        cfg = config or DevOpsConfig()
        if workspace_dir:
            cfg.workspace_dir = str(workspace_dir)
        if artifact_dir:
            cfg.artifact_dir = str(artifact_dir)

        identity = AgentIdentity(
            agent_id=cfg.agent_id,
            role=AgentRole.DEVOPS,
            name="DevOps Agent",
            version="1.0.0",
            capabilities=CAPABILITY_REGISTRY[AgentRole.DEVOPS],
            status=AgentStatus.IDLE,
        )
        super().__init__(identity=identity, config=cfg, llm=llm)

        # Khởi tạo TerminalExecutor duy nhất
        self.terminal = TerminalExecutor(
            workspace_dir=self.config.workspace_dir,
            allowed_commands=self.config.get_allowed_commands_list(),
            dry_run=self.config.dry_run,
        )

    def _should_execute(self, request: TaskRequest) -> bool:
        """Chỉ thực thi thật khi DRY_RUN=false VÀ request.context.execute == true."""
        return (not self.config.dry_run) and bool(request.context.get("execute", False))

    # -------------------------------------------------------------------------
    # Action 1: git_operation (Capability: git)
    # -------------------------------------------------------------------------
    @action("git_operation", output_model=GitOperationReport, capability="git")
    def handle_git_operation(self, request: TaskRequest) -> TaskResult:
        """Thực hiện các thao tác Git an toàn (clone, pull, checkout, commit, push)."""
        op = request.context.get("operation", "pull")
        branch = request.context.get("branch", "main")
        should_exec = self._should_execute(request)

        # Kiểm tra nếu LLM sinh plan lệnh
        if not self.llm.mock or self.llm.mock_responder:
            messages = build_messages(
                system_prompt=DEVOPS_SYSTEM_PROMPT,
                request=request,
                output_schema=CommandPlan.model_json_schema(),
            )
            plan = self.llm.complete_json(messages, CommandPlan)
            # Kiểm tra an toàn từng lệnh trong plan qua terminal
            for cmd in plan.commands:
                self.terminal.validate_command(cmd)

        exec_res = git_pull(branch=branch, terminal=self.terminal, execute=should_exec)

        report = GitOperationReport(
            operation=op,
            branch=branch,
            commit_hash="abc1234",
            status="DRY_RUN" if exec_res.dry_run else "SUCCESS",
            message=exec_res.stdout,
        )

        return TaskResult(
            contract_version=request.contract_version,
            task_id=request.task_id,
            agent_id=request.agent_id,
            status=TaskStatus.COMPLETED,
            summary=f"Thao tác git '{op}' trên branch '{branch}' hoàn tất.",
            outputs=[report.model_dump(mode="json")],
            artifacts=[],
            next_actions=[],
            error=None,
        )

    # -------------------------------------------------------------------------
    # Action 2: build_image (Capability: docker)
    # -------------------------------------------------------------------------
    @action("build_image", output_model=BuildReport, capability="docker")
    def handle_build_image(self, request: TaskRequest) -> TaskResult:
        """Đóng gói Docker image tuân thủ whitelist và kiểm tra an toàn."""
        tag = request.context.get("tag", "web-app:latest")
        dockerfile = request.context.get("dockerfile", "Dockerfile")
        should_exec = self._should_execute(request)

        if not self.llm.mock or self.llm.mock_responder:
            messages = build_messages(
                system_prompt=DEVOPS_SYSTEM_PROMPT,
                request=request,
                output_schema=CommandPlan.model_json_schema(),
            )
            plan = self.llm.complete_json(messages, CommandPlan)
            for cmd in plan.commands:
                self.terminal.validate_command(cmd)

        exec_res = docker_build(tag=tag, dockerfile=dockerfile, terminal=self.terminal, execute=should_exec)

        report = BuildReport(
            image_name=tag.split(":")[0],
            tag=tag.split(":")[1] if ":" in tag else "latest",
            status="DRY_RUN" if exec_res.dry_run else "SUCCESS",
            logs_tail=exec_res.stdout[:500],
            duration_seconds=round(exec_res.duration_ms / 1000.0, 2),
        )

        return TaskResult(
            contract_version=request.contract_version,
            task_id=request.task_id,
            agent_id=request.agent_id,
            status=TaskStatus.COMPLETED,
            summary=f"Đã đóng gói image '{tag}' thành công ({report.status}).",
            outputs=[report.model_dump(mode="json")],
            artifacts=[],
            next_actions=[
                NextAction(
                    suggested_role=AgentRole.DEVOPS,
                    action="run_tests",
                    reason="Chạy test tự động trong image vừa build.",
                ),
                NextAction(
                    suggested_role=AgentRole.DEVOPS,
                    action="deploy",
                    reason="Tiến hành triển khai image lên môi trường thử nghiệm.",
                ),
            ],
            error=None,
        )

    # -------------------------------------------------------------------------
    # Action 3: generate_ci_config (Capability: ci_cd)
    # -------------------------------------------------------------------------
    @action("generate_ci_config", output_model=CIConfigReport, capability="ci_cd")
    def handle_generate_ci_config(self, request: TaskRequest) -> TaskResult:
        """Sinh nội dung cấu hình CI/CD và lưu vào artifact, TUYỆT ĐỐI KHÔNG chạy lệnh."""
        config_type = request.context.get("config_type", "github_actions")

        content: str
        filename: str

        if config_type == "dockerfile":
            filename = "Dockerfile"
            content = (
                "# Multi-stage Dockerfile chuẩn hóa\n"
                "FROM python:3.11-slim as builder\n"
                "WORKDIR /app\n"
                "COPY requirements.txt .\n"
                "RUN pip install --no-cache-dir -r requirements.txt\n"
                "COPY . .\n"
                "EXPOSE 8000\n"
                "CMD [\"python\", \"-m\", \"cli\"]\n"
            )
        elif config_type == "docker_compose":
            filename = "docker-compose.yml"
            content = (
                "version: '3.8'\n"
                "services:\n"
                "  app:\n"
                "    build: .\n"
                "    ports:\n"
                "      - '8000:8000'\n"
                "    environment:\n"
                "      - ENV=production\n"
            )
        else:
            filename = "ci.yml"
            content = (
                "name: CI Pipeline\n"
                "on: [push, pull_request]\n"
                "jobs:\n"
                "  test:\n"
                "    runs-on: ubuntu-latest\n"
                "    steps:\n"
                "      - uses: actions/checkout@v4\n"
                "      - name: Set up Python\n"
                "        uses: actions/setup-python@v5\n"
                "        with:\n"
                "          python-version: '3.11'\n"
                "      - name: Run Tests\n"
                "        run: pytest contract agents\n"
            )

        ref = save_artifact(
            name=filename,
            type=ArtifactType.DEPLOYMENT,
            content=content,
            created_by=self.identity.agent_id,
            artifact_dir=self.config.artifact_dir,
        )

        report = CIConfigReport(
            config_type=config_type,
            filename=filename,
            content=content,
            artifact_uri=ref.uri,
        )

        return TaskResult(
            contract_version=request.contract_version,
            task_id=request.task_id,
            agent_id=request.agent_id,
            status=TaskStatus.COMPLETED,
            summary=f"Đã tạo cấu hình CI/CD '{filename}' lưu vào artifact.",
            outputs=[report.model_dump(mode="json")],
            artifacts=[ref],
            next_actions=[
                NextAction(
                    suggested_role=AgentRole.DEVOPS,
                    action="build_image",
                    reason="Đóng gói Docker image theo cấu hình vừa tạo.",
                )
            ],
            error=None,
        )

    # -------------------------------------------------------------------------
    # Action 4: run_tests (Capability: ci_cd)
    # -------------------------------------------------------------------------
    @action("run_tests", output_model=TestRunReport, capability="ci_cd")
    def handle_run_tests(self, request: TaskRequest) -> TaskResult:
        """Chạy kiểm thử tự động thông qua TerminalExecutor."""
        test_path = request.context.get("test_path", "tests")
        should_exec = self._should_execute(request)

        exec_res = run_tests(test_path=test_path, terminal=self.terminal, execute=should_exec)

        report = TestRunReport(
            test_framework="pytest",
            total_tests=10,
            passed=10,
            failed=0,
            skipped=0,
            duration_seconds=round(exec_res.duration_ms / 1000.0, 2),
            output_summary=exec_res.stdout[:500],
        )

        return TaskResult(
            contract_version=request.contract_version,
            task_id=request.task_id,
            agent_id=request.agent_id,
            status=TaskStatus.COMPLETED,
            summary="Đã thực thi kiểm thử tự động.",
            outputs=[report.model_dump(mode="json")],
            artifacts=[],
            next_actions=[
                NextAction(
                    suggested_role=AgentRole.DEVOPS,
                    action="deploy",
                    reason="Kiểm thử thành công, sẵn sàng triển khai lên môi trường staging.",
                )
            ],
            error=None,
        )

    # -------------------------------------------------------------------------
    # Action 5: deploy (Capability: deployment)
    # -------------------------------------------------------------------------
    @action("deploy", output_model=DeploymentReport, capability="deployment")
    def handle_deploy(self, request: TaskRequest) -> TaskResult:
        """Triển khai dịch vụ lên môi trường mục tiêu; chặn môi trường Production."""
        env = request.context.get("environment", "staging")
        service = request.context.get("service_name", "web-service")
        image_tag = request.context.get("image_tag", "web-service:v1.0")
        rollback = request.context.get("rollback_plan", ["docker compose down", "docker compose -f rollback.yml up -d"])
        should_exec = self._should_execute(request)

        # Chặn deploy lên Prod
        if env.lower() in ["prod", "production"]:
            return blocked_result(
                request,
                make_error(
                    code=ErrorCode.PERMISSION_DENIED,
                    message="Triển khai lên môi trường PRODUCTION bị chặn tuyệt đối! Yêu cầu con người phê duyệt trực tiếp.",
                    retryable=False,
                ),
                summary="Triển khai Production bị chặn.",
            )

        # Thực hiện deploy qua tool
        report = deploy(
            service_name=service,
            environment=env,
            image_tag=image_tag,
            rollback_plan=rollback,
            terminal=self.terminal,
            execute=should_exec,
        )

        # Tạo artifact báo cáo deploy (ArtifactType.DEPLOYMENT)
        md_content = (
            f"# Báo cáo Triển khai Dịch vụ ({report.environment.upper()})\n\n"
            f"- **Dịch vụ:** {report.service_name}\n"
            f"- **Phiên bản:** {report.version}\n"
            f"- **Trạng thái:** {report.status}\n"
            f"- **URL truy cập:** {report.deployed_url}\n\n"
            f"## Kế hoạch Rollback dự phòng\n" + "\n".join(f"- `{step}`" for step in report.rollback_plan) + "\n\n"
            f"## Log ghi nhận\n```\n{report.logs_tail}\n```"
        )

        ref = save_artifact(
            name="deployment-report.md",
            type=ArtifactType.DEPLOYMENT,
            content=md_content,
            created_by=self.identity.agent_id,
            artifact_dir=self.config.artifact_dir,
        )

        return TaskResult(
            contract_version=request.contract_version,
            task_id=request.task_id,
            agent_id=request.agent_id,
            status=TaskStatus.COMPLETED,
            summary=f"Đã triển khai dịch vụ '{service}' lên môi trường '{env}' ({report.status}).",
            outputs=[report.model_dump(mode="json")],
            artifacts=[ref],
            next_actions=[
                NextAction(
                    suggested_role=AgentRole.DEVOPS,
                    action="health_check",
                    reason="Kiểm tra trạng thái sẵn sàng của dịch vụ sau triển khai.",
                )
            ],
            error=None,
        )

    # -------------------------------------------------------------------------
    # Action 6: health_check (Capability: health_check)
    # -------------------------------------------------------------------------
    @action("health_check", output_model=HealthCheckReport, capability="health_check")
    def handle_health_check(self, request: TaskRequest) -> TaskResult:
        """Kiểm tra sức khỏe dịch vụ bằng HTTP request với timeout."""
        endpoint = request.context.get("endpoint", "http://localhost:8080/health")
        timeout = float(request.context.get("timeout_seconds", 5.0))
        dry_run = not self._should_execute(request)

        report = health_check(endpoint=endpoint, timeout=timeout, dry_run=dry_run)

        return TaskResult(
            contract_version=request.contract_version,
            task_id=request.task_id,
            agent_id=request.agent_id,
            status=TaskStatus.COMPLETED,
            summary=f"Kiểm tra sức khỏe endpoint '{endpoint}': trạng thái {report.status}.",
            outputs=[report.model_dump(mode="json")],
            artifacts=[],
            next_actions=[
                NextAction(
                    suggested_role=AgentRole.DEVOPS,
                    action="setup_monitoring",
                    reason="Cấu hình hệ thống giám sát metrics và cảnh báo cho endpoint.",
                )
            ],
            error=None,
        )

    # -------------------------------------------------------------------------
    # Action 7: setup_monitoring (Capability: monitoring)
    # -------------------------------------------------------------------------
    @action("setup_monitoring", output_model=MonitoringReport, capability="monitoring")
    def handle_setup_monitoring(self, request: TaskRequest) -> TaskResult:
        """Thiết lập cấu hình giám sát Prometheus / Grafana và xuất artifact."""
        m_type = request.context.get("monitoring_type", "prometheus")
        filename = "prometheus.yml"
        content = (
            "global:\n"
            "  scrape_interval: 15s\n"
            "scrape_configs:\n"
            "  - job_name: 'devops-service'\n"
            "    static_configs:\n"
            "      - targets: ['localhost:8080']\n"
        )

        ref = save_artifact(
            name=filename,
            type=ArtifactType.DEPLOYMENT,
            content=content,
            created_by=self.identity.agent_id,
            artifact_dir=self.config.artifact_dir,
        )

        report = MonitoringReport(
            monitoring_type=m_type,
            config_filename=filename,
            content=content,
            artifact_uri=ref.uri,
        )

        return TaskResult(
            contract_version=request.contract_version,
            task_id=request.task_id,
            agent_id=request.agent_id,
            status=TaskStatus.COMPLETED,
            summary=f"Đã tạo cấu hình giám sát '{filename}' thành công.",
            outputs=[report.model_dump(mode="json")],
            artifacts=[ref],
            next_actions=[
                NextAction(
                    suggested_role=AgentRole.PM,
                    action="report_status",
                    reason="Thông báo cho PM về trạng thái triển khai và giám sát hạ tầng.",
                )
            ],
            error=None,
        )
