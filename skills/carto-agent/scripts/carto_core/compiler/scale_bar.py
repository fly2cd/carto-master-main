"""Mechanical scale-bar computation (plan phase 3, data-independent core).

The scale bar's ground distance is computed from the TARGET spatial configuration — the
map view's ground width in metres (which the caller derives from the declared CRS/extent)
and its pixel width — never fixed from a reference image and never a hardcoded '90 km'.
The program picks a nice round ground distance (1/2/5 x 10^n) whose bar fits the scale-bar
frame, then derives the exact pixel length and an m/km label. This is pure mechanical
derivation: no EPSG guessing, no geometry generation, no business vocabulary.

The renderers (static_page_renderer / page_renderer / svg_compositor) already consume a
scale_bar object {content_id, distance_m, distance_label, length_px}; this module supplies
the computed values a page compiler binds when a scale-bar frame is present.
"""
from __future__ import annotations

import math
from typing import Any

from ..errors import ProtocolError


def _nice_distance(max_m: float) -> float:
    """Largest 1/2/5 x 10^n mantissa distance not exceeding max_m."""
    exponent = math.floor(math.log10(max_m))
    base = 10.0 ** exponent
    for mantissa in (5.0, 2.0, 1.0):
        candidate = mantissa * base
        if candidate <= max_m:
            return candidate
    return base


def _format_label(distance_m: float) -> str:
    if distance_m >= 1000.0:
        return f"{distance_m / 1000.0:g} km"
    return f"{distance_m:g} m"


def compute_scale_bar(map_width_m: float, map_width_px: float, frame_width_px: float,
                      *, content_id: str = "scale", max_fraction: float = 1.0) -> dict[str, Any]:
    """Compute a fit-to-frame scale bar from explicit target spatial parameters.

    map_width_m: ground width of the map view in metres (caller derives from CRS/extent;
        this module does not guess a projection). map_width_px: map view pixel width.
    frame_width_px: available scale-bar frame pixel width. max_fraction caps the bar to a
        fraction of the frame (default 1.0). Returns {content_id, distance_m, distance_label,
        length_px}; length_px exactly represents distance_m at the map's ground-per-pixel
        scale and never exceeds the usable frame width.
    """
    for name, value in (("map_width_m", map_width_m), ("map_width_px", map_width_px),
                        ("frame_width_px", frame_width_px)):
        if not math.isfinite(value) or value <= 0:
            raise ProtocolError("SCALE_BAR_INPUT_INVALID", f"{name} must be finite and positive")
    if not math.isfinite(max_fraction) or not 0 < max_fraction <= 1:
        raise ProtocolError("SCALE_BAR_INPUT_INVALID", "max_fraction must be in (0, 1]")
    ground_per_px = map_width_m / map_width_px
    usable_px = frame_width_px * max_fraction
    max_distance_m = usable_px * ground_per_px
    distance_m = _nice_distance(max_distance_m)
    length_px = distance_m / ground_per_px
    if length_px > usable_px + 1e-6:
        raise ProtocolError("SCALE_BAR_FIT_INVALID", "computed bar exceeds the usable frame width")
    return {
        "content_id": content_id,
        "distance_m": distance_m,
        "distance_label": _format_label(distance_m),
        "length_px": round(length_px, 6),
    }