"""Incremental revision invalidation analysis (W1-M2, layer 1).

Pure functions parameterized by the scenario ``revision_contract`` (I-5): given a design
revision proposal's ``changes`` and the scenario's rules, compute which frozen products are
invalidated; given a request and the scenario's bundle-input keys, compute the bundle-input
digest. The kernel holds no scenario change vocabulary — rules/keys come from the component.
Reuse is gated at runtime by comparing the bundle-input digest, never by trusting the static
rules alone: equal input digest plus deterministic prepare means a byte-equal bundle.
Unknown change keys are rejected outright.
"""
from __future__ import annotations

from typing import Any

from ..canonical import sha256_digest
from ..errors import ProtocolError


def bundle_input_digest(request: dict[str, Any], keys: tuple[str, ...]) -> str:
    """Digest of exactly the request fields that determine the prepared bundle."""
    return sha256_digest({key: request.get(key) for key in keys if key in request})


def compute_invalidation(changes: dict[str, Any], rules: dict[str, tuple[str, ...]]) -> dict[str, Any]:
    """Compute the invalidated product nodes for a revision proposal's changes."""
    if not isinstance(changes, dict) or not changes:
        raise ProtocolError("REVISION_CHANGES_REQUIRED", "A revision proposal must carry changes")
    unknown = sorted(set(changes) - set(rules))
    if unknown:
        raise ProtocolError("REVISION_CHANGES_UNKNOWN", ",".join(unknown))
    invalidated: set[str] = set()
    for key in changes:
        invalidated.update(rules[key])
    # All admissible change keys are design-layer fields, so the bundle input is
    # untouched; the runtime digest gate remains the authoritative guard.
    return {
        "invalidated_nodes": sorted(invalidated),
        "data_evidence_reusable": True,
        "earliest_step": "compile",
    }