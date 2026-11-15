from __future__ import annotations

import unittest
from copy import deepcopy
from pathlib import Path
import sys

SCRIPTS_ROOT = Path(__file__).resolve().parents[1]
if str(SCRIPTS_ROOT) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_ROOT))

from carto_core.errors import ProtocolError
from carto_core.schema_registry import SchemaRegistry
from carto_core.compiler.chart_core import validate_chart, bind_chart_slots


def bar_chart(**overrides):
    base = {"chart_id": "chart-001", "content_id": "chart-frame",
            "kind": "bar-horizontal", "title": "Top industries",
            "value_max": 150,
            "series": [{"label": "Electronics", "value": 120, "color": "#2288CC"},
                       {"label": "Equipment", "value": 150, "color": "#CC3322"}]}
    base.update(overrides)
    return base


def pie_chart(**overrides):
    base = {"chart_id": "chart-002", "content_id": "chart-frame",
            "kind": "pie", "title": "Industry composition",
            "denominator": {"scope": "sum-of-parts"},
            "series": [{"label": "Electronics", "value": 120, "color": "#2288CC"},
                       {"label": "Equipment", "value": 90, "color": "#CC3322"},
                       {"label": "Textile", "value": 70, "color": "#228833"}]}
    base.update(overrides)
    return base


def layout_with_chart_slot():
    return {"contract": {"frames": [
        {"content_id": "map-1", "type": "map"},
        {"content_id": "chart-frame", "type": "chart"},
    ]}}


