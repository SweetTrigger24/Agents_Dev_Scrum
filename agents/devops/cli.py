import argparse
import io
import sys
from datetime import datetime, timezone
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

    # Prompt trực tiếp
    prompt_parser = subparsers.add_parser("prompt", help="Gửi câu lệnh prompt trực tiếp bằng văn bản")
    prompt_parser.add_argument("text", type=str, help="Nội dung câu prompt yêu cầu DevOps thực hiện")
    prompt_parser.add_argument(
        "--action",
        type=str,
        default="generate_ci_config",
        help="Action cần thực hiện: generate_ci_config (mặc định), build_image, run_tests, deploy, health_check, setup_monitoring",
    )
    prompt_parser.add_argument("--mock", action="store_true", help="Chạy ở chế độ Mock LLM")

    # Chat tương tác
    chat_parser = subparsers.add_parser("chat", help="Mở phiên chat tương tác trực tiếp với DevOps Agent")
    chat_parser.add_argument("--mock", action="store_true", help="Chạy ở chế độ Mock LLM")

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

    elif args.command == "prompt":
        now_tag = datetime.now(timezone.utc).strftime("%H%M%S")
        request = TaskRequest(
            task_id=f"TASK-DEVOPS-CLI-{now_tag}",
            project_id="PROJ-CLI",
            agent_id=config.agent_id,
            role=config.agent_role,
            action=args.action,
            instruction=args.text,
            context={"source": "cli_prompt"},
        )
        use_mock = args.mock or not bool(config.llm_api_key.strip())
        llm = LLMClient(config=config, mock=use_mock)
        agent = DevOpsAgent(config=config, llm=llm)

        mode_str = "MOCK LLM" if use_mock else f"REAL LLM ({config.llm_model})"
        print(f"[*] Đang gửi prompt tới DevOps Agent qua {mode_str}...")
        print(f"[*] Action: {args.action}")
        print(f"[*] Prompt: \"{args.text}\"\n")

        result = agent.handle(request)

        print("=" * 70)
        print(f"KẾT QUẢ THỰC THI: {result.status.value}")
        print(f"Tóm tắt: {result.summary}")
        if result.error:
            print(f"Chi tiết lỗi / lý do: {result.error.message} (Mã: {result.error.code.value})")
            questions = result.error.details.get("questions") if result.error.details else None
            if questions:
                print("Các câu hỏi cần làm rõ:")
                for q in questions:
                    print(f"  ? {q}")
        if result.artifacts:
            print("Artifacts tạo ra:")
            for art in result.artifacts:
                print(f"  + {art.name} ({art.type.value}): {art.uri}")
        if result.next_actions:
            print("Gợi ý bước kế tiếp:")
            for na in result.next_actions:
                print(f"  + {na.suggested_role.value} -> {na.action}: {na.reason}")
        print("=" * 70)
        print("\nJSON Chi tiết:")
        print(result.model_dump_json(indent=2))

    elif args.command == "chat":
        use_mock = args.mock or not bool(config.llm_api_key.strip())
        llm = LLMClient(config=config, mock=use_mock)
        agent = DevOpsAgent(config=config, llm=llm)
        mode_str = "MOCK LLM" if use_mock else f"REAL LLM ({config.llm_model})"
        current_action = "generate_ci_config"

        print("=" * 70)
        print(f"💬 DEVOPS AGENT INTERACTIVE CONSOLE [{mode_str}]")
        print("Nhập prompt trực tiếp để DevOps xử lý. Gõ 'exit' hoặc 'quit' để thoát.")
        print("Lệnh đặc biệt: ':action <tên_action>' để chuyển đổi action.")
        print("Actions: generate_ci_config | build_image | run_tests | deploy | health_check | setup_monitoring")
        print(f"Action hiện tại: {current_action}")
        print("=" * 70)

        counter = 1
        while True:
            try:
                user_input = input(f"\n[{counter}] Bạn > ").strip()
            except (EOFError, KeyboardInterrupt):
                print("\nĐã thoát chế độ chat.")
                break

            if not user_input:
                continue
            if user_input.lower() in ("exit", "quit", "q"):
                print("Tạm biệt!")
                break
            if user_input.startswith(":action"):
                parts = user_input.split(maxsplit=1)
                if len(parts) > 1 and parts[1].strip():
                    current_action = parts[1].strip()
                    print(f"[*] Đã chuyển action sang: {current_action}")
                else:
                    print(f"[*] Action hiện tại: {current_action}")
                continue

            now_tag = datetime.now(timezone.utc).strftime("%H%M%S")
            request = TaskRequest(
                task_id=f"TASK-DEVOPS-CHAT-{now_tag}-{counter}",
                project_id="PROJ-CHAT",
                agent_id=config.agent_id,
                role=config.agent_role,
                action=current_action,
                instruction=user_input,
                context={"source": "cli_chat"},
            )
            print(f"[*] Đang xử lý action '{current_action}' với {mode_str}...")
            result = agent.handle(request)

            print(f"\nDevOps [{result.status.value}] > {result.summary}")
            if result.error:
                print(f"⚠️  Lý do: {result.error.message}")
                questions = result.error.details.get("questions") if result.error.details else None
                if questions:
                    print("❓ DevOps cần bạn cung cấp thêm thông tin:")
                    for q in questions:
                        print(f"   • {q}")
            if result.artifacts:
                print("📁 Artifacts vừa tạo:")
                for art in result.artifacts:
                    print(f"   • {art.name} ({art.type.value}): {art.uri}")
            if result.next_actions:
                print("👉 Bước kế tiếp gợi ý:")
                for na in result.next_actions:
                    print(f"   • [{na.suggested_role.value}] {na.action}: {na.reason}")
            counter += 1


if __name__ == "__main__":
    main()

