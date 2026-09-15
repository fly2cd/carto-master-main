from __future__ import annotations

import hashlib
import json
from typing import Any

from .errors import ProtocolError


def canonical_json_bytes(value: Any) -> bytes:
    """Return the v1 canonical JSON representation used by protocol digests."""
    try:
        text = json.dumps(
            value,
            ensure_ascii=False,
            allow_nan=False,
            separators=(",", ":"),
            sort_keys=True,
        )
    except (TypeError, ValueError) as exc:
        raise ProtocolError("CANONICALIZATION_FAILED", str(exc)) from exc
    return text.encode("utf-8")


def sha256_digest(value: Any) -> str:
    return "sha256:" + hashlib.sha256(canonical_json_bytes(value)).hexdigest()
