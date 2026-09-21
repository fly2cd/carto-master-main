from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

from ..canonical import sha256_digest
from ..errors import ProtocolError, SecurityError
from ..repository.delivery_repository import DeliveryRepository
from ..schema_registry import SchemaRegistry, load_document
from ..security.approval import ApprovalReceipt, SqliteNonceStore
from ..security.paths import PathGuard
from .approvals import ApprovalGateCoordinator
from .map_data_preparation import atomic_yaml, file_digest
from .models import ExecutionContext

FailureHook = Callable[[str], None]


class MapDeliveryService:
    """Validate G3 and drive the recoverable local delivery transaction."""

    def __init__(self, *, path_guard: PathGuard, project_root: Path, work_root: Path,
                 registry: SchemaRegistry | None = None) -> None:
        self.path_guard = path_guard
        self.project_root = project_root
        self.work_root = work_root
        self.registry = registry or SchemaRegistry()
        self.repository = DeliveryRepository(
            path_guard=path_guard, project_root=project_root, work_root=work_root,
            registry=self.registry,
        )

    def deliver(self, *, request: dict[str, Any], manifest: dict[str, Any],
                manifest_ref: dict[str, str], report: dict[str, Any], approval_path: str | Path,
                approval_key: bytes, nonce_db: str | Path, policy_id: str, issuer: str,
                failure_hook: FailureHook | None = None) -> dict[str, Any]:
        self.validate_inputs(request=request, manifest=manifest, manifest_ref=manifest_ref, report=report)
        approval_file = self.path_guard.resolve(approval_path, base_root=self.project_root, must_exist=True)
        approval_value = load_document(approval_file)
        if not isinstance(approval_value, dict):
            raise ProtocolError("DELIVERY_APPROVAL_REQUIRED", "G3 approval must be an object")
        self.registry.validate("approval-receipt", approval_value)
        approval = ApprovalReceipt.from_dict(approval_value)
        approval_target = self.path_guard.resolve(
            self.work_root / "approvals" / "g3" / f"{manifest['manifest_id']}.yaml"
        )
        journal_exists = approval_target.exists()
        context = ExecutionContext(
            run_id=request["run_id"], tenant_id=request["subject"]["tenant_id"],
            project_id=request["project_id"], subject_id=request["subject"]["subject_id"],
            roles=frozenset({"operator"}), namespaces=frozenset({request["project_id"]}),
            authorized_capabilities=frozenset(request["allowed_capabilities"]),
            environment=request["environment"],
        )
        nonce_path = self.path_guard.resolve(nonce_db, base_root=self.project_root)
        nonce_path.parent.mkdir(parents=True, exist_ok=True)
        nonce_store = SqliteNonceStore(str(nonce_path))
        coordinator = ApprovalGateCoordinator(approval_key, nonce_store, policy_id, issuer)
        manifest_digest = sha256_digest(manifest)
        coordinator.validate(
            "G3", approval, manifest_digest, context,
            approver_subject_id=request["subject"]["approver_subject_id"],
            expected_scope=request["scope"],
        )
        already_consumed = nonce_store.contains(approval.issuer, approval.nonce)
        if already_consumed:
            if not journal_exists:
                raise SecurityError(
                    "APPROVAL_RECOVERY_EVIDENCE_MISSING",
                    "Consumed G3 approval has no workflow-local intent record",
                )
            retained = load_document(approval_target)
            if retained != approval_value:
                raise SecurityError("APPROVAL_RECOVERY_EVIDENCE_CONFLICT", manifest["manifest_id"])
            coordinator.require_consumed(
                "G3", approval, manifest_digest, context,
                approver_subject_id=request["subject"]["approver_subject_id"],
                expected_scope=request["scope"],
            )
        else:
            if approval_target.exists():
                retained = load_document(approval_target)
                if retained != approval_value:
                    raise SecurityError("APPROVAL_RECOVERY_EVIDENCE_CONFLICT", manifest["manifest_id"])
            atomic_yaml(approval_target, approval_value)
            coordinator.require(
                "G3", approval, manifest_digest, context,
                approver_subject_id=request["subject"]["approver_subject_id"],
                expected_scope=request["scope"],
            )
        if failure_hook:
            failure_hook("after-approval-consumed")
        approval_ref = {
            "id": approval.receipt_id,
            "version": "1.0.0",
            "digest": sha256_digest(approval_value),
            "uri": str(approval_target),
        }
        result = self.repository.deliver(
            manifest=manifest, manifest_ref=manifest_ref, approval_ref=approval_ref,
            failure_hook=failure_hook,
        )
        result["approval"] = approval_value
        result["approval_ref"] = approval_ref
        result["approval_replay"] = already_consumed
        return result

    def validate_inputs(self, *, request: dict[str, Any], manifest: dict[str, Any],
                        manifest_ref: dict[str, str], report: dict[str, Any]) -> None:
        self.registry.validate("delivery-manifest", manifest)
        self.registry.validate("validation-report", report)
        if manifest_ref.get("digest") != sha256_digest(manifest):
            raise ProtocolError("DELIVERY_MANIFEST_REFERENCE_MISMATCH", manifest["manifest_id"])
        expected = (
            request["project_id"], request["run_id"], request["subject"]["tenant_id"],
            request["scope"], request["environment"],
        )
        actual = (
            manifest["project_id"], manifest["run_id"], manifest["tenant_id"],
            manifest["scope"], manifest["environment"],
        )
        if actual != expected:
            raise ProtocolError("DELIVERY_MANIFEST_SCOPE_MISMATCH", manifest["manifest_id"])
        if report["status"] != "passed" or manifest["validation_report_ref"]["digest"] != sha256_digest(report):
            raise ProtocolError("DELIVERY_VALIDATION_REPORT_INVALID", manifest["manifest_id"])
        if manifest["validation_report_ref"].get("uri"):
            report_path = self.path_guard.resolve(manifest["validation_report_ref"]["uri"], must_exist=True)
            if load_document(report_path) != report:
                raise ProtocolError("DELIVERY_VALIDATION_REPORT_DRIFT", report["report_id"])
        lock = self._load_bound_ref(manifest["lock_ref"], "map-spec-lock", "DELIVERY_LOCK_DRIFT")
        attempt = self._load_bound_ref(
            manifest["render_attempt_ref"], "render-attempt", "DELIVERY_RENDER_ATTEMPT_DRIFT"
        )
        if (
            manifest["lock_digest"] != sha256_digest(lock)
            or manifest["execution_digest"] != lock["execution_digest"]
            or lock["project_id"] != request["project_id"]
            or lock["run_id"] != request["run_id"]
        ):
            raise ProtocolError("DELIVERY_LOCK_BINDING_MISMATCH", manifest["manifest_id"])
        if (
            attempt["project_id"] != request["project_id"]
            or attempt["run_id"] != request["run_id"]
            or attempt["lock_digest"] != manifest["lock_digest"]
            or attempt["business_execution_digest"] != manifest["execution_digest"]
            or attempt["renderer_execution_digest"] != manifest["renderer_execution_digest"]
            or attempt["status"] != "succeeded"
        ):
            raise ProtocolError("DELIVERY_RENDER_BINDING_MISMATCH", manifest["manifest_id"])
        checked = {
            item["target"]: (
                item["artifact_ref"]["digest"], item["size_bytes"], item["artifact_ref"].get("uri")
            )
            for item in report.get("checked_artifacts", [])
        }
        declared = {
            item["format"]: (item["digest"], item["size_bytes"], str(
                self.path_guard.resolve(item["path"], base_root=self.project_root)
            ))
            for item in manifest["artifacts"]
        }
        if checked != declared:
            raise ProtocolError("DELIVERY_REPORT_ARTIFACT_MISMATCH", manifest["manifest_id"])
        if {item["format"] for item in manifest["artifacts"]} != {"pdf", "png"}:
            raise ProtocolError("DELIVERY_ARTIFACT_SET_INVALID", manifest["manifest_id"])
        for item in manifest["artifacts"]:
            path = self.path_guard.resolve(item["path"], base_root=self.project_root, must_exist=True)
            try:
                path.relative_to(self.project_root)
            except ValueError as exc:
                raise SecurityError("DELIVERY_ARTIFACT_OUTSIDE_PROJECT", str(path)) from exc
            if not path.is_file() or path.is_symlink():
                raise SecurityError("DELIVERY_ARTIFACT_INVALID", str(path))
            if file_digest(path) != item["digest"] or path.stat().st_size != item["size_bytes"]:
                raise ProtocolError("DELIVERY_ARTIFACT_DRIFT", item["path"])
        destination = self.path_guard.resolve(
            manifest["destination"]["relative_path"], base_root=self.project_root
        )
        try:
            destination.relative_to(self.project_root)
        except ValueError as exc:
            raise SecurityError("DELIVERY_DESTINATION_OUTSIDE_PROJECT", str(destination)) from exc

    def _load_bound_ref(self, ref: dict[str, Any], schema: str, error_code: str) -> dict[str, Any]:
        uri = ref.get("uri")
        if not uri:
            raise ProtocolError(error_code, ref["id"])
        path = self.path_guard.resolve(uri, must_exist=True)
        value = load_document(path)
        if not isinstance(value, dict):
            raise ProtocolError(error_code, ref["id"])
        self.registry.validate(schema, value)
        if sha256_digest(value) != ref["digest"]:
            raise ProtocolError(error_code, ref["id"])
        return value
