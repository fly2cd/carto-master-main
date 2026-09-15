from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path

SCRIPTS_ROOT = Path(__file__).resolve().parents[1]
AGENT_ROOT = SCRIPTS_ROOT.parent
POLICIES = AGENT_ROOT / "policies"
if str(SCRIPTS_ROOT) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_ROOT))

from carto_core.adapters.qgis_probe import QgisEnvironmentProbe
from carto_core.adapters.mcp import McpAdapter, McpCapabilityDescriptor
from carto_core.adapters.tool_gateway import ToolGateway
from carto_core.canonical import sha256_digest
from carto_core.compiler.dependencies import DependencyResolver
from carto_core.compiler.ownership import OwnershipResolver
from carto_core.compiler.protocol import CompileRequest, ProtocolCompiler
from carto_core.errors import ProtocolError, SecurityError
from carto_core.repository.immutable_store import ImmutableArtifactStore
from carto_core.repository.knowledge import DomainKnowledgeService
from carto_core.schema_registry import SchemaRegistry
from carto_core.security.approval import ApprovalReceipt, InMemoryNonceStore, sign_receipt
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
        capability = self.resolver.resolve({"text": "洪涝应急图", "fields": self.fields("emergency_mapping"), "required_capabilities": ["qgis-render"], "available_capabilities": []})
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

    def test_qgis_probe_always_returns_valid_replayable_fingerprint(self) -> None:
        result = QgisEnvironmentProbe(timeout_seconds=2).run()
        SchemaRegistry().validate("environment-fingerprint", result)
        self.assertTrue(result["fingerprint"].startswith("sha256:"))
        if result["status"] == "unavailable":
            self.assertEqual(result["error"]["code"], "CAPABILITY_NOT_AVAILABLE")

    def test_environment_cli_returns_structured_result(self) -> None:
        completed = subprocess.run([sys.executable, str(SCRIPTS_ROOT / "carto.py"), "environment", "probe-qgis"], capture_output=True, text=True, check=False)
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertIn("environment", json.loads(completed.stdout))


if __name__ == "__main__":
    unittest.main()
