"""Basemap snapshot tool: freeze the online (Tianditu) view as a registered PNG.

Advisory layer, same pattern as geocode/plan_route: external data acquisition
happens OUTSIDE the kernel, then the snapshot enters the formal pipeline as
ordinary user material (a registered-transform basemap). The kernel re-verifies
digests and geometry (IMAGE_INPUT_DRIFT / registration checks); it never learns
where the PNG came from — a tool-produced snapshot and a manually exported view
are equally legal inputs.

Two input modes for the camera extent (mutually exclusive):
- ``extent``: the standard closed loop — compile emitted it in mapData when the
  request declared online_basemap; the host passes it through;
- ``derive_registration_path`` + ``derive_basemap_path``: the mid-run switch
  loop — the run started image-only and the request is fingerprint-locked, so
  no mapData exists; the tool derives the display-window extent from the
  registration itself (mirroring the kernel's window_extent math, see
  ``derive_camera_extent``).

The tool is pure Python: Web Mercator tile-grid math + httpx fetch + PIL
stitch/crop. No browser, no vector rendering — Tianditu raster tiles are the
image. Determinism: same extent + width (or zoom) + tile data => byte-identical
PNG and a deterministic registration.yaml; the only volatile field is the
provenance timestamp (injectable for tests).

Outbound governance: fetching tiles sends the extent area to the tile provider.
The caller must ensure the request declared online_basemap (the G1 outbound
face) before invoking this tool.

Registration derivation (extent + actual pixel size -> affine):
  work_crs       = EPSG:3857
  origin_m       = [merc_x(west), merc_y(north)]   (top-left corner)
  m_per_px       = (merc_x(east)-merc_x(west)) / width_px   (isotropic: height
                   uses the same value; the aspect is verified, not assumed)
  local_km_y_down_to_pixel = [[1000/m_per_px, 0, 0], [0, 1000/m_per_px, 0]]
  source_size    = [width_px, height_px]
"""
from __future__ import annotations

import io
import math
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx
import yaml

from _service_utils import ServiceError, resolve_under_root, atomic_write_text

_TILE_SIZE = 256
_EARTH_RADIUS = 6378137.0
_MAX_ZOOM = 18
_DEFAULT_WIDTH_PX = 4096
_LAYERS = ("vec_w", "img_w", "cia_w")
_DEFAULT_WHITE_THRESHOLD = 245

_MERCATOR_M_PER_PX_AT_Z0 = 40075016.686 / _TILE_SIZE  # 156543.03392


# ---------------------------------------------------------------- Web Mercator

def _merc_x(lon: float) -> float:
    return lon * (math.pi * _EARTH_RADIUS) / 180.0


def _merc_y(lat: float) -> float:
    return _EARTH_RADIUS * math.log(math.tan(math.pi / 4.0 + math.radians(lat) / 2.0))


def _tile_x(lon: float, zoom: int) -> float:
    return (lon + 180.0) / 360.0 * (2 ** zoom)


def _tile_y(lat: float, zoom: int) -> float:
    return (1.0 - math.log(math.tan(math.radians(lat))
                           + 1.0 / math.cos(math.radians(lat))) / math.pi) / 2.0 * (2 ** zoom)


def _select_zoom(extent: dict[str, float], width_px: int) -> int:
    """Integer zoom whose ground resolution matches the display target.

    The snapshot replaces the basemap shown inside the map FRAME: its ground
    resolution should match extent_width / requested pixel width — NOT
    print-native ground resolution (0.0254/dpi m/px), which is only correct
    when the extent is frame-sized and over-tiles any large extent. First
    real-material run (248km extent) caught the wrong formula: the budget
    guard failed closed on ~2M tiles. Deterministic function of
    (extent, width_px): the smallest integer zoom meeting the target quality.
    """
    extent_w_m = _merc_x(extent["east"]) - _merc_x(extent["west"])
    target_m_per_px = extent_w_m / max(1, width_px)
    center_lat = (extent["south"] + extent["north"]) / 2.0
    resolution_z0 = _MERCATOR_M_PER_PX_AT_Z0 * math.cos(math.radians(center_lat))
    if resolution_z0 <= target_m_per_px:
        return 0
    zoom = int(math.ceil(math.log2(resolution_z0 / target_m_per_px)))
    return max(0, min(zoom, _MAX_ZOOM))


