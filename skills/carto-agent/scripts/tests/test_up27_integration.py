from __future__ import annotations

import json
import sys
import tempfile
import threading
import time
import unittest
from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
from dataclasses import asdict, replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import patch

import yaml

SCRIPTS_ROOT = Path(__file__).resolve().parents[1]
TESTS_ROOT = Path(__file__).resolve().parent
for root in (SCRIPTS_ROOT, TESTS_ROOT):
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))

import test_up2_template as up2
from carto_core.canonical import sha256_digest
from carto_core.cli import build_parser, main as cli_main
from carto_core.errors import ProtocolError, SecurityError
from carto_core.security.approval import ApprovalReceipt, InMemoryNonceStore, sign_receipt
from carto_core.workflow.approvals import ApprovalGateCoordinator
from carto_core.workflow.models import ExecutionContext
from carto_core.workflow.state_machine import WorkflowStateStore


KEY = b"test-only-secret-that-is-at-least-32-bytes"


class StateRecoveryTests(unittest.TestCase):
    def test_transition_recovers_receipt_written_before_state(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "run"
            store = WorkflowStateStore(root)
            state = store.initialize("run-one", {"request": "map"})
            with patch.object(store, "_write_state_unlocked", side_effect=OSError("injected crash")):
                with self.assertRaises(OSError):
                    store.complete_step(
                        state,
                        status="succeeded",
                        prerequisites={},
                        output_refs=[],
                        next_step="brief",
                    )
            self.assertTrue(store.transition_path.is_file())
            self.assertEqual(len(list((root / "receipts").glob("*.json"))), 1)

            recovered_store = WorkflowStateStore(root)
            recovered = recovered_store.load()
            self.assertEqual(recovered.revision, 2)
            self.assertEqual(recovered.step, "brief")
            self.assertFalse(recovered_store.transition_path.exists())
            self.assertTrue(recovered_store.recovery_status()["recovered_transition"])

    def test_transition_without_receipt_is_not_silently_committed(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            store = WorkflowStateStore(Path(temp) / "run")
            state = store.initialize("run-one", {"request": "map"})
            following = replace(
                state,
                revision=2,
                status="pending",
                step="brief",
                last_receipt="receipts/intake-1-missing.json",
            )
            transition = {
                "schema_version": 1,
                "transition_id": "transition-missing",
                "run_id": state.run_id,
                "expected_revision": state.revision,
                "receipt_path": "receipts/intake-1-missing.json",
                "receipt_digest": "sha256:" + "0" * 64,
                "previous_state": state.to_dict(),
                "next_state": following.to_dict(),
                "created_at": "2026-09-18T00:00:00Z",
            }
            store.registry.validate("state-transition", transition)
            store.transition_path.write_text(json.dumps(transition), encoding="utf-8")
            with self.assertRaises(ProtocolError) as raised:
                store.load()
            self.assertEqual(raised.exception.code, "JOB_TRANSITION_INCOMPLETE")
            self.assertEqual(json.loads(store.state_path.read_text(encoding="utf-8")), state.to_dict())

    def test_stale_revision_is_rejected_and_waiting_status_is_preserved(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            store = WorkflowStateStore(Path(temp) / "run")
            state = store.initialize("run-one", {"request": "map"})
            time.sleep(0.02)
            advanced, receipt = store.complete_step(
                state,
                status="waiting_approval",
                prerequisites={},
                output_refs=[],
                next_step="compile",
            )
            self.assertEqual(advanced.status, "waiting_approval")
            self.assertEqual(advanced.revision, 2)
            self.assertLess(receipt.started_at, receipt.completed_at)
            with self.assertRaises(ProtocolError) as raised:
                store.complete_step(
                    state,
                    status="succeeded",
                    prerequisites={},
                    output_refs=[],
                    next_step="other",
                )
            self.assertEqual(raised.exception.code, "JOB_STATE_STALE")

    def test_retry_only_advances_failed_attempt(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            store = WorkflowStateStore(Path(temp) / "run")
            state = store.initialize("run-one", {"request": "map"})
            failed, _ = store.complete_step(
                state,
                status="failed",
                prerequisites={},
                output_refs=[],
                error={"code": "TEST_FAILURE", "message": "synthetic failure"},
            )
            retried = store.retry(failed)
            self.assertEqual((retried.status, retried.attempt, retried.revision), ("pending", 2, 3))
            with self.assertRaises(ProtocolError) as raised:
                store.retry(retried)
            self.assertEqual(raised.exception.code, "JOB_RETRY_NOT_ALLOWED")

    def test_receipts_are_queryable_and_immutable(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            store = WorkflowStateStore(Path(temp) / "run")
            state = store.initialize("run-one", {"request": "map"})
            output = {"id": "artifact-one", "version": "1.0.0", "digest": sha256_digest({"v": 1})}
            state, _ = store.complete_step(
                state,
                status="succeeded",
                prerequisites={},
                output_refs=[output],
                next_step="brief",
            )
            before = (store.run_root / state.last_receipt).read_bytes()
            queried = store.receipts()
            after = (store.run_root / state.last_receipt).read_bytes()
            self.assertEqual(before, after)
            self.assertEqual(len(queried), 1)
            self.assertEqual(store.find_output_digest("artifact-one"), output["digest"])

    def test_second_writer_times_out_while_run_lock_is_held(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "run"
            first = WorkflowStateStore(root)
            first.initialize("run-one", {"request": "map"})
            second = WorkflowStateStore(root, lock_timeout_seconds=0.1)
            errors: list[str] = []

            def contend() -> None:
                try:
                    second.load()
                except ProtocolError as exc:
                    errors.append(exc.code)

            with first.operation():
                thread = threading.Thread(target=contend)
                thread.start()
                thread.join(timeout=2)
            self.assertFalse(thread.is_alive())
            self.assertEqual(errors, ["JOB_OPERATION_LOCKED"])


class RouteClosureTests(unittest.TestCase):
    def test_template_validation_retry_preserves_attempt_evidence_and_can_publish(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            helper = up2.TemplateWorkflowTests(methodName="runTest")
            project, request, workdir, workflow, brief = helper._ready(root)
            workflow.author(
                request,
                helper._approval(project, brief),
                approval_key=up2.KEY,
                nonce_db="author-nonces.sqlite3",
                policy_id="carto-security",
                issuer="trusted-local",
            )

            with patch(
                "carto_core.workflow.template_validation.discover_browser",
                side_effect=ProtocolError("RENDER_BROWSER_UNAVAILABLE", "synthetic transient failure"),
            ):
                failed = workflow.validate(request, attestation_key=KEY)
            self.assertEqual("failed", failed["state"]["status"])
            first_path = workdir / "validation/template-validation-evidence.yaml"
            first_bytes = first_path.read_bytes()

            retried = workflow.retry()
            self.assertEqual(("pending", 2), (retried["state"]["status"], retried["state"]["attempt"]))
            passed = workflow.validate(request, attestation_key=KEY)
            self.assertEqual("passed", passed["evidence"]["status"])
            self.assertEqual(first_bytes, first_path.read_bytes())
            retry_path = workdir / "validation/attempt-2/template-validation-evidence.yaml"
            self.assertTrue(retry_path.is_file())
            self.assertEqual(
                "validation/attempt-2/template-validation-evidence.yaml",
                passed["receipt"]["output_refs"][0]["uri"],
            )

            scope = "local:templates"
            publication_object = {
                "package_digest": passed["evidence"]["package_ref"]["digest"],
                "evidence_digest": passed["evidence"]["evidence_digest"],
                "repository_scope": scope,
            }
            now = datetime.now(UTC)
            approval = sign_receipt(ApprovalReceipt(
                1,
                "publication-approval-retry",
                "trusted-local",
                "reviewer-one",
                "tenant-one",
                "approve-template-publish",
                "template-publication",
                sha256_digest(publication_object),
                scope,
                "carto-security",
                "local",
                (now - timedelta(minutes=1)).isoformat(),
                (now + timedelta(minutes=10)).isoformat(),
                "publication-nonce-retry-00000001",
            ), up2.KEY)
            approval_path = project / "publication-approval-retry.yaml"
            approval_path.write_text(yaml.safe_dump(asdict(approval), sort_keys=False), encoding="utf-8")
            published = workflow.publish(
                request,
                approval_path,
                repository_root="template-repository",
                repository_scope=scope,
                idempotency_key="publish-retry-0001",
                approval_key=up2.KEY,
                renderer_attestation_key=KEY,
                nonce_db="publication-nonces.sqlite3",
                policy_id="carto-security",
                issuer="trusted-local",
            )
            self.assertEqual("succeeded", published["state"]["status"])
            self.assertEqual(
                passed["evidence"]["evidence_digest"],
                published["publication"]["evidence_ref"]["digest"],
            )

    def test_cli_exposes_status_retry_and_receipts_for_both_routes(self) -> None:
        parser = build_parser()
        common = ["--project-root", ".", "--workdir", "run", "--allowed-root", "."]
        for route in ("create-template", "generate-map"):
            for command in ("status", "retry", "receipts"):
                extra = [] if route == "create-template" else ["--repository-root", ".", "--repository-scope", "project:test"]
                parsed = parser.parse_args([route, command, *common, *extra])
                self.assertEqual(parsed.command, route)

    def test_cli_status_receipts_and_retry_execute_for_both_routes(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            project = root / "project"
            repository = root / "repository"
            project.mkdir()
            repository.mkdir()
            for route in ("create-template", "generate-map"):
                workdir = project / route
                store = WorkflowStateStore(workdir)
                state = store.initialize("run-one", {"request": route})
                store.complete_step(
                    state,
                    status="failed",
                    prerequisites={},
                    output_refs=[],
                    error={"code": "TEST_FAILURE", "message": "synthetic failure"},
                )
                common = [
                    "--project-root", str(project),
                    "--workdir", str(workdir),
                    "--allowed-root", str(root),
                ]
                if route == "generate-map":
                    common.extend(["--repository-root", str(repository), "--repository-scope", "project:test"])
                for command in ("status", "receipts", "retry"):
                    output = StringIO()
                    error = StringIO()
                    with redirect_stdout(output), redirect_stderr(error):
                        code = cli_main([route, command, *common])
                    self.assertEqual(code, 0, error.getvalue() or output.getvalue())
                    self.assertTrue(json.loads(output.getvalue())["ok"])

    def test_template_approval_cannot_be_reused_as_map_g1(self) -> None:
        now = datetime.now(UTC)
        digest = sha256_digest({"brief": "one"})
        unsigned = ApprovalReceipt(
            1,
            "approval-one",
            "trusted-local",
            "reviewer-one",
            "tenant-one",
            "approve-template-brief",
            "template-brief",
            digest,
            "project:project-one",
            "carto-security",
            "local",
            (now - timedelta(minutes=1)).isoformat(),
            (now + timedelta(minutes=10)).isoformat(),
            "nonce-0000000000000001",
        )
        receipt = sign_receipt(unsigned, KEY)
        context = ExecutionContext(
            run_id="run-one",
            tenant_id="tenant-one",
            project_id="project-one",
            subject_id="operator-one",
            roles=frozenset({"operator"}),
            namespaces=frozenset({"project-one"}),
            authorized_capabilities=frozenset(),
            environment="local",
        )
        coordinator = ApprovalGateCoordinator(KEY, InMemoryNonceStore(), "carto-security", "trusted-local")
        with self.assertRaises(SecurityError) as raised:
            coordinator.require("G1", receipt, digest, context, approver_subject_id="reviewer-one")
        self.assertEqual(raised.exception.code, "APPROVAL_ACTION_MISMATCH")


if __name__ == "__main__":
    unittest.main()