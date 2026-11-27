"""leadership-visit style: grouped itinerary portrayal compiled to pixel graphics.

Migrated from the old framework's compiler/image_itinerary_style.py (v1): group
colors, route right-offsets, arrows, pin markers, callout boxes with greedy
placement, and support labels. The interface is refactored to read the frozen
image-itinerary style contract (image-itinerary-style schema) and the image
page context (source size + display window) instead of template YAML.
Graphics stay in original-image pixel coordinates; the renderer maps them
through the frame placement.
"""
from __future__ import annotations

import math
from typing import Any

from ...adapters.image_layout import callout_text
from ...compiler.image_symbols import (
    REFERENCE_HEIGHT_PX, REFERENCE_WIDTH_PX, symbol_scale,
)
from ...errors import ProtocolError
from . import content_contract



def itinerary_value(feature: dict, fields: dict, role: str):
    field = fields.get(role)
    return feature["properties"].get(field) if field else None


def _text(value, role: str) -> str:
    if value is None or value == "":
        return ""
    if not isinstance(value, str) or len(value) > 40 or any(c in value for c in "\r\n"):
        raise ProtocolError("ITINERARY_METADATA_INVALID", role)
    return value


def _number(value, role: str):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ProtocolError("ITINERARY_METADATA_INVALID", role)
    return value


def _place(graphic: dict, window: dict, placed: list, explicit: bool, anchors: list) -> None:
    """Greedy callout placement in window coordinates; deterministic order."""
    x = graphic["position"]["x"] - window["x"]
    y = graphic["position"]["y"] - window["y"]
    w, h = graphic["width_px"], graphic["height_px"]
    gap = graphic["padding_px"] * 2
    dx, dy = graphic["offset_x_px"], graphic["offset_y_px"]
    candidates = [(x + dx, y + dy)]
    if not explicit:
        candidates += [(x + ox, y + oy) for ox in (gap, -w - gap) for oy in (-h - gap, -h / 2, gap)]
        # Larger name labels may need a second nearby row before using the map edge.
        candidates += [(x + ox, y + oy) for ox in (gap, -w - gap, w + 2 * gap, -2 * w - 2 * gap)
                       for oy in (-2 * h - 2 * gap, h + 2 * gap, -3 * h - 3 * gap, 2 * h + 3 * gap)]
        candidates += [(left, top) for top in range(0, max(1, int(window["height"] - h) + 1), max(1, int(h + gap)))
                       for left in (gap, window["width"] - w - gap)]
    for left, top in candidates:
        right, bottom = left + w, top + h
        if left < 0 or top < 0 or right > window["width"] or bottom > window["height"]:
            continue
        if left - gap < x < right + gap and top - gap < y < bottom + gap:
            continue
        if any(left < ax + radius and right > ax - radius and top < ay + radius and bottom > ay - 3 * radius
               for ax, ay, radius in anchors):
            continue
        if any(left < r + gap and right > l - gap and top < b + gap and bottom > t - gap for l, t, r, b in placed):
            continue
        graphic.update(offset_x_px=left - x, offset_y_px=top - y)
        placed.append((left, top, right, bottom))
        return
    raise ProtocolError("ITINERARY_CALLOUT_PLACEMENT_FAILED", graphic["id"])


