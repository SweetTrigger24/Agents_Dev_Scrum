"""fake_agents.py - Giả lập 9 Agent độc lập theo Agent Contract v1.1.0 và Agent API v1.

Dùng cho kiểm thử tích hợp (integration tests) ngoại tuyến của PM Conductor.
Hỗ trợ tất cả pipeline actions tại Bảng 2.9 của Agent Contract.
"""

import hashlib
import io
import json
import logging
import socket
import threading
import time
import zipfile
from datetime import datetime, timezone
from typing import Any

import uvicorn
from fastapi import FastAPI, File, Form, Header, HTTPException, Request, Response, UploadFile, status
from fastapi.responses import JSONResponse

from agent_contract.enums import AgentRole, AgentStatus, ArtifactType, ErrorCode, TaskStatus
from agent_contract.models import (
    CONTRACT_VERSION,
    AgentIdentity,
    AgentState,
    ArtifactRef,
    TaskRequest,
    TaskResult,
    failed_result,
    make_error,
)
from agent_contract.registry import CAPABILITY_REGISTRY

logger = logging.getLogger("fake_agents")

def make_ref(artifact_id: str, name: str, art_type: ArtifactType, uri: str, created_by: str, checksum: str) -> ArtifactRef:
    return ArtifactRef(
        artifact_id=artifact_id,
        name=name,
        type=art_type,
        version="1.0.0",
        uri=uri,
        created_by=created_by,
        created_at=datetime.now(timezone.utc),
        checksum=checksum,
    )



class FakeState:
    """Trạng thái giả lập dùng để cấu hình hành vi cho các bài test."""

    def __init__(self) -> None:
        self.tester_failures: int = 0
        self.security_failures: int = 0
        self.corrupt_checksum: bool = False
        self.simulate_retryable_error: int = 0
        self.simulate_non_retryable_error: bool = False
        self.simulate_missing_context: int = 0
        self.deploy_received_contexts: list[dict[str, Any]] = []
        self.received_tasks: list[TaskRequest] = []
        self.artifacts_db: dict[str, tuple[bytes, ArtifactRef]] = {}
        self.inbox_files: dict[str, list[str]] = {}  # target_agent_id -> list of artifact_ids

    def reset(self) -> None:
        """Đặt lại toàn bộ trạng thái cấu hình về mặc định."""
        self.tester_failures = 0
        self.security_failures = 0
        self.corrupt_checksum = False
        self.simulate_retryable_error = 0
        self.simulate_non_retryable_error = False
        self.simulate_missing_context = 0
        self.deploy_received_contexts.clear()
        self.received_tasks.clear()
        self.artifacts_db.clear()
        self.inbox_files.clear()


