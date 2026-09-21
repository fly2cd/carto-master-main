from __future__ import annotations

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
from carto_core.canonical import sha256_digest
from carto_core.errors import ProtocolError, SecurityError
from carto_core.repository.template_repository import TemplateRepository
from carto_core.security.approval import ApprovalReceipt, sign_receipt
from carto_core.security.paths import PathGuard
from carto_core.workflow.template_validation import TemplatePackageValidator


RENDER_KEY = b"up24-render-attestation-key-32-bytes"
SCOPE = "local:templates"


class TemplateValidationPublicationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.helper = up2.TemplateWorkflowTests(methodName="runTest")

    def _author(self, root: Path):
        project, request, workdir, workflow, brief = self.helper._ready(root)
        workflow.author(
            request,
            self.helper._approval(project, brief),
            approval_key=up2.KEY,
            nonce_db="author-nonces.sqlite3",
            policy_id="carto-security",
            issuer="trusted-local",
        )
        return project, request, workdir, workflow

    def _validated(self, root: Path):
        project, request, workdir, workflow = self._author(root)
        result = workflow.validate(request, attestation_key=RENDER_KEY)
        self.assertEqual("passed", result["evidence"]["status"])
        return project, request, workdir, workflow, result["evidence"]

    @staticmethod
    def _publication_object(evidence: dict, scope: str = SCOPE) -> dict:
        return {
            "package_digest": evidence["package_ref"]["digest"],
            "evidence_digest": evidence["evidence_digest"],
            "repository_scope": scope,
        }

    def _publication_approval(
        self,
        project: Path,
        evidence: dict,
        *,
        suffix: str,
        action: str = "approve-template-publish",
        object_type: str = "template-publication",
        subject_id: str = "reviewer-one",
        receipt_scope: str = SCOPE,
        object_scope: str = SCOPE,
    ) -> Path:
        now = datetime.now(UTC)
        unsigned = ApprovalReceipt(
            1,
            f"publication-approval-{suffix}",
            "trusted-local",
            subject_id,
            "tenant-one",
            action,
            object_type,
            sha256_digest(self._publication_object(evidence, object_scope)),
            receipt_scope,
            "carto-security",
            "local",
            (now - timedelta(minutes=1)).isoformat(),
            (now + timedelta(minutes=10)).isoformat(),
            f"publication-nonce-{suffix}-00000001",
        )
        path = project / f"publication-approval-{suffix}.yaml"
        up2._write_yaml(path, asdict(sign_receipt(unsigned, up2.KEY)))
        return path

    def _publish(self, workflow, request: Path, approval: Path | None, *, key: str):
        return workflow.publish(
            request,
            approval,
            repository_root="template-repository",
            repository_scope=SCOPE,
            idempotency_key=key,
            approval_key=up2.KEY,
            renderer_attestation_key=RENDER_KEY,
            nonce_db="publication-nonces.sqlite3",
            policy_id="carto-security",
            issuer="trusted-local",
        )

    def test_full_validate_publish_discover_and_idempotent_replay(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            project, request, workdir, workflow, evidence = self._validated(root)
            self.assertEqual({"svg", "png", "pdf"}, {item["target"] for item in evidence["preview_artifacts"]})
            for item in evidence["preview_artifacts"]:
                artifact = Path(item["artifact_ref"]["uri"])
                self.assertTrue(artifact.is_file())
                self.assertGreater(artifact.stat().st_size, 0)

            approval = self._publication_approval(project, evidence, suffix="full")
            first = self._publish(workflow, request, approval, key="publish-flood-full-0001")
            self.assertFalse(first["idempotent_replay"])
            self.assertEqual("succeeded", first["state"]["status"])

            repository = TemplateRepository(
                path_guard=PathGuard([root]),
                root=project / "template-repository",
                repository_scope=SCOPE,
            )
            entry = repository.discover(
                namespace="local", kind="map-scenario", template_id="urban-flood-risk", version="1.0.0",
            )
            self.assertEqual(evidence["package_ref"]["digest"], entry["digest"])
            self.assertEqual(evidence["evidence_digest"], entry["evidence_digest"])

            replay = self._publish(workflow, request, None, key="publish-flood-full-0001")
            self.assertTrue(replay["idempotent_replay"])
            self.assertEqual(first["publication"], replay["publication"])

    def test_publish_recovers_repository_commit_before_workflow_state(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            project, request, workdir, workflow, evidence = self._validated(root)
            approval = self._publication_approval(project, evidence, suffix="state-recovery")
            with patch.object(
                workflow.state_store, "complete_step", side_effect=OSError("injected state failure")
            ):
                with self.assertRaises(OSError):
                    self._publish(
                        workflow, request, approval, key="publish-state-recovery-0001"
                    )

            self.assertEqual("publish", workflow.state_store.load().step)
            self.assertNotEqual("succeeded", workflow.state_store.load().status)
            self.assertEqual(
                1, len(list((project / "template-repository/transactions").glob("*.yaml")))
            )

            recovered_workflow = up2.TemplateCreationWorkflow(
                allowed_roots=[root], project_root=project, workdir=workdir
            )
            recovered = self._publish(
                recovered_workflow, request, None, key="publish-state-recovery-0001"
            )
            self.assertTrue(recovered["idempotent_replay"])
            self.assertEqual("succeeded", recovered["state"]["status"])
            self.assertEqual(
                sha256_digest(recovered["publication"]),
                recovered_workflow.state_store.find_output_digest("publication-receipt"),
            )
            receipt_count = len(recovered_workflow.state_store.receipts())
            replay = self._publish(
                recovered_workflow, request, None, key="publish-state-recovery-0001"
            )
            self.assertTrue(replay["idempotent_replay"])
            self.assertEqual(receipt_count, len(recovered_workflow.state_store.receipts()))

    def test_static_failure_does_not_invoke_renderer_and_failed_evidence_is_blocking(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            project, request, workdir, workflow = self._author(root)
            fixture = workdir / "staging/package/fixtures/flood-risk.synthetic.geojson"
            fixture.write_bytes(fixture.read_bytes() + b" ")
            invoked: list[bool] = []
            with patch(
                "carto_core.workflow.template_validation.discover_browser",
                side_effect=AssertionError("browser discovery must not run before static validation passes"),
            ):
                validator = TemplatePackageValidator(
                    path_guard=workflow.path_guard,
                    package_root=workdir / "staging/package",
                    evidence_root=workdir / "failed-validation",
                    attestation_key=RENDER_KEY,
                    render_hook=lambda: invoked.append(True),
                )
                request_value = yaml.safe_load(request.read_text(encoding="utf-8"))
                evidence = validator.validate(workflow._expected_validation(request_value), request_value["targets"])
            self.assertEqual("failed", evidence["status"])
            self.assertGreater(evidence["counts"]["blocker"], 0)
            self.assertEqual([], invoked)
            self.assertNotIn("render_receipt_ref", evidence)
            with self.assertRaises(ProtocolError) as raised:
                validator.verify_evidence(evidence, workflow._expected_validation(request_value), request_value["targets"])
            self.assertEqual("TEMPLATE_VALIDATION_FAILED", raised.exception.code)

    def test_package_and_preview_drift_are_rejected_before_publication(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            project, request, workdir, workflow, evidence = self._validated(root)
            fixture = workdir / "staging/package/fixtures/flood-risk.synthetic.geojson"
            fixture.write_bytes(fixture.read_bytes() + b" ")
            approval = self._publication_approval(project, evidence, suffix="package-drift")
            with self.assertRaises(ProtocolError) as raised:
                self._publish(workflow, request, approval, key="publish-package-drift-0001")
            self.assertEqual("PACKAGE_CHECKSUM_MISMATCH", raised.exception.code)

        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            project, request, _, workflow, evidence = self._validated(root)
            preview = Path(evidence["preview_artifacts"][0]["artifact_ref"]["uri"])
            preview.write_bytes(preview.read_bytes() + b"tampered")
            approval = self._publication_approval(project, evidence, suffix="preview-drift")
            with self.assertRaises(ProtocolError) as raised:
                self._publish(workflow, request, approval, key="publish-preview-drift-0001")
            self.assertEqual("VALIDATION_PREVIEW_DRIFT", raised.exception.code)

    def test_renderer_binding_drift_is_rejected_even_with_rehashed_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            _, request, workdir, workflow, evidence = self._validated(root)
            changed = deepcopy(evidence)
            changed["renderer"]["environment_fingerprint"] = "sha256:" + "f" * 64
            body = dict(changed)
            body.pop("evidence_digest")
            changed["evidence_digest"] = sha256_digest(body)
            validator = TemplatePackageValidator(
                path_guard=workflow.path_guard,
                package_root=workdir / "staging/package",
                evidence_root=workdir / "validation",
                attestation_key=RENDER_KEY,
            )
            request_value = yaml.safe_load(request.read_text(encoding="utf-8"))
            with self.assertRaises(ProtocolError) as raised:
                validator.verify_evidence(changed, workflow._expected_validation(request_value), request_value["targets"])
            self.assertEqual("VALIDATION_RENDERER_BINDING_MISMATCH", raised.exception.code)

    def test_publication_approval_binds_gate_identity_object_scope_and_nonce(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            project, request, _, workflow, evidence = self._validated(root)
            cases = [
                ("action", {"action": "approve-map-brief", "object_type": "map-brief"}, "APPROVAL_ACTION_MISMATCH"),
                ("identity", {"subject_id": "reviewer-two"}, "APPROVAL_IDENTITY_MISMATCH"),
                ("scope", {"receipt_scope": "project:project-one"}, "APPROVAL_SCOPE_MISMATCH"),
                ("object", {"object_scope": "other:templates"}, "APPROVAL_OBJECT_MISMATCH"),
            ]
            for suffix, overrides, code in cases:
                with self.subTest(binding=suffix):
                    approval = self._publication_approval(project, evidence, suffix=suffix, **overrides)
                    with self.assertRaises(SecurityError) as raised:
                        self._publish(workflow, request, approval, key=f"publish-invalid-{suffix}-0001")
                    self.assertEqual(code, raised.exception.code)

            approval = self._publication_approval(project, evidence, suffix="valid")
            self._publish(workflow, request, approval, key="publish-valid-approval-0001")
            with self.assertRaises(SecurityError) as replay:
                self._publish(workflow, request, approval, key="publish-valid-approval-0002")
            self.assertEqual("APPROVAL_REPLAYED", replay.exception.code)

    def test_repository_conflicts_and_index_only_discovery(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            project, request, workdir, workflow, evidence = self._validated(root)
            approval = self._publication_approval(project, evidence, suffix="repository")
            self._publish(workflow, request, approval, key="publish-repository-0001")
            repository = TemplateRepository(
                path_guard=PathGuard([root]), root=project / "template-repository", repository_scope=SCOPE,
            )
            restricted_repository = TemplateRepository(
                path_guard=PathGuard([project]), root=project / "restricted-repository", repository_scope=SCOPE,
            )
            outside_package = root / "outside-package"
            outside_package.mkdir()
            with self.assertRaises(SecurityError) as outside:
                restricted_repository.publish(
                    package_root=outside_package, snapshot={}, evidence={}, approval={},
                    idempotency_key="publish-outside-package-0001",
                )
            self.assertEqual("PATH_OUTSIDE_ALLOWED_ROOT", outside.exception.code)
            with self.assertRaises(ProtocolError) as conflict:
                repository.lookup_idempotency(
                    "publish-repository-0001",
                    package_digest="sha256:" + "f" * 64,
                    evidence_digest=evidence["evidence_digest"],
                )
            self.assertEqual("IDEMPOTENCY_CONFLICT", conflict.exception.code)

            snapshot = TemplatePackageValidator(
                path_guard=workflow.path_guard,
                package_root=workdir / "staging/package",
                evidence_root=workdir / "validation",
                attestation_key=RENDER_KEY,
            ).inspect(workflow._expected_validation(yaml.safe_load(request.read_text(encoding="utf-8"))), ["svg", "pdf", "png"])
            changed_snapshot = deepcopy(snapshot)
            changed_snapshot["package_digest"] = "sha256:" + "e" * 64
            with self.assertRaises(ProtocolError) as version_conflict:
                repository.publish(
                    package_root=workdir / "staging/package",
                    snapshot=changed_snapshot,
                    evidence=evidence,
                    approval=yaml.safe_load(approval.read_text(encoding="utf-8")),
                    idempotency_key="publish-version-conflict-0001",
                )
            self.assertEqual("VERSION_CONFLICT", version_conflict.exception.code)

            residue = project / "template-repository/packages/local/map-scenario/residue/9.9.9"
            residue.mkdir(parents=True)
            (residue / "manifest.yaml").write_text("residue: true\n", encoding="utf-8")
            with self.assertRaises(ProtocolError) as unindexed:
                repository.discover(namespace="local", kind="map-scenario", template_id="residue", version="9.9.9")
            self.assertEqual("TEMPLATE_NOT_INDEXED", unindexed.exception.code)
            with self.assertRaises(ProtocolError) as inexact:
                repository.discover(namespace="local", kind="map-scenario", template_id="urban-flood-risk", version="")
            self.assertEqual("EXACT_TEMPLATE_REF_REQUIRED", inexact.exception.code)

    def test_repository_detects_published_package_corruption(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            project, request, _, workflow, evidence = self._validated(root)
            approval = self._publication_approval(project, evidence, suffix="corruption")
            self._publish(workflow, request, approval, key="publish-corruption-0001")
            repository = TemplateRepository(
                path_guard=PathGuard([root]), root=project / "template-repository", repository_scope=SCOPE,
            )
            entry = repository.discover(namespace="local", kind="map-scenario", template_id="urban-flood-risk", version="1.0.0")
            manifest = project / "template-repository" / entry["manifest_path"]
            original = manifest.read_bytes()
            manifest.write_bytes(original + b" ")
            with self.assertRaises(ProtocolError) as manifest_error:
                repository.discover(namespace="local", kind="map-scenario", template_id="urban-flood-risk", version="1.0.0")
            self.assertEqual("PUBLISHED_MANIFEST_CORRUPT", manifest_error.exception.code)
            manifest.write_bytes(original)
            contract = manifest.parent / "contracts/scenario.yaml"
            contract.write_bytes(contract.read_bytes() + b" ")
            with self.assertRaises(ProtocolError) as package_error:
                repository.discover(namespace="local", kind="map-scenario", template_id="urban-flood-risk", version="1.0.0")
            self.assertEqual("PUBLISHED_PACKAGE_CORRUPT", package_error.exception.code)


if __name__ == "__main__":
    unittest.main()

