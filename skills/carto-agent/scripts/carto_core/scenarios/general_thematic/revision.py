"""general-thematic revision_contract: scenario design-revision semantics (I-5).

The kernel keeps revision numbering, refs, drift gates, schema validation and the state
transition; this component supplies the scenario-specific change vocabulary, bundle-input
keys, change application and brief source-plan refresh. Moved verbatim from
workflow.revision_graph / workflow.map_generation._revision_documents; error codes preserved.
"""
from __future__ import annotations

from copy import deepcopy
from typing import Any

from ...errors import ProtocolError

_COMPILATION_NODES = ("candidate", "preview", "preflight", "scene")


class GeneralRevisionContract:
    def rules(self) -> dict[str, tuple[str, ...]]:
        return {
            "style": _COMPILATION_NODES,
            "layout_parameters": _COMPILATION_NODES,
            "map_title": _COMPILATION_NODES,
            "color_scheme": _COMPILATION_NODES,
            "panel_designs": ("plan",) + _COMPILATION_NODES,
            # P4: replacing a component re-plans and recompiles; the prepared data
            # evidence stays reusable because bundle inputs are untouched.
            "segment_refs": ("plan",) + _COMPILATION_NODES,
        }

    def bundle_input_keys(self) -> tuple[str, ...]:
        return ("source_bindings", "prepared_raster_bindings", "vector_sources", "sources", "material_sources")

    def apply_changes(self, request: dict[str, Any], changes: dict[str, Any]) -> dict[str, Any]:
        revised = deepcopy(request)
        for key, change in changes.items():
            if key == "panel_designs":
                panels = revised.get("vector_panels", revised.get("panels", []))
                if set(change["new_value"]) - {p["id"] for p in panels}:
                    raise ProtocolError("THEMATIC_VIEW_UNKNOWN", "Proposal refers to an unknown view")
                for panel in panels:
                    if panel["id"] in change["new_value"]:
                        panel["design"] = deepcopy(change["new_value"][panel["id"]])
            elif key == "color_scheme":
                # 裁决4: a compile-time effective-color overlay; the prepared bundle stays
                # frozen and reusable (color is not a bundle-input key).
                revised["revised_color_scheme"] = deepcopy(change["new_value"])
            else:
                revised["revised_cartography" if key == "style" else key] = deepcopy(change["new_value"])
        return revised

    def refresh_brief(self, brief: dict[str, Any], revised_request: dict[str, Any]) -> dict[str, Any]:
        # A different thematic field changes the business binding shown to the approver.
        if revised_request["geometry"] == "vector":
            for source in brief["source_plan"]:
                sid = source["source_ref"]["id"]
                fields = set()
                for panel in revised_request["vector_panels"]:
                    if panel["source_id"] != sid:
                        continue
                    design = panel["design"]
                    if design["field"] is not None:
                        fields.add(design["field"])
                    if design.get("normalization"):
                        fields.add(design["normalization"]["denominator_field"])
                source["field_bindings"] = [{"semantic_role": "thematic-value", "source_field": f}
                                            for f in sorted(fields)]
        if revised_request.get("revised_color_scheme"):
            # 裁决7: surface the effective palette to the G1 approver (conditional required
            # for a color revision); mechanically derived from the frozen revision overlay.
            scheme = revised_request["revised_color_scheme"]
            brief["design_changes"] = {"color_scheme": {
                "scope": scheme["scope"],
                "colors": [{"value": c["value"], "effective_color": c["color"]}
                           for c in scheme["colors"]],
            }}
        return brief


REVISION_CONTRACT = GeneralRevisionContract()