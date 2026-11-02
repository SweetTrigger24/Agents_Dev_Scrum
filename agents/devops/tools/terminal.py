import os
import re
import subprocess
import time
from pathlib import Path
from typing import Any, Sequence

from pydantic import BaseModel


class TerminalError(Exception):
    """Ngoại lệ chung cho lớp terminal."""
    pass


class SecurityViolationError(TerminalError):
    """Vi phạm quy tắc an toàn (lệnh ngoài whitelist, mẫu nguy hiểm, shell operator, symlink)."""
    pass


class CommandTimeoutError(TerminalError):
    """Lệnh chạy quá thời gian timeout cho phép."""
    pass


class CommandExecutionError(TerminalError):
    """Lệnh chạy thất bại với mã lỗi (exit code khác 0)."""

    def __init__(
        self,
        message: str,
        exit_code: int,
        stdout: str,
        stderr: str,
        retryable: bool = False,
    ) -> None:
        super().__init__(message)
        self.exit_code = exit_code
        self.stdout = stdout
        self.stderr = stderr
        self.retryable = retryable


class ExecutionResult(BaseModel):
    """Kết quả thực thi một lệnh từ terminal."""

    command: list[str]
    exit_code: int
    stdout: str
    stderr: str
    duration_ms: int
    dry_run: bool


# Danh sách các mẫu lệnh nguy hiểm bị cấm tuyệt đối
DANGEROUS_PATTERNS = [
    re.compile(r"\brm\s+-[a-zA-Z]*r[a-zA-Z]*f\b", re.IGNORECASE),
    re.compile(r"\brm\s+-[a-zA-Z]*f[a-zA-Z]*r\b", re.IGNORECASE),
    re.compile(r"\bgit\s+push\s+.*--force\b", re.IGNORECASE),
    re.compile(r"\bgit\s+push\s+.*-f\b", re.IGNORECASE),
    re.compile(r"\bdocker\s+system\s+prune\b", re.IGNORECASE),
    re.compile(r"\bdocker\s+volume\s+prune\b", re.IGNORECASE),
    re.compile(r"\bdrop\s+(database|table|schema)\b", re.IGNORECASE),
    re.compile(r"\b(curl|wget)\b.*\|\s*(sh|bash|zsh)\b", re.IGNORECASE),
    re.compile(r"\b(sudo|su|runas)\b", re.IGNORECASE),
    re.compile(r"\b(mkfs|dd\s+if=)\b", re.IGNORECASE),
]

# Các toán tử shell bị từ chối để ngăn chặn command injection
SHELL_OPERATORS = ["&&", "||", "|", ";", ">", ">>", "<", "`", "$("]
MAX_OUTPUT_LENGTH = 50000


def mask_secrets(text: str, custom_env: dict[str, str] | None = None) -> str:
    """Che giấu giá trị của các secret trong văn bản stdout/stderr."""
    if not text:
        return ""

    masked = text

    # 1. Quét biến môi trường có tên chứa KEY, TOKEN, SECRET, PASSWORD
    all_envs = {**os.environ, **(custom_env or {})}
    for key, val in all_envs.items():
        upper_key = key.upper()
        if any(term in upper_key for term in ["KEY", "TOKEN", "SECRET", "PASSWORD"]):
            if val and len(val.strip()) >= 4:
                masked = masked.replace(val, "***REDACTED***")

    # 2. Quét pattern thông dụng của token và API key
    pattern = re.compile(
        r"(?i)\b(key|token|secret|password|api_key|bearer)[\s:=]+(['\"]?)([a-zA-Z0-9_\-\.]{6,})\2"
    )
    masked = pattern.sub(r"\1=***REDACTED***", masked)

    # 3. Quét tiền tố API key phổ biến
    masked = re.sub(r"gsk_[a-zA-Z0-9]{20,}", "***REDACTED***", masked)
    masked = re.sub(r"sk-[a-zA-Z0-9]{20,}", "***REDACTED***", masked)
    masked = re.sub(r"AIza[0-9A-Za-z\-_]{35}", "***REDACTED***", masked)

    return masked


def truncate_output(text: str, max_chars: int = MAX_OUTPUT_LENGTH) -> str:
    """Giới hạn kích thước output để tránh tràn bộ nhớ."""
    if len(text) > max_chars:
        half = max_chars // 2
        return text[:half] + "\n\n[... NỘI DUNG ĐÃ ĐƯỢC CẮT BỚT DO VƯỢT QUÁ GIỚI HẠN ...]\n\n" + text[-half:]
    return text


