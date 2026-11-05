"""AI advisory for Scrum Master via Google Antigravity CLI (Google AI Pro account).

The official Agent Contract response remains deterministic: AI only adds advisory text.
The module does not execute any AI-proposed instructions or shell commands.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path
from typing import Any

from prompt import build_scrum_review_prompt

REVIEW_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "risks": {"type": "array", "items": {"type": "string"}},
        "recommendations": {"type": "array", "items": {"type": "string"}},
        "message_to_pm": {"type": "string"},
    },
    "required": ["risks", "recommendations", "message_to_pm"],
    "additionalProperties": False,
}


def review_report_with_antigravity(report: str, timeout_seconds: int, workspace: Path,
                                  skill_instructions: str = "") -> dict[str, Any]:
    """Return {used, status, review, reason}; never mark AI used if CLI failed."""
    executable = shutil.which("agy")
    if not executable:
        return {"used": False, "status": "fallback", "review": "", "reason": "agy_not_installed_or_not_on_PATH"}

    workspace.mkdir(parents=True, exist_ok=True)
    prompt = build_scrum_review_prompt(report, skill_instructions)
    argv = [
        executable, "-p", prompt,
        "--output-format", "json",
        "--json-schema", json.dumps(REVIEW_SCHEMA, ensure_ascii=False),
        "--print-timeout", f"{max(15, timeout_seconds)}s",
        "--sandbox",
    ]
    try:
        result = subprocess.run(
            argv,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=max(15, timeout_seconds) + 15,
            cwd=str(workspace),
            check=False,
        )
    except subprocess.TimeoutExpired:
        return {"used": False, "status": "fallback", "review": "", "reason": "ai_timeout"}
    except OSError:
        return {"used": False, "status": "fallback", "review": "", "reason": "cli_launch_failed"}

    if result.returncode != 0:
        return {"used": False, "status": "fallback", "review": "", "reason": "cli_returned_error"}
    try:
        outer = json.loads(result.stdout)
        if not isinstance(outer, dict):
            raise ValueError("CLI envelope must be an object")
        if outer.get("status") != "SUCCESS":
            return {"used": False, "status": "fallback", "review": "", "reason": "ai_not_successful"}
        structured = outer.get("structured_output")
        if not isinstance(structured, dict):
            structured = json.loads(outer.get("response", "{}"))
        if not isinstance(structured, dict):
            raise ValueError("Not an object")
        risks = structured.get("risks")
        recs = structured.get("recommendations")
        message = structured.get("message_to_pm")
        if not isinstance(risks, list) or not isinstance(recs, list) or not isinstance(message, str):
            raise ValueError("Invalid structure")
        if not all(isinstance(x, str) for x in risks + recs):
            raise ValueError("Invalid array items")
        body = ["## Nhận xét của AI Scrum Master", "", "### Rủi ro"]
        body += [f"- {x[:400]}" for x in risks[:5]] or ["- Không phát hiện thêm rủi ro có căn cứ."]
        body += ["", "### Đề xuất cho PM"]
        body += [f"- {x[:400]}" for x in recs[:5]] or ["- Tiếp tục theo dõi trạng thái và bằng chứng kiểm thử."]
        body += ["", "### Thông điệp gửi PM", "", message[:1200], ""]
        return {"used": True, "status": "success", "review": "\n".join(body), "reason": ""}
    except (json.JSONDecodeError, ValueError, TypeError):
        return {"used": False, "status": "fallback", "review": "", "reason": "invalid_ai_json"}
