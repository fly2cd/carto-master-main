"""leadership-visit revision_contract: scenario design-revision semantics (I-5).

The kernel keeps revision numbering, refs, drift gates, schema validation and the
state transition; this component supplies the scenario-specific change vocabulary,
bundle-input keys, change application and brief source-plan refresh.
"""
from __future__ import annotations

from copy import deepcopy
from typing import Any

from ...errors import ProtocolError

_COMPILATION_NODES = ("candidate", "preview", "preflight", "scene")


class RouteRevisionContract:
    """Design-revision semantics for leadership visit maps."""

    # ------------------------------------------------------------------
    # rules
    # ------------------------------------------------------------------

    def rules(self) -> dict[str, tuple[str, ...]]:
        return {
            "map_title": _COMPILATION_NODES,
            "annotation_layout": _COMPILATION_NODES,
            "page_layout": ("plan",) + _COMPILATION_NODES,
            # Design-layer style patch (colors / fonts / frame border): recompile
            # + re-preview only — the bundle inputs are untouched, so the frozen
            # data evidence stays reusable (the runtime digest gate remains the
            # authoritative guard, never the static rules).
            "style_overrides": _COMPILATION_NODES,
        }

    # ------------------------------------------------------------------
    # bundle_input_keys
    # ------------------------------------------------------------------

    def bundle_input_keys(self) -> tuple[str, ...]:
        return ("source_bindings", "sources", "itinerary_structure", "basemap")

    # ------------------------------------------------------------------
    # apply_changes
    # ------------------------------------------------------------------

    def apply_changes(self, request: dict[str, Any],
                      changes: dict[str, Any]) -> dict[str, Any]:
        revised = deepcopy(request)
        for key, change in changes.items():
            if key in ("map_title", "annotation_layout", "page_layout", "style_overrides"):
                revised[key] = deepcopy(change["new_value"])
            else:
                raise ProtocolError("LEADERSHIP_REVISION_UNKNOWN_KEY",
                                    f"Unknown revision key: {key}")
        return revised

    # ------------------------------------------------------------------
    # refresh_brief
    # ------------------------------------------------------------------

    def refresh_brief(self, brief: dict[str, Any],
                      revised_request: dict[str, Any]) -> dict[str, Any]:
        # The revised brief re-approval binds the revised request through the
        # kernel-added request_ref (an artifact_ref digest); the map-brief
        # contract is closed and admits no metadata section, so a title change
        # reaches the approver's digest through the request it references —
        # not through a scenario-local brief field.
        return brief


REVISION_CONTRACT = RouteRevisionContract()