# ---------------------------------------------------------------- tile fetching

def _tianditu_url(layer: str, x: int, y: int, zoom: int, key: str) -> str:
    # Deterministic subdomain rotation (t0..t7), stable across runs.
    subdomain = (x + y) % 8
    return (f"https://t{subdomain}.tianditu.gov.cn/DataServer"
            f"?T={layer}&x={x}&y={y}&l={zoom}&tk={key}")


def _fetch_tile_sync(layer: str, x: int, y: int, zoom: int, key: str) -> bytes:
    """Fetch one raster tile. Module-level so tests can monkeypatch it."""
    with httpx.Client(trust_env=False, verify=True, timeout=30.0) as client:
        response = client.get(_tianditu_url(layer, x, y, zoom, key))
    if response.status_code != 200:
        raise ServiceError("TILE_FETCH_FAILED",
                           f"tile {x}/{y}/{zoom} HTTP {response.status_code}")
    return response.content


# ---------------------------------------------------------------- extent derivation

def _visible_window(data: bytes, threshold: int = _DEFAULT_WHITE_THRESHOLD) -> dict[str, int]:
    """White-border trim, byte-identical semantics to the kernel's
    ``carto_core.adapters.image_display.visible_window`` (alpha-composite over
    white, per-channel minimum, threshold, getbbox) so the tool's derived
    window matches what compile would freeze for the same image.
    """
    from PIL import Image, ImageChops
    with Image.open(io.BytesIO(data)) as image:
        rgba = image.convert("RGBA")
        white = Image.new("RGBA", image.size, "white")
        rgb = Image.alpha_composite(white, rgba).convert("RGB")
        red, green, blue = rgb.split()
        minimum = ImageChops.darker(ImageChops.darker(red, green), blue)
        mask = minimum.point(lambda value: 255 if value < threshold else 0)
        bounds = mask.getbbox()
    if bounds is None:
        raise ServiceError("IMAGE_CONTENT_EMPTY", "image has no visible map content")
    left, top, right, bottom = bounds
    return {"x": left, "y": top, "width": right - left, "height": bottom - top}


