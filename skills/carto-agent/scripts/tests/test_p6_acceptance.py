"""P6 acceptance evidence — non-baseline cases, effectiveness, revision preservation,
and request/plan/execution/lock consistency (not only baseline round-trip equality).

Synthetic data + synthetic approvals; real graphics construction and rendering paths.
Each test names the acceptance claim it evidences.
"""
from __future__ import annotations

from copy import deepcopy
from pathlib import Path
import sys
import unittest

SCRIPTS_ROOT = Path(__file__).resolve().parents[1]
if str(SCRIPTS_ROOT) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_ROOT))

from carto_core.errors import ProtocolError
from carto_core.scenarios.leadership_visit.contract_migration import (
    migrate_image_itinerary, resolve_effective_style,
)
from carto_core.scenarios.leadership_visit.route_author import TEMPLATE_STYLE
from carto_core.scenarios.leadership_visit.style import apply_grouped_style
from carto_core.adapters.geo_to_image_pixels import project_features
from carto_core.adapters.image_display import display_bounds
from tests.fixtures.schema_cases import A
from tests.test_leadership_visit import LeadershipFixture, STYLE, _migrate_style


def _rule(ref_id="reference-design-a3-144dpi"):
    return {"id": ref_id, "version": "1.0.0", "digest": "sha256:" + "0" * 64}


class NonBaselineEffectivenessTests(LeadershipFixture, unittest.TestCase):
    """Non-baseline positive/negative cases: changing a selection actually changes the
    effective design, and invalid selections are refused (not baseline round-trip only)."""

    def _itinerary(self, stops=None):
        stops = stops if stops is not None else self.stops_fc
        projection = project_features(self.parameters, self.image_bytes, stops, self.route_fc)
        window = display_bounds(self.image_bytes)
        page = {"basemap": {"source_size": {"width_px": 400, "height_px": 300},
                            "display_window": window}}
        fields = {"route-stops": {i["semantic_role"]: i["source_field"]
                                  for i in self.request["source_bindings"][0]["field_bindings"]},
                  "route-line": {}}
        fields["route-stops"]["stop-type"] = "stop_type"
        return page, {"projection": projection, "sources": {"route-stops": stops,
                                                            "route-line": self.route_fc},
                      "fields": fields}

    def test_nonbaseline_group_color_role_changes_only_that_group(self):
        """Changing the morning visual-role color changes morning graphics only; afternoon
        and default keep their colors; geometry/labels unchanged (non-baseline positive)."""
        instances = _migrate_style(STYLE)
        page, itin = self._itinerary()
        base = apply_grouped_style(resolve_effective_style(instances), page, itin,
                                   frame_id="main-map", appearance_roles=instances["style_roles"])
        changed = deepcopy(instances)
        changed["style_roles"]["group-morning"]["color"] = "#228833"
        after = apply_grouped_style(resolve_effective_style(changed), page, itin,
                                    frame_id="main-map", appearance_roles=changed["style_roles"])
        morning_before = [g for g in base["graphics"] if g.get("group") == "morning"]
        morning_after = [g for g in after["graphics"] if g.get("group") == "morning"]
        self.assertTrue(morning_before)
        self.assertTrue(all(g["color"] == "#228833" for g in morning_after))
        self.assertTrue(all(g["color"] == "#1769D2" for g in morning_before))
        # default group graphics unchanged
        def_before = [g["color"] for g in base["graphics"] if g.get("group") == "default"]
        def_after = [g["color"] for g in after["graphics"] if g.get("group") == "default"]
        self.assertEqual(def_before, def_after)

    def test_nonbaseline_measurement_rule_changes_symbol_scale(self):
        """A different adopted measurement rule (U) changes the effective symbol scale —
        the rule reference is effective, not decorative (non-baseline positive)."""
        from carto_core.compiler.image_symbols import scale_for_rule
        window = {"width": 2381, "height": 1684}
        baseline = {"schema_version": 1, "rule_id": "b", "version": "1.0.0",
                    "reference_width_px": 2381, "reference_height_px": 1684,
                    "scale_floor": 1.0, "scale_function": "min-ratio-floor"}
        half = {**baseline, "rule_id": "half", "reference_width_px": 1190.5,
                "reference_height_px": 842.0}
        self.assertAlmostEqual(scale_for_rule(window, baseline), 1.0, delta=1e-9)
        self.assertAlmostEqual(scale_for_rule(window, half), 2.0, delta=1e-9)

    def test_unknown_group_refused_not_defaulted(self):
        """Data with an unknown non-empty group is refused, not silently defaulted (negative)."""
        bad_stops = deepcopy(self.stops_fc)
        bad_stops["features"][0]["properties"]["itinerary_group"] = "evening"
        page, itin = self._itinerary(bad_stops)
        with self.assertRaises(ProtocolError) as raised:
            apply_grouped_style(STYLE, page, itin, frame_id="main-map")
        self.assertEqual("ITINERARY_GROUP_UNKNOWN", raised.exception.code)

    def test_content_selection_arrival_time_effective(self):
        """show_arrival_time content selection actually controls the arrival line (positive
        both ways), independent of the renderer default."""
        page, itin = self._itinerary()
        with_arrival = deepcopy(STYLE)
        with_arrival["callout"]["show_arrival_time"] = True
        without = deepcopy(STYLE)
        without["callout"]["show_arrival_time"] = False
        g_with = apply_grouped_style(with_arrival, page, itin, frame_id="main-map")["graphics"]
        g_without = apply_grouped_style(without, page, itin, frame_id="main-map")["graphics"]
        callouts_with = [g for g in g_with if g["type"] == "callout"]
        callouts_without = [g for g in g_without if g["type"] == "callout"]
        self.assertTrue(any(any("到达时间" in ln for ln in g["lines"]) for g in callouts_with))
        self.assertFalse(any(any("到达时间" in ln for ln in g["lines"]) for g in callouts_without))

    def test_fixed_annotation_offset_honored(self):
        """A fixed (explicit) annotation offset is honored, not moved by the solver (X09)."""
        from carto_core.scenarios.leadership_visit.style import _place
        graphic = {"id": "c1", "position": {"x": 200, "y": 150}, "width_px": 50, "height_px": 30,
                   "padding_px": 4, "offset_x_px": 40, "offset_y_px": -50}
        window = {"x": 0, "y": 0, "width": 400, "height": 300}
        _place(graphic, window, [], explicit=True, anchors=[])
        self.assertEqual(graphic["offset_x_px"], 40)
        self.assertEqual(graphic["offset_y_px"], -50)

    def test_invalid_measurement_representation_refused(self):
        """A reference-design measurement without a rule_ref is refused (negative)."""
        from carto_core.schema_registry import SchemaRegistry
        registry = SchemaRegistry()
        with self.assertRaises(ProtocolError):
            registry.validate("symbol-measurement", {"kind": "reference-design-px", "value": 6})


