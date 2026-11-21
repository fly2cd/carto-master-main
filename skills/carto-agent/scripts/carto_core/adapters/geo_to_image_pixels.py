"""WGS84 -> original-image pixel centers (deterministic registered affine).

Migrated from the old framework's adapters/geo_to_image_pixels.py (v1). The
projection/affine equations originate from SpatialRegistration's
BoundaryRegistration. The image itself is never warped or reprojected: only the
lon/lat -> source-pixel mapping is evaluated, so pixels and registration stay
fixed. Production call sites invoke this only through the ToolGateway
``geo-to-image-pixels`` capability (adapters/image_tools.py: typed I/O schemas,
ToolResult evidence, budget accounting); importing the functions directly from
scenario code is blocked by the image-tool boundary ratchet.
"""
from __future__ import annotations

import hashlib
import io
from typing import Any

import numpy as np
from PIL import Image
from pyproj import CRS, Transformer, network
from pyproj.exceptions import CRSError, ProjError

from ..errors import ProtocolError
from .image_layout import inspect_png

CAPABILITY = "geo-to-image-pixels"
METHOD = "registered-affine"
VERSION = "1.0.0"

VALID_ROUTE_MODES = frozenset({"road_network", "provided_geometry", "schematic", "straight_line"})


class PixelConverter:
    """Return original zero-based floating-point pixel-center indices."""

    def __init__(self, parameters: dict[str, Any]) -> None:
        try:
            self.matrix = np.asarray(parameters["local_km_y_down_to_pixel"], dtype=float)
            self.origin = np.asarray(parameters["origin_m"], dtype=float)
            self.size = np.asarray(parameters["source_size"], dtype=float)
        except (KeyError, TypeError, ValueError) as exc:
            raise ProtocolError("REGISTRATION_PARAMETERS_INVALID",
                                "work_crs/origin_m/local_km_y_down_to_pixel/source_size are required") from exc
        if self.matrix.shape != (2, 3) or self.origin.shape != (2,) or self.size.shape != (2,):
            raise ProtocolError("REGISTRATION_PARAMETERS_INVALID",
                                "affine matrix must be 2x3 (2x2 linear + translation); "
                                "origin and size are 2-vectors")
        if not all(np.isfinite(a).all() for a in (self.matrix, self.origin, self.size)):
            raise ProtocolError("REGISTRATION_PARAMETERS_INVALID", "nonfinite registration values")
        if np.any(self.size <= 0):
            raise ProtocolError("REGISTRATION_PARAMETERS_INVALID", "source size must be positive")
        condition = np.linalg.cond(self.matrix[:, :2])
        if not np.isfinite(condition) or condition > 1e12:
            raise ProtocolError("REGISTRATION_MATRIX_SINGULAR", "affine matrix is singular or ill conditioned")
        work = parameters.get("work_crs", "")
        if not isinstance(work, str) or not work.startswith(("PROJCRS[", "PROJCS[", "EPSG:")):
            raise ProtocolError("REGISTRATION_CRS_UNSUPPORTED", "projected WKT or EPSG identifier required")
        try:
            crs = CRS.from_user_input(work)
            if not crs.is_projected or len(crs.axis_info) != 2 or any(
                    abs(axis.unit_conversion_factor - 1) > 1e-12 for axis in crs.axis_info):
                raise ProtocolError("REGISTRATION_CRS_UNSUPPORTED", "work CRS must use projected meters")
            network.set_network_enabled(False)
            self.project = Transformer.from_crs("EPSG:4326", crs, always_xy=True, allow_ballpark=False)
        except (CRSError, ProjError, ValueError) as exc:
            raise ProtocolError("REGISTRATION_CRS_UNSUPPORTED", "cannot create offline projected transformation") from exc

    def coordinates(self, coordinates: list, minimum: int = 1) -> tuple[list, list]:
        try:
            points = np.asarray(coordinates, dtype=float)
        except (TypeError, ValueError) as exc:
            raise ProtocolError("REGISTRATION_COORDINATES_INVALID", "numeric longitude/latitude pairs required") from exc
        if (points.ndim != 2 or points.shape[1] != 2 or not minimum <= len(points) <= 250000
                or any(isinstance(v, (str, bool)) for pair in coordinates for v in pair)
                or not np.isfinite(points).all() or np.any(np.abs(points[:, 0]) > 180) or np.any(np.abs(points[:, 1]) > 90)):
            raise ProtocolError("REGISTRATION_COORDINATES_INVALID", "invalid WGS84 longitude/latitude geometry")
        try:
            x, y = self.project.transform(points[:, 0], points[:, 1], errcheck=True)
        except (ProjError, ValueError) as exc:
            raise ProtocolError("REGISTRATION_TRANSFORM_FAILED", "coordinate projection failed") from exc
        local = (np.column_stack([x, y]) - self.origin) / [1000, -1000]
        pixels = local @ self.matrix[:, :2].T + self.matrix[:, 2]
        if not np.isfinite(pixels).all() or np.any(np.abs(pixels) > 1e9):
            raise ProtocolError("REGISTRATION_TRANSFORM_FAILED", "invalid projected pixel range")
        inside = ((pixels >= -.5) & (pixels < self.size - .5)).all(axis=1)
        return pixels.tolist(), inside.tolist()


