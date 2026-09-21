from __future__ import annotations

import json
import shutil
import sys
import unittest
from pathlib import Path
from unittest.mock import PropertyMock, patch

import yaml

SCRIPTS_ROOT = Path(__file__).resolve().parents[1]
TESTS_ROOT = Path(__file__).resolve().parent
for root in (SCRIPTS_ROOT, TESTS_ROOT):
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))

import test_up25_up26_map_generation as up26
from carto_core.adapters.controlled_renderer import discover_browser
from carto_core.canonical import sha256_digest
from carto_core.errors import ProtocolError
from carto_core.cli import build_parser
from carto_core.schema_registry import SchemaRegistry, load_document
from carto_core.workflow.map_preview import freeze_object_digest
from carto_core.workflow.map_render import FormalMapRenderService


class FormalRenderWorkflowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        up26.MapGenerationWorkflowTests.setUpClass()
        cls.helper = up26.MapGenerationWorkflowTests(methodName="runTest")

    @classmethod
    def tearDownClass(cls) -> None:
        up26.MapGenerationWorkflowTests.tearDownClass()

    def _frozen(self, suffix: str):
        if discover_browser() is None:
            self.skipTest("Chromium browser is unavailable")
        project, request_path, request, workflow = self.helper._workflow(suffix)
        workflow.intake(request_path)
        brief = workflow.brief(request_path)["brief"]
        g1 = self.helper._approval(
            project, request, sha256_digest(brief), gate="G1",
            nonce=f"map-g1-{suffix}-00000001",
        )
        compiled = workflow.compile(
            request_path, g1, approval_key=up26.APPROVAL_KEY,
            nonce_db="g1.sqlite3", policy_id="carto-security", issuer="trusted-local",
        )
        preview = workflow.preview(request_path, attestation_key=up26.RENDER_KEY)
        g2 = self.helper._approval(
            project, request,
            freeze_object_digest(request, compiled["candidate"], preview["evidence"]),
            gate="G2", nonce=f"map-g2-{suffix}-00000001",
        )
        frozen = workflow.freeze(
            request_path, g2, approval_key=up26.APPROVAL_KEY,
            attestation_key=up26.RENDER_KEY, nonce_db="g2.sqlite3",
            policy_id="carto-security", issuer="trusted-local",
        )
        return project, request_path, request, workflow, frozen

    def test_up31_renders_locked_pdf_png_and_stops_before_check(self) -> None:
        project, request_path, request, workflow, frozen = self._frozen("formal-success")
        result = workflow.render(request_path, attestation_key=up26.RENDER_KEY)

        self.assertEqual("pending", result["state"]["status"])
        self.assertEqual("check", result["state"]["step"])
        self.assertEqual("succeeded", result["attempt"]["status"])
        self.assertEqual(frozen["lock"]["execution_digest"], result["attempt"]["business_execution_digest"])
        self.assertEqual(result["render_receipt"]["execution_digest"], result["attempt"]["renderer_execution_digest"])
        self.assertEqual("not-checked", result["evidence"]["quality_status"])
        self.assertEqual("合成数据演示，非真实风险研判", result["evidence"]["synthetic_data_notice"])
        self.assertTrue({"pdf", "png"}.issubset(
            {item["target"] for item in result["evidence"]["output_artifacts"]}
        ))
        SchemaRegistry().validate("render-attempt", result["attempt"])
        SchemaRegistry().validate("formal-render-evidence", result["evidence"])
        expected_fragment = Path("output") / frozen["lock"]["lock_id"] / "formal-map" / result["attempt"]["attempt_id"]
        for item in result["evidence"]["output_artifacts"]:
            output = Path(item["artifact_ref"]["uri"])
            self.assertTrue(output.is_file())
            self.assertIn(str(expected_fragment), str(output))

        replay = workflow.render(request_path, attestation_key=up26.RENDER_KEY)
        self.assertTrue(replay["idempotent_replay"])
        self.assertEqual(result["attempt"], replay["attempt"])
        self.assertEqual(result["evidence"], replay["evidence"])

    def test_up31_timeout_creates_immutable_retry_attempt(self) -> None:
        project, request_path, request, workflow, frozen = self._frozen("formal-retry")
        with patch(
            "carto_core.workflow.map_render.WebMapRendererAdapter.submit_render",
            side_effect=ProtocolError("RENDER_TIMEOUT", "injected timeout"),
        ):
            with self.assertRaises(ProtocolError) as raised:
                workflow.render(request_path, attestation_key=up26.RENDER_KEY)
        self.assertEqual("RENDER_TIMEOUT", raised.exception.code)
        state = workflow.status()["state"]
        self.assertEqual(("failed", "render", 1), (state["status"], state["step"], state["attempt"]))
        first_path = project / "generation" / "render-attempts" / f"render-attempt-{request['run_id']}-1.yaml"
        first = load_document(first_path)
        self.assertEqual("failed", first["status"])
        self.assertTrue(first["retryable"])

        attempt_root = (project / "generation" / "output" / frozen["lock"]["lock_id"] /
                        "formal-map" / f"render-attempt-{request['run_id']}-1")
        if attempt_root.exists():
            shutil.rmtree(attempt_root)
        workflow.retry()
        result = workflow.render(request_path, attestation_key=up26.RENDER_KEY)
        self.assertEqual(2, result["attempt"]["attempt_number"])
        self.assertEqual("succeeded", result["attempt"]["status"])
        self.assertTrue(first_path.is_file())
        self.assertEqual(first, load_document(first_path))
        self.assertEqual(first["attempt_id"], result["attempt"]["previous_attempt_ref"]["id"])

    def test_up31_lock_input_drift_fails_without_retry(self) -> None:
        project, request_path, request, workflow, frozen = self._frozen("formal-drift")
        scene_path = project / "generation" / "candidates" / "render-scene.yaml"
        scene = load_document(scene_path)
        scene["camera"]["bearing"] = 1
        scene_path.write_text(
            yaml.safe_dump(scene, allow_unicode=True, sort_keys=False), encoding="utf-8"
        )
        with self.assertRaises(ProtocolError) as raised:
            workflow.render(request_path, attestation_key=up26.RENDER_KEY)
        self.assertEqual("LOCK_INPUT_DRIFT", raised.exception.code)
        state = workflow.status()["state"]
        self.assertEqual(("failed", "render"), (state["status"], state["step"]))
        with self.assertRaises(ProtocolError) as retry_error:
            workflow.retry()
        self.assertEqual("JOB_RETRY_NOT_ALLOWED", retry_error.exception.code)

    def test_up31_environment_drift_is_non_retryable(self) -> None:
        project, request_path, request, workflow, frozen = self._frozen("formal-env-drift")
        with patch.object(
            FormalMapRenderService, "environment_fingerprint",
            new_callable=PropertyMock, return_value="sha256:" + "0" * 64,
        ):
            with self.assertRaises(ProtocolError) as raised:
                workflow.render(request_path, attestation_key=up26.RENDER_KEY)
        self.assertEqual("RENDER_ENVIRONMENT_DRIFT", raised.exception.code)
        attempt_path = project / "generation" / "render-attempts" / f"render-attempt-{request['run_id']}-1.yaml"
        attempt = load_document(attempt_path)
        self.assertFalse(attempt["retryable"])
        with self.assertRaises(ProtocolError) as retry_error:
            workflow.retry()
        self.assertEqual("JOB_RETRY_NOT_ALLOWED", retry_error.exception.code)

    def test_up31_recovers_completed_attempt_before_step_receipt(self) -> None:
        project, request_path, request, workflow, frozen = self._frozen("formal-recovery")
        lock, lock_ref, scene, preview_receipt = workflow._locked_render_inputs(
            request, attestation_key=up26.RENDER_KEY, browser=None
        )
        service = FormalMapRenderService(
            path_guard=workflow.path_guard, work_root=workflow.work_root,
            attestation_key=up26.RENDER_KEY, registry=workflow.registry,
        )
        service.validate_environment(lock, preview_receipt)
        service.validate_scene(scene)
        existing = service.render(
            request=request, lock=lock, lock_ref=lock_ref, scene=scene,
            attempt_number=1, started_at="2026-09-21T00:00:00+00:00",
        )
        result = workflow.render(request_path, attestation_key=up26.RENDER_KEY)
        self.assertTrue(result["idempotent_replay"])
        self.assertEqual(existing["attempt"], result["attempt"])
        self.assertEqual(("pending", "check"), (result["state"]["status"], result["state"]["step"]))

    def test_up31_replay_rejects_formal_output_tampering(self) -> None:
        project, request_path, request, workflow, frozen = self._frozen("formal-output-drift")
        result = workflow.render(request_path, attestation_key=up26.RENDER_KEY)
        output = Path(next(
            item["artifact_ref"]["uri"] for item in result["evidence"]["output_artifacts"]
            if item["target"] == "png"
        ))
        payload = bytearray(output.read_bytes())
        payload[-1] ^= 1
        output.write_bytes(payload)
        with self.assertRaises(ProtocolError) as raised:
            workflow.render(request_path, attestation_key=up26.RENDER_KEY)
        self.assertIn(raised.exception.code, {"RENDER_OUTPUT_DIGEST_MISMATCH", "FORMAL_RENDER_OUTPUT_DRIFT"})

    def test_up31_scene_semantics_fail_before_browser_submission(self) -> None:
        project, request_path, request, workflow, frozen = self._frozen("formal-semantics")
        scene = load_document(project / "generation" / "candidates" / "render-scene.yaml")
        scene["overlays"] = [
            item for item in scene["overlays"] if item["id"] != "synthetic-data-notice"
        ]
        service = FormalMapRenderService(
            path_guard=workflow.path_guard, work_root=workflow.work_root,
            attestation_key=up26.RENDER_KEY, registry=workflow.registry,
        )
        with patch("carto_core.workflow.map_render.WebMapRendererAdapter.submit_render") as submit:
            with self.assertRaises(ProtocolError) as raised:
                service.validate_scene(scene)
        self.assertEqual("ENCODING_SEMANTICS_INVALID", raised.exception.code)
        submit.assert_not_called()

    def test_up31_cli_keeps_render_contract_after_delivery_is_exposed(self) -> None:
        parser = build_parser()
        action = next(item for item in parser._actions if item.dest == "command")
        generate = action.choices["generate-map"]
        generate_action = next(item for item in generate._actions if item.dest == "generate_command")
        self.assertIn("render", generate_action.choices)
        self.assertIn("check", generate_action.choices)
        self.assertIn("deliver", generate_action.choices)
        render = generate_action.choices["render"]
        destinations = {item.dest for item in render._actions}
        self.assertIn("attestation_key_env", destinations)
        self.assertIn("browser", destinations)
        self.assertNotIn("approval", destinations)


if __name__ == "__main__":
    unittest.main()
