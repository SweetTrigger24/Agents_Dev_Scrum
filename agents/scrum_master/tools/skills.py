"""Load trusted, action-specific instructions shipped with this agent."""
from pathlib import Path

SKILLS = {"track_blockers": "scrum-track-blockers", "run_retrospective": "scrum-retrospective",
          "review_module": "scrum-review-module"}


def load_skill(action: str) -> tuple[str, str]:
    name = SKILLS[action]
    path = Path(__file__).resolve().parents[1] / "skills" / name / "SKILL.md"
    return name, path.read_text(encoding="utf-8")
