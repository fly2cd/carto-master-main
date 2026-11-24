"""Framework contracts, immutable artifacts and quality gates.

Synthetic fixtures only; these regressions do not grant scenario admission or approvals.
"""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
import hashlib
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

from carto_core.artifacts import artifact_ref, atomic_json, atomic_yaml, file_digest, utc_now
from carto_core.canonical import canonical_json_bytes, sha256_digest
from carto_core.contracts.execution import ExecutionContext
from carto_core.errors import ProtocolError
from carto_core.repository.delivery_repository import DeliveryRepository
from carto_core.repository.immutable_store import ImmutableArtifactStore
from carto_core.repository.staging_package import StagingPackageWriter
from carto_core.scenario_registry import ScenarioCapability
from carto_core.schema_registry import SchemaRegistry, load_document
from carto_core.security.paths import PathGuard
from carto_core.validation.map_checks import MapQualityChecks, legend_consistency
from carto_core.validation.registry import CheckerRegistry, DEFAULT_POLICY
from carto_core.workflow.map_final_check import FinalMapCheckService
from carto_core.workflow.state_machine import _create_json_once
from carto_core.workflow.template_validation import TemplatePackageValidator
from tests.fixtures.schema_cases import VALID_CASES

FIXTURES = Path(__file__).with_name("fixtures")


class FrameworkContractTests(unittest.TestCase):
    """Isolated framework assertions, not an executable business scenario."""

    def test_expression_metadata_does_not_fabricate_fixture_evidence(self):
        value = deepcopy(VALID_CASES["map-expression"])
        value.pop("fixture_refs")
        registry = SchemaRegistry()
        registry.validate("map-expression", value)
        value["fixture_refs"] = []
        with self.assertRaises(ProtocolError):
            registry.validate("map-expression", value)

    def test_delivery_readme_uses_only_manifest_disclosures(self):
        manifest = {"licenses": ["license-from-manifest"],
                    "limitations": ["limitation-from-manifest"],
                    "recipient": {"recipient_type": "internal", "recipient_id": "unit-recipient"}}
        text = DeliveryRepository._readme(manifest)
        self.assertIn("license-from-manifest", text)
        self.assertIn("limitation-from-manifest", text)
        self.assertTrue(text.rstrip().endswith("- limitation-from-manifest"))

    def test_notice_requires_matching_scene_evidence_receipt_and_artifact(self):
        checker = object.__new__(FinalMapCheckService)
        checker._artifact_path = Mock(return_value=Path("unit-artifact"))
        scene = {"overlays": [{"content": "Required restriction", "coordinate_space": "page"}]}
        context = {"scenario_profile": SimpleNamespace(notice="Required restriction"),
                   "scene": scene, "evidence": {"scenario_notice": "Required restriction"},
                   "receipt": {"scene_digest": sha256_digest(scene)}, "artifacts": [{}]}
        self.assertTrue(checker._scenario_notice(context)[0])
        context["evidence"]["scenario_notice"] = "Wrong restriction"
        self.assertFalse(checker._scenario_notice(context)[0])
        context["evidence"]["scenario_notice"] = "Required restriction"
        context["receipt"]["scene_digest"] = "sha256:" + "0" * 64
        self.assertFalse(checker._scenario_notice(context)[0])
        context["receipt"]["scene_digest"] = sha256_digest(scene)
        checker._artifact_path.return_value = None
        self.assertFalse(checker._scenario_notice(context)[0])

    def test_validation_data_checker_is_required(self):
        validator = object.__new__(TemplatePackageValidator)
        validator.registry = Mock()
        validator.package_root = Path("not-read")
        capability = ScenarioCapability({"implementation": "unregistered-module"})
        with patch("carto_core.workflow.template_validation.ScenarioRegistry") as registry:
            registry.return_value.for_template.return_value = capability
            with self.assertRaises(ProtocolError) as raised:
                validator._check_semantics({"manifest": {"package": {}}, "documents": {}}, {}, [])
        self.assertEqual("CAPABILITY_NOT_AVAILABLE", raised.exception.code)

    def test_staging_reads_declared_prototype_instead_of_a_fixed_name(self):
        # Empty documents and mock validators isolate filename discovery; no real template is authored.
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            files = ["dependencies.lock.yaml", "prototypes/declared-view.yml"]
            contracts = {key: "contracts/" + key + ".yaml" for key in (
                "scenario", "data_schema", "spatial_behavior", "portrayal", "delivery", "quality_gates")}
            files.extend(contracts.values())
            contents = {name: b"{}\n" for name in ["manifest.yaml", "checksums.sha256", *files]}
            contents["prototypes/declared-view.yml"] = b"prototype_id: unit-prototype\n"
            for name, content in contents.items():
                path = root / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(content)
            checksums = {name: "sha256:" + hashlib.sha256(content).hexdigest()
                         for name, content in contents.items() if name != "checksums.sha256"}
            writer = object.__new__(StagingPackageWriter)
            writer.registry = Mock()
            writer.resolver = Mock()
            writer.verify_closed_package(root, {"files": files, "dependency_lock": "dependencies.lock.yaml",
                                                "business_contracts": contracts}, checksums)
            writer.registry.validate.assert_any_call("prototype-description", {"prototype_id": "unit-prototype"})


class ArtifactUtilityTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def test_yaml_immutability_is_semantic_but_json_is_serialized(self):
        yaml_path, json_path = self.root / "report.yaml", self.root / "report.json"
        yaml_path.write_text("b: 2\na: 1\n", encoding="utf-8")
        before = yaml_path.read_bytes()
        atomic_yaml(yaml_path, {"a": 1, "b": 2})
        self.assertEqual(before, yaml_path.read_bytes())
        with self.assertRaisesRegex(ProtocolError, "IMMUTABLE_ARTIFACT_CONFLICT"):
            atomic_yaml(yaml_path, {"a": 2})
        atomic_yaml(yaml_path, {"a": 2}, create_once=False)
        self.assertEqual({"a": 2}, load_document(yaml_path))
        atomic_json(json_path, {"b": 2, "a": 1})
        self.assertEqual(b'{"a":1,"b":2}\n', json_path.read_bytes())
        atomic_json(json_path, {"a": 1, "b": 2})
        json_path.write_text('{ "a": 1, "b": 2 }\n', encoding="utf-8")
        with self.assertRaisesRegex(ProtocolError, "IMMUTABLE_ARTIFACT_CONFLICT"):
            atomic_json(json_path, {"a": 1, "b": 2})
        # State receipts intentionally compare decoded JSON, unlike artifact JSON.
        _create_json_once(json_path, {"a": 1, "b": 2})
        json_path.write_text("broken", encoding="utf-8")
        with self.assertRaisesRegex(ProtocolError, "IMMUTABLE_ARTIFACT_INVALID"):
            _create_json_once(json_path, {"a": 1})

    def test_atomic_replacement_failure_preserves_target_and_removes_tempfile(self):
        for name, writer in (("report.yaml", atomic_yaml), ("report.json", atomic_json)):
            target = self.root / name
            writer(target, {"revision": 1})
            before = target.read_bytes()
            with patch("carto_core.artifacts.os.replace", side_effect=OSError("synthetic failure")):
                with self.assertRaises(OSError):
                    writer(target, {"revision": 2}, create_once=False)
            self.assertEqual(before, target.read_bytes())
            self.assertEqual([], list(self.root.glob(".*.tmp")))

    def test_file_and_object_digests_remain_distinct(self):
        path = self.root / "bytes.bin"
        payload = b"synthetic-only" * 100_000
        path.write_bytes(payload)
        self.assertEqual("sha256:" + hashlib.sha256(payload).hexdigest(), file_digest(path))
        document = {"text": "test", "value": 1}
        path.write_text(json.dumps(document, indent=2), encoding="utf-8")
        self.assertNotEqual(sha256_digest(document), file_digest(path))
        ref = artifact_ref("test-artifact", document, path)
        self.assertEqual(sha256_digest(document), ref["digest"])
        self.assertEqual(str(path), ref["uri"])

    def test_content_addressed_store_keeps_canonical_bytes_and_rejects_conflicts(self):
        store = ImmutableArtifactStore(self.root / "store")
        value = {"b": 2, "a": 1}
        artifact = store.put("test-artifact", "1.0.0", value)
        self.assertEqual(canonical_json_bytes(value) + b"\n", artifact.path.read_bytes())
        self.assertEqual(artifact, store.put("test-artifact", "1.0.0", value))
        self.assertEqual(value, store.get(artifact))
        artifact.path.write_text(json.dumps(value, indent=2), encoding="utf-8")
        with self.assertRaisesRegex(ProtocolError, "IMMUTABLE_ARTIFACT_CONFLICT"):
            store.put("test-artifact", "1.0.0", value)
        with self.assertRaisesRegex(ProtocolError, "CANONICALIZATION_FAILED"):
            store.put("test-artifact", "1.0.0", {"nan": float("nan")})

    def test_clock_format_and_request_context_factory(self):
        self.assertRegex(utc_now(), r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z$")
        self.assertEqual(timezone.utc, datetime.fromisoformat(utc_now()).tzinfo)
        request = {"run_id": "run-test", "project_id": "project-test", "environment": "local",
                   "subject": {"tenant_id": "tenant-test", "subject_id": "operator-test"},
                   "allowed_capabilities": ["read", "classify"]}
        first = ExecutionContext.from_generate_request(request)
        second = ExecutionContext.from_generate_request(request)
        self.assertEqual(frozenset({"operator"}), first.roles)
        self.assertEqual(frozenset({"project-test"}), first.namespaces)
        self.assertEqual(frozenset({"read", "classify"}), first.authorized_capabilities)
        self.assertIsNot(first.budget, second.budget)
        first.require_project_scope()


class CheckerConsolidationTests(unittest.TestCase):
    def setUp(self):
        self.schemas = SchemaRegistry()
        self.checkers = CheckerRegistry(schema_registry=self.schemas)
        self.gates = load_document(FIXTURES / "quality-gates-registered.valid.json")

    def test_registered_and_unregistered_fixtures(self):
        self.assertEqual(tuple(item["id"] for item in self.gates["checks"]),
                         MapQualityChecks(self.schemas).selection(self.gates, raster=True))
        invalid = load_document(FIXTURES / "quality-gates-registered.invalid.json")
        # Structurally legal does not imply registered executable capability.
        self.schemas.validate("quality-gates", invalid)
        with self.assertRaisesRegex(ProtocolError, "CHECKER_UNREGISTERED"):
            MapQualityChecks(self.schemas).selection(invalid)

    def test_quality_gates_reject_version_params_phase_and_duplicate_ids(self):
        variants = []
        wrong_version = deepcopy(self.gates)
        wrong_version["checks"][0]["version"] = "9.0.0"
        variants.append((wrong_version, "CHECKER_VERSION_MISMATCH"))
        unknown_params = deepcopy(self.gates)
        unknown_params["checks"][0]["params"] = {"skip": True}
        variants.append((unknown_params, "CHECKER_PARAMS_UNSUPPORTED"))
        wrong_phase = deepcopy(self.gates)
        wrong_phase["checks"][0]["id"] = "security.path-contained"
        variants.append((wrong_phase, "CHECKER_PHASE_UNSUPPORTED"))
        duplicate = deepcopy(self.gates)
        duplicate["checks"].append({**duplicate["checks"][0], "version": "2.0.0"})
        variants.append((duplicate, "CHECKER_DUPLICATE"))
        for value, code in variants:
            with self.subTest(code=code), self.assertRaisesRegex(ProtocolError, code):
                self.checkers.resolve_quality_gates(value)

    def test_omitted_template_checks_cannot_remove_raster_baseline(self):
        gates = deepcopy(self.gates)
        gates["checks"] = gates["checks"][:1]
        selected = MapQualityChecks(self.schemas).selection(gates, raster=True)
        self.assertEqual({item["id"] for item in self.gates["checks"]}, set(selected))
        with self.assertRaisesRegex(ProtocolError, "CHECKER_NOT_AVAILABLE"):
            self.checkers.evaluate("protocol.schema-valid", {})

    def test_quality_reference_binds_template_and_effective_checks(self):
        checks = MapQualityChecks(self.schemas)
        scene = {"renderer_id": "rasterio-matplotlib-page"}
        original = checks.reference(self.gates, scene)
        self.assertEqual(original, checks.reference(deepcopy(self.gates), scene))
        narrower = deepcopy(self.gates)
        narrower["checks"] = narrower["checks"][:1]
        # Even when mandatory checks produce the same effective set, a changed
        # template declaration must require a new candidate and approval.
        self.assertEqual(checks.selection(self.gates, raster=True), checks.selection(narrower, raster=True))
        self.assertNotEqual(original, checks.reference(narrower, scene))
        self.assertEqual({"id", "version", "digest"}, set(original))

    def test_missing_stale_or_duplicate_quality_reference_fails_before_execution(self):
        checks = MapQualityChecks(self.schemas)
        scene = {"renderer_id": "rasterio-matplotlib-page"}
        reference = checks.reference(self.gates, scene)
        variants = [[], [{**reference, "digest": "sha256:" + "0" * 64}],
                    [reference, deepcopy(reference)]]
        with patch.object(checks.checkers, "evaluate") as evaluate:
            for refs in variants:
                candidate = {"execution": {"policy_refs": refs}}
                with self.subTest(refs=refs), self.assertRaisesRegex(ProtocolError, "CANDIDATE_CHECKER_SET_DRIFT"):
                    checks.inspect(candidate, scene, self.gates, profile=None)
            evaluate.assert_not_called()

    def test_shared_results_keep_warning_disposition_and_fail_closed(self):
        self.checkers.register("final.renderer-warnings", lambda _, ctx: (False, {}, ctx["disposition"]))
        result = self.checkers.evaluate("final.renderer-warnings", {}, {"disposition": "fix-and-recheck"}).to_dict()
        self.assertEqual("fix-and-recheck", result["disposition"])
        self.assertTrue(self.checkers.has_blocking_failure([result]))
        result = self.checkers.evaluate("final.renderer-warnings", {}, {"disposition": "accepted"}).to_dict()
        self.assertFalse(self.checkers.has_blocking_failure([result]))
        self.checkers.register("protocol.schema-valid", lambda _, ctx: (True, {}))
        report = self.checkers.run("validate", {})
        self.schemas.validate("validation-report", report.to_dict())
        self.assertEqual("passed", report.status)
        self.assertNotIn("disposition", report.to_dict()["results"][0])

    def test_final_baseline_cannot_be_dropped_and_duplicate_registry_is_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            policy = load_document(DEFAULT_POLICY)
            policy["checks"] = [item for item in policy["checks"] if item["id"] != "final.required-targets"]
            path = root / "policy.yaml"
            atomic_yaml(path, policy)
            with self.assertRaisesRegex(ProtocolError, "FINAL_CHECKERS_MISSING"):
                FinalMapCheckService(path_guard=PathGuard([root]), project_root=root, work_root=root,
                                     policy_path=path)
            policy["checks"].append(deepcopy(policy["checks"][0]))
            atomic_yaml(path, policy, create_once=False)
            with self.assertRaisesRegex(ProtocolError, "CHECKER_DUPLICATE"):
                CheckerRegistry(path)

    def test_legend_and_classification_checks_use_content_not_just_ids(self):
        from carto_core.scenarios.general_thematic.raster import legend_checker
        class Profile:
            def component(self, name):
                if name != "legend_checker":
                    raise AssertionError(name)
                return legend_checker
        table = [{"value": 1, "label": "Category A", "color": "#FF0000", "order": 1,
                  "display": "color", "include_in_legend": True}]
        items = [{key: row[key] for key in ("value", "label", "color", "order")} for row in table]
        report = {"status": "ready", "questions": [], "request": {"source": {"source_ref": {"id": "source-a"}}}}
        ref = artifact_ref("raster-prepared-data", report)
        portrayal = {"lookup_table": table, "legend_items": items, "prepared_ref": ref,
                     "source_mask_policy": "preserve", "resampling": "nearest"}
        raster = {"layers": {"main-view": {"portrayal": portrayal, "report": report}},
                  "page": {"legends": [{"content_id": "legend", "items": items}]},
                  "bundle": {"digest": "sha256:" + "a" * 64, "open_issues": [],
                             "role_bindings": [{"source_id": "source-a", "prepared_ref": ref}]}}
        context = {"raster": raster, "scenario_profile": Profile()}
        self.assertTrue(legend_consistency(context)[0])
        checks = MapQualityChecks(self.schemas).checkers
        self.assertEqual("passed", checks.evaluate("raster.classification-clarified", {}, context).status)
        portrayal["legend_items"][0]["color"] = "#000000"
        self.assertFalse(legend_consistency(context)[0])
        report["status"] = "needs-clarification"
        report["questions"] = [{"question_id": "synthetic-question"}]
        self.assertEqual("failed", checks.evaluate("raster.classification-clarified", {}, context).status)

    def test_template_static_and_replay_share_failure_order_without_rendering(self):
        validator = TemplatePackageValidator.__new__(TemplatePackageValidator)
        validator.registry, validator.checkers = self.schemas, self.checkers
        snapshot = {"actual_files": ["manifest.yaml"], "package_digest": "sha256:" + "0" * 64}
        with patch.object(validator, "_check_package_files", return_value=snapshot), \
             patch.object(validator, "_check_schemas", side_effect=ProtocolError("SYNTHETIC_SCHEMA_FAILURE", "test")), \
             patch.object(validator, "_check_dependencies") as dependencies, \
             patch.object(validator, "_render_fixture") as render:
            results = []
            validator._validate_static({}, [], results)
            self.assertEqual(["template.package-closed", "template.schema-valid"],
                             [item["check_id"] for item in results])
            self.assertEqual("failed", results[-1]["status"])
            with self.assertRaisesRegex(ProtocolError, "SYNTHETIC_SCHEMA_FAILURE"):
                validator.inspect({}, [])
            dependencies.assert_not_called()
            render.assert_not_called()


if __name__ == "__main__":
    unittest.main()
