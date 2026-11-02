#!/usr/bin/env python3
"""
tools/scaffold_agent.py
Công cụ tự động khởi tạo khung mã nguồn (scaffolding) cho một Agent mới
đảm bảo tuân thủ 100% Agent Contract v1.0 và vượt qua 13 tiêu chí của validate_agent.py.

Cách dùng:
    python tools/scaffold_agent.py --list
    python tools/scaffold_agent.py --role BA
    python tools/scaffold_agent.py --role DEV --force
"""

import argparse
import io
import json
import shutil
import sys
from pathlib import Path

# Đảm bảo in UTF-8
if sys.platform == "win32" and hasattr(sys.stdout, "buffer"):
    try:
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
        sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")
    except Exception:
        pass

ROOT_DIR = Path(__file__).resolve().parent.parent
CONFIG_FILE = ROOT_DIR / "config" / "agents_registry.json"
TEMPLATE_DIR = ROOT_DIR / "agent-template"
AGENTS_DIR = ROOT_DIR / "agents"


def load_registry() -> dict:
    if not CONFIG_FILE.exists():
        print(f"Lỗi: Không tìm thấy file cấu hình tại {CONFIG_FILE}", file=sys.stderr)
        sys.exit(1)
    with open(CONFIG_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


def print_agent_list(registry: dict) -> None:
    print("=" * 90)
    print(" DANH SÁCH 10 AGENT TRONG HỆ THỐNG AI-TEAM (Agent Contract v1.0)")
    print("=" * 90)
    print(f"| {'ROLE':<14} | {'AGENT_ID':<16} | {'MÁY':<6} | {'PORT':<6} | {'CAPABILITIES':<36} |")
    print("|" + "-" * 16 + "|" + "-" * 18 + "|" + "-" * 8 + "|" + "-" * 8 + "|" + "-" * 38 + "|")
    for key, data in registry.get("agents", {}).items():
        caps = ", ".join(data.get("capabilities", []))
        if len(caps) > 34:
            caps = caps[:31] + "..."
        print(f"| {data['role']:<14} | {data['agent_id']:<16} | {data.get('machine', '?'):<6} | {data['port']:<6} | {caps:<36} |")
    print("=" * 90)


def to_pascal_case(snake_str: str) -> str:
    return "".join(word.capitalize() for word in snake_str.replace("-", "_").split("_"))


def generate_agent_py(role_key: str, agent_info: dict) -> str:
    role_upper = agent_info["role"]
    agent_id = agent_info["agent_id"]
    class_name = f"{to_pascal_case(role_key)}Agent"
    actions = agent_info.get("actions", {})
    first_action = list(actions.keys())[0] if actions else "execute"
    first_cap = actions.get(first_action, "execute")

    return f'''import json
import time
from datetime import datetime, timezone
from typing import Any, Callable, TypeVar, Union
from pathlib import Path

from pydantic import BaseModel

from agent_contract.enums import AgentRole, AgentStatus, ArtifactType, ErrorCode, Priority, TaskStatus
from agent_contract.models import (
    AgentError,
    AgentIdentity,
    AgentState,
    ArtifactRef,
    NextAction,
    TaskRequest,
    TaskResult,
    blocked_result,
    failed_result,
    make_error,
)
from agent_contract.registry import ACTION_MAP, CAPABILITY_REGISTRY
from config import AgentConfig
from llm import LLMClient, LLMError
from prompt import {role_upper}_SYSTEM_PROMPT, build_messages
from schemas import {to_pascal_case(first_action)}Output
from tools.artifact import ArtifactError, save_artifact

T = TypeVar("T", bound=BaseModel)


def action(
    name: str,
    output_model: type[BaseModel] | None = None,
    capability: str | None = None,
) -> Callable:
    """Decorator đăng ký action cho {role_upper} Agent."""
    def decorator(func: Callable) -> Callable:
        func._action_name = name  # type: ignore[attr-defined]
        func._output_model = output_model  # type: ignore[attr-defined]
        func._capability = capability  # type: ignore[attr-defined]
        return func
    return decorator


class BaseAgent:
    """Lớp nền tảng quản lý vòng đời tác vụ và bảo vệ lỗi chuẩn Contract v1.0."""

    def __init__(
        self,
        identity: AgentIdentity,
        config: AgentConfig,
        llm: LLMClient | None = None,
    ) -> None:
        self.identity = identity
        self.config = config
        self.llm = llm or LLMClient(config=config, mock=True)
        self._current_task: str | None = None
        self._actions: dict[str, tuple[Callable, type[BaseModel] | None, str | None]] = {{}}
        self._scan_and_register_actions()

    def _scan_and_register_actions(self) -> None:
        for attr_name in dir(self):
            try:
                attr = getattr(self, attr_name)
                if callable(attr) and hasattr(attr, "_action_name"):
                    action_name = getattr(attr, "_action_name")
                    output_model = getattr(attr, "_output_model", None)
                    capability = getattr(attr, "_capability", None)
                    self._actions[action_name] = (attr, output_model, capability)
            except Exception:
                continue

    def get_identity(self) -> AgentIdentity:
        return self.identity

    def get_state(self) -> AgentState:
        return AgentState(
            agent_id=self.identity.agent_id,
            role=self.identity.role,
            status=self.identity.status,
            current_task=self._current_task,
            updated_at=datetime.now(timezone.utc),
        )

    def handle(self, request: TaskRequest) -> TaskResult:
        start_time = time.perf_counter()

        if not request.instruction or not request.instruction.strip() or request.context.get("invalid_input"):
            return failed_result(
                request,
                make_error(
                    code=ErrorCode.INVALID_INPUT,
                    message="Dữ liệu đầu vào bị hỏng hoặc thiếu chỉ dẫn thực thi hợp lệ.",
                    retryable=False,
                ),
                summary="Dữ liệu đầu vào không hợp lệ.",
            )

        if request.role != self.identity.role:
            return failed_result(
                request,
                make_error(
                    code=ErrorCode.PERMISSION_DENIED,
                    message=f"Role mismatch: Agent role is {{self.identity.role.value}}, but request role is {{request.role.value}}.",
                    retryable=False,
                ),
            )

        if request.agent_id != self.identity.agent_id:
            return failed_result(
                request,
                make_error(
                    code=ErrorCode.PERMISSION_DENIED,
                    message=f"Agent ID mismatch: Agent is {{self.identity.agent_id}}, but request is for {{request.agent_id}}.",
                    retryable=False,
                ),
            )

        if request.action not in self._actions:
            return failed_result(
                request,
                make_error(
                    code=ErrorCode.PERMISSION_DENIED,
                    message=f"Action '{{request.action}}' không được hỗ trợ bởi agent {{self.identity.agent_id}}.",
                    retryable=False,
                ),
            )

        self.identity.status = AgentStatus.RUNNING
        self._current_task = request.task_id

        final_result: TaskResult

        try:
            handler, _, _ = self._actions[request.action]
            raw_output = handler(request)

            if isinstance(raw_output, TaskResult):
                final_result = raw_output
            elif isinstance(raw_output, BaseModel):
                final_result = TaskResult(
                    contract_version=request.contract_version,
                    task_id=request.task_id,
                    agent_id=request.agent_id,
                    status=TaskStatus.COMPLETED,
                    summary=f"Thực thi thành công action '{{request.action}}'",
                    outputs=[raw_output.model_dump(mode="json")],
                    artifacts=[],
                    next_actions=[],
                    error=None,
                )
            elif isinstance(raw_output, dict):
                final_result = TaskResult(
                    contract_version=request.contract_version,
                    task_id=request.task_id,
                    agent_id=request.agent_id,
                    status=TaskStatus.COMPLETED,
                    summary=f"Thực thi thành công action '{{request.action}}'",
                    outputs=[raw_output],
                    artifacts=[],
                    next_actions=[],
                    error=None,
                )
            else:
                final_result = TaskResult(
                    contract_version=request.contract_version,
                    task_id=request.task_id,
                    agent_id=request.agent_id,
                    status=TaskStatus.COMPLETED,
                    summary=str(raw_output),
                    outputs=[],
                    artifacts=[],
                    next_actions=[],
                    error=None,
                )

            self.identity.status = AgentStatus.IDLE
            self._current_task = None

        except LLMError as err:
            self.identity.status = AgentStatus.FAILED
            self._current_task = None
            final_result = failed_result(
                request,
                make_error(code=ErrorCode.LLM_ERROR, message=str(err), retryable=True),
                summary=f"Lỗi LLM khi thực thi action '{{request.action}}'",
            )
        except ArtifactError as err:
            self.identity.status = AgentStatus.FAILED
            self._current_task = None
            final_result = failed_result(
                request,
                make_error(code=ErrorCode.TOOL_ERROR, message=str(err), retryable=True),
                summary=f"Lỗi artifact khi thực thi action '{{request.action}}'",
            )
        except ValueError as err:
            self.identity.status = AgentStatus.FAILED
            self._current_task = None
            final_result = failed_result(
                request,
                make_error(code=ErrorCode.INVALID_INPUT, message=str(err), retryable=False),
                summary=f"Dữ liệu đầu vào không hợp lệ khi thực thi action '{{request.action}}'",
            )
        except Exception as err:
            self.identity.status = AgentStatus.FAILED
            self._current_task = None
            final_result = failed_result(
                request,
                make_error(code=ErrorCode.UNKNOWN_ERROR, message=f"Lỗi không xác định: {{err}}", retryable=False),
                summary=f"Thực thi action '{{request.action}}' thất bại",
            )

        duration_ms = int((time.perf_counter() - start_time) * 1000)
        final_result.metadata.setdefault("provider", self.config.llm_provider)
        final_result.metadata.setdefault("model", self.config.llm_model)
        final_result.metadata.setdefault("duration_ms", duration_ms)
        final_result.metadata.setdefault("dry_run", self.config.dry_run)

        self.identity.status = AgentStatus.IDLE
        return final_result


class {class_name}(BaseAgent):
    """{agent_info.get('description', f'{role_upper} Agent độc lập')}."""

    def __init__(
        self,
        config: AgentConfig | None = None,
        llm: LLMClient | None = None,
        artifact_dir: Union[Path, str, None] = None,
    ) -> None:
        cfg = config or AgentConfig()
        if artifact_dir:
            cfg.artifact_dir = str(artifact_dir)

        identity = AgentIdentity(
            agent_id=cfg.agent_id or "{agent_id}",
            role=AgentRole.{role_upper},
            name="{role_upper} Agent",
            version="1.0.0",
            capabilities=CAPABILITY_REGISTRY[AgentRole.{role_upper}],
            status=AgentStatus.IDLE,
        )
        super().__init__(identity=identity, config=cfg, llm=llm)

    @action("{first_action}", output_model={to_pascal_case(first_action)}Output, capability="{first_cap}")
    def handle_{first_action}(self, request: TaskRequest) -> TaskResult:
        """Xử lý action '{first_action}'."""
        if not self.llm.mock or self.llm.mock_responder:
            messages = build_messages(
                system_prompt={role_upper}_SYSTEM_PROMPT,
                request=request,
                output_schema={to_pascal_case(first_action)}Output.model_json_schema(),
            )
            data = self.llm.complete_json(messages, {to_pascal_case(first_action)}Output)
        else:
            data = {to_pascal_case(first_action)}Output(
                summary=f"Kết quả xử lý từ {role_upper}: {{request.instruction}}",
                details={{"task_id": request.task_id, "role": "{role_upper}"}},
            )

        # Lưu artifact mẫu
        art_ref = save_artifact(
            name="{agent_info.get('primary_artifacts', ['output.md'])[0]}",
            type=ArtifactType.REQUIREMENT if "{role_upper}" == "BA" else ArtifactType.REPORT,
            content=f"# Báo cáo từ {role_upper}\\n\\n**Tóm tắt:** {{data.summary}}\\n",
            created_by=self.identity.agent_id,
            artifact_dir=self.config.artifact_dir,
        )

        return TaskResult(
            contract_version=request.contract_version,
            task_id=request.task_id,
            agent_id=request.agent_id,
            status=TaskStatus.COMPLETED,
            summary=f"Đã hoàn thành action '{first_action}'.",
            outputs=[data.model_dump(mode="json")],
            artifacts=[art_ref],
            next_actions=[],
            error=None,
        )
'''


def generate_schemas_py(role_key: str, agent_info: dict) -> str:
    actions = agent_info.get("actions", {})
    first_action = list(actions.keys())[0] if actions else "execute"
    class_name = f"{to_pascal_case(first_action)}Output"

    return f'''from typing import Any
from pydantic import BaseModel, Field


class {class_name}(BaseModel):
    """Schema đầu ra cho action '{first_action}' của {agent_info['role']} Agent."""
    summary: str = Field(description="Tóm tắt kết quả thực hiện")
    details: dict[str, Any] = Field(default_factory=dict, description="Chi tiết kết quả")
'''


def generate_prompt_py(role_key: str, agent_info: dict) -> str:
    role_upper = agent_info["role"]
    caps_str = ", ".join(agent_info.get("capabilities", []))

    return f'''import json
from typing import Any, Callable
from agent_contract.models import ArtifactRef, TaskRequest

{role_upper}_SYSTEM_PROMPT = """Bạn là {role_upper} AI Agent (ID: {agent_info['agent_id']}) trong hệ thống 'ai-team'.
Chuyên môn và khả năng: {caps_str}.

QUY TẮC:
1. Bạn chỉ thực hiện các công việc thuộc phạm vi của vai trò {role_upper}.
2. Trả về DUY NHẤT một chuỗi JSON hợp lệ theo Schema được cung cấp, không kèm văn bản dẫn dắt bên ngoài.
"""


def build_messages(
    system_prompt: str,
    request: TaskRequest,
    output_schema: dict[str, Any] | None = None,
) -> list[dict[str, str]]:
    """Ghép system prompt, instruction, context thành messages chuẩn OpenAI-compatible."""
    system_parts = [system_prompt.strip()]
    system_parts.append(
        "\\n--- QUY TẮC BẮT BUỘC ---\\n"
        "1. Trả về DUY NHẤT một chuỗi JSON hợp lệ theo Schema.\\n"
        "2. Không thêm bất kỳ lời dẫn hay văn bản nào bên ngoài JSON."
    )
    if output_schema:
        schema_json = json.dumps(output_schema, indent=2, ensure_ascii=False)
        system_parts.append(f"\\n--- JSON SCHEMA BẮT BUỘC ---\\n```json\\n{{schema_json}}\\n```")

    full_system = "\\n\\n".join(system_parts)

    user_parts = [
        f"Mã tác vụ (Task ID): {{request.task_id}}",
        f"Hành động (Action): {{request.action}}",
        f"Chỉ dẫn (Instruction):\\n{{request.instruction}}",
    ]
    if request.context:
        user_parts.append(f"Ngữ cảnh (Context):\\n```json\\n{{json.dumps(request.context, indent=2, ensure_ascii=False)}}\\n```")

    return [
        {{"role": "system", "content": full_system}},
        {{"role": "user", "content": "\\n\\n".join(user_parts)}},
    ]
'''


def generate_test_py(role_key: str, agent_info: dict) -> str:
    role_upper = agent_info["role"]
    agent_id = agent_info["agent_id"]
    class_name = f"{to_pascal_case(role_key)}Agent"
    actions = agent_info.get("actions", {})
    first_action = list(actions.keys())[0] if actions else "execute"

    return f'''import sys
from pathlib import Path

agent_dir = Path(__file__).resolve().parent.parent
if str(agent_dir) not in sys.path:
    sys.path.insert(0, str(agent_dir))

for key in list(sys.modules.keys()):
    if key in ["agent", "config", "llm", "prompt", "schemas", "api", "tools"] or key.startswith("tools."):
        sys.modules.pop(key, None)

import pytest
from agent_contract.enums import AgentRole, ErrorCode, TaskStatus
from agent_contract.models import TaskRequest
from agent import {class_name}
from config import AgentConfig
from llm import LLMClient


@pytest.fixture
def agent(tmp_path) -> {class_name}:
    cfg = AgentConfig(
        base_dir=tmp_path,
        port={agent_info['port']},
        agent_id="{agent_id}",
        agent_role=AgentRole.{role_upper},
        artifact_dir=str(tmp_path / "artifacts"),
    )
    llm = LLMClient(config=cfg, mock=True)
    return {class_name}(config=cfg, llm=llm, artifact_dir=cfg.artifact_dir)


def test_identity(agent):
    identity = agent.get_identity()
    assert identity.agent_id == "{agent_id}"
    assert identity.role == AgentRole.{role_upper}
    assert len(identity.capabilities) > 0


def test_handle_valid_action(agent):
    req = TaskRequest(
        task_id="TASK-TEST-001",
        project_id="PROJ-TEST",
        agent_id="{agent_id}",
        role=AgentRole.{role_upper},
        action="{first_action}",
        instruction="Chạy thử nghiệm kiểm tra tính tương thích",
        context={{}},
    )
    res = agent.handle(req)
    assert res.status == TaskStatus.COMPLETED
    assert res.error is None
    assert len(res.outputs) == 1


def test_handle_invalid_action(agent):
    req = TaskRequest(
        task_id="TASK-TEST-BAD-ACT",
        project_id="PROJ-TEST",
        agent_id="{agent_id}",
        role=AgentRole.{role_upper},
        action="action_khong_ton_tai",
        instruction="Thử action sai",
    )
    res = agent.handle(req)
    assert res.status == TaskStatus.FAILED
    assert res.error.code == ErrorCode.PERMISSION_DENIED


def test_handle_invalid_input(agent):
    req = TaskRequest(
        task_id="TASK-TEST-BAD-INPUT",
        project_id="PROJ-TEST",
        agent_id="{agent_id}",
        role=AgentRole.{role_upper},
        action="{first_action}",
        instruction="   ",
    )
    res = agent.handle(req)
    assert res.status == TaskStatus.FAILED
    assert res.error.code == ErrorCode.INVALID_INPUT
'''


def generate_task_json(role_key: str, agent_info: dict) -> dict:
    actions = agent_info.get("actions", {})
    first_action = list(actions.keys())[0] if actions else "execute"
    return {
        "contract_version": "1.0.0",
        "task_id": f"TASK-{agent_info['role']}-001",
        "project_id": "PROJECT-SAMPLE",
        "agent_id": agent_info["agent_id"],
        "role": agent_info["role"],
        "action": first_action,
        "instruction": f"Thực hiện tác vụ mẫu cho {agent_info['role']} Agent",
        "context": {},
        "input_artifacts": [],
        "constraints": {
            "priority": "MEDIUM",
            "timeout_seconds": 60
        }
    }


def scaffold_agent(role_input: str, force: bool = False) -> None:
    registry = load_registry()
    agents = registry.get("agents", {})

    target_key = None
    for k, v in agents.items():
        if k.lower() == role_input.lower() or v["role"].lower() == role_input.lower():
            target_key = k
            break

    if not target_key:
        print(f"Lỗi: Không tìm thấy vai trò '{role_input}' trong registry.", file=sys.stderr)
        print("Dùng 'python tools/scaffold_agent.py --list' để xem danh sách vai trò hợp lệ.")
        sys.exit(1)

    info = agents[target_key]
    dest_dir = AGENTS_DIR / target_key.lower()

    if dest_dir.exists():
        if not force:
            print(f"Lỗi: Thư mục '{dest_dir}' đã tồn tại! Sử dụng '--force' nếu muốn ghi đè.", file=sys.stderr)
            sys.exit(1)
        else:
            print(f"[*] Ghi đè thư mục tồn tại: {dest_dir}")
            shutil.rmtree(dest_dir)

    dest_dir.mkdir(parents=True, exist_ok=True)
    print(f"[*] Đang khởi tạo Agent '{info['role']}' tại: {dest_dir}")

    # Copy các file nền tảng từ agent-template
    for item in ["config.py", "llm.py", "api.py", "cli.py", "requirements.txt"]:
        src = TEMPLATE_DIR / item
        if src.exists():
            shutil.copy2(src, dest_dir / item)

    # Thư mục tools/
    tools_dir = dest_dir / "tools"
    tools_dir.mkdir(exist_ok=True)
    shutil.copy2(TEMPLATE_DIR / "tools" / "artifact.py", tools_dir / "artifact.py")
    (tools_dir / "__init__.py").write_text("", encoding="utf-8")

    # Thư mục artifacts/ và inbox
    (dest_dir / "artifacts" / "inbox").mkdir(parents=True, exist_ok=True)
    (dest_dir / "workspace").mkdir(exist_ok=True)
    (dest_dir / "data").mkdir(exist_ok=True)
    (dest_dir / "tests").mkdir(exist_ok=True)
    (dest_dir / "examples").mkdir(exist_ok=True)

    # .gitignore
    (dest_dir / ".gitignore").write_text(".env\nworkspace/\ndata/\n__pycache__/\n*.pyc\n", encoding="utf-8")

    # .env.example & .env
    env_content = f"""HOST=0.0.0.0
PORT={info['port']}
CONTRACT_MIN_VERSION=1.0.0
AGENT_ID={info['agent_id']}
AGENT_ROLE={info['role']}
LLM_PROVIDER=gemini
LLM_MODEL=gemini-3.6-flash
LLM_API_KEY=
LLM_BASE_URL=https://generativelanguage.googleapis.com/v1beta/openai/
LLM_TEMPERATURE=0.2
LLM_TIMEOUT_SECONDS=60
LLM_MAX_RETRIES=2
ARTIFACT_DIR=./artifacts
WORKSPACE_DIR=./workspace
ALLOWED_COMMANDS={info.get('allowed_commands', 'python,pytest')}
DRY_RUN=true
"""
    (dest_dir / ".env.example").write_text(env_content, encoding="utf-8")
    (dest_dir / ".env").write_text(env_content, encoding="utf-8")

    # Cập nhật config.py để đổi default agent_id và role
    config_path = dest_dir / "config.py"
    config_text = config_path.read_text(encoding="utf-8")
    config_text = config_text.replace('agent_id: str = "pm-01"', f'agent_id: str = "{info["agent_id"]}"')
    config_text = config_text.replace('agent_role: AgentRole = AgentRole.PM', f'agent_role: AgentRole = AgentRole.{info["role"]}')
    config_path.write_text(config_text, encoding="utf-8")

    # Sinh agent.py
    (dest_dir / "agent.py").write_text(generate_agent_py(target_key, info), encoding="utf-8")

    # Sinh schemas.py
    (dest_dir / "schemas.py").write_text(generate_schemas_py(target_key, info), encoding="utf-8")

    # Sinh prompt.py
    (dest_dir / "prompt.py").write_text(generate_prompt_py(target_key, info), encoding="utf-8")

    # Sinh examples/task.json
    task_json_path = dest_dir / "examples" / "task.json"
    task_json_path.write_text(json.dumps(generate_task_json(target_key, info), indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    # Sinh tests/test_<role>_agent.py
    test_path = dest_dir / "tests" / f"test_{target_key.lower()}_agent.py"
    test_path.write_text(generate_test_py(target_key, info), encoding="utf-8")

    # Sinh README.md
    readme_content = f"""# {info['role']} Agent ({info['agent_id']})

- **Vai trò:** {info['role']}
- **Máy phát triển:** Máy {info.get('machine', '?')}
- **Cổng kết nối mặc định (Port):** {info['port']}
- **Capabilities đã đăng ký:** {', '.join(info.get('capabilities', []))}
- **Mô tả:** {info.get('description', '')}

## Cách chạy thử nghiệm:

```powershell
# 1. Chạy prompt trực tiếp qua CLI
python cli.py prompt "Thực hiện tác vụ đầu tiên"

# 2. Mở chế độ chat tương tác
python cli.py chat

# 3. Chạy server API
python -m uvicorn api:app --port {info['port']}
```
"""
    (dest_dir / "README.md").write_text(readme_content, encoding="utf-8")

    print(f"[✓] Đã tạo thành công Agent '{info['role']}' tại: agents/{target_key.lower()}/")
    print(f"[*] Port phân bổ: {info['port']}")
    print(f"[*] Để kiểm tra tính tương thích, chạy lệnh: python tools/validate_agent.py\n")


def main() -> None:
    parser = argparse.ArgumentParser(description="Công cụ khởi tạo (scaffold) Agent độc lập chuẩn Contract v1.0")
    parser.add_argument("--role", type=str, help="Tên vai trò Agent cần tạo (ví dụ: BA, SA, DEV, TESTER, PO, DBA, SCRUM_MASTER, SECURITY)")
    parser.add_argument("--list", action="store_true", help="Hiển thị danh sách ma trận 10 Agent")
    parser.add_argument("--force", action="store_true", help="Ghi đè thư mục agent nếu đã tồn tại")

    args = parser.parse_args()
    registry = load_registry()

    if args.list:
        print_agent_list(registry)
    elif args.role:
        scaffold_agent(args.role, force=args.force)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
