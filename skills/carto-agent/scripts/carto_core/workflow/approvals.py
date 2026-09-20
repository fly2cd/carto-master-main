from __future__ import annotations

from dataclasses import dataclass

from ..security.approval import (
    ApprovalReceipt,
    NonceStore,
    verify_consumed_receipt,
    verify_receipt,
    verify_receipt_claims,
)
from .models import ExecutionContext


@dataclass(frozen=True, slots=True)
class GateDefinition:
    gate_id: str
    action: str
    object_type: str


GATES = {
    "G1": GateDefinition("G1", "approve-map-brief", "map-brief"),
    "G2": GateDefinition("G2", "approve-freeze", "resolved-map"),
    "G3": GateDefinition("G3", "approve-delivery", "delivery-manifest"),
    "T1": GateDefinition("T1", "approve-template-brief", "template-brief"),
    "TP": GateDefinition("TP", "approve-template-publish", "template-publication"),
}


class ApprovalGateCoordinator:
    def __init__(self, key: bytes, nonce_store: NonceStore, policy_id: str, issuer: str) -> None:
        self.key = key
        self.nonce_store = nonce_store
        self.policy_id = policy_id
        self.issuer = issuer

    def require(
        self,
        gate_id: str,
        receipt: ApprovalReceipt,
        object_digest: str,
        context: ExecutionContext,
        *,
        approver_subject_id: str | None = None,
        expected_scope: str | None = None,
    ) -> None:
        gate = GATES[gate_id]
        verify_receipt(
            receipt,
            self.key,
            self.nonce_store,
            expected_action=gate.action,
            expected_object_digest=object_digest,
            expected_scope=expected_scope or f"project:{context.project_id}",
            expected_policy_id=self.policy_id,
            expected_tenant_id=context.tenant_id,
            expected_issuer=self.issuer,
            expected_subject_id=approver_subject_id or receipt.subject_id,
            expected_object_type=gate.object_type,
            expected_environment=context.environment,
        )

    def validate(
        self,
        gate_id: str,
        receipt: ApprovalReceipt,
        object_digest: str,
        context: ExecutionContext,
        *,
        approver_subject_id: str | None = None,
        expected_scope: str | None = None,
    ) -> None:
        """Validate approval claims before recording a workflow-local recovery intent."""
        gate = GATES[gate_id]
        verify_receipt_claims(
            receipt,
            self.key,
            expected_action=gate.action,
            expected_object_digest=object_digest,
            expected_scope=expected_scope or f"project:{context.project_id}",
            expected_policy_id=self.policy_id,
            expected_tenant_id=context.tenant_id,
            expected_issuer=self.issuer,
            expected_subject_id=approver_subject_id or receipt.subject_id,
            expected_object_type=gate.object_type,
            expected_environment=context.environment,
        )

    def require_consumed(
        self,
        gate_id: str,
        receipt: ApprovalReceipt,
        object_digest: str,
        context: ExecutionContext,
        *,
        approver_subject_id: str | None = None,
        expected_scope: str | None = None,
    ) -> None:
        """Validate a prior approval without consuming its nonce a second time."""
        gate = GATES[gate_id]
        verify_consumed_receipt(
            receipt,
            self.key,
            self.nonce_store,
            expected_action=gate.action,
            expected_object_digest=object_digest,
            expected_scope=expected_scope or f"project:{context.project_id}",
            expected_policy_id=self.policy_id,
            expected_tenant_id=context.tenant_id,
            expected_issuer=self.issuer,
            expected_subject_id=approver_subject_id or receipt.subject_id,
            expected_object_type=gate.object_type,
            expected_environment=context.environment,
        )
