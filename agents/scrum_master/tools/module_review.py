"""Review the evidence PM supplied for one module; never execute source code."""
import json
from pathlib import Path

from agent_contract.enums import ArtifactType
from tools.history import normalize_tasks


def _inbox_file(artifact, artifact_dir: str) -> Path | None:
    root = Path(artifact_dir).resolve()
    # Only read files inside this agent. Input artifact presence/checksums are
    # also checked by BaseAgent before dispatching the action.
    for candidate in [root / "inbox" / artifact.created_by / Path(artifact.name).name,
                      root / "inbox" / Path(artifact.name).name,
                      root / artifact.name,
                      root.parent / artifact.uri]:
        resolved = candidate.resolve()
        if resolved.is_relative_to(root) and resolved.is_file():
            return resolved
    return None


def build_module_review(request, artifact_dir: str) -> tuple[str, dict]:
    context = request.context
    module_id = context.get("module_id")
    if module_id is not None and (not isinstance(module_id, str) or not module_id.strip()):
        raise ValueError("module_id phải là chuỗi không rỗng")
    module_id = module_id.strip() if module_id else None
    tasks = normalize_tasks(context)
    if module_id and any(task.get("module_id") not in (None, module_id) for task in context.get("tasks", [])):
        raise ValueError("Snapshot chứa task thuộc module khác")
    criteria = context.get("acceptance_criteria", [])
    if not isinstance(criteria, list):
        raise ValueError("acceptance_criteria phải là danh sách")
    normalized, ids = [], set()
    for item in criteria:
        if not isinstance(item, dict):
            raise ValueError("Mỗi tiêu chí nghiệm thu phải là object")
        criterion_id = item.get("id")
        if not isinstance(criterion_id, str) or not criterion_id.strip() or criterion_id in ids:
            raise ValueError("Tiêu chí cần ID không rỗng và không trùng")
        status = item.get("status", "UNVERIFIED")
        evidence = item.get("evidence", "")
        if status not in ("PASS", "FAIL", "UNVERIFIED") or not isinstance(evidence, str):
            raise ValueError("Tiêu chí cần status PASS/FAIL/UNVERIFIED và evidence dạng chuỗi")
        ids.add(criterion_id)
        normalized.append({"id": criterion_id, "description": str(item.get("description", "")),
                           "status": status, "evidence": evidence.strip()})
    missing = []
    if not module_id:
        missing.append("context.module_id")
    if not tasks:
        missing.append("context.tasks của module")
    if not normalized:
        missing.append("context.acceptance_criteria")
    for item in normalized:
        if item["status"] == "UNVERIFIED" or not item["evidence"]:
            missing.append(f"Bằng chứng nghiệm thu {item['id']}")

    sources = [art for art in request.input_artifacts if art.type == ArtifactType.SOURCE_CODE and art.name.lower().endswith(".zip")]
    reports = [art for art in request.input_artifacts if art.type == ArtifactType.TEST_REPORT]
    if len(sources) != 1:
        missing.append("Đúng một artifact SOURCE_CODE ZIP hiện tại của module")
    if len(reports) != 1:
        missing.append("Đúng một artifact TEST_REPORT của module")
    test_result = None
    if len(reports) == 1:
        ref = reports[0]
        path = _inbox_file(ref, artifact_dir)
        if path is None:
            missing.append(f"Nội dung TEST_REPORT {ref.artifact_id} trong inbox")
        elif path.stat().st_size > 2 * 1024 * 1024:
            missing.append("TEST_REPORT vượt giới hạn đọc 2 MB")
        else:
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
            except (ValueError, UnicodeError):
                payload = None
            if isinstance(payload, dict) and payload.get("verdict") in ("PASS", "FAIL"):
                findings = payload.get("findings", [])
                if not isinstance(findings, list) or not all(isinstance(item, dict) for item in findings):
                    raise ValueError("findings trong TEST_REPORT phải là danh sách object")
                test_result = {"artifact_id": ref.artifact_id, "verdict": payload["verdict"],
                               "findings": findings, "evidence_source": "test_report_artifact"}
            else:
                # Markdown/text reports can be accompanied by a result explicitly
                # supplied by PM and bound to the exact relayed report artifact.
                supplied = context.get("test_result")
                if (isinstance(supplied, dict) and supplied.get("artifact_id") == ref.artifact_id
                        and supplied.get("verdict") in ("PASS", "FAIL")
                        and isinstance(supplied.get("evidence"), str) and supplied["evidence"].strip()):
                    test_result = {"artifact_id": ref.artifact_id, "verdict": supplied["verdict"],
                                   "findings": [], "evidence": supplied["evidence"],
                                   "evidence_source": "pm_supplied_test_result"}
                else:
                    missing.append("TEST_REPORT JSON có verdict PASS/FAIL, hoặc context.test_result gắn đúng artifact_id kèm evidence")

    blockers = [task for task in tasks if task["status"] in ("BLOCKED", "FAILED") or task["blocked_reason"]]
    unfinished = [task["id"] for task in tasks if task["status"] not in ("DONE", "COMPLETED")]
    failed_criteria = [item["id"] for item in normalized if item["status"] == "FAIL"]
    reasons = []
    if blockers:
        reasons.append("Còn task bị chặn hoặc lỗi: " + ", ".join(task["id"] for task in blockers))
    if unfinished:
        reasons.append("Task chưa hoàn thành: " + ", ".join(unfinished))
    if failed_criteria:
        reasons.append("Tiêu chí chưa đạt: " + ", ".join(failed_criteria))
    if test_result:
        if test_result["verdict"] == "FAIL":
            reasons.append("Kết quả kiểm thử là FAIL")
        if any(str(item.get("severity", "")).upper() in ("HIGH", "CRITICAL") for item in test_result["findings"]):
            reasons.append("Báo cáo kiểm thử còn finding HIGH/CRITICAL")
    verdict = "FAIL" if reasons else "BLOCKED" if missing else "PASS"
    output = {"review_type": "module_review", "module_id": module_id, "verdict": verdict,
              "can_start_next_module": verdict == "PASS", "missing_inputs": missing,
              "reasons": reasons, "acceptance_criteria": normalized, "test_result": test_result,
              "total": len(tasks), "done": sum(task["status"] in ("COMPLETED", "DONE") for task in tasks),
              "blockers": blockers, "unfinished_tasks": unfinished,
              "input_evidence": [{"artifact_id": art.artifact_id, "name": art.name, "type": art.type.value,
                                  "checksum": art.checksum} for art in request.input_artifacts]}
    lines = [f"# Báo cáo review module – {module_id or 'Chưa cung cấp module_id'}", "",
             f"- Dự án: {request.project_id}", f"- Yêu cầu review: {request.task_id}",
             f"- Chỉ dẫn PM: {request.instruction}", f"- Kết luận: {verdict}",
             f"- Đủ điều kiện chuyển module tiếp theo: {'Có' if verdict == 'PASS' else 'Chưa'}", "",
             "## Công việc và blocker", ""]
    lines += [f"- {task['id']}: {task['status']} — {task['blocked_reason'] or 'Không ghi nhận blocker'}" for task in tasks] or ["- Thiếu snapshot công việc của module."]
    lines += ["", "## Tiêu chí nghiệm thu", ""]
    lines += [f"- {item['id']}: {item['status']} — {item['description']} — Bằng chứng: {item['evidence'] or 'Chưa có'}" for item in normalized] or ["- Chưa có tiêu chí nghiệm thu."]
    lines += ["", "## Bằng chứng bàn giao", ""]
    lines += [f"- {art.type.value}: {art.artifact_id} ({art.name})" for art in request.input_artifacts] or ["- Chưa nhận artifact đầu vào."]
    if test_result:
        lines += [f"- Kiểm thử: {test_result['verdict']} ({test_result['evidence_source']})"]
    lines += ["", "## Vấn đề cần PM xử lý trước khi chuyển module", ""]
    lines += [f"- {reason}" for reason in reasons + missing] or ["- Đã đủ điều kiện theo bằng chứng PM cung cấp."]
    lines += ["", "## Phạm vi kết luận", "",
              "Scrum đối chiếu bằng chứng được cung cấp; không chạy source hoặc thay Tester nghiệm thu kỹ thuật.",
              "PASS chỉ áp dụng cho module và snapshot đang review, không phải nghiệm thu toàn bộ dự án.", ""]
    return "\n".join(lines), output
