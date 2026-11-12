"""Strict shared legends over already-confirmed categorical raster definitions.

This is a compiler component, not a scene admission, export or approval entry.
It never changes source data, color definitions or individual legend decisions.
"""
from __future__ import annotations

from copy import deepcopy
from typing import Any

from ..errors import ProtocolError
from .raster_portrayal import RasterPortrayalCompiler, legend_items

_DEFINITION_FIELDS = ("value", "semantic", "display", "label", "color", "order")


def _merge_verified_reports(reports: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Pure step; callers must authenticate reports before using its output."""
    if not reports or len(reports) > 4:
        raise ProtocolError("SHARED_LEGEND_INPUT_COUNT", "Require one to four verified preparations")
    if any(report["status"] != "ready" or report["questions"] for report in reports):
        raise ProtocolError("CLASSIFICATION_CLARIFICATION_REQUIRED", "Resolve every preparation first")
    policies = {report["request"]["legend_policy"] for report in reports}
    if len(policies) != 1 or not policies <= {"observed", "all"}:
        raise ProtocolError("SHARED_LEGEND_POLICY_MISMATCH", "Shared legends require the same legend policy")
    policy = next(iter(policies))
    baseline = None
    baseline_inclusion = None
    included: set[int] = set()
    definitions: dict[int, dict[str, Any]] = {}
    for report in reports:
        rows = report["rows"]
        indexed = {row["value"]: row for row in rows}
        if len(indexed) != len(rows):
            raise ProtocolError("SHARED_LEGEND_DEFINITION_INVALID", "Category values must be unique")
        orders = [row["order"] for row in rows]
        if len(set(orders)) != len(orders):
            raise ProtocolError("SHARED_LEGEND_DEFINITION_INVALID", "Category order must be unambiguous")
        definition = {value: tuple(row[field] for field in _DEFINITION_FIELDS)
                      for value, row in indexed.items()}
        inclusion = {value: bool(row["include_in_legend"]) for value, row in indexed.items()}
        if baseline is None:
            baseline, baseline_inclusion, definitions = definition, inclusion, indexed
        elif definition != baseline:
            raise ProtocolError(
                "SHARED_LEGEND_DEFINITION_MISMATCH",
                "Category codes, semantics, names, colors, display and order must match; no recoloring or merging",
            )
        elif policy == "all" and inclusion != baseline_inclusion:
            raise ProtocolError("SHARED_LEGEND_INCLUSION_MISMATCH", "All-category legends require common inclusion decisions")
        # Honor the already-confirmed per-panel inclusion flags. In particular,
        # do not turn a hidden/excluded category into a visible legend entry.
        included.update(item["value"] for item in legend_items(rows))
    result = [{key: definitions[value][key] for key in ("value", "label", "color", "order")}
              for value in sorted(included, key=lambda value: definitions[value]["order"])]
    if not result:
        raise ProtocolError("SHARED_LEGEND_EMPTY", "The confirmed legend union is empty")
    return deepcopy(result)


def resolve_shared_legend(preparation, portrayal_refs, context) -> list[dict[str, Any]]:
    """Verify every portrayal/report in the caller's trusted context, then merge.

    Reusing the same source across panels is allowed. Different observed class
    sets are allowed, but the full confirmed definition must be identical.
    Layout placement and legend capacity are intentionally not decided here.
    """
    if not isinstance(portrayal_refs, (list, tuple)) or not 1 <= len(portrayal_refs) <= 4:
        raise ProtocolError("SHARED_LEGEND_INPUT_COUNT", "Require one to four explicit portrayal references")
    context.require_project_scope()
    compiler = RasterPortrayalCompiler(preparation)
    reports = []
    for reference in portrayal_refs:
        portrayal = compiler.load_verified(reference, context)
        report, _ = preparation.load_verified(portrayal["prepared_ref"])
        if portrayal["legend_items"] != legend_items(report["rows"]):
            raise ProtocolError("SHARED_LEGEND_SOURCE_MISMATCH", "Legend differs from its verified preparation")
        reports.append(report)
    return _merge_verified_reports(reports)
