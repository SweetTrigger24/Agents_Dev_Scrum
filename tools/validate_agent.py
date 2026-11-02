import ast
import importlib.util
import io
import os
import re
import subprocess
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# Đảm bảo UTF-8 an toàn trên Windows console
if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

# Thêm root vào sys.path để import agent_contract
ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from agent_contract.enums import AgentRole, ErrorCode, TaskStatus
from agent_contract.models import AgentIdentity, TaskRequest, TaskResult
from agent_contract.registry import ACTION_MAP, CAPABILITY_REGISTRY

REQUIRED_FILES = [
    "agent.py",
    "config.py",
    "prompt.py",
    "schemas.py",
    ".env.example",
    "requirements.txt",
    "README.md",
]

REQUIRED_DIRS = [
    "tools",
    "tests",
    "artifacts",
]

REQUIRED_ENV_KEYS = [
    "AGENT_ID",
    "AGENT_ROLE",
    "LLM_PROVIDER",
    "LLM_MODEL",
    "LLM_API_KEY",
    "LLM_BASE_URL",
    "LLM_TEMPERATURE",
    "LLM_TIMEOUT_SECONDS",
    "LLM_MAX_RETRIES",
    "ARTIFACT_DIR",
    "WORKSPACE_DIR",
    "ALLOWED_COMMANDS",
    "DRY_RUN",
]

SECRET_PATTERNS = [
    re.compile(r"gsk_[a-zA-Z0-9]{20,}"),
    re.compile(r"AIza[0-9A-Za-z\-_]{35}"),
    re.compile(r"sk-[a-zA-Z0-9]{20,}"),
]


@dataclass
class CheckResult:
    name: str
    passed: bool
    message: str = ""


@dataclass
class AgentValidationSummary:
    agent_dir: str
    agent_id: str = "unknown"
    role: str = "unknown"
    passed: bool = True
    checks: list[CheckResult] = field(default_factory=list)

    def add_check(self, name: str, passed: bool, message: str = "") -> None:
        if not passed:
            self.passed = False
        self.checks.append(CheckResult(name=name, passed=passed, message=message))


def check_1_required_files(agent_path: Path, summary: AgentValidationSummary) -> None:
    """1. Kiểm tra có đủ các file và thư mục bắt buộc."""
    missing = []
    for f in REQUIRED_FILES:
        target = agent_path / f
        if not target.exists() or not target.is_file():
            missing.append(f)

    for d in REQUIRED_DIRS:
        target = agent_path / d
        if not target.exists() or not target.is_dir():
            missing.append(f"{d}/")

    if missing:
        summary.add_check("Required Files", False, f"Thiếu file/thư mục: {', '.join(missing)}")
    else:
        summary.add_check("Required Files", True, "Đầy đủ tất cả file và thư mục bắt buộc.")


def check_2_env_and_secrets(agent_path: Path, summary: AgentValidationSummary) -> None:
    """2. Kiểm tra .env.example có đủ biến mục 2.6 và không chứa API key thật trong mã nguồn."""
    env_example = agent_path / ".env.example"
    if not env_example.exists():
        summary.add_check("Env & Secrets", False, "Không tìm thấy file .env.example.")
        return

    content = env_example.read_text(encoding="utf-8")
    missing_keys = []
    for k in REQUIRED_ENV_KEYS:
        if not re.search(rf"^\s*{re.escape(k)}\s*=", content, re.MULTILINE):
            missing_keys.append(k)

    if missing_keys:
        summary.add_check("Env & Secrets", False, f".env.example thiếu các khóa: {', '.join(missing_keys)}")
        return

    # Quét xem có API key thật trong toàn bộ thư mục agent
    secret_findings = []
    for py_file in agent_path.rglob("*.py"):
        text = py_file.read_text(encoding="utf-8", errors="replace")
        for pat in SECRET_PATTERNS:
            if pat.search(text):
                secret_findings.append(f"{py_file.name}")

    # Kiểm tra giá trị LLM_API_KEY trong .env.example phải rỗng
    for line in content.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("LLM_API_KEY"):
            parts = line.split("=", 1)
            if len(parts) == 2:
                val = parts[1].split("#")[0].strip()
                if val:
                    secret_findings.append(".env.example (LLM_API_KEY không được gán sẵn giá trị thật)")

    if secret_findings:
        summary.add_check("Env & Secrets", False, f"Phát hiện secret/API key: {', '.join(secret_findings)}")
    else:
        summary.add_check("Env & Secrets", True, ".env.example đủ khóa chuẩn và không rò rỉ secret.")


