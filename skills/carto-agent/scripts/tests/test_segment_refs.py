"""S2 segment-reference admission chain tests.

Synthetic data, synthetic approval keys and TemporaryDirectory roots only. Covers:
repository resolution (fetch/resolve + tamper fail-closed), author declaration,
create-request protocol samples, and the real author -> validate -> publish line
with a referenced layout segment, plus generate-side load_contracts resolution.
"""
from __future__ import annotations

from copy import deepcopy
from dataclasses import asdict
import json
from pathlib import Path
import sys
import tempfile
import unittest

SCRIPTS_ROOT = Path(__file__).resolve().parents[1]
if str(SCRIPTS_ROOT) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_ROOT))

from carto_core.artifacts import atomic_yaml, file_digest
from carto_core.canonical import sha256_digest
from carto_core.compiler.map_candidate import MapCandidateCompiler
from carto_core.compiler.ownership import OwnershipResolver
from carto_core.errors import CartoError, ProtocolError
from carto_core.repository.template_installer import ProjectTemplateInstaller
from carto_core.repository.template_repository import TemplateRepository
from carto_core.scenarios.general_thematic.raster import GeneralThematicAuthor, layout_contract
from carto_core.schema_registry import SchemaRegistry, load_document
from carto_core.security.paths import PathGuard
from carto_core.workflow.template_workflow import TemplateCreationWorkflow
from tests.fixtures.schema_cases import D, REFERENCED_SCENARIO, SEGMENT_REF_LAYOUT, VALID_CASES
from tests.test_general_thematic import (
    APPROVAL_KEY, BRIEF_STUB, CRS_26911, KEY, LEGEND_CSV, VALIDATION_TEXT,
    find_cjk_font, sign,
)
from tests.helpers import release_test_font_handles

SEGMENT_ID = "general-layout-seg"


def referenced_create_request(segment_ref: dict) -> dict:
    request = deepcopy(VALID_CASES["general-template-create-request"])
    request["source_crs"] = deepcopy(CRS_26911)
    request["display_crs"] = deepcopy(CRS_26911)
    request["segment_refs"] = {"layout": deepcopy(segment_ref)}
    return request


class SegmentPackageFixture(unittest.TestCase):
    """Publishes one synthetic map-layout segment through the real publish path."""

    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.guard = PathGuard([self.root])
        self.repo_root = self.root / "repo"
        self.repository = TemplateRepository(path_guard=self.guard, root=self.repo_root,
                                             repository_scope="local:templates")
        self.registry = self.repository.registry

    def publish_layout_segment(self, contract: dict | None = None) -> dict:
        contract = layout_contract() if contract is None else contract
        staging = self.root / "segment-staging"
        (staging / "contracts").mkdir(parents=True)
        (staging / "contracts" / "layout.yaml").write_text(json.dumps(contract), encoding="utf-8")
        lock = deepcopy(VALID_CASES["dependency-lock"])
        lock["package"] = {"namespace": "local", "kind": "map-layout", "id": SEGMENT_ID,
                           "version": "1.0.0", "digest": D}
        lock["dependencies"] = []
        (staging / "dependencies.lock.yaml").write_text(json.dumps(lock), encoding="utf-8")
        files = ["dependencies.lock.yaml", "contracts/layout.yaml"]
        manifest = {
            "schema_version": 1,
            "package": {"namespace": "local", "kind": "map-layout", "id": SEGMENT_ID,
                        "version": "1.0.0", "status": "published", "summary": "Synthetic S2 layout segment"},
            "dependency_lock": "dependencies.lock.yaml",
            "files": files,
            "checksums": {relative: file_digest(staging / relative) for relative in files},
        }
        (staging / "manifest.yaml").write_text(json.dumps(manifest), encoding="utf-8")
        manifest_digest = file_digest(staging / "manifest.yaml")
        lines = [f"{manifest['checksums'][relative][7:]}  {relative}" for relative in files]
        lines.append(f"{manifest_digest[7:]}  manifest.yaml")
        (staging / "checksums.sha256").write_text("\n".join(sorted(lines)) + "\n", encoding="utf-8")
        snapshot = {"package_digest": file_digest(staging / "checksums.sha256"),
                    "manifest_digest": manifest_digest, "manifest": manifest,
                    "dependency_lock_digest": file_digest(staging / "dependencies.lock.yaml")}
        publication = self.repository.publish(
            package_root=staging, snapshot=snapshot, evidence={"evidence_digest": D},
            approval={"synthetic": "s2-segment-test"}, idempotency_key="s2-segment-layout-0001",
            publication_object={"schema_version": 1, "run_id": "s2-segment-run", "request_digest": D,
                                "package_ref": {"kind": "map-layout", "id": SEGMENT_ID, "version": "1.0.0",
                                                "digest": snapshot["package_digest"]},
                                "evidence_ref": {"id": "template-validation-evidence", "version": "1.0.0",
                                                 "digest": D, "uri": "evidence.yaml"},
                                "repository_scope": "local:templates",
                                "repository_root": self.repo_root.as_posix(),
                                "idempotency_key": "s2-segment-layout-0001"})
        return {"kind": "map-layout", "id": SEGMENT_ID, "version": "1.0.0",
                "digest": publication["package_ref"]["digest"]}

    def segment_contract_path(self) -> Path:
        return self.repo_root / "packages/local/map-layout" / SEGMENT_ID / "1.0.0/contracts/layout.yaml"


