import importlib.util
import socket
from pathlib import Path
import pytest

ROOT_DIR = Path(__file__).resolve().parent.parent

config_path = ROOT_DIR / "agent-template" / "config.py"
spec = importlib.util.spec_from_file_location("template_config_for_startup_test", str(config_path))
template_config_mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(template_config_mod)
AgentConfig = template_config_mod.AgentConfig
is_port_in_use = template_config_mod.is_port_in_use


def get_random_free_port() -> int:
    """Lấy một cổng ngẫu nhiên khả dụng trên máy."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("", 0))
        return s.getsockname()[1]


class TestStartupChecks:
    def test_contract_version_lower_raises_error(self, tmp_path):
        """1. Khi khởi động: version contract đang cài < CONTRACT_MIN_VERSION thì báo lỗi rõ ràng."""
        cfg = AgentConfig(
            base_dir=tmp_path,
            port=get_random_free_port(),
            contract_min_version="2.0.0",
        )

        with pytest.raises(RuntimeError) as exc_info:
            cfg.verify_startup(check_port=False)

        assert "thấp hơn yêu cầu tối thiểu" in str(exc_info.value)
        assert "2.0.0" in str(exc_info.value)

    def test_occupied_port_raises_error_with_suggestion(self, tmp_path):
        """2. Khi khởi động: port bị chiếm thì báo lỗi và gợi ý cổng khác."""
        occupied_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        occupied_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        occupied_sock.bind(("127.0.0.1", 0))
        occupied_sock.listen(1)
        occupied_port = occupied_sock.getsockname()[1]

        try:
            cfg = AgentConfig(
                base_dir=tmp_path,
                port=occupied_port,
                contract_min_version="1.0.0",
            )

            with pytest.raises(RuntimeError) as exc_info:
                cfg.verify_startup(check_port=True)

            msg = str(exc_info.value)
            assert f"Cổng PORT {occupied_port} đã bị chiếm dụng" in msg
            assert "Gợi ý cổng khả dụng khác" in msg
        finally:
            occupied_sock.close()
