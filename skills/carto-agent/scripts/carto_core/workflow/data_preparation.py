from __future__ import annotations

from pathlib import Path
from typing import Any

from ..canonical import sha256_digest
from ..errors import ProtocolError, SecurityError
from ..schema_registry import SchemaRegistry, load_document
from .models import ExecutionContext


class DeterministicDataPreparer:
    def __init__(self, policy_path: Path, registry: SchemaRegistry | None = None) -> None:
        policy = load_document(policy_path)
        if policy["default_mode"] != "deterministic" or policy["data_agent"]["enabled"]:
            raise SecurityError("DATA_PREPARATION_POLICY_UNSAFE", str(policy_path))
        self.policy_version = str(policy["version"])
        self.allowed_operations = frozenset(policy["allowed_operations"])
        self.forbidden_operations = frozenset(policy["forbidden_operations"])
        self.registry = registry or SchemaRegistry()

    def prepare_data(self, approved_requirements: dict[str, Any], execution_context: ExecutionContext) -> dict[str, Any]:
        execution_context.require_project_scope()
        self.registry.validate("data-preparation-task", approved_requirements)
        operations = set(approved_requirements["allowed_operations"])
        if operations & self.forbidden_operations or not operations <= self.allowed_operations:
            raise SecurityError("DATA_OPERATION_DENIED", ",".join(sorted(operations - self.allowed_operations)))
        datasets = list(approved_requirements["allowed_sources"])
        transformations = [{"id": f"transform-{index + 1}", "version": "1.0.0", "digest": sha256_digest({"operation": operation, "task": approved_requirements["task_id"]})} for index, operation in enumerate(sorted(operations))]
        evidence = {"id": "data-acceptance", "version": self.policy_version, "digest": sha256_digest({"checks": approved_requirements["acceptance_checks"], "datasets": datasets})}
        body = {"schema_version": 1, "bundle_id": f"bundle-{approved_requirements['task_id']}", "task_ref": {"id": approved_requirements["task_id"], "version": "1.0.0", "digest": sha256_digest(approved_requirements)}, "datasets": datasets, "transformations": transformations, "tool_receipts": [], "quality_evidence": [evidence], "open_issues": []}
        body["digest"] = sha256_digest(body)
        self.registry.validate("prepared-data-bundle", body)
        return body