def derive_camera_extent(registration: dict[str, Any], image_bytes: bytes) -> dict[str, float]:
    """Registration + basemap bytes -> the frozen camera extent (WGS84 bbox).

    Mirrors the kernel's ``frontend_geo.window_extent``: the display window
    (white-trimmed visible content) corners are inverse-mapped through the
    registration affine to WGS84. This closes the mid-run switch gap — the
    designed closed loop reads the extent from compile output (mapData), which
    does not exist when the run started image-only and the request is
    fingerprint-locked. pyproj/numpy are imported lazily so the standard
    extent-input path keeps the service's zero-carto_core, zero-pyproj
    footprint; the kernel re-validates the produced registration at compile.
    """
    try:
        import numpy as np
        from pyproj import CRS, Transformer
    except ImportError as exc:
        raise ServiceError(
            "DERIVE_DEPENDENCY_MISSING",
            "extent derivation requires numpy and pyproj in the tool environment") from exc
    try:
        matrix = np.asarray(registration["local_km_y_down_to_pixel"], dtype=float)
        origin = np.asarray(registration["origin_m"], dtype=float)
        size = np.asarray(registration["source_size"], dtype=float)
        work = str(registration["work_crs"])
    except (KeyError, TypeError, ValueError) as exc:
        raise ServiceError("REGISTRATION_INVALID",
                           "registration requires work_crs/origin_m/local_km_y_down_to_pixel/source_size") from exc
    if matrix.shape != (2, 3) or origin.shape != (2,) or size.shape != (2,):
        raise ServiceError("REGISTRATION_INVALID",
                           "affine must be 2x3 (2x2 linear + translation); origin/size 2-vectors")
    if not np.isfinite(matrix).all() or not np.isfinite(origin).all():
        raise ServiceError("REGISTRATION_INVALID", "nonfinite registration values")
    from PIL import Image
    with Image.open(io.BytesIO(image_bytes)) as image:
        actual_size = [image.width, image.height]
    if actual_size != [int(value) for value in size]:
        raise ServiceError("REGISTRATION_IMAGE_MISMATCH",
                           "basemap dimensions differ from registration source_size")
    try:
        crs = CRS.from_user_input(work)
        if not crs.is_projected:
            raise ServiceError("REGISTRATION_CRS_INVALID",
                               "work_crs must be a projected CRS (metres)")
        transformer = Transformer.from_crs(crs, "EPSG:4326", always_xy=True, allow_ballpark=False)
    except ServiceError:
        raise
    except Exception as exc:  # pyproj CRSError/ProjError
        raise ServiceError("REGISTRATION_CRS_INVALID",
                           f"cannot build the work-CRS transformation: {exc}") from exc

    window = _visible_window(image_bytes)
    corners = np.asarray([[window["x"], window["y"]],
                          [window["x"] + window["width"], window["y"]],
                          [window["x"] + window["width"], window["y"] + window["height"]],
                          [window["x"], window["y"] + window["height"]]], dtype=float)
    local = (corners - np.asarray(matrix[:, 2], dtype=float)) @ np.linalg.inv(matrix[:, :2].T)
    meters = local * np.asarray([1000.0, -1000.0]) + origin
    try:
        lon, lat = transformer.transform(meters[:, 0], meters[:, 1], errcheck=True)
    except Exception as exc:
        raise ServiceError("REGISTRATION_TRANSFORM_FAILED",
                           f"inverse projection failed: {exc}") from exc
    lon, lat = np.asarray(lon), np.asarray(lat)
    if not (np.isfinite(lon).all() and np.isfinite(lat).all()):
        raise ServiceError("REGISTRATION_TRANSFORM_FAILED", "nonfinite extent corners")
    return {"west": float(lon.min()), "south": float(lat.min()),
            "east": float(lon.max()), "north": float(lat.max())}


# ---------------------------------------------------------------- snapshot core

