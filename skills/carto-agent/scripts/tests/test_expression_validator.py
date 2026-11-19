"""ExpressionValidator guards: the catalog is a closed world, not a best-effort hint.

The validator is a live gate in template validation (template_validation.py:497-501),
so a rule name without a handler must fail closed rather than silently disable the
constraint. Also records the known class-count authority gap on the encoding-IR path.
"""
from __future__ import annotations

import json
from pathlib import Path
import sys
import unittest

SCRIPTS_ROOT = Path(__file__).resolve().parents[1]
if str(SCRIPTS_ROOT) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_ROOT))

from carto_core.compiler.expression_validator import ExpressionValidator, _RULE_HANDLERS
from carto_core.errors import ProtocolError
from carto_core.repository.map_expression_catalog import MapExpressionCatalog
from carto_core.schema_registry import SchemaRegistry, load_document

CATALOG_PATH = SCRIPTS_ROOT.parent / "policies" / "map-expression-catalog.yaml"
SCHEMAS = SCRIPTS_ROOT.parent / "schemas"


def _collect_max_items(node, names, out=None):
    """Walk a schema and collect maxItems per property name, regardless of nesting."""
    if out is None:
        out = {}
    if isinstance(node, dict):
        props = node.get("properties")
        if isinstance(props, dict):
            for name, spec in props.items():
                if name in names and isinstance(spec, dict) and "maxItems" in spec:
                    out.setdefault(name, set()).add(spec["maxItems"])
        for value in node.values():
            _collect_max_items(value, names, out)
    elif isinstance(node, list):
        for value in node:
            _collect_max_items(value, names, out)
    return out


class _StubCatalog:
    """Minimal catalog seam: returns one entry with the given validation rules."""

    def __init__(self, rules):
        self._entry = {"validation": {"rules": rules}, "parameter_definitions": []}

    def require(self, reference):
        return self._entry


