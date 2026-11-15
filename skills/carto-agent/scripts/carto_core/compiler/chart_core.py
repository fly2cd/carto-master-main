"""E6 chart core: pure validation and proportion computation in local coordinates.

The chart core is placement-agnostic (the same core serves page-frame placement
now and geo-anchored placement later): it receives a chart declaration,
validates the declared scale semantics, and computes normalized proportions
in [0, 1]. Key design decisions, aligned with doc/template/map-expression-and-
symbol-design.md sections 4.5, 5 and 7.6-7.7:

1. No implicit normalization. Bar charts require an explicit shared ``value_max``
   (the cross-comparison scale is a design decision, never silently derived);
   values above it are rejected, not rescaled.
2. Pie denominator semantics are explicit. ``sum-of-parts`` normalizes by the
   series sum (fractions sum to 1); ``declared-total`` normalizes by a declared
   total (fractions sum to <= 1; the remainder represents other categories).
   Using 280 or 330 as a denominator expresses different questions.
3. Length/area proportions are computed from the zero baseline exactly, so
   verification can recompute them deterministically from the frozen chart.
"""
from __future__ import annotations

import math
from typing import Any

from ..errors import ProtocolError


def validate_chart(chart: dict[str, Any], registry: Any = None) -> dict[str, Any]:
    # Schema + semantic validation; returns computed proportions for the caller
    # to freeze. All proportions are local [0, 1] values, placement-agnostic.
    if registry is not None:
        registry.validate("chart", chart)
    kind = chart["kind"]
    values = [item["value"] for item in chart["series"]]
    labels = [item["label"] for item in chart["series"]]
    if len(set(labels)) != len(labels):
        raise ProtocolError("CHART_LABEL_AMBIGUOUS", "Chart series labels must be unique")
    if any(not math.isfinite(v) for v in values):
        raise ProtocolError("CHART_VALUE_INVALID", "Chart series values must be finite numbers")
    if kind in ("bar-horizontal", "bar-vertical"):
        return _bar_proportions(chart, values)
    if kind == "pie":
        return _pie_fractions(chart, values)
    raise ProtocolError("CHART_KIND_INVALID", str(kind))


def _bar_proportions(chart: dict[str, Any], values: list[float]) -> dict[str, Any]:
    # Bars: length is proportional to the value from the zero baseline under an
    # explicitly declared shared scale; no value may exceed it (no clamping).
    value_max = chart["value_max"]
    if any(v < 0 for v in values):
        raise ProtocolError("CHART_VALUE_NEGATIVE", "Bar chart series values must be nonnegative")
    if any(v > value_max for v in values):
        raise ProtocolError("CHART_SCALE_EXCEEDED", "Series value exceeds the declared shared scale; no silent rescaling")
    return {"kind": chart["kind"], "fractions": [v / value_max for v in values],
            "sum": sum(values), "value_max": value_max, "denominator_total": None,
            "count": len(values)}


def _pie_fractions(chart: dict[str, Any], values: list[float]) -> dict[str, Any]:
    # Pie: each slice fraction is value/denominator where the denominator scope
    # is an explicit design decision (sum-of-parts vs declared-total).
    if any(v <= 0 for v in values):
        raise ProtocolError("CHART_PIE_VALUE_INVALID", "Pie chart series values must be positive")
    scope = chart["denominator"]["scope"]
    total = sum(values) if scope == "sum-of-parts" else chart["denominator"]["total"]
    if scope == "declared-total" and total < sum(values):
        raise ProtocolError("CHART_DENOMINATOR_INVALID", "Declared total is below the sum of series values")
    return {"kind": "pie", "fractions": [v / total for v in values],
            "sum": sum(values), "value_max": None, "denominator_total": total,
            "count": len(values)}


def bind_chart_slots(layout: dict[str, Any], charts: list[dict[str, Any]]) -> list[dict[str, Any]]:
    # Page binding: every layout chart slot must have exactly one chart declared
    # (by content_id); unknown or duplicate bindings are rejected.
    slots = {f["content_id"] for f in layout["contract"]["frames"] if f["type"] == "chart"}
    declared = [c["content_id"] for c in charts]
    if len(set(declared)) != len(declared):
        raise ProtocolError("CHART_SLOT_DUPLICATE", "A chart slot may receive at most one chart")
    if set(declared) != slots:
        raise ProtocolError("CHART_SLOT_BINDING", "Chart declarations must match all declared chart slots exactly")
    return sorted(charts, key=lambda c: c["content_id"])
