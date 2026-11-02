import time
from typing import Sequence

import httpx

from schemas import DeploymentReport, HealthCheckReport
from tools.terminal import SecurityViolationError, TerminalExecutor


def deploy(
    service_name: str,
    environment: str,
    image_tag: str,
    rollback_plan: list[str],
    terminal: TerminalExecutor | None = None,
    execute: bool = False,
) -> DeploymentReport:
    """Thực hiện quy trình triển khai dịch vụ thông qua TerminalExecutor."""
    if terminal is None:
        raise ValueError("Yêu cầu TerminalExecutor.")

    env_norm = environment.lower().strip()
    if env_norm in ["prod", "production"]:
        raise SecurityViolationError(
            f"Triển khai lên môi trường '{environment}' bị chặn tuyệt đối! "
            f"Bắt buộc phải có sự phê duyệt trực tiếp của con người (PERMISSION_DENIED)."
        )

    if not rollback_plan or len(rollback_plan) == 0:
        raise ValueError("Kế hoạch triển khai bắt buộc phải có rollback_plan.")

    # Chạy lệnh docker compose up -d qua TerminalExecutor
    cmd = ["docker", "compose", "up", "-d"]
    exec_res = terminal.run(cmd, execute=execute)

    status_str = "DRY_RUN" if exec_res.dry_run else "SUCCESS"
    deployed_url = f"https://{service_name}.staging.internal" if env_norm == "staging" else f"http://localhost:8080"

    return DeploymentReport(
        service_name=service_name,
        environment=environment,
        version=image_tag,
        status=status_str,
        rollback_plan=rollback_plan,
        deployed_url=deployed_url,
        logs_tail=exec_res.stdout[:500],
    )


def health_check(
    endpoint: str,
    timeout: float = 5.0,
    dry_run: bool = True,
) -> HealthCheckReport:
    """Kiểm tra sức khỏe dịch vụ bằng HTTP request với timeout."""
    if dry_run:
        return HealthCheckReport(
            endpoint=endpoint,
            status_code=200,
            status="HEALTHY",
            latency_ms=15.0,
            response_body_sample='{"status": "ok", "dry_run": true}',
        )

    start_time = time.perf_counter()
    try:
        with httpx.Client(timeout=timeout) as client:
            response = client.get(endpoint)
            latency_ms = round((time.perf_counter() - start_time) * 1000, 2)
            is_healthy = 200 <= response.status_code < 300
            sample = response.text[:200] if response.text else ""
            return HealthCheckReport(
                endpoint=endpoint,
                status_code=response.status_code,
                status="HEALTHY" if is_healthy else "UNHEALTHY",
                latency_ms=latency_ms,
                response_body_sample=sample,
            )
    except Exception as e:
        latency_ms = round((time.perf_counter() - start_time) * 1000, 2)
        return HealthCheckReport(
            endpoint=endpoint,
            status_code=500,
            status="UNHEALTHY",
            latency_ms=latency_ms,
            response_body_sample=f"Connection error: {e}",
        )
