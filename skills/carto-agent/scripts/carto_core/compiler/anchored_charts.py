"""P6 geographically-anchored chart annotation (dual-thematic overlay), refactored.

ONE chart component (C[chart]) whose drawing geometry is discriminated by ``kind``
(bar-vertical/bar-horizontal/pie/line); anchoring (geographic vs frame) is an orthogonal
placement concern, NOT a separate component. Adding a chart kind extends the kind enum +
a renderer branch, never a new component/schema (prevents component explosion).

The anchor + per-instance values come from data bindings (I); chart appearance from the
registered C[chart] parameters (J); placement (preferred/fixed) is an annotation selection
(N). This module assembles frozen chart graphics; the renderer dispatches on kind.
"""
from __future__ import annotations

from typing import Any

from ..errors import ProtocolError

_BAR_KINDS = {"bar-vertical", "bar-horizontal"}


def build_anchored_charts(records: list[dict[str, Any]], parameters: dict[str, Any],
                          window: dict[str, Any], *, frame_id: str,
                          placement: str = "preferred") -> list[dict[str, Any]]:
    """Assemble anchored chart graphics (kind-discriminated, single chart component).

    records: [{id, position{x,y}, values{role:number}, offset?{x,y}, value_labels?, ratio_label?}]
    parameters: chart-parameters (kind, series[role,color], bar_width_px, chart_height_px, ...)
    placement: 'fixed' keeps each record's offset; 'preferred' clamps the suggestion into the
    display window. Only bar kinds are rendered today; pie/line are declared kinds whose
    renderer branch is not yet implemented (fail closed, not silent).
    """
    if placement not in {"preferred", "fixed"}:
        raise ProtocolError("ANNOTATION_PLACEMENT_MODE_UNSUPPORTED", placement)
    kind = parameters.get("kind")
    if kind not in _BAR_KINDS:
        raise ProtocolError("CHART_KIND_NOT_IMPLEMENTED", str(kind))
    series = parameters["series"]
    bw = parameters["bar_width_px"]
    ch = parameters["chart_height_px"]
    all_values = [v for r in records for v in r.get("values", {}).values()]
    if not all_values:
        raise ProtocolError("ANCHORED_CHART_NO_DATA", "no values to chart")
    vmax = max(all_values)
    if vmax <= 0:
        raise ProtocolError("ANCHORED_CHART_INVALID_SCALE", "max value must be positive")
    n = len(series)
    width_px = n * bw + (n - 1) * 2
    height_px = ch + 14
    graphics = []
    for rec in records:
        bars = [{"value": rec["values"].get(s["role"], 0), "color": s["color"],
                 "label": s["role"]} for s in series]
        off = rec.get("offset", {"x": 12, "y": -height_px - 8})
        ox, oy = off["x"], off["y"]
        if placement == "preferred":
            px = rec["position"]["x"] - window["x"]
            py = rec["position"]["y"] - window["y"]
            ox = min(max(ox, -px), window["width"] - width_px - px)
            oy = min(max(oy, -py), window["height"] - height_px - py)
        graphic = {
            "id": f"chart-{rec['id']}", "frame_id": frame_id,
            "coordinate_space": "image-pixel", "type": "chart", "kind": kind,
            "position": rec["position"], "offset_x_px": ox, "offset_y_px": oy,
            "bars": bars, "max_value": vmax, "chart_height_px": ch, "bar_width_px": bw,
            "width_px": width_px, "height_px": height_px, "padding_px": 2,
            "font_size_px": parameters.get("font_size_px", 9),
        }
        if parameters.get("show_value_labels", True):
            graphic["value_labels"] = rec.get("value_labels",
                                              [f"{rec['values'].get(s['role'], 0):g}" for s in series])
        if parameters.get("show_ratio_label", False) and rec.get("ratio_label"):
            graphic["ratio_label"] = rec["ratio_label"]
        graphics.append(graphic)
    return graphics