class RevisionPreservationTests(LeadershipFixture, unittest.TestCase):
    """A revision/override of one selection must not lose unrelated selections."""

    def test_override_one_group_preserves_other_selections(self):
        from carto_core.scenarios.leadership_visit.request_contract import REQUEST_CONTRACT
        contracts = deepcopy(self.contracts)
        before = contracts["portrayal"]["design_instances"]
        request = {"style_overrides": {"groups": [{"id": "morning", "color": "#228833"}]}}
        REQUEST_CONTRACT.apply_overrides(request, contracts)
        after = contracts["portrayal"]["design_instances"]
        # morning color changed
        self.assertEqual(after["style_roles"]["group-morning"]["color"], "#228833")
        # unrelated selections preserved: default group color, callout params, content, basemap
        self.assertEqual(after["style_roles"]["group-default"]["color"],
                         before["style_roles"]["group-default"]["color"])
        self.assertEqual(after["components"]["card"]["parameters"],
                         before["components"]["card"]["parameters"])
        self.assertEqual(after["content"], before["content"])
        self.assertEqual(after["basemap_display"], before["basemap_display"])
        self.assertEqual(after["annotations"], before["annotations"])

    def test_override_callout_width_preserves_groups_and_content(self):
        from carto_core.scenarios.leadership_visit.request_contract import REQUEST_CONTRACT
        contracts = deepcopy(self.contracts)
        before = contracts["portrayal"]["design_instances"]
        request = {"style_overrides": {"callout": {"width_px": 300}}}
        REQUEST_CONTRACT.apply_overrides(request, contracts)
        after = contracts["portrayal"]["design_instances"]
        self.assertEqual(after["components"]["card"]["parameters"]["sizing"]["width"]["limit"]["value"], 300)
        self.assertEqual(after["style_roles"], before["style_roles"])
        self.assertEqual(after["content"], before["content"])
        self.assertEqual(after["group_bindings"], before["group_bindings"])


