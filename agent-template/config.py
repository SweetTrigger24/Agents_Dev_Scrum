from pathlib import Path
from agent_contract.enums import AgentRole
from pydantic_settings import BaseSettings, SettingsConfigDict


class AgentConfig(BaseSettings):
    """Cấu hình chung cho Agent đọc từ biến môi trường hoặc file .env."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    agent_id: str = "pm-01"
    agent_role: AgentRole = AgentRole.PM
    llm_provider: str = "groq"
    llm_model: str = "llama-3.3-70b-versatile"
    llm_api_key: str = ""
    llm_base_url: str | None = None
    llm_temperature: float = 0.2
    llm_timeout_seconds: int = 60
    llm_max_retries: int = 2
    artifact_dir: str = "./artifacts"
    workspace_dir: str = "./workspace"
    allowed_commands: str = "git,docker,pytest,npm,mvn,python"
    dry_run: bool = True

    def get_allowed_commands_list(self) -> list[str]:
        """Trả về danh sách các lệnh được phép thực thi (tách bởi dấu phẩy)."""
        return [cmd.strip() for cmd in self.allowed_commands.split(",") if cmd.strip()]

    def get_artifact_path(self) -> Path:
        """Trả về đường dẫn thư mục lưu trữ artifact dưới dạng Path object."""
        return Path(self.artifact_dir).resolve()

    def get_workspace_path(self) -> Path:
        """Trả về đường dẫn thư mục làm việc workspace dưới dạng Path object."""
        return Path(self.workspace_dir).resolve()
