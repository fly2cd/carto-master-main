"""R2/R5/R6: admission_class taxonomy, semantic digest, shared component defaults."""
import unittest
from copy import deepcopy
from pathlib import Path

import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from carto_core import roadmap, scenario_registry
from carto_core.canonical import sha256_digest
from carto_core.compiler.layout import LayoutResolver
from carto_core.errors import ConfigurationError, ProtocolError
from carto_core.schema_registry import SchemaRegistry, load_document
from carto_core.scenario_registry import ScenarioRegistry
from tests.fixtures.schema_cases import INVALID_CASES, VALID_CASES

POLICY = Path(scenario_registry.__file__).resolve().parents[2] / "policies" / "scenario-capabilities.yaml"


def _three_map_contract():
    base = deepcopy(VALID_CASES["layout"])
    template = next(f for f in base["frames"] if f["type"] == "map")
    maps = []
    for i in range(3):
        frame = deepcopy(template)
        frame.update(id=f"m{i}", content_id=f"v{i}", bounds=[15 + i * 130, 28, 120, 250])
        maps.append(frame)
    contract = deepcopy(base)
    contract["frames"] = maps
    return contract


class RoadmapTaxonomyTest(unittest.TestCase):
    def setUp(self):
        self.registry = SchemaRegistry()

    def test_schema_cases_registered(self):
        self.registry.validate("capability-roadmap", VALID_CASES["capability-roadmap"])
        with self.assertRaises(ProtocolError):
            self.registry.validate("capability-roadmap", INVALID_CASES["capability-roadmap"])

    def test_undeclared_feature_is_configuration_error(self):
        with self.assertRaisesRegex(ConfigurationError, "ROADMAP_FEATURE_UNDECLARED"):
            roadmap.not_implemented("no-such-feature", "X_UNSUPPORTED", "msg", registry=self.registry)

    def test_delivered_feature_cannot_stay_guarded(self):
        with self.assertRaisesRegex(ConfigurationError, "ROADMAP_FEATURE_DELIVERED"):
            roadmap.not_implemented("comparison-grid-shared-legend", "X_UNSUPPORTED", "msg",
                                    registry=self.registry)

    def test_variant_unification_declared_queueable_not_delivered(self):
        policy = roadmap.CapabilityRoadmap(registry=self.registry)
        item = policy.item("variant-geometry-adapter-unification")
        self.assertEqual("planned", item["status"])
        self.assertEqual("U-P4", item["target"])
        with self.assertRaises(ProtocolError) as ctx:
            roadmap.not_implemented("variant-geometry-adapter-unification",
                                    "VARIANT_MERGE_NOT_STARTED", "msg", registry=self.registry)
        self.assertEqual("not_implemented", roadmap.admission_class(ctx.exception))
        self.assertEqual("variant-geometry-adapter-unification", ctx.exception.details["feature"])
        self.assertEqual(policy.version, ctx.exception.details["roadmap_version"])

    def test_scope_reject_is_queueable_not_forbidden(self):
        with self.assertRaises(ProtocolError) as ctx:
            LayoutResolver(self.registry).resolve(_three_map_contract(), 300, 1)
        self.assertEqual("LAYOUT_MAP_COUNT_UNSUPPORTED", ctx.exception.code)
        self.assertEqual("not_implemented", roadmap.admission_class(ctx.exception))
        self.assertEqual("composition-map-counts", ctx.exception.details["feature"])
        self.assertIn(ctx.exception.details["status"], ("planned", "backlog"))

    def test_safety_reject_stays_forbidden(self):
        # Undeclared capability boundaries stay forbidden: unit and DPR rejects are
        # permanent page-backend limits, never queueable roadmap items.
        contract = deepcopy(VALID_CASES["layout"])
        contract["canvas"]["unit"] = "px"
        with self.assertRaises(ProtocolError) as ctx:
            LayoutResolver(self.registry).resolve(contract, 300, 1)
        self.assertEqual("LAYOUT_COORDINATE_UNSUPPORTED", ctx.exception.code)
        self.assertEqual("forbidden", roadmap.admission_class(ctx.exception))
        with self.assertRaises(ProtocolError) as ctx:
            LayoutResolver(self.registry).resolve(deepcopy(VALID_CASES["layout"]), 300, 2)
        self.assertEqual("LAYOUT_DPR_UNSUPPORTED", ctx.exception.code)
        self.assertEqual("forbidden", roadmap.admission_class(ctx.exception))


