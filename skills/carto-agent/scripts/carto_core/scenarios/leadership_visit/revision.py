"""leadership-visit revision_contract: scenario design-revision semantics (I-5).

The kernel keeps revision numbering, refs, drift gates, schema validation and the
state transition; this component supplies the scenario-specific change vocabulary,
bundle-input keys, change application and brief source-plan refresh.

The vocabulary spans two layers:

- design-layer scalars/objects (map_title, annotation_layout, page_layout,
  style_overrides): compiled presentation parameters;
- compile-resource keys (basemap, online_basemap): the registered basemap and
  the online tile binding. The basemap NEVER enters the prepared bundle (the
  compiler reads it straight from the request refs), so swapping it keeps the
  data evidence reusable — the kernel's runtime bundle-input digest gate
  (map_generation._reusable_bundle) independently re-verifies that the
  itinerary keys are untouched. Revising it invalidates the plan decisions
  (planner copies basemap_ref/extent) and every compiled product, exactly like
  page_layout.

Itinerary data keys (source_bindings / sources / itinerary_structure) stay OUT
of the vocabulary: those feed the prepared bundle, and changing them is a new
run with host-level data reuse instead.
"""
from __future__ import annotations

from copy import deepcopy
from typing import Any

from ...canonical import sha256_digest
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
            # Compile-resource layer (see module docstring). The plan node is
            # invalidated because the planner copies basemap_ref/extent into
            # its decisions; the online binding only affects compiled products.
            "basemap": ("plan",) + _COMPILATION_NODES,
            "online_basemap": _COMPILATION_NODES,
        }

    # ------------------------------------------------------------------
    # bundle_input_keys
    # ------------------------------------------------------------------

    def bundle_input_keys(self) -> tuple[str, ...]:
        # "basemap" deliberately removed: it is a compile input, never bundle
        # content — keeping it here forced a full data re-preparation on every
        # basemap swap (worse than a new run). The kernel's runtime digest gate
        # still re-verifies the itinerary keys below, so data evidence
        # protection is NOT loosened: any itinerary change breaks the digest
        # and the bundle is re-prepared.
        return ("source_bindings", "sources", "itinerary_structure")

    # ------------------------------------------------------------------
    # apply_changes
    # ------------------------------------------------------------------

    def apply_changes(self, request: dict[str, Any],
                      changes: dict[str, Any]) -> dict[str, Any]:
        revised = deepcopy(request)
        for key, change in changes.items():
            if key in ("map_title", "annotation_layout", "page_layout", "style_overrides"):
                revised[key] = deepcopy(change["new_value"])
            elif key == "basemap":
                value = deepcopy(change["new_value"])
                if (not isinstance(value, dict) or value.get("mode") != "registered-transform"
                        or not value.get("image_ref") or not value.get("parameters_ref")):
                    raise ProtocolError("LEADERSHIP_REVISION_BASEMAP_INVALID",
                                        "basemap revision requires mode/image_ref/parameters_ref")
                revised["basemap"] = value
            elif key == "online_basemap":
                value = change["new_value"]
                if value is None:
                    # Remove semantics: switch back to the image-only display.
                    revised.pop("online_basemap", None)
                else:
                    value = deepcopy(value)
                    if (not isinstance(value, dict) or value.get("provider") != "Tianditu"
                            or value.get("layer") not in {"vec_w", "img_w", "cia_w"}):
                        raise ProtocolError("LEADERSHIP_REVISION_BASEMAP_INVALID",
                                            "online_basemap revision requires Tianditu "
                                            "with an admitted raster layer")
                    revised["online_basemap"] = value
            else:
                raise ProtocolError("LEADERSHIP_REVISION_UNKNOWN_KEY",
                                    f"Unknown revision key: {key}")
        return revised

    # ------------------------------------------------------------------
    # refresh_brief
    # ------------------------------------------------------------------

    def refresh_brief(self, brief: dict[str, Any],
                      revised_request: dict[str, Any]) -> dict[str, Any]:
        """Rebind the brief's source plan to the revised basemap facts.

        The basemap entries carry the new image digest via the request's
        artifactRef (the intake/compile digest gates re-verify the actual file:
        IMAGE_INPUT_DRIFT), and the online declaration enters (or leaves) the
        G1 approval face — the approver's digest always covers the data facts
        the revised design will actually use.
        """
        refreshed = deepcopy(brief)
        plan = refreshed.get("source_plan")
        if not isinstance(plan, list):
            return refreshed
        kept = [entry for entry in plan
                if entry.get("role") not in {"basemap", "online-basemap"}]
        basemap = revised_request.get("basemap") or {}
        image_ref = basemap.get("image_ref")
        if image_ref:
            kept.append({"role": "basemap", "source_ref": deepcopy(image_ref),
                         "allowed_operations": ["read"]})
        online = revised_request.get("online_basemap")
        if online:
            kept.append({
                "role": "online-basemap",
                "source_ref": {"id": "online-basemap", "version": "1.0.0",
                               "digest": sha256_digest(online)},
                "allowed_operations": [],
            })
        refreshed["source_plan"] = kept
        return refreshed


REVISION_CONTRACT = RouteRevisionContract()