def _load_agent_instance(agent_path: Path) -> Any:
    """Import động agent class và khởi tạo instance ở chế độ mock."""
    agent_file = agent_path / "agent.py"
    if not agent_file.exists():
        raise FileNotFoundError(f"Không tìm thấy {agent_file}")

    # Làm sạch sys.modules để tránh cache giữa các agent
    for key in list(sys.modules.keys()):
        if key in ["agent", "config", "llm", "prompt", "schemas", "api", "tools"] or key.startswith("tools."):
            sys.modules.pop(key, None)

    # Thêm agent_path vào đầu sys.path
    if str(agent_path) in sys.path:
        sys.path.remove(str(agent_path))
    sys.path.insert(0, str(agent_path))

    spec = importlib.util.spec_from_file_location(f"agent_module_{agent_path.name}", str(agent_file))
    if spec is None or spec.loader is None:
        raise ImportError(f"Không thể tải spec từ {agent_file}")

    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)

    # Tìm class kế thừa BaseAgent hoặc có hàm handle
    agent_cls = None
    for name, obj in vars(mod).items():
        if isinstance(obj, type) and hasattr(obj, "handle") and hasattr(obj, "get_identity") and name != "BaseAgent":
            agent_cls = obj
            break

    if agent_cls is None:
        # Nếu chỉ có BaseAgent
        agent_cls = getattr(mod, "BaseAgent", None)

    if agent_cls is None:
        raise AttributeError(f"Không tìm thấy Agent class hợp lệ trong {agent_file}")

    # Khởi tạo instance
    try:
        # Thử khởi tạo không tham số (PMAgent, DevOpsAgent)
        return agent_cls()
    except TypeError:
        # Thử khởi tạo với config và identity
        config_mod = importlib.import_module("config")
        config_cls = getattr(config_mod, "AgentConfig", None) or getattr(config_mod, "DevOpsConfig", None) or getattr(config_mod, "PMConfig", None)
        cfg = config_cls() if config_cls else None
        role_enum = getattr(AgentRole, agent_path.name.upper(), AgentRole.PM)
        identity = AgentIdentity(
            agent_id=f"{agent_path.name.lower()}-01",
            role=role_enum,
            name=f"{role_enum.value} Agent",
            version="1.0.0",
            capabilities=CAPABILITY_REGISTRY.get(role_enum, []),
        )
        return agent_cls(identity=identity, config=cfg)


def check_3_identity_and_capabilities(agent_path: Path, agent_instance: Any, summary: AgentValidationSummary) -> None:
    """3. Kiểm tra import agent, get_identity() hợp lệ, capabilities là tập con của registry, role khớp thư mục."""
    try:
        identity = agent_instance.get_identity()
        if not isinstance(identity, AgentIdentity):
            summary.add_check("Identity & Registry", False, "get_identity() không trả về đối tượng AgentIdentity.")
            return

        summary.agent_id = identity.agent_id
        summary.role = identity.role.value

        # Kiểm tra khớp role với tên thư mục
        expected_role_str = agent_path.name.upper()
        if identity.role.value != expected_role_str:
            summary.add_check(
                "Identity & Registry",
                False,
                f"Role '{identity.role.value}' không khớp tên thư mục '{agent_path.name}' (kỳ vọng '{expected_role_str}').",
            )
            return

        # Kiểm tra capabilities là tập con của registry
        allowed = set(CAPABILITY_REGISTRY.get(identity.role, []))
        actual = set(identity.capabilities)
        if not actual.issubset(allowed):
            invalid_caps = actual - allowed
            summary.add_check(
                "Identity & Registry",
                False,
                f"Capabilities chứa phần tử ngoài registry của role {identity.role.value}: {invalid_caps}",
            )
            return

        summary.add_check("Identity & Registry", True, f"Identity {identity.agent_id} ({identity.role.value}) hợp lệ.")

    except Exception as e:
        summary.add_check("Identity & Registry", False, f"Lỗi khi kiểm tra identity: {e}")


