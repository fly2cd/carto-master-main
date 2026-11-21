"""Frontend geographic map sections (online-view binding, renderer-neutral).

Builds the optional top-level ``baseMap`` + ``mapData`` sections of the frontend
map document when the request declares ``online_basemap``. Pure derivation from
frozen inputs: the display window — the geographic authority of the registered
image — is translated to a WGS84 extent/center through the INVERSE registration
affine, so the online view shows the same geography as the canvas/PDF view.
Switching basemaps at display time moves no itinerary element; itinerary
coordinates never participate in the extent computation (the existing
stop-inside-image gate already guarantees coverage).

Camera contract is scale-free: zoom is a device-dependent runtime quantity
derived from the declared ``zoomRule`` (contain-replicate: replicate the
``contain_layout`` placement in Web Mercator), never a frozen number. The
kernel emits ``referenceZoom`` as a page-DPI diagnostic only.

Gates fail closed (error family LEADERSHIP_ONLINE_BASEMAP_*): the work CRS must
be EPSG:3857 (the affine's Mercator plane must coincide with the engine's Web
Mercator projection) and the affine must be isotropic and axis-aligned (a
rotated or anisotropic mapping cannot be replayed by a north-up engine camera).

Layering: deterministic compile-time derivation governed by the frozen document
digests — deliberately NOT a ToolGateway capability (same class as
``frontend_canvas``). This module never imports a concrete scenario (boundary
guard); the scenario resolves semantic values (stop/route style and text) and
hands them over as plain data.
"""
from __future__ import annotations

import math
from typing import Any

import numpy as np

from copy import deepcopy

from ..errors import ProtocolError
from ..compiler.layout import LayoutResolver
from .geo_to_image_pixels import PixelConverter
from .image_layout import contain_layout

_EARTH_EQUATOR_CIRCUMFERENCE_M = 40075016.686  # Web Mercator equator circumference
_TILE_SIZE_PX = 256
_PERIOD_NAMES = {"morning": "上午行程点", "afternoon": "下午行程点", "default": "行程点"}
_ROUTE_PERIOD_NAMES = {"morning": "上午路线", "afternoon": "下午路线", "default": "路线"}
_PERIODS = ("morning", "afternoon", "default")
_MERCATOR_M_PER_PX_AT_Z0 = _EARTH_EQUATOR_CIRCUMFERENCE_M / _TILE_SIZE_PX  # 156543.03392
_ISOTROPY_TOLERANCE = 1e-3
_EXTENT_EPSILON_DEG = 1e-7


def _validated_affine(parameters: dict[str, Any]) -> tuple[PixelConverter, np.ndarray]:
    """Gate the registration for online replay: EPSG:3857 + isotropic + axis-aligned."""
    work = str(parameters.get("work_crs", "")).strip()
    if work != "EPSG:3857":
        raise ProtocolError(
            "LEADERSHIP_ONLINE_BASEMAP_CRS_UNSUPPORTED",
            "online basemap replay requires work_crs EPSG:3857 (Web Mercator) so the "
            "registration affine plane coincides with the engine projection")
    converter = PixelConverter(parameters)
    matrix = np.asarray(converter.matrix, dtype=float)
    a, b = matrix[0, 0], matrix[0, 1]
    c, d = matrix[1, 0], matrix[1, 1]
    scale = (abs(a) + abs(d)) / 2.0
    if scale <= 0:
        raise ProtocolError("LEADERSHIP_ONLINE_BASEMAP_AFFINE_UNSUPPORTED",
                            "degenerate registration affine")
    if (abs(b) > _ISOTROPY_TOLERANCE * scale or abs(c) > _ISOTROPY_TOLERANCE * scale
            or abs(abs(a) - abs(d)) > _ISOTROPY_TOLERANCE * scale):
        raise ProtocolError(
            "LEADERSHIP_ONLINE_BASEMAP_AFFINE_UNSUPPORTED",
            "online basemap replay requires an axis-aligned isotropic affine "
            "(a north-up engine camera cannot replay rotated or anisotropic mappings)")
    return converter, matrix


