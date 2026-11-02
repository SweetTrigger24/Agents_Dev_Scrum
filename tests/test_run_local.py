import json
import socket
import sys
import time
from pathlib import Path
from unittest.mock import patch

import pytest
import yaml

ROOT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT_DIR / "scripts"))

from run_local import (
    cmd_down,
    cmd_status,
    cmd_up,
    load_yaml_config,
    validate_preflight,
)


def get_two_free_ports() -> tuple[int, int]:
    """Tìm 2 port ngẫu nhiên còn trống."""
    s1 = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s1.bind(("", 0))
    p1 = s1.getsockname()[1]

    s2 = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s2.bind(("", 0))
    p2 = s2.getsockname()[1]

    s1.close()
    s2.close()
    return p1, p2


def setup_mock_agent(agent_dir: Path, agent_id: str, role: str) -> None:
    """Tạo thư mục agent giả lập với FastAPI app trả về /health chuẩn."""
    agent_dir.mkdir(parents=True, exist_ok=True)
    (agent_dir / ".env").write_text("HOST=0.0.0.0\nPORT=8999\n", encoding="utf-8")

    api_content = f"""
from fastapi import FastAPI
app = FastAPI()

@app.get("/health")
def health():
    return {{
        "status": "healthy",
        "agent_id": "{agent_id}",
        "role": "{role}",
        "contract_version": "1.0.0",
        "agent_version": "1.0.0"
    }}
"""
    (agent_dir / "api.py").write_text(api_content.strip(), encoding="utf-8")


class TestRunLocalScript:
    def test_duplicate_port_rejected(self, tmp_path):
        """1. YAML có 2 agent trùng port thì bị từ chối ngay ở bước preflight."""
        yaml_data = [
            {"name": "agent1", "path": "agents/pm", "port": 8001},
            {"name": "agent2", "path": "agents/devops", "port": 8001},
        ]
        with pytest.raises(ValueError, match="Phát hiện trùng lặp PORT"):
            validate_preflight(yaml_data, ROOT_DIR)

    def test_missing_env_file_rejected(self, tmp_path):
        """2. Agent thiếu file .env thì bị từ chối trước khi khởi động."""
        dummy_dir = tmp_path / "dummy_agent"
        dummy_dir.mkdir()
        # Không tạo file .env
        yaml_data = [
            {"name": "dummy", "path": str(dummy_dir), "port": 8088},
        ]
        with pytest.raises(FileNotFoundError, match="thiếu file .env"):
            validate_preflight(yaml_data, tmp_path)

    def test_unhealthy_agent_stops_all(self, tmp_path):
        """3. Agent không phản hồi /health trong thời gian chờ thì dừng tất cả và trả exit code 1."""
        agent1 = tmp_path / "agent1"
        agent1.mkdir()
        (agent1 / ".env").write_text("PORT=8888\n", encoding="utf-8")
        # api.py không có /health hoặc không start
        (agent1 / "api.py").write_text("import sys\nsys.exit(1)", encoding="utf-8")

        p1, _ = get_two_free_ports()
        cfg_file = tmp_path / "test_agents.yaml"
        with open(cfg_file, "w", encoding="utf-8") as f:
            yaml.dump({"agents": [{"name": "fail_agent", "path": str(agent1), "port": p1}]}, f)

        # Chạy cmd_up với timeout ngắn
        with patch("run_local.ROOT_DIR", tmp_path):
            exit_code = cmd_up(cfg_file, foreground=False, timeout_limit=2.0)
            assert exit_code == 1

    def test_up_status_down_lifecycle(self, tmp_path):
        """4. Khởi động 2 mock agent thành công, kiểm tra status và dừng sạch với down."""
        agent1 = tmp_path / "agent1"
        agent2 = tmp_path / "agent2"
        setup_mock_agent(agent1, "mock-01", "PM")
        setup_mock_agent(agent2, "mock-02", "DEVOPS")

        p1, p2 = get_two_free_ports()
        cfg_file = tmp_path / "local_mock.yaml"
        with open(cfg_file, "w", encoding="utf-8") as f:
            yaml.dump(
                {
                    "agents": [
                        {"name": "mock1", "path": str(agent1), "port": p1},
                        {"name": "mock2", "path": str(agent2), "port": p2},
                    ]
                },
                f,
            )

        with patch("run_local.ROOT_DIR", tmp_path):
            try:
                # 1. UP
                up_code = cmd_up(cfg_file, foreground=False)
                assert up_code == 0

                # 2. STATUS
                status_code = cmd_status(cfg_file)
                assert status_code == 0
            finally:
                # 3. DOWN
                down_code = cmd_down()
                assert down_code == 0
