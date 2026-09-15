from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from ..errors import ProtocolError, SecurityError
from ..schema_registry import SchemaRegistry
from ..security.sensitive import redact_for_log
from .models import ExecutionContext


FORBIDDEN_FIELDS = {"sql", "shell", "command", "python", "python_code", "gis_expression"}
FORBIDDEN_SNIPPETS = ("select ", "insert ", "delete ", "subprocess", "os.system", "eval(", "exec(")
ROLE_SCHEMAS = {"planner": {"map-plan"}, "composer": {"resolved-map"}}


@dataclass(frozen=True, slots=True)
class AgentSubmission:
    role: str
    schema_name: str
    candidate: dict[str, Any]
    configuration_version: str
    estimated_cost_units: float = 1.0


class BoundedAgentRuntime:
    """Accepts typed candidates only; it never executes generated code or expressions."""

    def __init__(self, registry: SchemaRegistry | None = None) -> None:
        self.registry = registry or SchemaRegistry()

    def submit(self, submission: AgentSubmission, context: ExecutionContext) -> dict[str, Any]:
        allowed = ROLE_SCHEMAS.get(submission.role)
        if allowed is None or submission.schema_name not in allowed:
            raise SecurityError("AGENT_ROLE_SCHEMA_DENIED", f"{submission.role}:{submission.schema_name}")
        self._reject_executable_content(submission.candidate)
        context.budget.consume("model_calls")
        context.budget.consume("cost_units", submission.estimated_cost_units)
        context.budget.consume("context_bytes", len(json.dumps(submission.candidate, ensure_ascii=False).encode("utf-8")))
        self.registry.validate(submission.schema_name, submission.candidate)
        return {"accepted": True, "role": submission.role, "schema": submission.schema_name, "configuration_version": submission.configuration_version, "candidate": submission.candidate}

    @staticmethod
    def repair(context: ExecutionContext) -> None:
        context.budget.consume("revisions")

    @staticmethod
    def stage_context(role: str, value: dict[str, Any]) -> dict[str, Any]:
        allowed = {"planner": {"intent", "brief", "templates", "evidence", "data_summary"}, "composer": {"plan", "prepared_data", "templates", "validation"}}
        if role not in allowed:
            raise ProtocolError("AGENT_ROLE_UNKNOWN", role)
        return redact_for_log({key: value[key] for key in allowed[role] if key in value})

    @classmethod
    def _reject_executable_content(cls, value: Any) -> None:
        if isinstance(value, dict):
            for key, item in value.items():
                if str(key).casefold().replace("-", "_") in FORBIDDEN_FIELDS:
                    raise SecurityError("MODEL_EXECUTABLE_CONTENT_DENIED", str(key))
                cls._reject_executable_content(item)
        elif isinstance(value, list):
            for item in value:
                cls._reject_executable_content(item)
        elif isinstance(value, str):
            lowered = value.casefold()
            if any(snippet in lowered for snippet in FORBIDDEN_SNIPPETS):
                raise SecurityError("MODEL_EXECUTABLE_CONTENT_DENIED", "string-content")
