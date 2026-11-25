"""Image-pixel layout primitives; no geographic coordinate interpretation.

Migrated from the old framework's adapters/image_layout.py (v1). The layout
functions are pure pixel math: PNG bounds checking, aspect-preserving map-frame
placement and conservative CJK callout text measurement. Geographic registration
lives in geo_to_image_pixels.py; display-window detection in image_display.py.

Layering: this is mechanical-derivation-layer code (design-principles.md §2.3),
governed by the frozen scene/page digests — it is deliberately NOT a ToolGateway
capability. Gateway capabilities cover the image algorithms with authorization
and evidence semantics (geo-to-image-pixels / image-display-bounds /
annotation-layout, bound in adapters/image_tools.py).
"""
from __future__ import annotations

import io
import math
import warnings
from typing import Any

from PIL import Image

from ..errors import ProtocolError

MAX_IMAGE_BYTES = 64 * 1024 * 1024
MAX_IMAGE_PIXELS = 64 * 1024 * 1024
MAX_IMAGE_SIDE = 16384


def furniture_font_pt(item: dict[str, Any], bounds_px: tuple[float, float, float, float],
                      pt_per_px: float, *, fit_mode: str = "shrink-to-fit",
                      min_pt: float = 4.0) -> float:
    """Nominal page-furniture font in points — the shared derivation BOTH renderers
    consume (PDF and frontend map_json stay pixel-consistent).

    X10: the capacity-fit behavior is an EXPLICIT adopted mode, not an implicit authority:
      * ``shrink-to-fit`` (recorded baseline preset): clamp the nominal size down to the
        frame capacity, floored at ``min_pt``;
      * ``reject-overflow``: the nominal size must fit; otherwise refuse (design revision),
        never silently shrink.
    The frozen page contract's ``font_pt`` wins as the nominal size; absent falls back to
    the historical renderer nominal (title 18pt / other 9pt). An explicit value is a nominal
    size, never an overflow bypass.
    """
    if fit_mode not in {"shrink-to-fit", "reject-overflow"}:
        raise ProtocolError("FONT_FIT_MODE_UNSUPPORTED", fit_mode)
    _x, _y, w, h = bounds_px
    nominal = float(item.get("font_pt", 18.0 if item.get("content_id") == "title" else 9.0))
    fit_width = (w - 8) * pt_per_px / max(1, len(item.get("text", "")))
    fit_height = h * 0.8 * pt_per_px
    capacity = min(fit_width, fit_height)
    if fit_mode == "reject-overflow":
        if nominal > capacity:
            raise ProtocolError("FONT_CAPACITY_OVERFLOW", item.get("content_id", "furniture"))
        return nominal
    return max(min_pt, min(nominal, capacity))


def legend_font_pt(legend: dict[str, Any], bounds_px: tuple[float, float, float, float],
                   pt_per_px: float) -> float:
    """Legend font in points — the shared derivation BOTH renderers consume
    (PDF and frontend map_json stay pixel-consistent).

    Nominal cap 3mm (8.504pt), capped by the legend frame's row height and
    label width fits, floored at 3pt. Positions and swatch geometry derive
    from the pt value via ``pt / pt_per_px`` in page pixels — the same
    two-domain discipline ``furniture_font_pt`` uses.
    """
    _x, _y, w, h = bounds_px
    rows = len(legend.get("items", []))
    labels = max(len(item["label"]) for item in legend["items"]) if rows else 1
    font = min(3 * 72 / 25.4, (h - 8) * pt_per_px / (rows + 1),
               (w - 16) * pt_per_px / (labels + 4))
    return max(3.0, font)


