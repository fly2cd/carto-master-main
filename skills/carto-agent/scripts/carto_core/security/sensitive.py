from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Any, Mapping

from ..errors import SecurityError


class DataClassification(StrEnum):
    PUBLIC = "public"
    INTERNAL = "internal"
    CONFIDENTIAL = "confidential"
    RESTRICTED = "restricted"


@dataclass(frozen=True, slots=True)
class ExternalAccessPolicy:
    approved_services: frozenset[str]
    allow_public_for_internal: bool = False

    def require_allowed(
        self,
        *,
        service_id: str,
        classification: DataClassification,
        data_kind: str,
        explicit_approval: bool,
    ) -> None:
        if service_id not in self.approved_services:
            raise SecurityError("EXTERNAL_SERVICE_DENIED", f"Service is not approved: {service_id}")
        if classification in {DataClassification.CONFIDENTIAL, DataClassification.RESTRICTED}:
            raise SecurityError("SENSITIVE_DATA_EGRESS_DENIED", "Sensitive data cannot use a public service")
        if data_kind in {"leadership_itinerary", "emergency_location"} and not explicit_approval:
            raise SecurityError(
                "SENSITIVE_DATA_APPROVAL_REQUIRED",
                f"Explicit approval is required for data kind: {data_kind}",
            )
        if classification is DataClassification.INTERNAL and not (
            self.allow_public_for_internal and explicit_approval
        ):
            raise SecurityError("INTERNAL_DATA_EGRESS_DENIED", "Internal data egress is not approved")


def _is_sensitive_key(key: object) -> bool:
    normalized = "".join(character for character in str(key).lower() if character.isalnum())
    sensitive_fragments = {
        "apikey", "authorization", "coordinate", "credential", "geometry",
        "itinerary", "password", "secret", "token",
    }
    return any(fragment in normalized for fragment in sensitive_fragments)


def redact_for_log(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {
            str(key): "[REDACTED]" if _is_sensitive_key(key) else redact_for_log(item)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [redact_for_log(item) for item in value]
    if isinstance(value, tuple):
        return tuple(redact_for_log(item) for item in value)
    return value