def _inverse_pixels(converter: PixelConverter, matrix: np.ndarray,
                    pixels: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Map source-image pixels back to WGS84 lon/lat (inverse registration affine)."""
    origin = np.asarray(converter.origin, dtype=float)
    local = (pixels - np.asarray(matrix[:, 2], dtype=float)) @ np.linalg.inv(matrix[:, :2].T)
    meters = local * np.asarray([1000.0, -1000.0]) + origin
    lon, lat = converter.project.transform(meters[:, 0], meters[:, 1],
                                          direction="INVERSE", errcheck=True)
    return np.asarray(lon), np.asarray(lat)


def window_extent(parameters: dict[str, Any],
                  window: dict[str, Any]) -> tuple[dict[str, float], dict[str, float]]:
    """Display window -> WGS84 extent bbox + center (the window's geographic translation)."""
    converter, matrix = _validated_affine(parameters)
    corners = np.asarray([[window["x"], window["y"]],
                          [window["x"] + window["width"], window["y"]],
                          [window["x"] + window["width"], window["y"] + window["height"]],
                          [window["x"], window["y"] + window["height"]]], dtype=float)
    lon, lat = _inverse_pixels(converter, matrix, corners)
    if not (np.isfinite(lon).all() and np.isfinite(lat).all()):
        raise ProtocolError("FRONTEND_GEO_EXTENT_INVALID", "window extent inversion failed")
    extent = {"west": float(lon.min()), "south": float(lat.min()),
              "east": float(lon.max()), "north": float(lat.max()), "unit": "degree"}
    center_lon, center_lat = _inverse_pixels(
        converter, matrix,
        np.asarray([[window["x"] + window["width"] / 2.0,
                     window["y"] + window["height"] / 2.0]], dtype=float))
    center = {"lon": float(center_lon[0]), "lat": float(center_lat[0])}
    return extent, center


def _reference_zoom(converter: PixelConverter, matrix: np.ndarray, window: dict[str, Any],
                    placement_scale: float, center_lat: float) -> float:
    """Diagnostic zoom at the page DPI (not part of the binding contract)."""
    meters_per_window_px = 1000.0 / abs(float(matrix[0, 0]))
    meters_per_page_px = meters_per_window_px / placement_scale
    if meters_per_page_px <= 0:
        raise ProtocolError("FRONTEND_GEO_EXTENT_INVALID", "nonpositive page resolution")
    zoom = math.log2(_MERCATOR_M_PER_PX_AT_Z0 * math.cos(math.radians(center_lat))
                     / meters_per_page_px)
    if not math.isfinite(zoom):
        raise ProtocolError("FRONTEND_GEO_EXTENT_INVALID", "reference zoom not finite")
    return zoom


def _hex_color(value: Any, role: str) -> str:
    if not isinstance(value, str) or not value.startswith("#") or len(value) != 7:
        raise ProtocolError("FRONTEND_GEO_STYLE_INVALID", role)
    return value


def attach_geo_sections(document: dict[str, Any],
                        geo: dict[str, Any] | None) -> None:
    """Merge the frozen online-view sections into a canvas document.

    Used identically by the compile-time document builder and the renderer's
    preview copy so both produce byte-identical documents from the same frozen
    page contract (``page.document.geo``).
    """
    if not geo:
        return
    document["baseMap"] = deepcopy(geo["baseMap"])
    document["mapData"] = deepcopy(geo["mapData"])


def build_geo_sections(scene: dict[str, Any], page: dict[str, Any],
                       parameters: dict[str, Any], online_decl: dict[str, Any], *,
                       stops: list[dict[str, Any]], routes: list[dict[str, Any]],
                       stop_card: dict[int, int]) -> dict[str, Any]:
    """Build the top-level ``baseMap`` + ``mapData`` sections for a frozen image scene.

    ``stops``/``routes`` are scenario-resolved semantic lists (WGS84 facts with
    resolved group styles, px-domain sizes); ``stop_card`` is the stop_order ->
    RectIndex card map from ``frontend_canvas.stop_card_index`` so mapData
    points reference the same cards the canvas view shows.
    """
    basemap = page.get("basemap") or {}
    window = basemap.get("display_window")
    if not window:
        raise ProtocolError("FRONTEND_PAGE_CONTEXT_REQUIRED",
                            "image page request with a display window is required")
    converter, matrix = _validated_affine(parameters)
    extent, center = window_extent(parameters, window)

    frame = LayoutResolver.map_frame(scene["resolved_layout"])
    frame_x, frame_y, frame_w, frame_h = frame["bounds_px"]
    # Page dimensions come from the scene's resolved layout (the page argument
    # may be a draft carrying only the basemap window before the freeze).
    page_mm = scene["resolved_layout"]["page"]
    viewport = scene["viewport"]
    mm_x = page_mm["width_mm"] / viewport["width_px"]
    mm_y = page_mm["height_mm"] / viewport["height_px"]
    placement = contain_layout({"width_px": window["width"], "height_px": window["height"]},
                               {"x": frame_x, "y": frame_y, "width": frame_w, "height": frame_h})

    # Completeness: the window-derived extent must cover every stop (the image
    # gate already forces stops inside the image; this catches the pathological
    # case of a stop landing in a trimmed white margin — which would also hurt
    # the canvas view — and protects BOTH views).
    for stop in stops:
        if not (extent["west"] - _EXTENT_EPSILON_DEG <= stop["lon"] <= extent["east"] + _EXTENT_EPSILON_DEG
                and extent["south"] - _EXTENT_EPSILON_DEG <= stop["lat"] <= extent["north"] + _EXTENT_EPSILON_DEG):
            raise ProtocolError(
                "LEADERSHIP_ONLINE_STOP_OUTSIDE_EXTENT",
                f"stop {stop.get('id', '?')} lies outside the display-window extent; "
                "the registered image's trimmed window does not cover the itinerary")

    reference_zoom = _reference_zoom(converter, matrix, window, placement["scale"], center["lat"])

    base_map = {"type": str(online_decl["provider"]), "layer": str(online_decl["layer"])}
    for key in ("opacity", "minZoom", "maxZoom"):
        if key in online_decl:
            base_map[key] = online_decl[key]

    point_features: list[dict[str, Any]] = []
    for period in _PERIODS:
        period_stops = [s for s in stops if s["period"] == period]
        if not period_stops:
            continue
        points = []
        for stop in period_stops:
            if stop["order"] not in stop_card:
                raise ProtocolError("FRONTEND_GEO_STOP_CARD_MISSING",
                                    f"stop {stop['id']} has no canvas card group")
            entry: dict[str, Any] = {
                "id": stop["id"], "name": stop["name"],
                "formattedAddress": stop["formatted_address"],
                "lon": round(float(stop["lon"]), 6), "lat": round(float(stop["lat"]), 6),
                "label": stop["label"], "RectIndex": stop_card[stop["order"]],
                "style": {"icon": stop["icon"],
                          "size": round((2.0 * stop["radius_px"] + 4.0) * mm_x, 6),
                          "color": _hex_color(stop["color"], "point color")},
            }
            if stop["index"] is not None:
                entry["index"] = stop["index"]
            points.append(entry)
        point_features.append({"type": "stops", "name": _PERIOD_NAMES[period],
                               "properties": {"period": period, "points": points}})

    route_features: list[dict[str, Any]] = []
    for period in _PERIODS:
        period_routes = [r for r in routes if r["period"] == period]
        if not period_routes:
            continue
        legs = []
        for route in period_routes:
            legs.append({"fromName": route["from_name"], "toName": route["to_name"],
                         "polyline": [[round(float(lon), 6), round(float(lat), 6)]
                                      for lon, lat in route["polyline"]]})
        route_features.append({
            "type": "route", "name": _ROUTE_PERIOD_NAMES[period],
            "properties": {"period": period, "legs": legs},
            "style": {"strokeColor": _hex_color(period_routes[0]["stroke_color"], "route color"),
                      "strokeWidth": round(
                          period_routes[0]["stroke_width_px"] * placement["scale"] * mm_x, 6),
                      "strokeDash": ""}})

    if not point_features:
        raise ProtocolError("FRONTEND_GEO_STOPS_REQUIRED", "stops facts are required")

    map_data = {
        "x": round(frame_x * mm_x, 6), "y": round(frame_y * mm_y, 6),
        "w": round(frame_w * mm_x, 6), "h": round(frame_h * mm_y, 6),
        "type": "Vector",
        "extent": {key: (round(value, 9) if isinstance(value, float) else value)
                   for key, value in extent.items()},
        "center": {key: round(value, 9) for key, value in center.items()},
        "bearing": 0,
        "zoomRule": "contain-replicate",
        "referenceZoom": round(reference_zoom, 4),
        "coordinateSystem": "WGS84",
        "features": point_features + route_features,
    }
    return {"baseMap": base_map, "mapData": map_data}
