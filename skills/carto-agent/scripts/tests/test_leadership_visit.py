"""leadership-visit scenario tests (P3: rendering pipeline + product document).

Synthetic only: a synthetic PNG basemap with a deterministic registration
affine, synthetic itinerary stops/routes, a synthetic layout contract and a
matplotlib-bundled font. No real itinerary data, approvals, or production
claims. The tests cover the migrated algorithms (geo_to_image_pixels /
image_display / image_layout), apply_grouped_style, the candidate compiler
(scene + candidate), the ImagePageRenderer (PDF/PNG + RenderReceipt) and the
FrontendDocumentBuilder (map_json).
"""
from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path
import sys
import tempfile
import unittest

import matplotlib
from PIL import Image, ImageDraw

SCRIPTS_ROOT = Path(__file__).resolve().parents[1]
if str(SCRIPTS_ROOT) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_ROOT))

from carto_core.adapters.annotation_solver import RouteIndex, check_layout, collides, solve_layout
from carto_core.adapters.geo_to_image_pixels import PixelConverter, clip_line, project_features
from carto_core.adapters.image_display import display_bounds
from carto_core.adapters.image_layout import callout_text, contain_layout, validate_image_geometry
from carto_core.adapters.image_page_renderer import ImagePageRenderer
from carto_core.artifacts import atomic_json, atomic_yaml, file_digest
from carto_core.canonical import sha256_digest
from carto_core.compiler.layout import LayoutResolver
from carto_core.contracts.execution import ExecutionContext
from carto_core.errors import ProtocolError, SecurityError
from carto_core.schema_registry import SchemaRegistry, load_document
from carto_core.scenario_registry import ScenarioRegistry
from carto_core.scenarios.leadership_visit.candidate_compiler import RouteCandidateCompiler
from carto_core.scenarios.leadership_visit.frontend_document import FrontendDocumentBuilder
from carto_core.scenarios.leadership_visit.planner import RoutePlanner
from carto_core.scenarios.leadership_visit.style import apply_grouped_style
from carto_core.security.paths import PathGuard
from tests.fixtures.schema_cases import VALID_CASES

STYLE = {
    "schema_version": 1,
    "groups": [
        {"id": "morning", "label": "上午", "color": "#1769D2"},
        {"id": "default", "label": "行程", "color": "#403B96", "right_offset_px": 12},
    ],
    "default_group": "default",
    "route": {"width_px": 6, "halo_width_px": 2, "right_offset_px": 12,
              "arrows": {"size_px": 8, "spacing_px": 200}},
    "pin": {"radius_px": 12, "font_size_px": 12},
    "callout": {"width_px": 220, "title_font_px": 22, "body_font_px": 14, "padding_px": 8,
                "line_gap_px": 4, "opacity": 0.88, "leader_width_px": 1.5,
                "offset_x_px": 16, "offset_y_px": -16, "font_weight": 700,
                "title_wrap": True, "show_arrival_time": False, "fit_content": False},
    "support_label": {"color": "#E65C6C", "text_color": "#FFFFFF", "point_radius_px": 6,
                      "font_size_px": 14, "padding_px": 4, "opacity": 0.88,
                      "leader_width_px": 1.0, "offset_x_px": 12, "offset_y_px": -12},
    "numbering": "global",
    "white_threshold": 245,
}