class InstanceConsistencyTests(LeadershipFixture, unittest.TestCase):
    """Request / plan / execution instance / lock consistency for the leadership chain."""

    def test_compile_execution_binds_design_instances_consistently(self):
        """The compiled candidate's execution and frozen scene derive from the same adopted
        design instances; the resolved style is consistent across graphics and page."""
        from carto_core.scenarios.leadership_visit.candidate_compiler import RouteCandidateCompiler
        from carto_core.scenarios.leadership_visit.planner import RoutePlanner
        from carto_core.contracts.execution import ExecutionContext
        contracts = deepcopy(self.contracts)
        plan = RoutePlanner().build(self.request, self.intent, self.brief, self.bundle,
                                    self.installation, contracts)
        compiler = RouteCandidateCompiler(self.guard, self.registry, project_root=self.root,
                                          context=ExecutionContext.from_generate_request(self.request))
        compiled = compiler.compile(self.request, self.intent, plan, self.bundle,
                                    self.installation, contracts, self.font_path)
        # execution digest binds the execution; scene graphics digest binds the graphics.
        from carto_core.canonical import sha256_digest
        self.assertEqual(compiled["candidate"]["execution_digest"],
                         sha256_digest(compiled["candidate"]["execution"]))
        self.assertTrue(compiled["scene"]["image_graphics"])
        # The frozen scene's graphics carry the adopted role colors (consistent with instances).
        roles = contracts["portrayal"]["design_instances"]["style_roles"]
        morning = [g for g in compiled["scene"]["image_graphics"] if g.get("group") == "morning"]
        self.assertTrue(morning)
        self.assertTrue(all(g["color"] == roles["group-morning"]["color"] for g in morning))
        # execution template_refs bind the scenario; ownership records the scenario authority.
        self.assertEqual(compiled["candidate"]["execution"]["ownership"]["scenario"], "map-scenario")

    def test_missing_design_instances_refused_at_compile(self):
        """A portrayal without design_instances is refused (no silent image_itinerary fallback)."""
        from carto_core.scenarios.leadership_visit.candidate_compiler import RouteCandidateCompiler
        from carto_core.scenarios.leadership_visit.planner import RoutePlanner
        from carto_core.contracts.execution import ExecutionContext
        contracts = deepcopy(self.contracts)
        contracts["portrayal"].pop("design_instances")
        plan = RoutePlanner().build(self.request, self.intent, self.brief, self.bundle,
                                    self.installation, contracts)
        compiler = RouteCandidateCompiler(self.guard, self.registry, project_root=self.root,
                                          context=ExecutionContext.from_generate_request(self.request))
        with self.assertRaises(ProtocolError) as raised:
            compiler.compile(self.request, self.intent, plan, self.bundle,
                             self.installation, contracts, self.font_path)
        self.assertEqual("LEADERSHIP_STYLE_CONTRACT_MISSING", raised.exception.code)


