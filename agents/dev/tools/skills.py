"""Load trusted, action-specific instructions shipped with this agent."""
from pathlib import Path

SKILLS = {"implement_project": "dev-implement", "fix_bugs": "dev-fix-bugs",
          "review_code": "dev-review-code", "refactor_code": "dev-refactor-code"}


def load_skill(action: str) -> tuple[str, str]:
    name = SKILLS[action]
    path = Path(__file__).resolve().parents[1] / "skills" / name / "SKILL.md"
    return name, path.read_text(encoding="utf-8")
