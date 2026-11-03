import hashlib
import json
import logging
import os
import sys
from pathlib import Path
from typing import Any

import httpx
import yaml

from agent_contract.enums import AgentRole, ArtifactType
from agent_contract.models import ArtifactRef, Constraints, TaskRequest, TaskResult
from conductor.state import ArtifactRecord, ProjectState

logger = logging.getLogger("pm.conductor.dispatcher")
ROOT_DIR = Path(__file__).resolve().parent.parent.parent.parent


def load_env_lan() -> None:
    """Tự động nạp cấu hình token từ .env.lan nếu có."""
    for p in [ROOT_DIR / ".env.lan", ROOT_DIR / "scripts" / ".env.lan"]:
        if p.exists():
            with open(p, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line and not line.startswith("#") and "=" in line:
                        k, v = line.split("=", 1)
                        os.environ.setdefault(k.strip(), v.strip())


def load_endpoints() -> dict[str, str]:
    """Đọc file scripts/endpoints.yaml, fallback sang endpoints.example.yaml nếu chưa có."""
    yaml_path = ROOT_DIR / "scripts" / "endpoints.yaml"
    if not yaml_path.exists():
        yaml_path = ROOT_DIR / "scripts" / "endpoints.example.yaml"
    if not yaml_path.exists():
        raise FileNotFoundError("Không tìm thấy endpoints.yaml hoặc endpoints.example.yaml")
    with open(yaml_path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f)
    if not isinstance(data, dict):
        raise ValueError("File cấu hình endpoints YAML không hợp lệ.")
    return {str(k).lower(): str(v).rstrip("/") for k, v in data.items()}


def get_token_for_agent(agent_id: str) -> str:
    """Lấy Bearer token của agent từ biến môi trường AGENT_API_KEY_<AGENT_ID> hoặc AGENT_API_KEY."""
    load_env_lan()
    env_var_name = f"AGENT_API_KEY_{agent_id.upper().replace('-', '_')}"
    token = os.environ.get(env_var_name)
    if not token:
        token = os.environ.get("AGENT_API_KEY", "")
    return token.strip()


def find_agent_id_for_role(role: AgentRole | str, endpoints: dict[str, str]) -> str:
    """Xác định agent_id tương ứng với vai trò (AgentRole) dựa trên cấu hình endpoints."""
    role_str = role.value.lower() if isinstance(role, AgentRole) else str(role).lower()
    prefix = f"{role_str}-"
    for aid in endpoints.keys():
        if aid == f"{role_str}-01" or aid.startswith(prefix):
            return aid
    # Fallback mặc định
    return f"{role_str}-01"


def download_artifact(
    origin_agent_id: str,
    artifact_id: str,
    endpoints: dict[str, str],
    expected_checksum: str | None = None,
) -> tuple[bytes, str]:
    """Tải nội dung artifact từ agent nguồn (GET /artifacts/{id}/content) và kiểm tra checksum SHA-256."""
    base_url = endpoints.get(origin_agent_id.lower())
    if not base_url:
        raise ValueError(f"Không tìm thấy base URL cho agent nguồn '{origin_agent_id}'")

    token = get_token_for_agent(origin_agent_id)
    headers = {}
    if token:
        headers["Authorization"] = f"Bearer {token}"

    url = f"{base_url}/artifacts/{artifact_id}/content"
    with httpx.Client(timeout=60.0) as client:
        res = client.get(url, headers=headers)
        if res.status_code != 200:
            raise RuntimeError(f"Không thể tải artifact '{artifact_id}' từ {url} (HTTP {res.status_code}): {res.text}")

        content_bytes = res.content
        actual_sha = hashlib.sha256(content_bytes).hexdigest()
        header_sha = res.headers.get("X-Checksum-SHA256")

        if header_sha and actual_sha.lower() != header_sha.lower():
            raise ValueError(
                f"Sai lệch checksum SHA-256 từ header tải về của artifact '{artifact_id}'. "
                f"Nhận: {actual_sha}, Header: {header_sha}"
            )
        if expected_checksum and actual_sha.lower() != expected_checksum.lower():
            raise ValueError(
                f"Sai lệch checksum SHA-256 so với metadata của artifact '{artifact_id}'. "
                f"Nhận: {actual_sha}, Mong đợi: {expected_checksum}"
            )

        return content_bytes, actual_sha


def push_artifact_to_inbox(
    target_agent_id: str,
    artifact: ArtifactRef,
    content_bytes: bytes,
    endpoints: dict[str, str],
) -> None:
    """Đẩy file artifact vào inbox của agent đích (POST /artifacts/inbox)."""
    base_url = endpoints.get(target_agent_id.lower())
    if not base_url:
        raise ValueError(f"Không tìm thấy base URL cho agent đích '{target_agent_id}'")

    token = get_token_for_agent(target_agent_id)
    headers = {}
    if token:
        headers["Authorization"] = f"Bearer {token}"

    url = f"{base_url}/artifacts/inbox"
    files = {"file": (artifact.name, content_bytes, "application/octet-stream")}
    data = {"metadata": artifact.model_dump_json()}

    with httpx.Client(timeout=60.0) as client:
        res = client.post(url, data=data, files=files, headers=headers)
        if res.status_code not in [200, 201]:
            raise RuntimeError(
                f"Không thể đẩy artifact '{artifact.name}' vào inbox {target_agent_id} ({url}): "
                f"HTTP {res.status_code} - {res.text}"
            )


def relay_input_artifacts(
    target_agent_id: str,
    required_artifacts: list[ArtifactRecord],
    endpoints: dict[str, str],
) -> list[ArtifactRef]:
    """PM đóng vai trung chuyển: tải artifact từ agent nguồn và đẩy vào inbox của agent đích."""
    relayed_refs: list[ArtifactRef] = []
    for record in required_artifacts:
        art = record.artifact
        origin_id = record.origin_agent_id
        content_bytes, _ = download_artifact(
            origin_agent_id=origin_id,
            artifact_id=art.artifact_id,
            endpoints=endpoints,
            expected_checksum=art.checksum,
        )
        push_artifact_to_inbox(
            target_agent_id=target_agent_id,
            artifact=art,
            content_bytes=content_bytes,
            endpoints=endpoints,
        )
        relayed_refs.append(art)
    return relayed_refs


def send_task_request(
    target_agent_id: str,
    request: TaskRequest,
    endpoints: dict[str, str],
    timeout_seconds: float = 120.0,
) -> TaskResult:
    """Gửi TaskRequest qua HTTP tới agent đích (POST /tasks) và nhận về TaskResult."""
    base_url = endpoints.get(target_agent_id.lower())
    if not base_url:
        raise ValueError(f"Không tìm thấy base URL cho agent '{target_agent_id}'")

    token = get_token_for_agent(target_agent_id)
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"

    url = f"{base_url}/tasks"
    payload = request.model_dump(mode="json")

    with httpx.Client(timeout=timeout_seconds + 5.0) as client:
        res = client.post(url, json=payload, headers=headers)
        if res.status_code != 200:
            raise RuntimeError(
                f"Gọi POST /tasks tới {target_agent_id} thất bại (HTTP {res.status_code}): {res.text}"
            )
        data = res.json()
        return TaskResult.model_validate(data)
