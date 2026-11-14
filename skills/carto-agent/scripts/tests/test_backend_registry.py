"""ADR-001 阶段1：backend_registry 收敛的回归与一致性测试。

三条关键保证：
1. registry 的 renderer_id 与 compiler.*_scene 的自我 id 常量逐字一致——阶段1为规避
   compiler→adapters 循环 import 未改 scene 常量，故用此断言锚定两处字面量不漂移。
2. is_static/is_browser 的家族分类与历史硬编码判断行为等价（未知 id → False）。
3. resolve / create_render_backend 对未知 id 明确拒绝（RENDER_BACKEND_NOT_AVAILABLE）。
"""
from pathlib import Path
import sys
SCRIPTS_ROOT = Path(__file__).resolve().parents[1]
if str(SCRIPTS_ROOT) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_ROOT))
import unittest

from carto_core.adapters import backend_registry as reg
from carto_core.errors import ProtocolError


class BackendRegistryTests(unittest.TestCase):
    def test_registry_ids_match_scene_constants(self):
        from carto_core.compiler.raster_scene import RASTER_RENDERER_ID
        from carto_core.compiler.vector_scene import RENDERER_ID as VECTOR_RENDERER_ID
        self.assertEqual(reg.RASTER_PAGE.renderer_id, RASTER_RENDERER_ID)
        self.assertEqual(reg.VECTOR_PAGE.renderer_id, VECTOR_RENDERER_ID)

    def test_is_static_matches_legacy_hardcoded_set(self):
        # 历史判断：renderer_id in {"rasterio-matplotlib-page", "matplotlib-vector-page"}
        legacy_static = {"rasterio-matplotlib-page", "matplotlib-vector-page"}
        probes = ("rasterio-matplotlib-page", "matplotlib-vector-page",
                  "maplibre-web", "unknown-backend", "auto-fallback", "")
        for rid in probes:
            self.assertEqual(reg.is_static(rid), rid in legacy_static,
                             f"is_static({rid!r}) must equal legacy `in {{...}}` result")

    def test_is_browser_classification(self):
        self.assertTrue(reg.is_browser("maplibre-web"))
        self.assertFalse(reg.is_browser("rasterio-matplotlib-page"))
        self.assertFalse(reg.is_browser("matplotlib-vector-page"))
        self.assertFalse(reg.is_browser("unknown-backend"))

    def test_families_are_disjoint_and_cover_known_backends(self):
        for rid in reg.renderer_ids():
            self.assertTrue(reg.is_static(rid) ^ reg.is_browser(rid), rid)
            self.assertTrue(reg.is_known(rid))

    def test_resolve_known_returns_descriptor_and_unknown_rejects(self):
        self.assertIs(reg.resolve("rasterio-matplotlib-page"), reg.RASTER_PAGE)
        self.assertIs(reg.resolve("matplotlib-vector-page"), reg.VECTOR_PAGE)
        self.assertIs(reg.resolve("maplibre-web"), reg.MAPLIBRE_WEB)
        with self.assertRaises(ProtocolError) as raised:
            reg.resolve("auto-fallback")
        self.assertEqual("RENDER_BACKEND_NOT_AVAILABLE", raised.exception.code)

    def test_descriptor_capabilities(self):
        self.assertEqual("raster", reg.RASTER_PAGE.geometry)
        self.assertEqual("vector", reg.VECTOR_PAGE.geometry)
        self.assertEqual(reg.STATIC_PAGE, reg.RASTER_PAGE.family)
        self.assertEqual(reg.STATIC_PAGE, reg.VECTOR_PAGE.family)
        self.assertEqual(reg.BROWSER, reg.MAPLIBRE_WEB.family)
        self.assertEqual(reg.IMPL_FORMAL, reg.RASTER_PAGE.impl)
        self.assertEqual(reg.IMPL_FORMAL, reg.VECTOR_PAGE.impl)
        self.assertEqual(reg.IMPL_BROWSER, reg.MAPLIBRE_WEB.impl)
        self.assertTrue({"pdf", "png"} <= reg.RASTER_PAGE.export_formats)
        self.assertTrue({"pdf", "png"} <= reg.VECTOR_PAGE.export_formats)

    def test_create_render_backend_rejects_unknown_id(self):
        # 收敛后未知 id 仍由 resolve 抛 RENDER_BACKEND_NOT_AVAILABLE（等价原 raise）。
        from carto_core.adapters.render_backend import create_render_backend
        with self.assertRaises(ProtocolError) as raised:
            create_render_backend("auto-fallback")
        self.assertEqual("RENDER_BACKEND_NOT_AVAILABLE", raised.exception.code)


if __name__ == "__main__":
    unittest.main()
