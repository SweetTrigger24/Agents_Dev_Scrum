import logging
from conductor.state import ProjectState, ProjectStatus, StepStatus

logger = logging.getLogger("pm.conductor.gates")

GATE_APPROVE_SCOPE = "approve_scope"
GATE_APPROVE_DEPLOY = "approve_deploy"
SUPPORTED_GATES = [GATE_APPROVE_SCOPE, GATE_APPROVE_DEPLOY]


def is_gate_approved(gate_name: str, state: ProjectState) -> bool:
    """Kiểm tra xem một cổng đã được phê duyệt trong state hay chưa."""
    for step in state.steps.values():
        if step.gate == gate_name and step.status == StepStatus.COMPLETED:
            return True
    return False


def handle_gate_step(
    step_id: str,
    gate_name: str,
    state: ProjectState,
    auto_approve: bool = False,
) -> bool:
    """Xử lý bước cổng kiểm soát. Trả về True nếu được thông qua (COMPLETED), False nếu dừng chờ duyệt."""
    step = state.steps.get(step_id)
    if not step:
        return False

    if auto_approve or state.auto_approve:
        step.status = StepStatus.COMPLETED
        step.summary = f"Cổng '{gate_name}' được tự động phê duyệt (chế độ auto-approve)."
        logger.info(f"Dự án {state.project_id}: Cổng '{gate_name}' tự động duyệt.")
        return True

    # Nếu chưa auto approve và chưa được duyệt trước đó -> chuyển sang WAITING_APPROVAL
    if step.status != StepStatus.COMPLETED:
        step.status = StepStatus.WAITING_APPROVAL
        state.status = ProjectStatus.WAITING_APPROVAL
        state.waiting_gate = gate_name
        step.summary = f"Đang tạm dừng chờ phê duyệt thủ công cổng '{gate_name}'."
        logger.info(f"Dự án {state.project_id}: Tạm dừng tại cổng '{gate_name}', chờ phê duyệt.")
        return False

    return True


def approve_gate(
    gate_name: str,
    state: ProjectState,
    approver: str = "PM",
) -> bool:
    """Phê duyệt thủ công một cổng duyệt và cập nhật trạng thái project."""
    found = False
    for step in state.steps.values():
        if step.gate == gate_name:
            step.status = StepStatus.COMPLETED
            step.summary = f"Cổng '{gate_name}' đã được phê duyệt thành công bởi {approver}."
            found = True

    if found:
        state.waiting_gate = None
        state.status = ProjectStatus.RUNNING
        logger.info(f"Dự án {state.project_id}: Đã duyệt cổng '{gate_name}' bởi {approver}.")
        return True
    return False


def should_execute_real_deploy(
    state: ProjectState,
    allow_real_deploy_config: bool,
) -> bool:
    """Kiểm tra điều kiện thực hiện deploy thật.
    CHỈ bật khi PM_ALLOW_REAL_DEPLOY=true VÀ cổng approve_deploy đã được duyệt.
    Ngoài ra luôn trả False (chạy dry-run / context.execute=false).
    """
    if not allow_real_deploy_config:
        return False

    return is_gate_approved(GATE_APPROVE_DEPLOY, state)
