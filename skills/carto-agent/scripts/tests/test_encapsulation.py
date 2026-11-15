"""Encapsulation guard: private members must not cross object or module boundaries.

A leading underscore is a promise that the member is not a contract: its owner may change
its name, signature or semantics at any time. When another module -- let alone another
*layer* -- calls it, that promise is broken silently: nothing at import time, at type-check
time or in the owner's own tests will notice, and the caller breaks later.

This codebase had 24 such accesses and 12 private-name imports across four layers when the
guard was introduced (P1). Measured worst case: ``RasterPreparationService._json_ref`` was
called from compiler, adapters, scenarios and workflow (12 sites) and had to be declared on
a public port -- an underscore member inside ``contracts.protocols`` is a self-documenting
contradiction. It has since been renamed to ``document`` (P1 Step A).

The guard is a two-way ratchet:
  * a NEW private cross-boundary use fails (the detected set exceeds the allowlist);
  * a FIXED one also fails until the allowlist entry is deleted (the allowlist has a stale
    entry), so the list can only shrink and cannot silently become a junk drawer.

Two categories are excluded by rule rather than allowlisted, because they are not violations:
  * ``self._x`` / ``cls._x`` -- the object reaching into itself;
  * ``EnclosingClass._x`` -- a class calling its own static/class private member by name.

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

# Frozen, shrink-only. Key = private member name, value = why it is still here and what
# removes it. Adding a key requires justifying a new boundary break in review.
ALLOWED_ATTRIBUTES = {
    "_asset": "StaticAssetStore._asset: 5 cross-layer call sites (adapters x4, workflow.thematic). "
              "Renamed to a public member in P1 Step B.",
    "_validate": "PageRenderer._validate called from compiler.raster_scene -- kernel reaching into an "
                 "adapter's private method. Fixed in P1 Step D (page freeze/validate port).",
    "_scale_label": "PageRenderer._scale_label called from workflow.map_final_check. Fixed in P1 Step D.",
    "_directory_size": "ControlledBrowserRenderer._directory_size, called by a collaborator object inside "
                       "the same module family (adapters, intra-layer). Cosmetic rename, tracked as P2.",
    "_fields_": "ctypes.Structure._fields_ -- stdlib API, not a carto private member.",
    "_handle": "subprocess.Popen._handle -- stdlib private (the only way to get a Windows process handle "
               "for AssignProcessToJobObject); already carries a type: ignore.",
}

ALLOWED_IMPORTS = {
    "_publish_bytes": "adapters.geospatial_mcp._publish_bytes imported by adapters.formal_renderer and by "
                      "workflow.{raster_preparation,static_assets} -- a cross-layer private import. Moved to "
                      "carto_core.artifacts as a public helper in P1 Step B.",
    "_dependencies": "adapters.raster_renderer._dependencies (the plotting-stack accessor), imported by 3 "
                     "other adapters modules. Intra-layer; sibling of the vector dependencies() relocation, "
                     "tracked as P2.",
    "_number": "compiler.portrayal_resolver._number, imported by compiler.vector_portrayal. Intra-layer "
               "shared IR primitive; it is a delegating alias of the public finite(). Cosmetic, P2.",
    "_key": "compiler.portrayal_resolver._key, imported by compiler.vector_portrayal. Intra-layer shared "
            "IR primitive; cosmetic rename, P2.",
    "_size_symbol": "compiler.portrayal_resolver._size_symbol, imported by compiler.vector_portrayal. "
                    "Intra-layer shared IR primitive; cosmetic rename, P2.",
}


def modules():
    for path in sorted(CORE.rglob("*.py")):
        if "__pycache__" not in path.parts:
            rel = path.relative_to(SCRIPTS_ROOT).with_suffix("")
            yield ".".join(p for p in rel.parts if p != "__init__"), path


def enclosing_classes(tree: ast.AST) -> dict[int, str]:
    """Map every line number inside a class body to that class's name."""
    out: dict[int, str] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef):
            for sub in ast.walk(node):
                for line in range(getattr(sub, "lineno", 0), (getattr(sub, "end_lineno", 0) or 0) + 1):
                    out.setdefault(line, node.name)
    return out


