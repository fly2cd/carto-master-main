"""Frontend Image Canvas v2 document builder (renderer-neutral layer).

Pure conversion: frozen RenderScene ``image_graphics`` + image page-request ->
the frontend-consumable map document, all coordinates/sizes in millimetres.
The placement transform is the SAME math ``ImagePageRenderer`` uses (map frame +
aspect-preserving contain_layout + display window), so the frontend rendering
and the PDF stay pixel-consistent. The basemap is NOT embedded: the frontend
loads the registered image separately.

Scenario packages (e.g. ``scenarios.leadership_visit.frontend_document``)
delegate here; the renderer writes the preview copy next to its PDF/PNG. This
module never imports a concrete scenario (boundary guard).

Layering: deterministic compile-time derivation governed by the frozen document
digests — deliberately NOT a ToolGateway capability.
"""
from __future__ import annotations

from typing import Any

from ..canonical import sha256_digest
from ..compiler.layout import LayoutResolver
from ..errors import ProtocolError
from ..schema_registry import SchemaRegistry
from .image_layout import callout_text, contain_layout, frame_border_rects, furniture_font_pt, legend_font_pt
from .route_display import display_points

MAIN_FRAME = "main-map"


def stop_card_index(graphics: list[dict[str, Any]]) -> dict[int, int]:
    """Replay the builder's group allocation to get stop_order -> RectIndex.

    Single source of truth for which canvasData card each itinerary stop
    belongs to: replays the exact allocation order ``_CanvasBuilder.build``
    performs (background = group 0, route-layer = 1, then per-graphic ids in
    list order, page-furniture last). Callout registration overwrites the
    point's own group because callouts rank after points — the final value is
    the shared card group. Used both inside the builder and by the compile-time
    geo-section builder (which needs the map before the full document exists).
    """
    groups: dict[str, int] = {}
    next_group = 0

    def group(key: str) -> int:
        nonlocal next_group
        if key not in groups:
            next_group += 1
            groups[key] = next_group
        return groups[key]

    group("route-layer")
    stop_card: dict[int, int] = {}
    for graphic in graphics:
        kind = graphic.get("type")
        if kind == "point":
            allocated = group(graphic["id"])
            if "visit_order" in graphic:
                stop_card.setdefault(graphic["visit_order"], allocated)
        elif kind == "callout":
            allocated = group(graphic["id"])
            for order in graphic.get("stop_orders", []):
                groups[f"image-stop-{order}"] = allocated
                stop_card[order] = allocated
        elif kind == "label":
            group(graphic["id"])
    return stop_card


def _pin_icon(radius_px: float, color: str, scale: float, mm_x: float) -> tuple[str, float]:
    """Inline SVG icon for a pin marker (mm-sized in the global canvas)."""
    r = radius_px * scale
    size = (2 * r + 4) * mm_x
    icon = (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="{-r-2} {-3*r-2} {2*r+4} {3*r+2}">'
            f'<circle cx="0" cy="{-2*r}" r="{r}" fill="{color}" stroke="#FFFFFF" stroke-width="1"/>'
            f'<polygon points="{-r*.35},{-r*1.1} {r*.35},{-r*1.1} 0,0" fill="{color}"/>'
            f'<circle cx="0" cy="{-2*r}" r="{r*.55}" fill="#FFFFFF"/></svg>')
    return icon, size


