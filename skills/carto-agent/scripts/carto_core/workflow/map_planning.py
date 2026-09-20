from __future__ import annotations

from typing import Any

from ..canonical import sha256_digest
from ..errors import ProtocolError
from ..schema_registry import SchemaRegistry
from .map_data_preparation import artifact_ref


class MapPlanner:
    """Build the deterministic U-P2.5 map plan from approved brief and prepared roles."""

    def __init__(self, registry: SchemaRegistry | None = None) -> None:
        self.registry = registry or SchemaRegistry()

    def build(self, request: dict[str, Any], intent: dict[str, Any], brief: dict[str, Any],
              bundle: dict[str, Any], installation: dict[str, Any],
              contracts: dict[str, Any]) -> dict[str, Any]:
        scenario = contracts["scenario"]
        portrayal = contracts["portrayal"]
        if scenario["business_scene"] != intent["business_scene"] or scenario["tasks"] != intent["tasks"]:
            raise ProtocolError("TEMPLATE_INTENT_INCOMPATIBLE", scenario["scenario_id"])
        risk_layer = next((item for item in portrayal["layers"] if item["data_role"] == "risk-area"), None)
        point_layer = next((item for item in portrayal["layers"] if item["data_role"] == "shelter-point"), None)
        if not risk_layer or not point_layer:
            raise ProtocolError("TEMPLATE_LAYER_SET_INVALID", "risk-area and shelter-point layers are required")
        classification = risk_layer.get("classification", {})
        if classification.get("method") != "quantile":
            raise ProtocolError("CLASSIFICATION_UNSUPPORTED", str(classification.get("method")))
        if point_layer.get("scaling", {}).get("method") != "area-proportional":
            raise ProtocolError("POINT_SCALING_UNSUPPORTED", str(point_layer.get("scaling", {}).get("method")))
        title = request["goal"].strip()
        if len(title) > 200:
            title = title[:197] + "..."
        plan = {
            "schema_version": 1, "plan_id": f"plan-{request['run_id']}", "revision": 1,
            "project_id": request["project_id"], "intent_ref": artifact_ref("map-intent", intent),
            "brief_ref": artifact_ref("map-brief", brief), "business_scene": intent["business_scene"],
            "tasks": list(intent["tasks"]), "template_refs": [installation["template_ref"]],
            "data_bindings": [{"role": item["role"], "dataset_ref": item["prepared_ref"]}
                              for item in bundle["role_bindings"]],
            "decisions": {"classification": "quantile", "class_count": classification["classes"],
                          "extent": bundle["summary"]["combined_bbox"], "title": title,
                          "legend_source": "actual-encoding", "renderer_id": "maplibre-web",
                          "point_scaling": "area-proportional"},
            "open_issues": [],
        }
        self.registry.validate("map-plan", plan)
        return plan

    @staticmethod
    def digest(plan: dict[str, Any]) -> str:
        return sha256_digest(plan)
