"""Guard: design-doc YAML examples must be machine-classified and current-valid.

Convention — the first non-empty line inside a ```yaml fence carries a directive:

    # schema-check: <schema-name>   current-complete example; MUST validate against
                                    that registered schema (directive line stripped)
    # illustrative: <note>          target design / partial skeleton / proposal;
                                    excluded from current validation
    (unmarked)                      skipped, but counted

This catches the doc-code drift where a target-vocabulary example (e.g. the
schema_version 2 proposal in map-layout.md §10.2) is mistaken for current
protocol. The current-valid counterpart lives in map-layout.md §10.3 and is
generated from the real layout contract. See the evaluation of doc design
alignment (doc/template/map-layout.md §10).
"""
from __future__ import annotations

import re
import sys
import unittest
from pathlib import Path

SCRIPTS_ROOT = Path(__file__).resolve().parents[1]
if str(SCRIPTS_ROOT) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_ROOT))

import yaml
from carto_core.errors import CartoError
from carto_core.schema_registry import SchemaRegistry

DOC_TEMPLATE = SCRIPTS_ROOT.parents[2] / "doc" / "template"
_FENCE = re.compile(r"```yaml[^\n]*\n(.*?)```", re.DOTALL)


def _yaml_blocks(text: str):
    for match in _FENCE.finditer(text):
        body = match.group(1)
        first = next((line for line in body.splitlines() if line.strip()), "")
        yield first.strip(), body


def _classify(first: str):
    if first.startswith("# schema-check:"):
        return "check", first.split(":", 1)[1].strip()
    if first.startswith("# illustrative:"):
        return "illustrative", None
    return "unmarked", None


def _payload(body: str):
    lines = []
    dropped = False
    for line in body.splitlines():
        if not dropped and line.strip().startswith("# schema-check:"):
            dropped = True
            continue
        lines.append(line)
    return yaml.safe_load("\n".join(lines))


def _iter_docs():
    for path in sorted(DOC_TEMPLATE.glob("*.md")):
        yield path, path.read_text(encoding="utf-8")


class DocExampleTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.registry = SchemaRegistry()

    def test_schema_check_examples_validate_against_current_schema(self) -> None:
        failures = []
        checked = 0
        for path, text in _iter_docs():
            for first, body in _yaml_blocks(text):
                kind, schema = _classify(first)
                if kind != "check":
                    continue
                checked += 1
                try:
                    document = _payload(body)
                    self.registry.validate(schema, document)
                except (CartoError, yaml.YAMLError, ValueError) as exc:
                    failures.append(f"{path.name} -> {schema}: {exc}")
        self.assertGreater(checked, 0, "no # schema-check example found; convention not adopted")
        self.assertEqual(failures, [], "current-doc examples failed schema validation:\n" + "\n".join(failures))

    def test_current_layout_example_is_present(self) -> None:
        # The flagship layout doc must carry a current-valid, schema-checkable example
        # (map-layout.md §10.3), so the guard actually exercises layout validation.
        found = False
        for path, text in _iter_docs():
            for first, body in _yaml_blocks(text):
                kind, schema = _classify(first)
                if kind == "check" and schema == "layout":
                    found = True
        self.assertTrue(found, "expected a # schema-check: layout example in doc/template")

    def test_v2_layout_proposal_is_not_marked_current(self) -> None:
        # The schema_version 2 sidebar proposal (§10.2) uses target vocabulary
        # (slot/text_flow/arrangement/overflow.actions) absent from the current
        # schema; it must never be tagged schema-check.
        for path, text in _iter_docs():
            for first, body in _yaml_blocks(text):
                if "layout_id: a3-landscape-sidebar" in body:
                    kind, _ = _classify(first)
                    self.assertNotEqual(
                        kind, "check",
                        f"{path.name}: the v2 sidebar proposal must be # illustrative, not # schema-check")


if __name__ == "__main__":
    unittest.main()