def frame_border_rects(placement: dict[str, float], border: dict[str, Any],
                       px_per_mm: float, *, surrounds: str = "placed-map-content"
                       ) -> tuple[dict[str, float], dict[str, float]]:
    """Inner and outer map-frame border rectangles in page pixels — the shared
    geometry BOTH renderers draw.

    X06: ``surrounds`` is an EXPLICIT binding, not an implicit choice. The baseline
    ``placed-map-content`` rides the actual contain-placed image rectangle (including
    letterbox whitespace); ``view-frame`` (surrounding the whole map frame) is a separate
    explicit design choice and is not admitted by this baseline preset. The inner stroke
    rides the bound path; the outer path sits ``gap_mm + (inner + outer) / 2`` outward so
    the visual edge-to-edge distance between the two strokes is ``gap_mm`` (strokes are
    centred on their paths in both renderers). Widths travel in millimetres.
    """
    if surrounds != "placed-map-content":
        raise ProtocolError("BORDER_SURROUNDS_UNSUPPORTED", surrounds)
    gap = float(border["gap_mm"]) * px_per_mm
    inner_w = float(border["inner_width_mm"]) * px_per_mm
    outer_w = float(border["outer_width_mm"]) * px_per_mm
    x, y = float(placement["x"]), float(placement["y"])
    w, h = float(placement["width"]), float(placement["height"])
    inner = {"x": x, "y": y, "width": w, "height": h}
    offset = gap + (inner_w + outer_w) / 2
    outer = {"x": x - offset, "y": y - offset,
             "width": w + 2 * offset, "height": h + 2 * offset}
    return inner, outer


def contain_layout(source_size: dict[str, int], frame: dict[str, float]) -> dict[str, float]:
    """Aspect-preserving placement of a source image inside a page frame."""
    values = [source_size["width_px"], source_size["height_px"], *frame.values()]
    if any(isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v) for v in values):
        raise ProtocolError("IMAGE_LAYOUT_INVALID", "finite numeric dimensions required")
    width, height = source_size["width_px"], source_size["height_px"]
    if min(width, height, frame["width"], frame["height"]) <= 0 or min(frame["x"], frame["y"]) < 0:
        raise ProtocolError("IMAGE_LAYOUT_INVALID", "invalid frame or source dimensions")
    if max(width, height) > MAX_IMAGE_SIDE or width * height > MAX_IMAGE_PIXELS:
        raise ProtocolError("IMAGE_SIZE_LIMIT", "image dimensions exceed limits")
    scale = min(frame["width"] / width, frame["height"] / height)
    return {
        "x": frame["x"] + (frame["width"] - width * scale) / 2,
        "y": frame["y"] + (frame["height"] - height * scale) / 2,
        "width": width * scale,
        "height": height * scale,
        "scale": scale,
    }


def inspect_png(data: bytes) -> dict[str, int]:
    """Verify structure and fully decode a bounded, single-frame PNG."""
    if len(data) > MAX_IMAGE_BYTES:
        raise ProtocolError("IMAGE_SIZE_LIMIT", "image file exceeds limits")
    if not data.startswith(b"\x89PNG\r\n\x1a\n"):
        raise ProtocolError("IMAGE_FORMAT_UNSUPPORTED", "image map frames require PNG")
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(io.BytesIO(data)) as image:
                width, height = image.size
                if (max(width, height) > MAX_IMAGE_SIDE or width * height > MAX_IMAGE_PIXELS
                        or getattr(image, "n_frames", 1) != 1):
                    raise ProtocolError("IMAGE_SIZE_LIMIT", "image dimensions or frame count exceed limits")
                image.verify()
            with Image.open(io.BytesIO(data)) as image:
                image.load()
    except ProtocolError:
        raise
    except (OSError, ValueError, SyntaxError, Image.DecompressionBombError, Image.DecompressionBombWarning) as exc:
        raise ProtocolError("IMAGE_DECODE_FAILED", "PNG cannot be decoded") from exc
    return {"width_px": width, "height_px": height}


def frame_layout(frame: dict[str, Any]) -> dict[str, float]:
    """Placement of the (possibly windowed) source image inside the frame."""
    size = frame["source_size"]
    window = frame.get("display_window")
    if window:
        if window["x"] + window["width"] > size["width_px"] or window["y"] + window["height"] > size["height_px"]:
            raise ProtocolError("IMAGE_DISPLAY_WINDOW_INVALID", "display window exceeds original image")
        size = {"width_px": window["width"], "height_px": window["height"]}
    return contain_layout(size, frame["frame"])


