"""leadership-visit legend_checker: itinerary business checks on the frozen scene.

Called by ``validation.map_checks`` through the ``cartography.legend-consistency``
gate (the scenario business-check slot). The template quality-gates contract
declares that gate; the scenario implements what "consistent" means here:

1. visit_order continuity — every stop point carries visit_order 1..N, each
   exactly once, no gaps or duplicates;
2. route_mode validity — every route line graphic declares one of the four
   admitted modes;
3. group color consistency — pins/callouts of the same itinerary group share
   one color, distinct groups never share a color, and every callout's color
   matches the group of the stops it covers;
4. callout/stop coverage — every stop has exactly one point marker and is
   covered by exactly one callout.
"""
from __future__ import annotations

from typing import Any

from ...errors import ProtocolError

_VALID_ROUTE_MODES = frozenset({"road_network", "provided_geometry", "schematic", "straight_line"})


def route_legend_checker(context: dict[str, Any]) -> tuple[bool, dict[str, Any], None]:
    """Legend/display consistency for leadership visit route maps."""
    scene = context.get("scene") or {}
    graphics = scene.get("image_graphics") or []
    if not graphics:
        raise ProtocolError("LEGEND_CHECK_INPUT_REQUIRED", "the image scene carries no graphics")
    points = [g for g in graphics if g["type"] == "point"]
    callouts = [g for g in graphics if g["type"] == "callout"]
    lines = [g for g in graphics if g["type"] == "line"]

    # 1. visit_order continuity: 1..N, each exactly once.
    orders = sorted(g["visit_order"] for g in points)
    order_ok = orders == list(range(1, len(points) + 1)) if points else False

    # 2. route_mode validity on every route line.
    modes = {g.get("route_mode") for g in lines}
    mode_ok = bool(lines) and modes <= _VALID_ROUTE_MODES

    # 3. group color consistency.
    group_colors: dict[str, str] = {}
    color_groups: dict[str, set[str]] = {}
    color_ok = True
    for graphic in (*points, *callouts):
        group = graphic.get("group")
        color = graphic.get("color", "")
        if not group:
            color_ok = False
            continue
        if group_colors.setdefault(group, color) != color:
            color_ok = False
        color_groups.setdefault(color, set()).add(group)
    if any(len(groups) > 1 for groups in color_groups.values()):
        color_ok = False  # two groups share one color — the legend cannot distinguish them
    for callout in callouts:
        covered = {g["group"] for g in points if g["visit_order"] in callout.get("stop_orders", [])}
        if covered and covered != {callout.get("group")}:
            color_ok = False

    # 4. callout/stop coverage: each stop appears in exactly one callout.
    coverage_counts: dict[int, int] = {}
    for callout in callouts:
        for order in callout.get("stop_orders", []):
            coverage_counts[order] = coverage_counts.get(order, 0) + 1
    point_orders = {g["visit_order"] for g in points}
    coverage_ok = (point_orders == set(coverage_counts)
                   and all(count == 1 for count in coverage_counts.values())) if points else False

    details = {
        "stop_count": len(points),
        "callout_count": len(callouts),
        "route_line_count": len(lines),
        "visit_orders": orders,
        "route_modes": sorted(str(mode) for mode in modes),
        "group_colors": {group: group_colors[group] for group in sorted(group_colors)},
        "checks": {"visit_order_sequential": order_ok, "route_mode_valid": bool(mode_ok),
                   "group_colors_consistent": color_ok, "callout_coverage_exact": coverage_ok},
    }
    ok = order_ok and mode_ok and color_ok and coverage_ok
    return ok, details, None
