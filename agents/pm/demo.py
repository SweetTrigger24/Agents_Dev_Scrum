import argparse
import io
import json
import sys
from pathlib import Path

# Đảm bảo import đúng trong thư mục agents/pm và in UTF-8
current_dir = Path(__file__).resolve().parent
if str(current_dir) not in sys.path:
    sys.path.insert(0, str(current_dir))

if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

from agent_contract.models import TaskRequest, TaskResult
from agent import PMAgent
from config import PMConfig
from llm import LLMClient


def load_request_from_file(file_name: str) -> TaskRequest:
    """Tải TaskRequest từ file json trong thư mục examples."""
    file_path = current_dir / "examples" / file_name
    with open(file_path, "r", encoding="utf-8") as f:
        data = f.read()
    return TaskRequest.model_validate_json(data)


def print_step_result(step_num: int, title: str, result: TaskResult) -> None:
    """In định dạng trực quan kết quả TaskResult của từng bước."""
    print("=" * 70)
    print(f" BƯỚC {step_num}: {title.upper()}")
    print("=" * 70)
    print(f"Task ID     : {result.task_id}")
    print(f"Trạng thái  : {result.status.value}")
    print(f"Tóm tắt     : {result.summary}")
    print(f"Artifacts   : {[a.name for a in result.artifacts]}")
    print(f"Gợi ý tiếp  : {[(na.suggested_role.value, na.action) for na in result.next_actions]}")
    print(f"Metadata    : {result.metadata}")
    print("-" * 70)
    print("JSON Chi tiết:")
    print(result.model_dump_json(indent=2))
    print("\n")


def run_demo(mock: bool = False) -> None:
    """Chạy chuỗi tác vụ: create_plan -> decompose_tasks -> assign_tasks -> report_status."""
    config = PMConfig()
    # Tự động bật mock nếu không có API key
    use_mock = mock or not bool(config.llm_api_key.strip())
    llm = LLMClient(config=config, mock=use_mock)
    agent = PMAgent(config=config, llm=llm)

    mode_label = "MOCK (Offline)" if use_mock else f"REAL LLM ({config.llm_provider})"
    print(f"\n>>> BẮT ĐẦU CHUỖI DEMO PM AGENT [{mode_label}] <<<\n")

    # 1. Bước 1: create_plan
    req1 = load_request_from_file("task_create_plan.json")
    res1 = agent.handle(req1)
    # Xác thực TaskResult tuân thủ schema contract
    TaskResult.model_validate(res1.model_dump())
    print_step_result(1, "Lập kế hoạch tổng thể (create_plan)", res1)

    # 2. Bước 2: decompose_tasks
    req2 = load_request_from_file("task_decompose_tasks.json")
    res2 = agent.handle(req2)
    TaskResult.model_validate(res2.model_dump())
    print_step_result(2, "Phân rã nhiệm vụ (decompose_tasks)", res2)

    # 3. Bước 3: assign_tasks
    req3 = load_request_from_file("task_assign_tasks.json")
    res3 = agent.handle(req3)
    TaskResult.model_validate(res3.model_dump())
    print_step_result(3, "Phân công nhiệm vụ (assign_tasks)", res3)

    # 4. Bước 4: report_status
    req4 = load_request_from_file("task_report_status.json")
    res4 = agent.handle(req4)
    TaskResult.model_validate(res4.model_dump())
    print_step_result(4, "Báo cáo trạng thái (report_status)", res4)

    print("=" * 70)
    print(">>> HOÀN THÀNH DEMO CHUỖI 4 BƯỚC CỦA PM AGENT THÀNH CÔNG! <<<")
    print("=" * 70)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Chạy demo chuỗi 4 tác vụ của PM Agent")
    parser.add_argument("--mock", action="store_true", help="Bắt buộc sử dụng Mock LLM không gọi mạng")
    args = parser.parse_args()
    run_demo(mock=args.mock)
