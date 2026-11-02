import json
from typing import Any, Callable

from agent_contract.models import ArtifactRef, TaskRequest

DEVOPS_SYSTEM_PROMPT = """Bạn là DevOps AI Agent (ID: devops-01) trong dự án 'ai-team'.

QUY TẮC AN TOÀN BẮT BUỘC:
1. Bạn CHỈ sinh KẾ HOẠCH LỆNH (CommandPlan): mỗi lệnh là danh sách các đối số (list of strings, ví dụ ["docker", "build", "-t", "app:latest", "."]), kèm giải thích và phương án rollback_plan.
2. TUYỆT ĐỐI KHÔNG sinh toán tử shell (&&, ||, ;, |, >, <, `). Mỗi lệnh phải là mảng string độc lập.
3. TUYỆT ĐỐI KHÔNG đề xuất các lệnh phá hủy bị cấm: rm -rf, git push --force/-f, docker system prune, DROP, curl|sh, sudo.
4. Chỉ đề xuất các binary nằm trong whitelist: git, docker, pytest, npm, mvn, python.
5. Với action 'generate_ci_config': Chỉ sinh nội dung cấu hình (Dockerfile, GitHub Actions, docker-compose) để lưu thành artifact, KHÔNG chạy bất kỳ lệnh nào.
6. Khi deploy: BẮT BUỘC phải có rollback_plan rõ ràng. Không tự ý deploy lên Production.
7. Trả về DUY NHẤT một chuỗi JSON hợp lệ tuân thủ Schema được cung cấp.
"""


def build_messages(
    system_prompt: str,
    request: TaskRequest,
    artifact_reader: Callable[[ArtifactRef | str], str] | None = None,
    output_schema: dict[str, Any] | None = None,
) -> list[dict[str, str]]:
    """Ghép system prompt, instruction, context và input_artifacts thành messages chuẩn cho DevOps."""
    system_parts = [system_prompt.strip()]
    system_parts.append(
        "\n--- YÊU CẦU ĐỊNH DẠNG ---\n"
        "1. Trả về DUY NHẤT một chuỗi JSON hợp lệ theo Schema.\n"
        "2. Không thêm bất kỳ lời dẫn, markdown giải thích nào ngoài JSON."
    )

    if output_schema:
        schema_json = json.dumps(output_schema, indent=2, ensure_ascii=False)
        system_parts.append(f"\n--- JSON SCHEMA BẮT BUỘC ---\n```json\n{schema_json}\n```")

    full_system = "\n\n".join(system_parts)

    user_parts = [
        f"Mã tác vụ (Task ID): {request.task_id}",
        f"Hành động (Action): {request.action}",
        f"Chỉ dẫn (Instruction):\n{request.instruction}",
    ]

    if request.context:
        user_parts.append(f"Ngữ cảnh (Context):\n```json\n{json.dumps(request.context, indent=2, ensure_ascii=False)}\n```")

    if request.input_artifacts:
        art_sections = ["Tài liệu đầu vào (Input Artifacts):"]
        for art in request.input_artifacts:
            header = f"- Artifact ID: {art.artifact_id} | Tên: {art.name} | Loại: {art.type.value}"
            content = ""
            if artifact_reader:
                try:
                    content = artifact_reader(art)
                except Exception as e:
                    content = f"[Lỗi đọc artifact: {e}]"
            if content:
                art_sections.append(f"{header}\nNội dung:\n```\n{content}\n```")
            else:
                art_sections.append(f"{header} (URI: {art.uri})")
        user_parts.append("\n\n".join(art_sections))

    return [
        {"role": "system", "content": full_system},
        {"role": "user", "content": "\n\n".join(user_parts)},
    ]
