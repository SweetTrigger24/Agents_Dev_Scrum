from pathlib import Path
from agent_contract.enums import AgentRole
from pydantic_settings import BaseSettings, SettingsConfigDict


class DevOpsConfig(BaseSettings):
    """Cấu hình cho DevOps Agent (devops-01)."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    agent_id: str = "devops-01"
    agent_role: AgentRole = AgentRole.DEVOPS
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
        """Trả về danh sách các binary được phép thực thi (whitelist)."""
        return [cmd.strip().lower() for cmd in self.allowed_commands.split(",") if cmd.strip()]

    def get_artifact_path(self) -> Path:
        """Trả về đường dẫn tuyệt đối tới thư mục artifacts."""
        path = Path(self.artifact_dir).resolve()
        path.mkdir(parents=True, exist_ok=True)
        return path

    def get_workspace_path(self) -> Path:
        """Trả về đường dẫn tuyệt đối tới thư mục workspace giới hạn cho DevOps."""
        path = Path(self.workspace_dir).resolve()
        path.mkdir(parents=True, exist_ok=True)
        return path
