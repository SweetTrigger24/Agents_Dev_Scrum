import importlib.util
from pathlib import Path
import pytest
from pydantic import ValidationError

ROOT_DIR = Path(__file__).resolve().parent.parent

# Tải module config từ agent-template một cách độc lập
config_path = ROOT_DIR / "agent-template" / "config.py"
spec = importlib.util.spec_from_file_location("template_config_for_test", str(config_path))
template_config_mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(template_config_mod)
AgentConfig = template_config_mod.AgentConfig


class TestConfigPathAndPortValidation:
    def test_missing_port_raises_error(self, tmp_path):
        """1. Thiếu PORT hoặc để trống PORT thì dừng với lỗi rõ ràng."""
        with pytest.raises(ValidationError) as exc_info:
            AgentConfig(base_dir=tmp_path, port=None)
        assert "PORT là bắt buộc, không có giá trị mặc định chung" in str(exc_info.value)

        with pytest.raises(ValidationError) as exc_info2:
            AgentConfig(base_dir=tmp_path, port="")
        assert "PORT là bắt buộc, không có giá trị mặc định chung" in str(exc_info2.value)

    def test_relative_path_resolved_from_agent_dir(self, tmp_path):
        """2. Đường dẫn tương đối tính theo thư mục của agent chứ không theo thư mục cwd."""
        agent_dir = tmp_path / "mock_agent"
        agent_dir.mkdir(parents=True, exist_ok=True)

        cfg = AgentConfig(
            base_dir=agent_dir,
            port=8080,
            artifact_dir="./custom_artifacts",
            workspace_dir="custom_workspace",
        )

        expected_art = (agent_dir / "custom_artifacts").resolve()
        expected_ws = (agent_dir / "custom_workspace").resolve()

        assert Path(cfg.artifact_dir).resolve() == expected_art
        assert Path(cfg.workspace_dir).resolve() == expected_ws

    def test_outside_path_rejected(self, tmp_path):
        """3. Từ chối đường dẫn trỏ ra ngoài thư mục agent."""
        agent_dir = tmp_path / "mock_agent"
        agent_dir.mkdir(parents=True, exist_ok=True)

        with pytest.raises(ValidationError) as exc_info:
            AgentConfig(
                base_dir=agent_dir,
                port=8080,
                artifact_dir="../outside_artifacts",
            )
        assert "trỏ ra ngoài thư mục agent" in str(exc_info.value)

        outside_abs = (tmp_path / "totally_outside").resolve()
        with pytest.raises(ValidationError) as exc_info2:
            AgentConfig(
                base_dir=agent_dir,
                port=8080,
                workspace_dir=str(outside_abs),
            )
        assert "trỏ ra ngoài thư mục agent" in str(exc_info2.value)
