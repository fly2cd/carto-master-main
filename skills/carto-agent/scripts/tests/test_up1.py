from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from copy import deepcopy
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path

SCRIPTS_ROOT = Path(__file__).resolve().parents[1]
AGENT_ROOT = SCRIPTS_ROOT.parent
POLICIES = AGENT_ROOT / "policies"
if str(SCRIPTS_ROOT) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_ROOT))

from carto_core.adapters.renderer_probe import RendererCapabilityProbe
from carto_core.adapters.mcp import McpAdapter, McpCapabilityDescriptor
from carto_core.adapters.svg_compositor import SvgCompositor
from carto_core.adapters.tool_gateway import ToolGateway
from carto_core.adapters.webmap_renderer import (
    RenderReceiptValidator,
    RenderSessionGateway,
    RendererCapabilityProfile,
    RendererCapabilityRegistry,
    WebMapRendererAdapter,
    compute_renderer_attestation,
)
from carto_core.canonical import sha256_digest
from carto_core.compiler.dependencies import DependencyResolver
from carto_core.compiler.ownership import OwnershipResolver
from carto_core.compiler.protocol import CompileRequest, ProtocolCompiler
from carto_core.errors import ProtocolError, SecurityError
from carto_core.repository.immutable_store import ImmutableArtifactStore
from carto_core.repository.knowledge import DomainKnowledgeService
from carto_core.schema_registry import SchemaRegistry
from carto_core.security.approval import ApprovalReceipt, InMemoryNonceStore, sign_receipt
from carto_core.security.paths import PathGuard
from carto_core.workflow.agent_runtime import AgentSubmission, BoundedAgentRuntime
from carto_core.workflow.approvals import ApprovalGateCoordinator, GATES
from carto_core.workflow.data_preparation import DeterministicDataPreparer
from carto_core.workflow.intent import IntentResolver, TaskDispatcher
from carto_core.workflow.models import ExecutionBudget, ExecutionContext
from carto_core.workflow.state_machine import WorkflowStateStore
from carto_core.validation.registry import CheckerRegistry
from tests.fixtures.schema_cases import VALID_CASES


def context(**overrides: object) -> ExecutionContext:
    values = {
        "run_id": "run-one",
        "tenant_id": "tenant-one",
        "project_id": "project-one",
        "subject_id": "operator-one",
        "roles": frozenset({"operator"}),
        "namespaces": frozenset({"project-one"}),
        "authorized_capabilities": frozenset({"schema-validate"}),
    }
    values.update(overrides)
    return ExecutionContext(**values)