LAYOUT_CONTRACT = {
    "schema_version": 1, "layout_id": "leadership-a3-landscape", "version": "1.0.0",
    "category": "report",
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

STOPS = [
    {"id": "stop-1", "visit_order": 1, "stop_name": "甲地", "stop_type": "visit",
     "itinerary_group": "morning", "visit_date": "11月18日", "arrival_time": "09:00",
     "distance_km": 0, "duration_min": 30, "map_role": "origin"},
    {"id": "stop-2", "visit_order": 2, "stop_name": "乙地", "stop_type": "visit",
     "itinerary_group": "default", "visit_date": "11月18日", "arrival_time": "11:00",
     "distance_km": 12, "duration_min": 45, "map_role": "visit"},
    {"id": "stop-3", "visit_order": 3, "stop_name": "丙地", "stop_type": "visit",
     "itinerary_group": "default", "visit_date": "11月18日", "arrival_time": "15:00",
     "distance_km": 8, "duration_min": 20, "map_role": "destination"},
]


def _coordinates(stop_index: int) -> list[float]:
    delta = [[0.0, 0.0], [0.02, -0.02], [-0.02, 0.02]][stop_index]
    return [120.0 + delta[0], 30.0 + delta[1]]


class LeadershipFixture(unittest.TestCase):
    """Synthetic project: registered basemap, itinerary data, font, request."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.root = Path(tempfile.mkdtemp(prefix="leadership-visit-"))
        cls.guard = PathGuard([cls.root])
        cls.registry = SchemaRegistry()
        # Synthetic basemap at the 144-DPI reference design size (2381x1684):
        # white with a black border so the visible window is deterministic.
        cls.image_path = cls.root / "basemap.png"
        image = Image.new("RGB", (2381, 1684), "white")
        draw = ImageDraw.Draw(image)
        draw.rectangle([60, 60, 2320, 1620], outline="black", width=6)
        image.save(cls.image_path, format="PNG")
        cls.image_bytes = cls.image_path.read_bytes()
        cls.image_digest = "sha256:" + __import__("hashlib").sha256(cls.image_bytes).hexdigest()
        # Registration: (120, 30) -> pixel (1190, 842), 100 px per local km.
        from pyproj import Transformer
        transformer = Transformer.from_crs("EPSG:4326", "EPSG:3857", always_xy=True)
        x0, y0 = transformer.transform(120.0, 30.0)
        cls.parameters = {"work_crs": "EPSG:3857", "origin_m": [x0, y0],
                          "local_km_y_down_to_pixel": [[100.0, 0.0, 1190.0], [0.0, 100.0, 842.0]],
                          "source_size": [2381, 1684]}
        cls.parameters_path = cls.root / "registration.yaml"
        atomic_yaml(cls.parameters_path, cls.parameters)
        # Prepared itinerary GeoJSON (the P2 data preparer's output shape).
        stops_features = [{"id": stop["id"], "type": "Feature",
                           "geometry": {"type": "Point", "coordinates": _coordinates(i)},
                           "properties": dict(stop)}
                          for i, stop in enumerate(STOPS)]
        cls.stops_fc = {"type": "FeatureCollection", "features": stops_features}
        route_features = []
        for index, (a, b) in enumerate([(0, 1), (1, 2)]):
            route_features.append({"id": f"leg-{index + 1}", "type": "Feature",
                                   "geometry": {"type": "LineString",
                                                "coordinates": [_coordinates(a), _coordinates(b)]},
                                   "properties": {"leg_id": f"leg-{index + 1}",
                                                  "route_mode": "straight_line",
                                                  "itinerary_group": "default"}})
        cls.route_fc = {"type": "FeatureCollection", "features": route_features}
        cls.data_dir = cls.root / "data" / "prepared"
        cls.data_dir.mkdir(parents=True, exist_ok=True)
        cls.stops_path = cls.data_dir / "route-stops.geojson"
        cls.route_path = cls.data_dir / "route-line.geojson"
        atomic_json(cls.stops_path, cls.stops_fc)
        atomic_json(cls.route_path, cls.route_fc)
        # Font: matplotlib's bundled DejaVu Sans (synthetic, non-CJK is fine).
        cls.font_path = cls.root / "fonts" / "selected-font.ttf"
        cls.font_path.parent.mkdir(parents=True, exist_ok=True)
        import shutil
        shutil.copy(Path(matplotlib.get_data_path()) / "fonts" / "ttf" / "DejaVuSans.ttf",
                    cls.font_path)
        # Source itinerary document (the MCP itinerary service's product shape):
        # the kernel data preparer normalizes it into prepared GeoJSON.
        cls.itinerary = {
            "stops": [
                {"stop_id": "s1", "name": "甲地", "visit_order": 1,
                 "location": {"lon": _coordinates(0)[0], "lat": _coordinates(0)[1]},
                 "stop_type": "visit", "itinerary_group": "morning", "visit_date": "11月18日",
                 "arrival_time": "09:00", "distance_km": 0, "duration_min": 30,
                 "activities": [{"type": "visit"}]},
                {"stop_id": "s2", "name": "乙地", "visit_order": 2,
                 "location": {"lon": _coordinates(1)[0], "lat": _coordinates(1)[1]},
                 "stop_type": "visit", "itinerary_group": "default", "visit_date": "11月18日",
                 "arrival_time": "11:00", "distance_km": 12, "duration_min": 45,
                 "activities": [{"type": "meeting"}]},
                {"stop_id": "s3", "name": "丙地", "visit_order": 3,
                 "location": {"lon": _coordinates(2)[0], "lat": _coordinates(2)[1]},
                 "stop_type": "visit", "itinerary_group": "default", "visit_date": "11月18日",
                 "arrival_time": "15:00", "distance_km": 8, "duration_min": 20,
                 "activities": [{"type": "visit"}]},
            ],
            "legs": [
                {"leg_id": "leg-1", "kind": "travel", "from_stop_id": "s1", "to_stop_id": "s2",
                 "route_mode": "straight_line"},
                {"leg_id": "leg-2", "kind": "travel", "from_stop_id": "s2", "to_stop_id": "s3",
                 "route_mode": "straight_line"},
            ],
        }
        cls.itinerary_path = cls.root / "data" / "itinerary.json"
        cls.itinerary_path.parent.mkdir(parents=True, exist_ok=True)
        atomic_json(cls.itinerary_path, cls.itinerary)
        # Request body: the closed leadership profile with real file references.
        cls.request = json.loads(json.dumps(VALID_CASES["leadership-visit-generate-request"]))
        cls.request.update(
            project_id="test-project", run_id="test-run", scope="project:test-project",
            goal="编制领导调研行程路线图",
            idempotency_key="leadership-test-00001",
            font={"path": "fonts/selected-font.ttf", "family": "DejaVu Sans", "version": "1.0.0"},
            sources=[{"id": "itinerary", "version": "1.0.0", "digest": cls.image_digest}],
            page_layout={"model": "fixed-page", "width_mm": 420, "height_mm": 297, "dpi": 200},
        )
        cls.request["intent"] = {
            "business_scene": "leadership_visit", "theme_tags": [], "tasks": ["visit-route-map"],
            "fields": {"itinerary": "甲地至丙地", "visit-order": "1,2,3", "route-mode": "road",
                       "geography": "unit-region", "confidentiality": "internal", "output": "pdf"},
        }
        cls.request["itinerary_structure"] = {
            "source_ref": {"id": "itinerary-source", "version": "1.0.0",
                           "digest": sha256_digest(cls.itinerary), "uri": "data/itinerary.json"},
            "normalized_ref": {"id": "itinerary-normalized", "version": "1.0.0",
                               "digest": sha256_digest(cls.stops_fc)},
        }
        cls.request["basemap"] = {
            "mode": "registered-transform",
            "image_ref": {"id": "basemap-image", "version": "1.0.0", "digest": cls.image_digest,
                          "uri": "basemap.png"},
            "parameters_ref": {"id": "registration-parameters", "version": "1.0.0",
                               "digest": sha256_digest(cls.parameters), "uri": "registration.yaml"},
        }
        cls.request["source_bindings"] = [{
            "role": "route-stops",
            "source_ref": {"id": "itinerary-source", "version": "1.0.0",
                           "digest": sha256_digest(cls.itinerary)},
            "path": "data/itinerary.json",
            "geometry_types": ["point"],
            "field_bindings": [
                {"semantic_role": "stop-label", "source_field": "stop_name"},
                {"semantic_role": "visit-date", "source_field": "visit_date"},
                {"semantic_role": "arrival-time", "source_field": "arrival_time"},
                {"semantic_role": "distance-km", "source_field": "distance_km"},
                {"semantic_role": "duration-min", "source_field": "duration_min"},
                {"semantic_role": "itinerary-group", "source_field": "itinerary_group"},
            ],
        }]
        cls.intent = ScenarioRegistry(cls.registry).generate_intent(cls.request)
        # Conforms to the shared prepared-data-bundle contract (the revision
        # reuse gate validates the stored bundle against that schema).
        _dataset_ref = dict(cls.request["itinerary_structure"]["source_ref"])
        _stops_ref = {"id": "vector-prepared-data", "version": "1.0.0",
                      "digest": sha256_digest(cls.stops_fc),
                      "uri": "data/prepared/route-stops.geojson"}
        _route_ref = {"id": "vector-prepared-data", "version": "1.0.0",
                      "digest": sha256_digest(cls.route_fc),
                      "uri": "data/prepared/route-line.geojson"}
        _stop_fields = {item["semantic_role"]: item["source_field"]
                        for item in cls.request["source_bindings"][0]["field_bindings"]}
        cls.bundle = {
            "schema_version": 1, "bundle_id": "leadership-visit-test-run",
            "task_ref": {"id": "generate-request", "version": "1.0.0",
                         "digest": sha256_digest(cls.request)},
            "datasets": [_dataset_ref], "transformations": [], "tool_receipts": [],
            "quality_evidence": [_stops_ref, _route_ref], "open_issues": [],
            "role_bindings": [
                {"data_type": "vector", "source_id": "route-stops", "role": "route-stops",
                 "dataset_ref": _dataset_ref, "prepared_ref": _stops_ref,
                 "geometry_types": ["point"], "feature_count": 3,
                 "bbox": [119.97, 29.97, 120.03, 30.03],
                 "crs": {"authority": "EPSG", "code": "4326"},
                 "semantic_fields": _stop_fields},
                {"data_type": "vector", "source_id": "route-line", "role": "route-line",
                 "dataset_ref": _dataset_ref, "prepared_ref": _route_ref,
                 "geometry_types": ["linestring"], "feature_count": 2,
                 "bbox": [119.97, 29.97, 120.03, 30.03],
                 "crs": {"authority": "EPSG", "code": "4326"},
                 "semantic_fields": {}},
            ],
            "summary": {"data_nature": "itinerary"},
        }
        cls.bundle["digest"] = sha256_digest(cls.bundle)
        cls.installation = {
            "template_ref": {"kind": "map-scenario", "id": "leadership-visit-map",
                             "version": "1.0.0", "digest": "sha256:" + "0" * 64},
        }
        cls.contracts = {
            "scenario": {"business_scene": "leadership_visit", "tasks": ["visit-route-map"],
                         "scenario_id": "leadership-visit-map", "version": "1.0.0",
                         "embedded": {"layout": LAYOUT_CONTRACT}},
            "portrayal": {"schema_version": 1, "rules": [], "image_itinerary": STYLE},
        }
        cls.brief = {"brief_id": "brief-test-run", "revision": 1}

    def artifact_uri(self, relative: str) -> str:
        return (self.root / relative).as_posix()


class AlgorithmTests(LeadershipFixture, unittest.TestCase):
    def test_pixel_converter_center_anchor(self):
        converter = PixelConverter(self.parameters)
        pixels, inside = converter.coordinates([[120.0, 30.0]])
        self.assertEqual([(1190.0, 842.0)], [tuple(p) for p in pixels])
        self.assertEqual([True], inside)

    def test_project_features_stops_and_routes(self):
        projection = project_features(self.parameters, self.image_bytes, self.stops_fc, self.route_fc)
        self.assertEqual([1, 2, 3], [s["visit_order"] for s in projection["stops"]])
        self.assertEqual((1190.5, 842.5),
                         (projection["stops"][0]["position"]["x"], projection["stops"][0]["position"]["y"]))
        self.assertEqual(2, len(projection["routes"]))
        for route in projection["routes"]:
            self.assertEqual("straight_line", route["route_mode"])
            self.assertTrue(route["parts"])

    def test_project_features_rejects_gap(self):
        shifted = json.loads(json.dumps(self.stops_fc))
        shifted["features"][1]["properties"]["visit_order"] = 4
        with self.assertRaises(ProtocolError) as raised:
            project_features(self.parameters, self.image_bytes, shifted, self.route_fc)
        self.assertEqual("IMAGE_PROJECTION_ORDER_INVALID", raised.exception.code)

    def test_display_bounds_window(self):
        window = display_bounds(self.image_bytes)
        self.assertEqual(60, window["x"])
        self.assertEqual(60, window["y"])
        self.assertEqual(2261, window["width"])
        self.assertEqual(1561, window["height"])

    def test_contain_layout_aspect(self):
        layout = contain_layout({"width_px": 380, "height_px": 280},
                                {"x": 0.0, "y": 0.0, "width": 300.0, "height": 230.0})
        self.assertAlmostEqual(300.0 / 380.0, layout["scale"], places=6)
        self.assertAlmostEqual(0.0, layout["x"], places=6)

    def test_clip_line_keeps_segments(self):
        parts = clip_line([{"x": -10, "y": 5}, {"x": 50, "y": 5}, {"x": 500, "y": 5}], 400, 300)
        # Liang-Barsky retains the middle vertex and merges the adjacent visible parts.
        self.assertEqual([[{"x": 0, "y": 5}, {"x": 50, "y": 5}, {"x": 400, "y": 5}]],
                         [[{"x": p["x"], "y": p["y"]} for p in part] for part in parts])

    def test_callout_text_measures_height(self):
        graphic = {"id": "g", "title": "甲地", "lines": ["到达时间：09:00"], "title_font_px": 22,
                   "body_font_px": 14, "width_px": 220, "padding_px": 8, "line_gap_px": 4,
                   "title_wrap": True}
        wrapped, height = callout_text(graphic)
        self.assertEqual(["甲地"], wrapped)
        self.assertGreater(height, 16)


class StyleTests(LeadershipFixture, unittest.TestCase):
    def test_apply_grouped_style_graphics(self):
        projection = project_features(self.parameters, self.image_bytes, self.stops_fc, self.route_fc)
        window = display_bounds(self.image_bytes)
        page_request = {"basemap": {"source_size": {"width_px": 400, "height_px": 300},
                                    "display_window": window}}
        fields = {"route-stops": {item["semantic_role"]: item["source_field"]
                                  for item in self.request["source_bindings"][0]["field_bindings"]},
                  "route-line": {}}
        styled = apply_grouped_style(STYLE, page_request,
                                     {"projection": projection, "sources": {"route-stops": self.stops_fc,
                                                                            "route-line": self.route_fc},
                                      "fields": fields})
        graphics = styled["graphics"]
        types = {g["type"] for g in graphics}
        self.assertEqual({"line", "point", "callout"}, types)
        self.assertEqual(3, sum(1 for g in graphics if g["type"] == "point"))
        self.assertEqual(3, sum(1 for g in graphics if g["type"] == "callout"))
        for graphic in graphics:
            self.assertEqual("image-pixel", graphic["coordinate_space"])
            self.assertEqual("main-map", graphic["frame_id"])
        for graphic in graphics:
            if graphic["type"] == "callout":
                wrapped, height = callout_text(graphic)
                self.assertAlmostEqual(height, graphic["height_px"], places=6)
        self.assertIn("行程点", [item["label"] for item in styled["legend_items"]])
        self.assertIn("上午", [item["label"] for item in styled["legend_items"]])

    def test_apply_grouped_style_rejects_unknown_group(self):
        projection = project_features(self.parameters, self.image_bytes, self.stops_fc, self.route_fc)
        shifted = json.loads(json.dumps(self.stops_fc))
        shifted["features"][0]["properties"]["itinerary_group"] = "evening"
        window = display_bounds(self.image_bytes)
        with self.assertRaises(ProtocolError) as raised:
            apply_grouped_style(STYLE, {"basemap": {"source_size": {"width_px": 2381, "height_px": 1684},
                                                    "display_window": window}},
                                {"projection": projection, "sources": {"route-stops": shifted,
                                                                       "route-line": self.route_fc},
                                 "fields": {"route-stops": {"itinerary-group": "itinerary_group"}}})
        self.assertEqual("ITINERARY_GROUP_UNKNOWN", raised.exception.code)


class StyleOverrideTests(LeadershipFixture, unittest.TestCase):
    """Phase 1: request-level style_overrides patch the template style contract
    (groups by id, sections key-wise, scalars replaced); the template stays the
    default authority for everything the patch does not mention."""

    def _request_with_override(self):
        request = json.loads(json.dumps(self.request))
        request["style_overrides"] = {
            "groups": [{"id": "morning", "color": "#228833"}],
            "route": {"width_px": 9},
        }
        return request

    def test_closed_request_profile_admits_style_overrides(self):
        request = self._request_with_override()
        self.registry.validate("leadership-visit-generate-request", request)
        # Invalid shapes reject at the closed-profile schema layer.
        bad = json.loads(json.dumps(request))
        bad["style_overrides"] = {"groups": [{"id": "morning", "color": "#2288GG"}]}
        with self.assertRaises(ProtocolError):
            self.registry.validate("leadership-visit-generate-request", bad)
        bad["style_overrides"] = {"callout": {"opacity": 2.0}}
        with self.assertRaises(ProtocolError):
            self.registry.validate("leadership-visit-generate-request", bad)
        bad["style_overrides"] = {"unknown_section": True}
        with self.assertRaises(ProtocolError):
            self.registry.validate("leadership-visit-generate-request", bad)

    def test_merge_preserves_unpatched_fields_and_rejects_unknown_groups(self):
        from carto_core.scenarios.leadership_visit.request_contract import _merge_style_override
        merged = _merge_style_override(STYLE, {
            "groups": [{"id": "morning", "color": "#228833"}],
            "route": {"width_px": 9},
        })
        self.assertEqual("#228833", merged["groups"][0]["color"])
        self.assertEqual(9, merged["route"]["width_px"])
        # Untouched fields preserved: template stays the default authority.
        self.assertEqual(STYLE["groups"][0]["label"], merged["groups"][0]["label"])
        self.assertEqual(STYLE["groups"][1], merged["groups"][1])
        self.assertEqual(STYLE["route"]["halo_width_px"], merged["route"]["halo_width_px"])
        self.assertEqual(STYLE["route"]["arrows"], merged["route"]["arrows"])
        self.assertEqual(STYLE["callout"], merged["callout"])
        # The merged contract satisfies the full style schema (formal gate).
        self.registry.validate("image-itinerary-style", merged)
        # Unknown group id / unknown default_group reject (patch-by-id semantics).
        for patch in ({"groups": [{"id": "evening", "color": "#000000"}]},
                      {"default_group": "evening"}):
            with self.assertRaises(ProtocolError) as raised:
                _merge_style_override(STYLE, patch)
            self.assertEqual("LEADERSHIP_STYLE_GROUP_UNKNOWN", raised.exception.code)

    def test_apply_overrides_merges_into_portrayal_contract(self):
        from carto_core.scenarios.leadership_visit.request_contract import REQUEST_CONTRACT
        self.assertEqual(("map_title", "style_overrides"), REQUEST_CONTRACT.override_keys())
        request = self._request_with_override()
        contracts = deepcopy(self.contracts)
        REQUEST_CONTRACT.apply_overrides(request, contracts)
        self.assertEqual(
            "#228833", contracts["portrayal"]["image_itinerary"]["groups"][0]["color"])
        # The fixture's template contract itself stays untouched (merge copies).
        self.assertEqual(
            "#1769D2", self.contracts["portrayal"]["image_itinerary"]["groups"][0]["color"])
        # A template without an image_itinerary section cannot be overridden.
        with self.assertRaises(ProtocolError) as raised:
            REQUEST_CONTRACT.apply_overrides({"style_overrides": {"pin": {"radius_px": 20}}},
                                             {"portrayal": {}})
        self.assertEqual("LEADERSHIP_STYLE_CONTRACT_MISSING", raised.exception.code)

    def _compile(self, request, contracts):
        plan = RoutePlanner().build(request, self.intent, self.brief, self.bundle,
                                    self.installation, contracts)
        compiler = RouteCandidateCompiler(self.guard, self.registry, project_root=self.root,
                                          context=ExecutionContext.from_generate_request(request))
        return compiler.compile(request, self.intent, plan, self.bundle, self.installation,
                                contracts, self.font_path)

    def test_style_overrides_reach_graphics_and_legend(self):
        from carto_core.scenarios.leadership_visit.request_contract import REQUEST_CONTRACT
        # Regression anchor: applying the override hook (map_title only, no
        # style_overrides) compiles byte-identically to bypassing the hook —
        # the hook is inert for requests without a style patch.
        baseline = self._compile(self.request, deepcopy(self.contracts))
        hooked_contracts = deepcopy(self.contracts)
        REQUEST_CONTRACT.apply_overrides(self.request, hooked_contracts)
        hooked = self._compile(self.request, hooked_contracts)
        self.assertEqual(sha256_digest(baseline["scene"]), sha256_digest(hooked["scene"]))
        # Override path: patched color and width reach the frozen graphics.
        request = self._request_with_override()
        contracts = deepcopy(self.contracts)
        REQUEST_CONTRACT.apply_overrides(request, contracts)
        compiled = self._compile(request, contracts)
        scene = compiled["scene"]
        self.assertNotEqual(sha256_digest(baseline["scene"]), sha256_digest(scene))
        points = {g["visit_order"]: g for g in scene["image_graphics"]
                  if g["type"] == "point" and g.get("group") == "morning"}
        self.assertEqual("#228833", points[1]["color"])
        callouts = {tuple(g["stop_orders"]): g for g in scene["image_graphics"]
                    if g["type"] == "callout"}
        self.assertEqual("#228833", callouts[(1,)]["color"])
        lines = [g for g in scene["image_graphics"] if g["type"] == "line"]
        self.assertTrue(lines)
        for line in lines:
            self.assertEqual(9, line["width_px"])
        # Legend colors derive from the same merged groups contract.
        page = load_document(self.guard.resolve(scene["page_request_ref"]["uri"]))
        legend = page["legends"][0]["items"]
        morning = next(item for item in legend if item["id"] == "legend-item-1")
        self.assertEqual("#228833", morning["color"])
        # Baseline (template) colours for the untouched group remain authoritative.
        default_pin = next(g for g in scene["image_graphics"]
                           if g["type"] == "point" and g.get("group") == "default")
        self.assertEqual("#403B96", default_pin["color"])


FURNITURE = {
    "title_font_pt": 26,
    "body_font_pt": 8,
    "frame_border": {"color": "#000000", "inner_width_mm": 0.5, "gap_mm": 1.2,
                     "outer_width_mm": 1.0},
}


class PageFurnitureTests(LeadershipFixture, unittest.TestCase):
    """Phase 1.5 (migration backfill, option A): page-domain furniture (title/body
    fonts, map frame border) lives in the style contract's page_furniture section,
    freezes into the page request, and is consumed by BOTH renderers through the
    SHARED image_layout derivations."""

    def _compile_with_furniture(self, furniture_patch):
        """Compile through the real request path: the furniture patch enters as a
        request-level style_overrides (Phase 1 mechanism), so the request digest —
        and therefore the authoritative map-document filename — varies with it."""
        from carto_core.scenarios.leadership_visit.request_contract import REQUEST_CONTRACT
        request = json.loads(json.dumps(self.request))
        if furniture_patch is None:
            request.pop("style_overrides", None)
        else:
            request["style_overrides"] = {"page_furniture": furniture_patch}
            self.registry.validate("leadership-visit-generate-request", request)
        contracts = deepcopy(self.contracts)
        REQUEST_CONTRACT.apply_overrides(request, contracts)
        plan = RoutePlanner().build(request, self.intent, self.brief, self.bundle,
                                    self.installation, contracts)
        compiler = RouteCandidateCompiler(self.guard, self.registry, project_root=self.root,
                                          context=ExecutionContext.from_generate_request(request))
        return compiler.compile(request, self.intent, plan, self.bundle, self.installation,
                                contracts, self.font_path)

    def test_style_and_override_schemas_admit_page_furniture(self):
        styled = deepcopy(STYLE)
        styled["page_furniture"] = FURNITURE
        self.registry.validate("image-itinerary-style", styled)
        self.registry.validate("image-itinerary-style-override",
                               {"page_furniture": {"title_font_pt": 26}})
        self.registry.validate("image-itinerary-style-override",
                               {"page_furniture": {"frame_border": {"color": "#123456"}}})
        for bad in ({"page_furniture": {"title_font_pt": 100}},
                    {"page_furniture": {"frame_border": {"color": "#12345"}}},
                    {"page_furniture": {"frame_border": {"inner_width_mm": 0}}}):
            with self.assertRaises(ProtocolError):
                self.registry.validate("image-itinerary-style-override", bad)

    def test_merge_patches_page_furniture_keywise(self):
        from carto_core.scenarios.leadership_visit.request_contract import _merge_style_override
        # Patch onto a template WITHOUT page_furniture: the section appears.
        merged = _merge_style_override(STYLE, {"page_furniture": {"title_font_pt": 26}})
        self.assertEqual({"title_font_pt": 26}, merged["page_furniture"])
        # Patch onto a template WITH furniture: frame_border merges key-wise,
        # unmentioned keys (and the rest of the style) preserved.
        template = deepcopy(STYLE)
        template["page_furniture"] = deepcopy(FURNITURE)
        merged = _merge_style_override(template, {
            "page_furniture": {"frame_border": {"color": "#FF0000"}}})
        border = merged["page_furniture"]["frame_border"]
        self.assertEqual("#FF0000", border["color"])
        self.assertEqual(FURNITURE["frame_border"]["inner_width_mm"], border["inner_width_mm"])
        self.assertEqual(FURNITURE["frame_border"]["gap_mm"], border["gap_mm"])
        self.assertEqual(FURNITURE["frame_border"]["outer_width_mm"], border["outer_width_mm"])
        self.assertEqual(FURNITURE["title_font_pt"], merged["page_furniture"]["title_font_pt"])
        self.assertEqual(STYLE["callout"], merged["callout"])
        self.registry.validate("image-itinerary-style", merged)

    def test_compile_freezes_furniture_into_page_request(self):
        compiled = self._compile_with_furniture(FURNITURE)
        page = load_document(self.guard.resolve(compiled["scene"]["page_request_ref"]["uri"]))
        self.assertEqual(26, page["texts"][0]["font_pt"])
        self.assertEqual(8, page["texts"][1]["font_pt"])
        self.assertEqual(FURNITURE["frame_border"], page["furniture"]["frame_border"])
        # Absent furniture: no font_pt, no furniture node (renderers fall back).
        plain = self._compile_with_furniture(None)
        plain_page = load_document(self.guard.resolve(plain["scene"]["page_request_ref"]["uri"]))
        self.assertNotIn("font_pt", plain_page["texts"][0])
        self.assertNotIn("furniture", plain_page)

    def _furniture_text_feature(self, document, text):
        return next(f for f in document["canvasData"]["features"]
                    if f["type"] == "Text" and f["text"] == text)

    def test_frontend_document_consumes_shared_derivation_and_border(self):
        from carto_core.adapters.image_layout import frame_border_rects, furniture_font_pt
        compiled = self._compile_with_furniture(FURNITURE)
        scene, document = compiled["scene"], compiled["frontend_document"]
        dpi = scene["export"]["dpi"]
        pt_per_px = 72 / dpi
        page = load_document(self.guard.resolve(scene["page_request_ref"]["uri"]))
        frames = {f["content_id"]: f for f in scene["resolved_layout"]["frames"]
                  if f["type"] != "map"}
        # Title text: fontSize equals the SHARED derivation (26pt nominal fits the
        # frame, so the full nominal applies) expressed in document millimetres.
        bounds = frames["title"]["bounds_px"]
        expected_pt = furniture_font_pt(page["texts"][0], tuple(bounds), pt_per_px)
        self.assertEqual(26.0, expected_pt)
        title = self._furniture_text_feature(document, page["texts"][0]["text"])
        self.assertAlmostEqual(expected_pt * 25.4 / 72, title["fontSize"], places=3)
        # Explicit size never bypasses the frame-capacity gate: a huge nominal is
        # capped to the fit width.
        huge_compiled = self._compile_with_furniture({"title_font_pt": 72})
        huge_page = load_document(
            self.guard.resolve(huge_compiled["scene"]["page_request_ref"]["uri"]))
        capped_pt = furniture_font_pt(huge_page["texts"][0], tuple(bounds), pt_per_px)
        self.assertLess(capped_pt, 72.0)
        huge_title = self._furniture_text_feature(
            huge_compiled["frontend_document"], huge_page["texts"][0]["text"])
        self.assertAlmostEqual(capped_pt * 25.4 / 72, huge_title["fontSize"], places=3)
        # Frame border: two stroke-only Rect features with the SHARED geometry.
        rects = [f for f in document["canvasData"]["features"]
                 if f["type"] == "Rect" and f.get("fillColor") == "none"]
        self.assertEqual(2, len(rects))
        by_width = {f["strokeWidth"]: f for f in rects}
        self.assertEqual({0.5, 1.0}, set(by_width))
        for feature in rects:
            self.assertEqual("#000000", feature["strokeColor"])
        mm_x = document["designWidth"] / scene["viewport"]["width_px"]
        mm_y = document["designHeight"] / scene["viewport"]["height_px"]
        placement = compiled["projection"]["placement"]
        inner, outer = frame_border_rects(placement, FURNITURE["frame_border"], dpi / 25.4)
        self.assertAlmostEqual(inner["x"] * mm_x, by_width[0.5]["x"], places=3)
        self.assertAlmostEqual(inner["y"] * mm_y, by_width[0.5]["y"], places=3)
        self.assertAlmostEqual(outer["x"] * mm_x, by_width[1.0]["x"], places=3)
        offset_mm = 1.2 + (0.5 + 1.0) / 2
        self.assertAlmostEqual((inner["x"] - offset_mm * dpi / 25.4) * mm_x,
                               by_width[1.0]["x"], places=3)

    def test_pdf_renderer_draws_border_and_keeps_fallback(self):
        """The PDF side draws the frozen border (visual change vs the fallback
        render) and compiles without furniture identically to the pre-1.5
        behaviour (fallback = historical 18/9pt nominals)."""
        with_border = self._compile_with_furniture(FURNITURE)
        without_border = self._compile_with_furniture(None)
        outputs = {}
        for name, compiled in (("border", with_border), ("plain", without_border)):
            output_root = self.root / ("work-furniture-" + name)
            renderer = ImagePageRenderer(path_guard=self.guard, output_root=output_root,
                                         attestation_key=b"0" * 40, registry=self.registry)
            receipt = renderer.render("session-" + name, compiled["scene"])
            self.registry.validate("render-receipt", receipt)
            png = next(Path(item["artifact_ref"]["uri"]) for item in receipt["output_artifacts"]
                       if item["target"] == "png")
            outputs[name] = png.read_bytes()
        self.assertNotEqual(outputs["border"], outputs["plain"])
        # The fallback path is deterministic: rerendering the plain scene is
        # byte-stable (regression anchor for the no-furniture behaviour).
        output_root = self.root / "work-furniture-plain-2"
        renderer = ImagePageRenderer(path_guard=self.guard, output_root=output_root,
                                     attestation_key=b"0" * 40, registry=self.registry)
        receipt = renderer.render("session-plain-2", without_border["scene"])
        png = next(Path(item["artifact_ref"]["uri"]) for item in receipt["output_artifacts"]
                   if item["target"] == "png")
        self.assertEqual(outputs["plain"], png.read_bytes())


class LegendConsistencyTests(LeadershipFixture, unittest.TestCase):
    """Legacy fix ①: the legend block shares ONE derivation
    (image_layout.legend_font_pt) across both renderers. The frontend's former
    mm-as-px mix-up collapsed legend text to ~1pt with overlapping rows while
    the PDF rendered ~8.5pt from the same frozen page."""

    def _compiled(self):
        plan = RoutePlanner().build(self.request, self.intent, self.brief, self.bundle,
                                    self.installation, self.contracts)
        compiler = RouteCandidateCompiler(self.guard, self.registry, project_root=self.root,
                                          context=ExecutionContext.from_generate_request(self.request))
        return compiler.compile(self.request, self.intent, plan, self.bundle, self.installation,
                                self.contracts, self.font_path)

    def test_legend_font_and_layout_match_shared_derivation(self):
        from carto_core.adapters.image_layout import legend_font_pt
        compiled = self._compiled()
        scene, document = compiled["scene"], compiled["frontend_document"]
        page = load_document(self.guard.resolve(scene["page_request_ref"]["uri"]))
        frames = {f["content_id"]: f for f in scene["resolved_layout"]["frames"]
                  if f["type"] != "map"}
        dpi = scene["export"]["dpi"]
        pt_per_px = 72 / dpi
        mm_x = document["designWidth"] / scene["viewport"]["width_px"]
        legend = page["legends"][0]
        bounds = frames["legend"]["bounds_px"]
        font_pt = legend_font_pt(legend, tuple(bounds), pt_per_px)
        # The nominal cap (3mm = 8.504pt) fits the fixture frame, so the legend
        # renders at the full nominal — ~8.5pt, not the former ~1.1pt collapse.
        self.assertAlmostEqual(8.504, font_pt, places=2)
        labels = {item["label"] for item in legend["items"]}
        texts = [f for f in document["canvasData"]["features"]
                 if f["type"] == "Text" and (f["text"] == legend["title"]
                                             or f["text"] in labels)]
        self.assertEqual(1 + len(legend["items"]), len(texts))
        for feature in texts:
            self.assertAlmostEqual(font_pt * 25.4 / 72, feature["fontSize"], places=3)
        # Rows follow the shared font spacing (visibly separated, not stacked).
        mm_y = document["designHeight"] / scene["viewport"]["height_px"]
        entries = sorted((f for f in texts if f["text"] != legend["title"]),
                         key=lambda f: f["y"])
        if len(entries) >= 2:
            spacing = entries[1]["y"] - entries[0]["y"]
            self.assertAlmostEqual(font_pt / pt_per_px * 1.5 * mm_y, spacing, places=3)
            self.assertGreater(spacing, 2.0)


class CompilerTests(LeadershipFixture, unittest.TestCase):
    def _plan(self):
        return RoutePlanner().build(self.request, self.intent, self.brief, self.bundle,
                                    self.installation, self.contracts)

    def test_planner_build_map_plan_schema(self):
        plan = self._plan()
        self.registry.validate("map-plan", plan)
        self.assertEqual("image-itinerary-page", plan["decisions"]["renderer_id"])
        self.assertEqual(2, len(plan["data_bindings"]))
        self.assertEqual(sha256_digest(self.intent), plan["intent_ref"]["digest"])
        self.assertEqual(sha256_digest(self.brief), plan["brief_ref"]["digest"])

    def test_candidate_compiler_scene(self):
        plan = self._plan()
        compiler = RouteCandidateCompiler(self.guard, self.registry, project_root=self.root,
                                          context=ExecutionContext.from_generate_request(self.request))
        compiled = compiler.compile(self.request, self.intent, plan, self.bundle, self.installation,
                                    self.contracts, self.font_path)
        scene, candidate = compiled["scene"], compiled["candidate"]
        self.registry.validate("render-scene", scene)
        self.registry.validate("resolved-map", candidate)
        self.assertEqual("image-itinerary-page", scene["renderer_id"])
        self.assertTrue(scene["image_graphics"])
        self.assertEqual("image", load_document(
            self.guard.resolve(scene["page_request_ref"]["uri"]))["geometry"])
        self.assertEqual(candidate["execution_digest"], sha256_digest(candidate["execution"]))
        self.assertEqual(candidate["execution"]["render_scene_ref"]["digest"], sha256_digest(scene))
        self.assertEqual(candidate["execution"]["business_scene"], "leadership_visit")
        # The migrated algorithms ran as authorized ToolGateway capabilities: one
        # ToolResult receipt each (projection, display, annotation solver) with
        # immutable evidence artifacts frozen into the scene as contract resources.
        receipts = {item["capability_id"]: item for item in compiled["tool_receipts"]}
        self.assertEqual({"geo-to-image-pixels", "image-display-bounds", "annotation-layout"},
                         set(receipts))
        for capability, receipt in receipts.items():
            self.assertEqual("succeeded", receipt["status"])
            self.assertTrue(receipt["artifact_refs"])
            evidence = Path(receipt["artifact_refs"][0]["uri"])
            self.assertTrue(evidence.is_file(), capability)
            self.assertEqual(receipt["output_digest"], sha256_digest(load_document(evidence)))
        resource_ids = {item["id"] for item in scene["resources"]}
        self.assertTrue({"tool-geo-to-image-pixels", "tool-image-display-bounds",
                         "tool-annotation-layout"} <= resource_ids)
        self.assertTrue((self.root / ".carto" / "image" / "evidence").is_dir())
        compiler.verify_request(self.request, scene, None)

    def test_candidate_compiler_rejects_basemap_drift(self):
        plan = self._plan()
        compiler = RouteCandidateCompiler(self.guard, self.registry, project_root=self.root,
                                          context=ExecutionContext.from_generate_request(self.request))
        compiled = compiler.compile(self.request, self.intent, plan, self.bundle, self.installation,
                                    self.contracts, self.font_path)
        drifted = json.loads(json.dumps(self.request))
        drifted["basemap"]["image_ref"]["digest"] = "sha256:" + "1" * 64
        with self.assertRaises(ProtocolError) as raised:
            compiler.verify_request(drifted, compiled["scene"], None)
        self.assertEqual("IMAGE_SCENE_BASEMAP_DRIFT", raised.exception.code)

    def test_candidate_compiler_rejects_scope_mismatch(self):
        plan = self._plan()
        other = dict(self.request)
        other["run_id"] = "another-run"
        compiler = RouteCandidateCompiler(self.guard, self.registry, project_root=self.root,
                                          context=ExecutionContext.from_generate_request(self.request))
        with self.assertRaises(ProtocolError) as raised:
            compiler.compile(other, self.intent, plan, self.bundle, self.installation,
                             self.contracts, self.font_path)
        self.assertIn(raised.exception.code, {"IMAGE_SCOPE_MISMATCH", "SCHEMA_VALIDATION_FAILED"})

    def test_kernel_compile_wrapper_runs_preflight(self):
        """The kernel MapCandidateCompiler wrapper drives the scenario compiler and
        recomputes the preflight (G2 binds actual gates, policy and inputs)."""
        from carto_core.compiler.map_candidate import MapCandidateCompiler
        from carto_core.workflow.material_evidence import verify_material_facts
        from copy import deepcopy
        gates = {"schema_version": 1,
                 "baseline": {"id": "quality-gates", "version": "1.0.0", "digest": "sha256:" + "0" * 64},
                 "checks": [{"id": "protocol.schema-valid", "version": "1.0.0", "params": {}}]}
        contracts = deepcopy(self.contracts)
        contracts["quality_gates"] = gates
        compiler = MapCandidateCompiler(self.guard, self.registry, project_root=self.root,
                                        context=ExecutionContext.from_generate_request(self.request),
                                        material_facts=verify_material_facts)
        plan = RoutePlanner().build(self.request, self.intent, self.brief, self.bundle,
                                    self.installation, contracts)
        compiled = compiler.compile(self.request, self.intent, plan, self.bundle, self.installation,
                                    contracts, self.font_path)
        self.assertEqual("passed", compiled["preflight"]["status"])
        self.assertEqual(["protocol.schema-valid"],
                         [item["check_id"] for item in compiled["preflight"]["results"]])
        self.assertTrue(compiled["scene"]["image_graphics"])


class ImageToolGatewayTests(LeadershipFixture, unittest.TestCase):
    """The migrated image algorithms execute only as authorized ToolGateway capabilities.

    Deny-by-default policy, typed I/O schemas, digest re-verification inside the
    handler, ToolResult evidence artifacts and budget accounting — the same
    contract as gis-raster-statistics on the raster route.
    """

    def _gateway(self):
        from carto_core.adapters.image_tools import make_image_gateway
        from carto_core.repository.immutable_store import ImmutableArtifactStore
        store = ImmutableArtifactStore(self.root / ".carto" / "image" / "evidence",
                                       path_guard=PathGuard([self.root]))
        return make_image_gateway(store, self.registry, guard=self.guard, project_root=self.root)

    def _context(self, capabilities):
        request = dict(self.request)
        request["allowed_capabilities"] = sorted(capabilities)
        return ExecutionContext.from_generate_request(request)

    def _projection_input(self):
        return {
            "schema_version": 1,
            "image_ref": {"id": "basemap-image", "version": "1.0.0",
                          "digest": self.image_digest, "uri": "basemap.png"},
            "parameters_ref": {"id": "registration-parameters", "version": "1.0.0",
                               "digest": sha256_digest(self.parameters), "uri": "registration.yaml"},
            "stops_ref": {"id": "prepared-route-stops", "version": "1.0.0",
                          "digest": sha256_digest(self.stops_fc),
                          "uri": "data/prepared/route-stops.geojson"},
            "route_ref": {"id": "prepared-route-line", "version": "1.0.0",
                          "digest": sha256_digest(self.route_fc),
                          "uri": "data/prepared/route-line.geojson"},
        }

    def test_projection_capability_binds_evidence(self):
        gateway = self._gateway()
        context = self._context({"read", "geo-to-image-pixels"})
        typed = self._projection_input()
        receipt = gateway.invoke("geo-to-image-pixels", typed, context)
        self.assertEqual("succeeded", receipt.status)
        self.assertEqual("geo-to-image-pixels", receipt.capability_id)
        self.assertEqual(sha256_digest(typed), receipt.input_digest)
        document = load_document(Path(receipt.artifact_refs[0]["uri"]))
        self.assertEqual(3, len(document["stops"]))
        self.assertEqual(2, len(document["routes"]))
        self.assertEqual(sha256_digest(document), receipt.output_digest)
        self.assertEqual("registered-affine", document["method"])

    def test_display_capability_measures_window(self):
        gateway = self._gateway()
        context = self._context({"read", "image-display-bounds"})
        typed = {"schema_version": 1,
                 "image_ref": {"id": "basemap-image", "version": "1.0.0",
                               "digest": self.image_digest, "uri": "basemap.png"},
                 "white_threshold": 245}
        receipt = gateway.invoke("image-display-bounds", typed, context)
        document = load_document(Path(receipt.artifact_refs[0]["uri"]))
        self.assertEqual({"x": 60, "y": 60, "width": 2261, "height": 1561},
                         document["display_window"])
        self.assertEqual({"width_px": 2381, "height_px": 1684}, document["source_size"])

    def test_unauthorized_capability_is_denied(self):
        gateway = self._gateway()
        context = self._context({"read"})
        with self.assertRaises(SecurityError) as raised:
            gateway.invoke("geo-to-image-pixels", self._projection_input(), context)
        self.assertEqual("CAPABILITY_SCOPE_DENIED", raised.exception.code)

    def test_input_drift_is_rejected(self):
        gateway = self._gateway()
        context = self._context({"read", "geo-to-image-pixels"})
        typed = self._projection_input()
        typed["image_ref"] = {**typed["image_ref"], "digest": "sha256:" + "1" * 64}
        with self.assertRaises(ProtocolError) as raised:
            gateway.invoke("geo-to-image-pixels", typed, context)
        self.assertEqual("IMAGE_TOOL_INPUT_DRIFT", raised.exception.code)

    def test_annotation_requires_the_capability_grant(self):
        plan = RoutePlanner().build(self.request, self.intent, self.brief, self.bundle,
                                    self.installation, self.contracts)
        request = deepcopy(self.request)
        request["allowed_capabilities"] = ["read", "render-preview",
                                           "geo-to-image-pixels", "image-display-bounds"]
        compiler = RouteCandidateCompiler(self.guard, self.registry, project_root=self.root,
                                          context=ExecutionContext.from_generate_request(request))
        with self.assertRaises(SecurityError) as raised:
            compiler.compile(request, self.intent, plan, self.bundle, self.installation,
                             self.contracts, self.font_path)
        self.assertEqual("CAPABILITY_SCOPE_DENIED", raised.exception.code)

    def test_data_summary_capability_inventories_a_directory(self):
        from carto_core.adapters.image_tools import make_data_summary_gateway
        from carto_core.repository.immutable_store import ImmutableArtifactStore
        source = self.root / "data-src"
        source.mkdir(parents=True, exist_ok=True)
        (source / "notes.txt").write_text("第一站 甲地", encoding="utf-8")
        atomic_json(source / "stops.geojson", self.stops_fc)
        store = ImmutableArtifactStore(self.root / ".carto" / "data" / "evidence",
                                       path_guard=PathGuard([self.root]))
        gateway = make_data_summary_gateway(store, self.registry, guard=self.guard,
                                            project_root=self.root)
        context = self._context({"data-summary"})
        typed = {"schema_version": 1, "data_dir": "data-src"}
        receipt = gateway.invoke("data-summary", typed, context)
        document = load_document(Path(receipt.artifact_refs[0]["uri"]))
        self.assertEqual(2, document["file_count"])
        self.assertEqual({"document", "geographic-vector"},
                         {item["category"] for item in document["categories"]})
        self.assertIn("数据目录内容", document["summary_md"])


class RendererTests(CompilerTests):
    def _compiled(self):
        plan = self._plan()
        compiler = RouteCandidateCompiler(self.guard, self.registry, project_root=self.root,
                                          context=ExecutionContext.from_generate_request(self.request))
        return compiler.compile(self.request, self.intent, plan, self.bundle, self.installation,
                                self.contracts, self.font_path)

    def test_image_page_renderer_render_and_receipt(self):
        compiled = self._compiled()
        scene = compiled["scene"]
        output_root = self.root / "work" / "render"
        renderer = ImagePageRenderer(path_guard=self.guard, output_root=output_root,
                                     attestation_key=b"0" * 40, registry=self.registry)
        renderer.validate_scene(scene)
        texts = renderer.scene_texts(scene)
        self.assertIn("编制领导调研行程路线图", texts)
        receipt = renderer.render("map-preview-candidate-test-run", scene)
        self.registry.validate("render-receipt", receipt)
        for item in receipt["output_artifacts"]:
            path = Path(item["artifact_ref"]["uri"])
            self.assertTrue(path.is_file(), item["target"])
            self.assertGreater(path.stat().st_size, 100, item["target"])
        renderer.validate_receipt(scene, receipt, expected_session_id="map-preview-candidate-test-run")
        headers = {item["target"]: Path(item["artifact_ref"]["uri"]).read_bytes()[:8]
                   for item in receipt["output_artifacts"]}
        self.assertEqual(b"\x89PNG\r\n\x1a\n", headers["png"])
        self.assertEqual(b"%PDF-1.4", headers["pdf"][:8])

    def test_route_line_passes_through_the_stops(self):
        """Pixel-level regression: the rendered route must land on the same page
        transform the pins use (guards against double-placement offsets)."""
        from PIL import Image
        from carto_core.adapters.image_layout import contain_layout
        from carto_core.adapters.route_display import display_points
        compiled = self._compiled()
        scene = compiled["scene"]
        page = load_document(self.guard.resolve(scene["page_request_ref"]["uri"]))
        window = page["basemap"]["display_window"]
        frame = LayoutResolver.map_frame(scene["resolved_layout"])
        frame_box = {key: value for key, value in zip(("x", "y", "width", "height"), frame["bounds_px"])}
        placement = contain_layout({"width_px": window["width"], "height_px": window["height"]}, frame_box)
        scale = placement["scale"]
        # Pin 1's page position under the CORRECT transform.
        pin = next(g for g in scene["image_graphics"] if g["type"] == "point" and g["visit_order"] == 1)
        pin_x = (pin["position"]["x"] * scale - window["x"] * scale + placement["x"])
        pin_y = (pin["position"]["y"] * scale - window["y"] * scale + placement["y"])
        # The first route line's drawn geometry must start at that same position
        # (tail anchor), i.e. within the stroke width of the pin anchor.
        line = next(g for g in scene["image_graphics"] if g["type"] == "line")
        drawn = display_points(line, scale, (window["x"] * scale, window["y"] * scale))
        start_x, start_y = drawn[0][0] + placement["x"], drawn[0][1] + placement["y"]
        tolerance = max(8.0, line.get("width_px", 4) * scale + line.get("right_offset_px", 0) * scale)
        self.assertLess(abs(start_x - pin_x), tolerance + 1e-6,
                        f"route start x {start_x} detached from pin x {pin_x}")
        self.assertLess(abs(start_y - pin_y), tolerance + 1e-6,
                        f"route start y {start_y} detached from pin y {pin_y}")
        # And the rendered PNG actually paints the pin at its projected position:
        # sample the head RING (between the white inner dot and the outer circle).
        output_root = self.root / "work" / "render-pin"
        renderer = ImagePageRenderer(path_guard=self.guard, output_root=output_root,
                                     attestation_key=b"0" * 40, registry=self.registry)
        renderer.render("pin-check", scene)
        image = Image.open(output_root / "pin-check" / "map.png").convert("RGB")
        radius = pin.get("radius_px", 12) * scale
        sample_x = int(round(pin_x + radius * 0.8))
        sample_y = int(round(pin_y - 2 * radius))
        pixel = image.getpixel((sample_x, sample_y))
        pin_color = pin.get("color", "#C41E3A").lstrip("#")
        expected = tuple(int(pin_color[i:i + 2], 16) for i in (0, 2, 4))
        self.assertTrue(all(abs(a - b) < 40 for a, b in zip(pixel, expected)),
                        f"pin not painted at its projected position: {pixel} vs {expected}")

    def test_image_page_renderer_rejects_foreign_renderer(self):
        compiled = self._compiled()
        scene = json.loads(json.dumps(compiled["scene"]))
        scene["renderer_id"] = "maplibre-web"
        renderer = ImagePageRenderer(path_guard=self.guard, output_root=self.root / "work" / "render",
                                     attestation_key=b"0" * 40, registry=self.registry)
        with self.assertRaises(ProtocolError):
            renderer.validate_scene(scene)

    def test_frontend_document_build(self):
        compiled = self._compiled()
        scene = compiled["scene"]
        page = load_document(self.guard.resolve(scene["page_request_ref"]["uri"]))
        document = FrontendDocumentBuilder(self.registry).build(
            scene, page, identifier="map-scene-test-run", name="领导调研行程路线图 test")
        self.registry.validate("frontend-map-document", document)
        # The document IS the canvas payload: no {code, msg, data} envelope.
        self.assertNotIn("code", document)
        self.assertNotIn("data", document)
        data = document
        self.assertEqual(420.0, data["designWidth"])
        self.assertEqual(297.0, data["designHeight"])
        types = {f["type"] for f in data["canvasData"]["features"]}
        self.assertIn("MultiLineString", types)
        self.assertIn("MultiPoint", types)
        self.assertIn("Rect", types)
        layer_ids = {layer["id"] for layer in data["canvasData"]["mapData"]["layers"]}
        self.assertEqual({"basemap", "route-layer", "stops", "furniture"}, layer_ids)


CONTRACT_ITINERARY = {
    "schema_version": 1, "itinerary_id": "itinerary-unit", "date_label": "11月18日（星期三）",
    "input_crs": "EPSG:4326",
    "places": [
        {"place_id": "place-a", "name": "甲地大院", "location": {"lon": 120.0, "lat": 30.0}},
        {"place_id": "place-b", "name": "乙地产业园", "location": {"lon": 120.02, "lat": 29.98}},
        {"place_id": "place-c", "name": "丙地餐厅", "location": {"lon": 119.98, "lat": 30.02}},
    ],
    "stops": [
        {"stop_id": "stop-01", "place_id": "place-a",
         "activities": [{"activity_id": "a1", "type": "departure", "period": "morning",
                         "start_time": "09:00"}], "departure_time": "09:00"},
        {"stop_id": "stop-02", "place_id": "place-b",
         "activities": [{"activity_id": "a2", "type": "visit", "period": "morning",
                         "duration_min": 45}], "arrival_time": "09:45"},
        {"stop_id": "stop-03-meal", "place_id": "place-c",
         "activities": [{"activity_id": "a3", "type": "meal_and_rest", "period": "morning"}],
         "arrival_time": "12:45"},
        {"stop_id": "stop-03-visit", "place_id": "place-c",
         "activities": [{"activity_id": "a4", "type": "meeting", "period": "afternoon"}]},
    ],
    "legs": [
        {"leg_id": "leg-01", "kind": "travel", "from_stop_id": "stop-01", "to_stop_id": "stop-02",
         "period": "morning", "route_mode": "road_network", "metric_source": "document",
         "document_metrics": {"distance_km": 43, "duration_min": 45},
         "routing_metrics": {"distance_km": 42.48, "duration_min": 56.6},
         "geometry": {"type": "LineString", "coordinates": [[120.0, 30.0], [120.01, 29.99],
                                                             [120.02, 29.98]]}},
        {"leg_id": "leg-02", "kind": "travel", "from_stop_id": "stop-02",
         "to_stop_id": "stop-03-meal", "period": "morning", "route_mode": "road_network",
         "metric_source": "routing", "document_metrics": {"distance_km": 113, "duration_min": 120},
         "routing_metrics": {"distance_km": 158.74, "duration_min": 211.6},
         "geometry": {"type": "LineString", "coordinates": [[120.02, 29.98], [120.0, 30.0],
                                                             [119.98, 30.02]]}},
        {"leg_id": "leg-03", "kind": "stay", "from_stop_id": "stop-03-meal",
         "to_stop_id": "stop-03-visit", "metric_source": "none"},
    ],
    "source_blocks": [],
}


class DataPreparerTests(LeadershipFixture, unittest.TestCase):
    """The MCP itinerary service's contract format feeds the preparer directly."""

    def _prepare(self, itinerary):
        from carto_core.scenarios.leadership_visit.data_preparer import RouteDataPreparer
        source = self.root / "data" / "itinerary-contract.json"
        source.write_text(json.dumps(itinerary, ensure_ascii=False), encoding="utf-8")
        request = json.loads(json.dumps(self.request))
        request["itinerary_structure"]["source_ref"]["uri"] = "data/itinerary-contract.json"
        request["itinerary_structure"]["source_ref"]["digest"] = sha256_digest(itinerary)
        preparer = RouteDataPreparer(self.guard, self.root, self.root / "work-contract", self.registry)
        return preparer.prepare(request, {"id": "generate-request", "version": "1.0.0",
                                          "digest": sha256_digest(request)})

    def test_contract_format_flattens_and_merges_stays(self):
        bundle = self._prepare(CONTRACT_ITINERARY)
        stops = load_document(self.root / "work-contract" / "prepared" / "route-stops.geojson")
        self.assertEqual(3, len(stops["features"]))
        props = [f["properties"] for f in stops["features"]]
        # Stay merge: meal + meeting at place-c become one stop (order 3).
        self.assertEqual(["甲地大院", "乙地产业园", "丙地餐厅"],
                         [p["stop_name"] for p in props])
        self.assertEqual([1, 2, 3], [p["visit_order"] for p in props])
        # Display metrics: stop 2 uses the document source, stop 3 the routing source.
        self.assertEqual(43, props[1]["distance_km"])
        self.assertEqual(158.74, props[2]["distance_km"])
        # Period → group mapping; the merged stop takes the primary (meeting) period.
        self.assertEqual(["morning", "morning", "afternoon"],
                         [p["itinerary_group"] for p in props])
        self.assertEqual(["上午", "上午", "下午"], [p["visit_period"] for p in props])
        # map_role: first origin, last destination (merged stay), middle visit.
        self.assertEqual(["origin", "visit", "destination"], [p["map_role"] for p in props])
        # date label travels as visit_date.
        self.assertTrue(all(p["visit_date"] == "11月18日（星期三）" for p in props))
        # Route legs: travel legs only, real geometry passed through.
        route = load_document(self.root / "work-contract" / "prepared" / "route-line.geojson")
        self.assertEqual(2, len(route["features"]))
        for feature in route["features"]:
            self.assertEqual("road_network", feature["properties"]["route_mode"])
            self.assertEqual(3, len(feature["geometry"]["coordinates"]))
        self.assertEqual(["morning", "morning"],
                         [f["properties"]["itinerary_group"] for f in route["features"]])

    def test_contract_format_rejects_unresolved_place(self):
        broken = json.loads(json.dumps(CONTRACT_ITINERARY))
        broken["places"][0].pop("location")
        with self.assertRaises(ProtocolError) as raised:
            self._prepare(broken)
        self.assertEqual("LEADERSHIP_ITINERARY_LOCATION_UNRESOLVED", raised.exception.code)


class PendingSourceTests(LeadershipFixture, unittest.TestCase):
    """G1-后数据准备：source_plan 支持 pending 模式（itinerary 文件 G1 后才产出）."""

    def _pending_request(self):
        request = json.loads(json.dumps(self.request))
        # G1 前模式：设 pending，指向尚不存在的文件
        request["source_bindings"][0]["pending"] = True
        request["source_bindings"][0]["preparation"] = "mcp-itinerary-chain"
        request["source_bindings"][0]["path"] = "data/itinerary.json"
        request["itinerary_structure"]["source_ref"]["uri"] = "data/itinerary.json"
        return request

    def test_source_plan_skips_file_existence_in_pending_mode(self):
        from carto_core.scenarios.leadership_visit.request_contract import REQUEST_CONTRACT
        request = self._pending_request()
        plan = REQUEST_CONTRACT.source_plan(request, self.guard, self.root)
        # route-stops 条目声明 preparation，不绑定 path_digest
        stops_entry = next(e for e in plan if e["role"] == "route-stops")
        self.assertIn("preparation", stops_entry)
        self.assertEqual("mcp-itinerary-chain", stops_entry["preparation"])
        self.assertNotIn("path_digest", stops_entry)
        # basemap 条目仍绑定摘要（用户提供的原始材料）
        basemap_entry = next(e for e in plan if e["role"] == "basemap")
        self.assertIn("path_digest", basemap_entry)

    def test_source_plan_computes_digest_in_non_pending_mode(self):
        from carto_core.scenarios.leadership_visit.request_contract import REQUEST_CONTRACT
        # 非 pending 模式：文件已存在，正常计算摘要
        request = json.loads(json.dumps(self.request))
        request["source_bindings"][0]["path"] = "data/itinerary.json"
        plan = REQUEST_CONTRACT.source_plan(request, self.guard, self.root)
        stops_entry = next(e for e in plan if e["role"] == "route-stops")
        self.assertIn("path_digest", stops_entry)
        self.assertNotIn("preparation", stops_entry)

    def test_validate_body_accepts_pending_mode(self):
        from carto_core.scenarios.leadership_visit.request_contract import REQUEST_CONTRACT
        # G1 前无 itinerary.json，validate_body 不应拒绝
        request = self._pending_request()
        # itinerary.json 此时不存在（fixture 的 data/itinerary.json 存在，但 pending 标志
        # 告诉内核这个绑定是"将要处理"的，不要求文件存在）
        REQUEST_CONTRACT.validate_body(request)  # 不抛错即通过

    def test_data_preparer_friendly_error_when_pending_and_missing(self):
        from carto_core.scenarios.leadership_visit.data_preparer import RouteDataPreparer
        request = self._pending_request()
        # 指向一个确实不存在的文件
        request["itinerary_structure"]["source_ref"]["uri"] = "data/itinerary-not-yet.json"
        preparer = RouteDataPreparer(self.guard, self.root, self.root / "work-pending", self.registry)
        with self.assertRaises(ProtocolError) as raised:
            preparer.prepare(request, {"id": "generate-request", "version": "1.0.0",
                                      "digest": sha256_digest(request)})
        self.assertEqual("LEADERSHIP_ITINERARY_NOT_PREPARED", raised.exception.code)
        self.assertIn("MCP", raised.exception.message)

    def test_data_preparer_not_found_when_not_pending(self):
        from carto_core.scenarios.leadership_visit.data_preparer import RouteDataPreparer
        request = json.loads(json.dumps(self.request))
        request["itinerary_structure"]["source_ref"]["uri"] = "data/itinerary-missing.json"
        preparer = RouteDataPreparer(self.guard, self.root, self.root / "work-missing", self.registry)
        with self.assertRaises(ProtocolError) as raised:
            preparer.prepare(request, {"id": "generate-request", "version": "1.0.0",
                                      "digest": sha256_digest(request)})
        self.assertEqual("LEADERSHIP_ITINERARY_NOT_FOUND", raised.exception.code)


class AnnotationSolverTests(LeadershipFixture, unittest.TestCase):
    """Bounded greedy+annealing callout placement; fixed seed, no global RNG."""

    def _value(self, *, items=None, hard_lines=None, hard_boxes=None):
        return {
            "items": items or [
                {"id": "a", "anchor_x": 100.0, "anchor_y": 100.0, "w": 220.0, "h": 88.0},
                {"id": "b", "anchor_x": 800.0, "anchor_y": 900.0, "w": 220.0, "h": 88.0},
                {"id": "c", "anchor_x": 1600.0, "anchor_y": 400.0, "w": 220.0, "h": 88.0},
            ],
            "hard_lines": hard_lines or [{"points": [{"x": 0.0, "y": 500.0}, {"x": 2000.0, "y": 500.0}],
                                          "width_px": 6.0}],
            "hard_boxes": hard_boxes or [],
            "canvas": {"width": 2000.0, "height": 1500.0},
            "gap_px": 8.0, "seed": 7, "iterations": 200,
        }

    def test_solve_layout_places_all_annotations(self):
        value = self._value()
        result = solve_layout(value)
        self.assertEqual("placed", result["status"])
        self.assertEqual(7, result["seed"])
        self.assertTrue(check_layout(value, result))
        placed = [a for a in result["assignments"] if a["status"] == "placed"]
        self.assertEqual(3, len(placed))
        for a, b in zip(placed, placed[1:]):
            self.assertFalse(collides(a, b, value["gap_px"]))
        self.assertTrue(all(not RouteIndex(value["hard_lines"], value["gap_px"], value["canvas"]).collides(a)
                            for a in placed))

    def test_solve_layout_is_deterministic(self):
        value = self._value()
        self.assertEqual(solve_layout(value), solve_layout(self._value()))

    def test_check_layout_rejects_tampering(self):
        from carto_core.adapters.annotation_solver import check_layout as verify
        value = self._value()
        result = solve_layout(value)
        moved = json.loads(json.dumps(result))
        moved["assignments"][0]["dx"] += 10
        with self.assertRaises(ProtocolError) as raised:
            verify(value, moved)
        self.assertEqual("ANNOTATION_OFFSET_INVALID", raised.exception.code)
        wrong_seed = dict(result, seed=8)
        with self.assertRaises(ProtocolError) as raised:
            verify(value, wrong_seed)
        self.assertEqual("ANNOTATION_RESULT_INVALID", raised.exception.code)

    def test_fixed_annotations_cannot_move(self):
        value = self._value(items=[{"id": "a", "anchor_x": 100.0, "anchor_y": 100.0,
                                    "w": 220.0, "h": 88.0, "fixed": {"x": 300.0, "y": 300.0}}])
        result = solve_layout(value)
        placed = next(a for a in result["assignments"] if a["status"] == "placed")
        self.assertEqual((300.0, 300.0), (placed["x"], placed["y"]))


class LegendCheckerTests(CompilerTests):
    def _scene(self):
        plan = self._plan()
        compiler = RouteCandidateCompiler(self.guard, self.registry, project_root=self.root,
                                          context=ExecutionContext.from_generate_request(self.request))
        return compiler.compile(self.request, self.intent, plan, self.bundle, self.installation,
                                self.contracts, self.font_path)["scene"]

    def test_legend_checker_valid(self):
        from carto_core.scenarios.leadership_visit.legend_checker import route_legend_checker
        ok, details, disposition = route_legend_checker({"scene": self._scene()})
        self.assertTrue(ok, details)
        self.assertIsNone(disposition)
        self.assertEqual(3, details["stop_count"])
        self.assertEqual(3, details["callout_count"])
        self.assertEqual(["straight_line"], details["route_modes"])
        self.assertTrue(all(details["checks"].values()))

    def test_legend_checker_rejects_broken_visit_order(self):
        from carto_core.scenarios.leadership_visit.legend_checker import route_legend_checker
        scene = json.loads(json.dumps(self._scene()))
        points = [g for g in scene["image_graphics"] if g["type"] == "point"]
        points[2]["visit_order"] = 5
        ok, details, _ = route_legend_checker({"scene": scene})
        self.assertFalse(ok)
        self.assertFalse(details["checks"]["visit_order_sequential"])

    def test_legend_checker_rejects_color_conflict(self):
        from carto_core.scenarios.leadership_visit.legend_checker import route_legend_checker
        scene = json.loads(json.dumps(self._scene()))
        for graphic in scene["image_graphics"]:
            if graphic["type"] == "point" and graphic.get("group") == "default":
                graphic["color"] = "#1769D2"  # collides with the morning group color
        ok, details, _ = route_legend_checker({"scene": scene})
        self.assertFalse(ok)
        self.assertFalse(details["checks"]["group_colors_consistent"])

    def test_legend_checker_rejects_missing_callout(self):
        from carto_core.scenarios.leadership_visit.legend_checker import route_legend_checker
        scene = json.loads(json.dumps(self._scene()))
        scene["image_graphics"] = [g for g in scene["image_graphics"]
                                   if not (g["type"] == "callout" and g.get("stop_orders") == [3])]
        ok, details, _ = route_legend_checker({"scene": scene})
        self.assertFalse(ok)
        self.assertFalse(details["checks"]["callout_coverage_exact"])


def _leadership_documents(style: dict | None = None, layout: dict | None = None) -> dict:
    """The closed leadership-visit template package documents — delegated to the
    scenario author's single content source (route_author.template_documents)."""
    from carto_core.scenarios.leadership_visit import route_author
    return route_author.template_documents(
        {"purpose": "领导调研行程路线图模板（合成验收）", "targets": ["pdf", "png"],
         "requested_at": "2026-11-19T00:00:00Z"})


class EndToEndWorkflowTests(LeadershipFixture, unittest.TestCase):
    """Synthetic end-to-end: intake -> brief -> G1 -> compile -> preview -> G2 ->
    freeze -> render -> check -> review -> G3 -> deliver through the real kernel
    workflow. Only repository discovery/installation is substituted with the exact
    authored package metadata (same seam as the general scenario's tests)."""

    def setUp(self) -> None:
        from carto_core.repository.staging_package import StagingPackageWriter
        from carto_core.compiler.map_candidate import MapCandidateCompiler
        from carto_core.workflow.map_generation import MapGenerationWorkflow
        from carto_core.repository.template_installer import ProjectTemplateInstaller
        from unittest.mock import patch
        # Per-test directories: the fixture tempdir is shared across classes, and
        # both the staging package writer (create-once) and the workflow's state
        # journal are not reset between tests — subclasses that add more
        # workflow-driving tests must not replay or collide with a sibling's
        # artifacts. (Class name included: an inherited test method has the same
        # method name in the subclass and would otherwise collide.)
        unique = "-".join(self.id().rsplit(".", 2)[-2:])
        template_work = self.root / f"template-work-{unique}"
        template_work.mkdir(parents=True, exist_ok=True)
        documents = _leadership_documents()
        manifest = {
            "schema_version": 1,
            "package": {"namespace": "local", "kind": "map-scenario", "id": "leadership-visit-map",
                        "version": "1.0.0", "status": "draft",
                        "summary": "领导调研行程路线图模板（合成验收）"},
            "business_contracts": {
                "scenario": "contracts/scenario.yaml", "data_schema": "contracts/data.schema.yaml",
                "spatial_behavior": "contracts/spatial-behavior.yaml",
                "portrayal": "contracts/portrayal.yaml", "delivery": "contracts/delivery.yaml",
                "quality_gates": "contracts/quality-gates.yaml"},
            "dependencies": [], "dependency_lock": "dependencies.lock.yaml",
            "targets": ["pdf", "png"],
        }
        package = StagingPackageWriter(self.guard, template_work, self.registry).write(manifest, documents)
        # contract_digest must match the installed manifest's business contract checksums.
        from carto_core.schema_registry import load_document as _load
        from dataclasses import asdict
        installed_manifest = _load(Path(package["package_path"]) / "manifest.yaml")
        self.installation = {
            "schema_version": 1, "installation_id": "installed-leadership-visit-map-1-0-0",
            "template_ref": {"kind": "map-scenario", "id": "leadership-visit-map",
                             "version": "1.0.0", "digest": package["package_digest"]},
            "namespace": "local", "manifest_digest": package["manifest_digest"],
            "package_path": package["package_path"],
            "contract_digest": sha256_digest({
                name: installed_manifest["checksums"][relative]
                for name, relative in installed_manifest["business_contracts"].items()}),
        }
        self.contracts = MapCandidateCompiler(self.guard, self.registry).load_contracts(self.installation)
        self.work = self.root / f"work-{unique}"
        self.work.mkdir(parents=True, exist_ok=True)
        repository_root = self.root / "template-repo"
        repository_root.mkdir(exist_ok=True)
        self.workflow = MapGenerationWorkflow(allowed_roots=[self.root], project_root=self.root,
                                              workdir=self.work, registry=self.registry,
                                              repository_root=repository_root,
                                              repository_scope="local:templates")
        for seam in (patch.object(self.workflow, "_verify_installed_template"),
                     patch.object(ProjectTemplateInstaller, "install",
                                  return_value=json.loads(json.dumps(self.installation)))):
            seam.start()
            self.addCleanup(seam.stop)
        # The request selects the authored template by exact digest, so the brief
        # step never needs repository discovery (publication is the L6 route).
        self.request = json.loads(json.dumps(self.request))
        self.request["template"]["digest"] = self.installation["template_ref"]["digest"]
        self.request_path = self.root / "generate-request.yaml"
        atomic_yaml(self.request_path, self.request)

    def _signed(self, name: str, action: str, kind: str, digest: str):
        from dataclasses import asdict
        from tests.test_general_thematic import sign
        from carto_core.artifacts import atomic_yaml as write_yaml
        path = self.root / (name + ".yaml")
        write_yaml(path, asdict(sign(name, action, kind, digest,
                                     subject_id=self.request["subject"]["approver_subject_id"],
                                     scope=self.request["scope"],
                                     tenant_id=self.request["subject"]["tenant_id"])),
                   create_once=False)
        return path

    def test_full_generation_workflow_delivers_pdf_png_and_map_document(self):
        from tests.test_general_thematic import APPROVAL_KEY, KEY
        intake = self.workflow.intake(self.request_path)
        self.assertEqual(self.intent, intake["intent"])
        briefed = self.workflow.brief(self.request_path)
        self.assertEqual("compile", briefed["state"]["step"])
        g1 = self._signed("g1", "approve-map-brief", "map-brief", briefed["approval_object_digest"])
        compiled = self.workflow.compile(self.request_path, g1, approval_key=APPROVAL_KEY)
        self.assertEqual("preview", compiled["state"]["step"])
        self.assertEqual("passed", compiled["preflight"]["status"])
        scene = load_document(self.work / "candidates/render-scene.yaml")
        self.assertTrue(scene["image_graphics"])
        # The frontend map document (成果本体) was produced at compile time...
        # (filename carries the request digest: revision-distinct, create-once safe)
        document_path = self.root / ".carto" / "image" / "map-documents" / (
            "map-test-run-" + sha256_digest(self.request)[7:23] + ".json")
        self.assertTrue(document_path.is_file())
        document = load_document(document_path)
        self.registry.validate("frontend-map-document", document)
        self.assertNotIn("code", document)
        self.assertEqual(420.0, document["designWidth"])
        preview = self.workflow.preview(self.request_path, attestation_key=KEY)
        # ...and the renderer wrote a byte-identical copy next to the preview outputs.
        preview_document = self.work / "previews" / "map-preview-candidate-test-run" / "map-document.json"
        self.assertTrue(preview_document.is_file(), str(preview_document))
        self.assertEqual(load_document(document_path), load_document(preview_document))
        g2 = self._signed("g2", "approve-freeze", "resolved-map", preview["approval_object_digest"])
        frozen = self.workflow.freeze(self.request_path, g2, approval_key=APPROVAL_KEY,
                                      attestation_key=KEY)
        self.assertEqual("render", frozen["state"]["step"])
        self.workflow.render(self.request_path, attestation_key=KEY)
        checked = self.workflow.check(self.request_path, attestation_key=KEY)
        self.assertEqual("passed", checked["validation_report"]["status"])
        args = dict(approval_key=APPROVAL_KEY, attestation_key=KEY,
                    recipient_id="synthetic-recipient", recipient_type="project-user",
                    destination="delivery/leadership-e2e", idempotency_key="leadership-e2e-0001")
        approval = self._signed("review", "approve-product-review", "validation-report",
                                sha256_digest(checked["validation_report"]))
        reviewed = self.workflow.review(self.request_path, approval, **args)
        g3 = self._signed("g3", "approve-delivery", "delivery-manifest",
                          reviewed["g3"]["object_digest"])
        delivered = self.workflow.deliver(self.request_path, g3, approval_key=APPROVAL_KEY)
        self.assertEqual("succeeded", delivered["state"]["status"])
        delivery = self.root / "delivery" / "leadership-e2e"
        for name in ("map.pdf", "map.png", "README.md", "delivery-manifest.yaml", "checksums.sha256"):
            self.assertTrue((delivery / name).is_file(), name)
        # The frontend document is NOT part of the formal delivery package.
        self.assertFalse((delivery / "map-document.json").exists())


class DesignRevisionTests(EndToEndWorkflowTests):
    """Phase 0: the design-revision loop runs end-to-end for the leadership
    scenario through the existing map_title vocabulary: propose -> new G1 ->
    revise -> bundle-reusing recompile -> new preview -> the OLD G2 no longer
    authorizes the revised design (a new G2 is required)."""

    def _document_path(self, request: dict) -> Path:
        return self.root / ".carto" / "image" / "map-documents" / (
            "map-test-run-" + sha256_digest(request)[7:23] + ".json")

    def test_map_title_revision_reuses_bundle_and_requires_new_g2(self):
        from tests.test_general_thematic import APPROVAL_KEY, KEY
        from unittest.mock import patch
        from carto_core.workflow import map_data_preparation
        intake = self.workflow.intake(self.request_path)
        briefed = self.workflow.brief(self.request_path)
        g1 = self._signed("g1", "approve-map-brief", "map-brief", briefed["approval_object_digest"])
        compiled = self.workflow.compile(self.request_path, g1, approval_key=APPROVAL_KEY)
        self.assertEqual("preview", compiled["state"]["step"])
        preview = self.workflow.preview(self.request_path, attestation_key=KEY)
        first_document = self._document_path(self.request)
        self.assertTrue(first_document.is_file(), str(first_document))
        first_bytes = first_document.read_bytes()
        old_g2 = self._signed("g2-old", "approve-freeze", "resolved-map",
                              preview["approval_object_digest"])
        # -- propose a map_title revision (the pre-existing legal vocabulary) --
        proposal = {"schema_version": 1, "proposal_id": "proposal-retitle",
                    "run_id": "test-run", "parent_revision": 1,
                    "changes": {"map_title": {"new_value": "领导调研路线图（修订版）"}},
                    "justification": "Synthetic design-revision acceptance"}
        proposal_path = self.root / "revision-proposal.yaml"
        atomic_yaml(proposal_path, proposal, create_once=False)
        revised_brief = self.workflow.revision_brief(self.request_path, proposal_path)
        self.assertEqual(2, revised_brief["brief"]["revision"])
        new_g1 = self._signed("g1-rev", "approve-map-brief", "map-brief",
                              revised_brief["approval_object_digest"])
        revised = self.workflow.revise(self.request_path, proposal_path, new_g1,
                                       approval_key=APPROVAL_KEY)
        revised_path = Path(revised["request_path"])
        self.assertEqual("compile", revised["state"]["step"])
        revised_request = load_document(revised_path)
        self.assertEqual("领导调研路线图（修订版）", revised_request["map_title"])
        # The revised artifacts land under revisions/r2/request/, never over the
        # originals in the initial design root.
        self.assertEqual("request", revised_path.parent.name)
        self.assertEqual("r2", revised_path.parent.parent.name)
        self.assertEqual("revisions", revised_path.parent.parent.parent.name)
        # -- the revised compile must skip data preparation: the bundle is reused --
        calls = []
        original = map_data_preparation.MapDataPreparer.prepare
        def spy(preparer, request, ref):
            calls.append(1)
            return original(preparer, request, ref)
        with patch.object(map_data_preparation.MapDataPreparer, "prepare", side_effect=spy):
            recompiled = self.workflow.compile(revised_path, new_g1, approval_key=APPROVAL_KEY)
        self.assertEqual(0, len(calls))
        self.assertEqual("preview", recompiled["state"]["step"])
        # The authoritative frontend document is revision-distinct: new file,
        # the previous one untouched at its immutable path.
        second_document = self._document_path(revised_request)
        self.assertTrue(second_document.is_file(), str(second_document))
        self.assertNotEqual(first_document, second_document)
        self.assertEqual(first_bytes, first_document.read_bytes())
        self.assertIn("领导调研路线图（修订版）", json.dumps(load_document(second_document),
                                                    ensure_ascii=False))
        new_preview = self.workflow.preview(revised_path, attestation_key=KEY)
        self.assertEqual("passed", new_preview["evidence"]["status"])
        # -- the old G2 must NOT authorize the revised design; a new G2 does --
        with self.assertRaises(SecurityError) as raised:
            self.workflow.freeze(revised_path, old_g2, approval_key=APPROVAL_KEY,
                                 attestation_key=KEY)
        self.assertEqual("APPROVAL_OBJECT_MISMATCH", raised.exception.code)
        new_g2 = self._signed("g2-new", "approve-freeze", "resolved-map",
                              new_preview["approval_object_digest"])
        frozen = self.workflow.freeze(revised_path, new_g2, approval_key=APPROVAL_KEY,
                                      attestation_key=KEY)
        self.assertEqual("render", frozen["state"]["step"])

    def test_style_overrides_revision_changes_colors_and_reuses_bundle(self):
        """Phase 2: G2-stage colour change through the design-revision channel —
        the point of the whole plan. MCP data chain skipped, compilation-only
        invalidation, new colours reach the frozen scene, the OLD G2 no longer
        authorizes the revised design."""
        from tests.test_general_thematic import APPROVAL_KEY, KEY
        from unittest.mock import patch
        from carto_core.workflow import map_data_preparation
        intake = self.workflow.intake(self.request_path)
        briefed = self.workflow.brief(self.request_path)
        g1 = self._signed("g1", "approve-map-brief", "map-brief", briefed["approval_object_digest"])
        self.workflow.compile(self.request_path, g1, approval_key=APPROVAL_KEY)
        preview = self.workflow.preview(self.request_path, attestation_key=KEY)
        old_g2 = self._signed("g2-old", "approve-freeze", "resolved-map",
                              preview["approval_object_digest"])
        first_scene = load_document(self.work / "candidates/render-scene.yaml")
        first_pin = next(g for g in first_scene["image_graphics"]
                         if g["type"] == "point" and g.get("group") == "morning")
        self.assertEqual("#1769D2", first_pin["color"])
        # -- propose a colour revision through the style_overrides vocabulary --
        proposal = {"schema_version": 1, "proposal_id": "proposal-restyle",
                    "run_id": "test-run", "parent_revision": 1,
                    "changes": {"style_overrides": {"new_value": {
                        "groups": [{"id": "morning", "color": "#228833"}]}}},
                    "justification": "Synthetic style-revision acceptance"}
        proposal_path = self.root / "style-proposal.yaml"
        atomic_yaml(proposal_path, proposal, create_once=False)
        revised_brief = self.workflow.revision_brief(self.request_path, proposal_path)
        self.assertEqual(2, revised_brief["brief"]["revision"])
        new_g1 = self._signed("g1-restyle", "approve-map-brief", "map-brief",
                              revised_brief["approval_object_digest"])
        revised = self.workflow.revise(self.request_path, proposal_path, new_g1,
                                       approval_key=APPROVAL_KEY)
        revised_path = Path(revised["request_path"])
        design_root = revised_path.parent.parent
        revised_request = load_document(revised_path)
        self.assertEqual([{"id": "morning", "color": "#228833"}],
                         revised_request["style_overrides"]["groups"])
        # Dependency graph: compilation-only invalidation, evidence reusable.
        graph = load_document(design_root / "dependency-graph.yaml")
        self.registry.validate("revision-dependency-graph", graph)
        self.assertTrue(graph["data_evidence_reusable"])
        self.assertIn("candidate", graph["invalidated_nodes"])
        self.assertNotIn("plan", graph["invalidated_nodes"])
        # The revised compile skips data preparation entirely: bundle reused.
        calls = []
        original = map_data_preparation.MapDataPreparer.prepare
        def spy(preparer, request, ref):
            calls.append(1)
            return original(preparer, request, ref)
        with patch.object(map_data_preparation.MapDataPreparer, "prepare", side_effect=spy):
            recompiled = self.workflow.compile(revised_path, new_g1, approval_key=APPROVAL_KEY)
        self.assertEqual(0, len(calls))
        self.assertEqual("preview", recompiled["state"]["step"])
        # The patched colour reaches the frozen scene; untouched group unchanged.
        new_scene = load_document(design_root / "candidates/render-scene.yaml")
        new_pin = next(g for g in new_scene["image_graphics"]
                       if g["type"] == "point" and g.get("group") == "morning")
        self.assertEqual("#228833", new_pin["color"])
        default_pin = next(g for g in new_scene["image_graphics"]
                           if g["type"] == "point" and g.get("group") == "default")
        self.assertEqual("#403B96", default_pin["color"])
        new_preview = self.workflow.preview(revised_path, attestation_key=KEY)
        self.assertEqual("passed", new_preview["evidence"]["status"])
        # The old G2 must NOT authorize the revised design; a new G2 does.
        with self.assertRaises(SecurityError) as raised:
            self.workflow.freeze(revised_path, old_g2, approval_key=APPROVAL_KEY,
                                 attestation_key=KEY)
        self.assertEqual("APPROVAL_OBJECT_MISMATCH", raised.exception.code)
        new_g2 = self._signed("g2-new", "approve-freeze", "resolved-map",
                              new_preview["approval_object_digest"])
        frozen = self.workflow.freeze(revised_path, new_g2, approval_key=APPROVAL_KEY,
                                      attestation_key=KEY)
        self.assertEqual("render", frozen["state"]["step"])

    def test_style_revision_full_loop_to_delivery(self):
        """Phase 3 closure: a G2-stage colour change runs the COMPLETE loop —
        propose → new G1 → revise (data evidence reused) → recompile → new
        preview → new G2 → freeze → render → check → review → G3 → deliver.
        The delivered package is the revised design; the first design's
        artifacts stay immutable at their original paths; the revision budget
        is charged exactly once."""
        from tests.test_general_thematic import APPROVAL_KEY, KEY
        from carto_core.workflow.budget_store import BudgetStore
        intake = self.workflow.intake(self.request_path)
        briefed = self.workflow.brief(self.request_path)
        g1 = self._signed("g1", "approve-map-brief", "map-brief", briefed["approval_object_digest"])
        self.workflow.compile(self.request_path, g1, approval_key=APPROVAL_KEY)
        first_preview = self.workflow.preview(self.request_path, attestation_key=KEY)
        first_scene = load_document(self.work / "candidates/render-scene.yaml")
        first_callouts = {tuple(g["stop_orders"]): g for g in first_scene["image_graphics"]
                          if g["type"] == "callout"}
        # -- propose the colour revision --
        proposal = {"schema_version": 1, "proposal_id": "proposal-final-restyle",
                    "run_id": "test-run", "parent_revision": 1,
                    "changes": {"style_overrides": {"new_value": {
                        "groups": [{"id": "morning", "color": "#228833"}]}}},
                    "justification": "Synthetic final style-revision acceptance"}
        proposal_path = self.root / "final-restyle-proposal.yaml"
        atomic_yaml(proposal_path, proposal, create_once=False)
        revised_brief = self.workflow.revision_brief(self.request_path, proposal_path)
        new_g1 = self._signed("g1-final", "approve-map-brief", "map-brief",
                              revised_brief["approval_object_digest"])
        revised = self.workflow.revise(self.request_path, proposal_path, new_g1,
                                       approval_key=APPROVAL_KEY)
        revised_path = Path(revised["request_path"])
        design_root = revised_path.parent.parent
        # -- recompile + new preview + new G2 → freeze → render → check → review → deliver --
        recompiled = self.workflow.compile(revised_path, new_g1, approval_key=APPROVAL_KEY)
        self.assertEqual("preview", recompiled["state"]["step"])
        new_preview = self.workflow.preview(revised_path, attestation_key=KEY)
        self.assertEqual("passed", new_preview["evidence"]["status"])
        new_g2 = self._signed("g2-final", "approve-freeze", "resolved-map",
                              new_preview["approval_object_digest"])
        frozen = self.workflow.freeze(revised_path, new_g2, approval_key=APPROVAL_KEY,
                                      attestation_key=KEY)
        self.assertEqual("render", frozen["state"]["step"])
        self.workflow.render(revised_path, attestation_key=KEY)
        checked = self.workflow.check(revised_path, attestation_key=KEY)
        self.assertEqual("passed", checked["validation_report"]["status"])
        args = dict(approval_key=APPROVAL_KEY, attestation_key=KEY,
                    recipient_id="synthetic-recipient", recipient_type="project-user",
                    destination="delivery/leadership-style-revision",
                    idempotency_key="leadership-style-revision-0001")
        approval = self._signed("review-final", "approve-product-review", "validation-report",
                                sha256_digest(checked["validation_report"]))
        reviewed = self.workflow.review(revised_path, approval, **args)
        g3 = self._signed("g3-final", "approve-delivery", "delivery-manifest",
                          reviewed["g3"]["object_digest"])
        delivered = self.workflow.deliver(revised_path, g3, approval_key=APPROVAL_KEY)
        self.assertEqual("succeeded", delivered["state"]["status"])
        delivery = self.root / "delivery" / "leadership-style-revision"
        for name in ("map.pdf", "map.png", "README.md", "delivery-manifest.yaml",
                     "checksums.sha256"):
            self.assertTrue((delivery / name).is_file(), name)
        self.assertFalse((delivery / "map-document.json").exists())
        # -- immutability & budget accounting --
        new_scene = load_document(design_root / "candidates/render-scene.yaml")
        new_callouts = {tuple(g["stop_orders"]): g for g in new_scene["image_graphics"]
                        if g["type"] == "callout"}
        # Same solver seed: annotation geometry (positions/offsets/size) unchanged
        # while the patched group's colour changed — only the style moved.
        for orders, callout in new_callouts.items():
            first = first_callouts[orders]
            for key in ("position", "offset_x_px", "offset_y_px", "width_px", "height_px"):
                self.assertEqual(first[key], callout[key], f"callout {orders} {key}")
        morning = new_callouts[(1,)]
        self.assertEqual("#228833", morning["color"])
        self.assertEqual("#1769D2", first_callouts[(1,)]["color"])
        # The first design's frozen scene stays byte-identical at its own path.
        self.assertEqual(first_scene, load_document(self.work / "candidates/render-scene.yaml"))
        # Revision budget charged exactly once.
        budget = BudgetStore(self.work, self.registry).load()
        self.assertEqual(1, budget.revisions)

    def test_route_author_template_style_carries_page_furniture(self):
        """Legacy fix ②: the authoring template carries the old 1.2.0
        image_presentation values (title 48px / body 18px / border 1-4-2px),
        converted at the 4px-per-mm canvas re-anchoring — so published
        templates exercise the contract path instead of the renderer fallback."""
        from carto_core.scenarios.leadership_visit.route_author import TEMPLATE_STYLE
        self.registry.validate("image-itinerary-style", TEMPLATE_STYLE)
        furniture = TEMPLATE_STYLE["page_furniture"]
        self.assertEqual(34.0, furniture["title_font_pt"])
        self.assertEqual(12.76, furniture["body_font_pt"])
        self.assertEqual({"color": "#000000", "inner_width_mm": 0.25,
                          "gap_mm": 1.0, "outer_width_mm": 0.5},
                         furniture["frame_border"])
        # The authored style freezes through the compile chain unchanged.
        contracts = deepcopy(self.contracts)
        contracts["portrayal"]["image_itinerary"] = json.loads(json.dumps(TEMPLATE_STYLE))
        plan = RoutePlanner().build(self.request, self.intent, self.brief, self.bundle,
                                    self.installation, contracts)
        compiler = RouteCandidateCompiler(self.guard, self.registry, project_root=self.root,
                                          context=ExecutionContext.from_generate_request(self.request))
        compiled = compiler.compile(self.request, self.intent, plan, self.bundle, self.installation,
                                    contracts, self.font_path)
        page = load_document(self.guard.resolve(compiled["scene"]["page_request_ref"]["uri"]))
        self.assertEqual(34.0, page["texts"][0]["font_pt"])
        self.assertEqual(12.76, page["texts"][1]["font_pt"])
        self.assertEqual(furniture["frame_border"], page["furniture"]["frame_border"])

    def test_annotation_layout_and_page_layout_proposals_validate(self):
        """Phase 0 schema backfill: the leadership change keys pass the shared
        design-revision-proposal schema (previously rejected at validation,
        before the scenario contract could even apply them)."""
        base = {"schema_version": 1, "proposal_id": "proposal-leadership-keys",
                "run_id": "test-run", "parent_revision": 1, "justification": "Schema backfill"}
        proposal = dict(base, changes={
            "annotation_layout": {"new_value": {"seed": 7, "iterations": 500, "gap_px": 4}}})
        self.registry.validate("design-revision-proposal", proposal)
        proposal = dict(base, changes={
            "page_layout": {"new_value": {"model": "fixed-page", "width_mm": 297,
                                           "height_mm": 210, "dpi": 300}}})
        self.registry.validate("design-revision-proposal", proposal)
        # Closed shapes are enforced: out-of-range and unknown fields reject.
        with self.assertRaises(ProtocolError):
            self.registry.validate("design-revision-proposal", dict(base, changes={
                "annotation_layout": {"new_value": {"seed": 7, "iterations": 0, "gap_px": 4}}}))
        with self.assertRaises(ProtocolError):
            self.registry.validate("design-revision-proposal", dict(base, changes={
                "page_layout": {"new_value": {"model": "a3-landscape"}}}))
        with self.assertRaises(ProtocolError):
            self.registry.validate("design-revision-proposal", dict(base, changes={
                "page_layout": {"new_value": {"model": "fixed-page", "orientation": "landscape"}}}))


class TemplateLifecycleTests(LeadershipFixture, unittest.TestCase):
    """L6: the real template creation route for the leadership scenario.

    analyze → brief → [T1] → author (real RouteAuthor, 1.2.0 style values) →
    validate (synthetic fixture render through the real ImagePageRenderer) →
    [TP] → publish into a real template repository — then the generate route
    installs the published template from the repository (no stub) and compiles
    a real candidate from it."""

    def setUp(self) -> None:
        from carto_core.workflow.template_workflow import TemplateCreationWorkflow
        # Per-test suffix keeps the state store / workdir / receipts isolated.
        self.suffix = self.id().rsplit("_", 1)[-1]
        (self.root / "sources").mkdir(parents=True, exist_ok=True)
        sample = {"type": "FeatureCollection", "features": [
            {"type": "Feature", "geometry": {"type": "Point", "coordinates": [120.0, 30.0]},
             "properties": {"visit_order": 1, "stop_name": "甲地", "itinerary_group": "morning",
                            "visit_date": "11月18日"}},
            {"type": "Feature", "geometry": {"type": "Point", "coordinates": [120.02, 29.98]},
             "properties": {"visit_order": 2, "stop_name": "乙地", "itinerary_group": "afternoon",
                            "visit_date": "11月18日"}},
            {"type": "Feature", "geometry": {"type": "Point", "coordinates": [119.98, 30.02]},
             "properties": {"visit_order": 3, "stop_name": "丙地", "itinerary_group": "afternoon",
                            "visit_date": "11月18日"}},
        ]}
        sample_path = self.root / "sources" / "visit-route-sample.geojson"
        atomic_json(sample_path, sample)
        manifest = {
            "schema_version": 1, "manifest_id": "leadership-sources",
            "sources": [{
                "source_id": "visit-route-sample", "kind": "geojson",
                "location_ref": "sources/visit-route-sample.geojson",
                "digest": file_digest(sample_path),
                "provenance": {"source_type": "user", "source_ref": "user-upload:visit-route-sample",
                               "version": "1", "retrieved_at": "2026-11-19T00:00:00Z",
                               "classification": "internal"},
                "license": "project-approved", "captured_at": "2026-11-19T00:00:00Z",
                "data_profile": {"data_nature": "user-provided", "contains_production_data": False,
                                 "contains_sensitive_coordinates": False,
                                 "source_crs": {"authority": "EPSG", "code": "4326"}},
            }],
        }
        atomic_yaml(self.root / "source-manifest.yaml", manifest)
        self.create_request = json.loads(json.dumps(
            VALID_CASES["leadership-visit-template-create-request"]))
        self.create_request.update(
            request_id=f"leadership-template-request-{self.suffix}",
            scope="project:test-project",
            subject={"tenant_id": "test-tenant", "project_id": "test-project",
                     "requester_subject_id": "test-operator",
                     "approver_subject_id": "test-approver", "environment": "local"},
            source_manifest_path="source-manifest.yaml",
            role_bindings={"route-stops": "visit-route-sample"},
        )
        self.create_path = self.root / f"create-request-{self.suffix}.json"
        self.create_path.write_text(json.dumps(self.create_request, ensure_ascii=False), encoding="utf-8")
        self.template_repo = self.root / f"template-repo-{self.suffix}"
        self.template_repo.mkdir(parents=True, exist_ok=True)
        self.workflow = TemplateCreationWorkflow(
            allowed_roots=[self.root], project_root=self.root,
            workdir=self.root / f"template-work-{self.suffix}", registry=self.registry)

    def _sign(self, name: str, action: str, kind: str, digest: str):
        from dataclasses import asdict
        from tests.test_general_thematic import sign
        path = self.root / f"{name}-{self.suffix}.yaml"
        atomic_yaml(path, asdict(sign(name, action, kind, digest,
                                      subject_id=self.create_request["subject"]["approver_subject_id"],
                                      scope=self.create_request["scope"],
                                      tenant_id=self.create_request["subject"]["tenant_id"])),
                    create_once=False)
        return path

    def _publish_template(self) -> dict:
        from tests.test_general_thematic import APPROVAL_KEY, KEY
        analyzed = self.workflow.analyze(self.create_path)
        summaries = analyzed["analysis"]["source_summaries"]
        self.assertEqual(["point"], summaries[0]["geometry_types"])
        briefed = self.workflow.brief(self.create_path)
        self.assertEqual(["route-stops"], [role["role_id"] for role in briefed["brief"]["data_roles"]])
        t1 = self._sign("t1", "approve-template-brief", "template-brief",
                        briefed["approval"]["object_digest"])
        authored = self.workflow.author(self.create_path, t1, approval_key=APPROVAL_KEY)
        package_path = Path(authored["package"]["package_path"])
        portrayal = load_document(package_path / "contracts" / "portrayal.yaml")
        # The authored portrayal carries the tuned old-framework 1.2.0 style values.
        self.assertEqual(2, portrayal["image_itinerary"]["groups"][0]["right_offset_px"])
        self.assertEqual(45, portrayal["image_itinerary"]["callout"]["offset_x_px"])
        self.assertTrue(portrayal["image_itinerary"]["callout"]["fit_content"])
        validated = self.workflow.validate(self.create_path, attestation_key=KEY,
                                           font_path=self.font_path)
        evidence = validated["evidence"]
        self.assertEqual("passed", evidence["status"])
        self.assertEqual("image-itinerary-page", evidence["renderer"]["renderer_id"])
        self.assertEqual({"pdf", "png"},
                         {item["target"] for item in evidence["preview_artifacts"]})
        publication_digest = sha256_digest({
            "package_digest": evidence["package_ref"]["digest"],
            "evidence_digest": evidence["evidence_digest"],
            "repository_scope": "local:templates",
        })
        tp = self._sign("tp", "approve-template-publish", "template-publication",
                        publication_digest)
        published = self.workflow.publish(self.create_path, tp,
                                          repository_root=self.template_repo,
                                          repository_scope="local:templates",
                                          idempotency_key=f"publish-leadership-{self.suffix}",
                                          approval_key=APPROVAL_KEY, renderer_attestation_key=KEY)
        self.assertFalse(published["idempotent_replay"])
        self.assertTrue((self.template_repo / "template-index.yaml").is_file())
        return published

    def test_template_creation_publishes_real_repository(self):
        published = self._publish_template()
        entry = published["publication"]["package_ref"]
        self.assertEqual("leadership-visit-map", entry["id"])
        self.assertIn("digest", entry)

    def test_published_template_feeds_the_generate_route_without_seams(self):
        from tests.test_general_thematic import APPROVAL_KEY, KEY
        from carto_core.workflow.map_generation import MapGenerationWorkflow
        published = self._publish_template()
        entry = published["publication"]["package_ref"]
        generate = json.loads(json.dumps(self.request))
        generate["template"]["digest"] = entry["digest"]
        generate.update(run_id=f"run-lifecycle-{self.suffix}")
        request_path = self.root / f"generate-request-{self.suffix}.yaml"
        atomic_yaml(request_path, generate)
        workflow = MapGenerationWorkflow(allowed_roots=[self.root], project_root=self.root,
                                         workdir=self.root / f"work-{self.suffix}",
                                         registry=self.registry,
                                         repository_root=self.template_repo,
                                         repository_scope="local:templates")
        intake = workflow.intake(request_path)
        self.assertEqual("leadership_visit", intake["intent"]["business_scene"])
        briefed = workflow.brief(request_path)
        self.assertEqual("leadership-visit-map", briefed["brief"]["template_candidates"][0]["id"])
        # G1 is signed by the GENERATE request's approver (not the template author's).
        from dataclasses import asdict
        from tests.test_general_thematic import sign
        g1_path = self.root / f"g1-{self.suffix}.yaml"
        atomic_yaml(g1_path, asdict(sign(
            "g1", "approve-map-brief", "map-brief", briefed["approval_object_digest"],
            subject_id=generate["subject"]["approver_subject_id"],
            scope=generate["scope"], tenant_id=generate["subject"]["tenant_id"])),
            create_once=False)
        g1 = g1_path
        compiled = workflow.compile(request_path, g1, approval_key=APPROVAL_KEY)
        self.assertEqual("preview", compiled["state"]["step"])
        self.assertEqual("passed", compiled["preflight"]["status"])
        # The installed package came from the real repository install (no stub).
        installed = load_document(self.root / f"work-{self.suffix}" / "templates" / "installed-template.yaml")
        self.assertTrue(installed["package_path"].startswith(
            (self.root / ".carto" / "templates" / "installed").as_posix()))
        preview = workflow.preview(request_path, attestation_key=KEY)
        self.assertEqual({"pdf", "png"},
                         {item["target"] for item in preview["receipt"]["output_artifacts"]})


if __name__ == "__main__":
    unittest.main()
