import importlib
import io
import json
import sys
import zipfile
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


@pytest.mark.parametrize("action,skill", [("implement_project", "dev-implement"), ("fix_bugs", "dev-fix-bugs"),
    ("review_code", "dev-review-code"), ("refactor_code", "dev-refactor-code")])
def test_pm_api_loads_action_skill(action, skill, tmp_path, monkeypatch):
    import config
    import agent
    from agent_contract import ArtifactRef
    from agent_contract.enums import ArtifactType
    from datetime import datetime, timezone

    cfg = config.AgentConfig(base_dir=tmp_path, port=8006, host="127.0.0.1",
        agent_id="dev-01", agent_role="DEV", agent_api_key="test-token",
        dry_run=False, dev_backend="codex")
    monkeypatch.setattr(config, "AgentConfig", lambda: cfg)
    monkeypatch.setattr(agent.shutil, "which", lambda _: "fake-codex")
    def run(argv, **kwargs):
        assert (ROOT / "skills" / skill / "SKILL.md").read_text(encoding="utf-8") in argv[-1]
        workspace = Path(kwargs["cwd"])
        if action != "implement_project":
            assert (workspace / "app.py").read_text() == "broken"
        if action != "review_code":
            (workspace / "app.py").write_text("fixed")
        (workspace / "delivery_report.json").write_text(json.dumps({
            "action": action, "scope_status": "COMPLETE", "summary": "Finished scope; independent tests pending",
            "acceptance": [{"id": "AC-001", "status": "IMPLEMENTED", "evidence": "app.py"}],
            "changes": [] if action == "review_code" else [{"path": "app.py", "summary": "Requested change"}],
            "checks": [{"command": "runtime tests", "status": "NOT_RUN", "evidence": "Mock environment"}],
            "findings": [{"id": "R-001", "severity": "HIGH", "path": "app.py", "line": 1,
                          "detail": "Concrete observed problem", "recommendation": "Repair behavior"}] if action == "review_code" else [],
            "unresolved": [],
        }), encoding="utf-8")
        return SimpleNamespace(returncode=0, stdout="done", stderr="")
    monkeypatch.setattr(agent.subprocess, "run", run)
    refs = []
    if action != "implement_project":
        inbox = Path(cfg.artifact_dir) / "inbox" / "dev-01"
        inbox.mkdir(parents=True)
        blob = io.BytesIO()
        with zipfile.ZipFile(blob, "w") as archive:
            archive.writestr("app.py", "broken")
        (inbox / "source.zip").write_bytes(blob.getvalue())
        refs = [ArtifactRef(artifact_id="ART-001", name="source.zip", type=ArtifactType.SOURCE_CODE,
            uri="artifacts/source.zip", created_by="dev-01", created_at=datetime.now(timezone.utc)).model_dump(mode="json")]
    api = importlib.import_module("api")
    with TestClient(api.app) as client:
        result = client.post("/tasks", headers={"Authorization": "Bearer test-token"}, json={
            "task_id": "DEV-" + action, "project_id": "PROJ-TEST", "agent_id": "dev-01",
            "role": "DEV", "action": action, "instruction": "Implement PM request", "input_artifacts": refs,
        })
    assert result.status_code == 200
    data = result.json()
    assert data["status"] == "COMPLETED", data
    assert data["metadata"]["skill"] == skill
    assert data["metadata"]["skill_applied"] is True
    assert data["outputs"][0]["delivery"]["action"] == action
    assert data["outputs"][0]["verified"] is False
    if action == "review_code":
        assert [a["type"] for a in data["artifacts"]] == ["DOCUMENTATION"]
    else:
        assert data["artifacts"][0]["type"] == "SOURCE_CODE"
        assert data["artifacts"][1]["type"] == "DOCUMENTATION"
    sys.modules.pop("api", None)


@pytest.mark.parametrize("action", ["fix_bugs", "review_code", "refactor_code"])
def test_source_required_before_calling_ai(action, tmp_path):
    from agent import DeveloperAgent
    from config import AgentConfig
    from agent_contract import AgentIdentity, TaskRequest
    from agent_contract.registry import CAPABILITY_REGISTRY
    from agent_contract.enums import AgentRole
    cfg = AgentConfig(base_dir=tmp_path, port=8006, agent_id="dev-01", agent_role="DEV", dry_run=False)
    identity = AgentIdentity(agent_id="dev-01", role="DEV", name="DEV", version="1.0",
                             capabilities=CAPABILITY_REGISTRY[AgentRole.DEV])
    res = DeveloperAgent(identity, cfg).handle(TaskRequest(task_id="MISSING", project_id="P",
        agent_id="dev-01", role="DEV", action=action, instruction="Perform request"))
    assert res.status.value == "BLOCKED"
    assert res.error.code.value == "MISSING_CONTEXT"


