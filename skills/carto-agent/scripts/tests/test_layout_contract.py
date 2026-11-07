from __future__ import annotations

import base64
import json
import struct
import sys
import tempfile
import unittest
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock
from xml.etree import ElementTree

SCRIPTS_ROOT = Path(__file__).resolve().parents[1]
if str(SCRIPTS_ROOT) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_ROOT))

from carto_core.adapters.controlled_renderer import ControlledBrowserRenderer, _ChromeCdpSession
from carto_core.adapters.svg_compositor import SvgCompositor
from carto_core.adapters.webmap_renderer import WebMapRendererAdapter
from carto_core.canonical import sha256_digest
from carto_core.compiler.layout import LayoutResolver, raster_size
from carto_core.errors import ProtocolError
from carto_core.schema_registry import SchemaRegistry
from carto_core.security.paths import PathGuard
from carto_core.workflow.map_final_check import FinalMapCheckService
from carto_core.workflow.map_preview import MapPreviewService
from tests.fixtures.schema_cases import VALID_CASES

FIXTURES = Path(__file__).parent / "fixtures"


class LayoutContractTests(unittest.TestCase):
    """Pure contract/composition regressions; browser interactions below are mocks."""

    def setUp(self) -> None:
        self.registry = SchemaRegistry()
        self.resolver = LayoutResolver(self.registry)
        self.fixture = json.loads((FIXTURES / "resolved-layout.valid.json").read_text(encoding="utf-8"))
        self.contract = deepcopy(self.fixture["contract"])
        self.raw = deepcopy(VALID_CASES["render-scene"])
        self.raw["viewport"]["device_pixel_ratio"] = 1
        self.raw["renderer_requirements"]["minimum_device_pixel_ratio"] = 1
        self.raw["export"]["dpi"] = 144
        self.raw["overlays"] = [
            {"id": "title", "type": "text", "content": "Layout title"},
            {"id": "legend", "type": "legend", "legend_items": [{"label": "Category", "color": "#FF0000", "symbol": "fill"}]},
            {"id": "north", "type": "north-arrow"},
            {"id": "scale", "type": "scale-bar", "distance_label": "1 km"},
            {"id": "source", "type": "attribution", "content": "Source attribution"},
            {"id": "scenario-notice", "type": "text", "content": "Required disclosure"},
        ]
        self.scene = self.resolver.apply(self.raw, self.contract)

    def _frame(self, content_id: str) -> dict:
        return next(frame for frame in self.contract["frames"] if frame["content_id"] == content_id)

    @staticmethod
    def _overlay(scene: dict, content_id: str) -> dict:
        return next(item for item in scene["overlays"] if item["id"] == content_id)

    def _execution(self, scene: dict | None = None) -> dict:
        scene = scene or self.scene
        result = deepcopy(VALID_CASES["resolved-map"]["execution"])
        result.update({"resolved_layout": deepcopy(scene["resolved_layout"]),
                       "render_scene_ref": {"id": scene["scene_id"], "version": "1.0.0", "digest": sha256_digest(scene)},
                       "camera": deepcopy(scene["camera"])})
        result["views"][0]["id"] = "main-view"
        result["targets"] = {f"a3-{kind}": {"format": kind, "display_crs": {"authority": "EPSG", "code": "4326"},
                                          "dpi": 144, "width_mm": 420, "height_mm": 297}
                             for kind in scene["export"]["targets"]}
        result["views"][0]["target_ids"] = sorted(result["targets"])
        return result

    def test_schema_examples_and_missing_binding(self) -> None:
        self.registry.validate("resolved-layout", self.fixture)
        invalid = json.loads((FIXTURES / "resolved-layout.invalid.json").read_text(encoding="utf-8"))
        with self.assertRaises(ProtocolError):
            self.registry.validate("resolved-layout", invalid)
        self._frame("title").pop("content_id")
        with self.assertRaises(ProtocolError):
            self.resolver.resolve(self.contract, 144)

    def test_resolution_matches_explicit_fixture_and_does_not_mutate_inputs(self) -> None:
        raw, contract = deepcopy(self.raw), deepcopy(self.contract)
        scene = self.resolver.apply(self.raw, self.contract)
        self.assertEqual(raw, self.raw)
        self.assertEqual(contract, self.contract)
        self.assertEqual(self.fixture, scene["resolved_layout"])
        self.assertEqual((2381, 1684), tuple(scene["viewport"][key] for key in ("width_px", "height_px")))
        self.assertEqual(dict.fromkeys(("top", "right", "bottom", "left"), 0), scene["camera"]["padding"])
        self.registry.validate("render-scene", scene)
        WebMapRendererAdapter().compile_scene(scene)

    def test_changing_frame_moves_output_anchor_and_invalidates_scene_digest(self) -> None:
        old = self._overlay(self.scene, "legend")["position"]
        self._frame("legend")["bounds"][0] += 2
        changed = self.resolver.apply(self.raw, self.contract)
        new = self._overlay(changed, "legend")["position"]
        self.assertAlmostEqual(2 * 144 / 25.4, new["x"] - old["x"], places=5)
        self.assertEqual(old["y"], new["y"])
        self.assertNotEqual(sha256_digest(self.scene), sha256_digest(changed))
        self.assertNotEqual(self.scene["resolved_layout"]["contract_ref"], changed["resolved_layout"]["contract_ref"])

    def test_missing_and_duplicate_overlay_bindings_are_rejected(self) -> None:
        for overlays in (self.raw["overlays"][:-1], self.raw["overlays"] + [self.raw["overlays"][0]]):
            raw = {**self.raw, "overlays": overlays}
            with self.assertRaises(ProtocolError) as raised:
                self.resolver.apply(raw, self.contract)
            self.assertEqual("LAYOUT_CONTENT_BINDING_MISMATCH", raised.exception.code)

    def test_duplicate_frame_content_and_map_binding_are_rejected(self) -> None:
        self._frame("title")["content_id"] = "legend"
        with self.assertRaises(ProtocolError) as raised:
            self.resolver.resolve(self.contract, 144)
        self.assertEqual("LAYOUT_BINDING_DUPLICATE", raised.exception.code)
        self.contract = deepcopy(self.fixture["contract"])
        self._frame("main-view")["content_id"] = "other-view"
        with self.assertRaises(ProtocolError) as raised:
            self.resolver.apply(self.raw, self.contract)
        self.assertEqual("LAYOUT_MAP_BINDING_MISMATCH", raised.exception.code)

    def test_frame_overlap_and_safe_margin_violations_are_rejected(self) -> None:
        for box, error in (([320, 55, 75, 170], "LAYOUT_FRAME_OVERLAP"),
                           ([400, 55, 75, 170], "LAYOUT_FRAME_OUT_OF_BOUNDS"),
                           ([330, 5, 75, 170], "LAYOUT_FRAME_OUT_OF_BOUNDS")):
            self._frame("legend")["bounds"] = box
            with self.assertRaises(ProtocolError) as raised:
                self.resolver.resolve(self.contract, 144)
            self.assertEqual(error, raised.exception.code)

    def test_unsupported_overflow_never_silently_falls_back(self) -> None:
        for policy in ("shrink", "paginate", "clip"):
            self._frame("title")["overflow_policy"] = policy
            with self.assertRaises(ProtocolError) as raised:
                self.resolver.resolve(self.contract, 144)
            self.assertEqual("LAYOUT_OVERFLOW_UNSUPPORTED", raised.exception.code)

    def test_unsupported_units_dpr_and_multiple_maps_fail(self) -> None:
        with self.assertRaises(ProtocolError):
            self.resolver.resolve(self.contract, 144, 2)
        self.contract["canvas"]["unit"] = "px"
        with self.assertRaises(ProtocolError):
            self.resolver.resolve(self.contract, 144)
        self.contract = deepcopy(self.fixture["contract"])
        self._frame("legend").update(type="map", overflow_policy="clip")
        with self.assertRaises(ProtocolError) as raised:
            self.resolver.resolve(self.contract, 144)
        self.assertEqual("LAYOUT_MAP_COUNT_UNSUPPORTED", raised.exception.code)

    def test_conservative_content_overflow_is_rejected_not_shrunk(self) -> None:
        self.raw["overlays"][0]["content"] = "W" * 200
        with self.assertRaises(ProtocolError) as raised:
            self.resolver.apply(self.raw, self.contract)
        self.assertEqual("LAYOUT_CONTENT_OVERFLOW", raised.exception.code)

    def test_tampered_snapshot_anchor_and_viewport_fail(self) -> None:
        variants = []
        changed = deepcopy(self.scene)
        changed["resolved_layout"]["frames"][0]["bounds_px"][0] += 1
        variants.append((changed, "LAYOUT_SNAPSHOT_MISMATCH"))
        changed = deepcopy(self.scene)
        self._overlay(changed, "legend")["position"]["x"] += 1
        variants.append((changed, "LAYOUT_ANCHOR_MISMATCH"))
        changed = deepcopy(self.scene)
        changed["viewport"]["width_px"] += 1
        variants.append((changed, "LAYOUT_PAGE_MISMATCH"))
        for changed, error in variants:
            with self.subTest(error=error), self.assertRaises(ProtocolError) as raised:
                self.resolver.validate_scene(changed)
            self.assertEqual(error, raised.exception.code)

    def test_target_page_and_margin_cannot_diverge(self) -> None:
        execution = self._execution()
        self.resolver.validate_execution(self.scene, execution)
        next(iter(execution["targets"].values()))["dpi"] = 300
        with self.assertRaises(ProtocolError) as raised:
            self.resolver.validate_execution(self.scene, execution)
        self.assertEqual("LAYOUT_TARGET_MISMATCH", raised.exception.code)
        with self.assertRaises(ProtocolError):
            self.resolver.validate_targets(self.fixture, [{"width_mm": 420, "height_mm": 297, "dpi": 144, "safe_margin_mm": 5}])

    def test_old_execution_and_old_scene_evidence_are_rejected_before_browser_use(self) -> None:
        service = object.__new__(MapPreviewService)
        service.registry = self.registry
        candidate = deepcopy(VALID_CASES["resolved-map"])
        candidate["execution"] = self._execution()
        candidate["execution_digest"] = sha256_digest(candidate["execution"])
        service._validate_candidate_scene(candidate, self.scene)
        self._frame("legend")["bounds"][0] += 2
        changed = self.resolver.apply(self.raw, self.contract)
        with self.assertRaises(ProtocolError) as raised:
            service.validate_persisted(candidate, changed, {})
        self.assertEqual("LAYOUT_EXECUTION_MISMATCH", raised.exception.code)
        candidate["execution"].pop("resolved_layout")
        candidate["execution_digest"] = sha256_digest(candidate["execution"])
        with self.assertRaises(ProtocolError):
            service._validate_candidate_scene(candidate, self.scene)

    def test_final_check_uses_same_snapshot_and_detects_anchor_drift(self) -> None:
        checker = object.__new__(FinalMapCheckService)
        checker.registry = self.registry
        context = {"scene": self.scene, "lock": {"execution": self._execution()}}
        passed, details, _ = checker._layout_elements(context)
        self.assertTrue(passed)
        self.assertEqual(self.fixture["frames"], details["frames"])
        self._overlay(self.scene, "title")["position"]["y"] += 1
        self.assertFalse(checker._layout_elements(context)[0])

    def test_compositor_places_map_image_in_frame_and_binds_print_size(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            png = root / "map.png"
            # Minimal real PNG; this test inspects SVG geometry, not browser pixels.
            png.write_bytes(base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+a1ioAAAAASUVORK5CYII="))
            svg = SvgCompositor(2381, 1684, PathGuard([root])).compose(
                png, self.scene["overlays"], root / "page.svg", resolved_layout=self.fixture)
            document = ElementTree.fromstring(svg.read_text(encoding="utf-8"))
            image = document.find("{http://www.w3.org/2000/svg}image")
            self.assertIsNotNone(image)
            for key, value in zip(("x", "y", "width", "height"), self.resolver.map_frame(self.fixture)["bounds_px"]):
                self.assertAlmostEqual(value, float(image.attrib[key]), places=2)
            self.assertIn("size:420mm 297mm", svg.read_text(encoding="utf-8"))
            self.assertNotEqual("2381", image.attrib["width"])

    def test_cdp_viewport_and_pdf_use_layout_units_without_browser(self) -> None:
        session = object.__new__(_ChromeCdpSession)
        session.scene = self.scene
        session.call = Mock(return_value={"data": base64.b64encode(b"%PDF-test").decode()})
        session.set_viewport(1757, 1417)
        session.call.assert_called_with("Emulation.setDeviceMetricsOverride", {
            "width": 1757, "height": 1417, "deviceScaleFactor": 1, "mobile": False})
        session.print_pdf()
        args = session.call.call_args.args
        self.assertEqual("Page.printToPDF", args[0])
        self.assertAlmostEqual(420 / 25.4, args[1]["paperWidth"])
        self.assertAlmostEqual(297 / 25.4, args[1]["paperHeight"])

    def test_renderer_captures_map_viewport_then_restores_page_viewport(self) -> None:
        scene = deepcopy(self.scene)
        scene["export"]["targets"] = ["svg", "png"]
        page_size = (2381, 1684)
        map_size = tuple(raster_size(v) for v in self.resolver.map_frame(self.fixture)["bounds_px"][2:])
        class FakeBrowser:
            def __init__(self):
                self.size = page_size
                self.sizes = []
            def __enter__(self): return self
            def __exit__(self, *args): pass
            def set_viewport(self, *size): self.size = size; self.sizes.append(size)
            def navigate(self, url): pass
            def wait_for_map_ready(self): pass
            def wait_for_document_ready(self): pass
            def capture_png(self):
                # Header-only bytes are confined to this mocked renderer test.
                return b"\x89PNG\r\n\x1a\n" + struct.pack("!I", 13) + b"IHDR" + struct.pack("!II", *self.size)
        browser = FakeBrowser()
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            renderer = object.__new__(ControlledBrowserRenderer)
            renderer.path_guard = PathGuard([root])
            renderer.output_root = root
            renderer.environment_fingerprint = "sha256:" + "0" * 64
            renderer.attestation_key = b"layout-unit-test-key-32-bytes-only"
            renderer._load_resources = Mock(return_value=({}, []))
            renderer._build_html = Mock(return_value="<html></html>")
            renderer._open_browser = Mock(return_value=browser)
            renderer.receipt_controls = Mock(return_value={})
            profile = SimpleNamespace(renderer_id="maplibre-web", frontend_build="unit-test",
                                      renderer_version="1.1.0", maplibre_version="3.6.0",
                                      overlay_engine_version="1.1.0", browser_engine="mock",
                                      profile_digest=lambda: "sha256:" + "0" * 64)
            receipt = renderer.render({"scene": scene, "session_id": "layout-unit", "scene_id": scene["scene_id"],
                                       "scene_revision": scene["revision"], "scene_digest": sha256_digest(scene)}, profile)
            self.assertEqual([map_size, page_size], browser.sizes)
            self.assertEqual(2381, receipt["viewport"]["width_px"])



if __name__ == "__main__":
    unittest.main()
