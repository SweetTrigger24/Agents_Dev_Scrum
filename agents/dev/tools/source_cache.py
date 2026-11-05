"""Keep a project-specific pointer to the last successful source handoff."""
import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path

from agent_contract import ArtifactRef
from agent_contract.enums import ArtifactType


class SourceUnavailable(ValueError):
    pass


def resolve_input_file(artifact: ArtifactRef, artifact_dir: str) -> Path | None:
    root = Path(artifact_dir).resolve()
    name = Path(artifact.name).name
    candidates = [root / "inbox" / artifact.created_by / name, root / "inbox" / name,
                  root.parent / artifact.uri, root / artifact.uri, root / name]
    existing = []
    for candidate in candidates:
        resolved = candidate.resolve()
        if resolved.is_relative_to(root) and resolved.is_file() and not candidate.is_symlink():
            if resolved not in existing:
                existing.append(resolved)
            if not artifact.checksum or hashlib.sha256(resolved.read_bytes()).hexdigest().lower() == artifact.checksum.lower():
                return resolved
    # Let the checksum validation report corruption instead of treating it as
    # an absent relay and silently selecting a different source.
    return existing[0] if existing else None


def checked_source(artifact: ArtifactRef, artifact_dir: str) -> Path | None:
    if not artifact.name.lower().endswith(".zip"):
        raise SourceUnavailable("Artifact SOURCE_CODE phải là ZIP.")
    file = resolve_input_file(artifact, artifact_dir)
    if file and artifact.checksum and hashlib.sha256(file.read_bytes()).hexdigest().lower() != artifact.checksum.lower():
        raise SourceUnavailable("Source được chỉ định sai checksum; không tự dùng bản khác.")
    return file


def cache_path(data_dir: str, project_id: str) -> Path:
    return Path(data_dir) / "project_sources" / (hashlib.sha256(project_id.encode()).hexdigest() + ".json")


def load_source(config, project_id: str, agent_id: str):
    path = cache_path(config.data_dir, project_id)
    if not path.exists():
        return None
    try:
        record = json.loads(path.read_text(encoding="utf-8"))
        if record["project_id"] != project_id or record["agent_id"] != agent_id:
            raise ValueError("Project mismatch")
        artifact = ArtifactRef.model_validate(record["artifact"])
        if artifact.type != ArtifactType.SOURCE_CODE or artifact.created_by != agent_id or not artifact.checksum:
            raise ValueError("Invalid source provenance")
        if checked_source(artifact, config.artifact_dir) is None:
            raise ValueError("Source file is missing")
        return artifact, record["task_id"]
    except (OSError, ValueError, KeyError, TypeError) as err:
        raise SourceUnavailable("Bản source lưu của dự án bị thiếu hoặc không hợp lệ; cần PM gửi lại source.") from err


def prepare_source(request, config, agent_id: str):
    sources = [art for art in request.input_artifacts if art.type == ArtifactType.SOURCE_CODE]
    if len(sources) > 1:
        raise SourceUnavailable("Chỉ nhận một SOURCE_CODE tích hợp làm đầu vào mỗi task.")
    expected = sources[0] if sources else None
    if expected:
        file = checked_source(expected, config.artifact_dir)
        if file:
            origin = "pm_relay" if file.is_relative_to(Path(config.artifact_dir).resolve() / "inbox") else "local_artifact"
            return request, {"origin": origin, "artifact_id": expected.artifact_id,
                             "checksum": hashlib.sha256(file.read_bytes()).hexdigest()}
    cached = load_source(config, request.project_id, agent_id)
    if cached:
        artifact, task_id = cached
        if expected:
            matches = (artifact.checksum.lower() == expected.checksum.lower()) if expected.checksum else (
                artifact.artifact_id == expected.artifact_id and artifact.created_by == expected.created_by)
            if not matches:
                raise SourceUnavailable("Source PM yêu cầu khác bản lưu dự án; không tự thay bằng phiên bản cũ.")
        inputs = [art for art in request.input_artifacts if art.type != ArtifactType.SOURCE_CODE] + [artifact]
        return request.model_copy(update={"input_artifacts": inputs}), {
            "origin": "local_project_cache", "artifact_id": artifact.artifact_id,
            "checksum": artifact.checksum, "source_task_id": task_id,
            "fallback_reason": "pm_source_not_relayed" if expected else "pm_source_not_supplied"}
    if expected or request.action != "implement_project" or request.context.get("continue_project") is True:
        raise SourceUnavailable("PM chưa gửi source và DEV chưa có bản source hoàn tất của cùng project_id để làm tiếp.")
    return request, {"origin": "new_project"}


def save_source(config, project_id: str, agent_id: str, task_id: str, artifact: ArtifactRef) -> None:
    # Point only at the immutable artifact, never at a workspace modified by AI.
    if artifact.created_by != agent_id or not artifact.checksum or checked_source(artifact, config.artifact_dir) is None:
        raise SourceUnavailable("Không xác minh được source vừa bàn giao.")
    path = cache_path(config.data_dir, project_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps({"project_id": project_id, "agent_id": agent_id, "task_id": task_id,
        "artifact": artifact.model_dump(mode="json"), "updated_at": datetime.now(timezone.utc).isoformat()},
        ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(temporary, path)
