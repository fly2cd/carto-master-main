"""Image-tool boundary ratchet: migrated image algorithms run only through ToolGateway.

Two structural guards (fail-only, no allowlists — this ratchet can only stay
tight or get tighter):

Guard 1 — scenario packages must not import the capability algorithm entry
points (``project_features`` / ``display_bounds`` / ``visible_window`` /
``solve_layout`` / ``check_layout``) from ``adapters.geo_to_image_pixels`` /
``adapters.image_display`` / ``adapters.annotation_solver``. Those algorithms
execute as authorized gateway capabilities bound in ``adapters.image_tools``;
scenario code reaches them only via the gateway (constants such as METHOD /
VERSION / ALGORITHM and the pure ``normalize_extent`` derivation stay
importable).

Guard 2 — the single-CLI rule: no entry-point script may appear beside
``carto.py`` under ``scripts/`` (the old ``data_summary.py`` second entry was
removed by folding it into the ``data-summary`` gateway capability).

Pure AST/path inspection: no projects, data or rendering.
"""
from __future__ import annotations

import ast
from pathlib import Path
import sys
import unittest

SCRIPTS_ROOT = Path(__file__).resolve().parents[1]
if str(SCRIPTS_ROOT) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_ROOT))

CORE = SCRIPTS_ROOT / "carto_core"
SCENARIOS = CORE / "scenarios"

# Modules whose capability algorithms are gateway-only for scenario packages.
GATEWAY_ONLY_MODULES = {
    "carto_core.adapters.geo_to_image_pixels",
    "carto_core.adapters.image_display",
    "carto_core.adapters.annotation_solver",
}
# Algorithm entry points that must never be imported by scenario code.
FORBIDDEN_NAMES = frozenset({"project_features", "display_bounds", "visible_window",
                             "solve_layout", "check_layout"})


def _module_key(node: ast.ImportFrom) -> str | None:
    module = node.module or ""
    for prefix in ("carto_core.adapters.", ".adapters.", "adapters."):
        if module.startswith(prefix):
            return "carto_core.adapters." + module[len(prefix):]
    return None


class ImageToolBoundaryTests(unittest.TestCase):
    def test_scenarios_never_import_gateway_only_algorithm_entry_points(self):
        violations: list[str] = []
        for path in sorted(SCENARIOS.rglob("*.py")):
            if "__pycache__" in path.parts:
                continue
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            short = path.relative_to(SCRIPTS_ROOT).as_posix()
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        if alias.name in GATEWAY_ONLY_MODULES:
                            violations.append(f"{short}: import {alias.name}")
                elif isinstance(node, ast.ImportFrom):
                    key = _module_key(node)
                    if key in GATEWAY_ONLY_MODULES:
                        forbidden = sorted(set(alias.name for alias in node.names) & FORBIDDEN_NAMES)
                        if forbidden:
                            violations.append(f"{short}: from {key} import {', '.join(forbidden)}")
        self.assertEqual([], violations)

    def test_scripts_root_has_no_entry_beside_the_single_cli(self):
        entries = sorted(path.name for path in SCRIPTS_ROOT.glob("*.py"))
        self.assertEqual(["carto.py"], entries)


if __name__ == "__main__":
    unittest.main()
