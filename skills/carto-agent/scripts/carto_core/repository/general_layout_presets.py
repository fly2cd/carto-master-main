"""General-purpose single-main-map layout presets (reusable map-layout segments).

A3 / A4 x landscape / portrait, each a single main map plus standard cartographic
furniture: title bar, legend, source note, scale bar, north arrow. These are pure
page-composition contracts (map-layout), scenario-agnostic and reusable across
business scenarios via segment_refs / replaceable layout. They carry no business
vocabulary and no data semantics — only canvas, frames, capacity (field-mapping
Layout authority).

Paper sizes (mm): A4 = 297x210, A3 = 420x297. Orientation swaps width/height.
All frames stay inside the safe margin; the main map is the single map frame.
"""
from __future__ import annotations

from typing import Any

PAPER_MM = {"A4": (297.0, 210.0), "A3": (420.0, 297.0)}


def _frames(w: float, h: float, landscape: bool) -> list[dict[str, Any]]:
    """Single main map + title bar + legend + scale bar + north arrow + source."""
    m = 10.0  # safe margin
    title_h = 12.0
    source_h = 8.0
    top = m + title_h + 4.0
    bottom = h - m - source_h - 4.0
    body_h = bottom - top
    if landscape:
        side_w = 62.0
        map_w = w - 2 * m - side_w - 6.0
        map_box = [m, top, map_w, body_h]
        side_x = m + map_w + 6.0
        legend = [side_x, top, side_w, body_h * 0.55]
        scale = [side_x, top + body_h * 0.60, side_w, 12.0]
        north = [side_x, top + body_h * 0.60 + 16.0, 20.0, 20.0]
    else:
        # portrait: legend/scale/north in a bottom band above the source note
        band_h = 40.0
        map_h = body_h - band_h - 4.0
        map_box = [m, top, w - 2 * m, map_h]
        band_y = top + map_h + 4.0
        legend = [m, band_y, (w - 2 * m) * 0.5, band_h]
        scale = [m + (w - 2 * m) * 0.55, band_y, (w - 2 * m) * 0.45, 12.0]
        north = [m + (w - 2 * m) * 0.55, band_y + 16.0, 20.0, 20.0]
    return [
        {"id": "main-map", "content_id": "main-view", "type": "map",
         "coordinate_space": "page", "bounds": map_box, "overflow_policy": "clip"},
        {"id": "map-title", "content_id": "title", "type": "title",
         "coordinate_space": "page", "bounds": [m, m, w - 2 * m, title_h],
         "overflow_policy": "reject"},
        {"id": "legend", "content_id": "legend", "type": "legend",
         "coordinate_space": "page", "bounds": legend, "overflow_policy": "reject"},
        {"id": "scale-bar", "content_id": "scale-bar", "type": "scale-bar",
         "coordinate_space": "page", "bounds": scale, "overflow_policy": "reject"},
        {"id": "north-arrow", "content_id": "north-arrow", "type": "north-arrow",
         "coordinate_space": "page", "bounds": north, "overflow_policy": "reject"},
        {"id": "source", "content_id": "source", "type": "marginalia",
         "coordinate_space": "page", "bounds": [m, h - m - source_h, w - 2 * m, source_h],
         "overflow_policy": "reject"},
    ]


def general_single_map_layout(paper: str = "A4", orientation: str = "landscape",
                              *, version: str = "1.0.0") -> dict[str, Any]:
    """Build one general single-main-map layout contract (A3/A4 x landscape/portrait)."""
    if paper not in PAPER_MM:
        raise ValueError(f"unsupported paper {paper}")
    if orientation not in {"landscape", "portrait"}:
        raise ValueError(f"unsupported orientation {orientation}")
    long_side, short_side = PAPER_MM[paper]
    landscape = orientation == "landscape"
    w, h = (long_side, short_side) if landscape else (short_side, long_side)
    return {
        "schema_version": 1,
        "layout_id": f"general-single-map-{paper.lower()}-{orientation}",
        "version": version,
        "category": "report",
        "canvas": {"width": w, "height": h, "unit": "mm",
                   "orientation": orientation, "safe_margin": 10},
        "content_padding_mm": 2,
        "frames": _frames(w, h, landscape),
        "placeholders": ["{{MAP_TITLE}}", "{{MAP_FRAME}}", "{{LEGEND}}"],
        "capacity": {"legend_items": 12, "title_characters": 60},
        "rules": [],
    }


def all_general_layouts() -> dict[str, dict[str, Any]]:
    """The four general presets keyed by layout_id."""
    return {
        f"general-single-map-{p.lower()}-{o}": general_single_map_layout(p, o)
        for p in ("A4", "A3") for o in ("landscape", "portrait")
    }