@pytest.mark.parametrize("problem", ["missing_report", "wrong_action", "contradictory_complete", "unsafe_path", "invalid_line", "edited_review"])
def test_invalid_handoff_rejected(problem, tmp_path):
    from tools.delivery import source_snapshot, read_report
    (tmp_path / "app.py").write_text("original")
    before = source_snapshot(tmp_path)
    data = {"action": "review_code", "scope_status": "COMPLETE", "summary": "Review",
            "acceptance": [], "changes": [], "checks": [{"command": "tests", "status": "NOT_RUN", "evidence": "Unavailable"}],
            "findings": [], "unresolved": []}
    action = "review_code"
    if problem == "wrong_action":
        data["action"] = "fix_bugs"
    elif problem == "contradictory_complete":
        action = data["action"] = "fix_bugs"
        data["unresolved"] = ["Required fix unfinished"]
    elif problem in ("unsafe_path", "invalid_line"):
        data["findings"] = [{"id": "F-1", "severity": "HIGH", "path": "../secret" if problem == "unsafe_path" else "app.py",
                              "line": 99, "detail": "Issue", "recommendation": "Fix"}]
    elif problem == "edited_review":
        (tmp_path / "app.py").write_text("edited")
    if problem != "missing_report":
        (tmp_path / "delivery_report.json").write_text(json.dumps(data))
    with pytest.raises(ValueError):
        read_report(tmp_path, action, before)


@pytest.mark.parametrize("mode,expected", [("partial", "BLOCKED"), ("missing_report", "FAILED")])
def test_incomplete_or_missing_delivery_never_completes(mode, expected, tmp_path, monkeypatch):
    import agent
    from config import AgentConfig
    from agent_contract import AgentIdentity, TaskRequest
    from agent_contract.registry import CAPABILITY_REGISTRY
    from agent_contract.enums import AgentRole
    cfg = AgentConfig(base_dir=tmp_path, port=8006, agent_id="dev-01", agent_role="DEV", dry_run=False)
    identity = AgentIdentity(agent_id="dev-01", role="DEV", name="DEV", version="1.0",
                             capabilities=CAPABILITY_REGISTRY[AgentRole.DEV])
    monkeypatch.setattr(agent.shutil, "which", lambda _: "fake-codex")
    def run(argv, **kwargs):
        workspace = Path(kwargs["cwd"])
        (workspace / "app.py").write_text("prototype")
        if mode == "partial":
            (workspace / "delivery_report.json").write_text(json.dumps({
                "action": "implement_project", "scope_status": "PARTIAL", "summary": "Unfinished prototype",
                "acceptance": [{"id": "AC-1", "status": "NOT_IMPLEMENTED", "evidence": "Missing database"}],
                "changes": [{"path": "app.py", "summary": "Prototype"}],
                "checks": [{"command": "tests", "status": "NOT_RUN", "evidence": "No database"}],
                "findings": [], "unresolved": ["Database feature"],
            }))
        return SimpleNamespace(returncode=0, stdout="CLI exited successfully", stderr="")
    monkeypatch.setattr(agent.subprocess, "run", run)
    res = agent.DeveloperAgent(identity, cfg).handle(TaskRequest(task_id="INCOMPLETE", project_id="P",
        agent_id="dev-01", role="DEV", action="implement_project", instruction="Build app"))
    assert res.status.value == expected
    if mode == "partial":
        assert res.outputs[0]["delivery"]["scope_status"] == "PARTIAL"
        assert len(res.artifacts) == 2
    else:
        assert res.error.code.value == "VALIDATION_ERROR"
        assert not res.artifacts


def test_sample_stays_explicitly_unverified(tmp_path):
    from agent import DeveloperAgent
    from config import AgentConfig
    from agent_contract import AgentIdentity, TaskRequest
    from agent_contract.registry import CAPABILITY_REGISTRY
    from agent_contract.enums import AgentRole
    cfg = AgentConfig(base_dir=tmp_path, port=8006, agent_id="dev-01", agent_role="DEV", dry_run=False, dev_backend="sample")
    identity = AgentIdentity(agent_id="dev-01", role="DEV", name="DEV", version="1.0",
                             capabilities=CAPABILITY_REGISTRY[AgentRole.DEV])
    result = DeveloperAgent(identity, cfg).handle(TaskRequest(task_id="SAMPLE", project_id="P",
        agent_id="dev-01", role="DEV", action="implement_project", instruction="Test sample"))
    assert result.status.value == "COMPLETED"
    assert result.metadata["demo_only"] is True
    assert result.metadata["skill_applied"] is False
    assert result.outputs[0]["delivery"]["scope_status"] == "PARTIAL"
    assert result.outputs[0]["verified"] is False
