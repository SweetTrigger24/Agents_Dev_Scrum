import argparse
import io
import sys
from pathlib import Path

# Đảm bảo import đúng các module nội bộ của agent-template và in UTF-8
current_dir = Path(__file__).resolve().parent
if str(current_dir) not in sys.path:
    sys.path.insert(0, str(current_dir))

if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

from agent_contract.models import AgentIdentity, TaskRequest
from agent_contract.registry import CAPABILITY_REGISTRY
from agent import BaseAgent
from config import AgentConfig
from llm import LLMClient


def create_default_agent(config: AgentConfig, mock: bool = False) -> BaseAgent:
    """Khởi tạo agent mặc định dựa trên config."""
    identity = AgentIdentity(
        agent_id=config.agent_id,
        role=config.agent_role,
        name=f"{config.agent_role.value} Template Agent",
        version="1.0.0",
        capabilities=CAPABILITY_REGISTRY.get(config.agent_role, []),
    )
    llm = LLMClient(config=config, mock=mock)
    return BaseAgent(identity=identity, config=config, llm=llm)


def main() -> None:
    """CLI thực thi tác vụ hoặc truy vấn thông tin định danh của Agent."""
    parser = argparse.ArgumentParser(description="CLI chạy Agent độc lập tuân thủ Agent Contract v1.0")
    subparsers = parser.add_subparsers(dest="command", required=True)

    # Subcommand: identity
    subparsers.add_parser("identity", help="In thông tin AgentIdentity dưới dạng JSON")

    # Subcommand: run
    run_parser = subparsers.add_parser("run", help="Thực thi một tác vụ từ file TaskRequest JSON")
    run_parser.add_argument("task_file", type=str, help="Đường dẫn tới file TaskRequest JSON")
    run_parser.add_argument("--mock", action="store_true", help="Sử dụng LLM giả lập không gọi mạng")

    args = parser.parse_args()
    config = AgentConfig()

    if args.command == "identity":
        agent = create_default_agent(config, mock=True)
        print(agent.get_identity().model_dump_json(indent=2))

    elif args.command == "run":
        task_path = Path(args.task_file)
        if not task_path.exists():
            print(f"Lỗi: Không tìm thấy file task tại '{task_path}'", file=sys.stderr)
            sys.exit(1)

        with open(task_path, "r", encoding="utf-8") as f:
            raw_json = f.read()

        request = TaskRequest.model_validate_json(raw_json)
        agent = create_default_agent(config, mock=args.mock)
        result = agent.handle(request)
        print(result.model_dump_json(indent=2))


if __name__ == "__main__":
    main()
