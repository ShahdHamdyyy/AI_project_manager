from __future__ import annotations

from models.base import StrictModel


class ValidationIssue(StrictModel):
    code: str
    severity: str  # "error" | "warning"
    message: str
    entity_id: str = ""


class ValidationReport(StrictModel):
    stage: str = "final"
    passed: bool = False
    error_count: int = 0
    warning_count: int = 0
    issues: list[ValidationIssue] = []
    checked_revision: int = -1
    semantic_verdict: str = ""
    semantic_notes: list[str] = []

    @property
    def errors(self):
        return [i for i in self.issues if i.severity == "error"]