def check_4_run_mock_task(agent_path: Path, agent_instance: Any, summary: AgentValidationSummary) -> None:
    """4. Chạy examples/task.json ở chế độ mock: kết quả là TaskResult hợp lệ, status thuộc TaskStatus."""
    examples_dir = agent_path / "examples"
    task_file = examples_dir / "task.json"

    # Nếu không có task.json, thử tìm file task_*.json đầu tiên
    if not task_file.exists() and examples_dir.exists():
        json_files = list(examples_dir.glob("task*.json"))
        if json_files:
            task_file = json_files[0]

    if not task_file.exists():
        summary.add_check("Mock Task Execution", False, "Không tìm thấy file task mẫu trong examples/.")
        return

    try:
        raw_content = task_file.read_text(encoding="utf-8")
        task_request = TaskRequest.model_validate_json(raw_content)

        # Chạy tác vụ
        result = agent_instance.handle(task_request)

        # Xác thực kết quả
        if not isinstance(result, TaskResult):
            summary.add_check("Mock Task Execution", False, f"handle() trả về kiểu {type(result)}, không phải TaskResult.")
            return

        # Validate bằng Pydantic
        TaskResult.model_validate(result.model_dump())

        if result.status not in TaskStatus:
            summary.add_check("Mock Task Execution", False, f"Status '{result.status}' không thuộc TaskStatus.")
            return

        if result.status == TaskStatus.COMPLETED and result.error is not None:
            summary.add_check("Mock Task Execution", False, "status là COMPLETED nhưng error không phải None.")
            return

        if result.status in [TaskStatus.FAILED, TaskStatus.BLOCKED] and result.error is None:
            summary.add_check("Mock Task Execution", False, f"status là {result.status.value} nhưng thiếu trường error.")
            return

        summary.add_check("Mock Task Execution", True, f"Tác vụ mẫu thực thi thành công (Status: {result.status.value}).")

    except Exception as e:
        summary.add_check("Mock Task Execution", False, f"Lỗi khi chạy task mẫu: {e}")


def check_5_error_handling(agent_instance: Any, summary: AgentValidationSummary) -> None:
    """5. Gửi action không hợp lệ (nhận FAILED + PERMISSION_DENIED) và input hỏng (nhận FAILED + INVALID_INPUT)."""
    identity = agent_instance.get_identity()

    # 5a. Action không hợp lệ
    try:
        bad_action_req = TaskRequest(
            task_id="VAL-TASK-001",
            project_id="PROJ-VAL",
            agent_id=identity.agent_id,
            role=identity.role,
            action="unregistered_illegal_action_12345",
            instruction="Thực hiện lệnh không có trong đăng ký",
        )
        res_action = agent_instance.handle(bad_action_req)

        if res_action.status != TaskStatus.FAILED or res_action.error is None or res_action.error.code != ErrorCode.PERMISSION_DENIED:
            summary.add_check(
                "Action/Input Error Handling",
                False,
                f"Action sai phải trả FAILED + PERMISSION_DENIED, nhận được: status={res_action.status.value}, "
                f"error={res_action.error.code if res_action.error else None}",
            )
            return
    except Exception as e:
        summary.add_check("Action/Input Error Handling", False, f"handle() ném exception ra ngoài khi gặp action sai: {e}")
        return

    # 5b. Input bị hỏng
    try:
        # Chọn một action hợp lệ của agent
        valid_action = "create_plan" if identity.role == AgentRole.PM else "build_image"
        role_action_map = ACTION_MAP.get(identity.role, {})
        if role_action_map:
            valid_action = list(role_action_map.keys())[0]

        corrupted_req = TaskRequest(
            task_id="VAL-TASK-002",
            project_id="PROJ-VAL",
            agent_id=identity.agent_id,
            role=identity.role,
            action=valid_action,
            instruction="   ",  # Chỉ dẫn rỗng/hỏng
            context={"invalid_input": True},
        )
        res_input = agent_instance.handle(corrupted_req)

        if res_input.status != TaskStatus.FAILED or res_input.error is None or res_input.error.code != ErrorCode.INVALID_INPUT:
            summary.add_check(
                "Action/Input Error Handling",
                False,
                f"Input hỏng phải trả FAILED + INVALID_INPUT, nhận được: status={res_input.status.value}, "
                f"error={res_input.error.code if res_input.error else None}",
            )
            return

        summary.add_check("Action/Input Error Handling", True, "Xử lý chuẩn action sai và input hỏng (không ném ngoại lệ).")

    except Exception as e:
        summary.add_check("Action/Input Error Handling", False, f"handle() ném exception ra ngoài khi gặp input hỏng: {e}")


