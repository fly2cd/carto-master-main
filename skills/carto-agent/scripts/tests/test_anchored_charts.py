"""P6 anchored chart annotation, refactored to ONE chart component (kind-discriminated).

Guards against component explosion: bar/pie/line are kinds of a single C[chart] component;
anchoring is an orthogonal placement concern. Adding a kind extends the enum + renderer
branch, never a new component/schema.
"""
from __future__ import annotations

from pathlib import Path
import sys
import unittest

SCRIPTS_ROOT = Path(__file__).resolve().parents[1]
if str(SCRIPTS_ROOT) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_ROOT))

from carto_core.compiler.anchored_charts import build_anchored_charts
from carto_core.compiler.component_registry import (
    _COMPONENT_DEFINITIONS, validate_component_instance,
)
from carto_core.errors import ProtocolError
from carto_core.schema_registry import SchemaRegistry
from tests.fixtures.schema_cases import VALID_CASES

PARAMS = VALID_CASES["chart-parameters"]
WINDOW = {"x": 0, "y": 0, "width": 400, "height": 300}
RECORDS = [
    {"id": "hangzhou", "position": {"x": 200, "y": 150},
     "values": {"urban": 80838, "rural": 53636}, "ratio_label": "1.51"},
    {"id": "ningbo", "position": {"x": 300, "y": 160},
     "values": {"urban": 86088, "rural": 53636}, "ratio_label": "1.60"},
]


class AnchoredChartTests(unittest.TestCase):
    def test_builds_chart_graphics_kind_discriminated(self):
        g = build_anchored_charts(RECORDS, PARAMS, WINDOW, frame_id="main-map")
        self.assertEqual(len(g), 2)
        self.assertTrue(all(x["type"] == "chart" for x in g))
        self.assertTrue(all(x["kind"] == "bar-vertical" for x in g))
        self.assertEqual(g[0]["max_value"], 86088)
        self.assertEqual(len(g[0]["bars"]), 2)
        self.assertEqual(g[0]["ratio_label"], "1.51")

    def test_single_chart_component_no_per_kind_explosion(self):
        # ONE chart component; bar/pie/line are kinds, not separate components.
        self.assertIn("chart", _COMPONENT_DEFINITIONS)
        self.assertNotIn("anchored-bar-chart", _COMPONENT_DEFINITIONS)
        self.assertNotIn("bar-chart", _COMPONENT_DEFINITIONS)
        self.assertNotIn("pie-chart", _COMPONENT_DEFINITIONS)
        self.assertEqual(_COMPONENT_DEFINITIONS["chart"]["parameter_schema"], "chart-parameters")

    def test_new_kind_needs_no_new_component(self):
        # pie is a declared kind of the SAME chart component; validates against the same
        # schema (no new component/schema). Renderer branch not yet implemented -> fail closed.
        registry = SchemaRegistry()
        pie_params = {**PARAMS, "kind": "pie"}
        validate_component_instance({"type": "chart", "parameters": pie_params}, registry)
        with self.assertRaises(ProtocolError) as r:
            build_anchored_charts(RECORDS, pie_params, WINDOW, frame_id="main-map")
        self.assertEqual("CHART_KIND_NOT_IMPLEMENTED", r.exception.code)

    def test_fixed_placement_keeps_offset(self):
        rec = [{**RECORDS[0], "offset": {"x": 40, "y": -80}}]
        g = build_anchored_charts(rec, PARAMS, WINDOW, frame_id="main-map", placement="fixed")
        self.assertEqual(g[0]["offset_x_px"], 40)
        self.assertEqual(g[0]["offset_y_px"], -80)

    def test_preferred_placement_clamps_into_window(self):
        rec = [{"id": "edge", "position": {"x": 395, "y": 150},
                "values": {"urban": 10, "rural": 5}, "offset": {"x": 50, "y": -80}}]
        g = build_anchored_charts(rec, PARAMS, WINDOW, frame_id="main-map", placement="preferred")
        self.assertLessEqual(g[0]["position"]["x"] + g[0]["offset_x_px"] + g[0]["width_px"],
                             WINDOW["width"])

    def test_no_data_and_invalid_scale_refused(self):
        with self.assertRaises(ProtocolError):
            build_anchored_charts([], PARAMS, WINDOW, frame_id="main-map")
        with self.assertRaises(ProtocolError):
            build_anchored_charts([{"id": "z", "position": {"x": 1, "y": 1},
                                    "values": {"urban": 0}}], PARAMS, WINDOW, frame_id="main-map")

    def test_unknown_param_refused_closed_schema(self):
        registry = SchemaRegistry()
        validate_component_instance({"type": "chart", "parameters": PARAMS}, registry)
        with self.assertRaises(ProtocolError):
            validate_component_instance({"type": "chart", "parameters": {**PARAMS, "knob": 1}}, registry)

    def test_chart_graphic_schema_valid(self):
        registry = SchemaRegistry()
        g = build_anchored_charts(RECORDS, PARAMS, WINDOW, frame_id="main-map")[0]

        def find(node):
            if isinstance(node, dict):
                if "image_graphics" in node.get("properties", {}):
                    return node["properties"]["image_graphics"]["items"]
                for v in node.values():
                    r = find(v)
                    if r is not None:
                        return r
            elif isinstance(node, list):
                for v in node:
                    r = find(v)
                    if r is not None:
                        return r
            return None

        item_schema = find(registry.schemas["render-scene"])
        self.assertIsNotNone(item_schema)
        import jsonschema
        jsonschema.validators.validator_for(item_schema)(
            item_schema, registry=registry.registry).validate(g)


if __name__ == "__main__":
    unittest.main()