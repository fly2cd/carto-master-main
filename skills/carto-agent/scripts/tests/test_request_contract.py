"""request_contract component tests (I-3): scenario request-body understanding.

Covers geometry discrimination, required fields, the capability-derivation matrix,
source-reference cross-checks (error codes preserved), brief source-plan construction,
override keys and design-override application (deepcopy/no-op semantics).
"""
from __future__ import annotations

import sys
import tempfile
import unittest
from copy import deepcopy
from pathlib import Path

SCRIPTS_ROOT = Path(__file__).resolve().parents[1]
if str(SCRIPTS_ROOT) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_ROOT))

from carto_core.canonical import sha256_digest
from carto_core.errors import ProtocolError
from carto_core.scenarios.general_thematic.request_contract import REQUEST_CONTRACT
from carto_core.security.paths import PathGuard


class GeometryAndFieldsTests(unittest.TestCase):
    def test_geometry_explicit(self):
        self.assertEqual("raster", REQUEST_CONTRACT.geometry({"geometry": "raster"}))
        self.assertEqual("vector", REQUEST_CONTRACT.geometry({"geometry": "vector"}))

    def test_geometry_unknown_rejects(self):
        with self.assertRaisesRegex(ProtocolError, "SCENARIO_GEOMETRY_REQUIRED"):
            REQUEST_CONTRACT.geometry({"geometry": "line"})
        with self.assertRaisesRegex(ProtocolError, "SCENARIO_GEOMETRY_REQUIRED"):
            REQUEST_CONTRACT.geometry({})

    def test_required_fields(self):
        self.assertEqual(frozenset({"run_id", "audience", "scope", "environment", "requested_at",
                                    "template", "allowed_capabilities", "font", "intent"}),
                         REQUEST_CONTRACT.required_fields())

    def test_override_keys(self):
        self.assertEqual(("revised_cartography", "output_profile"), REQUEST_CONTRACT.override_keys())


class CapabilityMatrixTests(unittest.TestCase):
    def test_raster_requires_classify(self):
        self.assertEqual({"classify"}, REQUEST_CONTRACT.required_capabilities({"geometry": "raster"}))

    def test_choropleth_vector_requires_classify(self):
        req = {"geometry": "vector", "vector_panels": [{"design": {"kind": "choropleth"}}]}
        self.assertEqual({"classify"}, REQUEST_CONTRACT.required_capabilities(req))

    def test_attribute_join_requires_join(self):
        req = {"geometry": "vector", "vector_sources": [{"attribute_join": {"source_id": "t"}}]}
        self.assertEqual({"join"}, REQUEST_CONTRACT.required_capabilities(req))

    def test_binding_join_required_requires_join(self):
        req = {"geometry": "raster", "source_bindings": [{"join": {"required": True}}]}
        self.assertEqual({"classify", "join"}, REQUEST_CONTRACT.required_capabilities(req))

    def test_plain_vector_no_extra(self):
        self.assertEqual(set(), REQUEST_CONTRACT.required_capabilities(
            {"geometry": "vector", "vector_panels": [{"design": {"kind": "single"}}]}))


class ValidateBodyTests(unittest.TestCase):
    def _vector_request(self):
        source = {"source_id": "s1", "role": "thematic-features", "files": []}
        return {"request_id": "r1", "geometry": "vector", "vector_sources": [source],
                "sources": [{"id": "s1", "version": "1.0.0", "digest": sha256_digest(source)}]}

    def test_vector_source_refs_match_passes(self):
        REQUEST_CONTRACT.validate_body(self._vector_request())  # no raise

    def test_vector_source_digest_mismatch_rejects(self):
        req = self._vector_request()
        req["sources"][0]["digest"] = "sha256:" + "0" * 64
        with self.assertRaisesRegex(ProtocolError, "GENERATE_SOURCE_REF_MISMATCH"):
            REQUEST_CONTRACT.validate_body(req)

    def test_vector_with_source_bindings_rejects(self):
        req = self._vector_request()
        req["source_bindings"] = [{"role": "x"}]
        with self.assertRaisesRegex(ProtocolError, "GENERATE_SOURCE_REF_MISMATCH"):
            REQUEST_CONTRACT.validate_body(req)

    def test_raster_missing_source_bindings_rejects(self):
        with self.assertRaisesRegex(ProtocolError, "GENERATE_REQUEST_INCOMPLETE"):
            REQUEST_CONTRACT.validate_body({"request_id": "r1", "geometry": "raster", "sources": []})

    def test_raster_source_ref_set_mismatch_rejects(self):
        req = {"request_id": "r1", "geometry": "raster",
               "sources": [{"id": "a", "version": "1.0.0", "digest": "d"}],
               "source_bindings": [{"source_ref": {"id": "b", "version": "1.0.0", "digest": "d"}}]}
        with self.assertRaisesRegex(ProtocolError, "SOURCE_REFERENCE_SET_MISMATCH"):
            REQUEST_CONTRACT.validate_body(req)