class ContractConsumptionTests(LeadershipFixture, unittest.TestCase):
    """事项1: a legal new-contract selection actually drives output/refusal by its semantics;
    no 'field accepted but runs by fixed name/default'."""

    def test_physical_unit_in_symbol_field_refused(self):
        """事项1.1: a physical-mm value where reference-px is expected is refused, not used as px."""
        instances = _migrate_style(STYLE)
        instances["components"]["card"]["parameters"]["sizing"]["width"]["limit"] = {
            "kind": "physical-mm", "value": 500}
        with self.assertRaises(ProtocolError) as raised:
            resolve_effective_style(instances)
        self.assertEqual("MEASUREMENT_UNIT_MISMATCH", raised.exception.code)

    def test_reference_px_missing_rule_ref_refused(self):
        instances = _migrate_style(STYLE)
        instances["components"]["card"]["parameters"]["inset"] = {"kind": "reference-design-px", "value": 4}
        with self.assertRaises(ProtocolError) as raised:
            resolve_effective_style(instances)
        self.assertEqual("MEASUREMENT_RULE_REF_INVALID", raised.exception.code)

    def test_binding_drives_color_not_name_concatenation(self):
        """事项1.2: rebinding semantic_group to a different visual_role changes the color,
        proving the consumer reads the binding, not a name-concatenated role."""
        instances = _migrate_style(STYLE)
        # add an alternate role and rebind morning to it
        instances["style_roles"]["alternate-green"] = {"color": "#228833"}
        for b in instances["group_bindings"]:
            if b["semantic_group"] == "morning":
                b["visual_role"] = "alternate-green"
        resolved = resolve_effective_style(instances)
        morning = next(g for g in resolved["groups"] if g["id"] == "morning")
        self.assertEqual(morning["color"], "#228833")

    def test_duplicate_missing_dangling_binding_refused(self):
        instances = _migrate_style(STYLE)
        dup = deepcopy(instances)
        dup["group_bindings"].append(deepcopy(dup["group_bindings"][0]))
        with self.assertRaises(ProtocolError) as r:
            resolve_effective_style(dup)
        self.assertEqual("GROUP_BINDING_DUPLICATE", r.exception.code)
        missing = deepcopy(instances)
        missing["group_bindings"] = [b for b in missing["group_bindings"] if b["semantic_group"] != "morning"]
        with self.assertRaises(ProtocolError) as r:
            resolve_effective_style(missing)
        self.assertEqual("GROUP_BINDING_MISSING", r.exception.code)
        dangling = deepcopy(instances)
        dangling["group_bindings"][0]["visual_role"] = "no-such-role"
        with self.assertRaises(ProtocolError) as r:
            resolve_effective_style(dangling)
        self.assertEqual("GROUP_BINDING_DANGLING", r.exception.code)

    def test_unknown_component_parameter_refused_not_dropped(self):
        """事项1.3: an unknown component parameter is refused by the closed definition schema."""
        from carto_core.compiler.component_registry import validate_component_instance
        from carto_core.schema_registry import SchemaRegistry
        registry = SchemaRegistry()
        instances = _migrate_style(STYLE)
        bad = deepcopy(instances["components"]["card"])
        bad["parameters"]["secret_knob"] = 1
        with self.assertRaises(ProtocolError):
            validate_component_instance(bad, registry)
        # unknown component type refused
        with self.assertRaises(ProtocolError) as r:
            validate_component_instance({"type": "map-card", "parameters": {}}, registry)
        self.assertEqual("COMPONENT_DEFINITION_UNKNOWN", r.exception.code)

    def test_fixed_annotation_mode_enters_layout_constraint(self):
        """事项1.4: a fixed card placement is binding; the solver does not move it."""
        projection = project_features(self.parameters, self.image_bytes, self.stops_fc, self.route_fc)
        window = display_bounds(self.image_bytes)
        page = {"basemap": {"source_size": {"width_px": 400, "height_px": 300}, "display_window": window}}
        fields = {"route-stops": {i["semantic_role"]: i["source_field"]
                                  for i in self.request["source_bindings"][0]["field_bindings"]}, "route-line": {}}
        itin = {"projection": projection, "sources": {"route-stops": self.stops_fc,
                                                      "route-line": self.route_fc}, "fields": fields}
        instances = _migrate_style(STYLE)
        fixed_ann = {"card": {"placement": {"mode": "fixed",
                                            "offset": {"x": {"kind": "reference-design-px", "value": 16, "rule_ref": _rule()},
                                                       "y": {"kind": "reference-design-px", "value": -16, "rule_ref": _rule()}}}}}
        g = apply_grouped_style(STYLE, page, itin, frame_id="main-map", annotations=fixed_ann)["graphics"]
        callouts = [x for x in g if x["type"] == "callout"]
        # fixed mode keeps the declared offsets (solver did not relocate)
        self.assertTrue(all(c["offset_x_px"] == 16 and c["offset_y_px"] == -16 for c in callouts))

    def test_leadership_single_candidate_boundary(self):
        """领导调研单候选边界：design_variants 被显式拒绝；多候选保留给通用专题。
        直接风格版式覆盖走 style_overrides（单候选）。"""
        from carto_core.scenarios.leadership_visit.request_contract import REQUEST_CONTRACT
        req = deepcopy(self.request)
        req["design_variants"] = [{"variant_id": "a"}, {"variant_id": "b"}]
        with self.assertRaises(ProtocolError) as raised:
            REQUEST_CONTRACT.validate_body(req)
        self.assertEqual("LEADERSHIP_VARIANTS_UNSUPPORTED", raised.exception.code)
        # single-candidate request (no variants) passes the boundary
        REQUEST_CONTRACT.validate_body(deepcopy(self.request))

    def test_p6_layout_segment_admitted_style_refused(self):
        """P6: leadership admits layout segment replacement (cross-scene reuse) but refuses
        style segment replacement (design_instances owns style)."""
        from carto_core.scenarios.leadership_visit.request_contract import REQUEST_CONTRACT
        layout_ref = {"kind": "map-layout", "id": "general-single-map-a3-landscape",
                      "version": "1.0.0", "digest": "sha256:" + "0" * 64}
        req = deepcopy(self.request)
        req["segment_refs"] = {"layout": layout_ref}
        REQUEST_CONTRACT.validate_body(req)  # layout admitted
        req_style = deepcopy(self.request)
        req_style["segment_refs"] = {"style": {"kind": "map-style", "id": "s", "version": "1.0.0",
                                               "digest": "sha256:" + "0" * 64}}
        with self.assertRaises(ProtocolError) as raised:
            REQUEST_CONTRACT.validate_body(req_style)
        self.assertEqual("SEGMENT_SELECTION_UNSUPPORTED", raised.exception.code)


if __name__ == "__main__":
    unittest.main()