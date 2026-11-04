import json
from typing import Any, Callable

from agent_contract.models import ArtifactRef, TaskRequest


def build_messages(
    system_prompt: str,
    request: TaskRequest,
    artifact_reader: Callable[[ArtifactRef | str], str] | None = None,
    output_schema: dict[str, Any] | None = None,
) -> list[dict[str, str]]:
    """Ghép system prompt, instruction, context và nội dung input_artifacts thành danh sách messages chuẩn.

    Đồng thời bổ sung yêu cầu bắt buộc trả về đúng định dạng JSON tuân thủ schema.
    """
    # 1. Xây dựng nội dung System Message
    system_parts = [system_prompt.strip()]
    system_parts.append(
        "\n--- QUY TẮC PHẢN HỒI BẮT BUỘC ---\n"
        "1. Bạn PHẢI trả về kết quả DUY NHẤT dưới dạng chuỗi JSON hợp lệ.\n"
        "2. KHÔNG được thêm bất kỳ văn bản chào hỏi, lời dẫn, hay giải thích bên ngoài JSON.\n"
        "3. Nếu sử dụng markdown, chỉ được bao bằng duy nhất một khối ```json ... ```."
    )

    if output_schema:
        schema_json = json.dumps(output_schema, indent=2, ensure_ascii=False)
        system_parts.append(f"\n--- CẤU TRÚC JSON SCHEMA BẮT BUỘC ---\n```json\n{schema_json}\n```")

    full_system_content = "\n\n".join(system_parts)

    # 2. Xây dựng nội dung User Message
    user_parts = [
        f"Mã tác vụ (Task ID): {request.task_id}",
        f"Hành động (Action): {request.action}",
        f"Chỉ dẫn (Instruction):\n{request.instruction}",
    ]

    # Bổ sung Context nếu có
    if request.context:
        context_json = json.dumps(request.context, indent=2, ensure_ascii=False)
        user_parts.append(f"Ngữ cảnh (Context):\n```json\n{context_json}\n```")

    # Bổ sung Input Artifacts nếu có
    if request.input_artifacts:
        artifact_sections = ["Tài liệu đầu vào (Input Artifacts):"]
        for art in request.input_artifacts:
            art_header = f"- Artifact ID: {art.artifact_id} | Tên: {art.name} | Loại: {art.type.value}"
            content_str = ""
            if artifact_reader:
                try:
                    content_str = artifact_reader(art)
                except Exception as e:
                    content_str = f"[Không thể đọc nội dung artifact: {e}]"

            if content_str:
                artifact_sections.append(f"{art_header}\nNội dung:\n```\n{content_str}\n```")
            else:
                artifact_sections.append(f"{art_header} (URI: {art.uri})")

        user_parts.append("\n\n".join(artifact_sections))

    full_user_content = "\n\n".join(user_parts)

    return [
        {"role": "system", "content": full_system_content},
        {"role": "user", "content": full_user_content},
    ]
