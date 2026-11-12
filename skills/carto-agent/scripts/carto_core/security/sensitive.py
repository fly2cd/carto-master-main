"""Log-sanitization utility, kept from the now-removed data classification framework.

The full DataClassification / ExternalAccessPolicy framework was removed as premature
for single-user CLI use; only ``redact_for_log`` is exercised by agent_runtime.
"""
from __future__ import annotations

from typing import Any, Mapping


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