class ChartSchemaTests(unittest.TestCase):
    """chart.schema.json: kind-conditional requirements and strict typing."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.registry = SchemaRegistry()

    def test_bar_chart_accepted(self) -> None:
        self.registry.validate("chart", bar_chart())

    def test_pie_chart_accepted(self) -> None:
        self.registry.validate("chart", pie_chart())

    def test_bar_missing_value_max_rejected(self) -> None:
        chart = bar_chart()
        del chart["value_max"]
        with self.assertRaises(ProtocolError):
            self.registry.validate("chart", chart)

    def test_pie_missing_denominator_rejected(self) -> None:
        chart = pie_chart()
        del chart["denominator"]
        with self.assertRaises(ProtocolError):
            self.registry.validate("chart", chart)

    def test_declared_total_missing_total_rejected(self) -> None:
        chart = pie_chart()
        chart["denominator"] = {"scope": "declared-total"}
        with self.assertRaises(ProtocolError):
            self.registry.validate("chart", chart)

    def test_unknown_kind_rejected(self) -> None:
        with self.assertRaises(ProtocolError):
            self.registry.validate("chart", bar_chart(kind="scatter"))

    def test_empty_series_rejected(self) -> None:
        with self.assertRaises(ProtocolError):
            self.registry.validate("chart", bar_chart(series=[]))

    def test_unknown_member_rejected(self) -> None:
        chart = bar_chart()
        chart["orientation"] = "auto"
        with self.assertRaises(ProtocolError):
            self.registry.validate("chart", chart)


class ChartCoreSemanticTests(unittest.TestCase):
    """chart_core: explicit shared scale, pie denominator semantics, no implicit normalization."""

    def test_shared_scale_proportion(self) -> None:
        # The design doc's canonical example: 150 -> 60px means 120 -> 48px (fraction 0.8).
        computed = validate_chart(bar_chart())
        self.assertAlmostEqual(120 / 150, computed["fractions"][0])
        self.assertAlmostEqual(150 / 150, computed["fractions"][1])
        self.assertEqual(150, computed["value_max"])
        self.assertIsNone(computed["denominator_total"])

    def test_value_above_declared_scale_rejected(self) -> None:
        # No silent rescaling: a value above the explicit shared scale is an error,
        # not a clamped bar (this is the shared-scale vs independent-normalization trap).
        with self.assertRaisesRegex(ProtocolError, "CHART_SCALE_EXCEEDED"):
            validate_chart(bar_chart(value_max=100))

    def test_negative_bar_value_rejected(self) -> None:
        with self.assertRaisesRegex(ProtocolError, "CHART_VALUE_NEGATIVE"):
            validate_chart(bar_chart(series=[{"label": "A", "value": -1, "color": "#2288CC"}]))

    def test_duplicate_labels_rejected(self) -> None:
        with self.assertRaisesRegex(ProtocolError, "CHART_LABEL_AMBIGUOUS"):
            validate_chart(bar_chart(series=[{"label": "A", "value": 1, "color": "#2288CC"},
                                             {"label": "A", "value": 2, "color": "#CC3322"}]))

    def test_pie_sum_of_parts(self) -> None:
        # sum-of-parts: fractions sum to 1 (denominator = the series sum itself).
        computed = validate_chart(pie_chart())
        self.assertAlmostEqual(120 / 280, computed["fractions"][0])
        self.assertAlmostEqual(90 / 280, computed["fractions"][1])
        self.assertAlmostEqual(70 / 280, computed["fractions"][2])
        self.assertAlmostEqual(1.0, sum(computed["fractions"]))
        self.assertEqual(280, computed["denominator_total"])

    def test_pie_declared_total(self) -> None:
        # declared-total: using 330 as the denominator expresses a different question
        # than using 280 -- the remainder (50) represents other categories.
        chart = pie_chart()
        chart["denominator"] = {"scope": "declared-total", "total": 330}
        computed = validate_chart(chart)
        self.assertAlmostEqual(120 / 330, computed["fractions"][0])
        self.assertAlmostEqual(280 / 330, sum(computed["fractions"]))
        self.assertEqual(330, computed["denominator_total"])

    def test_pie_declared_total_below_sum_rejected(self) -> None:
        chart = pie_chart()
        chart["denominator"] = {"scope": "declared-total", "total": 200}
        with self.assertRaisesRegex(ProtocolError, "CHART_DENOMINATOR_INVALID"):
            validate_chart(chart)

    def test_pie_nonpositive_value_rejected(self) -> None:
        chart = pie_chart(series=[{"label": "A", "value": 0, "color": "#2288CC"}])
        with self.assertRaisesRegex(ProtocolError, "CHART_PIE_VALUE_INVALID"):
            validate_chart(chart)

    def test_output_is_placement_agnostic(self) -> None:
        # The core output carries only local fractions -- no page or geographic
        # coordinates -- so the same core serves page frames and geo anchors.
        computed = validate_chart(bar_chart())
        self.assertEqual({"kind", "fractions", "sum", "value_max", "denominator_total", "count"},
                         set(computed))
        self.assertTrue(all(0.0 <= f <= 1.0 for f in computed["fractions"]))


class ChartSlotBindingTests(unittest.TestCase):
    """bind_chart_slots: page-frame binding by content_id, exact match required."""

    def test_exact_binding_accepted(self) -> None:
        charts = [bar_chart()]
        result = bind_chart_slots(layout_with_chart_slot(), charts)
        self.assertEqual(1, len(result))

    def test_unbound_slot_rejected(self) -> None:
        with self.assertRaisesRegex(ProtocolError, "CHART_SLOT_BINDING"):
            bind_chart_slots(layout_with_chart_slot(), [])

    def test_unknown_chart_rejected(self) -> None:
        chart = bar_chart(content_id="unknown-frame")
        with self.assertRaisesRegex(ProtocolError, "CHART_SLOT_BINDING"):
            bind_chart_slots(layout_with_chart_slot(), [chart])

    def test_duplicate_binding_rejected(self) -> None:
        charts = [bar_chart(), pie_chart(content_id="chart-frame")]
        with self.assertRaisesRegex(ProtocolError, "CHART_SLOT_DUPLICATE"):
            bind_chart_slots(layout_with_chart_slot(), charts)


try:
    import importlib.util as _ilu
    _HAS_FIONA = _ilu.find_spec("fiona") is not None
except Exception:
    _HAS_FIONA = False


@unittest.skipUnless(_HAS_FIONA, "vector integration requires Fiona (geo313 environment)")
class ChartCompilePageTests(unittest.TestCase):
    """Integration: compile_page freezes charts into the page request with full slot binding."""

    def _compile_with_chart(self, chart):
        import json
        import tempfile
        from pathlib import Path as P
        from carto_core.workflow.vector_preparation import VectorPreparationService
        from carto_core.compiler.vector_portrayal import VectorPortrayalCompiler
        from carto_core.compiler.vector_page import compile_page
        from carto_core.compiler.layout import LayoutResolver
        from carto_core.workflow.models import ExecutionContext
        from carto_core.artifacts import file_digest
        from tests.fixtures.schema_cases import VALID_CASES
        from copy import deepcopy
        root = P(tempfile.mkdtemp())
        features = [{"type": "Feature", "geometry": {"type": "Point", "coordinates": [0.0, 0.0]},
                     "properties": {"code": "A", "value": 1.0}}]
        f = root / "pts.geojson"
        f.write_text(json.dumps({"type": "FeatureCollection", "features": features}), encoding="utf8")
        source = {"schema_version": 1, "source_id": "pts", "role": "thematic-features",
                  "format": "geojson", "crs": "EPSG:4326", "encoding": "utf-8",
                  "files": [{"extension": ".geojson", "path": str(f), "digest": file_digest(f),
                             "size_bytes": f.stat().st_size}],
                  "data_nature": "user-provided", "contains_sensitive_coordinates": False,
                  "contains_production_data": False, "license": "project-approved"}
        registry = SchemaRegistry()
        service = VectorPreparationService(project_root=root, allowed_roots=[str(root)], registry=registry)
        context = ExecutionContext("run", "tenant", "project", "subj",
                                    frozenset({"operator"}), frozenset({"project"}), frozenset())
        prepared = service.prepare(source, context)
        symbol = {"color": "#2277AA", "stroke": "#222222", "stroke_width_pt": 0.4, "radius_mm": 2}
        encoding = {"schema_version": 1, "key_mode": "discrete", "geometry_role": "point",
                    "domain": {"field": None, "measurement": "nominal", "unit": None, "normalization": None},
                    "scale": {"categories": []},
                    "channels": {"symbols": [symbol], "shape": "auto"},
                    "missing": {"policy": "reject", "label": "Missing", "symbol": None},
                    "legend": {"policy": "all", "uniform_label": "Features"}}
        portrayal = VectorPortrayalCompiler(service).compile(prepared.ref(), encoding, context)
        layout_doc = deepcopy(VALID_CASES["layout"])
        # Shrink the single map frame in this private copy to free a bottom strip;
        # the shared fixture itself is never mutated.
        layout_doc["frames"][0]["bounds"] = [20, 120, 380, 140]
        layout_doc["frames"].append({"id": "frame-chart", "content_id": "chart-frame",
                                      "type": "chart", "coordinate_space": "page",
                                      "bounds": [20, 30, 160, 80], "overflow_policy": "reject"})
        layout_doc["frames"].append({"id": "frame-legend", "content_id": "legend-frame",
                                      "type": "legend", "coordinate_space": "page",
                                      "bounds": [200, 30, 160, 80], "overflow_policy": "reject",
                                      "view_ids": ["main-view"]})
        layout_doc["frames"].append({"id": "frame-title", "content_id": "title-frame",
                                      "type": "title", "coordinate_space": "page",
                                      "bounds": [20, 262, 380, 20], "overflow_policy": "reject"})
        layout = LayoutResolver(registry).resolve(layout_doc, 300)
        map_frame = next(f for f in layout["contract"]["frames"] if f["type"] == "map")
        panels = [{"view_id": map_frame["content_id"], "portrayal_ref": portrayal.ref(),
                   "extent": [-1, -1, 1, 1]}]
        texts = [{"content_id": fr["content_id"], "text": "T" if fr["type"] == "title" else "S"}
                 for fr in layout["contract"]["frames"] if fr["type"] not in {"map", "legend", "chart"}]
        legend_titles = {fr["content_id"]: "L" for fr in layout["contract"]["frames"] if fr["type"] == "legend"}
        font = {"path": str(f), "digest": file_digest(f), "size_bytes": f.stat().st_size}
        cartography = deepcopy(VALID_CASES["cartography"])
        return compile_page(service, layout=layout, cartography=cartography, panels=panels,
                            font=font, texts=texts, legend_titles=legend_titles, context=context,
                            charts=[chart])

    def test_chart_frozen_into_page(self) -> None:
        page = self._compile_with_chart(bar_chart(content_id="chart-frame"))
        self.assertEqual(1, len(page["charts"]))
        frozen = page["charts"][0]
        self.assertEqual("bar-horizontal", frozen["kind"])
        self.assertEqual(150, frozen["value_max"])
        self.assertEqual(2, len(frozen["series"]))

    def test_chart_scale_violation_propagates(self) -> None:
        with self.assertRaisesRegex(ProtocolError, "CHART_SCALE_EXCEEDED"):
            self._compile_with_chart(bar_chart(content_id="chart-frame", value_max=100))

    def test_unbound_chart_rejected_at_page_compile(self) -> None:
        with self.assertRaisesRegex(ProtocolError, "CHART_SLOT_BINDING"):
            self._compile_with_chart(bar_chart(content_id="nonexistent-frame"))




@unittest.skipUnless(_HAS_FIONA, "vector integration requires Fiona (geo313 environment)")
class StackedLayerPanelTests(unittest.TestCase):
    """Integration: an ordered two-layer panel (choropleth base + points on top)."""

    def _compile_stacked_page(self):
        import json
        import tempfile
        from pathlib import Path as P
        from carto_core.workflow.vector_preparation import VectorPreparationService
        from carto_core.compiler.vector_portrayal import VectorPortrayalCompiler
        from carto_core.compiler.vector_page import compile_page, validate_page
        from carto_core.compiler.layout import LayoutResolver
        from carto_core.workflow.models import ExecutionContext
        from carto_core.artifacts import file_digest
        from tests.fixtures.schema_cases import VALID_CASES
        from copy import deepcopy
        root = P(tempfile.mkdtemp())
        # Layer 1 (ground): three polygons with a category field.
        polygons = [{"type": "Feature",
                     "geometry": {"type": "Polygon",
                                  "coordinates": [[[i, 0], [i + .8, 0], [i + .8, .8], [i, .8], [i, 0]]]},
                     "properties": {"code": "A" if i == 0 else "B"}}
                    for i in range(3)]
        f1 = root / "areas.geojson"
        f1.write_text(json.dumps({"type": "FeatureCollection", "features": polygons}), encoding="utf8")
        # Layer 2 (figure): points on top of the polygons.
        points = [{"type": "Feature", "geometry": {"type": "Point", "coordinates": [float(i + .4), 0.4]},
                   "properties": {"code": "A" if i == 0 else "B"}}
                  for i in range(3)]
        f2 = root / "sites.geojson"
        f2.write_text(json.dumps({"type": "FeatureCollection", "features": points}), encoding="utf8")
        def source(sid, path):
            return {"schema_version": 1, "source_id": sid, "role": "thematic-features",
                    "format": "geojson", "crs": "EPSG:4326", "encoding": "utf-8",
                    "files": [{"extension": ".geojson", "path": str(path), "digest": file_digest(path),
                               "size_bytes": path.stat().st_size}],
                    "data_nature": "user-provided", "contains_sensitive_coordinates": False,
                    "contains_production_data": False, "license": "project-approved"}
        registry = SchemaRegistry()
        service = VectorPreparationService(project_root=root, allowed_roots=[str(root)], registry=registry)
        context = ExecutionContext("run", "tenant", "project", "subj",
                                    frozenset({"operator"}), frozenset({"project"}), frozenset())
        symbol = {"color": "#2277AA", "stroke": "#222222", "stroke_width_pt": 0.4, "radius_mm": 2}
        missing = {"policy": "reject", "label": "Missing", "symbol": None}
        poly_ir = {"schema_version": 1, "key_mode": "discrete", "geometry_role": "polygon",
                   "domain": {"field": "code", "measurement": "nominal", "unit": None, "normalization": None},
                   "scale": {"categories": [{"value": "A", "label": "Area A"}, {"value": "B", "label": "Area B"}]},
                   "channels": {"symbols": [dict(symbol, color="#66AA99"), dict(symbol, color="#EEAA44")], "shape": "auto"},
                   "missing": missing, "legend": {"policy": "observed"}}
        # Same categorical domain as the ground layer: a shared legend requires
        # identical categories/scales, so both layers key on the A/B domain.
        point_ir = {"schema_version": 1, "key_mode": "discrete", "geometry_role": "point",
                    "domain": {"field": "code", "measurement": "nominal", "unit": None, "normalization": None},
                    "scale": {"categories": [{"value": "A", "label": "Area A"}, {"value": "B", "label": "Area B"}]},
                    "channels": {"symbols": [dict(symbol, color="#66AA99"), dict(symbol, color="#EEAA44")], "shape": "auto"},
                    "missing": missing, "legend": {"policy": "observed"}}
        p1 = VectorPortrayalCompiler(service).compile(service.prepare(source("areas", f1), context).ref(), poly_ir, context)
        p2 = VectorPortrayalCompiler(service).compile(service.prepare(source("sites", f2), context).ref(), point_ir, context)
        layout_doc = deepcopy(VALID_CASES["layout"])
        # Shrink the map frame to free a bottom strip (shared fixture untouched).
        layout_doc["frames"][0]["bounds"] = [20, 120, 380, 140]
        layout_doc["frames"].append({"id": "frame-legend", "content_id": "legend-frame",
                                      "type": "legend", "coordinate_space": "page",
                                      "bounds": [200, 30, 160, 80], "overflow_policy": "reject",
                                      "view_ids": ["main-view"]})
        layout_doc["frames"].append({"id": "frame-title", "content_id": "title-frame",
                                      "type": "title", "coordinate_space": "page",
                                      "bounds": [20, 262, 380, 20], "overflow_policy": "reject"})
        layout = LayoutResolver(registry).resolve(layout_doc, 300)
        map_frame = next(f for f in layout["contract"]["frames"] if f["type"] == "map")
        panel = {"view_id": map_frame["content_id"], "extent": [-1, -1, 4, 2],
                 "layers": [{"portrayal_ref": p1.ref()}, {"portrayal_ref": p2.ref()}]}
        texts = [{"content_id": fr["content_id"], "text": "T" if fr["type"] == "title" else "S"}
                 for fr in layout["contract"]["frames"] if fr["type"] not in {"map", "legend", "chart"}]
        legend_titles = {fr["content_id"]: "L" for fr in layout["contract"]["frames"] if fr["type"] == "legend"}
        font = {"path": str(f1), "digest": file_digest(f1), "size_bytes": f1.stat().st_size}
        page = compile_page(service, layout=layout, cartography=deepcopy(VALID_CASES["cartography"]),
                            panels=[panel], font=font, texts=texts, legend_titles=legend_titles,
                            context=context)
        return service, page, context

    def test_stacked_panel_freezes_ordered_layers(self):
        service, page, context = self._compile_stacked_page()
        panel = page["panels"][0]
        self.assertIn("layers", panel)
        self.assertEqual(2, len(panel["layers"]))
        # Binding identity: multi-layer views get per-layer ids in declared order.
        layer_ids = [l["id"] for l in page["bindings"]["layers"]]
        self.assertEqual(["layer-main-view-0", "layer-main-view-1"], layer_ids)
        self.assertEqual(2, len(page["bindings"]["views"][0]["layer_ids"]))
        self.assertEqual(2, len(page["bindings"]["data_bindings"]))

    def test_stacked_panel_replay_is_exact(self):
        from carto_core.compiler.vector_page import validate_page
        service, page, context = self._compile_stacked_page()
        layers = validate_page(service, page, context)
        self.assertEqual(2, len(layers["main-view"]))
        self.assertEqual("polygon", layers["main-view"][0]["report"]["geometry"])
        self.assertEqual("point", layers["main-view"][1]["report"]["geometry"])

    def test_legacy_single_panel_still_passes(self):
        # The oneOf compatibility: a legacy single-layer panel behaves exactly as before.
        service, page, context = self._compile_stacked_page()
        panel = {k: v for k, v in page["panels"][0].items() if k != "layers"}
        panel["portrayal_ref"] = page["panels"][0]["layers"][0]["portrayal_ref"]
        stripped = {k: v for k, v in panel.items() if k != "frame_id"}
        from carto_core.compiler.vector_page import _panel_refs
        refs = _panel_refs(stripped)
        self.assertEqual(1, len(refs))


if __name__ == "__main__":
    unittest.main()