class StateAndRepositoryTests(unittest.TestCase):
    def test_state_receipt_is_immutable_and_resume_detects_drift(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            store = WorkflowStateStore(Path(temp) / "run")
            inputs = {"request": "map"}
            state = store.initialize("run-one", inputs)
            output_ref = {"id": "state", "version": "1.0.0", "digest": sha256_digest(state.to_dict())}
            state, receipt = store.complete_step(state, status="succeeded", prerequisites={"policy": {"version": 1}}, output_refs=[output_ref], tool_versions={"schema-validate": "1.0.0"}, next_step="intent")
            self.assertTrue((store.run_root / state.last_receipt).is_file())
            self.assertEqual(receipt.step, "intake")
            store.resume(inputs, {"policy": {"version": 1}})
            with self.assertRaises(ProtocolError) as raised:
                store.resume({"request": "changed"}, {"policy": {"version": 1}})
            self.assertEqual(raised.exception.code, "JOB_INPUT_DRIFT")

    def test_immutable_store_is_content_addressed(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            store = ImmutableArtifactStore(Path(temp))
            first = store.put("artifact-one", "1.0.0", {"value": 1})
            second = store.put("artifact-one", "1.0.0", {"value": 1})
            self.assertEqual(first.path, second.path)
            self.assertEqual(store.get(first), {"value": 1})


class ToolAndKnowledgeTests(unittest.TestCase):
    def test_gateway_rejects_unknown_and_unauthorized_capabilities(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            gateway = ToolGateway(POLICIES / "tool-bindings.yaml", ImmutableArtifactStore(Path(temp)))
            gateway.register("schema-validate", lambda value, _: {"valid": bool(value)})
            with self.assertRaises(SecurityError) as unknown:
                gateway.invoke("mcp-discovered-only", {}, context())
            self.assertEqual(unknown.exception.code, "CAPABILITY_UNREGISTERED")
            with self.assertRaises(SecurityError) as denied:
                gateway.invoke("schema-validate", {}, context(authorized_capabilities=frozenset()))
            self.assertEqual(denied.exception.code, "CAPABILITY_SCOPE_DENIED")

    def test_gateway_pins_typed_output_and_enforces_budget(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            gateway = ToolGateway(POLICIES / "tool-bindings.yaml", ImmutableArtifactStore(Path(temp)))
            gateway.register("schema-validate", lambda value, _: {"valid": value["valid"]})
            ctx = context(budget=ExecutionBudget(max_tool_calls=1))
            result = gateway.invoke("schema-validate", {"valid": True}, ctx)
            self.assertEqual(result.status, "succeeded")
            self.assertTrue(Path(result.artifact_refs[0]["uri"]).is_file())
            with self.assertRaises(ProtocolError) as raised:
                gateway.invoke("schema-validate", {"valid": True}, ctx)
            self.assertEqual(raised.exception.code, "EXECUTION_BUDGET_EXCEEDED")

    def test_mcp_discovery_does_not_grant_authorization(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            gateway = ToolGateway(POLICIES / "tool-bindings.yaml", ImmutableArtifactStore(Path(temp)))
            adapter = McpAdapter("example-mcp", [McpCapabilityDescriptor("example-mcp", "mcp-discovered-only", {})])
            self.assertEqual(adapter.discover()[0].capability_id, "mcp-discovered-only")
            with self.assertRaises(SecurityError) as raised:
                adapter.bind(gateway, "mcp-discovered-only", lambda value, _: value)
            self.assertEqual(raised.exception.code, "CAPABILITY_UNREGISTERED")

    def test_knowledge_returns_versioned_evidence_and_denies_unregistered_source(self) -> None:
        record = {"source_id": "approved-standard-catalog", "publisher": "标准机构", "version": "2026", "source_ref": "catalog:label", "content": "道路标注应按比例尺控制密度", "applicability": {"jurisdiction": "general", "valid_from": "2026-01-01"}}
        service = DomainKnowledgeService(POLICIES / "knowledge-sources.yaml", [record])
        evidence = service.lookup_or_search("道路 标注", "general", context())
        self.assertEqual(evidence[0].source["version"], "2026")
        SchemaRegistry().validate("knowledge-evidence", evidence[0].to_dict())
        bad = dict(record, source_id="web-search")
        with self.assertRaises(SecurityError):
            DomainKnowledgeService(POLICIES / "knowledge-sources.yaml", [bad]).lookup_or_search("道路", "general", context())
        self.assertFalse(service.external_search_allowed())


class IntentAndRuntimeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.resolver = IntentResolver(POLICIES / "intent-profiles.yaml")

    @staticmethod
    def fields(scene: str) -> dict[str, str]:
        if scene == "government_thematic":
            return {"theme": "经济发展", "geography": "示例市", "time": "2026", "source": "统计数据", "output": "A3 PDF"}
        if scene == "emergency_mapping":
            return {"hazard": "flood", "event-phase": "response", "data-nature": "observed", "observation-time": "2026-09-15", "geography": "示例市", "source": "应急数据", "output": "A3 PDF"}
        return {"itinerary": "甲地至乙地", "visit-order": "1,2", "route-mode": "road", "geography": "示例市", "confidentiality": "internal", "output": "A3 PDF"}

    def test_three_business_scenes_resolve_and_dispatch(self) -> None:
        texts = {"government_thematic": "制作经济发展政务专题图", "emergency_mapping": "制作洪涝应急灾情图", "leadership_visit": "制作领导调研行程路线图"}
        for scene, text in texts.items():
            with self.subTest(scene=scene):
                intent = self.resolver.resolve({"intent_id": f"intent-{scene.replace('_', '-')}", "text": text, "fields": self.fields(scene)})
                self.assertEqual(intent["business_scene"], scene)
                self.assertEqual(intent["readiness_status"], "ready")
                self.assertTrue(TaskDispatcher().dispatch(intent))

    def test_ambiguity_missing_information_capability_and_rejection_are_distinct(self) -> None:
        ambiguous = self.resolver.resolve({"text": "政务专题与洪涝应急地图", "fields": {}})
        self.assertEqual(ambiguous["intent_status"], "ambiguous")
        missing = self.resolver.resolve({"text": "洪涝应急图", "fields": {}})
        self.assertEqual(missing["readiness_status"], "missing_information")
        capability = self.resolver.resolve({"text": "洪涝应急图", "fields": self.fields("emergency_mapping"), "required_capabilities": ["web-map-export"], "available_capabilities": []})
        self.assertEqual(capability["readiness_status"], "missing_capability")
        rejected = self.resolver.resolve({"text": "写一首诗", "fields": {}})
        self.assertEqual(rejected["intent_status"], "unsupported")

    def test_agent_runtime_accepts_only_typed_non_executable_candidates(self) -> None:
        runtime = BoundedAgentRuntime()
        accepted = runtime.submit(AgentSubmission("planner", "map-plan", VALID_CASES["map-plan"], "planner-1.0.0"), context())
        self.assertTrue(accepted["accepted"])
        candidate = dict(VALID_CASES["map-plan"], shell="rm -rf data")
        with self.assertRaises(SecurityError) as raised:
            runtime.submit(AgentSubmission("planner", "map-plan", candidate, "planner-1.0.0"), context())
        self.assertEqual(raised.exception.code, "MODEL_EXECUTABLE_CONTENT_DENIED")
        limited = context(budget=ExecutionBudget(max_revisions=1))
        runtime.repair(limited)
        with self.assertRaises(ProtocolError):
            runtime.repair(limited)

    def test_sensitive_values_do_not_cross_role_context(self) -> None:
        staged = BoundedAgentRuntime.stage_context("planner", {"intent": {"itinerary": "secret", "coordinates": [1, 2]}, "raw_credentials": "token", "data_summary": "safe"})
        self.assertNotIn("raw_credentials", staged)
        self.assertEqual(staged["intent"]["itinerary"], "[REDACTED]")


class ProtocolAndGateTests(unittest.TestCase):
    def test_dependency_and_ownership_conflicts_are_blocking(self) -> None:
        self.assertEqual(DependencyResolver().resolve(["scenario"], {"base": [], "scenario": ["base"]}), ["base", "scenario"])
        with self.assertRaises(ProtocolError):
            DependencyResolver().resolve(["a"], {"a": ["b"], "b": ["a"]})
        with self.assertRaises(ProtocolError):
            OwnershipResolver().merge([("map-style", {"color": "blue"}), ("project", {"color": "red"})])

    def test_compiler_and_validation_modules_return_structured_results(self) -> None:
        compiled = ProtocolCompiler().compile(CompileRequest(contracts=(("state", "job-state", VALID_CASES["job-state"]),), dependency_graph={"state": []}, root_contracts=("state",)))
        self.assertEqual(compiled["order"], ["state"])
        self.assertTrue(compiled["digest"].startswith("sha256:"))
        registry = CheckerRegistry(POLICIES / "checker-registry.yaml")
        registry.register("protocol.schema-valid", lambda subject, _: (isinstance(subject, dict), {"schema": "test"}))
        report = registry.run("validate", {"value": 1})
        self.assertEqual(report.status, "passed")
        SchemaRegistry().validate("validation-report", report.to_dict())

    def test_g1_g2_g3_verify_exact_context(self) -> None:
        key = b"test-only-secret-that-is-at-least-32-bytes"
        coordinator = ApprovalGateCoordinator(key, InMemoryNonceStore(), "carto-security", "trusted-local")
        now = datetime.now(UTC)
        for index, (gate_id, gate) in enumerate(GATES.items(), 1):
            digest = sha256_digest({"gate": gate_id})
            unsigned = ApprovalReceipt(1, f"receipt-{gate_id.lower()}", "trusted-local", "reviewer-one", "tenant-one", gate.action, gate.object_type, digest, "project:project-one", "carto-security", "local", (now - timedelta(minutes=1)).isoformat(), (now + timedelta(minutes=10)).isoformat(), f"nonce-{index:016d}")
            coordinator.require(gate_id, sign_receipt(unsigned, key), digest, context())
        wrong = replace(unsigned, nonce="nonce-9999999999999999", object_digest=sha256_digest({"wrong": True}))
        with self.assertRaises(SecurityError):
            coordinator.require("G3", sign_receipt(wrong, key), sha256_digest({"expected": True}), context())

    def test_deterministic_data_preparation_returns_valid_bundle(self) -> None:
        bundle = DeterministicDataPreparer(POLICIES / "data-preparation-policy.yaml").prepare_data(VALID_CASES["data-preparation-task"], context())
        SchemaRegistry().validate("prepared-data-bundle", bundle)
        self.assertTrue(bundle["quality_evidence"])

    def test_renderer_probe_always_returns_valid_replayable_fingerprint(self) -> None:
        result = RendererCapabilityProbe(timeout_seconds=2).run()
        SchemaRegistry().validate("environment-fingerprint", result)
        self.assertTrue(result["fingerprint"].startswith("sha256:"))
        self.assertEqual(result["probe_id"], "renderer-capability-probe")
        self.assertIn(result["status"], {"available", "unavailable"})
        if result["status"] == "available":
            self.assertTrue(result["capabilities"]["webgl_available"])
            self.assertTrue(result["capabilities"]["headless_export"])
            self.assertNotIn("error", result)
        else:
            self.assertFalse(result["capabilities"]["headless_export"])
            self.assertEqual(result["error"]["code"], "CAPABILITY_NOT_AVAILABLE")

    def test_environment_cli_returns_structured_result(self) -> None:
        completed = subprocess.run([sys.executable, str(SCRIPTS_ROOT / "carto.py"), "environment", "probe-renderer"], capture_output=True, text=True, check=False)
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertIn("environment", json.loads(completed.stdout))


class WebMapRendererAdapterTests(unittest.TestCase):
    @staticmethod
    def profile(
        *,
        renderer_id: str = "maplibre-web",
        formats: tuple[str, ...] = ("svg", "png"),
        width: int = 16384,
        height: int = 16384,
    ) -> RendererCapabilityProfile:
        return RendererCapabilityProfile(
            renderer_id=renderer_id,
            frontend_build="2026.09.15",
            renderer_version="1.0.0",
            maplibre_version="3.6.0",
            overlay_engine_version="1.0.0",
            browser_engine="Chromium 117.0",
            webgl_available=True,
            supported_export_formats=formats,
            max_canvas_width=width,
            max_canvas_height=height,
            device_pixel_ratio=2.0,
            available_fonts=("Noto Sans CJK SC",),
            offline_rendering=True,
        )

    def submitted(self) -> tuple[WebMapRendererAdapter, RendererCapabilityProfile, dict[str, object]]:
        profile = self.profile()
        adapter = WebMapRendererAdapter(RendererCapabilityRegistry([profile]))
        scene = deepcopy(VALID_CASES["render-scene"])
        adapter.submit_render("session-one", scene, profile.renderer_id, profile.frontend_build)
        return adapter, profile, scene

    @staticmethod
    def signed_receipt(
        profile: RendererCapabilityProfile,
        scene: dict[str, object],
        key: bytes,
    ) -> dict[str, object]:
        receipt = deepcopy(VALID_CASES["render-receipt"])
        receipt["scene_digest"] = sha256_digest(scene)
        receipt["renderer_profile_digest"] = profile.profile_digest()
        evidence = [
            {"resource_id": item["resource_id"], "digest": item["digest"], "status": item["status"]}
            for item in sorted(receipt["resource_evidence"], key=lambda item: item["resource_id"])
        ]
        receipt["resource_set_digest"] = sha256_digest(evidence)
        receipt["execution_digest"] = sha256_digest({
            "scene_digest": receipt["scene_digest"],
            "resource_set_digest": receipt["resource_set_digest"],
            "renderer_profile_digest": receipt["renderer_profile_digest"],
            "environment_fingerprint": receipt["environment_fingerprint"],
            "random_seed": receipt["random_seed"],
        })
        receipt["renderer_attestation"] = compute_renderer_attestation(receipt, key)
        return receipt

    def test_compile_scene_validates_render_scene_schema(self) -> None:
        adapter = WebMapRendererAdapter()
        scene = deepcopy(VALID_CASES["render-scene"])
        compiled = adapter.compile_scene(scene)
        self.assertEqual(compiled["renderer_id"], "maplibre-web")
        SchemaRegistry().validate("render-scene", compiled)

    def test_compile_scene_rejects_duplicate_and_broken_references(self) -> None:
        adapter = WebMapRendererAdapter()
        duplicate = deepcopy(VALID_CASES["render-scene"])
        duplicate["resources"].append(deepcopy(duplicate["resources"][0]))
        with self.assertRaises(ProtocolError) as raised:
            adapter.compile_scene(duplicate)
        self.assertEqual(raised.exception.code, "RENDER_SCENE_DUPLICATE_ID")

        broken = deepcopy(VALID_CASES["render-scene"])
        broken["map"]["layers"][0]["source_id"] = "missing-source"
        with self.assertRaises(ProtocolError) as raised:
            adapter.compile_scene(broken)
        self.assertEqual(raised.exception.code, "RENDER_LAYER_SOURCE_UNKNOWN")

    def test_schema_rejects_overlay_without_coordinate_or_type_payload(self) -> None:
        scene = deepcopy(VALID_CASES["render-scene"])
        del scene["overlays"][0]["position"]
        with self.assertRaises(ProtocolError):
            SchemaRegistry().validate("render-scene", scene)
        scene = deepcopy(VALID_CASES["render-scene"])
        del scene["overlays"][0]["content"]
        with self.assertRaises(ProtocolError):
            SchemaRegistry().validate("render-scene", scene)

    def test_submit_render_rejects_untrusted_renderer(self) -> None:
        adapter = WebMapRendererAdapter()
        scene = deepcopy(VALID_CASES["render-scene"])
        with self.assertRaises(SecurityError) as raised:
            adapter.submit_render("session-one", scene, "untrusted-renderer", "2026.09.15")
        self.assertEqual(raised.exception.code, "RENDERER_NOT_TRUSTED")

    def test_submit_render_accepts_trusted_renderer(self) -> None:
        profile = self.profile()
        adapter = WebMapRendererAdapter(RendererCapabilityRegistry([profile]))
        scene = deepcopy(VALID_CASES["render-scene"])
        result = adapter.submit_render("session-one", scene, "maplibre-web", "2026.09.15")
        self.assertEqual(result["status"], "submitted")
        self.assertEqual(result["renderer_profile_digest"], profile.profile_digest())

    def test_submit_rejects_renderer_export_and_viewport_mismatches(self) -> None:
        profile = self.profile()
        adapter = WebMapRendererAdapter(RendererCapabilityRegistry([profile]))
        scene = deepcopy(VALID_CASES["render-scene"])
        scene["renderer_id"] = "other-renderer"
        scene["renderer_requirements"]["renderer_id"] = "other-renderer"
        with self.assertRaises(SecurityError) as raised:
            adapter.submit_render("session-renderer", scene, profile.renderer_id, profile.frontend_build)
        self.assertEqual(raised.exception.code, "RENDERER_SCENE_MISMATCH")

        adapter = WebMapRendererAdapter(RendererCapabilityRegistry([self.profile(formats=("svg",))]))
        with self.assertRaises(ProtocolError) as raised:
            adapter.submit_render("session-export", deepcopy(VALID_CASES["render-scene"]), "maplibre-web", "2026.09.15")
        self.assertEqual(raised.exception.code, "RENDER_EXPORT_UNSUPPORTED")

        adapter = WebMapRendererAdapter(RendererCapabilityRegistry([self.profile(width=1000)]))
        with self.assertRaises(ProtocolError) as raised:
            adapter.submit_render("session-viewport", deepcopy(VALID_CASES["render-scene"]), "maplibre-web", "2026.09.15")
        self.assertEqual(raised.exception.code, "RENDER_VIEWPORT_UNSUPPORTED")

    def test_render_receipt_validation(self) -> None:
        adapter, profile, scene = self.submitted()
        key = b"render-attestation-key-32-bytes!!"
        receipt = self.signed_receipt(profile, scene, key)
        adapter.validate_receipt(receipt, key)

        with self.assertRaises(ProtocolError) as raised:
            adapter.validate_receipt(receipt, key)
        self.assertEqual(raised.exception.code, "RENDER_SESSION_STATE_INVALID")

        adapter, profile, scene = self.submitted()
        receipt = self.signed_receipt(profile, scene, key)
        tampered = deepcopy(receipt)
        tampered["warnings"] = ["modified after signing"]
        with self.assertRaises(SecurityError) as raised:
            adapter.validate_receipt(tampered, key)
        self.assertEqual(raised.exception.code, "RENDER_ATTESTATION_INVALID")

    def test_submitted_scene_is_an_immutable_snapshot(self) -> None:
        adapter, profile, scene = self.submitted()
        key = b"render-attestation-key-32-bytes!!"
        receipt = self.signed_receipt(profile, scene, key)
        scene["viewport"]["width_px"] = 1
        scene["resources"][0]["ref"]["digest"] = "sha256:" + "f" * 64
        adapter.validate_receipt(receipt, key)

    def test_render_receipt_rejects_binding_time_and_resource_failures(self) -> None:
        key = b"render-attestation-key-32-bytes!!"
        adapter, profile, scene = self.submitted()
        receipt = self.signed_receipt(profile, scene, key)
        receipt["renderer_version"] = "9.0.0"
        receipt["renderer_attestation"] = compute_renderer_attestation(receipt, key)
        with self.assertRaises(ProtocolError) as raised:
            adapter.validate_receipt(receipt, key)
        self.assertEqual(raised.exception.code, "RENDER_RECEIPT_BINDING_MISMATCH")

        receipt = self.signed_receipt(profile, scene, key)
        receipt["render_completed_at"] = "2026-09-14T23:59:59Z"
        receipt["renderer_attestation"] = compute_renderer_attestation(receipt, key)
        with self.assertRaises(ProtocolError) as raised:
            adapter.validate_receipt(receipt, key)
        self.assertEqual(raised.exception.code, "RENDER_RECEIPT_TIME_INVALID")

        receipt = self.signed_receipt(profile, scene, key)
        receipt["resource_evidence"][0]["status"] = "missing"
        receipt["renderer_attestation"] = compute_renderer_attestation(receipt, key)
        with self.assertRaises(ProtocolError) as raised:
            adapter.validate_receipt(receipt, key)
        self.assertEqual(raised.exception.code, "RENDER_REQUIRED_RESOURCE_NOT_LOADED")

        receipt = self.signed_receipt(profile, scene, key)
        receipt["resource_evidence"].append({
            "resource_id": "unknown-resource",
            "status": "loaded",
            "digest": "sha256:" + "f" * 64,
        })
        receipt["renderer_attestation"] = compute_renderer_attestation(receipt, key)
        with self.assertRaises(ProtocolError) as raised:
            adapter.validate_receipt(receipt, key)
        self.assertEqual(raised.exception.code, "RENDER_RESOURCE_EVIDENCE_UNKNOWN")

    def test_renderer_profile_and_session_ids_are_immutable(self) -> None:
        profile = self.profile()
        registry = RendererCapabilityRegistry([profile])
        with self.assertRaises(SecurityError):
            registry.register(profile)
        adapter = WebMapRendererAdapter(registry)
        scene = deepcopy(VALID_CASES["render-scene"])
        adapter.submit_render("session-one", scene, profile.renderer_id, profile.frontend_build)
        with self.assertRaises(ProtocolError) as raised:
            adapter.submit_render("session-one", scene, profile.renderer_id, profile.frontend_build)
        self.assertEqual(raised.exception.code, "RENDER_SESSION_DUPLICATE")


class SvgCompositorTests(unittest.TestCase):
    def test_compose_creates_svg_with_image_and_overlay(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            screenshot = root / "map.png"
            screenshot.write_bytes(b"\x89PNG\r\n\x1a\n")
            output = root / "output.svg"
            compositor = SvgCompositor(800, 600, PathGuard([root]))
            overlays = [{"id": "title", "type": "text", "coordinate_space": "page", "position": {"x": 0.5, "y": 0.1, "unit": "normalized"}, "content": "Test Map"}]
            compositor.compose(screenshot, overlays, output)
            self.assertTrue(output.exists())
            text = output.read_text(encoding="utf-8")
            self.assertIn("<svg", text)
            self.assertIn("Test Map", text)
            self.assertIn('x="400"', text)

    def test_compose_supports_declared_overlay_vocabulary(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            screenshot = root / "map.jpg"
            screenshot.write_bytes(b"\xff\xd8\xff\xe0")
            overlays = [
                {"id": "symbol-one", "type": "symbol", "coordinate_space": "geographic", "screen_position": {"x": 20, "y": 30, "unit": "pixel"}, "symbol_ref": "icon-one", "label": "Point"},
                {"id": "legend-one", "type": "legend", "coordinate_space": "page", "position": {"x": 10, "y": 50, "unit": "pixel"}, "legend_items": [{"label": "Risk", "color": "#FF0000"}]},
                {"id": "north-one", "type": "north-arrow", "coordinate_space": "page", "position": {"x": 760, "y": 40, "unit": "pixel"}},
                {"id": "scale-one", "type": "scale-bar", "coordinate_space": "page", "position": {"x": 20, "y": 570, "unit": "pixel"}, "length_px": 100, "distance_label": "10 km"},
            ]
            output = root / "supported.svg"
            SvgCompositor(800, 600, PathGuard([root])).compose(screenshot, overlays, output)
            text = output.read_text(encoding="utf-8")
            self.assertIn("10 km", text)
            self.assertIn("north-one", text)
            self.assertIn("legend-one", text)

    def test_compose_rejects_unresolved_and_unsupported_overlays(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            screenshot = root / "map.png"
            screenshot.write_bytes(b"\x89PNG\r\n\x1a\n")
            compositor = SvgCompositor(800, 600, PathGuard([root]))
            unresolved = {"id": "point-one", "type": "symbol", "coordinate_space": "geographic", "anchor": {"longitude": 1, "latitude": 1}, "symbol_ref": "icon-one"}
            with self.assertRaises(ProtocolError) as raised:
                compositor.compose(screenshot, [unresolved], root / "unresolved.svg")
            self.assertEqual(raised.exception.code, "OVERLAY_COORDINATE_UNRESOLVED")

            unsupported = {"id": "custom-one", "type": "custom", "coordinate_space": "page", "position": {"x": 1, "y": 1, "unit": "pixel"}}
            with self.assertRaises(ProtocolError) as raised:
                compositor.compose(screenshot, [unsupported], root / "unsupported.svg")
            self.assertEqual(raised.exception.code, "OVERLAY_TYPE_UNSUPPORTED")

    def test_compose_enforces_allowed_roots_and_output_immutability(self) -> None:
        with tempfile.TemporaryDirectory() as temp, tempfile.TemporaryDirectory() as outside:
            root = Path(temp)
            screenshot = root / "map.png"
            screenshot.write_bytes(b"\x89PNG\r\n\x1a\n")
            compositor = SvgCompositor(800, 600, PathGuard([root]))
            overlays = [{"id": "title", "type": "text", "coordinate_space": "page", "position": {"x": 10, "y": 20, "unit": "pixel"}, "content": "Map"}]
            with self.assertRaises(SecurityError) as raised:
                compositor.compose(screenshot, overlays, Path(outside) / "escaped.svg")
            self.assertEqual(raised.exception.code, "PATH_OUTSIDE_ALLOWED_ROOT")

            output = root / "existing.svg"
            output.write_text("existing", encoding="utf-8")
            with self.assertRaises(SecurityError) as raised:
                compositor.compose(screenshot, overlays, output)
            self.assertEqual(raised.exception.code, "COMPOSITE_OUTPUT_EXISTS")

    def test_inline_font_rejects_css_injection_family(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            screenshot = root / "map.png"
            screenshot.write_bytes(b"\x89PNG\r\n\x1a\n")
            compositor = SvgCompositor(800, 600, PathGuard([root]))
            overlays = [{"id": "title", "type": "text", "coordinate_space": "page", "position": {"x": 10, "y": 20, "unit": "pixel"}, "content": "Map"}]
            with self.assertRaises(ProtocolError) as raised:
                compositor.compose(
                    screenshot,
                    overlays,
                    root / "font.svg",
                    inline_fonts=[('unsafe";}svg{display:none}', b"wOF2")],
                )
            self.assertEqual(raised.exception.code, "COMPOSITE_FONT_FAMILY_INVALID")


if __name__ == "__main__":
    unittest.main()
