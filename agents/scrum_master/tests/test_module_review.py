import hashlib
import importlib
import io
import json
import sys
import zipfile
from datetime import datetime, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from agent import ScrumMasterAgent
from agent_contract import AgentIdentity, ArtifactRef, TaskRequest
from agent_contract.enums import AgentRole
from agent_contract.registry import CAPABILITY_REGISTRY
from config import AgentConfig


@pytest.fixture
def module_task(tmp_path):
    cfg = AgentConfig(base_dir=tmp_path, host="127.0.0.1", port=8009,
        agent_id="scrum_master-01", agent_role="SCRUM_MASTER", agent_api_key="test-token",
        sm_backend="rules", dry_run=True)
    identity = AgentIdentity(agent_id="scrum_master-01", role="SCRUM_MASTER", name="SM", version="1.0",
        capabilities=CAPABILITY_REGISTRY[AgentRole.SCRUM_MASTER])
    refs = []
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("app.py", "print('module')")
    for origin, name, kind, blob in [
        ("dev-01", "source.zip", "SOURCE_CODE", buffer.getvalue()),
        ("tester-01", "test-report.json", "TEST_REPORT", b'{"verdict":"PASS","findings":[]}'),
    ]:
        folder = Path(cfg.artifact_dir) / "inbox" / origin
        folder.mkdir(parents=True, exist_ok=True)
        (folder / name).write_bytes(blob)
        refs.append(ArtifactRef(artifact_id="ART-" + kind, name=name, type=kind,
            uri=f"artifacts/inbox/{origin}/{name}", created_by=origin,
            created_at=datetime.now(timezone.utc), checksum=hashlib.sha256(blob).hexdigest()))
    req = TaskRequest(task_id="SM-MODULE-1", project_id="PROJECT-1", agent_id="scrum_master-01",
        role="SCRUM_MASTER", action="review_module", instruction="Review module đăng nhập trước khi chuyển tiếp",
        input_artifacts=refs, context={"module_id": "AUTH", "tasks": [
            {"id": "DEV-AUTH", "module_id": "AUTH", "status": "COMPLETED"},
            {"id": "TEST-AUTH", "module_id": "AUTH", "status": "COMPLETED"}],
            "acceptance_criteria": [{"id": "AC-AUTH-1", "description": "Đăng nhập hợp lệ",
                                     "status": "PASS", "evidence": "test-report.json: test_valid_login đạt"}]})
    return ScrumMasterAgent(identity, cfg), cfg, req


def test_module_review_api_generates_downloadable_document(module_task, monkeypatch):
    sm, cfg, req = module_task
    import config
    monkeypatch.setattr(config, "AgentConfig", lambda: cfg)
    sys.modules.pop("api", None)
    api = importlib.import_module("api")
    with TestClient(api.app) as client:
        response = client.post("/tasks", json=req.model_dump(mode="json"),
            headers={"Authorization": "Bearer test-token"})
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "COMPLETED", data
        assert data["outputs"][0]["verdict"] == "PASS"
        assert data["outputs"][0]["can_start_next_module"] is True
        assert data["metadata"]["skill"] == "scrum-review-module"
        ref = data["artifacts"][0]
        assert ref["type"] == "DOCUMENTATION"
        download = client.get(f"/artifacts/{ref['artifact_id']}/content", headers={"Authorization": "Bearer test-token"})
        assert download.status_code == 200
        assert hashlib.sha256(download.content).hexdigest() == ref["checksum"]
        text = download.content.decode("utf-8")
        assert "Báo cáo review module" in text and "AUTH" in text and "AC-AUTH-1" in text
    sys.modules.pop("api", None)


