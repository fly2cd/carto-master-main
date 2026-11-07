"""Tests for the registered general_thematic_mapping scenario (general-thematic-raster).

Synthetic data, synthetic approval keys and TemporaryDirectory roots only. These tests
never create or consume a real user approval, and they assert that the unregistered
raster fixture-render branch fails closed instead of working around it. Publishing the
template and delivering a real map therefore stay out of reach until that framework
evolution lands — exactly what the scenario admission README requires.
"""
from __future__ import annotations

from copy import deepcopy
from dataclasses import asdict, replace
from datetime import UTC, datetime, timedelta
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

SCRIPTS_ROOT = Path(__file__).resolve().parents[1]
if str(SCRIPTS_ROOT) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_ROOT))

from carto_core.canonical import sha256_digest
from carto_core.compiler.map_candidate import MapCandidateCompiler
from carto_core.compiler.raster_scene import RASTER_RENDERER_ID, RasterSceneCompiler
from carto_core.errors import CartoError, ProtocolError, SecurityError
from carto_core.repository.template_installer import ProjectTemplateInstaller
from carto_core.scenario_registry import ScenarioCapability, ScenarioRegistry
from carto_core.schema_registry import SchemaRegistry, load_document
from carto_core.scenarios.general_thematic import (
    GeneralThematicAuthor, GeneralThematicCandidateCompiler, GeneralThematicDataPreparer,
    GeneralThematicPlanner, SOURCE_CONTRACT, legend_checker,
    validation_data_checker, validation_scene,
)
from carto_core.security.approval import ApprovalReceipt, sign_receipt
from carto_core.security.paths import PathGuard
from carto_core.artifacts import artifact_ref, atomic_yaml, file_digest, utc_now
from carto_core.workflow.models import ExecutionContext
from carto_core.validation.map_checks import MapQualityChecks
from carto_core.workflow.map_generation import MapGenerationWorkflow
from carto_core.workflow.raster_bundle import RasterBundlePreparer
from carto_core.workflow.template_workflow import TemplateCreationWorkflow
from tests.fixtures.schema_cases import VALID_CASES
from tests.test_raster_classification import PreparationFixture
from tests.test_raster_page_renderer import release_test_font_handles
from tests import test_raster_renderer as raster_helpers

KEY = b"synthetic-render-key-not-for-production-1234"
APPROVAL_KEY = b"synthetic-approval-key-not-for-production-1234"
NOTICE = "通用专题图：依据用户提供的数据编制，未经业务审定"
GOAL = "编制土地覆盖通用专题图"
LEGEND_TITLE = "图例"
TEMPLATE = {"namespace": "local", "kind": "map-scenario",
            "id": "general-thematic-map", "version": "1.0.0"}
BRIEF_STUB = {"kind": "map-scenario", "namespace": "local",
              "template_id": "general-thematic-map", "version": "1.0.0"}
SCENE_TEXT = NOTICE + GOAL + LEGEND_TITLE
LEGEND_CSV = "category_value,category_label\n1,示例类别一\n2,示例类别二\n3,示例类别三\n"
CRS_26911 = {"authority": "EPSG", "code": "26911"}
CRS_4326 = {"authority": "EPSG", "code": "4326"}
# Fail-closed codes the fixture-render blocker may carry: the scenario component itself
# (RASTER_FIXTURE_RENDER_UNREGISTERED) or a host without a controlled browser/font.
FIXTURE_RENDER_BLOCKED = {"RASTER_FIXTURE_RENDER_UNREGISTERED",
                          "RENDER_BROWSER_UNAVAILABLE", "RENDER_FONT_UNAVAILABLE"}


def find_cjk_font(required_text: str) -> Path | None:
    """First embeddable single-face Windows TTF that covers every scenario string."""
    fonts = Path(os.environ.get("SystemRoot", os.environ.get("WINDIR", r"C:\Windows"))) / "Fonts"
    for name in ("simhei.ttf", "simkai.ttf", "simfang.ttf", "Deng.ttf", "msyh.ttf"):
        candidate = fonts / name
        try:
            if not candidate.is_file():
                continue
            with open(candidate, "rb") as stream:
                if stream.read(4) != b"\x00\x01\x00\x00":
                    continue
            from fontTools.ttLib import TTFont
            font = TTFont(str(candidate), lazy=True)
            try:
                if int(font["OS/2"].fsType) & (0x2 | 0x100 | 0x200):
                    continue
                cmap = font.getBestCmap()
            finally:
                font.close()
        except Exception:
            continue
        if all(ord(ch) in cmap for ch in required_text if not ch.isspace()):
            return candidate
    return None


def sign(gate: str, action: str, object_type: str, digest: str, *,
         tenant_id: str, approver: str, scope: str) -> ApprovalReceipt:
    now = datetime.now(UTC)
    return sign_receipt(ApprovalReceipt(
        1, f"synthetic-{gate.lower()}-general", "synthetic-issuer", approver, tenant_id,
        action, object_type, digest, scope, "synthetic-policy", "local",
        (now - timedelta(minutes=1)).isoformat(), (now + timedelta(minutes=10)).isoformat(),
        f"synthetic-nonce-{gate.lower()}-general-1"), APPROVAL_KEY)


