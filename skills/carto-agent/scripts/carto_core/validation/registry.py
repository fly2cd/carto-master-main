from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Callable

from ..canonical import sha256_digest
from ..errors import ProtocolError
from ..schema_registry import SchemaRegistry, load_document
from .models import CheckResult, ValidationReport

Checker = Callable[[Any, dict[str, Any]], tuple[bool, dict[str, Any]]]


class CheckerRegistry:
    def __init__(self, policy_path: Path, schema_registry: SchemaRegistry | None = None) -> None:
        policy = load_document(policy_path)
        self.version = str(policy["version"])
        self._definitions = {item["id"]: item for item in policy["checks"]}
        self._handlers: dict[str, Checker] = {}
        self._schemas = schema_registry or SchemaRegistry()

    def register(self, check_id: str, handler: Checker) -> None:
        if check_id not in self._definitions:
            raise ProtocolError("CHECKER_UNREGISTERED", check_id)
        self._handlers[check_id] = handler

    def run(self, phase: str, subject: Any, context: dict[str, Any] | None = None) -> ValidationReport:
        results: list[CheckResult] = []
        for check_id, definition in self._definitions.items():
            if definition["phase"] != phase:
                continue
            handler = self._handlers.get(check_id)
            if handler is None:
                raise ProtocolError("CHECKER_NOT_AVAILABLE", check_id)
            passed, details = handler(subject, context or {})
            results.append(CheckResult(check_id, str(definition["version"]), "passed" if passed else "failed", definition["failure_severity"], details))
        failed = any(item.status == "failed" and item.severity in {"blocker", "error"} for item in results)
        digest = sha256_digest(subject)
        report = ValidationReport(1, f"report-{digest[7:23]}", phase, digest, "failed" if failed else "passed", results, datetime.now(UTC).isoformat().replace("+00:00", "Z"))
        self._schemas.validate("validation-report", report.to_dict())
        return report
