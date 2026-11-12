"""Signed approval receipt for workflow gate verification.

Simplified from multi-tenant enterprise design to the current single-user CLI scope:
  - Keeps: HMAC signature, action/digest matching, time-bound validity.
  - Removed: NonceStore replay protection, multi-claim cross-org delegation
    (tenant/scope/policy/issuer/subject/object_type/environment), recovery paths.
  - These can be reintroduced when multi-tenant deployment is needed.
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
MINIMUM_HMAC_KEY_BYTES = 16


@dataclass(frozen=True, slots=True)
class ApprovalReceipt:
    receipt_id: str
    action: str
    object_digest: str
    issued_at: str
    expires_at: str
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
    expected_object_digest: str,
    now: datetime | None = None,
) -> None:
    """Verify HMAC signature, action, digest, and time window."""
    _validate_shape(receipt, require_signature=True)
    _validate_key(key)
    expected_signature = hmac.new(
        key, canonical_json_bytes(receipt.signing_payload()), sha256
    ).hexdigest()
    if not hmac.compare_digest(receipt.signature, expected_signature):
        raise SecurityError("APPROVAL_SIGNATURE_INVALID", "Approval signature is invalid")
    if receipt.action != expected_action:
        raise SecurityError("APPROVAL_ACTION_MISMATCH", "Approval action does not match")
    if receipt.object_digest != expected_object_digest:
        raise SecurityError("APPROVAL_OBJECT_MISMATCH", "Approved object digest does not match")

    issued = _parse_time(receipt.issued_at)
    expires = _parse_time(receipt.expires_at)
    current = now or datetime.now(timezone.utc)
    if current.tzinfo is None:
        raise SecurityError("APPROVAL_TIME_INVALID", "Verification time must include a timezone")
    current = current.astimezone(timezone.utc)
    if issued > current or expires <= current or expires <= issued:
        raise SecurityError("APPROVAL_TIME_INVALID", "Approval is not currently valid")


def _validate_shape(receipt: ApprovalReceipt, *, require_signature: bool) -> None:
    if not receipt.receipt_id or not receipt.action or not _DIGEST.fullmatch(receipt.object_digest):
        raise SecurityError("APPROVAL_FORMAT_INVALID", "Approval contains invalid required fields")
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