def check_6_isolation(agent_path: Path, summary: AgentValidationSummary) -> None:
    """6. Phân tích AST đảm bảo không import trực tiếp agent khác hoặc gọi HTTP tới agent khác."""
    violations = []
    current_agent_name = agent_path.name.lower()

    for py_file in agent_path.rglob("*.py"):
        try:
            tree = ast.parse(py_file.read_text(encoding="utf-8", errors="replace"))
        except SyntaxError:
            violations.append(f"{py_file.name}: Lỗi cú pháp Python")
            continue

        for node in ast.walk(tree):
            # Kiểm tra import khác agent
            if isinstance(node, ast.Import):
                for alias in node.names:
                    parts = alias.name.split(".")
                    if len(parts) >= 2 and parts[0] == "agents" and parts[1] != current_agent_name:
                        violations.append(f"{py_file.name}:{node.lineno} import trực tiếp '{alias.name}'")
            elif isinstance(node, ast.ImportFrom):
                if node.module:
                    parts = node.module.split(".")
                    if len(parts) >= 2 and parts[0] == "agents" and parts[1] != current_agent_name:
                        violations.append(f"{py_file.name}:{node.lineno} import từ '{node.module}'")

            # Kiểm tra gọi HTTP tới agent khác (ví dụ: localhost:800x hoặc agent-với-agent URL)
            elif isinstance(node, ast.Constant) and isinstance(node.value, str):
                val = node.value.lower()
                if any(x in val for x in ["http://localhost:800", "http://pm:", "http://devops:", "http://sa:", "http://ba:"]):
                    violations.append(f"{py_file.name}:{node.lineno} chứa URL gọi agent khác: '{node.value}'")

    if violations:
        summary.add_check("Agent Isolation", False, f"Vi phạm cách ly: {'; '.join(violations)}")
    else:
        summary.add_check("Agent Isolation", True, "Hoàn toàn độc lập, không import hay gọi HTTP tới agent khác.")


def check_7_unit_tests(agent_path: Path, summary: AgentValidationSummary) -> None:
    """7. Mỗi agent có ít nhất một test và pytest của agent đó xanh."""
    tests_dir = agent_path / "tests"
    if not tests_dir.exists():
        summary.add_check("Unit Tests", False, "Không tìm thấy thư mục tests/.")
        return

    test_files = list(tests_dir.glob("test_*.py"))
    if not test_files:
        summary.add_check("Unit Tests", False, "Thư mục tests/ không chứa file test_*.py nào.")
        return

    try:
        proc = subprocess.run(
            [sys.executable, "-m", "pytest", str(tests_dir), "-q"],
            capture_output=True,
            text=True,
            timeout=60,
            cwd=str(ROOT_DIR),
        )
        if proc.returncode == 0:
            summary.add_check("Unit Tests", True, f"Pytest chạy xanh ({len(test_files)} file test).")
        else:
            err_output = proc.stdout.strip() or proc.stderr.strip()
            summary.add_check("Unit Tests", False, f"Pytest thất bại (exit code {proc.returncode}): {err_output[:200]}")
    except subprocess.TimeoutExpired:
        summary.add_check("Unit Tests", False, "Pytest chạy quá thời gian (timeout 60s).")
    except Exception as e:
        summary.add_check("Unit Tests", False, f"Không thể thực thi pytest: {e}")


def validate_single_agent(agent_dir_path: Path) -> AgentValidationSummary:
    """Kiểm tra toàn diện một thư mục Agent."""
    summary = AgentValidationSummary(agent_dir=agent_dir_path.name)

    # Check 1: File bắt buộc
    check_1_required_files(agent_dir_path, summary)

    # Check 2: .env.example và secrets
    check_2_env_and_secrets(agent_dir_path, summary)

    # Check 6: Isolation (chạy trước khi load instance)
    check_6_isolation(agent_dir_path, summary)

    # Check 7: Unit tests
    check_7_unit_tests(agent_dir_path, summary)

    # Import và chạy các check runtime
    try:
        instance = _load_agent_instance(agent_dir_path)
    except Exception as e:
        summary.add_check("Agent Instantiation", False, f"Không thể khởi tạo Agent: {e}")
        return summary

    # Check 3: Identity & Capabilities
    check_3_identity_and_capabilities(agent_dir_path, instance, summary)

    # Check 4: Run Mock Task
    check_4_run_mock_task(agent_dir_path, instance, summary)

    # Check 5: Error Handling
    check_5_error_handling(instance, summary)

    return summary


