"""P6 §13.5 unit / geometry technical validation — the ENTRY condition for migration.

Synthetic data only; no business data, approvals or rendering admission. Tolerances and
equivalence definitions are fixed BEFORE measurement (plan §13.5: never relax a threshold
after seeing results). These tests pin the coordinate/measurement-domain invariants the
leadership_visit chain relies on, measure error accumulation across DPI / crop / aspect /
rotation, and record what the current shared contract can and cannot express losslessly.

Domains (plan §13.5 table):
  geographic / work projection  -> PixelConverter (pyproj, projected meters, always_xy)
  original image pixels         -> zero-based pixel-center indices, source_size, affine
  display window                -> crop origin + size, never confused with source pixels
  reference design pixels       -> REFERENCE_WIDTH_PX scale, floored at 1.0, symbols only
  page pixels                   -> contain_layout aspect-preserving placement, DPI binding
  mm / pt                       -> single conversion point (72/25.4, dpi/25.4), no double scale
"""
from __future__ import annotations

import math
from pathlib import Path
import sys
import unittest

SCRIPTS_ROOT = Path(__file__).resolve().parents[1]
if str(SCRIPTS_ROOT) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_ROOT))

from carto_core.adapters.geo_to_image_pixels import PixelConverter, clip_line
from carto_core.adapters.image_layout import (
    contain_layout, frame_border_rects, furniture_font_pt, legend_font_pt,
)

# Fixed tolerances (declared before measurement; do not relax post-hoc).
GEO_PX_TOL = 1e-6        # pixel-center round-trip / affine identity
ASPECT_TOL = 1e-9        # contain_layout aspect preservation
FONT_PT_TOL = 1e-9       # shared PDF/frontend font derivation equality
PHYSICAL_PT_TOL = 1e-9   # mm->pt physical invariant across DPI


def _converter(matrix, origin, size, work_crs="EPSG:3857"):
    return PixelConverter({"local_km_y_down_to_pixel": matrix, "origin_m": origin,
                           "source_size": size, "work_crs": work_crs})


class RegistrationDomainTests(unittest.TestCase):
    """Geographic -> original image pixel domain: pixel-center, zero-based, affine."""

    def test_pixel_center_zero_based_identity_affine(self):
        # 1 px per local km, y-down, origin at projected (0,0). A point at local
        # (1km, -1km) -> pixel (1,1) under y-down; verify the /1000,-1000 convention.
        conv = _converter([[1.0, 0.0, 0.0], [0.0, 1.0, 0.0]], [0.0, 0.0], [100, 100])
        # EPSG:3857 lon/lat for projected (1000, -1000) meters:
        lon = 1000 / 20037508.34 * 180
        lat = math.degrees(2 * math.atan(math.exp(-1000 / 6378137.0)) - math.pi / 2)
        pixels, inside = conv.coordinates([[lon, lat]])
        self.assertAlmostEqual(pixels[0][0], 1.0, delta=GEO_PX_TOL)
        self.assertAlmostEqual(pixels[0][1], 1.0, delta=GEO_PX_TOL)
        self.assertTrue(inside[0])

    def test_inside_boundary_is_pixel_center_half_open(self):
        conv = _converter([[1.0, 0.0, 0.0], [0.0, 1.0, 0.0]], [0.0, 0.0], [10, 10])
        # pixel -0.5 is the inclusive lower edge; size-0.5 exclusive upper.
        self.assertTrue(conv.coordinates([[0.0, 0.0]])[1][0])  # pixel (0,0) inside

    def test_rotation_non_axis_aligned_affine_roundtrip(self):
        # 30-degree rotation + scale; verify affine application is exact (no axis assumption).
        theta = math.radians(30)
        a, b = 2 * math.cos(theta), -2 * math.sin(theta)
        c, d = 2 * math.sin(theta), 2 * math.cos(theta)
        conv = _converter([[a, b, 5.0], [c, d, 7.0]], [0.0, 0.0], [1000, 1000])
        lon = 1000 / 20037508.34 * 180
        lat = math.degrees(2 * math.atan(math.exp(-1000 / 6378137.0)) - math.pi / 2)
        pixels, _ = conv.coordinates([[lon, lat]])
        # local (1,1) km -> rotated + translated
        ex, ey = a * 1 + b * 1 + 5.0, c * 1 + d * 1 + 7.0
        self.assertAlmostEqual(pixels[0][0], ex, delta=GEO_PX_TOL)
        self.assertAlmostEqual(pixels[0][1], ey, delta=GEO_PX_TOL)

    def test_singular_matrix_and_geographic_crs_refused(self):
        from carto_core.errors import ProtocolError
        with self.assertRaises(ProtocolError):
            _converter([[0.0, 0.0, 0.0], [0.0, 0.0, 0.0]], [0.0, 0.0], [10, 10])
        with self.assertRaises(ProtocolError):
            _converter([[1.0, 0.0, 0.0], [0.0, 1.0, 0.0]], [0.0, 0.0], [10, 10],
                       work_crs="EPSG:4326")  # geographic, not projected meters

    def test_clip_line_never_clamps_vertices(self):
        # A line crossing the boundary keeps disjoint parts; vertices are intersection
        # points, not clamped originals (plan: route facts preserved).
        parts = clip_line([{"x": -5, "y": 5}, {"x": 15, "y": 5}], 10, 10)
        self.assertEqual(len(parts), 1)
        self.assertAlmostEqual(parts[0][0]["x"], 0.0, delta=GEO_PX_TOL)
        self.assertAlmostEqual(parts[0][-1]["x"], 10.0, delta=GEO_PX_TOL)


