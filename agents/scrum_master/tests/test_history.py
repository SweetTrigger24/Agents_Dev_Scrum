import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tools.history import commit, normalize_tasks, observe


def test_blocker_lifecycle_partial_snapshots_and_project_isolation(tmp_path):
    start = datetime(2026, 11, 5, tzinfo=timezone.utc)
    def call(request_id, tasks, minutes, project="P"):
        summary, path, state = observe(str(tmp_path), project, request_id,
            normalize_tasks({"tasks": tasks}), start + timedelta(minutes=minutes))
        commit(path, state)
        return summary
    blocked = {"id": "DEV", "status": "BLOCKED", "blocked_reason": "Waiting for schema"}
    first = call("1", [blocked], 0)
    assert first["new"][0]["id"] == "DEV"
    later = call("2", [blocked], 5)
    assert later["persistent"][0]["observed_age_seconds"] == 300
    missing = call("3", [], 6)
    assert not missing["resolved"]
    assert missing["not_observed"][0]["id"] == "DEV"
    unknown = call("4", [{"id": "DEV", "status": "UNKNOWN"}], 7)
    assert not unknown["resolved"]
    resolved = call("5", [{"id": "DEV", "status": "RUNNING"}], 8)
    assert resolved["resolved"][0]["id"] == "DEV"
    reopened = call("6", [blocked], 9)
    assert reopened["new"][0]["observed_age_seconds"] == 0
    repeat = call("6", [blocked], 10)
    assert repeat == reopened
    other = call("7", [blocked], 11, project="../../another-project")
    assert other["new"][0]["observations"] == 1
    assert len(list((tmp_path / "scrum_history").glob("*.json"))) == 2


@pytest.mark.parametrize("tasks", [None, {}, ["task"], [{"status": "BLOCKED"}],
    [{"id": "A"}, {"id": "A"}], [{"id": "A", "status": 123}]])
def test_malformed_snapshots_rejected(tasks):
    with pytest.raises(ValueError):
        normalize_tasks({"tasks": tasks})


def test_null_reason_is_not_a_blocker():
    assert normalize_tasks({"tasks": [{"id": "A", "status": "COMPLETED", "blocked_reason": None}]})[0]["blocked_reason"] == ""


def test_rules_and_ai_fallback_keep_history(tmp_path, monkeypatch):
    import agent
    from config import AgentConfig
    from agent_contract import AgentIdentity, TaskRequest
    from agent_contract.registry import CAPABILITY_REGISTRY
    from agent_contract.enums import AgentRole
    cfg = AgentConfig(base_dir=tmp_path, port=8009, agent_id="scrum_master-01", agent_role="SCRUM_MASTER",
        dry_run=True, sm_backend="rules")
    identity = AgentIdentity(agent_id="scrum_master-01", role="SCRUM_MASTER", name="SM", version="1.0",
                             capabilities=CAPABILITY_REGISTRY[AgentRole.SCRUM_MASTER])
    sm = agent.ScrumMasterAgent(identity, cfg)
    def request(task_id, tasks):
        return TaskRequest(task_id=task_id, project_id="P", agent_id="scrum_master-01", role="SCRUM_MASTER",
            action="track_blockers", instruction="Track", context={"tasks": tasks})
    blocked = [{"id": "TEST", "status": "BLOCKED"}]
    first = sm.handle(request("1", blocked))
    assert first.outputs[0]["history"]["new"][0]["id"] == "TEST"
    cfg.sm_backend, cfg.dry_run = "antigravity", False
    monkeypatch.setattr(agent, "review_report_with_antigravity", lambda *a, **k: {
        "used": False, "status": "fallback", "reason": "ai_timeout", "review": ""})
    second = sm.handle(request("2", blocked))
    assert second.status.value == "COMPLETED"
    assert second.outputs[0]["history"]["persistent"][0]["observations"] == 2
    assert second.metadata["skill_applied"] is False
    assert second.metadata["ai_status"] == "fallback"
    third = sm.handle(request("3", [{"id": "TEST", "status": "COMPLETED", "blocked_reason": None}]))
    assert third.outputs[0]["blocked"] == 0
    assert third.outputs[0]["history"]["resolved"][0]["id"] == "TEST"