def generate_markdown_report(summaries: list[AgentValidationSummary], output_file: Path) -> None:
    """Xuất báo cáo kết quả kiểm tra định dạng Markdown."""
    output_file.parent.mkdir(parents=True, exist_ok=True)
    now_str = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")

    lines = [
        "# Báo cáo Contract Validation các Agent (Agent Contract v1.0)",
        f"\n*Thời gian tạo: {now_str}*",
        "\n## 1. Tổng quan kết quả\n",
        "| Thư mục | Agent ID | Role | Trạng thái | Ghi chú |",
        "|---|---|---|---|---|",
    ]

    for s in summaries:
        status_badge = "✅ **PASS**" if s.passed else "❌ **FAIL**"
        fail_reasons = [c.message for c in s.checks if not c.passed]
        note = "Đạt toàn bộ tiêu chí contract" if s.passed else f"Lỗi: {'; '.join(fail_reasons)}"
        lines.append(f"| `{s.agent_dir}` | `{s.agent_id}` | `{s.role}` | {status_badge} | {note} |")

    lines.append("\n## 2. Chi tiết các hạng mục kiểm tra từng Agent\n")

    for s in summaries:
        lines.append(f"### Agent: `{s.agent_dir}` (Role: {s.role}, ID: {s.agent_id})")
        lines.append("| Tiêu chí kiểm tra | Kết quả | Chi tiết |")
        lines.append("|---|---|---|")
        for c in s.checks:
            badge = "PASS" if c.passed else "**FAIL**"
            lines.append(f"| {c.name} | {badge} | {c.message} |")
        lines.append("")

    output_file.write_text("\n".join(lines), encoding="utf-8")
    print(f"\nĐã xuất báo cáo chi tiết ra file: {output_file.resolve()}")


def print_console_table(summaries: list[AgentValidationSummary]) -> None:
    """In bảng kết quả PASS/FAIL trực quan ra màn hình console."""
    sep = "=" * 90
    print("\n" + sep)
    print(" KẾT QUẢ KIỂM TRA CONTRACT VALIDATION (Agent Contract v1.0)")
    print(sep)
    header = f"| {'AGENT DIR':<12} | {'ID':<10} | {'ROLE':<8} | {'STATUS':<6} | {'CHI TIẾT KIỂM TRA':<42} |"
    print(header)
    print("|" + "-" * 14 + "|" + "-" * 12 + "|" + "-" * 10 + "|" + "-" * 8 + "|" + "-" * 44 + "|")

    for s in summaries:
        status_str = "PASS" if s.passed else "FAIL"
        if s.passed:
            detail = f"Tất cả {len(s.checks)} kiểm tra đều ĐẠT."
        else:
            failed_checks = [c.name for c in s.checks if not c.passed]
            detail = f"Không đạt: {', '.join(failed_checks)}"
        print(f"| {s.agent_dir:<12} | {s.agent_id:<10} | {s.role:<8} | {status_str:<6} | {detail:<42} |")

    print(sep + "\n")


def main() -> int:
    """Hàm chạy chính quét tất cả các agent trong agents/."""
    agents_dir = ROOT_DIR / "agents"
    if not agents_dir.exists():
        print(f"Lỗi: Thư mục agents không tồn tại tại {agents_dir}", file=sys.stderr)
        return 1

    # Tìm các thư mục con trong agents/ (bỏ qua __pycache__ hoặc file ẩn)
    agent_folders = [d for d in agents_dir.iterdir() if d.is_dir() and not d.name.startswith((".", "_"))]
    if not agent_folders:
        print("Không tìm thấy thư mục agent nào trong agents/.", file=sys.stderr)
        return 0

    summaries: list[AgentValidationSummary] = []
    has_failure = False

    for folder in sorted(agent_folders, key=lambda p: p.name):
        print(f"Đang kiểm tra agent '{folder.name}'...")
        summary = validate_single_agent(folder)
        summaries.append(summary)
        if not summary.passed:
            has_failure = True

    # In bảng ra console
    print_console_table(summaries)

    # Xuất file báo cáo markdown docs/validation-report.md
    report_file = ROOT_DIR / "docs" / "validation-report.md"
    generate_markdown_report(summaries, report_file)

    if has_failure:
        print("Phát hiện có Agent KHÔNG ĐẠT tiêu chuẩn Contract Validation!", file=sys.stderr)
        return 1

    print("Tất cả các Agent đã vượt qua bài kiểm tra Contract Validation thành công!")
    return 0


if __name__ == "__main__":
    sys.exit(main())
