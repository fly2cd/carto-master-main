from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from copy import deepcopy
from dataclasses import asdict
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import patch
import sys

import yaml

SCRIPTS_ROOT = Path(__file__).resolve().parents[1]
TESTS_ROOT = Path(__file__).resolve().parent
for root in (SCRIPTS_ROOT, TESTS_ROOT):
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))

import test_up2_template as up2
from carto_core.adapters.controlled_renderer import discover_browser
from carto_core.canonical import sha256_digest
from carto_core.compiler.map_lock import MapSpecLockCompiler
from carto_core.errors import ProtocolError, SecurityError
from carto_core.schema_registry import load_document
from carto_core.security.approval import ApprovalReceipt, SqliteNonceStore, sign_receipt
from carto_core.workflow.approvals import ApprovalGateCoordinator
from carto_core.workflow.map_generation import MapGenerationWorkflow
from carto_core.workflow.map_preview import MapPreviewService, freeze_object_digest

APPROVAL_KEY = b"map-generation-approval-key-32-bytes"
RENDER_KEY = b"map-generation-render-key-32-bytes"
REPOSITORY_SCOPE = "local:templates"


def write_yaml(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(value, allow_unicode=True, sort_keys=False), encoding="utf-8")


def file_digest(path: Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


class MapGenerationWorkflowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.temp = tempfile.TemporaryDirectory()
        cls.root = Path(cls.temp.name)
        helper = up2.TemplateWorkflowTests(methodName="runTest")
        project, request, workdir, workflow, brief = helper._ready(cls.root)
        workflow.author(request, helper._approval(project, brief), approval_key=up2.KEY,
                        nonce_db="author.sqlite3", policy_id="carto-security", issuer="trusted-local")
        validated = workflow.validate(request, attestation_key=RENDER_KEY)
        evidence = validated["evidence"]
        now = datetime.now(UTC)
        approval = ApprovalReceipt(
            1, "publish-for-generation", "trusted-local", "reviewer-one", "tenant-one",
            "approve-template-publish", "template-publication",
            sha256_digest({"package_digest": evidence["package_ref"]["digest"],
                           "evidence_digest": evidence["evidence_digest"],
                           "repository_scope": REPOSITORY_SCOPE}),
            REPOSITORY_SCOPE, "carto-security", "local",
            (now - timedelta(minutes=1)).isoformat(), (now + timedelta(minutes=10)).isoformat(),
            "publish-generation-nonce-0001",
        )
        approval_path = project / "publish-generation.yaml"
        write_yaml(approval_path, asdict(sign_receipt(approval, up2.KEY)))
        published = workflow.publish(
            request, approval_path, repository_root="template-repository",
            repository_scope=REPOSITORY_SCOPE, idempotency_key="publish-generation-template-0001",
            approval_key=up2.KEY, renderer_attestation_key=RENDER_KEY,
            nonce_db="publish.sqlite3", policy_id="carto-security", issuer="trusted-local",
        )
        cls.repository = project / "template-repository"
        cls.template_digest = published["publication"]["package_ref"]["digest"]
        cls.font = next((path for path in (
            Path(r"C:\Windows\Fonts\NotoSansSC-VF.ttf"), Path(r"C:\Windows\Fonts\msyh.ttc"),
            Path("/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc"),
            Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"),
        ) if path.is_file()), None)

    @classmethod
    def tearDownClass(cls) -> None:
        cls.temp.cleanup()

    def _workflow(self, suffix: str):
        if self.font is None:
            self.skipTest("Pinned test font is unavailable")
        project = self.root / f"map-{suffix}"
        data = project / "data"
        data.mkdir(parents=True)
        risk = data / "risk.geojson"
        shelter = data / "shelters.geojson"
        risk.write_text(json.dumps({"type": "FeatureCollection", "features": [
            {"type": "Feature", "id": "r1", "properties": {"risk_col": 12.0}, "geometry": {"type": "Polygon", "coordinates": [[[112.0, 28.0], [112.4, 28.0], [112.4, 28.4], [112.0, 28.4], [112.0, 28.0]]]}},
            {"type": "Feature", "id": "r2", "properties": {"risk_col": 75.0}, "geometry": {"type": "Polygon", "coordinates": [[[112.5, 28.0], [112.9, 28.0], [112.9, 28.4], [112.5, 28.4], [112.5, 28.0]]]}},
        ]}, ensure_ascii=False), encoding="utf-8")
        shelter.write_text(json.dumps({"type": "FeatureCollection", "features": [
            {"type": "Feature", "id": "s1", "properties": {"people_col": 120}, "geometry": {"type": "Point", "coordinates": [112.2, 28.2]}},
            {"type": "Feature", "id": "s2", "properties": {"people_col": 350}, "geometry": {"type": "Point", "coordinates": [112.7, 28.2]}},
        ]}, ensure_ascii=False), encoding="utf-8")
        now = datetime.now(UTC).isoformat()
        refs = [
            {"id": "risk-source", "version": "1.0.0", "digest": file_digest(risk), "uri": str(risk)},
            {"id": "shelter-source", "version": "1.0.0", "digest": file_digest(shelter), "uri": str(shelter)},
        ]
        request = {
            "schema_version": 1, "request_id": f"request-{suffix}", "run_id": f"run-{suffix}",
            "project_id": f"project-{suffix}", "goal": "?????????",
            "scene_hint": "emergency_mapping", "audience": "??????",
            "sources": refs, "requested_outputs": ["svg", "png", "pdf"],
            "subject": {"subject_id": "operator-one", "tenant_id": "tenant-one",
                        "namespace": "local", "approver_subject_id": "reviewer-one"},
            "idempotency_key": f"generate-{suffix}-00000001", "scope": f"project:project-{suffix}",
            "environment": "local", "requested_at": now,
            "template": {"namespace": "local", "kind": "map-scenario", "id": "urban-flood-risk",
                         "version": "1.0.0", "digest": self.template_digest},
            "allowed_capabilities": ["read", "filter", "classify", "render-preview"],
            "source_bindings": [
                {"role": "risk-area", "source_ref": refs[0], "path": str(risk), "format": "geojson",
                 "crs": {"authority": "EPSG", "code": "4326"}, "geometry_types": ["polygon"],
                 "field_bindings": [{"semantic_role": "risk-value", "source_field": "risk_col", "value_type": "number"}],
                 "unit_bindings": [{"semantic_role": "risk-value", "unit": "percent"}],
                 "freshness": {"observed_at": now, "max_age_days": 1}, "join": {"required": False}, "synthetic": True},
                {"role": "shelter-point", "source_ref": refs[1], "path": str(shelter), "format": "geojson",
                 "crs": {"authority": "EPSG", "code": "4326"}, "geometry_types": ["point"],
                 "field_bindings": [{"semantic_role": "count-value", "source_field": "people_col", "value_type": "integer"}],
                 "unit_bindings": [{"semantic_role": "count-value", "unit": "people"}],
                 "freshness": {"observed_at": now, "max_age_days": 1}, "join": {"required": False}, "synthetic": True},
            ],
            "font": {"path": str(self.font), "family": "Noto Sans SC", "version": "1.0.0"},
        }
        request_path = project / "generate-request.yaml"
        write_yaml(request_path, request)
        workflow = MapGenerationWorkflow(
            allowed_roots=[self.root, self.font.parent], project_root=project, workdir="generation",
            repository_root=self.repository, repository_scope=REPOSITORY_SCOPE,
        )
        return project, request_path, request, workflow

    @staticmethod
    def _approval(project: Path, request: dict, digest: str, *, gate: str, nonce: str) -> Path:
        now = datetime.now(UTC)
        action, object_type = (("approve-map-brief", "map-brief") if gate == "G1"
                               else ("approve-freeze", "resolved-map"))
        value = ApprovalReceipt(
            1, f"approval-{gate.lower()}-{request['run_id']}", "trusted-local", "reviewer-one", "tenant-one",
            action, object_type, digest, request["scope"], "carto-security", request["environment"],
            (now - timedelta(minutes=1)).isoformat(), (now + timedelta(minutes=10)).isoformat(), nonce,
        )
        path = project / f"approval-{gate.lower()}.yaml"
        write_yaml(path, asdict(sign_receipt(value, APPROVAL_KEY)))
        return path

    def test_up25_rejects_source_geometry_mismatch(self) -> None:
        project, request_path, request, workflow = self._workflow("geometry-mismatch")
        risk_path = Path(request["source_bindings"][0]["path"])
        document = json.loads(risk_path.read_text(encoding="utf-8"))
        document["features"][0]["geometry"] = {"type": "Point", "coordinates": [112.2, 28.2]}
        risk_path.write_text(json.dumps(document), encoding="utf-8")
        digest = file_digest(risk_path)
        request["sources"][0]["digest"] = digest
        request["source_bindings"][0]["source_ref"]["digest"] = digest
        write_yaml(request_path, request)

        workflow.intake(request_path)
        brief = workflow.brief(request_path)["brief"]
        approval = self._approval(
            project, request, sha256_digest(brief), gate="G1", nonce="map-g1-geometry-00000001"
        )
        with self.assertRaises(ProtocolError) as raised:
            workflow.compile(
                request_path, approval, approval_key=APPROVAL_KEY,
                nonce_db="g1.sqlite3", policy_id="carto-security", issuer="trusted-local",
            )
        self.assertEqual("SOURCE_GEOMETRY_TYPE_INVALID", raised.exception.code)

    def test_up25_rejects_source_digest_drift_after_brief(self) -> None:
        project, request_path, request, workflow = self._workflow("source-drift")
        workflow.intake(request_path)
        brief = workflow.brief(request_path)["brief"]
        approval = self._approval(
            project, request, sha256_digest(brief), gate="G1", nonce="map-g1-source-drift-00000001"
        )
        risk_path = Path(request["source_bindings"][0]["path"])
        risk_path.write_bytes(risk_path.read_bytes() + b"\n")
        with self.assertRaises(ProtocolError) as raised:
            workflow.compile(
                request_path, approval, approval_key=APPROVAL_KEY,
                nonce_db="g1.sqlite3", policy_id="carto-security", issuer="trusted-local",
            )
        self.assertEqual("SOURCE_DIGEST_MISMATCH", raised.exception.code)

    def test_up26_rejects_g2_digest_for_changed_freeze_object(self) -> None:
        if discover_browser() is None:
            self.skipTest("Chromium browser is unavailable")
        project, request_path, request, workflow = self._workflow("g2-binding")
        workflow.intake(request_path)
        brief = workflow.brief(request_path)["brief"]
        g1 = self._approval(
            project, request, sha256_digest(brief), gate="G1", nonce="map-g1-g2-binding-00000001"
        )
        compiled = workflow.compile(
            request_path, g1, approval_key=APPROVAL_KEY,
            nonce_db="g1.sqlite3", policy_id="carto-security", issuer="trusted-local",
        )
        preview = workflow.preview(request_path, attestation_key=RENDER_KEY)
        changed = deepcopy(preview["evidence"])
        changed["environment_fingerprint"] = "sha256:" + "0" * 64
        wrong_digest = freeze_object_digest(request, compiled["candidate"], changed)
        g2 = self._approval(
            project, request, wrong_digest, gate="G2", nonce="map-g2-binding-00000001"
        )
        with self.assertRaises(SecurityError) as raised:
            workflow.freeze(
                request_path, g2, approval_key=APPROVAL_KEY, attestation_key=RENDER_KEY,
                nonce_db="g2.sqlite3", policy_id="carto-security", issuer="trusted-local",
            )
        self.assertEqual("APPROVAL_OBJECT_MISMATCH", raised.exception.code)

    def test_up26_rejects_preview_output_tampering(self) -> None:
        if discover_browser() is None:
            self.skipTest("Chromium browser is unavailable")
        project, request_path, request, workflow = self._workflow("output-drift")
        workflow.intake(request_path)
        brief = workflow.brief(request_path)["brief"]
        g1 = self._approval(
            project, request, sha256_digest(brief), gate="G1", nonce="map-g1-output-drift-00000001"
        )
        compiled = workflow.compile(
            request_path, g1, approval_key=APPROVAL_KEY,
            nonce_db="g1.sqlite3", policy_id="carto-security", issuer="trusted-local",
        )
        preview = workflow.preview(request_path, attestation_key=RENDER_KEY)
        g2 = self._approval(
            project, request, freeze_object_digest(request, compiled["candidate"], preview["evidence"]),
            gate="G2", nonce="map-g2-output-drift-00000001",
        )
        output_path = Path(preview["evidence"]["output_artifacts"][0]["artifact_ref"]["uri"])
        payload = bytearray(output_path.read_bytes())
        payload[-1] ^= 1
        output_path.write_bytes(payload)
        with self.assertRaises(ProtocolError) as raised:
            workflow.freeze(
                request_path, g2, approval_key=APPROVAL_KEY, attestation_key=RENDER_KEY,
                nonce_db="g2.sqlite3", policy_id="carto-security", issuer="trusted-local",
            )
        self.assertEqual("RENDER_OUTPUT_DIGEST_MISMATCH", raised.exception.code)

    def test_up26_consumes_g2_nonce_once(self) -> None:
        if discover_browser() is None:
            self.skipTest("Chromium browser is unavailable")
        project, request_path, request, workflow = self._workflow("g2-replay")
        workflow.intake(request_path)
        brief = workflow.brief(request_path)["brief"]
        g1 = self._approval(
            project, request, sha256_digest(brief), gate="G1", nonce="map-g1-g2-replay-00000001"
        )
        compiled = workflow.compile(
            request_path, g1, approval_key=APPROVAL_KEY,
            nonce_db="g1.sqlite3", policy_id="carto-security", issuer="trusted-local",
        )
        preview = workflow.preview(request_path, attestation_key=RENDER_KEY)
        digest = freeze_object_digest(request, compiled["candidate"], preview["evidence"])
        g2 = self._approval(
            project, request, digest, gate="G2", nonce="map-g2-replay-00000001"
        )
        workflow.freeze(
            request_path, g2, approval_key=APPROVAL_KEY, attestation_key=RENDER_KEY,
            nonce_db="g2.sqlite3", policy_id="carto-security", issuer="trusted-local",
        )
        receipt = ApprovalReceipt.from_dict(load_document(g2))
        coordinator = ApprovalGateCoordinator(
            APPROVAL_KEY, SqliteNonceStore(str(project / "g2.sqlite3")), "carto-security", "trusted-local"
        )
        with self.assertRaises(SecurityError) as raised:
            coordinator.require(
                "G2", receipt, digest, workflow._context(request),
                approver_subject_id=request["subject"]["approver_subject_id"], expected_scope=request["scope"],
            )
        self.assertEqual("APPROVAL_REPLAYED", raised.exception.code)
    def test_up26_recovers_lock_written_before_workflow_state(self) -> None:
        if discover_browser() is None:
            self.skipTest("Chromium browser is unavailable")
        project, request_path, request, workflow = self._workflow("freeze-state-recovery")
        workflow.intake(request_path)
        brief = workflow.brief(request_path)["brief"]
        g1 = self._approval(
            project, request, sha256_digest(brief), gate="G1",
            nonce="map-g1-freeze-state-recovery-0001",
        )
        compiled = workflow.compile(
            request_path, g1, approval_key=APPROVAL_KEY,
            nonce_db="g1.sqlite3", policy_id="carto-security", issuer="trusted-local",
        )
        preview = workflow.preview(request_path, attestation_key=RENDER_KEY)
        g2 = self._approval(
            project, request,
            freeze_object_digest(request, compiled["candidate"], preview["evidence"]),
            gate="G2", nonce="map-g2-freeze-state-recovery-0001",
        )
        with patch.object(
            workflow.state_store, "complete_step", side_effect=OSError("injected state failure")
        ):
            with self.assertRaises(OSError):
                workflow.freeze(
                    request_path, g2, approval_key=APPROVAL_KEY, attestation_key=RENDER_KEY,
                    nonce_db="g2.sqlite3", policy_id="carto-security", issuer="trusted-local",
                )

        lock_path = project / "generation/locks" / f"lock-{request['run_id']}" / "map-spec-lock.yaml"
        original_bytes = lock_path.read_bytes()
        recovered_workflow = MapGenerationWorkflow(
            allowed_roots=[self.root, self.font.parent], project_root=project,
            workdir="generation", repository_root=self.repository,
            repository_scope=REPOSITORY_SCOPE,
        )
        recovered = recovered_workflow.freeze(
            request_path, g2, approval_key=APPROVAL_KEY, attestation_key=RENDER_KEY,
            nonce_db="g2.sqlite3", policy_id="carto-security", issuer="trusted-local",
        )
        self.assertTrue(recovered["idempotent_replay"])
        self.assertEqual("pending", recovered["state"]["status"])
        self.assertEqual("render", recovered["state"]["step"])
        self.assertEqual(original_bytes, lock_path.read_bytes())
        self.assertEqual(
            sha256_digest(recovered["lock"]),
            recovered_workflow.state_store.find_output_digest("map-spec-lock"),
        )
        receipt_count = len(recovered_workflow.state_store.receipts())
        replay = recovered_workflow.freeze(
            request_path, g2, approval_key=APPROVAL_KEY, attestation_key=RENDER_KEY,
            nonce_db="g2.sqlite3", policy_id="carto-security", issuer="trusted-local",
        )
        self.assertTrue(replay["idempotent_replay"])
        self.assertEqual(receipt_count, len(recovered_workflow.state_store.receipts()))

    def test_up26_existing_lock_requires_exact_context_and_consumed_nonce(self) -> None:
        if discover_browser() is None:
            self.skipTest("Chromium browser is unavailable")
        project, request_path, request, workflow = self._workflow("freeze-forged-lock")
        workflow.intake(request_path)
        brief = workflow.brief(request_path)["brief"]
        g1 = self._approval(
            project, request, sha256_digest(brief), gate="G1",
            nonce="map-g1-freeze-forged-lock-0001",
        )
        compiled = workflow.compile(
            request_path, g1, approval_key=APPROVAL_KEY,
            nonce_db="g1.sqlite3", policy_id="carto-security", issuer="trusted-local",
        )
        preview = workflow.preview(request_path, attestation_key=RENDER_KEY)
        g2 = self._approval(
            project, request,
            freeze_object_digest(request, compiled["candidate"], preview["evidence"]),
            gate="G2", nonce="map-g2-freeze-forged-lock-0001",
        )
        preflight = load_document(project / "generation/candidates/preflight-report.yaml")
        render_receipt = load_document(project / "generation/candidates/render-receipt.yaml")
        lock = MapSpecLockCompiler(workflow.registry).compile(
            request, compiled["candidate"], preview["evidence"], render_receipt, preflight,
            brief_approval_ref="approvals/g1-map-brief.yaml", freeze_approval_ref=str(g2),
        )
        lock_path = project / "generation/locks" / lock["lock_id"] / "map-spec-lock.yaml"
        tampered = deepcopy(lock)
        tampered["candidate_ref"]["digest"] = "sha256:" + "0" * 64
        write_yaml(lock_path, tampered)
        with self.assertRaises(ProtocolError) as mismatch:
            workflow.freeze(
                request_path, g2, approval_key=APPROVAL_KEY, attestation_key=RENDER_KEY,
                nonce_db="g2.sqlite3", policy_id="carto-security", issuer="trusted-local",
            )
        self.assertEqual("MAP_SPEC_LOCK_CONTEXT_MISMATCH", mismatch.exception.code)

        write_yaml(lock_path, lock)
        with self.assertRaises(SecurityError) as unconsumed:
            workflow.freeze(
                request_path, g2, approval_key=APPROVAL_KEY, attestation_key=RENDER_KEY,
                nonce_db="g2.sqlite3", policy_id="carto-security", issuer="trusted-local",
            )
        self.assertEqual("APPROVAL_NONCE_NOT_CONSUMED", unconsumed.exception.code)

    def test_up25_rejects_installed_contract_tampering_before_preview(self) -> None:
        project, request_path, request, workflow = self._workflow("installed-contract-drift")
        workflow.intake(request_path)
        brief = workflow.brief(request_path)["brief"]
        approval = self._approval(
            project, request, sha256_digest(brief), gate="G1", nonce="map-g1-contract-drift-00000001"
        )
        workflow.compile(
            request_path, approval, approval_key=APPROVAL_KEY,
            nonce_db="g1.sqlite3", policy_id="carto-security", issuer="trusted-local",
        )
        installation = load_document(project / "generation/templates/installed-template.yaml")
        contract_path = Path(installation["package_path"]) / "contracts/scenario.yaml"
        contract_path.write_bytes(contract_path.read_bytes() + b"\n")
        with self.assertRaises(ProtocolError) as raised:
            workflow.preview(request_path, attestation_key=RENDER_KEY)
        self.assertEqual("TEMPLATE_INSTALL_FILE_DRIFT", raised.exception.code)

    def test_up25_rejects_installation_not_bound_to_published_index(self) -> None:
        project, request_path, request, workflow = self._workflow("install-index-binding")
        workflow.intake(request_path)
        brief = workflow.brief(request_path)["brief"]
        approval = self._approval(
            project, request, sha256_digest(brief), gate="G1", nonce="map-g1-index-binding-00000001"
        )
        workflow.compile(
            request_path, approval, approval_key=APPROVAL_KEY,
            nonce_db="g1.sqlite3", policy_id="carto-security", issuer="trusted-local",
        )
        installation_path = project / "generation/templates/installed-template.yaml"
        installation = load_document(installation_path)
        installation["template_ref"]["digest"] = "sha256:" + "0" * 64
        write_yaml(installation_path, installation)
        with self.assertRaises(ProtocolError) as raised:
            workflow.preview(request_path, attestation_key=RENDER_KEY)
        self.assertEqual("TEMPLATE_INSTALL_PACKAGE_DRIFT", raised.exception.code)

    def test_up26_rejects_incomplete_or_rebound_preview_evidence(self) -> None:
        if discover_browser() is None:
            self.skipTest("Chromium browser is unavailable")
        project, request_path, request, workflow = self._workflow("evidence-binding")
        workflow.intake(request_path)
        brief = workflow.brief(request_path)["brief"]
        g1 = self._approval(
            project, request, sha256_digest(brief), gate="G1", nonce="map-g1-evidence-binding-00000001"
        )
        compiled = workflow.compile(
            request_path, g1, approval_key=APPROVAL_KEY,
            nonce_db="g1.sqlite3", policy_id="carto-security", issuer="trusted-local",
        )
        preview = workflow.preview(request_path, attestation_key=RENDER_KEY)
        candidate = compiled["candidate"]
        scene = compiled["scene"]
        receipt = preview["receipt"]

        rebound = deepcopy(preview["evidence"])
        rebound["output_artifacts"] = rebound["output_artifacts"][:-1]
        rebound_body = dict(rebound)
        rebound_body.pop("evidence_digest")
        rebound["evidence_digest"] = sha256_digest(rebound_body)
        with self.assertRaises(ProtocolError) as raised:
            MapPreviewService.validate_evidence(rebound, candidate, scene, receipt, workflow.registry)
        self.assertEqual("PREVIEW_EVIDENCE_BINDING_MISMATCH", raised.exception.code)

        incomplete = deepcopy(preview["evidence"])
        incomplete["checks"][0]["owner"] = "data"
        incomplete_body = dict(incomplete)
        incomplete_body.pop("evidence_digest")
        incomplete["evidence_digest"] = sha256_digest(incomplete_body)
        with self.assertRaises(ProtocolError) as raised:
            MapPreviewService.validate_evidence(incomplete, candidate, scene, receipt, workflow.registry)
        self.assertEqual("PREVIEW_EVIDENCE_OWNER_COVERAGE_MISMATCH", raised.exception.code)

        duplicate = deepcopy(preview["evidence"])
        duplicate["checks"][1]["check_id"] = duplicate["checks"][0]["check_id"]
        duplicate_body = dict(duplicate)
        duplicate_body.pop("evidence_digest")
        duplicate["evidence_digest"] = sha256_digest(duplicate_body)
        with self.assertRaises(ProtocolError) as raised:
            MapPreviewService.validate_evidence(duplicate, candidate, scene, receipt, workflow.registry)
        self.assertEqual("PREVIEW_EVIDENCE_CHECK_DUPLICATE", raised.exception.code)

    def test_up25_recovers_consumed_g1_before_candidate_materialization(self) -> None:
        project, request_path, request, workflow = self._workflow("g1-recovery-before-candidate")
        workflow.intake(request_path)
        brief = workflow.brief(request_path)["brief"]
        approval = self._approval(
            project, request, sha256_digest(brief), gate="G1",
            nonce="map-g1-recovery-before-candidate-0001",
        )
        with patch.object(
            workflow,
            "_compile_approved_candidate",
            side_effect=OSError("injected crash after G1 consumption"),
        ):
            with self.assertRaises(OSError):
                workflow.compile(
                    request_path, approval, approval_key=APPROVAL_KEY,
                    nonce_db="g1.sqlite3", policy_id="carto-security",
                    issuer="trusted-local",
                )
        self.assertTrue((project / "generation/approvals/g1-map-brief.yaml").is_file())
        self.assertFalse((project / "generation/candidates/resolved-map.yaml").exists())

        recovered_workflow = MapGenerationWorkflow(
            allowed_roots=[self.root, self.font.parent], project_root=project,
            workdir="generation", repository_root=self.repository,
            repository_scope=REPOSITORY_SCOPE,
        )
        recovered = recovered_workflow.compile(
            request_path, approval, approval_key=APPROVAL_KEY,
            nonce_db="g1.sqlite3", policy_id="carto-security",
            issuer="trusted-local",
        )
        self.assertEqual("preview", recovered["state"]["step"])
        self.assertTrue(recovered["idempotent_replay"])

    def test_up25_recovers_candidate_written_before_workflow_state(self) -> None:
        project, request_path, request, workflow = self._workflow("g1-recovery-after-candidate")
        workflow.intake(request_path)
        brief = workflow.brief(request_path)["brief"]
        approval = self._approval(
            project, request, sha256_digest(brief), gate="G1",
            nonce="map-g1-recovery-after-candidate-0001",
        )
        with patch.object(
            workflow.state_store,
            "complete_step",
            side_effect=OSError("injected crash after candidate materialization"),
        ):
            with self.assertRaises(OSError):
                workflow.compile(
                    request_path, approval, approval_key=APPROVAL_KEY,
                    nonce_db="g1.sqlite3", policy_id="carto-security",
                    issuer="trusted-local",
                )
        candidate_path = project / "generation/candidates/resolved-map.yaml"
        before = candidate_path.read_bytes()

        recovered_workflow = MapGenerationWorkflow(
            allowed_roots=[self.root, self.font.parent], project_root=project,
            workdir="generation", repository_root=self.repository,
            repository_scope=REPOSITORY_SCOPE,
        )
        recovered = recovered_workflow.compile(
            request_path, approval, approval_key=APPROVAL_KEY,
            nonce_db="g1.sqlite3", policy_id="carto-security",
            issuer="trusted-local",
        )
        self.assertEqual(before, candidate_path.read_bytes())
        self.assertEqual("preview", recovered["state"]["step"])
        self.assertTrue(recovered["idempotent_replay"])

    def test_up25_compiles_candidate_without_rendering(self) -> None:
        project, request_path, request, workflow = self._workflow("compile")
        workflow.intake(request_path)
        brief = workflow.brief(request_path)["brief"]
        approval = self._approval(project, request, sha256_digest(brief), gate="G1", nonce="map-g1-compile-00000001")
        result = workflow.compile(request_path, approval, approval_key=APPROVAL_KEY,
                                  nonce_db="g1.sqlite3", policy_id="carto-security", issuer="trusted-local")
        self.assertEqual("preview", result["state"]["step"])
        self.assertEqual(result["candidate"]["execution_digest"], sha256_digest(result["candidate"]["execution"]))
        self.assertEqual("risk_value", result["candidate"]["execution"]["shared_semantics"]["field_bindings"]["risk-area"]["risk-value"])
        self.assertFalse((project / "generation/previews").exists())
        self.assertFalse((project / "generation/locks").exists())

    def test_up26_renders_preview_and_freezes_exact_candidate(self) -> None:
        if discover_browser() is None:
            self.skipTest("Chromium browser is unavailable")
        project, request_path, request, workflow = self._workflow("freeze")
        workflow.intake(request_path)
        brief = workflow.brief(request_path)["brief"]
        g1 = self._approval(project, request, sha256_digest(brief), gate="G1", nonce="map-g1-freeze-00000001")
        compiled = workflow.compile(request_path, g1, approval_key=APPROVAL_KEY,
                                    nonce_db="g1.sqlite3", policy_id="carto-security", issuer="trusted-local")
        preview = workflow.preview(request_path, attestation_key=RENDER_KEY)
        self.assertEqual({"svg", "png", "pdf"}, {item["target"] for item in preview["evidence"]["output_artifacts"]})
        g2_digest = freeze_object_digest(request, compiled["candidate"], preview["evidence"])
        g2 = self._approval(project, request, g2_digest, gate="G2", nonce="map-g2-freeze-00000001")
        frozen = workflow.freeze(request_path, g2, approval_key=APPROVAL_KEY, attestation_key=RENDER_KEY,
                                 nonce_db="g2.sqlite3", policy_id="carto-security", issuer="trusted-local")
        self.assertEqual("pending", frozen["state"]["status"])
        self.assertEqual("render", frozen["state"]["step"])
        self.assertEqual(compiled["candidate"]["execution"], frozen["lock"]["execution"])
        self.assertEqual(preview["evidence"]["evidence_digest"], frozen["lock"]["preview_evidence_digest"])
        self.assertFalse((project / "generation/delivery").exists())


if __name__ == "__main__":
    unittest.main()