class _CanvasBuilder:
    """One-shot builder; keeps the feature list and element grouping state."""

    def __init__(self, registry: SchemaRegistry, scene: dict[str, Any], page: dict[str, Any],
                 *, identifier: str, name: str, category: str) -> None:
        self.registry = registry
        self.scene = scene
        self.page = page
        self.identifier = identifier
        self.name = name
        self.category = category
        self.features: list[dict[str, Any]] = []
        self.groups: dict[str, int] = {}
        self.stop_card: dict[int, int] = {}
        self._next_group = 0

    def build(self) -> dict[str, Any]:
        registry, scene, page = self.registry, self.scene, self.page
        registry.validate("render-scene", scene)
        registry.validate("page-request", page)
        basemap = page.get("basemap") or {}
        window = basemap.get("display_window")
        if not window:
            raise ProtocolError("FRONTEND_PAGE_CONTEXT_REQUIRED",
                                "image page request with a display window is required")
        frame = LayoutResolver.map_frame(scene["resolved_layout"])
        viewport = scene["viewport"]
        frame_box = {key: value for key, value in zip(("x", "y", "width", "height"), frame["bounds_px"])}
        placement = contain_layout({"width_px": window["width"], "height_px": window["height"]}, frame_box)
        scale = placement["scale"]
        mm_x = page["resolved_layout"]["page"]["width_mm"] / viewport["width_px"]
        mm_y = page["resolved_layout"]["page"]["height_mm"] / viewport["height_px"]
        self._mm_x, self._mm_y = mm_x, mm_y

        def mm(x: float, y: float) -> tuple[float, float]:
            return (round(px_x(x) * mm_x, 6), round(px_y(y) * mm_y, 6))

        def px_x(x: float) -> float:
            return x * scale - window["x"] * scale + placement["x"]

        def px_y(y: float) -> float:
            return y * scale - window["y"] * scale + placement["y"]

        route_group = self._group("route-layer")
        # stop -> card map from the single replay implementation (see
        # stop_card_index); the graphics loop below performs the identical
        # allocation as a by-product but the map is derived once, here.
        self.stop_card = stop_card_index(scene.get("image_graphics", []))
        self._rect(0, 0, viewport["width_px"], viewport["height_px"], "#FFFFFF", group=0)
        for graphic in scene.get("image_graphics", []):
            if graphic["type"] == "line":
                # Same single-placement transform as the renderer: subtract the
                # window origin, then add the frame placement exactly once.
                displayed = display_points(
                    graphic, scale,
                    (window["x"] * scale, window["y"] * scale))
                coordinates = [[round((x + placement["x"]) * mm_x, 6), round((y + placement["y"]) * mm_y, 6)]
                               for x, y in displayed]
                self.features.append({"type": "MultiLineString", "RectIndex": route_group,
                                      "coordinates": coordinates, "color": graphic.get("color", "#1A3A5C"),
                                      "strokeWidth": round(graphic.get("width_px", 4) * scale * mm_x, 6),
                                      "strokeDash": "", "closed": False})
                continue
            if graphic["type"] == "point":
                group = self._group(graphic["id"])
                icon, size = _pin_icon(graphic.get("radius_px", 12), graphic.get("color", "#C41E3A"),
                                       scale, mm_x)
                self.features.append({"type": "MultiPoint", "RectIndex": group, "icon": icon,
                                      "size": round(size, 6), "color": graphic.get("color", "#C41E3A"),
                                      "coordinates": [list(mm(graphic["position"]["x"],
                                                              graphic["position"]["y"]))]})
                continue
            if graphic["type"] == "callout":
                group = self._group(graphic["id"])
                for order in graphic.get("stop_orders", []):
                    self.groups[f"image-stop-{order}"] = group
                x, y = px_x(graphic["position"]["x"]), px_y(graphic["position"]["y"])
                left, top = x + graphic["offset_x_px"], y + graphic["offset_y_px"]
                width, height = graphic["width_px"], graphic["height_px"]
                cx = min(max(x, left), left + width)
                cy = min(max(y, top), top + height)
                self.features.append({"type": "MultiLineString", "RectIndex": group,
                                      "coordinates": [[round(x * mm_x, 6), round(y * mm_y, 6)],
                                                      [round(cx * mm_x, 6), round(cy * mm_y, 6)]],
                                      "color": graphic.get("color", "#1A3A5C"),
                                      "strokeWidth": round(graphic.get("leader_width_px", 1) * scale * mm_x, 6),
                                      "strokeDash": "", "closed": False})
                self.features.append({"type": "Rect", "RectIndex": group,
                                      "x": round(left * mm_x, 6), "y": round(top * mm_y, 6),
                                      "w": round(width * mm_x, 6), "h": round(height * mm_y, 6),
                                      "fillColor": graphic.get("color", "#1A3A5C"),
                                      "opacity": graphic.get("opacity", 0.88)})
                cursor = top + graphic["padding_px"]
                for line in graphic.get("lines", []):
                    row = graphic["body_font_px"] * 1.3
                    self._text(left + graphic["padding_px"], cursor + row / 2,
                               len(line) * graphic["body_font_px"], row, line,
                               graphic.get("body_color", "#FFFFFF"), graphic["body_font_px"], group)
                    cursor += row
                if graphic.get("lines"):
                    cursor += 2 * graphic.get("line_gap_px", 0)
                title_lines, _ = callout_text(graphic)
                for line in title_lines:
                    row = graphic["title_font_px"] * 1.25
                    self._text(left + graphic["padding_px"], cursor + row / 2,
                               len(line) * graphic["title_font_px"], row, line,
                               graphic.get("title_color", "#FFFFFF"), graphic["title_font_px"], group,
                               bold=graphic.get("font_weight", 400) >= 700)
                    cursor += row
                continue
            if graphic["type"] == "label":
                group = self._group(graphic["id"])
                lx = px_x(graphic["position"]["x"]) + graphic.get("offset_x_px", 16) * scale
                ly = px_y(graphic["position"]["y"]) + graphic.get("offset_y_px", -16) * scale
                font = graphic.get("font_size_px", 16) * scale
                self._text(lx, ly, len(graphic.get("content", "")) * font, font * 1.2,
                           graphic.get("content", ""), graphic.get("color", "#1A3A5C"), font, group)
                continue
            raise ProtocolError("FRONTEND_PRIMITIVE_UNSUPPORTED", graphic["type"])
        # Page furniture in mm. The font derivation is the SHARED
        # image_layout.furniture_font_pt the PDF renderer consumes (frozen page
        # contract font_pt with the 18pt/9pt historical fallback, frame-fit
        # capped, 4pt floor) — one function, both renderers, no per-side
        # formula drift.
        dpi = scene["export"]["dpi"]
        pt_per_px = 72 / dpi
        furniture = self._group("page-furniture")
        frames = {f["content_id"]: f for f in scene["resolved_layout"]["frames"] if f["type"] != "map"}
        for item in page.get("texts", []):
            bounds = frames.get(item["content_id"])
            if bounds is None:
                continue
            x, y, w, h = bounds["bounds_px"]
            # _text takes px-domain sizes (it converts via mm_x); the frozen
            # derivation returns pt, so convert pt -> viewport px here. This also
            # fixes the historical mm-as-px mix-up that shrank the frontend title
            # to ~2pt while the PDF rendered 18pt from the same page contract.
            font_px = furniture_font_pt(item, (x, y, w, h), pt_per_px) / pt_per_px
            self._text(x + w / 2, y + h / 2, len(item["text"]) * font_px, font_px * 1.2,
                       item["text"], "#1A3A5C", font_px, furniture, bold=True, align="center")
        # Map frame border (frozen furniture): the same shared geometry
        # (image_layout.frame_border_rects) the PDF renderer draws.
        border = (page.get("furniture") or {}).get("frame_border")
        if border:
            inner, outer = frame_border_rects(placement, border, dpi / 25.4)
            for rect, width_mm in ((inner, border["inner_width_mm"]),
                                   (outer, border["outer_width_mm"])):
                self.features.append({
                    "type": "Rect", "RectIndex": furniture,
                    "x": round(rect["x"] * self._mm_x, 6), "y": round(rect["y"] * self._mm_y, 6),
                    "w": round(rect["width"] * self._mm_x, 6),
                    "h": round(rect["height"] * self._mm_y, 6),
                    "fillColor": "none", "strokeColor": border["color"],
                    "strokeWidth": round(width_mm, 6)})
        for legend in page.get("legends", []):
            bounds = frames.get(legend["content_id"])
            if bounds is None:
                continue
            x, y, w, h = bounds["bounds_px"]
            # Shared derivation (image_layout.legend_font_pt), the same one the
            # PDF renderer consumes. Sizes AND positions use font_px — the
            # previous code passed an mm-domain value where px was expected,
            # collapsing the legend to ~1pt text with overlapping rows.
            font_px = legend_font_pt(legend, (x, y, w, h), pt_per_px) / pt_per_px
            self._text(x + 4, y + font_px * 1.5, len(legend["title"]) * font_px, font_px * 1.4,
                       legend["title"], "#1A3A5C", font_px, furniture, bold=True)
            for index, entry in enumerate(legend["items"]):
                cy = y + (index + 2.2) * font_px * 1.5
                self._rect(x + 4, cy - font_px * .35, font_px * 2, font_px * .7,
                           entry["color"], group=furniture)
                self._text(x + 4 + font_px * 2.6, cy, len(entry["label"]) * font_px, font_px * 1.2,
                           entry["label"], "#333333", font_px, furniture)
        layers = [
            {"id": "basemap", "type": "basemap", "rect_indices": [0],
             "fields": ["image_digest", "display_window"]},
            {"id": "route-layer", "type": "route", "rect_indices": [route_group],
             "fields": ["route_mode", "itinerary_group"]},
            {"id": "stops", "type": "stops",
             "rect_indices": [g for k, g in self.groups.items() if k.startswith("image-stop-")],
             "fields": ["visit_order", "stop_name", "stop_type", "map_role"]},
            {"id": "furniture", "type": "furniture", "rect_indices": [furniture],
             "fields": ["title", "notice", "legend"]},
        ]
        page_mm = page["resolved_layout"]["page"]
        # The document IS the canvas payload: no HTTP-style {code, msg, data}
        # envelope — the frontend consumes this file directly as the map object.
        document = {
            "id": self.identifier, "name": self.name, "category": self.category,
            "designWidth": page_mm["width_mm"], "designHeight": page_mm["height_mm"],
            "canvasData": {"type": "Grid", "features": self.features, "mapData": {"layers": layers}},
        }
        registry.validate("frontend-map-document", document)
        for feature in document["canvasData"]["features"]:
            if feature["type"] in {"MultiPoint", "MultiLineString"}:
                if any(not (0 <= x <= page_mm["width_mm"] and 0 <= y <= page_mm["height_mm"])
                       for x, y in feature["coordinates"]):
                    raise ProtocolError("FRONTEND_GEOMETRY_OUTSIDE_CANVAS",
                                        "Canvas geometry must use millimetres within the page")
        return document

    def _group(self, key: str) -> int:
        if key not in self.groups:
            self._next_group += 1
            self.groups[key] = self._next_group
        return self.groups[key]

    def _rect(self, x: float, y: float, w: float, h: float, fill: str, group: int) -> None:
        self.features.append({"type": "Rect", "RectIndex": group,
                              "x": round(x * self._mm_x, 6), "y": round(y * self._mm_y, 6),
                              "w": round(w * self._mm_x, 6), "h": round(h * self._mm_y, 6),
                              "fillColor": fill})

    def _text(self, x: float, y: float, w: float, h: float, text: str, color: str,
              font: float, group: int, *, bold: bool = False, align: str = "left") -> None:
        self.features.append({"type": "Text", "RectIndex": group,
                              "x": round(x * self._mm_x, 6), "y": round(y * self._mm_y, 6),
                              "w": round(max(w, 1e-6) * self._mm_x, 6),
                              "h": round(max(h, 1e-6) * self._mm_y, 6),
                              "text": text, "fontSize": round(font * self._mm_x, 6), "lineHeight": 1.2,
                              "color": color, "textAlign": align, "bold": bold, "italic": False,
                              "underline": False})


def build_canvas_document(registry: SchemaRegistry, scene: dict[str, Any], page: dict[str, Any],
                          *, identifier: str, name: str, category: str) -> dict[str, Any]:
    """Build the frontend Image Canvas v2 document from a frozen image scene."""
    return _CanvasBuilder(registry, scene, page, identifier=identifier, name=name,
                          category=category).build()


def document_digest(document: dict[str, Any]) -> str:
    return sha256_digest(document)
