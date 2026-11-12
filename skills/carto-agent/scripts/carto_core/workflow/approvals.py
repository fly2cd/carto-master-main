from __future__ import annotations

from dataclasses import dataclass

from ..security.approval import ApprovalReceipt, verify_receipt


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
    def __init__(self, key: bytes) -> None:
        self.key = key

    def require(
        self,
        gate_id: str,
        receipt: ApprovalReceipt,
        object_digest: str,
    ) -> None:
        gate = GATES[gate_id]
        verify_receipt(
            receipt,
            self.key,
            expected_action=gate.action,
            expected_object_digest=object_digest,
        )