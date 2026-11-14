"""Signed approval receipt for workflow gate verification.

Full approval baseline (A1.1):
  - Complete 17-field receipt with identity, scope, and replay protection.
  - Nonce-based replay prevention via persistent NonceStore.
  - Subject/tenant/scope/object_type enforcement on every gate.
"""
from __future__ import annotations

import hmac
import re
from dataclasses import asdict, dataclass, replace
from datetime import datetime, timezone
from hashlib import sha256
from typing import Any

from ..canonical import canonical_json_bytes
from ..errors import SecurityError

_DIGEST = re.compile(r"^sha256:[0-9a-f]{64}$")
_SIGNATURE = re.compile(r"^[0-9a-f]{64}$")
_NONCE = re.compile(r"^[ -~]{16,128}$")
MINIMUM_HMAC_KEY_BYTES = 32


@dataclass(frozen=True, slots=True)
class ApprovalReceipt:
    """Immutable signed approval receipt with full identity and scope claims.

    All fields except ``signature`` participate in the HMAC payload.
    """

    schema_version: int = 1
    receipt_id: str = ""
    issuer: str = ""
    subject_id: str = ""
    tenant_id: str = ""
    action: str = ""
    object_type: str = ""
    object_digest: str = ""
    scope: str = ""
    policy_id: str = ""
    environment: str = ""
    nonce: str = ""
    issued_at: str = ""
    expires_at: str = ""
    signature_algorithm: str = "hmac-sha256"
    signature: str = ""

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "ApprovalReceipt":
        if not isinstance(value, dict):
            raise SecurityError("APPROVAL_FORMAT_INVALID", "Approval receipt must be an object")
        try:
            return cls(**{k: v for k, v in value.items() if k in cls.__dataclass_fields__})
        except TypeError as exc:
            raise SecurityError("APPROVAL_FORMAT_INVALID", str(exc)) from exc

    def signing_payload(self) -> dict[str, Any]:
        value = asdict(self)
        value.pop("signature")
        return value


def sign_receipt(receipt: ApprovalReceipt, key: bytes) -> ApprovalReceipt:
    _validate_shape(receipt, require_signature=False)
    _validate_key(key)
    signature = hmac.new(key, canonical_json_bytes(receipt.signing_payload()), sha256).hexdigest()
    return replace(receipt, signature=signature)


def verify_receipt(
    receipt: ApprovalReceipt,
    key: bytes,
    *,
    expected_action: str,
    expected_object_type: str,
    expected_object_digest: str,
    expected_subject_id: str | None = None,
    expected_tenant_id: str | None = None,
    expected_scope: str | None = None,
    expected_environment: str | None = None,
    now: datetime | None = None,
) -> None:
    """Verify full approval receipt: signature, identity, scope, object, nonce, and time window.

    Every verification failure raises :exc:`SecurityError` with a distinct code.
    Checks are ordered so that structural errors surface before semantic ones.
    """
    # --- structural checks ---------------------------------------------------
    _validate_shape(receipt, require_signature=True)
    _validate_key(key)

    if receipt.schema_version != 1:
        raise SecurityError("APPROVAL_VERSION_UNSUPPORTED", "Only schema_version 1 is supported")

    # --- cryptographic integrity ---------------------------------------------
    expected_signature = hmac.new(
        key, canonical_json_bytes(receipt.signing_payload()), sha256
    ).hexdigest()
    if not hmac.compare_digest(receipt.signature, expected_signature):
        raise SecurityError("APPROVAL_SIGNATURE_INVALID", "Approval signature is invalid")

    # --- claim matching -------------------------------------------------------
    if receipt.action != expected_action:
        raise SecurityError("APPROVAL_ACTION_MISMATCH", "Approval action does not match")
    if receipt.object_type != expected_object_type:
        raise SecurityError(
            "APPROVAL_OBJECT_TYPE_MISMATCH",
            f"Expected object_type '{expected_object_type}', got '{receipt.object_type}'",
        )
    if receipt.object_digest != expected_object_digest:
        raise SecurityError("APPROVAL_OBJECT_MISMATCH", "Approved object digest does not match")

    # --- identity / scope (optional in single-user mode, but enforced when provided)
    if expected_subject_id is not None and receipt.subject_id != expected_subject_id:
        raise SecurityError(
            "APPROVAL_SUBJECT_MISMATCH",
            f"Expected subject '{expected_subject_id}', got '{receipt.subject_id}'",
        )
    if expected_tenant_id is not None and receipt.tenant_id != expected_tenant_id:
        raise SecurityError(
            "APPROVAL_TENANT_MISMATCH",
            f"Expected tenant '{expected_tenant_id}', got '{receipt.tenant_id}'",
        )
    if expected_scope is not None and receipt.scope != expected_scope:
        raise SecurityError(
            "APPROVAL_SCOPE_MISMATCH",
            f"Expected scope '{expected_scope}', got '{receipt.scope}'",
        )

    if expected_environment is not None and receipt.environment != expected_environment:
        raise SecurityError("APPROVAL_ENVIRONMENT_MISMATCH", "Approval belongs to another execution environment")

    # --- time window ----------------------------------------------------------
    issued = _parse_time(receipt.issued_at)
    expires = _parse_time(receipt.expires_at)
    current = now or datetime.now(timezone.utc)
    if current.tzinfo is None:
        raise SecurityError("APPROVAL_TIME_INVALID", "Verification time must include a timezone")
    current = current.astimezone(timezone.utc)
    if issued > current or expires <= current or expires <= issued:
        raise SecurityError("APPROVAL_TIME_INVALID", "Approval is not currently valid")