def _snapshot(extent: dict[str, float], layer: str, width_px: int,
              fetched_at: str | None, zoom_override: int | None = None) -> tuple[bytes, dict[str, Any]]:
    """Stitch the tile grid covering the extent and crop to its pixel bounds."""
    from PIL import Image
    import io

    zoom = zoom_override if zoom_override is not None else _select_zoom(extent, width_px)
    tx_w = _tile_x(extent["west"], zoom)
    tx_e = _tile_x(extent["east"], zoom)
    ty_n = _tile_y(extent["north"], zoom)
    ty_s = _tile_y(extent["south"], zoom)
    x0, x1 = math.floor(tx_w), math.floor(tx_e)
    y0, y1 = math.floor(ty_n), math.floor(ty_s)
    if x1 < x0 or y1 < y0 or (x1 - x0 + 1) * (y1 - y0 + 1) > 4000:
        raise ServiceError("EXTENT_TILE_BUDGET",
                           "extent resolves to an empty or oversized tile grid")

    key = os.environ.get("CARTO_TIANDITU_KEY", "")
    if not key:
        raise ServiceError("TIANDITU_KEY_MISSING",
                           "CARTO_TIANDITU_KEY is required for tile fetching")

    stitched = Image.new("RGB", ((x1 - x0 + 1) * _TILE_SIZE, (y1 - y0 + 1) * _TILE_SIZE))
    tile_count = 0
    for x in range(x0, x1 + 1):
        for y in range(y0, y1 + 1):
            data = _fetch_tile_sync(layer, x, y, zoom, key)
            tile = Image.open(io.BytesIO(data))
            if tile.mode != "RGB":
                tile = tile.convert("RGB")
            stitched.paste(tile, ((x - x0) * _TILE_SIZE, (y - y0) * _TILE_SIZE))
            tile_count += 1

    # Exact extent pixel bounds (fractional tile positions), rounded so the
    # affine is defined against the ACTUAL pixel size.
    left = (tx_w - x0) * _TILE_SIZE
    top = (ty_n - y0) * _TILE_SIZE
    width_px = max(1, int(round((tx_e - tx_w) * _TILE_SIZE)))
    height_px = max(1, int(round((ty_s - ty_n) * _TILE_SIZE)))
    left_i = int(round(left))
    top_i = int(round(top))
    if (left_i < 0 or top_i < 0
            or left_i + width_px > stitched.width or top_i + height_px > stitched.height):
        raise ServiceError("EXTENT_CROP_OUT_OF_RANGE", "extent crop exceeds stitched grid")
    cropped = stitched.crop((left_i, top_i, left_i + width_px, top_i + height_px))

    # Aspect consistency: pixels derive from the extent, so the ratio must
    # hold up to the independent per-axis rounding (one pixel each way).
    merc_w = _merc_x(extent["east"]) - _merc_x(extent["west"])
    merc_h = _merc_y(extent["north"]) - _merc_y(extent["south"])
    m_per_px_x = merc_w / width_px
    m_per_px_y = merc_h / height_px
    tolerance = max(2.0 / max(width_px, height_px), 1e-6)
    if abs(m_per_px_x - m_per_px_y) > tolerance * max(m_per_px_x, m_per_px_y):
        raise ServiceError("SNAPSHOT_GEOMETRY_MISMATCH",
                           "extent aspect and pixel aspect disagree")

    png_buffer = io.BytesIO()
    cropped.save(png_buffer, format="PNG")
    provenance = {
        "provider": "Tianditu",
        "layer": layer,
        "zoom": zoom,
        "tile_count": tile_count,
        "fetched_at": fetched_at or datetime.now(timezone.utc).isoformat(),
        "width_px": width_px,
        "height_px": height_px,
        "extent": dict(extent),
        "requested_width_px": width_px if zoom_override is None else None,
    }
    if provenance["requested_width_px"] is None:
        provenance.pop("requested_width_px")
    return png_buffer.getvalue(), provenance


def _registration(extent: dict[str, float], width_px: int, height_px: int) -> dict[str, Any]:
    merc_w = _merc_x(extent["east"]) - _merc_x(extent["west"])
    m_per_px = merc_w / width_px
    px_per_km = 1000.0 / m_per_px
    return {
        "work_crs": "EPSG:3857",
        "origin_m": [_merc_x(extent["west"]), _merc_y(extent["north"])],
        "local_km_y_down_to_pixel": [[px_per_km, 0.0, 0.0], [0.0, px_per_km, 0.0]],
        "source_size": [width_px, height_px],
    }


def _validate_extent(extent: Any) -> dict[str, float]:
    if not isinstance(extent, dict):
        raise ServiceError("EXTENT_INVALID", "extent must be an object")
    try:
        west, south = float(extent["west"]), float(extent["south"])
        east, north = float(extent["east"]), float(extent["north"])
    except (KeyError, TypeError, ValueError) as exc:
        raise ServiceError("EXTENT_INVALID", "extent requires numeric west/south/east/north") from exc
    if not (-180 <= west < east <= 180 and -90 <= south < north <= 90):
        raise ServiceError("EXTENT_INVALID", "extent bounds are unordered or out of range")
    return {"west": west, "south": south, "east": east, "north": north}