def callout_text(graphic: dict) -> tuple[list[str], float]:
    """Conservative CJK wrapping shared by layout validation and painting."""
    available = graphic["width_px"] - 2 * graphic["padding_px"]
    title_font, body_font = graphic["title_font_px"], graphic["body_font_px"]
    count = int(available // title_font)
    if count < 1 or any(len(line) * body_font > available for line in graphic["lines"]):
        raise ProtocolError("IMAGE_CALLOUT_TEXT_OVERFLOW", graphic["id"])
    title = graphic["title"]
    if graphic.get("title_wrap", True):
        wrapped = [title[i:i + count] for i in range(0, len(title), count)]
    else:
        if len(title) * title_font > available + 1e-6:
            raise ProtocolError("IMAGE_CALLOUT_TEXT_OVERFLOW", graphic["id"])
        wrapped = [title]
    gap = graphic["line_gap_px"]
    # X04: line-height multipliers are explicit design parameters (recorded baseline
    # preset 1.25 / 1.3), carried on the graphic instance — not hidden literals. Both
    # renderers measure with the same declared values.
    title_line_height = graphic.get("title_line_height", 1.25)
    body_line_height = graphic.get("body_line_height", 1.3)
    height = 2 * graphic["padding_px"] + len(wrapped) * title_font * title_line_height
    if graphic["lines"]:
        height += len(graphic["lines"]) * body_font * body_line_height + 2 * gap
    return wrapped, height


def validate_image_geometry(frame: dict[str, Any], graphics: list[dict[str, Any]],
                            viewport: dict[str, Any]) -> None:
    """Check image references, fixed placement, and original-image pixel anchors."""
    layout = frame_layout(frame)
    box = frame["frame"]
    if box["x"] + box["width"] > viewport["width_px"] or box["y"] + box["height"] > viewport["height_px"]:
        raise ProtocolError("IMAGE_FRAME_OUTSIDE_VIEWPORT", frame["id"])
    width, height = frame["source_size"]["width_px"], frame["source_size"]["height_px"]
    for graphic in graphics:
        if graphic["frame_id"] != frame["id"]:
            raise ProtocolError("IMAGE_GRAPHIC_FRAME_UNKNOWN", graphic["id"])
        positions = graphic["points"] if graphic["type"] == "line" else [graphic["position"]]
        for position in positions:
            x, y = position["x"], position["y"]
            if not math.isfinite(x) or not math.isfinite(y) or not (0 <= x <= width and 0 <= y <= height):
                raise ProtocolError("IMAGE_PIXEL_OUTSIDE_SOURCE", graphic["id"])
        for value in graphic.values():
            if isinstance(value, (int, float)) and not math.isfinite(value):
                raise ProtocolError("IMAGE_GRAPHIC_INVALID", graphic["id"])
        if graphic["type"] == "callout":
            _, expected_height = callout_text(graphic)
            if abs(graphic["height_px"] - expected_height) > 1e-6:
                raise ProtocolError("IMAGE_CALLOUT_SIZE_INVALID", graphic["id"])
            window = frame.get("display_window", {"x": 0, "y": 0})
            px = (graphic["position"]["x"] - window["x"]) * layout["scale"]
            py = (graphic["position"]["y"] - window["y"]) * layout["scale"]
            left, top = px + graphic["offset_x_px"], py + graphic["offset_y_px"]
            right, bottom = left + graphic["width_px"], top + graphic["height_px"]
            if left < 0 or top < 0 or right > layout["width"] or bottom > layout["height"]:
                raise ProtocolError("IMAGE_CALLOUT_OUTSIDE_MAP", graphic["id"])
            if left <= px <= right and top <= py <= bottom:
                raise ProtocolError("IMAGE_CALLOUT_COVERS_ANCHOR", graphic["id"])
