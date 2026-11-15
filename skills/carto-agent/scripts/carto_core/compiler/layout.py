from __future__ import annotations
from .grid_layout import instantiate_grid

import math
from copy import deepcopy
from typing import Any

from ..canonical import sha256_digest
from ..errors import ProtocolError
from ..schema_registry import SchemaRegistry
from ..roadmap import not_implemented

RESOLVER_VERSION = "2.0.0"
# These are conservative envelopes for the existing fixed-size SVG primitives,
# NOT measured glyph bounds. Real font/content measurement is a later stage.
FONT_SIZE_PX = 16
INSET_PX = 4
_FRAME_OVERLAYS = {
    "title": {"text"}, "legend": {"legend"}, "scale-bar": {"scale-bar"},
    "north-arrow": {"north-arrow"}, "marginalia": {"text", "attribution"},
    "chart": {"chart"},
}


def _pixels(mm: float, dpi: int) -> float:
    return round(mm * dpi / 25.4, 6)


def raster_size(value: float) -> int:
    """Nearest integral output pixel; DPR is deliberately fixed at one."""
    return max(1, math.floor(value + 0.5))


def overlay_bounds(item: dict[str, Any], x: float, y: float) -> tuple[float, float, float, float]:
    """Conservative fixed-primitive envelope in logical page pixels (not QA measurement)."""
    kind = item["type"]
    if kind == "legend":
        rows = item["legend_items"]
        width = max((len(row["label"]) for row in rows), default=0) * FONT_SIZE_PX
        return x, y - 4, x + 20 + width, y + max(16, (len(rows) - 1) * 22 + 16)
    if kind == "scale-bar":
        length = item["length_px"]
        label_width = len(item["distance_label"]) * FONT_SIZE_PX
        return (min(x - 1, x + (length - label_width) / 2), y - 27,
                max(x + length + 1, x + (length + label_width) / 2), y + 5)
    if kind == "north-arrow":
        return x - 10, y - 43, x + 10, y + 12
    width = max(FONT_SIZE_PX, len(item.get("content", "")) * FONT_SIZE_PX)
    return x, y - 20, x + width, y + 5


_SEMANTIC_POSITIONS = {
    "top-left":      lambda x, y, w, h, inset: (x + inset,           y + inset),
    "top-center":    lambda x, y, w, h, inset: (x + w / 2,           y + inset),
    "top-right":     lambda x, y, w, h, inset: (x + w - inset,       y + inset),
    "center-left":   lambda x, y, w, h, inset: (x + inset,           y + h / 2),
    "center":        lambda x, y, w, h, inset: (x + w / 2,           y + h / 2),
    "center-right":  lambda x, y, w, h, inset: (x + w - inset,       y + h / 2),
    "bottom-left":   lambda x, y, w, h, inset: (x + inset,           y + h - inset),
    "bottom-center": lambda x, y, w, h, inset: (x + w / 2,           y + h - inset),
    "bottom-right":  lambda x, y, w, h, inset: (x + w - inset,       y + h - inset),
}


# Type-specific default semantic specs as (anchor, dx_px, dy_px) from the anchor point.
# Persisted with the derived anchor so validation round-trips are idempotent.
_DEFAULT_OFFSET_PX = {
    "text": ("top-left", 0, 20), "attribution": ("top-left", 0, 20),
    "legend": ("top-left", 0, 4), "north-arrow": ("top-center", 0, 43),
    "scale-bar": ("top-left", 0, 27), "chart": ("top-left", 0, 0),
}


def _semantic_spec(position: Any, kind: str, dpi: int) -> tuple[str, float, float]:
    """Normalize an overlay position into (anchor, offset_mm_x, offset_mm_y).

    The semantic source travels with the derived anchor so validation round-trips
    re-derive the same pixel anchor. An absolute position without its semantic source
    is rejected rather than trusted: trust would make anchor tampering undetectable.
    """
    if position is None:
        anchor, dx_px, dy_px = _DEFAULT_OFFSET_PX[kind]
        return anchor, dx_px * 25.4 / dpi, dy_px * 25.4 / dpi
    if isinstance(position, str):
        return position, 0.0, 0.0
    if isinstance(position, dict):
        if "anchor" in position or "offset_mm" in position:
            offset = position.get("offset_mm", [0, 0])
            return position.get("anchor", "top-left"), float(offset[0]), float(offset[1])
        raise ProtocolError("LAYOUT_POSITION_UNSUPPORTED",
            "Absolute position without its semantic source cannot be re-validated")
    raise ProtocolError("LAYOUT_POSITION_UNSUPPORTED",
        f"Position must be a semantic string or dict, got {type(position).__name__}")