class ApplyOverridesTests(unittest.TestCase):
    def test_no_overrides_is_identity(self):
        contracts = {"scenario": {"embedded": {"cartography": {"title_pt": 18}}}}
        before = deepcopy(contracts)
        result = REQUEST_CONTRACT.apply_overrides({}, contracts)
        self.assertIs(result, contracts)
        self.assertEqual(before, contracts)

    def test_revised_cartography_applied(self):
        contracts = {"scenario": {"embedded": {}}}
        cart = {"title_pt": 22}
        REQUEST_CONTRACT.apply_overrides({"revised_cartography": cart}, contracts)
        self.assertEqual(cart, contracts["scenario"]["embedded"]["cartography"])
        # deepcopy: mutating the source must not leak into contracts
        cart["title_pt"] = 99
        self.assertEqual(22, contracts["scenario"]["embedded"]["cartography"]["title_pt"])

    def test_output_profile_applied_to_canvas(self):
        contracts = {"scenario": {"embedded": {"layout": {"canvas": {"width": 297, "height": 210}}}}}
        REQUEST_CONTRACT.apply_overrides({"output_profile": {"width_mm": 420, "height_mm": 297}}, contracts)
        canvas = contracts["scenario"]["embedded"]["layout"]["canvas"]
        self.assertEqual(420, canvas["width"])
        self.assertEqual(297, canvas["height"])

    def test_output_profile_partial(self):
        contracts = {}
        REQUEST_CONTRACT.apply_overrides({"output_profile": {"width_mm": 300}}, contracts)
        canvas = contracts["scenario"]["embedded"]["layout"]["canvas"]
        self.assertEqual(300, canvas["width"])
        self.assertNotIn("height", canvas)


class SourcePlanTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.guard = PathGuard([str(self.root)])

    def test_raster_binding_source_plan(self):
        data = self.root / "data.geojson"
        data.write_text('{"type":"FeatureCollection","features":[]}', encoding="utf-8")
        from carto_core.artifacts import file_digest
        req = {"allowed_capabilities": ["read", "classify"],
               "source_bindings": [{"role": "classified-surface",
                                    "source_ref": {"id": "a", "version": "1.0.0", "digest": "d"},
                                    "path": "data.geojson",
                                    "field_bindings": [{"semantic_role": "thematic-value", "source_field": "value"}]}]}
        plan = REQUEST_CONTRACT.source_plan(req, self.guard, self.root)
        self.assertEqual(1, len(plan))
        self.assertEqual("classified-surface", plan[0]["role"])
        self.assertEqual(["read", "classify"], plan[0]["allowed_operations"])
        self.assertEqual(file_digest(data), plan[0]["path_digest"])
        self.assertEqual([{"semantic_role": "thematic-value", "source_field": "value"}], plan[0]["field_bindings"])

    def test_vector_sidecar_drift_rejects(self):
        sidecar = self.root / "s1.shp"
        sidecar.write_bytes(b"abc")
        req = {"allowed_capabilities": ["read"], "sources": [{"id": "s1"}],
               "vector_sources": [{"source_id": "s1", "role": "thematic-features",
                                   "files": [{"extension": "shp", "path": "s1.shp", "size_bytes": 999, "digest": "d"}]}],
               "vector_panels": []}
        with self.assertRaisesRegex(ProtocolError, "VECTOR_SOURCE_CHANGED"):
            REQUEST_CONTRACT.source_plan(req, self.guard, self.root)


if __name__ == "__main__":
    unittest.main()