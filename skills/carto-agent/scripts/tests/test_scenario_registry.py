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
from carto_core.schema_registry import SchemaRegistry
from carto_core.security.paths import PathGuard
from carto_core.workflow.template_analysis import ControlledSourceAnalyzer
from tests.fixtures.schema_cases import VALID_CASES


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
            self.assertEqual({("map-scenario", "general-thematic-map", "1.0.0")},
                             set(registry._templates))
            profile = registry.for_create(
                deepcopy(VALID_CASES["general-thematic-template-create-request"]))
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
        request = deepcopy(VALID_CASES["generate-request"])
        request["source_bindings"][0]["temporary_override"] = True
        self.assert_code("SCHEMA_VALIDATION_FAILED", lambda: self.schemas.validate("generate-request", request))

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


if __name__ == "__main__":
    unittest.main()