def build_installation(package_path: Path, package: dict[str, str]) -> dict:
    """Test seam: the metadata ProjectTemplateInstaller would return for a published package."""
    manifest = load_document(package_path / "manifest.yaml")
    return {
        "schema_version": 1,
        "installation_id": "installed-general-thematic-map-1-0-0",
        "template_ref": {"kind": manifest["package"]["kind"], "id": manifest["package"]["id"],
                         "version": manifest["package"]["version"],
                         "digest": package["package_digest"]},
        "namespace": manifest["package"]["namespace"],
        "manifest_digest": package["manifest_digest"],
        "package_path": package_path.as_posix(),
        "contract_digest": sha256_digest({
            name: manifest["checksums"][relative]
            for name, relative in manifest["business_contracts"].items()}),
    }


class AdmissionTests(unittest.TestCase):
    """The registered profile states a purpose, and both overlays only ever narrow."""

    def setUp(self):
        self.registry = SchemaRegistry()
        self.scenarios = ScenarioRegistry(self.registry)
        self.profile = self.scenarios.for_template(deepcopy(TEMPLATE))

    def assert_schema_rejects(self, schema: str, document: dict) -> None:
        with self.assertRaises(ProtocolError):
            self.registry.validate(schema, document)

    def test_registered_capability_states_its_purpose_and_limits(self):
        definition = self.profile.definition
        self.assertEqual("general-thematic-mapping", definition["id"])
        self.assertEqual("general_thematic_mapping", definition["intent_constraints"]["business_scene"])
        self.assertEqual(["thematic-map"], definition["intent_constraints"]["allowed_tasks"])
        self.assertEqual("user-provided", definition["data_nature"])
        self.assertFalse(definition["production_enabled"])
        self.assertEqual(["user-declared-source-license"], definition["licenses"])
        self.assertEqual(NOTICE, self.profile.notice)
        self.assertEqual({"width_mm": 297, "height_mm": 210, "dpi": 300,
                          "width_px": 3508, "height_px": 2480}, definition["output_profile"])

    def test_component_allowlist_is_closed(self):
        from carto_core import scenario_registry
        entry = scenario_registry._COMPONENTS["general-thematic-raster"]
        self.assertEqual({"data_preparer", "planner", "candidate_compiler", "legend_checker",
                          "source_contract", "author", "validation_data_checker", "validation_scene"},
                         set(entry))
        self.assertEqual({".scenarios.general_thematic"}, {module for module, _ in entry.values()})
        with self.assertRaisesRegex(ProtocolError, "CAPABILITY_NOT_AVAILABLE"):
            self.profile.component("renderer")
        with patch("carto_core.scenario_registry.import_module") as importer:
            with self.assertRaises(ProtocolError):
                ScenarioCapability({"implementation": "unregistered-module"}).component("author")
            importer.assert_not_called()

    def test_generate_overlay_only_narrows_the_registered_shape(self):
        base = deepcopy(VALID_CASES["general-thematic-generate-request"])
        self.registry.validate("general-thematic-generate-request", base)
        mutations = [
            ("template", {**TEMPLATE, "id": "test-scenario"}),
            ("intent", {**base["intent"], "business_scene": "government_thematic"}),
            ("intent", {**base["intent"], "tasks": ["indicator-map"]}),
            ("goal", "编" * 61),
            ("requested_outputs", ["pdf"]),
            ("font", {"path": "fonts/font.otf", "family": "x", "version": "1.0.0"}),
            ("unexpected", True),
        ]
        for key, value in mutations:
            with self.subTest(key=key, value=value):
                case = deepcopy(base)
                case[key] = value
                self.assert_schema_rejects("general-thematic-generate-request", case)
        for path, value in [("data_nature", "synthetic"), ("role", "other-role")]:
            with self.subTest(path=path):
                case = deepcopy(base)
                case["source_bindings"][0][path] = value
                self.assert_schema_rejects("general-thematic-generate-request", case)
        case = deepcopy(base)
        case["prepared_raster_bindings"][0]["role"] = "other-role"
        self.assert_schema_rejects("general-thematic-generate-request", case)

    def test_create_overlay_only_narrows_the_registered_shape(self):
        base = deepcopy(VALID_CASES["general-thematic-template-create-request"])
        self.registry.validate("general-thematic-template-create-request", base)
        mutations = [
            ("profile", "test-profile"),
            ("version", "2.0.0"),
            ("targets", ["svg", "pdf", "png"]),
            ("data_nature", "observed"),
            ("contains_production_data", True),
            ("contains_sensitive_coordinates", True),
            ("role_bindings", {"area_source": "area-source"}),
            ("unexpected", True),
        ]
        for key, value in mutations:
            with self.subTest(key=key, value=value):
                case = deepcopy(base)
                case[key] = value
                self.assert_schema_rejects("general-thematic-template-create-request", case)

    def test_intent_resolution_binds_only_the_registered_purpose(self):
        request = deepcopy(VALID_CASES["general-thematic-generate-request"])
        profile, intent = self.scenarios.resolve_generate(request)
        self.assertEqual(self.profile.ref, profile.ref)
        self.assertEqual("general_thematic_mapping", intent["business_scene"])
        self.assertEqual(["land-cover"], intent["theme_tags"])
        self.assertEqual(["thematic-map"], intent["tasks"])
        self.assertEqual("ready", intent["readiness_status"])
        self.assertEqual(3, len(intent["evidence_refs"]))
        self.assertEqual("intent-input", intent["evidence_refs"][1]["id"])
        self.assertEqual(profile.ref, intent["evidence_refs"][2])
        # A goal without the purpose term still resolves from the explicit selection.
        plain = deepcopy(request)
        plain["goal"] = "输出土地覆盖分类栅格的图面"
        self.assertEqual(intent["business_scene"],
                         self.scenarios.resolve_generate(plain)[1]["business_scene"])
        # Fields outside the registered required information are refused.
        wrong = deepcopy(request)
        wrong["intent"]["fields"]["time"] = "2026"
        with self.assertRaisesRegex(ProtocolError, "INTENT_FIELD_UNKNOWN"):
            self.scenarios.resolve_generate(wrong)
        # A registered-but-unsupported action never resolves.
        action = deepcopy(request)
        action["intent"]["requested_actions"] = ["alter-frozen-classification"]
        with self.assertRaisesRegex(ProtocolError, "INTENT_NOT_RESOLVED"):
            self.scenarios.resolve_generate(action)
        # A topic outside the catalog never resolves, ...
        topic = deepcopy(request)
        topic["intent"]["theme_tags"] = ["unit-theme"]
        with self.assertRaisesRegex(ProtocolError, "INTENT_NOT_RESOLVED"):
            self.scenarios.resolve_generate(topic)
        # ... and semantics outside the profile never bind even when structurally valid.
        for scene, tasks, tags in [("general_thematic_mapping", ["indicator-map"], ["land-cover"]),
                                   ("general_thematic_mapping", ["thematic-map"], ["unit-theme"]),
                                   ("government_thematic", ["thematic-map"], ["land-cover"])]:
            with self.subTest(scene=scene, tasks=tasks, tags=tags):
                with self.assertRaisesRegex(ProtocolError, "SCENARIO_INTENT_MISMATCH"):
                    self.profile.require_semantics(scene, tasks, tags)