def source_pixel_digest(data: bytes) -> str:
    """Match OpenCV IMREAD_UNCHANGED uint8 BGR/BGRA; never hash RGB as BGR."""
    if len(data) < 25 or data[:8] != b"\x89PNG\r\n\x1a\n" or data[24] != 8:
        raise ProtocolError("REGISTRATION_IMAGE_MODE_UNSUPPORTED", "8-bit PNG required")
    with Image.open(io.BytesIO(data)) as image:
        if image.mode in {"RGBA", "RGB"}:
            array = np.asarray(image)
            order = [2, 1, 0, 3] if image.mode == "RGBA" else [2, 1, 0]
            array = array[:, :, order]
        elif image.mode == "L":
            array = np.repeat(np.asarray(image)[:, :, None], 3, axis=2)
        else:
            raise ProtocolError("REGISTRATION_IMAGE_MODE_UNSUPPORTED", "8-bit RGB, RGBA or grayscale PNG required")
        return hashlib.sha256(memoryview(np.ascontiguousarray(array))).hexdigest()


def clip_line(points: list[dict], width: int, height: int) -> list[list[dict]]:
    """Liang-Barsky clipping; retain disjoint parts, never clamp vertices."""
    parts: list[list[dict]] = []
    for start, stop in zip(points, points[1:]):
        x, y = start["x"], start["y"]
        dx, dy = stop["x"] - x, stop["y"] - y
        low, high = 0.0, 1.0
        visible = True
        for p, q in ((-dx, x), (dx, width - x), (-dy, y), (dy, height - y)):
            if p == 0:
                if q < 0:
                    visible = False
                    break
            elif p < 0:
                low = max(low, q / p)
            else:
                high = min(high, q / p)
        if not visible or low > high:
            continue
        a = {"x": min(width, max(0.0, x + low * dx)), "y": min(height, max(0.0, y + low * dy))}
        b = {"x": min(width, max(0.0, x + high * dx)), "y": min(height, max(0.0, y + high * dy))}
        if a == b:
            continue
        if parts and parts[-1][-1] == a:
            parts[-1].append(b)
        else:
            parts.append([a, b])
    return parts


def _feature_collection(document: Any, role: str, *, allow_empty: bool = False) -> list[dict]:
    if (not isinstance(document, dict) or document.get("type") != "FeatureCollection"
            or not isinstance(document.get("features"), list)):
        raise ProtocolError("GEOJSON_FEATURE_COLLECTION_REQUIRED", role)
    if not document["features"]:
        if allow_empty:
            return []
        raise ProtocolError("GEOJSON_FEATURE_COLLECTION_REQUIRED", role)
    if len(document["features"]) > 1000:
        raise ProtocolError("REGISTRATION_GEOMETRY_LIMIT", "too many features")
    return document["features"]


