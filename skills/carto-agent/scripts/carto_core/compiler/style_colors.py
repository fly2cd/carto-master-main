"""Style category-color resolution (plan 裁决5 + Path A integration).

A reusable Style stores category colors keyed by semantic role (``symbol_roles`` with
``key_mode == "discrete"``), never by instance category code (plan §1.2.2). A run supplies
an instance role↔category-code binding table; this pure resolver lifts the Style's
role→color into the value→color ``category_colors`` authority that Path A's classification
request consumes. The compile-time operational key is the data value (category code), so
the lifted colors align with the revision ``color_scheme`` key space (裁决5).

Kernel-safe: operates only on contracts, no scenario import, no I/O, deterministic. The
caller validates the Style closed-world; this resolver only extracts and lifts.
"""
from __future__ import annotations

from copy import deepcopy
from typing import Any

from ..errors import ProtocolError


def style_discrete_colors(style: dict[str, Any]) -> dict[str, str]:
    """Extract {role_id: uppercase hex} from discrete symbol_roles carrying a fill color."""
    colors: dict[str, str] = {}
    for role in style.get("symbol_roles", []):
        if role.get("key_mode") != "discrete":
            continue
        color = (role.get("symbol") or {}).get("color")
        if color:
            colors[role["role_id"]] = color.upper()
    return colors


def resolve_style_category_colors(style: dict[str, Any],
                                  role_bindings: dict[str, int]) -> list[dict[str, Any]]:
    """Lift Style role colors through an instance role↔value binding into category_colors.

    ``role_bindings`` maps role_id -> category code (value). Every bound role must have a
    discrete Style color (missing -> reject); two roles binding the same value is a
    conflict (reject). Unbound data values are left to preparation clarification, not
    auto-filled. The result is deterministically ordered by value for stable digests.
    """
    colors = style_discrete_colors(style)
    seen_values: set[int] = set()
    category_colors: list[dict[str, Any]] = []
    for role_id, value in role_bindings.items():
        if role_id not in colors:
            raise ProtocolError("STYLE_ROLE_COLOR_MISSING",
                                f"Bound role '{role_id}' has no discrete Style color")
        if value in seen_values:
            raise ProtocolError("STYLE_ROLE_BINDING_CONFLICT",
                                f"Category code {value} is bound by more than one role")
        seen_values.add(value)
        category_colors.append({"value": value, "color": colors[role_id]})
    return sorted(category_colors, key=lambda item: item["value"])


def apply_color_scheme(rows: list[dict[str, Any]], color_scheme: dict[str, Any],
                       *, registry: Any = None) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Apply a compile-time effective-color overlay to frozen portrayal rows (裁决4).

    The baseline rows stay frozen in the prepared report; this produces EFFECTIVE rows for
    the candidate/scene. ``color_scheme`` is scoped to one shared-legend category contract
    (裁决6) and keyed by category code (裁决5): an overlay value absent from the rows is
    rejected (fail closed), never guessed by legend order. Both map and legend must consume
    the returned effective rows (single source). The colour redlines run on the effective
    ordered colors. Returns (effective_rows, per-value mapping provenance).
    """
    overlay = {item["value"]: item["color"].upper() for item in color_scheme["colors"]}
    if len(overlay) != len(color_scheme["colors"]):
        raise ProtocolError("COLOR_SCHEME_DUPLICATE", "Duplicate category codes in color_scheme")
    row_values = {row["value"] for row in rows}
    unknown = sorted(set(overlay) - row_values)
    if unknown:
        raise ProtocolError("COLOR_SCHEME_UNKNOWN_CATEGORY",
                            f"color_scheme references absent category codes: {unknown}")
    effective: list[dict[str, Any]] = []
    mapping: list[dict[str, Any]] = []
    for row in rows:
        new_row = deepcopy(row)
        if row["value"] in overlay and row.get("display") == "color":
            new_row["color"] = overlay[row["value"]]
            mapping.append({"value": row["value"], "baseline_color": row.get("color"),
                            "effective_color": new_row["color"], "source": "color_scheme"})
        effective.append(new_row)
    from .color_checks import ColorRedlinesPolicy, check_color_sequence, enforce
    ordered = [r["color"] for r in sorted(effective, key=lambda r: r["order"])
               if r.get("display") == "color" and r.get("color")]
    enforce(check_color_sequence(ordered, ColorRedlinesPolicy.load(registry=registry)))
    return effective, mapping


def overlay_legend_colors(items: list[dict[str, Any]],
                          color_scheme: dict[str, Any]) -> list[dict[str, Any]]:
    """Apply the same value->color overlay to shared-legend items (裁决6 group consistency).

    Shared legends are merged from frozen reports; this overlays the effective colors so a
    shared legend matches the effective map colors (single source, 裁决4). Unknown values
    are rejected to keep the group consistent.
    """
    overlay = {item["value"]: item["color"].upper() for item in color_scheme["colors"]}
    unknown = sorted(set(overlay) - {item["value"] for item in items})
    if unknown:
        raise ProtocolError("COLOR_SCHEME_UNKNOWN_CATEGORY",
                            f"color_scheme references absent legend categories: {unknown}")
    result = deepcopy(items)
    for item in result:
        if item["value"] in overlay:
            item["color"] = overlay[item["value"]]
    return result