def _derive_anchor(spec: tuple[str, float, float], x: float, y: float, w: float, h: float,
                   inset: float, dpi: int) -> tuple[float, float]:
    """Mechanically derive the pixel anchor from a semantic spec.

    The position declaration is a pure semantic parameter — the program computes the
    exact pixel coordinates without injecting any design preference.
    """
    anchor, off_x_mm, off_y_mm = spec
    if anchor not in _SEMANTIC_POSITIONS:
        raise ProtocolError("LAYOUT_POSITION_UNSUPPORTED",
            f"Unknown anchor '{anchor}'; expected one of {sorted(_SEMANTIC_POSITIONS)}")
    base_x, base_y = _SEMANTIC_POSITIONS[anchor](x, y, w, h, inset)
    return base_x + _pixels(off_x_mm, dpi), base_y + _pixels(off_y_mm, dpi)


class LayoutResolver:
    """One layout-contract interpreter shared by compilation, rendering and checks.

    The supported subset is one map or a template-declared finite grid,
    disjoint page frames, millimetres, DPR=1,
    map clipping and reject-only overlays. No automatic shrink, pagination,
    overlap exceptions, real content measurement or layout search is implied.
    """

    def __init__(self, registry: SchemaRegistry | None = None) -> None:
        self.registry = registry or SchemaRegistry()

    def resolve(self, contract: dict[str, Any], dpi: int, device_pixel_ratio: int = 1, *, parameters=None) -> dict[str, Any]:
        template_contract = deepcopy(contract)
        contract = instantiate_grid(contract, parameters, self.registry)
        self.registry.validate("layout", contract)
        canvas = contract["canvas"]
        if canvas["unit"] != "mm":
            raise ProtocolError("LAYOUT_COORDINATE_UNSUPPORTED",
                f"Canvas unit '{canvas['unit']}' is not supported by the current page backend; only 'mm' is executable")
        if device_pixel_ratio is not None and device_pixel_ratio != 1:
            raise ProtocolError("LAYOUT_DPR_UNSUPPORTED",
                f"device_pixel_ratio={device_pixel_ratio} is not supported by the current page backend; DPR must be 1")
        if isinstance(dpi, bool) or not isinstance(dpi, int) or not 72 <= dpi <= 1200:
            raise ProtocolError("LAYOUT_DPI_INVALID", str(dpi))
        numeric = [canvas["width"], canvas["height"], canvas["safe_margin"]]
        numeric.extend(value for frame in contract["frames"] for value in frame["bounds"])
        if not all(math.isfinite(value) for value in numeric):
            raise ProtocolError("LAYOUT_NUMBER_INVALID", contract["layout_id"])
        width, height, margin = canvas["width"], canvas["height"], canvas["safe_margin"]
        if ((canvas["orientation"] == "landscape" and width < height)
                or (canvas["orientation"] == "portrait" and width > height)):
            raise ProtocolError("LAYOUT_ORIENTATION_MISMATCH", contract["layout_id"])
        page = {"width_mm": width, "height_mm": height, "dpi": dpi,
                "width_px": raster_size(_pixels(width, dpi)), "height_px": raster_size(_pixels(height, dpi)),
                "device_pixel_ratio": 1, "safe_margin_px": _pixels(margin, dpi)}
        frames: list[dict[str, Any]] = []
        ids: set[str] = set()
        contents: set[str] = set()
        maps: list[str] = []
        for frame in sorted(contract["frames"], key=lambda item: item["id"]):
            if frame["id"] in ids or frame["content_id"] in contents:
                raise ProtocolError("LAYOUT_BINDING_DUPLICATE", frame["id"])
            ids.add(frame["id"])
            contents.add(frame["content_id"])
            kind = frame["type"]
            if kind != "map" and kind not in _FRAME_OVERLAYS:
                not_implemented("layout-frame-types", "LAYOUT_FRAME_UNSUPPORTED",
                    f"Frame type {kind} is on the roadmap; current layout admits map and controlled overlays")
            expected_overflow = "clip" if kind == "map" else "reject"
            if frame["overflow_policy"] != expected_overflow:
                not_implemented("layout-overflow-strategies", "LAYOUT_OVERFLOW_UNSUPPORTED",
                    f"Overflow policy {frame['overflow_policy']} is on the roadmap; current layout admits clip for map and reject elsewhere")
            x, y, w, h = frame["bounds"]
            if min(w, h) <= 0 or x < margin or y < margin or x + w > width - margin or y + h > height - margin:
                raise ProtocolError("LAYOUT_FRAME_OUT_OF_BOUNDS", frame["id"])
            for other in frames:
                original = next(item for item in contract["frames"] if item["id"] == other["id"])
                ox, oy, ow, oh = original["bounds"]
                if x < ox + ow and ox < x + w and y < oy + oh and oy < y + h:
                    raise ProtocolError("LAYOUT_FRAME_OVERLAP", f"{other['id']}:{frame['id']}")
            frames.append({"id": frame["id"], "content_id": frame["content_id"], "type": kind,
                           "bounds_px": [_pixels(v, dpi) for v in frame["bounds"]],
                           "overflow_policy": frame["overflow_policy"]})
            if kind == "map":
                maps.append(frame["id"])
        if len(maps) != 1 and parameters is None:
            not_implemented("composition-map-counts", "LAYOUT_MAP_COUNT_UNSUPPORTED",
                f"Panel count {len(maps)} is on the roadmap; current layout admits one map or a template-declared grid")
        resolved = {
            "schema_version": 2, "resolver_version": RESOLVER_VERSION,
            "contract_ref": {"id": template_contract["layout_id"], "version": template_contract["version"], "digest": sha256_digest(template_contract)},
            "contract": deepcopy(contract), "template_contract": template_contract, "parameters": deepcopy(parameters),
            "page": page, "map_frame_ids": maps, "frames": frames,
        }
        self.registry.validate("resolved-layout", resolved)
        return resolved

    def validate(self, resolved: dict[str, Any]) -> None:
        self.registry.validate("resolved-layout", resolved)
        expected = self.resolve(resolved["template_contract"], resolved["page"]["dpi"], resolved["page"]["device_pixel_ratio"], parameters=resolved["parameters"])
        if resolved != expected:
            raise ProtocolError("LAYOUT_SNAPSHOT_MISMATCH", resolved["contract_ref"]["id"])

    @staticmethod
    def map_frame(resolved: dict[str, Any], frame_id=None) -> dict[str, Any]:
        if frame_id is None:
            if len(resolved["map_frame_ids"]) != 1:
                raise ProtocolError("LAYOUT_MAP_BINDING_REQUIRED", "Select a map frame explicitly")
            frame_id = next(iter(resolved["map_frame_ids"]))
        matches = [f for f in resolved["frames"] if f["id"] == frame_id and f["type"] == "map"]
        if len(matches) != 1:
            raise ProtocolError("LAYOUT_MAP_BINDING_MISMATCH", str(frame_id))
        return matches[0]

    def place_overlays(self, resolved: dict[str, Any], overlays: list[dict[str, Any]],
                       map_view_id: str = "main-view") -> list[dict[str, Any]]:
        if self.map_frame(resolved)["content_id"] != map_view_id:
            raise ProtocolError("LAYOUT_MAP_BINDING_MISMATCH", map_view_id)
        by_id = {item["id"]: item for item in overlays}
        expected = {frame["content_id"] for frame in resolved["frames"] if frame["type"] != "map"}
        if len(by_id) != len(overlays) or set(by_id) != expected:
            raise ProtocolError("LAYOUT_CONTENT_BINDING_MISMATCH", "Every overlay must bind exactly one frame, with no unused frame")
        result = []
        for frame in resolved["frames"]:
            if frame["type"] == "map":
                continue
            item = deepcopy(by_id[frame["content_id"]])
            if item["type"] not in _FRAME_OVERLAYS[frame["type"]]:
                raise ProtocolError("LAYOUT_CONTENT_TYPE_MISMATCH", item["id"])
            x, y, w, h = frame["bounds_px"]
            spec = _semantic_spec(item.get("position"), item["type"], resolved["page"]["dpi"])
            anchor_x, anchor_y = _derive_anchor(spec, x, y, w, h, INSET_PX, resolved["page"]["dpi"])
            if item["type"] == "scale-bar":
                item["length_px"] = round(w - 2 * INSET_PX, 6)
            # Discarding unresolved alternate coordinates would hide a bad contract.
            if any(key in item for key in ("screen_position", "anchor", "anchor_rule", "source_id", "feature_id")):
                raise ProtocolError("LAYOUT_CONTENT_COORDINATE_UNSUPPORTED", item["id"])
            item["coordinate_space"] = "page"
            # Persist the semantic source next to the derived anchor so re-validation
            # re-derives the same pixel anchor instead of resetting to the frame corner.
            item["position"] = {"x": round(anchor_x, 6), "y": round(anchor_y, 6), "unit": "pixel",
                                "anchor": spec[0], "offset_mm": [spec[1], spec[2]]}
            left, top, right, bottom = overlay_bounds(item, anchor_x, anchor_y)
            if left < x or top < y or right > x + w or bottom > y + h:
                raise ProtocolError("LAYOUT_CONTENT_OVERFLOW", f"{item['id']}: conservative envelope exceeds reject frame")
            result.append(item)
        return sorted(result, key=lambda item: item["id"])

    def apply(self, scene: dict[str, Any], contract: dict[str, Any]) -> dict[str, Any]:
        """Compile content-only overlays to absolute anchors; never mutate input."""
        result = deepcopy(scene)
        resolved = self.resolve(contract, scene["export"]["dpi"], scene["viewport"]["device_pixel_ratio"])
        result["resolved_layout"] = resolved
        for key in ("width_px", "height_px", "device_pixel_ratio"):
            result["viewport"][key] = resolved["page"][key]
        # Geographic fitting takes place in the independently sized map viewport.
        result["camera"]["padding"] = dict.fromkeys(("top", "right", "bottom", "left"), 0)
        result["overlays"] = self.place_overlays(resolved, scene["overlays"])
        self.validate_scene(result)
        return result

    def validate_scene(self, scene: dict[str, Any]) -> None:
        resolved = scene.get("resolved_layout")
        if resolved is None:
            raise ProtocolError("LAYOUT_SNAPSHOT_MISSING", scene.get("scene_id", "unknown"))
        self.validate(resolved)
        page = resolved["page"]
        if (any(scene["viewport"].get(key) != page[key] for key in ("width_px", "height_px", "device_pixel_ratio"))
                or scene["export"]["dpi"] != page["dpi"]):
            raise ProtocolError("LAYOUT_PAGE_MISMATCH", scene["scene_id"])
        if scene.get("renderer_id") in {"rasterio-matplotlib-page", "matplotlib-vector-page"}:
            if scene["viewport"]["device_pixel_ratio"] != 1:
                raise ProtocolError("RASTER_PIXEL_RATIO_UNSUPPORTED", "Static page uses physical pixels, DPR must be one")
            return
        if scene["camera"].get("padding") != dict.fromkeys(("top", "right", "bottom", "left"), 0):
            raise ProtocolError("LAYOUT_CAMERA_PADDING_UNSUPPORTED", scene["scene_id"])
        expected = self.place_overlays(resolved, scene["overlays"])
        if sorted(scene["overlays"], key=lambda item: item["id"]) != expected:
            raise ProtocolError("LAYOUT_ANCHOR_MISMATCH", scene["scene_id"])

    def validate_execution(self, scene: dict[str, Any], execution: dict[str, Any]) -> None:
        self.validate_scene(scene)
        if execution.get("resolved_layout") != scene["resolved_layout"]:
            raise ProtocolError("LAYOUT_EXECUTION_MISMATCH", scene["scene_id"])
        if execution.get("render_scene_ref", {}).get("digest") != sha256_digest(scene):
            raise ProtocolError("LAYOUT_SCENE_DIGEST_MISMATCH", scene["scene_id"])
        if scene.get("renderer_id") in {"rasterio-matplotlib-page", "matplotlib-vector-page"}:
            if (execution.get("environment", {}).get("renderer_id") != scene["renderer_id"]
                    or execution.get("page_inputs") != {k: scene[k] for k in ("prepared_bundle_ref", "page_request_ref")}):
                raise ProtocolError("RASTER_EXECUTION_INPUT_DRIFT", scene["scene_id"])
        elif execution.get("camera") != scene["camera"]:
            raise ProtocolError("LAYOUT_CAMERA_MISMATCH", scene["scene_id"])
        views = execution["views"]
        expected_views = {f["content_id"] for f in scene["resolved_layout"]["frames"] if f["type"] == "map"}
        if len(views) != len(expected_views) or {v["id"] for v in views} != expected_views:
            raise ProtocolError("LAYOUT_MAP_BINDING_MISMATCH", scene["scene_id"])
        self.validate_targets(scene["resolved_layout"], list(execution["targets"].values()))

    @staticmethod
    def validate_targets(resolved: dict[str, Any], targets: list[dict[str, Any]]) -> None:
        page = resolved["page"]
        if not targets or any(any(target.get(key) != page[key] for key in ("width_mm", "height_mm", "dpi")) for target in targets):
            raise ProtocolError("LAYOUT_TARGET_MISMATCH", "All outputs must use the resolved physical page and DPI")
        canvas = resolved["contract"]["canvas"]
        for target in targets:
            if (("safe_margin_mm" in target and target["safe_margin_mm"] != canvas["safe_margin"])
                    or ("orientation" in target and target["orientation"] != canvas["orientation"])):
                raise ProtocolError("LAYOUT_TARGET_MISMATCH", "Output safety margin/orientation differs from the layout")
