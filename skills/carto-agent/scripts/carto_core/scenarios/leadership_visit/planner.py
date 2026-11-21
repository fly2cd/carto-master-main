"""leadership-visit planner: builds a MapPlan v4 from intent + template + data.

The planner reads the layout contract from the template installation and the
page parameters from the request, and preserves intent semantics. No pixel
projection or rendering happens here — this is a semantic decision layer; the
image geometry (extent normalization from registration) is executed
mechanically by the candidate compiler.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from ...artifacts import artifact_ref
from ...backend_registry import IMAGE_ITINERARY_PAGE
from ...errors import ProtocolError

_DEFAULT_DPI = 300
_DEFAULT_EXTENT = [120.0, 30.0, 121.0, 31.0]


class RoutePlanner:
    """Build a schema-valid MapPlan v4 for a leadership visit route map."""

    def __init__(self, registry: Any = None, *, project_root: Any = None) -> None:
        self._registry = registry
        self._project_root = Path(project_root) if project_root else None

    def build(self, request: dict[str, Any], intent: dict[str, Any],
              brief: dict[str, Any], bundle: dict[str, Any],
              installation: dict[str, Any],
              contracts: dict[str, Any]) -> dict[str, Any]:
        """Emit a MapPlan v4 that preserves intent semantics.

        The plan declares (map-plan schema, image branch):
        - decisions: title, renderer_id, extent, canvas, basemap_ref,
          layout_model and annotation_layout — the semantic inputs the
          compiler executes mechanically.
        - data_bindings: one entry per prepared bundle role.
        """
        layout_contract = contracts.get("scenario", {}).get("embedded", {}).get("layout") or {}
        canvas = layout_contract.get("canvas", {})
        width_mm = canvas.get("width", 420)
        height_mm = canvas.get("height", 297)
        page_layout = request.get("page_layout", {})
        dpi = int(page_layout.get("dpi", _DEFAULT_DPI))
        basemap = request.get("basemap", {})
        decisions = {
            # Explicit run-level title (request.map_title, also the design-revision
            # vocabulary key) wins over the goal text; the goal remains the fallback
            # so requests without a title keep today's behaviour.
            "title": request.get("map_title") or request.get("goal", "领导调研行程路线图"),
            "renderer_id": IMAGE_ITINERARY_PAGE.renderer_id,
            "extent": list(basemap.get("extent") or _DEFAULT_EXTENT),
            "canvas": {"width_mm": width_mm, "height_mm": height_mm, "dpi": dpi},
            "basemap_ref": basemap.get("image_ref", {}),
            "layout_model": page_layout.get("model", "fixed-page"),
        }
        annotation_layout = request.get("annotation_layout")
        if annotation_layout:
            decisions["annotation_layout"] = {
                "seed": int(annotation_layout["seed"]),
                "iterations": int(annotation_layout["iterations"]),
                "gap_px": int(annotation_layout["gap_px"]),
            }
        plan = {
            "schema_version": 4,
            "plan_id": f"plan-{request.get('run_id', 'leadership')}",
            "revision": int(brief.get("revision", 1)),
            "project_id": request["project_id"],
            "intent_ref": artifact_ref("map-intent", intent),
            "brief_ref": artifact_ref("map-brief", brief),
            "business_scene": intent["business_scene"],
            "theme_tags": list(intent.get("theme_tags", [])),
            "tasks": list(intent.get("tasks", ["visit-route-map"])),
            "template_refs": [dict(installation["template_ref"])],
            "data_bindings": [
                {"role": binding.get("role") or binding.get("source_id", "route"),
                 "dataset_ref": binding["prepared_ref"]}
                for binding in bundle.get("role_bindings", [])],
            "decisions": decisions,
            "open_issues": [],
        }
        if not plan["data_bindings"]:
            raise ProtocolError("LEADERSHIP_PLAN_BUNDLE_REQUIRED", "Plan requires prepared itinerary data")
        return plan
