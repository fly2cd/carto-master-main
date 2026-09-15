from __future__ import annotations

import hmac
import re
import sqlite3
import threading
from contextlib import closing
from dataclasses import asdict, dataclass, replace
from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path
from typing import Any, Protocol

from ..canonical import canonical_json_bytes
from ..errors import SecurityError

_DIGEST = re.compile(r"^sha256:[0-9a-f]{64}$")
_SIGNATURE = re.compile(r"^[0-9a-f]{64}$")
MINIMUM_HMAC_KEY_BYTES = 32


class NonceStore(Protocol):
    def consume(self, issuer: str, nonce: str, expires_at: datetime) -> bool: ...


class InMemoryNonceStore:
    def __init__(self) -> None:
        self._seen: set[tuple[str, str]] = set()
        self._lock = threading.Lock()

    def consume(self, issuer: str, nonce: str, expires_at: datetime) -> bool:
        key = (issuer, nonce)
        with self._lock:
            if key in self._seen:
                return False
            self._seen.add(key)
            return True


class SqliteNonceStore:
    """Persistent, process-safe replay protection for controlled single-host use."""

    def __init__(self, database_path: str) -> None:
        self.database_path = database_path
        parent = Path(database_path).parent
        if not parent.exists() or not parent.is_dir():
            raise SecurityError("NONCE_STORE_PARENT_INVALID", "Nonce database parent must exist")
        with closing(self._connect()) as connection:
            connection.execute(
                "CREATE TABLE IF NOT EXISTS consumed_nonce ("
                "issuer TEXT NOT NULL, nonce TEXT NOT NULL, expires_at REAL NOT NULL, "
                "PRIMARY KEY (issuer, nonce))"
            )

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(self.database_path, timeout=10.0, isolation_level=None)

    def consume(self, issuer: str, nonce: str, expires_at: datetime) -> bool:
        now = datetime.now(timezone.utc).timestamp()
        with closing(self._connect()) as connection:
            connection.execute("BEGIN IMMEDIATE")
            connection.execute("DELETE FROM consumed_nonce WHERE expires_at <= ?", (now,))
            cursor = connection.execute(
                "INSERT OR IGNORE INTO consumed_nonce (issuer, nonce, expires_at) VALUES (?, ?, ?)",
                (issuer, nonce, expires_at.timestamp()),
            )
            connection.commit()
            return cursor.rowcount == 1


@dataclass(frozen=True, slots=True)
class ApprovalReceipt:
    schema_version: int
    receipt_id: str
    issuer: str
    subject_id: str
    tenant_id: str
    action: str
    object_type: str
    object_digest: str
    scope: str
    policy_id: str
    environment: str
    issued_at: str
    expires_at: str
    nonce: str
    signature_algorithm: str = "hmac-sha256"
    signature: str = ""

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "ApprovalReceipt":
        if not isinstance(value, dict):
            raise SecurityError("APPROVAL_FORMAT_INVALID", "Approval receipt must be an object")
        try:
            return cls(**value)
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
    nonce_store: NonceStore,
    *,
    expected_action: str,
    expected_object_digest: str,
    expected_scope: str,
    expected_policy_id: str,
    expected_tenant_id: str,
    expected_issuer: str,
    expected_subject_id: str,
    expected_object_type: str,
    expected_environment: str,
    now: datetime | None = None,
) -> None:
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
    if receipt.scope != expected_scope or receipt.tenant_id != expected_tenant_id:
        raise SecurityError("APPROVAL_SCOPE_MISMATCH", "Approval scope or tenant does not match")
    if receipt.policy_id != expected_policy_id:
        raise SecurityError("APPROVAL_POLICY_MISMATCH", "Approval policy does not match")
    if receipt.issuer != expected_issuer or receipt.subject_id != expected_subject_id:
        raise SecurityError("APPROVAL_IDENTITY_MISMATCH", "Approval issuer or subject does not match")
    if receipt.object_type != expected_object_type:
        raise SecurityError("APPROVAL_OBJECT_TYPE_MISMATCH", "Approval object type does not match")
    if receipt.environment != expected_environment:
        raise SecurityError("APPROVAL_ENVIRONMENT_MISMATCH", "Approval environment does not match")

    issued = _parse_time(receipt.issued_at)
    expires = _parse_time(receipt.expires_at)
    current = now or datetime.now(timezone.utc)
    if current.tzinfo is None:
        raise SecurityError("APPROVAL_TIME_INVALID", "Verification time must include a timezone")
    current = current.astimezone(timezone.utc)
    if issued > current or expires <= current or expires <= issued:
        raise SecurityError("APPROVAL_TIME_INVALID", "Approval is not currently valid")
    if not nonce_store.consume(receipt.issuer, receipt.nonce, expires):
        raise SecurityError("APPROVAL_REPLAYED", "Approval nonce has already been consumed")


def _validate_shape(receipt: ApprovalReceipt, *, require_signature: bool) -> None:
    if receipt.schema_version != 1:
        raise SecurityError("APPROVAL_VERSION_UNSUPPORTED", "Only approval schema version 1 is supported")
    required = (
        receipt.receipt_id,
        receipt.issuer,
        receipt.subject_id,
        receipt.tenant_id,
        receipt.action,
        receipt.object_type,
        receipt.scope,
        receipt.policy_id,
        receipt.environment,
        receipt.nonce,
    )
    if not all(required) or not _DIGEST.fullmatch(receipt.object_digest):
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