class SegmentResolutionTests(SegmentPackageFixture):
    def test_fetch_returns_the_exact_published_contract(self) -> None:
        ref = self.publish_layout_segment()
        contract = self.repository.fetch_segment(ref, namespace="local")
        self.assertEqual(contract, layout_contract())

    def test_fetch_fails_closed_on_digest_mismatch_missing_contract_and_corruption(self) -> None:
        ref = self.publish_layout_segment()
        drifted = {**ref, "digest": "sha256:" + "1" * 64}
        with self.assertRaises(ProtocolError) as caught:
            self.repository.fetch_segment(drifted, namespace="local")
        self.assertEqual(caught.exception.code, "SEGMENT_DIGEST_MISMATCH")
        with self.assertRaises(ProtocolError) as caught:
            self.repository.fetch_segment({**ref, "kind": "map-scenario"}, namespace="local")
        self.assertEqual(caught.exception.code, "SEGMENT_KIND_UNSUPPORTED")
        self.segment_contract_path().write_text(
            json.dumps({**layout_contract(), "category": "poster"}), encoding="utf-8")
        with self.assertRaises(ProtocolError) as caught:
            self.repository.fetch_segment(ref, namespace="local")
        self.assertEqual(caught.exception.code, "PUBLISHED_PACKAGE_CORRUPT")

    def test_resolve_materializes_referenced_segments_and_keeps_provenance(self) -> None:
        ref = self.publish_layout_segment()
        scenario = deepcopy(REFERENCED_SCENARIO)
        scenario["segment_refs"]["layout"] = deepcopy(ref)
        lock = deepcopy(VALID_CASES["dependency-lock"])
        lock["dependencies"] = [deepcopy(ref)]
        resolved = self.repository.resolve_scenario_segments(scenario, namespace="local", lock=lock)
        self.assertEqual(resolved["embedded"]["layout"], layout_contract())
        self.assertEqual(resolved["segment_refs"], {"layout": ref})
        self.assertEqual(resolved["embedded"]["style"], scenario["embedded"]["style"])
        # The source scenario is never mutated.
        self.assertNotIn("layout", scenario["embedded"])

    def test_resolve_rejects_lock_drift_and_legacy_passes_through(self) -> None:
        ref = self.publish_layout_segment()
        scenario = deepcopy(REFERENCED_SCENARIO)
        scenario["segment_refs"]["layout"] = deepcopy(ref)
        with self.assertRaises(ProtocolError) as caught:
            self.repository.resolve_scenario_segments(
                scenario, namespace="local", lock=VALID_CASES["dependency-lock"])
        self.assertEqual(caught.exception.code, "SEGMENT_LOCK_MISMATCH")
        legacy = self.repository.resolve_scenario_segments(
            VALID_CASES["scenario"], namespace="local", lock=VALID_CASES["dependency-lock"])
        self.assertEqual(legacy, VALID_CASES["scenario"])


