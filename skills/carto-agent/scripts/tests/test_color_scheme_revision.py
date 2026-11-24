# -*- coding: utf-8 -*-
"""裁决4/6/7 color-scheme revision tests.

Covers the revision protocol (color_scheme is a compilation-only change that reuses the
prepared bundle), the pure compile-time effective-color mapping (value-keyed, fail-closed,
redlines, shared-legend overlay), and the G1 brief palette visibility (裁决7).
"""
from __future__ import annotations

from pathlib import Path
import sys
import unittest

SCRIPTS_ROOT = Path(__file__).resolve().parents[1]
if str(SCRIPTS_ROOT) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_ROOT))

from carto_core.compiler.style_colors import apply_color_scheme, overlay_legend_colors
from carto_core.errors import ProtocolError
from carto_core.schema_registry import SchemaRegistry
from carto_core.scenarios.general_thematic.revision import REVISION_CONTRACT
from carto_core.workflow.revision_graph import bundle_input_digest, compute_invalidation

SCHEME = {"scope": "cat-contract", "colors": [{"value": 1, "color": "#FF0000"}]}


def _rows():
    return [
        {"value": 1, "color": "#1F611F", "label": "Forest", "order": 0,
         "display": "color", "include_in_legend": True},
        {"value": 2, "color": "#3C2FD5", "label": "Water", "order": 1,
         "display": "color", "include_in_legend": True},
    ]


class ColorSchemeRevisionProtocolTests(unittest.TestCase):
    def test_color_scheme_invalidates_compilation_only(self):
        result = compute_invalidation({"color_scheme": {"new_value": SCHEME}},
                                      REVISION_CONTRACT.rules())
        self.assertEqual(["candidate", "preflight", "preview", "scene"],
                         result["invalidated_nodes"])
        self.assertTrue(result["data_evidence_reusable"])
        self.assertEqual("compile", result["earliest_step"])

    def test_apply_changes_stores_revised_color_scheme(self):
        revised = REVISION_CONTRACT.apply_changes(
            {"geometry": "raster"}, {"color_scheme": {"new_value": SCHEME}})
        self.assertEqual(SCHEME, revised["revised_color_scheme"])

    def test_color_scheme_does_not_alter_bundle_inputs(self):
        keys = REVISION_CONTRACT.bundle_input_keys()
        before = {"source_bindings": [{"role": "r"}]}
        after = {"source_bindings": [{"role": "r"}], "revised_color_scheme": SCHEME}
        self.assertEqual(bundle_input_digest(before, keys), bundle_input_digest(after, keys))

    def test_proposal_schema_accepts_color_scheme(self):
        registry = SchemaRegistry()
        registry.validate("design-revision-proposal", {
            "schema_version": 1, "proposal_id": "p-1", "run_id": "run-1",
            "parent_revision": 1, "changes": {"color_scheme": {"new_value": SCHEME}},
            "justification": "preview palette revision"})

    def test_proposal_schema_rejects_incomplete_color_scheme(self):
        registry = SchemaRegistry()
        with self.assertRaises(ProtocolError):
            registry.validate("design-revision-proposal", {
                "schema_version": 1, "proposal_id": "p-1", "run_id": "run-1",
                "parent_revision": 1,
                "changes": {"color_scheme": {"new_value": {"colors": [{"value": 1, "color": "#FF0000"}]}}},
                "justification": "missing scope"})


class ApplyColorSchemeTests(unittest.TestCase):
    def test_effective_colors_and_provenance(self):
        effective, mapping = apply_color_scheme(_rows(), SCHEME)
        self.assertEqual("#FF0000", effective[0]["color"])
        self.assertEqual("#3C2FD5", effective[1]["color"])
        self.assertEqual([{"value": 1, "baseline_color": "#1F611F",
                           "effective_color": "#FF0000", "source": "color_scheme"}], mapping)
        # baseline rows are not mutated
        self.assertEqual("#1F611F", _rows()[0]["color"])

    def test_unknown_category_is_rejected(self):
        with self.assertRaisesRegex(ProtocolError, "COLOR_SCHEME_UNKNOWN_CATEGORY"):
            apply_color_scheme(_rows(), {"scope": "c", "colors": [{"value": 99, "color": "#FF0000"}]})

    def test_duplicate_category_is_rejected(self):
        with self.assertRaisesRegex(ProtocolError, "COLOR_SCHEME_DUPLICATE"):
            apply_color_scheme(_rows(), {"scope": "c", "colors": [
                {"value": 1, "color": "#FF0000"}, {"value": 1, "color": "#00FF00"}]})

    def test_redline_blocker_on_effective_colors(self):
        with self.assertRaises(ProtocolError) as ctx:
            apply_color_scheme(_rows(), {"scope": "c", "colors": [
                {"value": 1, "color": "#FF0000"}, {"value": 2, "color": "#FE0000"}]})
        self.assertIn("COLOR_", ctx.exception.code)

    def test_shared_legend_overlay_matches_effective(self):
        items = [{"value": 1, "label": "Forest", "color": "#1F611F", "order": 0},
                 {"value": 2, "label": "Water", "color": "#3C2FD5", "order": 1}]
        overlaid = overlay_legend_colors(items, SCHEME)
        self.assertEqual("#FF0000", overlaid[0]["color"])
        self.assertEqual("#3C2FD5", overlaid[1]["color"])


class BriefPaletteVisibilityTests(unittest.TestCase):
    def test_refresh_brief_surfaces_color_scheme(self):
        brief = {"source_plan": []}
        revised = {"geometry": "raster", "revised_color_scheme": SCHEME}
        result = REVISION_CONTRACT.refresh_brief(brief, revised)
        self.assertEqual("cat-contract", result["design_changes"]["color_scheme"]["scope"])
        self.assertEqual([{"value": 1, "effective_color": "#FF0000"}],
                         result["design_changes"]["color_scheme"]["colors"])
        SchemaRegistry().validate("map-brief", {
            "schema_version": 1, "brief_id": "b-1", "revision": 2, "intent_ref": {
                "id": "map-intent", "version": "1.0.0", "digest": "sha256:" + "a" * 64, "uri": "i.yaml"},
            "purpose": "p", "audience": "a", "source_plan": [{"role": "r", "source_ref": {
                "id": "s", "version": "1.0.0", "digest": "sha256:" + "a" * 64, "uri": "s.yaml"},
                "allowed_operations": ["read"]}],
            "targets": ["png"], "template_candidates": [], "delegation": {
                "allow_data_agent": False, "max_tool_calls": 10},
            "approval_required": True, "business_scene": "general_thematic_mapping",
            "theme_tags": ["unit-theme"], "tasks": ["thematic-map"],
            "design_changes": result["design_changes"]})

    def test_refresh_brief_without_color_revision_has_no_design_changes(self):
        result = REVISION_CONTRACT.refresh_brief({"source_plan": []}, {"geometry": "raster"})
        self.assertNotIn("design_changes", result)


if __name__ == "__main__":
    unittest.main()