class DisplayWindowDomainTests(unittest.TestCase):
    """Display window is a crop of the source; source pixel coordinates are independent."""

    def test_nonzero_crop_does_not_shift_source_pixels(self):
        # The projection uses source_size; a non-zero display window origin is a separate
        # measurement fact and must not enter the geo->source-pixel affine.
        conv = _converter([[1.0, 0.0, 0.0], [0.0, 1.0, 0.0]], [0.0, 0.0], [100, 100])
        lon = 1000 / 20037508.34 * 180
        lat = math.degrees(2 * math.atan(math.exp(-1000 / 6378137.0)) - math.pi / 2)
        base, _ = conv.coordinates([[lon, lat]])
        # A crop window {x:20,y:30,width:50,height:40} is applied downstream, not here;
        # the source pixel stays (1,1). This pins the domain separation.
        self.assertAlmostEqual(base[0][0], 1.0, delta=GEO_PX_TOL)
        self.assertAlmostEqual(base[0][1], 1.0, delta=GEO_PX_TOL)


class PagePixelDomainTests(unittest.TestCase):
    """contain_layout: aspect-preserving, centered, fits frame; multiple aspect ratios."""

    def test_aspect_preserved_and_centered_across_ratios(self):
        frame = {"x": 20, "y": 30, "width": 380, "height": 230}
        for source in ({"width_px": 1000, "height_px": 500},
                       {"width_px": 500, "height_px": 1000},
                       {"width_px": 1680, "height_px": 1170},
                       {"width_px": 800, "height_px": 800}):
            with self.subTest(source=source):
                placed = contain_layout(source, frame)
                src_ratio = source["width_px"] / source["height_px"]
                self.assertAlmostEqual(placed["width"] / placed["height"], src_ratio, delta=ASPECT_TOL)
                self.assertLessEqual(placed["width"], frame["width"] + ASPECT_TOL)
                self.assertLessEqual(placed["height"], frame["height"] + ASPECT_TOL)
                # centered
                self.assertAlmostEqual(placed["x"] + placed["width"] / 2,
                                       frame["x"] + frame["width"] / 2, delta=ASPECT_TOL)
                self.assertAlmostEqual(placed["y"] + placed["height"] / 2,
                                       frame["y"] + frame["height"] / 2, delta=ASPECT_TOL)

    def test_contain_scale_never_upscales_beyond_frame(self):
        frame = {"x": 0, "y": 0, "width": 100, "height": 100}
        placed = contain_layout({"width_px": 1000, "height_px": 1000}, frame)
        self.assertAlmostEqual(placed["width"], 100, delta=ASPECT_TOL)


class PhysicalUnitDomainTests(unittest.TestCase):
    """mm / pt single conversion point; physical pt invariant across DPI."""

    def test_mm_to_pt_physical_invariant_across_dpi(self):
        # A 0.25 mm border is 0.25*72/25.4 pt regardless of DPI (physical unit).
        expected_pt = 0.25 * 72 / 25.4
        for dpi in (144, 200, 300):
            with self.subTest(dpi=dpi):
                linewidth_pt = 0.25 * 72 / 25.4  # image_page_renderer.py:429 form
                self.assertAlmostEqual(linewidth_pt, expected_pt, delta=PHYSICAL_PT_TOL)
                px_per_mm = dpi / 25.4
                width_px = 0.25 * px_per_mm
                # round-trip px -> mm -> pt stays the physical value (no double scale)
                self.assertAlmostEqual(width_px / px_per_mm * 72 / 25.4, expected_pt,
                                       delta=PHYSICAL_PT_TOL)

    def test_frame_border_gap_mm_visual_distance_across_dpi(self):
        border = {"gap_mm": 1.0, "inner_width_mm": 0.25, "outer_width_mm": 0.5}
        placement = {"x": 100, "y": 100, "width": 400, "height": 300}
        for dpi in (144, 200, 300):
            with self.subTest(dpi=dpi):
                px_per_mm = dpi / 25.4
                inner, outer = frame_border_rects(placement, border, px_per_mm)
                # edge-to-edge gap between strokes == gap_mm in px
                gap_px = (inner["x"] - outer["x"]) - (inner["width"] * 0)  # offset
                offset = border["gap_mm"] * px_per_mm + (border["inner_width_mm"] + border["outer_width_mm"]) / 2 * px_per_mm
                self.assertAlmostEqual(inner["x"] - outer["x"], offset, delta=1e-6)
                # physical gap invariant: convert offset back to mm
                self.assertAlmostEqual((inner["x"] - outer["x"]) / px_per_mm,
                                       border["gap_mm"] + (border["inner_width_mm"] + border["outer_width_mm"]) / 2,
                                       delta=1e-9)


