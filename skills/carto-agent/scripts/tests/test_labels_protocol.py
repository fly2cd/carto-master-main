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
from tests.fixtures.schema_cases import VALID_CASES, VARIANT_CASES


class LabelDeclarationTests(unittest.TestCase):
    """generate-request: vector_panels[].labels is an optional, strictly typed declaration."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.registry = SchemaRegistry()

    def _vector_request(self):
        return deepcopy(VARIANT_CASES["general-generate-request.vector"])

    def test_request_without_labels_still_valid(self) -> None:
        self.registry.validate("general-generate-request", self._vector_request())

    def test_labels_with_field_accepted(self) -> None:
        request = self._vector_request()
        request["vector_panels"][0]["labels"] = {"field": "name"}
        self.registry.validate("general-generate-request", request)

    def test_labels_with_max_labels_accepted(self) -> None:
        request = self._vector_request()
        request["vector_panels"][0]["labels"] = {"field": "name", "max_labels": 50}
        self.registry.validate("general-generate-request", request)

    def test_labels_missing_field_rejected(self) -> None:
        request = self._vector_request()
        request["vector_panels"][0]["labels"] = {"max_labels": 5}
        with self.assertRaises(ProtocolError):
            self.registry.validate("general-generate-request", request)

    def test_labels_unknown_member_rejected(self) -> None:
        request = self._vector_request()
        request["vector_panels"][0]["labels"] = {"field": "name", "size_pt": 9}
        with self.assertRaises(ProtocolError):
            self.registry.validate("general-generate-request", request)


class ResolvedLabelsTests(unittest.TestCase):
    """resolved-portrayal: label_source (frozen declaration) + labels (feature_id/text/anchor)."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.registry = SchemaRegistry()

    def _portrayal(self):
        return deepcopy(VALID_CASES["resolved-portrayal"])

    def test_portrayal_without_labels_still_valid(self) -> None:
        self.registry.validate("resolved-portrayal", self._portrayal())

    def test_labels_with_anchor_accepted(self) -> None:
        value = self._portrayal()
        value["label_source"] = {"field": "name"}
        value["labels"] = [{"feature_id": "feature-0", "text": "Hangzhou", "anchor": [120.1, 30.2]}]
        self.registry.validate("resolved-portrayal", value)

    def test_labels_missing_anchor_rejected(self) -> None:
        value = self._portrayal()
        value["label_source"] = {"field": "name"}
        value["labels"] = [{"feature_id": "feature-0", "text": "Hangzhou"}]
        with self.assertRaises(ProtocolError):
            self.registry.validate("resolved-portrayal", value)

    def test_labels_bad_anchor_rejected(self) -> None:
        value = self._portrayal()
        value["labels"] = [{"feature_id": "feature-0", "text": "Hangzhou", "anchor": [120.1]}]
        with self.assertRaises(ProtocolError):
            self.registry.validate("resolved-portrayal", value)

    def test_label_source_missing_field_rejected(self) -> None:
        value = self._portrayal()
        value["label_source"] = {"max_labels": 5}
        with self.assertRaises(ProtocolError):
            self.registry.validate("resolved-portrayal", value)

    def test_labels_unknown_member_rejected(self) -> None:
        value = self._portrayal()
        value["labels"] = [{"feature_id": "feature-0", "text": "X", "anchor": [0, 0], "priority": 9}]
        with self.assertRaises(ProtocolError):
            self.registry.validate("resolved-portrayal", value)


class LabelHaloTests(unittest.TestCase):
    """cartography: labeling.halo is optional, color + width_mm only."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.registry = SchemaRegistry()

    def _cartography(self):
        return deepcopy(VALID_CASES["style"])

    def test_cartography_without_halo_still_valid(self) -> None:
        self.registry.validate("style", self._cartography())

    def test_halo_accepted(self) -> None:
        value = self._cartography()
        value["labeling"]["halo"] = {"color": "#FFFFFF", "width_mm": 0.5}
        self.registry.validate("style", value)

    def test_halo_bad_color_rejected(self) -> None:
        value = self._cartography()
        value["labeling"]["halo"] = {"color": "white", "width_mm": 0.5}
        with self.assertRaises(ProtocolError):
            self.registry.validate("style", value)

    def test_halo_missing_width_rejected(self) -> None:
        value = self._cartography()
        value["labeling"]["halo"] = {"color": "#FFFFFF"}
        with self.assertRaises(ProtocolError):
            self.registry.validate("style", value)

    def test_halo_out_of_range_width_rejected(self) -> None:
        value = self._cartography()
        value["labeling"]["halo"] = {"color": "#FFFFFF", "width_mm": 5}
        with self.assertRaises(ProtocolError):
            self.registry.validate("style", value)


if __name__ == "__main__":
    unittest.main()
