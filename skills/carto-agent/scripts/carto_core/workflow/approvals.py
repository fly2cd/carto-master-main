from __future__ import annotations

from dataclasses import dataclass

from ..security.approval import ApprovalReceipt, NonceStore, verify_receipt
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
}


class ApprovalGateCoordinator:
    def __init__(self, key: bytes, nonce_store: NonceStore, policy_id: str, issuer: str) -> None:
        self.key = key
        self.nonce_store = nonce_store
        self.policy_id = policy_id
        self.issuer = issuer

    def require(self, gate_id: str, receipt: ApprovalReceipt, object_digest: str, context: ExecutionContext) -> None:
        gate = GATES[gate_id]
        verify_receipt(receipt, self.key, self.nonce_store, expected_action=gate.action, expected_object_digest=object_digest, expected_scope=f"project:{context.project_id}", expected_policy_id=self.policy_id, expected_tenant_id=context.tenant_id, expected_issuer=self.issuer, expected_subject_id=receipt.subject_id, expected_object_type=gate.object_type, expected_environment=context.environment)
