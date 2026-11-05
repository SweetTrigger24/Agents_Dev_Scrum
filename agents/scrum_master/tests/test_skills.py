import importlib
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


@pytest.mark.parametrize("action,skill", [("track_blockers", "scrum-track-blockers"), ("run_retrospective", "scrum-retrospective")])
def test_pm_api_loads_action_skill(action, skill, tmp_path, monkeypatch):
    import config
    import agent
    cfg = config.AgentConfig(base_dir=tmp_path, port=8009, host="127.0.0.1",
        agent_id="scrum_master-01", agent_role="SCRUM_MASTER", agent_api_key="test-token",
        dry_run=False, sm_backend="antigravity")
    monkeypatch.setattr(config, "AgentConfig", lambda: cfg)
    def review(report, **kwargs):
        assert kwargs["skill_instructions"] == (ROOT / "skills" / skill / "SKILL.md").read_text(encoding="utf-8")
        assert "TEST-01" in report
        return {"used": True, "status": "success", "review": "AI review", "reason": ""}
    monkeypatch.setattr(agent, "review_report_with_antigravity", review)
    api = importlib.import_module("api")
    with TestClient(api.app) as client:
        result = client.post("/tasks", headers={"Authorization": "Bearer test-token"}, json={
            "task_id": "SM-" + action, "project_id": "PROJ-TEST", "agent_id": "scrum_master-01",
            "role": "SCRUM_MASTER", "action": action, "instruction": "Review PM snapshot",
            "context": {"tasks": [{"id": "TEST-01", "status": "BLOCKED", "blocked_reason": "Await source"}]},
        })
    data = result.json()
    assert result.status_code == 200
    assert data["status"] == "COMPLETED", data
    assert data["metadata"]["skill"] == skill
    assert data["metadata"]["skill_applied"] is True
    assert data["outputs"][0]["blocked"] == 1
    assert data["artifacts"][0]["type"] == "DOCUMENTATION"
    sys.modules.pop("api", None)