@pytest.mark.parametrize("missing", ["module_id", "tasks", "acceptance_criteria", "SOURCE_CODE", "TEST_REPORT", "evidence"])
def test_missing_inputs_block_and_still_write_report(module_task, missing, monkeypatch):
    sm, cfg, req = module_task
    cfg.sm_backend, cfg.dry_run = "antigravity", False
    import agent
    monkeypatch.setattr(agent, "review_report_with_antigravity", lambda *a, **k: pytest.fail("AI must not run for missing evidence"))
    if missing in ("SOURCE_CODE", "TEST_REPORT"):
        req.input_artifacts = [art for art in req.input_artifacts if art.type.value != missing]
    elif missing == "evidence":
        req.context["acceptance_criteria"][0]["evidence"] = ""
    else:
        req.context.pop(missing)
        if missing == "module_id":
            for task in req.context["tasks"]:
                task.pop("module_id")
    result = sm.handle(req)
    assert result.status.value == "BLOCKED", result
    assert result.error.code.value == "MISSING_CONTEXT"
    assert result.outputs[0]["verdict"] == "BLOCKED"
    assert result.outputs[0]["can_start_next_module"] is False
    assert result.outputs[0]["missing_inputs"]
    assert result.artifacts[0].type.value == "DOCUMENTATION"


@pytest.mark.parametrize("failure", ["unfinished", "blocked", "criterion_fail", "test_fail", "critical_finding"])
def test_failed_module_cannot_advance(module_task, failure):
    sm, cfg, req = module_task
    if failure == "unfinished":
        req.context["tasks"][0]["status"] = "RUNNING"
    elif failure == "blocked":
        req.context["tasks"][0]["blocked_reason"] = "Chưa sửa lỗi bàn giao"
    elif failure == "criterion_fail":
        req.context["acceptance_criteria"][0]["status"] = "FAIL"
    else:
        report = req.input_artifacts[1]
        path = Path(cfg.artifact_dir) / "inbox" / report.created_by / report.name
        payload = {"verdict": "FAIL" if failure == "test_fail" else "PASS", "findings": []}
        if failure == "critical_finding":
            payload["findings"] = [{"severity": "CRITICAL", "title": "Chưa xử lý lỗi"}]
        path.write_text(json.dumps(payload), encoding="utf-8")
        report.checksum = hashlib.sha256(path.read_bytes()).hexdigest()
        # A contradictory PM override must not replace the JSON artifact verdict.
        req.context["test_result"] = {"artifact_id": report.artifact_id, "verdict": "PASS", "evidence": "PM override"}
    result = sm.handle(req)
    assert result.status.value == "BLOCKED", result
    assert result.outputs[0]["verdict"] == "FAIL"
    assert result.outputs[0]["can_start_next_module"] is False
    assert result.artifacts


def test_markdown_test_report_requires_bound_pm_result(module_task):
    sm, cfg, req = module_task
    report = req.input_artifacts[1]
    path = Path(cfg.artifact_dir) / "inbox" / report.created_by / report.name
    path.write_text("# Test report\nValid login passed", encoding="utf-8")
    report.checksum = hashlib.sha256(path.read_bytes()).hexdigest()
    req.context["test_result"] = {"artifact_id": "WRONG-ID", "verdict": "PASS", "evidence": "Valid login passed"}
    assert sm.handle(req).status.value == "BLOCKED"
    req.task_id = "SM-MODULE-2"
    req.context["test_result"]["artifact_id"] = report.artifact_id
    result = sm.handle(req)
    assert result.status.value == "COMPLETED", result
    assert result.outputs[0]["test_result"]["evidence_source"] == "pm_supplied_test_result"


@pytest.mark.parametrize("ai_success", [True, False])
def test_ai_cannot_override_failed_verdict(module_task, monkeypatch, ai_success):
    sm, cfg, req = module_task
    cfg.sm_backend, cfg.dry_run = "antigravity", False
    req.context["acceptance_criteria"][0]["status"] = "FAIL"
    import agent
    def review(report, **kwargs):
        assert "scrum-review-module" in kwargs["skill_instructions"]
        assert "Kết luận: FAIL" in report
        return {"used": ai_success, "status": "success" if ai_success else "fallback",
                "review": "AI đề nghị PASS", "reason": "" if ai_success else "ai_timeout"}
    monkeypatch.setattr(agent, "review_report_with_antigravity", review)
    result = sm.handle(req)
    assert result.status.value == "BLOCKED"
    assert result.outputs[0]["verdict"] == "FAIL"
    assert result.metadata["ai_used"] is ai_success


def test_foreign_module_tasks_rejected(module_task):
    sm, _, req = module_task
    req.context["tasks"][0]["module_id"] = "OTHER"
    result = sm.handle(req)
    assert result.status.value == "FAILED"
    assert result.error.code.value == "INVALID_INPUT"
