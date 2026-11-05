from pathlib import Path
import hashlib
import time
from datetime import datetime, timezone
from typing import Any, Callable, TypeVar

from pydantic import BaseModel

from agent_contract.enums import AgentRole, AgentStatus, ErrorCode, TaskStatus
from agent_contract.models import (
    AgentIdentity,
    AgentState,
    TaskRequest,
    TaskResult,
    blocked_result,
    failed_result,
    make_error,
)
from agent_contract.registry import ACTION_MAP, CAPABILITY_REGISTRY
from config import AgentConfig
from llm import LLMClient, LLMError
from prompt import build_messages
from schemas import EchoOutput
from tools.artifact import ArtifactError

T = TypeVar("T", bound=BaseModel)


def action(
    name: str,
    output_model: type[BaseModel] | None = None,
    capability: str | None = None,
) -> Callable:
    """Decorator đánh dấu phương thức là hàm xử lý cho một action cụ thể."""

    def decorator(func: Callable) -> Callable:
        func._action_name = name  # type: ignore[attr-defined]
        func._output_model = output_model  # type: ignore[attr-defined]
        func._capability = capability  # type: ignore[attr-defined]
        return func

    return decorator


class BaseAgent:
    """Lớp Agent cơ sở chuẩn hóa giao thức, xử lý vòng đời tác vụ và an toàn ngoại lệ."""

    def __init__(
        self,
        identity: AgentIdentity,
        config: AgentConfig,
        llm: LLMClient | None = None,
    ) -> None:
        self.identity = identity
        self.config = config
        self.llm = llm or LLMClient(config=config, mock=True)
        self._current_task: str | None = None

        # Tự động đăng ký các action được gắn decorator @action
        self._actions: dict[str, tuple[Callable, type[BaseModel] | None, str | None]] = {}
        self._scan_and_register_actions()

    def _scan_and_register_actions(self) -> None:
        """Quét và đăng ký tất cả các method có decorator @action."""
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

    def register_action(
        self,
        name: str,
        handler: Callable,
        output_model: type[BaseModel] | None = None,
        capability: str | None = None,
    ) -> None:
        """Đăng ký thủ công hàm xử lý cho một action."""
        self._actions[name] = (handler, output_model, capability)

    def get_identity(self) -> AgentIdentity:
        """Trả về thông tin định danh và năng lực của Agent."""
        return self.identity

    def get_state(self) -> AgentState:
        """Trả về trạng thái hiện thời của Agent phục vụ Dashboard hoặc Orchestrator."""
        return AgentState(
            agent_id=self.identity.agent_id,
            role=self.identity.role,
            status=self.identity.status,
            current_task=self._current_task,
            updated_at=datetime.now(timezone.utc),
        )

    def handle(self, request: TaskRequest) -> TaskResult:
        """Xử lý tác vụ TaskRequest, kiểm tra quyền hạn, bắt ngoại lệ và trả về TaskResult chuẩn."""
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
                    message=(
                        f"Sai vai trò: Agent có role '{self.identity.role.value}', "
                        f"nhưng TaskRequest yêu cầu role '{request.role.value}'."
                    ),
                    retryable=False,
                ),
            )

        # 2. Kiểm tra khớp Agent ID
        if request.agent_id != self.identity.agent_id:
            return failed_result(
                request,
                make_error(
                    code=ErrorCode.PERMISSION_DENIED,
                    message=(
                        f"Sai mã định danh: Agent có id '{self.identity.agent_id}', "
                        f"nhưng TaskRequest gửi tới '{request.agent_id}'."
                    ),
                    retryable=False,
                ),
            )

        # 3. Kiểm tra hành động (action) có được đăng ký không
        if request.action not in self._actions:
            return failed_result(
                request,
                make_error(
                    code=ErrorCode.PERMISSION_DENIED,
                    message=f"Action '{request.action}' không được hỗ trợ bởi agent '{self.identity.agent_id}'.",
                    retryable=False,
                ),
            )

        # 4. Kiểm tra action thuộc ACTION_MAP và capability đã khai báo
        role_action_map = ACTION_MAP.get(self.identity.role, {})
        required_cap: str | None = None
        if request.action in role_action_map:
            required_cap = role_action_map[request.action]
        else:
            # Lấy capability từ metadata của action decorator
            required_cap = self._actions[request.action][2]

        if request.action != "echo":
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

        # 4b. Kiểm tra input_artifacts đã có trong inbox/ và khớp checksum chưa
        if request.input_artifacts:
            missing_artifacts = []
            inbox_dir = Path(self.config.artifact_dir) / "inbox"
            for art in request.input_artifacts:
                art_file = None
                if art.uri:
                    clean_uri = art.uri.replace("\\", "/").strip().lstrip("/")
                    cand1 = (Path(self.config.artifact_dir).parent / clean_uri).resolve()
                    if cand1.exists() and cand1.is_file():
                        art_file = cand1
                    else:
                        cand2 = (Path(self.config.artifact_dir) / Path(clean_uri).name).resolve()
                        if cand2.exists() and cand2.is_file():
                            art_file = cand2

                if not art_file and inbox_dir.exists():
                    for cand in [
                        inbox_dir / art.created_by / art.name,
                        inbox_dir / art.name,
                    ]:
                        if cand.exists() and cand.is_file():
                            art_file = cand
                            break

                if not art_file and inbox_dir.exists():
                    for f in inbox_dir.rglob(art.name):
                        if f.is_file():
                            art_file = f
                            break

                if not art_file or not art_file.exists():
                    missing_artifacts.append(art.artifact_id)
                elif art.checksum:
                    with open(art_file, "rb") as f:
                        file_sha = hashlib.sha256(f.read()).hexdigest()
                    if file_sha.lower() != art.checksum.lower():
                        missing_artifacts.append(art.artifact_id)

            if missing_artifacts:
                return blocked_result(
                    request,
                    make_error(
                        code=ErrorCode.MISSING_CONTEXT,
                        message="Thiếu artifact đầu vào trong thư mục inbox hoặc sai lệch checksum SHA-256.",
                        retryable=False,
                        missing_artifacts=missing_artifacts,
                    ),
                    summary="Bị chặn do thiếu artifact đầu vào trong inbox.",
                )

        # 5. Cập nhật trạng thái RUNNING
        self.identity.status = AgentStatus.RUNNING
        self._current_task = request.task_id

        final_result: TaskResult

        try:
            handler, output_model, _ = self._actions[request.action]
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

        except LLMError as err:
            self.identity.status = AgentStatus.FAILED
            self._current_task = None
            final_result = failed_result(
                request,
                make_error(code=ErrorCode.LLM_ERROR, message=str(err), retryable=True),
                summary=f"Lỗi LLM khi thực thi action '{request.action}'",
            )
        except ArtifactError as err:
            self.identity.status = AgentStatus.FAILED
            self._current_task = None
            final_result = failed_result(
                request,
                make_error(code=ErrorCode.TOOL_ERROR, message=str(err), retryable=True),
                summary=f"Lỗi công cụ artifact khi thực thi action '{request.action}'",
            )
        except ValueError as err:
            self.identity.status = AgentStatus.FAILED
            self._current_task = None
            final_result = failed_result(
                request,
                make_error(code=ErrorCode.INVALID_INPUT, message=str(err), retryable=False),
                summary=f"Lỗi dữ liệu đầu vào không hợp lệ khi thực thi action '{request.action}'",
            )
        except Exception as err:
            self.identity.status = AgentStatus.FAILED
            self._current_task = None
            final_result = failed_result(
                request,
                make_error(code=ErrorCode.UNKNOWN_ERROR, message=f"Ngoại lệ không xác định: {err}", retryable=False),
                summary=f"Thực thi action '{request.action}' thất bại",
            )

        # 6. Gắn metadata tiêu chuẩn
        duration_ms = int((time.perf_counter() - start_time) * 1000)
        final_result.metadata.setdefault("provider", self.config.llm_provider)
        final_result.metadata.setdefault("model", self.config.llm_model)
        final_result.metadata.setdefault("duration_ms", duration_ms)
        final_result.metadata.setdefault("dry_run", self.config.dry_run)

        # Reset lại status về IDLE sau khi đã đóng gói TaskResult
        self.identity.status = AgentStatus.IDLE

        return final_result

    @action("echo", output_model=EchoOutput)
    def handle_echo(self, request: TaskRequest) -> EchoOutput:
        """Hành động mẫu 'echo' trả về cấu trúc EchoOutput để chứng minh luồng thực thi."""
        if self.llm and not self.llm.mock:
            messages = build_messages(
                system_prompt="Bạn là trợ lý echo. Hãy đọc instruction và context rồi trả về JSON theo schema EchoOutput.",
                request=request,
                output_schema=EchoOutput.model_json_schema(),
            )
            return self.llm.complete_json(messages, EchoOutput)
        elif self.llm and self.llm.mock and self.llm.mock_responder:
            messages = build_messages(
                system_prompt="Mock system prompt cho echo",
                request=request,
                output_schema=EchoOutput.model_json_schema(),
            )
            return self.llm.complete_json(messages, EchoOutput)
        else:
            return EchoOutput(
                received_instruction=request.instruction,
                received_action=request.action,
                received_context=request.context,
                reply=f"Echoed: {request.instruction}",
            )