def project_features(parameters: dict[str, Any], image_bytes: bytes,
                     stops_collection: dict[str, Any],
                     route_collection: dict[str, Any]) -> dict[str, Any]:
    """Project ordered stops and route lines to original-image pixel anchors.

    Returns the frozen projection document consumed by apply_grouped_style:
    stops sorted by visit_order (sequential from 1) and clipped route parts.
    """
    size = inspect_png(image_bytes)
    converter = PixelConverter(parameters)
    declared = parameters.get("source_size")
    if [size["width_px"], size["height_px"]] != list(declared or []):
        raise ProtocolError("REGISTRATION_IMAGE_MISMATCH", "original dimensions do not match parameters")
    if parameters.get("source_pixel_sha256") and source_pixel_digest(image_bytes) != parameters["source_pixel_sha256"]:
        raise ProtocolError("REGISTRATION_IMAGE_MISMATCH", "decoded pixel digest does not match parameters")
    projection: dict[str, Any] = {
        "schema_version": 1, "method": METHOD, "method_version": VERSION,
        "pixel_convention": "image-edge; x-right; y-down; center-offset-applied-once",
        "source_size": size, "stops": [], "routes": [],
    }
    total_vertices = 0
    positional = {"route-stops": 0, "route-line": 0}
    for role, collection, target in (("route-stops", stops_collection, "stops"),
                                      ("route-line", route_collection, "routes")):
        for feature in _feature_collection(collection, role, allow_empty=(role == "route-line")):
            fid = str(feature.get("id") or f"{role}-{positional[role]}")
            positional[role] += 1
            geometry = feature.get("geometry") or {}
            properties = feature.get("properties") or {}
            if not isinstance(geometry, dict) or "coordinates" not in geometry or not isinstance(properties, dict):
                raise ProtocolError("REGISTRATION_GEOMETRY_INVALID", "geometry and typed properties required")
            if role == "route-stops":
                if geometry.get("type") != "Point" or not isinstance(properties.get("visit_order"), int):
                    raise ProtocolError("REGISTRATION_GEOMETRY_INVALID", "ordered Point stops required")
                pixels, inside = converter.coordinates([geometry["coordinates"]])
                if not inside[0]:
                    raise ProtocolError("REGISTRATION_STOP_OUTSIDE_IMAGE", "stop lies outside registered image")
                projection["stops"].append({"feature_id": fid, "visit_order": properties["visit_order"],
                                            "position": {"x": pixels[0][0] + .5, "y": pixels[0][1] + .5}})
                total_vertices += 1
            else:
                kind = geometry.get("type")
                if kind not in {"LineString", "MultiLineString"}:
                    raise ProtocolError("REGISTRATION_GEOMETRY_INVALID", "LineString/MultiLineString route required")
                coordinates = [geometry["coordinates"]] if kind == "LineString" else geometry["coordinates"]
                if not isinstance(coordinates, list) or not coordinates:
                    raise ProtocolError("REGISTRATION_GEOMETRY_INVALID", "empty route")
                if len(coordinates) > 1000:
                    raise ProtocolError("REGISTRATION_GEOMETRY_LIMIT", "too many route parts")
                parts, originals, outside = [], [], 0
                for line in coordinates:
                    if not isinstance(line, list) or len(line) > 10000:
                        raise ProtocolError("REGISTRATION_GEOMETRY_LIMIT", "too many route vertices")
                    pixels, inside = converter.coordinates(line, 2)
                    normalized = [{"x": x + .5, "y": y + .5} for x, y in pixels]
                    originals.append(normalized)
                    parts.extend(clip_line(normalized, size["width_px"], size["height_px"]))
                    outside += inside.count(False)
                    total_vertices += len(line)
                if len(parts) > 1000 or any(len(part) > 10000 for part in parts):
                    raise ProtocolError("REGISTRATION_GEOMETRY_LIMIT", "clipped geometry exceeds output limits")
                mode = properties.get("route_mode")
                if mode not in VALID_ROUTE_MODES:
                    raise ProtocolError("ROUTE_ENGINE_INVALID", "explicit route mode required")
                projection["routes"].append({"feature_id": fid, "parts": parts, "original_parts": originals,
                                             "outside_vertex_count": outside, "route_mode": mode})
            if total_vertices > 250000:
                raise ProtocolError("REGISTRATION_GEOMETRY_LIMIT", "too many input vertices")
    projection["stops"].sort(key=lambda s: s["visit_order"])
    if [s["visit_order"] for s in projection["stops"]] != list(range(1, len(projection["stops"]) + 1)):
        raise ProtocolError("IMAGE_PROJECTION_ORDER_INVALID", "stop order must be sequential")
    return projection


def normalize_extent(parameters: dict[str, Any]) -> list[float]:
    """Rough WGS84 bbox from the registration corners; declarative only."""
    converter = PixelConverter(parameters)
    corners = np.asarray([[0, 0], [parameters["source_size"][0], 0],
                          [parameters["source_size"][0], parameters["source_size"][1]],
                          [0, parameters["source_size"][1]]], dtype=float)
    matrix = converter.matrix
    # pixels = local @ matrix[:, :2].T + matrix[:, 2]  =>  local = (pixels - t) @ inv(M.T)
    local = (corners - np.asarray(matrix[:, 2], dtype=float)) @ np.linalg.inv(matrix[:, :2].T)
    meters = local * [1000, -1000] + converter.origin
    lon, lat = converter.project.transform(meters[:, 0], meters[:, 1], direction="INVERSE", errcheck=True)
    if not np.isfinite(lon).all() or not np.isfinite(lat).all():
        raise ProtocolError("REGISTRATION_TRANSFORM_FAILED", "extent inversion failed")
    return [float(min(lon)), float(min(lat)), float(max(lon)), float(max(lat))]


def display_scale(window: dict[str, int]) -> float:
    """Style scale relative to the 144-DPI reference design (2381x1684 A3)."""
    return max(1.0, min(window["width"] / 2381, window["height"] / 1684))
