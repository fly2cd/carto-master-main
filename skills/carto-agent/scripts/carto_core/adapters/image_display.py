"""Display-only bounds detection: transparent/white border trimming.

Migrated from the old framework's adapters/image_display.py (v1). Original raster
bytes and registration coordinates stay fixed; only the visible content window
is detected so the map frame can crop decorative margins.

Layering: production callers invoke this through the ToolGateway
``image-display-bounds`` capability (adapters/image_tools.py) — the window is
capability-shaped evidence (digest-bound input, ToolResult receipt). The
function itself is deterministic measurement, not an authorization decision.
"""
from __future__ import annotations

import io

from PIL import Image, ImageChops

from ..errors import ProtocolError

# The visible-content threshold: pixels darker than this in every channel count
# as map content. 245 trims near-white paper margins while keeping light basemaps.
DEFAULT_WHITE_THRESHOLD = 245


def visible_window(data: bytes, threshold: int) -> dict[str, int]:
    """Return the visible content window of a PNG (x, y, width, height)."""
    with Image.open(io.BytesIO(data)) as image:
        rgba = image.convert("RGBA")
        white = Image.new("RGBA", image.size, "white")
        rgb = Image.alpha_composite(white, rgba).convert("RGB")
        red, green, blue = rgb.split()
        minimum = ImageChops.darker(ImageChops.darker(red, green), blue)
        mask = minimum.point(lambda value: 255 if value < threshold else 0)
        bounds = mask.getbbox()
    if bounds is None:
        raise ProtocolError("IMAGE_CONTENT_EMPTY", "image has no visible map content")
    left, top, right, bottom = bounds
    return {"x": left, "y": top, "width": right - left, "height": bottom - top}


def display_bounds(data: bytes, *, white_threshold: int = DEFAULT_WHITE_THRESHOLD) -> dict[str, int]:
    """Deterministic display window for a registered basemap image."""
    if not 0 <= white_threshold <= 255:
        raise ProtocolError("IMAGE_DISPLAY_THRESHOLD_INVALID", "white threshold must stay within byte range")
    return visible_window(data, white_threshold)
