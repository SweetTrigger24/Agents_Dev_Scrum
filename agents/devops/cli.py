import argparse
import io
import sys
from pathlib import Path

current_dir = Path(__file__).resolve().parent
if str(current_dir) not in sys.path:
    sys.path.insert(0, str(current_dir))

if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

from agent_contract.models import TaskRequest
from agent import DevOpsAgent
from config import DevOpsConfig
from llm import LLMClient


def main() -> None:
    """CLI quản lý và thực thi cho DevOps Agent."""
    parser = argparse.ArgumentParser(description="CLI chạy DevOps Agent độc lập")
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("identity", help="In thông tin AgentIdentity của DevOps")

    run_parser = subparsers.add_parser("run", help="Thực thi TaskRequest từ file JSON")
    run_parser.add_argument("task_file", type=str, help="Đường dẫn file task JSON")
    run_parser.add_argument("--mock", action="store_true", help="Chạy ở chế độ Mock LLM")

    args = parser.parse_args()
    config = DevOpsConfig()

    if args.command == "identity":
        agent = DevOpsAgent(config=config, llm=LLMClient(config=config, mock=True))
        print(agent.get_identity().model_dump_json(indent=2))

    elif args.command == "run":
        task_path = Path(args.task_file)
        if not task_path.exists():
            print(f"Lỗi: Không tìm thấy file task tại '{task_path}'", file=sys.stderr)
            sys.exit(1)

        with open(task_path, "r", encoding="utf-8") as f:
            raw_json = f.read()

        request = TaskRequest.model_validate_json(raw_json)
        use_mock = args.mock or not bool(config.llm_api_key.strip())
        llm = LLMClient(config=config, mock=use_mock)
        agent = DevOpsAgent(config=config, llm=llm)
        result = agent.handle(request)
        print(result.model_dump_json(indent=2))


if __name__ == "__main__":
    main()
