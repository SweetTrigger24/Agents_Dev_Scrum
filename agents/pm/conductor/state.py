import json
import os
import shutil
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from agent_contract.models import ArtifactRef


class ProjectStatus(str, Enum):
    """Trạng thái tổng thể của dự án phát triển phần mềm."""
    CREATED = "CREATED"
    RUNNING = "RUNNING"
    WAITING_APPROVAL = "WAITING_APPROVAL"
    BLOCKED = "BLOCKED"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    ABORTED = "ABORTED"


class StepStatus(str, Enum):
    """Trạng thái thực thi của từng bước trong workflow."""
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    WAITING_APPROVAL = "WAITING_APPROVAL"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    BLOCKED = "BLOCKED"
    SKIPPED = "SKIPPED"


class ArtifactRecord(BaseModel):
    """Bản ghi lưu vết Artifact kèm theo agent nguồn tạo ra nó."""
    artifact: ArtifactRef
    origin_agent_id: str


class StepState(BaseModel):
    """Trạng thái chi tiết của một bước trong quy trình pipeline."""
    id: str
    role: str | None = None
    action: str | None = None
    gate: str | None = None
    status: StepStatus = StepStatus.PENDING
    attempts: int = 0
    task_id: str | None = None
    error: str | None = None
    summary: str | None = None
    artifacts: list[ArtifactRef] = Field(default_factory=list)
    started_at: datetime | None = None
    completed_at: datetime | None = None


class ProjectState(BaseModel):
    """Toàn bộ trạng thái và lịch sử thực thi của một dự án do PM Conductor quản lý."""
    project_id: str
    brief: str
    status: ProjectStatus = ProjectStatus.CREATED
    current_step_id: str | None = None
    waiting_gate: str | None = None
    steps: dict[str, StepState] = Field(default_factory=dict)
    artifacts: dict[str, ArtifactRecord] = Field(default_factory=dict)
    fix_loops_used: int = 0
    tasks_used: int = 0
    auto_approve: bool = False
    allow_real_deploy: bool = False
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    block_reason: str | None = None
    missing_questions: list[str] = Field(default_factory=list)


def get_project_dir(data_dir: Path | str, project_id: str) -> Path:
    """Trả về thư mục lưu trữ dữ liệu riêng cho dự án: data/projects/<project_id>/."""
    pdir = Path(data_dir).resolve() / "projects" / project_id
    pdir.mkdir(parents=True, exist_ok=True)
    return pdir


def save_project_state(state: ProjectState, data_dir: Path | str) -> Path:
    """Ghi trạng thái ProjectState nguyên tử (atomic write qua file tạm rồi đổi tên)."""
    pdir = get_project_dir(data_dir, state.project_id)
    state.updated_at = datetime.now(timezone.utc)
    target_file = pdir / "state.json"
    temp_file = pdir / "state.json.tmp"

    data_str = json.dumps(state.model_dump(mode="json"), indent=2, ensure_ascii=False)
    with open(temp_file, "w", encoding="utf-8") as f:
        f.write(data_str)
        f.flush()
        os.fsync(f.fileno())

    # Đổi tên nguyên tử
    shutil.move(str(temp_file), str(target_file))
    return target_file


def load_project_state(project_id: str, data_dir: Path | str) -> ProjectState | None:
    """Nạp trạng thái dự án từ data/projects/<project_id>/state.json nếu tồn tại."""
    pdir = Path(data_dir).resolve() / "projects" / project_id
    target_file = pdir / "state.json"
    if not target_file.exists():
        return None
    try:
        content = target_file.read_text(encoding="utf-8")
        data = json.loads(content)
        return ProjectState.model_validate(data)
    except Exception:
        return None


def append_project_event(project_id: str, event_type: str, details: dict[str, Any], data_dir: Path | str) -> None:
    """Ghi bổ sung nhật ký sự kiện vào data/projects/<project_id>/events.jsonl."""
    pdir = get_project_dir(data_dir, project_id)
    events_file = pdir / "events.jsonl"
    event_entry = {
        "timestamp": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "project_id": project_id,
        "event_type": event_type,
        "details": details,
    }
    with open(events_file, "a", encoding="utf-8") as f:
        f.write(json.dumps(event_entry, ensure_ascii=False) + "\n")


def list_all_projects(data_dir: Path | str) -> list[ProjectState]:
    """Liệt kê tất cả các project hiện có trong thư mục data/projects/."""
    projects_dir = Path(data_dir).resolve() / "projects"
    if not projects_dir.exists():
        return []
    results = []
    for item in projects_dir.iterdir():
        if item.is_dir():
            st = load_project_state(item.name, data_dir)
            if st:
                results.append(st)
    results.sort(key=lambda s: s.created_at, reverse=True)
    return results
