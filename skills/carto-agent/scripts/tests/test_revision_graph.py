from __future__ import annotations

import unittest
from pathlib import Path
import sys

SCRIPTS_ROOT = Path(__file__).resolve().parents[1]
if str(SCRIPTS_ROOT) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_ROOT))

from carto_core.errors import ProtocolError
from carto_core.workflow.revision_graph import (
    BUNDLE_INPUT_KEYS, bundle_input_digest, compute_invalidation,
)


class ComputeInvalidationTests(unittest.TestCase):
    """Layer-1 rules mirror the revision-impact table (Standard Thematic doc §7)."""

    def test_appearance_changes_invalidate_compilation_only(self) -> None:
        for key in ("cartography", "layout_parameters", "map_title"):
            with self.subTest(key=key):
                result = compute_invalidation({key: {"new_value": {}}})
                self.assertEqual(result["invalidated_nodes"],
                                 ["candidate", "preflight", "preview", "scene"])
                self.assertTrue(result["data_evidence_reusable"])
                self.assertEqual("compile", result["earliest_step"])

    def test_panel_designs_invalidate_plan_too(self) -> None:
        result = compute_invalidation({"panel_designs": {"new_value": {}}})
        self.assertIn("plan", result["invalidated_nodes"])
        self.assertEqual(5, len(result["invalidated_nodes"]))

    def test_combined_changes_union(self) -> None:
        result = compute_invalidation({"cartography": {"new_value": {}},
                                       "panel_designs": {"new_value": {}}})
        self.assertEqual(sorted(result["invalidated_nodes"]),
                         ["candidate", "plan", "preflight", "preview", "scene"])

    def test_unknown_change_key_rejected(self) -> None:
        with self.assertRaisesRegex(ProtocolError, "REVISION_CHANGES_UNKNOWN"):
            compute_invalidation({"data_sources": {"new_value": {}}})

    def test_empty_changes_rejected(self) -> None:
        with self.assertRaisesRegex(ProtocolError, "REVISION_CHANGES_REQUIRED"):
            compute_invalidation({})


class BundleInputDigestTests(unittest.TestCase):
    """The digest gate separates data inputs from design-layer inputs."""

    def test_design_changes_do_not_alter_bundle_inputs(self) -> None:
        before = {"source_bindings": [{"role": "r"}], "map_title": "A",
                  "revised_cartography": {"typography": {}}}
        after = {"source_bindings": [{"role": "r"}], "map_title": "B",
                 "revised_cartography": {"typography": {"title_pt": 18}}}
        self.assertEqual(bundle_input_digest(before), bundle_input_digest(after))

    def test_data_changes_alter_bundle_inputs(self) -> None:
        before = {"source_bindings": [{"role": "r", "path": "a.tif"}]}
        after = {"source_bindings": [{"role": "r", "path": "b.tif"}]}
        self.assertNotEqual(bundle_input_digest(before), bundle_input_digest(after))

    def test_digest_covers_only_bundle_keys(self) -> None:
        request = {key: None for key in BUNDLE_INPUT_KEYS}
        request["unrelated"] = "anything"
        self.assertEqual(bundle_input_digest(request),
                         bundle_input_digest({key: None for key in BUNDLE_INPUT_KEYS}))


if __name__ == "__main__":
    unittest.main()