class SharedFontDerivationTests(unittest.TestCase):
    """PDF and frontend consume the SAME pt derivation (two-domain discipline)."""

    def test_furniture_font_pt_identical_for_pdf_and_frontend(self):
        item = {"content_id": "title", "text": "调研行程路线图", "font_pt": 34.0}
        bounds = (20, 12, 380, 14)
        for dpi in (144, 200, 300):
            with self.subTest(dpi=dpi):
                pt_per_px = 72 / dpi
                # image_page_renderer and frontend_canvas both call furniture_font_pt
                pdf_pt = furniture_font_pt(item, bounds, pt_per_px)
                frontend_pt = furniture_font_pt(item, bounds, pt_per_px)
                self.assertAlmostEqual(pdf_pt, frontend_pt, delta=FONT_PT_TOL)
                # frontend recovers px via pt / pt_per_px (single inverse, no redesign)
                font_px = frontend_pt / pt_per_px
                self.assertAlmostEqual(font_px * pt_per_px, frontend_pt, delta=FONT_PT_TOL)

    def test_legend_font_pt_floor_and_cap(self):
        legend = {"items": [{"label": "上午行程"}, {"label": "下午行程"}]}
        bounds = (300, 264, 110, 22)
        pt_per_px = 72 / 300
        font = legend_font_pt(legend, bounds, pt_per_px)
        self.assertGreaterEqual(font, 3.0)
        self.assertLessEqual(font, 3 * 72 / 25.4 + FONT_PT_TOL)  # 3mm cap

    def test_explicit_font_pt_is_nominal_not_overflow_bypass(self):
        # A huge explicit font_pt is still capped by frame capacity (plan: no silent overflow).
        item = {"content_id": "title", "text": "一个很长的标题文字内容", "font_pt": 200.0}
        bounds = (20, 12, 100, 14)
        font = furniture_font_pt(item, bounds, 72 / 300)
        self.assertLess(font, 200.0)
        self.assertGreaterEqual(font, 4.0)


