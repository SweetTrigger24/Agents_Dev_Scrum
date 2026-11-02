import json
from pathlib import Path
from typing import Union

from agent_contract.enums import AgentRole, ArtifactType, TaskStatus
from agent_contract.models import ArtifactRef
from agent_contract.registry import CAPABILITY_REGISTRY
from schemas import TaskItem
from tools.artifact import DEFAULT_ARTIFACT_DIR, save_artifact


class TaskToolError(Exception):
    """Ngoại lệ phát sinh khi thao tác với danh sách công việc (task)."""
    pass


def load_tasks(artifact_dir: Union[Path, str, None] = None) -> list[TaskItem]:
    """Đọc danh sách công việc từ artifacts/tasks.json."""
    base_dir = Path(artifact_dir) if artifact_dir is not None else DEFAULT_ARTIFACT_DIR
    tasks_file = base_dir / "tasks.json"
    if not tasks_file.exists():
        return []

    try:
        with open(tasks_file, "r", encoding="utf-8") as f:
            data = json.load(f)
            if not isinstance(data, list):
                return []
            return [TaskItem.model_validate(item) for item in data]
    except Exception as e:
        raise TaskToolError(f"Không thể đọc file tasks.json: {e}") from e


def save_tasks_list(
    tasks: list[TaskItem],
    created_by: str = "pm-01",
    artifact_dir: Union[Path, str, None] = None,
) -> ArtifactRef:
    """Lưu danh sách công việc vào artifacts/tasks.json và đăng ký vào artifact index."""
    data = [t.model_dump(mode="json") for t in tasks]
    json_content = json.dumps(data, indent=2, ensure_ascii=False)
    return save_artifact(
        name="tasks.json",
        type=ArtifactType.BACKLOG,
        content=json_content,
        created_by=created_by,
        artifact_dir=artifact_dir,
    )


def create_task(
    task_id: str,
    title: str,
    description: str,
    assignee_role: AgentRole,
    acceptance_criteria: list[str],
    due: str | None = None,
    depends_on: list[str] | None = None,
    status: TaskStatus = TaskStatus.PENDING,
    created_by: str = "pm-01",
    artifact_dir: Union[Path, str, None] = None,
) -> TaskItem:
    """Tạo một task mới và lưu vào artifacts/tasks.json."""
    if not isinstance(assignee_role, AgentRole):
        try:
            assignee_role = AgentRole(assignee_role)
        except ValueError:
            raise TaskToolError(f"assignee_role '{assignee_role}' không phải là AgentRole hợp lệ.")

    tasks = load_tasks(artifact_dir)
    # Kiểm tra trùng lặp task_id
    for t in tasks:
        if t.task_id == task_id:
            raise TaskToolError(f"Task ID '{task_id}' đã tồn tại trong tasks.json.")

    new_task = TaskItem(
        task_id=task_id,
        title=title,
        description=description,
        assignee_role=assignee_role,
        acceptance_criteria=acceptance_criteria,
        due=due,
        depends_on=depends_on or [],
        status=status,
    )
    tasks.append(new_task)
    save_tasks_list(tasks, created_by=created_by, artifact_dir=artifact_dir)
    return new_task


def update_task(
    task_id: str,
    status: TaskStatus | None = None,
    title: str | None = None,
    description: str | None = None,
    due: str | None = None,
    created_by: str = "pm-01",
    artifact_dir: Union[Path, str, None] = None,
) -> TaskItem:
    """Cập nhật thông tin hoặc trạng thái của một task."""
    tasks = load_tasks(artifact_dir)
    target_task: TaskItem | None = None

    for t in tasks:
        if t.task_id == task_id:
            target_task = t
            break

    if target_task is None:
        raise TaskToolError(f"Không tìm thấy task có mã '{task_id}'.")

    if status is not None:
        target_task.status = status
    if title is not None:
        target_task.title = title
    if description is not None:
        target_task.description = description
    if due is not None:
        target_task.due = due

    save_tasks_list(tasks, created_by=created_by, artifact_dir=artifact_dir)
    return target_task


def assign_task(
    task_id: str,
    assignee_role: AgentRole,
    required_capability: str | None = None,
    created_by: str = "pm-01",
    artifact_dir: Union[Path, str, None] = None,
) -> TaskItem:
    """Phân công task cho một AgentRole hợp lệ và kiểm tra capability phù hợp."""
    if not isinstance(assignee_role, AgentRole):
        try:
            assignee_role = AgentRole(assignee_role)
        except ValueError:
            raise TaskToolError(f"assignee_role '{assignee_role}' không phải là AgentRole hợp lệ.")

    # Kiểm tra capability nếu có yêu cầu
    if required_capability:
        allowed_capabilities = CAPABILITY_REGISTRY.get(assignee_role, [])
        if required_capability not in allowed_capabilities:
            raise TaskToolError(
                f"Vai trò '{assignee_role.value}' không sở hữu capability '{required_capability}'. "
                f"Các capability hợp lệ: {allowed_capabilities}"
            )

    tasks = load_tasks(artifact_dir)
    target_task: TaskItem | None = None

    for t in tasks:
        if t.task_id == task_id:
            target_task = t
            break

    if target_task is None:
        raise TaskToolError(f"Không tìm thấy task có mã '{task_id}'.")

    target_task.assignee_role = assignee_role
    save_tasks_list(tasks, created_by=created_by, artifact_dir=artifact_dir)
    return target_task


def get_task_status(
    task_id: str,
    artifact_dir: Union[Path, str, None] = None,
) -> TaskStatus:
    """Lấy trạng thái thực thi hiện tại của một task."""
    tasks = load_tasks(artifact_dir)
    for t in tasks:
        if t.task_id == task_id:
            return t.status
    raise TaskToolError(f"Không tìm thấy task có mã '{task_id}'.")
