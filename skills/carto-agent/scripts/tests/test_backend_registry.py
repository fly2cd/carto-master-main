"""backend_registry 单一权威：家族分类、拒绝未知 id、以及"字面量不得复制"的守卫。

四条关键保证：
1. renderer_id 字面量**只允许出现在 backend_registry.py**。P0-1 之前，
   ``compiler.raster_scene`` / ``compiler.vector_scene`` / ``adapters.page_renderer`` /
   ``compiler.layout`` / ``validation.map_checks`` / ``workflow.map_final_check`` /
   ``adapters.renderer_probe`` / ``adapters.webmap_renderer`` / ``workflow.map_render`` /
   ``workflow.template_validation`` 各持副本，新增或改名一个后端需要散弹式修改 10 个文件。
   现在各处常量一律由本表派生，AST 守卫扫描全量字符串常量，出现副本即失败。
2. 派生常量与 registry 是**同一对象**（不是两份等值字符串），防止再次退化为副本。
3. is_static/is_browser 的家族分类与历史硬编码判断行为等价（未知 id → False）。
4. resolve / create_render_backend 对未知 id 明确拒绝（RENDER_BACKEND_NOT_AVAILABLE）。
"""
import ast
from pathlib import Path
import sys

SCRIPTS_ROOT = Path(__file__).resolve().parents[1]
if str(SCRIPTS_ROOT) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_ROOT))
import unittest

from carto_core import backend_registry as reg
from carto_core.errors import ProtocolError

CORE = SCRIPTS_ROOT / "carto_core"
AUTHORITY = "backend_registry.py"


def literal_sites():
    """Yield (module relative path, lineno, value) for every renderer_id string literal.

    Docstrings and other bare string expressions are skipped: the registry's own
    docstring legitimately quotes historical literals when explaining the convergence.
    """
    ids = set(reg.renderer_ids())
    for path in sorted(CORE.rglob("*.py")):
        if "__pycache__" in path.parts:
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        bare = {id(node.value) for node in ast.walk(tree)
                if isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant)
                and isinstance(node.value.value, str)}
        for node in ast.walk(tree):
            if (isinstance(node, ast.Constant) and isinstance(node.value, str)
                    and node.value in ids and id(node) not in bare):
                yield path.relative_to(CORE).as_posix(), node.lineno, node.value


class BackendRegistryTests(unittest.TestCase):
    def test_no_renderer_id_literal_outside_the_registry(self):
        offenders = [f"{path}:{line} {value!r}" for path, line, value in literal_sites()
                     if path != AUTHORITY]
        self.assertEqual(
            [], offenders,
            "renderer_id 字面量只允许出现在 carto_core/backend_registry.py；"
            "其他模块必须由 RASTER_PAGE / VECTOR_PAGE / MAPLIBRE_WEB 派生，"
            "否则新增后端又变成散弹式修改")

    def test_derived_constants_are_the_registry_values(self):
        from carto_core.adapters.page_renderer import RASTER_RENDERER_ID as PAGE_RASTER
        from carto_core.adapters.page_renderer import VECTOR_RENDERER_ID as PAGE_VECTOR
        from carto_core.adapters.renderer_probe import RendererCapabilityProbe
        from carto_core.adapters.webmap_renderer import WebMapRendererAdapter
        from carto_core.compiler.raster_scene import RASTER_RENDERER_ID
        from carto_core.compiler.vector_scene import RENDERER_ID as VECTOR_RENDERER_ID
        # Identity, not equality: a re-hardcoded copy would still compare equal.
        self.assertIs(reg.RASTER_PAGE.renderer_id, RASTER_RENDERER_ID)
        self.assertIs(reg.VECTOR_PAGE.renderer_id, VECTOR_RENDERER_ID)
        self.assertIs(reg.RASTER_PAGE.renderer_id, PAGE_RASTER)
        self.assertIs(reg.VECTOR_PAGE.renderer_id, PAGE_VECTOR)
        self.assertIs(reg.MAPLIBRE_WEB.renderer_id, WebMapRendererAdapter.DEFAULT_RENDERER)
        self.assertIs(reg.MAPLIBRE_WEB.renderer_id, RendererCapabilityProbe.DEFAULT_RENDERER)

    def test_is_static_matches_legacy_hardcoded_set(self):
        # 历史判断：renderer_id in {"rasterio-matplotlib-page", "matplotlib-vector-page"}
        legacy_static = {"rasterio-matplotlib-page", "matplotlib-vector-page"}
        probes = ("rasterio-matplotlib-page", "matplotlib-vector-page",
                  "maplibre-web", "unknown-backend", "auto-fallback", "")
        for rid in probes:
            self.assertEqual(reg.is_static(rid), rid in legacy_static,
                             f"is_static({rid!r}) must equal legacy `in {{...}}` result")

    def test_is_static_tolerates_missing_renderer_id(self):
        # compiler.layout 用 is_static(scene.get("renderer_id")) 取代字面量集合判断，
        # 缺字段时必须与 `None in {...}` 一样为 False，而不是抛错。
        self.assertFalse(reg.is_static(None))
        self.assertFalse(reg.is_browser(None))
        self.assertFalse(reg.is_known(None))

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
