from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from ..canonical import sha256_digest
from ..errors import ProtocolError, SecurityError
from ..repository.immutable_store import ImmutableArtifactStore
from ..schema_registry import SchemaRegistry, load_document
from ..workflow.models import ExecutionContext
from .contracts import CapabilityHandler


@dataclass(frozen=True, slots=True)
class ToolResult:
    schema_version: int
    invocation_id: str
    capability_id: str
    binding_version: str
    status: str
    input_digest: str
    output_digest: str
    artifact_refs: list[dict[str, str]]
    started_at: str
    completed_at: str
    error: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        value = asdict(self)
        if self.error is None:
            value.pop("error")
        return value


class ToolGateway:
    def __init__(self, policy_path: Path, artifact_store: ImmutableArtifactStore, registry: SchemaRegistry | None = None) -> None:
        policy = load_document(policy_path)
        if policy.get("default") != "deny" or policy.get("unregistered_capability") != "reject":
            raise SecurityError("TOOL_POLICY_NOT_DENY_BY_DEFAULT", str(policy_path))
        self.policy_version = str(policy["version"])
        self._bindings = {item["capability_id"]: item for item in policy["bindings"]}
        self._handlers: dict[str, tuple[CapabilityHandler, str | None, str | None]] = {}
        self._store = artifact_store
        self._registry = registry or SchemaRegistry()

    def register(self, capability_id: str, handler: CapabilityHandler, *, input_schema: str | None = None, output_schema: str | None = None) -> None:
        if capability_id not in self._bindings:
            raise SecurityError("CAPABILITY_UNREGISTERED", capability_id)
        if capability_id in self._handlers:
            raise ProtocolError("CAPABILITY_HANDLER_DUPLICATE", capability_id)
        self._handlers[capability_id] = (handler, input_schema, output_schema)

    def invoke(self, capability_id: str, typed_input: dict[str, Any], execution_context: ExecutionContext) -> ToolResult:
        binding = self._bindings.get(capability_id)
        if binding is None:
            raise SecurityError("CAPABILITY_UNREGISTERED", capability_id)
        execution_context.require_project_scope()
        if capability_id not in execution_context.authorized_capabilities:
            raise SecurityError("CAPABILITY_SCOPE_DENIED", capability_id)
        handler_record = self._handlers.get(capability_id)
        if handler_record is None:
            raise ProtocolError("CAPABILITY_NOT_AVAILABLE", capability_id)
        execution_context.budget.consume("tool_calls")
        handler, input_schema, output_schema = handler_record
        if input_schema:
            self._registry.validate(input_schema, typed_input)
        input_digest = sha256_digest(typed_input)
        timestamp = datetime.now(UTC).isoformat().replace("+00:00", "Z")
        output = handler(typed_input, execution_context)
        if not isinstance(output, dict):
            raise ProtocolError("TOOL_OUTPUT_NOT_TYPED", capability_id)
        if output_schema:
            self._registry.validate(output_schema, output)
        output_digest = sha256_digest(output)
        artifact = self._store.put(f"tool-{capability_id}", "1.0.0", output)
        result = ToolResult(1, f"invocation-{output_digest[7:23]}", capability_id, str(binding["version"]), "succeeded", input_digest, output_digest, [artifact.ref()], timestamp, datetime.now(UTC).isoformat().replace("+00:00", "Z"))
        self._registry.validate("tool-result", result.to_dict())
        return result
