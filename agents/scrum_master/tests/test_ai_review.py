"""Local tests; don't require a real Antigravity login or external network."""
import json
import sys
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools import ai_review


def test_antigravity_returns_verified_structured_comment(monkeypatch, tmp_path):
    monkeypatch.setattr(ai_review.shutil, "which", lambda tool: "/fake/agy" if tool == "agy" else None)

    def fake_run(argv, **kwargs):
        assert argv[0] == "/fake/agy"
        assert "--json-schema" in argv
        assert "--sandbox" in argv
        assert "Báo cáo" in argv[2]
        payload = {
            "status": "SUCCESS",
            "structured_output": {
                "risks": ["TEST-01 bị chặn vì thiếu source code"],
                "recommendations": ["PM nhắc Developer bàn giao SOURCE_CODE"],
                "message_to_pm": "Cần gỡ blocker trước khi deploy.",
            },
        }
        return SimpleNamespace(returncode=0, stdout=json.dumps(payload), stderr="")

    monkeypatch.setattr(ai_review.subprocess, "run", fake_run)
    value = ai_review.review_report_with_antigravity("# Báo cáo\n- TEST-01 BLOCKED", 75, tmp_path)
    assert value["used"] is True
    assert value["status"] == "success"
    assert "TEST-01" in value["review"]
    assert "PM nhắc Developer" in value["review"]


def test_antigravity_missing_cli_marks_fallback(monkeypatch, tmp_path):
    monkeypatch.setattr(ai_review.shutil, "which", lambda tool: None)
    value = ai_review.review_report_with_antigravity("report", 75, tmp_path)
    assert value == {
        "used": False,
        "status": "fallback",
        "review": "",
        "reason": "agy_not_installed_or_not_on_PATH",
    }


def test_invalid_ai_json_marks_fallback(monkeypatch, tmp_path):
    monkeypatch.setattr(ai_review.shutil, "which", lambda tool: "/fake/agy")
    monkeypatch.setattr(ai_review.subprocess, "run", lambda *a, **k: SimpleNamespace(returncode=0, stdout='{"status":"SUCCESS","response":"not json"}', stderr=""))
    value = ai_review.review_report_with_antigravity("report", 75, tmp_path)
    assert value["used"] is False
    assert value["reason"] == "invalid_ai_json"


def test_non_object_cli_envelope_marks_fallback(monkeypatch, tmp_path):
    monkeypatch.setattr(ai_review.shutil, "which", lambda tool: "/fake/agy")
    monkeypatch.setattr(ai_review.subprocess, "run", lambda *a, **k: SimpleNamespace(returncode=0, stdout="[]", stderr=""))
    assert ai_review.review_report_with_antigravity("report", 75, tmp_path)["reason"] == "invalid_ai_json"


def test_full_scrum_agent_marks_real_ai_usage(monkeypatch, tmp_path):
    from agent_contract.enums import AgentRole, TaskStatus
    from agent_contract.models import AgentIdentity, TaskRequest
    from agent_contract.registry import CAPABILITY_REGISTRY
    import agent as agent_module
    from config import AgentConfig

    config = AgentConfig(
        base_dir=tmp_path,
        port=8009,
        agent_id="scrum_master-01",
        agent_role=AgentRole.SCRUM_MASTER,
        dry_run=False,
        sm_backend="antigravity",
        artifact_dir="./artifacts",
        workspace_dir="./workspace",
        data_dir="./data",
    )
    identity = AgentIdentity(
        agent_id="scrum_master-01",
        role=AgentRole.SCRUM_MASTER,
        name="Scrum Master AI",
        version="1.0.0",
        capabilities=CAPABILITY_REGISTRY[AgentRole.SCRUM_MASTER],
    )
    monkeypatch.setattr(
        agent_module, "review_report_with_antigravity",
        lambda *args, **kwargs: {
            "used": True,
            "status": "success",
            "review": "## Nhận xét của AI Scrum Master\n\n- Gỡ blocker TEST-01.",
            "reason": "",
        },
    )
    sample = json.loads((ROOT / "examples" / "track.json").read_text(encoding="utf-8"))
    req = TaskRequest.model_validate(sample)
    result = agent_module.ScrumMasterAgent(identity, config).handle(req)
    assert result.status == TaskStatus.COMPLETED
    assert result.metadata["ai_used"] is True
    assert result.outputs[0]["blocked"] == 1
    assert result.artifacts
    report_files = list((tmp_path / "artifacts").glob("scrum_*.md"))
    assert len(report_files) == 1
    assert "Nhận xét của AI Scrum Master" in report_files[0].read_text(encoding="utf-8")
