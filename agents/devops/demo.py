import argparse
import io
import json
import sys
from pathlib import Path

# Đảm bảo import đúng trong thư mục agents/devops và in UTF-8
current_dir = Path(__file__).resolve().parent
if str(current_dir) not in sys.path:
    sys.path.insert(0, str(current_dir))

if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

from agent_contract.models import TaskRequest, TaskResult
from agent import DevOpsAgent
from config import DevOpsConfig
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


def run_demo(mock: bool = True) -> None:
    """Chạy chuỗi tác vụ DevOps: generate_ci_config -> build_image (dry-run) -> run_tests (dry-run) -> deploy (dry-run, staging) -> health_check."""
    config = DevOpsConfig(dry_run=True)  # Mặc định an toàn: DRY_RUN=true
    llm = LLMClient(config=config, mock=mock)
    agent = DevOpsAgent(config=config, llm=llm)

    print("\n>>> BẮT ĐẦU CHUỖI DEMO DEVOPS AGENT [CHẾ ĐỘ AN TOÀN DRY-RUN] <<<\n")

    # 1. Bước 1: generate_ci_config (chỉ tạo file artifact, không chạy lệnh)
    req1 = load_request_from_file("task_generate_ci_config.json")
    res1 = agent.handle(req1)
    TaskResult.model_validate(res1.model_dump())
    print_step_result(1, "Sinh cấu hình CI/CD (generate_ci_config)", res1)

    # 2. Bước 2: build_image (dry-run)
    req2 = load_request_from_file("task_build_image.json")
    res2 = agent.handle(req2)
    TaskResult.model_validate(res2.model_dump())
    print_step_result(2, "Đóng gói Docker Image (build_image, dry-run)", res2)

    # 3. Bước 3: run_tests (dry-run)
    req3 = load_request_from_file("task_run_tests.json")
    res3 = agent.handle(req3)
    TaskResult.model_validate(res3.model_dump())
    print_step_result(3, "Chạy kiểm thử tự động (run_tests, dry-run)", res3)

    # 4. Bước 4: deploy (dry-run, staging)
    req4 = load_request_from_file("task_deploy.json")
    res4 = agent.handle(req4)
    TaskResult.model_validate(res4.model_dump())
    print_step_result(4, "Triển khai Staging (deploy, dry-run)", res4)

    # 5. Bước 5: health_check
    req5 = load_request_from_file("task_health_check.json")
    res5 = agent.handle(req5)
    TaskResult.model_validate(res5.model_dump())
    print_step_result(5, "Kiểm tra sức khỏe dịch vụ (health_check)", res5)

    print("=" * 70)
    print(">>> HOÀN THÀNH DEMO CHUỖI 5 BƯỚC CỦA DEVOPS AGENT THÀNH CÔNG! <<<")
    print("=" * 70)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Chạy demo chuỗi 5 tác vụ của DevOps Agent")
    parser.add_argument("--mock", action="store_true", default=True, help="Sử dụng Mock LLM không gọi mạng")
    args = parser.parse_args()
    run_demo(mock=args.mock)
