"""leadership-visit frontend document: graphics list -> map_json (成果本体).

Thin scenario wrapper over the renderer-neutral Image Canvas v2 builder
(``adapters.frontend_canvas``): the scenario contributes its document
identity (category) and keeps the component-facing API stable. The document
is built directly from the frozen ``image_graphics`` list — never from
rendered PNG/SVG output — so the frontend rendering and the PDF stay
pixel-consistent. The basemap is NOT embedded: the frontend loads the
registered image separately.

Online-view binding: when the request declares ``online_basemap``, the
compiler calls ``geo_sections`` BEFORE freezing the page request — the
scenario resolves the semantic facts (stop/route colors via the SAME
grouped-style resolution the canvas graphics use, labels, periods, from/to
names) and delegates the geometric derivation to ``adapters.frontend_geo``
(display window -> WGS84 extent, scale-free camera contract). The sections
ride the frozen page contract (``page.document.geo``) so BOTH renderers
deterministically rebuild the identical document: ``build`` merges them back,
exactly like the renderer's preview copy. Without the declaration the output
is byte-identical to the canvas-only document (regression anchor).
"""
from __future__ import annotations

from typing import Any

from ...adapters.frontend_canvas import build_canvas_document, stop_card_index
from ...adapters.frontend_geo import attach_geo_sections, build_geo_sections
from ...backend_registry import IMAGE_ITINERARY_PAGE
from ...errors import ProtocolError
from ...schema_registry import SchemaRegistry
from .style import REFERENCE_HEIGHT_PX, REFERENCE_WIDTH_PX, itinerary_value

CATEGORY = "leadership_visit"
_PERIODS = ("morning", "afternoon", "default")


def _display_scale(window: dict[str, Any]) -> float:
    return max(1.0, min(window["width"] / REFERENCE_WIDTH_PX,
                        window["height"] / REFERENCE_HEIGHT_PX))


def _group_key(feature: dict[str, Any], role_fields: dict[str, str],
               default_group: str, groups: dict[str, dict[str, Any]]) -> str:
    """Same grouped-style resolution apply_grouped_style uses (via _value)."""
    value = itinerary_value(feature, role_fields, "itinerary-group")
    key = default_group if value is None or value == "" else value
    if not isinstance(key, str) or key not in groups:
        raise ProtocolError("ITINERARY_GROUP_UNKNOWN", "itinerary-group")
    return key


