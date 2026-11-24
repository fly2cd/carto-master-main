from __future__ import annotations

import unittest
from pathlib import Path
import sys

SCRIPTS_ROOT = Path(__file__).resolve().parents[1]
if str(SCRIPTS_ROOT) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_ROOT))

from carto_core.errors import ProtocolError
from carto_core.workflow.revision_graph import bundle_input_digest, compute_invalidation
from carto_core.scenarios.general_thematic.revision import REVISION_CONTRACT

# I-5: the kernel revision_graph is parameterized; the scenario revision_contract supplies
# the change rules and bundle-input keys exercised here.
RULES = REVISION_CONTRACT.rules()
BUNDLE_INPUT_KEYS = REVISION_CONTRACT.bundle_input_keys()


class ComputeInvalidationTests(unittest.TestCase):
    """Layer-1 rules mirror the revision-impact table (Standard Thematic doc §7)."""

    def test_appearance_changes_invalidate_compilation_only(self) -> None:
        for key in ("cartography", "layout_parameters", "map_title"):
            with self.subTest(key=key):
                result = compute_invalidation({key: {"new_value": {}}}, RULES)
                self.assertEqual(result["invalidated_nodes"],
                                 ["candidate", "preflight", "preview", "scene"])
                self.assertTrue(result["data_evidence_reusable"])
                self.assertEqual("compile", result["earliest_step"])

    def test_panel_designs_invalidate_plan_too(self) -> None:
        result = compute_invalidation({"panel_designs": {"new_value": {}}}, RULES)
        self.assertIn("plan", result["invalidated_nodes"])
        self.assertEqual(5, len(result["invalidated_nodes"]))

    def test_combined_changes_union(self) -> None:
        result = compute_invalidation({"cartography": {"new_value": {}},
                                       "panel_designs": {"new_value": {}}}, RULES)
        self.assertEqual(sorted(result["invalidated_nodes"]),
                         ["candidate", "plan", "preflight", "preview", "scene"])

    def test_unknown_change_key_rejected(self) -> None:
        with self.assertRaisesRegex(ProtocolError, "REVISION_CHANGES_UNKNOWN"):
            compute_invalidation({"data_sources": {"new_value": {}}}, RULES)

    def test_empty_changes_rejected(self) -> None:
        with self.assertRaisesRegex(ProtocolError, "REVISION_CHANGES_REQUIRED"):
            compute_invalidation({}, RULES)


class LeadershipInvalidationTests(unittest.TestCase):
    """Phase 2: the leadership contract's style_overrides vocabulary invalidates
    the compilation nodes only — the frozen data evidence stays reusable and the
    bundle-input digest is untouched by a style patch."""

    def test_style_overrides_invalidate_compilation_only(self) -> None:
        from carto_core.scenarios.leadership_visit.revision import REVISION_CONTRACT as ROUTE
        result = compute_invalidation({"style_overrides": {"new_value": {}}}, ROUTE.rules())
        self.assertEqual(result["invalidated_nodes"],
                         ["candidate", "preflight", "preview", "scene"])
        self.assertTrue(result["data_evidence_reusable"])
        self.assertEqual("compile", result["earliest_step"])

    def test_style_patch_never_alters_bundle_inputs(self) -> None:
        from carto_core.scenarios.leadership_visit.revision import REVISION_CONTRACT as ROUTE
        keys = ROUTE.bundle_input_keys()
        before = {"source_bindings": [{"role": "r"}],
                  "style_overrides": {"pin": {"radius_px": 9}}}
        after = {"source_bindings": [{"role": "r"}],
                 "style_overrides": {"pin": {"radius_px": 20}}}
        self.assertEqual(bundle_input_digest(before, keys),
                         bundle_input_digest(after, keys))

    def test_page_layout_still_invalidates_plan(self) -> None:
        from carto_core.scenarios.leadership_visit.revision import REVISION_CONTRACT as ROUTE
        result = compute_invalidation({"page_layout": {"new_value": {}}}, ROUTE.rules())
        self.assertIn("plan", result["invalidated_nodes"])


class BundleInputDigestTests(unittest.TestCase):
    """The digest gate separates data inputs from design-layer inputs."""

    def test_design_changes_do_not_alter_bundle_inputs(self) -> None:
        before = {"source_bindings": [{"role": "r"}], "map_title": "A",
                  "revised_cartography": {"typography": {}}}
        after = {"source_bindings": [{"role": "r"}], "map_title": "B",
                 "revised_cartography": {"typography": {"title_pt": 18}}}
        self.assertEqual(bundle_input_digest(before, BUNDLE_INPUT_KEYS),
                         bundle_input_digest(after, BUNDLE_INPUT_KEYS))

    def test_data_changes_alter_bundle_inputs(self) -> None:
        before = {"source_bindings": [{"role": "r", "path": "a.tif"}]}
        after = {"source_bindings": [{"role": "r", "path": "b.tif"}]}
        self.assertNotEqual(bundle_input_digest(before, BUNDLE_INPUT_KEYS),
                            bundle_input_digest(after, BUNDLE_INPUT_KEYS))

    def test_digest_covers_only_bundle_keys(self) -> None:
        request = {key: None for key in BUNDLE_INPUT_KEYS}
        request["unrelated"] = "anything"
        self.assertEqual(bundle_input_digest(request, BUNDLE_INPUT_KEYS),
                         bundle_input_digest({key: None for key in BUNDLE_INPUT_KEYS}, BUNDLE_INPUT_KEYS))


class DataRevisionInvalidationTests(unittest.TestCase):
    """Design B: change keys mapped onto the data-evidence node mark the prepared
    bundle non-reusable, so compile re-prepares; design-layer rules are unaffected
    (regression lock — their analysis stays byte-identical)."""

    def setUp(self) -> None:
        from carto_core.scenarios.leadership_visit.data_revision import DATA_REVISION_CONTRACT
        self.rules = DATA_REVISION_CONTRACT.rules()

    def test_route_legs_invalidate_data_evidence(self) -> None:
        result = compute_invalidation(
            {"route_legs": [{"leg_id": "leg-1", "via_points": [{"lon": 1.0, "lat": 2.0}]}]},
            self.rules)
        self.assertIn("data-evidence", result["invalidated_nodes"])
        self.assertFalse(result["data_evidence_reusable"])
        self.assertEqual("compile", result["earliest_step"])

    def test_data_rules_leave_compilation_nodes_intact(self) -> None:
        result = compute_invalidation(
            {"route_legs": [{"leg_id": "leg-1", "via_points": [{"lon": 0.0, "lat": 0.0}]}]},
            self.rules)
        for node in ("candidate", "preview", "preflight", "scene"):
            self.assertIn(node, result["invalidated_nodes"])

    def test_unknown_data_key_rejected(self) -> None:
        with self.assertRaises(ProtocolError):
            compute_invalidation({"stops": []}, self.rules)

    def test_design_rules_stay_reusable_regression(self) -> None:
        # The general scenario's design rules never mention the data node, so
        # their reusability verdict must remain True after the generalization.
        result = compute_invalidation({"cartography": {"new_value": {}}}, RULES)
        self.assertTrue(result["data_evidence_reusable"])
        self.assertNotIn("data-evidence", result["invalidated_nodes"])


if __name__ == "__main__":
    unittest.main()