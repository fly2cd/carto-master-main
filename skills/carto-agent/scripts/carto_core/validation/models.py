from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any


@dataclass(frozen=True, slots=True)
class CheckResult:
    check_id: str
    version: str
    status: str
    severity: str
    details: dict[str, Any]
    disposition: str | None = None

    def to_dict(self) -> dict[str, Any]:
        value = asdict(self)
        if self.disposition is None:
            value.pop("disposition")
        return value


@dataclass(frozen=True, slots=True)
class ValidationReport:
    schema_version: int
    report_id: str
    phase: str
    subject_digest: str
    status: str
    results: list[CheckResult]
    created_at: str

    def to_dict(self) -> dict[str, Any]:
        value = asdict(self)
        value["results"] = [item.to_dict() for item in self.results]
        return value
