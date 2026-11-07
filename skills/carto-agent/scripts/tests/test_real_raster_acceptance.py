"""Development harness contracts; no user data or actual approvals are used."""
from contextlib import redirect_stdout
import io
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from tests.manual import real_raster_acceptance as harness
from carto_core.security.paths import PathGuard
from carto_core.errors import SecurityError


class AcceptanceUtilityTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()

    def test_fingerprint_accepts_bounded_file_without_logging_bytes(self):
        path = self.root / "synthetic.bin"
        path.write_bytes(b"private-test-value")
        value = harness.fingerprint(path, 100)
        self.assertEqual(value["size_bytes"], 18)
        self.assertEqual(len(value["sha256"]), 64)
        self.assertNotIn("private-test-value", json.dumps(value))

    def test_empty_oversize_directory_and_bad_tiff_rejected(self):
        path = self.root / "synthetic.tif"
        for content in (b"", b"x" * 11):
            path.write_bytes(content)
            with self.assertRaises(harness.CheckError):
                harness.fingerprint(path, 10)
        with self.assertRaises(harness.CheckError):
            harness.fingerprint(self.root, 100)
        with self.assertRaises(harness.CheckError) as raised:
            harness.input_check(path, "raster")
        self.assertEqual(raised.exception.code, "TIFF_SIGNATURE_INVALID")

    def test_header_check_is_not_a_full_raster_validation(self):
        path = self.root / "synthetic.tif"
        path.write_bytes(b"II\x2a\x00not-a-complete-raster")
        value = harness.input_check(path, "raster")
        self.assertEqual(value["check_depth"], "size_digest_tiff_signature_only")

    def test_csv_is_not_interpreted_or_disclosed(self):
        path = self.root / "synthetic.csv"
        path.write_bytes(b"value,name\n0,private-test-name\n")
        value = harness.input_check(path, "legend")
        self.assertNotIn("private-test-name", json.dumps(value))
        self.assertIn("no_column_or_row_interpretation", value["check_depth"])

    def test_json_ok_is_not_enough_without_exit_success(self):
        completed = subprocess.CompletedProcess([], 2, '{"ok":true}', "private-secret")
        with self.assertRaises(harness.CheckError):
            harness.parse_success(completed, {"exit_code": 2})
        completed.returncode = 0
        completed.stdout = '{"ok":false}'
        with self.assertRaises(harness.CheckError):
            harness.parse_success(completed, {})
        completed.stdout = '{"ok":true}'
        self.assertEqual(harness.parse_success(completed, {}), {"ok": True})

    def test_subprocess_raw_output_is_not_metadata(self):
        output = subprocess.CompletedProcess([], 2, "private-stdout", "private-stderr")
        with patch.object(harness.subprocess, "run", return_value=output):
            _, evidence = harness.invoke(["synthetic-command"])
        self.assertEqual(evidence["exit_code"], 2)
        self.assertNotIn("private-", json.dumps(evidence))

    def test_timeout_is_not_retried(self):
        with patch.object(harness.subprocess, "run", side_effect=subprocess.TimeoutExpired("synthetic", 1)) as call:
            with self.assertRaises(harness.CheckError) as raised:
                harness.invoke(["synthetic-command"], timeout=1)
        self.assertEqual(call.call_count, 1)
        self.assertEqual(raised.exception.code, "SUBPROCESS_TIMEOUT")
        self.assertIs(raised.exception.evidence["retried"], False)

    def test_report_is_unique_and_host_label_does_not_attest(self):
        kwargs = dict(guard=PathGuard([self.root]), mode="preflight", host="vscode-claude-code", suite="raster")
        first = harness.Report(self.root / "project", **kwargs)
        second = harness.Report(self.root / "project", **kwargs)
        self.assertNotEqual(first.root, second.root)
        self.assertEqual(first.data["plugin_acceptance"], "not_verified")
        first.check("01", "safe", lambda: (_ for _ in ()).throw(harness.CheckError("SAFE_ERROR")))
        value = json.loads((first.root / "report.json").read_text(encoding="utf-8"))
        self.assertEqual(value["steps"][0]["code"], "SAFE_ERROR")
        self.assertIsNone(value["completed_at"])
        self.assertTrue((first.root / "report.md").is_file())

    def test_outside_report_path_is_rejected(self):
        allowed = self.root / "allowed"
        allowed.mkdir()
        with self.assertRaises(SecurityError):
            harness.Report(self.root / "outside", guard=PathGuard([allowed]), mode="preflight", host="terminal", suite="raster")

    def test_safe_error_code_rejects_messages(self):
        self.assertEqual(harness.safe_code(ValueError("private-secret")), "CHECK_EXCEPTION")
        self.assertEqual(harness.safe_code(harness.CheckError("private-secret")), "CHECK_EXCEPTION")

    def test_each_unittest_outcome_is_recorded_without_error_values(self):
        class Cases(unittest.TestCase):
            def test_pass(self):
                pass
            def test_fail(self):
                self.fail("private-failure")
            def test_skip(self):
                self.skipTest("private-skip")
            def test_subtest(self):
                with self.subTest(value="private-subtest"):
                    self.fail("private-message")
            def test_error(self):
                raise RuntimeError("private-error")
        result = harness.StepResult()
        unittest.defaultTestLoader.loadTestsFromTestCase(Cases).run(result)
        value = result.payload()
        self.assertFalse(value["ok"])
        self.assertEqual(value["tests_run"], 5)
        self.assertEqual(value["counts"], {"passed": 1, "failed": 3, "skipped": 1})
        self.assertNotIn("private-", json.dumps(value))
        self.assertTrue(all("duration_seconds" in row for row in value["records"]))

    def test_class_setup_failure_cannot_look_successful(self):
        class Cases(unittest.TestCase):
            @classmethod
            def setUpClass(cls):
                raise RuntimeError("private-setup")
            def test_never(self):
                pass
        result = harness.StepResult()
        unittest.defaultTestLoader.loadTestsFromTestCase(Cases).run(result)
        self.assertFalse(result.payload()["ok"])
        self.assertEqual(result.payload()["counts"]["failed"], 1)
        self.assertNotIn("private-setup", json.dumps(result.payload()))


class AcceptanceFlowTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.scripts = self.root / "skills/carto-agent/scripts"
        self.scripts.mkdir(parents=True)
        (self.scripts.parent / "schemas").mkdir()
        (self.scripts.parent / "schemas/example.schema.json").write_text("{}", encoding="utf-8")
        policies = self.scripts.parent / "policies"
        policies.mkdir()
        (policies / "scenario-capabilities.yaml").write_text("schema_version: 1\nversion: 1.2.0\ndefault: deny\nprofiles: []\n", encoding="utf-8")
        data = self.root / "projects/dataset"
        data.mkdir(parents=True)
        (data / "landCover_reclassified.tif").write_bytes(b"II\x2a\x00synthetic-only")
        (data / "reclass_legend.csv").write_bytes(b"value,label\n1,synthetic-only\n")
        for name, value in (("REPO_ROOT", self.root), ("SCRIPTS_ROOT", self.scripts)):
            patcher = patch.object(harness, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        patcher = patch.object(harness, "SchemaRegistry")
        patcher.start()
        self.addCleanup(patcher.stop)
        self.calls = []
        self.cli_failure = False
        self.schema_incomplete = False
        self.regression_payload = {"ok": True, "tests_run": 1, "counts": {"passed": 1, "failed": 0, "skipped": 0},
                                   "data_kind": "synthetic_only", "records": [{"test_id": "synthetic.test", "status": "passed"}]}
        patcher = patch.object(harness, "invoke", side_effect=self.invoke)
        patcher.start()
        self.addCleanup(patcher.stop)

    def invoke(self, command, **kwargs):
        self.calls.append(command)
        code = 0
        if "--help" in command:
            text = "Carto Agent controlled CLI generate-map data"
            code = 2 if self.cli_failure else 0
        elif "schema" in command:
            text = json.dumps({"ok": True, "checked": 1, "schemas": [] if self.schema_incomplete else ["example"]})
        elif "dependencies" in command:
            text = json.dumps({"ok": True, "dependencies": {key: "importable" for key in harness.DEPENDENCIES}})
        else:
            text = json.dumps(self.regression_payload)
            code = 0 if self.regression_payload["ok"] else 2
        return subprocess.CompletedProcess(command, code, text, "private-stderr"), {"exit_code": code}

    def run_harness(self, *args):
        with redirect_stdout(io.StringIO()) as stream:
            code = harness.main(list(args))
        result = json.loads(stream.getvalue())
        report = json.loads((self.root / result["report_dir"] / "report.json").read_text(encoding="utf-8")) if "report_dir" in result else result
        return code, report

    def test_preflight_success_still_does_not_claim_plugin_or_real_map(self):
        code, report = self.run_harness("--host", "vscode-claude-code")
        self.assertEqual(code, 0)
        self.assertEqual(report["real_map_acceptance"], "not_completed")
        self.assertEqual(report["plugin_acceptance"], "not_verified")
        self.assertEqual(len(report["steps"]), 12)
        self.assertEqual(report["steps"][-3]["status"], "blocked")
        self.assertNotIn("private-stderr", json.dumps(report))
        self.assertTrue(all("landCover" not in " ".join(call) for call in self.calls))

    def test_cli_failure_stops_following_commands(self):
        self.cli_failure = True
        code, report = self.run_harness("--mode", "regression")
        self.assertEqual(code, 2)
        self.assertEqual(len(self.calls), 1)
        self.assertEqual(report["steps"][2]["code"], "PREVIOUS_STEP_FAILED")

    def test_schema_zero_exit_with_incomplete_payload_is_failure(self):
        self.schema_incomplete = True
        code, report = self.run_harness()
        self.assertEqual(code, 2)
        self.assertEqual(report["steps"][2]["code"], "SCHEMA_CHECK_INCOMPLETE")

    def test_input_outside_allowed_roots_is_rejected_and_reported(self):
        code, report = self.run_harness("--raster", str(self.root.parent / "not-authorized.tif"))
        self.assertEqual(code, 2)
        self.assertEqual(report["steps"][3]["code"], "PATH_OUTSIDE_ALLOWED_ROOT")

    def test_output_cannot_be_written_into_source_or_dataset(self):
        for target in ("skills/acceptance", "projects/dataset", "projects/.carto-dev", "projects"):
            with self.subTest(target=target):
                code, report = self.run_harness("--project-root", target)
                self.assertEqual(code, 2)
                self.assertIs(report["report_created"], False)

    def test_skipped_regression_is_incomplete_not_green(self):
        self.regression_payload["counts"] = {"passed": 0, "failed": 0, "skipped": 1}
        self.regression_payload["records"][0]["status"] = "skipped"
        code, report = self.run_harness("--mode", "regression")
        self.assertEqual(code, 3)
        self.assertEqual(report["steps"][7]["code"], "REGRESSION_HAS_SKIPS")

    def test_failing_regression_keeps_sanitized_details(self):
        self.regression_payload.update(ok=False, counts={"passed": 0, "failed": 1, "skipped": 0})
        self.regression_payload["records"][0]["status"] = "failed"
        code, report = self.run_harness("--mode", "regression")
        self.assertEqual(code, 2)
        self.assertEqual(report["steps"][7]["code"], "REGRESSION_FAILED")
        self.assertEqual(report["steps"][7]["evidence"]["artifact"], "regression.json")

    def test_input_mutation_is_detected_by_final_integrity_check(self):
        original = self.invoke
        def mutate(command, **kwargs):
            if "dependencies" in command:
                (self.root / "projects/dataset/reclass_legend.csv").write_bytes(b"changed-synthetic-only")
            return original(command, **kwargs)
        with patch.object(harness, "invoke", side_effect=mutate):
            code, report = self.run_harness()
        self.assertEqual(code, 2)
        self.assertEqual(report["steps"][8]["code"], "INPUT_OR_POLICY_CHANGED")


if __name__ == "__main__":
    unittest.main()
