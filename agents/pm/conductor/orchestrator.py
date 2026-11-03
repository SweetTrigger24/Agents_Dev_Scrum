import asyncio
import logging
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

from agent_contract.enums import AgentRole, AgentStatus, ArtifactType, ErrorCode, Priority, TaskStatus
from agent_contract.models import ArtifactRef, Constraints, TaskRequest, TaskResult
from conductor.dispatcher import (
    find_agent_id_for_role,
    load_endpoints,
    relay_input_artifacts,
    send_task_request,
)
from conductor.gates import (
    GATE_APPROVE_DEPLOY,
    GATE_APPROVE_SCOPE,
    approve_gate as gate_approve,
    handle_gate_step,
    should_execute_real_deploy,
)
from conductor.policy import (
    generate_answers_for_missing_context,
    parse_verdict,
    should_trigger_fix_loop,
)
from conductor.release import package_release
from conductor.state import (
    ArtifactRecord,
    ProjectState,
    ProjectStatus,
    StepState,
    StepStatus,
    append_project_event,
    get_project_dir,
    list_all_projects,
    load_project_state,
    save_project_state,
)

logger = logging.getLogger("pm.conductor.orchestrator")
CURRENT_DIR = Path(__file__).resolve().parent
WORKFLOW_PATH = CURRENT_DIR / "workflows" / "software_delivery.yaml"


