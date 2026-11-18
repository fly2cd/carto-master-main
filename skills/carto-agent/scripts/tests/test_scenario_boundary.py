"""Scenario-boundary guard: the generic kernel must not know scenario-specific things.

Orthogonal to ``test_layer_ports`` (which forbids the five formal-verification kernel
layers from importing ``workflow``/``adapters``). This guard covers a different axis:
the kernel -- *including* the orchestration ``workflow`` layer and the root registries --
must not depend on concrete ``scenarios`` implementations, nor read scenario-specific
request-body vocabulary. A new business scenario must be addable by writing its own
``scenarios/<name>/`` package plus one allowlist registration line, without editing
kernel code.

Two guards, each a two-way ratchet (cf. ``test_encapsulation``):
  * a NEW violation fails (detected set exceeds the allowlist);
  * a FIXED violation also fails until its allowlist entry is deleted (stale entry),
    so the list can only shrink.

Guard A -- kernel -> scenarios dependency:
  * any import resolving to ``carto_core.scenarios`` (module-level, deferred, or
    ``TYPE_CHECKING`` all count via AST walk);
  * any ``".scenarios."`` string literal (the registry's component allowlist).

Guard B -- scenario request-body vocabulary in the kernel:
  * ``request[key]`` / ``request.get(key)`` (also ``revised`` / ``variant_request``)
    where key is a scenario body field;
  * module-level constants enumerating those fields.

Guard B is a heuristic keyed on the request variable names {request, revised,
variant_request}; it is a ratchet aid against accidental re-coupling, not a security
boundary. Entries are keyed (module, field) without line numbers so they survive the
line shifts of an in-progress migration; an entry goes stale only when the module no
longer touches that field at all.

Synthetic only: pure AST inspection, no projects, data or rendering.
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

# Kernel = orchestration + formal-verification layers + adapters + root modules.
# ``scenarios`` itself is deliberately excluded: it is the plug-in side of the boundary.
KERNEL_DIRS = ("workflow", "compiler", "validation", "repository", "contracts", "security", "adapters")

# Scenario-specific request-body fields. The kernel must obtain these through scenario
# component hooks (request_contract / revision_contract / candidate_compiler.verify_request),
# never by reading them directly.
BODY_KEYS = frozenset({
    "source_bindings", "prepared_raster_bindings", "vector_sources", "vector_panels", "panels",
    "revised_cartography", "output_profile", "map_title", "layout_parameters", "charts",
    "basemap", "panel_designs",
})
REQUEST_NAMES = frozenset({"request", "revised", "variant_request"})

# --- Guard A allowlists (shrink-only) ---------------------------------------------
# (module, imported scenarios module). Removed when the kernel stops importing it.
# I-3: the registry now obtains geometry via request_contract; no static scenario import remains.
ALLOWED_SCENARIO_IMPORTS: dict[tuple[str, str], str] = {}
# Modules allowed to carry a ".scenarios." string literal (the designed registration point).
ALLOWED_SCENARIO_LITERALS = {
    "carto_core.scenario_registry":
        "The closed component allowlist (_COMPONENTS / manifest paths). This is the designed "
        "registration point; it becomes a manifest path in I-2 but remains a .scenarios. literal.",
}

# --- Guard B allowlists (shrink-only) ---------------------------------------------
# (module, body field) read via request[key]/request.get(key). Each phase deletes the
# entries it eliminates; the stale-entry test forces the deletion.
ALLOWED_BODY_READS = {
    ("carto_core.adapters.page_renderer", "panels"): "page rendering reads request body; shared rendering infra, addressed in Part II product loop.",
    ("carto_core.adapters.page_renderer", "basemap"): "page rendering reads request body; shared rendering infra, addressed in Part II product loop.",
    ("carto_core.adapters.static_page_renderer", "charts"): "static page reads request body; shared rendering infra, addressed in Part II product loop.",
    ("carto_core.adapters.static_page_renderer", "basemap"): "static page reads request body; shared rendering infra, addressed in Part II product loop.",
}
# (module, constant name) module-level constants enumerating body fields.
# I-5: revision_graph vocabulary moved to the scenario revision_contract; none remain.
ALLOWED_BODY_CONSTANTS: dict[tuple[str, str], str] = {}


def kernel_files():
    for layer in KERNEL_DIRS:
        for path in sorted((CORE / layer).rglob("*.py")):
            if "__pycache__" not in path.parts:
                yield path
    for path in sorted(CORE.glob("*.py")):
        if "__pycache__" not in path.parts:
            yield path


def short(path: Path) -> str:
    return ".".join(path.relative_to(SCRIPTS_ROOT).with_suffix("").parts)


def imported_modules(path: Path):
    package = list(path.parent.relative_to(SCRIPTS_ROOT).parts)
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                yield node.lineno, alias.name
        elif isinstance(node, ast.ImportFrom):
            if node.level == 0:
                base = node.module or ""
            else:
                keep = len(package) - (node.level - 1)
                base = ".".join(package[:keep] + ([node.module] if node.module else []))
            yield node.lineno, base
            for alias in node.names:
                yield node.lineno, f"{base}.{alias.name}" if base else alias.name


def scan():
    a_imports: set[tuple[str, str]] = set()
    a_literals: set[str] = set()
    b_reads: set[tuple[str, str]] = set()
    b_constants: set[tuple[str, str]] = set()
    for path in kernel_files():
        module = short(path)
        text = path.read_text(encoding="utf-8")
        tree = ast.parse(text, filename=str(path))
        for _, target in imported_modules(path):
            if target == "carto_core.scenarios" or target.startswith("carto_core.scenarios."):
                # Normalize to the scenarios subpackage base (drop the imported symbol).
                parts = target.split(".")
                base = ".".join(parts[:3]) if len(parts) >= 3 else target
                a_imports.add((module, base))
        for node in ast.walk(tree):
            if isinstance(node, ast.Constant) and isinstance(node.value, str) and ".scenarios." in node.value:
                a_literals.add(module)
            if (isinstance(node, ast.Subscript) and isinstance(node.value, ast.Name)
                    and node.value.id in REQUEST_NAMES
                    and isinstance(node.slice, ast.Constant) and node.slice.value in BODY_KEYS):
                b_reads.add((module, node.slice.value))
            if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                    and node.func.attr == "get" and isinstance(node.func.value, ast.Name)
                    and node.func.value.id in REQUEST_NAMES and node.args
                    and isinstance(node.args[0], ast.Constant) and node.args[0].value in BODY_KEYS):
                b_reads.add((module, node.args[0].value))
        for node in tree.body:
            if isinstance(node, (ast.Assign, ast.AnnAssign)):
                segment = ast.get_source_segment(text, node) or ""
                if any(f'"{k}"' in segment or f"'{k}'" in segment for k in BODY_KEYS):
                    target = node.targets[0] if isinstance(node, ast.Assign) else node.target
                    name = getattr(target, "id", None)
                    if name:
                        b_constants.add((module, name))
    return a_imports, a_literals, b_reads, b_constants


class ScenarioBoundaryTests(unittest.TestCase):
    def setUp(self):
        self.a_imports, self.a_literals, self.b_reads, self.b_constants = scan()

    def test_no_new_kernel_import_of_scenarios(self):
        unallowed = self.a_imports - set(ALLOWED_SCENARIO_IMPORTS)
        self.assertEqual(set(), unallowed,
            f"kernel imports a concrete scenario module: {sorted(unallowed)}. Obtain scenario "
            "behavior through a registered component hook, not by import.")

    def test_no_new_scenarios_string_literal_in_kernel(self):
        unallowed = self.a_literals - set(ALLOWED_SCENARIO_LITERALS)
        self.assertEqual(set(), unallowed,
            f"kernel carries a .scenarios. literal outside the registration allowlist: {sorted(unallowed)}")

    def test_no_new_scenario_body_field_read_in_kernel(self):
        unallowed = self.b_reads - set(ALLOWED_BODY_READS)
        self.assertEqual(set(), unallowed,
            f"kernel reads a scenario request-body field directly: {sorted(unallowed)}. Move the "
            "logic into a scenario component hook (request_contract / revision_contract / verify_request).")

    def test_no_new_scenario_body_constant_in_kernel(self):
        unallowed = self.b_constants - set(ALLOWED_BODY_CONSTANTS)
        self.assertEqual(set(), unallowed,
            f"kernel declares a constant enumerating scenario body fields: {sorted(unallowed)}")

    def test_allowlists_have_no_stale_entries(self):
        # The ratchet's other direction: a fixed violation must have its entry deleted.
        stale = {
            "ALLOWED_SCENARIO_IMPORTS": sorted(set(ALLOWED_SCENARIO_IMPORTS) - self.a_imports),
            "ALLOWED_SCENARIO_LITERALS": sorted(set(ALLOWED_SCENARIO_LITERALS) - self.a_literals),
            "ALLOWED_BODY_READS": sorted(set(ALLOWED_BODY_READS) - self.b_reads),
            "ALLOWED_BODY_CONSTANTS": sorted(set(ALLOWED_BODY_CONSTANTS) - self.b_constants),
        }
        stale = {k: v for k, v in stale.items() if v}
        self.assertEqual({}, stale,
            f"these violations no longer exist; delete their allowlist entries: {stale}")


if __name__ == "__main__":
    unittest.main()