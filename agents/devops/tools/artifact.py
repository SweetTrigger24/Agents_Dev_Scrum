import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Union

from agent_contract.enums import ArtifactType
from agent_contract.models import ArtifactRef
from agent_contract.validators import validate_agent_id


class ArtifactError(Exception):
    """Ngoại lệ phát sinh trong quá trình xử lý hoặc truy cập Artifact."""
    pass


DEFAULT_ARTIFACT_DIR = Path("./artifacts")


def _get_target_dir(base_dir: Union[Path, str, None] = None) -> Path:
    """Xác định và tạo thư mục artifact mục tiêu."""
    target = Path(base_dir) if base_dir is not None else DEFAULT_ARTIFACT_DIR
    target.mkdir(parents=True, exist_ok=True)
    return target.resolve()


def _check_safe_filename(name: str, base_dir: Path) -> Path:
    """Kiểm tra và ngăn chặn triệt để lỗ hổng path traversal."""
    normalized = name.replace("\\", "/")
    if ".." in normalized.split("/"):
        raise ArtifactError(f"Phát hiện path traversal trong tên file: '{name}'")

    if normalized.startswith("/") or re.match(r"^[a-zA-Z]:", name):
        raise ArtifactError(f"Tên file không được là đường dẫn tuyệt đối: '{name}'")

    target_path = (base_dir / name).resolve()
    try:
        target_path.relative_to(base_dir)
    except ValueError:
        raise ArtifactError(f"Đường dẫn mục tiêu nằm ngoài thư mục artifact cho phép: '{name}'")

    return target_path


def list_artifacts(artifact_dir: Union[Path, str, None] = None) -> list[ArtifactRef]:
    """Đọc danh sách toàn bộ Artifact đã lưu trữ từ index.json."""
    base_dir = _get_target_dir(artifact_dir)
    index_file = base_dir / "index.json"
    if not index_file.exists():
        return []

    try:
        with open(index_file, "r", encoding="utf-8") as f:
            data = json.load(f)
            if not isinstance(data, list):
                return []
            return [ArtifactRef.model_validate(item) for item in data]
    except Exception as e:
        raise ArtifactError(f"Không thể đọc file index.json: {e}") from e


def _get_next_artifact_id(existing_artifacts: list[ArtifactRef]) -> str:
    """Tự động tính mã định danh ART-xxx tăng dần."""
    max_num = 0
    pattern = re.compile(r"^ART-(\d+)$")
    for art in existing_artifacts:
        match = pattern.match(art.artifact_id)
        if match:
            num = int(match.group(1))
            if num > max_num:
                max_num = num
    return f"ART-{max_num + 1:03d}"


def save_artifact(
    name: str,
    type: ArtifactType,
    content: Union[str, bytes],
    created_by: str,
    artifact_dir: Union[Path, str, None] = None,
) -> ArtifactRef:
    """Ghi artifact vào đĩa, kiểm tra path traversal, tính sha256 và cập nhật index.json."""
    validate_agent_id(created_by)
    base_dir = _get_target_dir(artifact_dir)
    target_path = _check_safe_filename(name, base_dir)
    target_path.parent.mkdir(parents=True, exist_ok=True)

    if isinstance(content, str):
        content_bytes = content.encode("utf-8")
    else:
        content_bytes = content

    checksum = hashlib.sha256(content_bytes).hexdigest()

    try:
        with open(target_path, "wb") as f:
            f.write(content_bytes)
    except Exception as e:
        raise ArtifactError(f"Ghi file artifact thất bại '{name}': {e}") from e

    existing = list_artifacts(base_dir)
    new_id = _get_next_artifact_id(existing)
    rel_uri = f"artifacts/{name}".replace("//", "/")

    ref = ArtifactRef(
        artifact_id=new_id,
        name=name,
        type=type,
        version="1.0",
        uri=rel_uri,
        created_by=created_by,
        created_at=datetime.now(timezone.utc),
        checksum=checksum,
    )

    existing.append(ref)
    index_file = base_dir / "index.json"
    try:
        with open(index_file, "w", encoding="utf-8") as f:
            json_data = [art.model_dump(mode="json") for art in existing]
            json.dump(json_data, f, indent=2, ensure_ascii=False)
            f.write("\n")
    except Exception as e:
        raise ArtifactError(f"Cập nhật file index.json thất bại: {e}") from e

    return ref


def read_artifact(
    ref: Union[ArtifactRef, str],
    artifact_dir: Union[Path, str, None] = None,
) -> str:
    """Đọc nội dung của một artifact từ đĩa theo ArtifactRef hoặc đường dẫn/ID."""
    base_dir = _get_target_dir(artifact_dir)

    target_name: str
    if isinstance(ref, ArtifactRef):
        target_name = ref.name
    elif isinstance(ref, str):
        if ref.startswith("ART-"):
            for item in list_artifacts(base_dir):
                if item.artifact_id == ref:
                    target_name = item.name
                    break
            else:
                raise ArtifactError(f"Không tìm thấy artifact có mã '{ref}' trong index.json")
        else:
            target_name = ref
            if target_name.startswith("artifacts/"):
                target_name = target_name[len("artifacts/"):]
    else:
        raise ArtifactError(f"Tham số ref không hợp lệ: {ref}")

    target_path = _check_safe_filename(target_name, base_dir)

    if not target_path.exists() or not target_path.is_file():
        raise ArtifactError(f"File artifact không tồn tại: '{target_name}'")

    try:
        with open(target_path, "r", encoding="utf-8") as f:
            return f.read()
    except UnicodeDecodeError:
        with open(target_path, "rb") as f:
            return f.read().decode("utf-8", errors="replace")
    except Exception as e:
        raise ArtifactError(f"Không thể đọc file artifact '{target_name}': {e}") from e
