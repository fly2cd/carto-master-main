from __future__ import annotations

import json
import sys
import tempfile
import unittest
from copy import deepcopy
from pathlib import Path
from unittest.mock import Mock, patch

SCRIPTS_ROOT = Path(__file__).resolve().parents[1]
if str(SCRIPTS_ROOT) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_ROOT))

from carto_core.canonical import sha256_digest
from carto_core.compiler.map_candidate import MapCandidateCompiler
from carto_core.errors import ProtocolError
from carto_core.scenario_registry import ScenarioCapability, ScenarioRegistry
from carto_core.schema_registry import SchemaRegistry, load_document
from carto_core.security.paths import PathGuard
from carto_core.workflow.intent import IntentResolver, default_profiles_path
from carto_core.workflow.map_planning import MapPlanner
from carto_core.workflow.map_generation import MapGenerationWorkflow
from tests.fixtures.schema_cases import VALID_CASES


class IntentSemanticsTests(unittest.TestCase):
    """Isolated protocol assertions; no business data, enabled implementation or rendering."""

    def setUp(self) -> None:
        self.schemas = SchemaRegistry()
        self.resolver = IntentResolver(registry=self.schemas)
        self.policy = load_document(default_profiles_path())

    def assert_code(self, code, action) -> None:
        with self.assertRaises(ProtocolError) as raised:
            action()
        self.assertEqual(code, raised.exception.code)

    def request(self, scene="government_thematic", text="Protocol input") -> dict:
        profile = next(item for item in self.policy["profiles"] if item["business_scene"] == scene)
        return {"schema_version": 1, "text": text, "selection": {
            "business_scene": scene, "theme_tags": ["economic-development"],
            "tasks": [profile["task_ids"][0]],
            "fields": {key: "provided" for key in profile["required_information"] if key != "theme_tags"},
        }}

    def capability(self) -> ScenarioCapability:
        # Metadata-only double: deliberately not installed into policy or the code allowlist.
        return ScenarioCapability({
            "id": "unit-capability", "version": "1.0.0", "implementation": "not-enabled",
            "template": {"kind": "map-scenario", "id": "test-scenario", "version": "1.0.0"},
            "request_schemas": {"generate-map": "generate-request"},
            "intent_constraints": {"business_scene": "government_thematic",
                "allowed_tasks": ["administrative-map", "indicator-map"],
                "allowed_theme_tags": ["economic-development", "flood"], "required_theme_tags": []},
            "data_nature": "observed",
            "output_profile": {"width_mm": 100, "height_mm": 100, "dpi": 96,
                "width_px": 1684, "height_px": 1191},
        })

    def generation_context(self):
        registry = ScenarioRegistry(self.schemas)
        capability = self.capability()
        registry._templates[("map-scenario", "test-scenario", "1.0.0")] = capability
        request = deepcopy(VALID_CASES["generate-request"])
        request["intent"] = self.request()["selection"]
        return registry, capability, request

    def projection(self, schema, intent):
        document = deepcopy(VALID_CASES[schema])
        for key in ("business_scene", "theme_tags", "tasks"):
            document[key] = deepcopy(intent[key])
        # Reference fixtures may share objects; projections must not alias brief_ref.
        document["intent_ref"] = {**document["intent_ref"], "digest": sha256_digest(intent)}
        return document

    def test_brief_schema_does_not_force_emergency(self):
        for profile in self.policy["profiles"]:
            with self.subTest(scene=profile["business_scene"]):
                intent = self.resolver.resolve(self.request(profile["business_scene"]))
                self.schemas.validate("map-brief", self.projection("map-brief", intent))

    def test_topic_terms_do_not_choose_business_purpose(self):
        cases = [("emergency_mapping", "洪涝应急专题图"),
                 ("leadership_visit", "领导调研洪涝安置点")]
        for scene, text in cases:
            with self.subTest(scene=scene):
                request = self.request(scene, text)
                request["selection"].pop("business_scene")
                request["selection"].pop("theme_tags")
                intent = self.resolver.resolve(request)
                self.assertEqual(scene, intent["business_scene"])
                self.assertEqual(["flood"], intent["theme_tags"])
                self.assertEqual("ready", intent["readiness_status"])
        request = self.request(text="洪涝专题图")
        request["selection"].pop("business_scene")
        request["selection"].pop("theme_tags")
        intent = self.resolver.resolve(request)
        self.assertIsNone(intent["business_scene"])
        self.assertEqual([], intent["tasks"])
        self.assertEqual("unsupported", intent["intent_status"])
        self.assertEqual(["flood"], intent["theme_tags"])

    def test_multiple_topics_are_ids_and_explicit_tags_are_authoritative(self):
        request = self.request(text="政务经济发展与交通运输专题图")
        request["selection"].pop("theme_tags")
        self.assertEqual(["economic-development", "transportation"],
                         self.resolver.resolve(request)["theme_tags"])
        request["selection"]["theme_tags"] = ["flood"]
        self.assertEqual(["flood"], self.resolver.resolve(request)["theme_tags"])
        request["selection"]["theme_tags"] = []
        result = self.resolver.resolve(request)
        self.assertEqual([], result["theme_tags"])
        self.assertIn("theme_tags", result["missing_items"])
        self.assertEqual("missing_information", result["readiness_status"])

    def test_missing_task_is_not_filled_from_scene(self):
        request = self.request()
        request["selection"].pop("tasks")
        result = self.resolver.resolve(request)
        self.assertEqual([], result["tasks"])
        self.assertEqual("ambiguous", result["intent_status"])
        self.assertIn("tasks", result["missing_items"])

    def test_explicit_unknown_or_conflicting_scene_is_not_rewritten(self):
        request = self.request()
        request["selection"]["business_scene"] = "not_registered"
        result = self.resolver.resolve(request)
        self.assertIsNone(result["business_scene"])
        self.assertEqual("unsupported", result["intent_status"])
        request = self.request(text="应急地图")
        result = self.resolver.resolve(request)
        self.assertEqual("government_thematic", result["business_scene"])
        self.assertEqual("ambiguous", result["intent_status"])

    def test_legacy_topic_locations_and_business_domain_are_rejected(self):
        for key in ("theme", "business_domain", "scene_hint"):
            for location in ("root", "selection", "fields"):
                with self.subTest(key=key, location=location):
                    request = self.request()
                    target = request if location == "root" else request["selection"]
                    if location == "fields":
                        target = target["fields"]
                    target[key] = "legacy"
                    self.assert_code("SCHEMA_VALIDATION_FAILED", lambda: self.resolver.resolve(request))

    def test_unknown_tasks_topics_fields_and_display_labels_are_not_accepted(self):
        for field in ("tasks", "theme_tags"):
            request = self.request()
            request["selection"][field] = ["not-registered"]
            self.assertEqual("unsupported", self.resolver.resolve(request)["intent_status"])
        request = self.request()
        request["selection"]["theme_tags"] = ["经济发展"]
        self.assert_code("SCHEMA_VALIDATION_FAILED", lambda: self.resolver.resolve(request))
        request = self.request()
        request["selection"]["fields"]["unregistered-field"] = "provided"
        self.assert_code("INTENT_FIELD_UNKNOWN", lambda: self.resolver.resolve(request))

    def test_request_cannot_claim_available_capabilities(self):
        request = self.request()
        request["selection"]["required_capabilities"] = ["web-map-export"]
        self.assertEqual("missing_capability", self.resolver.resolve(request)["readiness_status"])
        self.assertEqual("ready", self.resolver.resolve(
            request, available_capabilities=["web-map-export"])["readiness_status"])
        request["available_capabilities"] = ["web-map-export"]
        self.assert_code("SCHEMA_VALIDATION_FAILED", lambda: self.resolver.resolve(request))

    def test_catalog_rejects_duplicates_and_can_extend_without_schema_enum(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "intent-policy.json"
            for key in ("profiles", "themes"):
                policy = deepcopy(self.policy)
                policy[key].append(deepcopy(policy[key][0]))
                path.write_text(json.dumps(policy), encoding="utf-8")
                self.assert_code("INTENT_CATALOG_DUPLICATE", lambda: IntentResolver(path, self.schemas))
            policy = deepcopy(self.policy)
            policy["profiles"].append({"business_scene": "unit_extension", "purpose_terms": ["unit purpose"],
                "task_ids": ["unit-task"], "required_information": ["source"], "unsupported_actions": []})
            path.write_text(json.dumps(policy), encoding="utf-8")
            resolver = IntentResolver(path, self.schemas)
            intent = resolver.resolve({"schema_version": 1, "text": "unit purpose", "selection": {
                "tasks": ["unit-task"], "fields": {"source": "provided"}}})
            self.assertEqual("unit_extension", intent["business_scene"])
            self.assertEqual("ready", intent["readiness_status"])
            self.schemas.validate("map-brief", self.projection("map-brief", intent))
        # The temporary intent catalog never touches the packaged scenario policy:
        # it still admits only the registered general-thematic scenario.
        self.assertEqual({("map-scenario", "general-thematic-map", "1.0.0")},
                         set(ScenarioRegistry(self.schemas)._templates))

    def test_standalone_and_generate_share_the_same_intent(self):
        registry, capability, request = self.generation_context()
        standalone = self.resolver.resolve({"schema_version": 1, "text": request["goal"],
            "selection": request["intent"], "intent_id": f"intent-{request['request_id']}"})
        bound = registry.generate_intent(request)
        self.assertEqual(standalone, {**bound, "evidence_refs": bound["evidence_refs"][:2]})
        self.assertEqual(capability.ref, bound["evidence_refs"][-1])
        capability.require_intent(bound)

    def test_selected_template_cannot_supply_missing_or_change_incompatible_intent(self):
        registry, _, request = self.generation_context()
        request["intent"].pop("tasks")
        with patch.object(registry, "for_template") as lookup:
            self.assert_code("INTENT_NOT_RESOLVED", lambda: registry.for_generate(request))
            lookup.assert_not_called()
        registry, _, request = self.generation_context()
        request["intent"]["theme_tags"] = ["transportation"]
        self.assert_code("SCENARIO_INTENT_MISMATCH", lambda: registry.for_generate(request))
        registry, _, request = self.generation_context()
        request["intent"] = self.request("emergency_mapping")["selection"]
        self.assert_code("SCENARIO_INTENT_MISMATCH", lambda: registry.for_generate(request))

    def test_intent_drift_inside_template_allowlist_still_fails(self):
        registry, _, request = self.generation_context()
        intent = registry.generate_intent(request)
        for key, value in (("theme_tags", ["flood"]), ("tasks", ["indicator-map"])):
            with self.subTest(key=key):
                changed = deepcopy(intent)
                changed[key] = value
                self.assert_code("MAP_INTENT_INPUT_DRIFT", lambda: registry.require_request_intent(request, changed))
        intent["evidence_refs"][0]["digest"] = "sha256:" + "f" * 64
        self.assert_code("INTENT_CATALOG_DRIFT", lambda: self.resolver.require_current_intent(intent))

    def test_template_contract_does_not_alias_business_scene(self):
        profile = self.capability()
        contract = {"scenario_id": "test-scenario", "version": "1.0.0",
                    "business_scene": "government_thematic", "tasks": ["administrative-map", "indicator-map"]}
        profile.require_contract(contract)
        for key, value in (("scenario_id", "government_thematic"),
                           ("business_scene", "emergency_mapping"), ("tasks", ["administrative-map"])):
            changed = {**contract, key: value}
            self.assert_code("SCENARIO_CONTRACT_MISMATCH", lambda: profile.require_contract(changed))

    def test_brief_plan_and_execution_cannot_rewrite_intent(self):
        registry, profile, request = self.generation_context()
        intent = registry.generate_intent(request)
        for schema, kind in (("map-brief", "BRIEF"), ("map-plan", "PLAN")):
            document = self.projection(schema, intent)
            profile.require_intent_projection(document, intent, kind=kind)
            for key, value in (("business_scene", "emergency_mapping"),
                               ("theme_tags", ["flood"]), ("tasks", ["indicator-map"])):
                changed = {**document, key: value}
                self.assert_code(f"{kind}_INTENT_MISMATCH",
                    lambda: profile.require_intent_projection(changed, intent, kind=kind))
        execution = {"business_scene": intent["business_scene"], "map_tasks": intent["tasks"],
            "shared_semantics": {"theme_tags": intent["theme_tags"], "data_nature": "observed"},
            "intent_ref": {"digest": sha256_digest(intent)},
            "profile_refs": [registry.intent_resolver.catalog_ref, profile.ref],
            "template_refs": [profile.definition["template"]],
            "targets": {"pdf": {"width_mm": 100, "height_mm": 100, "dpi": 96}}}
        registry.for_execution(execution)
        MapCandidateCompiler.require_execution_intent(execution, intent)
        changed = deepcopy(execution)
        changed["shared_semantics"]["theme_tags"] = ["flood"]
        self.assert_code("CANDIDATE_INTENT_MISMATCH",
                         lambda: MapCandidateCompiler.require_execution_intent(changed, intent))
        changed["shared_semantics"]["theme_tags"] = ["transportation"]
        self.assert_code("SCENARIO_INTENT_MISMATCH", lambda: registry.for_execution(changed))
        execution["profile_refs"] = [profile.ref]
        self.assert_code("SCENARIO_PROFILE_DRIFT", lambda: registry.for_execution(execution))

    def test_planner_and_compiler_enforce_projection_and_preserve_envelope(self):
        registry, profile, request = self.generation_context()
        intent = registry.generate_intent(request)
        brief = self.projection("map-brief", intent)
        plan = self.projection("map-plan", intent)
        plan["brief_ref"]["digest"] = sha256_digest(brief)
        contracts = {"scenario": {"scenario_id": "test-scenario", "version": "1.0.0",
            "business_scene": "government_thematic", "tasks": ["administrative-map", "indicator-map"]},
            "quality_gates": deepcopy(VALID_CASES["quality-gates"])}
        planner = Mock()
        planner.build.return_value = plan
        with patch("carto_core.workflow.map_planning.ScenarioRegistry", return_value=registry), patch.object(
                ScenarioCapability, "component", return_value=Mock(return_value=planner)):
            self.assertEqual(plan, MapPlanner(self.schemas).build(request, intent, brief, {}, {}, contracts))
            planner.build.return_value = {**plan, "theme_tags": ["flood"]}
            self.assert_code("PLAN_INTENT_MISMATCH", lambda:
                             MapPlanner(self.schemas).build(request, intent, brief, {}, {}, contracts))
        candidate = deepcopy(VALID_CASES["resolved-map"])
        execution = candidate["execution"]
        execution.update(business_scene=intent["business_scene"], map_tasks=intent["tasks"],
            intent_ref={"id": intent["intent_id"], "version": "1.0.0", "digest": sha256_digest(intent)},
            profile_refs=[intent["evidence_refs"][0], intent["evidence_refs"][-1]])
        execution["shared_semantics"]["theme_tags"] = intent["theme_tags"]
        scene = deepcopy(VALID_CASES["render-scene"])
        # compile() re-runs check_candidate, so the frozen execution and scene must also
        # satisfy the enabled output profile and scene binding, not only the intent projection.
        output = profile.definition["output_profile"]
        scene["export"]["dpi"] = output["dpi"]
        execution["targets"] = {name: {**target, "dpi": output["dpi"], "width_mm": output["width_mm"],
                                       "height_mm": output["height_mm"]}
                                for name, target in execution["targets"].items()}
        execution["render_scene_ref"] = {"id": scene["scene_id"], "version": "1.0.0",
                                         "digest": sha256_digest(scene)}
        candidate["execution_digest"] = sha256_digest(execution)
        envelope = {"candidate": candidate, "scene": scene,
                    "preflight": deepcopy(VALID_CASES["validation-report"])}
        component = Mock()
        component.compile.return_value = envelope
        with tempfile.TemporaryDirectory() as temp, patch(
                "carto_core.compiler.map_candidate.ScenarioRegistry", return_value=registry), patch.object(
                ScenarioCapability, "component", return_value=Mock(return_value=component)):
            compiler = MapCandidateCompiler(PathGuard([temp]), self.schemas)
            self.assertIs(envelope, compiler.compile(request, intent, plan, {}, {}, contracts, Path(temp) / "unused"))
            envelope["candidate"]["execution"]["shared_semantics"]["theme_tags"] = ["flood"]
            self.assert_code("CANDIDATE_INTENT_MISMATCH", lambda:
                compiler.compile(request, intent, plan, {}, {}, contracts, Path(temp) / "unused"))

    def test_same_version_catalog_content_drift_is_rejected(self):
        intent = self.resolver.resolve(self.request())
        policy = deepcopy(self.policy)
        policy["themes"][0]["label"] = "Changed display label"
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "intent-policy.json"
            path.write_text(json.dumps(policy), encoding="utf-8")
            changed = IntentResolver(path, self.schemas)
            self.assert_code("INTENT_CATALOG_DRIFT", lambda: changed.require_current_intent(intent))
        intent["theme_tags"] = []
        self.assert_code("INTENT_THEME_REQUIRED", lambda: self.resolver.require_current_intent(intent))

    def test_brief_builder_preserves_non_emergency_intent_without_io(self):
        registry, _, request = self.generation_context()
        request.update(run_id="unit-run", audience="unit-audience", scope="project:test-project",
                       environment="unit", allowed_capabilities=["read"])
        request["template"]["digest"] = "sha256:" + "a" * 64
        request["intent"]["theme_tags"] = ["flood", "economic-development"]
        intent = registry.generate_intent(request)
        # Isolate only brief construction, not workflow authorization or any source data read.
        workflow = object.__new__(MapGenerationWorkflow)
        workflow.registry = self.schemas
        workflow.project_root = Path("unused-project")
        workflow.work_root = Path("unused-work")
        workflow.path_guard = Mock()
        workflow.path_guard.resolve.return_value = Path("unused-output")
        workflow._resume = Mock(return_value=(request, Mock()))
        workflow._load = Mock(return_value=intent)
        workflow.state_store = Mock()
        state, receipt = Mock(), Mock()
        state.to_dict.return_value = {}
        receipt.to_dict.return_value = {}
        workflow.state_store.complete_step.return_value = (state, receipt)
        with patch("carto_core.workflow.map_generation.ScenarioRegistry", return_value=registry), patch(
                "carto_core.workflow.map_generation.file_digest", return_value="sha256:" + "b" * 64), patch(
                "carto_core.workflow.map_generation.atomic_yaml") as persist:
            result = MapGenerationWorkflow.brief.__wrapped__(workflow, "unused-request")
        self.assertEqual("government_thematic", result["brief"]["business_scene"])
        for key in ("business_scene", "theme_tags", "tasks"):
            self.assertEqual(intent[key], result["brief"][key])
        self.assertEqual(sha256_digest(result["brief"]), result["approval_object_digest"])
        persist.assert_called_once_with(Path("unused-output"), result["brief"])

    def test_explicit_valid_and_invalid_intent_request_fixtures(self):
        root = Path(__file__).parent / "fixtures"
        self.schemas.validate("intent-request", load_document(root / "intent-request.valid.json"))
        self.assert_code("SCHEMA_VALIDATION_FAILED", lambda: self.schemas.validate(
            "intent-request", load_document(root / "intent-request.invalid.json")))


if __name__ == "__main__":
    unittest.main()