class ReferencedAuthoringTests(SegmentPackageFixture):
    def author_package(self, request: dict, work: Path) -> dict:
        work.mkdir(parents=True, exist_ok=True)
        author = GeneralThematicAuthor(self.guard, work, self.registry)
        package = author.author(request, BRIEF_STUB)
        self.assertEqual(package, author.verify_existing(request, BRIEF_STUB))
        return package

    def test_author_declares_refs_pins_dependencies_and_marks_replaceable(self) -> None:
        ref = self.publish_layout_segment()
        request = referenced_create_request(ref)
        self.registry.validate("general-template-create-request", request)
        package = self.author_package(request, self.root / "work-referenced")
        root = Path(package["package_path"])
        scenario = load_document(root / "contracts/scenario.yaml")
        self.assertNotIn("layout", scenario["embedded"])
        self.assertEqual(scenario["segment_refs"], {"layout": ref})
        self.assertEqual(scenario["replaceable_segments"], ["layout"])
        manifest = load_document(root / "manifest.yaml")
        lock = load_document(root / "dependencies.lock.yaml")
        self.assertEqual(manifest["dependencies"], [ref])
        self.assertEqual(lock["dependencies"], [ref])

    def test_legacy_author_output_is_unchanged_without_refs(self) -> None:
        request = deepcopy(VALID_CASES["general-template-create-request"])
        request["source_crs"] = deepcopy(CRS_26911)
        request["display_crs"] = deepcopy(CRS_26911)
        package = self.author_package(request, self.root / "work-legacy")
        root = Path(package["package_path"])
        scenario = load_document(root / "contracts/scenario.yaml")
        self.assertNotIn("segment_refs", scenario)
        self.assertEqual(scenario["replaceable_segments"], [])
        self.assertEqual(set(scenario["embedded"]), {"style", "layout"})
        manifest = load_document(root / "manifest.yaml")
        self.assertEqual(manifest["dependencies"], [])


class CreateRequestProtocolTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.registry = SchemaRegistry()

    def test_referenced_request_validates_and_kind_boundary_is_enforced(self) -> None:
        request = referenced_create_request(SEGMENT_REF_LAYOUT)
        self.registry.validate("template-create-request", request)
        self.registry.validate("general-template-create-request", request)
        wrong_kind = deepcopy(request)
        wrong_kind["segment_refs"]["layout"]["kind"] = "map-scenario"
        unknown_segment = deepcopy(request)
        unknown_segment["segment_refs"]["portrayal"] = deepcopy(SEGMENT_REF_LAYOUT)
        unpinned = deepcopy(request)
        unpinned["segment_refs"]["layout"].pop("digest")
        for case in (wrong_kind, unknown_segment, unpinned):
            with self.assertRaises(ProtocolError):
                self.registry.validate("template-create-request", case)


