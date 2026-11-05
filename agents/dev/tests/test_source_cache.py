import hashlib
import io
import json
import sys
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import agent
from config import AgentConfig
from agent_contract import AgentIdentity, ArtifactRef, TaskRequest
from agent_contract.enums import AgentRole
from agent_contract.registry import CAPABILITY_REGISTRY
from tools.source_cache import cache_path


@pytest.fixture
def dev_runner(tmp_path, monkeypatch):
    cfg = AgentConfig(base_dir=tmp_path, port=8006, host="127.0.0.1", agent_id="dev-01", agent_role="DEV",
        dry_run=False, dev_backend="codex")
    identity = AgentIdentity(agent_id="dev-01", role="DEV", name="DEV", version="1.0",
                             capabilities=CAPABILITY_REGISTRY[AgentRole.DEV])
    state = {"request": None, "edit": None, "partial": False, "omit_report": False, "calls": 0}
    monkeypatch.setattr(agent.shutil, "which", lambda _: "fake-codex")
    def run(argv, **kwargs):
        state["calls"] += 1
        workspace = Path(kwargs["cwd"])
        if state["edit"]:
            state["edit"](workspace)
        if not state["omit_report"]:
            (workspace / "delivery_report.json").write_text(json.dumps({
                "action": state["request"].action, "scope_status": "PARTIAL" if state["partial"] else "COMPLETE",
                "summary": "Task done", "acceptance": [{"id": "AC-1", "status": "IMPLEMENTED", "evidence": "Files created"}],
                "changes": [], "checks": [{"command": "test", "status": "NOT_RUN", "evidence": "Mock"}],
                "findings": [], "unresolved": ["Remaining work"] if state["partial"] else [],
            }))
        return SimpleNamespace(returncode=0, stdout="done", stderr="")
    monkeypatch.setattr(agent.subprocess, "run", run)
    def execute(task_id, action="implement_project", project="PROJECT-A", refs=None, context=None, edit=None):
        req = TaskRequest(task_id=task_id, project_id=project, agent_id="dev-01", role="DEV", action=action,
            instruction="Implement requested module", context=context or {}, input_artifacts=refs or [])
        state.update(request=req, edit=edit)
        # Reconstruct the agent to exercise persistence across process restarts.
        return agent.DeveloperAgent(identity.model_copy(deep=True), cfg).handle(req)
    return execute, cfg, state


def seed(execute):
    return execute("MODULE-1", edit=lambda workspace: (workspace / "base.py").write_text("module-one"))


def test_next_module_restores_project_source_and_packages_integrated_code(dev_runner):
    execute, cfg, _ = dev_runner
    first = seed(execute)
    assert first.status.value == "COMPLETED"
    assert first.metadata["source_checkpoint_saved"] is True
    def edit(workspace):
        assert (workspace / "base.py").read_text() == "module-one"
        (workspace / "feature.py").write_text("module-two")
    result = execute("MODULE-2", context={"continue_project": True}, edit=edit)
    assert result.status.value == "COMPLETED", result
    assert result.metadata["source_input"]["origin"] == "local_project_cache"
    assert result.metadata["source_input"]["source_task_id"] == "MODULE-1"
    with zipfile.ZipFile(Path(cfg.artifact_dir) / result.artifacts[0].name) as archive:
        assert {"base.py", "feature.py"} <= set(archive.namelist())


@pytest.mark.parametrize("action", ["fix_bugs", "refactor_code", "review_code"])
def test_actions_can_use_local_source_and_review_does_not_advance_checkpoint(dev_runner, action):
    execute, cfg, _ = dev_runner
    seed(execute)
    def edit(workspace):
        assert (workspace / "base.py").read_text() == "module-one"
        if action != "review_code":
            (workspace / "base.py").write_text("updated")
    result = execute("FOLLOWUP", action=action, edit=edit)
    assert result.status.value == "COMPLETED", result
    saved = json.loads(cache_path(cfg.data_dir, "PROJECT-A").read_text())
    assert saved["task_id"] == ("MODULE-1" if action == "review_code" else "FOLLOWUP")


