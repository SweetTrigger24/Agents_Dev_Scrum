import json
from pathlib import Path
import pytest

ROOT_DIR = Path(__file__).resolve().parent.parent
import sys
if str(ROOT_DIR / "tools") not in sys.path:
    sys.path.insert(0, str(ROOT_DIR / "tools"))

from validate_agent import (
    AgentValidationSummary,
    check_d1_no_hardcoded_paths,
    check_d2_timezone_aware_datetime,
    check_d3_no_inter_agent_access,
    check_d4_port_uniqueness_and_alignment,
    check_d5_requirements_pinned,
    check_d6_artifacts_relative_uris,
    check_d7_gitignore_isolation,
)


class TestValidateAgentExtensions:
    # 1. No Hardcoded Paths
    def test_d1_no_hardcoded_paths_pass(self, tmp_path):
        """D1 PASS: Mã nguồn không chứa đường dẫn tuyệt đối cứng."""
        agent_dir = tmp_path / "agent_pass"
        agent_dir.mkdir()
        (agent_dir / "safe.py").write_text("from pathlib import Path\np = Path('./data')", encoding="utf-8")

        summary = AgentValidationSummary(agent_dir="agent_pass")
        check_d1_no_hardcoded_paths(agent_dir, summary)
        assert summary.passed is True

    def test_d1_no_hardcoded_paths_fail(self, tmp_path):
        """D1 FAIL: Mã nguồn chứa đường dẫn tuyệt đối cứng như C:\\, /home/, /Users/."""
        agent_dir = tmp_path / "agent_fail"
        agent_dir.mkdir()
        (agent_dir / "bad.py").write_text("bad_path = 'C:\\\\Projects\\\\data'\n", encoding="utf-8")

        summary = AgentValidationSummary(agent_dir="agent_fail")
        check_d1_no_hardcoded_paths(agent_dir, summary)
        assert summary.passed is False
        assert "Phát hiện đường dẫn tuyệt đối cứng" in summary.checks[-1].message

    # 2. Timezone-Aware Datetime
    def test_d2_timezone_aware_datetime_pass(self, tmp_path):
        """D2 PASS: Dùng datetime.now(timezone.utc)."""
        agent_dir = tmp_path / "agent_pass"
        agent_dir.mkdir()
        (agent_dir / "safe.py").write_text("from datetime import datetime, timezone\nnow = datetime.now(timezone.utc)\n", encoding="utf-8")

        summary = AgentValidationSummary(agent_dir="agent_pass")
        check_d2_timezone_aware_datetime(agent_dir, summary)
        assert summary.passed is True

    def test_d2_timezone_aware_datetime_fail(self, tmp_path):
        """D2 FAIL: Dùng datetime.now() không tham số hoặc datetime.utcnow()."""
        agent_dir = tmp_path / "agent_fail"
        agent_dir.mkdir()
        (agent_dir / "bad.py").write_text("from datetime import datetime\nnow = datetime.utcnow()\n", encoding="utf-8")

        summary = AgentValidationSummary(agent_dir="agent_fail")
        check_d2_timezone_aware_datetime(agent_dir, summary)
        assert summary.passed is False
        assert "sử dụng datetime.utcnow()" in summary.checks[-1].message

    # 3. Inter-Agent Isolation
    def test_d3_no_inter_agent_access_pass(self, tmp_path):
        """D3 PASS: Agent không import hoặc đọc file từ agent khác."""
        agent_dir = tmp_path / "pm"
        agent_dir.mkdir()
        (agent_dir / "logic.py").write_text("import json\nfrom agent_contract.models import TaskRequest\n", encoding="utf-8")

        summary = AgentValidationSummary(agent_dir="pm")
        check_d3_no_inter_agent_access(agent_dir, summary)
        assert summary.passed is True

    def test_d3_no_inter_agent_access_fail(self, tmp_path):
        """D3 FAIL: Agent import module từ agent khác."""
        agent_dir = tmp_path / "pm"
        agent_dir.mkdir()
        (agent_dir / "bad.py").write_text("from agents.devops.tools.terminal import run\n", encoding="utf-8")

        summary = AgentValidationSummary(agent_dir="pm")
        check_d3_no_inter_agent_access(agent_dir, summary)
        assert summary.passed is False
        assert "Phát hiện truy cập agent khác" in summary.checks[-1].message

    def test_d3_conductor_allowed_for_pm(self, tmp_path):
        """D3 PASS: Duy nhất PM được phép import và sử dụng module conductor."""
        agent_dir = tmp_path / "pm"
        agent_dir.mkdir()
        (agent_dir / "service.py").write_text("from conductor.dispatcher import dispatch_step\n", encoding="utf-8")

        summary = AgentValidationSummary(agent_dir="pm")
        check_d3_no_inter_agent_access(agent_dir, summary)
        assert summary.passed is True

    def test_d3_conductor_forbidden_for_non_pm(self, tmp_path):
        """D3 FAIL: Agent không phải PM cấm import conductor."""
        agent_dir = tmp_path / "devops"
        agent_dir.mkdir()
        (agent_dir / "service.py").write_text("from conductor.dispatcher import dispatch_step\n", encoding="utf-8")

        summary = AgentValidationSummary(agent_dir="devops")
        check_d3_no_inter_agent_access(agent_dir, summary)
        assert summary.passed is False
        assert "cấm from 'conductor.dispatcher' import" in summary.checks[-1].message

    # 4. Port Uniqueness & Alignment
    def test_d4_port_uniqueness_pass(self, tmp_path):
        """D4 PASS: Port trong .env.example không trùng và khớp YAML."""
        agent_dir = tmp_path / "pm"
        agent_dir.mkdir()
        (agent_dir / ".env.example").write_text("PORT=8001\n", encoding="utf-8")

        # Mock YAML
        scripts_dir = tmp_path / "scripts"
        scripts_dir.mkdir()
        (scripts_dir / "local_agents.yaml").write_text("agents:\n  - name: pm\n    port: 8001\n    path: pm\n", encoding="utf-8")

        summary = AgentValidationSummary(agent_dir="pm")
        check_d4_port_uniqueness_and_alignment(agent_dir, summary, [agent_dir], root_dir=tmp_path)
        assert summary.passed is True

    def test_d4_port_uniqueness_fail_duplicate(self, tmp_path):
        """D4 FAIL: Port trùng lặp giữa 2 agent."""
        agent1 = tmp_path / "pm"
        agent1.mkdir()
        (agent1 / ".env.example").write_text("PORT=8001\n", encoding="utf-8")

        agent2 = tmp_path / "devops"
        agent2.mkdir()
        (agent2 / ".env.example").write_text("PORT=8001\n", encoding="utf-8")

        summary = AgentValidationSummary(agent_dir="pm")
        check_d4_port_uniqueness_and_alignment(agent1, summary, [agent1, agent2], root_dir=tmp_path)
        assert summary.passed is False
        assert "bị trùng với agent 'devops'" in summary.checks[-1].message

    # 5. Requirements Pinned
    def test_d5_requirements_pinned_pass(self, tmp_path):
        """D5 PASS: Tất cả package đều ghim == và agent-contract khớp nhau."""
        agent1 = tmp_path / "pm"
        agent1.mkdir()
        (agent1 / "requirements.txt").write_text("agent-contract==1.0.0\nfastapi==0.162.0\n", encoding="utf-8")

        summary = AgentValidationSummary(agent_dir="pm")
        check_d5_requirements_pinned(agent1, summary, [agent1])
        assert summary.passed is True

    def test_d5_requirements_pinned_fail_unpinned(self, tmp_path):
        """D5 FAIL: Có package dùng >= thay vì ==."""
        agent1 = tmp_path / "pm"
        agent1.mkdir()
        (agent1 / "requirements.txt").write_text("agent-contract==1.0.0\nfastapi>=0.162.0\n", encoding="utf-8")

        summary = AgentValidationSummary(agent_dir="pm")
        check_d5_requirements_pinned(agent1, summary, [agent1])
        assert summary.passed is False
        assert "chưa được ghim phiên bản (==)" in summary.checks[-1].message

    # 6. Artifacts Relative URI
    def test_d6_artifacts_relative_uris_pass(self, tmp_path):
        """D6 PASS: uri trong artifacts/index.json là đường dẫn tương đối."""
        agent_dir = tmp_path / "pm"
        art_dir = agent_dir / "artifacts"
        art_dir.mkdir(parents=True)
        index_data = [{"artifact_id": "ART-001", "name": "plan.md", "uri": "artifacts/plan.md"}]
        (art_dir / "index.json").write_text(json.dumps(index_data), encoding="utf-8")

        summary = AgentValidationSummary(agent_dir="pm")
        check_d6_artifacts_relative_uris(agent_dir, summary)
        assert summary.passed is True

    def test_d6_artifacts_relative_uris_fail_absolute(self, tmp_path):
        """D6 FAIL: uri trong index.json là đường dẫn tuyệt đối hoặc path traversal."""
        agent_dir = tmp_path / "pm"
        art_dir = agent_dir / "artifacts"
        art_dir.mkdir(parents=True)
        index_data = [{"artifact_id": "ART-001", "name": "plan.md", "uri": "/root/plan.md"}]
        (art_dir / "index.json").write_text(json.dumps(index_data), encoding="utf-8")

        summary = AgentValidationSummary(agent_dir="pm")
        check_d6_artifacts_relative_uris(agent_dir, summary)
        assert summary.passed is False
        assert "Phát hiện URI không hợp lệ/tuyệt đối" in summary.checks[-1].message

    # 7. Gitignore Isolation
    def test_d7_gitignore_isolation_pass(self, tmp_path):
        """D7 PASS: .gitignore có đủ .env, workspace/, data/."""
        agent_dir = tmp_path / "pm"
        agent_dir.mkdir()
        (agent_dir / ".gitignore").write_text(".env\nworkspace/\ndata/\n", encoding="utf-8")

        summary = AgentValidationSummary(agent_dir="pm")
        check_d7_gitignore_isolation(agent_dir, summary)
        assert summary.passed is True

    def test_d7_gitignore_isolation_fail_missing(self, tmp_path):
        """D7 FAIL: .gitignore thiếu data/ hoặc .env."""
        agent_dir = tmp_path / "pm"
        agent_dir.mkdir()
        (agent_dir / ".gitignore").write_text("workspace/\n", encoding="utf-8")

        summary = AgentValidationSummary(agent_dir="pm")
        check_d7_gitignore_isolation(agent_dir, summary)
        assert summary.passed is False
        assert "thiếu các mục cách ly bắt buộc" in summary.checks[-1].message