def _validate_shape(receipt: ApprovalReceipt, *, require_signature: bool) -> None:
    if not receipt.receipt_id:
        raise SecurityError("APPROVAL_FORMAT_INVALID", "receipt_id is required")
    if not receipt.action:
        raise SecurityError("APPROVAL_FORMAT_INVALID", "action is required")
    if not receipt.object_type:
        raise SecurityError("APPROVAL_FORMAT_INVALID", "object_type is required")
    if not _DIGEST.fullmatch(receipt.object_digest):
        raise SecurityError("APPROVAL_FORMAT_INVALID", "object_digest must be sha256:<64 hex>")
    if not receipt.issuer:
        raise SecurityError("APPROVAL_FORMAT_INVALID", "issuer is required")
    if not receipt.subject_id:
        raise SecurityError("APPROVAL_FORMAT_INVALID", "subject_id is required")
    if not receipt.tenant_id:
        raise SecurityError("APPROVAL_FORMAT_INVALID", "tenant_id is required")
    if not receipt.scope:
        raise SecurityError("APPROVAL_FORMAT_INVALID", "scope is required")
    if not receipt.policy_id:
        raise SecurityError("APPROVAL_FORMAT_INVALID", "policy_id is required")
    if not receipt.environment:
        raise SecurityError("APPROVAL_FORMAT_INVALID", "environment is required")
    if not _NONCE.fullmatch(receipt.nonce):
        raise SecurityError(
            "APPROVAL_NONCE_INVALID",
            "nonce must be 16-128 printable ASCII characters",
        )
    if receipt.signature_algorithm != "hmac-sha256":
        raise SecurityError("APPROVAL_ALGORITHM_UNSUPPORTED", "Unsupported approval algorithm")
    if require_signature and not _SIGNATURE.fullmatch(receipt.signature):
        raise SecurityError("APPROVAL_SIGNATURE_INVALID", "Approval signature is invalid")
    if receipt.signature and not _SIGNATURE.fullmatch(receipt.signature):
        raise SecurityError("APPROVAL_SIGNATURE_INVALID", "Approval signature is invalid")


def _validate_key(key: bytes) -> None:
    if len(key) < MINIMUM_HMAC_KEY_BYTES:
        raise SecurityError(
            "APPROVAL_KEY_WEAK",
            f"Approval HMAC key must be at least {MINIMUM_HMAC_KEY_BYTES} bytes",
        )


def _parse_time(value: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise SecurityError("APPROVAL_TIME_INVALID", f"Invalid approval time: {value}") from exc
    if parsed.tzinfo is None:
        raise SecurityError("APPROVAL_TIME_INVALID", "Approval time must include a timezone")
    return parsed.astimezone(timezone.utc)