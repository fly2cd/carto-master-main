from __future__ import annotations

from copy import deepcopy
from datetime import UTC, datetime
from typing import Any

from ..canonical import sha256_digest
from ..errors import ProtocolError
from ..schema_registry import SchemaRegistry


def _utc_now() -> str:
    return datetime.now(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")


class MapSpecLockCompiler:
    """Freeze and authenticate an approved candidate snapshot without recomputing semantics."""

    def __init__(self, registry: SchemaRegistry | None = None) -> None:
        self.registry = registry or SchemaRegistry()

    def compile(
        self,
        request: dict[str, Any],
        candidate: dict[str, Any],
        evidence: dict[str, Any],
        receipt: dict[str, Any],
        preflight: dict[str, Any],
        *,
        brief_approval_ref: str,
        freeze_approval_ref: str,
    ) -> dict[str, Any]:
        lock = {
            **self._expected_snapshot(
                request,
                candidate,
                evidence,
                receipt,
                preflight,
                brief_approval_ref=brief_approval_ref,
                freeze_approval_ref=freeze_approval_ref,
            ),
            "created_at": _utc_now(),
        }
        self.registry.validate("map-spec-lock", lock)
        return lock

    def verify_existing(
        self,
        lock: dict[str, Any],
        request: dict[str, Any],
        candidate: dict[str, Any],
        evidence: dict[str, Any],
        receipt: dict[str, Any],
        preflight: dict[str, Any],
        *,
        brief_approval_ref: str,
        freeze_approval_ref: str,
    ) -> None:
        """Verify that an existing immutable lock is exactly the expected freeze result."""
        self.registry.validate("map-spec-lock", lock)
        expected = self._expected_snapshot(
            request,
            candidate,
            evidence,
            receipt,
            preflight,
            brief_approval_ref=brief_approval_ref,
            freeze_approval_ref=freeze_approval_ref,
        )
        actual = {key: lock.get(key) for key in expected}
        if actual != expected:
            raise ProtocolError("MAP_SPEC_LOCK_CONTEXT_MISMATCH", lock.get("lock_id", "unknown"))

    @staticmethod
    def _expected_snapshot(
        request: dict[str, Any],
        candidate: dict[str, Any],
        evidence: dict[str, Any],
        receipt: dict[str, Any],
        preflight: dict[str, Any],
        *,
        brief_approval_ref: str,
        freeze_approval_ref: str,
    ) -> dict[str, Any]:
        execution = deepcopy(candidate["execution"])
        execution_digest = candidate["execution_digest"]
        if execution != candidate["execution"] or sha256_digest(execution) != execution_digest:
            raise ProtocolError("LOCK_EXECUTION_DIGEST_MISMATCH", f"lock-{request['run_id']}")
        return {
            "schema_version": 1,
            "lock_id": f"lock-{request['run_id']}",
            "project_id": request["project_id"],
            "run_id": request["run_id"],
            "candidate_ref": {
                "id": candidate["candidate_id"],
                "version": "1.0.0",
                "digest": sha256_digest(candidate),
            },
            "execution_digest": execution_digest,
            "execution": execution,
            "evidence": {
                "preflight_ref": {
                    "id": preflight["report_id"],
                    "version": "1.0.0",
                    "digest": sha256_digest(preflight),
                },
                "preview_ref": {
                    "id": evidence["evidence_id"],
                    "version": "1.0.0",
                    "digest": evidence["evidence_digest"],
                },
            },
            "approvals": {
                "brief_ref": brief_approval_ref,
                "freeze_ref": freeze_approval_ref,
            },
            "candidate_digest": sha256_digest(candidate),
            "preview_evidence_digest": evidence["evidence_digest"],
            "render_receipt_ref": {
                "id": receipt["receipt_id"],
                "version": "1.0.0",
                "digest": sha256_digest(receipt),
            },
            "environment_fingerprint": evidence["environment_fingerprint"],
        }