def scan() -> tuple[dict[str, list[str]], dict[str, list[str]]]:
    attrs: dict[str, list[str]] = {}
    imports: dict[str, list[str]] = {}
    for module, path in modules():
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        owners = enclosing_classes(tree)
        short = module.replace("carto_core.", "")
        for node in ast.walk(tree):
            if (isinstance(node, ast.Attribute) and node.attr.startswith("_")
                    and not node.attr.startswith("__")):
                holder = node.value
                # Only a DIRECT ``self._x`` / ``cls._x`` is the object reaching into itself.
                # ``self.renderer._directory_size`` is NOT: the private member belongs to a
                # different object that self merely holds, so it stays a violation.
                if isinstance(holder, ast.Name) and holder.id in ("self", "cls"):
                    continue
                # A class naming its own private static/class member is also legitimate.
                if isinstance(holder, ast.Name) and holder.id == owners.get(node.lineno):
                    continue
                attrs.setdefault(node.attr, []).append(f"{short}:{node.lineno}")
            elif isinstance(node, ast.ImportFrom):
                for alias in node.names:
                    if alias.name.startswith("_") and not alias.name.startswith("__"):
                        imports.setdefault(alias.name, []).append(f"{short}:{node.lineno}")
    return attrs, imports


class EncapsulationTests(unittest.TestCase):
    def setUp(self):
        self.attrs, self.imports = scan()

    def test_no_new_private_attribute_is_reached_across_objects(self):
        unallowed = {name: sites for name, sites in self.attrs.items() if name not in ALLOWED_ATTRIBUTES}
        self.assertEqual({}, unallowed,
            "new cross-object private attribute access; make the member public (a private name is not a "
            "contract) instead of allowlisting it")

    def test_no_new_private_name_is_imported_across_modules(self):
        unallowed = {name: sites for name, sites in self.imports.items() if name not in ALLOWED_IMPORTS}
        self.assertEqual({}, unallowed,
            "new private-name import; promote the symbol to a public name in its owning module")

    def test_allowlist_has_no_stale_entries(self):
        # The ratchet's other direction: once a violation is fixed, its entry must be deleted.
        stale_attrs = sorted(set(ALLOWED_ATTRIBUTES) - set(self.attrs))
        stale_imports = sorted(set(ALLOWED_IMPORTS) - set(self.imports))
        self.assertEqual([], stale_attrs,
            f"these private accesses no longer exist; delete their ALLOWED_ATTRIBUTES entries: {stale_attrs}")
        self.assertEqual([], stale_imports,
            f"these private imports no longer exist; delete their ALLOWED_IMPORTS entries: {stale_imports}")

    def test_public_ports_declare_no_private_member(self):
        # The concrete symptom that motivated P1 Step A: an underscore member inside a
        # published Protocol. Ports are contracts; a contract cannot contain a non-contract.
        from carto_core.contracts import protocols
        offenders = []
        for name in dir(protocols):
            obj = getattr(protocols, name)
            if isinstance(obj, type) and getattr(obj, "_is_protocol", False):
                offenders += [f"{name}.{m}" for m in vars(obj)
                              if m.startswith("_") and not m.startswith("__") and callable(vars(obj)[m])]
        self.assertEqual([], offenders,
            "a Protocol declares a private member; rename the implementation member to a public name")

    def test_both_preparation_services_expose_document(self):
        # P1 Step A outcome: one name for "load a frozen contract document" on both geometries,
        # declared once on the common base protocol.
        from carto_core.contracts.protocols import (
            PreparationServiceProtocol, RasterPreparationProtocol, VectorPreparationProtocol,
        )
        self.assertIn("document", vars(PreparationServiceProtocol))
        self.assertNotIn("document", vars(RasterPreparationProtocol))
        self.assertNotIn("document", vars(VectorPreparationProtocol))
        self.assertNotIn("_json_ref", vars(RasterPreparationProtocol))


if __name__ == "__main__":
    unittest.main()
