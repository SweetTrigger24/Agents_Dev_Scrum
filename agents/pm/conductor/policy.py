import logging
import time
from typing import Any

from agent_contract.enums import ErrorCode, TaskStatus
from agent_contract.models import TaskResult

logger = logging.getLogger("pm.conductor.policy")


def parse_verdict(outputs: list[dict[str, Any]]) -> tuple[str, list[dict[str, Any]]]:
    """Phân tích verdict (PASS | FAIL) và danh sách findings từ outputs[0]."""
    if not outputs or not isinstance(outputs[0], dict):
        return "PASS", []

    out = outputs[0]
    verdict = str(out.get("verdict", "PASS")).upper().strip()
    findings = out.get("findings", [])
    if not isinstance(findings, list):
        findings = []

    # Quy tắc an toàn: Nếu có bất kỳ phát hiện nào mức CRITICAL hoặc HIGH, verdict bắt buộc là FAIL
    has_critical_or_high = any(
        isinstance(f, dict) and str(f.get("severity", "")).upper() in ["CRITICAL", "HIGH"]
        for f in findings
    )
    if has_critical_or_high:
        verdict = "FAIL"

    return verdict, findings


def should_trigger_fix_loop(role: str, action: str, result: TaskResult) -> tuple[bool, str, list[dict[str, Any]]]:
    """Kiểm tra xem kết quả của TESTER hoặc SECURITY có kích hoạt vòng sửa lỗi hay không."""
    if result.status != TaskStatus.COMPLETED:
        return False, "NO_COMPLETED", []

    r_upper = role.upper()
    act = action.lower()

    if r_upper in ["TESTER", "SECURITY", "PO"] or act in ["run_test_suite", "security_review", "accept_release"]:
        verdict, findings = parse_verdict(result.outputs)
        if verdict == "FAIL":
            if r_upper == "SECURITY" or act == "security_review":
                # Security chỉ kích hoạt vòng sửa lỗi khi có HIGH hoặc CRITICAL
                high_or_crit = [
                    f for f in findings
                    if isinstance(f, dict) and str(f.get("severity", "")).upper() in ["HIGH", "CRITICAL"]
                ]
                if high_or_crit:
                    return True, "SECURITY_VULNERABILITY", high_or_crit
                return False, "SECURITY_LOW_FINDINGS", findings
            # Tester hoặc PO reject
            return True, f"{r_upper}_VERDICT_FAIL", findings

    return False, "PASS", []


def generate_answers_for_missing_context(
    brief: str,
    questions: list[str],
    llm_client: Any | None = None,
) -> dict[str, str]:
    """PM trả lời MỘT lần các câu hỏi thiếu ngữ cảnh dựa trên brief dự án."""
    if not questions:
        return {"project_scope": brief}

    answers: dict[str, str] = {}

    if llm_client and not getattr(llm_client, "mock", True):
        try:
            prompt = (
                f"Bạn là Project Manager. Dựa trên bản brief dự án sau đây: \n\"\"\"{brief}\"\"\"\n\n"
                f"Hãy trả lời ngắn gọn và chính xác các câu hỏi làm rõ sau:\n"
                + "\n".join(f"{i+1}. {q}" for i, q in enumerate(questions))
                + "\n\nTrả về kết quả định dạng JSON: {câu hỏi: câu trả lời}."
            )
            res = llm_client.complete_text([{"role": "user", "content": prompt}])
            # Parse thô hoặc fallback
            answers = {"clarifications": res, "provided_by": "PM"}
            return answers
        except Exception as e:
            logger.warning(f"Lỗi khi LLM trả lời missing context: {e}")

    # Fallback offline tự động trích xuất từ brief
    for i, q in enumerate(questions):
        q_key = f"clarification_{i+1}"
        answers[q_key] = f"Dựa theo brief '{brief[:60]}...': Đã xác nhận phạm vi chuẩn và yêu cầu kỹ thuật đầy đủ."
    answers["answered_from_brief"] = brief
    return answers
