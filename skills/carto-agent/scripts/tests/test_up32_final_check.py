from __future__ import annotations

import sys
import unittest
from copy import deepcopy
from pathlib import Path

SCRIPTS_ROOT = Path(__file__).resolve().parents[1]
TESTS_ROOT = Path(__file__).resolve().parent
for root in (SCRIPTS_ROOT, TESTS_ROOT):
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))

import test_up25_up26_map_generation as up26
import test_up31_formal_render as up31
from carto_core.canonical import sha256_digest
from carto_core.cli import build_parser
from carto_core.errors import ProtocolError, SecurityError
from carto_core.schema_registry import SchemaRegistry, load_document
from carto_core.workflow.map_final_check import FinalMapCheckService


class FinalCheckWorkflowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        up31.FormalRenderWorkflowTests.setUpClass()
        cls.helper = up31.FormalRenderWorkflowTests(methodName="runTest")

    @classmethod
    def tearDownClass(cls) -> None:
        up31.FormalRenderWorkflowTests.tearDownClass()

    def _rendered(self, suffix: str):
        project, request_path, request, workflow, frozen = self.helper._frozen(suffix)
        rendered = workflow.render(request_path, attestation_key=up26.RENDER_KEY)
        return project, request_path, request, workflow, frozen, rendered

    def _check_context(self, workflow, request, rendered):
        lock, lock_ref, scene, _ = workflow._locked_render_inputs(
            request, attestation_key=up26.RENDER_KEY, browser=None
        )
        checker = FinalMapCheckService(
            path_guard=workflow.path_guard,
            project_root=workflow.project_root,
            work_root=workflow.work_root,
            registry=workflow.registry,
        )
        return checker, {
            "lock": lock,
            "lock_ref": lock_ref,
            "scene": scene,
            "attempt": rendered["attempt"],
            "attempt_path": Path(rendered["evidence"]["attempt_ref"]["uri"]),
            "receipt": rendered["render_receipt"],
            "evidence": rendered["evidence"],
            "evidence_path": workflow.work_root / "formal-render" / f"{rendered['evidence']['evidence_id']}.yaml",
        }

    @staticmethod
    def _result(report: dict, check_id: str) -> dict:
        return next(item for item in report["results"] if item["check_id"] == check_id)

    def test_up32_check_passes_and_freezes_g3_object_without_delivery_side_effects(self) -> None:
        project, request_path, request, workflow, frozen, rendered = self._rendered("final-check-success")
        destination = project / "deliveries" / "review-one"
        result = workflow.check(
            request_path,
            attestation_key=up26.RENDER_KEY,
            recipient_id="reviewer-one",
            recipient_type="project-user",
            destination="deliveries/review-one",
            idempotency_key="final-check-success-0001",
        )
        self.assertEqual(("waiting_approval", "deliver"), (result["state"]["status"], result["state"]["step"]))
        self.assertEqual("passed", result["validation_report"]["status"])
        self.assertFalse(destination.exists())
        self.assertEqual(sha256_digest(result["delivery_manifest"]), result["g3"]["object_digest"])
        self.assertEqual("approve-delivery", result["g3"]["action"])
        self.assertNotIn("delivered_at", result["delivery_manifest"])
        SchemaRegistry().validate("validation-report", result["validation_report"])
        SchemaRegistry().validate("delivery-manifest", result["delivery_manifest"])
        failures = [item for item in result["validation_report"]["results"] if item["status"] != "passed"]
        self.assertEqual([], failures, failures)
        self.assertFalse(list(project.rglob("*delivery-receipt*")))

        replay = workflow.check(
            request_path,
            attestation_key=up26.RENDER_KEY,
            recipient_id="reviewer-one",
            recipient_type="project-user",
            destination="deliveries/review-one",
            idempotency_key="final-check-success-0001",
        )
        self.assertTrue(replay["idempotent_replay"])
        self.assertEqual(result["validation_report"], replay["validation_report"])
        self.assertEqual(result["delivery_manifest"], replay["delivery_manifest"])
        self.assertFalse(destination.exists())

    def test_up32_missing_png_fails_report_without_manifest_or_retry(self) -> None:
        project, request_path, request, workflow, frozen, rendered = self._rendered("final-check-missing-png")
        png = Path(next(
            item["artifact_ref"]["uri"] for item in rendered["evidence"]["output_artifacts"]
            if item["target"] == "png"
        ))
        png.unlink()
        with self.assertRaises(ProtocolError) as raised:
            workflow.check(
                request_path,
                attestation_key=up26.RENDER_KEY,
                recipient_id="reviewer-one",
                recipient_type="project-user",
                destination="deliveries/missing-png",
                idempotency_key="final-check-missing-png-0001",
            )
        self.assertEqual("FINAL_CHECK_FAILED", raised.exception.code)
        self.assertEqual(("failed", "check"), tuple(workflow.status()["state"][key] for key in ("status", "step")))
        report_path = workflow.work_root / "final-checks" / rendered["attempt"]["attempt_id"] / "validation-report.yaml"
        report = load_document(report_path)
        self.assertEqual("failed", report["status"])
        integrity = self._result(report, "final.artifact-integrity")
        self.assertEqual("failed", integrity["status"])
        self.assertFalse(next(item for item in integrity["details"]["artifacts"] if item["target"] == "png")["exists"])
        self.assertFalse((workflow.work_root / "delivery-manifests").exists())
        with self.assertRaises(ProtocolError) as retry_error:
            workflow.retry()
        self.assertEqual("JOB_RETRY_NOT_ALLOWED", retry_error.exception.code)

    def test_up32_tampering_fails_first_check_and_is_rejected_on_replay(self) -> None:
        project, request_path, request, workflow, frozen, rendered = self._rendered("final-check-tamper-first")
        png = Path(next(
            item["artifact_ref"]["uri"] for item in rendered["evidence"]["output_artifacts"]
            if item["target"] == "png"
        ))
        payload = bytearray(png.read_bytes())
        payload[-1] ^= 1
        png.write_bytes(payload)
        with self.assertRaises(ProtocolError) as raised:
            workflow.check(
                request_path,
                attestation_key=up26.RENDER_KEY,
                recipient_id="reviewer-one",
                recipient_type="project-user",
                destination="deliveries/tampered",
                idempotency_key="final-check-tampered-0001",
            )
        self.assertEqual("FINAL_CHECK_FAILED", raised.exception.code)
        report = load_document(
            workflow.work_root / "final-checks" / rendered["attempt"]["attempt_id"] / "validation-report.yaml"
        )
        integrity = self._result(report, "final.artifact-integrity")
        png_detail = next(item for item in integrity["details"]["artifacts"] if item["target"] == "png")
        self.assertTrue(png_detail["media_signature_valid"])
        self.assertFalse(png_detail["digest_matches"])
        self.assertFalse(png_detail["integrity_valid"])

        project2, request_path2, request2, workflow2, frozen2, rendered2 = self._rendered("final-check-tamper-replay")
        result = workflow2.check(
            request_path2,
            attestation_key=up26.RENDER_KEY,
            recipient_id="reviewer-one",
            recipient_type="project-user",
            destination="deliveries/replay",
            idempotency_key="final-check-replay-0001",
        )
        png2 = Path(next(
            item["artifact_ref"]["uri"] for item in result["validation_report"]["checked_artifacts"]
            if item["target"] == "png"
        ))
        tampered = bytearray(png2.read_bytes())
        tampered[-1] ^= 1
        png2.write_bytes(tampered)
        with self.assertRaises(ProtocolError) as replay_error:
            workflow2.check(
                request_path2,
                attestation_key=up26.RENDER_KEY,
                recipient_id="reviewer-one",
                recipient_type="project-user",
                destination="deliveries/replay",
                idempotency_key="final-check-replay-0001",
            )
        self.assertIn(replay_error.exception.code, {"RENDER_OUTPUT_DIGEST_MISMATCH", "FORMAL_RENDER_OUTPUT_DRIFT"})

    def test_up32_registered_semantic_checks_and_warning_disposition_block(self) -> None:
        project, request_path, request, workflow, frozen, rendered = self._rendered("final-check-semantic-unit")
        checker, context = self._check_context(workflow, request, rendered)

        cases = (
            ("missing-scale", "final.layout-elements", lambda scene: scene.update(
                overlays=[item for item in scene["overlays"] if item["id"] != "scale"]
            )),
            ("missing-source", "final.layout-elements", lambda scene: scene.update(
                overlays=[item for item in scene["overlays"] if item["id"] != "source"]
            )),
            ("missing-notice", "final.synthetic-notice", lambda scene: scene.update(
                overlays=[item for item in scene["overlays"] if item["id"] != "synthetic-data-notice"]
            )),
            ("missing-no-data", "final.legend-semantics", lambda scene: next(
                item for item in scene["overlays"] if item["id"] == "legend"
            ).update(legend_items=[
                item for item in next(value for value in scene["overlays"] if value["id"] == "legend")["legend_items"]
                if item["label"] != "无数据"
            ])),
        )
        for label, check_id, mutate in cases:
            with self.subTest(case=label):
                changed = dict(context)
                changed["scene"] = deepcopy(context["scene"])
                mutate(changed["scene"])
                report = checker.inspect(**changed)
                self.assertEqual("failed", report["status"])
                self.assertEqual("failed", self._result(report, check_id)["status"])

        warning_context = dict(context)
        warning_context["receipt"] = deepcopy(context["receipt"])
        warning_context["receipt"]["warnings"] = ["unexpected renderer fallback"]
        warning_report = checker.inspect(**warning_context)
        warning = self._result(warning_report, "final.renderer-warnings")
        self.assertEqual("failed", warning_report["status"])
        self.assertEqual("failed", warning["status"])
        self.assertEqual("blocked", warning["disposition"])

    def test_up32_manifest_inputs_and_destination_are_strict(self) -> None:
        project, request_path, request, workflow, frozen, rendered = self._rendered("final-check-manifest-inputs")
        destination = "deliveries/frozen-inputs"
        result = workflow.check(
            request_path,
            attestation_key=up26.RENDER_KEY,
            recipient_id="reviewer-one",
            recipient_type="project-user",
            destination=destination,
            idempotency_key="final-check-inputs-0001",
        )
        variants = (
            {"recipient_id": "reviewer-two"},
            {"recipient_type": "project-team"},
            {"destination": "deliveries/changed"},
            {"idempotency_key": "final-check-inputs-0002"},
        )
        base = {
            "recipient_id": "reviewer-one",
            "recipient_type": "project-user",
            "destination": destination,
            "idempotency_key": "final-check-inputs-0001",
        }
        for changed in variants:
            with self.subTest(changed=changed):
                arguments = {**base, **changed}
                with self.assertRaises(ProtocolError) as raised:
                    workflow.check(request_path, attestation_key=up26.RENDER_KEY, **arguments)
                self.assertEqual("DELIVERY_MANIFEST_INPUT_MISMATCH", raised.exception.code)

        checker, _ = self._check_context(workflow, request, rendered)
        with self.assertRaises(SecurityError) as absolute_error:
            checker.normalize_destination(project / "deliveries" / "absolute")
        self.assertEqual("DELIVERY_DESTINATION_NOT_RELATIVE", absolute_error.exception.code)
        with self.assertRaises(SecurityError) as escape_error:
            checker.normalize_destination("../escape")
        self.assertEqual("DELIVERY_DESTINATION_OUTSIDE_PROJECT", escape_error.exception.code)
        with self.assertRaises(SecurityError) as outside_error:
            checker.normalize_destination("../../outside")
        self.assertEqual("PATH_OUTSIDE_ALLOWED_ROOT", outside_error.exception.code)
        self.assertFalse((project / destination).exists())

    def test_up32_recovers_precreated_report_and_manifest_before_step_receipt(self) -> None:
        project, request_path, request, workflow, frozen, rendered = self._rendered("final-check-recovery")
        checker, context = self._check_context(workflow, request, rendered)
        report = checker.inspect(**context)
        report_path = checker.write_report(report, rendered["attempt"]["attempt_id"])
        manifest = checker.build_manifest(
            request=request,
            lock=context["lock"],
            lock_ref=context["lock_ref"],
            attempt=context["attempt"],
            attempt_path=context["attempt_path"],
            report=report,
            report_path=report_path,
            recipient_id="reviewer-one",
            recipient_type="project-user",
            destination="deliveries/recovered",
            idempotency_key="final-check-recovery-0001",
        )
        manifest_path = checker.write_manifest(manifest)
        self.assertEqual(("pending", "check"), tuple(workflow.status()["state"][key] for key in ("status", "step")))

        result = workflow.check(
            request_path,
            attestation_key=up26.RENDER_KEY,
            recipient_id="reviewer-one",
            recipient_type="project-user",
            destination="deliveries/recovered",
            idempotency_key="final-check-recovery-0001",
        )
        self.assertEqual(report, result["validation_report"])
        self.assertEqual(manifest, result["delivery_manifest"])
        self.assertEqual(manifest, load_document(manifest_path))
        self.assertEqual(("waiting_approval", "deliver"), (result["state"]["status"], result["state"]["step"]))
        self.assertFalse((project / "deliveries" / "recovered").exists())

    def test_up32_cli_keeps_check_contract_after_delivery_is_exposed(self) -> None:
        parser = build_parser()
        action = next(item for item in parser._actions if item.dest == "command")
        generate = action.choices["generate-map"]
        generate_action = next(item for item in generate._actions if item.dest == "generate_command")
        self.assertIn("check", generate_action.choices)
        self.assertIn("deliver", generate_action.choices)
        check = generate_action.choices["check"]
        destinations = {item.dest for item in check._actions}
        self.assertTrue({
            "request", "project_root", "workdir", "repository_root", "repository_scope",
            "allowed_root", "attestation_key_env", "browser", "recipient_id",
            "recipient_type", "destination", "idempotency_key",
        }.issubset(destinations))
        self.assertNotIn("approval", destinations)


if __name__ == "__main__":
    unittest.main()