class CreateLineTests(unittest.TestCase):
    """analyze -> brief -> T1 -> author -> validate with the real workflow objects."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name).resolve()
        self.registry = SchemaRegistry()
        (self.root / "sources").mkdir()
        self.csv_path = self.root / "sources/legend-sample.csv"
        self.csv_path.write_bytes(LEGEND_CSV.encode("utf-8"))
        manifest = {
            "schema_version": 1,
            "manifest_id": "general-sources",
            "sources": [{
                "source_id": "legend-sample", "kind": "csv",
                "location_ref": "sources/legend-sample.csv",
                "digest": file_digest(self.csv_path),
                "provenance": {"source_type": "user", "source_ref": "user-upload:legend-sample",
                               "version": "1", "retrieved_at": "2026-11-01T00:00:00Z",
                               "classification": "internal"},
                "license": "project-approved", "captured_at": "2026-11-01T00:00:00Z",
                "data_profile": {"data_nature": "user-provided", "contains_production_data": False,
                                 "contains_sensitive_coordinates": False,
                                 "source_crs": deepcopy(CRS_4326)},
            }],
        }
        atomic_yaml(self.root / "source-manifest.yaml", manifest)
        self.request = deepcopy(VALID_CASES["general-thematic-template-create-request"])
        self.request_path = self.root / "create-request.json"
        self.request_path.write_text(json.dumps(self.request, ensure_ascii=False), encoding="utf-8")
        self.workflow = TemplateCreationWorkflow(allowed_roots=[self.root], project_root=self.root,
                                                 workdir=self.root / "work", registry=self.registry)
        self.author_kwargs = dict(approval_key=APPROVAL_KEY, nonce_db=self.root / "nonces.sqlite",
                                  policy_id="synthetic-policy", issuer="synthetic-issuer")

    def t1(self, digest: str) -> ApprovalReceipt:
        return sign("T1", "approve-template-brief", "template-brief", digest,
                    tenant_id="tenant-one", approver="reviewer-one", scope="project:project-one")

    def run_to_brief(self):
        analyzed = self.workflow.analyze(self.request_path)
        briefed = self.workflow.brief(self.request_path)
        return analyzed, briefed

    def test_analyze_and_brief_use_the_registered_source_contract(self):
        analyzed, briefed = self.run_to_brief()
        summaries = analyzed["analysis"]["source_summaries"]
        self.assertEqual([{"source_id": "legend-sample", "kind": "csv",
                           "digest": file_digest(self.csv_path), "license": "project-approved",
                           "data_nature": "user-provided", "record_count": 3,
                           "field_names": ["category_label", "category_value"],
                           "geometry_types": ["none"]}], summaries)
        evidence = analyzed["analysis"]["evidence_records"]
        self.assertGreaterEqual(len(evidence), 4)
        suggestion = next(item for item in evidence if item["value_origin"] == "system_suggestion")
        self.assertEqual(["raster/categorical@1.0.0"], suggestion["value"])
        self.assertTrue(suggestion["rationale"])
        self.assertEqual([{"role_id": "classified-surface", "source_id": "legend-sample",
                           "geometry_types": ["none"], "value_field": "category_value",
                           "semantic_role": "category-value"}], briefed["brief"]["data_roles"])
        self.assertEqual(sha256_digest(briefed["brief"]), briefed["approval"]["object_digest"])
        self.assertEqual(("waiting_approval", "author"),
                         (briefed["state"]["status"], briefed["state"]["step"]))

    def test_author_requires_a_valid_t1_and_validate_fails_closed_on_fixture_render(self):
        _, briefed = self.run_to_brief()
        with self.assertRaisesRegex(ProtocolError, "BRIEF_NOT_CONFIRMED"):
            self.workflow.author(self.request_path, None, **self.author_kwargs)
        approval_path = self.root / "t1.yaml"
        atomic_yaml(approval_path, asdict(self.t1("sha256:" + "0" * 64)), create_once=False)
        with self.assertRaises(SecurityError):
            self.workflow.author(self.request_path, approval_path, **self.author_kwargs)
        atomic_yaml(approval_path, asdict(self.t1(sha256_digest(briefed["brief"]))), create_once=False)
        authored = self.workflow.author(self.request_path, approval_path, **self.author_kwargs)
        self.assertEqual(("pending", "validate"),
                         (authored["state"]["status"], authored["state"]["step"]))
        self.assertTrue((self.root / "work/staging/package/contracts/scenario.yaml").is_file())
        validated = self.workflow.validate(self.request_path, attestation_key=os.urandom(32))
        evidence = validated["evidence"]
        self.assertEqual("failed", evidence["status"])
        by_id = {item["check_id"]: item for item in evidence["results"]}
        for check in ("template.package-closed", "template.schema-valid", "template.dependencies-pinned",
                      "template.kind-ownership", "template.semantic-contracts", "template.target-capability"):
            self.assertEqual("passed", by_id[check]["status"], by_id[check].get("details"))
        blocked = by_id["template.fixture-render"]
        self.assertEqual("failed", blocked["status"])
        self.assertIn(blocked["details"]["code"], FIXTURE_RENDER_BLOCKED)
        self.assertEqual("failed", validated["state"]["status"])
        with self.assertRaisesRegex(ProtocolError, "WORKFLOW_STEP_MISMATCH"):
            self.workflow.publish(self.request_path, None, repository_root=self.root / "repo",
                                  repository_scope="local:templates", idempotency_key="publish-1",
                                  approval_key=APPROVAL_KEY, renderer_attestation_key=KEY,
                                  nonce_db=self.root / "nonces.sqlite",
                                  policy_id="synthetic-policy", issuer="synthetic-issuer")

    def test_author_rejects_foreign_requests_and_crs_drift(self):
        guard = PathGuard([self.root])
        work = self.root / "component-work"
        work.mkdir()
        author = GeneralThematicAuthor(guard, work, self.registry)
        foreign = deepcopy(VALID_CASES["template-create-request"])
        with self.assertRaisesRegex(ProtocolError, "CAPABILITY_NOT_AVAILABLE"):
            author.author(foreign, BRIEF_STUB)
        with self.assertRaisesRegex(ProtocolError, "TEMPLATE_BRIEF_MISMATCH"):
            author.author(self.request, dict(BRIEF_STUB, version="2.0.0"))
        for mutation, code in [({"targets": ["svg", "pdf", "png"]}, "RENDER_TARGET_UNSUPPORTED"),
                               ({"display_crs": {"authority": "EPSG", "code": "3857"}}, "SOURCE_CRS_UNSUPPORTED")]:
            request = deepcopy(self.request)
            request.update(mutation)
            with self.assertRaisesRegex(ProtocolError, code):
                author.author(request, BRIEF_STUB)

    def test_validation_components_fail_closed(self):
        guard = PathGuard([self.root])
        work = self.root / "checker-work"
        work.mkdir()
        author = GeneralThematicAuthor(guard, work, self.registry)
        package = author.author(self.request, BRIEF_STUB)
        self.assertEqual(package, author.verify_existing(self.request, BRIEF_STUB))
        package_root = Path(package["package_path"])
        snapshot = {"manifest": load_document(package_root / "manifest.yaml"),
                    "fixture_paths": ["fixtures/validation-input.csv"]}
        expected = {"namespace": "local", "kind": "map-scenario", "id": "general-thematic-map",
                    "version": "1.0.0", "source_crs": deepcopy(CRS_4326),
                    "display_crs": deepcopy(CRS_4326)}
        validation_data_checker(package_root, snapshot, expected)
        with self.assertRaisesRegex(ProtocolError, "TEMPLATE_IDENTITY_MISMATCH"):
            validation_data_checker(package_root, snapshot, dict(expected, id="other-template"))
        with self.assertRaisesRegex(ProtocolError, "SOURCE_CRS_UNSUPPORTED"):
            validation_data_checker(package_root, snapshot,
                                    dict(expected, display_crs={"authority": "EPSG", "code": "3857"}))
        with self.assertRaisesRegex(ProtocolError, "FIXTURE_SET_INVALID"):
            validation_data_checker(package_root, dict(snapshot, fixture_paths=[]), expected)
        fixture = package_root / "fixtures/validation-input.csv"
        original = fixture.read_bytes()
        bad_cases = [
            (b"category_value,category_label\n1,A\n1,B\n", "CLASSIFICATION_CODE_DUPLICATE"),
            (b"category_value,category_label\n1.5,A\n", "CLASSIFICATION_CODE_INVALID"),
            (b"category_value,category_label\n1,\n", "CLASSIFICATION_LABEL_INVALID"),
            (b"category_value,label\n1,A\n", "CSV_HEADER_INVALID"),
            (b"category_value,category_label\n", "CLASSIFICATION_CSV_EMPTY"),
        ]
        try:
            for content, code in bad_cases:
                fixture.write_bytes(content)
                with self.subTest(code=code), self.assertRaisesRegex(ProtocolError, code):
                    validation_data_checker(package_root, snapshot, expected)
        finally:
            fixture.write_bytes(original)
        with self.assertRaisesRegex(ProtocolError, "RASTER_FIXTURE_RENDER_UNREGISTERED"):
            validation_scene(package_root, snapshot, ["pdf", "png"], Path("unused.ttf"), "1.2.0")

    def test_source_contract_admission_is_bounded(self):
        request = deepcopy(self.request)
        source = {"source_id": "legend-sample", "kind": "csv", "license": "project-approved",
                  "data_profile": {"data_nature": "user-provided", "contains_production_data": False,
                                   "contains_sensitive_coordinates": False,
                                   "source_crs": deepcopy(CRS_4326)}}
        SOURCE_CONTRACT.validate_source_profile(source, request)
        variants = [
            (dict(source, kind="geojson"), ProtocolError, "SOURCE_TYPE_UNSUPPORTED"),
            (dict(source, license="restricted"), SecurityError, "SOURCE_LICENSE_RESTRICTED"),
            (dict(source, data_profile=dict(source["data_profile"], data_nature="observed")),
             ProtocolError, "SOURCE_DATA_NATURE_MISMATCH"),
            (dict(source, data_profile=dict(source["data_profile"], contains_production_data=True)),
             ProtocolError, "SOURCE_PRODUCTION_FLAG_MISMATCH"),
            (dict(source, data_profile=dict(source["data_profile"], contains_sensitive_coordinates=True)),
             SecurityError, "SOURCE_SENSITIVE_COORDINATES_FORBIDDEN"),
            (dict(source, data_profile=dict(source["data_profile"],
                                            source_crs={"authority": "EPSG", "code": "3857"})),
             ProtocolError, "SOURCE_CRS_UNSUPPORTED"),
        ]
        for variant, error, code in variants:
            with self.subTest(code=code), self.assertRaisesRegex(error, code):
                SOURCE_CONTRACT.validate_source_profile(variant, request)
        summary = {"source_id": "legend-sample", "kind": "csv",
                   "field_names": ["category_label", "category_value"]}
        SOURCE_CONTRACT.validate_role_bindings(request, [summary])
        with self.assertRaisesRegex(ProtocolError, "ROLE_BINDING_FIELD_MISSING"):
            SOURCE_CONTRACT.validate_role_bindings(request, [dict(summary, field_names=["value"])])
        with self.assertRaisesRegex(ProtocolError, "ROLE_BINDING_SOURCE_MISMATCH"):
            SOURCE_CONTRACT.validate_role_bindings(request, [dict(summary, source_id="other")])
        extra = deepcopy(request)
        extra["role_bindings"]["area_source"] = "areas"
        with self.assertRaisesRegex(ProtocolError, "ROLE_BINDING_UNSUPPORTED"):
            SOURCE_CONTRACT.validate_role_bindings(extra, [summary])


class GenerationTests(PreparationFixture, unittest.TestCase):
    """Component chain plus the real generate-map workflow up to atomic delivery."""

    def setUp(self):
        super().setUp()
        try:
            from carto_core.adapters.raster_renderer import _dependencies
            self.np, self.rio, _, _, _, _, _ = _dependencies()
            import fontTools  # noqa: F401
        except (CartoError, ImportError) as exc:
            self.skipTest(str(exc))
        font_source = find_cjk_font(SCENE_TEXT)
        if font_source is None:
            self.skipTest("No embeddable single-face CJK TTF is available on this machine")
        self.addCleanup(release_test_font_handles)
        (self.root / "fonts").mkdir()
        self.font_path = self.root / "fonts/selected-cjk.ttf"
        self.font_path.write_bytes(font_source.read_bytes())
        raster_helpers.RasterRendererTests.set_raster(
            self, self.np.array([[1, 0, 255], [255, 1, 0]], dtype="uint8"))
        # The registered scenario admits user-provided data only; the synthetic fixture
        # raster stands in for it, and the preparation chain records the declared nature.
        self.request["source"]["data_nature"] = "user-provided"
        self.prepared = self.ready()
        self.registry = SchemaRegistry()
        self.scenarios = ScenarioRegistry(self.registry)
        self.guard = self.service.project_guard
        self.work = self.root / "work"
        self.work.mkdir()
        create = deepcopy(VALID_CASES["general-thematic-template-create-request"])
        create["source_crs"] = deepcopy(CRS_26911)
        create["display_crs"] = deepcopy(CRS_26911)
        template_work = self.root / "template-work"
        template_work.mkdir()
        author = GeneralThematicAuthor(self.guard, template_work, self.registry)
        package = author.author(create, BRIEF_STUB)
        self.assertEqual(package, author.verify_existing(create, BRIEF_STUB))
        self.installation = build_installation(Path(package["package_path"]), package)
        self.contracts = MapCandidateCompiler(self.guard, self.registry).load_contracts(self.installation)
        self.generate = self.build_request()
        self.intent = self.scenarios.generate_intent(self.generate)

    def build_request(self) -> dict:
        request = deepcopy(VALID_CASES["general-thematic-generate-request"])
        request.update({
            "request_id": "general-generate-request",
            "project_id": self.context.project_id,
            "run_id": self.context.run_id,
            "goal": GOAL,
            "subject": {"tenant_id": self.context.tenant_id, "subject_id": self.context.subject_id,
                        "approver_subject_id": "synthetic-reviewer",
                        "namespace": self.context.project_id},
            "scope": f"project:{self.context.project_id}",
            "environment": "local",
            "template": {**TEMPLATE, "digest": self.installation["template_ref"]["digest"]},
            "sources": [deepcopy(self.request["source"]["source_ref"])],
            "source_bindings": [deepcopy(self.request["source"])],
            "prepared_raster_bindings": [{"role": self.request["source"]["role"],
                                          "prepared_ref": self.prepared.ref()}],
            "requested_at": utc_now(),
            "audience": "synthetic test only",
            "idempotency_key": "general-generate-00001",
            "font": {"path": "fonts/selected-cjk.ttf", "family": "Synthetic CJK", "version": "1.0.0"},
        })
        self.registry.validate("general-thematic-generate-request", request)
        return request

    def component_bundle(self) -> dict:
        preparer = GeneralThematicDataPreparer(self.guard, self.root, self.work / "data", self.registry)
        return preparer.prepare(self.generate, artifact_ref("generate-request", self.generate))["bundle"]

    def compile_via_components(self, *, bundle=None, contracts=None, compiler_kwargs=None):
        contracts = self.contracts if contracts is None else contracts
        bundle = self.component_bundle() if bundle is None else bundle
        plan = GeneralThematicPlanner(self.registry).build(
            self.generate, self.intent, {"synthetic": "brief"}, bundle,
            self.installation, contracts)
        kwargs = {"project_root": self.root, "context": ExecutionContext.from_generate_request(self.generate)}
        kwargs.update(compiler_kwargs or {})
        compiler = MapCandidateCompiler(self.guard, self.registry, **kwargs)
        return compiler.compile(self.generate, self.intent, plan, bundle, self.installation,
                                contracts, self.font_path)

    def test_data_preparer_binds_the_exact_request_and_evidence(self):
        preparer = GeneralThematicDataPreparer(self.guard, self.root, self.work / "data", self.registry)
        request_ref = artifact_ref("generate-request", self.generate)
        prepared = preparer.prepare(self.generate, request_ref)
        self.assertEqual(request_ref, prepared["request_ref"])
        bundle = RasterBundlePreparer(self.service).prepare_request(self.generate, self.context)["bundle"]
        self.assertEqual(bundle, prepared["bundle"])
        self.assertEqual("user-provided", prepared["bundle"]["summary"]["data_nature"])
        drifted = dict(request_ref, digest="sha256:" + "0" * 64)
        with self.assertRaisesRegex(ProtocolError, "RASTER_REQUEST_REF_MISMATCH"):
            preparer.prepare(self.generate, drifted)

    def test_planner_emits_a_valid_unique_value_raster_plan(self):
        bundle = self.component_bundle()
        plan = GeneralThematicPlanner(self.registry).build(
            self.generate, self.intent, {"synthetic": "brief"}, bundle,
            self.installation, self.contracts)
        self.registry.validate("map-plan", plan)
        self.assertEqual({"classification": "unique-values", "class_count": 12,
                          "extent": bundle["summary"]["combined_bbox"], "title": GOAL,
                          "legend_source": "actual-encoding", "renderer_id": RASTER_RENDERER_ID},
                         plan["decisions"])
        self.assertEqual(sha256_digest(self.intent), plan["intent_ref"]["digest"])
        with self.assertRaisesRegex(ProtocolError, "RASTER_BUNDLE_UNSUPPORTED"):
            GeneralThematicPlanner(self.registry).build(
                self.generate, self.intent, {}, dict(bundle, role_bindings=[]),
                self.installation, self.contracts)

    def test_candidate_compiler_freezes_a_deterministic_raster_execution(self):
        first = self.compile_via_components()
        second = self.compile_via_components()
        self.assertEqual(first["candidate"], second["candidate"])
        self.assertEqual(first["scene"], second["scene"])
        self.assertEqual(first["preflight"], second["preflight"])
        candidate, scene = first["candidate"], first["scene"]
        self.registry.validate("resolved-map", candidate)
        self.registry.validate("render-scene", scene)
        self.assertEqual("passed", first["preflight"]["status"])
        self.assertEqual(self.generate["requested_at"], candidate["created_at"])
        self.assertEqual(RASTER_RENDERER_ID, scene["renderer_id"])
        self.assertEqual({"width_px": 3508, "height_px": 2480, "device_pixel_ratio": 1},
                         scene["viewport"])
        self.assertEqual({"targets": ["pdf", "png"], "dpi": 300}, scene["export"])
        execution = candidate["execution"]
        self.assertEqual("general_thematic_mapping", execution["business_scene"])
        self.assertEqual(["thematic-map"], execution["map_tasks"])
        self.assertEqual(["land-cover"], execution["shared_semantics"]["theme_tags"])
        self.assertEqual("user-provided", execution["shared_semantics"]["data_nature"])
        self.assertEqual(CRS_26911, execution["targets"]["pdf"]["display_crs"])
        self.assertNotIn("camera", execution)
        self.assertNotIn("overlay_coordinate_policy", execution)
        # The frozen execution is admitted by the real registry and re-verified end to end.
        profile = self.scenarios.for_execution(execution)
        self.assertEqual(self.scenarios.for_template(deepcopy(TEMPLATE)).ref, profile.ref)
        profile.require_scene(scene)
        MapCandidateCompiler.require_execution_intent(execution, self.intent)
        RasterSceneCompiler(self.service).validate_generation(
            scene, execution, self.generate, self.context)

    def test_candidate_compiler_rejects_context_drift_and_input_tampering(self):
        with self.assertRaisesRegex(SecurityError, "RASTER_EXECUTION_CONTEXT_REQUIRED"):
            self.compile_via_components(compiler_kwargs={"project_root": None})
        with self.assertRaisesRegex(SecurityError, "RASTER_EXECUTION_CONTEXT_REQUIRED"):
            self.compile_via_components(compiler_kwargs={"context": None})
        drifted = replace(ExecutionContext.from_generate_request(self.generate), run_id="other-run")
        with self.assertRaisesRegex(SecurityError, "CLASSIFICATION_SCOPE_MISMATCH"):
            self.compile_via_components(compiler_kwargs={"context": drifted})
        bundle = self.component_bundle()
        tampered = deepcopy(bundle)
        tampered["role_bindings"][0]["width"] += 1
        with self.assertRaisesRegex(ProtocolError, "RASTER_CANDIDATE_BUNDLE_MISMATCH"):
            self.compile_via_components(bundle=tampered)

    def test_candidate_compiler_rejects_display_crs_drift(self):
        create = deepcopy(VALID_CASES["general-thematic-template-create-request"])
        work = self.root / "template-work-4326"
        work.mkdir()
        author = GeneralThematicAuthor(self.guard, work, self.registry)
        package = author.author(create, BRIEF_STUB)
        installation = build_installation(Path(package["package_path"]), package)
        contracts = MapCandidateCompiler(self.guard, self.registry).load_contracts(installation)
        with self.assertRaisesRegex(ProtocolError, "RASTER_DISPLAY_CRS_MISMATCH"):
            self.compile_via_components(contracts=contracts)

    def test_legend_checker_requires_an_unambiguous_ordered_legend(self):
        def context(items):
            return {"raster": {"portrayal": {"legend_items": items}}}
        good = [{"value": 1, "label": "Category A", "color": "#FF0000", "order": 1},
                {"value": 255, "label": "Category B", "color": "#0000FF", "order": 3}]
        passed, details, disposition = legend_checker(context(good))
        self.assertTrue(passed)
        self.assertIsNone(disposition)
        self.assertEqual(2, details["legend_item_count"])
        broken = {
            "empty-legend": [],
            "missing-label": [dict(good[0], label="  "), good[1]],
            "duplicate-label": [good[0], dict(good[1], label="Category A")],
            "duplicate-color": [good[0], dict(good[1], color="#FF0000")],
            "order-invalid": [good[1], good[0]],
        }
        for problem, items in broken.items():
            with self.subTest(problem=problem):
                passed, details, _ = legend_checker(context(items))
                self.assertFalse(passed)
                self.assertIn(problem, details["problems"])
        with self.assertRaisesRegex(ProtocolError, "RASTER_EXECUTION_CONTEXT_REQUIRED"):
            legend_checker({"raster": {}})

    def workflow_at_compile(self):
        request_path = self.root / "generate-request.yaml"
        atomic_yaml(request_path, self.generate)
        repository_root = self.root / "template-repo"
        repository_root.mkdir()
        workflow = MapGenerationWorkflow(allowed_roots=[self.root], project_root=self.root,
                                         workdir=self.work, registry=self.registry,
                                         repository_root=repository_root,
                                         repository_scope="local:templates")
        # Only seams: the package is authored but NOT published (the fixture-render branch
        # fails closed), so repository discovery/installation is stubbed with the exact
        # authored package metadata, and browser discovery must never be reached by the
        # raster backend. Everything else — intent resolution, G1/G2/G3 receipt validation,
        # contracts, compilation, rendering, checks, delivery — stays real.
        seams = [patch.object(workflow, "_verify_installed_template"),
                 patch.object(ProjectTemplateInstaller, "install",
                              return_value=deepcopy(self.installation)),
                 patch("carto_core.adapters.render_backend.discover_browser",
                       side_effect=AssertionError("No browser for the raster line"))]
        for seam in seams:
            seam.start()
            self.addCleanup(seam.stop)
        intake = workflow.intake(request_path)
        self.assertEqual(self.intent, intake["intent"])
        briefed = workflow.brief(request_path)
        self.assertEqual("compile", briefed["state"]["step"])
        self.assertEqual(GOAL, briefed["brief"]["purpose"])
        atomic_yaml(self.root / "workflow-g1.yaml", asdict(sign(
            "G1", "approve-map-brief", "map-brief", briefed["approval_object_digest"],
            tenant_id=self.context.tenant_id, approver="synthetic-reviewer",
            scope=self.generate["scope"])))
        return workflow, request_path

    def test_failed_candidate_quality_does_not_advance_to_preview(self):
        workflow, request_path = self.workflow_at_compile()
        # Inject one negative checker result, not a fabricated passing report;
        # the real compile/preflight/state machinery must preserve the failure.
        with patch.object(MapQualityChecks, "_classification", return_value=(False, {"synthetic_failure": True})):
            with self.assertRaisesRegex(ProtocolError, "CANDIDATE_QUALITY_FAILED"):
                workflow.compile(request_path, self.root / "workflow-g1.yaml",
                    approval_key=APPROVAL_KEY, nonce_db=self.root / "workflow-nonces.sqlite",
                    policy_id="synthetic-policy", issuer="synthetic-issuer")
        state = workflow.state_store.load()
        self.assertEqual(("failed", "compile"), (state.status, state.step))
        report = load_document(self.work / "candidates/preflight-report.yaml")
        self.assertEqual("failed", report["status"])
        receipt = load_document(self.work / state.last_receipt)
        self.assertEqual("CANDIDATE_QUALITY_FAILED", receipt["error"]["code"])
        self.assertTrue(any(ref["id"] == "preflight-report" for ref in receipt["output_refs"]))
        with self.assertRaises(CartoError):
            workflow.preview(request_path, attestation_key=KEY)
        self.assertFalse((self.work / "candidates/render-receipt.yaml").exists())

    def test_full_workflow_preview_g2_render_check_g3_delivery(self):
        workflow, request_path = self.workflow_at_compile()
        compiled = workflow.compile(request_path, self.root / "workflow-g1.yaml",
                                    approval_key=APPROVAL_KEY,
                                    nonce_db=self.root / "workflow-nonces.sqlite",
                                    policy_id="synthetic-policy", issuer="synthetic-issuer")
        self.assertEqual("preview", compiled["state"]["step"])
        self.assertEqual(f"candidate-{self.context.run_id}", compiled["candidate"]["candidate_id"])
        plan = load_document(self.work / "plan/map-plan.yaml")
        self.assertEqual(RASTER_RENDERER_ID, plan["decisions"]["renderer_id"])
        bundle = load_document(self.work / "data/prepared-data-bundle.yaml")
        self.assertEqual("user-provided", bundle["summary"]["data_nature"])
        previewed = workflow.preview(request_path, attestation_key=KEY)
        self.assertEqual(("waiting_approval", "freeze"),
                         (previewed["state"]["status"], previewed["state"]["step"]))
        atomic_yaml(self.root / "workflow-g2.yaml", asdict(sign(
            "G2", "approve-freeze", "resolved-map", previewed["approval_object_digest"],
            tenant_id=self.context.tenant_id, approver="synthetic-reviewer",
            scope=self.generate["scope"])), create_once=False)
        frozen = workflow.freeze(request_path, self.root / "workflow-g2.yaml",
                                 approval_key=APPROVAL_KEY, attestation_key=KEY,
                                 nonce_db=self.root / "workflow-nonces.sqlite",
                                 policy_id="synthetic-policy", issuer="synthetic-issuer")
        self.assertEqual("render", frozen["state"]["step"])
        rendered = workflow.render(request_path, attestation_key=KEY)
        self.assertEqual("check", rendered["state"]["step"])
        checked = workflow.check(request_path, attestation_key=KEY,
                                 recipient_id="synthetic-recipient", recipient_type="project-user",
                                 destination="deliveries/general",
                                 idempotency_key="general-delivery-00000001")
        self.assertEqual("passed", checked["validation_report"]["status"])
        manifest = checked["delivery_manifest"]
        self.assertEqual(["user-declared-source-license"], manifest["licenses"])
        self.assertEqual([NOTICE], manifest["limitations"])
        self.assertEqual(sha256_digest(manifest), checked["g3"]["object_digest"])
        atomic_yaml(self.root / "workflow-g3.yaml", asdict(sign(
            "G3", "approve-delivery", "delivery-manifest", sha256_digest(manifest),
            tenant_id=self.context.tenant_id, approver="synthetic-reviewer",
            scope=self.generate["scope"])), create_once=False)
        deliver_kwargs = dict(approval_key=APPROVAL_KEY,
                              nonce_db=self.root / "workflow-nonces.sqlite",
                              policy_id="synthetic-policy", issuer="synthetic-issuer")
        delivered = workflow.deliver(request_path, self.root / "workflow-g3.yaml", **deliver_kwargs)
        self.assertEqual(("succeeded", "deliver"),
                         (delivered["state"]["status"], delivered["state"]["step"]))
        final = self.root / "deliveries/general"
        self.assertEqual({"map.pdf", "map.png", "README.md", "delivery-manifest.yaml",
                          "checksums.sha256"}, {item.name for item in final.iterdir()})
        readme = (final / "README.md").read_text(encoding="utf-8")
        self.assertIn(NOTICE, readme)
        self.assertNotIn("classified.tif", readme)
        replay = workflow.deliver(request_path, self.root / "workflow-g3.yaml", **deliver_kwargs)
        self.assertTrue(replay["idempotent_replay"])


if __name__ == "__main__":
    unittest.main()
