from pathlib import Path
from agent_contract.enums import AgentRole
from pydantic_settings import BaseSettings, SettingsConfigDict


class PMConfig(BaseSettings):
    """Cấu hình cho PM Agent (pm-01)."""

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
    allowed_commands: str = ""
    dry_run: bool = True

    def get_artifact_path(self) -> Path:
        """Trả về đường dẫn tuyệt đối tới thư mục artifacts."""
        return Path(self.artifact_dir).resolve()