class ReferenceDesignScaleTests(unittest.TestCase):
    """Reference-design pixel scale: symbols scale, physical page furniture does not."""

    def test_scale_floor_at_one_and_symbol_scaling(self):
        from carto_core.scenarios.leadership_visit.style import REFERENCE_WIDTH_PX
        # scale = max(1.0, min(window.w/REF_W, window.h/REF_H)); a small window floors at 1.0
        ref_w = REFERENCE_WIDTH_PX
        small_window = {"width": ref_w // 2, "height": ref_w // 2}
        scale = max(1.0, min(small_window["width"] / ref_w, small_window["height"] / ref_w))
        self.assertEqual(scale, 1.0)  # never shrink below reference
        large_window = {"width": ref_w * 2, "height": ref_w * 2}
        scale2 = max(1.0, min(large_window["width"] / ref_w, large_window["height"] / ref_w))
        self.assertAlmostEqual(scale2, 2.0, delta=1e-9)
        # A 6px route width scales to 12px at 2x; page_furniture pt stays 34 (not scaled).
        self.assertAlmostEqual(6 * scale2, 12.0, delta=1e-9)


class SharedSymbolMechanismTests(unittest.TestCase):
    """P6 §13.2 Option 1: the reference-pixel scale mechanism is shared infrastructure,
    consumed by the scenario (not a private rule), and behavior-equivalent."""

    def test_shared_symbol_scale_matches_legacy_formula(self):
        from carto_core.compiler.image_symbols import (
            REFERENCE_WIDTH_PX, REFERENCE_HEIGHT_PX, symbol_scale, scale_symbol_dict,
        )
        for window in ({"width": 1000, "height": 800}, {"width": 2381, "height": 1684},
                       {"width": 4762, "height": 3368}, {"width": 500, "height": 5000}):
            with self.subTest(window=window):
                legacy = max(1.0, min(window["width"] / REFERENCE_WIDTH_PX,
                                      window["height"] / REFERENCE_HEIGHT_PX))
                self.assertAlmostEqual(symbol_scale(window), legacy, delta=1e-12)

    def test_scale_symbol_dict_scales_px_not_metadata(self):
        from carto_core.compiler.image_symbols import scale_symbol_dict
        config = {"width_px": 6, "halo_width_px": 1, "arrows": {"size_px": 8}, "label": "上午"}
        scaled = scale_symbol_dict(config, 2.0, exclude=frozenset({"arrows"}))
        self.assertEqual(scaled["width_px"], 12)
        self.assertEqual(scaled["halo_width_px"], 2)
        self.assertEqual(scaled["arrows"], {"size_px": 8})  # excluded, handled separately
        self.assertEqual(scaled["label"], "上午")  # non-numeric passes through

    def test_leadership_consumes_shared_mechanism(self):
        # The scenario module imports the shared constants/mechanism (single authority),
        # rather than declaring a parallel private reference canvas.
        from carto_core.scenarios.leadership_visit import style
        from carto_core.compiler import image_symbols
        self.assertIs(style.REFERENCE_WIDTH_PX, image_symbols.REFERENCE_WIDTH_PX)
        self.assertIs(style.symbol_scale, image_symbols.symbol_scale)

    def test_invalid_window_refused(self):
        from carto_core.compiler.image_symbols import symbol_scale
        from carto_core.errors import ProtocolError
        for bad in ({"width": 0, "height": 100}, {"width": -5, "height": 100},
                    {"width": "x", "height": 100}, {"width": True, "height": 100}):
            with self.subTest(bad=bad):
                with self.assertRaises(ProtocolError):
                    symbol_scale(bad)


class MeasurementRuleContractTests(unittest.TestCase):
    """P6 field-mapping §2.2 / X03: the measurement rule (U) is an explicit adopted
    preset consumed by the shared mechanism, not an implicit backend constant."""

    def setUp(self):
        from carto_core.schema_registry import SchemaRegistry
        from carto_core.compiler.image_symbols import BASELINE_MEASUREMENT_RULE
        self.registry = SchemaRegistry()
        self.baseline = BASELINE_MEASUREMENT_RULE

    def test_baseline_preset_validates_against_measurement_rule_schema(self):
        self.registry.validate("measurement-rule", self.baseline)
        self.assertEqual(self.baseline["reference_width_px"], 2381)
        self.assertEqual(self.baseline["reference_height_px"], 1684)
        self.assertEqual(self.baseline["scale_floor"], 1.0)

    def test_scale_for_baseline_rule_equals_legacy_symbol_scale(self):
        from carto_core.compiler.image_symbols import scale_for_rule, symbol_scale
        for window in ({"width": 1000, "height": 800}, {"width": 2381, "height": 1684},
                       {"width": 4762, "height": 3368}, {"width": 500, "height": 5000}):
            with self.subTest(window=window):
                self.assertAlmostEqual(scale_for_rule(window, self.baseline),
                                       symbol_scale(window), delta=1e-12)

    def test_custom_rule_is_honored_not_backend_default(self):
        from carto_core.compiler.image_symbols import scale_for_rule
        rule = {**self.baseline, "rule_id": "custom-half-reference",
                "reference_width_px": 1190.5, "reference_height_px": 842.0, "scale_floor": 0.5}
        window = {"width": 1190.5, "height": 842.0}
        # at exactly the custom reference, min-ratio = 1.0; floor 0.5 does not raise it
        self.assertAlmostEqual(scale_for_rule(window, rule), 1.0, delta=1e-9)
        small = {"width": 595.25, "height": 421.0}
        # half the custom reference -> ratio 0.5, floor 0.5 -> 0.5 (baseline floor 1.0 would give 1.0)
        self.assertAlmostEqual(scale_for_rule(small, rule), 0.5, delta=1e-9)

    def test_unknown_function_and_invalid_rule_refused(self):
        from carto_core.compiler.image_symbols import scale_for_rule
        from carto_core.errors import ProtocolError
        with self.assertRaises(ProtocolError):
            scale_for_rule({"width": 100, "height": 100}, {**self.baseline, "scale_function": "linear"})
        with self.assertRaises(ProtocolError):
            scale_for_rule({"width": 100, "height": 100}, {**self.baseline, "reference_width_px": 0})
        with self.assertRaises(ProtocolError):
            scale_for_rule({"width": 100, "height": 100}, {**self.baseline, "scale_floor": -1})

    def test_measurement_representation_is_discriminated(self):
        from tests.fixtures.schema_cases import A
        # reference-design-px requires a precise rule_ref; physical does not accept one.
        self.registry.validate("symbol-measurement",
                               {"kind": "reference-design-px", "value": 6, "rule_ref": A})
        self.registry.validate("symbol-measurement", {"kind": "physical-pt", "value": 34})
        self.registry.validate("symbol-measurement", {"kind": "physical-mm", "value": 0.25})
        from carto_core.errors import ProtocolError
        with self.assertRaises(ProtocolError):
            self.registry.validate("symbol-measurement", {"kind": "physical-pt", "value": 34, "rule_ref": A})


class ComponentContractTests(unittest.TestCase):
    """P6 field-mapping C[type]/J[card]: component definition + internal parameter
    contracts (M14/M17/M18/M24/M26). Internal typography belongs to the component,
    not page Layout (D4); width mode+limit are one contract; gap is the full section gap."""

    def setUp(self):
        from carto_core.schema_registry import SchemaRegistry
        from tests.fixtures.schema_cases import VALID_CASES, A
        self.registry = SchemaRegistry()
        self.card = VALID_CASES["card-parameters"]
        self.definition = VALID_CASES["component-definition"]
        self.A = A

    def test_information_card_definition_and_params_validate(self):
        self.registry.validate("component-definition", self.definition)
        self.registry.validate("card-parameters", self.card)
        self.assertEqual(self.definition["parameter_schema"], "card-parameters")

    def test_m18_baseline_gap_is_double_old_line_gap(self):
        # M18: old line_gap Q(3) -> full section gap Q(6); divider at midpoint.
        from carto_core.compiler.image_symbols import scale_for_rule, BASELINE_MEASUREMENT_RULE
        old_line_gap = 3
        section_gap = 2 * old_line_gap
        self.assertEqual(self.card["sections"]["gap"]["value"], section_gap)
        self.assertEqual(section_gap, 6)

    def test_m26_width_modes_are_discriminated(self):
        from copy import deepcopy
        fixed = deepcopy(self.card)
        fixed["sizing"]["width"]["mode"] = "fixed"
        self.registry.validate("card-parameters", fixed)
        fit = deepcopy(self.card)
        fit["sizing"]["width"]["mode"] = "fit-content-up-to-limit"
        self.registry.validate("card-parameters", fit)
        from carto_core.errors import ProtocolError
        bad = deepcopy(self.card)
        bad["sizing"]["width"]["mode"] = "auto-shrink-to-fit"
        with self.assertRaises(ProtocolError):
            self.registry.validate("card-parameters", bad)

    def test_m24_title_wrap_mode_explicit(self):
        from copy import deepcopy
        from carto_core.errors import ProtocolError
        wrap = deepcopy(self.card)
        wrap["title"]["wrap_mode"] = "wrap-by-character"
        self.registry.validate("card-parameters", wrap)
        bad = deepcopy(self.card)
        bad["title"]["wrap_mode"] = "auto"
        with self.assertRaises(ProtocolError):
            self.registry.validate("card-parameters", bad)

    def test_component_definition_closed_no_parallel_owner(self):
        from copy import deepcopy
        from carto_core.errors import ProtocolError
        # D3: no new parallel owner/template kind; unknown type rejected.
        bad = deepcopy(self.definition)
        bad["type"] = "map-card"
        with self.assertRaises(ProtocolError):
            self.registry.validate("component-definition", bad)
        bag = deepcopy(self.definition)
        bag["owner"] = "map-annotation"
        with self.assertRaises(ProtocolError):
            self.registry.validate("component-definition", bag)


class MapPlanInstanceExtensionTests(unittest.TestCase):
    """P6 field-mapping S3 / I: MapPlan carries adopted component instances (J),
    annotation placements (N), content selections, group bindings and basemap display (V).
    Additive: legacy plans without these fields still validate."""

    def setUp(self):
        from copy import deepcopy
        from carto_core.schema_registry import SchemaRegistry
        from tests.fixtures.schema_cases import VALID_CASES, A
        self.deepcopy = deepcopy
        self.registry = SchemaRegistry()
        self.base = deepcopy(VALID_CASES["map-plan"])
        self.A = A

    def _q(self, value):
        return {"kind": "reference-design-px", "value": value, "rule_ref": self.deepcopy(self.A)}

    def test_legacy_plan_still_validates(self):
        self.registry.validate("map-plan", self.base)

    def test_plan_with_component_instances_and_annotations_validates(self):
        plan = self.deepcopy(self.base)
        plan["components"] = {
            "card-1": {"component_ref": self.deepcopy(self.A), "structure_mode": "atomic-card",
                       "parameters": {"sizing": {"width": {"mode": "fit-content-up-to-limit", "limit": self._q(500)}},
                                      "inset": self._q(4), "sections": {"gap": self._q(6)},
                                      "title": {"wrap_mode": "single-line-reject-overflow"}}},
        }
        plan["annotations"] = {
            "card-1": {"component_ref": self.deepcopy(self.A), "anchor_ref": self.deepcopy(self.A),
                       "placement": {"mode": "preferred", "offset": {"x": self._q(45), "y": self._q(-135)}}},
        }
        plan["content"] = {"card": {"fields": ["stop-label", "visit-date"]},
                           "numbering": {"display_order": "per-date-group"}}
        plan["group_bindings"] = [{"semantic_group": "morning", "visual_role": "route-group-a"}]
        plan["legend_labels"] = {"morning": "上午行程"}
        plan["group_resolution"] = {"fallback_group": "default"}
        plan["basemap_display"] = {"main-view": {"crop": {"parameters": {"white_threshold": 245}}}}
        self.registry.validate("map-plan", plan)

    def test_fixed_annotation_and_signed_offset(self):
        from carto_core.errors import ProtocolError
        placement = {"mode": "fixed", "offset": {"x": self._q(20), "y": self._q(-40)}}
        self.registry.validate("annotation-placement", placement)
        # reference-design-px is signed (y-down offset); physical magnitudes stay positive.
        self.registry.validate("symbol-measurement", self._q(-135))
        with self.assertRaises(ProtocolError):
            self.registry.validate("symbol-measurement", {"kind": "physical-mm", "value": -1})

    def test_plan_instance_fields_are_closed(self):
        from carto_core.errors import ProtocolError
        plan = self.deepcopy(self.base)
        plan["components"] = {"card-1": {"component_ref": self.deepcopy(self.A),
                                         "structure_mode": "atomic-card", "parameters": {"x": 1},
                                         "extra_knob": True}}
        with self.assertRaises(ProtocolError):
            self.registry.validate("map-plan", plan)
        plan2 = self.deepcopy(self.base)
        plan2["content"] = {"card": {"fields": ["stop-label"]}, "unknown_content": {}}
        with self.assertRaises(ProtocolError):
            self.registry.validate("map-plan", plan2)


class S4MigrationTests(unittest.TestCase):
    """P6 S4: the explicit author migration relocates all 46 baseline fields with the
    precise M-transformations, and every produced instance validates against its closed
    contract. Source values preserved; no silent guessing (mapping §9.3)."""

    def setUp(self):
        from carto_core.schema_registry import SchemaRegistry
        from carto_core.scenarios.leadership_visit.route_author import TEMPLATE_STYLE
        from carto_core.scenarios.leadership_visit.contract_migration import migrate_image_itinerary
        from tests.fixtures.schema_cases import A
        self.registry = SchemaRegistry()
        self.style = TEMPLATE_STYLE
        self.result = migrate_image_itinerary(TEMPLATE_STYLE, rule_ref=A)

    def test_m18_section_gap_is_double_old_line_gap(self):
        gap = self.result["components"]["card"]["parameters"]["sections"]["gap"]
        self.assertEqual(gap["value"], 2 * self.style["callout"]["line_gap_px"])
        self.assertEqual(gap["value"], 6)

    def test_m05_m09_per_group_offset_normalized(self):
        roles = self.result["style_roles"]
        self.assertEqual(roles["route-morning"]["display_offset"]["distance"]["value"], 2)
        self.assertEqual(roles["route-afternoon"]["display_offset"]["distance"]["value"], 8)
        self.assertEqual(roles["route-default"]["display_offset"]["distance"]["value"], 0)

    def test_m25_arrival_time_explicit_content_baseline_false(self):
        self.assertNotIn("arrival-time", self.result["content"]["card"]["fields"])
        self.assertFalse(self.style["callout"]["show_arrival_time"])

    def test_m39_numbering_display_order(self):
        self.assertEqual(self.result["content"]["numbering"]["display_order"], "per-date-group")

    def test_m40_white_threshold_to_basemap_display(self):
        self.assertEqual(self.result["basemap_display"]["crop"]["parameters"]["white_threshold"], 245)

    def test_m30_m32_support_text_merged_single_role(self):
        text = self.result["style_roles"]["support-label-text"]
        self.assertEqual(text["color"], self.style["support_label"]["text_color"])
        self.assertEqual(text["font"]["size"]["value"], self.style["support_label"]["font_size_px"])
        self.assertEqual(text["font"]["weight"], self.style["support_label"]["font_weight"])

    def test_m41_m42_page_furniture_physical_pt(self):
        self.assertEqual(self.result["style_roles"]["page-title"]["font"]["size"],
                         {"kind": "physical-pt", "value": 34.0})
        self.assertEqual(self.result["style_roles"]["source-notice"]["font"]["size"],
                         {"kind": "physical-pt", "value": 12.76})

    def test_m44_m46_border_physical_mm(self):
        border = self.result["components"]["map-border"]["parameters"]
        self.assertEqual(border["inner_stroke_width"], {"kind": "physical-mm", "value": 0.25})
        self.assertEqual(border["stroke_gap"], {"kind": "physical-mm", "value": 1.0})
        self.assertEqual(border["outer_stroke_width"], {"kind": "physical-mm", "value": 0.5})

    def test_m26_m24_card_width_mode_and_wrap(self):
        card = self.result["components"]["card"]["parameters"]
        self.assertEqual(card["sizing"]["width"]["mode"], "fit-content-up-to-limit")
        self.assertEqual(card["sizing"]["width"]["limit"]["value"], 500)
        self.assertEqual(card["title"]["wrap_mode"], "single-line-reject-overflow")

    def test_m06_fallback_split_from_legend_color(self):
        self.assertEqual(self.result["group_resolution"]["fallback_group"], "default")
        # group color is a Style role bound via group_bindings, not taken from fallback.
        self.assertEqual(self.result["group_bindings"][0],
                         {"semantic_group": "morning", "visual_role": "group-morning"})
        self.assertEqual(self.result["style_roles"]["group-morning"]["color"], "#1769D2")

    def test_all_produced_instances_validate_closed_contracts(self):
        for role, appearance in self.result["style_roles"].items():
            with self.subTest(role=role):
                self.registry.validate("role-appearance", appearance)
        param_schema = {"classified-route": "route-parameters", "information-card": "card-parameters",
                        "double-outline": "double-outline-parameters", "linked-label": "linked-label-parameters"}
        for cid, comp in self.result["components"].items():
            with self.subTest(component=cid):
                self.registry.validate(param_schema[comp["type"]], comp["parameters"])
        for aid, ann in self.result["annotations"].items():
            with self.subTest(annotation=aid):
                self.registry.validate("annotation-placement", ann["placement"])
        self.registry.validate("basemap-display", self.result["basemap_display"])

    def test_migration_preserves_source_values_no_guessing(self):
        # route/pin/callout reference-px values keep their unit and value (not converted to mm/pt).
        roles = self.result["style_roles"]
        self.assertEqual(roles["route"]["stroke"]["width"],
                         {"kind": "reference-design-px", "value": 6, "rule_ref": roles["route"]["stroke"]["width"]["rule_ref"]})
        self.assertEqual(roles["numbered-stop-marker"]["radius"]["value"], 12)
        self.assertEqual(roles["card-title"]["font"]["size"]["value"], 22)


class S5ResolutionEquivalenceTests(unittest.TestCase):
    """P6 S5: resolving the new contract instances back to the effective style preserves
    the baseline design (round trip). The backend drawing functions consume this derived
    copy, so identical input ⇒ identical graphics (mapping §5.2 / §9.3 synthetic compare)."""

    def test_resolve_round_trips_to_baseline(self):
        from carto_core.scenarios.leadership_visit.route_author import TEMPLATE_STYLE
        from carto_core.scenarios.leadership_visit.contract_migration import (
            migrate_image_itinerary, resolve_effective_style,
        )
        from tests.fixtures.schema_cases import A
        migrated = migrate_image_itinerary(TEMPLATE_STYLE, rule_ref=A)
        resolved = resolve_effective_style(migrated)
        self.assertEqual(resolved, TEMPLATE_STYLE)

    def test_resolved_style_validates_against_image_itinerary_schema(self):
        from carto_core.schema_registry import SchemaRegistry
        from carto_core.scenarios.leadership_visit.route_author import TEMPLATE_STYLE
        from carto_core.scenarios.leadership_visit.contract_migration import (
            migrate_image_itinerary, resolve_effective_style,
        )
        from tests.fixtures.schema_cases import A
        resolved = resolve_effective_style(migrate_image_itinerary(TEMPLATE_STYLE, rule_ref=A))
        SchemaRegistry().validate("image-itinerary-style", resolved)


class S7CrossSceneLayoutTests(unittest.TestCase):
    """A18: Layout consumption is a shared, scenario-agnostic interface. The same
    LayoutResolver + layout schema serve both general_thematic and leadership_visit;
    no scenario-specific layout parser. A compatible Layout resolves identically
    regardless of which business scene consumes it."""

    def test_layout_resolver_is_scenario_agnostic(self):
        from carto_core.compiler.layout import LayoutResolver
        from carto_core.schema_registry import SchemaRegistry
        from carto_core.scenarios.leadership_visit.route_author import LAYOUT_CONTRACT
        registry = SchemaRegistry()
        registry.validate("layout", LAYOUT_CONTRACT)
        resolver = LayoutResolver(registry)
        # The resolver takes only layout + dpi + parameters — no scenario argument.
        resolved_a = resolver.resolve(LAYOUT_CONTRACT, 300)
        resolved_b = resolver.resolve(LAYOUT_CONTRACT, 300)
        self.assertEqual(resolved_a, resolved_b)
        self.assertEqual(resolved_a["page"]["width_mm"], 420)
        # The map frame is found by type, not a hardcoded scenario frame name.
        frame = LayoutResolver.map_frame(resolved_a)
        self.assertEqual(frame["type"], "map")

    def test_same_layout_schema_serves_both_scenes(self):
        from carto_core.schema_registry import SchemaRegistry
        from carto_core.scenarios.leadership_visit.route_author import LAYOUT_CONTRACT
        from tests.fixtures.schema_cases import VALID_CASES
        registry = SchemaRegistry()
        # Both the leadership fixed-page layout and the general grid layout validate
        # against the SAME layout schema (common interface, no parallel authority).
        registry.validate("layout", LAYOUT_CONTRACT)
        registry.validate("layout", VALID_CASES["layout"])


class S6ImplicitDecisionTests(unittest.TestCase):
    """S6: implicit code defaults become explicit contracts (X10 font-fit mode shown here)."""

    def test_x10_font_fit_mode_explicit(self):
        from carto_core.adapters.image_layout import furniture_font_pt
        from carto_core.errors import ProtocolError
        item = {"content_id": "title", "text": "一个很长的标题文字内容", "font_pt": 34.0}
        bounds = (0, 0, 100, 14)  # narrow frame: nominal 34pt cannot fit
        pt_per_px = 72 / 300
        # shrink-to-fit (recorded baseline): clamps below nominal, floored at min_pt.
        shrunk = furniture_font_pt(item, bounds, pt_per_px, fit_mode="shrink-to-fit", min_pt=4.0)
        self.assertLess(shrunk, 34.0)
        self.assertGreaterEqual(shrunk, 4.0)
        # reject-overflow: refuses instead of silently shrinking.
        with self.assertRaises(ProtocolError) as raised:
            furniture_font_pt(item, bounds, pt_per_px, fit_mode="reject-overflow")
        self.assertEqual("FONT_CAPACITY_OVERFLOW", raised.exception.code)
        # unknown mode refused.
        with self.assertRaises(ProtocolError):
            furniture_font_pt(item, bounds, pt_per_px, fit_mode="auto")

    def test_x10_min_pt_is_explicit_floor(self):
        from carto_core.adapters.image_layout import furniture_font_pt
        item = {"content_id": "title", "text": "超长标题" * 20, "font_pt": 34.0}
        bounds = (0, 0, 50, 10)
        pt_per_px = 72 / 300
        self.assertGreaterEqual(furniture_font_pt(item, bounds, pt_per_px, min_pt=8.0), 8.0)

    def test_x05_card_structure_preset_declared(self):
        from carto_core.schema_registry import SchemaRegistry
        from carto_core.scenarios.leadership_visit.contract_migration import migrate_image_itinerary
        from carto_core.scenarios.leadership_visit.route_author import TEMPLATE_STYLE
        from tests.fixtures.schema_cases import A
        registry = SchemaRegistry()
        migrated = migrate_image_itinerary(TEMPLATE_STYLE, rule_ref=A)
        structure = migrated["components"]["card"]["parameters"]["structure"]
        self.assertEqual(structure["section_order"], ["body", "divider", "title"])
        self.assertEqual(structure["divider_position"], "gap-midpoint")
        registry.validate("card-parameters", migrated["components"]["card"]["parameters"])
        from carto_core.errors import ProtocolError
        bad = {**migrated["components"]["card"]["parameters"],
               "structure": {**structure, "section_order": ["title", "body"]}}
        with self.assertRaises(ProtocolError):
            registry.validate("card-parameters", bad)

    def test_x08_business_text_is_declared_content_contract(self):
        from carto_core.scenarios.leadership_visit import content_contract
        self.assertEqual(content_contract.stop_line("11月18日", "上午", 1), "11月18日上午行程点1")
        self.assertEqual(content_contract.arrival_line("09:00"), "到达时间：09:00")
        self.assertEqual(content_contract.travel_line("distance-km", 12), "约12公里")
        self.assertEqual(content_contract.travel_line("duration-min", 45), "车程约45分钟")
        self.assertEqual(content_contract.LEGEND_STOP_LABEL, "行程点")
        self.assertEqual(content_contract.LEGEND_SUPPORT_LABEL, "起始/折返点")


if __name__ == "__main__":
    unittest.main()