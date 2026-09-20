from __future__ import annotations

import json
import shutil
import sys
import tempfile
import unittest
from copy import deepcopy
from pathlib import Path

SCRIPTS_ROOT = Path(__file__).resolve().parents[1]
if str(SCRIPTS_ROOT) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_ROOT))

from carto_core.adapters import (  # noqa: E402
    BrowserLimits,
    ControlledBrowserRenderer,
    RendererCapabilityProfile,
    RendererCapabilityRegistry,
    WebMapRendererAdapter,
    compute_renderer_attestation,
)
from carto_core.adapters.controlled_renderer import (  # noqa: E402
    FRONTEND_BUILD,
    MAPLIBRE_VERSION,
    OVERLAY_ENGINE_VERSION,
    RANDOM_SEED,
    RENDERER_VERSION,
    discover_browser,
    sha256_file,
)
from carto_core.errors import ProtocolError, SecurityError  # noqa: E402
from carto_core.schema_registry import SchemaRegistry  # noqa: E402


class DeterministicRendererTests(unittest.TestCase):
    KEY = b"up23-render-attestation-key-32-bytes"

    @staticmethod
    def _font_path() -> Path | None:
        candidates = [
            Path(r"C:\Windows\Fonts\NotoSansSC-VF.ttf"),
            Path(r"C:\Windows\Fonts\msyh.ttc"),
            Path("/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc"),
            Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"),
        ]
        return next((path for path in candidates if path.is_file()), None)

    def setUp(self) -> None:
        browser = discover_browser()
        font = self._font_path()
        if browser is None:
            self.skipTest("Chromium browser is unavailable")
        if font is None:
            self.skipTest("Pinned test font is unavailable")
        self.browser = browser
        self.font = font
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.output = self.root / "outputs"
        self.output.mkdir()
        self.risk = self.root / "risk.geojson"
        self.points = self.root / "shelters.geojson"
        self.risk.write_text(json.dumps({
            "type": "FeatureCollection",
            "features": [
                {"type": "Feature", "id": "risk-1", "properties": {"risk": 4}, "geometry": {"type": "Polygon", "coordinates": [[[112.2, 28.2], [113.2, 28.2], [113.2, 29.2], [112.2, 29.2], [112.2, 28.2]]]}},
                {"type": "Feature", "id": "risk-2", "properties": {"risk": 2}, "geometry": {"type": "Polygon", "coordinates": [[[113.2, 28.2], [114.1, 28.2], [114.1, 29.2], [113.2, 29.2], [113.2, 28.2]]]}},
            ],
        }, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
        self.points.write_text(json.dumps({
            "type": "FeatureCollection",
            "features": [
                {"type": "Feature", "id": "shelter-1", "properties": {"capacity": 800}, "geometry": {"type": "Point", "coordinates": [112.8, 28.7]}},
                {"type": "Feature", "id": "shelter-2", "properties": {"capacity": 1400}, "geometry": {"type": "Point", "coordinates": [113.7, 28.8]}},
            ],
        }, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")

    def tearDown(self) -> None:
        self.temp.cleanup()

    def _scene(self) -> dict[str, object]:
        artifact = {"id": "local-style", "version": "1.0.0", "digest": "sha256:" + "0" * 64}
        return {
            "schema_version": 1,
            "scene_id": "synthetic-flood-scene",
            "revision": 1,
            "renderer_id": "maplibre-web",
            "spatial_context": {"display_crs": {"authority": "EPSG", "code": "4490"}, "axis_order": "longitude-latitude", "coordinate_units": "degrees"},
            "renderer_requirements": {"renderer_id": "maplibre-web", "require_webgl": True, "require_offline_rendering": True, "required_capabilities": ["svg-overlay", "headless-export"], "required_fonts": ["Noto Sans SC"], "minimum_device_pixel_ratio": 1},
            "viewport": {"width_px": 800, "height_px": 565, "device_pixel_ratio": 1, "background": "#F8FAFC"},
            "camera": {"bounds": [112.1, 28.0, 114.2, 29.5], "bearing": 0, "pitch": 0, "padding": {"top": 64, "right": 180, "bottom": 64, "left": 64}},
            "map": {
                "style_ref": artifact,
                "sources": [
                    {"id": "risk-source", "type": "geojson", "resource_id": "risk-data"},
                    {"id": "shelter-source", "type": "geojson", "resource_id": "shelter-data"},
                ],
                "layers": [
                    {"id": "risk-fill", "source_id": "risk-source", "type": "fill", "paint": {"fill-color": ["match", ["get", "risk"], 4, "#B91C1C", "#FBBF24"], "fill-opacity": 0.78}, "z_index": 10},
                    {"id": "shelter-points", "source_id": "shelter-source", "type": "circle", "paint": {"circle-color": "#0F766E", "circle-radius": ["interpolate", ["linear"], ["get", "capacity"], 0, 5, 1500, 14], "circle-stroke-color": "#FFFFFF", "circle-stroke-width": 2}, "z_index": 20},
                ],
            },
            "overlays": [
                {"id": "title", "type": "text", "coordinate_space": "page", "position": {"x": 40, "y": 38, "unit": "pixel"}, "content": "合成洪涝风险与避难场所图", "style_role": "map-title"},
                {"id": "legend", "type": "legend", "coordinate_space": "page", "position": {"x": 630, "y": 90, "unit": "pixel"}, "legend_items": [{"label": "高风险", "color": "#B91C1C", "symbol": "fill"}, {"label": "中风险", "color": "#FBBF24", "symbol": "fill"}, {"label": "避难场所", "color": "#0F766E", "symbol": "circle"}]},
                {"id": "north", "type": "north-arrow", "coordinate_space": "page", "position": {"x": 744, "y": 48, "unit": "pixel"}},
                {"id": "scale", "type": "scale-bar", "coordinate_space": "page", "position": {"x": 64, "y": 520, "unit": "pixel"}, "length_px": 120, "distance_label": "10 km"},
                {"id": "source", "type": "attribution", "coordinate_space": "page", "position": {"x": 500, "y": 540, "unit": "pixel"}, "content": "数据来源：纯合成测试数据", "style_role": "source-note"},
            ],
            "resources": [
                {"id": "risk-data", "kind": "geojson", "ref": {"id": "risk-data", "version": "1.0.0", "digest": sha256_file(self.risk), "uri": str(self.risk)}, "required": True},
                {"id": "shelter-data", "kind": "geojson", "ref": {"id": "shelter-data", "version": "1.0.0", "digest": sha256_file(self.points), "uri": str(self.points)}, "required": True},
                {"id": "noto-font", "kind": "font", "font_family": "Noto Sans SC", "ref": {"id": "noto-font", "version": "1.0.0", "digest": sha256_file(self.font), "uri": str(self.font)}, "required": True},
            ],
            "export": {"targets": ["svg", "png", "pdf"], "dpi": 144},
            "random_seed": RANDOM_SEED,
            "provenance": [{"source_type": "derived", "source_ref": "synthetic:test-fixture", "version": "1.0.0", "classification": "public"}],
        }

    def _adapter(
        self,
        *,
        limits: BrowserLimits | None = None,
        available_fonts: tuple[str, ...] = ("Noto Sans SC",),
    ) -> tuple[WebMapRendererAdapter, ControlledBrowserRenderer]:
        renderer = ControlledBrowserRenderer(
            allowed_roots=[self.root, self.font.parent], output_root=self.output,
            attestation_key=self.KEY, limits=limits, browser=self.browser,
        )
        profile = RendererCapabilityProfile(
            renderer_id="maplibre-web", frontend_build=FRONTEND_BUILD,
            renderer_version=RENDERER_VERSION, maplibre_version=MAPLIBRE_VERSION,
            overlay_engine_version=OVERLAY_ENGINE_VERSION, browser_engine=renderer.browser_engine,
            webgl_available=True, supported_export_formats=("svg", "png", "pdf"),
            max_canvas_width=4096, max_canvas_height=4096, device_pixel_ratio=2,
            available_fonts=available_fonts, offline_rendering=True,
        )
        return WebMapRendererAdapter(RendererCapabilityRegistry([profile]), renderer), renderer

    def _render(self, session_id: str = "up23-smoke") -> tuple[WebMapRendererAdapter, dict[str, object]]:
        adapter, _ = self._adapter()
        scene = adapter.compile_scene(self._scene())
        return adapter, adapter.submit_render(session_id, scene, "maplibre-web", FRONTEND_BUILD)

    def _resign(self, receipt: dict[str, object]) -> None:
        receipt["renderer_attestation"] = compute_renderer_attestation(receipt, self.KEY)

    def test_real_browser_renders_and_validates_svg_png_pdf_receipt(self) -> None:
        adapter, _ = self._adapter()
        scene = adapter.compile_scene(self._scene())
        receipt = adapter.submit_render("up23-smoke", scene, "maplibre-web", FRONTEND_BUILD)
        self.assertEqual(receipt["status"], "succeeded")
        self.assertEqual({item["target"] for item in receipt["output_artifacts"]}, {"svg", "png", "pdf"})
        self.assertEqual(receipt["composition"]["map_body"], "maplibre-webgl-raster")
        self.assertEqual(receipt["composition"]["overlays"], "svg-vector")
        self.assertEqual(receipt["controls"]["network_policy"], "deny-all")
        for artifact in receipt["output_artifacts"]:
            self.assertTrue(Path(artifact["artifact_ref"]["uri"]).is_file())
        svg_artifact = next(item for item in receipt["output_artifacts"] if item["target"] == "svg")
        svg = Path(svg_artifact["artifact_ref"]["uri"]).read_text(encoding="utf-8")
        self.assertIn("@font-face", svg)
        for overlay_id in ("title", "legend", "north", "scale", "source"):
            self.assertIn(f'id="{overlay_id}"', svg)
        self.assertEqual(adapter.capabilities(), {
            "maplibre-web", "svg-overlay", "controlled-render-session",
            "fill", "point-symbol", "offline-only", "svg", "png", "pdf-preview",
        })
        SchemaRegistry().validate("render-receipt", receipt)
        adapter.validate_receipt(receipt, self.KEY)

    def test_compile_is_sorted_and_rejects_unsupported_layer(self) -> None:
        adapter, _ = self._adapter()
        scene = self._scene()
        scene["map"]["layers"] = list(reversed(scene["map"]["layers"]))
        compiled = adapter.compile_scene(scene)
        self.assertEqual([item["id"] for item in compiled["map"]["layers"]], ["risk-fill", "shelter-points"])
        unsupported = self._scene()
        unsupported["map"]["layers"][0]["type"] = "heatmap"
        with self.assertRaises(ProtocolError) as raised:
            adapter.compile_scene(unsupported)
        self.assertEqual(raised.exception.code, "RENDER_LAYER_TYPE_UNSUPPORTED")

        seed_drift = self._scene()
        seed_drift["random_seed"] = RANDOM_SEED + 1
        with self.assertRaises(ProtocolError) as raised:
            adapter.compile_scene(seed_drift)
        self.assertEqual(raised.exception.code, "RENDER_RANDOM_SEED_UNSUPPORTED")

    def test_resource_drift_and_network_uri_are_rejected(self) -> None:
        adapter, _ = self._adapter()
        scene = adapter.compile_scene(self._scene())
        self.risk.write_text('{"type":"FeatureCollection","features":[]}', encoding="utf-8")
        with self.assertRaises(SecurityError) as raised:
            adapter.submit_render("drift", scene, "maplibre-web", FRONTEND_BUILD)
        self.assertEqual(raised.exception.code, "RENDER_RESOURCE_DIGEST_MISMATCH")

        adapter, _ = self._adapter()
        network = self._scene()
        network["resources"][0]["ref"]["uri"] = "https://example.invalid/risk.geojson"
        with self.assertRaises(SecurityError) as raised:
            adapter.submit_render("network", adapter.compile_scene(network), "maplibre-web", FRONTEND_BUILD)
        self.assertEqual(raised.exception.code, "RENDER_NETWORK_ACCESS_DENIED")


    def test_same_scene_and_environment_have_stable_execution_digests(self) -> None:
        adapter, _ = self._adapter()
        scene = adapter.compile_scene(self._scene())
        first = adapter.submit_render("deterministic-a", scene, "maplibre-web", FRONTEND_BUILD)
        second = adapter.submit_render("deterministic-b", scene, "maplibre-web", FRONTEND_BUILD)
        self.assertEqual(first["scene_digest"], second["scene_digest"])
        self.assertEqual(first["resource_set_digest"], second["resource_set_digest"])
        self.assertEqual(first["execution_digest"], second["execution_digest"])
        self.assertEqual(first["environment_fingerprint"], second["environment_fingerprint"])

    def test_missing_required_font_is_rejected(self) -> None:
        adapter, _ = self._adapter(available_fonts=())
        scene = adapter.compile_scene(self._scene())
        with self.assertRaises(ProtocolError) as raised:
            adapter.submit_render("missing-font", scene, "maplibre-web", FRONTEND_BUILD)
        self.assertEqual(raised.exception.code, "RENDER_FONT_UNAVAILABLE")

        adapter, _ = self._adapter()
        no_font_resource = self._scene()
        no_font_resource["resources"] = [
            item for item in no_font_resource["resources"] if item["kind"] != "font"
        ]
        with self.assertRaises(ProtocolError) as raised:
            adapter.compile_scene(no_font_resource)
        self.assertEqual(raised.exception.code, "RENDER_FONT_RESOURCE_MISSING")

        missing_font_file = self._scene()
        font_resource = next(item for item in missing_font_file["resources"] if item["kind"] == "font")
        font_resource["ref"]["uri"] = str(self.root / "missing-font.ttf")
        with self.assertRaises(ProtocolError) as raised:
            adapter.submit_render(
                "missing-font-file", adapter.compile_scene(missing_font_file),
                "maplibre-web", FRONTEND_BUILD,
            )
        self.assertEqual(raised.exception.code, "RENDER_FONT_UNAVAILABLE")

    def test_receipt_rejects_viewport_and_environment_drift(self) -> None:
        adapter, receipt = self._render("receipt-drift")
        viewport_drift = deepcopy(receipt)
        viewport_drift["viewport"]["width_px"] += 1
        self._resign(viewport_drift)
        with self.assertRaises(ProtocolError) as raised:
            adapter.validate_receipt(viewport_drift, self.KEY)
        self.assertEqual(raised.exception.code, "RENDER_RECEIPT_VIEWPORT_MISMATCH")

        environment_drift = deepcopy(receipt)
        environment_drift["environment_fingerprint"] = "sha256:" + "f" * 64
        self._resign(environment_drift)
        with self.assertRaises(ProtocolError) as raised:
            adapter.validate_receipt(environment_drift, self.KEY)
        self.assertEqual(raised.exception.code, "RENDER_ENVIRONMENT_MISMATCH")

        control_drift = deepcopy(receipt)
        control_drift["controls"]["memory_bytes"] *= 2
        self._resign(control_drift)
        with self.assertRaises(ProtocolError) as raised:
            adapter.validate_receipt(control_drift, self.KEY)
        self.assertEqual(raised.exception.code, "RENDER_CONTROL_MISMATCH")

    def test_receipt_rejects_output_tampering(self) -> None:
        adapter, receipt = self._render("output-tamper")
        artifact = next(item for item in receipt["output_artifacts"] if item["target"] == "png")
        path = Path(artifact["artifact_ref"]["uri"])
        payload = bytearray(path.read_bytes())
        payload[-1] ^= 1
        path.write_bytes(payload)
        with self.assertRaises(ProtocolError) as raised:
            adapter.validate_receipt(receipt, self.KEY)
        self.assertEqual(raised.exception.code, "RENDER_OUTPUT_DIGEST_MISMATCH")

    def test_failed_receipt_status_and_outputs_are_checked(self) -> None:
        adapter, receipt = self._render("failed-receipt")
        failed = deepcopy(receipt)
        failed["status"] = "failed"
        failed["output_artifacts"] = []
        failed["error"] = {"code": "RENDER_BROWSER_FAILED", "message": "synthetic failure"}
        self._resign(failed)
        with self.assertRaises(ProtocolError) as raised:
            adapter.validate_receipt(failed, self.KEY)
        self.assertEqual(raised.exception.code, "RENDER_RECEIPT_FAILED")

        failed_with_output = deepcopy(receipt)
        failed_with_output["status"] = "failed"
        failed_with_output["error"] = {"code": "RENDER_BROWSER_FAILED", "message": "synthetic failure"}
        self._resign(failed_with_output)
        with self.assertRaises(ProtocolError) as raised:
            adapter.validate_receipt(failed_with_output, self.KEY)
        self.assertEqual(raised.exception.code, "RENDER_FAILED_RECEIPT_HAS_OUTPUT")

    def test_temporary_disk_limit_is_enforced(self) -> None:
        adapter, _ = self._adapter(limits=BrowserLimits(temporary_disk_bytes=16 * 1024 * 1024))
        with self.assertRaises(SecurityError) as raised:
            adapter.submit_render("disk-limit", adapter.compile_scene(self._scene()), "maplibre-web", FRONTEND_BUILD)
        self.assertEqual(raised.exception.code, "RENDER_TEMP_DISK_LIMIT")

    def test_browser_timeout_is_enforced(self) -> None:
        adapter, _ = self._adapter(limits=BrowserLimits(timeout_seconds=0.01, cpu_seconds=5))
        with self.assertRaises(ProtocolError) as raised:
            adapter.submit_render("timeout", adapter.compile_scene(self._scene()), "maplibre-web", FRONTEND_BUILD)
        self.assertEqual(raised.exception.code, "RENDER_TIMEOUT")


if __name__ == "__main__":
    unittest.main()
