from __future__ import annotations

import time
from dataclasses import asdict, dataclass, field
from typing import Any

from ..errors import ProtocolError, SecurityError


@dataclass(slots=True)
class ExecutionBudget:
    max_tool_calls: int = 20
    max_model_calls: int = 10
    max_revisions: int = 2
    max_elapsed_seconds: float = 600.0
    max_cost_units: float = 100.0
    max_context_bytes: int = 2_000_000
    tool_calls: int = 0
    model_calls: int = 0
    revisions: int = 0
    cost_units: float = 0.0
    context_bytes: int = 0
    started_monotonic: float = field(default_factory=time.monotonic)

    def consume(self, resource: str, amount: float = 1.0) -> None:
        if amount < 0:
            raise ProtocolError("BUDGET_AMOUNT_INVALID", resource)
        if resource == "tool_calls":
            self.tool_calls += int(amount)
            exceeded = self.tool_calls > self.max_tool_calls
        elif resource == "model_calls":
            self.model_calls += int(amount)
            exceeded = self.model_calls > self.max_model_calls
        elif resource == "revisions":
            self.revisions += int(amount)
            exceeded = self.revisions > self.max_revisions
        elif resource == "cost_units":
            self.cost_units += amount
            exceeded = self.cost_units > self.max_cost_units
        elif resource == "context_bytes":
            self.context_bytes += int(amount)
            exceeded = self.context_bytes > self.max_context_bytes
        else:
            raise ProtocolError("BUDGET_RESOURCE_UNKNOWN", resource)
        if exceeded or time.monotonic() - self.started_monotonic > self.max_elapsed_seconds:
            raise ProtocolError("EXECUTION_BUDGET_EXCEEDED", resource)


@dataclass(slots=True)
class ExecutionContext:
    run_id: str
    tenant_id: str
    project_id: str
    subject_id: str
    roles: frozenset[str]
    namespaces: frozenset[str]
    authorized_capabilities: frozenset[str]
    classification: str = "internal"
    environment: str = "local"
    budget: ExecutionBudget = field(default_factory=ExecutionBudget)

    def require_project_scope(self) -> None:
        if self.project_id not in self.namespaces:
            raise SecurityError("PROJECT_SCOPE_DENIED", self.project_id)


@dataclass(frozen=True, slots=True)
class StepReceipt:
    schema_version: int
    receipt_id: str
    run_id: str
    step: str
    attempt: int
    status: str
    input_fingerprint: str
    prerequisite_fingerprints: dict[str, str]
    tool_versions: dict[str, str]
    output_refs: list[dict[str, str]]
    started_at: str
    completed_at: str
    error: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class JobState:
    schema_version: int
    status: str
    step: str
    attempt: int
    run_id: str
    input_fingerprint: str
    last_receipt: str | None = None

    def to_dict(self) -> dict[str, Any]:
        value = asdict(self)
        if self.last_receipt is None:
            value.pop("last_receipt")
        return value