class ReferencedPublishLineTests(SegmentPackageFixture):
    """author -> validate (real raster fixture render) -> tamper -> publish.

    Static-gate tests run everywhere; the render-dependent assertions skip on
    hosts without the raster-rendering extra or an embeddable CJK font.
    """

    def setUp(self) -> None:
        super().setUp()
        self.render_ready = True
        try:
            from carto_core.adapters.raster_renderer import _dependencies
            _dependencies()
            import fontTools  # noqa: F401
        except (CartoError, ImportError):
            self.render_ready = False
        font_source = find_cjk_font(VALIDATION_TEXT) if self.render_ready else None
        if font_source is None:
            self.render_ready = False
        if self.render_ready:
            self.addCleanup(release_test_font_handles)
            self.font_path = self.root / "fonts/selected-cjk.ttf"
            self.font_path.parent.mkdir()
            self.font_path.write_bytes(font_source.read_bytes())
        else:
            self.font_path = None
        (self.root / "sources").mkdir()
        csv_path = self.root / "sources/legend-sample.csv"
        csv_path.write_bytes(LEGEND_CSV.encode("utf-8"))
        manifest = {
            "schema_version": 1,
            "manifest_id": "general-sources",
            "sources": [{
                "source_id": "legend-sample", "kind": "csv",
                "location_ref": "sources/legend-sample.csv",
                "digest": file_digest(csv_path),
                "provenance": {"source_type": "user", "source_ref": "user-upload:legend-sample",
                               "version": "1", "retrieved_at": "2026-11-01T00:00:00Z",
                               "classification": "internal"},
                "license": "project-approved", "captured_at": "2026-11-01T00:00:00Z",
                "data_profile": {"data_nature": "user-provided", "contains_production_data": False,
                                 "contains_sensitive_coordinates": False,
                                 "source_crs": deepcopy(CRS_26911)},
            }],
        }
        atomic_yaml(self.root / "source-manifest.yaml", manifest)
        self.segment_ref = self.publish_layout_segment()
        self.request = referenced_create_request(self.segment_ref)
        self.request_path = self.root / "create-request.json"
        self.request_path.write_text(json.dumps(self.request, ensure_ascii=False), encoding="utf-8")
        self.workflow = TemplateCreationWorkflow(allowed_roots=[self.root], project_root=self.root,
                                                 workdir=self.root / "work", registry=self.registry)
        self.repo_kwargs = dict(repository_root=self.root / "repo", repository_scope="local:templates")
        self.publish_kwargs = dict(**self.repo_kwargs, idempotency_key="publish-s2-referenced-0001",
                                   approval_key=APPROVAL_KEY, renderer_attestation_key=KEY)

    def run_to_validated(self, **repo_kwargs) -> dict:
        self.workflow.analyze(self.request_path)
        self.workflow.brief(self.request_path)
        self.workflow.author(self.request_path)
        return self.workflow.validate(self.request_path, attestation_key=KEY,
                                      font_path=self.font_path, **repo_kwargs)

    def test_validate_without_repository_fails_closed(self) -> None:
        validated = self.run_to_validated()
        evidence = validated["evidence"]
        self.assertEqual(evidence["status"], "failed")
        failed = [item for item in evidence["results"] if item["status"] == "failed"]
        self.assertEqual(failed[0]["details"]["code"], "SEGMENT_REPOSITORY_REQUIRED")

    def test_referenced_package_validates_publishes_and_tamper_fails_closed(self) -> None:
        validated = self.run_to_validated(**self.repo_kwargs)
        evidence = validated["evidence"]
        if not self.render_ready:
            # Static gates must all pass without rendering; only the fixture
            # render itself may fail closed on a host lacking the raster extra.
            static = [item for item in evidence["results"]
                      if item["check_id"] != "template.fixture-render"]
            self.assertTrue(all(item["status"] == "passed" for item in static),
                            [item for item in static if item["status"] != "passed"])
            self.skipTest("Raster rendering extra or embeddable CJK font unavailable")
        self.assertEqual(evidence["status"], "passed")
        self.assertEqual({"pdf", "png"},
                         {item["target"] for item in evidence["preview_artifacts"]})
        # The resolved fixture scene must bind the referenced layout contract exactly.
        scene = load_document(Path(evidence["render_scene_ref"]["uri"]))
        self.assertEqual(scene["resolved_layout"]["template_contract"], layout_contract())
        prepared = self.workflow.prepare_publication(
            self.request_path, repository_root=self.root / "repo",
            repository_scope="local:templates", idempotency_key="publish-s2-referenced-0001")

        # Tampering with the published segment after validation fails closed at
        # publish re-verification (the evidence itself stays untouched).
        contract_path = self.segment_contract_path()
        original = contract_path.read_bytes()
        try:
            contract_path.write_text(json.dumps({**layout_contract(), "category": "poster"}),
                                     encoding="utf-8")
            with self.assertRaisesRegex(ProtocolError, "PUBLISHED_PACKAGE_CORRUPT"):
                self.workflow.publish(self.request_path, None, **self.publish_kwargs)
        finally:
            contract_path.write_bytes(original)

        publication_digest = prepared["object_digest"]
        atomic_yaml(self.root / "tp.yaml", asdict(sign(
            "TP", "approve-template-publish", "template-publication", publication_digest,
            subject_id=self.request["subject"]["approver_subject_id"], scope=self.request["scope"],
            tenant_id=self.request["subject"]["tenant_id"])))
        published = self.workflow.publish(self.request_path, self.root / "tp.yaml",
                                          **self.publish_kwargs)
        self.assertFalse(published["idempotent_replay"])
        self.assertEqual(published["publication"]["package_ref"]["digest"],
                         evidence["package_ref"]["digest"])

        # Generate side: install the published referenced scenario and resolve at
        # load_contracts; the resolved view must equal the legacy embedded contracts.
        installation = ProjectTemplateInstaller(
            path_guard=self.guard, project_root=self.root,
            repository=self.repository, registry=self.registry).install(
                {**published["publication"]["package_ref"], "namespace": "local"})
        compiler = MapCandidateCompiler(self.guard, self.registry)
        contracts = compiler.load_contracts(installation, repository=self.repository)
        self.assertEqual(contracts["scenario"]["embedded"]["layout"], layout_contract())
        self.assertEqual(contracts["scenario"]["segment_refs"], {"layout": self.segment_ref})

        legacy_work = self.root / "legacy-work"
        legacy_work.mkdir()
        legacy_request = deepcopy(self.request)
        legacy_request.pop("segment_refs")
        legacy_package = GeneralThematicAuthor(self.guard, legacy_work, self.registry).author(
            legacy_request, BRIEF_STUB)
        legacy_root = Path(legacy_package["package_path"])
        legacy_manifest = load_document(legacy_root / "manifest.yaml")
        legacy_installation = {
            "package_path": legacy_root.as_posix(), "namespace": "local",
            "template_ref": {"kind": "map-scenario", "id": legacy_manifest["package"]["id"],
                             "version": legacy_manifest["package"]["version"],
                             "digest": file_digest(legacy_root / "checksums.sha256")},
            "manifest_digest": file_digest(legacy_root / "manifest.yaml"),
            "contract_digest": sha256_digest({
                name: legacy_manifest["checksums"][path]
                for name, path in legacy_manifest["business_contracts"].items()}),
        }
        legacy_contracts = compiler.load_contracts(legacy_installation)
        for key in ("data_schema", "spatial_behavior", "portrayal", "delivery", "quality_gates"):
            self.assertEqual(contracts[key], legacy_contracts[key], key)
        # The lock is NOT byte-comparable across the two packages, by design:
        #   * a referenced package must pin its segment dependencies
        #     (OwnershipResolver.validate_segment_lock), an embedded one has none;
        #   * lock_id / package.digest / generated_at are per-package identity and
        #     authoring time, not resolved content.
        # So assert the segment part positively, then compare the resolved remainder.
        segment_kinds = set(OwnershipResolver.KIND_TO_SEGMENT)
        referenced_deps = contracts["lock"]["dependencies"]
        self.assertEqual([item for item in referenced_deps if item["kind"] in segment_kinds],
                         [self.segment_ref])
        self.assertEqual([item for item in referenced_deps if item["kind"] not in segment_kinds],
                         legacy_contracts["lock"]["dependencies"])
        self.assertEqual(contracts["lock"]["resources"], legacy_contracts["lock"]["resources"])
        self.assertEqual(contracts["lock"]["resolver_version"], legacy_contracts["lock"]["resolver_version"])
        self.assertEqual(legacy_contracts["lock"]["dependencies"], [])
        resolved_scenario = deepcopy(contracts["scenario"])
        resolved_scenario.pop("segment_refs")
        resolved_scenario["replaceable_segments"] = []
        self.assertEqual(resolved_scenario, legacy_contracts["scenario"])

        # Without a repository the referenced installation fails closed; a tampered
        # segment fails closed even with one.
        with self.assertRaises(ProtocolError) as caught:
            compiler.load_contracts(installation)
        self.assertEqual(caught.exception.code, "SEGMENT_REPOSITORY_REQUIRED")
        try:
            contract_path.write_bytes(original + b"\n# tampered")
            with self.assertRaisesRegex(ProtocolError, "PUBLISHED_PACKAGE_CORRUPT"):
                compiler.load_contracts(installation, repository=self.repository)
        finally:
            contract_path.write_bytes(original)


if __name__ == "__main__":
    unittest.main()