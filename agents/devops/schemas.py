from typing import Any
from pydantic import BaseModel, Field, model_validator


class CommandItem(BaseModel):
    """Chi tiết một lệnh trong kế hoạch thực thi của DevOps."""

    command: list[str]
    explanation: str


class CommandPlan(BaseModel):
    """Kế hoạch thực thi danh sách lệnh được đề xuất bởi LLM."""

    action: str
    commands: list[list[str]]
    explanation: str
    rollback_plan: list[list[str]] = Field(default_factory=list)
    estimated_duration_seconds: int = 30


class BuildReport(BaseModel):
    """Báo cáo kết quả đóng gói Docker image."""

    image_name: str
    tag: str = "latest"
    status: str = "SUCCESS"  # SUCCESS | FAILED | DRY_RUN
    logs_tail: str = ""
    duration_seconds: float = 0.0


class TestRunReport(BaseModel):
    """Báo cáo kết quả thực thi kiểm thử tự động."""

    test_framework: str = "pytest"
    total_tests: int = 0
    passed: int = 0
    failed: int = 0
    skipped: int = 0
    duration_seconds: float = 0.0
    output_summary: str = ""


class DeploymentReport(BaseModel):
    """Báo cáo triển khai dịch vụ lên môi trường mục tiêu (bắt buộc có rollback_plan)."""

    service_name: str
    environment: str  # staging | prod | dev
    version: str
    status: str = "SUCCESS"  # SUCCESS | FAILED | DRY_RUN
    rollback_plan: list[str]
    deployed_url: str | None = None
    logs_tail: str = ""

    @model_validator(mode="after")
    def validate_rollback_plan(self) -> "DeploymentReport":
        """Xác thực bắt buộc phải có kế hoạch rollback khi deploy."""
        if not self.rollback_plan or len(self.rollback_plan) == 0:
            raise ValueError("Deployment bắt buộc phải có rollback_plan (kế hoạch phục hồi khi lỗi).")
        return self


class HealthCheckReport(BaseModel):
    """Báo cáo kiểm tra sức khỏe của dịch vụ sau triển khai."""

    endpoint: str
    status_code: int = 200
    status: str = "HEALTHY"  # HEALTHY | UNHEALTHY | DRY_RUN
    latency_ms: float = 0.0
    response_body_sample: str = ""


class GitOperationReport(BaseModel):
    """Báo cáo thao tác với hệ thống quản lý mã nguồn Git."""

    operation: str
    branch: str = "main"
    commit_hash: str | None = None
    status: str = "SUCCESS"
    message: str = ""


class CIConfigReport(BaseModel):
    """Báo cáo sinh cấu hình CI/CD (GitHub Actions / Dockerfile / Compose)."""

    config_type: str
    filename: str
    content: str
    artifact_uri: str


class MonitoringReport(BaseModel):
    """Báo cáo thiết lập cấu hình giám sát (Prometheus / Grafana)."""

    monitoring_type: str
    config_filename: str
    content: str
    artifact_uri: str