class ConductorOrchestrator:
    """Động cơ điều phối trung tâm của PM Conductor thực thi quy trình theo workflow YAML."""

    def __init__(
        self,
        data_dir: Path | str,
        artifact_dir: Path | str,
        config: Any = None,
        llm_client: Any = None,
        agent_identity: Any = None,
    ) -> None:
        self.data_dir = Path(data_dir).resolve()
        self.artifact_dir = Path(artifact_dir).resolve()
        self.config = config
        self.llm_client = llm_client
        self.agent_identity = agent_identity
        self.workflow_def = self._load_workflow()

    def _load_workflow(self) -> dict[str, Any]:
        if not WORKFLOW_PATH.exists():
            raise FileNotFoundError(f"Không tìm thấy file workflow tại {WORKFLOW_PATH}")
        with open(WORKFLOW_PATH, "r", encoding="utf-8") as f:
            return yaml.safe_load(f)

    def _update_pm_status(self, status: AgentStatus, current_task: str | None = None) -> None:
        """Cập nhật trạng thái tự khai báo của PM Agent (RUNNING, WAITING, BLOCKED, IDLE)."""
        if self.agent_identity:
            self.agent_identity.status = status

    def init_project(
        self,
        project_id: str,
        brief: str,
        auto_approve: bool = False,
    ) -> ProjectState:
        """Khởi tạo cấu trúc ProjectState từ workflow YAML."""
        steps_dict: dict[str, StepState] = {}
        for s in self.workflow_def.get("steps", []):
            sid = s["id"]
            steps_dict[sid] = StepState(
                id=sid,
                role=s.get("role"),
                action=s.get("action"),
                gate=s.get("gate"),
                status=StepStatus.PENDING,
            )

        state = ProjectState(
            project_id=project_id,
            brief=brief,
            status=ProjectStatus.CREATED,
            auto_approve=auto_approve or getattr(self.config, "pm_auto_approve", False),
            allow_real_deploy=getattr(self.config, "pm_allow_real_deploy", False),
            steps=steps_dict,
        )
        save_project_state(state, self.data_dir)
        append_project_event(project_id, "PROJECT_CREATED", {"brief": brief[:100]}, self.data_dir)
        return state

    def run_pipeline(self, state: ProjectState) -> ProjectState:
        """Chạy pipeline điều phối dự án (đồng bộ hoặc trong worker background)."""
        endpoints = load_endpoints()
        max_tasks = getattr(self.config, "max_tasks_per_project", 60)
        max_fix_loops = getattr(self.config, "max_fix_loops", 3)
        timeout_minutes = getattr(self.config, "project_timeout_minutes", 240)
        start_time = time.time()

        state.status = ProjectStatus.RUNNING
        self._update_pm_status(AgentStatus.RUNNING, f"Project {state.project_id}")
        save_project_state(state, self.data_dir)

        steps_cfg = {s["id"]: s for s in self.workflow_def.get("steps", [])}
        missing_context_attempts: dict[str, int] = {}

        try:
            for step_cfg in self.workflow_def.get("steps", []):
                sid = step_cfg["id"]
                step = state.steps[sid]

                # Bỏ qua bước đã hoàn tất (hỗ trợ resume)
                if step.status == StepStatus.COMPLETED:
                    continue

                # Kiểm tra nếu dự án bị hủy (ABORTED) từ bên ngoài
                persisted = load_project_state(state.project_id, self.data_dir)
                if persisted and persisted.status == ProjectStatus.ABORTED:
                    state.status = ProjectStatus.ABORTED
                    state.block_reason = persisted.block_reason or "Dự án đã bị hủy bỏ."
                    self._update_pm_status(AgentStatus.IDLE)
                    return state

                # 1. Kiểm tra giới hạn bảo vệ an toàn
                if state.tasks_used >= max_tasks:
                    state.status = ProjectStatus.BLOCKED
                    state.block_reason = f"Vượt quá giới hạn tối đa số tác vụ của dự án (MAX_TASKS_PER_PROJECT={max_tasks})."
                    self._update_pm_status(AgentStatus.BLOCKED)
                    save_project_state(state, self.data_dir)
                    return state

                if (time.time() - start_time) > (timeout_minutes * 60):
                    state.status = ProjectStatus.BLOCKED
                    state.block_reason = f"Dự án vượt quá thời gian thực thi cho phép ({timeout_minutes} phút)."
                    self._update_pm_status(AgentStatus.BLOCKED)
                    save_project_state(state, self.data_dir)
                    return state

                # 2. Kiểm tra phụ thuộc (depends_on)
                deps = step_cfg.get("depends_on", [])
                deps_satisfied = all(
                    state.steps[d].status == StepStatus.COMPLETED for d in deps if d in state.steps
                )
                if not deps_satisfied:
                    logger.warning(f"Bước {sid} chưa thỏa mãn dependencies.")
                    continue

                state.current_step_id = sid

                # 3. Xử lý Cổng kiểm soát (Gate)
                gate_name = step_cfg.get("gate")
                if gate_name:
                    passed = handle_gate_step(
                        step_id=sid,
                        gate_name=gate_name,
                        state=state,
                        auto_approve=state.auto_approve,
                    )
                    save_project_state(state, self.data_dir)
                    append_project_event(state.project_id, "GATE_EVALUATED", {"gate": gate_name, "passed": passed}, self.data_dir)
                    if not passed:
                        # Dừng lại chờ duyệt
                        self._update_pm_status(AgentStatus.WAITING, f"Gate {gate_name}")
                        return state
                    continue

                # 4. Xử lý Action của Agent
                role_str = step_cfg["role"]
                action_str = step_cfg["action"]
                target_agent_id = find_agent_id_for_role(role_str, endpoints)

                step.status = StepStatus.RUNNING
                step.started_at = datetime.now(timezone.utc)
                save_project_state(state, self.data_dir)

                # Thu thập artifact đầu vào cần thiết
                needed_types = step_cfg.get("input_artifact_types", [])
                input_records: list[ArtifactRecord] = []
                for n_type in needed_types:
                    for rec in reversed(list(state.artifacts.values())):
                        t_val = rec.artifact.type.value if hasattr(rec.artifact.type, "value") else str(rec.artifact.type)
                        if t_val == n_type:
                            input_records.append(rec)
                            break

                # PM làm trung chuyển đẩy artifact vào inbox của agent đích
                try:
                    relayed_artifacts = relay_input_artifacts(
                        target_agent_id=target_agent_id,
                        required_artifacts=input_records,
                        endpoints=endpoints,
                    )
                except Exception as err:
                    logger.error(f"Lỗi chuyển tiếp artifact cho bước {sid}: {err}")
                    step.status = StepStatus.BLOCKED
                    state.status = ProjectStatus.BLOCKED
                    state.block_reason = f"Lỗi trung chuyển artifact: {err}"
                    self._update_pm_status(AgentStatus.BLOCKED)
                    save_project_state(state, self.data_dir)
                    return state

                # Chuẩn bị instruction và context
                prev_summary = "Không có tóm tắt trước đó."
                for prev_id in reversed(list(state.steps.keys())):
                    if state.steps[prev_id].status == StepStatus.COMPLETED and state.steps[prev_id].summary:
                        prev_summary = state.steps[prev_id].summary
                        break

                instruction = step_cfg["instruction_template"].format(
                    brief=state.brief,
                    summary_previous=prev_summary,
                )

                context_dict = dict(step_cfg.get("context", {}))
                context_dict["project_id"] = state.project_id
                context_dict["brief"] = state.brief

                # Kiểm tra cờ execute cho devops deploy
                if role_str == "DEVOPS" and action_str == "deploy":
                    is_real_deploy = should_execute_real_deploy(state, state.allow_real_deploy)
                    context_dict["execute"] = is_real_deploy

                # Thực hiện gọi task với retry policy
                max_retries = step_cfg.get("max_retries", 2)
                step_timeout = float(step_cfg.get("timeout_seconds", 120))
                step_attempts = 0
                step_succeeded = False

                # Đặt task_id cố định theo quy ước để tận dụng tính idempotent
                task_seq = state.tasks_used + 1
                task_id = f"TASK-{state.project_id}-{task_seq:03d}"
                step.task_id = task_id

                while step_attempts <= max_retries and not step_succeeded:
                    step_attempts += 1
                    step.attempts = step_attempts
                    state.tasks_used += 1

                    task_req = TaskRequest(
                        contract_version="1.1.0",
                        task_id=task_id,
                        project_id=state.project_id,
                        agent_id=target_agent_id,
                        role=getattr(AgentRole, role_str.upper()),
                        action=action_str,
                        instruction=instruction,
                        context=context_dict,
                        input_artifacts=relayed_artifacts,
                        constraints=Constraints(timeout_seconds=int(step_timeout)),
                    )

                    try:
                        result = send_task_request(
                            target_agent_id=target_agent_id,
                            request=task_req,
                            endpoints=endpoints,
                            timeout_seconds=step_timeout,
                        )
                    except Exception as err:
                        logger.warning(f"Lỗi kết nối tới {target_agent_id} (thử lần {step_attempts}/{max_retries}): {err}")
                        if step_attempts <= max_retries:
                            time.sleep(1.0)
                            continue
                        else:
                            state.status = ProjectStatus.BLOCKED
                            state.block_reason = f"Không thể kết nối tới {target_agent_id}: {err}"
                            step.status = StepStatus.BLOCKED
                            self._update_pm_status(AgentStatus.BLOCKED)
                            save_project_state(state, self.data_dir)
                            return state

                    # Xử lý kết quả trả về từ Agent
                    if result.status == TaskStatus.COMPLETED:
                        step_succeeded = True
                        step.status = StepStatus.COMPLETED
                        step.completed_at = datetime.now(timezone.utc)
                        step.summary = result.summary
                        step.artifacts = result.artifacts

                        # Lưu trữ artifact vào state
                        for art in result.artifacts:
                            state.artifacts[art.artifact_id] = ArtifactRecord(
                                artifact=art,
                                origin_agent_id=target_agent_id,
                            )

                        append_project_event(
                            state.project_id,
                            "STEP_COMPLETED",
                            {"step": sid, "summary": result.summary},
                            self.data_dir,
                        )

                        # Kiểm tra xem có kích hoạt vòng sửa lỗi (Fix loop) hay không
                        should_fix, fix_reason, findings = should_trigger_fix_loop(role_str, action_str, result)
                        while should_fix:
                            if state.fix_loops_used >= max_fix_loops:
                                state.status = ProjectStatus.BLOCKED
                                state.block_reason = (
                                    f"Đạt giới hạn vòng sửa lỗi tối đa (MAX_FIX_LOOPS={max_fix_loops}). "
                                    f"Lý do: {fix_reason}"
                                )
                                self._update_pm_status(AgentStatus.BLOCKED)
                                save_project_state(state, self.data_dir)
                                return state

                            # Kích hoạt vòng sửa lỗi
                            state.fix_loops_used += 1
                            append_project_event(
                                state.project_id,
                                "FIX_LOOP_TRIGGERED",
                                {"loop": state.fix_loops_used, "reason": fix_reason, "findings": findings},
                                self.data_dir,
                            )
                            last_res = self._execute_fix_loop(
                                state=state,
                                endpoints=endpoints,
                                findings=findings,
                                fix_reason=fix_reason,
                            )
                            if not last_res or last_res.status != TaskStatus.COMPLETED:
                                state.status = ProjectStatus.BLOCKED
                                state.block_reason = f"Thất bại trong vòng sửa lỗi {state.fix_loops_used}: {last_res.summary if last_res else 'Lỗi kết nối'}"
                                self._update_pm_status(AgentStatus.BLOCKED)
                                save_project_state(state, self.data_dir)
                                return state

                            result = last_res
                            step.summary = result.summary
                            step.artifacts = result.artifacts
                            should_fix, fix_reason, findings = should_trigger_fix_loop(role_str, action_str, result)

                    elif result.status == TaskStatus.BLOCKED:
                        err_code = result.error.code if result.error else ErrorCode.UNKNOWN_ERROR
                        if err_code == ErrorCode.MISSING_CONTEXT:
                            # PM trả lời MISSING_CONTEXT đúng 1 lần từ brief
                            times_answered = missing_context_attempts.get(sid, 0)
                            if times_answered == 0:
                                missing_context_attempts[sid] = 1
                                questions = (
                                    result.error.details.get("questions")
                                    or result.error.details.get("details", {}).get("questions")
                                    or []
                                ) if result.error else []
                                answers = generate_answers_for_missing_context(state.brief, questions, self.llm_client)
                                context_dict.update(answers)
                                clarification_text = "\n\n[Bổ sung từ PM]: " + " | ".join(f"{k}: {v}" for k, v in answers.items())
                                instruction += clarification_text
                                append_project_event(
                                    state.project_id,
                                    "MISSING_CONTEXT_ANSWERED_BY_PM",
                                    {"step": sid, "answers": answers},
                                    self.data_dir,
                                )
                                continue  # Thử lại ngay với context đã bổ sung
                            else:
                                state.status = ProjectStatus.BLOCKED
                                questions = (
                                    result.error.details.get("questions")
                                    or result.error.details.get("details", {}).get("questions")
                                    or []
                                ) if result.error else []
                                state.block_reason = "Thiếu thông tin ngữ cảnh cốt lõi cần người dùng làm rõ."
                                state.missing_questions = [str(q) for q in questions]
                                self._update_pm_status(AgentStatus.BLOCKED)
                                save_project_state(state, self.data_dir)
                                return state
                        else:
                            state.status = ProjectStatus.BLOCKED
                            state.block_reason = result.error.message if result.error else "Bị chặn không rõ lý do."
                            self._update_pm_status(AgentStatus.BLOCKED)
                            save_project_state(state, self.data_dir)
                            return state

                    elif result.status == TaskStatus.FAILED:
                        is_retryable = result.error.retryable if result.error else False
                        if is_retryable and step_attempts <= max_retries:
                            time.sleep(0.5)
                            continue  # Thử lại với cùng task_id
                        else:
                            state.status = ProjectStatus.BLOCKED
                            state.block_reason = result.error.message if result.error else "Tác vụ thất bại."
                            self._update_pm_status(AgentStatus.BLOCKED)
                            save_project_state(state, self.data_dir)
                            return state

                save_project_state(state, self.data_dir)

            # Toàn bộ pipeline đã hoàn tất -> Đóng gói bản phát hành (RELEASE)
            state.status = ProjectStatus.COMPLETED
            state.current_step_id = None
            package_release(
                project_state=state,
                data_dir=self.data_dir,
                artifact_dir=self.artifact_dir,
                endpoints=endpoints,
                llm_client=self.llm_client,
            )
            append_project_event(state.project_id, "PROJECT_COMPLETED", {"release": True}, self.data_dir)
            self._update_pm_status(AgentStatus.IDLE)
            save_project_state(state, self.data_dir)

        except Exception as e:
            logger.exception(f"Lỗi không mong muốn trong pipeline dự án {state.project_id}: {e}")
            state.status = ProjectStatus.BLOCKED
            state.block_reason = f"Lỗi hệ thống trong điều phối: {e}"
            self._update_pm_status(AgentStatus.BLOCKED)
            save_project_state(state, self.data_dir)

        return state

    def resume_project(self, project_id: str) -> ProjectState:
        """Khôi phục và chạy tiếp pipeline của một dự án dở dang."""
        state = load_project_state(project_id, self.data_dir)
        if not state:
            raise FileNotFoundError(f"Không tìm thấy dự án {project_id}")
        if state.status in [ProjectStatus.COMPLETED, ProjectStatus.ABORTED]:
            return state
        if state.status == ProjectStatus.BLOCKED:
            state.block_reason = None
            state.status = ProjectStatus.RUNNING
        return self.run_pipeline(state)

    def approve_gate(self, project_id: str, gate_name: str, approver: str = "PM") -> ProjectState:
        """Duyệt cổng kiểm soát của dự án và tiếp tục pipeline."""
        state = load_project_state(project_id, self.data_dir)
        if not state:
            raise FileNotFoundError(f"Không tìm thấy dự án {project_id}")
        gate_approve(gate_name=gate_name, state=state, approver=approver)
        save_project_state(state, self.data_dir)
        append_project_event(
            project_id,
            "GATE_APPROVED_MANUALLY",
            {"gate": gate_name, "approver": approver},
            self.data_dir,
        )
        return self.run_pipeline(state)

    def _execute_fix_loop(
        self,
        state: ProjectState,
        endpoints: dict[str, str],
        findings: list[dict[str, Any]],
        fix_reason: str,
    ) -> TaskResult:
        """Thực thi vòng sửa lỗi (Fix Loop): gọi dev.fix_bugs, sau đó re-test hoặc re-review."""
        dev_agent_id = find_agent_id_for_role("DEV", endpoints)
        tester_agent_id = find_agent_id_for_role("TESTER", endpoints)
        sec_agent_id = find_agent_id_for_role("SECURITY", endpoints)

        # Tìm artifact SOURCE_CODE mới nhất và report lỗi mới nhất
        source_code_rec = None
        report_rec = None
        for rec in reversed(list(state.artifacts.values())):
            t_val = rec.artifact.type.value if hasattr(rec.artifact.type, "value") else str(rec.artifact.type)
            if not source_code_rec and t_val == "SOURCE_CODE":
                source_code_rec = rec
            if not report_rec and t_val in ["TEST_REPORT", "SECURITY_REPORT"]:
                report_rec = rec
            if source_code_rec and report_rec:
                break

        if not source_code_rec or not report_rec:
            logger.error("Không tìm thấy đủ SOURCE_CODE và TEST/SECURITY_REPORT cho vòng sửa lỗi.")
            return TaskResult(
                contract_version="1.1.0",
                task_id=f"TASK-{state.project_id}-FIX-ERR",
                agent_id=dev_agent_id,
                status=TaskStatus.FAILED,
                summary="Thiếu artifact SOURCE_CODE hoặc báo cáo kiểm thử cho fix loop.",
            )

        # 1. Gọi dev.fix_bugs
        state.tasks_used += 1
        dev_fix_task_id = f"TASK-{state.project_id}-FIX-{state.fix_loops_used:02d}-DEV"
        relayed = relay_input_artifacts(dev_agent_id, [source_code_rec, report_rec], endpoints)

        fix_req = TaskRequest(
            contract_version="1.1.0",
            task_id=dev_fix_task_id,
            project_id=state.project_id,
            agent_id=dev_agent_id,
            role=AgentRole.DEV,
            action="fix_bugs",
            instruction=f"Sửa lỗi mã nguồn dựa trên báo cáo ({fix_reason}) và đóng gói SOURCE_CODE mới.",
            context={"findings": findings, "fix_loop": state.fix_loops_used},
            input_artifacts=relayed,
            constraints=Constraints(timeout_seconds=180),
        )
        dev_res = send_task_request(dev_agent_id, fix_req, endpoints, timeout_seconds=180)
        if dev_res.status != TaskStatus.COMPLETED:
            return dev_res

        if dev_res.artifacts:
            for art in dev_res.artifacts:
                state.artifacts[art.artifact_id] = ArtifactRecord(artifact=art, origin_agent_id=dev_agent_id)
                if (art.type.value if hasattr(art.type, "value") else str(art.type)) == "SOURCE_CODE":
                    source_code_rec = ArtifactRecord(artifact=art, origin_agent_id=dev_agent_id)

        # 2. Chạy lại tester.run_test_suite
        state.tasks_used += 1
        tester_task_id = f"TASK-{state.project_id}-FIX-{state.fix_loops_used:02d}-TEST"
        tc_rec = next((r for r in reversed(list(state.artifacts.values())) if (r.artifact.type.value if hasattr(r.artifact.type, "value") else str(r.artifact.type)) == "TEST_CASE"), None)
        inputs_for_tester = [source_code_rec] + ([tc_rec] if tc_rec else [])
        relayed_tester = relay_input_artifacts(tester_agent_id, inputs_for_tester, endpoints)

        test_req = TaskRequest(
            contract_version="1.1.0",
            task_id=tester_task_id,
            project_id=state.project_id,
            agent_id=tester_agent_id,
            role=AgentRole.TESTER,
            action="run_test_suite",
            instruction="Chạy lại bộ test sau khi DEV sửa lỗi.",
            context={"fix_loop": state.fix_loops_used},
            input_artifacts=relayed_tester,
            constraints=Constraints(timeout_seconds=120),
        )
        test_res = send_task_request(tester_agent_id, test_req, endpoints, timeout_seconds=120)
        if test_res.status == TaskStatus.COMPLETED and test_res.artifacts:
            for art in test_res.artifacts:
                state.artifacts[art.artifact_id] = ArtifactRecord(artifact=art, origin_agent_id=tester_agent_id)

        # 3. Nếu lý do là Security, chạy lại security_review
        if "SECURITY" in fix_reason:
            if test_res.status != TaskStatus.COMPLETED:
                return test_res
            state.tasks_used += 1
            sec_task_id = f"TASK-{state.project_id}-FIX-{state.fix_loops_used:02d}-SEC"
            arch_rec = next((r for r in reversed(list(state.artifacts.values())) if (r.artifact.type.value if hasattr(r.artifact.type, "value") else str(r.artifact.type)) == "ARCHITECTURE"), None)
            inputs_sec = [source_code_rec] + ([arch_rec] if arch_rec else [])
            relayed_sec = relay_input_artifacts(sec_agent_id, inputs_sec, endpoints)
            sec_req = TaskRequest(
                contract_version="1.1.0",
                task_id=sec_task_id,
                project_id=state.project_id,
                agent_id=sec_agent_id,
                role=AgentRole.SECURITY,
                action="security_review",
                instruction="Rà soát lại bảo mật sau khi DEV khắc phục lỗ hổng.",
                context={"fix_loop": state.fix_loops_used},
                input_artifacts=relayed_sec,
                constraints=Constraints(timeout_seconds=120),
            )
            sec_res = send_task_request(sec_agent_id, sec_req, endpoints, timeout_seconds=120)
            if sec_res.status == TaskStatus.COMPLETED and sec_res.artifacts:
                for art in sec_res.artifacts:
                    state.artifacts[art.artifact_id] = ArtifactRecord(artifact=art, origin_agent_id=sec_agent_id)
            return sec_res

        return test_res
