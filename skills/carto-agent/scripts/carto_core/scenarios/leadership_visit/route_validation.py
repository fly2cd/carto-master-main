"""leadership-visit template validation components (L6).

``route_validation_data_checker``: fail-closed static validation of the packaged
synthetic fixture (format, ordered stops, typed fields, coordinate sanity) before
anything can enter a published package.

``route_validation_scene``: builds the deterministic synthetic render scene for
template validation — a synthetic basemap PNG generated at validation time
(never a copy of user imagery), a synthetic registration affine derived from the
fixture coordinates, the packaged image_itinerary style applied to the fixture
stops, and the frozen image page request — rendered through the real
``ImagePageRenderer`` by the kernel validator. The projection and display-window
algorithms run through the authorized ToolGateway capabilities (same contract
as the generate route), never as direct library calls.
"""
from __future__ import annotations

import hashlib
import shutil
from copy import deepcopy
from pathlib import Path
from typing import Any

from ...adapters.image_display import DEFAULT_WHITE_THRESHOLD
from ...adapters.image_tools import (
    DISPLAY_CAPABILITY,
    PROJECTION_CAPABILITY,
    make_image_gateway,
)
from ...artifacts import atomic_json, atomic_yaml
from ...backend_registry import IMAGE_ITINERARY_PAGE
from ...canonical import sha256_digest
from ...compiler.layout import LayoutResolver
from ...errors import ProtocolError, SecurityError
from ...repository.immutable_store import ImmutableArtifactStore
from ...schema_registry import SchemaRegistry, load_document
from ...security.paths import PathGuard
from .style import apply_grouped_style

FIXTURE_KEY = "fixtures/visit-route.synthetic.geojson"
_SYNTHETIC_BASEMAP = (2381, 1684)
_SYNTHETIC_BORDER = 60
_PX_PER_KM = 100.0
_SEED = 20260918


def _fixture_path(package_root: Path, snapshot: dict[str, Any]) -> Path:
    documents = snapshot.get("documents") or {}
    prototype = documents.get("prototype") or {}
    relative = prototype.get("fixture_ref") or FIXTURE_KEY
    path = package_root / relative
    if not path.is_file():
        raise ProtocolError("VALIDATION_FIXTURE_MISSING", relative)
    return path


def _fixture_document(package_root: Path, snapshot: dict[str, Any]) -> dict[str, Any]:
    path = _fixture_path(package_root, snapshot)
    document = load_document(path)
    if not isinstance(document, dict):
        raise ProtocolError("VALIDATION_FIXTURE_INVALID", str(path))
    return document


def _invoke_tool(gateway: Any, guard: PathGuard, capability_id: str,
                 typed_input: dict[str, Any], context: Any) -> tuple[dict[str, Any], Any]:
    """Invoke an authorized capability and load its verified output document."""
    receipt = gateway.invoke(capability_id, typed_input, context)
    if (receipt.status != "succeeded"
            or receipt.input_digest != sha256_digest(typed_input)
            or receipt.capability_id != capability_id
            or len(receipt.artifact_refs) != 1
            or receipt.artifact_refs[0]["digest"] != receipt.output_digest):
        raise ProtocolError("IMAGE_TOOL_EVIDENCE_INVALID",
                            f"{capability_id} gateway evidence is not bound to this request")
    ref = receipt.artifact_refs[0]
    document = load_document(guard.resolve(ref["uri"], must_exist=True))
    if not isinstance(document, dict) or sha256_digest(document) != ref["digest"]:
        raise ProtocolError("IMAGE_TOOL_EVIDENCE_CORRUPT", str(ref["uri"]))
    return document, receipt


def _evidence_resource(receipt: Any) -> dict[str, Any]:
    ref = receipt.artifact_refs[0]
    return {"id": ref["id"], "kind": "contract", "digest_mode": "canonical-json",
            "ref": {"id": ref["id"], "version": ref["version"],
                    "digest": ref["digest"], "uri": ref["uri"]}}