class SemanticDigestTest(unittest.TestCase):
    def test_disclosure_edits_do_not_change_ref(self):
        base = deepcopy(load_document(POLICY))["profiles"][0]
        cap = scenario_registry.ScenarioCapability(deepcopy(base))
        edited = deepcopy(base)
        edited["notice"] = "仅改披露措辞"
        edited["licenses"] = ["other-license"]
        self.assertEqual(cap.ref, scenario_registry.ScenarioCapability(edited).ref)
        semantic = deepcopy(base)
        semantic["allowed_geometries"] = ["raster", "vector"]
        self.assertNotEqual(cap.ref, scenario_registry.ScenarioCapability(semantic).ref)
        self.assertEqual(cap.ref["digest"],
                         sha256_digest(scenario_registry.semantic_definition(base)))


class SingleBundleGeometryDispatchTest(unittest.TestCase):
    def test_one_bundle_provides_every_route_component(self):
        from carto_core.scenarios import general_dispatch, general_thematic
        cap = scenario_registry.ScenarioCapability({"implementation": "general-thematic"})
        for name in ("data_preparer", "planner", "candidate_compiler", "legend_checker",
                     "source_contract", "author", "validation_data_checker", "validation_scene"):
            self.assertIsNotNone(cap.component(name))
        self.assertIs(cap.component("validation_data_checker"), general_thematic.validation_data_checker)
        self.assertIs(cap.component("source_contract"), general_dispatch.SOURCE_CONTRACT)
        with self.assertRaisesRegex(ProtocolError, "CAPABILITY_NOT_AVAILABLE"):
            cap.component("no-such-component")

    def test_geometry_dispatch_is_explicit_not_guessed(self):
        from carto_core.scenarios import general_dispatch
        # Explicit geometry field (primary path)
        self.assertEqual("raster", general_dispatch.geometry_of_request({"geometry": "raster", "panels": [1]}))
        self.assertEqual("vector", general_dispatch.geometry_of_request({"geometry": "vector", "vector_panels": [1]}))
        # Unknown explicit geometry rejects
        with self.assertRaisesRegex(ProtocolError, "SCENARIO_GEOMETRY_UNKNOWN"):
            general_dispatch.geometry_of_request({"geometry": "unknown"})
        # Backward-compatible heuristic fallback (no explicit geometry field)
        self.assertEqual("raster", general_dispatch.geometry_of_request({"panels": [1]}))
        self.assertEqual("vector", general_dispatch.geometry_of_request({"vector_panels": [1]}))
        for request in ({}, {"panels": [1], "vector_panels": [1]}):
            with self.assertRaisesRegex(ProtocolError, "SCENARIO_GEOMETRY_AMBIGUOUS"):
                general_dispatch.geometry_of_request(request)

    def test_vector_geometry_withheld_by_policy(self):
        registry = ScenarioRegistry()
        profile = registry.for_template({"kind": "map-scenario", "id": "general-thematic-map",
                                         "version": "3.0.0"})
        self.assertEqual(["raster"], profile.definition["allowed_geometries"])
        with self.assertRaisesRegex(ProtocolError, "CAPABILITY_NOT_AVAILABLE"):
            registry.require_geometry(profile, "vector")

    def test_registry_still_admits_packaged_profile(self):
        registry = ScenarioRegistry()
        profile = registry.for_template({"kind": "map-scenario", "id": "general-thematic-map",
                                         "version": "3.0.0"})
        self.assertEqual("general-thematic-mapping", profile.definition["id"])


if __name__ == "__main__":
    unittest.main()
