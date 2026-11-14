from __future__ import annotations

from pathlib import Path
from typing import Any, Callable, TYPE_CHECKING

from ..canonical import sha256_digest
from ..errors import ProtocolError, SecurityError
from ..repository.delivery_repository import DeliveryRepository
from ..scenario_registry import ScenarioRegistry
from ..schema_registry import SchemaRegistry, load_document
from ..security.approval import ApprovalReceipt, verify_receipt
from datetime import datetime
from ..security.paths import PathGuard
from .approvals import ApprovalGateCoordinator
from ..artifacts import file_digest

if TYPE_CHECKING:
    from ..security.nonce_store import NonceStore

FailureHook = Callable[[str], None]


class MapDeliveryService:
    """Validate G3 and drive the recoverable local delivery transaction."""

    def __init__(self, *, path_guard: PathGuard, project_root: Path, work_root: Path,
                 registry: SchemaRegistry | None = None,
                 nonce_store: "NonceStore | None" = None,
                 trusted_subject_id: str | None = None,
                 trusted_tenant_id: str | None = None,
                 trusted_scope: str | None = None,
                 trusted_environment: str | None = None) -> None:
        self.path_guard = path_guard
        self.project_root = project_root
        self.work_root = work_root
        self.registry = registry or SchemaRegistry()
        self._nonce_store = nonce_store
        self._trusted_subject_id = trusted_subject_id
        self._trusted_tenant_id = trusted_tenant_id
        self._trusted_scope = trusted_scope
        self._trusted_environment = trusted_environment
        self.repository = DeliveryRepository(
            path_guard=path_guard, project_root=project_root, work_root=work_root,
            registry=self.registry,
        )

    def deliver(self, *, request: dict[str, Any], manifest: dict[str, Any],
                manifest_ref: dict[str, str], report: dict[str, Any], approval_path: str | Path,
                approval_key: bytes,
                failure_hook: FailureHook | None = None) -> dict[str, Any]:
        self.validate_inputs(request=request, manifest=manifest, manifest_ref=manifest_ref, report=report)
        self.validate_review(request, manifest, approval_key)
        approval_file = self.path_guard.resolve(approval_path, base_root=self.project_root, must_exist=True)
        approval_value = load_document(approval_file)
        if not isinstance(approval_value, dict):
            raise ProtocolError("DELIVERY_APPROVAL_REQUIRED", "G3 approval must be an object")
        self.registry.validate("approval-receipt", approval_value)
        approval = ApprovalReceipt.from_dict(approval_value)
        coordinator = ApprovalGateCoordinator(
            approval_key,
            nonce_store=self._nonce_store,
            trusted_subject_id=self._trusted_subject_id or request["subject"]["approver_subject_id"],
            trusted_tenant_id=self._trusted_tenant_id or request["subject"]["tenant_id"],
            trusted_scope=self._trusted_scope or request["scope"],
            trusted_environment=self._trusted_environment or request["environment"],
        )
        manifest_digest = sha256_digest(manifest)
        coordinator.require("G3", approval, manifest_digest,
                            run_id=request.get("run_id", approval.receipt_id))
        if failure_hook:
            failure_hook("after-approval-consumed")
        approval_ref = {
            "id": approval.receipt_id,
            "version": "1.0.0",
            "digest": sha256_digest(approval_value),
            "uri": str(approval_file),
        }
        result = self.repository.deliver(
            manifest=manifest, manifest_ref=manifest_ref, approval_ref=approval_ref,
            failure_hook=failure_hook,
        )
        result["approval"] = approval_value
        result["approval_ref"] = approval_ref
        return result

    def validate_review(self, request, manifest, approval_key):
        review = self._load_bound_ref(manifest["review_ref"], "product-review", "PRODUCT_REVIEW_DRIFT")
        if (review["run_id"] != request["run_id"] or review["project_id"] != request["project_id"]
                or review["report_ref"]["digest"] != manifest["validation_report_ref"]["digest"]):
            raise ProtocolError("PRODUCT_REVIEW_BINDING", "Review belongs to another output or run")
        # This verifies a recorded attestation, not a new approval consumption.
        verify_receipt(ApprovalReceipt.from_dict(review["approval"]), approval_key,
                       expected_action="approve-product-review", expected_object_type="validation-report",
                       expected_object_digest=review["report_ref"]["digest"],
                       expected_subject_id=request["subject"]["approver_subject_id"],
                       expected_tenant_id=request["subject"]["tenant_id"], expected_scope=request["scope"],
                       expected_environment=request["environment"],
                       now=datetime.fromisoformat(review["reviewed_at"].replace("Z", "+00:00")))
        return review

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
        profile = ScenarioRegistry(self.registry).for_execution(lock["execution"])
        profile.require_manifest(manifest)
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