import json
from collections import Counter
from agent_contract.enums import ArtifactType, TaskStatus
from agent_contract.models import TaskResult
from tools.artifact import save_artifact
from tools.ai_review import review_report_with_antigravity
from tools.skills import load_skill
from tools.history import normalize_tasks, observe, commit
from tools.module_review import build_module_review


class ScrumMasterAgent(BaseAgent):
    """Tính KPI từ dữ liệu PM gửi, không tự bịa trạng thái task."""

    def _append_ai_advice(self, report: str, skill_text: str) -> tuple[str, dict, str]:
        backend = self.config.sm_backend.lower().strip()
        if backend not in ("rules", "antigravity"):
            raise ValueError(f"SM_BACKEND không hợp lệ: {backend}")
        info = {"used": False, "status": "disabled", "reason": "rules_backend_or_dry_run"}
        if backend == "antigravity" and not self.config.dry_run:
            info = review_report_with_antigravity(report, timeout_seconds=self.config.sm_timeout_seconds,
                workspace=Path(self.config.workspace_dir) / "scrum_ai_review", skill_instructions=skill_text)
            if info["used"]:
                report += "\n" + info["review"] + "\n"
            else:
                report += ("\n## Trạng thái tích hợp AI\n\n"
                    "- AI không chạy thành công; giữ báo cáo dựa trên dữ liệu PM. "
                    "Kiểm tra CLI, đăng nhập và quota trên máy chạy Scrum Master.\n")
        return report, info, backend

    @staticmethod
    def _report(request: TaskRequest, retrospective: bool) -> tuple[str, dict]:
        normalized = normalize_tasks(request.context)
        counts = Counter(t["status"] for t in normalized)
        total = len(normalized)
        done = counts.get("COMPLETED", 0) + counts.get("DONE", 0)
        blockers = [t for t in normalized if t["status"] in ("BLOCKED", "FAILED") or t["blocked_reason"]]
        pct = round(100 * done / total, 1) if total else None
        title = "Retrospective" if retrospective else "Theo dõi blocker"
        lines = [f"# {title} – {request.project_id}", "", f"- Mô tả: {request.instruction}",
                 f"- Số task có dữ liệu: {total}", f"- Task hoàn thành: {done}",
                 f"- Tỷ lệ: {pct}%" if pct is not None else "- Tỷ lệ: chưa đủ dữ liệu", "",
                 "## Trạng thái", ""]
        if normalized:
            lines += [f"- {k}: {v}" for k,v in sorted(counts.items())]
        else:
            lines += ["Không có snapshot task trong context.tasks; không suy đoán số liệu."]
        lines += ["", "## Blockers", ""]
        if blockers:
            lines += [f"- {t['id']}: {t['blocked_reason'] or t['status']}" for t in blockers]
        else:
            lines += ["Chưa ghi nhận blocker trong snapshot được cung cấp."]
        lines += ["", "## Khuyến nghị", ""]
        if blockers:
            lines += ["- PM xem lại task bị chặn, xác định phụ thuộc và giao bước xử lý phù hợp."]
        else:
            lines += ["- PM tiếp tục theo dõi trạng thái; chỉ kết luận hoàn tất sau khi Tester/DevOps có bằng chứng."]
        if retrospective:
            lines += ["", "## Bài học", "", "- Đối chiếu task, artifact và kết quả kiểm thử.",
                      "- Báo cáo phản ánh dữ liệu đã quan sát, không suy đoán lịch sử Sprint chưa được cung cấp."]
        return "\n".join(lines) + "\n", {"total":total,"done":done,"percentage":pct,"blocked":len(blockers),
            "status_counts":dict(counts), "blockers": blockers, "snapshot_provided": "tasks" in request.context}

    def _run(self, request: TaskRequest, retrospective: bool) -> TaskResult:
        skill_name, skill_text = load_skill(request.action)
        report, metrics = self._report(request, retrospective)
        history, history_path, history_state = observe(self.config.data_dir, request.project_id,
            request.task_id, normalize_tasks(request.context), snapshot_provided="tasks" in request.context)
        metrics["history"] = history
        report += "\n## Lịch sử quan sát blocker\n\n"
        for key, label in [("new", "Mới"), ("persistent", "Còn tồn tại"),
                           ("resolved", "Đã gỡ theo snapshot"), ("not_observed", "Chưa có quan sát mới")]:
            report += f"- {label}: " + (", ".join(item["id"] for item in history[key]) or "Không") + "\n"
        report += "\nTuổi blocker tính từ lần agent ghi nhận đầu tiên, không phải thời điểm lỗi thực sự bắt đầu.\n"
        report += "\n```json\n" + json.dumps(history, ensure_ascii=False) + "\n```\n"
        report, ai_info, sm_backend = self._append_ai_advice(report, skill_text)
        safeid = ''.join(ch if ch.isalnum() or ch in '_-' else '_' for ch in request.task_id)[:80]
        ref = save_artifact(name=f"scrum_{safeid}.md", type=ArtifactType.DOCUMENTATION,
            content=report, created_by=self.identity.agent_id, artifact_dir=self.config.artifact_dir)
        commit(history_path, history_state)
        return TaskResult(contract_version=request.contract_version, task_id=request.task_id,
            agent_id=request.agent_id, status=TaskStatus.COMPLETED,
            summary="Đã tạo báo cáo Scrum Master từ trạng thái được cung cấp.",
            artifacts=[ref], outputs=[metrics], metadata={
                "backend": sm_backend,
                "skill": skill_name,
                "skill_applied": ai_info["used"],
                "ai_used": ai_info["used"],
                "ai_status": ai_info["status"],
                "ai_reason": ai_info.get("reason", ""),
                "has_task_snapshot": bool(metrics["total"]),
            })

    @action("track_blockers", capability="blocker_tracking")
    def track_blockers(self, request: TaskRequest) -> TaskResult:
        return self._run(request, retrospective=False)

    @action("run_retrospective", capability="retrospective")
    def run_retrospective(self, request: TaskRequest) -> TaskResult:
        return self._run(request, retrospective=True)

    @action("review_module", capability="scrum_management")
    def review_module(self, request: TaskRequest) -> TaskResult:
        skill_name, skill_text = load_skill(request.action)
        report, output = build_module_review(request, self.config.artifact_dir)
        # Missing context is handled deterministically; avoid spending an AI call
        # to explain the absence of essential evidence.
        if output["missing_inputs"]:
            backend = self.config.sm_backend.lower().strip()
            if backend not in ("rules", "antigravity"):
                raise ValueError(f"SM_BACKEND không hợp lệ: {backend}")
            ai_info = {"used": False, "status": "disabled", "reason": "missing_module_context"}
        else:
            report, ai_info, backend = self._append_ai_advice(report, skill_text)
        safeid = ''.join(ch if ch.isalnum() or ch in '_-' else '_' for ch in request.task_id)[:80]
        ref = save_artifact(name=f"scrum_module_review_{safeid}.md", type=ArtifactType.DOCUMENTATION,
            content=report, created_by=self.identity.agent_id, artifact_dir=self.config.artifact_dir)
        passed = output["can_start_next_module"]
        return TaskResult(contract_version=request.contract_version, task_id=request.task_id,
            agent_id=request.agent_id, status=TaskStatus.COMPLETED if passed else TaskStatus.BLOCKED,
            summary=f"Review module {output['module_id'] or '(chưa có ID)'}: {output['verdict']}.",
            outputs=[output], artifacts=[ref],
            error=None if passed else make_error(
                ErrorCode.MISSING_CONTEXT if output["missing_inputs"] else ErrorCode.VALIDATION_ERROR,
                "Chưa đủ điều kiện chuyển module; PM xem báo cáo review.", retryable=False,
                missing_inputs=output["missing_inputs"], reasons=output["reasons"]),
            metadata={"backend": backend, "skill": skill_name, "skill_applied": ai_info["used"],
                "ai_used": ai_info["used"], "ai_status": ai_info["status"],
                "ai_reason": ai_info.get("reason", ""), "review_type": "module_review"})
