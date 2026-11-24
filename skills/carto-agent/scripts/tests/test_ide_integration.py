from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
import unittest


REPO_ROOT = Path(__file__).resolve().parents[4]
SCRIPTS_ROOT = REPO_ROOT / "skills/carto-agent/scripts"
if str(SCRIPTS_ROOT) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_ROOT))
CLI = "${workspaceFolder}/skills/carto-agent/scripts/carto.py"
TESTS = "${workspaceFolder}/skills/carto-agent/scripts/tests"
RUNNER = "${workspaceFolder}/skills/carto-agent/scripts/tests/run_tests.py"


class IdeIntegrationTests(unittest.TestCase):
    """Check repository IDE wiring, not extension installation or live sessions."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.config = json.loads((REPO_ROOT / ".vscode/tasks.json").read_text(encoding="utf-8"))
        cls.tasks = {task["label"]: task for task in cls.config["tasks"]}

    def _run_task(self, label: str, *extra_args: str) -> subprocess.CompletedProcess[str]:
        task = self.tasks[label]

        def expand(value: str) -> str:
            value = value.replace("${workspaceFolder}", str(REPO_ROOT))
            value = value.replace("${command:python.interpreterPath}", sys.executable)
            self.assertNotIn("${", value)
            return value

        # Substitute the test interpreter for VS Code's selected-interpreter command.
        # This exercises actual CLI commands, without pretending to run the extension.
        return subprocess.run(
            [expand(task["command"]), *(expand(arg) for arg in task["args"]), *extra_args],
            cwd=expand(task["options"]["cwd"]),
            env={**os.environ, **task["options"]["env"]},
            shell=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=30,
            check=False,
        )

    def test_tasks_use_selected_python_without_shell_or_autorun(self) -> None:
        self.assertEqual(self.config["version"], "2.0.0")
        self.assertEqual(len(self.tasks), len(self.config["tasks"]))
        for task in self.tasks.values():
            with self.subTest(task=task["label"]):
                self.assertEqual(task["type"], "process")
                self.assertEqual(task["command"], "${command:python.interpreterPath}")
                self.assertEqual(task["options"], {
                    "cwd": "${workspaceFolder}", "env": {"PYTHONUTF8": "1"},
                })
                self.assertEqual(task["problemMatcher"], [])
                self.assertIsInstance(task["args"], list)
                for key in ("runOptions", "dependsOn", "windows", "linux", "osx"):
                    self.assertNotIn(key, task)

    def test_regression_discovery_is_importable_and_unique(self) -> None:
        from collections import Counter
        from tests.run_tests import discover, iter_cases

        cases = list(iter_cases(discover()))
        ids = [case.id() for case in cases]
        self.assertTrue(ids, "Regression discovery must not be empty")
        self.assertEqual([], [test_id for test_id in ids if "_FailedTest." in test_id])
        self.assertEqual({}, {test_id: count for test_id, count in Counter(ids).items() if count > 1},
                         "Import fixture modules rather than TestCase classes to avoid duplicate runs")

    def test_task_commands_are_generic_and_only_use_existing_entrypoints(self) -> None:
        expected = {
            "Carto: CLI help": [CLI, "--help"],
            "Carto: Check schemas": [CLI, "schema", "check"],
            "Carto: Probe renderer": [CLI, "environment", "probe-renderer"],
            "Carto: Test IDE integration": [
                "-m", "unittest", "discover", "-s", TESTS, "-p", "test_ide_integration.py", "-v",
            ],
            # Tiered regression runner: fast inner loop, slow real-rendering tier, the
            # full merge gate, and the pass that rewrites the timing baseline.
            "Carto: Run tests (fast tier)": [RUNNER, "--tier", "fast"],
            "Carto: Run tests (slow tier)": [RUNNER, "--tier", "slow"],
            "Carto: Run tests": [RUNNER, "--tier", "full"],
            "Carto: Re-measure test baseline": [RUNNER, "--measure", "--quiet"],
        }
        self.assertEqual({label: task["args"] for label, task in self.tasks.items()}, expected)
        self.assertTrue((REPO_ROOT / "skills/carto-agent/scripts/carto.py").is_file())
        self.assertTrue((REPO_ROOT / "skills/carto-agent/scripts/tests").is_dir())
        self.assertTrue((REPO_ROOT / "skills/carto-agent/scripts/tests/run_tests.py").is_file())

    def test_extensions_are_recommendations_not_machine_settings(self) -> None:
        config = json.loads((REPO_ROOT / ".vscode/extensions.json").read_text(encoding="utf-8"))
        self.assertEqual(config, {
            "recommendations": ["ms-python.python", "openai.chatgpt", "anthropic.claude-code"],
        })

    def test_both_agents_share_the_single_skill_instruction_chain(self) -> None:
        claude = (REPO_ROOT / "CLAUDE.md").read_text(encoding="utf-8")
        agents = (REPO_ROOT / "AGENTS.md").read_text(encoding="utf-8")
        self.assertIn("@AGENTS.md", claude.splitlines())
        self.assertIn("skills/carto-agent/SKILL.md", agents)
        skill = (REPO_ROOT / "skills/carto-agent/SKILL.md").read_text(encoding="utf-8")
        self.assertIn("workflows/routing.md", skill)
        self.assertIn("skills/carto-agent/scripts/carto.py", skill)

    def test_only_shared_vscode_configuration_is_unignored(self) -> None:
        rules = (REPO_ROOT / ".gitignore").read_text(encoding="utf-8").splitlines()
        self.assertNotIn(".vscode/", rules)
        self.assertIn(".vscode/*", rules)
        self.assertEqual(
            [rule for rule in rules if rule.startswith("!.vscode/")],
            ["!.vscode/tasks.json", "!.vscode/extensions.json"],
        )

    def test_help_task_runs_the_real_cli(self) -> None:
        result = self._run_task("Carto: CLI help")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("Carto Agent controlled CLI", result.stdout)
        self.assertIn("generate-map", result.stdout)
        self.assertIn("create-template", result.stdout)

    def test_schema_task_runs_and_reports_all_registered_schemas(self) -> None:
        result = self._run_task("Carto: Check schemas")
        self.assertEqual(result.returncode, 0, result.stderr)
        report = json.loads(result.stdout)
        self.assertIs(report["ok"], True)
        self.assertGreater(report["checked"], 0)
        self.assertEqual(report["checked"], len(report["schemas"]))
        self.assertEqual(
            set(report["schemas"]),
            {path.name.removesuffix(".schema.json")
             for path in (REPO_ROOT / "skills/carto-agent/schemas").glob("*.schema.json")},
        )

    def test_cli_error_exit_is_not_hidden_by_the_task(self) -> None:
        result = self._run_task("Carto: Check schemas", "--unsupported-ide-option")
        self.assertEqual(result.returncode, 2)
        self.assertIn("--unsupported-ide-option", result.stderr)
        self.assertEqual(result.stdout, "")


if __name__ == "__main__":
    unittest.main()
