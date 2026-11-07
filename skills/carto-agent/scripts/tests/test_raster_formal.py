"""Synthetic formal backend/gate integration, not a registered production scenario.

Keys, grants and tiny TIFFs are generated only in TemporaryDirectory. No repository
policy or actual user approval is created, changed or consumed by these tests.
"""
from __future__ import annotations
from copy import deepcopy
from datetime import UTC, datetime, timedelta
from dataclasses import asdict, replace
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

SCRIPTS_ROOT = Path(__file__).resolve().parents[1]
if str(SCRIPTS_ROOT) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_ROOT))

from carto_core.adapters.raster_formal_renderer import RasterFormalRenderer, RasterRendererProfile
from carto_core.adapters.render_backend import create_render_backend
from carto_core.adapters.webmap_renderer import compute_renderer_attestation, WebMapRendererAdapter
from carto_core.canonical import sha256_digest
from carto_core.compiler.map_lock import MapSpecLockCompiler
from carto_core.compiler.map_candidate import MapCandidateCompiler
from carto_core.workflow.map_generation import MapGenerationWorkflow
from carto_core.compiler.raster_scene import RasterSceneCompiler, RASTER_RENDERER_ID
from carto_core.errors import CartoError, ProtocolError, SecurityError
from carto_core.scenario_registry import ScenarioRegistry, ScenarioCapability
from carto_core.schema_registry import load_document
from carto_core.security.approval import ApprovalReceipt, InMemoryNonceStore, sign_receipt
from carto_core.workflow.approvals import ApprovalGateCoordinator
from carto_core.artifacts import atomic_yaml, artifact_ref, utc_now
from carto_core.workflow.map_delivery import MapDeliveryService
from carto_core.validation.map_checks import MapQualityChecks
from carto_core.workflow.map_final_check import FinalMapCheckService
from carto_core.workflow.map_preview import MapPreviewService, freeze_object_digest
from carto_core.workflow.map_render import FormalMapRenderService
from carto_core.workflow.raster_bundle import RasterBundlePreparer
from tests.fixtures.schema_cases import VALID_CASES
from tests.test_raster_classification import PreparationFixture
from tests.test_raster_page_renderer import page_request, release_test_font_handles
from tests import test_raster_renderer as raster_helpers

KEY = b"synthetic-render-key-not-for-production-1234"
APPROVAL_KEY = b"synthetic-approval-key-not-for-production-1234"
NOTICE = "Synthetic data only"


class SyntheticCapability:
    """Only injected by this test; never registered in application code or policies."""
    notice = NOTICE
    definition = {"licenses": ["synthetic-test-only"], "internal_field_names": ["private-test-marker"]}

    def require_contract(self, contract):
        assert contract == {"scenario_id": "synthetic-test"}

    def require_scene(self, scene):
        assert scene["renderer_id"] == RASTER_RENDERER_ID
        assert scene["resolved_layout"]["page"]["width_mm"] == 297
        assert scene["resolved_layout"]["page"]["height_mm"] == 210

    def component(self, name):
        assert name == "legend_checker"
        # This synthetic purpose explicitly checks its test display labels.
        return lambda ctx: (ctx["raster"]["portrayal"]["legend_items"][0]["label"] == "Category A",
                            {"synthetic-purpose-check": True}, None)

    def require_manifest(self, manifest):
        if manifest["licenses"] != self.definition["licenses"] or manifest["limitations"] != [self.notice]:
            raise ProtocolError("DELIVERY_SCENARIO_POLICY_MISMATCH", "Synthetic purpose policy mismatch")


