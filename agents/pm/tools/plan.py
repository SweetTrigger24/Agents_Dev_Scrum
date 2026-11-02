from pathlib import Path
from typing import Union

from agent_contract.enums import ArtifactType
from agent_contract.models import ArtifactRef
from schemas import Milestone, ProjectPlan, SprintPlan
from tools.artifact import save_artifact


def create_milestone(
    milestone_id: str,
    name: str,
    description: str,
    target_date: str | None = None,
    deliverables: list[str] | None = None,
) -> Milestone:
    """Tạo đối tượng Milestone cho dự án."""
    return Milestone(
        milestone_id=milestone_id,
        name=name,
        description=description,
        target_date=target_date,
        deliverables=deliverables or [],
    )


def format_plan_markdown(plan: ProjectPlan) -> str:
    """Định dạng kế hoạch dự án thành tài liệu Markdown plan.md."""
    lines = [
        f"# Kế hoạch dự án: {plan.project_name}",
        "",
        "## 1. Tổng quan",
        plan.overview,
        "",
        "## 2. Các cột mốc quan trọng (Milestones)",
    ]

    for m in plan.milestones:
        date_str = f" (Hạn: {m.target_date})" if m.target_date else ""
        lines.append(f"- **{m.milestone_id}: {m.name}**{date_str}")
        lines.append(f"  - Mô tả: {m.description}")
        if m.deliverables:
            lines.append(f"  - Sản phẩm bàn giao: {', '.join(m.deliverables)}")

    lines.append("")
    lines.append("## 3. Kế hoạch phân chia Sprint")
    for s in plan.sprints:
        lines.append(f"- **Sprint {s.sprint_number}** ({s.duration_weeks} tuần): {s.goal}")
        if s.deliverables:
            lines.append(f"  - Mục tiêu bàn giao: {', '.join(s.deliverables)}")

    lines.append("")
    lines.append("## 4. Quản lý rủi ro dự án")
    if plan.risks:
        for r in plan.risks:
            lines.append(f"- [!] {r}")
    else:
        lines.append("- Chưa phát hiện rủi ro nghiêm trọng.")

    lines.append("")
    return "\n".join(lines)


def create_plan(
    project_name: str,
    overview: str,
    milestones: list[Milestone],
    sprints: list[SprintPlan],
    risks: list[str],
    created_by: str = "pm-01",
    artifact_dir: Union[Path, str, None] = None,
) -> tuple[ProjectPlan, ArtifactRef]:
    """Tạo kế hoạch dự án, xuất ra file plan.md và lưu vào artifact index."""
    plan = ProjectPlan(
        project_name=project_name,
        overview=overview,
        milestones=milestones,
        sprints=sprints,
        risks=risks,
    )
    md_content = format_plan_markdown(plan)
    ref = save_artifact(
        name="plan.md",
        type=ArtifactType.PLAN,
        content=md_content,
        created_by=created_by,
        artifact_dir=artifact_dir,
    )
    return plan, ref
