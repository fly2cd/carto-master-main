from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from ..errors import ProtocolError
from ..security.approval import ApprovalReceipt, verify_receipt

if TYPE_CHECKING:
    from ..security.nonce_store import NonceStore


@dataclass(frozen=True, slots=True)
class GateDefinition:
    gate_id: str
    action: str
    object_type: str


GATES = {
    "G1": GateDefinition("G1", "approve-map-brief", "map-brief"),
    "G2": GateDefinition("G2", "approve-freeze", "resolved-map"),
    "G3": GateDefinition("G3", "approve-delivery", "delivery-manifest"),
    "TP": GateDefinition("TP", "approve-template-publish", "template-publication"),
}


class ApprovalGateCoordinator:
    def __init__(
        self,
        key: bytes,
        *,
        nonce_store: NonceStore | None = None,
        trusted_subject_id: str | None = None,
        trusted_tenant_id: str | None = None,
        trusted_scope: str | None = None,
        trusted_environment: str | None = None,
    ) -> None:
        self.key = key
        self._nonce_store = nonce_store
        self._trusted_subject_id = trusted_subject_id
        self._trusted_tenant_id = trusted_tenant_id
        self._trusted_scope = trusted_scope
        self._trusted_environment = trusted_environment

    def require(
        self,
        gate_id: str,
        receipt: ApprovalReceipt,
        object_digest: str,
        *,
        subject_id: str | None = None,
        tenant_id: str | None = None,
        scope: str | None = None,
        run_id: str | None = None,
    ) -> None:
        gate = GATES.get(gate_id)
        if gate is None:
            raise ProtocolError("APPROVAL_GATE_UNKNOWN", f"Unknown approval gate: {gate_id}")

        self.require_attestation(gate.action, gate.object_type, receipt, object_digest,
                                 subject_id=subject_id, tenant_id=tenant_id, scope=scope, run_id=run_id)

    def require_attestation(self, action: str, object_type: str, receipt: ApprovalReceipt,
                            object_digest: str, *, subject_id: str | None = None,
                            tenant_id: str | None = None, scope: str | None = None,
                            run_id: str | None = None) -> None:
        """Verify a typed record without reassigning the meaning of a workflow gate."""
        # R3: use trusted identity from ExecutionContext when available,
        #     falling back to caller-provided values (which should NOT be
        #     the receipt's own fields — that creates a tautology).
        check_subject = self._trusted_subject_id or subject_id
        check_tenant = self._trusted_tenant_id or tenant_id
        check_scope = self._trusted_scope or scope

        verify_receipt(
            receipt,
            self.key,
            expected_action=action,
            expected_object_type=object_type,
            expected_object_digest=object_digest,
            expected_subject_id=check_subject,
            expected_tenant_id=check_tenant,
            expected_scope=check_scope,
            expected_environment=self._trusted_environment,
        )

        # R1: nonce replay protection — verify and consume via persistent ledger
        if self._nonce_store is not None:
            effective_run = run_id or receipt.receipt_id
            self._nonce_store.verify_and_consume(
                receipt.nonce,
                receipt.receipt_id,
                effective_run,
                object_digest,
            )