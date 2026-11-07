from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from typing import Any, Callable

from ..artifacts import utc_now
from ..canonical import sha256_digest
from ..errors import ProtocolError
from ..schema_registry import SchemaRegistry, load_document
from .models import CheckResult, ValidationReport

Checker = Callable[[Any, dict[str, Any]],
                   tuple[bool, dict[str, Any]] | tuple[bool, dict[str, Any], str | None]]
DEFAULT_POLICY = Path(__file__).resolve().parents[3] / "policies" / "checker-registry.yaml"


class CheckerRegistry:
    """One definition/result/dispatch path; callers retain phase-specific orchestration."""

    def __init__(self, policy_path: Path | None = None, schema_registry: SchemaRegistry | None = None) -> None:
        policy = load_document(policy_path or DEFAULT_POLICY)
        if not isinstance(policy, dict) or policy.get("unknown_checker") != "reject":
            raise ProtocolError("CHECKER_REGISTRY_INVALID", "A closed checker policy is required")
        self.version = str(policy["version"])
        self.policy_digest = sha256_digest(policy)
        self._definitions: dict[str, dict[str, Any]] = {}
        for item in policy["checks"]:
            if item["id"] in self._definitions:
                raise ProtocolError("CHECKER_DUPLICATE", item["id"])
            self._definitions[item["id"]] = item
        self._handlers: dict[str, Checker] = {}
        self._schemas = schema_registry or SchemaRegistry()

    def definition(self, check_id: str) -> dict[str, Any]:
        if check_id not in self._definitions:
            raise ProtocolError("CHECKER_UNREGISTERED", check_id)
        return deepcopy(self._definitions[check_id])

    def definitions(self, phase: str) -> list[dict[str, Any]]:
        return [deepcopy(item) for item in self._definitions.values() if item["phase"] == phase]

    def phase_digest(self, phase: str) -> str:
        return sha256_digest({"registry": self.policy_digest, "checks": self.definitions(phase)})

    def register(self, check_id: str, handler: Checker) -> None:
        self.definition(check_id)
        self._handlers[check_id] = handler

    def require_handlers(self, check_ids: tuple[str, ...]) -> None:
        for check_id in check_ids:
            self.definition(check_id)
            if check_id not in self._handlers:
                raise ProtocolError("CHECKER_NOT_AVAILABLE", check_id)

    def resolve_quality_gates(self, document: dict[str, Any], *, required: tuple[str, ...] = ()) -> tuple[str, ...]:
        """Templates may add supported checks, never remove mandatory checks or tune severity.

        Current implementations are parameterless. Reject, rather than ignore, any
        parameter until an implementation and a parameter contract are registered.
        """
        self._schemas.validate("quality-gates", document)
        selected = list(required)
        seen: set[str] = set()
        for item in document["checks"]:
            check_id = item["id"]
            definition = self.definition(check_id)
            if check_id in seen:
                raise ProtocolError("CHECKER_DUPLICATE", check_id)
            seen.add(check_id)
            if item["version"] != str(definition["version"]):
                raise ProtocolError("CHECKER_VERSION_MISMATCH", check_id)
            if definition["phase"] not in {"validate", "candidate-check"}:
                raise ProtocolError("CHECKER_PHASE_UNSUPPORTED", check_id)
            if item["params"]:
                raise ProtocolError("CHECKER_PARAMS_UNSUPPORTED", check_id)
            if check_id not in selected:
                selected.append(check_id)
        for check_id in selected:
            self.definition(check_id)
        return tuple(selected)

    def result(self, check_id: str, passed: bool, details: dict[str, Any],
               disposition: str | None = None) -> CheckResult:
        definition = self.definition(check_id)
        severity = definition["failure_severity"]
        if severity == "warning":
            disposition = disposition or ("accepted" if passed else "blocked")
        else:
            disposition = None
        return CheckResult(check_id, str(definition["version"]), "passed" if passed else "failed",
                           severity, details, disposition)

    def evaluate(self, check_id: str, subject: Any, context: dict[str, Any] | None = None) -> CheckResult:
        self.require_handlers((check_id,))
        outcome = self._handlers[check_id](subject, context if context is not None else {})
        return self.result(check_id, *outcome)

    @staticmethod
    def has_blocking_failure(results: list[dict[str, Any]]) -> bool:
        return any((item["status"] == "failed" and item["severity"] in {"blocker", "error"})
                   or (item["severity"] == "warning" and item.get("disposition") != "accepted")
                   for item in results)

    def run(self, phase: str, subject: Any, context: dict[str, Any] | None = None) -> ValidationReport:
        results = [self.evaluate(item["id"], subject, context) for item in self.definitions(phase)]
        failed = self.has_blocking_failure([item.to_dict() for item in results])
        digest = sha256_digest(subject)
        report = ValidationReport(1, f"report-{digest[7:23]}", phase, digest,
                                  "failed" if failed else "passed", results, utc_now())
        self._schemas.validate("validation-report", report.to_dict())
        return report
