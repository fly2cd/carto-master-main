"""Expression parameter validation driven by the map-expression catalog.

Each catalog entry declares its own validation rules and fixture specification.
This module validates portrayal layer parameters against those catalog-defined
rules — it does not hardcode expression-specific checks.
"""
from __future__ import annotations

from typing import Any

from .map_candidate import MapCandidateCompiler  # noqa: F401 — re-exported by __init__
from ..canonical import sha256_digest
from ..errors import ProtocolError
from ..schema_registry import SchemaRegistry


class ExpressionValidator:
    """Validate portrayal layer parameters against the expression catalog entry."""

    def __init__(self, catalog: Any, registry: SchemaRegistry | None = None) -> None:
        self._catalog = catalog
        self.registry = registry or SchemaRegistry()

    # -- public API -----------------------------------------------------------

    def validate_layer(self, layer: dict[str, Any]) -> list[dict[str, Any]]:
        """Return findings (empty list = pass).  Severity is 'blocker' or 'warning'."""
        entry = self._catalog.require(layer["map_expression_ref"])
        findings: list[dict[str, Any]] = []
        validation = entry.get("validation", {})
        for rule in validation.get("rules", []):
            finding = self._check_rule(rule, layer, entry)
            if finding is not None:
                findings.append(finding)
        return findings

    def fixture_kind(self, expression_ref: dict[str, str]) -> str:
        """Return the ``fixture.kind`` declared by this expression, or ``"none"``."""
        entry = self._catalog.require(expression_ref)
        return entry.get("fixture", {}).get("kind", "none")

    # -- rule dispatch --------------------------------------------------------

    def _check_rule(self, rule: dict[str, Any], layer: dict[str, Any],
                    entry: dict[str, Any]) -> dict[str, Any] | None:
        name = rule["name"]
        handler = _RULE_HANDLERS.get(name)
        if handler is None:
            return None  # forward-compat: unknown rules are not errors
        try:
            return handler(rule, layer, entry, self._catalog)
        except ProtocolError as exc:
            return {"severity": "blocker", "code": exc.code, "message": str(exc)}
        except Exception as exc:
            return {"severity": "blocker", "code": "EXPRESSION_VALIDATION_ERROR",
                    "message": f"{name}: {exc}"}


# -- rule implementations ----------------------------------------------------

def _check_class_count_range(rule: dict[str, Any], layer: dict[str, Any],
                             entry: dict[str, Any], catalog: Any) -> dict[str, Any] | None:
    """Validate that the number of legend items / classes is within the allowed range."""
    min_val = rule.get("min", 2)
    max_val = rule.get("max", 12)
    # For categorical expressions the layer itself doesn't carry the class count;
    # it comes from the fixture data.  This rule fires only when the layer carries
    # a per-layer class_count parameter (e.g. graduated expressions).
    class_count = layer.get("classification", {}).get("class_count")
    if class_count is None:
        return None  # not applicable — fixture handles this
    if not (min_val <= class_count <= max_val):
        return {"severity": "blocker", "code": "EXPRESSION_CLASS_COUNT_OUT_OF_RANGE",
                "message": f"class_count {class_count} not in [{min_val}, {max_val}]"}
    return None


def _check_parameter_range(rule: dict[str, Any], layer: dict[str, Any],
                           entry: dict[str, Any], catalog: Any) -> dict[str, Any] | None:
    """Check that a numeric parameter stays within [min, max]."""
    param = rule["param"]
    value = layer.get(param)
    if value is None:
        # Parameter may be optional — check the catalog definition
        for pdef in entry.get("parameter_definitions", []):
            if pdef["name"] == param:
                if pdef.get("required"):
                    return {"severity": "blocker", "code": "EXPRESSION_PARAMETER_MISSING",
                            "message": f"Required parameter '{param}' is missing"}
                return None  # optional and absent
        return None  # unknown parameter — forward compat
    low = rule.get("min")
    high = rule.get("max")
    if low is not None and value < low:
        return {"severity": "blocker", "code": "EXPRESSION_PARAMETER_OUT_OF_RANGE",
                "message": f"{param}={value} < min={low}"}
    if high is not None and value > high:
        return {"severity": "blocker", "code": "EXPRESSION_PARAMETER_OUT_OF_RANGE",
                "message": f"{param}={value} > max={high}"}
    return None


def _check_parameter_enum(rule: dict[str, Any], layer: dict[str, Any],
                          entry: dict[str, Any], catalog: Any) -> dict[str, Any] | None:
    """Check that a value is one of the allowed set."""
    param = rule["param"]
    allowed = rule.get("allowed", [])
    value = layer.get(param)
    if value is None:
        return None  # absent is handled by parameter_range / required check
    if value not in allowed:
        return {"severity": "blocker", "code": "EXPRESSION_PARAMETER_NOT_ALLOWED",
                "message": f"{param}='{value}' not in {allowed}"}
    return None


def _check_parameter_relation(rule: dict[str, Any], layer: dict[str, Any],
                              entry: dict[str, Any], catalog: Any) -> dict[str, Any] | None:
    """Check a relation between two parameters (e.g. min < max)."""
    a = layer.get(rule["param_a"])
    b = layer.get(rule["param_b"])
    if a is None or b is None:
        return None
    rel = rule["relation"]
    if rel == "less_than_or_equal" and not (a <= b):
        return {"severity": "blocker", "code": "EXPRESSION_PARAMETER_RELATION_VIOLATED",
                "message": f"{rule['param_a']}({a}) must be <= {rule['param_b']}({b})"}
    return None


def _check_explicit_encoding_defined(rule: dict[str, Any], layer: dict[str, Any],
                                     entry: dict[str, Any], catalog: Any) -> dict[str, Any] | None:
    """Placeholder for vector/explicit encoding validation."""
    return None  # the portrayal compiler handles this


# -- handler registry --------------------------------------------------------

_RULE_HANDLERS: dict[str, Any] = {
    "class_count_range": _check_class_count_range,
    "parameter_range": _check_parameter_range,
    "parameter_enum": _check_parameter_enum,
    "parameter_relation": _check_parameter_relation,
    "explicit_encoding_defined": _check_explicit_encoding_defined,
}