class ExpressionValidatorTests(unittest.TestCase):
    def setUp(self):
        self.registry = SchemaRegistry()
        self.catalog = MapExpressionCatalog(self.registry)
        self.validator = ExpressionValidator(self.catalog, self.registry)

    def _layer(self, expression_id="graduated-color", version="2.0.0", **extra):
        return {"id": "area-layer", "data_role": "thematic-features", "geometry": "polygon",
                "map_expression_ref": self.catalog.reference(expression_id, version), **extra}

    def test_every_catalog_rule_name_has_a_handler(self):
        """Ratchet: a new catalog rule without a handler would silently disable itself."""
        document = load_document(CATALOG_PATH)
        declared = {rule["name"] for entry in document["entries"]
                    for rule in entry.get("validation", {}).get("rules", [])}
        self.assertTrue(declared, "catalog declares no validation rules")
        self.assertEqual(set(), declared - set(_RULE_HANDLERS),
                         "catalog rule names without a handler would fail closed at validation")

    def test_unknown_rule_name_is_a_blocker_not_silently_skipped(self):
        validator = ExpressionValidator(_StubCatalog([
            {"name": "parameter_enm", "param": "classification-method", "allowed": ["quantile"]}]),
            self.registry)
        findings = validator.validate_layer({"map_expression_ref": {"id": "x", "version": "1.0.0"},
                                             "classification-method": "NOT-ALLOWED"})
        self.assertEqual(1, len(findings))
        self.assertEqual("blocker", findings[0]["severity"])
        self.assertEqual("EXPRESSION_RULE_UNKNOWN", findings[0]["code"])

    def test_parameter_enum_violation_is_blocked(self):
        findings = self.validator.validate_layer(
            self._layer(**{"classification-method": "kmeans", "class-count": 5}))
        self.assertEqual(["EXPRESSION_PARAMETER_NOT_ALLOWED"], [f["code"] for f in findings])

    def test_missing_required_parameter_is_blocked(self):
        findings = self.validator.validate_layer(self._layer(**{"classification-method": "quantile"}))
        self.assertEqual(["EXPRESSION_PARAMETER_MISSING"], [f["code"] for f in findings])

    def test_parameter_range_violation_is_blocked(self):
        findings = self.validator.validate_layer(self._layer(**{"class-count": 13}))
        self.assertEqual(["EXPRESSION_PARAMETER_OUT_OF_RANGE"], [f["code"] for f in findings])

    def test_valid_parameters_have_no_findings(self):
        self.assertEqual([], self.validator.validate_layer(
            self._layer(**{"classification-method": "quantile", "class-count": 5})))

    def test_class_count_range_only_fires_with_a_classification_block(self):
        """The validator reads portrayal layers, not the IR.

        The IR path carries scale.categories instead of classification.class_count, so
        this rule cannot see it. The upper bound is enforced on that path by the IR
        schema itself (see the two guards below), not by this validator.
        """
        categorical = self._layer("categorical", "2.0.0", encoding_policy="explicit-per-panel")
        self.assertEqual([], self.validator.validate_layer(categorical))
        with_block = {**categorical, "classification": {"class_count": 13}}
        self.assertEqual(["EXPRESSION_CLASS_COUNT_OUT_OF_RANGE"],
                         [f["code"] for f in self.validator.validate_layer(with_block)])

    def test_parameter_definitions_carry_no_duplicate_constraints(self):
        """Allowed sets and ranges live only in validation.rules (single authority)."""
        document = load_document(CATALOG_PATH)
        allowed_keys = {"name", "type", "required", "default"}
        for entry in document["entries"]:
            for pdef in entry.get("parameter_definitions", []):
                with self.subTest(expression=entry["expression_id"], param=pdef["name"]):
                    self.assertLessEqual(set(pdef), allowed_keys,
                                         "constraint copy belongs in validation.rules, not here")

    def test_dedup_dropped_no_constraint(self):
        """Every enum/numeric parameter must still be constrained by a validation rule.

        Guards the dedup itself: removing parameter_definitions copies is only safe
        while validation.rules remains the enforced authority for each parameter.
        """
        document = load_document(CATALOG_PATH)
        for entry in document["entries"]:
            rules = entry.get("validation", {}).get("rules", [])
            constrained = {rule.get("param") for rule in rules
                           if rule["name"] in ("parameter_enum", "parameter_range")}
            for pdef in entry.get("parameter_definitions", []):
                if pdef["type"] in ("enum", "integer", "number"):
                    with self.subTest(expression=entry["expression_id"], param=pdef["name"]):
                        self.assertIn(pdef["name"], constrained,
                                      "parameter lost its only constraint during dedup")

    def test_class_count_upper_bound_has_a_single_authority(self):
        """Ratchet: every structural class-count bound must match the catalog maximum.

        The catalog's validation.rules[class_count_range] is the semantic authority.
        JSON Schema cannot read a YAML policy, so the structural bounds are held equal
        by this guard instead of drifting (they were 32 against a catalog max of 12).
        """
        document = load_document(CATALOG_PATH)
        maxima = {rule["max"] for entry in document["entries"]
                  for rule in entry.get("validation", {}).get("rules", [])
                  if rule["name"] == "class_count_range"}
        self.assertEqual(1, len(maxima), "catalog must declare exactly one class-count maximum")
        catalog_max = maxima.pop()
        for name in ("encoding-ir", "thematic-design", "vector-encoding"):
            schema = json.loads((SCHEMAS / f"{name}.schema.json").read_text(encoding="utf-8"))
            bounds = _collect_max_items(schema, {"categories", "symbols", "labels", "edges"})
            with self.subTest(schema=name):
                for field in ("categories", "symbols", "labels"):
                    self.assertIn(catalog_max, bounds[field],
                                  f"{name}.{field} must admit the catalog maximum")
                    self.assertTrue(all(b <= catalog_max for b in bounds[field]),
                                    f"{name}.{field} bounds {sorted(bounds[field])} exceed {catalog_max}")
                self.assertEqual({catalog_max + 1}, bounds["edges"],
                                 f"{name}.edges must admit exactly catalog_max intervals")

    def test_ir_rejects_more_classes_than_the_catalog_allows(self):
        """Closes the previously pinned gap: 13 categories must not pass the IR schema."""
        symbol = {"color": "#4477AA", "stroke": "#222222", "stroke_width_pt": 0.4, "radius_mm": 2}
        ir = {"schema_version": 1, "key_mode": "discrete", "geometry_role": "polygon",
              "domain": {"field": "value", "measurement": "nominal", "unit": None, "normalization": None},
              "scale": {"categories": [{"value": i, "label": f"Class {i}"} for i in range(1, 14)]},
              "channels": {"symbols": [{**symbol, "color": f"#{i:02X}0000"} for i in range(1, 14)],
                           "shape": "auto"},
              "missing": {"policy": "reject", "label": "Missing"},
              "legend": {"policy": "observed"}}
        with self.assertRaises(ProtocolError):
            self.registry.validate("encoding-ir", ir)
        ir["scale"]["categories"] = ir["scale"]["categories"][:12]
        ir["channels"]["symbols"] = ir["channels"]["symbols"][:12]
        self.registry.validate("encoding-ir", ir)


if __name__ == "__main__":
    unittest.main()