def route_validation_data_checker(package_root: Path, snapshot: dict[str, Any],
                                   expected: dict[str, Any]) -> None:
    """Validate the packaged synthetic route fixture; fail closed on any drift."""
    package_root = Path(package_root)
    fixture = _fixture_document(package_root, snapshot)
    if fixture.get("type") != "FeatureCollection":
        raise ProtocolError("VALIDATION_FIXTURE_INVALID", "Expected a FeatureCollection")
    features = fixture.get("features")
    if not isinstance(features, list) or not 1 <= len(features) <= 1000:
        raise ProtocolError("VALIDATION_FIXTURE_INVALID", "Between 1 and 1000 ordered stops required")
    documents = snapshot.get("documents") or {}
    roles = {role["id"]: role for role in (documents.get("data_schema") or {}).get("roles", [])}
    role = roles.get("route-stops")
    if role is None:
        raise ProtocolError("VALIDATION_FIXTURE_INVALID", "route-stops role is not declared")
    fields = {field["name"]: field for field in role.get("fields", [])}
    orders: list[int] = []
    for index, feature in enumerate(features):
        if not isinstance(feature, dict) or feature.get("type") != "Feature":
            raise ProtocolError("VALIDATION_FIXTURE_INVALID", f"feature {index}")
        geometry = feature.get("geometry") or {}
        if geometry.get("type") != "Point":
            raise ProtocolError("VALIDATION_FIXTURE_INVALID", f"feature {index}: Point required")
        coordinates = geometry.get("coordinates")
        if (not isinstance(coordinates, list) or len(coordinates) != 2
                or not all(isinstance(v, (int, float)) and not isinstance(v, bool)
                           and -180 <= v <= 180 for v in coordinates[:1])
                or not isinstance(coordinates[1], (int, float))
                or not -90 <= coordinates[1] <= 90):
            raise ProtocolError("VALIDATION_FIXTURE_INVALID", f"feature {index}: WGS84 coordinates required")
        properties = feature.get("properties") or {}
        if not isinstance(properties, dict):
            raise ProtocolError("VALIDATION_FIXTURE_INVALID", f"feature {index}")
        order = properties.get("visit_order")
        if not isinstance(order, int) or isinstance(order, bool):
            raise ProtocolError("VALIDATION_FIXTURE_INVALID", f"feature {index}: integer visit_order required")
        orders.append(order)
        if not isinstance(properties.get("stop_name"), str) or not properties.get("stop_name"):
            raise ProtocolError("VALIDATION_FIXTURE_INVALID", f"feature {index}: stop_name required")
        group = properties.get("itinerary_group")
        if group is not None and not isinstance(group, str):
            raise ProtocolError("VALIDATION_FIXTURE_INVALID", f"feature {index}: itinerary_group must be a string")
    if orders != list(range(1, len(orders) + 1)):
        raise ProtocolError("VALIDATION_FIXTURE_INVALID", "visit_order must be sequential from 1")
    for name in ("stop_name", "visit_order"):
        if name not in fields:
            raise ProtocolError("VALIDATION_FIXTURE_INVALID", f"data schema field {name} is undeclared")