def basemap_snapshot(arguments: dict[str, Any], ctx: dict[str, Any] | None = None) -> dict[str, Any]:
    """Synchronous entry point for the MCP tool.

    Input:
        extent: {west, south, east, north} (WGS84 degrees — the frozen camera
                extent from the map-document's mapData section) — OR the
                registration_path + basemap_path pair below (mutually
                exclusive): the tool derives the display-window extent from
                the registration itself, closing the mid-run switch loop where
                no compile-time mapData exists yet
        derive_registration_path: registration YAML for extent derivation
                (with derive_basemap_path): work_crs/origin_m/
                local_km_y_down_to_pixel/source_size
        derive_basemap_path: the registered basemap PNG for extent derivation
                (display window detection)
        output_path: PNG destination (project-relative or absolute under the
                allowed root)
        registration_path: optional YAML destination (default: PNG stem +
                ".registration.yaml" next to it)
        layer: Tianditu raster layer, default "vec_w"
        width_px: target snapshot width in pixels (default 4096) — drives the
                zoom selection: the smallest integer zoom whose ground
                resolution matches extent_width / width_px
        zoom: optional explicit integer zoom (0..18), overriding the selection
        fetched_at: optional ISO timestamp override (tests/reproducibility)
    Output:
        status=complete: {png_path, registration_path, provenance, registration,
                          extent_source}
    """
    ctx = ctx or {}
    allowed_root = ctx.get("allowed_root")
    if allowed_root is None:
        raise ServiceError("ALLOWED_ROOT_REQUIRED", "the snapshot tool needs the allowed-root context")
    root = Path(allowed_root)

    extent_argument = arguments.get("extent")
    derive_registration = arguments.get("derive_registration_path")
    derive_basemap = arguments.get("derive_basemap_path")
    extent_source = "declared"
    if extent_argument is not None:
        if derive_registration or derive_basemap:
            raise ServiceError("EXTENT_INPUT_CONFLICT",
                               "pass either extent or derive_registration_path + "
                               "derive_basemap_path, not both")
        extent = _validate_extent(extent_argument)
    else:
        if not (derive_registration and derive_basemap):
            raise ServiceError("EXTENT_INPUT_REQUIRED",
                               "extent or derive_registration_path + derive_basemap_path "
                               "is required")
        registration_doc = yaml.safe_load(
            resolve_under_root(str(derive_registration), root).read_text(encoding="utf-8"))
        if not isinstance(registration_doc, dict):
            raise ServiceError("REGISTRATION_INVALID", "registration must be a mapping")
        derive_bytes = resolve_under_root(str(derive_basemap), root).read_bytes()
        extent = {key: round(value, 6)
                  for key, value in derive_camera_extent(registration_doc, derive_bytes).items()}
        extent_source = "derived-registration"
    layer = arguments.get("layer", "vec_w")
    if layer not in _LAYERS:
        raise ServiceError("LAYER_UNSUPPORTED", f"layer must be one of {_LAYERS}")
    try:
        width_px = int(arguments.get("width_px", _DEFAULT_WIDTH_PX))
    except (TypeError, ValueError) as exc:
        raise ServiceError("WIDTH_INVALID", "width_px must be an integer") from exc
    if not 512 <= width_px <= 16384:
        raise ServiceError("WIDTH_INVALID", "width_px must be within 512..16384")
    zoom_override = arguments.get("zoom")
    if zoom_override is not None:
        try:
            zoom_override = int(zoom_override)
        except (TypeError, ValueError) as exc:
            raise ServiceError("ZOOM_INVALID", "zoom must be an integer") from exc
        if not 0 <= zoom_override <= _MAX_ZOOM:
            raise ServiceError("ZOOM_INVALID", "zoom must be within 0..18")

    output_path = arguments.get("output_path", "")
    if not output_path:
        raise ServiceError("OUTPUT_PATH_REQUIRED", "output_path is required")
    png_path = resolve_under_root(str(output_path), root)
    if png_path.suffix.lower() != ".png":
        raise ServiceError("OUTPUT_PATH_INVALID", "output_path must end with .png")
    registration_path = arguments.get("registration_path")
    if registration_path:
        reg_path = resolve_under_root(str(registration_path), root)
    else:
        reg_path = png_path.with_suffix(".registration.yaml")

    png_bytes, provenance = _snapshot(extent, layer, width_px,
                                       arguments.get("fetched_at"), zoom_override)
    png_path.parent.mkdir(parents=True, exist_ok=True)
    png_path.write_bytes(png_bytes)
    registration = _registration(extent, provenance["width_px"], provenance["height_px"])
    atomic_write_text(reg_path, yaml.safe_dump(registration, sort_keys=True, allow_unicode=True))

    return {
        "status": "complete",
        "png_path": str(png_path),
        "registration_path": str(reg_path),
        "provenance": provenance,
        "registration": registration,
        "extent_source": extent_source,
    }