def apply_grouped_style(style: dict[str, Any], page_request: dict[str, Any],
                        itinerary_data: dict[str, Any], *, frame_id: str,
                        appearance_roles: dict[str, Any] | None = None,
                        annotations: dict[str, Any] | None = None) -> dict[str, Any]:
    """Compile the frozen style contract + projected itinerary to pixel graphics.

    Inputs:
      style          -- image-itinerary-style document (groups/route/pin/callout/...)
      page_request   -- image page request carrying basemap.source_size and
                        basemap.display_window
      itinerary_data -- {"projection": frozen projection document,
                         "sources": {"route-stops": FeatureCollection, "route-line": ...},
                         "fields": {role: {semantic_role: source_field}}}
      frame_id       -- the resolved map frame's actual id (P6 §13.3: graphics bind to
                        the verified view/content frame, not a hardcoded "main-map"
                        string imposed on every Layout).

    Output: {"graphics": [...], "legend_items": [...]} where graphics use
    original-image pixel anchors on the resolved map frame.
    """
    if not isinstance(frame_id, str) or not frame_id:
        raise ProtocolError("ITINERARY_FRAME_BINDING_INVALID", "a resolved map frame id is required")
    basemap = page_request.get("basemap") or {}
    window = basemap.get("display_window")
    source_size = basemap.get("source_size")
    if not window or not source_size:
        raise ProtocolError("ITINERARY_PAGE_CONTEXT_INVALID", "basemap source size and display window are required")
    projection = itinerary_data.get("projection") or {}
    sources = itinerary_data.get("sources") or {}
    fields = itinerary_data.get("fields") or {}
    groups = {g["id"]: g for g in style["groups"]}
    if len(groups) != len(style["groups"]) or style["default_group"] not in groups:
        raise ProtocolError("ITINERARY_GROUP_CONFIG_INVALID", "unique groups and a declared default are required")

    def group(feature, role):
        value = itinerary_value(feature, fields.get(role, {}), "itinerary-group")
        key = style["default_group"] if value is None or value == "" else value
        if not isinstance(key, str) or key not in groups:
            raise ProtocolError("ITINERARY_GROUP_UNKNOWN", role)
        used.add(key)
        return groups[key]

    scale = symbol_scale(window)
    used: set[str] = set()
    graphics: list[dict] = []
    placed: list = []
    group_counts: dict = {}
    support_seen: dict = {}
    # Key by feature id; fall back to the same positional ids the projection
    # assigns (geo_to_image_pixels) so featureless collections stay consistent.
    stops = {str(f.get("id", f"route-stops-{i}")): f
             for i, f in enumerate(sources.get("route-stops", {}).get("features", []))}
    routes = {str(f.get("id", f"route-line-{i}")): f
              for i, f in enumerate(sources.get("route-line", {}).get("features", []))}
    for i, route in enumerate(projection.get("routes", [])):
        route_group = group(routes.get(route["feature_id"], {"properties": {}}), "route-line")
        color = route_group["color"]
        route_style = {k: v * scale for k, v in style["route"].items()
                       if k not in {"arrows"}}
        if "right_offset_px" in route_group:
            route_style["right_offset_px"] = route_group["right_offset_px"] * scale
        if "arrows" in style["route"]:
            route_style["arrows"] = {k: v * scale for k, v in style["route"]["arrows"].items()}
        for j, part in enumerate(route["parts"]):
            graphics.append({"id": f"image-route-{i + 1}-{j + 1}", "frame_id": frame_id,
                             "coordinate_space": "image-pixel", "type": "line", "points": part,
                             "color": color, "route_mode": route["route_mode"], **route_style})
    metadata = fields.get("route-stops", {})
    anchors = [(s["position"]["x"] - window["x"], s["position"]["y"] - window["y"],
                style["pin"]["radius_px"] * scale) for s in projection.get("stops", [])]

    # 事项1.4: the adopted annotation placement mode enters the real layout constraint.
    # A fixed card placement is binding (solver must not move it); preferred may be solved.
    card_fixed = (annotations or {}).get("card", {}).get("placement", {}).get("mode") == "fixed"

    def finish(graphic: dict, source: dict) -> None:
        explicit = card_fixed
        for role, key in (("callout-offset-x", "offset_x_px"), ("callout-offset-y", "offset_y_px")):
            value = itinerary_value(source, metadata, role)
            if value is not None:
                graphic[key] = _number(value, role) * scale
                explicit = True
        _, graphic["height_px"] = callout_text(graphic)
        _place(graphic, window, placed, explicit, anchors)
        graphics.append(graphic)

    for stop in sorted(projection.get("stops", []), key=lambda s: s["visit_order"]):
        order = stop["visit_order"]
        source = stops.get(stop["feature_id"], {"properties": {}})
        selected_group = group(source, "route-stops")
        color = selected_group["color"]
        base = {"frame_id": frame_id, "coordinate_space": "image-pixel", "position": stop["position"]}
        support = style.get("support_label")
        # X02: role classification reads the data fact (stop-type/map-role), never the
        # existence of a style section. A non-visit role requires the support appearance
        # role; missing it is refused, not silently downgraded to a normal visit point.
        kind = itinerary_value(source, metadata, "stop-type")
        if kind is None or kind == "":
            kind = "visit"
        if not isinstance(kind, str) or kind not in {"departure", "visit", "transit"}:
            raise ProtocolError("ITINERARY_STOP_TYPE_UNKNOWN", "stop-type")
        if "map-role" in metadata:
            map_role = itinerary_value(source, metadata, "map-role")
            if not isinstance(map_role, str) or map_role not in {"origin", "visit", "waypoint", "destination"}:
                raise ProtocolError("ITINERARY_MAP_ROLE_INVALID", "map-role")
            kind = "visit" if map_role == "visit" else "transit"
        if kind != "visit" and support is None:
            raise ProtocolError("LEADERSHIP_SUPPORT_ROLE_MISSING",
                                f"stop role '{kind}' requires the support_label appearance role")
        title = source["properties"].get(metadata.get("stop-label", "stop_name"), "")
        if not isinstance(title, str) or not title.strip() or len(title) > 200 or any(c in title for c in "\r\n"):
            raise ProtocolError("ITINERARY_METADATA_INVALID", "stop-label")
        if kind != "visit":
            graphics.append({**base, "id": f"image-stop-{order}", "type": "point", "visit_order": order,
                             "shape": "pin", "show_number": False, "color": support["color"],
                             "group": "support", "radius_px": support["point_radius_px"] * scale})
            offsets = [itinerary_value(source, metadata, role) for role in ("callout-offset-x", "callout-offset-y")]
            offsets = [None if v is None else _number(v, "callout-offset") for v in offsets]
            label_key = (title, stop["position"]["x"], stop["position"]["y"], *offsets)
            if label_key in support_seen:
                support_seen[label_key]["stop_orders"].append(order)
                continue
            font, padding = support["font_size_px"] * scale, support["padding_px"] * scale
            graphic = {**base, "id": f"image-callout-{order}", "type": "callout", "title": title,
                       "stop_orders": [order], "lines": [], "color": support["color"], "group": "support",
                       "title_color": support["text_color"], "body_color": support["text_color"],
                       "title_font_px": font, "body_font_px": font,
                       "font_weight": support.get("font_weight", 400), "title_wrap": False,
                       "width_px": math.ceil(len(title) * font + 2 * padding), "padding_px": padding,
                       "line_gap_px": 0, "opacity": support["opacity"],
                       "leader_width_px": support["leader_width_px"] * scale,
                       "offset_x_px": support["offset_x_px"] * scale,
                       "offset_y_px": support["offset_y_px"] * scale}
            finish(graphic, source)
            support_seen[label_key] = graphic
            continue
        pin_graphic = {**base, "id": f"image-stop-{order}", "type": "point", "visit_order": order,
                       "shape": "pin", "color": color, "group": selected_group["id"],
                       "radius_px": style["pin"]["radius_px"] * scale,
                       "font_size_px": style["pin"]["font_size_px"] * scale, "show_number": True}
        # X07: number text / marker edge colors come from Style roles (A), not renderer defaults.
        if appearance_roles:
            pin_graphic["text_color"] = appearance_roles.get("visit-order-text", {}).get("color", "#FFFFFF")
            pin_graphic["edge_color"] = appearance_roles.get("numbered-stop-marker", {}).get("stroke", {}).get("color", "#FFFFFF")
        graphics.append(pin_graphic)
        date = _text(itinerary_value(source, metadata, "visit-date"), "visit-date")
        period = _text(itinerary_value(source, metadata, "visit-period"), "visit-period")
        key = (date, selected_group["id"])
        group_counts[key] = group_counts.get(key, 0) + 1
        display_order = group_counts[key] if style.get("numbering", "global") == "per-date-group" else order
        lines = [content_contract.stop_line(date, period, display_order)]
        config = style["callout"]
        if config.get("show_arrival_time", True):
            arrival = _text(itinerary_value(source, metadata, "arrival-time"), "arrival-time")
            if arrival:
                lines.append(content_contract.arrival_line(arrival))
        travel = []
        for role in ("distance-km", "duration-min"):
            value = itinerary_value(source, metadata, role)
            if value is not None:
                value = _number(value, role)
                if value < 0 or value > 100000:
                    raise ProtocolError("ITINERARY_METADATA_INVALID", role)
                travel.append(content_contract.travel_line(role, value))
        if travel:
            lines.append(content_contract.TRAVEL_JOINER.join(travel))
        graphic = {**base, "id": f"image-callout-{order}", "type": "callout", "title": title,
                   "stop_orders": [order], "lines": lines, "color": color,
                   "group": selected_group["id"],
                   "title_color": config.get("title_color", "#FFFFFF"),
                   "body_color": config.get("body_color", "#FFFFFF"),
                   **{k: v * scale if k.endswith("_px") else v for k, v in config.items()
                      if k not in {"show_arrival_time", "fit_content", "title_color", "body_color"}}}
        if config.get("fit_content", False):
            text_width = max(len(graphic["title"]) * graphic["title_font_px"],
                             max((len(line) * graphic["body_font_px"] for line in lines), default=0))
            graphic["width_px"] = min(graphic["width_px"], math.ceil(text_width + 2 * graphic["padding_px"]))
        finish(graphic, source)
    rank = {"line": 0, "point": 1, "callout": 3}
    graphics = sorted(graphics, key=lambda g: (rank[g["type"]], g["id"]))
    legend_items = [{"label": g["label"], "color": g["color"], "shape": "line"}
                    for g in style["groups"] if g["id"] in used]
    legend_items += [{"label": content_contract.LEGEND_STOP_LABEL,
                      "color": groups[style["default_group"]]["color"], "shape": "pin"}]
    if support_seen:
        legend_items.append({"label": content_contract.LEGEND_SUPPORT_LABEL,
                             "color": style["support_label"]["color"], "shape": "pin"})
    return {"graphics": graphics, "legend_items": legend_items}