class FrontendDocumentBuilder:
    """Deterministic map_json builder; consumes the same graphics as the renderer."""

    def __init__(self, registry: SchemaRegistry | None = None) -> None:
        self.registry = registry or SchemaRegistry()

    def build(self, scene: dict[str, Any], page: dict[str, Any], *,
              identifier: str, name: str) -> dict[str, Any]:
        """Build the frontend document for a frozen image RenderScene.

        ``scene`` carries image_graphics + resolved_layout + viewport; ``page``
        is the validated image page-request (basemap window, texts, legends).
        The frozen online-view sections (``page.document.geo``) are merged back
        so the compile-time document, the renderer's preview copy and the
        immutable-store original are byte-identical by construction.
        """
        if scene["renderer_id"] != IMAGE_ITINERARY_PAGE.renderer_id:
            raise ProtocolError("FRONTEND_MODE_UNSUPPORTED",
                                "the image itinerary document requires the image backend")
        document = build_canvas_document(self.registry, scene, page,
                                         identifier=identifier, name=name,
                                         category=CATEGORY)
        geo = (page.get("document") or {}).get("geo")
        if geo:
            attach_geo_sections(document, geo)
            self.registry.validate("frontend-map-document", document)
        return document

    def build_for_scene(self, scene: dict[str, Any], page: dict[str, Any]) -> dict[str, Any]:
        """Convenience wrapper: identifier/name derived from the scene identity."""
        return self.build(scene, page, identifier=f"map-{scene['scene_id']}",
                          name=f"领导调研行程路线图 {scene['scene_id']}")

    # ------------------------------------------------------------------
    # online-view geo sections (called BEFORE the page request is frozen)
    # ------------------------------------------------------------------

    def geo_sections(self, scene: dict[str, Any], page: dict[str, Any],
                     request: dict[str, Any], parameters: dict[str, Any],
                     fields: dict[str, dict[str, str]],
                     stops_document: dict[str, Any],
                     route_document: dict[str, Any],
                     style: dict[str, Any]) -> dict[str, Any] | None:
        """Compute the frozen online-view sections, or None when not declared.

        ``scene`` may be a partial dict carrying resolved_layout/viewport (the
        full scene is assembled later); ``page`` is the in-progress page
        request with its basemap display window. Call before freezing the page
        request so the sections can ride ``page.document.geo``.
        """
        online = request.get("online_basemap")
        if not online:
            return None
        for required, label in ((parameters, "registration parameters"),
                                (stops_document, "prepared stops document"),
                                (style, "style contract")):
            if required is None:
                raise ProtocolError("FRONTEND_GEO_INPUT_REQUIRED",
                                    f"online basemap sections require {label}")
        stops, routes = self._resolve_facts(scene.get("image_graphics", []), page,
                                            stops_document, route_document or {},
                                            style, fields or {})
        stop_card = stop_card_index(scene.get("image_graphics", []))
        return build_geo_sections(scene, page, parameters, online,
                                  stops=stops, routes=routes, stop_card=stop_card)

    # ------------------------------------------------------------------
    # semantic fact resolution (colors/labels/periods consistent with canvas)
    # ------------------------------------------------------------------

    def _resolve_facts(self, graphics: list[dict[str, Any]], page: dict[str, Any],
                       stops_document: dict[str, Any], route_document: dict[str, Any],
                       style: dict[str, Any],
                       fields: dict[str, dict[str, str]]) -> tuple[list[dict], list[dict]]:
        window = page["basemap"]["display_window"]
        groups = {g["id"]: g for g in style["groups"]}
        stop_fields = fields.get("route-stops", {})
        route_fields = fields.get("route-line", {})
        point_index = {g["visit_order"]: g for g in graphics
                       if g.get("type") == "point" and "visit_order" in g}

        stops: list[dict[str, Any]] = []
        name_by_stop_id: dict[str, str] = {}
        for feature in sorted(stops_document.get("features", []),
                              key=lambda f: (f.get("properties") or {}).get("visit_order", 0)):
            props = feature.get("properties") or {}
            order = int(props.get("visit_order", 0))
            geometry = feature.get("geometry") or {}
            lon, lat = (geometry.get("coordinates") or [0.0, 0.0])[:2]
            graphic = point_index.get(order)
            if graphic is None:
                raise ProtocolError("FRONTEND_GEO_STOP_GRAPHIC_MISSING",
                                    f"stop {order} has no point graphic in the frozen scene")
            stop_id = str(feature.get("id") or f"stop-{order}")
            name_by_stop_id[stop_id] = str(props.get("stop_name", ""))
            period = _group_key(feature, stop_fields, style["default_group"], groups)
            if period not in _PERIODS:
                raise ProtocolError("FRONTEND_GEO_PERIOD_UNSUPPORTED", period)
            role = props.get("map_role", "visit")
            label = "出发点" if role == "origin" else ("返程点" if role == "destination"
                                                       else f"行程点 {order}")
            stops.append({
                "id": stop_id, "name": str(props.get("stop_name", "")),
                "formatted_address": str(props.get("formatted_address", "")),
                "lon": lon, "lat": lat, "order": order,
                "label": label,
                "index": None if role in ("origin", "destination") else order,
                "period": period,
                # Colors/radius come from the frozen point graphics so mapData
                # and canvasData agree by construction, not by re-derivation.
                "icon": "star" if graphic.get("group") == "support" else "circle",
                "color": graphic.get("color"), "radius_px": graphic.get("radius_px", 12),
            })

        scale = _display_scale(window)
        routes: list[dict[str, Any]] = []
        for feature in route_document.get("features", []):
            props = feature.get("properties") or {}
            geometry = feature.get("geometry") or {}
            coordinates = geometry.get("coordinates") or []
            if geometry.get("type") != "LineString" or len(coordinates) < 2:
                raise ProtocolError("FRONTEND_GEO_ROUTE_INVALID",
                                    "route legs require a LineString with >= 2 vertices")
            period = _group_key(feature, route_fields, style["default_group"], groups)
            if period not in _PERIODS:
                raise ProtocolError("FRONTEND_GEO_PERIOD_UNSUPPORTED", period)
            routes.append({
                "period": period,
                "from_name": name_by_stop_id.get(str(props.get("from_stop_id", "")), ""),
                "to_name": name_by_stop_id.get(str(props.get("to_stop_id", "")), ""),
                "polyline": [[float(lon), float(lat)] for lon, lat in coordinates],
                "stroke_color": groups[period]["color"],
                "stroke_width_px": float(style["route"]["width_px"]) * scale,
            })
        return stops, routes