class TerminalExecutor:
    """Lớp thực thi lệnh hệ thống DUY NHẤT trong DevOps Agent, đảm bảo an toàn tuyệt đối."""

    def __init__(
        self,
        workspace_dir: str | Path,
        allowed_commands: list[str],
        dry_run: bool = True,
    ) -> None:
        self.workspace_dir = Path(workspace_dir).resolve()
        self.workspace_dir.mkdir(parents=True, exist_ok=True)
        self.allowed_commands = [cmd.lower().strip() for cmd in allowed_commands]
        self.dry_run = dry_run

    def validate_command(self, cmd_list: Sequence[str]) -> None:
        """Xác thực danh sách lệnh: kiểm tra shell operator, mẫu nguy hiểm và whitelist."""
        if not cmd_list:
            raise SecurityViolationError("Lệnh không được để trống.")

        # 1. Kiểm tra shell operators trong từng đối số
        for token in cmd_list:
            for op in SHELL_OPERATORS:
                if op in token:
                    raise SecurityViolationError(
                        f"Phát hiện shell operator '{op}' trong đối số '{token}'. "
                        f"Lệnh chỉ được truyền dưới dạng list không qua shell."
                    )

        # 2. Kiểm tra các mẫu lệnh nguy hiểm (ưu tiên chặn trước khi xét whitelist)
        cmd_str = " ".join(cmd_list)
        for pattern in DANGEROUS_PATTERNS:
            if pattern.search(cmd_str):
                raise SecurityViolationError(
                    f"Phát hiện mẫu lệnh phá hủy nguy hiểm bị cấm: '{pattern.pattern}' trong '{cmd_str}'."
                )

        # 3. Kiểm tra Binary trong ALLOWED_COMMANDS whitelist
        binary_raw = cmd_list[0].lower().strip()
        binary_name = Path(binary_raw).name.replace(".exe", "")
        if binary_name not in self.allowed_commands:
            raise SecurityViolationError(
                f"Lệnh '{binary_name}' không nằm trong whitelist ALLOWED_COMMANDS: {self.allowed_commands}."
            )

    def validate_cwd(self, cwd: str | Path | None) -> Path:
        """Xác thực thư mục làm việc (cwd): bắt buộc nằm trong WORKSPACE_DIR, chặn path traversal và symlink."""
        target_cwd = (Path(cwd) if cwd is not None else self.workspace_dir).resolve()

        # Chặn path traversal dạng '..'
        if cwd and ".." in str(cwd).replace("\\", "/").split("/"):
            raise SecurityViolationError(f"Phát hiện path traversal '..' trong thư mục làm việc: '{cwd}'.")

        # Kiểm tra symlink và vị trí tương đối
        try:
            target_cwd.relative_to(self.workspace_dir)
        except ValueError:
            raise SecurityViolationError(
                f"Thư mục làm việc '{target_cwd}' nằm ngoài phạm vi WORKSPACE_DIR cho phép: '{self.workspace_dir}'."
            )

        return target_cwd

    def run(
        self,
        cmd_list: list[str],
        cwd: str | Path | None = None,
        timeout: int = 60,
        env: dict[str, str] | None = None,
        execute: bool = False,
    ) -> ExecutionResult:
        """Thực thi lệnh với kiểm soát an toàn nghiêm ngặt:

        Chỉ chạy thật khi: self.dry_run is False VÀ execute is True.
        """
        self.validate_command(cmd_list)
        safe_cwd = self.validate_cwd(cwd)

        # Kiểm tra chế độ Dry-Run
        if self.dry_run or not execute:
            cmd_preview = " ".join(cmd_list)
            return ExecutionResult(
                command=cmd_list,
                exit_code=0,
                stdout=f"[DRY_RUN] Lệnh dự kiến thực thi: {cmd_preview} (tại {safe_cwd})",
                stderr="",
                duration_ms=0,
                dry_run=True,
            )

        # Thực thi lệnh thật
        start_time = time.perf_counter()
        merged_env = {**os.environ, **(env or {})}

        try:
            process = subprocess.run(
                cmd_list,
                shell=False,  # TUYỆT ĐỐI KHÔNG DÙNG shell=True
                cwd=str(safe_cwd),
                timeout=float(timeout),
                capture_output=True,
                text=True,
                env=merged_env,
                encoding="utf-8",
                errors="replace",
            )
            duration_ms = int((time.perf_counter() - start_time) * 1000)
            masked_stdout = truncate_output(mask_secrets(process.stdout, env))
            masked_stderr = truncate_output(mask_secrets(process.stderr, env))

            if process.returncode != 0:
                # Phân loại retryable dựa trên lỗi (ví dụ lỗi mạng git pull có thể retry, syntax error thì không)
                retryable = "timed out" in masked_stderr.lower() or "connection" in masked_stderr.lower()
                raise CommandExecutionError(
                    message=f"Lệnh '{cmd_list[0]}' thất bại với mã thoát {process.returncode}.",
                    exit_code=process.returncode,
                    stdout=masked_stdout,
                    stderr=masked_stderr,
                    retryable=retryable,
                )

            return ExecutionResult(
                command=cmd_list,
                exit_code=process.returncode,
                stdout=masked_stdout,
                stderr=masked_stderr,
                duration_ms=duration_ms,
                dry_run=False,
            )

        except subprocess.TimeoutExpired as e:
            duration_ms = int((time.perf_counter() - start_time) * 1000)
            raise CommandTimeoutError(
                f"Lệnh '{cmd_list[0]}' đã quá thời gian thực thi tối đa ({timeout} giây)."
            ) from e
