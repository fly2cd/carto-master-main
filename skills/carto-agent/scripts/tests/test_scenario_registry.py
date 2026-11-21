from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

SCRIPTS_ROOT = Path(__file__).resolve().parents[1]
if str(SCRIPTS_ROOT) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_ROOT))

from carto_core.errors import ProtocolError, SecurityError
from carto_core.scenario_registry import ScenarioCapability, ScenarioRegistry
from carto_core.schema_registry import SchemaRegistry, load_document
from carto_core.security.paths import PathGuard
from carto_core.workflow.template_analysis import ControlledSourceAnalyzer
from tests.fixtures.schema_cases import VALID_CASES, VARIANT_CAPABILITIES_POLICY


class ScenarioRegistryTests(unittest.TestCase):
    """Admission and protocol checks for the single registered general-thematic scenario."""

    def setUp(self):
        self.schemas = SchemaRegistry()

    def assert_code(self, code, action):
        with self.assertRaises(ProtocolError) as raised:
            action()
        self.assertEqual(code, raised.exception.code)

    def test_packaged_registry_admits_only_the_registered_scenario(self):
        with patch("carto_core.scenario_registry.import_module") as importer:
            registry = ScenarioRegistry(self.schemas)
            self.assertEqual({("map-scenario", "general-thematic-map", "3.0.0"),
                              ("map-scenario", "general-thematic-map", "4.0.0"),
                              ("map-scenario", "leadership-visit-map", "1.0.0")},
                             set(registry._templates))
            profile = registry.for_create(
                deepcopy(VALID_CASES["general-template-create-request"]))
            self.assertEqual("general-thematic-mapping", profile.definition["id"])
            self.assertEqual("general_thematic_mapping",
                             profile.definition["intent_constraints"]["business_scene"])
            # Every other identity stays default-deny, including the structural test fixtures.
            self.assert_code("CAPABILITY_NOT_AVAILABLE", lambda: registry.for_create(
                deepcopy(VALID_CASES["template-create-request"])))
            self.assert_code("CAPABILITY_NOT_AVAILABLE", lambda: registry.for_generate(
                deepcopy(VALID_CASES["generate-request"])))
            # Admission and schema checks are lazy; registering never imports implementations.
            importer.assert_not_called()

    def test_unknown_identity_and_version_have_no_fallback(self):
        registry = ScenarioRegistry(self.schemas)
        for identity in ({"id": "unregistered-scene"}, {"version": "9.0.0"}):
            request = deepcopy(VALID_CASES["generate-request"])
            request["template"].update(identity)
            self.assert_code("CAPABILITY_NOT_AVAILABLE", lambda: registry.for_generate(request))

    def test_generic_request_structure_does_not_certify_capability(self):
        request = deepcopy(VALID_CASES["template-create-request"])
        request.update(template_id="unregistered-scene", profile="unregistered-profile",
                       data_nature="observed", contains_production_data=True,
                       role_bindings={"line_source": "lines"},
                       source_crs={"authority": "EPSG", "code": "4490"})
        self.schemas.validate("template-create-request", request)
        self.assert_code("CAPABILITY_NOT_AVAILABLE", lambda: ScenarioRegistry(self.schemas).for_create(request))
        brief = deepcopy(VALID_CASES["template-brief"])
        brief["data_roles"] = [{"role_id": "line-role", "source_id": "lines",
                                "geometry_types": ["line"], "value_field": "metric",
                                "semantic_role": "metric-value"}]
        self.schemas.validate("template-brief", brief)

    def test_undeclared_source_binding_fields_are_rejected(self):
        # source_bindings is a scenario body field: closure lives in the profile, not the open envelope.
        request = deepcopy(VALID_CASES["general-generate-request"])
        request["source_bindings"][0]["temporary_override"] = True
        self.assert_code("SCHEMA_VALIDATION_FAILED", lambda: self.schemas.validate("general-generate-request", request))

    def test_empty_policy_requires_explicit_default_deny(self):
        policy = deepcopy(VALID_CASES["scenario-capabilities"])
        self.schemas.validate("scenario-capabilities", policy)
        policy["default"] = "allow"
        with patch("carto_core.scenario_registry.load_document", return_value=policy), patch(
                "carto_core.scenario_registry.import_module") as importer:
            self.assert_code("SCHEMA_VALIDATION_FAILED", lambda: ScenarioRegistry(self.schemas))
            importer.assert_not_called()

    def test_arbitrary_component_is_not_imported(self):
        capability = ScenarioCapability({"implementation": "unregistered-module"})
        with patch("carto_core.scenario_registry.import_module") as importer:
            self.assert_code("CAPABILITY_NOT_AVAILABLE", lambda: capability.component("author"))
            importer.assert_not_called()

    def test_rejected_create_does_not_read_the_source_manifest(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            request = deepcopy(VALID_CASES["template-create-request"])
            request["source_manifest_path"] = "must-not-be-opened.json"
            path = root / "request.json"
            path.write_text(json.dumps(request), encoding="utf-8")
            analyzer = ControlledSourceAnalyzer(PathGuard([root]), root, self.schemas)
            with patch.object(analyzer, "_analyze_sources") as analyze:
                self.assert_code("CAPABILITY_NOT_AVAILABLE", lambda: analyzer.load_inputs(path))
                analyze.assert_not_called()

    def test_source_contract_validation_is_required_even_for_empty_manifest(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            analyzer = ControlledSourceAnalyzer(PathGuard([root]), root, self.schemas)
            self.assert_code("CAPABILITY_NOT_AVAILABLE", lambda: analyzer._analyze_sources(
                {"sources": []}, {}, SimpleNamespace()))

    def test_source_admission_runs_before_any_source_path_read(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            analyzer = ControlledSourceAnalyzer(PathGuard([root]), root, self.schemas)
            validator = Mock(side_effect=SecurityError("SOURCE_ADMISSION_DENIED", "Denied by scene policy"))
            source = {"source_id": "source-one", "kind": "csv", "license": "project-approved",
                      "data_profile": {"data_nature": "observed"}}
            with self.assertRaises(SecurityError) as raised:
                analyzer._analyze_sources({"sources": [source]}, {},
                                         SimpleNamespace(validate_source_profile=validator))
            self.assertEqual("SOURCE_ADMISSION_DENIED", raised.exception.code)
            validator.assert_called_once_with(source, {})


class GeometryVariantPolicyTests(unittest.TestCase):
    """ADR-001 §9.5 项④: one capability profile, geometry as a data-adaptation variant."""

    POLICY_PATH = Path(__file__).resolve().parents[2] / "policies" / "scenario-capabilities.yaml"

    def setUp(self):
        self.schemas = SchemaRegistry()

    def assert_code(self, code, action):
        with self.assertRaises(ProtocolError) as raised:
            action()
        self.assertEqual(code, raised.exception.code)

    def registry_for(self, policy):
        with patch("carto_core.scenario_registry.load_document", return_value=policy), patch(
                "carto_core.scenario_registry.import_module"):
            return ScenarioRegistry(self.schemas)

    def test_packaged_policy_declares_the_shared_segment_once(self):
        policy = load_document(self.POLICY_PATH)
        self.schemas.validate("scenario-capabilities", policy)
        # Two registered business purposes: general thematic + leadership visit.
        self.assertEqual(["general-thematic-mapping", "leadership-visit-mapping"],
                         [item["id"] for item in policy["profiles"]])
        profile = policy["profiles"][0]
        self.assertEqual(["raster", "vector"],
                         [variant["geometry"] for variant in profile["geometry_variants"]])
        # The convergence has to be textual, not only structural: a shared declaration
        # copied per geometry is what let the two profiles drift apart before. Counted
        # within one profile's own declaration — a second scenario is a legitimate
        # second registration of a different purpose, not a drift of this one.
        profile_text = json.dumps(profile, ensure_ascii=False)
        for fragment in ("administrative-division", "land-cover", "max_width_mm",
                         "allowed_shapes", "user-declared-source-license"):
            self.assertEqual(1, profile_text.count(fragment), fragment)
        # Per-geometry fields live only inside a variant.
        for field in ("template", "authoring_profile", "renderer_id",
                      "template_geometry", "allowed_geometries"):
            self.assertNotIn(field, profile, field)
        # The leadership-visit profile registers its own purpose, implementation and
        # single vector variant (P2 admission skeleton; renderer derives from the registry).
        leadership = policy["profiles"][1]
        self.assertEqual("leadership_visit",
                         leadership["intent_constraints"]["business_scene"])
        self.assertEqual("leadership-visit", leadership["implementation"])
        self.assertEqual(["vector"],
                         [variant["geometry"] for variant in leadership["geometry_variants"]])
        self.assertFalse(leadership["production_enabled"])

    def test_variants_flatten_into_one_capability_per_geometry(self):
        policy = deepcopy(VARIANT_CAPABILITIES_POLICY)
        self.schemas.validate("scenario-capabilities", policy)
        registry = self.registry_for(policy)
        self.assertEqual({("map-scenario", "unit-scenario-map", "9.9.0"),
                          ("map-scenario", "unit-scenario-map", "9.8.0")}, set(registry._templates))
        raster = registry.for_template({"kind": "map-scenario", "id": "unit-scenario-map",
                                        "version": "9.9.0"})
        vector = registry.for_template({"kind": "map-scenario", "id": "unit-scenario-map",
                                        "version": "9.8.0"})
        for cap, geometry, renderer, authoring in (
                (raster, "raster", "rasterio-matplotlib-page", "unit-raster-authoring"),
                (vector, "vector", "matplotlib-vector-page", "unit-vector-authoring")):
            with self.subTest(geometry=geometry):
                # The shared segment reaches every variant unchanged.
                self.assertEqual("unit-scenario", cap.definition["id"])
                self.assertEqual("general_thematic_mapping",
                                 cap.definition["intent_constraints"]["business_scene"])
                self.assertEqual(["thematic-map"], cap.definition["intent_constraints"]["allowed_tasks"])
                # Only the geometry-adaptation fields differ, and they stay explicit.
                self.assertEqual(geometry, cap.definition["template_geometry"])
                self.assertEqual([geometry], cap.definition["allowed_geometries"])
                self.assertEqual(renderer, cap.definition["renderer_id"])
                self.assertEqual(authoring, cap.definition["authoring_profile"])
        # One profile identity, two distinguishable capability refs.
        self.assertEqual(raster.ref["id"], vector.ref["id"])
        self.assertEqual(raster.ref["version"], vector.ref["version"])
        self.assertNotEqual(raster.ref["digest"], vector.ref["digest"])
        # Each geometry remains its own admission lever.
        self.assert_code("CAPABILITY_NOT_AVAILABLE", lambda: registry.require_geometry(raster, "vector"))
        self.assert_code("CAPABILITY_NOT_AVAILABLE", lambda: registry.require_geometry(vector, "raster"))

    def test_two_variants_of_one_geometry_stay_ambiguous(self):
        policy = deepcopy(VARIANT_CAPABILITIES_POLICY)
        variants = policy["profiles"][0]["geometry_variants"]
        variants[1] = deepcopy(variants[0])
        variants[1]["template"]["version"] = "9.7.0"
        self.assert_code("SCENARIO_PROFILE_DUPLICATE", lambda: self.registry_for(policy))

    def test_two_profiles_sharing_one_authoring_profile_stay_ambiguous(self):
        policy = deepcopy(VARIANT_CAPABILITIES_POLICY)
        second = deepcopy(policy["profiles"][0])
        second["id"] = "unit-scenario-two"
        second["geometry_variants"] = [deepcopy(second["geometry_variants"][1])]
        second["geometry_variants"][0]["template"]["version"] = "9.7.0"
        policy["profiles"].append(second)
        self.assert_code("SCENARIO_PROFILE_DUPLICATE", lambda: self.registry_for(policy))


if __name__ == "__main__":
    unittest.main()
