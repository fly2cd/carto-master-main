# -*- coding: utf-8 -*-
"""Phase 3 inset locator-map declaration validation tests (mechanical core)."""
from __future__ import annotations

from copy import deepcopy
from pathlib import Path
import sys
import unittest

SCRIPTS_ROOT = Path(__file__).resolve().parents[1]
if str(SCRIPTS_ROOT) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_ROOT))

from carto_core.compiler.inset import validate_inset_declaration
from carto_core.compiler.layout import LayoutResolver
from carto_core.errors import ProtocolError
from carto_core.schema_registry import SchemaRegistry
from tests.fixtures.schema_cases import VALID_CASES

CONTAINER = {"id": "main-map", "type": "map", "bounds": [20, 30, 380, 230]}
INSET = {
    "id": "locator", "type": "inset", "bounds": [30, 40, 80, 60],
    "inside_frame": "main-map", "view": {"extent": [33.0, -4.0, 42.0, 1.0]},
    "main_map_ref": "main-view", "highlight_id": "kenya",
}


class InsetValidationTests(unittest.TestCase):
    def test_valid_inset_resolves_metadata(self):
        result = validate_inset_declaration(deepcopy(INSET), CONTAINER)
        self.assertEqual("locator", result["id"])
        self.assertEqual("main-map", result["container_id"])
        self.assertEqual([33.0, -4.0, 42.0, 1.0], result["view_extent"])
        self.assertEqual("main-view", result["main_map_ref"])
        self.assertEqual("kenya", result["highlight_id"])

    def test_not_enclosed_rejected(self):
        inset = deepcopy(INSET)
        inset["bounds"] = [30, 40, 400, 60]  # exceeds container right edge
        with self.assertRaisesRegex(ProtocolError, "INSET_NOT_ENCLOSED"):
            validate_inset_declaration(inset, CONTAINER)

    def test_non_map_container_rejected(self):
        with self.assertRaisesRegex(ProtocolError, "INSET_CONTAINER_TYPE"):
            validate_inset_declaration(deepcopy(INSET), {"id": "main-map", "type": "legend",
                                                         "bounds": [20, 30, 380, 230]})

    def test_missing_containment_reference_rejected(self):
        inset = deepcopy(INSET)
        inset.pop("inside_frame")
        with self.assertRaisesRegex(ProtocolError, "INSET_CONTAINMENT_REFERENCE"):
            validate_inset_declaration(inset, CONTAINER)

    def test_image_only_inset_rejected(self):
        inset = deepcopy(INSET)
        inset.pop("view")  # a pasted picture, not a map view
        with self.assertRaisesRegex(ProtocolError, "INSET_VIEW_REQUIRED"):
            validate_inset_declaration(inset, CONTAINER)

    def test_invalid_extent_rejected(self):
        inset = deepcopy(INSET)
        inset["view"]["extent"] = [42.0, -4.0, 33.0, 1.0]  # minx >= maxx
        with self.assertRaisesRegex(ProtocolError, "INSET_EXTENT_INVALID"):
            validate_inset_declaration(inset, CONTAINER)

    def test_missing_main_map_association_rejected(self):
        inset = deepcopy(INSET)
        inset.pop("main_map_ref")
        with self.assertRaisesRegex(ProtocolError, "INSET_MAIN_MAP_REQUIRED"):
            validate_inset_declaration(inset, CONTAINER)

    def test_wrong_inset_type_rejected(self):
        inset = deepcopy(INSET)
        inset["type"] = "image"
        with self.assertRaisesRegex(ProtocolError, "INSET_TYPE_INVALID"):
            validate_inset_declaration(inset, CONTAINER)

    def test_optional_highlight_absent_is_none(self):
        inset = deepcopy(INSET)
        inset.pop("highlight_id")
        result = validate_inset_declaration(inset, CONTAINER)
        self.assertIsNone(result["highlight_id"])


class InsetLayoutAdmissionTests(unittest.TestCase):
    def setUp(self):
        self.registry = SchemaRegistry()
        self.contract = deepcopy(VALID_CASES["resolved-layout"]["contract"])
        self.contract.update(layout_id="synthetic-inset-layout")
        self.contract["canvas"].update(width=297, height=210, safe_margin=10, orientation="landscape")
        self.contract["frames"] = [
            {"id": "map", "content_id": "main-view", "type": "map", "bounds": [10, 25, 215, 175],
             "coordinate_space": "page", "overflow_policy": "clip"},
            {"id": "title", "content_id": "title", "type": "title", "bounds": [10, 10, 277, 15],
             "coordinate_space": "page", "overflow_policy": "reject"},
            {"id": "legend", "content_id": "legend", "type": "legend", "bounds": [230, 40, 57, 130],
             "coordinate_space": "page", "overflow_policy": "reject"},
            {"id": "locator", "content_id": "locator-view", "type": "inset", "bounds": [15, 30, 60, 50],
             "coordinate_space": "page", "overflow_policy": "clip", "inside_frame": "map",
             "view": {"extent": [33.0, -4.0, 42.0, 1.0]}, "main_map_ref": "main-view",
             "highlight_id": "kenya"},
        ]

    def _inset(self):
        return next(f for f in self.contract["frames"] if f["type"] == "inset")

    def test_resolve_admits_inset_with_metadata(self):
        resolved = LayoutResolver(self.registry).resolve(self.contract, 300)
        inset = next(f for f in resolved["frames"] if f["type"] == "inset")
        self.assertEqual([33.0, -4.0, 42.0, 1.0], inset["view_extent"])
        self.assertEqual("main-view", inset["main_map_ref"])
        self.assertEqual("kenya", inset["highlight_id"])
        self.assertEqual(["map"], resolved["map_frame_ids"])
        self.registry.validate("resolved-layout", resolved)

    def test_place_overlays_skips_inset(self):
        resolver = LayoutResolver(self.registry)
        resolved = resolver.resolve(self.contract, 300)
        overlays = [{"id": "title", "type": "text", "content": "T"},
                    {"id": "legend", "type": "legend", "legend_items": [{"label": "A"}]}]
        placed = resolver.place_overlays(resolved, overlays)
        self.assertEqual({"title", "legend"}, {p["id"] for p in placed})

    def test_inset_without_containment_rejected(self):
        self._inset().pop("inside_frame")
        with self.assertRaisesRegex(ProtocolError, "INSET_CONTAINMENT_REFERENCE"):
            LayoutResolver(self.registry).resolve(self.contract, 300)

    def test_image_only_inset_rejected(self):
        self._inset().pop("view")
        with self.assertRaisesRegex(ProtocolError, "INSET_VIEW_REQUIRED"):
            LayoutResolver(self.registry).resolve(self.contract, 300)

    def test_inset_not_enclosed_rejected(self):
        self._inset()["bounds"] = [15, 30, 300, 50]
        with self.assertRaises(ProtocolError):
            LayoutResolver(self.registry).resolve(self.contract, 300)


if __name__ == "__main__":
    unittest.main()