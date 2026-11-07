from __future__ import annotations

import contextlib
from copy import deepcopy
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

SCRIPTS_ROOT = Path(__file__).resolve().parents[1]
if str(SCRIPTS_ROOT) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_ROOT))

from carto_core.adapters.host_probe import HermesHostProbe, _local_result
from carto_core.cli import main
from carto_core.errors import ProtocolError, SecurityError
from carto_core.schema_registry import SchemaRegistry, load_document

FIXTURES = Path(__file__).parent / "fixtures"
WORKER = SCRIPTS_ROOT / "carto_core/adapters/hermes_probe_worker.py"
RESOURCE = SCRIPTS_ROOT.parent / "schemas/layout.schema.json"


class HostProbeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name).resolve()
        self.project = self.root / "project"
        self.home = self.root / "hermes"
        self.skill = self.project / "skills/carto-agent"
        (self.skill / "schemas").mkdir(parents=True)
        (self.skill / "SKILL.md").write_text("---\nname: carto-agent\n---\nUnit-test skill\n", encoding="utf-8")
        (self.skill / "schemas/layout.schema.json").write_bytes(RESOURCE.read_bytes())
        (self.home / "bin").mkdir(parents=True)
        (self.home / "bin" / ("hermes.exe" if os.name == "nt" else "hermes")).write_bytes(b"not-executed-test-stub")
        self.source = self.home / "hermes-agent"
        self.source.mkdir()
        (self.source / "pyproject.toml").write_text('[project]\nversion = "0.21.1"\n', encoding="utf-8")
        self.config = self.home / "config.yaml"
        self.config.write_text("terminal:\n  backend: local\n", encoding="utf-8")
        self.probe = HermesHostProbe(allowed_roots=[str(self.root)], project_root=str(self.project), host_home=str(self.home))
        self.registry = SchemaRegistry()

    def test_static_probe_never_executes_host_and_never_claims_session(self) -> None:
        with patch("carto_core.adapters.host_probe.subprocess.run") as run:
            report = self.probe.run()
        run.assert_not_called()
        self.assertTrue(report["installation"]["executable_present"])
        self.assertEqual(report["installation"]["source_version"], "0.21.1")
        self.assertEqual(report["configuration"]["state"], "read")
        self.assertFalse(report["active_session_verified"])
        self.assertFalse(report["stage_passed"])
        self.assertFalse(report["production_ready"])
        self.assertEqual(set(report["capabilities"].values()), {"unverified"})

    def test_config_is_summarized_without_names_commands_urls_or_env(self) -> None:
        self.config.write_text('''terminal:
  backend: local
mcp_servers:
  SECRET_NAME:
    command: SECRET_COMMAND
    args: [SECRET_ARGUMENT]
    env: {TOKEN: SECRET_TOKEN}
  other:
    url: https://SECRET_HOST/?key=SECRET_QUERY
''', encoding="utf-8")
        report = self.probe.run()
        self.assertNotIn("SECRET", json.dumps(report))
        self.assertEqual([x["transport"] for x in report["configuration"]["mcp_servers"]], ["stdio", "remote"])
        self.assertEqual(report["configuration"]["mcp_servers"][0]["verification"], "not-connected")

    def test_malformed_config_does_not_leak_parser_source(self) -> None:
        for data in ("mcp_servers: [SECRET_TOKEN", "[]", "mcp_servers: []", "terminal: 17", "mcp_servers: {x: false}"):
            with self.subTest(data=data):
                self.config.write_text(data, encoding="utf-8")
                report = self.probe.run()
                self.assertIn(report["configuration"]["state"], {"invalid", "unreadable"})
                self.assertNotIn("SECRET_TOKEN", json.dumps(report))

    def test_missing_config_is_not_evidence_of_no_tools(self) -> None:
        self.config.unlink()
        report = self.probe.run()
        self.assertEqual(report["configuration"]["state"], "missing")
        self.assertEqual(report["capabilities"]["gis_read"], "unverified")

    def test_large_config_is_not_parsed(self) -> None:
        self.config.write_text("#" * (512 * 1024 + 1), encoding="utf-8")
        with patch("carto_core.adapters.host_probe.load_document") as loader:
            report = self.probe.run()
        loader.assert_not_called()
        self.assertEqual(report["configuration"]["state"], "invalid")

    def test_roots_checked_before_host_reads(self) -> None:
        with self.assertRaises(SecurityError):
            HermesHostProbe(allowed_roots=[str(self.project)], project_root=str(self.project), host_home=str(self.home))

    def test_report_only_written_inside_project_and_never_overwritten(self) -> None:
        report = self.probe.run()
        with self.assertRaises(SecurityError):
            self.probe.save(report, str(self.home / "report.json"))
        path = self.probe.save(report, "reports/inspection.json")
        self.assertEqual(load_document(path), report)
        original = path.read_bytes()
        with self.assertRaises(FileExistsError):
            self.probe.save(report, "reports/inspection.json")
        self.assertEqual(path.read_bytes(), original)
        with self.assertRaises(ProtocolError):
            self.probe.save(report, "reports/inspection.yaml")

    def test_runtime_requires_explicit_opt_in_and_interpreter(self) -> None:
        for kwargs in ({"verify_local_tools": True}, {"host_python": sys.executable}):
            with self.subTest(kwargs=kwargs), self.assertRaises(ProtocolError):
                self.probe.run(**kwargs)

    def test_timeout_range_checked_before_launch(self) -> None:
        with patch("carto_core.adapters.host_probe.subprocess.run") as run:
            for timeout in (0, 121, float("nan")):
                with self.subTest(timeout=timeout), self.assertRaises(ProtocolError):
                    self.probe.run(verify_local_tools=True, host_python=str(self.home / "fake-python"), timeout=timeout)
        run.assert_not_called()

    def _runtime(self, **kwargs):
        interpreter = self.home / "fake-python"
        interpreter.write_bytes(b"never-executed")
        return self.probe.run(verify_local_tools=True, host_python=str(interpreter), **kwargs)

    def test_timeout_is_recorded_not_a_success(self) -> None:
        with patch("carto_core.adapters.host_probe.subprocess.run", side_effect=subprocess.TimeoutExpired("host", 1, output="SECRET")):
            report = self._runtime(timeout=1)
        self.assertEqual(report["local_probe"]["status"], "timeout")
        self.assertNotIn("SECRET", json.dumps(report))

    def test_failed_or_invalid_child_never_leaks_stdout_stderr(self) -> None:
        results = [
            subprocess.CompletedProcess([], 1, "SECRET", "SECRET"),
            subprocess.CompletedProcess([], 0, "SECRET", "SECRET"),
            subprocess.CompletedProcess([], 0, '{"status":"passed", "secret":"SECRET"}', "SECRET"),
        ]
        for result in results:
            with self.subTest(result=result), patch("carto_core.adapters.host_probe.subprocess.run", return_value=result):
                report = self._runtime()
            self.assertEqual(report["local_probe"]["status"], "failed")
            self.assertNotIn("SECRET", json.dumps(report))

    def test_runtime_success_still_cannot_approve_session_or_map(self) -> None:
        result = _local_result("passed", "LOCAL_RESOURCE_READ_VERIFIED")
        result.update(skill_document_read=True, resource_read=True, tool_names=["skill_view"])
        with patch("carto_core.adapters.host_probe.subprocess.run", return_value=subprocess.CompletedProcess([], 0, json.dumps(result), "")) as run:
            report = self._runtime()
        self.assertEqual(report["local_probe"]["status"], "passed")
        self.assertFalse(report["active_session_verified"])
        self.assertFalse(report["stage_passed"])
        self.assertFalse(report["production_ready"])
        self.assertIn("-I", run.call_args.args[0])
        self.assertEqual(run.call_args.kwargs["timeout"], 30)
        self.assertEqual(run.call_args.kwargs["cwd"], self.project)

    def test_child_environment_does_not_receive_provider_keys(self) -> None:
        with patch.dict(os.environ, {"OPENAI_API_KEY": "SECRET", "ANTHROPIC_API_KEY": "SECRET", "TERMINAL_ENV": "ssh"}):
            with patch("carto_core.adapters.host_probe.subprocess.run", return_value=subprocess.CompletedProcess([], 1, "", "")) as run:
                self._runtime()
        env = run.call_args.kwargs["env"]
        self.assertNotIn("OPENAI_API_KEY", env)
        self.assertNotIn("ANTHROPIC_API_KEY", env)
        self.assertEqual(env["TERMINAL_ENV"], "local")

    def test_link_registration_only_inspects_metadata(self) -> None:
        parent = self.home / "skills/creative"
        parent.mkdir(parents=True)
        link = parent / "carto-agent"
        try:
            link.symlink_to(self.skill, target_is_directory=True)
        except OSError:
            self.skipTest("Creating symlinks is not permitted on this platform")
        report = self.probe.run()
        self.assertTrue(report["skill"]["registrations"][0]["matches_workspace"])
        link.unlink()
        link.symlink_to(self.root / "unapproved-missing-target", target_is_directory=True)
        report = self.probe.run()
        self.assertFalse(report["skill"]["registrations"][0]["matches_workspace"])

    def test_cli_success_means_inspection_not_readiness(self) -> None:
        args = ["environment", "probe-host", "--host-home", str(self.home), "--project-root", str(self.project), "--allowed-root", str(self.root), "--output", "report.json"]
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = main(args)
        self.assertEqual(code, 0)
        payload = json.loads(out.getvalue())
        self.assertTrue(payload["ok"])
        self.assertFalse(payload["host_preflight"]["stage_passed"])
        self.assertEqual(Path(payload["report_path"]), self.project / "report.json")

    def test_worker_calls_mock_installed_api_without_leaking_tool_content(self) -> None:
        tools = self.source / "tools"
        tools.mkdir()
        (tools / "__init__.py").write_text("", encoding="utf-8")
        code = "import json\nfrom pathlib import Path\n" + f"SKILL = Path({str(self.skill)!r})\n" + '''def skill_view(name, *, file_path, task_id, preprocess):
    assert name == "carto-agent" and preprocess is False
    print("SECRET_NOISE")
    return json.dumps({"success": True, "content": (SKILL / file_path).read_text(encoding="utf-8"), "_source_path": str(SKILL / file_path)})
'''
        (tools / "skills_tool.py").write_text(code, encoding="utf-8")
        completed = subprocess.run([sys.executable, "-I", "-B", str(WORKER), str(self.source), str(self.home), str(self.skill)], capture_output=True, text=True, timeout=15)
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertNotIn("SECRET_NOISE", completed.stdout + completed.stderr)
        self.assertEqual(json.loads(completed.stdout)["status"], "passed")

    def test_worker_rejects_equal_content_from_wrong_skill_path(self) -> None:
        tools = self.source / "tools"
        tools.mkdir()
        (tools / "__init__.py").write_text("", encoding="utf-8")
        code = "import json\nfrom pathlib import Path\n" + f"SKILL = Path({str(self.skill)!r})\n" + (
            'def skill_view(name, *, file_path, task_id, preprocess):\n'
            '    return json.dumps({"success": True, "content": (SKILL / file_path).read_text(encoding="utf-8"), "_source_path": str(SKILL / "wrong-copy" / file_path)})\n'
        )
        (tools / "skills_tool.py").write_text(code, encoding="utf-8")
        completed = subprocess.run([sys.executable, "-I", "-B", str(WORKER), str(self.source), str(self.home), str(self.skill)], capture_output=True, text=True, timeout=15)
        self.assertEqual(completed.returncode, 0, completed.stderr)
        result = json.loads(completed.stdout)
        self.assertEqual(result["status"], "failed")
        self.assertFalse(result["skill_document_read"])
        self.assertFalse(result["resource_read"])

    def test_worker_blocks_credentials_network_and_writes(self) -> None:
        tools = self.source / "tools"
        tools.mkdir()
        (tools / "__init__.py").write_text("", encoding="utf-8")
        secret = self.home / ".env"
        secret.write_text("SECRET", encoding="utf-8")
        target = self.project / "must-not-exist.txt"
        snippets = [
            f"open({str(secret)!r}).read()",
            f"open({str(target)!r}, 'w').write('changed')",
            "__import__('socket').create_connection(('127.0.0.1', 9), timeout=1)",
            "__import__('subprocess').run(['not-a-real-command'])",
        ]
        for snippet in snippets:
            with self.subTest(snippet=snippet):
                (tools / "skills_tool.py").write_text("def skill_view(*args, **kwargs):\n    " + snippet + "\n", encoding="utf-8")
                completed = subprocess.run([sys.executable, "-I", "-B", str(WORKER), str(self.source), str(self.home), str(self.skill)], capture_output=True, text=True, timeout=15)
                self.assertEqual(completed.returncode, 0, completed.stderr)
                self.assertEqual(json.loads(completed.stdout)["status"], "failed")
                self.assertFalse(target.exists())
                self.assertEqual(secret.read_text(encoding="utf-8"), "SECRET")

    def test_input_drift_during_probe_invalidates_local_success(self) -> None:
        result = _local_result("passed", "LOCAL_RESOURCE_READ_VERIFIED")
        result.update(skill_document_read=True, resource_read=True, tool_names=["skill_view"])
        def changed(*args, **kwargs):
            (self.skill / "SKILL.md").write_text("changed", encoding="utf-8")
            return subprocess.CompletedProcess([], 0, json.dumps(result), "")
        with patch("carto_core.adapters.host_probe.subprocess.run", side_effect=changed):
            report = self._runtime()
        self.assertEqual(report["local_probe"]["code"], "HOST_PROBE_INPUT_CHANGED")
        self.assertEqual(report["local_probe"]["status"], "failed")

    def test_real_child_timeout_is_bounded(self) -> None:
        tools = self.source / "tools"
        tools.mkdir()
        (tools / "__init__.py").write_text("", encoding="utf-8")
        (tools / "skills_tool.py").write_text("import time\ntime.sleep(10)\n", encoding="utf-8")
        probe = HermesHostProbe(allowed_roots=[str(self.root), str(Path(sys.executable).parent)],
                                project_root=str(self.project), host_home=str(self.home))
        report = probe.run(verify_local_tools=True, host_python=sys.executable, timeout=1)
        self.assertEqual(report["local_probe"]["code"], "HOST_PROBE_TIMEOUT")

    def test_schema_valid_and_invalid_examples(self) -> None:
        self.registry.validate("host-preflight", load_document(FIXTURES / "host-preflight.valid.json"))
        with self.assertRaises(ProtocolError):
            self.registry.validate("host-preflight", load_document(FIXTURES / "host-preflight.invalid.json"))

    def test_schema_rejects_nested_unknown_fields_and_false_readiness(self) -> None:
        valid = load_document(FIXTURES / "host-preflight.valid.json")
        for key in ("active_session_verified", "stage_passed", "production_ready"):
            invalid = deepcopy(valid)
            invalid[key] = True
            with self.subTest(key=key), self.assertRaises(ProtocolError):
                self.registry.validate("host-preflight", invalid)
        for key in ("configuration", "local_probe", "capabilities", "skill", "resource", "installation"):
            invalid = deepcopy(valid)
            invalid[key]["secret"] = "not allowed"
            with self.subTest(nested=key), self.assertRaises(ProtocolError):
                self.registry.validate("host-preflight", invalid)
        invalid = deepcopy(valid)
        invalid["local_probe"]["status"] = "passed"
        with self.assertRaises(ProtocolError):
            self.registry.validate("host-preflight", invalid)


if __name__ == "__main__":
    unittest.main()
