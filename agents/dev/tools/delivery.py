"""Validate the handoff format; AI check claims still require independent verification."""
import hashlib
from pathlib import Path

from schemas import DeliveryReport

REPORT_NAME = "delivery_report.json"


def source_snapshot(workspace: Path) -> dict[str, str]:
    snapshot = {}
    for file in sorted(workspace.rglob("*")):
        if file.is_symlink():
            raise ValueError("Workspace contains a symlink")
        if file.is_file() and file.relative_to(workspace).as_posix() != REPORT_NAME:
            snapshot[file.relative_to(workspace).as_posix()] = hashlib.sha256(file.read_bytes()).hexdigest()
    return snapshot


def read_report(workspace: Path, action: str, before: dict[str, str]) -> DeliveryReport:
    file = workspace / REPORT_NAME
    if not file.is_file() or file.is_symlink() or file.stat().st_size > 1024 * 1024:
        raise ValueError("Missing or oversized delivery_report.json")
    report = DeliveryReport.model_validate_json(file.read_text(encoding="utf-8"))
    if report.action != action:
        raise ValueError("Report action does not match request")
    if not report.checks:
        raise ValueError("Report must declare checks, including NOT_RUN when unavailable")
    if len({item.id for item in report.acceptance}) != len(report.acceptance):
        raise ValueError("Duplicate acceptance IDs")
    if len({item.id for item in report.findings}) != len(report.findings):
        raise ValueError("Duplicate finding IDs")
    if report.scope_status == "COMPLETE" and action != "review_code":
        if (not report.acceptance or report.unresolved
                or any(item.status != "IMPLEMENTED" for item in report.acceptance)
                or any(item.status == "FAIL" for item in report.checks)):
            raise ValueError("COMPLETE contradicts unfinished acceptance, unresolved work or failed checks")
    if action == "review_code" and (report.changes or source_snapshot(workspace) != before):
        raise ValueError("review_code modified source or references")
    for item in [*report.changes, *report.findings]:
        relative = Path(item.path)
        target = (workspace / relative).resolve()
        if (not relative.parts or relative.is_absolute() or ".." in relative.parts or ":" in item.path
                or not target.is_relative_to(workspace.resolve()) or target.is_symlink()):
            raise ValueError("Unsafe report path")
        if item.path in {REPORT_NAME} or relative.parts[0] == "references":
            raise ValueError("Findings and changes must refer to source")
        if hasattr(item, "line"):
            if not target.is_file() or item.line > len(target.read_text(encoding="utf-8", errors="replace").splitlines()):
                raise ValueError("Finding must cite an existing source line")
        elif not target.is_file() and item.path not in before:
            raise ValueError("Change must refer to an existing or removed source file")
    return report
