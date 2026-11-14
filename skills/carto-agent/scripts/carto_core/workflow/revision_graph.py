"""Incremental revision invalidation analysis (W1-M2, layer 1).

Pure functions: given a design-revision proposal's ``changes``, compute which
frozen products are invalidated and whether the data evidence (the prepared
bundle) may be reused. The rules mirror the revision-impact table in
doc/标准专题图制图流程说明.md §7. Reuse is gated at runtime by comparing the
bundle-input digest, never by trusting the static rules alone: equal input
digest plus the deterministic prepare means a byte-equal bundle, so the
shortcut is equivalent to recomputation. Unknown change keys are rejected
outright (the proposal schema already whitelists the four design fields).
"""
from __future__ import annotations

from typing import Any

from ..canonical import sha256_digest
from ..errors import ProtocolError

# Request fields that (and only) determine the prepared bundle. Design-layer
# fields (cartography/layout/title/panel designs) are deliberately absent:
# they never reach the data-preparation path.
BUNDLE_INPUT_KEYS = (
    "source_bindings", "prepared_raster_bindings", "vector_sources", "sources", "material_sources",
)

_COMPILATION_NODES = ("candidate", "preview", "preflight", "scene")
_RULES = {
    # Appearance-only changes invalidate from compilation downward.
    "cartography": _COMPILATION_NODES,
    "layout_parameters": _COMPILATION_NODES,
    "map_title": _COMPILATION_NODES,
    # Encoding decisions change, so the plan is invalidated as well.
    "panel_designs": ("plan",) + _COMPILATION_NODES,
}


def bundle_input_digest(request: dict[str, Any]) -> str:
    """Digest of exactly the request fields that determine the prepared bundle."""
    return sha256_digest({key: request.get(key) for key in BUNDLE_INPUT_KEYS if key in request})


def compute_invalidation(changes: dict[str, Any]) -> dict[str, Any]:
    """Compute the invalidated product nodes for a revision proposal's changes."""
    if not isinstance(changes, dict) or not changes:
        raise ProtocolError("REVISION_CHANGES_REQUIRED", "A revision proposal must carry changes")
    unknown = sorted(set(changes) - set(_RULES))
    if unknown:
        raise ProtocolError("REVISION_CHANGES_UNKNOWN", ",".join(unknown))
    invalidated: set[str] = set()
    for key in changes:
        invalidated.update(_RULES[key])
    # All admissible change keys are design-layer fields, so the bundle input is
    # untouched; the runtime digest gate remains the authoritative guard.
    return {
        "invalidated_nodes": sorted(invalidated),
        "data_evidence_reusable": True,
        "earliest_step": "compile",
    }
