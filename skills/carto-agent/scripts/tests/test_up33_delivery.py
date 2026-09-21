from __future__ import annotations

import sys
import unittest
from copy import deepcopy
from dataclasses import asdict
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import patch

SCRIPTS_ROOT = Path(__file__).resolve().parents[1]
TESTS_ROOT = Path(__file__).resolve().parent
for root in (SCRIPTS_ROOT, TESTS_ROOT):
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))

import test_up25_up26_map_generation as up26
import test_up32_final_check as up32
from carto_core.canonical import sha256_digest
from carto_core.cli import build_parser
from carto_core.errors import ProtocolError, SecurityError
from carto_core.repository.delivery_repository import DeliveryRepository
from carto_core.schema_registry import SchemaRegistry, load_document
from carto_core.security.approval import ApprovalReceipt, sign_receipt


class AtomicDeliveryWorkflowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        up32.FinalCheckWorkflowTests.setUpClass()
        cls.helper = up32.FinalCheckWorkflowTests(methodName="runTest")

    @classmethod
    def tearDownClass(cls) -> None:
        up32.FinalCheckWorkflowTests.tearDownClass()

    def _checked(self, suffix: str, *, destination: str | None = None,
                 idempotency_key: str | None = None):
        project, request_path, request, workflow, frozen, rendered = self.helper._rendered(suffix)
        checked = workflow.check(
            request_path,
            attestation_key=up26.RENDER_KEY,
            recipient_id="reviewer-one",
            recipient_type="project-user",
            destination=destination or f"deliveries/{suffix}",
            idempotency_key=idempotency_key or f"delivery-{suffix}-00000001",
        )
        return project, request_path, request, workflow, checked

    @staticmethod
    def _g3(project: Path, request: dict, manifest: dict, *, nonce: str,
            action: str = "approve-delivery", object_type: str = "delivery-manifest",
            digest: str | None = None) -> Path:
        now = datetime.now(UTC)
        value = ApprovalReceipt(
            1, f"approval-g3-{request['run_id']}", "trusted-local",
            request["subject"]["approver_subject_id"], request["subject"]["tenant_id"],
            action, object_type, digest or sha256_digest(manifest), request["scope"],
            "carto-security", request["environment"],
            (now - timedelta(minutes=1)).isoformat(),
            (now + timedelta(minutes=10)).isoformat(), nonce,
        )
        path = project / "approval-g3.yaml"
        up26.write_yaml(path, asdict(sign_receipt(value, up26.APPROVAL_KEY)))
        return path

    def _deliver(self, project, request_path, request, workflow, checked, *, suffix: str,
                 failure_hook=None):
        approval = self._g3(
            project, request, checked["delivery_manifest"],
            nonce=f"map-g3-{suffix}-00000001",
        )
        return workflow.deliver(
            request_path, approval, approval_key=up26.APPROVAL_KEY,
            nonce_db="g3.sqlite3", policy_id="carto-security", issuer="trusted-local",
            failure_hook=failure_hook,
        ), approval

    def test_up33_commits_whitelisted_package_receipt_and_query(self) -> None:
        project, request_path, request, workflow, checked = self._checked("delivery-success")
        result, approval = self._deliver(
            project, request_path, request, workflow, checked, suffix="delivery-success"
        )
        self.assertEqual(("succeeded", "deliver"), (result["state"]["status"], result["state"]["step"]))
        self.assertEqual("receipt-written", result["delivery_transaction"]["status"])
        self.assertEqual("committed", result["delivery_receipt"]["status"])
        SchemaRegistry().validate("delivery-transaction", result["delivery_transaction"])
        SchemaRegistry().validate("delivery-receipt", result["delivery_receipt"])
        final = project / checked["delivery_manifest"]["destination"]["relative_path"]
        files = {path.relative_to(final).as_posix() for path in final.rglob("*") if path.is_file()}
        self.assertEqual(
            {"map.pdf", "map.png", "README.md", "delivery-manifest.yaml", "checksums.sha256"}, files
        )
        self.assertIn("合成数据演示，非真实风险研判", (final / "README.md").read_text(encoding="utf-8"))
        forbidden_names = {"map-spec-lock.yaml", "validation-report.yaml", "render-receipt.json"}
        self.assertFalse(files & forbidden_names)
        query = workflow.delivery_status(checked["delivery_manifest"]["idempotency_key"])
        self.assertEqual(result["delivery_transaction"], query["transaction"])
        self.assertEqual(result["delivery_receipt"], query["receipt"])
        by_delivery = DeliveryRepository(
            path_guard=workflow.path_guard, project_root=workflow.project_root,
            work_root=workflow.work_root, registry=workflow.registry,
        ).lookup_delivery(result["delivery_receipt"]["delivery_id"])
        self.assertEqual(query, by_delivery)

        replay = workflow.deliver(
            request_path, approval, approval_key=up26.APPROVAL_KEY,
            nonce_db="g3.sqlite3", policy_id="carto-security", issuer="trusted-local",
        )
        self.assertTrue(replay["idempotent_replay"])
        self.assertEqual(result["delivery_receipt"], replay["delivery_receipt"])
        deliver_receipts = [
            item for item in workflow.receipts()["receipts"]
            if item["receipt"]["step"] == "deliver"
        ]
        self.assertEqual(1, len(deliver_receipts))

    def test_up33_rejects_wrong_gate_and_artifact_drift_before_delivery(self) -> None:
        project, request_path, request, workflow, checked = self._checked("delivery-reject")
        wrong = self._g3(
            project, request, checked["delivery_manifest"], nonce="map-g3-wrong-00000001",
            action="approve-freeze", object_type="resolved-map",
        )
        with self.assertRaises(SecurityError) as gate_error:
            workflow.deliver(
                request_path, wrong, approval_key=up26.APPROVAL_KEY,
                nonce_db="g3.sqlite3", policy_id="carto-security", issuer="trusted-local",
            )
        self.assertEqual("APPROVAL_ACTION_MISMATCH", gate_error.exception.code)

        wrong_object = self._g3(
            project, request, checked["delivery_manifest"], nonce="map-g3-object-00000001",
            digest="sha256:" + "0" * 64,
        )
        with self.assertRaises(SecurityError) as object_error:
            workflow.deliver(
                request_path, wrong_object, approval_key=up26.APPROVAL_KEY,
                nonce_db="g3.sqlite3", policy_id="carto-security", issuer="trusted-local",
            )
        self.assertEqual("APPROVAL_OBJECT_MISMATCH", object_error.exception.code)

        artifact = project / checked["delivery_manifest"]["artifacts"][0]["path"]
        original = artifact.read_bytes()
        artifact.write_bytes(original + b"tampered")
        good = self._g3(
            project, request, checked["delivery_manifest"], nonce="map-g3-drift-00000001"
        )
        with self.assertRaises(ProtocolError) as drift_error:
            workflow.deliver(
                request_path, good, approval_key=up26.APPROVAL_KEY,
                nonce_db="g3.sqlite3", policy_id="carto-security", issuer="trusted-local",
            )
        self.assertEqual("DELIVERY_ARTIFACT_DRIFT", drift_error.exception.code)
        self.assertEqual(("waiting_approval", "deliver"), tuple(workflow.status()["state"][key] for key in ("status", "step")))
        self.assertFalse((project / checked["delivery_manifest"]["destination"]["relative_path"]).exists())

    def test_up33_recovers_consumed_nonce_before_transaction(self) -> None:
        project, request_path, request, workflow, checked = self._checked("delivery-recover-approval")
        approval = self._g3(
            project, request, checked["delivery_manifest"], nonce="map-g3-recover-approval-0001"
        )
        def fail(phase: str) -> None:
            if phase == "after-approval-consumed":
                raise RuntimeError("injected")
        with self.assertRaises(RuntimeError):
            workflow.deliver(
                request_path, approval, approval_key=up26.APPROVAL_KEY,
                nonce_db="g3.sqlite3", policy_id="carto-security", issuer="trusted-local",
                failure_hook=fail,
            )
        result = workflow.deliver(
            request_path, approval, approval_key=up26.APPROVAL_KEY,
            nonce_db="g3.sqlite3", policy_id="carto-security", issuer="trusted-local",
        )
        self.assertEqual("succeeded", result["state"]["status"])
        self.assertTrue(result["idempotent_replay"])

    def test_up33_recovers_staged_atomic_commit_and_step_windows(self) -> None:
        for suffix, phase in (
            ("delivery-recover-intent", "after-transaction-intent"),
            ("delivery-recover-staged", "after-staging"),
            ("delivery-recover-commit", "after-atomic-commit"),
            ("delivery-recover-receipt", "after-receipt"),
            ("delivery-recover-step", "before-step-complete"),
        ):
            with self.subTest(phase=phase):
                project, request_path, request, workflow, checked = self._checked(suffix)
                approval = self._g3(
                    project, request, checked["delivery_manifest"],
                    nonce=f"map-g3-{suffix}-00000001",
                )
                def fail(current: str, expected: str = phase) -> None:
                    if current == expected:
                        raise RuntimeError("injected")
                with self.assertRaises(RuntimeError):
                    workflow.deliver(
                        request_path, approval, approval_key=up26.APPROVAL_KEY,
                        nonce_db="g3.sqlite3", policy_id="carto-security", issuer="trusted-local",
                        failure_hook=fail,
                    )
                self.assertEqual("waiting_approval", workflow.status()["state"]["status"])
                result = workflow.deliver(
                    request_path, approval, approval_key=up26.APPROVAL_KEY,
                    nonce_db="g3.sqlite3", policy_id="carto-security", issuer="trusted-local",
                )
                self.assertEqual("succeeded", result["state"]["status"])
                self.assertTrue((project / result["delivery_receipt"]["final_path"]).is_dir())

    def test_up33_staging_write_failure_leaves_no_visible_partial_delivery(self) -> None:
        project, request_path, request, workflow, checked = self._checked("delivery-disk-full")
        approval = self._g3(
            project, request, checked["delivery_manifest"], nonce="map-g3-disk-full-0001"
        )
        with patch(
            "carto_core.repository.delivery_repository.shutil.copyfile",
            side_effect=OSError("simulated disk full"),
        ):
            with self.assertRaises(ProtocolError) as raised:
                workflow.deliver(
                    request_path, approval, approval_key=up26.APPROVAL_KEY,
                    nonce_db="g3.sqlite3", policy_id="carto-security", issuer="trusted-local",
                )
        self.assertEqual("DELIVERY_STAGING_WRITE_FAILED", raised.exception.code)
        final = project / checked["delivery_manifest"]["destination"]["relative_path"]
        self.assertFalse(final.exists())
        self.assertFalse(any(final.parent.glob(f".{final.name}.staging-*")))
        recovered = workflow.deliver(
            request_path, approval, approval_key=up26.APPROVAL_KEY,
            nonce_db="g3.sqlite3", policy_id="carto-security", issuer="trusted-local",
        )
        self.assertEqual("succeeded", recovered["state"]["status"])

    def test_up33_same_idempotency_key_with_different_manifest_conflicts(self) -> None:
        project, request_path, request, workflow, checked = self._checked("delivery-key-conflict")
        result, _ = self._deliver(
            project, request_path, request, workflow, checked, suffix="delivery-key-conflict"
        )
        conflicting = deepcopy(checked["delivery_manifest"])
        conflicting["destination"]["relative_path"] = "deliveries/different-destination"
        repository = DeliveryRepository(
            path_guard=workflow.path_guard,
            project_root=workflow.project_root,
            work_root=workflow.work_root,
            registry=workflow.registry,
        )
        manifest_ref = deepcopy(result["delivery_transaction"]["manifest_ref"])
        manifest_ref["digest"] = sha256_digest(conflicting)
        with self.assertRaises(ProtocolError) as raised:
            repository.deliver(
                manifest=conflicting,
                manifest_ref=manifest_ref,
                approval_ref=result["delivery_transaction"]["approval_ref"],
            )
        self.assertEqual("IDEMPOTENCY_CONFLICT", raised.exception.code)
        self.assertFalse((project / "deliveries" / "different-destination").exists())

    def test_up33_consumed_g3_without_local_intent_is_not_recoverable(self) -> None:
        project, request_path, request, workflow, checked = self._checked("delivery-missing-intent")
        approval = self._g3(
            project, request, checked["delivery_manifest"], nonce="map-g3-missing-intent-0001"
        )

        def fail(phase: str) -> None:
            if phase == "after-approval-consumed":
                raise RuntimeError("injected")

        with self.assertRaises(RuntimeError):
            workflow.deliver(
                request_path, approval, approval_key=up26.APPROVAL_KEY,
                nonce_db="g3.sqlite3", policy_id="carto-security", issuer="trusted-local",
                failure_hook=fail,
            )
        intent = workflow.work_root / "approvals" / "g3" / (
            checked["delivery_manifest"]["manifest_id"] + ".yaml"
        )
        intent.unlink()
        with self.assertRaises(SecurityError) as raised:
            workflow.deliver(
                request_path, approval, approval_key=up26.APPROVAL_KEY,
                nonce_db="g3.sqlite3", policy_id="carto-security", issuer="trusted-local",
            )
        self.assertEqual("APPROVAL_RECOVERY_EVIDENCE_MISSING", raised.exception.code)
        self.assertFalse((project / checked["delivery_manifest"]["destination"]["relative_path"]).exists())

    def test_up33_conflicting_existing_destination_is_not_overwritten(self) -> None:
        project, request_path, request, workflow, checked = self._checked("delivery-conflict")
        destination = project / checked["delivery_manifest"]["destination"]["relative_path"]
        destination.mkdir(parents=True)
        marker = destination / "foreign.txt"
        marker.write_text("foreign", encoding="utf-8")
        approval = self._g3(
            project, request, checked["delivery_manifest"], nonce="map-g3-conflict-00000001"
        )
        with self.assertRaises(ProtocolError) as raised:
            workflow.deliver(
                request_path, approval, approval_key=up26.APPROVAL_KEY,
                nonce_db="g3.sqlite3", policy_id="carto-security", issuer="trusted-local",
            )
        self.assertEqual("DELIVERY_PACKAGE_FILE_SET_MISMATCH", raised.exception.code)
        self.assertEqual("foreign", marker.read_text(encoding="utf-8"))
        self.assertEqual("waiting_approval", workflow.status()["state"]["status"])

    def test_up33_cli_exposes_delivery_commands(self) -> None:
        parser = build_parser()
        action = next(item for item in parser._actions if item.dest == "command")
        generate = action.choices["generate-map"]
        generate_action = next(item for item in generate._actions if item.dest == "generate_command")
        self.assertIn("deliver", generate_action.choices)
        self.assertIn("delivery-status", generate_action.choices)
        deliver = generate_action.choices["deliver"]
        destinations = {item.dest for item in deliver._actions}
        self.assertTrue({"request", "approval", "key_env", "nonce_db", "policy_id", "issuer"}.issubset(destinations))
        status = generate_action.choices["delivery-status"]
        self.assertIn("idempotency_key", {item.dest for item in status._actions})


if __name__ == "__main__":
    unittest.main()