def test_project_isolation_and_explicit_continuation(dev_runner):
    execute, cfg, state = dev_runner
    seed(execute)
    result = execute("OTHER", action="fix_bugs", project="PROJECT-B")
    assert result.status.value == "BLOCKED"
    result = execute("NEW-CONTINUE", project="../../other", context={"continue_project": True})
    assert result.status.value == "BLOCKED"
    assert state["calls"] == 1
    assert not cache_path(cfg.data_dir, "../../other").exists()


@pytest.mark.parametrize("bad", ["partial", "missing_report", "sample"])
def test_unsuccessful_or_demo_source_does_not_replace_checkpoint(dev_runner, bad):
    execute, cfg, state = dev_runner
    seed(execute)
    if bad == "partial":
        state["partial"] = True
    elif bad == "missing_report":
        state["omit_report"] = True
    else:
        cfg.dev_backend = "sample"
    result = execute("BAD", edit=lambda workspace: (workspace / "base.py").write_text("bad-version"))
    assert result.status.value in ("BLOCKED", "FAILED")
    assert json.loads(cache_path(cfg.data_dir, "PROJECT-A").read_text())["task_id"] == "MODULE-1"


@pytest.mark.parametrize("bad", ["deleted", "corrupted"])
def test_missing_or_corrupted_checkpoint_never_starts_fresh(dev_runner, bad):
    execute, cfg, state = dev_runner
    first = seed(execute)
    file = Path(cfg.artifact_dir) / first.artifacts[0].name
    if bad == "deleted":
        file.unlink()
    else:
        file.write_bytes(b"corrupted")
    result = execute("NEXT")
    assert result.status.value == "BLOCKED"
    assert state["calls"] == 1


def make_pm_source(cfg, content="pm-authoritative"):
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("base.py", content)
    folder = Path(cfg.artifact_dir) / "inbox" / "dev-02"
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "pm-source.zip").write_bytes(buffer.getvalue())
    return ArtifactRef(artifact_id="ART-PM", name="pm-source.zip", type="SOURCE_CODE",
        uri="artifacts/pm-source.zip", created_by="dev-02", created_at=datetime.now(timezone.utc),
        checksum=hashlib.sha256(buffer.getvalue()).hexdigest())


def test_valid_pm_source_takes_priority_over_local_checkpoint(dev_runner):
    execute, cfg, _ = dev_runner
    seed(execute)
    ref = make_pm_source(cfg)
    def edit(workspace):
        assert (workspace / "base.py").read_text() == "pm-authoritative"
    result = execute("WITH-PM", refs=[ref], edit=edit)
    assert result.status.value == "COMPLETED", result
    assert result.metadata["source_input"]["origin"] == "pm_relay"


def test_pm_can_send_just_local_artifact_metadata_without_upload(dev_runner):
    execute, _, _ = dev_runner
    first = seed(execute)
    result = execute("LOCAL-REF", refs=[first.artifacts[0]],
        edit=lambda workspace: (workspace / "base.py").read_text())
    assert result.status.value == "COMPLETED", result
    assert result.metadata["source_input"]["origin"] == "local_artifact"


def test_failed_relay_can_use_matching_checkpoint_but_not_another_version(dev_runner):
    execute, _, state = dev_runner
    first = seed(execute)
    missing = first.artifacts[0].model_copy(update={"name": "not-relayed.zip", "uri": "artifacts/not-relayed.zip"})
    result = execute("FALLBACK", refs=[missing])
    assert result.status.value == "COMPLETED", result
    assert result.metadata["source_input"]["fallback_reason"] == "pm_source_not_relayed"
    missing.checksum = "a" * 64
    result = execute("WRONG-VERSION", refs=[missing])
    assert result.status.value == "BLOCKED"
    assert state["calls"] == 2


def test_corrupt_pm_source_and_missing_non_source_artifacts_still_block(dev_runner):
    execute, cfg, state = dev_runner
    seed(execute)
    ref = make_pm_source(cfg)
    ref.checksum = "b" * 64
    assert execute("CORRUPT-PM", refs=[ref]).status.value == "BLOCKED"
    report = ref.model_copy(update={"type": "TEST_REPORT", "name": "absent.json", "uri": "artifacts/absent.json", "checksum": None})
    assert execute("NO-TEST-REPORT", action="fix_bugs", refs=[report]).status.value == "BLOCKED"
    assert state["calls"] == 1
