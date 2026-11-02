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
from agent import PMAgent
from config import PMConfig
from llm import LLMClient


def main() -> None:
    """CLI quản lý và thực thi cho PM Agent."""
    parser = argparse.ArgumentParser(description="CLI chạy PM Agent độc lập")
    subparsers = parser.add_subparsers(dest="command", required=True)

    # 1. Lệnh xem identity
    subparsers.add_parser("identity", help="In thông tin AgentIdentity của PM")

    # 2. Lệnh chạy từ file JSON
    run_parser = subparsers.add_parser("run", help="Thực thi TaskRequest từ file JSON")
    run_parser.add_argument("task_file", type=str, help="Đường dẫn file task JSON")
    run_parser.add_argument("--mock", action="store_true", help="Chạy ở chế độ Mock LLM")

    # 3. Lệnh gửi prompt trực tiếp
    prompt_parser = subparsers.add_parser("prompt", help="Gửi câu lệnh prompt trực tiếp bằng văn bản")
    prompt_parser.add_argument("text", type=str, help="Nội dung câu prompt yêu cầu PM thực hiện")
    prompt_parser.add_argument(
        "--action",
        type=str,
        default="create_plan",
        help="Action cần thực hiện: create_plan (mặc định), analyze_requirement, decompose_tasks, report_status",
    )
    prompt_parser.add_argument("--mock", action="store_true", help="Chạy ở chế độ Mock LLM")

    # 4. Chế độ chat tương tác liên tục
    chat_parser = subparsers.add_parser("chat", help="Mở phiên chat tương tác trực tiếp với PM Agent")
    chat_parser.add_argument("--mock", action="store_true", help="Chạy ở chế độ Mock LLM")

    args = parser.parse_args()
    config = PMConfig()

    if args.command == "identity":
        agent = PMAgent(config=config, llm=LLMClient(config=config, mock=True))
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
        agent = PMAgent(config=config, llm=llm)
        result = agent.handle(request)
        print(result.model_dump_json(indent=2))

    elif args.command == "prompt":
        now_tag = datetime.now(timezone.utc).strftime("%H%M%S")
        request = TaskRequest(
            task_id=f"TASK-CLI-{now_tag}",
            project_id="PROJ-CLI",
            agent_id=config.agent_id,
            role=config.agent_role,
            action=args.action,
            instruction=args.text,
            context={"source": "cli_prompt"},
        )
        use_mock = args.mock or not bool(config.llm_api_key.strip())
        llm = LLMClient(config=config, mock=use_mock)
        agent = PMAgent(config=config, llm=llm)

        mode_str = "MOCK LLM" if use_mock else f"REAL LLM ({config.llm_model})"
        print(f"[*] Đang gửi prompt tới PM Agent qua {mode_str}...")
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
        agent = PMAgent(config=config, llm=llm)
        mode_str = "MOCK LLM" if use_mock else f"REAL LLM ({config.llm_model})"
        current_action = "create_plan"

        print("=" * 70)
        print(f"💬 PM AGENT INTERACTIVE CONSOLE [{mode_str}]")
        print("Nhập prompt trực tiếp để PM xử lý. Gõ 'exit' hoặc 'quit' để thoát.")
        print("Lệnh đặc biệt: ':action <tên_action>' để chuyển đổi action.")
        print(f"Action hiện tại: {current_action} (create_plan | analyze_requirement | decompose_tasks | report_status)")
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
                task_id=f"TASK-CHAT-{now_tag}-{counter}",
                project_id="PROJ-CHAT",
                agent_id=config.agent_id,
                role=config.agent_role,
                action=current_action,
                instruction=user_input,
                context={"source": "cli_chat"},
            )
            print(f"[*] Đang xử lý action '{current_action}' với {mode_str}...")
            result = agent.handle(request)

            print(f"\nPM [{result.status.value}] > {result.summary}")
            if result.error:
                print(f"⚠️  Lý do: {result.error.message}")
                questions = result.error.details.get("questions") if result.error.details else None
                if questions:
                    print("❓ PM cần bạn cung cấp thêm thông tin:")
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
