from typing import Any, Literal
from pydantic import BaseModel, Field, ConfigDict


class EchoOutput(BaseModel):
    """Schema đầu ra riêng của action mẫu 'echo' phục vụ demo và kiểm thử."""

    received_instruction: str
    received_action: str
    received_context: dict[str, Any] = Field(default_factory=dict)
    reply: str


class ReportItem(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class AcceptanceEvidence(ReportItem):
    id: str = Field(min_length=1)
    status: Literal["IMPLEMENTED", "PARTIAL", "NOT_IMPLEMENTED", "UNVERIFIED"]
    evidence: str = Field(min_length=1)


class CodeChange(ReportItem):
    path: str = Field(min_length=1)
    summary: str = Field(min_length=1)
    finding_id: str | None = None


class CheckEvidence(ReportItem):
    command: str = Field(min_length=1)
    status: Literal["PASS", "FAIL", "NOT_RUN"]
    evidence: str = Field(min_length=1)


class ReviewFinding(ReportItem):
    id: str = Field(min_length=1)
    severity: Literal["LOW", "MEDIUM", "HIGH", "CRITICAL"]
    path: str = Field(min_length=1)
    line: int = Field(ge=1)
    detail: str = Field(min_length=1)
    recommendation: str = Field(min_length=1)


class DeliveryReport(ReportItem):
    schema_version: Literal["1.0"] = "1.0"
    action: Literal["implement_project", "fix_bugs", "review_code", "refactor_code"]
    scope_status: Literal["COMPLETE", "PARTIAL", "NEEDS_CONTEXT"]
    summary: str = Field(min_length=1)
    acceptance: list[AcceptanceEvidence]
    changes: list[CodeChange]
    checks: list[CheckEvidence]
    findings: list[ReviewFinding]
    unresolved: list[str]