def route_validation_scene(package_root: Path, snapshot: dict[str, Any], targets: list[str],
                           font: Path, validator_version: str, *,
                           context: Any = None, workspace: Path | None = None,
                           registry: SchemaRegistry | None = None,
                           layout_parameters: dict[str, Any] | None = None,
                           validation_expression: str | None = None,
                           category_colors: Any = None) -> dict[str, Any]:
    """Freeze the deterministic synthetic image scene for template validation."""
    if context is None or workspace is None:
        raise SecurityError("IMAGE_VALIDATION_CONTEXT_REQUIRED",
                            "Fixture rendering requires the trusted validation context and workspace")
    if sorted(targets) != ["pdf", "png"]:
        raise ProtocolError("RENDER_TARGET_UNSUPPORTED", "The image fixture render requires exactly pdf and png")
    if layout_parameters is not None:
        raise ProtocolError("IMAGE_VALIDATION_PARAMETERS_UNSUPPORTED",
                            "The image itinerary template declares no layout parameters")
    registry = registry or SchemaRegistry()
    package_root = Path(package_root)
    workspace = Path(workspace)
    workspace.mkdir(parents=True, exist_ok=True)
    documents = snapshot["documents"]
    scenario = documents["scenario"]
    # P6 S8: resolve the effective style from the adopted design instances (the authority).
    from .contract_migration import resolve_effective_style
    instances = documents["portrayal"]["design_instances"]
    registry.validate("design-instances", instances)
    style = resolve_effective_style(instances)
    registry.validate("image-itinerary-style", style)
    fixture = _fixture_document(package_root, snapshot)

    # --- Synthetic basemap + registration derived from the fixture coordinates ---
    from PIL import Image, ImageDraw
    width, height = _SYNTHETIC_BASEMAP
    basemap_path = workspace / "basemap.png"
    image = Image.new("RGB", (width, height), "white")
    draw = ImageDraw.Draw(image)
    draw.rectangle([_SYNTHETIC_BORDER, _SYNTHETIC_BORDER,
                    width - _SYNTHETIC_BORDER, height - _SYNTHETIC_BORDER],
                   outline="black", width=6)
    image.save(basemap_path, format="PNG")
    image_bytes = basemap_path.read_bytes()
    image_digest = "sha256:" + hashlib.sha256(image_bytes).hexdigest()
    points = [feature["geometry"]["coordinates"] for feature in fixture["features"]]
    from pyproj import Transformer
    transformer = Transformer.from_crs("EPSG:4326", "EPSG:3857", always_xy=True)
    xs, ys = transformer.transform([p[0] for p in points], [p[1] for p in points])
    origin = [float(xs[0]), float(ys[0])]
    matrix = [[_PX_PER_KM, 0.0, width / 2], [0.0, _PX_PER_KM, height / 2]]
    parameters = {"work_crs": "EPSG:3857", "origin_m": origin,
                  "local_km_y_down_to_pixel": matrix, "source_size": [width, height]}
    parameters_path = workspace / "registration.yaml"
    atomic_yaml(parameters_path, parameters)

    # --- Deterministic projection + display window through ToolGateway --------
    # Same authorized capability path as the generate-route compiler: typed I/O
    # schemas, ToolResult evidence and budget accounting; the algorithms are
    # never called as direct library functions even inside validation.
    route_features = []
    for index, (a, b) in enumerate(zip(points, points[1:])):
        route_features.append({"id": f"leg-{index + 1}", "type": "Feature",
                               "geometry": {"type": "LineString", "coordinates": [a, b]},
                               "properties": {"leg_id": f"leg-{index + 1}",
                                              "route_mode": "straight_line"}})
    route_fc = {"type": "FeatureCollection", "features": route_features}
    route_path = workspace / "route-line.geojson"
    atomic_json(route_path, route_fc)
    fixture_path = _fixture_path(package_root, snapshot)
    guard = PathGuard([workspace, package_root])
    store = ImmutableArtifactStore(workspace / "tool-evidence", path_guard=guard)
    gateway = make_image_gateway(store, registry, guard=guard, project_root=workspace)
    image_ref = {"id": "basemap-image", "version": "1.0.0",
                 "digest": image_digest, "uri": str(basemap_path)}
    projection_input = {
        "schema_version": 1,
        "image_ref": image_ref,
        "parameters_ref": {"id": "registration-parameters", "version": "1.0.0",
                           "digest": sha256_digest(parameters), "uri": str(parameters_path)},
        "stops_ref": {"id": "validation-fixture", "version": "1.0.0",
                      "digest": sha256_digest(fixture), "uri": str(fixture_path)},
        "route_ref": {"id": "validation-route", "version": "1.0.0",
                      "digest": sha256_digest(route_fc), "uri": str(route_path)},
    }
    projection, projection_receipt = _invoke_tool(gateway, guard, PROJECTION_CAPABILITY,
                                                  projection_input, context)
    display_input = {"schema_version": 1, "image_ref": deepcopy(image_ref),
                     "white_threshold": int(style.get("white_threshold", DEFAULT_WHITE_THRESHOLD))}
    display_result, display_receipt = _invoke_tool(gateway, guard, DISPLAY_CAPABILITY,
                                                   display_input, context)
    window = display_result["display_window"]
    role = {r["id"]: r for r in documents["data_schema"]["roles"]}["route-stops"]
    fields = {"route-stops": {field["semantic_role"]: field["name"] for field in role["fields"]}}
    # P6 §13.3: bind graphics to the layout's actual map frame, not a hardcoded string.
    map_frames = [f for f in scenario["embedded"]["layout"]["frames"] if f["type"] == "map"]
    if len(map_frames) != 1:
        raise ProtocolError("ITINERARY_FRAME_BINDING_INVALID", "validation layout needs exactly one map frame")
    styled = apply_grouped_style(style, {"basemap": {"source_size": {"width_px": width, "height_px": height},
                                                     "display_window": window}},
                                 {"projection": projection, "sources": {"route-stops": fixture,
                                                                        "route-line": route_fc},
                                  "fields": fields}, frame_id=map_frames[0]["id"])

    # --- Frozen page request and scene ----------------------------------------
    from ...scenario_registry import ScenarioRegistry
    profile = ScenarioRegistry(registry).for_template(snapshot["manifest"]["package"])
    output = profile.definition["output_profile"]
    resolved_layout = LayoutResolver(registry).resolve(scenario["embedded"]["layout"], output["dpi"])
    if any(resolved_layout["page"][key] != output[key]
           for key in ("width_mm", "height_mm", "dpi", "width_px", "height_px")):
        raise ProtocolError("SCENARIO_OUTPUT_PROFILE_MISMATCH", "Layout differs from the enabled output profile")
    font_copy = workspace / "fonts" / Path(font).name
    font_copy.parent.mkdir(parents=True, exist_ok=True)
    if not font_copy.is_file():
        shutil.copy(font, font_copy)
    font_digest = "sha256:" + hashlib.sha256(font_copy.read_bytes()).hexdigest()
    page_request = {
        "schema_version": 5, "geometry": "vector", "expression": "canvas-overlay",
        "coordinate_mode": "image-pixel-registration",
        "layer_stack": ["basemap", "thematic", "furniture", "legends"],
        "font": {"path": str(font_copy), "digest": font_digest,
                 "size_bytes": font_copy.stat().st_size},
        "grid_north": None, "scale_bar": None,
        "resolved_layout": resolved_layout,
        "texts": [{"content_id": "title", "text": profile.notice and "领导调研行程路线图（模板验证样张）"},
                  {"content_id": "source", "text": profile.notice}],
        "legends": [{"content_id": "legend", "title": "图例",
                     "items": [{"id": f"legend-item-{index + 1}", "label": item["label"],
                                "color": item["color"], "shape": item["shape"]}
                                for index, item in enumerate(styled["legend_items"])]}],
        "document": {"category": scenario["business_scene"], "name": "领导调研行程路线图（模板验证样张）"},
        "overlay": {"graphics_digest": sha256_digest(styled["graphics"])},
        "basemap": {"image": {"path": str(basemap_path), "digest": image_digest,
                              "size_bytes": len(image_bytes)},
                    "registration": {"kind": "affine",
                                     "parameters_ref": {"id": "registration-parameters", "version": "1.0.0",
                                                        "digest": sha256_digest(parameters),
                                                        "uri": str(parameters_path)}},
                    "source_size": {"width_px": width, "height_px": height},
                    "display_window": window,
                    "white_threshold": style.get("white_threshold", DEFAULT_WHITE_THRESHOLD)},
    }
    registry.validate("page-request", page_request)
    page_path = workspace / "page-request.yaml"
    atomic_yaml(page_path, page_request)
    bundle = {"schema_version": 1, "bundle_id": "validation-bundle",
              "role_bindings": [], "shared_semantics": {"stop_count": len(fixture["features"])}}
    bundle_path = workspace / "prepared-data-bundle.yaml"
    atomic_yaml(bundle_path, bundle)
    scene = {
        "schema_version": 1, "scene_id": f"validation-{snapshot['package_digest'][7:23]}",
        "revision": 1,
        "viewport": {"width_px": resolved_layout["page"]["width_px"],
                     "height_px": resolved_layout["page"]["height_px"],
                     "device_pixel_ratio": 1},
        "resolved_layout": resolved_layout,
        "export": {"targets": ["pdf", "png"], "dpi": output["dpi"]},
        "random_seed": _SEED,
        "renderer_id": IMAGE_ITINERARY_PAGE.renderer_id,
        "context": {"run_id": context.run_id, "tenant_id": context.tenant_id,
                    "project_id": context.project_id, "subject_id": context.subject_id},
        "prepared_bundle_ref": {"id": "prepared-data-bundle", "version": "1.0.0",
                                "digest": sha256_digest(bundle), "uri": str(bundle_path)},
        "page_request_ref": {"id": "page-request", "version": "5.0.0",
                             "digest": sha256_digest(page_request), "uri": str(page_path)},
        "resources": [
            {"id": "basemap-image", "kind": "data", "digest_mode": "bytes",
             "ref": {"id": "basemap-image", "version": "1.0.0", "digest": image_digest,
                     "uri": str(basemap_path)}},
            {"id": "registration-parameters", "kind": "contract", "digest_mode": "canonical-json",
             "ref": {"id": "registration-parameters", "version": "1.0.0",
                     "digest": sha256_digest(parameters), "uri": str(parameters_path)}},
            {"id": "map-font", "kind": "font", "digest_mode": "bytes",
             "ref": {"id": "map-font", "version": "1.0.0", "digest": font_digest,
                     "uri": str(font_copy)}},
            # ToolGateway capability evidence travels with the frozen scene.
            _evidence_resource(projection_receipt),
            _evidence_resource(display_receipt),
        ],
        "image_graphics": styled["graphics"],
    }
    registry.validate("render-scene", scene)
    return scene
