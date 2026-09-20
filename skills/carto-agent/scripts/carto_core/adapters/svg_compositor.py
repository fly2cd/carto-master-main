from __future__ import annotations

import base64
import html
import math
import re
from pathlib import Path
from typing import Any

from ..errors import ProtocolError, SecurityError
from ..security.paths import PathGuard

_COLOR = re.compile(r"^#[0-9A-Fa-f]{6}$")
_FONT_FAMILY = re.compile(r"^[\w .-]{1,128}$", re.UNICODE)


class SvgCompositor:
    """Compose a guarded raster map frame with supported SVG overlay elements."""

    def __init__(
        self,
        width_px: int,
        height_px: int,
        path_guard: PathGuard,
        background: str = "#FFFFFF",
    ) -> None:
        if width_px <= 0 or height_px <= 0:
            raise ProtocolError("COMPOSITE_VIEWPORT_INVALID", f"{width_px}x{height_px}")
        if not _COLOR.fullmatch(background):
            raise ProtocolError("COMPOSITE_COLOR_INVALID", background)
        self.width_px = width_px
        self.height_px = height_px
        self.path_guard = path_guard
        self.background = background

    @staticmethod
    def _encode_image(path: Path) -> str:
        data = path.read_bytes()
        if data.startswith(b"\x89PNG\r\n\x1a\n"):
            mime = "image/png"
        elif data.startswith(b"\xff\xd8\xff"):
            mime = "image/jpeg"
        else:
            raise ProtocolError("COMPOSITE_IMAGE_FORMAT_UNSUPPORTED", str(path))
        encoded = base64.b64encode(data).decode("ascii")
        return f"data:{mime};base64,{encoded}"

    def compose(
        self,
        map_screenshot_path: Path,
        overlays: list[dict[str, Any]],
        output_path: Path,
        *,
        inline_fonts: list[tuple[str, bytes]] | None = None,
    ) -> Path:
        screenshot = self.path_guard.resolve(map_screenshot_path, must_exist=True)
        output = self.path_guard.resolve(output_path)
        if output.suffix.lower() != ".svg":
            raise ProtocolError("COMPOSITE_OUTPUT_FORMAT_INVALID", str(output))
        if output.exists():
            raise SecurityError("COMPOSITE_OUTPUT_EXISTS", str(output))
        if not output.parent.is_dir():
            raise SecurityError("COMPOSITE_OUTPUT_PARENT_MISSING", str(output.parent))

        font_styles = [self._inline_font(family, data) for family, data in (inline_fonts or [])]
        parts: list[str] = [
            '<?xml version="1.0" encoding="UTF-8"?>',
            f'<svg xmlns="http://www.w3.org/2000/svg" width="{self.width_px}" height="{self.height_px}" viewBox="0 0 {self.width_px} {self.height_px}">',
            *font_styles,
            f'<rect width="100%" height="100%" fill="{self.background}"/>',
            f'<image href="{self._encode_image(screenshot)}" width="{self.width_px}" height="{self.height_px}"/>',
        ]
        for overlay in overlays:
            parts.append(self._render_overlay(overlay))
        parts.append("</svg>")
        try:
            with output.open("x", encoding="utf-8", newline="\n") as stream:
                stream.write("\n".join(parts))
        except FileExistsError as exc:
            raise SecurityError("COMPOSITE_OUTPUT_EXISTS", str(output)) from exc
        return output

    @staticmethod
    def _number(value: Any, field: str) -> float:
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
            raise ProtocolError("COMPOSITE_NUMBER_INVALID", field)
        return float(value)

    @staticmethod
    def _color(value: Any, field: str) -> str:
        if not isinstance(value, str) or not _COLOR.fullmatch(value):
            raise ProtocolError("COMPOSITE_COLOR_INVALID", field)
        return value

    def _position(self, overlay: dict[str, Any]) -> tuple[float, float]:
        coordinate_space = overlay.get("coordinate_space")
        if coordinate_space in {"page", "viewport"}:
            position = overlay.get("position")
        elif coordinate_space in {"geographic", "feature"}:
            position = overlay.get("screen_position")
            if position is None:
                raise ProtocolError("OVERLAY_COORDINATE_UNRESOLVED", str(overlay.get("id", "")))
        else:
            raise ProtocolError("OVERLAY_COORDINATE_SPACE_INVALID", str(coordinate_space))
        if not isinstance(position, dict):
            raise ProtocolError("OVERLAY_POSITION_MISSING", str(overlay.get("id", "")))
        x = self._number(position.get("x"), "position.x")
        y = self._number(position.get("y"), "position.y")
        unit = position.get("unit")
        if unit == "normalized":
            x *= self.width_px
            y *= self.height_px
        elif unit != "pixel":
            raise ProtocolError("OVERLAY_POSITION_UNIT_INVALID", str(unit))
        return x, y

    def _render_overlay(self, overlay: dict[str, Any]) -> str:
        overlay_type = overlay.get("type")
        overlay_id = html.escape(str(overlay.get("id", "")), quote=True)
        x, y = self._position(overlay)
        if overlay_type in {"text", "attribution"}:
            content = html.escape(str(overlay.get("content", "")))
            role = html.escape(str(overlay.get("style_role", overlay_type)), quote=True)
            return f'<text id="{overlay_id}" data-style-role="{role}" x="{x:g}" y="{y:g}">{content}</text>'
        if overlay_type == "symbol":
            label = html.escape(str(overlay.get("label", "")))
            symbol_ref = html.escape(str(overlay.get("symbol_ref", "")), quote=True)
            return f'<g id="{overlay_id}" data-symbol-ref="{symbol_ref}" transform="translate({x:g},{y:g})"><circle r="5" fill="#D32F2F"/><text x="8" y="4">{label}</text></g>'
        if overlay_type == "complex-symbol":
            label = html.escape(str(overlay.get("label", "")))
            symbol_ref = html.escape(str(overlay.get("symbol_ref", "")), quote=True)
            return f'<g id="{overlay_id}" data-symbol-ref="{symbol_ref}" transform="translate({x:g},{y:g})"><path d="M0,-7 L7,0 L0,7 L-7,0 Z" fill="#D32F2F"/><text x="10" y="4">{label}</text></g>'
        if overlay_type == "north-arrow":
            return f'<g id="{overlay_id}" transform="translate({x:g},{y:g})"><path d="M0,-18 L7,10 L0,6 L-7,10 Z" fill="#111827"/><text x="0" y="-23" text-anchor="middle">N</text></g>'
        if overlay_type == "scale-bar":
            length = self._number(overlay.get("length_px"), "length_px")
            label = html.escape(str(overlay.get("distance_label", "")))
            return f'<g id="{overlay_id}" transform="translate({x:g},{y:g})"><path d="M0,0 H{length:g} M0,-4 V4 M{length:g},-4 V4" stroke="#111827" fill="none"/><text x="{length / 2:g}" y="-7" text-anchor="middle">{label}</text></g>'
        if overlay_type == "legend":
            rows: list[str] = []
            for index, item in enumerate(overlay.get("legend_items", [])):
                color = self._color(item.get("color"), "legend.color")
                label = html.escape(str(item.get("label", "")))
                offset = index * 22
                rows.append(f'<rect x="0" y="{offset}" width="14" height="14" fill="{color}"/><text x="20" y="{offset + 12}">{label}</text>')
            return f'<g id="{overlay_id}" transform="translate({x:g},{y:g})">{"".join(rows)}</g>'
        raise ProtocolError("OVERLAY_TYPE_UNSUPPORTED", str(overlay_type))

    @staticmethod
    def _inline_font(family: str, data: bytes) -> str:
        if not _FONT_FAMILY.fullmatch(family):
            raise ProtocolError("COMPOSITE_FONT_FAMILY_INVALID", family)
        if data.startswith(b"wOF2"):
            mime, font_format = "font/woff2", "woff2"
        elif data.startswith(b"\x00\x01\x00\x00") or data.startswith(b"true"):
            mime, font_format = "font/ttf", "truetype"
        elif data.startswith(b"OTTO"):
            mime, font_format = "font/otf", "opentype"
        else:
            raise ProtocolError("COMPOSITE_FONT_FORMAT_UNSUPPORTED", family)
        encoded = base64.b64encode(data).decode("ascii")
        safe_family = html.escape(family, quote=True)
        return (
            f'<style>@font-face{{font-family:"{safe_family}";src:url("data:{mime};base64,{encoded}") '
            f'format("{font_format}");font-weight:100 900}}svg,text{{font-family:"{safe_family}"}}</style>'
        )