def create_sample_zip() -> tuple[bytes, str]:
    """Tạo file .zip mẫu đại diện cho artifact SOURCE_CODE."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("main.py", "# Auto-generated sample source code\nprint('Hello AI Team!')\n")
        zf.writestr("requirements.txt", "fastapi>=0.110.0\npydantic>=2.0.0\n")
        zf.writestr("README.md", "# Sample Delivered Project\nImplemented by DEV agent.\n")
    data = buf.getvalue()
    sha = hashlib.sha256(data).hexdigest()
    return data, sha


def create_fake_app(fake_state: FakeState) -> FastAPI:
    """Khởi tạo FastAPI app phục vụ toàn bộ 9 Agent độc lập qua HTTP."""
    app = FastAPI(title="Fake LAN Agents Server", version=CONTRACT_VERSION)

    @app.get("/health")
    def health_check() -> dict[str, str]:
        return {
            "status": "healthy",
            "contract_version": CONTRACT_VERSION,
            "agent_version": "1.0.0",
        }

    @app.get("/agent")
    def get_agent_identity(request: Request) -> AgentIdentity:
        return AgentIdentity(
            agent_id="fake-agent",
            role=AgentRole.DEV,
            name="Fake Agent",
            version="1.0.0",
            capabilities=CAPABILITY_REGISTRY.get(AgentRole.DEV, []),
            status=AgentStatus.IDLE,
        )

    @app.get("/state")
    def get_agent_state() -> AgentState:
        return AgentState(
            agent_id="fake-agent",
            role=AgentRole.DEV,
            status=AgentStatus.IDLE,
            updated_at=datetime.now(timezone.utc),
        )

    @app.get("/artifacts")
    def list_artifacts() -> list[ArtifactRef]:
        return [ref for _, ref in fake_state.artifacts_db.values()]

    @app.get("/artifacts/{artifact_id}/content")
    def get_artifact_content(artifact_id: str) -> Response:
        if artifact_id not in fake_state.artifacts_db:
            raise HTTPException(status_code=404, detail=f"Không tìm thấy artifact '{artifact_id}'")

        content_bytes, ref = fake_state.artifacts_db[artifact_id]

        if fake_state.corrupt_checksum:
            content_bytes = b"corrupted content"
            header_sha = "0000000000000000000000000000000000000000000000000000000000000000"
        else:
            header_sha = ref.checksum or hashlib.sha256(content_bytes).hexdigest()

        return Response(
            content=content_bytes,
            media_type="application/octet-stream",
            headers={
                "X-Checksum-SHA256": header_sha,
                "Content-Disposition": f'attachment; filename="{ref.name}"',
            },
        )

    @app.post("/artifacts/inbox")
    async def receive_inbox(
        metadata: str = Form(...),
        file: UploadFile = File(...),
    ) -> ArtifactRef:
        meta_dict = json.loads(metadata)
        ref = ArtifactRef.model_validate(meta_dict)
        content_bytes = await file.read()
        sha = hashlib.sha256(content_bytes).hexdigest()

        if ref.checksum and sha.lower() != ref.checksum.lower():
            raise HTTPException(
                status_code=422,
                detail=f"ARTIFACT_ERROR: Checksum mismatch. Actual: {sha}, expected: {ref.checksum}",
            )

        fake_state.artifacts_db[ref.artifact_id] = (content_bytes, ref)
        target = ref.created_by or "unknown"
        fake_state.inbox_files.setdefault(target, []).append(ref.artifact_id)
        return ref

    @app.post("/tasks")
    def handle_task(task_req: TaskRequest) -> TaskResult:
        fake_state.received_tasks.append(task_req)
        role = task_req.role
        action = task_req.action
        now_ts = int(time.time() * 1000)

        # 1. Giả lập lỗi chập chờn mạng/server (retryable)
        if fake_state.simulate_retryable_error > 0:
            fake_state.simulate_retryable_error -= 1
            return failed_result(
                task_req,
                make_error(
                    code=ErrorCode.UNKNOWN_ERROR,
                    message="Lỗi kết nối mạng tạm thời (mô phỏng retryable)",
                    retryable=True,
                ),
                summary="Lỗi tạm thời",
            )

        # 2. Giả lập lỗi không thể thử lại (non-retryable)
        if fake_state.simulate_non_retryable_error:
            return failed_result(
                task_req,
                make_error(
                    code=ErrorCode.TOOL_ERROR,
                    message="Lỗi hệ thống nghiêm trọng không thể thử lại",
                    retryable=False,
                ),
                summary="Lỗi không thể retry",
            )

        # 3. Giả lập thiếu ngữ cảnh (MISSING_CONTEXT)
        if fake_state.simulate_missing_context > 0:
            fake_state.simulate_missing_context -= 1
            return TaskResult(
                contract_version=task_req.contract_version,
                task_id=task_req.task_id,
                agent_id=task_req.agent_id,
                status=TaskStatus.BLOCKED,
                summary="Bị chặn do thiếu ngữ cảnh dự án",
                error=make_error(
                    code=ErrorCode.MISSING_CONTEXT,
                    message="Yêu cầu cần làm rõ một số chi tiết",
                    retryable=False,
                    questions=["Quy mô dự án là gì?", "Môi trường triển khai nào?"],
                ),
            )

        artifacts: list[ArtifactRef] = []
        outputs: list[dict[str, Any]] = []

        # Xử lý theo từng Role & Action của Bảng 2.9
        if role == AgentRole.PO:
            if action == "define_backlog":
                content = json.dumps({"backlog": ["User auth", "Task API", "Deploy config"]}, indent=2).encode("utf-8")
                sha = hashlib.sha256(content).hexdigest()
                ref = make_ref(f"ART-BACKLOG-{now_ts}", "backlog.json", ArtifactType.BACKLOG, "artifacts/backlog.json", task_req.agent_id, sha)
                fake_state.artifacts_db[ref.artifact_id] = (content, ref)
                artifacts.append(ref)
                outputs.append({"epics_count": 3, "status": "defined"})

            elif action == "accept_release":
                outputs.append({"verdict": "PASS", "findings": []})
                content = b"# Acceptance Report\nRelease accepted by PO.\n"
                sha = hashlib.sha256(content).hexdigest()
                ref = make_ref(f"ART-ACCEPT-{now_ts}", "acceptance_report.md", ArtifactType.DOCUMENTATION, "artifacts/acceptance_report.md", task_req.agent_id, sha)
                fake_state.artifacts_db[ref.artifact_id] = (content, ref)
                artifacts.append(ref)

        elif role == AgentRole.BA:
            if action == "write_requirements":
                content = b"# Software Requirements Specification (SRS)\nDetailed requirements.\n"
                sha = hashlib.sha256(content).hexdigest()
                ref = make_ref(f"ART-REQ-{now_ts}", "requirements.md", ArtifactType.REQUIREMENT, "artifacts/requirements.md", task_req.agent_id, sha)
                fake_state.artifacts_db[ref.artifact_id] = (content, ref)
                artifacts.append(ref)
                outputs.append({"requirements_count": 5})

            elif action == "write_user_stories":
                content = json.dumps({"user_stories": ["US-1: Login", "US-2: CRUD", "US-3: CI/CD"]}, indent=2).encode("utf-8")
                sha = hashlib.sha256(content).hexdigest()
                ref = make_ref(f"ART-US-{now_ts}", "user_stories.json", ArtifactType.USER_STORY, "artifacts/user_stories.json", task_req.agent_id, sha)
                fake_state.artifacts_db[ref.artifact_id] = (content, ref)
                artifacts.append(ref)
                outputs.append({"stories_count": 3})

        elif role == AgentRole.SA:
            if action == "design_architecture":
                content = b"# System Architecture\nComponent diagrams and microservices.\n"
                sha = hashlib.sha256(content).hexdigest()
                ref = make_ref(f"ART-ARCH-{now_ts}", "architecture.md", ArtifactType.ARCHITECTURE, "artifacts/architecture.md", task_req.agent_id, sha)
                fake_state.artifacts_db[ref.artifact_id] = (content, ref)
                artifacts.append(ref)
                outputs.append({"arch_style": "modular_monolith"})

        elif role == AgentRole.DBA:
            if action == "design_schema":
                content = b"CREATE TABLE users (id SERIAL PRIMARY KEY, username VARCHAR(50));\n"
                sha = hashlib.sha256(content).hexdigest()
                ref = make_ref(f"ART-SCHEMA-{now_ts}", "schema.sql", ArtifactType.DATABASE_SCHEMA, "artifacts/schema.sql", task_req.agent_id, sha)
                fake_state.artifacts_db[ref.artifact_id] = (content, ref)
                artifacts.append(ref)
                outputs.append({"tables": ["users"]})

        elif role == AgentRole.DEV:
            if action in ["implement_project", "fix_bugs"]:
                zip_bytes, zip_sha = create_sample_zip()
                ref = make_ref(f"ART-SRC-{now_ts}", "source_code.zip", ArtifactType.SOURCE_CODE, "artifacts/source_code.zip", task_req.agent_id, zip_sha)
                fake_state.artifacts_db[ref.artifact_id] = (zip_bytes, ref)
                artifacts.append(ref)
                outputs.append({"files": ["main.py", "requirements.txt", "README.md"]})

        elif role == AgentRole.TESTER:
            if action == "create_test_cases":
                content = json.dumps({"test_cases": ["TC-01", "TC-02"]}, indent=2).encode("utf-8")
                sha = hashlib.sha256(content).hexdigest()
                ref = make_ref(f"ART-TC-{now_ts}", "test_cases.json", ArtifactType.TEST_CASE, "artifacts/test_cases.json", task_req.agent_id, sha)
                fake_state.artifacts_db[ref.artifact_id] = (content, ref)
                artifacts.append(ref)
                outputs.append({"tc_count": 2})

            elif action == "run_test_suite":
                if fake_state.tester_failures > 0:
                    fake_state.tester_failures -= 1
                    outputs.append({
                        "verdict": "FAIL",
                        "findings": [
                            {
                                "severity": "HIGH",
                                "title": "Unit test failure in auth",
                                "detail": "AssertionError: expected 200 got 500",
                            }
                        ],
                    })
                else:
                    outputs.append({"verdict": "PASS", "findings": []})

                content = json.dumps(outputs[0], indent=2).encode("utf-8")
                sha = hashlib.sha256(content).hexdigest()
                ref = make_ref(f"ART-TESTRPT-{now_ts}", "test_report.json", ArtifactType.TEST_REPORT, "artifacts/test_report.json", task_req.agent_id, sha)
                fake_state.artifacts_db[ref.artifact_id] = (content, ref)
                artifacts.append(ref)

        elif role == AgentRole.SECURITY:
            if action == "security_review":
                if fake_state.security_failures > 0:
                    fake_state.security_failures -= 1
                    outputs.append({
                        "verdict": "FAIL",
                        "findings": [
                            {
                                "severity": "CRITICAL",
                                "title": "SQL Injection found",
                                "detail": "Raw SQL concatenation detected.",
                            }
                        ],
                    })
                else:
                    outputs.append({"verdict": "PASS", "findings": []})

                content = json.dumps(outputs[0], indent=2).encode("utf-8")
                sha = hashlib.sha256(content).hexdigest()
                ref = make_ref(f"ART-SECRPT-{now_ts}", "security_report.json", ArtifactType.SECURITY_REPORT, "artifacts/security_report.json", task_req.agent_id, sha)
                fake_state.artifacts_db[ref.artifact_id] = (content, ref)
                artifacts.append(ref)

        elif role == AgentRole.DEVOPS:
            if action in ["generate_ci_config", "build_image", "deploy", "health_check"]:
                if action == "deploy":
                    fake_state.deploy_received_contexts.append(dict(task_req.context))
                content = b"deployment_status: ok\n"
                sha = hashlib.sha256(content).hexdigest()
                ref = make_ref(f"ART-DEPLOY-{now_ts}", "deployment.yaml", ArtifactType.DEPLOYMENT, "artifacts/deployment.yaml", task_req.agent_id, sha)
                fake_state.artifacts_db[ref.artifact_id] = (content, ref)
                artifacts.append(ref)
                outputs.append({"deploy": "success"})

        elif role == AgentRole.SCRUM_MASTER:
            if action in ["run_retrospective", "track_blockers"]:
                content = b"# Retrospective Notes\nGood collaboration.\n"
                sha = hashlib.sha256(content).hexdigest()
                ref = make_ref(f"ART-RETRO-{now_ts}", "retro.md", ArtifactType.DOCUMENTATION, "artifacts/retro.md", task_req.agent_id, sha)
                fake_state.artifacts_db[ref.artifact_id] = (content, ref)
                artifacts.append(ref)
                outputs.append({"retro": "completed"})

        return TaskResult(
            contract_version=task_req.contract_version,
            task_id=task_req.task_id,
            agent_id=task_req.agent_id,
            status=TaskStatus.COMPLETED,
            summary=f"Fake {role.value} executed {action} successfully.",
            outputs=outputs,
            artifacts=artifacts,
        )

    return app


class FakeAgentsServer:
    """Quản lý tiến trình HTTP server nền của Fake Agents phục vụ kiểm thử."""

    def __init__(self, port: int | None = None) -> None:
        self.state = FakeState()
        self.port = port or self._get_free_port()
        self.app = create_fake_app(self.state)
        self.server: uvicorn.Server | None = None
        self.thread: threading.Thread | None = None

    @staticmethod
    def _get_free_port() -> int:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.bind(("127.0.0.1", 0))
            return s.getsockname()[1]

    def start(self) -> None:
        """Khởi động uvicorn server trong một daemon thread."""
        config = uvicorn.Config(
            self.app,
            host="127.0.0.1",
            port=self.port,
            log_level="error",
        )
        self.server = uvicorn.Server(config)
        self.thread = threading.Thread(target=self.server.run, daemon=True)
        self.thread.start()

        # Đợi server sẵn sàng
        start_time = time.time()
        while not self.server.started:
            if time.time() - start_time > 5.0:
                raise TimeoutError("Không thể khởi động FakeAgentsServer trong 5 giây.")
            time.sleep(0.05)

    def stop(self) -> None:
        """Dừng server."""
        if self.server:
            self.server.should_exit = True
        if self.thread:
            self.thread.join(timeout=2.0)

    def get_endpoints(self) -> dict[str, str]:
        """Tạo bảng endpoints ánh xạ toàn bộ 9 agent về server giả lập này."""
        base_url = f"http://127.0.0.1:{self.port}"
        return {
            "po-01": base_url,
            "ba-01": base_url,
            "sa-01": base_url,
            "dba-01": base_url,
            "dev-01": base_url,
            "tester-01": base_url,
            "security-01": base_url,
            "devops-01": base_url,
            "scrum_master-01": base_url,
        }


if __name__ == "__main__":
    server = FakeAgentsServer(port=8080)
    print(f"Starting FakeAgentsServer on port {server.port}...")
    server.start()
    try:
        while True:
            time.sleep(1.0)
    except KeyboardInterrupt:
        server.stop()
        print("Stopped.")
