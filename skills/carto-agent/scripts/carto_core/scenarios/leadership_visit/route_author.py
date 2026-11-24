"""leadership-visit route_author: deterministic template package authoring (L6).

Every declaration is a scenario constant (the closed template contract content,
including the tuned image_itinerary style values ported from the old framework's
leadership-visit template 1.2.0); this class pins the package identity and
subjects the request to the same fail-closed authoring gates as the general
scenario's authors. ``author`` writes the closed staging package via the shared
StagingPackageWriter; ``verify_existing`` re-derives and byte-verifies it.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from ...artifacts import sha256_digest
from ...canonical import sha256_digest as _sha
from ...errors import ProtocolError
from ...repository.staging_package import StagingPackageWriter
from ...schema_registry import SchemaRegistry

VERSION = "1.0.0"
KIND = "map-scenario"
NAMESPACE = "local"
SCENARIO_ID = "leadership-visit-map"
AUTHORING_PROFILE = "leadership-visit-authoring"
LAYER_ID = "route-layer"
PROTOTYPE_ID = "route-overview"
PROTOTYPE_PATH = "prototypes/route-overview.yaml"
FIXTURE_PATH = "fixtures/visit-route.synthetic.geojson"
LAYOUT_ID = "leadership-a3-landscape"
BUSINESS_SCENE = "leadership_visit"

# Tuned image-itinerary style, ported from the old framework's template 1.2.0
# (grouped callouts profile): real measured values for grouped colors, route
# right-offsets, callout geometry and support labels.
TEMPLATE_STYLE: dict[str, Any] = {
    "schema_version": 1,
    "default_group": "default",
    "groups": [
        {"id": "morning", "label": "上午行程", "color": "#1769D2", "right_offset_px": 2},
        {"id": "afternoon", "label": "下午行程", "color": "#E43D96", "right_offset_px": 8},
        {"id": "default", "label": "其他行程", "color": "#403B96"},
    ],
    "route": {"width_px": 6, "halo_width_px": 1,
              "arrows": {"size_px": 8, "spacing_px": 200}},
    "pin": {"radius_px": 12, "font_size_px": 12},
    "callout": {"width_px": 500, "title_font_px": 22, "body_font_px": 14, "padding_px": 4,
                "line_gap_px": 3, "opacity": 0.88, "leader_width_px": 3,
                "offset_x_px": 45, "offset_y_px": -135, "body_color": "#17352D",
                "title_color": "#FFFFFF", "show_arrival_time": False, "fit_content": True,
                "title_wrap": False, "font_weight": 700},
    "numbering": "per-date-group",
    "support_label": {"color": "#E65C6C", "text_color": "#FFFFFF", "font_size_px": 24,
                      "font_weight": 700, "padding_px": 4, "opacity": 0.95,
                      "leader_width_px": 2, "offset_x_px": 20, "offset_y_px": -40,
                      "point_radius_px": 12},
    "white_threshold": 245,
    # Page furniture — ported from the old framework's scenario contract
    # (layout.image_presentation: title_font_px 48 / body_font_px 18, frame
    # border 1px/4px/2px) via the canvas re-anchoring the author performs:
    # the old 1680x1170 px canvas maps onto this A3 420x297mm layout, i.e.
    # 4 px per mm. 48px -> 12mm -> 34pt; 18px -> 4.5mm -> 12.76pt;
    # 1px/4px/2px -> 0.25mm / 1.0mm / 0.5mm. Physical units (pt/mm), NOT the
    # graphics reference-design pixels: these do not participate in style scale.
    "page_furniture": {
        "title_font_pt": 34.0,
        "body_font_pt": 12.76,
        "frame_border": {"color": "#000000", "inner_width_mm": 0.25,
                         "gap_mm": 1.0, "outer_width_mm": 0.5},
    },
}

TARGET_IDS = ("leadership-map-pdf", "leadership-map-png")

# The A3 landscape layout contract: one map frame plus title/legend/source
# marginalia frames; shared by the author, the compiler and the validator.
LAYOUT_CONTRACT: dict[str, Any] = {
    "schema_version": 1, "layout_id": LAYOUT_ID, "version": "1.0.0", "category": "report",
    "canvas": {"width": 420, "height": 297, "unit": "mm", "orientation": "landscape",
               "safe_margin": 10},
    "frames": [
        {"id": "main-map", "content_id": "main-view", "type": "map", "coordinate_space": "page",
         "bounds": [20, 30, 380, 230], "overflow_policy": "clip"},
        {"id": "map-title", "content_id": "title", "type": "title", "coordinate_space": "page",
         "bounds": [20, 12, 380, 14], "overflow_policy": "reject"},
        {"id": "legend", "content_id": "legend", "type": "legend", "coordinate_space": "page",
         "bounds": [300, 264, 110, 22], "overflow_policy": "reject"},
        {"id": "source", "content_id": "source", "type": "marginalia", "coordinate_space": "page",
         "bounds": [20, 264, 200, 22], "overflow_policy": "reject"},
    ],
    "placeholders": ["{{MAP_TITLE}}"],
    "capacity": {"legend_items": 12, "title_characters": 40},
    "rules": [],
}

VALIDATION_TITLE = "领导调研行程路线图（模板验证样张）"
VALIDATION_NOTICE = "领导调研路线图：行程路线为示意参考，不用于实际导航"

CARTOGRAPHY: dict[str, Any] = {
    "schema_version": 2, "style_id": "technical-map", "version": "2.0.0",
    "visual_language": "technical",
    "symbolization": {"color_system": "sequential", "symbol_catalogs": ["ramps/test-theme@1.0.0"],
                      "default_opacity": 0.8},
    "labeling": {"density": "medium", "collision_policy": "prioritize", "font_role": "body"},
    "generalization": {"scale_dependent": True, "strategy": "simplify"},
    "defaults": {"line_width_mm": 0.2, "point_size_mm": 3, "opacity": 0.8},
    "rules": [],
    "typography": {"title_pt": 18, "body_pt": 9, "legend_pt": 10,
                   "legend_heading_pt": 11, "line_spacing": 1.25},
}


def _require_admitted(request: dict[str, Any], brief: dict[str, Any]) -> None:
    """Fail-closed authoring gates: identity, targets, preserve-CRS, brief."""
    if (request.get("kind") != KIND or request.get("namespace") != NAMESPACE
            or request.get("template_id") != SCENARIO_ID or request.get("version") != VERSION
            or request.get("profile") != AUTHORING_PROFILE):
        raise ProtocolError("CAPABILITY_NOT_AVAILABLE",
                            "Only the registered authoring profile may use this author")
    if sorted(request.get("targets", [])) != ["pdf", "png"]:
        raise ProtocolError("RENDER_TARGET_UNSUPPORTED", "Admitted targets are exactly pdf and png")
    if request["source_crs"] != request["display_crs"]:
        raise ProtocolError("SOURCE_CRS_UNSUPPORTED",
                            "The preserve policy requires display_crs to equal source_crs")
    if (brief.get("kind") != KIND or brief.get("namespace") != NAMESPACE
            or brief.get("template_id") != SCENARIO_ID or brief.get("version") != VERSION):
        raise ProtocolError("TEMPLATE_BRIEF_MISMATCH", "Brief does not describe this template")


def template_documents(request: dict[str, Any] | None = None) -> dict[str, Any]:
    """The closed package documents (single content source for author and tests)."""
    identity = {"namespace": NAMESPACE, "kind": KIND, "id": SCENARIO_ID, "version": VERSION}
    scenario = {
        "schema_version": 1, "scenario_id": SCENARIO_ID, "version": VERSION,
        "business_scene": BUSINESS_SCENE, "tasks": ["visit-route-map"],
        "owned_segments": ["scenario", "data", "spatial-behavior", "portrayal",
                           "delivery", "quality-gates"],
        "embedded": {"style": CARTOGRAPHY, "layout": LAYOUT_CONTRACT},
        "replaceable_segments": ["layout"],
        "data_role_refs": ["route-stops", "route-line"],
        "target_ids": list(TARGET_IDS),
        "application": {"supported_uses": ["engineering-preview"],
                        "excluded_uses": ["navigation", "formal-delivery", "actual-navigation"]},
        "compatibility": {"target_profiles": list(TARGET_IDS),
                          "placeholders": ["{{MAP_TITLE}}"]},
        "rules": [],
    }
    gates = {
        "schema_version": 1,
        "baseline": {"id": "leadership-quality-gates", "version": VERSION,
                     "digest": _sha({"scenario_id": SCENARIO_ID, "version": VERSION,
                                     "business_scene": BUSINESS_SCENE})},
        "checks": [
            {"id": "protocol.schema-valid", "version": "1.0.0", "params": {}},
            {"id": "cartography.legend-consistency", "version": "1.0.0", "params": {}},
        ],
    }
    page = {"width_mm": 420, "height_mm": 297, "orientation": "landscape",
            "dpi": 300, "safe_margin_mm": 10}
    purpose = (request or {}).get("purpose", "领导调研行程路线图模板")[:500]
    documents = {
        "contracts/scenario.yaml": scenario,
        "contracts/data.schema.yaml": {
            "schema_version": 1,
            "roles": [
                {"id": "route-stops", "required": True, "geometry_types": ["point"],
                 "fields": [
                     {"name": "stop_name", "type": "string", "nullable": False,
                      "semantic_role": "stop-label"},
                     {"name": "visit_order", "type": "integer", "nullable": False,
                      "semantic_role": "visit-order"},
                     {"name": "visit_date", "type": "string", "nullable": True,
                      "semantic_role": "visit-date"},
                     {"name": "arrival_time", "type": "string", "nullable": True,
                      "semantic_role": "arrival-time"},
                     {"name": "distance_km", "type": "number", "nullable": True,
                      "semantic_role": "distance-km"},
                     {"name": "duration_min", "type": "number", "nullable": True,
                      "semantic_role": "duration-min"},
                     {"name": "itinerary_group", "type": "string", "nullable": True,
                      "semantic_role": "itinerary-group"}],
                 "license_policy": "project-approved"},
                {"id": "route-line", "required": False, "geometry_types": ["linestring"],
                 "fields": [{"name": "route_mode", "type": "string", "nullable": False,
                             "semantic_role": "route-mode"}],
                 "license_policy": "project-approved"},
            ]},
        "contracts/spatial-behavior.yaml": {
            "schema_version": 1, "source_crs_policy": "preserve",
            "display_crs": {"authority": "EPSG", "code": "4326"},
            "extent_policy": "approved-bbox",
            "scale_bands": [{"id": "registered-basemap", "min_denominator": 1000,
                             "max_denominator": 1000000, "generalization": "none"}],
            "topology": {"preserve_adjacency": False, "preserve_route_order": True},
            "rules": []},
        "contracts/portrayal.yaml": {
            "schema_version": 1, "rules": [], "layer_ids": [LAYER_ID],
            "image_itinerary": TEMPLATE_STYLE},
        "contracts/delivery.yaml": {
            "schema_version": 1,
            "targets": [
                {"id": TARGET_IDS[0], "delivery_class": "engineering-preview", "format": "pdf",
                 "composition": "raster-map-vector-overlay", "vector_claim": "overlay-only",
                 "page": dict(page), "color_mode": "rgb", "font_policy": "embed-approved",
                 "production_ready": False},
                {"id": TARGET_IDS[1], "delivery_class": "engineering-preview", "format": "png",
                 "composition": "flattened-raster", "vector_claim": "none",
                 "page": dict(page), "color_mode": "rgb", "font_policy": "embed-approved",
                 "production_ready": False},
            ],
            "rules": []},
        "contracts/quality-gates.yaml": gates,
        "dependencies.lock.yaml": {
            "schema_version": 1, "lock_id": "leadership-visit-map-lock",
            "package": {**identity, "digest": sha256_digest(identity)},
            "dependencies": [], "resources": [], "resolver_version": "1.0.0",
            "generated_at": (request or {}).get("requested_at", "2026-11-19T00:00:00Z")},
        PROTOTYPE_PATH: {
            "schema_version": 1, "prototype_id": PROTOTYPE_ID, "status": "pending-validation",
            "render_required": True, "renderer_execution": "not-run",
            "layout_id": LAYOUT_ID, "target_ids": list(TARGET_IDS),
            "layer_ids": [LAYER_ID], "fixture_ref": FIXTURE_PATH,
            "limitations": ["Synthetic validation only; not real itinerary data or navigation."]},
        FIXTURE_PATH: {
            "type": "FeatureCollection",
            "features": [
                {"type": "Feature", "geometry": {"type": "Point", "coordinates": [120.0, 30.0]},
                 "properties": {"visit_order": 1, "stop_name": "甲地",
                                "itinerary_group": "morning", "visit_date": "11月18日"}},
                {"type": "Feature", "geometry": {"type": "Point", "coordinates": [120.02, 29.98]},
                 "properties": {"visit_order": 2, "stop_name": "乙地",
                                "itinerary_group": "afternoon", "visit_date": "11月18日"}},
                {"type": "Feature", "geometry": {"type": "Point", "coordinates": [119.98, 30.02]},
                 "properties": {"visit_order": 3, "stop_name": "丙地",
                                "itinerary_group": "afternoon", "visit_date": "11月18日"}},
            ]},
    }
    return documents


def template_manifest_base(request: dict[str, Any]) -> dict[str, Any]:
    identity = {"namespace": NAMESPACE, "kind": KIND, "id": SCENARIO_ID, "version": VERSION}
    return {
        "schema_version": 1,
        "package": {**identity, "status": "draft", "summary": request["purpose"][:500]},
        "business_contracts": {
            "scenario": "contracts/scenario.yaml", "data_schema": "contracts/data.schema.yaml",
            "spatial_behavior": "contracts/spatial-behavior.yaml",
            "portrayal": "contracts/portrayal.yaml", "delivery": "contracts/delivery.yaml",
            "quality_gates": "contracts/quality-gates.yaml"},
        "dependencies": [], "dependency_lock": "dependencies.lock.yaml",
        "targets": sorted(request["targets"]),
    }


class RouteAuthor:
    """Deterministically author the closed leadership-visit staging package."""

    def __init__(self, path_guard, work_root: Path, registry: SchemaRegistry | None = None) -> None:
        self.path_guard = path_guard
        self.work_root = path_guard.resolve(work_root, must_exist=True)
        self.registry = registry or SchemaRegistry()

    def _check(self, request: dict[str, Any], brief: dict[str, Any]) -> None:
        _require_admitted(request, brief)
        self.registry.validate("leadership-visit-template-create-request", request)

    def author(self, request: dict[str, Any], brief: dict[str, Any]) -> dict[str, str]:
        self._check(request, brief)
        return StagingPackageWriter(self.path_guard, self.work_root, self.registry).write(
            template_manifest_base(request), template_documents(request))

    def verify_existing(self, request: dict[str, Any], brief: dict[str, Any]) -> dict[str, str]:
        self._check(request, brief)
        return StagingPackageWriter(self.path_guard, self.work_root, self.registry).verify_existing(
            template_manifest_base(request), template_documents(request))
