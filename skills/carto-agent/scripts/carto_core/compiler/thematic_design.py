"""Mechanical derivation of the encoding IR from an explicitly declared design.

``doc/design-principles.md`` §2.3 puts "semantic parameters -> numeric execution
parameters" in the mechanical-derivation layer: program-owned, deterministic, and
injecting zero design preference. That is exactly what ``resolve_design`` does, so
it lives here in the kernel next to the IR primitives it produces, rather than in
the orchestration layer. The former ``workflow.thematic`` re-export shim was dissolved
(I-5): callers import ``resolve_design`` / ``equal_interval_edges`` from here directly,
which is what removed the ``compiler -> workflow`` runtime edge (Tier-2 去环 Step4).

Nothing here selects a method, infers a unit, computes an undeclared statistic or
evaluates code: the design states kind / field / measurement / unit / breaks, the
frozen preparation report states the observed values, and the IR is the
deterministic combination of the two. A design whose declared expression cannot
cover the observed values is rejected, never silently repaired.
"""
from __future__ import annotations

from copy import deepcopy

from ..errors import ProtocolError
from ..schema_registry import SchemaRegistry
from .portrayal_resolver import finite, metric_value
from .vector_portrayal import resolve_features


def equal_interval_edges(low, high, count):
    """Shared equal-interval break computation for raster & vector choropleth (ADR-001 阶段2.3)."""
    if low == high:
        raise ProtocolError("THEMATIC_CONSTANT_DOMAIN", "Equal intervals need a nonconstant domain; select another explicit expression")
    edges = [low + (high - low) * i / count for i in range(count)] + [high]
    labels = [f"Class {i+1}" for i in range(count)]
    return edges, labels


def _domain(design):
    return {"field": design["field"], "measurement": design["measurement"],
            "unit": design["unit"], "normalization": design.get("normalization")}


def _design_to_ir(design, stats):
    """Map a kind-based thematic-design into the geometry-agnostic encoding IR (ADR-001 stage 2)."""
    kind = design["kind"]
    geometry_role = design["geometry"]
    missing = deepcopy(design["missing"])
    domain = _domain(design)
    if kind == "single":
        return {"schema_version": 1, "key_mode": "discrete", "geometry_role": geometry_role, "domain": domain,
                "scale": {"categories": []},
                "channels": {"symbols": [deepcopy(design["symbol"])], "shape": "auto"},
                "missing": missing, "legend": {"policy": "all", "uniform_label": design["label"]}}
    if kind == "categorical":
        return {"schema_version": 1, "key_mode": "discrete", "geometry_role": geometry_role, "domain": domain,
                "scale": {"categories": [{"value": c["value"], "label": c["label"]} for c in design["categories"]]},
                "channels": {"symbols": [deepcopy(c["symbol"]) for c in design["categories"]], "shape": "auto"},
                "missing": missing, "legend": {"policy": design["legend_policy"]}}
    if kind == "choropleth":
        classification = design["classification"]
        if classification["method"] == "equal-interval":
            edges, labels = equal_interval_edges(stats["minimum"], stats["maximum"], classification["class_count"])
        else:
            edges, labels = classification["edges"], classification["labels"]
        return {"schema_version": 1, "key_mode": "interval", "geometry_role": geometry_role, "domain": domain,
                "scale": {"edges": edges, "labels": labels, "interval_policy": "left-closed-last-both", "out_of_range": "reject"},
                "channels": {"symbols": deepcopy(design["symbols"]), "shape": "auto"},
                "missing": missing, "legend": {"policy": "all"}}
    return {"schema_version": 1, "key_mode": "scaling", "geometry_role": geometry_role, "domain": domain,
            "scale": {"domain_max": design["maximum_value"], "range_mm": [design["minimum_radius_mm"], design["maximum_radius_mm"]],
                      "size_scale": "sqrt", "zero_policy": design["zero_policy"], "negative_policy": design["negative_policy"],
                      "out_of_range": design["out_of_range"], "legend_values": design["legend_values"]},
            "channels": {"symbols": [deepcopy(design["symbol"])], "shape": "auto"},
            "missing": missing, "legend": {"policy": "all"}}


def resolve_design(design, report, registry=None):
    """Derive and immediately falsify the IR for one declared design + frozen report.

    Returns ``(ir, statistics)``. ``resolve_features`` is executed here on purpose:
    interval coverage, missing-value policy and symbol domains are validated against
    the observed values at derivation time, not deferred to painting.
    """
    registry = registry or SchemaRegistry()
    registry.validate("thematic-design", design)
    if design["geometry"] != report["geometry"]:
        raise ProtocolError("THEMATIC_GEOMETRY_MISMATCH", "Design must match the source geometry")
    kind = design["kind"]
    if kind == "proportional" and design.get("normalization") is not None:
        raise ProtocolError("THEMATIC_MEASUREMENT_INVALID", "Count symbols cannot silently normalize their values")
    domain = _domain(design)
    values = [metric_value(feature["properties"], domain) for feature in report["features"]]
    numeric = [value for value in values if value is not None]
    if kind in {"choropleth", "proportional"} and (not numeric or any(not finite(v) for v in numeric)):
        raise ProtocolError("THEMATIC_VALUE_INVALID", "A numeric expression requires observed finite numeric values")
    stats = {"count": len(numeric), "minimum": min(numeric) if numeric and all(finite(v) for v in numeric) else None,
             "maximum": max(numeric) if numeric and all(finite(v) for v in numeric) else None}
    ir = _design_to_ir(design, stats)
    # Validate the actual values, all interval coverage, missing policy and symbol domains now.
    resolve_features(report, ir, registry)
    return ir, stats