class RasterFormalTests(PreparationFixture, unittest.TestCase):
    def setUp(self):
        super().setUp()
        try:
            from carto_core.adapters.raster_renderer import _dependencies
            self.np, self.rio, self.mpl, _, _, _, self.Image = _dependencies()
            import fontTools
        except (CartoError, ImportError) as exc:
            self.skipTest(str(exc))
        self.addCleanup(release_test_font_handles)
        raster_helpers.RasterRendererTests.set_raster(self, self.np.array([[1,0,255],[255,1,0]],dtype="uint8"))
        self.prepared = self.ready()
        self.bundle_preparer = RasterBundlePreparer(self.service)
        self.bundle_ref = self.bundle_preparer.prepare(self.prepared.ref(), self.context).ref()
        self.page = page_request(self.service, self.prepared, self.context, dpi=72)
        self.compiler = RasterSceneCompiler(self.service)
        self.scene = self.compiler.compile(bundle_ref=self.bundle_ref, page_request=self.page,
                                           context=self.context, scene_id="synthetic-raster-scene")
        self.candidate = deepcopy(VALID_CASES["resolved-map"])
        self.candidate.update(project_id=self.context.project_id, run_id=self.context.run_id)
        base = self.candidate["execution"]
        base["shared_semantics"]["data_nature"] = "synthetic"
        self.execution = self.compiler.bind_execution(base, self.scene, self.context)
        self.candidate.update(execution=self.execution, execution_digest=sha256_digest(self.execution))
        self.generate = {"project_id": self.context.project_id, "run_id": self.context.run_id,
                         "subject": {"tenant_id": self.context.tenant_id, "subject_id": self.context.subject_id,
                                     "approver_subject_id": "synthetic-reviewer"},
                         "scope": "project:"+self.context.project_id, "environment": "local",
                         "allowed_capabilities": ["read", "classify", "render-preview"]}
        self.work = self.root / "work"
        self.work.mkdir()
        self.preview = MapPreviewService(path_guard=self.service.guard, output_root=self.work/"previews",
            attestation_key=KEY, project_root=self.root, context=self.context)
        self.formal = FormalMapRenderService(path_guard=self.service.guard, work_root=self.work,
            attestation_key=KEY, renderer_id=RASTER_RENDERER_ID, project_root=self.root, context=self.context)
        self.capability = SyntheticCapability()
        patcher = patch.object(ScenarioRegistry, "for_execution", return_value=self.capability)
        patcher.start(); self.addCleanup(patcher.stop)
        no_browser = patch("carto_core.adapters.render_backend.discover_browser", side_effect=AssertionError("No browser for raster"))
        no_browser.start(); self.addCleanup(no_browser.stop)
        self.registry = self.service.registry

    def approval(self, gate, digest, *, nonce=None):
        now = datetime.now(UTC)
        action, kind = {"G2": ("approve-freeze", "resolved-map"),
                        "G3": ("approve-delivery", "delivery-manifest")}[gate]
        return sign_receipt(ApprovalReceipt(1, "synthetic-approval-"+gate.lower(), "synthetic-issuer",
            "synthetic-reviewer", self.context.tenant_id, action, kind, digest, self.generate["scope"],
            "synthetic-policy", "local", (now-timedelta(minutes=1)).isoformat(),
            (now+timedelta(minutes=10)).isoformat(), nonce or "synthetic-nonce-"+gate.lower()+"-123456"), APPROVAL_KEY)

    def freeze_and_render(self):
        self.preview_result = self.preview.render(self.generate, self.candidate, self.scene)
        self.preview.validate_persisted(self.candidate, self.scene, self.preview_result["receipt"])
        evidence, receipt = self.preview_result["evidence"], self.preview_result["receipt"]
        digest = freeze_object_digest(self.generate, self.candidate, evidence)
        approval = self.approval("G2", digest)
        coordinator = ApprovalGateCoordinator(APPROVAL_KEY, InMemoryNonceStore(), "synthetic-policy", "synthetic-issuer")
        coordinator.require("G2", approval, digest, self.context, approver_subject_id="synthetic-reviewer",
                            expected_scope=self.generate["scope"])
        self.lock = MapSpecLockCompiler().compile(self.generate, self.candidate, evidence, receipt,
            deepcopy(VALID_CASES["validation-report"]), brief_approval_ref="synthetic-g1-test-boundary",
            freeze_approval_ref="synthetic-g2")
        path = self.work / "map-spec-lock.yaml"
        atomic_yaml(path, self.lock)
        self.lock_ref = artifact_ref(self.lock["lock_id"], self.lock, path)
        self.formal.validate_environment(self.lock, receipt)
        self.rendered = self.formal.render(request=self.generate, lock=self.lock, lock_ref=self.lock_ref,
            scene=self.scene, attempt_number=1, started_at=utc_now())
        return self.rendered

    def check_rendered(self):
        self.checker = FinalMapCheckService(path_guard=self.service.guard, project_root=self.root,
            work_root=self.work, execution_context=self.context)
        r = self.rendered
        self.report = self.checker.inspect(lock=self.lock, lock_ref=self.lock_ref, scene=self.scene,
            attempt=r["attempt"], attempt_path=r["attempt_path"], receipt=r["receipt"], evidence=r["evidence"],
            evidence_path=r["evidence_path"])
        return self.report

    def manifest(self):
        report_path = self.checker.write_report(self.report, self.rendered["attempt"]["attempt_id"])
        r = self.rendered
        manifest = self.checker.build_manifest(request=self.generate, lock=self.lock, lock_ref=self.lock_ref,
            attempt=r["attempt"], attempt_path=r["attempt_path"], report=self.report, report_path=report_path,
            recipient_id="synthetic-recipient", recipient_type="project-user", destination="deliveries/synthetic",
            idempotency_key="synthetic-delivery-idempotency")
        path = self.checker.write_manifest(manifest)
        return manifest, artifact_ref(manifest["manifest_id"], manifest, path)

    def generation_request(self):
        request = deepcopy(VALID_CASES["generate-request"])
        request.update(self.generate)
        request["subject"]["namespace"] = self.context.project_id
        request.update(source_bindings=[deepcopy(self.request["source"])],
            sources=[deepcopy(self.request["source"]["source_ref"])],
            prepared_raster_bindings=[{"role": self.request["source"]["role"], "prepared_ref": self.prepared.ref()}],
            requested_at=utc_now(), audience="synthetic test only",
            allowed_capabilities=["read", "classify", "render-preview"],
            font={"path": self.page["font"]["path"], "family": "DejaVu Sans", "version": "1.0.0"})
        self.registry.validate("generate-request", request)
        return request

    def staged_workflow(self):
        """Start at a test-only prepared candidate boundary, NOT a T1/G1/template admission test.

        Only capability discovery and installed-template validation are test seams.
        Request/schema/intent projection, data, layout, backend, approvals, nonce store,
        candidate/lock/evidence, final checks and delivery/state recovery remain real.
        """
        self.generate = self.generation_request()
        intent = deepcopy(VALID_CASES["map-intent"])
        intent["evidence_refs"] = [{"id": name, "version": "1.0.0", "digest": "sha256:"+"0"*64}
                                   for name in ("synthetic-catalog", "intent-input", "synthetic-purpose")]
        for key in ("business_scene", "theme_tags", "tasks"):
            intent[key] = deepcopy(self.generate["intent"][key])
        self.execution.update(business_scene=intent["business_scene"], map_tasks=intent["tasks"],
            intent_ref={"id": intent["intent_id"], "version": "1.0.0", "digest": sha256_digest(intent)},
            profile_refs=[intent["evidence_refs"][0], intent["evidence_refs"][-1]])
        self.execution["shared_semantics"]["theme_tags"] = intent["theme_tags"]
        self.contracts = {"scenario": {"scenario_id": "synthetic-test"},
                          "quality_gates": deepcopy(VALID_CASES["quality-gates"])}
        reference = MapQualityChecks(self.registry).reference(self.contracts["quality_gates"], self.scene)
        self.execution["policy_refs"] = [reference]
        self.candidate.update(execution=self.execution, execution_digest=sha256_digest(self.execution))
        workflow = MapGenerationWorkflow(allowed_roots=[self.root], project_root=self.root, workdir=self.work)
        for seam in [patch.object(ScenarioRegistry, "resolve_generate", return_value=(self.capability, intent)),
                     patch.object(workflow, "_verify_installed_template"),
                     patch.object(MapCandidateCompiler, "load_contracts", return_value=self.contracts)]:
            seam.start(); self.addCleanup(seam.stop)
        self.request_path = self.work/"request/generate-request.yaml"
        preflight = MapCandidateCompiler(self.service.guard, self.registry,
            project_root=self.root, context=self.context).check_candidate(
                self.generate, self.candidate, self.scene, self.contracts)
        files = {"request/generate-request.yaml": self.generate, "intent/map-intent.yaml": intent,
                 "candidates/resolved-map.yaml": self.candidate, "candidates/render-scene.yaml": self.scene,
                 "candidates/preflight-report.yaml": preflight, "templates/installed-template.yaml": {"test_only": True}}
        for relative, document in files.items(): atomic_yaml(self.work/relative, document)
        state = workflow.state_store.initialize(self.context.run_id, self.generate, step="compile")
        workflow.state_store.complete_step(state, status="succeeded", prerequisites={},
            output_refs=[artifact_ref("resolved-map", self.candidate, self.work/"candidates/resolved-map.yaml")],
            next_step="preview")
        return workflow

    def freeze_workflow(self, workflow):
        preview = workflow.preview(self.request_path, attestation_key=KEY)
        self.assertEqual(("waiting_approval", "freeze"), (preview["state"]["status"], preview["state"]["step"]))
        approval_path = self.root/"workflow-g2.yaml"
        kwargs = dict(approval_key=APPROVAL_KEY, attestation_key=KEY, nonce_db=self.root/"workflow-nonces.sqlite",
                      policy_id="synthetic-policy", issuer="synthetic-issuer")
        for wrong in [self.approval("G2", "sha256:"+"0"*64),
                      sign_receipt(replace(self.approval("G2", preview["approval_object_digest"]),
                                           scope="project:other"), APPROVAL_KEY)]:
            atomic_yaml(approval_path, asdict(wrong), create_once=False)
            with self.assertRaises(SecurityError): workflow.freeze(self.request_path, approval_path, **kwargs)
            self.assertFalse((self.work/"locks"/f"lock-{self.context.run_id}"/"map-spec-lock.yaml").exists())
        atomic_yaml(approval_path, asdict(self.approval("G2", preview["approval_object_digest"])), create_once=False)
        frozen = workflow.freeze(self.request_path, approval_path, **kwargs)
        recovered = workflow.freeze(self.request_path, approval_path, **kwargs)
        self.assertEqual(frozen["lock"], recovered["lock"])
        self.assertTrue(recovered["idempotent_replay"])
        return frozen

    def test_workflow_preview_g2_render_check_g3_and_crash_recovery(self):
        workflow = self.staged_workflow()
        frozen = self.freeze_workflow(workflow)
        Path(self.page["font"]["path"]).unlink()  # downstream uses only the frozen font
        rendered = workflow.render(self.request_path, attestation_key=KEY)
        self.assertEqual("check", rendered["state"]["step"])
        checked = workflow.check(self.request_path, attestation_key=KEY, recipient_id="synthetic-recipient",
            recipient_type="project-user", destination="deliveries/workflow", idempotency_key="workflow-delivery-1234")
        self.assertEqual("passed", checked["validation_report"]["status"])
        manifest = checked["delivery_manifest"]
        self.assertEqual(sha256_digest(frozen["lock"]), manifest["lock_ref"]["digest"])
        approval_path = self.root/"workflow-g3.yaml"
        kwargs = dict(approval_key=APPROVAL_KEY, nonce_db=self.root/"workflow-nonces.sqlite",
                      policy_id="synthetic-policy", issuer="synthetic-issuer")
        for wrong in [self.approval("G3", "sha256:"+"0"*64),
                      sign_receipt(replace(self.approval("G3", sha256_digest(manifest)),
                                           scope="project:other"), APPROVAL_KEY)]:
            atomic_yaml(approval_path, asdict(wrong), create_once=False)
            with self.assertRaises(SecurityError): workflow.deliver(self.request_path, approval_path, **kwargs)
            self.assertFalse((self.root/"deliveries/workflow").exists())
        atomic_yaml(approval_path, asdict(self.approval("G3", sha256_digest(manifest))), create_once=False)
        def crash(phase):
            if phase == "after-atomic-commit": raise RuntimeError("synthetic workflow interruption")
        with self.assertRaisesRegex(RuntimeError, "synthetic workflow interruption"):
            workflow.deliver(self.request_path, approval_path, failure_hook=crash, **kwargs)
        completed = workflow.deliver(self.request_path, approval_path, **kwargs)
        self.assertEqual(("succeeded", "deliver"), (completed["state"]["status"], completed["state"]["step"]))
        repeated = workflow.deliver(self.request_path, approval_path, **kwargs)
        self.assertTrue(repeated["idempotent_replay"])
        self.assertEqual({"map.pdf", "map.png", "README.md", "delivery-manifest.yaml", "checksums.sha256"},
                         {p.name for p in (self.root/"deliveries/workflow").iterdir()})
        original = ApprovalReceipt.from_dict(load_document(approval_path))
        changed = sign_receipt(replace(original, receipt_id="changed-g3-receipt"), APPROVAL_KEY)
        atomic_yaml(approval_path, asdict(changed), create_once=False)
        with self.assertRaisesRegex(SecurityError, "APPROVAL_RECOVERY_EVIDENCE_CONFLICT"):
            workflow.deliver(self.request_path, approval_path, **kwargs)

    def test_preview_rejects_tampered_preflight_before_rendering(self):
        workflow = self.staged_workflow()
        path = self.work / "candidates/preflight-report.yaml"
        report = load_document(path)
        report["checker_set_digest"] = "sha256:" + "0" * 64
        atomic_yaml(path, report, create_once=False)
        with patch.object(MapPreviewService, "render") as render:
            with self.assertRaisesRegex(ProtocolError, "CANDIDATE_PREFLIGHT_DRIFT"):
                workflow.preview(self.request_path, attestation_key=KEY)
            render.assert_not_called()
        self.assertFalse(list((self.work / "locks").rglob("map-spec-lock.yaml")))

    def test_freeze_rejects_changed_gates_before_consuming_g2(self):
        workflow = self.staged_workflow()
        workflow.preview(self.request_path, attestation_key=KEY)
        self.contracts["quality_gates"]["checks"].append({
            "id": "cartography.legend-consistency", "version": "1.0.0", "params": {}})
        # The approval path is deliberately absent: gate drift must be caught
        # before any approval lookup or nonce consumption.
        with patch.object(ApprovalGateCoordinator, "require") as consume:
            with self.assertRaisesRegex(ProtocolError, "CANDIDATE_CHECKER_SET_DRIFT"):
                workflow.freeze(self.request_path, self.root / "absent-g2.yaml",
                    approval_key=APPROVAL_KEY, attestation_key=KEY,
                    nonce_db=self.root / "unconsumed-nonces.sqlite",
                    policy_id="synthetic-policy", issuer="synthetic-issuer")
            consume.assert_not_called()
        self.assertFalse((self.root / "unconsumed-nonces.sqlite").exists())
        self.assertFalse(list((self.work / "locks").rglob("map-spec-lock.yaml")))

    def test_lock_replay_rejects_changed_quality_policy(self):
        workflow = self.staged_workflow()
        self.freeze_workflow(workflow)
        self.contracts["quality_gates"]["checks"].append({
            "id": "cartography.legend-consistency", "version": "1.0.0", "params": {}})
        with self.assertRaisesRegex(ProtocolError, "LOCK_INPUT_DRIFT.*CANDIDATE_CHECKER_SET_DRIFT"):
            workflow.render(self.request_path, attestation_key=KEY)
        self.assertEqual("failed", workflow.state_store.load().status)
        self.assertFalse(list((self.work / "output").rglob("map.pdf")))

    def test_workflow_environment_drift_requires_new_preview_and_freeze(self):
        workflow = self.staged_workflow()
        self.freeze_workflow(workflow)
        profile = RasterRendererProfile.current()
        changed = replace(profile, runtime={**profile.runtime, "matplotlib": "0.0.0"})
        with patch.object(RasterRendererProfile, "current", return_value=changed):
            with self.assertRaisesRegex(ProtocolError, "RENDER_ENVIRONMENT_DRIFT"):
                workflow.render(self.request_path, attestation_key=KEY)
        self.assertEqual("failed", workflow.state_store.load().status)
        self.assertFalse(list((self.work/"output").rglob("map.pdf")))
        with self.assertRaises(CartoError): workflow.retry()

    def test_candidate_component_receives_trusted_scope_and_cannot_swap_bundle(self):
        workflow = self.staged_workflow()
        intent = load_document(self.work/"intent/map-intent.yaml")
        plan = deepcopy(VALID_CASES["map-plan"])
        for key in ("business_scene", "tasks", "theme_tags"): plan[key] = intent[key]
        plan["intent_ref"]["digest"] = sha256_digest(intent)
        prepared = self.bundle_preparer.prepare_request(self.generate, self.context)
        envelope = {"candidate": self.candidate, "scene": self.scene,
                    "preflight": deepcopy(VALID_CASES["validation-report"])}
        owner = self
        class CandidateComponent:
            def __init__(self, guard, registry, *, project_root, context):
                owner.assertEqual(owner.root, project_root)
                owner.assertIs(owner.context, context)
            def compile(self, *args): return envelope
        def projection(document, supplied_intent, *, kind):
            ScenarioCapability.require_intent_projection(document, supplied_intent, kind=kind)
        original_component = self.capability.component
        with patch.object(self.capability, "component", side_effect=lambda name:
                          CandidateComponent if name == "candidate_compiler" else original_component(name)), \
             patch.object(self.capability, "require_contract", create=True), \
             patch.object(self.capability, "require_intent_projection", side_effect=projection, create=True):
            compiler = MapCandidateCompiler(self.service.guard, self.registry, project_root=self.root, context=self.context)
            args = (self.generate, intent, plan, prepared["bundle"], {}, self.contracts, Path(self.page["font"]["path"]))
            self.assertIs(envelope, compiler.compile(*args))
            prepared["bundle"]["role_bindings"][0]["width"] += 1
            with self.assertRaisesRegex(ProtocolError, "RASTER_CANDIDATE_BUNDLE_MISMATCH"):
                compiler.compile(*args)

    def test_sensitive_check_includes_vectorized_north_label(self):
        checker = FinalMapCheckService(path_guard=self.service.guard, project_root=self.root,
                                      work_root=self.work, execution_context=self.context)
        page = deepcopy(self.page)
        page["grid_north"] = {"label": "private-test-marker"}
        context = {"scenario_profile": self.capability, "artifacts": [],
                   "raster": {"page": page, "portrayal": {"legend_items": []}}}
        passed, details, _ = checker._sensitive_content(context)
        self.assertFalse(passed)
        self.assertIn("frozen-rendered-text", str(details))

    def test_workflow_changed_output_fails_check_without_g3_manifest(self):
        workflow = self.staged_workflow()
        self.freeze_workflow(workflow)
        workflow.render(self.request_path, attestation_key=KEY)
        png = next((self.work/"output").rglob("map.png"))
        png.write_bytes(png.read_bytes()+b"tampered")
        with self.assertRaisesRegex(ProtocolError, "FINAL_CHECK_FAILED"):
            workflow.check(self.request_path, attestation_key=KEY, recipient_id="synthetic-recipient",
                recipient_type="project-user", destination="deliveries/workflow", idempotency_key="workflow-delivery-1234")
        self.assertEqual("failed", workflow.state_store.load().status)
        self.assertFalse(list(self.work.rglob("delivery-manifest*.yaml")))
        with self.assertRaises(CartoError): workflow.retry()

    def test_generation_requires_exact_preparation_source_and_requested_outputs(self):
        request = self.generation_request()
        ready = self.bundle_preparer.prepare_request(request, self.context)
        self.assertEqual(self.bundle_ref, ready["bundle_ref"])
        self.compiler.validate_generation(self.scene, self.execution, request, self.context)
        # Malformed contracts must fail before opening or materializing preparation artifacts.
        malformed = deepcopy(request)
        malformed["prepared_raster_bindings"][0]["unexpected"] = True
        with patch.object(self.bundle_preparer, "build", side_effect=AssertionError("Must reject before I/O")):
            with self.assertRaises(ProtocolError):
                self.bundle_preparer.prepare_request(malformed, self.context)
        for field in ("prepared_raster_bindings", "source_bindings", "sources"):
            wrong = deepcopy(request)
            if field == "prepared_raster_bindings": wrong[field][0]["role"] = "another-role"
            elif field == "source_bindings": wrong[field][0]["path"] = "another.tif"
            else: wrong[field][0]["digest"] = "sha256:"+"0"*64
            with self.assertRaises(CartoError): self.bundle_preparer.prepare_request(wrong, self.context)
        request["requested_outputs"].append("svg")
        with self.assertRaisesRegex(ProtocolError, "RASTER_GENERATE_TARGET_MISMATCH"):
            self.compiler.validate_generation(self.scene, self.execution, request, self.context)

    def test_formal_g2_render_check_g3_atomic_delivery_and_recovery(self):
        r = self.freeze_and_render()
        self.assertNotIn("browser_version", r["receipt"])
        self.assertNotIn("maplibre_version", r["receipt"])
        self.assertEqual("not-provided", r["receipt"]["controls"]["network_isolation"])
        report = self.check_rendered()
        self.assertEqual("passed", report["status"], report["results"])
        self.assertEqual(11, len(report["results"]))
        manifest, ref = self.manifest()
        service = MapDeliveryService(path_guard=self.service.guard, project_root=self.root, work_root=self.work)
        approval_path = self.root/"synthetic-g3.yaml"
        atomic_yaml(approval_path, asdict(self.approval("G3", sha256_digest(manifest))), create_once=False)
        kwargs = dict(request=self.generate, manifest=manifest, manifest_ref=ref, report=report,
                      approval_path=approval_path, approval_key=APPROVAL_KEY, nonce_db=self.root/"nonces.sqlite",
                      policy_id="synthetic-policy", issuer="synthetic-issuer")
        def crash(phase):
            if phase == "after-atomic-commit":
                raise RuntimeError("synthetic interruption")
        with self.assertRaisesRegex(RuntimeError, "synthetic interruption"):
            service.deliver(**kwargs, failure_hook=crash)
        delivered = service.deliver(**kwargs)
        self.assertTrue(delivered["receipt"])
        final = self.root / "deliveries/synthetic"
        self.assertEqual({"map.pdf","map.png","README.md","delivery-manifest.yaml","checksums.sha256"},
                         {p.name for p in final.iterdir()})
        replay = service.deliver(**kwargs)
        self.assertTrue(replay["approval_replay"])
        self.assertTrue(replay["idempotent_replay"])
        self.assertNotIn("classified.tif", (final/"README.md").read_text(encoding="utf-8"))

    def test_typed_bundle_has_no_invented_vector_metadata(self):
        bundle = self.bundle_preparer.load_verified(self.bundle_ref, self.context)
        binding = bundle["role_bindings"][0]
        self.assertEqual("raster", binding["data_type"])
        self.assertNotIn("feature_count", binding)
        self.assertNotIn("join_coverage", binding)
        self.assertEqual([], bundle["transformations"])
        mutated = deepcopy(bundle); mutated["role_bindings"][0]["feature_count"] = 6
        with self.assertRaises(ProtocolError): self.registry.validate("prepared-data-bundle", mutated)

    def test_wrong_backend_and_unknown_fields_fail_closed(self):
        with self.assertRaises(ProtocolError): create_render_backend("auto-fallback")
        backend = self.preview.backend(self.scene)
        with patch.object(backend.page_renderer, "render", side_effect=AssertionError("Must reject before drawing")):
            for session in ("../escape", "1numeric", "a-", "a--b", "a"*80):
                with self.assertRaises(SecurityError): backend.render(session, self.scene)
        with self.assertRaises(ProtocolError): WebMapRendererAdapter().compile_scene(self.scene)
        for key,value in [("camera", {}), ("renderer_id", "maplibre-web"), ("unknown", True)]:
            scene = deepcopy(self.scene); scene[key] = value
            with self.assertRaises(ProtocolError): self.registry.validate("render-scene", scene)
        execution = deepcopy(self.execution); execution["environment"]["browser_version"] = "fake"
        candidate = {**self.candidate, "execution": execution, "execution_digest": sha256_digest(execution)}
        with self.assertRaises(ProtocolError): self.registry.validate("resolved-map", candidate)

    def test_scene_scope_resources_page_and_bundle_tampering(self):
        for field in ["tenant_id", "run_id", "subject_id", "project_id"]:
            scene = deepcopy(self.scene); scene["context"][field] = "other"
            with self.assertRaises(SecurityError): self.compiler.validate_scene(scene, self.context)
        scene = deepcopy(self.scene); scene["resources"][0]["digest_mode"] = ("bytes" if scene["resources"][0]["digest_mode"] == "canonical-json" else "canonical-json")
        with self.assertRaises(ProtocolError): self.compiler.validate_scene(scene, self.context)
        bundle = self.bundle_preparer.load_verified(self.bundle_ref, self.context)
        bundle["role_bindings"][0]["width"] += 1
        body = {k:v for k,v in bundle.items() if k != "digest"}; bundle["digest"] = sha256_digest(body)
        ref = self.service.save_document(bundle,"prepared-data-bundle").ref()
        with self.assertRaises(ProtocolError): self.bundle_preparer.load_verified(ref,self.context)
        for key in ["prepared_data_refs", "dataset_refs", "resolved_assets"]:
            execution = deepcopy(self.execution); execution[key] = []
            with self.assertRaises(ProtocolError): self.compiler.validate_execution(self.scene,execution,self.context)

    def test_font_source_removed_after_freeze_and_raw_snapshot_tamper(self):
        Path(self.page["font"]["path"]).unlink()
        r = self.preview.render(self.generate,self.candidate,self.scene)
        self.preview.validate_persisted(self.candidate,self.scene,r["receipt"])
        report,_ = self.service.load_verified(self.prepared.ref())
        source = Path(report["source_snapshot"]["artifact_ref"]["uri"])
        source.write_bytes(source.read_bytes()+b"changed")
        with self.assertRaises(CartoError): self.compiler.validate_scene(self.scene,self.context)

    def test_signed_but_wrong_receipt_bindings_and_output_drift(self):
        r = self.freeze_and_render()
        backend = self.formal._backend(self.work/"output"/self.lock["lock_id"]/"formal-map")
        for key,value in [("environment_fingerprint","sha256:"+"0"*64), ("resource_evidence",[]),
                          ("scene_digest","sha256:"+"0"*64), ("viewport",{"width_px":1,"height_px":1,"device_pixel_ratio":1})]:
            receipt=deepcopy(r["receipt"]);receipt[key]=value
            receipt["renderer_attestation"]=compute_renderer_attestation(receipt,KEY)
            with self.assertRaises(CartoError):backend.validate_receipt(self.scene,receipt)
        bad=deepcopy(r["receipt"]);bad["renderer_attestation"]="0"*64
        with self.assertRaises(SecurityError):backend.validate_receipt(self.scene,bad)
        with self.assertRaises(ProtocolError):backend.validate_receipt(self.scene,r["receipt"],expected_session_id="other-attempt")
        artifact=Path(r["receipt"]["output_artifacts"][0]["artifact_ref"]["uri"])
        artifact.write_bytes(b"bad")
        with self.assertRaises(CartoError):backend.validate_receipt(self.scene,r["receipt"])
        report=self.check_rendered()
        self.assertEqual("failed",report["status"])
        with self.assertRaises(ProtocolError):self.manifest()

    def test_recovered_formal_attempt_is_identical_and_not_overwritten(self):
        r=self.freeze_and_render()
        recovered=self.formal.load_existing(request=self.generate,lock=self.lock,lock_ref=self.lock_ref,
            scene=self.scene,attempt_number=1)
        self.assertEqual(r["attempt"],recovered["attempt"])
        self.assertEqual(r["evidence"],recovered["evidence"])
        with self.assertRaises(ProtocolError):self.formal.render(request=self.generate,lock=self.lock,
            lock_ref=self.lock_ref,scene=self.scene,attempt_number=1,started_at=utc_now())
        lock=deepcopy(self.lock);lock["execution"]["environment"]["runtime"]["gdal"]="drift"
        with self.assertRaises(ProtocolError):self.formal.validate_environment(lock,self.preview_result["receipt"])


if __name__ == "__main__":
    unittest.main()
