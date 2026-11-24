"""Inset locator-map declaration validation (plan phase 3, mechanical core).

An inset is a REAL secondary map view — an independent geographic extent associated with
the main map — never a pasted screenshot of a country/region. This module mechanically
validates an inset declaration against its container map frame: declared containment, full
geometric enclosure, an independent view extent, and a main-map association (with an
optional highlight object id). It rejects an image-only inset that would substitute a
picture for a map view.

Pure and data-independent: no EPSG guessing (the extent is supplied by the caller from the
declared CRS), no geometry derivation, no business vocabulary. The layout resolver consumes
these checks when admitting an inset frame; rendering a secondary view is a separate step.
"""
from __future__ import annotations

import math
from typing import Any

from ..errors import ProtocolError


def validate_inset_declaration(inset: dict[str, Any], container: dict[str, Any]) -> dict[str, Any]:
    """Validate an inset frame declaration; return resolved inset metadata or fail closed.

    inset: {id, type:"inset", bounds:[x,y,w,h], inside_frame, view:{extent:[minx,miny,maxx,maxy]},
            main_map_ref, highlight_id?}. container: {id, type:"map", bounds:[x,y,w,h]}.
    """
    if inset.get("type") != "inset":
        raise ProtocolError("INSET_TYPE_INVALID", str(inset.get("type")))
    if container.get("type") != "map":
        raise ProtocolError("INSET_CONTAINER_TYPE", "an inset must be contained in a map frame")
    if inset.get("id") == container.get("id") or inset.get("inside_frame") != container.get("id"):
        raise ProtocolError("INSET_CONTAINMENT_REFERENCE",
                            "inset must declare inside_frame naming a different map frame")
    cx, cy, cw, ch = inset["bounds"]
    mx, my, mw, mh = container["bounds"]
    if min(cw, ch) <= 0:
        raise ProtocolError("INSET_BOUNDS_INVALID", inset["id"])
    if not (cx >= mx - 1e-9 and cy >= my - 1e-9
            and cx + cw <= mx + mw + 1e-9 and cy + ch <= my + mh + 1e-9):
        raise ProtocolError("INSET_NOT_ENCLOSED",
                            f"{inset['id']}: inset requires full enclosure by {container['id']}")
    view = inset.get("view")
    if not isinstance(view, dict) or "extent" not in view:
        raise ProtocolError("INSET_VIEW_REQUIRED",
                            "an inset requires an independent map view extent, not a pasted image")
    extent = view["extent"]
    if (not isinstance(extent, (list, tuple)) or len(extent) != 4
            or not all(math.isfinite(v) for v in extent)
            or extent[0] >= extent[2] or extent[1] >= extent[3]):
        raise ProtocolError("INSET_EXTENT_INVALID", "extent must be [minx,miny,maxx,maxy] with min<max")
    if not inset.get("main_map_ref"):
        raise ProtocolError("INSET_MAIN_MAP_REQUIRED", "an inset must associate with the main map view")
    return {
        "id": inset["id"],
        "container_id": container["id"],
        "bounds": list(inset["bounds"]),
        "view_extent": list(extent),
        "main_map_ref": inset["main_map_ref"],
        "highlight_id": inset.get("highlight_id"),
    }